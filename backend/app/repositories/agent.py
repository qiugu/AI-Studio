from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.repositories.base import BaseRepository
from app.models.agent import Agent
from app.models.agent_tool import AgentTool


class AgentRepository(BaseRepository[Agent]):
    """Agent Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(Agent, db, tenant_id)

    def get_with_tools(self, agent_id: str) -> Optional[Agent]:
        """获取Agent及其工具"""
        return (
            self.db.query(Agent)
            .filter(self._tenant_filter(), Agent.id == agent_id)
            .first()
        )

    def list_by_status(
        self, status: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> List[Agent]:
        """按状态列出Agent"""
        query = self.db.query(Agent).filter(self._tenant_filter())
        if status:
            query = query.filter(Agent.status == status)
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_status(self, status: Optional[str] = None) -> int:
        """按状态统计Agent数量"""
        query = self.db.query(Agent).filter(self._tenant_filter())
        if status:
            query = query.filter(Agent.status == status)
        return query.count()


class AgentToolRepository(BaseRepository[AgentTool]):
    """AgentTool Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(AgentTool, db, tenant_id)

    def list_by_agent(self, agent_id: str) -> List[AgentTool]:
        """获取Agent的所有工具"""
        return (
            self.db.query(AgentTool)
            .filter(self._tenant_filter(), AgentTool.agent_id == agent_id)
            .all()
        )

    def delete_by_agent(self, agent_id: str) -> None:
        """删除Agent的所有工具"""
        self.db.query(AgentTool).filter(
            and_(AgentTool.tenant_id == self.tenant_id, AgentTool.agent_id == agent_id)
        ).delete(synchronize_session=False)
        self.db.flush()
