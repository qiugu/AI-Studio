"""插件列表必须回显已配置的能力。"""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.plugin import Plugin, PluginEndpoint
from app.services.plugin import PluginService


def test_plugin_list_attaches_configured_endpoints_to_each_plugin():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        plugin_id = str(uuid.uuid4())
        plugin = Plugin(
            id=plugin_id,
            tenant_id="tenant-1",
            name="企业搜索",
            source_type="http",
            status="active",
        )
        db.add(plugin)
        db.add(
            PluginEndpoint(
                id=str(uuid.uuid4()),
                plugin_id=plugin_id,
                endpoint="/v1/search",
                method="POST",
                description="搜索企业资料",
            )
        )
        db.commit()

        items, _ = PluginService(db, "tenant-1").list()

        assert len(items) == 1
        assert [endpoint.endpoint for endpoint in items[0]._endpoints] == ["/v1/search"]
    finally:
        db.close()
        engine.dispose()
