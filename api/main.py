# ./api/main.py 实现基本功能
import shutil, os, uuid, math, json, time, signal, base64
import numpy as np
from fastapi import FastAPI, UploadFile, Request, Query, File, Form, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
from celery.result import AsyncResult

from .task import run_reconstruction, run_preprocess, get_available_models
from .task import app as celery_app
from .logger import setup_logger, log_exception
from .data_utils import analyze_pairs_file
from .benchmark import align_and_benchmark,generate_chromatin_trajectory
from .utils import save_task_meta, get_all_tasks, delete_task_meta, update_task_status, get_detail, save_compare_task,get_and_clear_task_process_pid, get_task_meta, update_compare_child_tasks
from .preprocess import load_dipc_coords

from pathlib import Path

logger = setup_logger('main')
app = FastAPI()

# 目录配置
DATA_DIR = Path("usr_data")                 # 用户上传数据临时存储
RESULTS_DIR = Path("usr_results")           # 推理结果存储
SOURCE_DATA = Path("data")                  # 原始数据根目录
PROCESSED_DIR = Path("processed_data")      # 预处理输出根目录

os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


# ============================================================
# 中间件
# ============================================================

# 全局异常捕获中间件
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    """全局异常捕获中间件"""
    try:
        return await call_next(request)
    except Exception as e:
        # 记录完整的异常信息
        log_exception(logger, e, context=f"{request.method} {request.url.path}")
        # 返回统一的错误响应
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": str(e),
                "type": type(e).__name__
            }
        )
