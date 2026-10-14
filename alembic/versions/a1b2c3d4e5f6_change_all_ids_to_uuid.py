"""change all ids to uuid

Revision ID: a1b2c3d4e5f6
Revises: fbb05b8897d5
Create Date: 2025-01-01
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'fbb05b8897d5'
branch_labels = None
depends_on = None


def upgrade():
    """
    Migrate all integer/BIGINT IDs to UUID strings.

    NOTE: 原实现使用 MySQL 不支持的 `UUID5()` 函数，会导致语法错误。
    经核查，后续迁移 `f7a3b8c7d9e0` 已将所有主键/外键列改为 VARCHAR(36)，
    当前数据库列类型即为 UUID 字符串，无需再做任何数据转换。
    因此此步骤改为幂等空操作，仅用于让迁移链路正常推进到 head。
    """
    pass


def downgrade():
    """此迁移为幂等占位，无实际 schema 变更，无需回滚。"""
    pass
