"""Agent服务"""
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
import logging
import uuid

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_tool import AgentTool
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.repositories.agent import AgentRepository, AgentToolRepository
from app.core.exceptions import NotFoundException, ValidationException
from app.schemas.agent import AgentCreate, AgentUpdate, AgentToolCreate
from app.utils import llm as llm_utils
from app.utils.encryption import decrypt
from app.services.knowledge import KnowledgeBaseService
from app.services.token_usage import TokenUsageService
from app.services.conversation import ConversationService
from app.services.audit import record_model_call

logger = logging.getLogger(__name__)


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
        user_id: uuid.UUID,
    ) -> Agent:
        """创建Agent"""
        # 验证AI模型存在
        model = self.db.query(AIModel).filter(
            AIModel.id == data.model_id,
            (AIModel.tenant_id == self.tenant_id) | (AIModel.tenant_id.is_(None)),
            AIModel.deleted_at.is_(None),
        ).first()
        if not model:
            raise NotFoundException("AIModel", data.model_id)

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
                (AIModel.tenant_id == self.tenant_id) | (AIModel.tenant_id.is_(None)),
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
            # 删除旧工具
            self.tool_repo.delete_by_agent(agent_id)
            # 创建新工具
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
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> None:
        """删除Agent"""
        agent = self.get_agent(agent_id)
        self.agent_repo.delete(agent)
        self.db.commit()

    # ── Agent工具构建 ───────────────────────────────────────────────────────

    def _build_langchain_tools(self, agent: Agent) -> List[Any]:
        """构建LangChain工具列表"""
        from langchain_core.tools import Tool

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
                
                def knowledge_search_func(query: str) -> str:
                    """知识库检索"""
                    results = kb_service.search(kb_id=kb_id, query_text=query, top_k=top_k)
                    if not results:
                        return "未找到相关知识"
                    return "\n".join([r.get("content", "") for r in results])

                tools.append(
                    Tool(
                        name=agent_tool.name,
                        description=agent_tool.description or f"搜索知识库 {kb_id}",
                        func=knowledge_search_func,
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
                        with _httpx.Client(timeout=_timeout) as client:
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
                        return f"API 调用异常：{str(e)}"

                tools.append(
                    Tool(
                        name=agent_tool.name,
                        description=agent_tool.description
                        or f"调用外部 API（{method} {url}）",
                        func=api_call_func,
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
                    Tool(
                        name=agent_tool.name,
                        description=agent_tool.description or f"执行自定义函数 {agent_tool.name}",
                        func=function_call_func,
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
                    Tool(
                        name=agent_tool.name,
                        description=agent_tool.description or f"执行工作流 {workflow_id}",
                        func=workflow_run_func,
                    )
                )

            # Plugin工具
            elif tool_type == "plugin":
                from app.services.plugin import PluginService
                from app.models.plugin import PluginEndpoint
                from app.utils.plugin_executor import execute_plugin_call

                plugin_id = config.get("plugin_id")
                if not plugin_id:
                    continue

                plugin_svc = PluginService(self.db, self.tenant_id)
                try:
                    plugin = plugin_svc.get(plugin_id)
                except Exception:
                    logger.warning("Agent 插件工具跳过：插件 %s 不存在", plugin_id)
                    continue

                # 解析目标端点：优先 endpoint_id，其次 endpoint 路径，最后取首个端点
                endpoint = None
                endpoint_id = config.get("endpoint_id")
                if endpoint_id:
                    endpoint = (
                        self.db.query(PluginEndpoint)
                        .filter(
                            PluginEndpoint.id == endpoint_id,
                            PluginEndpoint.plugin_id == plugin_id,
                        )
                        .first()
                    )
                if endpoint is None and config.get("endpoint"):
                    endpoint = (
                        self.db.query(PluginEndpoint)
                        .filter(
                            PluginEndpoint.plugin_id == plugin_id,
                            PluginEndpoint.endpoint == config.get("endpoint"),
                        )
                        .first()
                    )
                if endpoint is None:
                    endpoints = getattr(plugin, "_endpoints", None)
                    endpoint = endpoints[0] if endpoints else None
                if endpoint is None:
                    logger.warning("Agent 插件工具跳过：插件 %s 无可用端点", plugin_id)
                    continue

                method = config.get("method") or endpoint.method
                config_values = plugin_svc._load_config_dict(plugin_id)

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
                        return f"插件调用异常：{str(e)}"
                    if not result["success"]:
                        return f"插件调用失败：{result.get('error')}"
                    return json.dumps(result.get("data"), ensure_ascii=False, default=str)

                tools.append(
                    Tool(
                        name=agent_tool.name,
                        description=agent_tool.description or f"调用插件 {plugin.name}",
                        func=plugin_func,
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
        from langchain.agents import AgentExecutor, create_react_agent
        from langchain_core.prompts import PromptTemplate
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

        try:
            # 如果有工具，构建ReAct Agent
            if tools:
                # ReAct提示词模板
                template = """你是一个助手，可以使用工具完成任务。

可用工具:
{tools}

使用工具时，请遵循以下格式：
Thought: 思考下一步应该做什么
Action: 工具名称
Action Input: 工具输入参数
Observation: 工具执行结果
... (重复Thought/Action/Action Input/Observation直到完成)
Thought: 我现在知道最终答案了
Final Answer: 最终答案

开始！

问题: {input}
{agent_scratchpad}"""

                prompt = PromptTemplate.from_template(template)
                lc_agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
                agent_executor = AgentExecutor(agent=lc_agent, tools=tools, verbose=True)

                # 执行
                result = await agent_executor.ainvoke({"input": message})
                response_content = result.get("output", "")

                # Token统计（ReAct Agent暂不精确统计，后续可优化）
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
            else:
                # 无工具，直接对话
                messages = []
                if agent.system_prompt:
                    messages.append(SystemMessage(content=agent.system_prompt))

                # 添加对话历史
                # 优先使用前端传递的历史消息，如果没有则从数据库查询
                if history_messages:
                    # 使用前端传递的历史消息
                    for hist_msg in history_messages:
                        if hist_msg["role"] == "user":
                            messages.append(HumanMessage(content=hist_msg["content"]))
                        elif hist_msg["role"] == "assistant":
                            messages.append(AIMessage(content=hist_msg["content"]))
                elif conversation_id:
                    # 从数据库查询历史消息
                    # 注意：API 层会先添加用户消息到数据库，所以历史消息中已包含当前用户消息
                    history = self.conv_service.get_conversation_history(conversation_id)
                    # 检查最后一条消息是否是当前用户消息（避免重复添加）
                    last_is_current = (
                        history and
                        history[-1]["role"] == "user" and
                        history[-1]["content"] == message
                    )

                    # 添加历史消息
                    for hist_msg in history:
                        if hist_msg["role"] == "user":
                            messages.append(HumanMessage(content=hist_msg["content"]))
                        elif hist_msg["role"] == "assistant":
                            messages.append(AIMessage(content=hist_msg["content"]))

                    # 如果历史消息中没有当前用户消息，则添加
                    if not last_is_current:
                        messages.append(HumanMessage(content=message))
                else:
                    # 新对话，没有历史消息，直接添加当前用户消息
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
            error_msg = f"模型调用失败：{str(e)[:100]}"
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
        from langchain.agents import AgentExecutor, create_react_agent
        from langchain_core.prompts import PromptTemplate
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
 

        try:
            if tools:
                # ReAct提示词模板
                template = """你是一个助手，可以使用工具完成任务。

可用工具:
{tools}

使用工具时，请遵循以下格式：
Thought: 思考下一步应该做什么
Action: 工具名称
Action Input: 工具输入参数
Observation: 工具执行结果
... (重复Thought/Action/Action Input/Observation直到完成)
Thought: 我现在知道最终答案了
Final Answer: 最终答案

开始！

问题: {input}
{agent_scratchpad}"""

                prompt = PromptTemplate.from_template(template)
                lc_agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
                agent_executor = AgentExecutor(agent=lc_agent, tools=tools, verbose=True)

                # 执行
                response_content = await agent_executor.astream({"input": message})
                # response_content = result.get("output", "")
            else:
                messages = []
                if agent.system_prompt:
                    messages.append(SystemMessage(content=agent.system_prompt))

                # 添加对话历史
                # 优先使用前端传递的历史消息，如果没有则从数据库查询
                if history_messages:
                    # 调试日志：显示接收到的历史消息数量和内容
                    logger.info(
                        f"[DEBUG] Received history_messages: {len(history_messages)} items",
                        extra={
                            "agent_id": agent_id,
                            "conversation_id": conversation_id,
                            "history_count": len(history_messages),
                            "history_preview": [
                                {"role": msg.role, "content": msg.content[:50]}
                                for msg in history_messages[:3]
                            ],
                        }
                    )
                    # 使用前端传递的历史消息（Pydantic MessageBase 对象列表）
                    for hist_msg in history_messages:
                        if hist_msg.role == "user":
                            messages.append(HumanMessage(content=hist_msg.content))
                        elif hist_msg.role == "assistant":
                            messages.append(AIMessage(content=hist_msg.content))
                elif conversation_id:
                    # 从数据库查询历史消息
                    # 注意：API 层会先添加用户消息到数据库，所以历史消息中已包含当前用户消息
                    history = self.conv_service.get_conversation_history(conversation_id)
                    # 检查最后一条消息是否是当前用户消息（避免重复添加）
                    last_is_current = (
                        history and
                        history[-1]["role"] == "user" and
                        history[-1]["content"] == message
                    )

                    # 添加历史消息
                    for hist_msg in history:
                        if hist_msg["role"] == "user":
                            messages.append(HumanMessage(content=hist_msg["content"]))
                        elif hist_msg["role"] == "assistant":
                            messages.append(AIMessage(content=hist_msg["content"]))

                    # 如果历史消息中没有当前用户消息，则添加
                    if not last_is_current:
                        messages.append(HumanMessage(content=message))
                else:
                    # 新对话，没有历史消息，直接添加当前用户消息
                    messages.append(HumanMessage(content=message))

                # 流式生成
                full_content = ""
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                response_content = llm.astream(messages)
            async for chunk in response_content:
                content = chunk.content
                if not content:
                    continue
                full_content += content

                # 尝试获取Token统计（流式时可能不完整）
                usage = getattr(chunk, "usage_metadata", None) or {}
                if usage:
                    prompt_tokens = usage.get("input_tokens", 0)
                    completion_tokens = usage.get("output_tokens", 0)

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
                "content": chunk,
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
                error_msg = f"模型调用失败：{str(e)[:100]}"
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
