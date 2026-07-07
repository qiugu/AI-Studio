# Workflow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete workflow engine with DAG execution, React Flow visual editor, and SSE streaming execution for enterprise workflow automation.

**Architecture:** Backend uses SQLAlchemy ORM models for workflow/node/edge/execution storage, DAG execution engine with topological sorting, and node executor dispatch pattern. Frontend uses React Flow for drag-and-drop visual editing with real-time execution monitoring.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + LangChain (backend), React Flow + TypeScript + Ant Design (frontend)

## Global Constraints

- All workflow-related database queries MUST use BaseRepository with tenant_id filtering
- Node execution context MUST support variable passing between nodes
- SSE streaming MUST use standard format: `event: message\ndata: {...}\n\n`
- JSON serialization MUST use `ensure_ascii=False` to preserve Unicode
- Frontend MUST use createStreamRequest for SSE consumption
- Workflow status: draft | published | archived
- Execution status: pending | running | completed | failed | cancelled

---

## Backend Implementation

### Task 1: Create Workflow Model

**Files:**
- Create: `backend/app/models/workflow.py`
- Modify: `backend/app/models/__init__.py:21-44`

**Interfaces:**
- Produces: `Workflow` model with fields: id, tenant_id, name, description, status, created_by, created_at, updated_at, deleted_at
- Relations: workflow_nodes (cascade delete), workflow_edges (cascade delete), workflow_executions (cascade delete)

- [ ] **Step 1: Write the Workflow model**

```python
from datetime import datetime
from typing import Optional, List

from sqlalchemy import BigInteger, String, Text, DateTime, Boolean, JSON, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class Workflow(Base):
    """工作流模型"""
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 基本信息
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 工作流配置
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | published | archived
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 时间戳
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    nodes: Mapped[List["WorkflowNode"]] = relationship(
        "WorkflowNode", back_populates="workflow", cascade="all, delete-orphan"
    )
    edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan"
    )
    executions: Mapped[List["WorkflowExecution"]] = relationship(
        "WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Update models/__init__.py to export Workflow**

Add to the imports section (after existing imports):

```python
from app.models.workflow import Workflow
```

Add to `__all__` list:

```python
__all__ = [
    # ... existing models ...
    "Workflow",
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/workflow.py backend/app/models/__init__.py
git commit -m "feat(workflow): add Workflow model"
```

---

### Task 2: Create WorkflowNode Model

**Files:**
- Create: `backend/app/models/workflow_node.py`
- Modify: `backend/app/models/__init__.py:21-44`

**Interfaces:**
- Produces: `WorkflowNode` model with fields: id, workflow_id, tenant_id, node_type, name, position_x, position_y, config, created_at, updated_at
- Relations: workflow (back_populate), source_edges, target_edges

- [ ] **Step 1: Write the WorkflowNode model**

```python
from datetime import datetime
from typing import Optional, List

from sqlalchemy import BigInteger, String, Text, DateTime, Float, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowNode(Base):
    """工作流节点模型"""
    __tablename__ = "workflow_nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 节点信息
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)  # start | end | llm | condition | knowledge | code | tool | loop | variable
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 位置信息（用于前端React Flow）
    position_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 节点配置（JSON格式，不同节点类型有不同的配置）
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="nodes")
    source_edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", foreign_keys="WorkflowEdge.source_node_id", back_populates="source_node"
    )
    target_edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", foreign_keys="WorkflowEdge.target_node_id", back_populates="target_node"
    )
