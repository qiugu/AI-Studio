"""Seed the stable RBAC permission catalog and grant it to tenant admins."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from app.core.permissions import PERMISSION_CATALOG


revision = "o3_rbac_permission_catalog"
down_revision = "n2_workflow_edge_handles"
branch_labels = None
depends_on = None


def _permission_id(bind, resource: str, action: str, description: str) -> str:
    existing = bind.execute(
        sa.text(
            "SELECT id FROM permissions "
            "WHERE resource=:resource AND action=:action LIMIT 1"
        ),
        {"resource": resource, "action": action},
    ).scalar()
    if existing is not None:
        return str(existing)

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
    return permission_id


def _grant_if_missing(bind, role_id: str, permission_id: str) -> None:
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM role_permissions "
            "WHERE role_id=:role_id AND permission_id=:permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).first()
    if exists is None:
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    tenant_permission_ids: list[str] = []

    for definition in PERMISSION_CATALOG.values():
        permission_id = _permission_id(
            bind,
            definition.resource,
            definition.action,
            definition.description,
        )
        if definition.scope == "tenant":
            tenant_permission_ids.append(permission_id)

    admin_roles = bind.execute(
        sa.text("SELECT id FROM roles WHERE is_admin = :is_admin"),
        {"is_admin": True},
    ).all()
    for (role_id,) in admin_roles:
        for permission_id in tenant_permission_ids:
            _grant_if_missing(bind, str(role_id), permission_id)


def downgrade() -> None:
    # Permission catalog rows may be referenced by custom roles. Keep the data
    # during downgrade so rolling back code cannot silently remove grants.
    pass
