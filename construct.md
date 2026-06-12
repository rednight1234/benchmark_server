# 3D Genome Structure Reconstruction Benchmark Server — 后端开发与维护文档

> 本文档面向需要对平台进行**维护、调试、功能扩展**的开发人员。阅读本文前请先阅读 `README.md` 了解平台的基本功能和使用方法。

---

## 一、整体架构概览

### 1.1 技术栈

- **Web 框架**：FastAPI
- **异步任务**：Celery + Redis
- **前端**：Jinja2 模板 + 原生 JavaScript
- **模型调用**：Python `subprocess` 模块
- **数值计算**：NumPy, SciPy, scikit-learn
- **绘图**：Matplotlib
- **环境管理**：Conda（每个模型有独立环境）

### 1.2 架构图

```
用户浏览器
    │
    ▼
FastAPI (Uvicorn)      # 处理 HTTP 请求
    │
    ├─→ Redis           # 存储任务元数据、任务状态
    └─→ Celery Worker   # 执行长时间任务
         │
         ├─→ 数据预处理（process_cell）
         ├─→ 模型推理（调用 models/ 下的各个模型）
         └─→ 自动评估（align_and_benchmark）
              │
              └─→ Redis（存储评估结果）
```

### 1.3 数据流

```
原始数据 (data/目录)
    │
    ▼
预处理任务 (run_preprocess)
    │
    ├─→ Hi-C 接触对文件 (*_hic_pairs.txt)
    └─→ 真实坐标文件 (*_true_coords.npy)
         │
         ▼
推理任务 (run_reconstruction)
    │
    ├─→ 调用模型封装函数 (models/*.py)
    └─→ 模型预测坐标文件 (flamingo_output.txt / sic_output.txt)
         │
         ▼
自动评估 (align_and_benchmark)
    │
    ├─→ 距离相关性指标 (PCC, Spearman, MSE)
    ├─→ 2D 距离对比图 (base64 PNG)
    ├─→ 3D 染色质轨迹图 (base64 PNG)
    └─→ 覆盖率统计
         │
         ▼
Redis (task_meta:{id} 的 eval_result 字段)
         │
         ▼
前端展示（任务详情页）
```

---

## 二、目录结构及各文件说明

```
benchmark_server/
├── api/                          # 后端核心代码
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用，路由定义
│   ├── task.py                   # Celery 任务（预处理、推理、自动评估）
│   ├── preprocess.py             # 数据预处理逻辑
│   ├── benchmark.py              # 评估函数、绘图函数
│   ├── data_utils.py             # 上传文件格式分析
│   ├── utils.py                  # Redis 操作、任务元数据管理
│   ├── logger.py                 # 统一日志配置
│   └── register_models.py        # 自动扫描 models/ 目录注册模型
├── models/                       # 模型封装（每个模型一个文件）
│   ├── __init__.py
│   ├── tensorflamingo.py         # Tensor-FLAMINGO 模型
│   ├── sic.py                    # Si-C 模型
│   └── example_model.py          # 示例模型（用于测试）
├── frontend/                     # 前端文件（详见 README.md）
├── start.sh                      # 一键启动脚本
├── environment.yml               # Conda 环境文件
└── README.md                     # 用户文档
```

### 2.1 `api/main.py` — FastAPI 路由

**主要路由分类：**

| 路由前缀 | 功能 | 关键函数 |
|:---|:---|:---|
| `/api/datasets` | 数据集浏览 API | `list_datasets`, `get_dataset_info`, `get_cell_list`, `get_cell_files` |
| `/preprocess` | 数据预处理 | `start_preprocess`, `preprocess_progress`, `preprocess_result` |
| `/api/tasks` | 任务管理 | `list_tasks`, `get_task_detail`, `delete_task` |
| `/api/task/{id}/*` | 任务进度、结果下载 | `get_progress`, `get_result`, `revoke_task` |
| `/reconstruct` | 单模型推理 | `submit_task` |
| `/api/benchmark/compare` | 多模型对比 | `submit_compare_task` |
| `/api/benchmark/evaluate` | 上传评估 | `evaluate_upload` |
| `/api/evaluate` | 内部评估接口 | `evaluate` |
| `/visualize` | 3D 轨迹图生成 | `visualize` |
| `/api/models` | 获取可用模型列表 | `list_models` |

