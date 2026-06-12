document.addEventListener('DOMContentLoaded', () => {
    const cardGrid = document.getElementById('dataset-cards');
    const detailPanel = document.getElementById('dataset-detail');
    const backBtn = document.getElementById('back-btn');
    const detailTitle = document.getElementById('detail-title');
    const detailDesc = document.getElementById('detail-desc');
    const repTabs = document.getElementById('rep-tabs');
    const cellList = document.getElementById('cell-list');
    const fileModal = document.getElementById('file-modal');
    const fileModalTitle = document.getElementById('file-modal-title');
    const fileListUl = document.getElementById('file-list');
    const useDataBtn = document.getElementById('use-data-btn');
    const closeBtns = document.querySelectorAll('.close');

    let currentDataset = null;
    let selectedFileName = null;
    let selectedFilePath = null;
    let currentRepType = null;
    let currentCellId = null;

    // 加载数据集列表
    async function loadDatasets() {
        try {
            const resp = await fetch('/api/datasets');
            const data = await resp.json();
            renderCards(data.datasets);
        } catch (err) {
            console.error('加载数据集失败', err);
        }
    }

    function renderCards(datasets) {
        cardGrid.innerHTML = '';
        if (!datasets || datasets.length === 0) {
            cardGrid.innerHTML = '<p>暂无数据集</p>';
            return;
        }
        datasets.forEach(name => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<h3>${name}</h3><p>点击查看详情</p>`;
            card.addEventListener('click', () => showDatasetDetail(name));
            cardGrid.appendChild(card);
        });
    }

    // 显示数据集详情
    async function showDatasetDetail(name) {
        currentDataset = name;
        try {
            const resp = await fetch(`/api/datasets/${name}`);
            const data = await resp.json();
            detailTitle.textContent = data.name;
            detailDesc.textContent = data.description || '';
            renderRepTabs(data.rep_types, data);
            cardGrid.style.display = 'none';
            detailPanel.style.display = 'block';
        } catch (err) {
            console.error('加载数据集详情失败', err);
        }
    }

    // 渲染重复类型选项卡
    function renderRepTabs(repTypes, datasetData) {
        repTabs.innerHTML = '';
        repTypes.forEach((rep, index) => {
            const tab = document.createElement('button');
            tab.textContent = rep;
            tab.className = 'tab-btn';
            if (index === 0) tab.classList.add('active');
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                tab.classList.add('active');
                currentRepType = rep;
                loadCellsForRep(rep);
            });
            repTabs.appendChild(tab);
        });
        if (repTypes.length > 0) {
            currentRepType = repTypes[0];
            loadCellsForRep(repTypes[0]);
        }
    }

    // 加载某重复类型下的细胞列表
    async function loadCellsForRep(repType) {
        try {
            const resp = await fetch(`/api/datasets/${currentDataset}/${repType}`);
            const data = await resp.json();
            renderCells(data.cells, repType);
        } catch (err) {
            console.error('加载细胞列表失败', err);
        }
    }

    function renderCells(cells, repType) {
        cellList.innerHTML = '';
        if (!cells || cells.length === 0) {
            cellList.innerHTML = '<p>无可用细胞</p>';
            return;
        }
        cells.forEach(cellId => {
            const cellDiv = document.createElement('div');
            cellDiv.className = 'cell-card';
            cellDiv.innerHTML = `<h4>Cell ${cellId}</h4>`;
            cellDiv.addEventListener('click', () => {
                currentCellId = cellId;
                showCellFiles(currentDataset, repType, cellId);
            });
            cellList.appendChild(cellDiv);
        });
    }

    // 展示某个细胞下的文件
    async function showCellFiles(dataset, repType, cellId) {
        try {
            const resp = await fetch(`/api/datasets/${dataset}/${repType}/${cellId}/files`);
            const data = await resp.json();
            fileModalTitle.textContent = `Cell ${cellId} - 文件列表`;
            fileListUl.innerHTML = '';
            data.files.forEach(file => {
                const li = document.createElement('li');
                const typeBadge = file.type === 'hic' ? '🔬 Hi-C' : '📍 pos';
                const previewLines = file.preview.join('\n');
                li.innerHTML = `
                    <div class="file-info">
                        <strong>${file.filename}</strong>
                        <span class="badge badge-${file.type}">${typeBadge}</span>
                        <span class="file-meta">${file.line_count} 行, ${(file.size/1024).toFixed(1)} KB</span>
                        <div class="file-preview">
                            <pre>${previewLines}</pre>
                        </div>
                        <a href="/api/files/download?path=${encodeURIComponent(file.path)}" 
                        class="download-btn" download>⬇ 下载</a>
                    </div>
                `;
                li.style.cursor = 'pointer';
                fileListUl.appendChild(li);
            });
            fileModal.style.display = 'block';
        } catch (err) {
            console.error('加载文件列表失败', err);
        }
    }


    // 关闭模态框
    closeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            fileModal.style.display = 'none';
            useDataBtn.disabled = true;
        });
    });
    window.addEventListener('click', (e) => {
        if (e.target === fileModal) {
            fileModal.style.display = 'none';
            useDataBtn.disabled = true;
        }
    });

    backBtn.addEventListener('click', () => {
        detailPanel.style.display = 'none';
        cardGrid.style.display = 'grid';
    });

    loadDatasets();
});