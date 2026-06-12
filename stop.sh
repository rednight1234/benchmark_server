#!/bin/bash
echo "停止 3D Genome Web Service ..."

# 停止 Uvicorn
pkill -f "uvicorn api.main:app" && echo "Uvicorn 已停止" || echo "Uvicorn 未运行"

# 停止 Celery Worker
pkill -f "api.task worker" && echo "Celery Worker 已停止" || echo "Celery Worker 未运行"

# 停止 Redis（如果需要）
# redis-cli shutdown && echo "Redis 已停止" || echo "Redis 未运行"
echo "所有服务已停止。"