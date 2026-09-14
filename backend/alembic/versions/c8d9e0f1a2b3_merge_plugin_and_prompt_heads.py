"""merge 插件接入方式分支与 prompt 分支（消除双 head）

迁移链在 ``phase8_audit_monitoring`` 之后分叉，长期存在两个 head，
导致 ``alembic upgrade head`` 因多头而失败：

- 左支：``phase7_plugin_system`` → ``a7b8c9d0e1f2``（插件接入方式 ``source_type``）
- 右支：``b2c3d4e5f6a7`` → ``b3c4d5e6f7a8`` → ``d1e2f3a4b5c6``（prompt 表租户列与 ID 字符化）

本迁移**不含任何 DDL**，只做拓扑合并，使版本图收敛为单一 head。

两条分支改动互不相交（一为 ``plugins`` 表，一为 ``prompt*`` 表），合并顺序不影响结果。

Revision ID: c8d9e0f1a2b3
Revises: a7b8c9d0e1f2, d1e2f3a4b5c6
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op  # noqa: F401  (保留以便后续在该合并点追加 DDL)


# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = ('a7b8c9d0e1f2', 'd1e2f3a4b5c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """纯合并点：无结构变更。"""
    pass


def downgrade() -> None:
    """回退即重新拆分出两个 head，无结构变更。"""
    pass
