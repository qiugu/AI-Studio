from typing import Optional, List, Dict, Any, Sequence
import logging
import uuid

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.repositories.workflow import WorkflowRepository, WorkflowNodeRepository, WorkflowEdgeRepository
from app.core.exceptions import NotFoundException, ValidationException
from app.core.authorization import AuthorizationService
from app.models.user import User
from app.services.resource_authorization import ResourceAuthorizationService
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate

logger = logging.getLogger(__name__)


class WorkflowService:
    """工作流服务"""

    def __init__(self, db: Session, tenant_id: str, actor: User | None = None):
        self.db = db
        self.tenant_id = str(tenant_id)
        self.actor = actor
        self.resource_authorization = ResourceAuthorizationService(db)
        self.workflow_repo = WorkflowRepository(db=db, tenant_id=self.tenant_id)
        self.node_repo = WorkflowNodeRepository(db=db, tenant_id=self.tenant_id)
        self.edge_repo = WorkflowEdgeRepository(db=db, tenant_id=self.tenant_id)

    # ── Workflow CRUD ───────────────────────────────────────────────────────────

    def create_workflow(
        self,
        data: WorkflowCreate,
        user_id: str,
    ) -> Workflow:
        """创建工作流"""
        if getattr(self, "actor", None) is not None:
            AuthorizationService(self.db).require_permission(
                self.actor, self.tenant_id, "workflow", "create"
            )
        try:
            workflow = self.workflow_repo.create(
                name=data.name,
                description=data.description,
                status="draft",
                created_by=str(user_id),
            )
            if data.nodes is not None or data.edges is not None:
                self._replace_graph(workflow, data.nodes or [], data.edges or [])
            self.db.commit()
            self._expire_graph(workflow)
            return self.get_workflow(workflow.id, authorize=False)
        except Exception:
            self.db.rollback()
            raise

    def get_workflow(
        self,
        workflow_id: str | uuid.UUID,
        *,
        authorize: bool = True,
    ) -> Workflow:
        """获取工作流详情"""
        workflow_id = str(workflow_id)
        workflow = self.workflow_repo.get_with_nodes_and_edges(workflow_id)
        if not workflow:
            raise NotFoundException("Workflow", workflow_id)
        if authorize and getattr(self, "actor", None) is not None:
            self.resource_authorization.require(
                self.actor,
                self.tenant_id,
                "workflow",
                "read",
                workflow,
            )
        return workflow

    def list_workflows(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[List[Workflow], int]:
        """列出工作流"""
        if getattr(self, "actor", None) is not None:
            AuthorizationService(self.db).require_permission(
                self.actor, self.tenant_id, "workflow", "read"
            )
        workflows = self.workflow_repo.list_by_status(status=status, page=page, page_size=page_size)
        total = self.workflow_repo.count_by_status(status=status)
        return workflows, total

    def update_workflow(
        self,
        workflow_id: str | uuid.UUID,
        data: WorkflowUpdate,
    ) -> Workflow:
        """更新工作流"""
        workflow_id = str(workflow_id)
        workflow = self.get_workflow(workflow_id, authorize=False)
        if getattr(self, "actor", None) is not None:
            self.resource_authorization.require(
                self.actor, self.tenant_id, "workflow", "update", workflow
            )

        try:
            updates = data.model_dump(exclude={"nodes", "edges"}, exclude_unset=True)
            if updates:
                self.workflow_repo.update(workflow, **updates)

            if data.nodes is not None:
                self._replace_graph(workflow, data.nodes, data.edges or [])
            elif data.edges is not None:
                self._replace_edges(workflow, data.edges)

            self.db.commit()
            self._expire_graph(workflow)
            return self.get_workflow(workflow_id, authorize=False)
        except Exception:
            self.db.rollback()
            raise

    def _replace_graph(self, workflow: Workflow, nodes: Sequence, edges: Sequence) -> None:
        """整图替换并把客户端节点引用映射到新生成的 UUID。"""
        workflow_id = str(workflow.id)
        self.edge_repo.delete_by_workflow(workflow_id)
        self.node_repo.delete_by_workflow(workflow_id)

        node_id_map: Dict[str, str] = {}
        for node_data in nodes:
            client_id = node_data.temp_id
            if client_id and client_id in node_id_map:
                raise ValidationException(f"节点引用重复: {client_id}")

            node = self.node_repo.create(
                workflow_id=workflow_id,
                node_type=node_data.node_type,
                name=node_data.name,
                position_x=node_data.position_x,
                position_y=node_data.position_y,
                config=node_data.config,
            )
            persisted_id = str(node.id)
            node_id_map[persisted_id] = persisted_id
            if client_id:
                node_id_map[client_id] = persisted_id

        self._create_edges(workflow_id, edges, node_id_map)

    def _replace_edges(self, workflow: Workflow, edges: Sequence) -> None:
        """仅替换连线时，端点必须引用当前工作流已有节点。"""
        workflow_id = str(workflow.id)
        node_id_map = {str(node.id): str(node.id) for node in workflow.nodes}
        self.edge_repo.delete_by_workflow(workflow_id)
        self._create_edges(workflow_id, edges, node_id_map)

    def _create_edges(
        self,
        workflow_id: str,
        edges: Sequence,
        node_id_map: Dict[str, str],
    ) -> None:
        for edge_data in edges:
            source_ref = str(edge_data.source_node_id)
            target_ref = str(edge_data.target_node_id)
            source_id = node_id_map.get(source_ref)
            target_id = node_id_map.get(target_ref)
            if source_id is None or target_id is None:
                missing = source_ref if source_id is None else target_ref
                raise ValidationException(f"连线引用了不存在的节点: {missing}")
            self.edge_repo.create(
                workflow_id=workflow_id,
                source_node_id=source_id,
                target_node_id=target_id,
                source_handle=edge_data.source_handle,
                target_handle=edge_data.target_handle,
                condition=edge_data.condition,
                label=edge_data.label,
            )

    def _expire_graph(self, workflow: Workflow) -> None:
        """避免整图替换后返回 Session identity map 中的旧关系集合。"""
        self.db.expire(workflow, ["nodes", "edges"])

    def delete_workflow(self, workflow_id: str | uuid.UUID) -> None:
        """删除工作流"""
        workflow = self.get_workflow(workflow_id, authorize=False)
        if getattr(self, "actor", None) is not None:
            self.resource_authorization.require(
                self.actor, self.tenant_id, "workflow", "delete", workflow
            )
        self.workflow_repo.delete(workflow)
        self.db.commit()

    # ── Workflow状态管理 ───────────────────────────────────────────────────────

    def publish_workflow(self, workflow_id: str | uuid.UUID) -> Workflow:
        """发布工作流"""
        workflow = self.get_workflow(workflow_id, authorize=False)
        if getattr(self, "actor", None) is not None:
            self.resource_authorization.require(
                self.actor, self.tenant_id, "workflow", "publish", workflow
            )
        if workflow.status != "draft":
            raise ValidationException("只有草稿状态的工作流才能发布")
        self.workflow_repo.update(workflow, status="published")
        self.db.commit()
        return self.get_workflow(workflow_id, authorize=False)

    def archive_workflow(self, workflow_id: str | uuid.UUID) -> Workflow:
        """归档工作流"""
        workflow = self.get_workflow(workflow_id, authorize=False)
        if getattr(self, "actor", None) is not None:
            self.resource_authorization.require(
                self.actor, self.tenant_id, "workflow", "update", workflow
            )
        self.workflow_repo.update(workflow, status="archived")
        self.db.commit()
        return self.get_workflow(workflow_id, authorize=False)

    # ── Workflow验证 ───────────────────────────────────────────────────────────

    def validate_workflow_dag(
        self,
        workflow_id: str | uuid.UUID,
        *,
        authorize: bool = True,
    ) -> Dict[str, Any]:
        """验证工作流DAG结构"""
        workflow = self.get_workflow(workflow_id, authorize=authorize)

        nodes = {node.id: node for node in workflow.nodes}
        edges = workflow.edges

        start_nodes = [n for n in workflow.nodes if n.node_type == "start"]
        end_nodes = [n for n in workflow.nodes if n.node_type == "end"]

        if not start_nodes:
            raise ValidationException("工作流必须包含至少一个开始节点")
        if not end_nodes:
            raise ValidationException("工作流必须包含至少一个结束节点")

        graph = {node_id: [] for node_id in nodes}
        for edge in edges:
            if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                raise ValidationException(f"边 {edge.id} 引用了不存在的节点")
            graph[edge.source_node_id].append(edge.target_node_id)

        visited = set()
        recursion_stack = set()

        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            recursion_stack.add(node_id)

            for neighbor in graph[node_id]:
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    return True

            recursion_stack.remove(node_id)
            return False

        for node_id in nodes:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise ValidationException("工作流包含循环依赖，不是有效的DAG")

        reachable = set()
        def dfs(node_id: str):
            reachable.add(node_id)
            for neighbor in graph[node_id]:
                if neighbor not in reachable:
                    dfs(neighbor)

        for start_node in start_nodes:
            dfs(start_node.id)

        unreachable_nodes = [nodes[nid].name for nid in nodes if nid not in reachable]
        if unreachable_nodes:
            raise ValidationException(f"节点 {unreachable_nodes} 不可达")

        return {
            "valid": True,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "start_nodes": [n.name for n in start_nodes],
            "end_nodes": [n.name for n in end_nodes],
        }
