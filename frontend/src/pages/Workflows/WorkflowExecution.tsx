import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Form, Input, Space, Timeline, Alert, Spin, message, Result, Descriptions } from 'antd'
import { PlayCircleOutlined, StopOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { getWorkflow, validateWorkflow, executeWorkflowStreamUrl } from '../../api/workflow'
import { createWorkflowStreamRequest } from '../../utils/streamRequest'
import type { SSEWorkflowEvent } from '../../utils/streamRequest'
import type { Workflow } from '../../types/workflow'

const WorkflowExecution: React.FC = () => {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [executionEvents, setExecutionEvents] = useState<SSEWorkflowEvent[]>([])
  const [_, setExecutionId] = useState<string | null>(null)
  const [finalOutput, setFinalOutput] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    if (workflowId) {
      fetchWorkflow()
    }
  }, [workflowId])

  const fetchWorkflow = async () => {
    setLoading(true)
    try {
      const response = await getWorkflow(workflowId!)
      setWorkflow(response.data)
    } catch (error) {
      message.error('获取工作流失败')
    } finally {
      setLoading(false)
    }
  }

  const handleExecute = async (values: any) => {
    setExecuting(true)
    setExecutionEvents([])
    setFinalOutput(null)
    setError(null)

    try {
      // 验证工作流
      await validateWorkflow(workflowId!)

      // 使用 SSE 流式执行
      const streamUrl = executeWorkflowStreamUrl(workflowId!)
      const input_data = values.input_data ? JSON.parse(values.input_data) : {}

      createWorkflowStreamRequest(
        streamUrl,
        {
          method: 'POST',
          body: JSON.stringify({ input_data }),
          headers: { 'Content-Type': 'application/json' },
        },
        {
          onEvent: (event: SSEWorkflowEvent) => {
            setExecutionEvents((prev) => [...prev, event])

            if (event.type === 'execution_started') {
              setExecutionId(event.execution_id)
            } else if (event.type === 'execution_completed') {
              setFinalOutput(event.output)
              setExecuting(false)
            } else if (event.type === 'execution_failed') {
              setError(event.error)
              setExecuting(false)
            }
          },
          onError: (error: string) => {
            setError(error)
            setExecuting(false)
          },
        }
      )
    } catch (error: any) {
      setError(error.message || '执行失败')
      setExecuting(false)
    }
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
              <div style={{ fontSize: 12, color: '#ff4d4f' }}>{event.error}</div>
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
      <Card>
        <Spin size="large" />
      </Card>
    )
  }

  if (!workflow) {
    return <Result status="404" title="工作流不存在" />
  }

  return (
    <div style={{ padding: 24 }}>
      <Card title={`执行工作流: ${workflow.name}`}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
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
                    onClick={() => {
                      // TODO: 实现取消执行功能
                      message.info('取消功能待实现')
                    }}
                  >
                    取消
                  </Button>
                )}
                <Button style={{ marginLeft: 8 }} onClick={() => navigate(`/workflows/${workflowId}/edit`)}>
                  返回编辑
                </Button>
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