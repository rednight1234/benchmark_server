#!/bin/bash
# 启动 3D Genome Web Service (Redis + Celery Worker + FastAPI)

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=============================="
echo " 启动 3D Genome Web Service"
echo "=============================="

# 激活 conda 环境（根据你的环境名修改）
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate benchmark
fi

# 1. 启动 Redis（如果未运行）
if ! pgrep -x "redis-server" > /dev/null; then
    echo "[1/3] 启动 Redis ..."
    redis-server --daemonize yes --port 6379
else
    echo "[1/3] Redis 已在运行"
fi

# 2. 启动 Celery Worker
echo "[2/3] 启动 Celery Worker ..."
# 先杀掉旧的 worker，防止代码未更新
pkill -f "api.task worker" 2>/dev/null
sleep 1
# 更改concurrency以更改最大并发进程数量
celery -A api.task worker --loglevel=info --concurrency=16 --detach \
    --logfile="$PROJECT_DIR/celery_worker.log" --pidfile="$PROJECT_DIR/celery_worker.pid" 
echo "Celery Worker 已启动 (日志: celery_worker.log)"

# 3. 启动 FastAPI
echo "[3/3] 启动 FastAPI (Uvicorn) ..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload \
    --log-level info > "$PROJECT_DIR/uvicorn.log" 2>&1 &
echo "FastAPI 已启动 (访问 http://localhost:8000)"
echo ""
echo "所有服务启动完成。"