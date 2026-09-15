"""插件接入方式体系：``source_type`` 维度的集中定义（单一事实源）。

``source_type`` 描述插件「怎么接进来」，是插件的**唯一**形态维度：

- ``http``  ：通过 HTTP / OpenAPI 端点接入（当前执行器唯一落地的形态）。
- ``mcp``   ：通过 Model Context Protocol 接入；一个 MCP 服务通常暴露多个工具。
- ``skill`` ：本地技能包（说明文档 + 可选脚本/资源），由 Agent 按需加载。

历史沿革（M2.0 移除）：

本模块原同时定义「能力形态」维度 ``plugin_type``（tool / connector / processor）。
该维度经评审确认**立不住**，故整体移除：

1. **边界不可判定**——同一插件可同时满足多个取值（调外部 API 做摘要既是 tool 又是
   processor；查数据库既是 connector 又是 tool），文档判据只有「以…为主」这类程度描述。
2. **零行为差异**——全仓不存在 ``if plugin_type ==`` 分支，它只用于列表筛选与展示，
   即无论选哪个，系统行为完全一致。
3. **定义混入他者语义**——connector 的定义写进「地址、凭据、协议」，那是接入方式
   （本模块 ``source_type``）的职责；processor 写「不依赖外部系统」，同属接入维度。

另，原取值 ``provider`` 更早已因与平台 AI 供应商（``/api/ai-providers``）语义重叠而
移除，历史记录由迁移 ``a7b8c9d0e1f2`` 统一改写为 ``connector``（``connector`` 亦已随
``plugin_type`` 一并移除）。

本模块是后端侧的唯一事实源；前端对应的展示元数据见
``frontend/src/pages/Plugins/pluginMeta.ts``，文档见 ``docs/plugin-types.md``。
"""
from enum import Enum
from typing import Dict, List


class PluginSourceType(str, Enum):
    """接入方式：插件「怎么接进来」。"""

    HTTP = "http"
    MCP = "mcp"
    SKILL = "skill"


# 默认值：新建插件默认 HTTP 接入，与既有行为保持一致。
DEFAULT_SOURCE_TYPE: str = PluginSourceType.HTTP.value


# 展示元数据：中文名 / 一句话作用 / 典型使用场景。
# 供前端渲染与文档引用，避免多处硬编码导致口径漂移。
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


def source_type_values() -> List[str]:
    """返回合法的接入方式取值。供校验、文档与测试复用。"""
    return [item.value for item in PluginSourceType]
