"""M2.0: drop plugins.plugin_type（移除「能力形态」维度）

能力形态 ``plugin_type``（tool / connector / processor）经评审确认立不住，故整体移除：

1. **边界不可判定**——同一插件可同时满足多个取值；
2. **零行为差异**——全仓不存在 ``if plugin_type ==`` 分支，它只用于列表筛选与展示；
3. **定义混入他者语义**——connector 的「地址/凭据/协议」属接入方式（``source_type``）。

插件形态此后由 ``source_type`` 单一维度承载（http / mcp / skill）。

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """检查列是否存在，使本迁移可幂等重跑（MySQL DDL 非事务，失败可能已部分生效）。"""
    bind = op.get_bind()
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if _has_column("plugins", "plugin_type"):
        op.drop_column("plugins", "plugin_type")


def downgrade() -> None:
    """仅恢复列结构，不还原历史取值。

    ``plugin_type`` 无行为语义（纯展示/筛选），故丢值可接受；如需还原真实取值，
    请从迁移前备份恢复。默认值沿用建表时的 ``'tool'``（见 ``phase7_plugin_system``）。
    """
    if not _has_column("plugins", "plugin_type"):
        op.add_column(
            "plugins",
            sa.Column(
                "plugin_type",
                sa.String(length=50),
                nullable=False,
                server_default="tool",
            ),
        )
