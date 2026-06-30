#!/bin/bash
# 后端服务启动脚本

cd /Volumes/Project/qiugu/AI-Studio/backend

# 激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
fi

# 启动服务
python -m uvicorn app.main:app --reload --port 8000