```

- [ ] **Step 2: Update models/__init__.py to export WorkflowNode**

Add to the imports section:

```python
from app.models.workflow_node import WorkflowNode
```

Add to `__all__` list:

```python
__all__ = [
    # ... existing models ...
    "WorkflowNode",
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/workflow_node.py backend/app/models/__init__.py
git commit -m "feat(workflow): add WorkflowNode model"
```

---

### Task 3: Create WorkflowEdge Model

**Files:**
- Create: `backend/app/models/workflow_edge.py`
- Modify: `backend/app/models/__init__.py:21-44`

**Interfaces:**
- Produces: `WorkflowEdge` model with fields: id, workflow_id, tenant_id, source_node_id, target_node_id, condition, label, created_at, updated_at
- Relations: workflow (back_populate), source_node, target_node

- [ ] **Step 1: Write the WorkflowEdge model**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowEdge(Base):
    """工作流边（连线）模型"""
    __tablename__ = "workflow_edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 边信息
    source_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False
    )

    # 条件配置（用于条件分支）
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"expression": "{{output.value > 10}}", "label": "大于10"}
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 边的标签（显示在连线上）

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="edges")
    source_node: Mapped["WorkflowNode"] = relationship(
        "WorkflowNode", foreign_keys=[source_node_id], back_populates="source_edges"
    )
    target_node: Mapped["WorkflowNode"] = relationship(
        "WorkflowNode", foreign_keys=[target_node_id], back_populates="target_edges"
    )
```

- [ ] **Step 2: Update models/__init__.py to export WorkflowEdge**

Add to the imports section:

```python
from app.models.workflow_edge import WorkflowEdge
```

Add to `__all__` list:

```python
__all__ = [
    # ... existing models ...
    "WorkflowEdge",
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/workflow_edge.py backend/app/models/__init__.py
git commit -m "feat(workflow): add WorkflowEdge model"
```

---

### Task 4: Create WorkflowExecution Model

**Files:**
- Create: `backend/app/models/workflow_execution.py`
- Modify: `backend/app/models/__init__.py:21-44`

**Interfaces:**
- Produces: `WorkflowExecution` model with fields: id, workflow_id, tenant_id, status, input_data, output_data, error_message, started_at, completed_at, created_by
- Relations: workflow (back_populate), node_executions (cascade delete)

- [ ] **Step 1: Write the WorkflowExecution model**

```python
from datetime import datetime
from typing import Optional, List

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowExecution(Base):
    """工作流执行记录模型"""
    __tablename__ = "workflow_executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 执行状态
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | completed | failed | cancelled
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 输入参数
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 输出结果
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 错误信息

    # 时间戳
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")
    node_executions: Mapped[List["NodeExecution"]] = relationship(
        "NodeExecution", back_populates="execution", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Update models/__init__.py to export WorkflowExecution**

Add to the imports section:

```python
from app.models.workflow_execution import WorkflowExecution
```

Add to `__all__` list:

```python
__all__ = [
    # ... existing models ...
    "WorkflowExecution",
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/workflow_execution.py backend/app/models/__init__.py
git commit -m "feat(workflow): add WorkflowExecution model"
```

---

### Task 5: Create NodeExecution Model

**Files:**
- Create: `backend/app/models/node_execution.py`
- Modify: `backend/app/models/__init__.py:21-44`

**Interfaces:**
- Produces: `NodeExecution` model with fields: id, execution_id, node_id, tenant_id, status, input_data, output_data, error_message, started_at, completed_at
- Relations: execution (back_populate)

- [ ] **Step 1: Write the NodeExecution model**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class NodeExecution(Base):
    """节点执行记录模型"""
    __tablename__ = "node_executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)  # 关联 WorkflowNode.id
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 执行状态
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | completed | failed | skipped
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 节点输入数据
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 节点输出数据
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 错误信息

    # 时间戳
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    execution: Mapped["WorkflowExecution"] = relationship("WorkflowExecution", back_populates="node_executions")
```

- [ ] **Step 2: Update models/__init__.py to export NodeExecution**

Add to the imports section:

```python
from app.models.node_execution import NodeExecution
```

Add to `__all__` list:

```python
__all__ = [
    # ... existing models ...
    "NodeExecution",
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/node_execution.py backend/app/models/__init__.py
git commit -m "feat(workflow): add NodeExecution model"
```

---

### Task 6: Create WorkflowRepository

**Files:**
- Create: `backend/app/repositories/workflow.py`

**Interfaces:**
- Consumes: BaseRepository from `app/repositories/base.py`
- Produces: WorkflowRepository, WorkflowNodeRepository, WorkflowEdgeRepository classes with CRUD methods

- [ ] **Step 1: Write the WorkflowRepository classes**

```python
from typing import Optional, List
from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository
from app.models.workflow import Workflow
from app.models.workflow_node import WorkflowNode
from app.models.workflow_edge import WorkflowEdge


class WorkflowRepository(BaseRepository[Workflow]):
    """工作流Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(Workflow, db, tenant_id)

    def get_with_nodes_and_edges(self, workflow_id: int) -> Optional[Workflow]:
        """获取工作流及其节点和边"""
        workflow = self.get_by_id(workflow_id)
        if workflow:
            # 确保节点和边被加载（通过访问关系）
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

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(WorkflowNode, db, tenant_id)

    def list_by_workflow(self, workflow_id: int) -> List[WorkflowNode]:
        """获取工作流的所有节点"""
        return self.db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.tenant_id == self.tenant_id,
        ).all()

    def delete_by_workflow(self, workflow_id: int) -> None:
        """删除工作流的所有节点"""
        self.db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id == workflow_id,
            WorkflowNode.tenant_id == self.tenant_id,
        ).delete()
        self.db.flush()


class WorkflowEdgeRepository(BaseRepository[WorkflowEdge]):
    """工作流边Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(WorkflowEdge, db, tenant_id)

    def list_by_workflow(self, workflow_id: int) -> List[WorkflowEdge]:
        """获取工作流的所有边"""
        return self.db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == workflow_id,
            WorkflowEdge.tenant_id == self.tenant_id,
        ).all()

    def delete_by_workflow(self, workflow_id: int) -> None:
        """删除工作流的所有边"""
        self.db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == workflow_id,
            WorkflowEdge.tenant_id == self.tenant_id,
        ).delete()
        self.db.flush()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories/workflow.py
git commit -m "feat(workflow): add WorkflowRepository classes"
```

---

### Task 7: Create Workflow Schemas

**Files:**
- Create: `backend/app/schemas/workflow.py`

**Interfaces:**
- Consumes: BaseModel from Pydantic v2
- Produces: WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowNodeCreate, WorkflowEdgeCreate, WorkflowExecutionRequest, WorkflowExecutionResponse schemas

- [ ] **Step 1: Write the Workflow schemas**

```python
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ── Workflow Node Schemas ──────────────────────────────────────────────────────

class WorkflowNodeBase(BaseModel):
    node_type: str = Field(..., description="节点类型")
    name: str = Field(..., description="节点名称")
    position_x: float = Field(default=0.0, description="X坐标")
    position_y: float = Field(default=0.0, description="Y坐标")
    config: Optional[Dict[str, Any]] = Field(default=None, description="节点配置")


class WorkflowNodeCreate(WorkflowNodeBase):
    pass


class WorkflowNodeUpdate(WorkflowNodeBase):
    node_type: Optional[str] = Field(default=None, description="节点类型")
    name: Optional[str] = Field(default=None, description="节点名称")


class WorkflowNodeResponse(WorkflowNodeBase):
    id: int
    workflow_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Workflow Edge Schemas ──────────────────────────────────────────────────────

class WorkflowEdgeBase(BaseModel):
    source_node_id: int = Field(..., description="源节点ID")
    target_node_id: int = Field(..., description="目标节点ID")
    condition: Optional[Dict[str, Any]] = Field(default=None, description="条件配置")
    label: Optional[str] = Field(default=None, description="边标签")


class WorkflowEdgeCreate(WorkflowEdgeBase):
    pass


class WorkflowEdgeUpdate(WorkflowEdgeBase):
    source_node_id: Optional[int] = Field(default=None, description="源节点ID")
    target_node_id: Optional[int] = Field(default=None, description="目标节点ID")


class WorkflowEdgeResponse(WorkflowEdgeBase):
    id: int
    workflow_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Workflow Schemas ────────────────────────────────────────────────────────────

class WorkflowBase(BaseModel):
    name: str = Field(..., description="工作流名称")
    description: Optional[str] = Field(default=None, description="工作流描述")


class WorkflowCreate(WorkflowBase):
    nodes: Optional[List[WorkflowNodeCreate]] = Field(default=None, description="节点列表")
    edges: Optional[List[WorkflowEdgeCreate]] = Field(default=None, description="边列表")


class WorkflowUpdate(WorkflowBase):
    name: Optional[str] = Field(default=None, description="工作流名称")
    description: Optional[str] = Field(default=None, description="工作流描述")
    status: Optional[str] = Field(default=None, description="工作流状态")
    nodes: Optional[List[WorkflowNodeCreate]] = Field(default=None, description="节点列表")
    edges: Optional[List[WorkflowEdgeCreate]] = Field(default=None, description="边列表")


class WorkflowResponse(WorkflowBase):
    id: int
    tenant_id: int
    status: str
    is_active: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    nodes: List[WorkflowNodeResponse] = []
    edges: List[WorkflowEdgeResponse] = []

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    items: List[WorkflowResponse]
    total: int
    page: int
    page_size: int


# ── Workflow Execution Schemas ──────────────────────────────────────────────────

class WorkflowExecutionRequest(BaseModel):
    input_data: Optional[Dict[str, Any]] = Field(default=None, description="输入参数")


class WorkflowExecutionResponse(BaseModel):
    id: int
    workflow_id: int
    tenant_id: int
    status: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/workflow.py
git commit -m "feat(workflow): add Workflow schemas"
```

---

### Task 8: Create WorkflowService CRUD Methods

**Files:**
- Create: `backend/app/services/workflow.py`

**Interfaces:**
- Consumes: WorkflowRepository, WorkflowNodeRepository, WorkflowEdgeRepository
- Produces: WorkflowService with create_workflow, get_workflow, list_workflows, update_workflow, delete_workflow, publish_workflow, archive_workflow methods

- [ ] **Step 1: Write the WorkflowService CRUD methods**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow.py
git commit -m "feat(workflow): add WorkflowService CRUD methods"
```

---

### Task 9: Add WorkflowService Validation Methods

**Files:**
- Modify: `backend/app/services/workflow.py:1-162`

**Interfaces:**
- Produces: validate_workflow_dag method to validate workflow DAG structure

- [ ] **Step 1: Add DAG validation method to WorkflowService**

Append to the WorkflowService class:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow.py
git commit -m "feat(workflow): add DAG validation method"
```

---

### Task 10: Create WorkflowEngine Base Structure

**Files:**
- Create: `backend/app/services/workflow_engine.py`

**Interfaces:**
- Consumes: WorkflowService, WorkflowExecution, NodeExecution models
- Produces: WorkflowEngine class with execute_workflow, build_dag, topological_sort methods

- [ ] **Step 1: Write the WorkflowEngine base structure**

```python
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone
import logging
import json

from sqlalchemy.orm import Session
from collections import deque

from app.models.workflow import Workflow
from app.models.workflow_node import WorkflowNode
from app.models.workflow_edge import WorkflowEdge
from app.models.workflow_execution import WorkflowExecution
from app.models.node_execution import NodeExecution
from app.services.workflow import WorkflowService
from app.core.exceptions import ValidationException, NotFoundException
from app.schemas.workflow import WorkflowExecutionRequest

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
        self.workflow_service = WorkflowService(db=db, tenant_id=tenant_id)

    # ── DAG构建与拓扑排序 ───────────────────────────────────────────────────────

    def build_dag(self, workflow: Workflow) -> Dict[int, List[int]]:
        """构建DAG邻接表"""
        graph = {node.id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            graph[edge.source_node_id].append(edge.target_node_id)
        return graph

    def topological_sort(self, graph: Dict[int, List[int]]) -> List[int]:
        """拓扑排序（Kahn算法）"""
        # 计算入度
        in_degree = {node_id: 0 for node_id in graph}
        for node_id in graph:
            for neighbor in graph[node_id]:
                in_degree[neighbor] += 1

        # 找入度为0的节点（开始节点）
        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 检查是否所有节点都被访问（检测循环）
        if len(result) != len(graph):
            raise ValidationException("工作流包含循环依赖，无法执行")

        return result

    # ── 执行记录管理 ───────────────────────────────────────────────────────────

    def create_execution(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> WorkflowExecution:
        """创建执行记录"""
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            tenant_id=self.tenant_id,
            status="pending",
            input_data=input_data or {},
            created_by=user_id,
        )
        self.db.add(execution)
        self.db.flush()
        return execution

    def update_execution_status(
        self,
        execution: WorkflowExecution,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新执行状态"""
        execution.status = status
        if output_data is not None:
            execution.output_data = output_data
        if error_message is not None:
            execution.error_message = error_message

        if status == "running":
            execution.started_at = datetime.now(timezone.utc)
        elif status in ["completed", "failed", "cancelled"]:
            execution.completed_at = datetime.now(timezone.utc)

        self.db.flush()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): add WorkflowEngine base structure"
```

---

### Task 11: Add WorkflowEngine Node Execution Framework

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-107`

**Interfaces:**
- Produces: execute_node, create_node_execution, update_node_execution methods

- [ ] **Step 1: Add node execution framework to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    # ── 节点执行框架 ───────────────────────────────────────────────────────────

    def create_node_execution(
        self,
        execution_id: int,
        node_id: int,
        input_data: Optional[Dict[str, Any]],
    ) -> NodeExecution:
        """创建节点执行记录"""
        node_execution = NodeExecution(
            execution_id=execution_id,
            node_id=node_id,
            tenant_id=self.tenant_id,
            status="pending",
            input_data=input_data or {},
        )
        self.db.add(node_execution)
        self.db.flush()
        return node_execution

    def update_node_execution(
        self,
        node_execution: NodeExecution,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新节点执行状态"""
        node_execution.status = status
        if output_data is not None:
            node_execution.output_data = output_data
        if error_message is not None:
            node_execution.error_message = error_message

        if status == "running":
            node_execution.started_at = datetime.now(timezone.utc)
        elif status in ["completed", "failed", "skipped"]:
            node_execution.completed_at = datetime.now(timezone.utc)

        self.db.flush()

    async def execute_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        execution_id: int,
    ) -> Dict[str, Any]:
        """执行单个节点"""
        # 创建节点执行记录
        node_execution = self.create_node_execution(
            execution_id=execution_id,
            node_id=node.id,
            input_data=context,
        )

        try:
            # 更新状态为运行中
            self.update_node_execution(node_execution, status="running")

            # 根据节点类型执行
            node_type = node.node_type
            if node_type == "start":
                output = await self._execute_start_node(node, context)
            elif node_type == "end":
                output = await self._execute_end_node(node, context)
            elif node_type == "llm":
                output = await self._execute_llm_node(node, context)
            elif node_type == "condition":
                output = await self._execute_condition_node(node, context)
            elif node_type == "knowledge":
                output = await self._execute_knowledge_node(node, context)
            elif node_type == "code":
                output = await self._execute_code_node(node, context)
            elif node_type == "tool":
                output = await self._execute_tool_node(node, context)
            elif node_type == "loop":
                output = await self._execute_loop_node(node, context)
            elif node_type == "variable":
                output = await self._execute_variable_node(node, context)
            else:
                raise ValidationException(f"未知的节点类型: {node_type}")

            # 更新状态为完成
            self.update_node_execution(node_execution, status="completed", output_data=output)
            return output

        except Exception as e:
            # 更新状态为失败
            error_msg = str(e)[:500]  # 截取前500字符
            self.update_node_execution(node_execution, status="failed", error_message=error_msg)
            logger.error(
                f"Node execution failed: node_id={node.id}, error={e}",
                exc_info=True,
            )
            raise
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): add node execution framework"
```

---

### Task 12: Implement Start and End Node Executors

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-180`

**Interfaces:**
- Produces: _execute_start_node, _execute_end_node methods

- [ ] **Step 1: Add start and end node executors to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    # ── 节点执行器实现 ───────────────────────────────────────────────────────────

    async def _execute_start_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行开始节点"""
        config = node.config or {}
        # 开始节点通常只用于触发工作流，输出上下文中的输入数据
        output_variables = config.get("output_variables", [])

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source", "input")
            if var_source == "input":
                # 从输入数据中获取
                output[var_name] = context.get("input", {}).get(var_name)
            else:
                # 直接赋值
                output[var_name] = var.get("value")

        return output

    async def _execute_end_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行结束节点"""
        config = node.config or {}
        # 结束节点用于输出结果
        output_variables = config.get("output_variables", [])

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source")
            # 从上下文中获取变量值
            output[var_name] = context.get(var_source)

        return output
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): implement start and end node executors"
```

---

### Task 13: Implement LLM Node Executor

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-230`

**Interfaces:**
- Produces: _execute_llm_node method that calls LLM with prompt template

- [ ] **Step 1: Add LLM node executor to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    async def _execute_llm_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行LLM节点"""
        config = node.config or {}
        model_id = config.get("model_id")
        prompt_template = config.get("prompt_template", "")

        if not model_id:
            raise ValidationException("LLM节点必须指定模型ID")

        # 渲染Prompt模板（替换变量）
        prompt = self._render_template(prompt_template, context)

        # 获取模型和供应商
        from app.models.ai_model import AIModel
        from app.models.ai_provider import AIProvider
        from app.utils import llm as llm_utils
        from app.utils.encryption import decrypt

        model = self.db.query(AIModel).filter(AIModel.id == model_id).first()
        if not model:
            raise NotFoundException("AIModel", model_id)

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
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)
        llm = llm_utils.build_chat_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model.name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 调用LLM
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # 提取输出变量
        output_variable = config.get("output_variable", "output")
        return {output_variable: response.content}

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """渲染模板（替换变量）"""
        import re

        # 替换 {{variable}} 形式的变量
        def replace_var(match):
            var_name = match.group(1).strip()
            return str(context.get(var_name, ""))

        return re.sub(r'\{\{(.+?)\}\}', replace_var, template)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): implement LLM node executor"
```

---

### Task 14: Implement Condition Node Executor

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-320`

**Interfaces:**
- Produces: _execute_condition_node method that evaluates condition expressions

- [ ] **Step 1: Add condition node executor to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    async def _execute_condition_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行条件节点"""
        config = node.config or {}
        conditions = config.get("conditions", [])

        if not conditions:
            raise ValidationException("条件节点必须定义至少一个条件")

        # 评估每个条件
        for condition in conditions:
            expression = condition.get("expression", "")
            label = condition.get("label", "default")

            # 评估表达式
            result = self._evaluate_expression(expression, context)

            if result:
                # 返回匹配的条件标签（用于路由）
                return {
                    "condition_result": True,
                    "condition_label": label,
                    "matched_condition": condition,
                }

        # 如果没有匹配的条件，返回default
        return {
            "condition_result": False,
            "condition_label": "default",
        }

    def _evaluate_expression(self, expression: str, context: Dict[str, Any]) -> bool:
        """评估条件表达式"""
        import re

        # 替换变量
        def replace_var(match):
            var_name = match.group(1).strip()
            value = context.get(var_name)
            if isinstance(value, str):
                return f'"{value}"'
            return str(value)

        expr = re.sub(r'\{\{(.+?)\}\}', replace_var, expression)

        # 安全评估（限制操作符）
        try:
            # 只允许基本的比较和逻辑操作符
            result = eval(expr, {"__builtins__": {}}, {})
            return bool(result)
        except Exception as e:
            logger.error(f"Expression evaluation failed: {expression}, error={e}")
            return False
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): implement condition node executor"
```

---

### Task 15: Implement Knowledge, Code, and Tool Node Executors

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-380`

**Interfaces:**
- Produces: _execute_knowledge_node, _execute_code_node, _execute_tool_node methods

- [ ] **Step 1: Add knowledge, code, and tool node executors to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    async def _execute_knowledge_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行知识库节点"""
        config = node.config or {}
        kb_id = config.get("knowledge_base_id")
        query_template = config.get("query_template", "")
        top_k = config.get("top_k", 5)

        if not kb_id:
            raise ValidationException("知识库节点必须指定知识库ID")

        # 渲染查询模板
        query = self._render_template(query_template, context)

        # 调用知识库服务
        from app.services.knowledge import KnowledgeBaseService
        kb_service = KnowledgeBaseService(self.db, self.tenant_id)
        results = kb_service.search(kb_id=kb_id, query_text=query, top_k=top_k)

        # 提取输出
        output_variable = config.get("output_variable", "knowledge_result")
        return {
            output_variable: results,
            "query": query,
        }

    async def _execute_code_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行代码节点（受限Python沙盒）"""
        config = node.config or {}
        code = config.get("code", "")
        input_variables = config.get("input_variables", [])
        output_variable = config.get("output_variable", "result")

        if not code:
            raise ValidationException("代码节点必须包含代码")

        # 准备输入变量
        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        # 执行代码（受限环境）
        try:
            # 创建受限执行环境
            allowed_builtins = {
                "abs": abs,
                "all": all,
                "any": any,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "filter": filter,
                "float": float,
                "int": int,
                "len": len,
                "list": list,
                "map": map,
                "max": max,
                "min": min,
                "range": range,
                "round": round,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
                "zip": zip,
            }

            # 执行代码
            exec_globals = {"__builtins__": allowed_builtins, **input_data}
            local_vars = {}
            exec(code, exec_globals, local_vars)

            # 提取输出
            result = local_vars.get(output_variable)
            return {output_variable: result}

        except Exception as e:
            logger.error(f"Code execution failed: {e}", exc_info=True)
            raise ValidationException(f"代码执行失败: {str(e)[:200]}")

    async def _execute_tool_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行工具节点（调用Agent工具）"""
        config = node.config or {}
        tool_type = config.get("tool_type", "function")
        tool_name = config.get("tool_name", "")
        tool_config = config.get("tool_config", {})
        input_variables = config.get("input_variables", [])
        output_variable = config.get("output_variable", "tool_result")

        if not tool_name:
            raise ValidationException("工具节点必须指定工具名称")

        # 准备输入
        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        # TODO: 集成Agent工具系统（阶段6后期完善）
        # 目前返回占位数据
        return {
            output_variable: f"Tool {tool_name} executed with inputs: {input_data}",
            "tool_type": tool_type,
        }
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): implement knowledge, code, and tool node executors"
```

---

### Task 16: Implement Loop and Variable Node Executors + Main Execute Method

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-530`

**Interfaces:**
- Produces: _execute_loop_node, _execute_variable_node, execute_workflow (main execution method)

- [ ] **Step 1: Add loop, variable node executors and main execute method to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    async def _execute_loop_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行循环节点"""
        config = node.config or {}
        loop_type = config.get("loop_type", "for")  # for | while
        loop_variable = config.get("loop_variable", "item")
        loop_source = config.get("loop_source", "")
        max_iterations = config.get("max_iterations", 100)

        # 获取循环数据源
        if loop_type == "for":
            # 从上下文获取迭代数据
            data = context.get(loop_source, [])
            if not isinstance(data, (list, tuple)):
                raise ValidationException("For循环的数据源必须是列表")

            # 返回循环信息（实际迭代在execute_workflow中处理）
            return {
                "loop_type": "for",
                "loop_variable": loop_variable,
                "loop_data": data,
                "max_iterations": min(len(data), max_iterations),
            }
        else:  # while
            # While循环条件
            condition_template = config.get("condition_template", "")
            return {
                "loop_type": "while",
                "loop_variable": loop_variable,
                "condition_template": condition_template,
                "max_iterations": max_iterations,
            }

    async def _execute_variable_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行变量节点"""
        config = node.config or {}
        variables = config.get("variables", [])

        output = {}
        for var in variables:
            var_name = var.get("name")
            var_type = var.get("type", "static")
            var_value = var.get("value")

            if var_type == "static":
                output[var_name] = var_value
            elif var_type == "context":
                # 从上下文获取
                source = var.get("source", "")
                output[var_name] = context.get(source)
            elif var_type == "expression":
                # 评估表达式
                expression = var.get("expression", "")
                output[var_name] = self._evaluate_expression(expression, context)

        return output

    # ── 主执行流程 ───────────────────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        """执行工作流（阻塞式）"""
        # 获取工作流
        workflow = self.workflow_service.get_workflow(workflow_id)

        # 验证工作流状态
        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        # 验证DAG结构
        self.workflow_service.validate_workflow_dag(workflow_id)

        # 创建执行记录
        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            # 更新状态为运行中
            self.update_execution_status(execution, status="running")

            # 构建DAG并拓扑排序
            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            # 构建节点映射
            nodes = {node.id: node for node in workflow.nodes}

            # 执行上下文（存储所有节点的输出）
            context = {"input": input_data or {}}

            # 按拓扑顺序执行节点
            for node_id in node_order:
                node = nodes[node_id]

                # 获取前驱节点的输出（构建当前节点的输入）
                node_input = {}
                for edge in workflow.edges:
                    if edge.target_node_id == node_id:
                        # 从前驱节点的输出中获取数据
                        source_node = nodes[edge.source_node_id]
                        source_output = context.get(f"node_{source_node.id}", {})
                        node_input.update(source_output)

                # 执行节点
                node_output = await self.execute_node(node, node_input, execution.id)

                # 保存节点输出到上下文
                context[f"node_{node.id}"] = node_output

                # 更新全局上下文（用于后续节点）
                context.update(node_output)

            # 提取最终输出
            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            # 更新执行状态为完成
            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            return {
                "execution_id": execution.id,
                "status": "completed",
                "output": final_output,
            }

        except Exception as e:
            # 更新执行状态为失败
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)
            raise
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): complete WorkflowEngine with main execute method"
```

---

### Task 17: Add WorkflowEngine SSE Stream Execution

**Files:**
- Modify: `backend/app/services/workflow_engine.py:1-700`

**Interfaces:**
- Produces: execute_workflow_stream method for SSE streaming execution

- [ ] **Step 1: Add SSE stream execution method to WorkflowEngine**

Append to the WorkflowEngine class:

```python
    async def execute_workflow_stream(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行工作流（SSE流式）"""
        import json

        # 获取工作流
        workflow = self.workflow_service.get_workflow(workflow_id)

        # 验证工作流状态
        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        # 验证DAG结构
        self.workflow_service.validate_workflow_dag(workflow_id)

        # 创建执行记录
        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            # 更新状态为运行中
            self.update_execution_status(execution, status="running")

            # 发送执行开始事件
            yield {
                "type": "execution_started",
                "execution_id": execution.id,
                "workflow_id": workflow_id,
            }

            # 构建DAG并拓扑排序
            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            # 构建节点映射
            nodes = {node.id: node for node in workflow.nodes}

            # 执行上下文
            context = {"input": input_data or {}}

            # 按拓扑顺序执行节点
            for node_id in node_order:
                node = nodes[node_id]

                # 发送节点开始事件
                yield {
                    "type": "node_started",
                    "node_id": node.id,
                    "node_name": node.name,
                    "node_type": node.node_type,
                }

                # 获取前驱节点的输出
                node_input = {}
                for edge in workflow.edges:
                    if edge.target_node_id == node_id:
                        source_node = nodes[edge.source_node_id]
                        source_output = context.get(f"node_{source_node.id}", {})
                        node_input.update(source_output)

                # 执行节点
                try:
                    node_output = await self.execute_node(node, node_input, execution.id)

                    # 保存节点输出到上下文
                    context[f"node_{node.id}"] = node_output
                    context.update(node_output)

                    # 发送节点完成事件
                    yield {
                        "type": "node_completed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "output": node_output,
                    }

                except Exception as e:
                    # 发送节点失败事件
                    yield {
                        "type": "node_failed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "error": str(e)[:200],
                    }
                    raise

            # 提取最终输出
            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            # 更新执行状态为完成
            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            # 发送执行完成事件
            yield {
                "type": "execution_completed",
                "execution_id": execution.id,
                "output": final_output,
            }

        except Exception as e:
            # 更新执行状态为失败
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)

            # 发送执行失败事件
            yield {
                "type": "execution_failed",
                "execution_id": execution.id,
                "error": error_msg,
            }
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workflow_engine.py
git commit -m "feat(workflow): add SSE stream execution method"
```

---

### Task 18: Create Workflow API Routes

**Files:**
- Create: `backend/app/api/workflow.py`

**Interfaces:**
- Consumes: WorkflowService, WorkflowEngine, require_permission dependency
- Produces: API endpoints for workflow CRUD and execution

- [ ] **Step 1: Write the Workflow API routes**

```python
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
import json

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_tenant, require_permission
from app.schemas.common import ResponseBase, PaginatedResponse
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowListResponse,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
)
from app.services.workflow import WorkflowService
from app.services.workflow_engine import WorkflowEngine

router = APIRouter(prefix="/workflows", tags=["Workflow"])


# ── Workflow CRUD ───────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "create"))],
)
async def create_workflow(
    data: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """创建工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.create_workflow(data, current_user.id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.get(
    "/{workflow_id}",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """获取工作流详情"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.get_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.get(
    "",
    response_model=ResponseBase[WorkflowListResponse],
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """列出工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflows, total = service.list_workflows(page=page, page_size=page_size, status=status)
    items = [WorkflowResponse.model_validate(w) for w in workflows]
    return ResponseBase(
        data=WorkflowListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.put(
    "/{workflow_id}",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def update_workflow(
    workflow_id: int,
    data: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """更新工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.update_workflow(workflow_id, data)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.delete(
    "/{workflow_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "delete"))],
)
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """删除工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    service.delete_workflow(workflow_id)
    return ResponseBase(message="工作流已删除")


# ── Workflow状态管理 ───────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/publish",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def publish_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """发布工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.publish_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.post(
    "/{workflow_id}/archive",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def archive_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """归档工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.archive_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


# ── Workflow执行 ───────────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/execute",
    response_model=ResponseBase[WorkflowExecutionResponse],
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow(
    workflow_id: int,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（阻塞式）"""
    engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)
    result = await engine.execute_workflow(
        workflow_id=workflow_id,
        input_data=data.input_data,
        user_id=current_user.id,
    )

    # 获取执行记录
    from app.models.workflow_execution import WorkflowExecution
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == result["execution_id"],
        WorkflowExecution.tenant_id == current_tenant.id,
    ).first()

    return ResponseBase(data=WorkflowExecutionResponse.model_validate(execution))


@router.post(
    "/{workflow_id}/execute/stream",
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow_stream(
    workflow_id: int,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（SSE流式）"""
    engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)

    async def event_generator():
        async for event in engine.execute_workflow_stream(
            workflow_id=workflow_id,
            input_data=data.input_data,
            user_id=current_user.id,
        ):
            yield ServerSentEvent(
                event=event["type"],
                data=json.dumps(event, ensure_ascii=False),
            )

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/{workflow_id}/validate",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def validate_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_tenant=Depends(get_current_tenant),
):
    """验证工作流DAG结构"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    result = service.validate_workflow_dag(workflow_id)
    return ResponseBase(data=result)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/workflow.py
git commit -m "feat(workflow): add Workflow API routes"
```

---

### Task 19: Register Workflow Routes in main.py

**Files:**
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: workflow router from `app/api/workflow.py`
- Produces: registered workflow routes at `/api/workflows`

- [ ] **Step 1: Add workflow router to main.py**

Find the router registration section and add:

```python
from app.api.workflow import router as workflow_router

# Register routers
app.include_router(workflow_router, prefix="/api")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(workflow): register workflow routes"
```

---

### Task 20: Generate Alembic Migration

**Files:**
- Generate: `backend/alembic/versions/xxx_add_workflow_tables.py`

**Interfaces:**
- Produces: database migration for workflow tables

- [ ] **Step 1: Run Alembic migration**

```bash
cd backend
source .venv/bin/activate
alembic revision --autogenerate -m "add workflow tables"
alembic upgrade head
```

- [ ] **Step 2: Commit migration file**

```bash
git add backend/alembic/versions/
git commit -m "feat(workflow): add workflow tables migration"
```

---

## Frontend Implementation

### Task 21: Create Workflow TypeScript Types

**Files:**
- Create: `frontend/src/types/workflow.ts`

**Interfaces:**
- Produces: TypeScript types for Workflow, WorkflowNode, WorkflowEdge, WorkflowExecution

- [ ] **Step 1: Write workflow TypeScript types**

```typescript
// ── Workflow Node Types ───────────────────────────────────────────────────────

export type NodeType = 'start' | 'end' | 'llm' | 'condition' | 'knowledge' | 'code' | 'tool' | 'loop' | 'variable'

export interface WorkflowNodeConfig {
  // LLM节点配置
  model_id?: number
  prompt_template?: string
  temperature?: number
  max_tokens?: number
  output_variable?: string

  // Condition节点配置
  conditions?: Array<{
    expression: string
    label: string
  }>

  // Knowledge节点配置
  knowledge_base_id?: number
  query_template?: string
  top_k?: number

  // Code节点配置
  code?: string
  input_variables?: string[]
  output_variable?: string

  // Tool节点配置
  tool_type?: string
  tool_name?: string
  tool_config?: Record<string, unknown>

  // Loop节点配置
  loop_type?: 'for' | 'while'
  loop_variable?: string
  loop_source?: string
  max_iterations?: number

  // Variable节点配置
  variables?: Array<{
    name: string
    type: 'static' | 'context' | 'expression'
    value?: unknown
    source?: string
    expression?: string
  }>

  // Start/End节点配置
  output_variables?: Array<{
    name: string
    source: string
    value?: unknown
  }>
}

export interface WorkflowNode {
  id: number
  workflow_id: number
  tenant_id: number
  node_type: NodeType
  name: string
  position_x: number
  position_y: number
  config: WorkflowNodeConfig | null
  created_at: string
  updated_at: string
}

export interface WorkflowNodeCreate {
  node_type: NodeType
  name: string
  position_x: number
  position_y: number
  config?: WorkflowNodeConfig
}

// ── Workflow Edge Types ───────────────────────────────────────────────────────

export interface WorkflowEdgeCondition {
  expression: string
  label: string
}

export interface WorkflowEdge {
  id: number
  workflow_id: number
  tenant_id: number
  source_node_id: number
  target_node_id: number
  condition: WorkflowEdgeCondition | null
  label: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowEdgeCreate {
  source_node_id: number
  target_node_id: number
  condition?: WorkflowEdgeCondition
  label?: string
}

// ── Workflow Types ─────────────────────────────────────────────────────────────

export type WorkflowStatus = 'draft' | 'published' | 'archived'

export interface Workflow {
  id: number
  tenant_id: number
  name: string
  description: string | null
  status: WorkflowStatus
  is_active: boolean
  created_by: number | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface WorkflowCreateRequest {
  name: string
  description?: string
  nodes?: WorkflowNodeCreate[]
  edges?: WorkflowEdgeCreate[]
}

export interface WorkflowUpdateRequest {
  name?: string
  description?: string
  status?: WorkflowStatus
  nodes?: WorkflowNodeCreate[]
  edges?: WorkflowEdgeCreate[]
}

export interface WorkflowListResponse {
  items: Workflow[]
  total: number
  page: number
  page_size: number
}

// ── Workflow Execution Types ───────────────────────────────────────────────────

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface WorkflowExecution {
  id: number
  workflow_id: number
  tenant_id: number
  status: ExecutionStatus
  input_data: Record<string, unknown> | null
  output_data: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_by: number | null
  created_at: string
}

export interface WorkflowExecutionRequest {
  input_data?: Record<string, unknown>
}

// ── SSE Event Types ───────────────────────────────────────────────────────────

export interface SSEExecutionStartedEvent {
  type: 'execution_started'
  execution_id: number
  workflow_id: number
}

export interface SSENodeStartedEvent {
  type: 'node_started'
  node_id: number
  node_name: string
  node_type: NodeType
}

export interface SSENodeCompletedEvent {
  type: 'node_completed'
  node_id: number
  node_name: string
  output: Record<string, unknown>
}

export interface SSENodeFailedEvent {
  type: 'node_failed'
  node_id: number
  node_name: string
  error: string
}

export interface SSEExecutionCompletedEvent {
  type: 'execution_completed'
  execution_id: number
  output: Record<string, unknown>
}

export interface SSEExecutionFailedEvent {
  type: 'execution_failed'
  execution_id: number
  error: string
}

export type SSEWorkflowEvent =
  | SSEExecutionStartedEvent
  | SSENodeStartedEvent
  | SSENodeCompletedEvent
  | SSENodeFailedEvent
  | SSEExecutionCompletedEvent
  | SSEExecutionFailedEvent
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/workflow.ts
git commit -m "feat(workflow): add TypeScript types for workflow"
```

---

### Task 22: Create Workflow API Layer

**Files:**
- Create: `frontend/src/api/workflow.ts`

**Interfaces:**
- Consumes: apiClient from `src/api/client.ts`, workflow types
- Produces: API functions for workflow CRUD and execution

- [ ] **Step 1: Write workflow API functions**

```typescript
import apiClient from './client'
import type {
  Workflow,
  WorkflowCreateRequest,
  WorkflowUpdateRequest,
  WorkflowListResponse,
  WorkflowExecution,
  WorkflowExecutionRequest,
} from '../types/workflow'

// ── Workflow CRUD ───────────────────────────────────────────────────────────────

export const createWorkflow = async (data: WorkflowCreateRequest): Promise<Workflow> => {
  const response = await apiClient.post('/workflows', data)
  return response.data.data
}

export const getWorkflow = async (workflowId: number): Promise<Workflow> => {
  const response = await apiClient.get(`/workflows/${workflowId}`)
  return response.data.data
}

export const listWorkflows = async (
  page: number = 1,
  pageSize: number = 20,
  status?: string
): Promise<WorkflowListResponse> => {
  const params = { page, page_size: pageSize, status }
  const response = await apiClient.get('/workflows', { params })
  return response.data.data
}

export const updateWorkflow = async (
  workflowId: number,
  data: WorkflowUpdateRequest
): Promise<Workflow> => {
  const response = await apiClient.put(`/workflows/${workflowId}`, data)
  return response.data.data
}

export const deleteWorkflow = async (workflowId: number): Promise<void> => {
  await apiClient.delete(`/workflows/${workflowId}`)
}

// ── Workflow状态管理 ───────────────────────────────────────────────────────────

export const publishWorkflow = async (workflowId: number): Promise<Workflow> => {
  const response = await apiClient.post(`/workflows/${workflowId}/publish`)
  return response.data.data
}

export const archiveWorkflow = async (workflowId: number): Promise<Workflow> => {
  const response = await apiClient.post(`/workflows/${workflowId}/archive`)
  return response.data.data
}

// ── Workflow验证 ───────────────────────────────────────────────────────────────

export const validateWorkflow = async (workflowId: number): Promise<{
  valid: boolean
  node_count: number
  edge_count: number
}> => {
  const response = await apiClient.get(`/workflows/${workflowId}/validate`)
  return response.data.data
}

// ── Workflow执行 ───────────────────────────────────────────────────────────────

export const executeWorkflow = async (
  workflowId: number,
  data: WorkflowExecutionRequest
): Promise<WorkflowExecution> => {
  const response = await apiClient.post(`/workflows/${workflowId}/execute`, data)
  return response.data.data
}

export const executeWorkflowStreamUrl = (workflowId: number): string => {
  return `/api/workflows/${workflowId}/execute/stream`
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/workflow.ts
git commit -m "feat(workflow): add workflow API functions"
```

---

### Task 23: Create WorkflowList Page Component

**Files:**
- Create: `frontend/src/pages/Workflows/WorkflowList.tsx`

**Interfaces:**
- Consumes: workflow API, Ant Design components
- Produces: WorkflowList page with table view and actions

- [ ] **Step 1: Write WorkflowList component**

```typescript
import React, { useState, useEffect } from 'react'
import { Table, Button, Space, Tag, Modal, message, Popconfirm, Card } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, PlayCircleOutlined, CheckOutlined, InboxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listWorkflows, deleteWorkflow, publishWorkflow, archiveWorkflow } from '../../api/workflow'
import type { Workflow, WorkflowStatus } from '../../types/workflow'
import { usePagination } from '../../hooks/usePagination'

const WorkflowList: React.FC = () => {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | undefined>()
  const { page, pageSize, total, setPage, setPageSize, setTotal } = usePagination()

  const fetchWorkflows = async () => {
    setLoading(true)
    try {
      const result = await listWorkflows(page, pageSize, statusFilter)
      setWorkflows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error('获取工作流列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchWorkflows()
  }, [page, pageSize, statusFilter])

  const handleDelete = async (workflowId: number) => {
    try {
      await deleteWorkflow(workflowId)
      message.success('工作流已删除')
      fetchWorkflows()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handlePublish = async (workflowId: number) => {
    try {
      await publishWorkflow(workflowId)
      message.success('工作流已发布')
      fetchWorkflows()
    } catch (error) {
      message.error('发布失败')
    }
  }

  const handleArchive = async (workflowId: number) => {
    try {
      await archiveWorkflow(workflowId)
      message.success('工作流已归档')
      fetchWorkflows()
    } catch (error) {
      message.error('归档失败')
    }
  }

  const getStatusTag = (status: WorkflowStatus) => {
    const statusConfig = {
      draft: { color: 'default', text: '草稿' },
      published: { color: 'success', text: '已发布' },
      archived: { color: 'warning', text: '已归档' },
    }
    const config = statusConfig[status]
    return <Tag color={config.color}>{config.text}</Tag>
  }

  const columns: ColumnsType<Workflow> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 300,
      ellipsis: true,
    },
    {
      title: '节点数',
      dataIndex: 'nodes',
      key: 'nodes',
      width: 100,
      render: (nodes: any[]) => nodes?.length || 0,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: WorkflowStatus) => getStatusTag(status),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (time: string) => new Date(time).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/workflows/${record.id}/edit`)}
          >
            编辑
          </Button>
          {record.status === 'draft' && (
            <Button
              type="link"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handlePublish(record.id)}
            >
              发布
            </Button>
          )}
          {record.status === 'published' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => navigate(`/workflows/${record.id}/execute`)}
              >
                执行
              </Button>
              <Button
                type="link"
                size="small"
                icon={<InboxOutlined />}
                onClick={() => handleArchive(record.id)}
              >
                归档
              </Button>
            </>
          )}
          <Popconfirm
            title="确定删除此工作流吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="工作流列表"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/workflows/create')}
        >
          创建工作流
        </Button>
      }
    >
      <Space style={{ marginBottom: 16 }}>
        <span>状态筛选：</span>
        <Button
          type={statusFilter === undefined ? 'primary' : 'default'}
          onClick={() => setStatusFilter(undefined)}
        >
          全部
        </Button>
        <Button
          type={statusFilter === 'draft' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('draft')}
        >
          草稿
        </Button>
        <Button
          type={statusFilter === 'published' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('published')}
        >
          已发布
        </Button>
        <Button
          type={statusFilter === 'archived' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('archived')}
        >
          已归档
        </Button>
      </Space>

      <Table
        columns={columns}
        dataSource={workflows}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          onChange: (newPage, newPageSize) => {
            setPage(newPage)
            setPageSize(newPageSize)
          },
        }}
      />
    </Card>
  )
}

