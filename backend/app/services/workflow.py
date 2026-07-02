from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.repositories.workflow import WorkflowRepository, WorkflowNodeRepository, WorkflowEdgeRepository
from app.core.exceptions import NotFoundException, ValidationException
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate

logger = logging.getLogger(__name__)


class WorkflowService:
    """工作流服务"""

    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
        self.workflow_repo = WorkflowRepository(db=db, tenant_id=tenant_id)
        self.node_repo = WorkflowNodeRepository(db=db, tenant_id=tenant_id)
        self.edge_repo = WorkflowEdgeRepository(db=db, tenant_id=tenant_id)

    # ── Workflow CRUD ───────────────────────────────────────────────────────────

    def create_workflow(
        self,
        data: WorkflowCreate,
        user_id: int,
    ) -> Workflow:
        """创建工作流"""
        # 创建工作流
        workflow = self.workflow_repo.create(
            name=data.name,
            description=data.description,
            status="draft",
            created_by=user_id,
        )

        # 创建节点
        if data.nodes:
            for node_data in data.nodes:
                self.node_repo.create(
                    workflow_id=workflow.id,
                    node_type=node_data.node_type,
                    name=node_data.name,
                    position_x=node_data.position_x,
                    position_y=node_data.position_y,
                    config=node_data.config,
                )

        # 创建边
        if data.edges:
            for edge_data in data.edges:
                self.edge_repo.create(
                    workflow_id=workflow.id,
                    source_node_id=edge_data.source_node_id,
                    target_node_id=edge_data.target_node_id,
                    condition=edge_data.condition,
                    label=edge_data.label,
                )

        self.db.commit()
        return self.get_workflow(workflow.id)

    def get_workflow(self, workflow_id: int) -> Workflow:
        """获取工作流详情"""
        workflow = self.workflow_repo.get_with_nodes_and_edges(workflow_id)
        if not workflow:
            raise NotFoundException("Workflow", workflow_id)
        return workflow

    def list_workflows(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[List[Workflow], int]:
        """列出工作流"""
        workflows = self.workflow_repo.list_by_status(status=status, page=page, page_size=page_size)
        total = self.workflow_repo.count_by_status(status=status)
        return workflows, total

    def update_workflow(
        self,
        workflow_id: int,
        data: WorkflowUpdate,
    ) -> Workflow:
        """更新工作流"""
        workflow = self.get_workflow(workflow_id)

        # 更新基本信息
        updates = data.model_dump(exclude={"nodes", "edges"}, exclude_unset=True)
        if updates:
            self.workflow_repo.update(workflow, **updates)

        # 更新节点和边（如果提供）
        if data.nodes is not None:
            # 删除旧节点和边
            self.edge_repo.delete_by_workflow(workflow_id)
            self.node_repo.delete_by_workflow(workflow_id)

            # 创建新节点
            node_id_map = {}  # 临时ID映射（用于边的创建）
            for node_data in data.nodes:
                node = self.node_repo.create(
                    workflow_id=workflow.id,
                    node_type=node_data.node_type,
                    name=node_data.name,
                    position_x=node_data.position_x,
                    position_y=node_data.position_y,
                    config=node_data.config,
                )
                # 如果节点数据中包含临时ID，记录映射关系
                if hasattr(node_data, 'temp_id'):
                    node_id_map[node_data.temp_id] = node.id

        if data.edges is not None:
            # 创建新边
            for edge_data in data.edges:
                # 处理临时ID映射
                source_id = edge_data.source_node_id
                target_id = edge_data.target_node_id
                if source_id in node_id_map:
                    source_id = node_id_map[source_id]
                if target_id in node_id_map:
                    target_id = node_id_map[target_id]

                self.edge_repo.create(
                    workflow_id=workflow.id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    condition=edge_data.condition,
                    label=edge_data.label,
                )

        self.db.commit()
        return self.get_workflow(workflow_id)

    def delete_workflow(self, workflow_id: int) -> None:
        """删除工作流"""
        workflow = self.get_workflow(workflow_id)
        self.workflow_repo.delete(workflow)
        self.db.commit()

    # ── Workflow状态管理 ───────────────────────────────────────────────────────

    def publish_workflow(self, workflow_id: int) -> Workflow:
        """发布工作流"""
        workflow = self.get_workflow(workflow_id)
        if workflow.status != "draft":
            raise ValidationException("只有草稿状态的工作流才能发布")
        self.workflow_repo.update(workflow, status="published")
        self.db.commit()
        return self.get_workflow(workflow_id)

    def archive_workflow(self, workflow_id: int) -> Workflow:
        """归档工作流"""
        workflow = self.get_workflow(workflow_id)
        self.workflow_repo.update(workflow, status="archived")
        self.db.commit()
        return self.get_workflow(workflow_id)

    # ── Workflow验证 ───────────────────────────────────────────────────────────

    def validate_workflow_dag(self, workflow_id: int) -> Dict[str, Any]:
        """验证工作流DAG结构"""
        workflow = self.get_workflow(workflow_id)

        # 构建节点映射
        nodes = {node.id: node for node in workflow.nodes}
        edges = workflow.edges

        # 验证必须有开始节点和结束节点
        start_nodes = [n for n in workflow.nodes if n.node_type == "start"]
        end_nodes = [n for n in workflow.nodes if n.node_type == "end"]

        if not start_nodes:
            raise ValidationException("工作流必须包含至少一个开始节点")
        if not end_nodes:
            raise ValidationException("工作流必须包含至少一个结束节点")

        # 构建邻接表
        graph = {node_id: [] for node_id in nodes}
        for edge in edges:
            if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                raise ValidationException(f"边 {edge.id} 引用了不存在的节点")
            graph[edge.source_node_id].append(edge.target_node_id)

        # 检测循环依赖（DFS）
        visited = set()
        recursion_stack = set()

        def has_cycle(node_id: int) -> bool:
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

        # 检查所有节点是否可达（从开始节点开始）
        reachable = set()
        def dfs(node_id: int):
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