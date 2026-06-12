document.addEventListener('DOMContentLoaded', () => {
    const datasetSelect = document.getElementById('dataset-select');
    const repSelect = document.getElementById('rep-select');
    const cellSelect = document.getElementById('cell-select');
    const chromInput = document.getElementById('chrom-input');
    const startInput = document.getElementById('start-input');
    const endInput = document.getElementById('end-input');
    const resolutionInput = document.getElementById('resolution-input');
    const predFile = document.getElementById('pred-file');
    const evaluateBtn = document.getElementById('evaluate-btn');
    const resultsDiv = document.getElementById('results');

    let currentDataset, currentRepType, currentCellId;

    // 加载数据集列表
    async function loadDatasets() {
        const resp = await fetch('/api/datasets');
        const data = await resp.json();
        data.datasets.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            datasetSelect.appendChild(opt);
        });
    }

    datasetSelect.addEventListener('change', async () => {
        currentDataset = datasetSelect.value;
        repSelect.innerHTML = '<option value="">-- 加载中 --</option>';
        repSelect.disabled = !currentDataset;
        cellSelect.innerHTML = '<option value="">-- 请先选重复类型 --</option>';
        cellSelect.disabled = true;
        if (!currentDataset) return;

        const resp = await fetch(`/api/datasets/${currentDataset}`);
        const data = await resp.json();
        repSelect.innerHTML = '<option value="">-- 请选择 --</option>';
        data.rep_types.forEach(rep => {
            const opt = document.createElement('option');
            opt.value = rep;
            opt.textContent = rep;
            repSelect.appendChild(opt);
        });
    });

    repSelect.addEventListener('change', async () => {
        currentRepType = repSelect.value;
        cellSelect.innerHTML = '<option value="">-- 加载中 --</option>';
        cellSelect.disabled = !currentRepType;
        if (!currentRepType) return;

        const resp = await fetch(`/api/datasets/${currentDataset}/${currentRepType}`);
        const data = await resp.json();
        cellSelect.innerHTML = '<option value="">-- 请选择 --</option>';
        data.cells.forEach(cell => {
            const opt = document.createElement('option');
            opt.value = cell;
            opt.textContent = cell;
            cellSelect.appendChild(opt);
        });
    });

    cellSelect.addEventListener('change', () => {
        currentCellId = cellSelect.value;
        evaluateBtn.disabled = !currentCellId || !predFile.files.length;
    });

    predFile.addEventListener('change', () => {
        evaluateBtn.disabled = !currentCellId || !predFile.files.length;
    });

    evaluateBtn.addEventListener('click', async () => {
        const formData = new FormData();
        formData.append('pred_file', predFile.files[0]);
        formData.append('dataset', currentDataset);
        formData.append('rep_type', currentRepType);
        formData.append('cell_id', currentCellId);
        formData.append('chrom', chromInput.value);
        formData.append('start', startInput.value);
        formData.append('end', endInput.value);
        formData.append('resolution', resolutionInput.value);

        evaluateBtn.disabled = true;
        evaluateBtn.textContent = '评估中...';
        resultsDiv.style.display = 'none';

        try {
            const resp = await fetch('/api/benchmark/evaluate', { method: 'POST', body: formData });
            if (!resp.ok) {
                const err = await resp.json();
                alert('评估失败: ' + (err.detail || err.error || resp.status));
                return;
            }
            const data = await resp.json();

            let html = '<h3>评估结果</h3>';
            html += '<table>';
            for (const [key, val] of Object.entries(data.metrics)) {
                html += `<tr><td>${key}</td><td>${Number(val).toFixed(4)}</td></tr>`;
            }
            html += `</table><p>点数: ${data.n_points}</p>`;
            if (data.plot_2d) html += `<h4>2D对比图</h4><img src="data:image/png;base64,${data.plot_2d}" style="max-width:100%;">`;
            if (data.plot_3d) html += `<h4>3D轨迹图</h4><img src="${data.plot_3d}" style="max-width:100%;">`;
            resultsDiv.innerHTML = html;
            resultsDiv.style.display = 'block';
        } catch (err) {
            alert('网络错误: ' + err.message);
        } finally {
            evaluateBtn.disabled = false;
            evaluateBtn.textContent = '开始评估';
        }
    });

    loadDatasets();
});