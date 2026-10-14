"""convert prompt tables id columns to varchar(36) (match models)

两个阶段的历史迁移存在分叉：
- ``93a1c4f6255f_phase3_add_prompt_tables`` 以 ``BigInteger`` 自增建立了
  ``prompts`` / ``prompt_versions`` / ``prompt_test_logs`` 的全部主键与外键列。
- ``f7a3b8c7d9e0_change_uuid_columns_to_string36`` 意图把所有主键/外键列改为
  ``VARCHAR(36)``（其 ``COLUMNS_BY_TABLE`` 已包含这三张表），但它与 prompt 表所在
  的迁移链不相交，导致该转换在很多部署中并未真正落到 prompt 表上。

结果：模型把 ``id`` / ``tenant_id`` / ``prompt_id`` / ``created_by`` 等声明为
``String(36)`` UUID，而真实库中这些列仍是 ``BigInteger``。调用 ``create_version``
/ ``create`` 时往 BigInteger 列写入 UUID 字符串，MySQL 严格模式下直接 500
（Incorrect integer value）。

本迁移幂等地将这三张表的 ID 类列统一为 ``VARCHAR(36)``，与全库（及
``f7a3b8c7d9e0`` 的意图、``AGENTS.md`` 中“核心业务 ID 统一为 String(36) UUID”的约定）保持一致：
- 若某列已是 ``String`` 类型则跳过（no-op），因此重复执行安全。
- 若真实库已经是 String(36)，整段迁移即为空操作。

Revision ID: d1e2f3a4b5c6
Revises: b3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


# 与 f7a3b8c7d9e0 中的定义保持一致，限定 prompt 相关表
COLUMNS_BY_TABLE = {
    'prompts': ['id', 'tenant_id', 'created_by'],
    'prompt_versions': ['id', 'prompt_id', 'created_by'],
    'prompt_test_logs': ['id', 'prompt_id', 'version_id', 'tenant_id', 'model_id'],
}


def _get_target_tables(inspector):
    return [table_name for table_name in COLUMNS_BY_TABLE if inspector.has_table(table_name)]


def _drop_foreign_keys(bind, table_name, inspector):
    foreign_keys = inspector.get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if not foreign_key.get('name'):
            continue
        try:
            op.drop_constraint(foreign_key['name'], table_name, type_='foreignkey')
        except Exception:
            pass


def _recreate_foreign_keys(bind, table_name, inspector):
    foreign_keys = inspector.get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if not foreign_key.get('name'):
            continue
        constraint_name = foreign_key['name']
        try:
            op.create_foreign_key(
                constraint_name,
                table_name,
                foreign_key['referred_table'],
                foreign_key['constrained_columns'],
                foreign_key['referred_columns'],
                ondelete=foreign_key.get('options', {}).get('ondelete'),
                onupdate=foreign_key.get('options', {}).get('onupdate'),
            )
        except Exception:
            pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    target_tables = _get_target_tables(inspector)

    # 仅 MySQL 需要临时关闭外键检查；SQLite 默认不强制，跳过即可。
    is_mysql = bind.dialect.name == 'mysql'
    if is_mysql:
        bind.execute(sa.text("SET foreign_key_checks = 0"))
    try:
        for table_name in target_tables:
            _drop_foreign_keys(bind, table_name, inspector)

        for table_name in target_tables:
            existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            if not existing_columns:
                continue

            with op.batch_alter_table(table_name, schema=None) as batch_op:
                for column_name in COLUMNS_BY_TABLE[table_name]:
                    if column_name not in existing_columns:
                        continue

                    column = existing_columns[column_name]
                    existing_type = column['type']
                    # 已是 String 类型则跳过，保证幂等（重复执行安全）
                    if isinstance(existing_type, sa.String):
                        continue

                    batch_op.alter_column(
                        column_name,
                        existing_type=existing_type,
                        type_=sa.String(length=36),
                        existing_nullable=column['nullable'],
                    )

        for table_name in target_tables:
            _recreate_foreign_keys(bind, table_name, inspector)
    finally:
        if is_mysql:
            bind.execute(sa.text("SET foreign_key_checks = 1"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    target_tables = _get_target_tables(inspector)

    is_mysql = bind.dialect.name == 'mysql'
    if is_mysql:
        bind.execute(sa.text("SET foreign_key_checks = 0"))
    try:
        for table_name in target_tables:
            _drop_foreign_keys(bind, table_name, inspector)

        for table_name in target_tables:
            existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            for column_name in COLUMNS_BY_TABLE[table_name]:
                if column_name not in existing_columns:
                    continue
                column = existing_columns[column_name]
                if isinstance(column['type'], sa.String):
                    with op.batch_alter_table(table_name, schema=None) as batch_op:
                        batch_op.alter_column(
                            column_name,
                            existing_type=sa.String(length=36),
                            type_=sa.BigInteger(),
                            existing_nullable=column['nullable'],
                        )

        for table_name in target_tables:
            _recreate_foreign_keys(bind, table_name, inspector)
    finally:
        if is_mysql:
            bind.execute(sa.text("SET foreign_key_checks = 1"))
