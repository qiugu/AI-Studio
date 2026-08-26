"""租户数据清理 Celery 任务。"""
from app.core.celery_app import celery_app
from app.core.database import sessionLocal
from app.services.admin import cascade_soft_delete_tenant


@celery_app.task(name="tenant_cleanup.cascade_delete", bind=True, max_retries=2)
def cascade_delete_tenant_task(self, tenant_id: str) -> None:
    """异步级联软删除租户业务数据（保留审计/计费数据）。"""
    db = sessionLocal()
    try:
        cascade_soft_delete_tenant(tenant_id, db)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
