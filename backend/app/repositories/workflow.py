from typing import Optional, List
import uuid
from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository
from app.models.workflow import Workflow
from app.models.workflow_node import WorkflowNode
from app.models.workflow_edge import WorkflowEdge


class WorkflowRepository(BaseRepository[Workflow]):
    """工作流Repository"""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        super().__init__(Workflow, db, tenant_id)

    def get_by_id(self, resource_id: uuid.UUID) -> Optional[Workflow]:
        return (
            self.db.query(self.model)
            .filter(self._tenant_filter(), self.model.id == resource_id)
            .first()
        )

    def get_with_nodes_and_edges(self, workflow_id: uuid.UUID) -> Optional[Workflow]:
        """获取工作流及其节点和边"""
        workflow = self.get_by_id(workflow_id)
        if workflow:
            _ = workflow.nodes
            _ = workflow.edges
        return workflow

    def list_by_status(
        self, status: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> List[Workflow]:
        """按状态列出工作流"""
        return self.list(page=page, page_size=page_size, status=status)

    def count_by_status(self, status: Optional[str] = None) -> int:
        """按状态计数"""
        return self.count(status=status)


class WorkflowNodeRepository(BaseRepository[WorkflowNode]):
    """工作流节点Repository"""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        super().__init__(WorkflowNode, db, tenant_id)

    def list_by_workflow(self, workflow_id: uuid.UUID) -> List[WorkflowNode]:
        """获取工作流的所有节点"""
        return self.db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.tenant_id == self.tenant_id,
        ).all()

    def delete_by_workflow(self, workflow_id: uuid.UUID) -> None:
        """删除工作流的所有节点"""
        self.db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.tenant_id == self.tenant_id,
        ).delete()
        self.db.flush()


class WorkflowEdgeRepository(BaseRepository[WorkflowEdge]):
    """工作流边Repository"""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        super().__init__(WorkflowEdge, db, tenant_id)

    def list_by_workflow(self, workflow_id: uuid.UUID) -> List[WorkflowEdge]:
        """获取工作流的所有边"""
        return self.db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == workflow_id,
            WorkflowEdge.tenant_id == self.tenant_id,
        ).all()

    def delete_by_workflow(self, workflow_id: uuid.UUID) -> None:
        """删除工作流的所有边"""
        self.db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == workflow_id,
            WorkflowEdge.tenant_id == self.tenant_id,
        ).delete()
        self.db.flush()
