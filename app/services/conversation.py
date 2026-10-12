"""对话服务"""
from typing import Optional, List
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message
from app.repositories.conversation import ConversationRepository, MessageRepository
from app.core.exceptions import NotFoundException
from app.schemas.conversation import ConversationCreate, ConversationUpdate


class ConversationService:
    """对话服务"""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.conv_repo = ConversationRepository(db=db, tenant_id=tenant_id)
        self.msg_repo = MessageRepository(db=db, tenant_id=tenant_id)

    # ── Conversation CRUD ────────────────────────────────────────────────────

    def create_conversation(
        self,
        data: ConversationCreate,
        user_id: str,
    ) -> Conversation:
        """创建对话"""
        conv = self.conv_repo.create(
            agent_id=data.agent_id,
            title=data.title,
            created_by=user_id,
        )
        self.db.commit()
        return conv

    def get_conversation(self, conversation_id: str) -> Conversation:
        """获取对话详情"""
        conv = self.conv_repo.get_with_messages(conversation_id)
        if not conv:
            raise NotFoundException("Conversation", conversation_id)
        return conv

    def list_conversations(
        self,
        agent_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Conversation], int]:
        """列出对话"""
        convs = self.conv_repo.list_by_agent(agent_id=agent_id, page=page, page_size=page_size)
        total = self.conv_repo.count_by_agent(agent_id=agent_id)
        return convs, total

    def update_conversation(
        self,
        conversation_id: str,
        data: ConversationUpdate,
    ) -> Conversation:
        """更新对话"""
        conv = self.get_conversation(conversation_id)
        updates = data.model_dump(exclude_unset=True)
        if updates:
            self.conv_repo.update(conv, **updates)
        self.db.commit()
        return conv

    def delete_conversation(self, conversation_id: str) -> None:
        """删除对话"""
        conv = self.get_conversation(conversation_id)
        self.conv_repo.delete(conv)
        self.db.commit()

    # ── Message管理 ───────────────────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        tool_calls: Optional[List[dict]] = None,
        tool_call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        citations: Optional[List[dict]] = None,
    ) -> Message:
        """添加消息"""
        msg = self.msg_repo.create(
            conversation_id=conversation_id,
            role=role,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            citations=citations,
        )
        
        # 更新对话时间戳
        conv = self.conv_repo.get_by_id(conversation_id)
        if conv:
            self.conv_repo.update(conv, updated_at=datetime.utcnow())
        
        self.db.commit()
        return msg

    def get_messages(
        self,
        conversation_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[List[Message], int]:
        """获取对话消息"""
        messages = self.msg_repo.list_by_conversation(
            conversation_id=conversation_id, page=page, page_size=page_size
        )
        total = self.msg_repo.count_by_conversation(conversation_id=conversation_id)
        return messages, total

    def get_conversation_history(self, conversation_id: str) -> List[dict]:
        """获取对话历史（用于LLM上下文）"""
        messages = self.msg_repo.list_by_conversation(conversation_id=conversation_id, page=1, page_size=100)
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
