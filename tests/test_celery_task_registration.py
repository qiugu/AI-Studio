"""验证 Celery 知识库文档处理任务的注册。

历史问题：worker 以 `celery -A app.core.celery_app worker` 启动时，仅加载
`app.core.celery_app` 本身，不会自动导入定义任务的 `app.services.knowledge_processor`，
导致 `process_document_task` 未注册进任务表，文档上传后状态永远卡在 `pending`
（worker 收到消息报 `Received unregistered task` 并丢弃）。

修复方式：在 `celery_app.conf` 中声明 `include=["app.services.knowledge_processor"]`，
worker 启动时会导入该模块并注册任务。本测试覆盖该修复。
"""
from app.core.celery_app import celery_app


def test_task_module_declared_in_include():
    """`include` 配置必须包含任务模块，否则 worker 不会注册任务。"""
    include = celery_app.conf.get("include") or []
    assert "app.services.knowledge_processor" in include
    assert "app.services.tenant_cleanup" in include


def test_knowledge_task_registered_via_include():
    """模拟 worker 启动（导入 `include` 声明的模块）后，任务应已注册。"""
    # import_default_modules 是 worker 启动时的标准行为，会导入 include/imports 中的模块
    celery_app.loader.import_default_modules()
    assert "process_document_task" in celery_app.tasks


def test_knowledge_task_has_expected_name():
    """任务声明名应与上传服务中的 .delay(...) 调用一致。"""
    task = celery_app.tasks.get("process_document_task")
    assert task is not None
    assert task.name == "process_document_task"


def test_enterprise_delivery_settings_are_enabled():
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.broker_transport_options["confirm_publish"] is True


def test_tasks_use_declared_quorum_queues():
    routes = celery_app.conf.task_routes
    assert routes["process_document_task"]["queue"] == "document.ingest"
    assert routes["tenant_cleanup.cascade_delete"]["queue"] == "tenant.cleanup"

    queues = {queue.name: queue for queue in celery_app.conf.task_queues}
    assert queues["document.ingest"].queue_arguments["x-queue-type"] == "quorum"
    assert queues["tenant.cleanup"].queue_arguments["x-queue-type"] == "quorum"
