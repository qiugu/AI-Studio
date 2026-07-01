from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.repositories.base import BaseRepository
from app.models.conversation import Conversation
from app.models.message import Message


class ConversationRepository(BaseRepository[Conversation]):
    """Conversation Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(Conversation, db, tenant_id)

    def get_with_messages(self, conversation_id: int) -> Optional[Conversation]:
        """获取对话及其消息"""
        return (
            self.db.query(Conversation)
            .filter(self._tenant_filter(), Conversation.id == conversation_id)
            .first()
        )

    def list_by_agent(
        self, agent_id: int, page: int = 1, page_size: int = 20
    ) -> List[Conversation]:
        """获取Agent的所有对话"""
        query = (
            self.db.query(Conversation)
            .filter(self._tenant_filter(), Conversation.agent_id == agent_id)
            .order_by(desc(Conversation.updated_at))
        )
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_agent(self, agent_id: int) -> int:
        """统计Agent的对话数量"""
        return (
            self.db.query(Conversation)
            .filter(self._tenant_filter(), Conversation.agent_id == agent_id)
            .count()
        )


class MessageRepository(BaseRepository[Message]):
    """Message Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(Message, db, tenant_id)

    def list_by_conversation(
        self, conversation_id: int, page: int = 1, page_size: int = 50
    ) -> List[Message]:
        """获取对话的所有消息"""
        query = (
            self.db.query(Message)
            .filter(self._tenant_filter(), Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_conversation(self, conversation_id: int) -> int:
        """统计对话的消息数量"""
        return (
            self.db.query(Message)
            .filter(self._tenant_filter(), Message.conversation_id == conversation_id)
            .count()
        )

    def get_last_message(self, conversation_id: int) -> Optional[Message]:
        """获取对话的最后一条消息"""
        return (
            self.db.query(Message)
            .filter(self._tenant_filter(), Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .first()
        )