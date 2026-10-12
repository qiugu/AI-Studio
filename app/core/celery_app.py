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
from kombu import Exchange, Queue

from app.core.config import config

TASK_EXCHANGE = Exchange("ai-studio.tasks", type="topic", durable=True)
QUORUM_QUEUE_ARGUMENTS = {"x-queue-type": "quorum"}
TASK_QUEUES = (
    Queue(
        "default",
        exchange=TASK_EXCHANGE,
        routing_key="default",
        durable=True,
        queue_arguments=QUORUM_QUEUE_ARGUMENTS,
    ),
    Queue(
        "document.ingest",
        exchange=TASK_EXCHANGE,
        routing_key="document.ingest",
        durable=True,
        queue_arguments=QUORUM_QUEUE_ARGUMENTS,
    ),
    Queue(
        "tenant.cleanup",
        exchange=TASK_EXCHANGE,
        routing_key="tenant.cleanup",
        durable=True,
        queue_arguments=QUORUM_QUEUE_ARGUMENTS,
    ),
)

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
    # 业务状态由 MySQL 的领域模型维护，不在 Broker 旁复制一套短期结果状态。
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_track_started=False,
    # 至少一次投递：任务成功后才 ack；Worker 异常退出时由 Broker 重新投递。
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_delivery_mode=2,
    worker_prefetch_multiplier=1,
    # RabbitMQ quorum queue + publisher confirms。
    task_queues=TASK_QUEUES,
    task_default_queue="default",
    task_default_exchange="ai-studio.tasks",
    task_default_exchange_type="topic",
    task_default_routing_key="default",
    task_create_missing_queues=False,
    task_routes={
        "process_document_task": {
            "queue": "document.ingest",
            "routing_key": "document.ingest",
        },
        "tenant_cleanup.cascade_delete": {
            "queue": "tenant.cleanup",
            "routing_key": "tenant.cleanup",
        },
    },
    broker_transport_options={"confirm_publish": True},
    broker_heartbeat=30,
    broker_connection_retry_on_startup=True,
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 5,
        "interval_start": 0,
        "interval_step": 1,
        "interval_max": 5,
    },
    worker_detect_quorum_queues=True,
    worker_soft_shutdown_timeout=30.0,
    worker_enable_soft_shutdown_on_idle=True,
    # Worker 启动时必须导入所有任务模块，否则消息会以 unregistered 被丢弃。
    include=[
        "app.services.knowledge_processor",
        "app.services.tenant_cleanup",
    ],
)
