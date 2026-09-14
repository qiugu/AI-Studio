"""插件类型体系：两个正交维度的集中定义（单一事实源）。

插件由两个**相互独立**的维度描述，二者不可混为一谈：

维度 A · 能力形态 ``plugin_type`` —— 插件「做什么」：

- ``tool``       工具   ：原子化、可被 Agent 调用的单个动作（HTTP 端点）。
- ``connector``  连接器 ：对接外部系统，负责数据的接入与回传。
- ``processor``  处理器 ：对数据做转换/加工，形如「输入 → 输出」的纯处理。

维度 B · 接入方式 ``source_type`` —— 插件「怎么接进来」：

- ``http``  ：通过 HTTP / OpenAPI 端点接入（当前执行器唯一落地的形态）。
- ``mcp``   ：通过 Model Context Protocol 接入；一个 MCP 服务通常暴露多个工具。
- ``skill`` ：本地技能包（说明文档 + 可选脚本/资源），由 Agent 按需加载。

关于 ``provider``：该取值已废弃。它表达的是「能力供应方」，与平台既有的 AI 供应商
（``/api/ai-providers``）语义重叠，故从能力形态维度移除；历史标记为 ``provider`` 的
记录由迁移 ``a7b8c9d0e1f2`` 统一改写为 ``connector``。

本模块是后端侧的唯一事实源；前端对应的展示元数据见
``frontend/src/pages/Plugins/pluginMeta.ts``，文档见 ``docs/plugin-types.md``。
"""
from enum import Enum
from typing import Dict, List


class PluginType(str, Enum):
    """维度 A · 能力形态：插件「做什么」。"""

    TOOL = "tool"
    CONNECTOR = "connector"
    PROCESSOR = "processor"


class PluginSourceType(str, Enum):
    """维度 B · 接入方式：插件「怎么接进来」。"""

    HTTP = "http"
    MCP = "mcp"
    SKILL = "skill"


# 默认值：新建插件默认「工具 + HTTP 接入」，与既有行为保持一致。
DEFAULT_PLUGIN_TYPE: str = PluginType.TOOL.value
DEFAULT_SOURCE_TYPE: str = PluginSourceType.HTTP.value


# 展示元数据：中文名 / 一句话作用 / 典型使用场景。
# 供前端渲染与文档引用，避免多处硬编码导致口径漂移。
PLUGIN_TYPE_META: Dict[str, Dict[str, str]] = {
    PluginType.TOOL.value: {
        "label": "工具",
        "description": "原子化、可被 Agent 调用的单个动作。",
        "use_cases": "需要让 Agent 在对话中执行动作：网页搜索、计算、发起 HTTP 请求等。",
    },
    PluginType.CONNECTOR.value: {
        "label": "连接器",
        "description": "对接外部系统，负责数据的接入与回传。",
        "use_cases": "把外部数据源或业务系统接进平台：数据库、企业 IM、对象存储、CRM 等。",
    },
    PluginType.PROCESSOR.value: {
        "label": "处理器",
        "description": "对数据做转换/加工，形如「输入 → 输出」的纯处理。",
        "use_cases": "数据清洗、格式转换、文本切分、摘要、脱敏等。",
    },
}

PLUGIN_SOURCE_TYPE_META: Dict[str, Dict[str, str]] = {
    PluginSourceType.HTTP.value: {
        "label": "HTTP / OpenAPI",
        "description": "通过标准 HTTP 端点接入，支持 OpenAPI 规范自动导入端点。",
        "use_cases": "绝大多数 REST 服务；当前执行器唯一落地的接入方式。",
    },
    PluginSourceType.MCP.value: {
        "label": "MCP 协议",
        "description": "通过 Model Context Protocol 接入，一个服务通常暴露多个工具。",
        "use_cases": "接入已支持 MCP 的第三方能力服务器（执行器实现属二期）。",
    },
    PluginSourceType.SKILL.value: {
        "label": "Skill 技能包",
        "description": "本地技能包（说明文档 + 可选脚本/资源），由 Agent 按需加载。",
        "use_cases": "把一组操作手册与脚本打包交给 Agent（执行器实现属二期）。",
    },
}


def plugin_type_values() -> List[str]:
    """返回合法的能力形态取值。供校验、文档与测试复用。"""
    return [item.value for item in PluginType]


def source_type_values() -> List[str]:
    """返回合法的接入方式取值。供校验、文档与测试复用。"""
    return [item.value for item in PluginSourceType]
