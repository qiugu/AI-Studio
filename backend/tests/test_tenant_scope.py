"""S3 全局租户过滤器的隔离单测。

仅依赖 SQLAlchemy（不依赖 MySQL / Redis / Qdrant），用 SQLite 内存库做**行为断言**：
真实插入两个租户的数据，真实执行查询，验证 ``app.core.tenant_scope`` 的查询级兜底机制。

覆盖场景：
- 租户用户只能查到本租户数据；
- 平台管理员跳过过滤（需跨租户视角）；
- 无上下文（CLI / Celery / 迁移）时不做注入；
- 主实体无 ``tenant_id`` 列的表不被注入；
- 跨租户按主键直取被兜底拦截（S3 评审点名的核心风险场景）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Boolean, Column, Integer, String, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import tenant_scope

Base = declarative_base()


class TenantDoc(Base):
    __tablename__ = "tenant_docs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(36))
    name = Column(String(50))


class GlobalRow(Base):
    __tablename__ = "global_rows"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))


class PublicDoc(Base):
    """tenant_id 为 NULL 即平台公共资源（对应 AIModel 的语义）。"""

    __tablename__ = "public_docs"
    __tenant_scope_clause__ = staticmethod(tenant_scope.tenant_or_public_clause)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(36), nullable=True)
    name = Column(String(50))


class FlaggedDoc(Base):
    """仅 tenant_id IS NULL 且 is_public=True 才是公共（对应 Plugin 的语义）。"""

    __tablename__ = "flagged_docs"
    __tenant_scope_clause__ = staticmethod(
        tenant_scope.tenant_or_flagged_public_clause
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(36), nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    name = Column(String(50))


class PublicDocAlt(Base):
    """与 ``PublicDoc`` 共用同一判据函数，用于验证判据不跨模型串味。"""

    __tablename__ = "public_docs_alt"
    __tenant_scope_clause__ = staticmethod(tenant_scope.tenant_or_public_clause)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(36), nullable=True)
    name = Column(String(50))


def _seeded_session():
    """构建共享同一内存库的会话，并预置两个租户的数据。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            TenantDoc(id=1, tenant_id="tenant-A", name="a1"),
            TenantDoc(id=2, tenant_id="tenant-B", name="b1"),
            GlobalRow(id=1, name="g1"),
            # tenant-A 自有 + tenant-B 自有 + 平台公共（tenant_id=NULL）
            PublicDoc(id=1, tenant_id="tenant-A", name="pa"),
            PublicDoc(id=2, tenant_id="tenant-B", name="pb"),
            PublicDoc(id=3, tenant_id=None, name="platform-preset"),
            # 本租户 + 公开的 NULL 行 + 未公开的 NULL 行
            FlaggedDoc(id=1, tenant_id="tenant-A", is_public=False, name="fa"),
            FlaggedDoc(id=2, tenant_id=None, is_public=True, name="public-plugin"),
            FlaggedDoc(id=3, tenant_id=None, is_public=False, name="hidden-plugin"),
            # 与 PublicDoc 共用判据，用于验证判据不跨模型串味
            PublicDocAlt(id=1, tenant_id="tenant-B", name="alt-b"),
            PublicDocAlt(id=2, tenant_id=None, name="alt-public"),
        ]
    )
    session.commit()
    return session


def setup_module(module):
    tenant_scope.register_tenant_filter()


def test_tenant_user_sees_only_own_rows():
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.query(TenantDoc).all()
        assert {r.tenant_id for r in rows} == {"tenant-A"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_platform_admin_bypasses_filter():
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=True)
    try:
        rows = s.query(TenantDoc).all()
        assert {r.tenant_id for r in rows} == {"tenant-A", "tenant-B"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_no_context_no_filter():
    s = _seeded_session()
    # 未设置上下文变量（模拟 Celery / 迁移等非请求上下文）
    rows = s.query(TenantDoc).all()
    assert {r.tenant_id for r in rows} == {"tenant-A", "tenant-B"}


def test_table_without_tenant_id_not_filtered():
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        assert len(s.query(GlobalRow).all()) == 1
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_cross_tenant_get_by_id_is_blocked():
    """跨租户按主键直取应被兜底过滤拦截 —— S3 评审的核心风险场景。"""
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        assert s.query(TenantDoc).filter(TenantDoc.id == 2).first() is None
        assert s.query(TenantDoc).filter(TenantDoc.id == 1).first() is not None
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_register_is_idempotent():
    """重复注册不应叠加监听器（否则会生成重复的 AND 条件）。"""
    tenant_scope.register_tenant_filter()
    tenant_scope.register_tenant_filter()
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.query(TenantDoc).all()
        assert {r.tenant_id for r in rows} == {"tenant-A"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_select_style_also_filtered():
    """2.0 风格 ``select()`` 也应被兜底过滤（钩子位于 Session 层，与查询风格无关）。"""
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.execute(select(TenantDoc)).scalars().all()
        assert {r.tenant_id for r in rows} == {"tenant-A"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_admin_sees_all_via_select():
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=True)
    try:
        rows = s.execute(select(TenantDoc)).scalars().all()
        assert {r.tenant_id for r in rows} == {"tenant-A", "tenant-B"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_null_tenant_row_is_visible_as_public():
    """``tenant_id IS NULL`` 声明为公共资源时，租户仍可见（对应平台预置 AIModel）。"""
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.query(PublicDoc).all()
        assert {r.name for r in rows} == {"pa", "platform-preset"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_null_tenant_row_hidden_when_not_public():
    """NULL 租户行必须同时 is_public=True 才可见，避免未公开行泄漏。"""
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.query(FlaggedDoc).all()
        assert {r.name for r in rows} == {"fa", "public-plugin"}
        assert "hidden-plugin" not in {r.name for r in rows}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_strict_model_does_not_leak_null_rows():
    """未声明公共语义的模型，NULL 租户行不应可见（默认严格策略）。"""
    s = _seeded_session()
    s.add(TenantDoc(id=9, tenant_id=None, name="orphan"))
    s.commit()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        rows = s.query(TenantDoc).all()
        assert {r.name for r in rows} == {"a1"}
    finally:
        tenant_scope.reset_tenant_scope(token)


def test_clause_not_shared_across_models_with_same_function():
    """共用同一判据函数的两个模型不得互相串味（曾因 lambda 按 code object 缓存而出错）。"""
    s = _seeded_session()
    token = tenant_scope.set_tenant_scope("tenant-A", is_platform_admin=False)
    try:
        # 先查 PublicDoc，再查共用判据的 PublicDocAlt，最后回到 PublicDoc 交叉验证
        assert {r.name for r in s.query(PublicDoc).all()} == {"pa", "platform-preset"}
        assert {r.name for r in s.query(PublicDocAlt).all()} == {"alt-public"}
        assert {r.name for r in s.query(PublicDoc).all()} == {"pa", "platform-preset"}
    finally:
        tenant_scope.reset_tenant_scope(token)
