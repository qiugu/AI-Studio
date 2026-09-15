"""Agent服务"""
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
import logging
import uuid

from pydantic import create_model
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_tool import AgentTool
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.repositories.agent import AgentRepository, AgentToolRepository
from app.core.exceptions import NotFoundException, ValidationException
from app.core.tenant_scope import public_or_tenant_filter
from app.core.plugin_policy import (
    binding_rejection_reason,
    check_plugin_method_gate,
    check_plugin_source_gate,
    check_plugin_status_gate,
    has_explicit_endpoint_ref,
    resolve_bound_endpoint,
)
from app.schemas.agent import AgentCreate, AgentUpdate, AgentToolCreate
from app.utils import llm as llm_utils
from app.utils.encryption import decrypt
from app.utils.net_guard import assert_outbound_url_allowed
from app.services.knowledge import KnowledgeBaseService
from app.services.token_usage import TokenUsageService
from app.services.conversation import ConversationService
from app.services.audit import record_model_call

logger = logging.getLogger(__name__)


def _exc_message(exc: Exception) -> str:
    """提取异常的人类可读信息。

    ``AppException`` 派生类（如 ``BadRequestException``）把 message 放在 ``detail``，
    ``str(exc)`` 会渲染成 ``400: xxx`` 这类带状态码的字符串，直接回给模型可读性差。
    """
    return str(getattr(exc, "detail", None) or exc)


# JSON Schema 原子类型 -> Python 类型（用于端点入参 schema 生成 args_schema）。
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_args_schema(schema: Dict[str, Any]):
    """从端点入参 JSON Schema 生成 Pydantic ``args_schema``（review P1-C11）。

    仅消费 ``properties`` / ``required``；未知类型回落为 ``str``。生成失败（或结构非法）
    由调用方捕获并退化到单字符串 ``query``，不影响工具可用性。
    """
    properties = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    fields = {}
    for name, prop in properties.items():
        py_type = _JSON_TYPE_MAP.get(
            prop.get("type") if isinstance(prop, dict) else None, str
        )
        fields[name] = (py_type, ...) if name in required else (Optional[py_type], None)
    return create_model("PluginToolArgs", **fields)


# 单字符串入参工具的共享 Schema。
# 原生工具调用下模型按 JSON 回传入参，只有显式声明字段名才能让模型知道该写哪个键；
# 历史上用 dict 之外的一个裸字符串（旧 ``Tool`` 的位置参数），模型无法判断语义。
_QUERY_ARGS = create_model("ToolQueryArgs", query=(str, ...))


class AgentAssemblyError(Exception):
    """智能体装配失败（工具/提示词/Executor 构建阶段）。

    与「模型调用失败」严格区分：这类错误**根本没走到模型**（例如模型不支持工具调用、
    提示词缺少必需变量），把它报成模型问题是误导——用户去查 API Key 会一无所获。
    """


def _content_text(chunk: Any) -> str:
    """从 LangChain 流块/消息中提取纯文本。

    兼容两种 ``content`` 形态：``str``，以及多模态/推理模型返回的
    ``[{"type": "text", "text": ...}, ...]`` 块列表（后者直接当字符串用会得到
    list 的 repr）。
    """
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


