#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RMUC 2026 规则测评题库管理系统
Web版本 - 支持团队协作
"""

import os
import re
import json
import sqlite3
import hashlib
from datetime import datetime
from flask import Flask, request, render_template, jsonify, g
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)
DATABASE = 'rmuc2026_questions.db'


# ==================== 数据库操作 ====================

def get_db():
    """获取数据库连接"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    """关闭数据库连接"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库"""
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                question_hash TEXT NOT NULL UNIQUE,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_option TEXT,
                count_a INTEGER DEFAULT 0,
                count_b INTEGER DEFAULT 0,
                count_c INTEGER DEFAULT 0,
                count_d INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS upload_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                score REAL,
                questions_added INTEGER DEFAULT 0,
                questions_updated INTEGER DEFAULT 0,
                uploader_info TEXT
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS upload_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_log_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                updated_option TEXT,
                FOREIGN KEY (upload_log_id) REFERENCES upload_logs(id),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        ''')

        # 轻量迁移：老数据库可能缺字段
        columns = [row['name'] for row in db.execute('PRAGMA table_info(questions)').fetchall()]
        if 'correct_option' not in columns:
            db.execute('ALTER TABLE questions ADD COLUMN correct_option TEXT')

        upload_log_columns = [row['name'] for row in db.execute('PRAGMA table_info(upload_logs)').fetchall()]
        if 'score' not in upload_log_columns:
            db.execute('ALTER TABLE upload_logs ADD COLUMN score REAL')
        db.commit()


def normalize_question(question_text):
    """标准化题目文本用于比较"""
    text = re.sub(r'\s+', ' ', question_text)
    text = re.sub(r'^\d+[.、]\s*', '', text)
    return text.strip()


def create_question_hash(question_text, options_set):
    """创建题目的唯一标识（基于题目文本和选项集合）
    
    使用 SHA256 确保跨进程/跨重启一致性（Python内置hash()会随机化）
    选项排序后再拼接，确保选项顺序打乱的同一道题生成相同的hash
    """
    norm_q = normalize_question(question_text)
    sorted_options = sorted(options_set)  # 排序确保顺序无关
    combined = norm_q + '|' + '|'.join(sorted_options)
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def get_text_with_breaks(element):
    """获取元素文本，将<div>和<br>转换为换行"""
    text_parts = []
    for child in element.children:
        if child.name == 'div':
            text_parts.append('\n' + get_text_with_breaks(child))
        elif child.name == 'br':
            text_parts.append('\n')
        elif child.string:
            text_parts.append(child.string)
        elif hasattr(child, 'get_text'):
            text_parts.append(child.get_text())
    return ''.join(text_parts).strip()


def extract_questions_from_html(html_content):
    """从HTML内容中提取题目信息"""
    soup = BeautifulSoup(html_content, 'html.parser')
    questions = []
    
    # 使用CSS选择器正确匹配同时拥有多个class的元素
    question_divs = soup.select('div.field.ui-field-contain[type="3"]')
    
    for q_div in question_divs:
        try:
            topic_html_div = q_div.find('div', class_='topichtml')
            if topic_html_div:
                question_text = get_text_with_breaks(topic_html_div)
            else:
                continue
            
            options = []
            selected_option = None
            option_divs = q_div.find_all('div', class_='ui-radio')
            
            for opt_div in option_divs:
                label_div = opt_div.find('div', class_='label')
                if label_div:
                    dit_value = label_div.get('dit', '')
                    if dit_value:
                        option_text = unquote(dit_value)
                    else:
                        option_text = label_div.get_text(strip=True)
                    
                    options.append(option_text)
                    
                    if 'checked' in opt_div.get('class', []):
                        selected_option = option_text
            
            # 只处理有4个选项的题目
            if question_text and len(options) == 4:
                questions.append({
                    'question': question_text.strip(),
                    'options': options,
                    'selected_option': selected_option,
                    'options_set': set(options)
                })
                
        except Exception as e:
            print(f"解析题目时出错: {e}")
            continue
    
    return questions


def process_questions(questions, score=None):
    """处理提取的题目，存入数据库"""
    db = get_db()
    added = 0
    updated = 0
    details = []  # 记录修改详情: [(question_id, action_type, updated_option), ...]
    
    for q in questions:
        question_hash = create_question_hash(q['question'], q['options_set'])
        
        # 查询是否已存在
        existing = db.execute(
            'SELECT * FROM questions WHERE question_hash = ?',
            (question_hash,)
        ).fetchone()
        
        if existing:
            # 题目已存在，更新选中选项的计数
            if q['selected_option']:
                # 找到选中的选项对应的列
                options_in_db = [existing['option_a'], existing['option_b'], 
                                existing['option_c'], existing['option_d']]
                
                if q['selected_option'] in options_in_db:
                    idx = options_in_db.index(q['selected_option'])
                    option_letter = ['a', 'b', 'c', 'd'][idx]
                    count_col = 'count_' + option_letter
                    db.execute(f'''
                        UPDATE questions 
                        SET {count_col} = {count_col} + 1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (existing['id'],))
                    details.append((existing['id'], 'updated', option_letter))
                    updated += 1
        else:
            # 新题目，插入数据库
            options = q['options']
            counts = [0, 0, 0, 0]
            selected_option_letter = None
            
            # 如果有选中的选项，设置对应的计数为1
            if q['selected_option'] and q['selected_option'] in options:
                idx = options.index(q['selected_option'])
                counts[idx] = 1
                selected_option_letter = ['a', 'b', 'c', 'd'][idx]
            
            cursor = db.execute('''
                INSERT INTO questions 
                (question, question_hash, option_a, option_b, option_c, option_d,
                 count_a, count_b, count_c, count_d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (q['question'], question_hash, 
                  options[0], options[1], options[2], options[3],
                  counts[0], counts[1], counts[2], counts[3]))
            new_question_id = cursor.lastrowid
            details.append((new_question_id, 'added', selected_option_letter))
            added += 1
    
    # 记录上传日志
    cursor = db.execute('''
        INSERT INTO upload_logs (score, questions_added, questions_updated)
        VALUES (?, ?, ?)
    ''', (score, added, updated))
    upload_log_id = cursor.lastrowid
    
    # 记录详细修改信息
    for question_id, action_type, updated_option in details:
        db.execute('''
            INSERT INTO upload_details (upload_log_id, question_id, action_type, updated_option)
            VALUES (?, ?, ?, ?)
        ''', (upload_log_id, question_id, action_type, updated_option))
    
    db.commit()
    return added, updated


# ==================== API路由 ====================

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/stats')
def get_stats():
    """获取统计信息"""
    db = get_db()
    
    # 题目总数
    total_questions = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    
    # 答题总次数
    total_answers = db.execute(
        'SELECT SUM(count_a + count_b + count_c + count_d) FROM questions'
    ).fetchone()[0] or 0
    
    # 上传次数
    total_uploads = db.execute('SELECT COUNT(*) FROM upload_logs').fetchone()[0]
    
    return jsonify({
        'total_questions': total_questions,
        'total_answers': int(total_answers),
        'total_uploads': total_uploads
    })


@app.route('/api/upload', methods=['POST'])
def upload_html():
    """上传HTML并解析"""
    try:
        data = request.get_json()
        html_content = data.get('html', '')
        score_raw = data.get('score', None)
        score = None
        if score_raw is not None and str(score_raw).strip() != '':
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': '分数格式不正确'}), 400
        
        if not html_content:
            return jsonify({'success': False, 'error': '未提供HTML内容'})
        
        # 解析HTML
        questions = extract_questions_from_html(html_content)
        
        if not questions:
            return jsonify({'success': False, 'error': '未能从HTML中提取到任何题目（需要4个选项的单选题）'})
        
        # 处理并存储
        added, updated = process_questions(questions, score=score)

        # 解析成功后保存原始HTML到 uploads 目录，便于审计和调试
        upload_dir = os.path.join(app.root_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f'upload_{timestamp}.html'
        file_path = os.path.join(upload_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return jsonify({
            'success': True,
            'extracted': len(questions),
            'added': added,
            'updated': updated
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/questions')
def get_questions():
    """获取题目列表"""
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 10, type=int)
    search = request.args.get('search', '').strip()
    
    db = get_db()
    
    # 构建查询
    if search:
        count_query = 'SELECT COUNT(*) FROM questions WHERE question LIKE ?'
        data_query = '''
            SELECT * FROM questions 
            WHERE question LIKE ? 
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        '''
        search_param = f'%{search}%'
        total = db.execute(count_query, (search_param,)).fetchone()[0]
        questions = db.execute(data_query, (search_param, size, (page - 1) * size)).fetchall()
    else:
        total = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        questions = db.execute(
            'SELECT * FROM questions ORDER BY id DESC LIMIT ? OFFSET ?',
            (size, (page - 1) * size)
        ).fetchall()
    
    pages = (total + size - 1) // size
    
    question_dicts = [dict(q) for q in questions]

    # 计算每题每选项的最高分（来自上传时填写的 score）
    question_ids = [q['id'] for q in question_dicts]
    max_score_map = {}
    if question_ids:
        placeholders = ','.join(['?'] * len(question_ids))
        rows = db.execute(
            f'''
            SELECT ud.question_id AS question_id,
                   ud.updated_option AS opt,
                   MAX(ul.score) AS max_score
            FROM upload_details ud
            JOIN upload_logs ul ON ul.id = ud.upload_log_id
            WHERE ud.question_id IN ({placeholders})
              AND ud.updated_option IN ('a','b','c','d')
              AND ul.score IS NOT NULL
            GROUP BY ud.question_id, ud.updated_option
            ''',
            tuple(question_ids),
        ).fetchall()
        for r in rows:
            max_score_map[(r['question_id'], r['opt'])] = r['max_score']

    for q in question_dicts:
        qid = q['id']
        q['max_score_a'] = max_score_map.get((qid, 'a'))
        q['max_score_b'] = max_score_map.get((qid, 'b'))
        q['max_score_c'] = max_score_map.get((qid, 'c'))
        q['max_score_d'] = max_score_map.get((qid, 'd'))

    return jsonify({
        'questions': question_dicts,
        'total': total,
        'page': page,
        'pages': pages
    })


@app.route('/api/history')
def get_history():
    """获取上传历史"""
    db = get_db()
    logs = db.execute(
        'SELECT * FROM upload_logs ORDER BY uploaded_at DESC LIMIT 50'
    ).fetchall()
    
    return jsonify([dict(log) for log in logs])


@app.route('/api/history/<int:log_id>/score', methods=['PUT'])
def update_upload_score(log_id):
    """更新上传记录的得分"""
    try:
        db = get_db()
        
        # 检查记录是否存在
        log = db.execute('SELECT * FROM upload_logs WHERE id = ?', (log_id,)).fetchone()
        if not log:
            return jsonify({'success': False, 'error': '记录不存在'})
        
        data = request.get_json()
        score_raw = data.get('score', None)
        
        # 处理得分：可以是数字、空字符串（清除得分）
        if score_raw is None or str(score_raw).strip() == '':
            score = None
        else:
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': '分数格式不正确'}), 400
        
        db.execute('UPDATE upload_logs SET score = ? WHERE id = ?', (score, log_id))
        db.commit()
        
        return jsonify({'success': True, 'score': score})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/history/<int:log_id>', methods=['DELETE'])
def delete_upload_log(log_id):
    """删除上传记录并回退修改"""
    try:
        db = get_db()
        
        # 检查记录是否存在
        log = db.execute('SELECT * FROM upload_logs WHERE id = ?', (log_id,)).fetchone()
        if not log:
            return jsonify({'success': False, 'error': '记录不存在'})
        
        # 获取该次上传的所有修改详情
        details = db.execute(
            'SELECT * FROM upload_details WHERE upload_log_id = ?', (log_id,)
        ).fetchall()
        
        reverted_added = 0
        reverted_updated = 0
        
        for detail in details:
            question_id = detail['question_id']
            action_type = detail['action_type']
            updated_option = detail['updated_option']
            
            if action_type == 'added':
                # 删除新增的题目
                db.execute('DELETE FROM questions WHERE id = ?', (question_id,))
                reverted_added += 1
            elif action_type == 'updated' and updated_option:
                # 回退计数更新（减1）
                count_col = 'count_' + updated_option
                db.execute(f'''
                    UPDATE questions 
                    SET {count_col} = MAX(0, {count_col} - 1)
                    WHERE id = ?
                ''', (question_id,))
                reverted_updated += 1
        
        # 删除修改详情记录
        db.execute('DELETE FROM upload_details WHERE upload_log_id = ?', (log_id,))
        
        # 删除上传日志
        db.execute('DELETE FROM upload_logs WHERE id = ?', (log_id,))
        
        db.commit()
        
        return jsonify({
            'success': True,
            'reverted_added': reverted_added,
            'reverted_updated': reverted_updated
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    """删除题目"""
    try:
        db = get_db()
        
        # 检查题目是否存在
        question = db.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
        if not question:
            return jsonify({'success': False, 'error': '题目不存在'})
        
        # 删除题目
        db.execute('DELETE FROM questions WHERE id = ?', (question_id,))
        db.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/questions/<int:question_id>/correct', methods=['POST'])
def set_correct_option(question_id):
    """标记该题已确认正确的选项（a/b/c/d）"""
    try:
        data = request.get_json(silent=True) or {}
        option = (data.get('option') or '').strip().lower()
        if option not in {'a', 'b', 'c', 'd'}:
            return jsonify({'success': False, 'error': 'option 必须是 a/b/c/d'}), 400

        db = get_db()
        question = db.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
        if not question:
            return jsonify({'success': False, 'error': '题目不存在'}), 404

        db.execute(
            'UPDATE questions SET correct_option = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (option, question_id),
        )
        db.commit()
        return jsonify({'success': True, 'correct_option': option})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/export')
def export_data():
    """导出题库为JSON"""
    db = get_db()
    questions = db.execute('SELECT * FROM questions ORDER BY id').fetchall()
    
    return jsonify({
        'exported_at': datetime.now().isoformat(),
        'total': len(questions),
        'questions': [dict(q) for q in questions]
    })


# ==================== 主程序 ====================

if __name__ == '__main__':
    # 初始化数据库
    init_db()
    
    print()
    print("=" * 60)
    print("   RMUC 2026 规则测评题库管理系统")
    print("=" * 60)
    print()
    print("   🌐 访问地址: http://127.0.0.1:5000")
    print("   📚 数据库文件: rmuc2026_questions.db")
    print()
    print("   按 Ctrl+C 停止服务器")
    print("=" * 60)
    print()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
