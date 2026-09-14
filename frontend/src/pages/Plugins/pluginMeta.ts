import type { PluginSourceType, PluginType } from '@/types/plugin'

/**
 * 插件类型展示元数据。
 *
 * 插件由两个正交维度描述，二者含义不同、不可混用：
 * - 维度 A `plugin_type`  能力形态：插件「做什么」，取值 tool / connector / processor；
 * - 维度 B `source_type`  接入方式：插件「怎么接进来」，取值 http / mcp / skill。
 *
 * 本文件是前端侧的唯一事实源，需与后端 `backend/app/core/plugin_types.py` 及
 * `docs/plugin-types.md` 保持口径一致；`Record<...>` 类型可保证取值无遗漏。
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

/** 维度 A · 能力形态（插件「做什么」）。 */
export const PLUGIN_TYPE_META: Record<PluginType, PluginMetaItem> = {
  tool: {
    label: '工具',
    description: '原子化、可被 Agent 调用的单个动作。',
    useCases: '让 Agent 在对话中执行动作：网页搜索、计算、发起 HTTP 请求等。',
    color: 'blue',
  },
  connector: {
    label: '连接器',
    description: '对接外部系统，负责数据的接入与回传。',
    useCases: '把外部数据源或业务系统接进平台：数据库、企业 IM、对象存储、CRM 等。',
    color: 'orange',
  },
  processor: {
    label: '处理器',
    description: '对数据做转换/加工，形如「输入 → 输出」的纯处理。',
    useCases: '数据清洗、格式转换、文本切分、摘要、脱敏等。',
    color: 'purple',
  },
}

/** 维度 B · 接入方式（插件「怎么接进来」）。 */
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

/** 能力形态下拉选项（供表单渲染）。 */
export const PLUGIN_TYPE_OPTIONS = (Object.keys(PLUGIN_TYPE_META) as PluginType[]).map(
  (value) => ({ value, label: `${PLUGIN_TYPE_META[value].label} (${value})` })
)

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

/** 取能力形态的展示元数据；未知取值降级为原值展示，避免历史脏值渲染异常。 */
export function pluginTypeMeta(value?: string | null): PluginMetaItem {
  // 用 hasOwnProperty 而非直接取键：避免 'constructor' 等原型链键被误判为已登记取值。
  if (value && Object.prototype.hasOwnProperty.call(PLUGIN_TYPE_META, value)) {
    return PLUGIN_TYPE_META[value as PluginType]
  }
  return UNKNOWN_META(value)
}

/** 取接入方式的展示元数据；未知取值降级为原值展示。 */
export function pluginSourceMeta(value?: string | null): PluginMetaItem {
  if (value && Object.prototype.hasOwnProperty.call(PLUGIN_SOURCE_META, value)) {
    return PLUGIN_SOURCE_META[value as PluginSourceType]
  }
  return UNKNOWN_META(value)
}
