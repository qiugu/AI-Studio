"""modify knowledge_document original_content

Revision ID: fbb05b8897d5
Revises: add_knowledge_perms
Create Date: 2026-06-29 20:44:45.245521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbb05b8897d5'
down_revision: Union[str, Sequence[str], None] = 'add_knowledge_perms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 修改 original_content 字段，移除长度限制，允许存储完整的文档内容
    # MySQL 的 TEXT 类型最大支持 65535 字节，足够存储大型文档
    op.alter_column(
        'knowledge_documents',
        'original_content',
        existing_type=sa.Text(),
        type_=sa.Text(),
        nullable=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 回滚时恢复为带长度限制的 TEXT(2000)
    # 注意：如果已有数据超过2000字符，回滚会失败
    op.alter_column(
        'knowledge_documents',
        'original_content',
        existing_type=sa.Text(),
        type_=sa.Text(2000),
        nullable=True
    )