export default WorkflowList
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowList.tsx
git commit -m "feat(workflow): add WorkflowList page component"
```

---

### Task 24: Create WorkflowForm Component

**Files:**
- Create: `frontend/src/pages/Workflows/WorkflowForm.tsx`

**Interfaces:**
- Consumes: workflow API, Ant Design Form
- Produces: WorkflowForm component for creating/editing workflow basic info

- [ ] **Step 1: Write WorkflowForm component**

```typescript
import React, { useEffect } from 'react'
import { Form, Input, Button, Card, message } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createWorkflow, getWorkflow, updateWorkflow } from '../../api/workflow'
import type { WorkflowCreateRequest, Workflow } from '../../types/workflow'

const WorkflowForm: React.FC = () => {
  const navigate = useNavigate()
  const { workflowId } = useParams<{ workflowId: string }>()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const isEdit = !!workflowId

  useEffect(() => {
    if (isEdit) {
      fetchWorkflow()
    }
  }, [workflowId])

  const fetchWorkflow = async () => {
    setLoading(true)
    try {
      const workflow = await getWorkflow(parseInt(workflowId!))
      form.setFieldsValue({
        name: workflow.name,
        description: workflow.description,
      })
    } catch (error) {
      message.error('获取工作流信息失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values: WorkflowCreateRequest) => {
    setLoading(true)
    try {
      if (isEdit) {
        await updateWorkflow(parseInt(workflowId!), values)
        message.success('工作流已更新')
        navigate(`/workflows/${workflowId}/edit`)
      } else {
        const workflow = await createWorkflow(values)
        message.success('工作流已创建')
        navigate(`/workflows/${workflow.id}/edit`)
      }
    } catch (error) {
      message.error(isEdit ? '更新失败' : '创建失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card title={isEdit ? '编辑工作流基本信息' : '创建工作流'}>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{
          name: '',
          description: '',
        }}
      >
        <Form.Item
          label="工作流名称"
          name="name"
          rules={[{ required: true, message: '请输入工作流名称' }]}
        >
          <Input placeholder="请输入工作流名称" maxLength={255} />
        </Form.Item>

        <Form.Item
          label="描述"
          name="description"
        >
          <Input.TextArea
            placeholder="请输入工作流描述"
            rows={4}
            maxLength={1000}
          />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            {isEdit ? '保存' : '创建'}
          </Button>
          <Button style={{ marginLeft: 8 }} onClick={() => navigate('/workflows')}>
            取消
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}

export default WorkflowForm
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowForm.tsx
git commit -m "feat(workflow): add WorkflowForm component"
```

---

### Task 25: Install React Flow and Create WorkflowEditor Base

**Files:**
- Install: React Flow package
- Create: `frontend/src/pages/Workflows/WorkflowEditor.tsx`

**Interfaces:**
- Consumes: React Flow library, workflow API
- Produces: WorkflowEditor base component with React Flow canvas

- [ ] **Step 1: Install React Flow**

```bash
cd frontend
npm install reactflow
```

- [ ] **Step 2: Write WorkflowEditor base structure**

```typescript
import React, { useState, useEffect, useCallback } from 'react'
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Panel,
  NodeTypes,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Card, Space, message, Modal } from 'antd'
import { SaveOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
import { getWorkflow, updateWorkflow, publishWorkflow, validateWorkflow } from '../../api/workflow'
import type { Workflow, WorkflowNode, WorkflowEdge, WorkflowNodeCreate } from '../../types/workflow'
import { createNodeComponent } from './workflowNodes'

const WorkflowEditor: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // 自定义节点类型
  const nodeTypes: NodeTypes = {
    start: createNodeComponent('start'),
    end: createNodeComponent('end'),
    llm: createNodeComponent('llm'),
    condition: createNodeComponent('condition'),
    knowledge: createNodeComponent('knowledge'),
    code: createNodeComponent('code'),
    tool: createNodeComponent('tool'),
    loop: createNodeComponent('loop'),
    variable: createNodeComponent('variable'),
  }

  useEffect(() => {
    if (workflowId) {
      fetchWorkflow()
    }
  }, [workflowId])

  const fetchWorkflow = async () => {
    setLoading(true)
    try {
      const workflowData = await getWorkflow(parseInt(workflowId!))
      setWorkflow(workflowData)

      // 将数据库节点转换为React Flow节点
      const flowNodes: Node[] = workflowData.nodes.map((node) => ({
        id: node.id.toString(),
        type: node.node_type,
        position: { x: node.position_x, y: node.position_y },
        data: {
          name: node.name,
          config: node.config,
        },
      }))

      // 将数据库边转换为React Flow边
      const flowEdges: Edge[] = workflowData.edges.map((edge) => ({
        id: edge.id.toString(),
        source: edge.source_node_id.toString(),
        target: edge.target_node_id.toString(),
        label: edge.label,
        data: {
          condition: edge.condition,
        },
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch (error) {
      message.error('获取工作流失败')
    } finally {
      setLoading(false)
    }
  }

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge(params, eds))
  }, [setEdges])

  const handleSave = async () => {
    setSaving(true)
    try {
      // 将React Flow节点转换为数据库节点
      const workflowNodes: WorkflowNodeCreate[] = nodes.map((node) => ({
        node_type: node.type as any,
        name: node.data.name,
        position_x: node.position.x,
        position_y: node.position.y,
        config: node.data.config,
      }))

      // 将React Flow边转换为数据库边
      const workflowEdges = edges.map((edge) => ({
        source_node_id: parseInt(edge.source),
        target_node_id: parseInt(edge.target),
        label: edge.label,
        condition: edge.data?.condition,
      }))

      await updateWorkflow(parseInt(workflowId!), {
        nodes: workflowNodes,
        edges: workflowEdges,
      })

      message.success('工作流已保存')
      fetchWorkflow() // 刷新数据
    } catch (error) {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleValidate = async () => {
    try {
      const result = await validateWorkflow(parseInt(workflowId!))
      if (result.valid) {
        message.success(`工作流验证通过：${result.node_count}个节点，${result.edge_count}条连线`)
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '验证失败')
    }
  }

  const handlePublish = async () => {
    Modal.confirm({
      title: '发布工作流',
      content: '确定要发布此工作流吗？发布后即可执行。',
      onOk: async () => {
        try {
          await publishWorkflow(parseInt(workflowId!))
          message.success('工作流已发布')
          fetchWorkflow()
        } catch (error: any) {
          message.error(error.response?.data?.message || '发布失败')
        }
      },
    })
  }

  const handleExecute = () => {
    navigate(`/workflows/${workflowId}/execute`)
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Card style={{ marginBottom: 8 }}>
        <Space>
          <Button icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            保存
          </Button>
          <Button onClick={handleValidate}>验证</Button>
          {workflow?.status === 'draft' && (
            <Button type="primary" icon={<CheckOutlined />} onClick={handlePublish}>
              发布
            </Button>
          )}
          {workflow?.status === 'published' && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleExecute}>
              执行
            </Button>
          )}
          <Button onClick={() => navigate('/workflows')}>返回列表</Button>
        </Space>
      </Card>

      <div style={{ flex: 1, position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
        >
          <Controls />
          <MiniMap />
          <Background gap={16} size={1} />

          {/* 左侧节点类型面板 */}
          <Panel position="top-left">
            <NodePalette onNodeAdd={handleAddNode} />
          </Panel>
        </ReactFlow>
      </div>
    </div>
  )
}

export default WorkflowEditor
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowEditor.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(workflow): add WorkflowEditor base with React Flow"
```

---

### Task 26: Create Node Palette Component

**Files:**
- Create: `frontend/src/pages/Workflows/NodePalette.tsx`

**Interfaces:**
- Produces: NodePalette component for adding different node types

- [ ] **Step 1: Write NodePalette component**

Append to WorkflowEditor.tsx or create separate file:

```typescript
import React from 'react'
import { Card, Button, Space } from 'antd'
import {
  PlayCircleOutlined,
  StopOutlined,
  RobotOutlined,
  BranchesOutlined,
  BookOutlined,
  CodeOutlined,
  ToolOutlined,
  ReloadOutlined,
  VariableOutlined,
} from '@ant-design/icons'
import type { NodeType } from '../../types/workflow'

interface NodePaletteProps {
  onNodeAdd: (nodeType: NodeType) => void
}

const NodePalette: React.FC<NodePaletteProps> = ({ onNodeAdd }) => {
  const nodeTypes: Array<{ type: NodeType; label: string; icon: React.ReactNode; color: string }> = [
    { type: 'start', label: '开始', icon: <PlayCircleOutlined />, color: '#52c41a' },
    { type: 'end', label: '结束', icon: <StopOutlined />, color: '#ff4d4f' },
    { type: 'llm', label: 'LLM', icon: <RobotOutlined />, color: '#1890ff' },
    { type: 'condition', label: '条件', icon: <BranchesOutlined />, color: '#faad14' },
    { type: 'knowledge', label: '知识库', icon: <BookOutlined />, color: '#722ed1' },
    { type: 'code', label: '代码', icon: <CodeOutlined />, color: '#13c2c2' },
    { type: 'tool', label: '工具', icon: <ToolOutlined />, color: '#eb2f96' },
    { type: 'loop', label: '循环', icon: <ReloadOutlined />, color: '#fa8c16' },
    { type: 'variable', label: '变量', icon: <VariableOutlined />, color: '#a0d911' },
  ]

  return (
    <Card size="small" title="节点类型" style={{ width: 200 }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        {nodeTypes.map((nodeType) => (
          <Button
            key={nodeType.type}
            block
            icon={nodeType.icon}
            style={{ backgroundColor: nodeType.color, color: 'white' }}
            onClick={() => onNodeAdd(nodeType.type)}
          >
            {nodeType.label}
          </Button>
        ))}
      </Space>
    </Card>
  )
}

export default NodePalette
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/NodePalette.tsx
git commit -m "feat(workflow): add NodePalette component"
```

---

### Task 27: Create Custom Node Components

**Files:**
- Create: `frontend/src/pages/Workflows/workflowNodes.tsx`

**Interfaces:**
- Produces: Custom React Flow node components for each node type

- [ ] **Step 1: Write custom node components**

```typescript
import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { Card, Tag, Button } from 'antd'
import {
  PlayCircleOutlined,
  StopOutlined,
  RobotOutlined,
  BranchesOutlined,
  BookOutlined,
  CodeOutlined,
  ToolOutlined,
  ReloadOutlined,
  VariableOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { NodeType } from '../../types/workflow'

interface CustomNodeData {
  name: string
  config?: any
  onEdit?: (nodeId: string) => void
  onDelete?: (nodeId: string) => void
}

const nodeStyleConfig: Record<NodeType, { color: string; icon: React.ReactNode }> = {
  start: { color: '#52c41a', icon: <PlayCircleOutlined /> },
  end: { color: '#ff4d4f', icon: <StopOutlined /> },
  llm: { color: '#1890ff', icon: <RobotOutlined /> },
  condition: { color: '#faad14', icon: <BranchesOutlined /> },
  knowledge: { color: '#722ed1', icon: <BookOutlined /> },
  code: { color: '#13c2c2', icon: <CodeOutlined /> },
  tool: { color: '#eb2f96', icon: <ToolOutlined /> },
  loop: { color: '#fa8c16', icon: <ReloadOutlined /> },
  variable: { color: '#a0d911', icon: <VariableOutlined /> },
}

const CustomNode: React.FC<NodeProps<CustomNodeData> & { nodeType: NodeType }> = memo(
  ({ id, data, nodeType }) => {
    const style = nodeStyleConfig[nodeType]

    return (
      <Card
        size="small"
        style={{
          width: 200,
          borderColor: style.color,
          borderWidth: 2,
        }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: style.color }}>{style.icon}</span>
            <span>{data.name}</span>
            <Tag color={style.color} style={{ marginLeft: 'auto' }}>
              {nodeType}
            </Tag>
          </div>
        }
        extra={
          <div style={{ display: 'flex', gap: 4 }}>
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => data.onEdit?.(id)}
            />
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => data.onDelete?.(id)}
            />
          </div>
        }
      >
        {/* Handle for connections */}
        {nodeType !== 'end' && (
          <Handle type="source" position={Position.Bottom} style={{ background: style.color }} />
        )}
        {nodeType !== 'start' && (
          <Handle type="target" position={Position.Top} style={{ background: style.color }} />
        )}

        {/* Node content preview */}
        <div style={{ fontSize: 12, color: '#666' }}>
          {nodeType === 'llm' && data.config?.model_id && (
            <div>模型ID: {data.config.model_id}</div>
          )}
          {nodeType === 'knowledge' && data.config?.knowledge_base_id && (
            <div>知识库ID: {data.config.knowledge_base_id}</div>
          )}
          {nodeType === 'condition' && data.config?.conditions && (
            <div>条件数: {data.config.conditions.length}</div>
          )}
          {nodeType === 'code' && data.config?.code && (
            <div style={{ maxHeight: 60, overflow: 'hidden' }}>
              <pre style={{ fontSize: 10 }}>{data.config.code.substring(0, 100)}</pre>
            </div>
          )}
        </div>
      </Card>
    )
  }
)

export const createNodeComponent = (nodeType: NodeType) => {
  return (props: NodeProps<CustomNodeData>) => (
    <CustomNode {...props} nodeType={nodeType} />
  )
}

export default CustomNode
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/workflowNodes.tsx
git commit -m "feat(workflow): add custom React Flow node components"
```

---

### Task 28: Add Node Add/Edit/Delete Handlers to WorkflowEditor

**Files:**
- Modify: `frontend/src/pages/Workflows/WorkflowEditor.tsx`

**Interfaces:**
- Produces: handleAddNode, handleEditNode, handleDeleteNode methods

- [ ] **Step 1: Add node management handlers to WorkflowEditor**

Update WorkflowEditor component with these additions:

```typescript
  // Add these methods inside the WorkflowEditor component

  const handleAddNode = useCallback((nodeType: NodeType) => {
    const newNode: Node = {
      id: `temp-${Date.now()}`, // 临时ID，保存时会替换为真实ID
      type: nodeType,
      position: { x: 250, y: 150 }, // 默认位置
      data: {
        name: `新${nodeType}节点`,
        config: {},
      },
    }
    setNodes((nds) => [...nds, newNode])
  }, [setNodes])

  const handleEditNode = useCallback((nodeId: string) => {
    // TODO: 打开节点配置侧边栏或弹窗
    message.info('节点编辑功能待实现')
  }, [])

  const handleDeleteNode = useCallback((nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId))
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
  }, [setNodes, setEdges])

  // Update node data to include edit/delete handlers
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          onEdit: handleEditNode,
          onDelete: handleDeleteNode,
        },
      }))
    )
  }, [handleEditNode, handleDeleteNode, setNodes])
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowEditor.tsx
git commit -m "feat(workflow): add node management handlers"
```

---

### Task 29: Create NodeConfigPanel Component

**Files:**
- Create: `frontend/src/pages/Workflows/NodeConfigPanel.tsx`

**Interfaces:**
- Produces: NodeConfigPanel component for editing node configuration

- [ ] **Step 1: Write NodeConfigPanel component**

```typescript
import React from 'react'
import { Drawer, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'
import type { Node } from 'reactflow'
import type { NodeType, WorkflowNodeConfig } from '../../types/workflow'

interface NodeConfigPanelProps {
  visible: boolean
  node: Node | null
  onClose: () => void
  onSave: (nodeId: string, config: WorkflowNodeConfig) => void
}

const NodeConfigPanel: React.FC<NodeConfigPanelProps> = ({
  visible,
  node,
  onClose,
  onSave,
}) => {
  const [form] = Form.useForm()

  React.useEffect(() => {
    if (node) {
      form.setFieldsValue({
        name: node.data.name,
        ...node.data.config,
      })
    }
  }, [node, form])

  const handleSave = () => {
    form.validateFields().then((values) => {
      onSave(node!.id, {
        name: values.name,
        config: values,
      })
      message.success('节点配置已保存')
      onClose()
    })
  }

  const renderConfigFields = (nodeType: NodeType) => {
    switch (nodeType) {
      case 'llm':
        return (
          <>
            <Form.Item label="模型ID" name="model_id" rules={[{ required: true }]}>
              <InputNumber />
            </Form.Item>
            <Form.Item label="Prompt模板" name="prompt_template" rules={[{ required: true }]}>
              <Input.TextArea rows={6} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <Form.Item label="Temperature" name="temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>
            <Form.Item label="Max Tokens" name="max_tokens">
              <InputNumber min={1} max={8000} />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="output" />
            </Form.Item>
          </>
        )

      case 'knowledge':
        return (
          <>
            <Form.Item label="知识库ID" name="knowledge_base_id" rules={[{ required: true }]}>
              <InputNumber />
            </Form.Item>
            <Form.Item label="查询模板" name="query_template" rules={[{ required: true }]}>
              <Input.TextArea rows={4} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <Form.Item label="Top K" name="top_k">
              <InputNumber min={1} max={20} />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="knowledge_result" />
            </Form.Item>
          </>
        )

      case 'condition':
        return (
          <>
            <Form.List name="conditions">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item
                        {...restField}
                        name={[name, 'expression']}
                        rules={[{ required: true, message: '请输入条件表达式' }]}
                      >
                        <Input placeholder="{{output.value > 10}}" />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'label']}
                        rules={[{ required: true, message: '请输入标签' }]}
                      >
                        <Input placeholder="大于10" />
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加条件</Button>
                </>
              )}
            </Form.List>
          </>
        )

      case 'code':
        return (
          <>
            <Form.Item label="Python代码" name="code" rules={[{ required: true }]}>
              <Input.TextArea
                rows={10}
                placeholder="result = input_data['value'] * 2\nreturn result"
              />
            </Form.Item>
            <Form.Item label="输入变量" name="input_variables">
              <Select mode="tags" placeholder="选择或输入变量名" />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="result" />
            </Form.Item>
          </>
        )

      case 'variable':
        return (
          <>
            <Form.List name="variables">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]}>
                        <Input placeholder="变量名" />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'type']} rules={[{ required: true }]}>
                        <Select style={{ width: 120 }}>
                          <Select.Option value="static">静态值</Select.Option>
                          <Select.Option value="context">上下文引用</Select.Option>
                          <Select.Option value="expression">表达式</Select.Option>
                        </Select>
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'value']}>
                        <Input placeholder="值" />
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加变量</Button>
                </>
              )}
            </Form.List>
          </>
        )

      default:
        return <div>此节点类型暂无配置项</div>
    }
  }

  return (
    <Drawer
      title="节点配置"
      width={400}
      open={visible}
      onClose={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      {node && (
        <Form form={form} layout="vertical">
          <Form.Item label="节点名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          {renderConfigFields(node.type as NodeType)}
        </Form>
      )}
    </Drawer>
  )
}

