#./api/task.py 实现任务调度和进度
from pathlib import Path
from celery import Celery
from .register_models import register_models
from .preprocess import process_cell
from .logger import setup_logger, log_exception
from .utils import update_task_status
from .utils import redis_client, check_and_finalize_compare
import numpy as np
from .benchmark import align_and_benchmark, generate_chromatin_trajectory
import base64, os, json
logger = setup_logger('celery_tasks')
app = Celery(
    'genome3d', 
    broker='redis://localhost:6379/0', 
    backend='redis://localhost:6379/0'
)
# 模型运行函数注册
MODEL_RUNNERS = register_models('./models')
def get_available_models():
    return list(MODEL_RUNNERS.keys())

@app.task(bind=True)
def run_preprocess(self, datadir, name, cell_id, chrom, start, end, resolution, rep_type, output_dir, assembly='hg19'):
    """预处理单个细胞的数据"""
    task_id = self.request.id
    logger.info(f"开始预处理: dataset={name}, cell={cell_id}, chrom={chrom}")
    # 1. 生成目标文件路径
    
    def progress_callback(percent, message):
        self.update_state(state='PROGRESS', meta={'percent': percent, 'message': message})
    progress_callback(5, f"正在处理 {name}/{cell_id}/{chrom}...")
    cache_dir = os.path.join(output_dir, name, cell_id)# e.g. usr_data/uuid/processed_data/GM12878/01
    os.makedirs(cache_dir, exist_ok=True)
    # 根据 name 和 rep_type 构建输入目录路径
    # 目录结构为: datadir/{name}/{rep_type}/{cell_id}
    # e.g. data/GM12878/original/01 
    # 该文件夹下应只有一个3dg文件和一个hic文件
    input_dir = os.path.join(datadir, name, rep_type, cell_id)
    if not os.path.isdir(input_dir):
        return {
            'status': 'error',
            'message': f'输入目录不存在: {input_dir}'
        }
    try:
        progress_callback(30, "正在读取接触数据和坐标数据...")
        files = process_cell(
            input_dir=input_dir,
            output_dir=cache_dir, chrom=chrom,
            region_start=start, region_end=end,
            assembly=assembly,
            resolution=resolution, rep_type=rep_type,
        )
        progress_callback(100, f"处理完成，共生成 {len(files)} 个文件")
        logger.info(f"预处理完成，生成文件: {files}")
        update_task_status(self.request.id, 'SUCCESS')
        result = {
            'status': 'success',
            'true_coords_file': files[0],
            'hic_file':files[1],
            'files':files
        }
        # 更新任务元数据，加入文件路径
        redis_client.hset(f"task_meta:{self.request.id}", mapping={
            'hic_file': files[1],
            'true_coords_file': files[0]
        })
        return result
    except Exception as e:
        log_exception(logger, e, context=f"preprocess task_id={task_id}")
        self.update_state(
            state='FAILURE',
            meta={'exc_type': type(e).__name__, 'exc_message': str(e)}
        )
        update_task_status(self.request.id, 'FAILURE')
        return {'status': 'error', 'message': str(e)}
# ================= Celery 任务入口 =================
@app.task(bind=True)
def run_reconstruction(self, model_name: str, info: dict):
    """执行 3D 重建任务，调用注册的模型运行函数"""
    task_id = self.request.id
    logger.info(f"开始执行推理任务: model={model_name}, chr={info.get('chr_name')}")
    def progress_callback(percent, message):
        self.update_state(state='PROGRESS', meta={'percent': percent, 'message': message})

    if model_name not in MODEL_RUNNERS:
        msg = f"未知模型: {model_name}"
        logger.error(f"[{task_id}] {msg}")
        raise ValueError(f"未知模型: {model_name}. 可用模型: {list(MODEL_RUNNERS.keys())}")

    runner = MODEL_RUNNERS[model_name]
    try:
        progress_callback(0, f"开始执行 {model_name} 模型")
        result = runner(info, progress_callback)
        
        # 如果模型返回错误状态，记录日志
        if isinstance(result, dict) and result.get('status') == 'error':
            progress_callback(100, "任务失败, 请检查log日志")
            logger.error(f"[{task_id}] 模型返回错误: {result.get('message')}")
            update_task_status(self.request.id, 'FAILURE')
        else:
            progress_callback(100, "任务完成")
            logger.info(f"[{task_id}] 推理成功")
            update_task_status(self.request.id, 'SUCCESS')

            # ===== 自动评估 =====
            output_file = result.get('output_file')
            true_coords_file = info.get('true_coords_file')
            logger.info(f"进入自动评估：output:{output_file}, true:{true_coords_file}")
            if output_file and true_coords_file and os.path.exists(output_file) and os.path.exists(true_coords_file):
                try:
                    # 加载坐标
                    pred_coords = np.loadtxt(output_file)
                    true_coords = np.load(true_coords_file) if true_coords_file.endswith('.npy') else np.loadtxt(true_coords_file)
                    
                    # 对齐尺寸
                    n = min(len(pred_coords), len(true_coords))
                    pred_coords, true_coords = pred_coords[:n], true_coords[:n]

                    # 计算指标和生成图表
                    result, plot_2d, coverage_info= align_and_benchmark(pred_coords, true_coords)
                    plot_3d_buf = generate_chromatin_trajectory(pred_coords, true_coords, title=f"{model_name} vs True")
                    plot_3d_b64 = base64.b64encode(plot_3d_buf.getvalue()).decode()
                    # 构建评估结果
                    eval_result = {
                        'eval_status': result['eval_status'],
                        'metrics': result['metrics'],
                        'plot_2d': plot_2d,
                        'plot_3d': f"data:image/png;base64,{plot_3d_b64}",
                        'n_points': n,
                        'coverage': coverage_info
                    }
                    # 存入 Redis
                    redis_client.hset(f"task_meta:{self.request.id}", mapping={
                        'eval_result': json.dumps(eval_result),
                        'eval_status': 'success'  # 单独存储评估状态
                    })
                    logger.info(f"[{task_id}] 自动评估完成")
                except Exception as eval_e:
                    logger.error(f"[{task_id}] 自动评估失败: {eval_e}")
                    eval_error = {
                        'error': str(eval_e),
                        'metrics': None,
                        'plot_2d': None,
                        'plot_3d': None
                    }
                    redis_client.hset(f"task_meta:{task_id}", mapping={'eval_result': json.dumps(eval_error),'eval_status':'failed'})
            parent_task_id = info.get('parent_task_id')
            if parent_task_id:
                check_and_finalize_compare(parent_task_id)
        return result
    except Exception as e:
        log_exception(logger, e, context=f"task_id={task_id}")
        self.update_state(state='FAILURE',
                          meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        update_task_status(self.request.id, 'FAILURE')
        parent_task_id = info.get('parent_task_id')
        if parent_task_id:
            check_and_finalize_compare(parent_task_id)
        return {'status': 'error', 'message': str(e), 'type': type(e).__name__}