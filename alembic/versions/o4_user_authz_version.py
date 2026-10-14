"""Add a version counter used to invalidate stale authorization tokens."""
from alembic import op
import sqlalchemy as sa


revision = "o4_user_authz_version"
down_revision = "o3_rbac_permission_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("authz_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.alter_column(
        "users",
        "authz_version",
        server_default=None,
        existing_type=sa.Integer(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.drop_column("users", "authz_version")
