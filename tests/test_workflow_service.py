"""Workflow CRUD and graph replacement regression tests."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
import uuid

import pytest
from pydantic import ValidationError

from app.api import workflow as workflow_api
from app.core.exceptions import ValidationException
from app.schemas.workflow import WorkflowUpdate
from app.services.workflow import WorkflowService
from app.services.workflow_engine import WorkflowEngine


def _workflow_row(*, status: str = "draft") -> SimpleNamespace:
    now = datetime.now()
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        name="draft workflow",
        description=None,
        status=status,
        is_active=True,
        created_by=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        deleted_at=None,
        nodes=[],
        edges=[],
    )


def test_permitted_non_admin_can_read_draft_workflow(monkeypatch):
    workflow = _workflow_row()

    class _Service:
        def __init__(self, **_kwargs):
            pass

        def get_workflow(self, _workflow_id):
            return workflow

    class _Authorization:
        def __init__(self, _db):
            pass

        def require(self, *_args):
            return None

        def allowed_actions(self, *_args):
            return ["read"]

    current_user = SimpleNamespace(id=workflow.created_by, tenant_id=workflow.tenant_id)

    monkeypatch.setattr(workflow_api, "WorkflowService", _Service)
    monkeypatch.setattr(workflow_api, "ResourceAuthorizationService", _Authorization)
    response = asyncio.run(
        workflow_api.get_workflow(
            workflow_id=uuid.UUID(workflow.id),
            db=object(),
            tenant_id=workflow.tenant_id,
            current_user=current_user,
        )
    )

    assert str(response.data.id) == workflow.id
    assert response.data.status == "draft"


def test_workflow_update_accepts_temporary_and_uuid_edge_references():
    persisted_id = str(uuid.uuid4())

    update = WorkflowUpdate.model_validate(
        {
            "nodes": [],
            "edges": [
                {
                    "source_node_id": "temp-start",
                    "target_node_id": persisted_id,
                }
            ],
        }
    )

    assert update.edges is not None
    assert update.edges[0].source_node_id == "temp-start"
    assert update.edges[0].target_node_id == persisted_id


def test_workflow_update_preserves_react_flow_handle_direction():
    update = WorkflowUpdate.model_validate(
        {
            "edges": [
                {
                    "source_node_id": "temp-start",
                    "target_node_id": str(uuid.uuid4()),
                    "source_handle": "source-bottom",
                    "target_handle": "target-top",
                }
            ],
        }
    )

    assert update.edges is not None
    assert update.edges[0].source_handle == "source-bottom"
    assert update.edges[0].target_handle == "target-top"


@pytest.mark.parametrize("reference", ["", "   ", "node-1", "not-a-uuid"])
def test_workflow_update_rejects_invalid_edge_reference(reference):
    with pytest.raises(ValidationError):
        WorkflowUpdate.model_validate(
            {
                "edges": [
                    {
                        "source_node_id": reference,
                        "target_node_id": str(uuid.uuid4()),
                    }
                ]
            }
        )


class _DB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.expired = []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def expire(self, instance, attributes):
        self.expired.append((instance, attributes))


class _WorkflowRepo:
    def __init__(self, workflow):
        self.workflow = workflow

    def get_with_nodes_and_edges(self, _workflow_id):
        return self.workflow

    def update(self, workflow, **updates):
        for key, value in updates.items():
            setattr(workflow, key, value)
        return workflow


class _NodeRepo:
    def __init__(self):
        self.created = []
        self.deleted = []

    def delete_by_workflow(self, workflow_id):
        self.deleted.append(workflow_id)

    def create(self, **values):
        row = SimpleNamespace(id=str(uuid.uuid4()), **values)
        self.created.append(row)
        return row


class _EdgeRepo:
    def __init__(self):
        self.created = []
        self.deleted = []

    def delete_by_workflow(self, workflow_id):
        self.deleted.append(workflow_id)

    def create(self, **values):
        row = SimpleNamespace(id=str(uuid.uuid4()), **values)
        self.created.append(row)
        return row


def _service_harness():
    existing_id = str(uuid.uuid4())
    workflow = _workflow_row()
    workflow.nodes = [SimpleNamespace(id=existing_id)]
    db = _DB()
    service = WorkflowService.__new__(WorkflowService)
    service.db = db
    service.tenant_id = workflow.tenant_id
    service.workflow_repo = _WorkflowRepo(workflow)
    service.node_repo = _NodeRepo()
    service.edge_repo = _EdgeRepo()
    return service, workflow, existing_id


def test_update_workflow_resolves_mixed_node_references_before_creating_edges():
    service, workflow, existing_id = _service_harness()
    update = WorkflowUpdate.model_validate(
        {
            "nodes": [
                {
                    "temp_id": existing_id,
                    "node_type": "start",
                    "name": "start",
                },
                {
                    "temp_id": "temp-end",
                    "node_type": "end",
                    "name": "end",
                },
            ],
            "edges": [
                {
                    "source_node_id": existing_id,
                    "target_node_id": "temp-end",
                    "source_handle": "source-bottom",
                    "target_handle": "target-top",
                }
            ],
        }
    )

    service.update_workflow(uuid.UUID(workflow.id), update)

    assert service.db.commits == 1
    assert service.node_repo.deleted == [workflow.id]
    assert service.edge_repo.deleted == [workflow.id]
    assert service.edge_repo.created[0].source_node_id == service.node_repo.created[0].id
    assert service.edge_repo.created[0].target_node_id == service.node_repo.created[1].id
    assert service.edge_repo.created[0].source_handle == "source-bottom"
    assert service.edge_repo.created[0].target_handle == "target-top"
    assert service.db.expired == [(workflow, ["nodes", "edges"])]


def test_update_workflow_rolls_back_when_edge_references_missing_node():
    service, workflow, _existing_id = _service_harness()
    update = WorkflowUpdate.model_validate(
        {
            "nodes": [
                {
                    "temp_id": "temp-start",
                    "node_type": "start",
                    "name": "start",
                }
            ],
            "edges": [
                {
                    "source_node_id": "temp-start",
                    "target_node_id": "temp-missing",
                }
            ],
        }
    )

    with pytest.raises(ValidationException, match="不存在的节点"):
        service.update_workflow(workflow.id, update)

    assert service.db.commits == 0
    assert service.db.rollbacks == 1


def test_execution_records_normalize_uuid_objects_to_string_ids():
    class _ExecutionDB:
        def __init__(self):
            self.row = None

        def add(self, row):
            self.row = row

        def flush(self):
            pass

    db = _ExecutionDB()
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.db = db
    engine.tenant_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    user_id = uuid.uuid4()

    execution = engine.create_execution(workflow_id, {}, user_id)

    assert execution.workflow_id == str(workflow_id)
    assert execution.tenant_id == str(engine.tenant_id)
    assert execution.created_by == str(user_id)


def test_stream_execution_passes_workflow_input_to_start_node():
    start = SimpleNamespace(id="start", node_type="start", name="开始")
    end = SimpleNamespace(id="end", node_type="end", name="结束")
    workflow = SimpleNamespace(
        id="workflow-1",
        status="published",
        nodes=[start, end],
        edges=[SimpleNamespace(source_node_id="start", target_node_id="end")],
    )

    class _WorkflowService:
        def get_workflow(self, _workflow_id, authorize=False):
            return workflow

        def validate_workflow_dag(self, _workflow_id, authorize=False):
            return None

    class _DB:
        def commit(self):
            return None

    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.tenant_id = "tenant-1"
    engine.actor = None
    engine.db = _DB()
    engine.workflow_service = _WorkflowService()
    engine.create_execution = lambda *_args, **_kwargs: SimpleNamespace(id="execution-1")
    engine.update_execution_status = lambda *_args, **_kwargs: None
    seen_contexts = []

    async def _execute_node(node, context, _execution_id):
        seen_contexts.append((node.node_type, context))
        return {"value": context.get("input", {}).get("value", "done")}

    engine.execute_node = _execute_node

    async def _run():
        return [event async for event in engine.execute_workflow_stream("workflow-1", {"value": 10}, "user-1")]

    asyncio.run(_run())

    assert seen_contexts[0] == ("start", {"input": {"value": 10}})


def test_end_node_without_output_mapping_passes_through_node_output():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    node = SimpleNamespace(config={})

    output = asyncio.run(engine._execute_end_node(node, {"result": 42}))

    assert output == {"result": 42}


def test_start_node_without_output_mapping_passes_through_workflow_input():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    node = SimpleNamespace(config={})

    output = asyncio.run(engine._execute_start_node(node, {"input": {"query": "北京"}}))

    assert output == {"query": "北京"}


def test_tool_node_calls_configured_plugin_endpoint(monkeypatch):
    endpoint = SimpleNamespace(
        id="endpoint-1",
        endpoint="/weather",
        method="POST",
        headers=None,
        request_body_schema=None,
    )
    plugin = SimpleNamespace(
        id="plugin-1",
        name="天气服务",
        status="active",
        source_type="http",
        api_spec={"servers": [{"url": "https://example.com"}]},
        _endpoints=[endpoint],
    )

    class _PluginService:
        def __init__(self, db, tenant_id, actor=None):
            assert tenant_id == "tenant-1"

        def get(self, plugin_id):
            assert plugin_id == "plugin-1"
            return plugin

        def _load_config_dict(self, plugin_id):
            assert plugin_id == "plugin-1"
            return {"base_url": "https://example.com"}

    calls = []

    def _execute_plugin_call(**kwargs):
        calls.append(kwargs)
        return {"success": True, "status_code": 200, "data": {"temperature": 26}}

    monkeypatch.setattr("app.services.plugin.PluginService", _PluginService)
    monkeypatch.setattr("app.utils.plugin_executor.execute_plugin_call", _execute_plugin_call)

    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.db = object()
    engine.tenant_id = "tenant-1"
    engine.actor = None
    node = SimpleNamespace(
        config={
            "tool_type": "plugin",
            "tool_name": "天气查询",
            "input_variables": ["city"],
            "output_variable": "weather",
            "tool_config": {
                "plugin_id": "plugin-1",
                "endpoint_id": "endpoint-1",
                "params": {"unit": "celsius"},
            },
        }
    )

    output = asyncio.run(engine._execute_tool_node(node, {"city": "北京"}))

    assert output["weather"] == {"temperature": 26}
    assert output["tool_type"] == "plugin"
    assert calls[0]["params"] == {"unit": "celsius", "city": "北京"}
    assert calls[0]["endpoint_path"] == "/weather"


def test_while_loop_requires_condition_template():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    node = SimpleNamespace(
        config={
            "loop_type": "while",
            "loop_variable": "count",
            "loop_source": "items",
            "max_iterations": 3,
        }
    )

    with pytest.raises(ValidationException, match="循环条件"):
        asyncio.run(engine._execute_loop_node(node, {"items": []}))


def test_code_node_supports_input_data_and_return_style_code():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    node = SimpleNamespace(
        config={
            "code": "return input_data['value'] * 2",
            "input_variables": ["value"],
            "output_variable": "result",
        }
    )

    output = asyncio.run(engine._execute_code_node(node, {"value": 21}))

    assert output == {"result": 42}


def test_for_loop_executes_right_branch_for_each_item_and_collects_results():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    loop = SimpleNamespace(id="loop", node_type="loop", config={
        "loop_type": "for",
        "loop_variable": "item",
        "loop_source": "items",
        "max_iterations": 10,
    })
    body = SimpleNamespace(id="body", node_type="variable", config={})
    exit_node = SimpleNamespace(id="end", node_type="end", config={})
    workflow = SimpleNamespace(
        nodes=[loop, body, exit_node],
        edges=[
            SimpleNamespace(source_node_id="loop", target_node_id="body", source_handle="source-right"),
            SimpleNamespace(source_node_id="loop", target_node_id="end", source_handle="source-bottom"),
            SimpleNamespace(source_node_id="body", target_node_id="end", source_handle="source-right"),
        ],
    )

    async def _execute_node(node, context, _execution_id):
        if node.id == "body":
            return {"seen": context["item"]}
        return {}

    engine.execute_node = _execute_node
    output, consumed = asyncio.run(
        engine._execute_loop_runtime(
            workflow,
            loop,
            {"items": ["a", "b"]},
            "execution-1",
            ["loop", "body", "end"],
        )
    )

    assert output["iterations"] == 2
    assert output["loop_results"] == [{"seen": "a"}, {"seen": "b"}]
    assert consumed == {"body"}


def test_for_loop_accepts_semantic_body_and_done_handles():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    loop = SimpleNamespace(id="loop", node_type="loop", config={
        "loop_type": "for",
        "loop_variable": "item",
        "loop_source": "items",
        "max_iterations": 10,
    })
    body = SimpleNamespace(id="body", node_type="variable", config={})
    exit_node = SimpleNamespace(id="end", node_type="end", config={})
    workflow = SimpleNamespace(
        nodes=[loop, body, exit_node],
        edges=[
            SimpleNamespace(source_node_id="loop", target_node_id="body", source_handle="loop-body"),
            SimpleNamespace(source_node_id="loop", target_node_id="end", source_handle="loop-done"),
        ],
    )

    async def _execute_node(node, context, _execution_id):
        if node.id == "body":
            return {"seen": context["item"]}
        return {}

    engine.execute_node = _execute_node
    output, consumed = asyncio.run(
        engine._execute_loop_runtime(
            workflow,
            loop,
            {"items": ["a"]},
            "execution-1",
            ["loop", "body", "end"],
        )
    )

    assert output["loop_results"] == [{"seen": "a"}]
    assert consumed == {"body"}


def test_while_loop_repeats_until_condition_is_false():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    loop = SimpleNamespace(id="loop", node_type="loop", config={
        "loop_type": "while",
        "loop_variable": "count",
        "loop_source": "count",
        "condition_template": "{{count}} < 3",
        "max_iterations": 10,
    })
    body = SimpleNamespace(id="body", node_type="code", config={})
    workflow = SimpleNamespace(
        nodes=[loop, body],
        edges=[SimpleNamespace(source_node_id="loop", target_node_id="body", source_handle="source-right")],
    )

    async def _execute_node(node, context, _execution_id):
        if node.id == "body":
            return {"count": context["count"] + 1}
        return {}

    engine.execute_node = _execute_node
    output, _consumed = asyncio.run(
        engine._execute_loop_runtime(
            workflow,
            loop,
            {"count": 0},
            "execution-1",
            ["loop", "body"],
        )
    )

    assert output["iterations"] == 3
    assert output["loop_results"] == [{"count": 1}, {"count": 2}, {"count": 3}]


def test_loop_requires_a_right_branch_as_body():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    loop = SimpleNamespace(id="loop", node_type="loop", config={
        "loop_type": "for",
        "loop_variable": "item",
        "loop_source": "items",
        "max_iterations": 10,
    })
    workflow = SimpleNamespace(
        nodes=[loop],
        edges=[],
    )

    with pytest.raises(ValidationException, match="循环体"):
        asyncio.run(
            engine._execute_loop_runtime(
                workflow,
                loop,
                {"items": [1]},
                "execution-1",
                ["loop"],
            )
        )
