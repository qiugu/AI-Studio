import React, { useState, useEffect, useCallback } from 'react'
import ReactFlow, {
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Panel,
} from 'reactflow'
import type { Node, Edge, Connection, NodeTypes } from 'reactflow'
import 'reactflow/dist/style.css'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Card, Space, message, Modal } from 'antd'
import { SaveOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
import { getWorkflow, updateWorkflow, publishWorkflow, validateWorkflow } from '../../api/workflow'
import type { Workflow, WorkflowNodeCreate, WorkflowNodeConfig } from '../../types/workflow'
import type { WorkflowEdgeCreate } from '../../types/workflow'
import { createNodeComponent } from './workflowNodes'
import NodePalette from './NodePalette'
import NodeConfigPanel from './NodeConfigPanel'

const WorkflowEditor: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editingNode, setEditingNode] = useState<Node | null>(null)
  const [configPanelVisible, setConfigPanelVisible] = useState(false)

  // 自定义节点类型
  const nodeTypes: NodeTypes = {
    start: createNodeComponent('start'),
    end: createNodeComponent('end'),
    llm: createNodeComponent('llm'),
    condition: createNodeComponent('condition'),
    knowledge: createNodeComponent('knowledge'),
    code: createNodeComponent('code'),
    tool: createNodeComponent('tool'),
    loop: createNodeComponent('loop'),
    variable: createNodeComponent('variable'),
  }

  useEffect(() => {
    if (workflowId) {
      fetchWorkflow()
    }
  }, [workflowId])

  const fetchWorkflow = async () => {
    setLoading(true)
    try {
      const response = await getWorkflow(parseInt(workflowId!))
      const workflowData = response.data
      setWorkflow(workflowData)

      // 将数据库节点转换为React Flow节点
      const flowNodes: Node[] = workflowData.nodes.map((node) => ({
        id: node.id.toString(),
        type: node.node_type,
        position: { x: node.position_x, y: node.position_y },
        data: {
          name: node.name,
          config: node.config,
        },
      }))

      // 将数据库边转换为React Flow边
      const flowEdges: Edge[] = workflowData.edges.map((edge) => ({
        id: edge.id.toString(),
        source: edge.source_node_id.toString(),
        target: edge.target_node_id.toString(),
        label: edge.label || undefined,
        data: {
          condition: edge.condition,
        },
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch (error) {
      message.error('获取工作流失败')
    } finally {
      setLoading(false)
    }
  }

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge(params, eds))
  }, [setEdges])

  const handleAddNode = useCallback((nodeType: any) => {
    const newNode: Node = {
      id: `temp-${Date.now()}`, // 临时ID，保存时会替换为真实ID
      type: nodeType,
      position: { x: 250, y: 150 }, // 默认位置
      data: {
        name: `新${nodeType}节点`,
        config: {},
      },
    }
    setNodes((nds) => [...nds, newNode])
  }, [setNodes])

  const handleEditNode = useCallback((nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    if (node) {
      setEditingNode(node)
      setConfigPanelVisible(true)
    }
  }, [nodes])

  const handleDeleteNode = useCallback((nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId))
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
  }, [setNodes, setEdges])

  const handleSaveNodeConfig = useCallback(
    (nodeId: string, data: { name: string; config: WorkflowNodeConfig }) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, name: data.name, config: data.config } }
            : node
        )
      )
    },
    [setNodes]
  )

  // Update node data to include edit/delete handlers
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          onEdit: handleEditNode,
          onDelete: handleDeleteNode,
        },
      }))
    )
  }, [handleEditNode, handleDeleteNode, setNodes])

  const handleSave = async () => {
    setSaving(true)
    try {
      // 将React Flow节点转换为数据库节点
      const workflowNodes: WorkflowNodeCreate[] = nodes.map((node) => ({
        node_type: node.type as any,
        name: node.data.name,
        position_x: node.position.x,
        position_y: node.position.y,
        config: node.data.config,
      }))

      // 将React Flow边转换为数据库边
      const workflowEdges: WorkflowEdgeCreate[] = edges.map((edge) => ({
        source_node_id: parseInt(edge.source),
        target_node_id: parseInt(edge.target),
        label: typeof edge.label === 'string' ? edge.label : undefined,
        condition: edge.data?.condition,
      }))

      await updateWorkflow(parseInt(workflowId!), {
        nodes: workflowNodes,
        edges: workflowEdges,
      })

      message.success('工作流已保存')
      fetchWorkflow() // 刷新数据
    } catch (error) {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleValidate = async () => {
    try {
      const response = await validateWorkflow(parseInt(workflowId!))
      const result = response.data
      if (result.valid) {
        message.success(`工作流验证通过：${result.node_count}个节点，${result.edge_count}条连线`)
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '验证失败')
    }
  }

  const handlePublish = async () => {
    Modal.confirm({
      title: '发布工作流',
      content: '确定要发布此工作流吗？发布后即可执行。',
      onOk: async () => {
        try {
          await publishWorkflow(parseInt(workflowId!))
          message.success('工作流已发布')
          fetchWorkflow()
        } catch (error: any) {
          message.error(error.response?.data?.message || '发布失败')
        }
      },
    })
  }

  const handleExecute = () => {
    navigate(`/workflows/${workflowId}/execute`)
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Card style={{ marginBottom: 8 }}>
        <Space>
          <Button icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            保存
          </Button>
          <Button onClick={handleValidate}>验证</Button>
          {workflow?.status === 'draft' && (
            <Button type="primary" icon={<CheckOutlined />} onClick={handlePublish}>
              发布
            </Button>
          )}
          {workflow?.status === 'published' && (
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleExecute}>
              执行
            </Button>
          )}
          <Button onClick={() => navigate('/workflows')}>返回列表</Button>
        </Space>
      </Card>

      <div style={{ flex: 1, position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
        >
          <Controls />
          <MiniMap />
          <Background gap={16} size={1} />

          {/* 左侧节点类型面板 */}
          <Panel position="top-left">
            <NodePalette onNodeAdd={handleAddNode} />
          </Panel>
        </ReactFlow>
      </div>

      <NodeConfigPanel
        visible={configPanelVisible}
        node={editingNode}
        onClose={() => setConfigPanelVisible(false)}
        onSave={handleSaveNodeConfig}
      />
    </div>
  )
}

export default WorkflowEditor