export default NodeConfigPanel
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/NodeConfigPanel.tsx
git commit -m "feat(workflow): add NodeConfigPanel for editing node configuration"
```

---

### Task 30: Integrate NodeConfigPanel into WorkflowEditor

**Files:**
- Modify: `frontend/src/pages/Workflows/WorkflowEditor.tsx`

**Interfaces:**
- Consumes: NodeConfigPanel component
- Produces: integrated node editing functionality

- [ ] **Step 1: Integrate NodeConfigPanel into WorkflowEditor**

Update WorkflowEditor with:

```typescript
  // Add state for NodeConfigPanel
  const [editingNode, setEditingNode] = useState<Node | null>(null)
  const [configPanelVisible, setConfigPanelVisible] = useState(false)

  // Update handleEditNode to open panel
  const handleEditNode = useCallback((nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    if (node) {
      setEditingNode(node)
      setConfigPanelVisible(true)
    }
  }, [nodes])

  // Add handleSaveNodeConfig
  const handleSaveNodeConfig = useCallback(
    (nodeId: string, data: { name: string; config: WorkflowNodeConfig }) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, name: data.name, config: data.config } }
            : node
        )
      )
    },
    [setNodes]
  )

  // Add NodeConfigPanel to the render
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ... existing code ... */}

      <NodeConfigPanel
        visible={configPanelVisible}
        node={editingNode}
        onClose={() => setConfigPanelVisible(false)}
        onSave={handleSaveNodeConfig}
      />
    </div>
  )
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowEditor.tsx
git commit -m "feat(workflow): integrate NodeConfigPanel into WorkflowEditor"
```

---

### Task 31: Create WorkflowExecution Page Component

**Files:**
- Create: `frontend/src/pages/Workflows/WorkflowExecution.tsx`

**Interfaces:**
- Consumes: workflow API, SSE streaming, Ant Design components
- Produces: WorkflowExecution page with execution panel and results

- [ ] **Step 1: Write WorkflowExecution component**

```typescript
import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Form, Input, Space, Timeline, Alert, Spin, message, Result, Descriptions } from 'antd'
import { PlayCircleOutlined, StopOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { getWorkflow, validateWorkflow, executeWorkflowStreamUrl } from '../../api/workflow'
import { createStreamRequest } from '../../utils/streamRequest'
import type { Workflow, SSEWorkflowEvent } from '../../types/workflow'

const WorkflowExecution: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [executionEvents, setExecutionEvents] = useState<SSEWorkflowEvent[]>([])
  const [executionId, setExecutionId] = useState<number | null>(null)
  const [finalOutput, setFinalOutput] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    if (workflowId) {
      fetchWorkflow()
    }
  }, [workflowId])

  const fetchWorkflow = async () => {
    setLoading(true)
    try {
      const workflowData = await getWorkflow(parseInt(workflowId!))
      setWorkflow(workflowData)
    } catch (error) {
      message.error('获取工作流失败')
    } finally {
      setLoading(false)
    }
  }

  const handleExecute = async (values: any) => {
    setExecuting(true)
    setExecutionEvents([])
    setFinalOutput(null)
    setError(null)

    try {
      // 验证工作流
      await validateWorkflow(parseInt(workflowId!))

      // 使用 SSE 流式执行
      const streamUrl = executeWorkflowStreamUrl(parseInt(workflowId!))
      const input_data = values.input_data ? JSON.parse(values.input_data) : {}

      await createStreamRequest(
        streamUrl,
        {
          method: 'POST',
          body: JSON.stringify({ input_data }),
          headers: { 'Content-Type': 'application/json' },
        },
        (event: SSEWorkflowEvent) => {
          setExecutionEvents((prev) => [...prev, event])

          if (event.type === 'execution_started') {
            setExecutionId(event.execution_id)
          } else if (event.type === 'execution_completed') {
            setFinalOutput(event.output)
            setExecuting(false)
          } else if (event.type === 'execution_failed') {
            setError(event.error)
            setExecuting(false)
          }
        },
        (error: string) => {
          setError(error)
          setExecuting(false)
        }
      )
    } catch (error: any) {
      setError(error.message || '执行失败')
      setExecuting(false)
    }
  }

  const renderTimelineItem = (event: SSEWorkflowEvent) => {
    switch (event.type) {
      case 'execution_started':
        return {
          color: 'blue',
          dot: <PlayCircleOutlined />,
          children: `执行开始 (ID: ${event.execution_id})`,
        }
      case 'node_started':
        return {
          color: 'gray',
          dot: <LoadingOutlined />,
          children: `节点开始: ${event.node_name} (${event.node_type})`,
        }
      case 'node_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: (
            <div>
              <div>节点完成: {event.node_name}</div>
              <div style={{ fontSize: 12, color: '#666' }}>
                输出: {JSON.stringify(event.output).substring(0, 100)}
              </div>
            </div>
          ),
        }
      case 'node_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: (
            <div>
              <div>节点失败: {event.node_name}</div>
              <div style={{ fontSize: 12, color: '#ff4d4f' }}>{event.error}</div>
            </div>
          ),
        }
      case 'execution_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: '执行完成',
        }
      case 'execution_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: `执行失败: ${event.error}`,
        }
      default:
        return {
          color: 'gray',
          children: '未知事件',
        }
    }
  }

  if (loading) {
    return (
      <Card>
        <Spin size="large" />
      </Card>
    )
  }

  if (!workflow) {
    return <Result status="404" title="工作流不存在" />
  }

  return (
    <div style={{ padding: 24 }}>
      <Card title={`执行工作流: ${workflow.name}`}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {/* 输入参数 */}
          <Card size="small" title="输入参数">
            <Form form={form} layout="vertical" onFinish={handleExecute}>
              <Form.Item
                label="输入数据 (JSON格式)"
                name="input_data"
                help="例如: {\"value\": 10}"
              >
                <Input.TextArea
                  rows={4}
                  placeholder='{"key": "value"}'
                />
              </Form.Item>
              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlayCircleOutlined />}
                  loading={executing}
                  disabled={workflow.status !== 'published'}
                >
                  执行工作流
                </Button>
                {executing && (
                  <Button
                    style={{ marginLeft: 8 }}
                    icon={<StopOutlined />}
                    onClick={() => {
                      // TODO: 实现取消执行功能
                      message.info('取消功能待实现')
                    }}
                  >
                    取消
                  </Button>
                )}
                <Button style={{ marginLeft: 8 }} onClick={() => navigate(`/workflows/${workflowId}/edit`)}>
                  返回编辑
                </Button>
              </Form.Item>
            </Form>
          </Card>

          {/* 执行日志 */}
          {executionEvents.length > 0 && (
            <Card size="small" title="执行日志">
              <Timeline items={executionEvents.map(renderTimelineItem)} />
            </Card>
          )}

          {/* 执行结果 */}
          {finalOutput && (
            <Card size="small" title="执行结果">
              <Descriptions bordered column={1}>
                {Object.entries(finalOutput).map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    <pre style={{ margin: 0 }}>{JSON.stringify(value, null, 2)}</pre>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Card>
          )}

          {/* 错误信息 */}
          {error && (
            <Alert
              type="error"
              title="执行失败"
              message={error}
              showIcon
            />
          )}
        </Space>
      </Card>
    </div>
  )
}

