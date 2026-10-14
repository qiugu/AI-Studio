"""LLM 请求超时与错误提示的单元测试。

背景：Prompt 测试、供应商连通性检测等 AI 调用此前没有显式的服务端超时
（langchain-openai 默认 600s），而前端 axios 默认 30s 会先超时，用户只能看到
"超时"而看不到真实原因。修复后：
1. 远端供应商使用 config.llm_request_timeout（默认 120s），Ollama 保持 600s；
2. 超时/连接类异常被翻译为明确的中文提示（LLMException，HTTP 502）。
"""
import pytest

from app.core.exceptions import LLMException
from app.utils import llm as llm_utils


def test_resolve_timeout_ollama_keeps_600():
    """Ollama 本地推理首次调用需加载模型，保持 600s。"""
    assert llm_utils.resolve_llm_timeout("ollama") == 600


def test_resolve_timeout_remote_uses_config():
    """远端供应商使用可配置超时，且默认值合理（>30s，避免前端先超时）。"""
    from app.core.config import config

    assert config.llm_request_timeout == llm_utils.resolve_llm_timeout("openai")
    assert config.llm_request_timeout > 30


def test_build_chat_model_sets_request_timeout():
    """构建模型时必须把超时传给底层客户端（此处断言 openai 分支）。"""
    from app.core.config import config

    model = llm_utils.build_chat_model("openai", api_key="k", model_name="gpt-4o-mini")
    assert model.request_timeout == float(config.llm_request_timeout)


def test_invoke_model_translates_timeout_error(monkeypatch):
    """底层超时异常必须转换为可读的中文提示，而非原样英文。"""

    class _TimeoutModel:
        def invoke(self, _messages):
            raise RuntimeError("Request timed out.")

    monkeypatch.setattr(llm_utils, "build_chat_model", lambda **_kw: _TimeoutModel())

    with pytest.raises(LLMException) as exc_info:
        llm_utils.invoke_model(
            provider_type="openai",
            api_key="k",
            api_base_url=None,
            model_name="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
        )

    detail = str(exc_info.value.detail)
    assert "超时" in detail
    assert "gpt-4o-mini" in detail
