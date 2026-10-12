"""插件接入方式（``source_type``）单测 + 能力形态 ``plugin_type`` 移除守卫。

仅依赖 Pydantic 与标准库，不触达数据库/外部服务：

- 接入方式恰为 http/mcp/skill；
- 新建/更新 Schema 接受合法值、拒绝非法值、默认值正确、局部更新不注入默认值；
- 展示元数据对每个取值都有条目，避免前后端与文档口径漂移；
- **移除守卫**：``plugin_type`` 已随 M2.0 整体移除，旧模块/字段/ORM 列均不应残留。
"""

import importlib
import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_source_types import (
    DEFAULT_SOURCE_TYPE,
    PLUGIN_SOURCE_TYPE_META,
    source_type_values,
)
from app.schemas.plugin import PluginCreate, PluginUpdate


# ── 接入方式取值 ────────────────────────────────────────────────────────────


def test_source_type_values_are_expected():
    assert source_type_values() == ["http", "mcp", "skill"]


# ── Schema 校验 ─────────────────────────────────────────────────────────────


def test_create_accepts_all_valid_combinations():
    for st in source_type_values():
        data = PluginCreate(name="p", source_type=st)
        # use_enum_values=True：落库前应已归一为纯字符串
        assert isinstance(data.source_type, str)
        assert data.source_type == st


def test_create_defaults():
    data = PluginCreate(name="p")
    assert data.source_type == DEFAULT_SOURCE_TYPE == "http"


def test_create_rejects_invalid_values():
    with pytest.raises(ValidationError):
        PluginCreate(name="p", source_type="not-a-source")


def test_update_accepts_valid_and_rejects_invalid():
    assert PluginUpdate(source_type="mcp").source_type == "mcp"
    with pytest.raises(ValidationError):
        PluginUpdate(source_type="grpc")


def test_update_partial_does_not_inject_defaults():
    """更新语义为局部更新：未提供的字段不应被默认值填充。"""
    dumped = PluginUpdate(name="renamed").model_dump(exclude_none=True)
    assert "source_type" not in dumped


# ── 元数据一致性 ────────────────────────────────────────────────────────────


def test_source_meta_covers_all_values():
    assert set(PLUGIN_SOURCE_TYPE_META) == set(source_type_values())


def test_meta_entries_are_complete():
    for key, item in PLUGIN_SOURCE_TYPE_META.items():
        for field in ("label", "description", "use_cases"):
            assert item.get(field), f"{key} 缺少 {field}"


# ── 移除守卫（M2.0） ────────────────────────────────────────────────────────


def test_plugin_type_module_is_removed():
    """旧模块 ``app.core.plugin_types`` 应已随 plugin_type 一并移除。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.plugin_types")


def test_create_ignores_legacy_plugin_type_kwarg():
    """旧字段不应再被接受。Pydantic 默认忽略多余入参，故断言「不落入库对象」。"""
    data = PluginCreate(name="p", plugin_type="tool")  # type: ignore[call-arg]
    assert not hasattr(data, "plugin_type")
    assert "plugin_type" not in data.model_dump()


def test_update_ignores_legacy_plugin_type_kwarg():
    data = PluginUpdate(plugin_type="connector")  # type: ignore[call-arg]
    assert not hasattr(data, "plugin_type")
    assert "plugin_type" not in data.model_dump(exclude_none=True)


def test_orm_model_has_no_plugin_type_column():
    from app.models.plugin import Plugin

    assert "plugin_type" not in Plugin.__table__.columns
    assert "source_type" in Plugin.__table__.columns


def test_plugin_out_has_no_plugin_type_field():
    from app.schemas.plugin import PluginOut

    assert "plugin_type" not in PluginOut.model_fields
    assert "source_type" in PluginOut.model_fields
