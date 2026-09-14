"""复现并回归 MySQL 1062（Duplicate entry for uq_prompt_version）。

故障链（真实生产故障）：
1. S3 全局租户过滤器（tenant_scope.with_loader_criteria）给所有含 tenant_id 的
   ORM 实体 SELECT 注入 ``tenant_id == 当前租户``；
2. ``create_version`` 用 ORM 查询"最大版本号"，存量版本行 tenant_id 与当前租户
   不一致（迁移回填未覆盖的旧数据）→ 查询"看不到"已有 v1 → next_num 误算为 1；
3. INSERT ('1', 1) 撞上已有 ('1',1) 唯一键 → MySQL 1062。

修复：版本号计算改走 Core 级查询（表对象），不受租户视图过滤影响
（prompt 归属已由 _get_or_404 校验）。本测试注册真实的全局过滤器，
构造"历史版本行挂在其他租户"的场景，断言 create_version 正确生成 v2。
"""
import os
import sys
import types
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _stub_heavy_utils():
    for modname, need_decrypt in [("app.utils.llm", False), ("app.utils.encryption", True)]:
        fake = types.ModuleType(modname)
        if need_decrypt:
            fake.decrypt = lambda x: x
        sys.modules.setdefault(modname, fake)


def _import_targets():
    _stub_heavy_utils()
    from app.services.prompt import PromptService
    from app.schemas.prompt import PromptVersionCreate
    from app.models.prompt import Prompt
    from app.models.prompt_version import PromptVersion
    from app.models.tenant import Tenant
    from app.core.database import Base
    from app.core.tenant_scope import register_tenant_filter, set_tenant_scope, reset_tenant_scope

    return (
        PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant, Base,
        register_tenant_filter, set_tenant_scope, reset_tenant_scope,
    )


@pytest.fixture
def env():
    db_path = "/tmp/test_prompt_scope_1062.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    (
        PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant, Base,
        register_tenant_filter, set_tenant_scope, reset_tenant_scope,
    ) = _import_targets()

    # 注册真实的全局租户过滤器（幂等）
    register_tenant_filter()

    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Prompt.__table__, PromptVersion.__table__],
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    # 请求作用域：当前租户 t-current，非平台管理员
    token = set_tenant_scope("t-current", is_platform_admin=False)

    yield session, PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant

    reset_tenant_scope(token)
    session.close()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_create_version_ignores_tenant_scope_when_counting(env):
    """历史版本行 tenant_id 不匹配当前租户时，next_num 仍必须基于真实最大版本号。"""
    session, PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant = env

    user_id = str(uuid.uuid4())
    prompt_id = str(uuid.uuid4())

    session.add(Tenant(id="t-current", name="current"))
    session.flush()
    session.add(Prompt(
        id=prompt_id,
        tenant_id="t-current",
        name="p",
        status="draft",
        created_by=user_id,
    ))
    session.flush()
    # 关键：v1 行挂在 legacy 租户名下（模拟迁移回填未覆盖的存量数据）。
    # 若 next_num 计算被租户过滤，此行将"不可见"→ next_num 误算为 1 → 撞唯一键。
    session.add(PromptVersion(
        id=str(uuid.uuid4()),
        prompt_id=prompt_id,
        tenant_id="t-legacy",
        version_number=1,
        content="v1",
        is_current=True,
        created_by=user_id,
    ))
    session.commit()

    svc = PromptService(session, "t-current")
    new_version = svc.create_version(
        prompt_id, PromptVersionCreate(content="v2"), user_id=user_id
    )
    session.commit()

    assert new_version.version_number == 2, "next_num 被租户过滤污染，误算为 1 会撞 uq_prompt_version"
    assert new_version.tenant_id == "t-current"
