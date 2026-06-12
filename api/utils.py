# api/utils.py
import redis
import json
from datetime import datetime
from .benchmark import generate_comparison_charts
# 连接 Redis（使用 db=1 避免与 Celery 冲突）
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)

def save_task_meta(task_id, username, task_type, model, params, status='PENDING'):
    """保存任务元数据到 Redis"""
    meta = {
        'task_id': task_id,
        'username': username,
        'task_type': task_type,
        'model': model,
        'params': json.dumps(params),
        'status': status,
        'created_at': datetime.now().isoformat()
    }
    redis_client.hset(f"task_meta:{task_id}", mapping=meta)
    redis_client.sadd("task_ids", task_id)

def update_task_status(task_id, status):
    """更新任务状态"""
    redis_client.hset(f"task_meta:{task_id}", 'status', status)

def get_all_tasks(username=None, status=None):
    """获取所有顶层任务（排除子任务），支持按用户和状态筛选"""
    task_ids = redis_client.smembers("task_ids")
    all_tasks = []
    child_task_ids = set()

    for tid in task_ids:
        meta = redis_client.hgetall(f"task_meta:{tid}")
        if not meta:
            continue
        task = dict(meta)

        all_tasks.append(task)

        # 收集对比任务的子任务 ID
        if task.get('task_type') == 'compare':
            try:
                child_ids = json.loads(task.get('child_tasks', '[]'))
                child_task_ids.update(child_ids)
            except:
                pass

    # 过滤掉子任务，只保留顶层任务
    top_level = [t for t in all_tasks if t['task_id'] not in child_task_ids]

    # 筛选
    if username:
        top_level = [t for t in top_level if t.get('username') == username]
    if status:
        top_level = [t for t in top_level if t.get('status') == status]

    # 按创建时间倒序
    top_level.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return top_level

def delete_task_meta(task_id):
    """删除任务元数据"""
    redis_client.delete(f"task_meta:{task_id}")
    redis_client.srem("task_ids", task_id)

# 获取任务的信息
def get_detail(task_id:str):
    return redis_client.hgetall(f"task_meta:{task_id}")
def set_task_process_pid(task_id, pid):
    """记录任务对应的工作进程 PID"""
    redis_client.set(f"task_process:{task_id}", pid)
def get_and_clear_task_process_pid(task_id):
    """获取并清除任务的进程 PID"""
    pid = redis_client.get(f"task_process:{task_id}")
    if pid:
        redis_client.delete(f"task_process:{task_id}")
    return pid

def get_task_meta(task_id):
    """获取单个任务的完整元数据字典，不存在则返回 None"""
    meta = redis_client.hgetall(f"task_meta:{task_id}")
    if not meta:
        return None
    return dict(meta)
def update_compare_child_tasks(parent_task_id, child_task_ids):
    """更新对比任务的子任务ID列表"""
    redis_client.hset(f"task_meta:{parent_task_id}", "child_tasks", json.dumps(child_task_ids))
def check_and_finalize_compare(parent_task_id):
    """
    检查父任务的所有子任务是否完成，如果完成则汇总评估结果。
    """
    meta = get_task_meta(parent_task_id)
    if not meta or meta.get('task_type') != 'compare':
        return

    child_ids = json.loads(meta.get('child_tasks', '[]'))
    if not child_ids:
        return

    all_done = True
    has_error = False
    eval_results = {}
    failed_models = []

    for child_id in child_ids:
        child_meta = get_task_meta(child_id)
        if not child_meta:
            continue
        status = child_meta.get('status')
        if status not in ('SUCCESS', 'FAILURE'):
            all_done = False
            break
        if status == 'FAILURE':
            has_error = True
        # 收集评估结果
        eval_str = child_meta.get('eval_result')
        if eval_str and child_meta.get('eval_status')=='success':
            try:
                eval_data = json.loads(eval_str)
                if 'error' not in eval_data and eval_data.get('metrics') is not None:
                    eval_results[child_meta.get('model', 'unknown')] = eval_data
                else:
                    # 记录该模型评估失败
                    eval_results[child_meta.get('model', 'unknown')] = {'error': eval_data.get('error', '评估失败')}
            except:
                failed_models.append(child_meta.get('model','unknown'))
                has_error = True
                pass

    if not all_done:
        return

    # 更新父任务状态
    parent_status = 'SUCCESS' if not has_error else 'PARTIAL_FAILURE'
    update_task_status(parent_task_id, parent_status)

    # 生成对比图表
    if eval_results:
        comparison_data = generate_comparison_charts(eval_results) if eval_results else {}
        comparison_data['failed_models'] = failed_models
        
        redis_client.hset(f"task_meta:{parent_task_id}", mapping={
            'eval_result': json.dumps(comparison_data),
            'eval_status': 'success' if eval_results else 'partial_failure',
            'status': parent_status
        })
def save_compare_task(task_id, username, models, params, child_task_ids, status='PENDING'):
    """保存对比任务元数据"""
    meta = {
        'task_id': task_id,
        'username': username,
        'task_type': 'compare',
        'model': ','.join(models),
        'params': json.dumps(params),
        'status': status,
        'child_tasks': json.dumps(child_task_ids),
        'created_at': datetime.now().isoformat()
    }
    redis_client.hset(f"task_meta:{task_id}", mapping=meta)
    redis_client.sadd("task_ids", task_id)