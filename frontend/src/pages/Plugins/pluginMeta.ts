import type { PluginSourceType } from '@/types/plugin'

/**
 * 插件接入方式展示元数据。
 *
 * 插件形态由**单一**维度承载：`source_type` 接入方式——插件「怎么接进来」，
 * 取值 http / mcp / skill。
 *
 * 历史沿革（M2.0 移除）：本文件原同时维护「能力形态」维度 `plugin_type`
 * （tool / connector / processor）。该维度经评审确认立不住，故整体移除：
 *
 * 1. 边界不可判定——同一插件可同时满足多个取值（调外部 API 做摘要既是 tool 又是
 *    processor；查数据库既是 connector 又是 tool）；
 * 2. 零行为差异——全仓不存在 `if plugin_type ==` 分支，它只用于列表筛选与展示；
 * 3. 定义混入他者语义——connector 的「地址 / 凭据 / 协议」属接入方式维度。
 *
 * 连带删除：`PLUGIN_TYPE_META`、`PLUGIN_TYPE_OPTIONS`、`pluginTypeMeta()`。
 *
 * 本文件是前端侧的唯一事实源，需与后端 `backend/app/core/plugin_source_types.py`
 * 及 `docs/plugin-types.md` 保持口径一致；`Record<...>` 类型可保证取值无遗漏。
 */
export interface PluginMetaItem {
  /** 中文名 */
  label: string
  /** 一句话作用，用于表格与 Tooltip */
  description: string
  /** 典型使用场景 */
  useCases: string
  /** Ant Design Tag 颜色 */
  color: string
}

/** 接入方式（插件「怎么接进来」）。 */
export const PLUGIN_SOURCE_META: Record<PluginSourceType, PluginMetaItem> = {
  http: {
    label: 'HTTP / OpenAPI',
    description: '通过标准 HTTP 端点接入，支持 OpenAPI 规范自动导入端点。',
    useCases: '绝大多数 REST 服务；当前执行器唯一落地的接入方式。',
    color: 'cyan',
  },
  mcp: {
    label: 'MCP 协议',
    description: '通过 Model Context Protocol 接入，一个服务通常暴露多个工具。',
    useCases: '接入已支持 MCP 的第三方能力服务器（执行器实现属二期）。',
    color: 'geekblue',
  },
  skill: {
    label: 'Skill 技能包',
    description: '本地技能包（说明文档 + 可选脚本/资源），由 Agent 按需加载。',
    useCases: '把一组操作手册与脚本打包交给 Agent（执行器实现属二期）。',
    color: 'gold',
  },
}

/** 接入方式下拉选项（供表单渲染）。 */
export const PLUGIN_SOURCE_OPTIONS = (
  Object.keys(PLUGIN_SOURCE_META) as PluginSourceType[]
).map((value) => ({ value, label: PLUGIN_SOURCE_META[value].label }))

const UNKNOWN_META = (value?: string | null): PluginMetaItem => ({
  label: value || '—',
  description: '',
  useCases: '',
  color: 'default',
})

/** 取接入方式的展示元数据；未知取值降级为原值展示。 */
export function pluginSourceMeta(value?: string | null): PluginMetaItem {
  // 用 hasOwnProperty 而非直接取键：避免 'constructor' 等原型链键被误判为已登记取值。
  if (value && Object.prototype.hasOwnProperty.call(PLUGIN_SOURCE_META, value)) {
    return PLUGIN_SOURCE_META[value as PluginSourceType]
  }
  return UNKNOWN_META(value)
}
