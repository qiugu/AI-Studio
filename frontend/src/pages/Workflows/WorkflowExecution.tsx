import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Form, Input, Space, Timeline, Alert, Spin, message, Result, Descriptions } from 'antd'
import { PlayCircleOutlined, StopOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { getWorkflow, validateWorkflow, executeWorkflowStreamUrl } from '../../api/workflow'
import { createWorkflowStreamRequest } from '../../utils/streamRequest'
import type { SSEWorkflowEvent } from '../../utils/streamRequest'
import type { Workflow } from '../../types/workflow'
import { getErrorMessage } from '../../utils/request'
import RouteHeader from '@/components/Layout/RouteHeader'

const WorkflowExecution: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [executionEvents, setExecutionEvents] = useState<SSEWorkflowEvent[]>([])
  const [finalOutput, setFinalOutput] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()
  const executionControllerRef = useRef<AbortController | null>(null)
  const cancelRequestedRef = useRef(false)

  const fetchWorkflow = useCallback(async () => {
    setLoading(true)
    try {
      const response = await getWorkflow(workflowId!)
      setWorkflow(response.data)
    } catch {
      message.error('获取工作流失败')
    } finally {
      setLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    if (workflowId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 路由参数变化后加载远端资源
      void fetchWorkflow()
    }
    return () => executionControllerRef.current?.abort()
  }, [workflowId, fetchWorkflow])

  const handleExecute = async (values: { input_data?: string }) => {
    setExecuting(true)
    setExecutionEvents([])
    setFinalOutput(null)
    setError(null)
    cancelRequestedRef.current = false

    try {
      // 验证工作流
      await validateWorkflow(workflowId!)
      if (cancelRequestedRef.current) return

      // 使用 SSE 流式执行
      const streamUrl = executeWorkflowStreamUrl(workflowId!)
      const input_data = values.input_data ? JSON.parse(values.input_data) : {}

      executionControllerRef.current = createWorkflowStreamRequest(
        streamUrl,
        {
          method: 'POST',
          body: JSON.stringify({ input_data }),
          headers: { 'Content-Type': 'application/json' },
        },
        {
          onEvent: (event: SSEWorkflowEvent) => {
            setExecutionEvents((prev) => [...prev, event])

            if (event.type === 'execution_completed') {
              executionControllerRef.current = null
              setFinalOutput(event.output)
              setExecuting(false)
            } else if (event.type === 'execution_failed') {
              executionControllerRef.current = null
              setError(event.error)
              setExecuting(false)
            }
          },
          onError: (error: string) => {
            executionControllerRef.current = null
            setError(error)
            setExecuting(false)
          },
        }
      )
    } catch (error: unknown) {
      setError(getErrorMessage(error) || '执行失败')
      setExecuting(false)
    }
  }

  const handleCancel = () => {
    cancelRequestedRef.current = true
    executionControllerRef.current?.abort()
    executionControllerRef.current = null
    setExecuting(false)
    message.info('执行已取消')
  }

  const renderTimelineItem = (event: SSEWorkflowEvent) => {
    switch (event.type) {
      case 'execution_started':
        return {
          color: 'blue',
          dot: <PlayCircleOutlined />,
          children: `执行开始 (ID: ${event.execution_id})`,
        }
      case 'node_started':
        return {
          color: 'gray',
          dot: <LoadingOutlined />,
          children: `节点开始: ${event.node_name} (${event.node_type})`,
        }
      case 'node_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: (
            <div>
              <div>节点完成: {event.node_name}</div>
              <div style={{ fontSize: 12, color: '#666' }}>
                输出: {JSON.stringify(event.output).substring(0, 100)}
              </div>
            </div>
          ),
        }
      case 'node_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: (
            <div>
              <div>节点失败: {event.node_name}</div>
              <div style={{ fontSize: 12, color: 'var(--app-color-danger)' }}>{event.error}</div>
            </div>
          ),
        }
      case 'execution_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: '执行完成',
        }
      case 'execution_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: `执行失败: ${event.error}`,
        }
      default:
        return {
          color: 'gray',
          children: '未知事件',
        }
    }
  }

  if (loading) {
    return (
      <div>
        <RouteHeader
          eyebrow="应用开发 / 工作流"
          title="执行工作流"
          backTo="/workflows"
          backLabel="返回工作流列表"
        />
        <Card><Spin size="large" /></Card>
      </div>
    )
  }

  if (!workflow) {
    return (
      <div>
        <RouteHeader
          eyebrow="应用开发 / 工作流"
          title="工作流不存在"
          backTo="/workflows"
          backLabel="返回工作流列表"
        />
        <Result status="404" title="工作流不存在" />
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <RouteHeader
        eyebrow="应用开发 / 工作流"
        title={`执行工作流：${workflow.name}`}
        backTo="/workflows"
        backLabel="返回工作流列表"
        extra={(
          <Button onClick={() => navigate(`/workflows/${workflowId}/edit`)}>
            返回编辑
          </Button>
        )}
      />
      <Card>
        <Space orientation="vertical" style={{ width: '100%' }} size="large">
          {/* 输入参数 */}
          <Card size="small" title="输入参数">
            <Form form={form} layout="vertical" onFinish={handleExecute}>
              <Form.Item
                label="输入数据 (JSON格式)"
                name="input_data"
                help='例如: {"value": 10}'
              >
                <Input.TextArea
                  rows={4}
                  placeholder='{"key": "value"}'
                />
              </Form.Item>
              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlayCircleOutlined />}
                  loading={executing}
                  disabled={workflow.status !== 'published'}
                >
                  执行工作流
                </Button>
                {executing && (
                  <Button
                    style={{ marginLeft: 8 }}
                    icon={<StopOutlined />}
                    onClick={handleCancel}
                  >
                    取消
                  </Button>
                )}
              </Form.Item>
            </Form>
          </Card>

          {/* 执行日志 */}
          {executionEvents.length > 0 && (
            <Card size="small" title="执行日志">
              <Timeline items={executionEvents.map(renderTimelineItem)} />
            </Card>
          )}

          {/* 执行结果 */}
          {finalOutput && (
            <Card size="small" title="执行结果">
              <Descriptions bordered column={1}>
                {Object.entries(finalOutput).map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    <pre style={{ margin: 0 }}>{JSON.stringify(value, null, 2)}</pre>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Card>
          )}

          {/* 错误信息 */}
          {error && (
            <Alert
              type="error"
              title="执行失败"
              message={error}
              showIcon
            />
          )}
        </Space>
      </Card>
    </div>
  )
}

export default WorkflowExecution
