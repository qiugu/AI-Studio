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

    def delete_by_agent(self, agent_id: str, tool_type: Optional[str] = None) -> None:
        """删除 Agent 的工具。

        ``tool_type`` 为 ``None`` 时删除全部（兼容旧调用）；指定类型时仅删除该类型，
        用于「更新 Agent 时只重建 plugin 类工具、保留 knowledge/api/function/workflow
        等其它类型」的场景（修复 §3.1：UI 仅提交 plugin 工具时会误删其它类型）。
        """
        filters = [
            AgentTool.tenant_id == self.tenant_id,
            AgentTool.agent_id == agent_id,
        ]
        if tool_type is not None:
            filters.append(AgentTool.tool_type == tool_type)
        self.db.query(AgentTool).filter(and_(*filters)).delete(
            synchronize_session=False
        )
        self.db.flush()