### 2.2 `api/task.py` — Celery 任务

**核心函数：**

- **`run_preprocess`**：数据预处理任务
  - 调用 `preprocess.py` 中的 `process_cell`
  - 返回 `hic_file`, `true_coords_file` 路径
  - 将文件路径存入 Redis `task_meta`

- **`run_reconstruction`**：模型推理任务
  - 从 `MODEL_RUNNERS` 中获取对应模型的 `run` 函数
  - 调用 `run(info, progress_callback)`
  - 成功后自动调用 `align_and_benchmark` 进行评估
  - 将评估结果存入 Redis
  - 如果是对比任务的子任务，调用 `check_and_finalize_compare` 通知父任务

### 2.3 `api/preprocess.py` — 数据预处理

**核心函数：**

- **`load_dipc_coords`**：加载真实坐标（自动识别 `.3dg.txt` 或 `.pdb` 格式）
- **`load_hic_contacts`**：加载 Hi-C 接触对（兼容 `.con.txt` 和 `pairs.txt` 格式）
- **`process_cell`**：处理单个细胞，生成 `hic_pairs.txt` 和 `true_coords.npy`

**适配新数据格式**：在此文件中修改 `load_dipc_coords` 和 `load_hic_contacts`，增加对新格式的解析逻辑。

### 2.4 `api/benchmark.py` — 评估与绘图

**核心函数：**

- **`clean_coords`**：清洗坐标（过滤 NaN 和全零行），返回覆盖率信息
- **`align_and_benchmark`**：对齐 + 计算指标 + 生成 2D 对比图
- **`generate_chromatin_trajectory`**：生成 3D 染色质轨迹图
- **`generate_comparison_charts`**：生成多模型对比柱状图

**修改评估指标**：在 `compute_distance_correlation` 中添加新指标的计算逻辑。

### 2.5 `api/utils.py` — Redis 操作

**核心函数：**

- **任务元数据**：`save_task_meta`, `get_task_meta`, `update_task_status`, `delete_task_meta`, `get_all_tasks`, `get_detail`
- **对比任务**：`save_compare_task`, `check_and_finalize_compare`, `update_compare_child_tasks`
- **进程管理**：`set_task_process_pid`, `get_and_clear_task_process_pid`

**注意**：所有 Redis 操作都通过此文件封装，`main.py` 和 `task.py` 不应直接导入 `redis_client`。(但目前的文件中有部分导入了redis_client进行操作, 这是有待改进的)

### 2.6 `models/` — 模型封装

每个模型文件必须实现以下接口：

```python
def run(info: dict, progress_callback) -> dict:
    """
    info: {
        'chr_name': str,           # 染色体名
        'assembly': str,           # 基因组版本
        'input_file': str,         # Hi-C 接触对文件路径
        'resolution': int,         # 分辨率 (bp)
        'work_dir': str,           # 任务工作目录
        'true_coords_file': str,   # 真实坐标文件路径（可选）
    }
    progress_callback(percent: int, message: str)

    return {
        'status': 'success' or 'error',
        'message': str,
        'output_file': str,        # 预测坐标文件路径（.txt 或 .npy）
        'format': str              # 'txt' 或 'npy'
    }
    """
```

新模型只需在 `models/` 下添加一个文件，重启 Celery Worker 即可自动注册。

---

## 三、任务执行调用流

### 3.1 单模型推理任务

```
用户提交 (new_task.js)
    │
    ▼
POST /reconstruct (main.py: submit_task)
    │
    ├─→ 保存任务元数据到 Redis
    └─→ 提交 Celery 任务 run_reconstruction.apply_async()
         │
         ▼
    Celery Worker (task.py: run_reconstruction)
         │
         ├─→ 从 MODEL_RUNNERS 获取模型 run 函数
         ├─→ 调用 run(info, progress_callback)
         │    │
         │    └─→ 模型内部通过 subprocess 调用外部程序, 或其他方法实现模型推理
         │
         ├─→ 推理成功后，调用 align_and_benchmark 进行评估
         │    │
         │    └─→ 评估结果存入 Redis (eval_result 字段)
         │
         └─→ 更新任务状态为 SUCCESS
```

### 3.2 多模型对比任务

