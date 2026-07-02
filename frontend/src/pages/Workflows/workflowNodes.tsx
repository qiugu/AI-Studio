import React, { memo } from 'react'
import { Handle, Position } from 'reactflow'
import type { NodeProps } from 'reactflow'
import { Card, Tag, Button } from 'antd'
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
import type { NodeType } from '../../types/workflow'

interface CustomNodeData {
  name: string
  config?: any
  onEdit?: (nodeId: string) => void
  onDelete?: (nodeId: string) => void
}

const nodeStyleConfig: Record<NodeType, { color: string; icon: React.ReactNode }> = {
  start: { color: '#52c41a', icon: <PlayCircleOutlined /> },
  end: { color: '#ff4d4f', icon: <StopOutlined /> },
  llm: { color: '#1890ff', icon: <RobotOutlined /> },
  condition: { color: '#faad14', icon: <BranchesOutlined /> },
  knowledge: { color: '#722ed1', icon: <BookOutlined /> },
  code: { color: '#13c2c2', icon: <CodeOutlined /> },
  tool: { color: '#eb2f96', icon: <ToolOutlined /> },
  loop: { color: '#fa8c16', icon: <ReloadOutlined /> },
  variable: { color: '#a0d911', icon: <ControlOutlined /> },
}

const CustomNode: React.FC<NodeProps<CustomNodeData> & { nodeType: NodeType }> = memo(
  ({ id, data, nodeType }) => {
    const style = nodeStyleConfig[nodeType]

    return (
      <Card
        size="small"
        style={{
          width: 200,
          borderColor: style.color,
          borderWidth: 2,
        }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: style.color }}>{style.icon}</span>
            <span>{data.name}</span>
            <Tag color={style.color} style={{ marginLeft: 'auto' }}>
              {nodeType}
            </Tag>
          </div>
        }
        extra={
          <div style={{ display: 'flex', gap: 4 }}>
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => data.onEdit?.(id)}
            />
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => data.onDelete?.(id)}
            />
          </div>
        }
      >
        {/* Handle for connections */}
        {nodeType !== 'end' && (
          <Handle type="source" position={Position.Bottom} style={{ background: style.color }} />
        )}
        {nodeType !== 'start' && (
          <Handle type="target" position={Position.Top} style={{ background: style.color }} />
        )}

        {/* Node content preview */}
        <div style={{ fontSize: 12, color: '#666' }}>
          {nodeType === 'llm' && data.config?.model_id && (
            <div>模型ID: {data.config.model_id}</div>
          )}
          {nodeType === 'knowledge' && data.config?.knowledge_base_id && (
            <div>知识库ID: {data.config.knowledge_base_id}</div>
          )}
          {nodeType === 'condition' && data.config?.conditions && (
            <div>条件数: {data.config.conditions.length}</div>
          )}
          {nodeType === 'code' && data.config?.code && (
            <div style={{ maxHeight: 60, overflow: 'hidden' }}>
              <pre style={{ fontSize: 10 }}>{data.config.code.substring(0, 100)}</pre>
            </div>
          )}
        </div>
      </Card>
    )
  }
)

export const createNodeComponent = (nodeType: NodeType) => {
  return (props: NodeProps<CustomNodeData>) => (
    <CustomNode {...props} nodeType={nodeType} />
  )
}

export default CustomNode