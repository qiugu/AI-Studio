"""Add one-time password reset tokens and credential session versioning."""
from alembic import op
import sqlalchemy as sa


revision = "q1_password_reset_tokens"
down_revision = "p2_permission_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("credentials_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_password_reset_tokens_tenant_id",
        "password_reset_tokens",
        ["tenant_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_requested_by",
        "password_reset_tokens",
        ["requested_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_requested_by", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_tenant_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "credentials_version")
