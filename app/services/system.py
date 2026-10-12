"""系统设置服务：当前租户信息、配额用量。"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.ai_model import AIModel
from app.models.agent import Agent
from app.models.knowledge_base import KnowledgeBase
from app.core.exceptions import NotFoundException


def get_tenant_settings(tenant_id: str, db: Session) -> dict:
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .first()
    )
    if not tenant:
        raise NotFoundException("Tenant", tenant_id)

    user_count = (
        db.query(User).filter(User.tenant_id == tenant_id, User.deleted_at.is_(None)).count()
    )
    model_count = db.query(AIModel).filter(AIModel.tenant_id == tenant_id).count()
    agent_count = (
        db.query(Agent).filter(Agent.tenant_id == tenant_id, Agent.deleted_at.is_(None)).count()
    )
    kb_count = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.deleted_at.is_(None))
        .count()
    )

    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description,
        "plan": tenant.plan,
        "max_users": tenant.max_users,
        "max_models": tenant.max_models,
        "status": tenant.status,
        "created_at": tenant.created_at,
        "usage": {
            "user_count": user_count,
            "model_count": model_count,
            "agent_count": agent_count,
            "knowledge_base_count": kb_count,
        },
    }


def update_tenant_settings(tenant_id: str, data: dict, db: Session) -> dict:
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .first()
    )
    if not tenant:
        raise NotFoundException("Tenant", tenant_id)
    if data.get("name") is not None:
        tenant.name = data["name"]
    if "description" in data:
        tenant.description = data["description"]
    db.flush()
    return get_tenant_settings(tenant_id, db)
