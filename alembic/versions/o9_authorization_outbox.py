"""Add transactional outbox for authorization-sensitive changes."""
from alembic import op
import sqlalchemy as sa


revision = "o9_authorization_outbox"
down_revision = "o8_knowledge_base_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authorization_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_authorization_outbox_tenant_id", "authorization_outbox", ["tenant_id"])
    op.create_index("ix_authorization_outbox_actor_id", "authorization_outbox", ["actor_id"])
    op.create_index("ix_authorization_outbox_event_type", "authorization_outbox", ["event_type"])
    op.create_index("ix_authorization_outbox_status", "authorization_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_authorization_outbox_status", table_name="authorization_outbox")
    op.drop_index("ix_authorization_outbox_event_type", table_name="authorization_outbox")
    op.drop_index("ix_authorization_outbox_actor_id", table_name="authorization_outbox")
    op.drop_index("ix_authorization_outbox_tenant_id", table_name="authorization_outbox")
    op.drop_table("authorization_outbox")
