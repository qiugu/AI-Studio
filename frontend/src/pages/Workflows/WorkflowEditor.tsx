import React, { useState, useEffect, useCallback, useMemo } from 'react'
import ReactFlow, {
  Controls,
  Background,
  MiniMap,
  BackgroundVariant,
  ConnectionLineType,
  useNodesState,
  useEdgesState,
  addEdge,
  Panel,
} from 'reactflow'
import type { Node, Edge, Connection, NodeTypes } from 'reactflow'
import 'reactflow/dist/style.css'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Space, message, Modal } from 'antd'
import { SaveOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
import { getWorkflow, updateWorkflow, publishWorkflow, validateWorkflow } from '../../api/workflow'
import type { NodeType, Workflow, WorkflowNodeConfig } from '../../types/workflow'
import { getErrorMessage } from '../../utils/request'
import { createNodeComponent } from './workflowNodes'
import NodePalette from './NodePalette'
import NodeConfigPanel from './NodeConfigPanel'
import { buildWorkflowGraphPayload } from './workflowPayload'
import './WorkflowEditor.css'

const WorkflowEditor: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [saving, setSaving] = useState(false)
  const [editingNode, setEditingNode] = useState<Node | null>(null)
  const [configPanelVisible, setConfigPanelVisible] = useState(false)

  // 定义处理器函数
  const handleEditNode = useCallback((nodeId: string) => {
    setNodes((nds) => {
      const node = nds.find((n) => n.id === nodeId)
      if (node) {
        setEditingNode(node)
        setConfigPanelVisible(true)
      }
      return nds
    })
  }, [setNodes])

  const handleDeleteNode = useCallback((nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId))
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
  }, [setNodes, setEdges])

  // 自定义节点类型 - 使用 useMemo 避免每次渲染重新创建
  const nodeTypes: NodeTypes = useMemo(() => ({
    start: createNodeComponent('start'),
    end: createNodeComponent('end'),
    llm: createNodeComponent('llm'),
    condition: createNodeComponent('condition'),
    knowledge: createNodeComponent('knowledge'),
    code: createNodeComponent('code'),
    tool: createNodeComponent('tool'),
    loop: createNodeComponent('loop'),
    variable: createNodeComponent('variable'),
  }), [])

  const fetchWorkflow = useCallback(async () => {
    try {
      const response = await getWorkflow(workflowId!)
      const workflowData = response.data
      setWorkflow(workflowData)

      // 将数据库节点转换为React Flow节点，使用 ref 中的处理器
      const flowNodes: Node[] = workflowData.nodes.map((node) => ({
        id: node.id.toString(),
        type: node.node_type,
        position: { x: node.position_x, y: node.position_y },
        data: {
          name: node.name,
          config: node.config,
          onEdit: handleEditNode,
          onDelete: handleDeleteNode,
        },
      }))

      // 将数据库边转换为React Flow边
      const flowEdges: Edge[] = workflowData.edges.map((edge) => ({
        id: edge.id.toString(),
        type: 'smoothstep',
        source: edge.source_node_id.toString(),
        target: edge.target_node_id.toString(),
        sourceHandle: edge.source_handle || undefined,
        targetHandle: edge.target_handle || undefined,
        label: edge.label || undefined,
        data: {
          condition: edge.condition,
        },
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch {
      message.error('获取工作流失败')
    }
  }, [workflowId, setNodes, setEdges, handleEditNode, handleDeleteNode])

  useEffect(() => {
    if (workflowId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 路由参数变化后加载远端资源
      void fetchWorkflow()
    }
  }, [workflowId, fetchWorkflow])

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge({ ...params, type: 'smoothstep' }, eds))
  }, [setEdges])

  const handleAddNode = useCallback((nodeType: NodeType) => {
    const newNode: Node = {
      id: `temp-${Date.now()}`, // 临时ID，保存时会替换为真实ID
      type: nodeType,
      position: { x: 250, y: 150 }, // 默认位置
      data: {
        name: `新${nodeType}节点`,
        config: {},
        onEdit: handleEditNode,
        onDelete: handleDeleteNode,
      },
    }
    setNodes((nds) => [...nds, newNode])
  }, [setNodes, handleEditNode, handleDeleteNode])

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

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateWorkflow(workflowId!, buildWorkflowGraphPayload(nodes, edges))

      message.success('工作流已保存')
      fetchWorkflow() // 刷新数据
    } catch (error: unknown) {
      message.error(getErrorMessage(error) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleValidate = async () => {
    try {
      const response = await validateWorkflow(workflowId!)
      const result = response.data
      if (result.valid) {
        message.success(`工作流验证通过：${result.node_count}个节点，${result.edge_count}条连线`)
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error) || '验证失败')
    }
  }

  const handlePublish = async () => {
    Modal.confirm({
      title: '发布工作流',
      content: '确定要发布此工作流吗？发布后即可执行。',
      onOk: async () => {
        try {
          await publishWorkflow(workflowId!)
          message.success('工作流已发布')
          fetchWorkflow()
        } catch (error: unknown) {
          message.error(getErrorMessage(error) || '发布失败')
        }
      },
    })
  }

  const handleExecute = () => {
    navigate(`/workflows/${workflowId}/execute`)
  }

  return (
    <div className="workflow-editor-container">
      {/* Toolbar */}
      <div className="workflow-editor-toolbar">
        <Space size={12}>
          <Button
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            type="primary"
            ghost
          >
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
      </div>

      {/* Canvas */}
      <div className="workflow-editor-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          connectionLineType={ConnectionLineType.SmoothStep}
          fitView
          attributionPosition="bottom-left"
        >
          <Controls />
          <MiniMap />
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />

          {/* Node palette - positioned in top-left */}
          <Panel position="top-left">
            <NodePalette onNodeAdd={handleAddNode} />
          </Panel>
        </ReactFlow>
      </div>

      {/* Config panel drawer */}
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
