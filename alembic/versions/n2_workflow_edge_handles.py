"""Persist React Flow source and target handle identifiers."""

from alembic import op
import sqlalchemy as sa


revision = "n2_workflow_edge_handles"
down_revision = "m1_tenant_role_boundaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_edges",
        sa.Column("source_handle", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "workflow_edges",
        sa.Column("target_handle", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_edges", "target_handle")
    op.drop_column("workflow_edges", "source_handle")
