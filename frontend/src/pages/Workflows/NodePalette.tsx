import React from 'react'
import { Card, Button, Space } from 'antd'
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

interface NodePaletteProps {
  onNodeAdd: (nodeType: NodeType) => void
}

const NodePalette: React.FC<NodePaletteProps> = ({ onNodeAdd }) => {
  const nodeTypes: Array<{ type: NodeType; label: string; icon: React.ReactNode; color: string }> = [
    { type: 'start', label: '开始', icon: <PlayCircleOutlined />, color: '#52c41a' },
    { type: 'end', label: '结束', icon: <StopOutlined />, color: '#ff4d4f' },
    { type: 'llm', label: 'LLM', icon: <RobotOutlined />, color: '#1890ff' },
    { type: 'condition', label: '条件', icon: <BranchesOutlined />, color: '#faad14' },
    { type: 'knowledge', label: '知识库', icon: <BookOutlined />, color: '#722ed1' },
    { type: 'code', label: '代码', icon: <CodeOutlined />, color: '#13c2c2' },
    { type: 'tool', label: '工具', icon: <ToolOutlined />, color: '#eb2f96' },
    { type: 'loop', label: '循环', icon: <ReloadOutlined />, color: '#fa8c16' },
    { type: 'variable', label: '变量', icon: <ControlOutlined />, color: '#a0d911' },
  ]

  return (
    <Card size="small" title="节点类型" style={{ width: 200 }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        {nodeTypes.map((nodeType) => (
          <Button
            key={nodeType.type}
            block
            icon={nodeType.icon}
            style={{ backgroundColor: nodeType.color, color: 'white' }}
            onClick={() => onNodeAdd(nodeType.type)}
          >
            {nodeType.label}
          </Button>
        ))}
      </Space>
    </Card>
  )
}

export default NodePalette