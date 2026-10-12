"""租户隔离的查询级兜底机制（S3）。

问题背景：代码评审发现 Service 层存在大量绕过 ``BaseRepository`` 的裸 ``db.query(...)``
（约 49 处），且租户过滤是否生效完全依赖编写者当次是否记得加 ``.filter(tenant_id=...)``
（见 ``docs/review/01-backend.md`` S3，典型反例 ``services/workflow_engine.py:255`` 与其紧邻
``:259`` 标准不一致）。

本模块提供一个**机制化兜底**：在 ORM 语句执行前，自动为涉及租户实体（含 ``tenant_id``
列的表）的查询注入 ``tenant_id == 当前请求租户`` 的过滤条件，使租户隔离不再依赖逐处手写。

实现要点（与 SQLAlchemy 2.0 兼容）：
- 使用 ``Session.do_orm_execute`` 事件钩子 + ``with_loader_criteria``，这是 SQLAlchemy
  官方推荐的「全局 WHERE 条件」实现方式（见官方文档 *ORM Events → Adding global WHERE / ON
  criteria*）。
- **注意**：SQLAlchemy 1.x 的 ``Query.before_compile`` 回调虽然仍会触发，但**其返回值在 2.0
  中被忽略**（``Session.query()`` 走 2.0 编译路径），据此实现会得到「看似生效、实则空转」的
  假保证 —— 本模块早期版本即因此缺陷失效，由 ``tests/test_tenant_scope.py`` 的行为断言发现。
- 同时覆盖 1.x 风格 ``db.query(Model)`` 与 2.0 风格 ``select(Model)``。
- 模型可通过类属性 ``__tenant_scope_clause__``（``staticmethod(cls, tenant_id) -> 表达式``）
  声明自定义可见性条件；未声明时使用严格的 ``tenant_id`` 等值过滤。
- 平台管理员（``is_platform_admin=True``）需要跨租户视角，跳过过滤。
- 上下文缺失（CLI / Celery / 迁移等非请求上下文）时不做任何注入，避免误伤。
- 已在查询中手写 ``tenant_id`` 过滤的，再多一条同值条件，语义无变化（幂等）。

已知边界：
- 仅过滤 ORM ``SELECT``（含 ``query()`` 与 ``select()``）。Core 层 ``text()`` 原生 SQL、
  ORM ``UPDATE`` / ``DELETE`` 不在此钩子覆盖范围内，仍需业务层自行保证。
- ``relationship`` 懒加载不单独注入（``with_loader_criteria`` 会从父查询自动传播），
  因此关系加载同样受父查询的租户条件约束。
- 语句中的**别名实体**（``aliased(Model)``）不会被注入（其 ``entity`` 非映射类，直接跳过），
  即此时不构成兜底；如需覆盖应改为在查询处显式过滤。
- 判据以 **SQL 表达式**而非 lambda 传入：``with_loader_criteria`` 对 lambda 按 code object
  缓存判据，多模型复用同一 lambda 源码会互相污染（本模块开发期即因此出现未公开行泄漏），
  表达式形式无此风险。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from sqlalchemy import and_, event, or_
from sqlalchemy.orm import Session, with_loader_criteria

# 每个请求隔离的租户上下文。FastAPI 每个请求在独立 Task 中执行，ContextVar 随 Task
# 上下文隔离，不会跨请求泄漏；非请求上下文（迁移/Celery）中该值为 None。
TenantScope = dict[str, Any]
tenant_scope_ctx: ContextVar[Optional[TenantScope]] = ContextVar(
    "tenant_scope_ctx", default=None
)

_REGISTERED = False


def strict_tenant_clause(cls: Any, tenant_id: str) -> Any:
    """默认策略：严格等值，仅本租户可见。"""
    return cls.tenant_id == tenant_id


def tenant_or_public_clause(cls: Any, tenant_id: str) -> Any:
    """本租户自有 + 平台公共行（``tenant_id IS NULL`` 即公共）。

    适用于 ``AIModel``：tenant_id 为 NULL 表示平台预置公共模型。
    """
    return or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None))


def tenant_or_flagged_public_clause(cls: Any, tenant_id: str) -> Any:
    """本租户自有 + 显式标记为公共的行（``tenant_id IS NULL AND is_public = true``）。

    适用于 ``Plugin``：仅 ``is_public=True`` 的 NULL 租户行才是平台公共插件，
    避免把 ``tenant_id IS NULL`` 但未公开的行误放行。
    """
    return or_(
        cls.tenant_id == tenant_id,
        and_(cls.tenant_id.is_(None), cls.is_public.is_(True)),
    )


def public_or_tenant_filter(
    model: Any, tenant_id: str, include_public: bool = False
) -> Any:
    """构造『本租户私有 + （可选）平台公共』的租户可见性条件。

    这是 service 层查询的公共行可见性**单一事实来源**，与全局租户过滤器
    （``do_orm_execute`` + 模型声明的 ``__tenant_scope_clause__``）保持完全一致：

    - ``include_public=False``：仅本租户私有行（``tenant_id == tenant_id``）。
    - ``include_public=True``：本租户私有行 + 平台公共行。公共行的判定规则
      直接复用模型声明的 ``__tenant_scope_clause__``（如 ``tenant_or_public_clause``
      或 ``tenant_or_flagged_public_clause``），未声明时回退为
      ``tenant_or_public_clause``（``tenant_id IS NULL`` 即公共）。

    用于替换 service 层散落的 ``or_(model.tenant_id == X, model.tenant_id.is_(None))``
    副本，消除语义分歧并确保与全局过滤器一致，避免越权或误放行。
    """
    if include_public:
        clause_fn = getattr(model, "__tenant_scope_clause__", None)
        if clause_fn is not None:
            return clause_fn(model, tenant_id)
        return tenant_or_public_clause(model, tenant_id)
    return strict_tenant_clause(model, tenant_id)


def set_tenant_scope(tenant_id: str, is_platform_admin: bool) -> Any:
    """设置当前请求的租户作用域，返回 reset 用的 token。"""
    return tenant_scope_ctx.set(
        {"tenant_id": tenant_id, "is_platform_admin": is_platform_admin}
    )


def reset_tenant_scope(token: Any) -> None:
    tenant_scope_ctx.reset(token)


def _tenant_scoped_models(statement: Any) -> list:
    """解析语句涉及的、且含 ``tenant_id`` 列的映射类。

    对实体查询与聚合查询均可从 ``column_descriptions`` 取到 ``entity``。
    """
    descriptions = getattr(statement, "column_descriptions", None)
    if not descriptions:
        return []

    models = []
    for desc in descriptions:
        entity = desc.get("entity")
        if not isinstance(entity, type) or not hasattr(entity, "__table__"):
            continue
        column_names = getattr(entity.__table__, "columns", None)
        if column_names is not None and "tenant_id" in column_names:
            models.append(entity)
    return models


def _tenant_clause(model: Any, tenant_id: str) -> Any:
    """构造指定模型的租户可见性条件（返回 SQL 表达式）。"""
    clause_fn = getattr(model, "__tenant_scope_clause__", None)
    if clause_fn is not None:
        return clause_fn(model, tenant_id)
    return model.tenant_id == tenant_id


def _apply_tenant_filter(state: Any) -> None:
    """``do_orm_execute`` 回调：为涉及租户实体的 SELECT 注入租户过滤。"""
    ctx = tenant_scope_ctx.get()
    if ctx is None or ctx.get("is_platform_admin"):
        return

    tenant_id = ctx.get("tenant_id")
    if not tenant_id:
        return

    # 仅处理顶层 SELECT；列加载/关系加载由 with_loader_criteria 自动传播，避免重复注入。
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return

    statement = state.statement
    for model in _tenant_scoped_models(statement):
        # 传入**SQL 表达式**（而非 lambda）：with_loader_criteria 对 lambda 按 code object
        # 缓存判据，多个模型复用同一 lambda 源码会互相污染（曾导致未公开行泄漏）。
        statement = statement.options(
            with_loader_criteria(model, _tenant_clause(model, tenant_id))
        )
    state.statement = statement


def register_tenant_filter() -> None:
    """注册全局查询过滤器（在应用/会话初始化时调用一次）。

    幂等：重复调用不会叠加监听器。
    """
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "do_orm_execute", _apply_tenant_filter)
    _REGISTERED = True
