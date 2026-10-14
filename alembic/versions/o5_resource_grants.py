"""Add explicit role-based resource sharing grants."""
from alembic import op
import sqlalchemy as sa


revision = "o5_resource_grants"
down_revision = "o4_user_authz_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False, server_default="role"),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_resource_grants_tenant_id", "resource_grants", ["tenant_id"])
    op.create_index("ix_resource_grants_resource_id", "resource_grants", ["resource_id"])
    op.create_index("ix_resource_grants_subject_id", "resource_grants", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_resource_grants_subject_id", table_name="resource_grants")
    op.drop_index("ix_resource_grants_resource_id", table_name="resource_grants")
    op.drop_index("ix_resource_grants_tenant_id", table_name="resource_grants")
    op.drop_table("resource_grants")
