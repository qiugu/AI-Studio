"""集成验证：在“修正后的 String(36) schema”上真实跑 PromptService.create_version。

证明口径：之前 500 的根因是 prompt 表以 BigInteger 存主键/外键，而模型用 String(36)
UUID，插入 UUID 字符串到 BigInteger 列触发 MySQL 类型错误。本测试用 SQLite 构造
“已修正”的 schema（id/外键均为 String(36)），直接调用真实的 PromptService.create_version
（非 mock），断言能成功生成 v2 版本。

说明：SQLite 为动态类型，不会像 MySQL 那样因类型不匹配报错，因此本测试用于证明
“服务代码本身在正确 schema 下工作”；schema 修正动作由
test_prompt_tables_uuid_migration.py 覆盖。两者结合即可确认 500 根因消除。

为加速，预先桩掉 app.utils.llm / app.utils.encryption（仅 test_run 使用，与本次修复无关）。
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


def _import_service():
    _stub_heavy_utils()
    from app.services.prompt import PromptService
    from app.schemas.prompt import PromptVersionCreate
    from app.models.prompt import Prompt
    from app.models.prompt_version import PromptVersion
    from app.models.tenant import Tenant
    from app.core.database import Base

    return PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant, Base


@pytest.fixture
def engine_and_session():
    db_path = "/tmp/test_prompt_svc_integration.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    (
        PromptService,
        PromptVersionCreate,
        Prompt,
        PromptVersion,
        Tenant,
        Base,
    ) = _import_service()

    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Prompt.__table__, PromptVersion.__table__],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session, PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant
    session.close()
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_create_version_on_fixed_schema(engine_and_session):
    session, PromptService, PromptVersionCreate, Prompt, PromptVersion, Tenant = engine_and_session

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    prompt_id = str(uuid.uuid4())

    session.add(Tenant(id=tenant_id, name="t"))
    session.flush()

    prompt = Prompt(
        id=prompt_id,
        tenant_id=tenant_id,
        name="hello",
        status="draft",
        created_by=user_id,
    )
    session.add(prompt)
    session.flush()

    v1 = PromptVersion(
        id=str(uuid.uuid4()),
        prompt_id=prompt_id,
        tenant_id=tenant_id,
        version_number=1,
        content="v1 content",
        is_current=True,
        created_by=user_id,
    )
    session.add(v1)
    session.commit()

    # 真实调用业务代码（非 mock）：在正确 schema 下应能成功生成 v2
    svc = PromptService(session, tenant_id)
    new_version = svc.create_version(
        prompt_id, PromptVersionCreate(content="v2 content"), user_id=user_id
    )
    session.commit()
    session.refresh(new_version)

    assert new_version.version_number == 2
    assert new_version.content == "v2 content"
    assert new_version.is_current is False
    assert new_version.tenant_id == tenant_id

    # 数据库中应有两条版本
    count = session.query(PromptVersion).filter_by(prompt_id=prompt_id).count()
    assert count == 2
