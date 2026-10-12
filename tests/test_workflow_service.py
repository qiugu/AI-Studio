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

    monkeypatch.setattr(workflow_api, "WorkflowService", _Service)
    response = asyncio.run(
        workflow_api.get_workflow(
            workflow_id=uuid.UUID(workflow.id),
            db=object(),
            tenant_id=workflow.tenant_id,
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
