"""Prompt 版本写入必须携带 tenant_id 的回归测试

背景：迁移 ``b3c4d5e6f7a8_add_tenant_id_to_prompt_versions`` 将
``prompt_versions.tenant_id`` 设为 NOT NULL（纵深防御 S4）。但 ``PromptService``
在构造 ``PromptVersion`` 时未赋值，导致任何新建/新版本写入都因 ``tenant_id`` 为 NULL
触发 IntegrityError → HTTP 500。

本测试用 MagicMock 模拟 Session，断言版本对象在落库前已正确设置 ``tenant_id``，
防止该回归再次出现。
"""

from unittest.mock import MagicMock

from app.schemas.prompt import PromptCreate, PromptVersionCreate
from app.services.prompt import PromptService

TENANT = "tenant-prompt-regression"


def _make_service() -> tuple[PromptService, MagicMock]:
    db = MagicMock()
    # _get_or_404 的 Prompt 查询链：query().filter().filter().first()
    fake_prompt = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = fake_prompt
    # _next_version_number 的 Core 级查询：execute(...).scalar() → 当前最大版本号 1 → next=2
    db.execute.return_value.scalar.return_value = 1
    return PromptService(db=db, tenant_id=TENANT), db


def test_create_version_sets_tenant_id():
    """新建版本（v2）必须带上当前租户，否则 DB NOT NULL 约束会 500。"""
    svc, db = _make_service()
    version = svc.create_version(
        "prompt-1",
        PromptVersionCreate(content="你好 {{name}}"),
    )
    assert version.tenant_id == TENANT
    assert version.version_number == 2
    # 落库对象与返回对象一致
    added = db.add.call_args.args[0]
    assert added.tenant_id == TENANT


def test_create_initial_version_sets_tenant_id():
    """创建 Prompt 时的初始版本（v1）同样必须带 tenant_id。"""
    svc, db = _make_service()
    prompt = svc.create(PromptCreate(name="欢迎语", content="你好"))
    assert prompt.current_version.tenant_id == TENANT
    # 第二个 add 调用即 PromptVersion（首个为 Prompt）
    version_added = db.add.call_args_list[-1].args[0]
    assert version_added.tenant_id == TENANT
    assert version_added.version_number == 1
