"""Agent API 路由"""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.authorization import AuthorizationService
from app.services.resource_authorization import (
    ResourceAuthorizationService,
    ResourceGrantService,
)
from app.core.dependencies import get_current_user, require_permission, require_tenant_user, CurrentUser, SessionDep
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.services.agent import AgentService
from app.services.conversation import ConversationService
from app.services.plugin import MAX_BINDABLE_PLUGINS, PluginService
from app.core.plugin_policy import DESTRUCTIVE_HTTP_METHODS
from app.schemas.common import ResponseBase, PaginatedResponse
from app.schemas.authorization import ResourceGrantCreate, ResourceGrantOut
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentListResponse,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationListResponse,
    ChatRequest,
    ChatResponse,
)
from app.utils.sse import create_sse_response, json_sse_event
from app.core.exceptions import AppException

router = APIRouter(dependencies=[Depends(require_tenant_user)])


def _merge_tool_call_traces(
    current: list[dict] | None,
    incoming: list[dict] | None,
) -> list[dict] | None:
    """合并工具生命周期快照，保留正常调用的完整输入、输出与状态。

    SSE 生命周期事件和 Agent ``done`` 摘要来自两条独立路径。不能用其中一条
    truthy 的列表覆盖另一条，否则 ``done`` 只带起始状态时会丢掉已完成调用的
    output/status，仪表盘后续也无法正确统计成功率。
    """
    if not current and not incoming:
        return None

    merged = [dict(item) for item in (current or []) if isinstance(item, dict)]
    for item in incoming or []:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        call_id = candidate.get("call_id")
        existing = next(
            (entry for entry in merged if call_id and entry.get("call_id") == call_id),
            None,
        )
        if existing is None:
            merged.append(candidate)
        else:
            # done 摘要可能比实时 tool_end 更早/更粗，只允许它补充缺失字段，
            # 不得把已经完成的 success/error 回退成 running。
            if (
                existing.get("status") in {"success", "error"}
                and candidate.get("status") == "running"
            ):
                candidate.pop("status", None)
            existing.update(candidate)
    return merged


def _authorize_agent(
    db: Session,
    current_user: User,
    agent,
    action: str,
) -> None:
    ResourceAuthorizationService(db).require(
        current_user,
        current_user.tenant_id,
        "agent",
        action,
        agent,
    )


def _agent_payload(db: Session, current_user: User, agent) -> dict:
    payload = AgentResponse.model_validate(agent).model_dump()
    payload["allowed_actions"] = ResourceAuthorizationService(db).allowed_actions(
        current_user,
        current_user.tenant_id,
        "agent",
        agent,
    )
    has_explicit_knowledge = any(
        getattr(tool, "tool_type", None) == "knowledge"
        for tool in getattr(agent, "tools", None) or []
    )
    if not has_explicit_knowledge:
        payload["default_knowledge_base_count"] = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.tenant_id == current_user.tenant_id,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.chunk_count > 0,
            )
            .count()
        )
    return payload


# ============ Agent CRUD ============


@router.post(
    "/agents",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "create"))],
)
async def create_agent(
    data: AgentCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """创建Agent"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        agent = service.create_agent(data=data, user_id=current_user.id)
        return ResponseBase.ok(
            data=_agent_payload(db, current_user, agent)
        )
    except AppException as e:
        raise e


@router.get(
    "/agents",
    response_model=PaginatedResponse,
    dependencies=[Depends(require_permission("agent", "read"))],
)
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """列出Agents"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        can_manage_drafts = (await AuthorizationService(db).check_permission_async(
            current_user,
            current_user.tenant_id,
            "agent",
            "update",
        )).allowed
        if not can_manage_drafts:
            status = "published"
        agents, total = service.list_agents(page=page, page_size=page_size, status=status)
        
        items = []
        for agent in agents:
            agent_dict = _agent_payload(db, current_user, agent)
            items.append(agent_dict)
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except AppException as e:
        raise e


