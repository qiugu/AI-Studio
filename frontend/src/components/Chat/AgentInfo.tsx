import type { ReactNode } from 'react'
import type { Agent, ToolType } from '@/types/agent'
import {
  ApiOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons'

interface AgentInfoProps {
  agent: Agent
}

const TOOL_META: Record<ToolType, { label: string; icon: ReactNode }> = {
  knowledge: { label: '知识库', icon: <DatabaseOutlined /> },
  api: { label: 'API', icon: <ApiOutlined /> },
  function: { label: '函数', icon: <ToolOutlined /> },
  workflow: { label: '工作流', icon: <BranchesOutlined /> },
  plugin: { label: '插件', icon: <AppstoreOutlined /> },
}

export default function AgentInfo({ agent }: AgentInfoProps) {
  const statusLabel = {
    draft: '草稿',
    published: '已发布',
    archived: '已归档',
  }[agent.status]
  const capabilityTypes = Array.from(new Set(agent.tools.map((tool) => tool.tool_type)))
  const defaultKnowledgeCount = agent.default_knowledge_base_count ?? 0
  if (defaultKnowledgeCount > 0 && !capabilityTypes.includes('knowledge')) {
    capabilityTypes.push('knowledge')
  }
  const runtimeLabel = {
    draft: '配置中',
    published: '可执行',
    archived: '已归档',
  }[agent.status]

  return (
    <div className="agent-info-card">
      <div className="agent-info-header">
        <div className="agent-info-avatar" aria-hidden="true">
          {agent.avatar ? <img src={agent.avatar} alt="" /> : <RobotOutlined />}
        </div>
        <div className="agent-info-content">
          <div className="agent-info-title-row">
            <h1 className="agent-name">{agent.name}</h1>
            <span className={`agent-status agent-status--${agent.status}`}>
              <span className="agent-status__dot" />
              {statusLabel}
            </span>
          </div>
          <p className="agent-description">
            {agent.description || '这个 Agent 会根据你的目标完成分析、检索与执行。'}
          </p>
          <div className="agent-info-meta">
            <span><ThunderboltOutlined /> 企业 Agent</span>
            <span><strong>{agent.tools.length + defaultKnowledgeCount}</strong> 项已授权能力</span>
          </div>
        </div>
        <div className="agent-info-runtime" aria-label="Agent 运行状态">
          <span className={`agent-runtime-dot agent-runtime-dot--${agent.status}`} />
          <span>{runtimeLabel}</span>
        </div>
      </div>
      <div className="agent-info-context">
        <span className="agent-info-context__label">执行上下文</span>
        <div className="agent-info-capabilities">
          {capabilityTypes.length > 0 ? capabilityTypes.map((type) => (
            <span className="agent-capability-chip" key={type}>
              {TOOL_META[type].icon}
              {TOOL_META[type].label}
              {type === 'knowledge' && defaultKnowledgeCount > 0 && !agent.tools.some((tool) => tool.tool_type === 'knowledge')
                ? ` · 默认接入 ${defaultKnowledgeCount} 库`
                : null}
            </span>
          )) : (
            <span className="agent-info-context__empty">当前仅使用模型本身的推理能力</span>
          )}
        </div>
      </div>
    </div>
  )
}