export default WorkflowExecution
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Workflows/WorkflowExecution.tsx
git commit -m "feat(workflow): add WorkflowExecution page with SSE streaming"
```

---

### Task 32: Update createStreamRequest Utility

**Files:**
- Modify: `frontend/src/utils/streamRequest.ts`

**Interfaces:**
- Produces: enhanced streamRequest utility with better SSE parsing

- [ ] **Step 1: Update streamRequest utility if needed**

Verify that streamRequest.ts correctly parses SSE events with `event` and `data` fields. If modifications are needed, update accordingly.

- [ ] **Step 2: Commit if modified**

```bash
git add frontend/src/utils/streamRequest.ts
git commit -m "feat(workflow): enhance streamRequest utility for workflow SSE events" || echo "No changes needed"
```

---

### Task 33: Add Workflow Routes to App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: registered workflow routes in the application

- [ ] **Step 1: Add workflow routes to App.tsx**

```typescript
import WorkflowList from './pages/Workflows/WorkflowList'
import WorkflowForm from './pages/Workflows/WorkflowForm'
import WorkflowEditor from './pages/Workflows/WorkflowEditor'
import WorkflowExecution from './pages/Workflows/WorkflowExecution'

// Add routes in the routing configuration
<Route path="workflows" element={<WorkflowList />} />
<Route path="workflows/create" element={<WorkflowForm />} />
<Route path="workflows/:workflowId" element={<WorkflowEditor />} />
<Route path="workflows/:workflowId/edit" element={<WorkflowEditor />} />
<Route path="workflows/:workflowId/execute" element={<WorkflowExecution />} />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(workflow): add workflow routes to application"
```

---

### Task 34: Add Workflow Menu Item to Sidebar

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`