async def _iter_plain_llm_output(stream: Any):
    """把无工具路径的 LLM 流包装成与工具路径一致的「内容块 / 用量」序列。

    两个路径产出同一种事件形状后，``chat_stream`` 的打字机下发、token 记账与
    ``done`` 事件只需写一份，不会随改动漂移。
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    async for chunk in stream:
        text = _content_text(chunk)
        if text:
            yield {"type": "content", "content": text}
        meta = getattr(chunk, "usage_metadata", None) or {}
        if meta:
            usage = {
                "input_tokens": int(meta.get("input_tokens") or 0),
                "output_tokens": int(meta.get("output_tokens") or 0),
                "total_tokens": int(meta.get("total_tokens") or 0),
            }
    yield {"type": "usage", **usage}


def _assert_plugin_tool_bindable(index: int, tool: Any, lookup) -> None:
    """校验单条 ``plugin`` 类工具绑定是否合法，不合法即抛 ``ValidationException``。

    **设计期门禁**（fail-closed）：在 Agent 创建/更新时就拒绝非法绑定，而不是留到
    运行时静默跳过。后者会让调用方以为"配上了"，实际工具根本没进工具池。

    ``lookup(plugin_id) -> (plugin, endpoints)`` 由调用方注入：生产路径走
    ``PluginService.get``（租户内或公共插件，否则 NotFound），单测可传入轻量替身，
    因此本函数无需数据库即可覆盖。
    """
    config = getattr(tool, "config", None) or {}
    name = getattr(tool, "name", None) or "(未命名)"
    label = f"第 {index + 1} 个工具「{name}」"

    plugin_id = config.get("plugin_id") if hasattr(config, "get") else None
    if not plugin_id:
        raise ValidationException(f"{label}缺少 plugin_id")

    try:
        plugin, endpoints = lookup(plugin_id)
    except NotFoundException:
        # from None：原始 NotFound 的信息已完整并入新消息，保留异常链只会让日志里
        # 出现无意义的双层 traceback。
        raise ValidationException(
            f"{label}引用的插件不存在或不属于当前租户：{plugin_id}"
        ) from None

    reason = binding_rejection_reason(config, plugin, endpoints)
    if reason:
        raise ValidationException(f"{label}不可绑定：{reason}")


def _extract_openai_error_message(error: Exception, default_msg: str) -> str:
    """
    从 OpenAI 异常中提取具体的错误消息。
    
    Args:
        error: OpenAI 异常对象
        default_msg: 默认错误消息
    
    Returns:
        提取的错误消息或默认消息
    """
    try:
        if hasattr(error, 'response') and error.response:
            import json
            response_data = json.loads(error.response.text)
            if 'error' in response_data and 'message' in response_data['error']:
                return response_data['error']['message']
    except Exception:
        pass
    
    # 尝试从 str(error) 中提取有用信息
    error_detail = str(error)
    if len(error_detail) > 50:
        return error_detail[:200]  # 截取前200个字符
    
    return default_msg


class AgentService:
    """Agent服务"""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.agent_repo = AgentRepository(db=db, tenant_id=tenant_id)
        self.tool_repo = AgentToolRepository(db=db, tenant_id=tenant_id)
        self.token_usage_service = TokenUsageService(db=db, tenant_id=tenant_id)
        self.conv_service = ConversationService(db=db, tenant_id=tenant_id)

    def _record_model_call(
        self,
        *,
        agent_id: Optional[str],
        user_id: Optional[str],
        conversation_id: Optional[str],
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """记录模型调用日志（同时补全 provider_id）。"""
        provider_id = None
        try:
            model = self.db.query(AIModel).filter(AIModel.id == model_id).first()
            provider_id = model.provider_id if model else None
        except Exception:
            pass
        record_model_call(
            self.db,
            self.tenant_id,
            model_id=model_id,
            user_id=user_id,
            agent_id=agent_id,
            provider_id=provider_id,
            conversation_id=conversation_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )

    # ── Agent CRUD ───────────────────────────────────────────────────────────

    def create_agent(
        self,
        data: AgentCreate,
        user_id: str,
    ) -> Agent:
        """创建Agent"""
        # 验证AI模型存在
        model = self.db.query(AIModel).filter(
            AIModel.id == data.model_id,
            public_or_tenant_filter(AIModel, self.tenant_id, include_public=True),
            AIModel.deleted_at.is_(None),
        ).first()
        if not model:
            raise NotFoundException("AIModel", data.model_id)

        # 设计期门禁：写入前校验插件绑定，避免落库后才发现不可用。
        self._validate_tool_bindings(data.tools)

        # 创建Agent
        agent = self.agent_repo.create(
            name=data.name,
            description=data.description,
            avatar=data.avatar,
            system_prompt=data.system_prompt,
            model_id=data.model_id,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            status=data.status,
            created_by=user_id,
        )

        # 创建工具
        for tool_data in data.tools:
            self.tool_repo.create(
                agent_id=agent.id,
                tool_type=tool_data.tool_type,
                config=tool_data.config,
                name=tool_data.name,
                description=tool_data.description,
                is_enabled=tool_data.is_enabled,
            )

        self.db.commit()
        return self.get_agent(agent.id)

    def get_agent(self, agent_id: str) -> Agent:
        """获取Agent详情"""
        agent = self.agent_repo.get_with_tools(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)
        return agent

    def list_agents(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[List[Agent], int]:
        """列出Agents"""
        agents = self.agent_repo.list_by_status(status=status, page=page, page_size=page_size)
        total = self.agent_repo.count_by_status(status=status)
        return agents, total

    def update_agent(
        self,
        agent_id: str,
        data: AgentUpdate,
    ) -> Agent:
        """更新Agent"""
        agent = self.get_agent(agent_id)

        # 验证AI模型存在（如果更新了模型）
        if data.model_id is not None:
            model = self.db.query(AIModel).filter(
                AIModel.id == data.model_id,
                public_or_tenant_filter(AIModel, self.tenant_id, include_public=True),
                AIModel.deleted_at.is_(None),
            ).first()
            if not model:
                raise NotFoundException("AIModel", data.model_id)

        # 更新基本信息
        updates = data.model_dump(exclude={"tools"}, exclude_unset=True)
        if updates:
            self.agent_repo.update(agent, **updates)

        # 更新工具（如果提供）
        if data.tools is not None:
            # 设计期门禁：必须先校验再删除旧工具。若先删后校验，一次非法提交
            # 会连带把已有的合法授权清空（虽在同一事务内可回滚，但语义上不该走到那一步）。
            self._validate_tool_bindings(data.tools)
            # 仅重建 plugin 类工具：knowledge / api / function / workflow 等其它类型
            # 由各自流程管理，此处不得触碰——否则 UI 仅提交 plugin 工具时会把它们
            # 静默清空（历史 bug，详见 review §3.1）。
            plugin_tools = [
                t for t in data.tools
                if getattr(t, "tool_type", None) == "plugin"
            ]
            self.tool_repo.delete_by_agent(agent_id, tool_type="plugin")
            # 创建新工具（仅 plugin 类；其它类型不在本端点的职责范围内）
            for tool_data in plugin_tools:
                self.tool_repo.create(
                    agent_id=agent.id,
                    tool_type=tool_data.tool_type,
                    config=tool_data.config,
                    name=tool_data.name,
                    description=tool_data.description,
                    is_enabled=tool_data.is_enabled,
                )

        self.db.commit()
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> None:
        """删除Agent"""
        agent = self.get_agent(agent_id)
        self.agent_repo.delete(agent)
        self.db.commit()

    # ── Agent工具授权校验（设计期门禁） ────────────────────────────────────

    def _lookup_plugin_for_binding(self, plugin_id: str):
        """取插件及其端点：本租户或平台公共插件，否则抛 ``NotFoundException``。"""
        from app.services.plugin import PluginService

        plugin = PluginService(self.db, self.tenant_id).get(plugin_id)
        return plugin, list(getattr(plugin, "_endpoints", None) or [])

    def _validate_tool_bindings(self, tools: Optional[List[AgentToolCreate]]) -> None:
        """在落库前校验全部 ``plugin`` 类工具绑定（fail-closed）。

        只校验 ``plugin`` 类型——``knowledge`` / ``api`` / ``function`` / ``workflow``
        各有自己的配置约束，不属本策略范围。

        任一条不合法即抛 ``ValidationException``，**整次请求失败**：部分成功会让调用方
        无法判断最终状态，也容易掩盖「以为配上了、其实被静默丢弃」的问题。
        """
        for index, tool in enumerate(tools or []):
            if getattr(tool, "tool_type", None) != "plugin":
                continue
            _assert_plugin_tool_bindable(index, tool, self._lookup_plugin_for_binding)

    # ── Agent工具构建 ───────────────────────────────────────────────────────

    def _build_langchain_tools(self, agent: Agent) -> List[Any]:
        """构建LangChain工具列表。

        所有工具统一构建为 ``StructuredTool``（旧版是 ``Tool``），原因是二者的入参
        语义不兼容：

        - ``langchain_core.tools.Tool`` 是**单入参**工具，``_to_args_and_kwargs``
          会把任何输入折叠成一个**位置参数**。多字段 ``args_schema`` 的插件端点被它
          驱动时，dict 入参直接抛 ``ToolException: Too many arguments to
          single-input tool``；字符串入参则整个塞进第一个形参（本项目里第一个形参是
          闭包用的 ``_plugin``），工具静默不执行。
        - 原生工具调用（function calling）下模型回传的是 ``dict``，只有
          ``StructuredTool`` 会按关键字展开为 ``func(**kwargs)``。

        因此单字符串工具也显式声明 ``_QUERY_ARGS``，而不是省略 ``args_schema``——
        省略会让模型看到一个语义不明的裸字符串参数。
        """
        from langchain_core.tools import StructuredTool

        tools = []
        for agent_tool in agent.tools:
            if not agent_tool.is_enabled:
                continue

            tool_type = agent_tool.tool_type
            config = agent_tool.config

            # 知识库工具
            if tool_type == "knowledge":
                kb_id = config.get("knowledge_base_id")
                top_k = config.get("top_k", 5)
                kb_service = KnowledgeBaseService(self.db, self.tenant_id)
                
                # kb_id / top_k 必须经**默认参数**绑定，不可直接在函数体内引用：
                # 二者是 `_build_langchain_tools` 的函数级局部变量，闭包捕获的是同一个
                # cell，循环结束后全部取最后一个知识库的值。表现为「一个 Agent 绑定多个
                # 知识库时，所有工具都只查最后一个库」——不报错、不告警的静默串库。
                # 同文件的 api / function / workflow 分支早已采用默认参数绑定，此处遗漏。
                def knowledge_search_func(
                    query: str, _kb_id=kb_id, _top_k=top_k, _tool_name=agent_tool.name
                ) -> str:
                    """知识库检索"""
                    try:
                        outcome = kb_service.search_with_diagnostics(
                            kb_id=_kb_id, query=query, top_k=_top_k
                        )
                    except Exception as exc:
                        # LangChain 的 Tool 默认不吞异常：抛出会中断整个 ReAct 执行，
                        # 并把内部异常文本暴露给模型。工具失败应作为一条**可读的观察
                        # 结果**返回，由模型自行决定换用其它工具或直接作答。
                        # 只回传异常类别，不回传栈或原始消息，避免泄漏内部结构。
                        logger.warning(
                            "Agent 知识库工具执行失败（tool=%s kb=%s）：%s",
                            _tool_name, _kb_id, exc,
                        )
                        return f"知识库检索失败：{type(exc).__name__}"

                    if outcome.degraded:
                        # 故障与「确实没有相关内容」必须区分：否则模型会把一次后端
                        # 故障当成事实依据，向用户断言「知识库中不存在该内容」。
                        return (
                            f"知识库检索未生效（降级原因：{outcome.reason}）。"
                            "该结果不能作为「知识库中没有相关内容」的依据，"
                            "请勿据此给出否定性结论。"
                        )
                    if not outcome.results:
                        return "未找到相关知识"
                    return "\n".join([r.get("content", "") for r in outcome.results])

                tools.append(
                    StructuredTool.from_function(
                        func=knowledge_search_func,
                        name=agent_tool.name,
                        description=agent_tool.description or f"搜索知识库 {kb_id}",
                        args_schema=_QUERY_ARGS,
                    )
                )

            # API工具
            elif tool_type == "api":
                url = config.get("url")
                if not url:
                    logger.warning("Agent API 工具跳过：缺少 url 配置 (%s)", agent_tool.name)
                    continue

                method = (config.get("method") or "GET").upper()
                headers = config.get("headers") or {}
                timeout = float(config.get("timeout") or 30)

                def api_call_func(
                    query: str,
                    _url=url,
                    _method=method,
                    _headers=headers,
                    _timeout=timeout,
                ) -> str:
                    """调用外部 HTTP API，入参可为 JSON 字符串或纯文本。"""
                    import json as _json

                    import httpx as _httpx

                    try:
                        payload = (
                            _json.loads(query)
                            if isinstance(query, str) and query.strip().startswith("{")
                            else {"query": query}
                        )
                    except Exception:
                        payload = {"query": query}

                    try:
                        # 与插件调用同源的风险：目标 URL 由租户配置，须先过出站护栏，
                        # 否则该工具可直接访问内网 / 云元数据地址。
                        assert_outbound_url_allowed(_url)
                        with _httpx.Client(
                            timeout=_timeout, follow_redirects=False
                        ) as client:
                            if _method == "GET":
                                resp = client.request(
                                    _method, _url, params=payload, headers=_headers
                                )
                            else:
                                resp = client.request(
                                    _method, _url, json=payload, headers=_headers
                                )
                        resp.raise_for_status()
                        try:
                            data = resp.json()
                        except Exception:
                            data = resp.text
                        return _json.dumps(data, ensure_ascii=False, default=str)
                    except Exception as e:
                        return f"API 调用异常：{_exc_message(e)}"

                tools.append(
                    StructuredTool.from_function(
                        func=api_call_func,
                        name=agent_tool.name,
                        description=agent_tool.description
                        or f"调用外部 API（{method} {url}）",
                        args_schema=_QUERY_ARGS,
                    )
                )

            # Function工具
            elif tool_type == "function":
                code = config.get("code")
                if not code:
                    logger.warning("Agent Function 工具跳过：缺少 code 配置 (%s)", agent_tool.name)
                    continue

                # 受限执行环境：禁用危险内置函数，仅暴露安全的辅助函数
                safe_builtins = {
                    "print": print,
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "tuple": tuple,
                    "set": set,
                    "sum": sum,
                    "min": min,
                    "max": max,
                    "abs": abs,
                    "round": round,
                    "sorted": sorted,
                    "enumerate": enumerate,
                    "range": range,
                    "json": __import__("json"),
                    "math": __import__("math"),
                    "datetime": __import__("datetime"),
                }

                def function_call_func(query: str, _code=code) -> str:
                    """执行用户自定义函数代码，code 需定义 main(input) 并返回结果。"""
                    import json as _json

                    local_ns: dict = {}
                    try:
                        compiled = compile(_code, "<agent_function_tool>", "exec")
                        exec(compiled, {"__builtins__": safe_builtins}, local_ns)
                        main_func = local_ns.get("main") or local_ns.get(
                            next(
                                (k for k in local_ns if callable(local_ns[k]) and not k.startswith("__")),
                                None,
                            )
                        )
                        if main_func is None:
                            return "Function 工具执行失败：未找到可调用函数（请定义 main(input)）"
                        try:
                            parsed = (
                                _json.loads(query)
                                if isinstance(query, str) and query.strip().startswith("{")
                                else query
                            )
                        except Exception:
                            parsed = query
                        result = main_func(parsed)
                        return _json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result
                    except Exception as e:
                        return f"Function 工具执行异常：{str(e)}"

                tools.append(
                    StructuredTool.from_function(
                        func=function_call_func,
                        name=agent_tool.name,
                        description=agent_tool.description or f"执行自定义函数 {agent_tool.name}",
                        args_schema=_QUERY_ARGS,
                    )
                )

            # Workflow工具
            elif tool_type == "workflow":
                workflow_id = config.get("workflow_id")
                if not workflow_id:
                    logger.warning("Agent Workflow 工具跳过：缺少 workflow_id 配置 (%s)", agent_tool.name)
                    continue

                def workflow_run_func(query: str, _workflow_id=workflow_id) -> str:
                    """执行工作流，入参可为 JSON 字符串或纯文本。"""
                    import asyncio
                    import json as _json

                    from app.services.workflow_engine import WorkflowEngine

                    try:
                        input_data = (
                            _json.loads(query)
                            if isinstance(query, str) and query.strip().startswith("{")
                            else {"query": query}
                        )
                    except Exception:
                        input_data = {"query": query}

                    try:
                        engine = WorkflowEngine(db=self.db, tenant_id=self.tenant_id)
                        result = asyncio.run(
                            engine.execute_workflow(
                                workflow_id=uuid.UUID(str(_workflow_id)),
                                input_data=input_data,
                                user_id=None,
                            )
                        )
                        return _json.dumps(result.get("output"), ensure_ascii=False, default=str)
                    except Exception as e:
                        return f"工作流执行异常：{str(e)}"

                tools.append(
                    StructuredTool.from_function(
                        func=workflow_run_func,
                        name=agent_tool.name,
                        description=agent_tool.description or f"执行工作流 {workflow_id}",
                        args_schema=_QUERY_ARGS,
                    )
                )

            # Plugin工具
            elif tool_type == "plugin":
                from app.services.plugin import PluginService
                from app.utils.plugin_executor import execute_plugin_call

                plugin_id = config.get("plugin_id")
                if not plugin_id:
                    continue

                # 门禁 1：必须显式指定端点。先于数据库查询判断，既省去一次注定被拒
                # 的查询，也让"未配端点"的失败原因更明确。
                if not has_explicit_endpoint_ref(config):
                    logger.warning(
                        "Agent 插件工具跳过：%s 未显式指定端点（endpoint_id / endpoint）",
                        agent_tool.name,
                    )
                    continue

                plugin_svc = PluginService(self.db, self.tenant_id)
                try:
                    plugin = plugin_svc.get(plugin_id)
                except Exception:
                    logger.warning("Agent 插件工具跳过：插件 %s 不存在", plugin_id)
                    continue

                # 门禁 0：接入方式必须已实现。插件被改为 mcp / skill 后，原有 http
                # 绑定必须立即失能（与设计期共用 BINDABLE_SOURCE_TYPES，避免 fail-open）。
                source_reason = check_plugin_source_gate(getattr(plugin, "source_type", None))
                if source_reason:
                    logger.warning(
                        "Agent 插件工具跳过：%s（插件 %s）", source_reason, plugin_id
                    )
                    continue

                # 门禁 2：插件状态必须允许暴露。禁用 / 待审插件不得被 Agent 调用，
                # 否则"停用插件"这一动作在运行时形同虚设。
                status_reason = check_plugin_status_gate(plugin.status)
                if status_reason:
                    logger.warning(
                        "Agent 插件工具跳过：%s（插件 %s）", status_reason, plugin_id
                    )
                    continue

                # 解析目标端点：仅接受配置显式指定的 endpoint_id 或 endpoint 路径。
                # 与设计期校验共用 resolve_bound_endpoint，避免两处解析规则漂移；
                # 不再回退到"首个端点"——该兜底使端点选择不可预期，
                # 且 OpenAPI 规范中破坏性端点常排在前面。
                # 复用 plugin_svc.get 已加载的端点，省去两次按端点查询。
                endpoint = resolve_bound_endpoint(
                    config, getattr(plugin, "_endpoints", None)
                )
                if endpoint is None:
                    logger.warning(
                        "Agent 插件工具跳过：插件 %s 未找到配置指定的端点", plugin_id
                    )
                    continue

                method = (config.get("method") or endpoint.method).upper()

                # 门禁 3：破坏性动词默认不暴露，需显式 allow_destructive=true。
                method_reason = check_plugin_method_gate(method, config)
                if method_reason:
                    logger.warning(
                        "Agent 插件工具跳过：%s（插件 %s，端点 %s %s）",
                        method_reason,
                        plugin_id,
                        method,
                        endpoint.endpoint,
                    )
                    continue

                config_values = plugin_svc._load_config_dict(plugin_id)

                # 若端点声明了入参 Schema，将其作为结构化参数提供给模型（review P1-C11）；
                # 否则退化为单字符串 query（历史行为）。
                request_schema = getattr(endpoint, "request_body_schema", None) or {}
                args_schema = None
                param_hint = ""
                if isinstance(request_schema, dict) and request_schema.get("properties"):
                    try:
                        args_schema = _build_args_schema(request_schema)
                        props = request_schema["properties"]
                        param_hint = "；参数：" + "、".join(
                            f"{k}:{props[k].get('type', 'any')}" for k in props
                        )
                    except Exception:
                        args_schema = None

                base_desc = agent_tool.description or f"调用插件 {plugin.name}"

                if args_schema is not None:
                    def plugin_func(
                        _plugin=plugin,
                        _endpoint=endpoint,
                        _method=method,
                        _config_values=config_values,
                        **kwargs,
                    ) -> str:
                        """调用插件端点，入参为端点声明的结构化参数。"""
                        import json

                        params = {k: v for k, v in kwargs.items() if v is not None}
                        try:
                            result = execute_plugin_call(
                                plugin_name=_plugin.name,
                                api_spec=_plugin.api_spec,
                                endpoint_path=_endpoint.endpoint,
                                method=_method,
                                endpoint_headers=_endpoint.headers,
                                config_values=_config_values,
                                params=params,
                            )
                        except Exception as e:
                            return f"插件调用异常：{_exc_message(e)}"
                        if not result["success"]:
                            return f"插件调用失败：{result.get('error')}"
                        return json.dumps(result.get("data"), ensure_ascii=False, default=str)

                    tools.append(
                        StructuredTool.from_function(
                            func=plugin_func,
                            name=agent_tool.name,
                            description=base_desc + param_hint,
                            args_schema=args_schema,
                        )
                    )
                else:
                    def plugin_func(
                        query: str,
                        _plugin=plugin,
                        _endpoint=endpoint,
                        _method=method,
                        _config_values=config_values,
                    ) -> str:
                        """调用插件端点，入参可为 JSON 字符串或纯文本。"""
                        import json

                        try:
                            params = (
                                json.loads(query)
                                if isinstance(query, str) and query.strip().startswith("{")
                                else {"query": query}
                            )
                        except Exception:
                            params = {"query": query}
                        try:
                            result = execute_plugin_call(
                                plugin_name=_plugin.name,
                                api_spec=_plugin.api_spec,
                                endpoint_path=_endpoint.endpoint,
                                method=_method,
                                endpoint_headers=_endpoint.headers,
                                config_values=_config_values,
                                params=params,
                            )
                        except Exception as e:
                            return f"插件调用异常：{_exc_message(e)}"
                        if not result["success"]:
                            return f"插件调用失败：{result.get('error')}"
                        return json.dumps(result.get("data"), ensure_ascii=False, default=str)

                    tools.append(
                        StructuredTool.from_function(
                            func=plugin_func,
                            name=agent_tool.name,
                            description=base_desc,
                            args_schema=_QUERY_ARGS,
                        )
                    )

        return tools

    def _build_llm_client(self, agent: Agent) -> Any:
        """构建LLM客户端"""
        # 获取模型和供应商
        model = self.db.query(AIModel).filter(AIModel.id == agent.model_id).first()
        if not model:
            raise NotFoundException("AIModel", agent.model_id)

        provider = self.db.query(AIProvider).filter(
            AIProvider.id == model.provider_id,
            AIProvider.tenant_id == self.tenant_id,
        ).first()
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)

        # 解密API Key
        api_key = decrypt(provider.api_key_encrypted)
        api_base_url = provider.api_base_url

        # 构建LLM
        return llm_utils.build_chat_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model.name,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )

    # ── 工具调用型 Agent 的装配与驱动 ────────────────────────────────────────

    def _build_tool_agent_executor(self, agent: Agent, tools: List[Any], llm: Any = None):
        """构建「原生工具调用」型 AgentExecutor。

        替代旧版的文本 ReAct（``create_react_agent``）。旧实现有三处硬伤：
        ① 提示词缺 ``{tool_names}``，LangChain 直接 ``ValueError``（本函数下方有说明）；
        ② 文本协议要求模型把入参写成 ``Action Input:`` 的裸文本，与结构化参数天然冲突；
        ③ 它绕开了模型的 function calling 能力，参数全靠字符串解析，易错且无法校验。

        原生工具调用把参数以 JSON Schema 交给模型、以 ``dict`` 收回，与本项目已落地的
        端点入参 schema（review P1-C11）才是配套的。
        """
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

        if not hasattr(llm, "bind_tools"):
            raise AgentAssemblyError(
                f"当前模型（{type(llm).__name__}）不支持工具调用，无法绑定 {len(tools)} 个工具。"
                "请改用支持 function calling 的模型，或移除该 Agent 的工具绑定。"
            )

        system_prompt = (getattr(agent, "system_prompt", None) or "").strip() or (
            "你是一个可以使用工具完成任务的助手。需要外部信息时先调用工具，"
            "拿到结果后再作答；不要编造工具未返回的内容。"
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                # optional=True：无历史时（新会话）该占位符允许为空，不必强制传参
                MessagesPlaceholder("chat_history", optional=True),
                ("human", "{input}"),
                # create_tool_calling_agent 要求该占位符存在，用于回灌工具调用与结果
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )

        try:
            lc_agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
        except Exception as exc:
            raise AgentAssemblyError(f"工具调用智能体装配失败：{_exc_message(exc)}") from exc

        return AgentExecutor(
            agent=lc_agent,
            tools=tools,
            verbose=False,
            # 解析失败时把错误回灌给模型让它自我修正，而不是中断整轮对话
            handle_parsing_errors=True,
        )

    async def _iter_tool_agent_output(self, executor: Any, inputs: Dict[str, Any]):
        """驱动工具调用型 Agent，产出内容块 / 工具事件 / 用量。

        **不能用 ``executor.astream``**：它只产出 ``actions`` / ``steps`` / ``output``
        这类**聚合**事件（实测 3 条 AddableDict），没有 ``.content``，拿不到逐字内容；
        而产品依赖打字机式的逐字流式。故订阅 ``astream_events(v2)`` 里底层 chat model
        的 ``on_chat_model_stream``。

        用量按**多次模型调用累加**：工具调用会触发多轮 LLM 请求，只取最后一次会严重
        低报 token（实测一轮工具调用 input 已达 10k）。
        """
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        async for event in executor.astream_events(inputs, version="v2"):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                # 中间轮（生成工具调用）的 content 通常为空，靠空串过滤即可
                text = _content_text(event.get("data", {}).get("chunk"))
                if text:
                    yield {"type": "content", "content": text}
            elif kind == "on_tool_start":
                yield {"type": "tool_start", "tool": event.get("name")}
            elif kind == "on_tool_end":
                yield {"type": "tool_end", "tool": event.get("name")}
            elif kind == "on_chat_model_end":
                meta = getattr(event.get("data", {}).get("output"), "usage_metadata", None) or {}
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    usage[key] += int(meta.get(key) or 0)
        yield {"type": "usage", **usage}

    def _build_chat_history(
        self,
        conversation_id: Optional[str],
        message: str,
        history_messages: Optional[List[Any]],
    ) -> List[Any]:
        """构建**当前轮之前**的对话历史（LangChain 消息列表）。

        只返回历史轮次、**不含当前这条用户消息**：调用方统一以 ``{input}`` / 末尾
        ``HumanMessage`` 的形式单独传入当前消息。两条来源都可能已经包含当前消息，
        故末尾需要按内容去重，否则当前问题在上下文里出现两次。

        容错两处历史遗留差异：
        ① 入参既有 ``dict``（``chat`` 的类型标注）也有 API 层实际传入的 ``MessageBase``
           对象（``ChatRequest.messages``）——旧代码分别用 ``msg["role"]`` / ``msg.role``
           取值，其中阻塞式路径一旦收到对象即 ``TypeError``；
        ② 前端会把它自己持有的消息一并回传，需去重。
        """
        from langchain_core.messages import AIMessage, HumanMessage

        def _role_content(item: Any):
            if isinstance(item, dict):
                return item.get("role"), item.get("content")
            return getattr(item, "role", None), getattr(item, "content", None)

        lc_history: List[Any] = []

        if history_messages:
            source = [_role_content(item) for item in history_messages]
        elif conversation_id:
            # API 层会先把当前用户消息落库，所以这里通常已含当前消息
            source = [
                (item.get("role"), item.get("content"))
                for item in self.conv_service.get_conversation_history(conversation_id)
            ]
        else:
            return lc_history

        for role, content in source:
            if role == "user":
                lc_history.append(HumanMessage(content=content or ""))
            elif role == "assistant":
                lc_history.append(AIMessage(content=content or ""))

        # 去重：末尾若是与当前提问同文的用户消息，说明它就是当前轮，剔除
        if (
            lc_history
            and isinstance(lc_history[-1], HumanMessage)
            and lc_history[-1].content == message
        ):
            lc_history.pop()

        return lc_history

    async def chat(
        self,
        agent_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """执行Agent对话（阻塞式）

        Args:
            agent_id: Agent ID
            message: 当前用户消息
            conversation_id: 对话ID（可选）
            user_id: 用户ID（可选）
            history_messages: 前端传递的历史消息数组（可选），格式：[{"role": "user", "content": "..."}]
        """
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        import httpx
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            RateLimitError,
            BadRequestError,
        )
        from app.core.exceptions import LLMException

        agent = self.get_agent(agent_id)

        # 构建LLM和工具
        llm = self._build_llm_client(agent)
        tools = self._build_langchain_tools(agent)
        # 历史只含「当前轮之前」，当前消息统一由 {input} / 末尾 HumanMessage 传入
        chat_history = self._build_chat_history(conversation_id, message, history_messages)

        try:
            # 如果有工具，走原生工具调用（function calling）
            if tools:
                executor = self._build_tool_agent_executor(agent, tools, llm)

                collected: List[str] = []
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                async for item in self._iter_tool_agent_output(
                    executor, {"input": message, "chat_history": chat_history}
                ):
                    if item["type"] == "content":
                        collected.append(item["content"])
                    elif item["type"] == "usage":
                        prompt_tokens = item["input_tokens"]
                        completion_tokens = item["output_tokens"]
                        total_tokens = item["total_tokens"]

                response_content = "".join(collected)
            else:
                # 无工具，直接对话
                messages = []
                if agent.system_prompt:
                    messages.append(SystemMessage(content=agent.system_prompt))

                # 添加对话历史（不含当前消息，故下面显式补当前消息）
                messages.extend(chat_history)
                messages.append(HumanMessage(content=message))

                response = await llm.ainvoke(messages)
                response_content = response.content

                # Token统计
                usage = getattr(response, "usage_metadata", None) or {}
                prompt_tokens = usage.get("input_tokens", 0)
                completion_tokens = usage.get("output_tokens", 0)
                total_tokens = prompt_tokens + completion_tokens

            # 记录Token使用情况
            if total_tokens > 0:
                self.token_usage_service.record_usage(
                    model_id=agent.model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                self._record_model_call(
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    model_id=agent.model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                self.db.commit()

            return {
                "content": response_content,
                "agent_id": agent_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }

        except AuthenticationError as e:
            # API 密钥无效或过期
            error_msg = "API认证失败，请检查API密钥是否有效"
            logger.error(
                f"LLM authentication failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "authentication_error",
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except RateLimitError as e:
            # API 限流 - 提取具体的错误消息
            error_msg = _extract_openai_error_message(
                e, "API调用频率超限，请稍后重试"
            )
            error_detail = str(e)

            logger.error(
                f"LLM rate limit exceeded for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "rate_limit_error",
                    "error_detail": error_detail,
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except BadRequestError as e:
            # 请求参数错误（如 token 超限、内容违规等）- 提取具体的错误消息
            error_detail = str(e)
            error_code = "BAD_REQUEST_ERROR"

            # 尝试提取 OpenAI 返回的具体消息
            error_msg = _extract_openai_error_message(e, "")
            
            if not error_msg:
                # 如果没有提取到具体消息，根据 error_detail 判断
                if "maximum context length" in error_detail.lower() or "token" in error_detail.lower():
                    error_msg = "输入内容过长，超出模型上下文限制"
                    error_code = "CONTEXT_LENGTH_EXCEEDED"
                elif "content_filter" in error_detail.lower() or "safety" in error_detail.lower():
                    error_msg = "内容审核未通过，请修改输入内容后重试"
                    error_code = "CONTENT_FILTER_ERROR"
                else:
                    error_msg = f"请求参数错误：{error_detail[:100]}"

            logger.error(
                f"LLM bad request for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "bad_request_error",
                    "error_detail": error_detail,
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except APIConnectionError as e:
            # 网络连接错误
            error_msg = "网络连接失败，请检查网络或稍后重试"
            logger.error(
                f"LLM connection failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "connection_error",
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except APIStatusError as e:
            # API 返回错误状态码
            error_msg = f"API服务异常（状态码：{e.status_code}），请稍后重试"
            logger.error(
                f"LLM API status error for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "api_status_error",
                    "status_code": e.status_code,
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except httpx.ConnectError as e:
            # httpx 连接错误（Ollama 等）
            error_msg = "无法连接到模型服务，请检查服务是否正常运行"
            logger.error(
                f"LLM service connection failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "service_connection_error",
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except AgentAssemblyError as e:
            # 装配失败（工具/提示词/Executor）：根本没走到模型，不能报成「模型调用失败」。
            # 必须排在通用 ``except Exception`` **之前**——Python 自上而下匹配，
            # 否则会先被通用分支吞掉，这里成为死代码。
            error_msg = f"智能体执行失败：{e}"
            logger.error(
                f"Agent assembly failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "agent_assembly_error",
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

        except Exception as e:
            # Ollama 特定错误处理
            error_str = str(e)
            if "OllamaEndpointNotFoundError" in error_str or ("Ollama" in error_str and "404" in error_str):
                error_msg = (
                    "Ollama 模型或端点不存在。请检查："
                    "1) Ollama 服务是否正在运行；"
                    "2) 模型名称是否正确（运行 'ollama list' 查看可用模型）；"
                    "3) 端点 URL 是否正确"
                )
                logger.error(
                    f"Ollama endpoint/model not found for agent {agent_id}: {e}",
                    extra={
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "error_type": "ollama_not_found_error",
                    },
                    exc_info=True,
                )
                raise LLMException(error_msg)

            # 其他未知错误
            error_msg = f"智能体执行失败：{str(e)[:300]}"
            logger.error(
                f"Unexpected LLM error for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "unknown_error",
                },
                exc_info=True,
            )
            raise LLMException(error_msg)

    async def chat_stream(
        self,
        agent_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行Agent对话（流式）

        Args:
            agent_id: Agent ID
            message: 当前用户消息
            conversation_id: 对话ID（可选）
            user_id: 用户ID（可选）
            history_messages: 前端传递的历史消息数组（可选），格式：[{"role": "user", "content": "..."}]
        """
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            RateLimitError,
            BadRequestError,
        )
        import httpx

        agent = self.get_agent(agent_id)

        # 构建LLM
        llm = self._build_llm_client(agent)
        tools = self._build_langchain_tools(agent)
        # 历史只含「当前轮之前」，当前消息统一由 {input} / 末尾 HumanMessage 传入
        chat_history = self._build_chat_history(conversation_id, message, history_messages)

        try:
            if tools:
                executor = self._build_tool_agent_executor(agent, tools, llm)
                # 工具路径与无工具路径统一成「内容块 + 用量」的异步序列，
                # 后面的打字机下发、token 记账、done 事件三者共用，避免两套逻辑漂移。
                stream_source = self._iter_tool_agent_output(
                    executor, {"input": message, "chat_history": chat_history}
                )
            else:
                messages = []
                if agent.system_prompt:
                    messages.append(SystemMessage(content=agent.system_prompt))

                # 添加对话历史（不含当前消息，故下面显式补当前消息）
                messages.extend(chat_history)
                messages.append(HumanMessage(content=message))

                stream_source = _iter_plain_llm_output(llm.astream(messages))

            # 流式生成
            full_content = ""
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

            async for item in stream_source:
                if item["type"] == "usage":
                    # 工具路径为多轮调用累加值；无工具路径为末块用量（此前行为）
                    prompt_tokens = item["input_tokens"]
                    completion_tokens = item["output_tokens"]
                    total_tokens = item["total_tokens"]
                    continue

                if item["type"] != "content":
                    # tool_start / tool_end：当前 SSE 契约里没有对应事件类型，
                    # 前端也无处渲染，先跳过（保留产出便于后续做"正在调用工具"提示）。
                    # 注意不能直接取 item["content"]——这些事件没有该键。
                    continue

                content = item["content"]
                if not content:
                    continue
                full_content += content

                # 打字机效果：将 LangChain 聚合后的大块内容按字符逐步下发，
                # 避免一次推送一整段导致“部分消息”式输出。
                for char in content:
                    yield {
                        "type": "message",
                        "content": char,
                    }

            # 返回完成信号
            total_tokens = prompt_tokens + completion_tokens

            # 记录Token使用情况
            if total_tokens > 0:
                self.token_usage_service.record_usage(
                    model_id=agent.model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                self._record_model_call(
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    model_id=agent.model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                self.db.commit()

            yield {
                "type": "done",
                # 此前这里回传的是 LangChain 的 chunk 对象（既不可 JSON 序列化，
                # 其 content 又只是最后一块），现已统一为完整正文
                "full_content": full_content,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }

        except AuthenticationError as e:
            # API 密钥无效或过期
            error_msg = "API认证失败，请检查API密钥是否有效"
            logger.error(
                f"LLM authentication failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "authentication_error",
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "AUTHENTICATION_ERROR",
            }

        except RateLimitError as e:
            # API 限流 - 提取具体的错误消息
            error_msg = _extract_openai_error_message(
                e, "API调用频率超限，请稍后重试"
            )
            error_detail = str(e)

            logger.error(
                f"LLM rate limit exceeded for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "rate_limit_error",
                    "error_detail": error_detail,
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "RATE_LIMIT_ERROR",
            }

        except BadRequestError as e:
            # 请求参数错误（如 token 超限、内容违规等）- 提取具体的错误消息
            error_detail = str(e)
            error_code = "BAD_REQUEST_ERROR"

            # 尝试提取 OpenAI 返回的具体消息
            error_msg = _extract_openai_error_message(e, "")

            if not error_msg:
                # 如果没有提取到具体消息，根据 error_detail 判断
                if "maximum context length" in error_detail.lower() or "token" in error_detail.lower():
                    error_msg = "输入内容过长，超出模型上下文限制"
                    error_code = "CONTEXT_LENGTH_EXCEEDED"
                elif "content_filter" in error_detail.lower() or "safety" in error_detail.lower():
                    error_msg = "内容审核未通过，请修改输入内容后重试"
                    error_code = "CONTENT_FILTER_ERROR"
                else:
                    error_msg = f"请求参数错误：{error_detail[:100]}"

            logger.error(
                f"LLM bad request for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "bad_request_error",
                    "error_detail": error_detail,
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": error_code,
            }

        except APIConnectionError as e:
            # 网络连接错误
            error_msg = "网络连接失败，请检查网络或稍后重试"
            logger.error(
                f"LLM connection failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "connection_error",
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "CONNECTION_ERROR",
            }

        except APIStatusError as e:
            # API 返回错误状态码
            error_msg = f"API服务异常（状态码：{e.status_code}），请稍后重试"
            logger.error(
                f"LLM API status error for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "api_status_error",
                    "status_code": e.status_code,
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "API_STATUS_ERROR",
            }

        except httpx.ConnectError as e:
            # httpx 连接错误（Ollama 等）
            error_msg = "无法连接到模型服务，请检查服务是否正常运行"
            logger.error(
                f"LLM service connection failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "service_connection_error",
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "SERVICE_CONNECTION_ERROR",
            }

        except AgentAssemblyError as e:
            # 装配失败（工具/提示词/Executor）：根本没走到模型，不能报成「模型调用失败」。
            # 必须排在通用 ``except Exception`` **之前**，否则会被其吞掉。
            error_msg = f"智能体执行失败：{e}"
            logger.error(
                f"Agent assembly failed for agent {agent_id}: {e}",
                extra={
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "error_type": "agent_assembly_error",
                },
                exc_info=True,
            )
            yield {
                "type": "error",
                "error": error_msg,
                "error_code": "AGENT_ASSEMBLY_ERROR",
            }

        except Exception as e:
            # Ollama 特定错误处理
            error_str = str(e)
            if "OllamaEndpointNotFoundError" in error_str or ("Ollama" in error_str and "404" in error_str):
                error_msg = (
                    "Ollama 模型或端点不存在。请检查："
                    "1) Ollama 服务是否正在运行；"
                    "2) 模型名称是否正确（运行 'ollama list' 查看可用模型）；"
                    "3) 端点 URL 是否正确"
                )
                logger.error(
                    f"Ollama endpoint/model not found for agent {agent_id}: {e}",
                    extra={
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "error_type": "ollama_not_found_error",
                    },
                    exc_info=True,
                )
                yield {
                    "type": "error",
                    "error": error_msg,
                    "error_code": "OLLAMA_NOT_FOUND_ERROR",
                }
            else:
                # 其他未知错误
                error_msg = f"智能体执行失败：{str(e)[:300]}"
                logger.error(
                    f"Unexpected LLM error for agent {agent_id}: {e}",
                    extra={
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "error_type": "unknown_error",
                    },
                    exc_info=True,
                )
                yield {
                    "type": "error",
                    "error": error_msg,
                    "error_code": "UNKNOWN_ERROR",
                }
