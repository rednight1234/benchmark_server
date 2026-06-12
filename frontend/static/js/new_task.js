document.addEventListener('DOMContentLoaded', () => {
    const datasetSelect = document.getElementById('dataset-select');
    const repSelect = document.getElementById('rep-select');
    const cellSelect = document.getElementById('cell-select');
    const preprocessBtn = document.getElementById('preprocess-btn');
    const stopPreBtn = document.getElementById('stop-preprocess-btn');
    const preprocessProgress = document.getElementById('preprocess-progress');
    const preprocessBar = document.getElementById('preprocess-bar');
    const preprocessMessage = document.getElementById('preprocess-message');
    const fileListDiv = document.getElementById('preprocess-files');
    const fileList = document.getElementById('file-list');

    const inferenceSection = document.getElementById('inference-section');
    const reconstructBtn = document.getElementById('reconstruct-btn');
    const infResolution = document.getElementById('inf-resolution');
    const infChrom = document.getElementById('inf-chrom');
    const inferenceProgress = document.getElementById('inference-progress');
    const inferenceBar = document.getElementById('inference-bar');
    const inferenceMessage = document.getElementById('inference-message');
    const downloadLink = document.getElementById('download-link');
    const inferenceResult = document.getElementById('inference-result');

    let currentDataset = null;
    let currentRepType = null;
    let selectedPrepFile = null;
    let selectedTrueCoords = null;   
    let preprocessTaskId = null;
    let preprocessInterval = null;
    let inferenceTaskId = null;
    let inferenceInterval = null;
    let selectedModels = [];

    // 解析 URL 参数
    const urlParams = new URLSearchParams(window.location.search);
    const prefilledDataset = urlParams.get('dataset');
    const prefilledRepType = urlParams.get('rep_type');
    const prefilledCellId = urlParams.get('cell_id');
    const prefilledFilePath = urlParams.get('file_path');

    async function prefilledParams() {
        if (prefilledDataset) {
            datasetSelect.value = prefilledDataset;
            datasetSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 1000));
        }
        if (prefilledRepType) {
            repSelect.value = prefilledRepType;
            repSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 1000));
        }
        if (prefilledCellId) {
            cellSelect.value = prefilledCellId;
            cellSelect.dispatchEvent(new Event('change'));
        }
    }
    async function loadModelCheckboxes() {
        try {
            const resp = await fetch('/api/models');
            const data = await resp.json();
            const container = document.getElementById('model-checkboxes');
            container.innerHTML = ''; // 清空原有内容

            data.models.forEach((modelName, index) => {
                const label = document.createElement('label');
                label.className = 'checkbox-label';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.name = 'model';
                cb.value = modelName;
                if (index === 0) cb.checked = true; // 默认勾选第一个

                label.appendChild(cb);
                label.appendChild(document.createTextNode(' ' + modelName));
                container.appendChild(label);
            });
        } catch (err) {
            console.error('加载模型列表失败', err);
        }
    }
    async function loadDatasets() {
        try {
            const resp = await fetch('/api/datasets');
            const data = await resp.json();
            if (data.datasets) {
                data.datasets.forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name;
                    datasetSelect.appendChild(opt);
                });
            }
        } catch (err) {
            console.error('加载数据集失败', err);
        }
    }

    // 先加载数据集，再执行预填充
    loadDatasets().then(() => prefilledParams());

    datasetSelect.addEventListener('change', async () => {
        const ds = datasetSelect.value;
        currentDataset = ds;
        repSelect.innerHTML = '<option value="">-- 加载中 --</option>';
        repSelect.disabled = !ds;
        cellSelect.innerHTML = '<option value="">-- 请先选重复类型 --</option>';
        cellSelect.disabled = true;
        preprocessBtn.disabled = true;
        if (!ds) return;
        try {
            const resp = await fetch(`/api/datasets/${ds}`);
            const data = await resp.json();
            repSelect.innerHTML = '<option value="">-- 请选择 --</option>';
            if (data.rep_types) {
                data.rep_types.forEach(rep => {
                    const opt = document.createElement('option');
                    opt.value = rep;
                    opt.textContent = rep;
                    repSelect.appendChild(opt);
                });
            }
        } catch (err) {
            console.error('加载重复类型失败', err);
        }
    });

    repSelect.addEventListener('change', async () => {
        const rep = repSelect.value;
        currentRepType = rep;
        cellSelect.innerHTML = '<option value="">-- 加载中 --</option>';
        cellSelect.disabled = !rep;
        preprocessBtn.disabled = true;
        if (!rep) return;
        try {
            const resp = await fetch(`/api/datasets/${currentDataset}/${rep}`);
            const data = await resp.json();
            cellSelect.innerHTML = '<option value="">-- 请选择 --</option>';
            if (data.cells) {
                data.cells.forEach(cell => {
                    const opt = document.createElement('option');
                    opt.value = cell;
                    opt.textContent = cell;
                    cellSelect.appendChild(opt);
                });
            }
        } catch (err) {
            console.error('加载细胞列表失败', err);
        }
    });

    cellSelect.addEventListener('change', () => {
        preprocessBtn.disabled = !cellSelect.value;
    });

    preprocessBtn.addEventListener('click', async () => {
        if (!currentDataset || !currentRepType || !cellSelect.value) {
            alert('请先选择数据集、重复类型和细胞');
            return;
        }
        const params = new URLSearchParams();
        params.append('datadir', 'data');
        params.append('name', currentDataset);
        params.append('rep_type', currentRepType);
        params.append('cell_id', cellSelect.value);
        params.append('chrom', document.getElementById('pre-chrom').value);
        params.append('start', document.getElementById('pre-start').value);
        params.append('end', document.getElementById('pre-end').value);
        params.append('resolution', document.getElementById('pre-resolution').value);

        preprocessBtn.disabled = true;
        stopPreBtn.style.display = 'inline-block';
        preprocessProgress.style.display = 'block';
        preprocessBar.style.width = '0%';
        preprocessBar.textContent = '0%';
        preprocessMessage.textContent = '正在提交...';
        fileListDiv.style.display = 'none';
        inferenceSection.style.display = 'none';

        try {
            const resp = await fetch('/preprocess', { method: 'POST', body: params });
            const data = await resp.json();
            preprocessTaskId = data.task_id;
            preprocessInterval = setInterval(pollPreprocess, 1000);
        } catch (err) {
            preprocessMessage.textContent = '请求失败: ' + err.message;
            preprocessBtn.disabled = false;
            stopPreBtn.style.display = 'none';
        }
    });

    stopPreBtn.addEventListener('click', async () => {
        if (preprocessTaskId) {
            await fetch(`/api/task/${preprocessTaskId}/revoke`, { method: 'POST' });
            clearInterval(preprocessInterval);
            preprocessMessage.textContent = '任务已被用户停止';
            stopPreBtn.style.display = 'none';
            preprocessBtn.disabled = false;
        }
    });

    async function pollPreprocess() {
        try {
            const resp = await fetch(`/preprocess/${preprocessTaskId}/progress`);
            const data = await resp.json();
            if (data.status === 'PROGRESS') {
                preprocessBar.style.width = data.percent + '%';
                preprocessBar.textContent = data.percent + '%';
                preprocessMessage.textContent = data.message || '';
            } else if (data.status === 'SUCCESS') {
                clearInterval(preprocessInterval);
                preprocessBar.style.width = '100%';
                preprocessBar.textContent = '100%';
                preprocessMessage.textContent = '预处理完成！';
                stopPreBtn.style.display = 'none';
                preprocessBtn.disabled = false;
                const resultResp = await fetch(`/preprocess/${preprocessTaskId}/result`);
                if (resultResp.ok) {
                    const resultData = await resultResp.json();
                    const files = resultData.files;
                    if (!Array.isArray(files) || files.length === 0) {
                        preprocessMessage.textContent = '预处理结果为空';
                        return;
                    }
                    let hicFile = null, coordsFile = null;
                    files.forEach(f => {
                        if (f.endsWith('_hic_pairs.txt')) hicFile = f;
                        else if (f.endsWith('_true_coords.npy')) coordsFile = f;
                    });
                    if (hicFile && coordsFile) {
                        selectedPrepFile = hicFile;
                        selectedTrueCoords = coordsFile;
                        reconstructBtn.disabled = false;
                        inferenceSection.style.display = 'block';
                        // 将 selectedTrueCoords 存入隐藏字段
                        const hiddenTrueCoords = document.getElementById('hidden-true-coords');
                        if (hiddenTrueCoords) hiddenTrueCoords.value = selectedTrueCoords;
                    } else {
                        preprocessMessage.textContent = '未找到有效文件';
                    }
                }
            } else if (data.status === 'FAILURE') {
                clearInterval(preprocessInterval);
                preprocessMessage.textContent = '失败: ' + (data.error || '未知错误');
                stopPreBtn.style.display = 'none';
                preprocessBtn.disabled = false;
            }
        } catch (err) {
            clearInterval(preprocessInterval);
            preprocessMessage.textContent = '轮询失败: ' + err.message;
            stopPreBtn.style.display = 'none';
            preprocessBtn.disabled = false;
        }
    }

    reconstructBtn.addEventListener('click', async () => {
        if (!selectedPrepFile) {
            alert('请先选择一个预处理文件');
            return;
        }

        // 获取选中的模型列表
        const modelCheckboxes = document.querySelectorAll('input[name="model"]:checked');
        selectedModels = Array.from(modelCheckboxes).map(cb => cb.value);

        if (selectedModels.length === 0) {
            alert('请至少选择一个模型');
            return;
        }

        const params = new URLSearchParams();
        const hiddenTrueCoords = document.getElementById('hidden-true-coords');
        const trueCoordsFile = hiddenTrueCoords ? hiddenTrueCoords.value : selectedTrueCoords;
        params.append('true_coords_file', trueCoordsFile);
        params.append('input_file_path', selectedPrepFile);
        params.append('resolution', infResolution.value);
        params.append('chr_name', infChrom.value);
        params.append('assembly', document.getElementById('assembly-select').value);
        const username = localStorage.getItem('username') || 'anonymous';
        params.append('username', username);

        // 禁用按钮，显示进度条
        reconstructBtn.disabled = true;
        inferenceProgress.style.display = 'block';
        inferenceBar.style.width = '0%';
        inferenceBar.textContent = '0%';
        inferenceMessage.textContent = '正在提交...';
        inferenceResult.style.display = 'none';

        try {
            let resp;
            if (selectedModels.length === 1) {
                // 单模型推理
                params.append('model', selectedModels[0]);
                resp = await fetch('/reconstruct', { method: 'POST', body: params });
            } else {
                // 多模型对比
                params.append('models', selectedModels.join(','));
                resp = await fetch('/api/benchmark/compare', { method: 'POST', body: params });
            }

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                inferenceMessage.textContent = '提交失败: ' + (errData.error || resp.status);
                reconstructBtn.disabled = false;
                return;
            }

            const data = await resp.json();
            inferenceTaskId = data.task_id;
            inferenceInterval = setInterval(pollInference, 1000);
        } catch (err) {
            inferenceMessage.textContent = '请求失败: ' + err.message;
            reconstructBtn.disabled = false;
        }
    });

    async function pollInference() {
        try {
            const resp = await fetch(`/api/task/${inferenceTaskId}/progress`);
            const data = await resp.json();
            if (data.status === 'PROGRESS' || data.status === 'PENDING') {
                inferenceBar.style.width = data.percent + '%';
                inferenceBar.textContent = data.percent + '%';
                inferenceMessage.textContent = data.message || '';
            } else if (data.status === 'SUCCESS') {
                clearInterval(inferenceInterval);
                inferenceBar.style.width = '100%';
                inferenceBar.textContent = '100%';
                inferenceMessage.textContent = '推理任务完成！';

                // 创建查看详情链接
                const detailLink = document.createElement('a');
                detailLink.href = `/tasks/${inferenceTaskId}`;
                detailLink.textContent = '📊 查看评估结果';
                detailLink.className = 'btn-detail';
                inferenceResult.innerHTML = ''; // 清空之前的内容
                inferenceResult.appendChild(detailLink);
                inferenceResult.style.display = 'block';

                // 如果是单模型，额外提供下载链接
                if (selectedModels.length === 1) {
                    const downloadLink = document.createElement('a');
                    downloadLink.href = `/api/task/${inferenceTaskId}/result`;
                    downloadLink.textContent = '📥 下载预测坐标';
                    downloadLink.className = 'btn-download';
                    inferenceResult.appendChild(document.createElement('br'));
                    inferenceResult.appendChild(downloadLink);
                }

                reconstructBtn.disabled = false;
            } else if (data.status === 'FAILURE') {
                clearInterval(inferenceInterval);
                inferenceMessage.textContent = '失败: ' + (data.error || '未知错误');
                reconstructBtn.disabled = false;
            }
        } catch (err) {
            clearInterval(inferenceInterval);
            inferenceMessage.textContent = '轮询失败: ' + err.message;
            reconstructBtn.disabled = false;
        }
    }
    loadModelCheckboxes();
});