# 记录每个请求的处理时间
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """请求日志中间件"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {response.status_code} [{process_time:.3f}s]")
    return response

# ============================================================
# 数据集相关 API
# ============================================================
# 列出所有数据集名称
@app.get("/api/datasets")
async def list_datasets():
    """
    列出 data/ 下所有数据集名称。
    返回: { "datasets": ["GM12878", "scHiC_mESC"] }
    """
    if not SOURCE_DATA.is_dir():
        return {"datasets": []}
    datasets = [d.name for d in SOURCE_DATA.iterdir() if d.is_dir()]
    return {"datasets": sorted(datasets)}

# 获取数据集详情
@app.get("/api/datasets/{dataset_name}")
async def get_dataset_info(dataset_name: str):
    """
    获取某个数据集的详细信息。
    返回: { "name": ..., "rep_types": [...], "cells": [...] }
    """
    dataset_dir = SOURCE_DATA / dataset_name
    if not dataset_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"数据集 '{dataset_name}' 不存在")

    # 读取 dataset_info.json
    info_file = dataset_dir / "dataset_info.json"
    info = {}
    if info_file.is_file():
        with open(info_file, 'r') as f:
            info = json.load(f)

    # 动态扫描：重复类型
    rep_types = sorted([d.name for d in dataset_dir.iterdir()
                        if d.is_dir() and not d.name.startswith('.') and not d.name.endswith('.json')])

    # 扫描每个重复类型下的细胞ID
    cells_by_rep = {}
    for rep in rep_types:
        rep_dir = dataset_dir / rep
        cells = [d.name for d in rep_dir.iterdir() if d.is_dir()]
        cells_by_rep[rep] = sorted(cells)

    return {
        "name": dataset_name,
        "description": info.get("description", ""),
        "species": info.get("species", ""),
        "assembly": info.get("assembly", ""),
        "rep_types": rep_types,
        "cells": cells_by_rep
    }

# 获取某重复类型下细胞列表
@app.get("/api/datasets/{dataset_name}/{rep_type}")
async def get_cell_list(dataset_name: str, rep_type: str):
    """
    获取某个数据集某个重复类型下的所有细胞ID。
    返回: { "cells": ["01", "02", ...] }
    """
    rep_dir = SOURCE_DATA / dataset_name / rep_type
    if not rep_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"类型 '{rep_type}' 在 '{dataset_name}' 中不存在")
    cells = sorted([d.name for d in rep_dir.iterdir() if d.is_dir()])
    return {"dataset_name": dataset_name, "rep_type": rep_type, "cells": cells}

# 获取某细胞下的文件列表
@app.get("/api/datasets/{dataset_name}/{rep_type}/{cell_id}/files")
async def get_cell_files(dataset_name: str, rep_type: str, cell_id: str):
    """获取某细胞下的文件列表（().txt, .3dg, .pdb)→ { files: [...] }"""
    cell_dir = SOURCE_DATA / dataset_name / rep_type / cell_id
    if not cell_dir.is_dir():
        logger.info(f"获取{cell_dir}失败")
        raise HTTPException(status_code=404, detail="细胞目录不存在")
    files = []
    for f in sorted(cell_dir.iterdir()):
        if f.is_file() and (f.name.endswith('.txt') or f.name.endswith('.3dg') or f.name.endswith('.pdb')):
            file_type = 'hic' if (f.name.endswith('.con.txt') or f.name.endswith('pairs.txt')) else 'pos'
            # 计算行数
            with open(f, 'r') as fh:
                lines = fh.readlines()
                line_count = len(lines)
                show=min(line_count,3)
                preview = lines[:show]  # 前3行
            files.append({
                "filename": f.name,
                "path": str(f.absolute()),
                "size": f.stat().st_size,
                "line_count": line_count,
                "preview": preview,
                "type": file_type
            })
    return {"cell_id": cell_id, "files": files}

# ============================================================
# 预处理相关 API
# ============================================================
# 提交预处理任务
@app.post("/preprocess")
async def start_preprocess(
    datadir: str = Form(...),
    name: str = Form(...),           # 数据集名称，如 'Dip-C_GM12878'
    cell_id: str = Form(...),        # 细胞ID，如 '01'
    chrom: str = Form("chr19"),
    start: int = Form(0),
    end: int = Form(-1),             # -1 表示全长
    resolution: int = Form(20000),
    rep_type: str = Form("original"),
    username: str = Form("anonymous")
):
    """提交预处理任务 → { task_id, progress_url, result_url }"""
    task_id = str(uuid.uuid4())
    output_dir = DATA_DIR / task_id / PROCESSED_DIR
    output_dir.mkdir(parents=True,exist_ok=True)
    logger.info(f"收到预处理任务: task_id={task_id}, dataset={name}, cell_id={cell_id}, chrom={chrom}, {start}-{end}, {resolution}bp, {rep_type}")
    logger.info(f"预处理任务已提交: task_id={task_id}")
    celery_task = run_preprocess.delay(
        datadir=datadir,
        name=name,
        cell_id=cell_id,
        chrom=chrom,
        start=start,
        end=end,
        resolution=resolution,
        rep_type=rep_type,
        output_dir=str(output_dir)
    )
    save_task_meta(
        task_id=celery_task.id, username=username, task_type='preprocess',
        model='preprocess', params={'chrom': chrom, 'resolution': resolution}, status='PENDING'
    )
    return {
        "task_id": celery_task.id,
        "progress_url": f"/preprocess/{celery_task.id}/progress",
        "result_url": f"/preprocess/{celery_task.id}/result"
    }

#查询预处理进度
@app.get("/preprocess/{task_id}/progress")
async def preprocess_progress(task_id: str):
    """查询预处理进度 → { status, percent, message }"""
    task = AsyncResult(task_id, app=celery_app)
    try:
        state = task.state
    except Exception:  
        return {"status": "FAILURE", "error": "Task state could not be retrieved"}

    if state == 'PENDING':
        return {"status": "PENDING", "percent": 0}
    elif state == 'PROGRESS':
        info = task.info or {}
        return {"status": "PROGRESS", "percent": info.get('percent', 0), "message": info.get('message', '')}
    elif state == 'SUCCESS':
        result = task.result
        response = {"status": "SUCCESS", "percent": 100, "message": "Done!"}
        if isinstance(result, dict) and 'output_file' in result:
            response['output_file'] = result['output_file']
        return response
    elif state == 'FAILURE':
        # 尝试从 task.info 获取错误信息，如果失败则返回通用信息
        try:
            error_info = task.info
            error_msg = error_info.get('exc_message', str(error_info)) if isinstance(error_info, dict) else str(error_info)
        except Exception:
            error_msg = "Unknown error"
        return {"status": "FAILURE", "error": error_msg}
    else:
        return {"status": state}

#获取预处理的文件列表
@app.get("/preprocess/{task_id}/result")
async def preprocess_result(task_id: str):
    """获取预处理结果文件列表 → { files: [...] }"""
    task = AsyncResult(task_id, app=celery_app)
    if task.state != 'SUCCESS':
        return JSONResponse(status_code=404, content={"error": "Task not completed"})
    result = task.result
    return {"files": result.get('files', [])}


# ============================================================
# 任务管理 API
# ============================================================
# 获取任务列表
@app.get("/api/tasks")
async def list_tasks(username: str = None, status: str = None):
    """获取任务列表，支持筛选 → { tasks: [...] }"""
    tasks = get_all_tasks()
    if username:
        tasks = [t for t in tasks if t.get('username') == username]
    if status:
        tasks = [t for t in tasks if t.get('status') == status]
    return {"tasks": tasks}

# 获取单个任务信息
@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """获取单个任务详情 → 包含 eval_result、文件信息等"""
    meta = get_detail(task_id=task_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v 
            for k, v in meta.items()}
    # 补充 Celery 结果中的 output_file 信息
    result_info = {}
    if task.get('task_type') == 'reconstruction' and task.get('status') == 'SUCCESS':
        # 从 Celery 结果中获取 output_file
        from celery.result import AsyncResult
        celery_result = AsyncResult(task_id, app=celery_app)
        if celery_result.ready() and celery_result.successful():
            result = celery_result.result
            if isinstance(result, dict) and 'output_file' in result:
                output_path = result['output_file']
                if os.path.exists(output_path):
                    result_info = {
                        "output_file": output_path,
                        "size": os.path.getsize(output_path),
                        "filename": os.path.basename(output_path)
                    }
    task['result_info'] = result_info
    # 将 eval_result 从 JSON 字符串转回对象
    if 'eval_result' in task:
        task['eval_result'] = json.loads(task['eval_result'])
    return task


#获取子任务信息 
@app.get("/api/tasks/{task_id}/children")
async def get_task_children(task_id: str):
    """获取对比任务的子任务状态列表"""
    meta = get_task_meta(task_id)
    if not meta or meta.get('task_type') != 'compare':
        return JSONResponse(status_code=400, content={"error": "任务不存在或不是对比任务"})
    
    child_ids = json.loads(meta.get('child_tasks', '[]'))
    children = []
    for child_id in child_ids:
        child_meta = get_task_meta(child_id)
        if child_meta:
            # 获取进度（从 Celery 任务状态中）
            percent = 0
            message = ""
            from celery.result import AsyncResult
            task = AsyncResult(child_id, app=celery_app)
            if task.state == 'PROGRESS':
                info = task.info or {}
                percent = info.get('percent', 0)
                message = info.get('message', '')
            elif task.state == 'SUCCESS':
                percent = 100
                message = "完成"
            elif task.state == 'FAILURE':
                percent = 100
                message = "失败"
            
            children.append({
                "task_id": child_id,
                "model": child_meta.get('model', 'unknown'),
                "status": child_meta.get('status', task.state),
                "percent": percent,
                "message": message
            })
    return {"children": children}

# 查询推理任务进度
@app.get("/api/task/{task_id}/progress")
async def get_progress(task_id: str):
    # 1. 尝试从 Redis 获取任务元数据
    meta = get_task_meta(task_id)
    if not meta:
        return {"status": "UNKNOWN", "error": "任务不存在"}
    
    task_type = meta.get('task_type')
    status = meta.get('status', 'PENDING')
    
    # 2. 如果是父任务（compare），计算整体进度
    if task_type == 'compare':
        child_ids = json.loads(meta.get('child_tasks', '[]'))
        if not child_ids:
            return {"status": status, "percent": 0, "message": "等待子任务"}
        completed = 0
        for cid in child_ids:
            c_meta = get_task_meta(cid)
            if c_meta and c_meta.get('status') in ('SUCCESS', 'FAILURE'):
                completed += 1
        percent = int(completed / len(child_ids) * 100) if child_ids else 0
        return {
            "status": status if status != 'PENDING' else 'PROGRESS',
            "percent": percent,
            "message": f"{completed}/{len(child_ids)} 个子任务完成",
            "cids": child_ids
        }
    
    # 3. 普通任务：从 Celery 获取进度（原有逻辑）
    task = AsyncResult(task_id, app=celery_app)
    if task.state == 'PENDING':
        return {"status": "PENDING", "percent": 0, "message": "等待中..."}
    elif task.state == 'PROGRESS':
        info = task.info or {}
        return {"status": "PROGRESS", "percent": info.get('percent', 0), "message": info.get('message', '')}
    elif task.state == 'SUCCESS':
        result = task.result
        response = {"status": "SUCCESS", "percent": 100, "message": "完成"}
        if isinstance(result, dict) and 'output_file' in result:
            response['output_file'] = result['output_file']
        return response
    elif task.state == 'FAILURE':
        return {"status": "FAILURE", "error": str(task.info)}
    else:
        return {"status": task.state}


# 删除任务
@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务（撤销 Celery 任务并清除元数据）"""
    # 从 Redis 获取该任务可能记录的子进程 PID
    process_pid = get_and_clear_task_process_pid(task_id)
    if process_pid:
        try:
            os.kill(int(process_pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass
    celery_app.control.revoke(task_id, terminate=True)
    delete_task_meta(task_id)
    dirs_to_delete = [
        DATA_DIR / task_id,       # 预处理数据 usr_data/{task_id}
        RESULTS_DIR / task_id,    # 推理结果 usr_results/{task_id}
    ]
    for d in dirs_to_delete:
        if d.exists() and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    eval_dir = Path("usr_data/evaluations")
    if eval_dir.exists():
        for f in eval_dir.iterdir():
            if f.name.startswith(task_id):
                f.unlink(missing_ok=True)
    return {"status": "deleted"}

# 撤销 Celery任务
@app.post("/task/{task_id}/revoke")
async def revoke_task(task_id: str):
    """撤销指定的 Celery 任务（推理或预处理）"""
    celery_app.control.revoke(task_id, terminate=True)
    return {"status": "revoked", "task_id": task_id}

# 获取模型列表
@app.get("/api/models")
async def list_models():
    return {"models": get_available_models()}
# ============================================================
# 推理与评估 API
# ============================================================
# 提交重建任务
@app.post("/reconstruct")
async def submit_task(
    file: UploadFile = File(None),          
    model: str = Form(...), resolution: int = Form(...),
    chr_name: str = Form("chr19"), assembly: str = Form("hg19"), 
    input_file_path: str = Form(None),  true_coords_file: str =Form(None),
    username: str = Form("anonymous")
):
    """提交重建任务 → { task_id, progress_url, result_url, stats }"""
    logger.info(f"收到推理任务: model={model}, chr={chr_name}, resolution={resolution}")
    stats = None
    task_id = str(uuid.uuid4())
    if input_file_path:
        input_path = input_file_path
        # 验证文件存在
        if not os.path.exists(input_path):
            return JSONResponse(status_code=400, content={"error": f"文件不存在: {input_path}"})
        work_dir = RESULTS_DIR / task_id
        os.makedirs(work_dir, exist_ok=True)
        stats = analyze_pairs_file(input_path)
    elif file:
        # 上传文件
        input_path = f"usr_data/uploads/{task_id}_{file.filename}"
        with open(input_path, "wb") as f:
            f.write(await file.read())
        # 验证格式
        stats = analyze_pairs_file(input_path)
        if not stats['format_ok']:
            return JSONResponse(status_code=400, content={"error": stats['error']})
    else:
        return JSONResponse(status_code=400, content={"error": "No file provided"})

    # 构建 info 字典
    info = {
        'chr_name': chr_name,
        'assembly': assembly,
        'input_file': input_path,
        'resolution': resolution,
        'work_dir': str(work_dir.absolute()),
        'true_coords_file':true_coords_file
    }

    # 提交 Celery 任务
    run_reconstruction.apply_async(args=[model,info],task_id=task_id)
    save_task_meta(
        task_id=task_id,
        username=username,  # 需要从请求中获取，目前暂时用 'anonymous'，后续加上登录
        task_type='reconstruction',
        model=model,
        params={'chr_name': chr_name, 'resolution': resolution, 'assembly': assembly},
        status='PENDING'
    )
    logger.info(f"任务已提交: task_id={task_id}")
    response_data = {
        "task_id": task_id,
        "progress_url": f"/api/task/{task_id}/progress",
        "result_url": f"/api/task/{task_id}/result",
        "stats": stats
    }
    return response_data

# 提交多模型对比任务
@app.post("/api/benchmark/compare")
async def submit_compare_task(
    input_file_path: str = Form(...),
    true_coords_file: str = Form(...),
    models: str = Form(...),  # 模型列表
    resolution: int = Form(...),
    chr_name: str = Form("chr19"),
    assembly: str = Form("hg19"),
    username: str = Form("anonymous")
):
    """提交多模型对比任务"""
    models_list = [m.strip() for m in models.split(',') if m.strip()]
    if len(models_list) < 2:
        return JSONResponse(status_code=400, content={"error": "至少选择两个模型进行对比"})
    if not os.path.exists(input_file_path):
        return JSONResponse(status_code=400, content={"error": f"输入文件不存在: {input_file_path}"})
    if not os.path.exists(true_coords_file):
        return JSONResponse(status_code=400, content={"error": f"真实坐标文件不存在: {true_coords_file}"})

    # 创建父任务
    parent_task_id = str(uuid.uuid4())
    child_task_ids = []
    save_compare_task(
        task_id=parent_task_id,
        username=username,
        models=models_list,
        params={'chr_name': chr_name, 'resolution': resolution, 'assembly': assembly},
        child_task_ids=child_task_ids,
        status='PENDING'
    )
    for model_name in models_list:
        task_id = str(uuid.uuid4())
        work_dir = RESULTS_DIR / task_id
        os.makedirs(work_dir, exist_ok=True)

        info = {
            'model_name': model_name,
            'chr_name': chr_name,
            'assembly': assembly,
            'input_file': input_file_path,
            'resolution': resolution,
            'work_dir': str(work_dir.absolute()),
            'true_coords_file': true_coords_file,
            'parent_task_id': parent_task_id
        }
        # 提交子任务（使用 apply_async 可以自定义 task_id）
        run_reconstruction.apply_async(args=[model_name, info], task_id=task_id)
        child_task_ids.append(task_id)

        # 保存子任务元数据
        save_task_meta(
            task_id=task_id, username=username, task_type='reconstruction',
            model=model_name, params={'chr_name': chr_name, 'resolution': resolution, 'assembly': assembly},
            status='PENDING'
        )
    update_compare_child_tasks(parent_task_id, child_task_ids)
    
    return {
    "task_id": parent_task_id,
    "progress_url": f"/api/task/{parent_task_id}/progress",
    "result_url": f"/api/task/{parent_task_id}/result"
}

# 下载重建结果文件
@app.get("/api/task/{celery_task_id}/result")
async def get_result(celery_task_id: str):
    """下载重建结果文件"""
    task = AsyncResult(celery_task_id, app=celery_app)
    if task.state != 'SUCCESS':
        return JSONResponse(status_code=404, content={"error": "Task not completed yet"})
    
    result = task.result
    output_file = result.get('output_file')
    if not output_file or not os.path.exists(output_file):
        return JSONResponse(status_code=404, content={"error": "Result file not found"})
    return FileResponse(output_file, filename=os.path.basename(output_file))

# 计算重建结果与真实坐标的指标 + 2D 对比图
@app.get("/api/evaluate")
async def evaluate(
    recon_file: str = Query(...),
    true_coords_file: str = Query(...)
):
    """[保留] 计算重建结果与真实坐标的指标 + 2D 对比图 → { metrics, plot }"""
    if not os.path.exists(recon_file) or not os.path.exists(true_coords_file):
        raise HTTPException(status_code=400, detail="文件不存在")

    try:
        # 加载重建坐标（txt 格式：每行 x y z）
        recon_coords = np.loadtxt(recon_file, dtype=np.float64)
        # 加载真实坐标（npy 格式）
        true_coords = np.load(true_coords_file)
        # 对齐尺寸
        n = min(len(recon_coords), len(true_coords))
        recon_coords = recon_coords[:n]
        true_coords = true_coords[:n]
        metrics, plot_base64, coverage_info = align_and_benchmark(recon_coords, true_coords)
        if isinstance(metrics, dict) and 'error' in metrics:
            return JSONResponse(status_code=400, content=metrics)
        return {'metrics': metrics['metrics'], 'plot': plot_base64, 'coverage': coverage_info}
    except Exception as e:
        log_exception(logger, e, context=f"evaluate - recon={recon_file}, true={true_coords_file}")
        return JSONResponse(status_code=500, content={'error': str(e)})

# 生成 3D 染色质轨迹图
@app.get("/visualize")
async def visualize(
    recon_file: str = Query(...),
    true_coords_file: str = Query(None)
):
    """生成 3D 染色质轨迹图 → PNG 图片"""
    if not os.path.exists(recon_file):
        raise HTTPException(status_code=400, detail="重建坐标文件不存在")
    try:
        recon_coords = np.loadtxt(recon_file, dtype=np.float64)
        if true_coords_file:
            if not os.path.exists(true_coords_file):
                raise HTTPException(status_code=400, detail="真实坐标文件不存在")
            true_coords = np.load(true_coords_file)
            n = min(len(recon_coords), len(true_coords))
            recon_coords, true_coords = recon_coords[:n], true_coords[:n]
        else:
            true_coords = None
        img_buf = generate_chromatin_trajectory(recon_coords, true_coords)
        return Response(content=img_buf.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 上传预测文件，指定细胞参数，自动提取真实坐标并评估
@app.post("/api/benchmark/evaluate")
async def evaluate_upload(
    pred_file: UploadFile = File(...),
    dataset: str = Form(...),
    rep_type: str = Form(...),
    cell_id: str = Form(...),
    chrom: str = Form(...),
    start: int = Form(0),
    end: int = Form(-1),
    resolution: int = Form(20000)
):
    """[上传评估] 上传预测文件，指定细胞参数，自动提取真实坐标并评估 → { metrics, plot_2d, plot_3d }"""
    # 找到 .3dg.txt 文件
    cell_dir = SOURCE_DATA / dataset / rep_type / cell_id
    if not cell_dir.is_dir():
        raise HTTPException(status_code=404, detail="细胞目录不存在")
    dipc_files = list(cell_dir.glob("*.3dg.txt"))
    if not dipc_files:
        raise HTTPException(status_code=400, detail="未找到 .3dg.txt 文件")
    dipc_file = str(dipc_files[0]) 
    # 提取真实坐标
    true_coords = load_dipc_coords(dipc_file, chrom, start, end, resolution)
    if true_coords is None or len(true_coords) == 0:
        raise HTTPException(status_code=400, detail="未能提取到真实坐标，请检查参数")
    # 保存上传的预测文件
    eval_dir = Path("usr_data/evaluations")
    eval_dir.mkdir(parents=True, exist_ok=True)
    pred_path = eval_dir / f"{uuid.uuid4()}_{pred_file.filename}"
    with open(pred_path, "wb") as f:
        f.write(await pred_file.read())
    try:
        # 加载预测坐标
        if pred_path.suffix == '.npy':
            pred_coords = np.load(pred_path)
        else:
            pred_coords = np.loadtxt(pred_path)
        logger.info(f"上传文件已读取, 形状为{pred_coords.shape}")
        # 对齐尺寸
        n = min(len(pred_coords), len(true_coords))
        pred_coords = pred_coords[:n]
        true_coords = true_coords[:n]
        if (pred_coords.shape[0]!=true_coords.shape[0]):
            logger.info(f"警告: 上传数据形状与目标形状不匹配: {pred_coords.shape}-{true_coords.shape}")
            return JSONResponse(status_code=500, content={'error': "上传数据形状与目标形状不匹配"})
        # 计算指标
        metrics, plot_2d, coverage_info = align_and_benchmark(pred_coords, true_coords)
        # 生成3D结构图
        plot_3d_buf = generate_chromatin_trajectory(pred_coords, true_coords, title=f"Upload vs True ({chrom})")
        # 将图片转base64
        plot_3d_b64 = base64.b64encode(plot_3d_buf.getvalue()).decode('utf-8')
        return {
            "eval_status": metrics['eval_status'],
            "metrics": metrics['metrics'],
            "plot_2d": plot_2d,
            "plot_3d": f"data:image/png;base64,{plot_3d_b64}",
            "n_points": n,
            "coverage": coverage_info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 清理上传的临时文件
        try:
            os.remove(pred_path)
        except:
            pass

# ============================================================
# 文件下载
# ============================================================

# 通过路径下载文件
@app.get("/api/files/download")
async def download_file(path: str = Query(...)):
    """下载指定路径的文件"""
    file_path = Path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(file_path, filename=file_path.name, media_type='application/octet-stream')

# ============================================================
# 前端页面路由
# ============================================================

emplates = Jinja2Templates(directory="frontend/templates")
@app.get("/")
async def base_page(request: Request):
    """base页面"""
    return templates.TemplateResponse("base.html", {"request": request})

@app.get("/tasks")
async def tasks_page(request: Request):
    """任务工作台页面"""
    return templates.TemplateResponse("tasks.html", {"request": request})

@app.get("/tasks/{task_id}")
async def task_detail_page(request: Request, task_id: str):
    """任务详情页面"""
    return templates.TemplateResponse("task_detail.html", {"request": request, "task_id": task_id})

@app.get("/new-task", response_class=HTMLResponse)
async def new_task_page(request: Request):
    """创建任务页面"""
    return templates.TemplateResponse("new_task.html", {"request": request})

@app.get("/datasets", response_class=HTMLResponse)
async def datasets_page(request: Request):
    """查看数据集页面"""
    return templates.TemplateResponse("datasets.html", {"request": request})

@app.get("/evaluate", response_class=HTMLResponse)
async def evaluate_page(request: Request):
    """评估页面"""
    return templates.TemplateResponse("evaluate.html", {"request": request})

# 挂载静态资源目录（CSS、JS、图片等）
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# 配置 Jinja2 模板引擎
templates = Jinja2Templates(directory="frontend/templates")