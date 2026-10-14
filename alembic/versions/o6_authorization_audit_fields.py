"""Add structured authorization context to audit logs."""
from alembic import op
import sqlalchemy as sa


revision = "o6_authorization_audit_fields"
down_revision = "o5_resource_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("user_agent", sa.String(500), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("decision", sa.String(10), nullable=True))
    op.add_column("audit_logs", sa.Column("permission_key", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("target_type", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("target_id", sa.String(36), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("metadata", sa.JSON(), nullable=True))
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_permission_key", "audit_logs", ["permission_key"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_permission_key", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_column("audit_logs", "metadata")
    op.drop_column("audit_logs", "reason")
    op.drop_column("audit_logs", "target_id")
    op.drop_column("audit_logs", "target_type")
    op.drop_column("audit_logs", "permission_key")
    op.drop_column("audit_logs", "decision")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "user_agent")
