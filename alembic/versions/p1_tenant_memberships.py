"""Add staged tenant memberships and backfill the legacy authorization graph."""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "p1_tenant_memberships"
down_revision = "o9_authorization_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authz_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("joined_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_user"),
    )
    op.create_index(
        "ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"]
    )
    op.create_index(
        "ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"]
    )
    op.create_table(
        "membership_roles",
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["tenant_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "role_id"),
    )

    bind = op.get_bind()
    users = bind.execute(
        sa.text(
            "SELECT u.id, u.tenant_id, u.status, u.deleted_at, "
            "t.owner_id FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id"
        )
    ).mappings().all()
    membership_ids: dict[str, str] = {}
    for user in users:
        membership_id = str(uuid.uuid4())
        membership_ids[user["id"]] = membership_id
        bind.execute(
            sa.text(
                "INSERT INTO tenant_memberships "
                "(id, tenant_id, user_id, status, is_owner, authz_version, joined_at, removed_at) "
                "VALUES (:id, :tenant_id, :user_id, :status, :is_owner, 1, CURRENT_TIMESTAMP, :removed_at)"
            ),
            {
                "id": membership_id,
                "tenant_id": user["tenant_id"],
                "user_id": user["id"],
                "status": bool(user["status"]),
                "is_owner": user["owner_id"] == user["id"],
                "removed_at": user["deleted_at"],
            },
        )

    role_rows = bind.execute(
        sa.text(
            "SELECT ur.user_id, ur.role_id FROM user_roles ur "
            "JOIN users u ON u.id = ur.user_id "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE u.tenant_id = r.tenant_id"
        )
    ).all()
    for user_id, role_id in role_rows:
        membership_id = membership_ids.get(user_id)
        if membership_id is None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO membership_roles (membership_id, role_id) "
                "VALUES (:membership_id, :role_id)"
            ),
            {"membership_id": membership_id, "role_id": role_id},
        )


def downgrade() -> None:
    op.drop_table("membership_roles")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
