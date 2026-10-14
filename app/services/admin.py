"""平台租户开通服务与内部租户清理任务。"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.models.knowledge_base import KnowledgeBase
from app.models.workflow import Workflow
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.core.exceptions import ConflictException
from app.models.role import Role
from app.models.user_role import user_role
from app.core.security import hash_password
from app.services.membership import sync_membership_owner, sync_membership_roles

# 支持软删除的租户维度模型（级联软删除）
_SOFT_DELETE_MODELS = [User, AIProvider, AIModel, KnowledgeBase, Workflow, Agent]


def create_tenant(data: dict, db: Session) -> Tenant:
    if db.query(Tenant).filter(Tenant.name == data["name"], Tenant.deleted_at.is_(None)).first():
        raise ConflictException("Tenant name already exists")
    if db.query(User).filter(User.email == data["admin_email"]).first():
        raise ConflictException("Admin email already registered")
    tenant = Tenant(
        name=data["name"],
        description=data.get("description"),
        plan="free",
        max_users=10,
        max_models=5,
        is_system_init=False,
    )
    db.add(tenant)
    db.flush()
    admin_role, _ = _init_builtin_roles(tenant.id, db)
    admin_user = User(
        tenant_id=tenant.id,
        email=data["admin_email"],
        password_hash=hash_password(data["admin_password"]),
        email_verified=True,
    )
    db.add(admin_user)
    db.flush()
    tenant.owner_id = admin_user.id
    db.execute(user_role.insert().values(user_id=admin_user.id, role_id=admin_role.id))
    db.flush()
    sync_membership_roles(admin_user.id, tenant.id, db, role_ids=[admin_role.id])
    sync_membership_owner(tenant.id, None, admin_user.id, db)
    return tenant


def _init_builtin_roles(tenant_id: str, db: Session) -> tuple[Role, Role]:
    admin = Role(
        tenant_id=tenant_id,
        name="租户管理员",
        code=f"tenant_admin_{tenant_id}",
        description="租户管理员",
        is_admin=True,
    )
    member = Role(tenant_id=tenant_id, name="租户成员", code=f"tenant_member_{tenant_id}", description="租户普通成员")
    db.add(admin)
    db.add(member)
    db.flush()
    from app.services.role import grant_all_tenant_permissions, grant_default_member_permissions
    grant_all_tenant_permissions(admin, db)
    grant_default_member_permissions(member, db)
    return admin, member


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
