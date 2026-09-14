"""
LangChain LLM 客户端封装。
根据供应商类型动态构建 BaseChatModel。
"""
import time
import json
from typing import Any
from dataclasses import asdict

from app.schemas.stream import StreamChunk
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.core.exceptions import LLMException


def resolve_llm_timeout(provider_type: str) -> int:
    """返回该供应商类型的 LLM 请求超时（秒）。

    - Ollama 为本地推理，首次调用需加载模型，允许更长时间（600s）；
    - openai / anthropic / azure / custom 等远端供应商使用
      ``config.llm_request_timeout``（默认 120s），以便超时后快速失败并返回
      明确错误，而不是让请求长时间悬挂（langchain-openai 默认 600s，
      前端/网关会先于其超时，用户只能看到"超时"而看不到真实原因）。
    """
    from app.core.config import config

    if provider_type == "ollama":
        return 600
    return config.llm_request_timeout


def _friendly_llm_error(exc: Exception, provider_type: str, model_name: str) -> str:
    """把底层异常翻译成用户可理解的中文提示（保留原始信息便于排查）。"""
    msg = str(exc)
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return (
            f"模型调用超时（供应商 {provider_type} / 模型 {model_name}，"
            f"超过 {resolve_llm_timeout(provider_type)}s 未返回）。"
            f"请检查供应商服务与网络连通性，或改用更快的模型。原始错误：{msg}"
        )
    if "connection" in low or "connect" in low:
        return f"无法连接模型服务（供应商 {provider_type} / 模型 {model_name}）：{msg}"
    return msg


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
    # 统一设置请求超时（调用方显式传入的 timeout 优先）
    kwargs.setdefault("timeout", resolve_llm_timeout(provider_type))

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
        from app.core.config import config

        # 优先使用传入的 api_base_url，其次使用配置文件中的 ollama_base_url
        ollama_url = api_base_url or config.ollama_base_url
        return ChatOllama(
            model=model_name,
            base_url=ollama_url,
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
        error_msg = _friendly_llm_error(e, provider_type, model_name)

        # 为 Ollama 404 错误提供更友好的提示
        if "Ollama" in error_msg and "404" in error_msg:
            error_msg = (
                f"Ollama service returned 404. Please check: "
                f"1) Ollama service is running at the specified endpoint; "
                f"2) Model '{model_name}' is available (run 'ollama list' to verify); "
                f"3) Base URL is correct. Original error: {error_msg}"
            )

        return {"success": False, "latency_ms": latency_ms, "error": error_msg}


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
        raise LLMException(_friendly_llm_error(e, provider_type, model_name))


def encode(chunk: StreamChunk):
    """生成标准 SSE 格式：event: xxx\ndata: xxx\n\n"""
    return f"event: {chunk.event}\ndata: {chunk.data}\n\n"
