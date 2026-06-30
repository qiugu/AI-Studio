from celery import Celery

from app.core.config import config

print(f"broker: {config.celery_broker_url}")

celery_app = Celery(
    "knowledge_processor",
    broker=config.celery_broker_url,
    backend=config.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
