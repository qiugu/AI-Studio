"""Agent 流式对话装配阶段的错误协议测试。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.services.agent as agent_module
from cryptography.fernet import InvalidToken


def _collect(gen):
    async def drain():
        return [item async for item in gen]

    return asyncio.run(drain())


def test_chat_stream_reports_setup_failure_as_typed_error():
    service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
    service.get_agent = lambda *_args, **_kwargs: SimpleNamespace(model_id="model-1")

    def fail_build_llm(*_args, **_kwargs):
        raise RuntimeError("模型配置不完整")

    service._build_llm_client = fail_build_llm

    events = _collect(
        service.chat_stream(
            agent_id="agent-1",
            message="你好",
            conversation_id="conversation-1",
            user_id="user-1",
        )
    )

    assert events == [
        {
            "type": "error",
            "error": "智能体初始化失败：模型配置不完整",
            "error_code": "UNKNOWN_ERROR",
        }
    ]


def test_chat_stream_explains_when_provider_key_cannot_be_decrypted():
    service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
    service.get_agent = lambda *_args, **_kwargs: SimpleNamespace(model_id="model-1")

    def fail_build_llm(*_args, **_kwargs):
        raise InvalidToken

    service._build_llm_client = fail_build_llm

    events = _collect(
        service.chat_stream(
            agent_id="agent-1",
            message="你好",
            conversation_id="conversation-1",
            user_id="user-1",
        )
    )

    assert events == [
        {
            "type": "error",
            "error": "AI供应商 API Key 无法解密，请重新保存该供应商的 API Key",
            "error_code": "PROVIDER_KEY_DECRYPT_ERROR",
        }
    ]