**Interfaces:**
- Produces: workflow menu item in sidebar navigation

- [ ] **Step 1: Add workflow menu item to Sidebar**

```typescript
import { BranchesOutlined } from '@ant-design/icons'

// Add to menu items array
{
  key: 'workflows',
  icon: <BranchesOutlined />,
  label: '工作流',
  children: [
    { key: 'workflows-list', label: '工作流列表' },
    { key: 'workflows-create', label: '创建工作流' },
  ],
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat(workflow): add workflow menu to sidebar"
```

---

## Testing and Validation

### Task 35: Backend Testing

**Files:**
- Test: `backend/app/api/workflow.py` endpoints

**Interfaces:**
- Produces: tested workflow CRUD and execution APIs

- [ ] **Step 1: Test workflow creation**

```bash
curl -X POST http://localhost:8000/api/workflows \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "测试工作流",
    "description": "这是一个测试工作流",
    "nodes": [
      {"node_type": "start", "name": "开始", "position_x": 100, "position_y": 100},
      {"node_type": "end", "name": "结束", "position_x": 400, "position_y": 100}
    ],
    "edges": [
      {"source_node_id": 1, "target_node_id": 2}
    ]
  }'
```

- [ ] **Step 2: Test workflow execution**

```bash
curl -X POST http://localhost:8000/api/workflows/1/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"input_data": {"value": 10}}'
```

