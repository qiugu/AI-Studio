import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import NotFoundException
from app.models import KnowledgeBase, KnowledgeDocument, Role, Tenant, User
from app.models.knowledge_document import DocumentStatus
from app.services.knowledge import KnowledgeBaseService
from app.services.role import ensure_permission_catalog


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db: Session, user_id: str, email: str) -> User:
    tenant = db.query(Tenant).filter(Tenant.id == "tenant-knowledge").one_or_none()
    if tenant is None:
        tenant = Tenant(id="tenant-knowledge", name="Knowledge Tenant")
        db.add(tenant)
        db.flush()
    catalog = ensure_permission_catalog(db)
    role = Role(
        id=f"role-{user_id}",
        tenant_id=tenant.id,
        name="Knowledge reader",
        code=f"knowledge-reader-{user_id}",
        status=True,
    )
    role.permissions.append(catalog[("knowledge", "read")])
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


def test_document_access_requires_a_live_parent_in_the_same_tenant(db):
    owner = _user(db, "knowledge-owner", "owner@knowledge.example")
    kb = KnowledgeBase(
        id="kb-live",
        tenant_id=owner.tenant_id,
        name="Live KB",
        created_by=owner.id,
    )
    document = KnowledgeDocument(
        id="doc-live",
        tenant_id=owner.tenant_id,
        kb_id=kb.id,
        file_name="readme.txt",
        file_type="txt",
        file_size=10,
        status=DocumentStatus.COMPLETED,
    )
    db.add_all([kb, document])
    db.commit()

    service = KnowledgeBaseService(db, owner.tenant_id, actor=owner)
    assert service.get_document(document.id).id == document.id

    kb.deleted_at = document.created_at
    db.commit()
    with pytest.raises(NotFoundException):
        service.get_document(document.id)


def test_document_with_cross_tenant_parent_is_not_visible(db):
    owner = _user(db, "knowledge-owner", "owner@knowledge.example")
    other_tenant = Tenant(id="tenant-other", name="Other Tenant")
    other_kb = KnowledgeBase(
        id="kb-other",
        tenant_id=other_tenant.id,
        name="Other KB",
    )
    malformed_document = KnowledgeDocument(
        id="doc-cross-parent",
        tenant_id=owner.tenant_id,
        kb_id=other_kb.id,
        file_name="cross.txt",
        file_type="txt",
        file_size=10,
        status=DocumentStatus.COMPLETED,
    )
    db.add_all([other_tenant, other_kb, malformed_document])
    db.commit()

    with pytest.raises(NotFoundException):
        KnowledgeBaseService(db, owner.tenant_id, actor=owner).get_document(
            malformed_document.id
        )
