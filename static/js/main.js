// 全局变量
let currentPage = 1;
let currentSearch = '';
const pageSize = 10;

// 页面加载时获取统计信息
document.addEventListener('DOMContentLoaded', function () {
    loadStats();
});

// 切换标签页
function switchTab(tabName, e) {
    // 切换标签按钮状态
    document.querySelectorAll('.tab-btn').forEach(function (btn) {
        btn.classList.remove('active');
    });
    if (e && e.target) {
        e.target.classList.add('active');
    }

    // 切换内容显示
    document.querySelectorAll('.tab-content').forEach(function (tab) {
        tab.classList.remove('active');
    });
    document.getElementById(tabName + 'Tab').classList.add('active');

    // 加载对应数据
    if (tabName === 'questions') {
        loadQuestions();
    } else if (tabName === 'history') {
        loadHistory();
    }
}

// 加载统计数据
function loadStats() {
    fetch('/api/stats')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            document.getElementById('totalQuestions').textContent = data.total_questions;
            document.getElementById('totalAnswers').textContent = data.total_answers;
            document.getElementById('totalUploads').textContent = data.total_uploads;
        })
        .catch(function (err) {
            console.error('加载统计失败:', err);
        });
}

// 上传HTML
function uploadHtml() {
    var html = document.getElementById('htmlInput').value;
    var scoreEl = document.getElementById('scoreInput');
    var scoreValue = scoreEl ? String(scoreEl.value || '').trim() : '';
    var btn = document.getElementById('uploadBtn');
    var resultBox = document.getElementById('resultBox');

    if (!html.trim()) {
        showResult('error', '请先粘贴HTML内容');
        return;
    }

    btn.disabled = true;
    btn.textContent = '⏳ 处理中...';

    fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html: html, score: scoreValue })
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                showResult('success',
                    '✅ 处理成功！<br>' +
                    '📝 提取题目: ' + data.extracted + ' 道<br>' +
                    '➕ 新增题目: ' + data.added + ' 道<br>' +
                    '🔄 更新计数: ' + data.updated + ' 道');
                document.getElementById('htmlInput').value = '';
                if (scoreEl) scoreEl.value = '';
                loadStats();
            } else {
                showResult('error', '❌ 处理失败: ' + data.error);
            }
        })
        .catch(function (err) {
            showResult('error', '❌ 上传失败: ' + err.message);
        })
        .finally(function () {
            btn.disabled = false;
            btn.textContent = '🚀 解析并上传';
        });
}

// 显示结果
function showResult(type, message) {
    var resultBox = document.getElementById('resultBox');
    resultBox.className = 'result-box ' + type;
    resultBox.innerHTML = message;
    resultBox.style.display = 'block';
}

// 加载题目列表
function loadQuestions(page) {
    if (page === undefined) page = 1;
    currentPage = page;
    var container = document.getElementById('questionsList');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载中...</p></div>';

    var url = '/api/questions?page=' + page + '&size=' + pageSize;
    if (currentSearch) {
        url += '&search=' + encodeURIComponent(currentSearch);
    }

    fetch(url)
        .then(function (res) { return res.json(); })
        .then(function (data) {
            renderQuestions(data.questions);
            renderPagination(data.total, data.page, data.pages);
        })
        .catch(function (err) {
            container.innerHTML = '<p style="color:#ff3232;">加载失败: ' + err.message + '</p>';
        });
}

