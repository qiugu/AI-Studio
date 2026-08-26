# AI-Studio 后端镜像（API 服务 / Celery Worker 共用）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 安装 curl（用于容器健康检查）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先拷贝依赖清单，充分利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码（含 Alembic 迁移）
COPY . .

EXPOSE 8000

# 启动前自动执行数据库迁移，随后启动 API 服务
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
