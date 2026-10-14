"""Enforce tenant role boundaries and repair built-in role assignments."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "m1_tenant_role_boundaries"
down_revision = "k6l7m8n9o0p3"
branch_labels = None
depends_on = None


MEMBER_PERMISSIONS = (
    ("knowledge", "read", "查看知识库"),
    ("agent", "read", "查看 Agent"),
    ("agent", "chat", "使用 Agent 对话"),
    ("workflow", "read", "查看工作流"),
    ("workflow", "execute", "执行工作流"),
)


def upgrade() -> None:
    bind = op.get_bind()
    allowed_permission_ids = []
    for resource, action, description in MEMBER_PERMISSIONS:
        permission_id = bind.execute(
            sa.text(
                "SELECT id FROM permissions WHERE resource=:resource AND action=:action LIMIT 1"
            ),
            {"resource": resource, "action": action},
        ).scalar()
        if permission_id is None:
            permission_id = str(uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, resource, action, description) "
                    "VALUES (:id, :resource, :action, :description)"
                ),
                {
                    "id": permission_id,
                    "resource": resource,
                    "action": action,
                    "description": description,
                },
            )

        allowed_permission_ids.append(permission_id)

    tenants = bind.execute(sa.text("SELECT id, owner_id FROM tenants")).all()
    for tenant_id, owner_id in tenants:
        roles = bind.execute(
            sa.text("SELECT id, code FROM roles WHERE tenant_id=:tenant_id"),
            {"tenant_id": tenant_id},
        ).all()
        roles_by_code = {code: role_id for role_id, code in roles}
        admin_code = f"tenant_admin_{tenant_id}"
        member_code = f"tenant_member_{tenant_id}"

        admin_id = roles_by_code.get(admin_code)
        if admin_id is None:
            admin_id = str(uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO roles (id, tenant_id, name, code, description, status, is_admin) "
                    "VALUES (:id, :tenant_id, '租户管理员', :code, '租户管理员', 1, 1)"
                ),
                {"id": admin_id, "tenant_id": tenant_id, "code": admin_code},
            )
        else:
            bind.execute(
                sa.text("UPDATE roles SET is_admin=1 WHERE id=:role_id"),
                {"role_id": admin_id},
            )

        member_id = roles_by_code.get(member_code)
        if member_id is None:
            member_id = str(uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO roles (id, tenant_id, name, code, description, status, is_admin) "
                    "VALUES (:id, :tenant_id, '租户成员', :code, '租户普通成员', 1, 0)"
                ),
                {"id": member_id, "tenant_id": tenant_id, "code": member_code},
            )

        for permission_id in allowed_permission_ids:
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions WHERE role_id=:role_id "
                    "AND permission_id=:permission_id"
                ),
                {"role_id": member_id, "permission_id": permission_id},
            ).first()
            if exists is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "VALUES (:role_id, :permission_id)"
                    ),
                    {"role_id": member_id, "permission_id": permission_id},
                )

        role_permissions = sa.table(
            "role_permissions",
            sa.column("role_id", sa.String(36)),
            sa.column("permission_id", sa.String(36)),
        )
        bind.execute(
            sa.delete(role_permissions).where(
                role_permissions.c.role_id == member_id,
                role_permissions.c.permission_id.not_in(allowed_permission_ids),
            )
        )

        if owner_id:
            owner_link = bind.execute(
                sa.text(
                    "SELECT 1 FROM user_roles WHERE user_id=:user_id AND role_id=:role_id"
                ),
                {"user_id": owner_id, "role_id": admin_id},
            ).first()
            if owner_link is None:
                bind.execute(
                    sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": owner_id, "role_id": admin_id},
                )

        unassigned_users = bind.execute(
            sa.text(
                "SELECT u.id FROM users u LEFT JOIN user_roles ur ON ur.user_id=u.id "
                "WHERE u.tenant_id=:tenant_id AND u.deleted_at IS NULL AND ur.user_id IS NULL"
            ),
            {"tenant_id": tenant_id},
        ).all()
        for (user_id,) in unassigned_users:
            role_id = admin_id if user_id == owner_id else member_id
            bind.execute(
                sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                {"user_id": user_id, "role_id": role_id},
            )


def downgrade() -> None:
    # Data repair and role grants are intentionally retained on downgrade.
    pass
