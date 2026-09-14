# 修复 Celery prefork 子进程加载 torch/sentence-transformers 时的 SIGABRT。
#
# 现象：Worker 以默认 prefork 池运行，fork 出的子进程在执行 process_document_task
# 首次 import sentence-transformers（依赖 torch CPU）时崩溃，日志仅见
# "WorkerLostError: signal 6 (SIGABRT)"，无 Python 堆栈。根因是 fork 后子进程内
# OpenMP 运行时（libiomp5）被重复初始化，触发 "OMP: Error #15: ... libiomp5 already
# initialized"，进程被 abort。macOS 上 Accelerate + fork 不兼容会进一步放大该问题。
#
# 必须在任何第三方库 import 之前设置以下环境变量，使其对本机与 Docker 启动均生效，
# 且对 openai/azure 等非 torch provider 无副作用：
#   KMP_DUPLICATE_LIB_OK=TRUE  容忍重复 OpenMP 运行时，避免触发 abort
#   OMP_NUM_THREADS=1          限制每进程 OpenMP 线程，规避 fork 后线程池损坏与资源争用
#   MKL_NUM_THREADS=1 / OPENBLAS_NUM_THREADS=1  一并限制其他 BLAS 后端线程
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from celery import Celery

from app.core.config import config

celery_app = Celery(
    "knowledge_processor",
    broker=config.get_celery_broker_url(),
    backend=config.get_celery_result_backend(),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # 确保 worker 启动时导入任务模块，将 process_document_task 注册进任务表。
    # 否则 worker 以 `celery -A app.core.celery_app worker` 启动后只包含 celery_app 本身，
    # 不会加载 app.services.knowledge_processor，导致任务以 unregistered 被丢弃，文档状态卡在 pending。
    include=["app.services.knowledge_processor"],
)
