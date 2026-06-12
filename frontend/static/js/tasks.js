document.addEventListener('DOMContentLoaded', () => {
    const taskListBody = document.getElementById('task-list-body');
    const refreshBtn = document.getElementById('refresh-btn');
    const statusFilter = document.getElementById('status-filter');
    const selectAll = document.getElementById('select-all');
    const deleteSelectedBtn = document.getElementById('delete-selected-btn');
    const username = localStorage.getItem('username') || 'anonymous';

    // 加载任务列表
    async function loadTasks() {
        const status = statusFilter.value;
        let url = `/api/tasks?username=${encodeURIComponent(username)}`;
        if (status) url += `&status=${status}`;
        const resp = await fetch(url);
        const data = await resp.json();
        renderTasks(data.tasks);
    }

    // 渲染任务表格
    function renderTasks(tasks) {
        taskListBody.innerHTML = '';
        tasks.forEach(task => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="checkbox" class="task-checkbox" data-taskid="${task.task_id}"></td>
                <td><a href="/tasks/${task.task_id}" class="task-link">${task.task_id.substring(0, 8)}...</a></td>
                <td>${task.username}</td>
                <td>${task.model}</td>
                <td>${task.task_type === 'reconstruction' ? '重建' : '预处理'}</td>
                <td>${JSON.parse(task.params).chr_name || '-'}</td>
                <td><span class="status-badge status-${task.status}">${task.status}</span></td>
                <td>${new Date(task.created_at).toLocaleString()}</td>
                <td>
                    ${task.status === 'SUCCESS' ? `<button class="download-btn" data-taskid="${task.task_id}">下载</button>` : ''}
                    <button class="delete-btn" data-taskid="${task.task_id}">删除</button>
                </td>
            `;
            taskListBody.appendChild(tr);
        });

        // 绑定下载和删除事件
        document.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const taskId = e.target.dataset.taskid;
                window.open(`/api/task/${taskId}/result`);
            });
        });

        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const taskId = e.target.dataset.taskid;
                if (confirm('确认删除此任务？')) {
                    await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
                    loadTasks();
                }
            });
        });
    }

    // 批量删除
    deleteSelectedBtn.addEventListener('click', async () => {
        const checkboxes = document.querySelectorAll('.task-checkbox:checked');
        for (const cb of checkboxes) {
            await fetch(`/api/tasks/${cb.dataset.taskid}`, { method: 'DELETE' });
        }
        loadTasks();
    });

    selectAll.addEventListener('change', (e) => {
        document.querySelectorAll('.task-checkbox').forEach(cb => cb.checked = e.target.checked);
    });

    refreshBtn.addEventListener('click', loadTasks);
    statusFilter.addEventListener('change', loadTasks);

    // 初始加载，并每30秒自动刷新
    loadTasks();
    setInterval(loadTasks, 30000);
});