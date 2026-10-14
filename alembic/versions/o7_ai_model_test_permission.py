"""Add the missing tenant permission for testing an AI model."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "o7_ai_model_test_permission"
down_revision = "o6_authorization_audit_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text(
            "SELECT id FROM permissions "
            "WHERE resource=:resource AND action=:action LIMIT 1"
        ),
        {"resource": "ai_model", "action": "test"},
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
                "resource": "ai_model",
                "action": "test",
                "description": "测试 AI 模型",
            },
        )

    admin_roles = bind.execute(
        sa.text("SELECT id FROM roles WHERE is_admin = :is_admin"),
        {"is_admin": True},
    ).all()
    for (role_id,) in admin_roles:
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


def downgrade() -> None:
    # Keep the catalog row and grants during rollback so existing custom roles
    # do not lose a permission binding unexpectedly.
    pass
