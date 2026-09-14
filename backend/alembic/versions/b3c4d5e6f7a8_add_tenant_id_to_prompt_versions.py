"""add tenant_id to prompt_versions (S4 defense-in-depth)

``prompt_versions`` 原先缺少 ``tenant_id``，导致按版本查询无法在 DB 层强制租户隔离，
仅依赖 Service 层手工过滤（见 ``docs/review/01-backend.md`` S4）。本迁移新增列并从父表
``prompts`` 回填租户，使租户条件可下推到查询层。

本迁移为幂等实现：部分真实库可能已存在 ``tenant_id`` 列但 alembic_version 未记录
（schema 与迁移进度不同步），直接重放 ``ADD COLUMN`` 会触发 MySQL 1060
（Duplicate column name）。因此每一步都先通过 inspector 检查真实结构：
- 列不存在 → 新增；
- 列存在但类型不是 String → 改为 VARCHAR(36)；
- 存在 NULL → 回填；
- 仍可为空 → 收紧为 NOT NULL。

Revision ID: b3c4d5e6f7a8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def _tenant_column(bind):
    """返回 prompt_versions.tenant_id 的真实列信息；列不存在时返回 None。"""
    inspector = sa.inspect(bind)
    if not inspector.has_table('prompt_versions'):
        return None
    for column in inspector.get_columns('prompt_versions'):
        if column['name'] == 'tenant_id':
            return column
    return None


def upgrade():
    bind = op.get_bind()
    column = _tenant_column(bind)

    # 1) 列不存在才新增，避免重放时触发 MySQL 1060 Duplicate column。
    if column is None:
        op.add_column(
            'prompt_versions',
            sa.Column('tenant_id', sa.String(36), nullable=True, index=True),
        )
    elif not isinstance(column['type'], sa.String):
        # 列存在但类型不符（如 BigInteger），统一为 VARCHAR(36)。
        # batch_alter_table 在 SQLite 上走重建表、在 MySQL 上走原生 ALTER，跨方言安全。
        with op.batch_alter_table('prompt_versions') as batch_op:
            batch_op.alter_column(
                'tenant_id',
                existing_type=column['type'],
                type_=sa.String(length=36),
                existing_nullable=column['nullable'],
            )

    # 2) 回填历史数据：沿用父表 prompts 的租户。
    #    使用关联子查询而非 MySQL 专用的 UPDATE ... JOIN，保证跨方言可执行。
    op.execute(
        "UPDATE prompt_versions "
        "SET tenant_id = (SELECT p.tenant_id FROM prompts p WHERE p.id = prompt_versions.prompt_id) "
        "WHERE tenant_id IS NULL OR tenant_id = ''"
    )

    # 3) 仍可为空时才收紧为 NOT NULL（已 NOT NULL 则为 no-op，保证幂等）。
    #    必须显式传 existing_type：MySQL 的 MODIFY/CHANGE COLUMN 需完整列定义，
    #    alembic 在缺少 existing_type 时会直接报错
    #    "All MySQL CHANGE/MODIFY COLUMN operations require the existing type."，
    #    导致本迁移在 MySQL 上整条无法执行（版本表长期停留在父版本）。
    column = _tenant_column(bind)
    if column is not None and column['nullable']:
        with op.batch_alter_table('prompt_versions') as batch_op:
            batch_op.alter_column(
                'tenant_id',
                existing_type=column['type'],
                existing_nullable=column['nullable'],
                nullable=False,
            )


def downgrade():
    bind = op.get_bind()
    if _tenant_column(bind) is not None:
        op.drop_column('prompt_versions', 'tenant_id')
