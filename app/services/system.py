"""系统设置服务：当前租户信息、配额用量。"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.ai_model import AIModel
from app.models.agent import Agent
from app.models.knowledge_base import KnowledgeBase
from app.core.exceptions import NotFoundException
from app.core.exceptions import ForbiddenException, ValidationException
from app.core.reauthentication import require_current_password
from app.models.role import Role
from app.models.user_role import user_role
from app.models.audit_log import AuditLog
from app.services.authorization_audit import AuthorizationAuditService
from app.services.membership import sync_membership_owner, sync_membership_roles


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


def transfer_tenant_owner(
    tenant_id: str,
    target_user_id: str,
    current_password: str,
    actor: User,
    db: Session,
) -> Tenant:
    """Transfer ownership with explicit re-authentication and an audit event."""
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if tenant is None:
        raise NotFoundException("Tenant", tenant_id)
    if tenant.owner_id != actor.id:
        raise ForbiddenException("tenant", "owner_transfer")
    require_current_password(actor, current_password, "owner_transfer")

    target = (
        db.query(User)
        .filter(
            User.id == target_user_id,
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if target is None:
        raise NotFoundException("User", target_user_id)
    if not target.status:
        raise ValidationException("目标用户必须处于启用状态")

    previous_owner_id = tenant.owner_id
    admin_role = (
        db.query(Role)
        .filter(
            Role.tenant_id == tenant_id,
            Role.status.is_(True),
            Role.is_admin.is_(True),
        )
        .order_by(Role.created_at.asc())
        .first()
    )
    if admin_role is None:
        raise ValidationException("租户缺少可用的管理员角色")

    if target.id != tenant.owner_id:
        already_admin = db.execute(
            user_role.select().where(
                user_role.c.user_id == target.id,
                user_role.c.role_id == admin_role.id,
            )
        ).first()
        if already_admin is None:
            db.execute(
                user_role.insert().values(
                    user_id=target.id,
                    role_id=admin_role.id,
                )
            )
            target.authz_version = int(target.authz_version or 1) + 1
        tenant.owner_id = target.id
        actor.authz_version = int(actor.authz_version or 1) + 1
        sync_membership_roles(target.id, tenant_id, db)
        sync_membership_owner(tenant_id, previous_owner_id, target.id, db)

    AuthorizationAuditService(db).record_change(
        actor=actor,
        tenant_id=tenant_id,
        action="OWNER_TRANSFER",
        resource="tenant",
        target_type="TenantOwner",
        target_id=target.id,
        permission_key="tenant.settings",
        reason="owner_transfer_completed"
        if previous_owner_id != target.id
        else "owner_transfer_idempotent",
        metadata={
            "previous_owner_id": previous_owner_id,
            "new_owner_id": target.id,
        },
    )
    db.flush()
    return tenant
