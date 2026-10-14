"""Add the optional creator reference used by knowledge-base authorization."""
from alembic import op
import sqlalchemy as sa


revision = "o8_knowledge_base_created_by"
down_revision = "o7_ai_model_test_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("created_by", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_knowledge_bases_created_by",
        "knowledge_bases",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_created_by", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "created_by")
