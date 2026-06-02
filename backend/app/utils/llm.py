"""
LangChain LLM 客户端封装。
根据供应商类型动态构建 BaseChatModel。
"""
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.core.exceptions import LLMException


def build_chat_model(
    provider_type: str,
    api_key: str,
    api_base_url: str | None = None,
    model_name: str = "gpt-4o-mini",
    **overrides: Any,
) -> BaseChatModel:
    """
    根据 provider_type 动态构建 LangChain BaseChatModel。

    支持：openai / anthropic / azure / ollama / custom（OpenAI 兼容模式）
    """
    kwargs: dict[str, Any] = {**overrides}

    if provider_type == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base_url,
            **kwargs,
        )

    elif provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            **kwargs,
        )

    elif provider_type == "azure":
        from langchain_openai import AzureChatOpenAI
        # Azure 需要 api_base_url 作为 azure_endpoint
        return AzureChatOpenAI(
            azure_deployment=model_name,
            api_key=api_key,
            azure_endpoint=api_base_url or "",
            api_version=kwargs.pop("api_version", "2024-02-01"),
            **kwargs,
        )

    elif provider_type == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model_name,
            base_url=api_base_url or "http://localhost:11434",
            **kwargs,
        )

    else:
        # zhipu / baichuan / custom — 通常兼容 OpenAI API
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base_url,
            **kwargs,
        )


def test_connectivity(
    provider_type: str,
    api_key: str,
    api_base_url: str | None,
    model_name: str,
) -> dict:
    """
    测试供应商连通性。
    策略：发送简单消息（max_tokens=1），捕获任何认证/网络错误。
    返回: {"success": bool, "latency_ms": int | None, "error": str | None}
    """
    start = time.monotonic()
    try:
        llm = build_chat_model(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            max_tokens=1,
            temperature=0,
        )
        llm.invoke([HumanMessage(content="hi")])
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": True, "latency_ms": latency_ms, "error": None}
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": False, "latency_ms": latency_ms, "error": str(e)}


def invoke_model(
    provider_type: str,
    api_key: str,
    api_base_url: str | None,
    model_name: str,
    messages: list[dict],
) -> dict:
    """
    调用模型并返回内容和 token 使用情况。
    messages 格式: [{"role": "user", "content": "..."}]
    返回: {"content": str, "prompt_tokens": int, "completion_tokens": int, "latency_ms": int}
    """
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    def to_lc_message(msg: dict):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            return SystemMessage(content=content)
        elif role == "assistant":
            return AIMessage(content=content)
        return HumanMessage(content=content)

    start = time.monotonic()
    try:
        llm = build_chat_model(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
        )
        lc_messages = [to_lc_message(m) for m in messages]
        response = llm.invoke(lc_messages)
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = getattr(response, "usage_metadata", None) or {}
        return {
            "content": response.content,
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "latency_ms": latency_ms,
        }
    except Exception as e:
        raise LLMException(str(e))
