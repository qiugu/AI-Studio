"""Workflow LLM 节点的模型边界测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationException
from app.services.workflow_engine import WorkflowEngine


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *_args):
        return self

    def first(self):
        return self.result


class _DB:
    def __init__(self, model):
        self.model = model

    def query(self, *_args):
        return _Query(self.model)


def _engine_for(model) -> WorkflowEngine:
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.db = _DB(model)
    engine.tenant_id = 'tenant-1'
    return engine


def test_llm_node_rejects_disabled_model_before_calling_provider():
    model = SimpleNamespace(
        id='model-1',
        provider_id='provider-1',
        name='gpt-4o',
        model_type='chat',
        status=False,
        max_output_tokens=4096,
    )
    node = SimpleNamespace(
        config={
            'model_id': model.id,
            'prompt_template': 'hello',
        }
    )

    with pytest.raises(ValidationException, match='已停用'):
        asyncio.run(_engine_for(model)._execute_llm_node(node, {}))


def test_llm_node_rejects_max_tokens_above_model_capability():
    model = SimpleNamespace(
        id='model-1',
        provider_id='provider-1',
        name='gpt-4o',
        model_type='chat',
        status=True,
        max_output_tokens=4096,
    )
    node = SimpleNamespace(
        config={
            'model_id': model.id,
            'prompt_template': 'hello',
            'max_tokens': 8192,
        }
    )

    with pytest.raises(ValidationException, match='4096'):
        asyncio.run(_engine_for(model)._execute_llm_node(node, {}))
