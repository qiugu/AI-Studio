import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import Permission, Role, Tenant, User
from app.models.prompt import Prompt
from app.models.prompt_version import PromptVersion
from app.services.prompt import PromptService
from app.services.role import ensure_permission_catalog


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(
    db: Session,
    *,
    user_id: str,
    email: str,
    role_id: str,
    actions: set[str],
) -> User:
    tenant = db.query(Tenant).filter(Tenant.id == "tenant-prompt").one_or_none()
    if tenant is None:
        tenant = Tenant(id="tenant-prompt", name="Prompt Tenant")
        db.add(tenant)
        db.flush()

    catalog = ensure_permission_catalog(db)
    role = Role(
        id=role_id,
        tenant_id=tenant.id,
        name=role_id,
        code=role_id,
        status=True,
    )
    for action in actions:
        role.permissions.append(catalog[("prompt", action)])
    user = User(
        id=user_id,
        tenant_id=tenant.id,
        email=email,
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    user.roles.append(role)
    db.add(user)
    db.flush()
    return user


def _prompt(db: Session, *, created_by: str, status: str = "draft") -> Prompt:
    prompt = Prompt(
        id="prompt-1",
        tenant_id="tenant-prompt",
        name="Support prompt",
        status=status,
        created_by=created_by,
    )
    db.add(prompt)
    db.flush()
    version = PromptVersion(
        id="prompt-version-1",
        prompt_id=prompt.id,
        tenant_id=prompt.tenant_id,
        version_number=1,
        content="hello",
        variables=[],
        is_current=True,
        created_by=created_by,
    )
    db.add(version)
    db.commit()
    return prompt


def test_prompt_draft_requires_owner_or_resource_grant(db):
    owner = _user(
        db,
        user_id="prompt-owner",
        email="owner@prompt.example",
        role_id="prompt-owner-role",
        actions={"read", "update", "publish"},
    )
    reader = _user(
        db,
        user_id="prompt-reader",
        email="reader@prompt.example",
        role_id="prompt-reader-role",
        actions={"read"},
    )
    prompt = _prompt(db, created_by=owner.id)

    owner_service = PromptService(db, owner.tenant_id, actor=owner)
    reader_service = PromptService(db, reader.tenant_id, actor=reader)

    assert owner_service.get(prompt.id).id == prompt.id
    with pytest.raises(ForbiddenException):
        reader_service.get(prompt.id)

    prompt.status = "published"
    db.commit()
    assert reader_service.get(prompt.id).id == prompt.id


def test_prompt_version_lookup_keeps_prompt_tenant_boundary(db):
    owner = _user(
        db,
        user_id="prompt-owner",
        email="owner@prompt.example",
        role_id="prompt-owner-role",
        actions={"read", "update"},
    )
    prompt = _prompt(db, created_by=owner.id)
    other_tenant = Tenant(id="tenant-other", name="Other Tenant")
    other_prompt = Prompt(
        id="prompt-other",
        tenant_id=other_tenant.id,
        name="Other prompt",
        status="published",
        created_by="other-user",
    )
    db.add_all([other_tenant, other_prompt])
    db.commit()

    service = PromptService(db, owner.tenant_id, actor=owner)
    with pytest.raises(NotFoundException):
        service.list_versions(other_prompt.id)

    assert service.list_versions(prompt.id)
