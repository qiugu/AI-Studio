from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Permission, Role, Tenant, User


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.get_calls = 0
        self.setex_calls = 0
        self.lock_values = {}

    async def get(self, key):
        self.get_calls += 1
        return self.values.get(key)

    async def setex(self, key, _ttl, value):
        self.setex_calls += 1
        self.values[key] = value
        return True

    async def set(self, key, value, nx=False, ex=None):
        del ex
        if nx and key in self.lock_values:
            return False
        self.lock_values[key] = value
        return True

    async def eval(self, _script, _numkeys, key, token):
        if self.lock_values.get(key) == token:
            del self.lock_values[key]
            return 1
        return 0

    async def delete(self, key):
        self.values.pop(key, None)


def _authorization_db_and_actor():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(id="redis-tenant", name="Redis Tenant")
    permission = Permission(resource="agent", action="chat", description="Chat")
    role = Role(
        tenant_id=tenant.id,
        name="Operator",
        code="redis-operator",
        status=True,
    )
    role.permissions.append(permission)
    actor = User(
        id="redis-user",
        tenant_id=tenant.id,
        email="redis@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    actor.roles.append(role)
    db.add_all([tenant, actor])
    db.commit()
    db.refresh(actor)
    return db, actor


def _hybrid_client():
    client = MagicMock()
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                sparse_vectors={"text": object()},
            )
        )
    )
    return client


def test_authorization_cache_round_trips_through_async_redis(monkeypatch):
    from app.core.authorization import AuthorizationService

    redis = FakeRedis()
    async def get_redis():
        return redis

    monkeypatch.setattr("app.core.authorization.get_redis", get_redis)
    db, actor = _authorization_db_and_actor()
    try:
        service = AuthorizationService(db)
        import asyncio

        first = asyncio.run(
            service.check_permission_async(actor, actor.tenant_id, "agent", "chat")
        )
        second = asyncio.run(
            service.check_permission_async(actor, actor.tenant_id, "agent", "chat")
        )

        assert first == second
        assert redis.get_calls == 2
        assert redis.setex_calls == 1
    finally:
        db.close()


def test_vector_layout_cache_is_shared_by_async_redis(monkeypatch):
    from app.core import vector_db

    redis = FakeRedis()
    async def get_redis():
        return redis

    monkeypatch.setattr(vector_db, "get_redis", get_redis)
    client = _hybrid_client()

    import asyncio

    assert asyncio.run(vector_db.collection_layout_async("kb-x", client=client)) == "hybrid"
    assert asyncio.run(vector_db.collection_layout_async("kb-x", client=client)) == "hybrid"
    assert client.get_collection.call_count == 1


def test_failed_vector_probe_is_not_cached(monkeypatch):
    from app.core import vector_db

    redis = FakeRedis()
    async def get_redis():
        return redis

    monkeypatch.setattr(vector_db, "get_redis", get_redis)
    client = MagicMock()
    client.get_collection.side_effect = RuntimeError("transient")

    import asyncio

    assert asyncio.run(vector_db.collection_layout_async("kb-x", client=client)) == "missing"
    assert asyncio.run(vector_db.collection_layout_async("kb-x", client=client)) == "missing"
    assert client.get_collection.call_count == 2
