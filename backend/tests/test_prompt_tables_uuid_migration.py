"""隔离验证 d1e2f3a4b5c6_convert_prompt_tables_to_uuid 迁移。

不依赖真实 MySQL：用 SQLite 构造一个“坏状态”库——prompt 三张表以 BigInteger
自增主键/外键建立（复刻 93a1c4f6255f 的真实形态），然后单独执行该迁移，
断言：
1. 迁移能无错执行；
2. id/外键列被改为 VARCHAR(36)（类型检查走 sa.String）；
3. 重复执行幂等（已是 String 则跳过，不再报错）；
4. downgrade 可回滚到 BigInteger，无异常。
"""
import importlib.util
import os
import types

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, Column, MetaData, Table, BigInteger, String, Text, Boolean, JSON, ForeignKey


MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "alembic", "versions",
    "d1e2f3a4b5c6_convert_prompt_tables_to_uuid.py",
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("m_convert_prompt", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_broken_schema(engine):
    """复刻 93a1c4f6255f + b3c4d5e6f7a8 在 SQLite 上的形态（BigInteger 主键/外键）。"""
    meta = MetaData()
    Table(
        "tenants", meta,
        Column("id", String(36), primary_key=True),
        Column("name", String(255), nullable=False),
    )
    Table(
        "users", meta,
        Column("id", String(36), primary_key=True),
        Column("tenant_id", String(36), nullable=False),
    )
    Table(
        "prompts", meta,
        Column("id", BigInteger(), autoincrement=True, nullable=False),
        Column("tenant_id", BigInteger(), nullable=False),
        Column("name", String(255), nullable=False),
        Column("description", Text(), nullable=True),
        Column("category", String(100), nullable=True),
        Column("tags", JSON(), nullable=True),
        Column("status", String(20), nullable=False, default="draft"),
        Column("created_by", BigInteger(), nullable=True),
        Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    Table(
        "prompt_versions", meta,
        Column("id", BigInteger(), autoincrement=True, nullable=False),
        Column("prompt_id", BigInteger(), nullable=False),
        Column("version_number", sa.Integer(), nullable=False),
        Column("content", Text(), nullable=False),
        Column("variables", JSON(), nullable=True),
        Column("is_current", Boolean(), nullable=False),
        Column("created_by", BigInteger(), nullable=True),
        Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        Column("tenant_id", String(36), nullable=False),  # 已由 b3c4 改为 String(36)
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),
    )
    Table(
        "prompt_test_logs", meta,
        Column("id", BigInteger(), autoincrement=True, nullable=False),
        Column("prompt_id", BigInteger(), nullable=False),
        Column("version_id", BigInteger(), nullable=True),
        Column("tenant_id", BigInteger(), nullable=False),
        Column("model_id", BigInteger(), nullable=True),
        Column("status", String(20), nullable=False),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["prompt_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    meta.create_all(engine)


def _run_with_op_ctx(engine, fn):
    """在 alembic op 上下文下执行迁移函数（不依赖 alembic CLI / 完整迁移链）。"""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    conn = engine.connect()
    try:
        ctx = MigrationContext.configure(conn)
        ops = Operations(ctx)
        mod = _load_migration_module()
        # 重定向迁移模块内的全局 op 到我们构造的上下文
        orig_op = mod.op
        mod.op = ops
        try:
            fn(mod, conn)
        finally:
            mod.op = orig_op
        conn.commit()
    finally:
        conn.close()


def _col_types(engine, table):
    insp = inspect(engine)
    return {c["name"]: c["type"] for c in insp.get_columns(table)}


def test_convert_prompt_tables_to_uuid():
    engine = create_engine("sqlite:///:memory:")
    _build_broken_schema(engine)

    # 初始：prompts.id / prompt_versions.prompt_id 等应为 BigInteger
    before = _col_types(engine, "prompt_versions")
    assert isinstance(before["id"], sa.BigInteger) or "INT" in str(before["id"]).upper()
    # tenant_id 已为 String（b3c4 已加），转换时应为 no-op 不被破坏
    assert isinstance(before["tenant_id"], sa.String)

    # 执行迁移
    def _up(mod, conn):
        mod.upgrade()

    _run_with_op_ctx(engine, _up)

    after = _col_types(engine, "prompt_versions")
    # 关键列应变为 VARCHAR(36)
    for col in ("id", "prompt_id", "created_by"):
        assert isinstance(after[col], sa.String), f"{col} 未变为 String，实际 {after[col]}"
    # tenant_id 保持 String
    assert isinstance(after["tenant_id"], sa.String)

    prompts_after = _col_types(engine, "prompts")
    for col in ("id", "tenant_id", "created_by"):
        assert isinstance(prompts_after[col], sa.String), f"prompts.{col} 未变为 String，实际 {prompts_after[col]}"

    # 幂等：再次执行不应抛错
    _run_with_op_ctx(engine, _up)
    after2 = _col_types(engine, "prompt_versions")
    assert isinstance(after2["id"], sa.String)

    # 可回滚
    def _down(mod, conn):
        mod.downgrade()

    _run_with_op_ctx(engine, _down)
    after_down = _col_types(engine, "prompt_versions")
    assert not isinstance(after_down["id"], sa.String)
