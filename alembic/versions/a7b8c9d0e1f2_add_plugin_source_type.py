"""plugin types: add source_type (接入方式) & migrate provider -> connector

引入插件类型体系的第二维度「接入方式」``plugins.source_type``（http/mcp/skill），
并清理与 ``/api/ai-providers`` 语义重叠的历史取值 ``provider``。

Revision ID: a7b8c9d0e1f2
Revises: phase7_plugin_system
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'phase7_plugin_system'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 维度 B · 接入方式：新建列默认 http（当前执行器唯一落地的形态）。
    op.add_column(
        'plugins',
        sa.Column(
            'source_type',
            sa.String(length=50),
            nullable=False,
            server_default='http',
        ),
    )
    # 维度 A · 能力形态：provider 与 ai-providers 语义重叠，统一改写为 connector。
    op.execute("UPDATE plugins SET plugin_type = 'connector' WHERE plugin_type = 'provider'")


def downgrade() -> None:
    op.drop_column('plugins', 'source_type')