// 渲染题目列表
function renderQuestions(questions) {
    var container = document.getElementById('questionsList');

    if (questions.length === 0) {
        container.innerHTML = '<p style="text-align:center;color:#888;padding:50px;">暂无题目</p>';
        return;
    }

    var html = '';
    questions.forEach(function (q, idx) {
        var total = q.count_a + q.count_b + q.count_c + q.count_d;
        var correct = (q.correct_option || '').toLowerCase();

        var maxA = q.max_score_a;
        var maxB = q.max_score_b;
        var maxC = q.max_score_c;
        var maxD = q.max_score_d;

        html += '<div class="question-card">' +
            '<div class="question-header">' +
            '<span class="question-number"># ' + q.id + '</span>' +
            '<div class="question-header-right">' +
            '<span class="question-total">总答题: ' + total + ' 次</span>' +
            '<button class="question-delete-btn" onclick="deleteQuestion(' + q.id + ')">🗑️ 删除</button>' +
            '</div>' +
            '</div>' +
            '<div class="question-text">' + escapeHtml(q.question) + '</div>' +
            '<div class="options-grid">' +
            renderOption(q.id, 'A', 'a', q.option_a, q.count_a, total, correct === 'a', maxA) +
            renderOption(q.id, 'B', 'b', q.option_b, q.count_b, total, correct === 'b', maxB) +
            renderOption(q.id, 'C', 'c', q.option_c, q.count_c, total, correct === 'c', maxC) +
            renderOption(q.id, 'D', 'd', q.option_d, q.count_d, total, correct === 'd', maxD) +
            '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

// 渲染单个选项
function formatScore(score) {
    if (score === null || score === undefined || score === '') return '';
    var n = Number(score);
    if (!isFinite(n)) return '';
    return Number.isInteger(n) ? String(n) : String(n);
}

function renderOption(questionId, label, optionKey, text, count, total, isCorrect, maxScore) {
    var percent = total > 0 ? Math.round(count / total * 100) : 0;
    var maxText = '';
    var formatted = formatScore(maxScore);
    if (count > 0 && formatted) {
        maxText = ' | 最高分: ' + formatted;
    }
    return '<div class="option-item' + (isCorrect ? ' confirmed' : '') + '">' +
        '<div class="option-header">' +
        '<span class="option-label">' + label + '</span>' +
        '<div class="option-actions">' +
        '<span class="option-count">' + count + ' 人 (' + percent + '%)' + maxText + '</span>' +
        (isCorrect
            ? '<span class="option-confirmed">已确认正确</span>'
            : '<button class="option-confirm-btn" onclick="confirmCorrectOption(' + questionId + ',\'' + optionKey + '\')">✅确认</button>') +
        '</div>' +
        '</div>' +
        '<div class="option-text">' + escapeHtml(text) + '</div>' +
        '<div class="option-bar">' +
        '<div class="option-bar-fill" style="width:' + percent + '%"></div>' +
        '</div>' +
        '</div>';
}

// 标记某题某选项为“已确认正确”
function confirmCorrectOption(questionId, optionKey) {
    if (!confirm('确认将该题正确答案标记为 ' + optionKey.toUpperCase() + ' 吗？')) {
        return;
    }

    fetch('/api/questions/' + questionId + '/correct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option: optionKey })
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                loadQuestions(currentPage);
            } else {
                alert('标记失败: ' + data.error);
            }
        })
        .catch(function (err) {
            alert('标记失败: ' + err.message);
        });
}

// 渲染分页
function renderPagination(total, currentPage, totalPages) {
    var container = document.getElementById('pagination');

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    var html = '';

    // 上一页
    html += '<button class="page-btn" onclick="loadQuestions(' + (currentPage - 1) + ')" ' +
        (currentPage === 1 ? 'disabled' : '') + '>« 上一页</button>';

    // 页码
    var startPage = Math.max(1, currentPage - 2);
    var endPage = Math.min(totalPages, currentPage + 2);

    if (startPage > 1) {
        html += '<button class="page-btn" onclick="loadQuestions(1)">1</button>';
        if (startPage > 2) html += '<span style="color:#666;padding:10px;">...</span>';
    }

    for (var i = startPage; i <= endPage; i++) {
        html += '<button class="page-btn ' + (i === currentPage ? 'active' : '') + '" ' +
            'onclick="loadQuestions(' + i + ')">' + i + '</button>';
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += '<span style="color:#666;padding:10px;">...</span>';
        html += '<button class="page-btn" onclick="loadQuestions(' + totalPages + ')">' + totalPages + '</button>';
    }

    // 下一页
    html += '<button class="page-btn" onclick="loadQuestions(' + (currentPage + 1) + ')" ' +
        (currentPage === totalPages ? 'disabled' : '') + '>下一页 »</button>';

    container.innerHTML = html;
}

// 搜索题目
function searchQuestions() {
    currentSearch = document.getElementById('searchInput').value.trim();
    loadQuestions(1);
}

// 清除搜索
function clearSearch() {
    document.getElementById('searchInput').value = '';
    currentSearch = '';
    loadQuestions(1);
}

// 加载历史记录
function loadHistory() {
    var container = document.getElementById('historyList');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载中...</p></div>';

    fetch('/api/history')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.length === 0) {
                container.innerHTML = '<p style="text-align:center;color:#888;padding:50px;">暂无上传记录</p>';
                return;
            }

            var html = '';
            data.forEach(function (item) {
                html += '<div class="history-item" id="history-' + item.id + '">' +
                    '<div class="history-info">' +
                    '<span class="history-time">📅 ' + item.uploaded_at + '</span>' +
                    '<span class="history-stats">' +
                    '新增 <strong>' + item.questions_added + '</strong> 道 | ' +
                    '更新 <strong>' + item.questions_updated + '</strong> 道' +
                    '</span>' +
                    '</div>' +
                    '<button class="delete-btn" onclick="deleteHistory(' + item.id + ')" title="删除此记录">🗑️</button>' +
                    '</div>';
            });
            container.innerHTML = html;
        })
        .catch(function (err) {
            container.innerHTML = '<p style="color:#ff3232;">加载失败: ' + err.message + '</p>';
        });
}

// 删除历史记录
function deleteHistory(logId) {
    if (!confirm('确定要删除这条上传记录吗？\n\n⚠️ 此操作将会：\n- 删除该次上传新增的所有题目\n- 回退该次上传的答题计数更新\n\n此操作不可恢复！')) {
        return;
    }

    fetch('/api/history/' + logId, {
        method: 'DELETE'
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                // 删除成功，移除DOM元素
                var element = document.getElementById('history-' + logId);
                if (element) {
                    element.remove();
                }
                loadStats();  // 刷新统计
                // 显示回退详情
                var msg = '删除成功！\n';
                if (data.reverted_added > 0) {
                    msg += '- 已删除 ' + data.reverted_added + ' 道新增题目\n';
                }
                if (data.reverted_updated > 0) {
                    msg += '- 已回退 ' + data.reverted_updated + ' 次答题计数';
                }
                alert(msg);
            } else {
                alert('删除失败: ' + data.error);
            }
        })
        .catch(function (err) {
            alert('删除失败: ' + err.message);
        });
}

// 删除题目
function deleteQuestion(questionId) {
    if (!confirm('确定要删除这道题目吗？\n此操作不可恢复！')) {
        return;
    }

    fetch('/api/questions/' + questionId, {
        method: 'DELETE'
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                loadQuestions(currentPage);  // 刷新题目列表
                loadStats();  // 刷新统计
            } else {
                alert('删除失败: ' + data.error);
            }
        })
        .catch(function (err) {
            alert('删除失败: ' + err.message);
        });
}

// HTML转义
function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/\n/g, '<br>');
}