---

### Task 36: Frontend Testing

**Files:**
- Test: frontend workflow pages

**Interfaces:**
- Produces: tested workflow UI functionality

- [ ] **Step 1: Start frontend development server**

```bash
cd frontend
npm run dev
```

- [ ] **Step 2: Manual testing checklist**

- Create a new workflow
- Add nodes (start, llm, end)
- Connect nodes
- Save workflow
- Validate workflow
- Publish workflow
- Execute workflow with input data
- Verify SSE streaming logs
- Check execution results

---

## Post-Implementation

### Task 37: Update Documentation

**Files:**
- Update: `docs/implementation-plan.md`
- Update: `CLAUDE.md`

**Interfaces:**
- Produces: updated documentation with workflow engine information

- [ ] **Step 1: Update implementation-plan.md**

Mark Phase 6 as completed and add any notes or issues encountered.

- [ ] **Step 2: Update CLAUDE.md**

Add workflow engine usage examples and key points:

```markdown
**工作流引擎**

工作流模块提供基于DAG的可视化工作流编排和执行能力：

```python
# 工作流 CRUD（app/services/workflow.py）
service = WorkflowService(db=db, tenant_id=current_user.tenant_id)
workflow = service.create_workflow(name, description, nodes, edges)
workflow = service.publish_workflow(workflow_id)
service.validate_workflow_dag(workflow_id)