```
用户提交 (new_task.js)
    │
    ▼
POST /api/benchmark/compare (main.py: submit_compare_task)
    │
    ├─→ 创建父任务元数据（task_type='compare'）
    ├─→ 为每个模型创建子任务（task_type='reconstruction'）
    └─→ 更新父任务的 child_tasks 列表
         │
         ▼
    每个子任务独立执行（同单模型流程）
         │
         └─→ 子任务完成后调用 check_and_finalize_compare
              │
              ├─→ 检查所有子任务是否完成
              ├─→ 收集各模型的评估结果
              ├─→ 调用 generate_comparison_charts 生成对比图表
              └─→ 存入父任务的 eval_result 字段
```

### 3.3 进度查询与前端轮询

```
前端 setInterval(pollInference, 1000)
    │
    ▼
GET /api/task/{id}/progress (main.py: get_progress)
    │
    ├─→ 从 Celery AsyncResult 获取状态
    └─→ 返回 {status, percent, message}
```

对于对比任务，进度接口会从 Redis 读取子任务状态，计算总体进度百分比。

---

## 四、已知问题与注意事项

### 4.1 子进程残留问题

**现象**：删除任务后，`Rscript` 或 `bash` 进程仍在后台运行。

**原因**：Celery 的 `revoke` 只能终止 Worker 中的任务，无法递归终止任务创建的子进程。

**目前方案(不一定确定解决)**：
- 模型封装代码中使用 `subprocess.Popen`，将 PID 存入 Redis（`set_task_process_pid`）。
- 删除任务时，后端从 Redis 获取 PID 并通过 `os.kill(pid, signal.SIGKILL)` 强制终止。
- 若仍残留，手动执行 `pkill -9 -f "Rscript|FLAMINGO|Si-C"` 清理。

### 4.2 FLAMINGO 模型端口冲突问题

**现象**：FLAMINGO 的 R 脚本报错 `creation of server socket failed: port XXXX cannot be opened`。

**原因**：FLAMINGO 内部使用 `makeCluster` 创建并行节点，默认占用随机端口，多个任务同时运行时可能冲突。

**目前方案**：
- 修改降低 `FLAMINGO_reconstruct.R` 中的 `nThread` 参数。

### 4.3 前端模型选择动态更新

**说明**：模型列表通过 `/api/models` 接口从后端动态获取，前端 `loadModelCheckboxes` 函数自动创建复选框。

**添加新模型后**：只需重启 Celery Worker，前端无需任何修改。

### 4.4 任务删除与本地文件清理

**说明**：删除任务时，后端会同时：
1. 撤销 Celery 任务（`revoke`）
2. 删除 Redis 中的元数据
3. 删除本地工作目录（`usr_data/{task_id}` 和 `usr_results/{task_id}`）

**注意**：如果任务正在运行，子进程可能不会立即终止，需通过 PID 强制 kill。如果遇到任务已删除但本地目录仍然存在的情况,请检查任务记录的task_id与实际使用的task_id是否一直

---

## 五、扩展指南

### 5.1 添加新模型

1. 在 `models/` 下新建 `.py` 文件。
2. 实现 `run(info: dict, progress_callback) -> dict` 函数。
3. 重启 Celery Worker，模型自动注册。
**注意**: log等功能需自行实现

### 5.2 适配新数据格式

- **坐标文件**：修改 `api/preprocess.py` 中的 `load_dipc_coords`，增加新格式的解析分支。
- **接触对文件**：修改 `api/preprocess.py` 中的 `load_hic_contacts`，支持新的列名或分隔符。

### 5.3 添加新评估指标

修改 `api/benchmark.py` 中的 `compute_distance_correlation` 函数，添加新指标的计算。

### 5.4 前端页面修改

所有前端模板位于 `frontend/templates/`，JavaScript 文件位于 `frontend/static/js/`。修改后刷新浏览器即可生效。

---

## 六、调试与日志

- **FastAPI 日志**：输出到终端，同时写入 `logs/` 目录。
- **Celery Worker 日志**：输出到终端，可通过 `celery_worker.log` 重定向。
- **模型内部日志**：FLAMINGO 的日志在任务工作目录下的 `flamingo_reconstruct.log`；Si‑C 的日志在 `sic_logs/sic_run.log`。
- **Redis 数据查看**：使用 `redis-cli -n 1` 连接到数据库 1，通过 `HGETALL task_meta:<id>` 查看任务详情。