@router.get(
    "/agents/tool-catalog",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "create"))],
)
async def get_agent_tool_catalog(
    keyword: Optional[str] = Query(None, max_length=100, description="按插件名称模糊搜索"),
    limit: int = Query(MAX_BINDABLE_PLUGINS, ge=1, le=500, description="返回上限"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取可授权给 Agent 的插件候选目录。

    这是**设计期**的候选面：回答「用户能给这个 Agent 选什么」，而不是「插件仓库里有什么」。
    服务端已按 归属 / 状态 / 接入方式 / 端点数量 裁剪，因此前端只需展示，不需要自行判断
    哪些插件可用——否则口径会随两端实现漂移。

    ⚠️ 路由顺序：本路由必须声明在 ``/agents/{agent_id}`` **之前**。FastAPI 按注册顺序
    匹配，若置于其后，``/agents/tool-catalog`` 会被 ``/agents/{agent_id}`` 当成
    ``agent_id="tool-catalog"`` 吞掉（表现为 404 或把目录名当 ID 查询）。
    """
    try:
        service = PluginService(db=db, tenant_id=current_user.tenant_id)
        bindable = service.list_bindable_for_agent(
            keyword=keyword, limit=limit
        )
        items = [
            {
                "id": plugin.id,
                "name": plugin.name,
                "source_type": plugin.source_type,
                "description": plugin.description,
                "icon": plugin.icon,
                # tenant_id 为 NULL 即平台公共插件，前端据此提示「平台内置」
                "is_public": plugin.tenant_id is None,
                "endpoints": [
                    {
                        "id": endpoint.id,
                        "endpoint": endpoint.endpoint,
                        "method": endpoint.method,
                        "description": endpoint.description,
                        "is_destructive": endpoint.method.upper()
                        in DESTRUCTIVE_HTTP_METHODS,
                    }
                    for endpoint in endpoints
                ],
            }
            for plugin, endpoints in bindable
        ]
        return ResponseBase.ok(data=items)
    except AppException as e:
        raise e


@router.get(
    "/agents/{agent_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "read"))],
)
async def get_agent(
    agent_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取Agent详情"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        agent = service.get_agent(agent_id)
        _authorize_agent(db, current_user, agent, "read")
        return ResponseBase.ok(
            data=_agent_payload(db, current_user, agent)
        )
    except AppException as e:
        raise e


@router.put(
    "/agents/{agent_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "update"))],
)
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """更新Agent"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        existing_agent = service.get_agent(agent_id)
        authorization_action = (
            "publish"
            if data.status == "published" and existing_agent.status != "published"
            else "update"
        )
        _authorize_agent(db, current_user, existing_agent, authorization_action)
        agent = service.update_agent(agent_id=agent_id, data=data)
        return ResponseBase.ok(
            data=_agent_payload(db, current_user, agent)
        )
    except AppException as e:
        raise e


@router.delete(
    "/agents/{agent_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "delete"))],
)
async def delete_agent(
    agent_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除Agent"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        _authorize_agent(db, current_user, service.get_agent(agent_id), "delete")
        service.delete_agent(agent_id)
        return ResponseBase.ok(message="Agent deleted successfully")
    except AppException as e:
        raise e


@router.post("/agents/{agent_id}/grants", response_model=ResponseBase)
async def create_agent_grant(
    agent_id: str,
    data: ResourceGrantCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        agent = service.get_agent(agent_id)
        grant = ResourceGrantService(db).create_grant(
            current_user,
            current_user.tenant_id,
            "agent",
            agent,
            subject_role_id=data.subject_role_id,
            actions=data.actions,
            expires_at=data.expires_at,
        )
        db.commit()
        db.refresh(grant)
        return ResponseBase.ok(data=ResourceGrantOut.model_validate(grant).model_dump())
    except AppException as e:
        raise e


@router.delete("/agents/{agent_id}/grants/{grant_id}", response_model=ResponseBase)
async def revoke_agent_grant(
    agent_id: str,
    grant_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        service.get_agent(agent_id)
        grant = ResourceGrantService(db).revoke_grant(
            current_user,
            current_user.tenant_id,
            grant_id,
            resource="agent",
            resource_id=agent_id,
        )
        db.commit()
        db.refresh(grant)
        return ResponseBase.ok(data=ResourceGrantOut.model_validate(grant).model_dump())
    except AppException as e:
        raise e


# ============ Conversation CRUD ============


@router.post(
    "/conversations",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """创建对话"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        conv = service.create_conversation(data=data, user_id=current_user.id)
        return ResponseBase.ok(
            data=ConversationResponse.model_validate(conv).model_dump()
        )
    except AppException as e:
        raise e


@router.get(
    "/agents/{agent_id}/conversations",
    response_model=PaginatedResponse,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def list_conversations(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """列出对话"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        convs, total = service.list_conversations(
            agent_id=agent_id, page=page, page_size=page_size
        )
        
        items = []
        for conv in convs:
            conv_dict = ConversationResponse.model_validate(conv).model_dump()
            items.append(conv_dict)
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except AppException as e:
        raise e


@router.get(
    "/conversations/{conversation_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取对话详情"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        conv = service.get_conversation(conversation_id)
        return ResponseBase.ok(
            data=ConversationResponse.model_validate(conv).model_dump()
        )
    except AppException as e:
        raise e


@router.put(
    "/conversations/{conversation_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """更新对话"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        conv = service.update_conversation(conversation_id=conversation_id, data=data)
        return ResponseBase.ok(
            data=ConversationResponse.model_validate(conv).model_dump()
        )
    except AppException as e:
        raise e


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除对话"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        service.delete_conversation(conversation_id)
        return ResponseBase.ok(message="Conversation deleted successfully")
    except AppException as e:
        raise e


# ============ Chat API ============


@router.post(
    "/agents/{agent_id}/chat",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def chat(
    agent_id: str,
    data: ChatRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Agent对话（阻塞式）"""
    try:
        agent_service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        agent = agent_service.get_agent(agent_id)
        _authorize_agent(db, current_user, agent, "chat")
        conv_service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)

        # 如果没有提供conversation_id，创建新对话
        conversation_id = data.conversation_id
        if not conversation_id:
            conv = conv_service.create_conversation(
                data=ConversationCreate(agent_id=agent_id),
                user_id=current_user.id,
            )
            conversation_id = conv.id

        # 添加用户消息
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=data.message,
        )

        # 调用Agent
        result = await agent_service.chat(
            agent_id=agent_id,
            message=data.message,
            conversation_id=conversation_id,
            user_id=current_user.id,
            history_messages=data.messages,
        )

        # 添加助手消息（含引用溯源，无引用时 citations 为 None）
        assistant_msg = conv_service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=result["content"],
            tool_calls=result.get("tool_calls"),
            citations=result.get("citations"),
        )

        return ResponseBase.ok(
            data={
                "conversation_id": conversation_id,
                "message": MessageResponse.model_validate(assistant_msg).model_dump(),
            }
        )
    except AppException as e:
        raise e


@router.post(
    "/agents/{agent_id}/chat/stream",
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def chat_stream(
    agent_id: str,
    data: ChatRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Agent对话（SSE流式）"""
    try:
        agent_service = AgentService(db=db, tenant_id=current_user.tenant_id, actor=current_user)
        agent = agent_service.get_agent(agent_id)
        _authorize_agent(db, current_user, agent, "chat")
        conv_service = ConversationService(db=db, tenant_id=current_user.tenant_id, actor=current_user)

        # 如果没有提供conversation_id，创建新对话
        conversation_id = data.conversation_id
        if not conversation_id:
            conv = conv_service.create_conversation(
                data=ConversationCreate(agent_id=agent_id),
                user_id=current_user.id,
            )
            conversation_id = conv.id

        # 添加用户消息
        conv_service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=data.message,
        )

        async def event_generator():
            """SSE事件生成器"""
            full_content = ""
            tool_calls = None
            assistant_message_persisted = False

            def persist_partial_tool_trace(error_message: str) -> None:
                """保留已发生的工具轨迹，避免失败流让工作台看起来像未调用。"""
                nonlocal assistant_message_persisted
                if assistant_message_persisted or not tool_calls:
                    return
                conv_service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_content or error_message,
                    tool_calls=tool_calls,
                )
                assistant_message_persisted = True

            try:
                async for chunk in agent_service.chat_stream(
                    agent_id=agent_id,
                    message=data.message,
                    conversation_id=conversation_id,
                    user_id=current_user.id,
                    history_messages=data.messages,
                ):
                    if chunk["type"] == "message":
                        full_content += chunk["content"]
                        yield json_sse_event(
                            "message",
                            {"content": chunk["content"]},
                        )
                    elif chunk["type"] == "citations":
                        # 检索命中来源，先于正文推送，便于前端边生成边展示来源面板
                        yield json_sse_event(
                            "citations",
                            {
                                "tool": chunk.get("tool"),
                                "citations": chunk.get("citations"),
                            },
                        )
                    elif chunk["type"] in {"tool_start", "tool_end", "tool_error"}:
                        # 工具生命周期事件是独立的 SSE 类型：前端可在助手回复气泡内
                        # 展示实时执行轨迹，同时 done 事件中的摘要可落库供仪表盘聚合。
                        tool_calls = _merge_tool_call_traces(
                            tool_calls,
                            [{key: value for key, value in chunk.items() if key != "type"}],
                        )
                        yield json_sse_event(
                            chunk["type"],
                            {key: value for key, value in chunk.items() if key != "type"},
                        )
                    elif chunk["type"] == "done":
                        tool_calls = _merge_tool_call_traces(
                            tool_calls,
                            chunk.get("tool_calls"),
                        )
                        # 添加助手消息（含引用溯源，无引用时 citations 为 None）
                        conv_service.add_message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=full_content,
                            tool_calls=tool_calls,
                            citations=chunk.get("citations"),
                        )
                        assistant_message_persisted = True
                        done_data = {"conversation_id": conversation_id}
                        # done 事件冗余携带完整 citations，作为前端丢包的兜底
                        if chunk.get("citations"):
                            done_data["citations"] = chunk["citations"]
                        yield json_sse_event("done", done_data)
                    elif chunk["type"] == "error":
                        # 错误事件：直接转发 Service 层的错误信息
                        persist_partial_tool_trace(
                            chunk.get("error", "工具调用后执行失败")
                        )
                        yield json_sse_event(
                            "error",
                            {
                                "error": chunk.get("error", "模型调用失败"),
                                "error_code": chunk.get("error_code", "UNKNOWN_ERROR"),
                            },
                        )
            except Exception as e:
                # 捕获其他未预期的异常（如数据库错误等）
                import logging
                persist_partial_tool_trace("系统内部错误，请稍后重试")
                logging.error(
                    f"Unexpected error in SSE generator: {e}",
                    exc_info=True,
                )
                yield json_sse_event(
                    "error",
                    {
                        "error": "系统内部错误，请稍后重试",
                        "error_code": "SYSTEM_ERROR",
                    },
                )

        return create_sse_response(event_generator())
    except AppException as e:
        raise e
