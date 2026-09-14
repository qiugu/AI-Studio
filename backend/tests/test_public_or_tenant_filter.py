"""
3a 共享租户/公共过滤 helper 测试（纯函数，无需数据库）。

验证 ``public_or_tenant_filter`` 是 service 层公共行可见性的单一事实来源：
- ``include_public=True`` 时复用模型声明的 ``__tenant_scope_clause__``，与全局过滤器一致；
- 对 Plugin 正确采用更严格的 ``tenant_or_flagged_public_clause``（消除与 model 层的语义分歧）；
- ``include_public=False`` 时退化为严格等值（仅本租户私有行）。
"""
import os

from sqlalchemy.dialects import sqlite

from app.core.tenant_scope import (
    public_or_tenant_filter,
    strict_tenant_clause,
    tenant_or_flagged_public_clause,
    tenant_or_public_clause,
)
from app.models.ai_model import AIModel
from app.models.plugin import Plugin


def _sql(clause) -> str:
    return str(clause.compile(dialect=sqlite.dialect()))


def test_aimodel_public_reuses_tenant_or_public_clause():
    got = _sql(public_or_tenant_filter(AIModel, "t1", include_public=True))
    expected = _sql(tenant_or_public_clause(AIModel, "t1"))
    assert got == expected


def test_aimodel_private_is_strict_equality():
    got = _sql(public_or_tenant_filter(AIModel, "t1", include_public=False))
    expected = _sql(strict_tenant_clause(AIModel, "t1"))
    assert got == expected


def test_plugin_public_uses_flagged_clause_not_naive_public():
    # 关键：Plugin 的公共行必须是 "tenant_id IS NULL AND is_public"，
    # 而非宽松的 "tenant_id IS NULL"，否则会与 Plugin.__tenant_scope_clause__ 分歧。
    got = _sql(public_or_tenant_filter(Plugin, "t1", include_public=True))
    flagged = _sql(tenant_or_flagged_public_clause(Plugin, "t1"))
    naive = _sql(tenant_or_public_clause(Plugin, "t1"))
    assert got == flagged
    assert got != naive  # 必须比宽松写法更严格


def test_plugin_private_is_strict_equality():
    got = _sql(public_or_tenant_filter(Plugin, "t1", include_public=False))
    expected = _sql(strict_tenant_clause(Plugin, "t1"))
    assert got == expected


def test_no_raise_http_exception_in_api():
    """C1 验收：api/ 下不得残留裸 ``raise HTTPException``。"""
    api_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "app", "api")
    )
    hits = []
    for root, _dirs, files in os.walk(api_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "raise HTTPException" in line:
                        hits.append(f"{path}:{lineno}")
    assert hits == [], f"api/ 仍残留裸 raise HTTPException: {hits}"
