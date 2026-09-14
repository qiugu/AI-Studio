"""drop unused api_keys table (dead code removal)

ApiKey 模型与 ``security.generate_api_key`` 已从代码中移除（详见
``docs/review/01-backend.md`` 的 A2 条目）。该表从未被任何 service / route 引用，
属于未接入的死代码；此处清理其 schema，避免新部署仍创建无用的孤立表。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-12
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS api_keys")


def downgrade():
    # 死代码表，不再重建；如需恢复请回滚代码并重新生成迁移。
    pass
