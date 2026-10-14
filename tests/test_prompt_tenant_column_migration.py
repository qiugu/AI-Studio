"""隔离验证 b3c4d5e6f7a8_add_tenant_id_to_prompt_versions 迁移的幂等性。

背景：部分真实库已存在 prompt_versions.tenant_id 列，但 alembic_version 未记录
该迁移已执行，upgrade 重放 ADD COLUMN 时触发 MySQL 1060（Duplicate column name）。

用 SQLite 构造两种初始状态分别验证：
A. 列缺失（原始缺陷态）→ 执行后列被新增、回填、收紧为 NOT NULL；
B. 列已存在（用户实际遇到的故障态）→ 重放不报错（幂等），数据不被破坏。
"""
import importlib.util
import os

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, Column, MetaData, Table, BigInteger, String, Text, Boolean, JSON, ForeignKey

MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "alembic", "versions",
    "b3c4d5e6f7a8_add_tenant_id_to_prompt_versions.py",
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("m_add_tenant", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_base_tables(meta):
    """tenants / users / prompts（bigint 形态，与本迁移无关，仅作回填来源）。"""
    Table(
        "tenants", meta,
        Column("id", String(36), primary_key=True),
        Column("name", String(255), nullable=False),
    )
    Table(
        "prompts", meta,
        Column("id", BigInteger(), autoincrement=True, nullable=False),
        Column("tenant_id", String(36), nullable=False),
        Column("name", String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _build_prompt_versions(meta, with_tenant_column: bool):
    cols = [
        Column("id", BigInteger(), autoincrement=True, nullable=False),
        Column("prompt_id", BigInteger(), nullable=False),
        Column("version_number", sa.Integer(), nullable=False),
        Column("content", Text(), nullable=False),
        Column("is_current", Boolean(), nullable=False),
    ]
    if with_tenant_column:
        cols.append(Column("tenant_id", String(36), nullable=True))
    cols += [
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),
    ]
    return Table("prompt_versions", meta, *cols)


def _run_with_op_ctx(engine, fn):
    """在 alembic op 上下文下执行迁移函数（不依赖 alembic CLI / 完整迁移链）。"""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    conn = engine.connect()
    try:
        ctx = MigrationContext.configure(conn)
        ops = Operations(ctx)
        mod = _load_migration_module()
        orig_op = mod.op
        mod.op = ops
        try:
            fn(mod, conn)
        finally:
            mod.op = orig_op
        conn.commit()
    finally:
        conn.close()


def _tenant_col_info(engine):
    insp = inspect(engine)
    for c in insp.get_columns("prompt_versions"):
        if c["name"] == "tenant_id":
            return c
    return None


def _seed_data(engine):
    """插入一条 prompt + 一条历史版本（tenant_id 为空，待回填）。"""
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO tenants (id, name) VALUES ('t-1', 'tenant')"))
        conn.execute(sa.text("INSERT INTO prompts (id, tenant_id, name) VALUES (1, 't-1', 'p')"))
        conn.execute(sa.text(
            "INSERT INTO prompt_versions (id, prompt_id, version_number, content, is_current) "
            "VALUES (1, 1, 1, 'hello', 1)"
        ))


def test_upgrade_adds_and_backfills_when_column_missing():
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    _build_base_tables(meta)
    _build_prompt_versions(meta, with_tenant_column=False)
    meta.create_all(engine)
    _seed_data(engine)

    def _up(mod, conn):
        mod.upgrade()

    _run_with_op_ctx(engine, _up)

    col = _tenant_col_info(engine)
    assert col is not None, "tenant_id 应被新增"
    assert isinstance(col["type"], sa.String)
    assert col["nullable"] is False, "回填后应收紧为 NOT NULL"

    # 回填正确：历史版本的 tenant_id 来自父表 prompts
    with engine.connect() as conn:
        val = conn.execute(sa.text("SELECT tenant_id FROM prompt_versions WHERE id = 1")).scalar()
    assert val == "t-1"


def test_upgrade_is_idempotent_when_column_already_exists():
    """复现用户故障态：tenant_id 已存在但迁移未记录 → 重放不再报 Duplicate column。"""
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    _build_base_tables(meta)
    _build_prompt_versions(meta, with_tenant_column=True)
    meta.create_all(engine)
    _seed_data(engine)

    def _up(mod, conn):
        mod.upgrade()

    # 第一次执行：跳过 ADD COLUMN，仅回填 + 收紧 NOT NULL，不应抛 1060 等错误
    _run_with_op_ctx(engine, _up)
    col = _tenant_col_info(engine)
    assert col is not None
    assert col["nullable"] is False
    with engine.connect() as conn:
        val = conn.execute(sa.text("SELECT tenant_id FROM prompt_versions WHERE id = 1")).scalar()
    assert val == "t-1"

    # 第二次执行（完全幂等）：不再抛错，数据不变
    _run_with_op_ctx(engine, _up)
    with engine.connect() as conn:
        val2 = conn.execute(sa.text("SELECT tenant_id FROM prompt_versions WHERE id = 1")).scalar()
    assert val2 == "t-1"


def test_downgrade_drops_column_when_present():
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    _build_base_tables(meta)
    _build_prompt_versions(meta, with_tenant_column=True)
    meta.create_all(engine)

    def _down(mod, conn):
        mod.downgrade()

    _run_with_op_ctx(engine, _down)
    assert _tenant_col_info(engine) is None, "downgrade 应删除 tenant_id 列"
