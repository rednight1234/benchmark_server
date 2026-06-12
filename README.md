# 3D Genome Structure Reconstruction Benchmark Server

一个用于单细胞 Hi-C 数据三维结构重建和模型对比的 Web 平台。提供自动数据预处理、分布式任务调度、评估指标计算和交互式可视化。

## ✨ 主要特性

- **多模型集成**：可通过简单封装扩展新模型。
- **一键预处理**：自动从原始 Hi-C 接触数据和 Dip‑C/PDB 坐标中提取训练/测试样本。
- **异步任务系统**：基于 Celery + Redis，支持长时间任务，实时进度反馈。
- **自动评估**：推理完成后自动计算 Pearson、Spearman、MSE 等指标，生成 2D/3D 对比图。
- **多模型对比**：可同时选择多个模型，在同一份数据上对比重建效果，结果以表格和柱状图展示。
- **交互式 Web 界面**：数据集浏览、任务管理、结果下载和可视化均通过浏览器完成。
- **模块化设计**：前后端分离，后端 API 通过 FastAPI 提供，便于集成到其他系统。

## 📋 环境要求

- **Python** 3.10+
- **Redis** (用于 Celery 消息队列和元数据存储)
- **Conda** (推荐，用于管理复杂依赖)
- **操作系统**：Linux / WSL2 (推荐)，macOS 可能需要额外配置

> 对于特定模型（如 Tensor-FLAMINGO、Si‑C），需要独立的 Conda 环境，模型代码中通过 `conda run -n <env>` 调用，无需在主环境中安装其依赖。 *但需要自行修改其运行环境的路径配置以指向正确的目录, 扩展新模型时请注意配置环境*

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/rednight1234/benchmark_server.git
cd benchmark_server
```

### 2. 创建主环境

```bash
conda env create -f environment.yml
conda activate benchmark
```

如果某些模型需要独立环境，请参照模型目录下的文档手动创建，并确保环境名称与模型代码中 `MODEL_ENV` 变量一致。

### 3. 启动 Redis

```bash
# 如果未安装 redis，请先安装：sudo apt install redis-server
redis-server --daemonize yes
```

### 4. 启动 Celery Worker

```bash
# 可以通过更改concurrency来控制并发数量
celery -A api.task worker --loglevel=info --concurrency=1
```

> 首次运行时，Worker 会自动注册 `models/` 目录下的所有模型。

### 5. 启动 FastAPI 服务

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

现在打开浏览器，访问 `http://localhost:8000` 即可使用平台。

### 6. (可选) 一键启动脚本

```bash
bash start.sh
```

## 📂 数据集准备

原始数据应放置在 `data/` 目录下，按以下结构组织：

```
data/
├── GM12878/                 # 数据集名称
│   ├── dataset_info.json    # 数据集描述文件
│   ├── original/            # 重复类型（如 original, rep1, rep2）
│   │   ├── 01/              # 细胞编号
│   │   │   ├── *.3dg.txt    # 3dg 格式坐标文件
│   │   │   └── *.con.txt    # Hi‑C 接触对文件
│   │   ├── 02/
│   │   └── ...
│   ├── rep1/
│   └── rep2/
└── scHiC_mESC/
    ├── dataset_info.json
    └── original/
        └── 01/
            ├── *.pdb        # PDB 格式坐标文件
            └── *_contact_pairs.txt  # Hi‑C 接触对文件
```

`dataset_info.json` 示例：

```json
{
  "name": "GM12878",
  "species": "human",
  "assembly": "hg19",
  "description": "GM12878细胞的Dip-C数据集，hg19，包含original和两个生物学重复(rep1/rep2)，共16个细胞"
}
```

平台会自动扫描该目录结构，并在“数据集浏览”页面上展示。

## 📖 使用流程

1. **浏览数据集**：导航栏“数据集浏览”可查看所有可用数据集及细胞，支持文件预览和下载。
2. **新建任务**：点击“新建任务”，选择数据集、重复类型、细胞、染色体、分辨率等参数，然后点击“开始预处理”。
   - 预处理完成后，会自动进入模型选择步骤。
   - 勾选一个或多个模型，提交后任务将排队执行。
3. **查看进度**：在“任务工作台”可查看所有任务的实时状态。对于多模型对比任务，详情页会展示每个子模型的独立进度条。
4. **查看结果**：任务完成后，进入任务详情页：
   - 下载原始 Hi‑C 文件、真实坐标文件以及模型预测坐标。
   - 自动评估结果包括指标表格（Pearson, Spearman, MSE）、2D 距离对比图和 3D 染色质轨迹对比图。
   - 多模型对比任务还会显示综合对比表格和柱状图。
5. **上传评估**：如果你有自己生成的预测坐标文件，可通过“上传评估”页面，选择数据集中的细胞作为真实坐标，快速计算指标。

## 🧩 添加新模型

添加新模型只需要三步：

1. 在 `models/` 目录下新建一个 Python 文件（如 `chromo3d.py`）。
2. 实现 `run(info: dict, progress_callback) -> dict` 函数，接口规范如下：
   ```python
   def run(info: dict, progress_callback) -> dict:
       """
       info: {
           'chr_name': str,      # 染色体名
           'assembly': str,      # 基因组版本
           'input_file': str,    # Hi‑C 接触对文件路径
           'resolution': int,    # 分辨率(bp)
           'work_dir': str,      # 任务工作目录
           'true_coords_file': str, # 真实坐标文件路径（可选，用于自动评估）
       }
       progress_callback(percent: int, message: str)  # 更新进度
       return {
           'status': 'success' or 'error',
           'message': '简短描述',
           'output_file': '预测坐标文件路径',  # .txt
       }
       ```
3. 重启 Celery Worker，模型会自动注册并出现在前端选择列表中。

如需适配其他格式或输入输出,请更改()接口
扩展模型时请自行核对模型是否可以正常运行
模型的运行log等其他功能需要自行实现

## 📚 API 文档

平台启动后，访问 `http://localhost:8000/docs` 可查看自动生成的 Swagger UI 文档。

## 🛠️ 停止服务

```bash
# 停止 Celery Worker
pkill -f "celery worker"

# 停止 Uvicorn
pkill -f "uvicorn"

# 停止 Redis (如果需要)
redis-cli shutdown
```

