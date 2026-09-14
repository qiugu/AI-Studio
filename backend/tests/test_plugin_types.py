"""插件类型体系（双维度）单测。

仅依赖 Pydantic 与标准库，不触达数据库/外部服务，对「类型枚举 + 校验 + 元数据一致性」
做行为断言：

- 能力形态恰为 tool/connector/processor（provider 已移除）；
- 接入方式恰为 http/mcp/skill；
- 新建/更新 Schema 接受合法值、拒绝非法值、默认值正确、局部更新不注入默认值；
- 展示元数据对每个取值都有条目，避免前后端与文档口径漂移。
"""

import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_types import (
    DEFAULT_PLUGIN_TYPE,
    DEFAULT_SOURCE_TYPE,
    PLUGIN_SOURCE_TYPE_META,
    PLUGIN_TYPE_META,
    plugin_type_values,
    source_type_values,
)
from app.schemas.plugin import PluginCreate, PluginUpdate


# ── 枚举取值 ────────────────────────────────────────────────────────────────


def test_plugin_type_values_are_expected():
    assert plugin_type_values() == ["tool", "connector", "processor"]


def test_source_type_values_are_expected():
    assert source_type_values() == ["http", "mcp", "skill"]


def test_provider_is_removed():
    """provider 与 /api/ai-providers 语义重叠，不应再是合法能力形态。"""
    assert "provider" not in plugin_type_values()
    with pytest.raises(ValidationError):
        PluginCreate(name="x", plugin_type="provider")


# ── Schema 校验 ─────────────────────────────────────────────────────────────


def test_create_accepts_all_valid_combinations():
    for pt in plugin_type_values():
        for st in source_type_values():
            data = PluginCreate(name="p", plugin_type=pt, source_type=st)
            # use_enum_values=True：落库前应已归一为纯字符串
            assert isinstance(data.plugin_type, str)
            assert data.plugin_type == pt
            assert data.source_type == st


def test_create_defaults():
    data = PluginCreate(name="p")
    assert data.plugin_type == DEFAULT_PLUGIN_TYPE == "tool"
    assert data.source_type == DEFAULT_SOURCE_TYPE == "http"


def test_create_rejects_invalid_values():
    with pytest.raises(ValidationError):
        PluginCreate(name="p", plugin_type="not-a-type")
    with pytest.raises(ValidationError):
        PluginCreate(name="p", source_type="not-a-source")


def test_update_accepts_valid_and_rejects_invalid():
    assert PluginUpdate(plugin_type="connector").plugin_type == "connector"
    assert PluginUpdate(source_type="mcp").source_type == "mcp"
    with pytest.raises(ValidationError):
        PluginUpdate(plugin_type="provider")
    with pytest.raises(ValidationError):
        PluginUpdate(source_type="grpc")


def test_update_partial_does_not_inject_defaults():
    """更新语义为局部更新：未提供的字段不应被默认值填充。"""
    dumped = PluginUpdate(name="renamed").model_dump(exclude_none=True)
    assert "plugin_type" not in dumped
    assert "source_type" not in dumped


# ── 元数据一致性 ────────────────────────────────────────────────────────────


def test_type_meta_covers_all_values():
    assert set(PLUGIN_TYPE_META) == set(plugin_type_values())


def test_source_meta_covers_all_values():
    assert set(PLUGIN_SOURCE_TYPE_META) == set(source_type_values())


@pytest.mark.parametrize("meta", [PLUGIN_TYPE_META, PLUGIN_SOURCE_TYPE_META])
def test_meta_entries_are_complete(meta):
    for key, item in meta.items():
        for field in ("label", "description", "use_cases"):
            assert item.get(field), f"{key} 缺少 {field}"
