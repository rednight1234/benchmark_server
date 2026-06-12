document.addEventListener('DOMContentLoaded', async () => {
    const taskId = window.location.pathname.split('/').pop();
    const container = document.getElementById('task-detail-container');

    // 保存当前运行的定时器，用于切换时清理
    let currentInterval = null;

    // 清除之前的轮询，避免重复
    function clearAllIntervals() {
        if (currentInterval) {
            clearInterval(currentInterval);
            currentInterval = null;
        }
    }

    // 重新加载任务详情数据，并更新 DOM（代替 location.reload）
    async function reloadTaskDetail() {
        try {
            const resp = await fetch(`/api/tasks/${taskId}`);
            if (!resp.ok) throw new Error('加载失败');
            const task = await resp.json();
            renderTaskDetail(task); // 提取渲染逻辑为独立函数
        } catch (err) {
            console.error('刷新任务详情失败', err);
        }
    }

    // 子任务进度轮询
    async function loadChildrenProgress(taskId) {
        try {
            const resp = await fetch(`/api/tasks/${taskId}/children`);
            const data = await resp.json();
            const childrenContainer = document.getElementById('children-progress');
            if (!childrenContainer) return;

            let allDone = true;
            let html = '';
            data.children.forEach(child => {
                const pct = child.percent || 0;
                if (child.status !== 'SUCCESS' && child.status !== 'FAILURE') {
                    allDone = false;
                }
                html += `
                    <div class="child-progress-item">
                        <div class="child-model-name">${child.model}</div>
                        <div class="progress-container small">
                            <div class="progress-bar" style="width:${pct}%">${pct}%</div>
                        </div>
                        <div class="child-message">${child.message || child.status}</div>
                    </div>`;
            });
            childrenContainer.innerHTML = html;

            if (allDone) {
                // ✅ 修复：不再刷新页面，而是重新获取任务数据并更新 DOM
                clearAllIntervals();
                setTimeout(() => reloadTaskDetail(), 1000);
            } else {
                // 继续轮询，并更新 currentInterval
                clearAllIntervals();
                currentInterval = setInterval(() => loadChildrenProgress(taskId), 2000);
            }
        } catch (err) {
            console.error('加载子任务进度失败', err);
        }
    }

    // 单任务进度轮询
    async function startSingleTaskPolling(taskId) {
        const interval = setInterval(async () => {
            try {
                const resp = await fetch(`/api/task/${taskId}/progress`);
                const data = await resp.json();
                const bar = document.getElementById('progress-bar');
                const msg = document.getElementById('progress-message');
                if (bar && data.percent !== undefined) {
                    bar.style.width = data.percent + '%';
                    bar.textContent = data.percent + '%';
                }
                if (msg && data.message) {
                    msg.textContent = data.message;
                }
                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    clearInterval(interval);
                    currentInterval = null;
                    setTimeout(() => reloadTaskDetail(), 1000);
                }
            } catch (e) {
                console.error('轮询进度失败', e);
            }
        }, 2000);
        currentInterval = interval;
    }

    // 将渲染逻辑提取为独立函数，方便重新调用
    async function renderTaskDetail(task) {
        try {
            const params = JSON.parse(task.params || '{}');
            let html = `
                <div class="section">
                    <h2>基本信息</h2>
                    <table class="detail-table">
                        <tr><td>任务ID</td><td>${task.task_id}</td></tr>
                        <tr><td>用户</td><td>${task.username || '-'}</td></tr>
                        <tr><td>类型</td><td>${task.task_type === 'reconstruction' ? '重建' : task.task_type === 'compare' ? '模型对比' : '预处理'}</td></tr>
                        <tr><td>模型</td><td>${task.model}</td></tr>
                        <tr><td>染色体</td><td>${params.chr_name || '-'}</td></tr>
                        <tr><td>分辨率</td><td>${params.resolution || '-'} bp</td></tr>
                        <tr><td>状态</td><td><span class="status-badge status-${task.status}">${task.status}</span></td></tr>
                        <tr><td>提交时间</td><td>${new Date(task.created_at).toLocaleString()}</td></tr>
                    </table>
                </div>
            `;

            // 文件下载区域
            html += `<div class="section"><h2>文件下载</h2><ul class="download-list">`;
            if (task.hic_file) {
                html += `<li><a href="/api/files/download?path=${encodeURIComponent(task.hic_file)}">📥 原始 Hi-C 接触文件</a></li>`;
            }
            if (task.true_coords_file) {
                html += `<li><a href="/api/files/download?path=${encodeURIComponent(task.true_coords_file)}">📥 真实坐标文件 (Dip-C)</a></li>`;
            }

            // 单模型任务下载
            if (task.status === 'SUCCESS' && task.task_type === 'reconstruction' && task.result_info?.output_file) {
                html += `<li><a href="/api/task/${task.task_id}/result">📥 预测坐标结果</a></li>`;
            }

            // 对比任务：获取子任务信息，生成带模型名的下载链接
            if (task.status === 'SUCCESS' && task.task_type === 'compare' && task.child_tasks) {
                try {
                    // 获取子任务列表（包含模型名和ID）
                    const childrenResp = await fetch(`/api/tasks/${task.task_id}/children`);
                    const childrenData = await childrenResp.json();
                    if (childrenData.children) {
                        childrenData.children.forEach(child => {
                            html += `<li><a href="/api/task/${child.task_id}/result">📥 ${child.model} 预测坐标</a></li>`;
                        });
                    }
                } catch (e) {
                    console.error('获取子任务信息失败', e);
                }
            }
            html += `</ul></div>`;

            // 评估结果
            if (task.eval_result) {
                const eval = task.eval_result;
                if (eval.eval_status === 'success' || eval.metrics_table || eval.metrics) {
                    html += '<div class="section"><h2>评估结果</h2>';
                    
                    if (task.task_type === 'compare' && eval.metrics_table) {
                        // 对比任务：表格 + 柱状图 + 子图
                        const models = Object.keys(eval.metrics_table);
                        if (models.length > 0) {
                            const metrics = Object.keys(eval.metrics_table[models[0]]);
                            html += '<table class="metrics-table"><tr><th>模型</th>';
                            metrics.forEach(m => html += `<th>${m}</th>`);
                            html += '</tr>';
                            models.forEach(m => {
                                html += `<tr><td>${m}</td>`;
                                metrics.forEach(met => {
                                    const val = eval.metrics_table[m][met];
                                    html += `<td>${val !== undefined && val !== null ? Number(val).toFixed(4) : '-'}</td>`;
                                });
                                html += '</tr>';
                            });
                            html += '</table>';
                        }
                        // 覆盖率显示
                        if (eval.individual_results) {
                            let covHtml = '<p><strong>评估覆盖:</strong><br>';
                            Object.keys(eval.individual_results).forEach(model => {
                                const cov = eval.individual_results[model]?.coverage;
                                if (cov) {
                                    covHtml += `${model}: ${cov.n_points_evaluated}/${cov.n_points_total} (${(cov.n_points_evaluated / cov.n_points_total * 100).toFixed(1)}%)<br>`;
                                } else {
                                    covHtml += `${model}: N/A<br>`;
                                }
                            });
                            covHtml += '</p>';
                            html += covHtml;
                        }
                        if (eval.bar_chart) {
                            html += `<img src="${eval.bar_chart}" class="result-plot" alt="对比图">`;
                        }
                        // 显示各个模型的3D图（如果有）
                        if (eval.individual_results) {
                            Object.keys(eval.individual_results).forEach(model => {
                                const indiv = eval.individual_results[model];
                                if (indiv.plot_3d) {
                                    html += `<div class="sub-plot"><h4>${model} 3D 轨迹图</h4><img src="${indiv.plot_3d}" class="result-plot"></div>`;
                                }
                            });
                        }
                    } else if (eval.metrics) {
                        // 单模型任务
                        html += '<table class="metrics-table">';
                        for (const [key, val] of Object.entries(eval.metrics)) {
                            html += `<tr><td>${key}</td><td>${Number(val).toFixed(4)}</td></tr>`;
                        }
                        html += `</table><p>评估点数: ${eval.n_points || '-'}</p>`;
                        if (eval.coverage) {
                            html += `<p class="coverage-info">评估覆盖: ${eval.coverage.n_points_evaluated} / ${eval.coverage.n_points_total} 位点 (${(eval.coverage.n_points_evaluated / eval.coverage.n_points_total * 100).toFixed(1)}%)</p>`;
                        }
                        if (eval.plot_2d) {
                            html += `<img src="data:image/png;base64,${eval.plot_2d}" class="result-plot">`;
                        }
                        if (eval.plot_3d) {
                            html += `<img src="${eval.plot_3d}" class="result-plot">`;
                        }
                    } else {
                        html += '<p class="warning">⚠️ 评估数据不完整</p>';
                    }
                    html += '</div>';
                } else {
                    html += '<p class="warning">⚠️ 自动评估失败</p>';
                }
            }

            // 运行中状态显示进度条
            if (task.status === 'PENDING' || task.status === 'PROGRESS') {
                if (task.task_type === 'compare') {
                    html += `
                        <div class="section">
                            <h2>子任务进度</h2>
                            <div id="children-progress"></div>
                        </div>`;
                    setTimeout(() => loadChildrenProgress(task.task_id), 100);
                } else {
                    html += `
                        <div class="section">
                            <h2>任务进度</h2>
                            <div class="progress-container">
                                <div id="progress-bar" class="progress-bar" style="width:0%">0%</div>
                            </div>
                            <p id="progress-message">等待中...</p>
                        </div>`;
                    setTimeout(() => startSingleTaskPolling(task.task_id), 100);
                }
            }

            container.innerHTML = html;
        } catch (err) {
            console.error('渲染任务详情失败', err);
            container.innerHTML = `<p class="error">渲染失败: ${err.message}</p>`;
        }
    }

    // 初次加载
    try {
        const resp = await fetch(`/api/tasks/${taskId}`);
        if (!resp.ok) {
            container.innerHTML = '<p class="error">任务不存在或加载失败</p>';
            return;
        }
        const task = await resp.json();
        renderTaskDetail(task);
    } catch (err) {
        container.innerHTML = '<p class="error">加载失败: ' + err.message + '</p>';
    }
});