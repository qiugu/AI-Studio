"""Agent API 路由"""
import json
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import get_current_user, require_permission, CurrentUser, SessionDep
from app.models.user import User
from app.services.agent import AgentService
from app.services.conversation import ConversationService
from app.services.plugin import MAX_BINDABLE_PLUGINS, PluginService
from app.core.plugin_policy import DESTRUCTIVE_HTTP_METHODS
from app.schemas.common import ResponseBase, PaginatedResponse
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentListResponse,
)
from app.schemas.stream import StreamChunk
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationListResponse,
    ChatRequest,
    ChatResponse,
)
from app.utils.llm import encode
from app.core.exceptions import AppException

router = APIRouter()


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
        service = AgentService(db=db, tenant_id=current_user.tenant_id)
        agent = service.create_agent(data=data, user_id=current_user.id)
        return ResponseBase.ok(
            data=AgentResponse.model_validate(agent).model_dump()
        )
    except AppException as e:
        raise e


@router.get(
    "/agents",
    response_model=PaginatedResponse,
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
        service = AgentService(db=db, tenant_id=current_user.tenant_id)
        agents, total = service.list_agents(page=page, page_size=page_size, status=status)
        
        items = []
        for agent in agents:
            agent_dict = AgentResponse.model_validate(agent).model_dump()
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
)
async def get_agent(
    agent_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取Agent详情"""
    try:
        service = AgentService(db=db, tenant_id=current_user.tenant_id)
        agent = service.get_agent(agent_id)
        return ResponseBase.ok(
            data=AgentResponse.model_validate(agent).model_dump()
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
        service = AgentService(db=db, tenant_id=current_user.tenant_id)
        agent = service.update_agent(agent_id=agent_id, data=data)
        return ResponseBase.ok(
            data=AgentResponse.model_validate(agent).model_dump()
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
        service = AgentService(db=db, tenant_id=current_user.tenant_id)
        service.delete_agent(agent_id)
        return ResponseBase.ok(message="Agent deleted successfully")
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
        service = ConversationService(db=db, tenant_id=current_user.tenant_id)
        conv = service.create_conversation(data=data, user_id=current_user.id)
        return ResponseBase.ok(
            data=ConversationResponse.model_validate(conv).model_dump()
        )
    except AppException as e:
        raise e


@router.get(
    "/agents/{agent_id}/conversations",
    response_model=PaginatedResponse,
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
        service = ConversationService(db=db, tenant_id=current_user.tenant_id)
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
)
async def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取对话详情"""
    try:
        service = ConversationService(db=db, tenant_id=current_user.tenant_id)
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
        service = ConversationService(db=db, tenant_id=current_user.tenant_id)
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
        service = ConversationService(db=db, tenant_id=current_user.tenant_id)
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
        agent_service = AgentService(db=db, tenant_id=current_user.tenant_id)
        conv_service = ConversationService(db=db, tenant_id=current_user.tenant_id)

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
    # response_model=StreamingResponse
)
async def chat_stream(
    agent_id: str,
    data: ChatRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Agent对话（SSE流式）"""
    try:
        agent_service = AgentService(db=db, tenant_id=current_user.tenant_id)
        conv_service = ConversationService(db=db, tenant_id=current_user.tenant_id)

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
                        yield encode(
                            StreamChunk(
                                event="message",
                                data=json.dumps({ 'content': chunk["content"] }, ensure_ascii=False),
                            )
                        )
                    elif chunk["type"] == "citations":
                        # 检索命中来源，先于正文推送，便于前端边生成边展示来源面板
                        yield encode(
                            StreamChunk(
                                event="citations",
                                data=json.dumps({
                                    "tool": chunk.get("tool"),
                                    "citations": chunk.get("citations"),
                                }, ensure_ascii=False),
                            )
                        )
                    elif chunk["type"] == "done":
                        # 添加助手消息（含引用溯源，无引用时 citations 为 None）
                        conv_service.add_message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=full_content,
                            citations=chunk.get("citations"),
                        )
                        done_data = {"conversation_id": conversation_id}
                        # done 事件冗余携带完整 citations，作为前端丢包的兜底
                        if chunk.get("citations"):
                            done_data["citations"] = chunk["citations"]
                        yield encode(
                            StreamChunk(
                                event="done",
                                data=json.dumps(done_data, ensure_ascii=False)
                            )
                        )
                    elif chunk["type"] == "error":
                        # 错误事件：直接转发 Service 层的错误信息
                        yield encode(
                            StreamChunk(
                                event="error",
                                data=json.dumps({
                                    "error": chunk.get("error", "模型调用失败"),
                                    "error_code": chunk.get("error_code", "UNKNOWN_ERROR"),
                                }, ensure_ascii=False),
                            )
                        )
            except Exception as e:
                # 捕获其他未预期的异常（如数据库错误等）
                import logging
                logging.error(
                    f"Unexpected error in SSE generator: {e}",
                    exc_info=True,
                )
                yield encode(
                    StreamChunk(
                        event="error",
                        data=json.dumps({
                            "error": "系统内部错误，请稍后重试",
                            "error_code": "SYSTEM_ERROR",
                        }, ensure_ascii=False),
                    )
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                # 关闭代理层（Nginx 等）的响应缓冲，保证逐块推送
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    except AppException as e:
        raise e
