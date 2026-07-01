"""Agent服务"""
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
import logging

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

    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
        self.agent_repo = AgentRepository(db=db, tenant_id=tenant_id)
        self.tool_repo = AgentToolRepository(db=db, tenant_id=tenant_id)
        self.token_usage_service = TokenUsageService(db=db, tenant_id=tenant_id)
        self.conv_service = ConversationService(db=db, tenant_id=tenant_id)

    # ── Agent CRUD ───────────────────────────────────────────────────────────

    def create_agent(
        self,
        data: AgentCreate,
        user_id: int,
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

    def get_agent(self, agent_id: int) -> Agent:
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
        agent_id: int,
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

    def delete_agent(self, agent_id: int) -> None:
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
                # 暂不实现，阶段7会完整实现插件系统
                pass

            # Function工具
            elif tool_type == "function":
                # 暂不实现，需要代码沙盒
                pass

            # Workflow工具
            elif tool_type == "workflow":
                # 暂不实现，阶段6会实现工作流引擎
                pass

            # Plugin工具
            elif tool_type == "plugin":
                # 暂不实现，阶段7会完整实现插件系统
                pass

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
        agent_id: int,
        message: str,
        conversation_id: Optional[int] = None,
        user_id: Optional[int] = None,
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
        agent_id: int,
        message: str,
        conversation_id: Optional[int] = None,
        user_id: Optional[int] = None,
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
        import httpx
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            RateLimitError,
            BadRequestError,
        )

        agent = self.get_agent(agent_id)

        # 构建LLM
        llm = self._build_llm_client(agent)
        tools = self._build_langchain_tools(agent)

        # 暂时简化：直接使用LLM流式（后续可集成ReAct Agent流式）
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

        try:
            async for chunk in llm.astream(messages):
                content = chunk.content
                full_content += content

                # 尝试获取Token统计（流式时可能不完整）
                usage = getattr(chunk, "usage_metadata", None) or {}
                if usage:
                    prompt_tokens = usage.get("input_tokens", 0)
                    completion_tokens = usage.get("output_tokens", 0)

                yield {
                    "type": "message",
                    "content": content,
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
