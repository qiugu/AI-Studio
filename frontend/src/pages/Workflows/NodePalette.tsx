import React from 'react'
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
} from '@ant-design/icons'
import type { NodeType } from '../../types/workflow'
import './WorkflowEditor.css'

interface NodePaletteProps {
  onNodeAdd: (nodeType: NodeType) => void
}

const NodePalette: React.FC<NodePaletteProps> = ({ onNodeAdd }) => {
  const nodeTypes: Array<{ type: NodeType; label: string; icon: React.ReactNode }> = [
    { type: 'start', label: '开始', icon: <PlayCircleOutlined /> },
    { type: 'end', label: '结束', icon: <StopOutlined /> },
    { type: 'llm', label: 'LLM', icon: <RobotOutlined /> },
    { type: 'condition', label: '条件', icon: <BranchesOutlined /> },
    { type: 'knowledge', label: '知识库', icon: <BookOutlined /> },
    { type: 'code', label: '代码', icon: <CodeOutlined /> },
    { type: 'tool', label: '工具', icon: <ToolOutlined /> },
    { type: 'loop', label: '循环', icon: <ReloadOutlined /> },
    { type: 'variable', label: '变量', icon: <ControlOutlined /> },
  ]

  return (
    <div className="node-palette">
      <div className="node-palette-header">节点类型</div>
      <div className="node-palette-list">
        {nodeTypes.map((nodeType) => (
          <button
            key={nodeType.type}
            className="node-palette-item"
            data-type={nodeType.type}
            onClick={() => onNodeAdd(nodeType.type)}
          >
            <span className="node-palette-item-icon">{nodeType.icon}</span>
            <span>{nodeType.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default NodePalette