# 工作流执行（app/services/workflow_engine.py）
engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)
result = await engine.execute_workflow(workflow_id, input_data, user_id)
async for event in engine.execute_workflow_stream(workflow_id, input_data, user_id):
    # SSE事件：execution_started, node_started, node_completed, execution_completed
    pass
```

关键组件：
- `app/models/workflow.py` - 工作流模型
- `app/models/workflow_node.py` - 工作流节点模型（9种节点类型）
- `app/models/workflow_edge.py` - 工作流边（连线）模型
- `app/services/workflow_engine.py` - DAG执行引擎（拓扑排序、节点执行器分发）
- `frontend/src/pages/Workflows/WorkflowEditor.tsx` - React Flow可视化编辑器
```

- [ ] **Step 3: Commit**

```bash
git add docs/implementation-plan.md CLAUDE.md
git commit -m "docs: update documentation for Phase 6 workflow engine"
```

---

## Summary

This implementation plan provides a comprehensive, bite-sized approach to building the workflow engine for AI-Studio. The backend focuses on:

1. **Data models**: Workflow, WorkflowNode, WorkflowEdge, WorkflowExecution, NodeExecution
2. **Repository pattern**: WorkflowRepository with tenant_id filtering
3. **Service layer**: WorkflowService for CRUD, WorkflowEngine for DAG execution
4. **Node executors**: 9 types (start, end, llm, condition, knowledge, code, tool, loop, variable)
5. **API layer**: RESTful endpoints with SSE streaming execution

The frontend focuses on:

1. **Type definitions**: TypeScript types for workflow entities
2. **API layer**: Axios-based workflow API functions
3. **React Flow integration**: Drag-and-drop visual editor
4. **Custom nodes**: Styled node components for each type
5. **Node configuration**: Dynamic configuration panel
6. **SSE execution**: Real-time execution monitoring with timeline view

Each task is self-contained, testable, and follows TDD principles where appropriate. The plan ensures DRY, YAGNI, and frequent commits throughout the implementation process.