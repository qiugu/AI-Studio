"""平台管理服务（超级管理员）：租户 CRUD、配额、级联软删除、公共模型管理。"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.models.knowledge_base import KnowledgeBase
from app.models.workflow import Workflow
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.core.exceptions import NotFoundException, ConflictException

import uuid


# 支持软删除的租户维度模型（级联软删除）
_SOFT_DELETE_MODELS = [User, AIProvider, AIModel, KnowledgeBase, Workflow, Agent]


def _usage_for(tenant_id: str, db: Session) -> dict:
    return {
        "user_count": db.query(User).filter(User.tenant_id == tenant_id, User.deleted_at.is_(None)).count(),
        "model_count": db.query(AIModel).filter(AIModel.tenant_id == tenant_id).count(),
        "agent_count": db.query(Agent).filter(Agent.tenant_id == tenant_id, Agent.deleted_at.is_(None)).count(),
        "knowledge_base_count": db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.deleted_at.is_(None)).count(),
    }


def list_tenants(db: Session, page: int = 1, page_size: int = 20, search: Optional[str] = None):
    query = db.query(Tenant).filter(Tenant.deleted_at.is_(None))
    if search:
        like = f"%{search}%"
        query = query.filter(Tenant.name.like(like))
    total = query.count()
    items = query.order_by(Tenant.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    result = []
    for t in items:
        d = {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "plan": t.plan,
            "max_users": t.max_users,
            "max_models": t.max_models,
            "status": t.status,
            "is_system_init": t.is_system_init,
            "created_at": t.created_at,
            "usage": _usage_for(t.id, db),
        }
        result.append(d)
    return result, total


def get_tenant(tenant_id: str, db: Session) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if not tenant:
        raise NotFoundException("Tenant", tenant_id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description,
        "plan": tenant.plan,
        "max_users": tenant.max_users,
        "max_models": tenant.max_models,
        "status": tenant.status,
        "is_system_init": tenant.is_system_init,
        "created_at": tenant.created_at,
        "usage": _usage_for(tenant_id, db),
    }


def create_tenant(data: dict, db: Session) -> Tenant:
    if db.query(Tenant).filter(Tenant.name == data["name"], Tenant.deleted_at.is_(None)).first():
        raise ConflictException("Tenant name already exists")
    tenant = Tenant(
        name=data["name"],
        description=data.get("description"),
        plan=data.get("plan", "free"),
        max_users=data.get("max_users", 10),
        max_models=data.get("max_models", 5),
        is_system_init=False,
    )
    db.add(tenant)
    db.flush()
    # 初始化内置角色，保证新租户可用
    _init_builtin_roles(tenant.id, db)
    return tenant


def _init_builtin_roles(tenant_id: str, db: Session) -> None:
    from app.models.role import Role

    admin = Role(tenant_id=tenant_id, name="租户管理员", code=f"tenant_admin_{tenant_id}", description="租户管理员")
    member = Role(tenant_id=tenant_id, name="租户成员", code=f"tenant_member_{tenant_id}", description="租户普通成员")
    db.add(admin)
    db.add(member)
    db.flush()


def update_tenant(tenant_id: str, data: dict, db: Session) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if not tenant:
        raise NotFoundException("Tenant", tenant_id)
    if data.get("name") is not None:
        tenant.name = data["name"]
    if "description" in data:
        tenant.description = data["description"]
    if data.get("plan") is not None:
        tenant.plan = data["plan"]
    if data.get("status") is not None:
        tenant.status = data["status"]
    db.flush()
    return get_tenant(tenant_id, db)


def set_quota(tenant_id: str, max_users: Optional[int], max_models: Optional[int], db: Session) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if not tenant:
        raise NotFoundException("Tenant", tenant_id)
    if max_users is not None:
        tenant.max_users = max_users
    if max_models is not None:
        tenant.max_models = max_models
    db.flush()
    return get_tenant(tenant_id, db)


def cascade_soft_delete_tenant(tenant_id: str, db: Session) -> None:
    """
    级联软删除租户数据。
    保留: audit_logs / token_usages / model_call_logs（合规 & 计费依据）。
    """
    now = datetime.now(timezone.utc)
    for model in _SOFT_DELETE_MODELS:
        db.query(model).filter(model.tenant_id == tenant_id).update(
            {model.deleted_at: now}, synchronize_session=False
        )
    # conversation 无 deleted_at，直接硬删除（messages 随 FK CASCADE 删除）
    try:
        db.query(Conversation).filter(Conversation.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
    except Exception:
        pass
    # 标记租户为已删除 & 禁用
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        tenant.deleted_at = now
        tenant.status = False
    db.flush()


def delete_tenant(tenant_id: str, db: Session) -> None:
    """注销租户：级联软删除所有业务数据并标记租户删除。"""
    existing = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if not existing:
        raise NotFoundException("Tenant", tenant_id)
    cascade_soft_delete_tenant(tenant_id, db)
