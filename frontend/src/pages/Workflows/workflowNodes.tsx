import React, { memo } from 'react'
import { Handle, Position } from 'reactflow'
import type { NodeProps } from 'reactflow'
import {
  PlayCircleOutlined,
  StopOutlined,
  RobotOutlined,
  BranchesOutlined,
  BookOutlined,
  CodeOutlined,
  ToolOutlined,
  ReloadOutlined,
  ControlOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { NodeType, WorkflowNodeConfig } from '../../types/workflow'
import './WorkflowEditor.css'

interface CustomNodeData {
  name: string
  config?: WorkflowNodeConfig
  onEdit?: (nodeId: string) => void
  onDelete?: (nodeId: string) => void
}

const nodeStyleConfig: Record<NodeType, { color: string; icon: React.ReactNode }> = {
  start: { color: 'var(--wf-node-start)', icon: <PlayCircleOutlined /> },
  end: { color: 'var(--wf-node-end)', icon: <StopOutlined /> },
  llm: { color: 'var(--wf-node-llm)', icon: <RobotOutlined /> },
  condition: { color: 'var(--wf-node-condition)', icon: <BranchesOutlined /> },
  knowledge: { color: 'var(--wf-node-knowledge)', icon: <BookOutlined /> },
  code: { color: 'var(--wf-node-code)', icon: <CodeOutlined /> },
  tool: { color: 'var(--wf-node-tool)', icon: <ToolOutlined /> },
  loop: { color: 'var(--wf-node-loop)', icon: <ReloadOutlined /> },
  variable: { color: 'var(--wf-node-variable)', icon: <ControlOutlined /> },
}

const nodeTypeLabels: Record<NodeType, string> = {
  start: '开始',
  end: '结束',
  llm: '模型',
  condition: '条件',
  knowledge: '知识',
  code: '代码',
  tool: '工具',
  loop: '循环',
  variable: '变量',
}

/**
 * 智能连接桩配置系统
 * 根据节点类型提供合适的连接桩布局，支持多方向工作流设计
 */
const getHandleConfig = (nodeType: NodeType) => {
  const configs: Record<NodeType, { sources: Position[]; targets: Position[] }> = {
    // 流向型节点：主要方向（水平）+ 辅助方向（垂直）
    start: { sources: [Position.Right, Position.Bottom, Position.Top], targets: [] },
    end: { sources: [], targets: [Position.Left, Position.Top, Position.Bottom] },

    // 处理型节点：四方向，水平方向为主（鼓励左右布局）
    llm: { sources: [Position.Right, Position.Bottom], targets: [Position.Left, Position.Top] },
    knowledge: { sources: [Position.Right, Position.Bottom], targets: [Position.Left, Position.Top] },
    code: { sources: [Position.Right, Position.Bottom], targets: [Position.Left, Position.Top] },
    tool: { sources: [Position.Right, Position.Bottom], targets: [Position.Left, Position.Top] },
    variable: { sources: [Position.Right, Position.Bottom], targets: [Position.Left, Position.Top] },

    // 分支型节点：多输出，支持条件分支
    condition: {
      sources: [Position.Right, Position.Bottom, Position.Top],
      targets: [Position.Left]
    },

    // 循环型节点：右侧继续循环，底部退出循环
    loop: {
      sources: [Position.Right, Position.Bottom],
      targets: [Position.Left, Position.Top]
    },
  }

  return configs[nodeType]
}

const CustomNode: React.FC<NodeProps<CustomNodeData> & { nodeType: NodeType }> = memo(
  ({ id, data, nodeType, selected }) => {
    const style = nodeStyleConfig[nodeType]
    const handleConfig = getHandleConfig(nodeType)

    return (
      <div
        className={`workflow-node workflow-node--compact ${selected ? 'selected' : ''}`}
        data-type={nodeType}
        aria-label={`${nodeTypeLabels[nodeType]}节点：${data.name}`}
      >
        {/* Node header */}
        <div className="workflow-node-header">
          <div className="workflow-node-icon" style={{ color: style.color }}>
            {style.icon}
          </div>
          <div className="workflow-node-label">{data.name}</div>

          {/* Action buttons - only visible on hover */}
          <div className="workflow-node-actions">
            <button
              className="workflow-node-action-btn"
              onClick={() => data.onEdit?.(id)}
              title="编辑节点"
            >
              <EditOutlined />
            </button>
            <button
              className="workflow-node-action-btn danger"
              onClick={() => data.onDelete?.(id)}
              title="删除节点"
            >
              <DeleteOutlined />
            </button>
          </div>
        </div>

        {/* Node content preview */}
        <div className="workflow-node-content">
          {nodeType === 'llm' && (data.config?.model_id || data.config?.prompt_id) && (
            <div className="workflow-node-meta">
              {data.config?.model_id && (
                <span className="workflow-node-chip">
                  <span className="workflow-node-chip-label">模型</span>
                  已配置
                </span>
              )}
              {data.config?.prompt_id && (
                <span className="workflow-node-chip workflow-node-chip--prompt">
                  Prompt · 已关联
                </span>
              )}
            </div>
          )}
          {nodeType === 'knowledge' && data.config?.knowledge_base_id && (
            <div>知识库：已选择</div>
          )}
          {nodeType === 'condition' && data.config?.conditions && (
            <div>条件数: {data.config.conditions.length}</div>
          )}
          {nodeType === 'code' && data.config?.code && (
            <div>
              <pre>{data.config.code.substring(0, 100)}</pre>
            </div>
          )}
          {nodeType === 'loop' && data.config?.max_iterations && (
            <div>最大迭代次数: {data.config.max_iterations}</div>
          )}
        </div>

        {/* Smart Connection Handles - Multi-directional */}
        {handleConfig.sources.map((position, index) => (
          <Handle
            key={`source-${index}`}
            type="source"
            position={position}
            id={`source-${position}`}
            style={{ background: style.color }}
            className={`handle-${position}`}
          />
        ))}
        {handleConfig.targets.map((position, index) => (
          <Handle
            key={`target-${index}`}
            type="target"
            position={position}
            id={`target-${position}`}
            style={{ background: style.color }}
            className={`handle-${position}`}
          />
        ))}
      </div>
    )
  }
)

// eslint-disable-next-line react-refresh/only-export-components -- React Flow 需要稳定的节点组件工厂
export const createNodeComponent = (nodeType: NodeType) => {
  return (props: NodeProps<CustomNodeData>) => (
    <CustomNode {...props} nodeType={nodeType} />
  )
}

export default CustomNode
