import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Empty, Form, Input, Result, Space, Spin, Tag, Timeline, message } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { getWorkflow, validateWorkflow, executeWorkflowStreamUrl } from '../../api/workflow'
import { createWorkflowStreamRequest } from '../../utils/streamRequest'
import type { SSEWorkflowEvent } from '../../utils/streamRequest'
import type { Workflow } from '../../types/workflow'
import { getErrorMessage } from '../../utils/request'
import RouteHeader from '@/components/Layout/RouteHeader'
import './WorkflowExecution.css'

function formatOutputValue(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

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

  const executionState = executing
    ? { label: '执行中', tone: 'running' }
    : error
      ? { label: '执行失败', tone: 'failed' }
      : finalOutput
        ? { label: '已完成', tone: 'completed' }
        : { label: '待执行', tone: 'ready' }

  const renderTimelineItem = (event: SSEWorkflowEvent) => {
    switch (event.type) {
      case 'execution_started':
        return {
          color: 'blue',
          dot: <PlayCircleOutlined />,
          children: (
            <div className="workflow-event workflow-event--started">
              <div className="workflow-event__title">执行开始</div>
              <div className="workflow-event__meta">运行 ID · {event.execution_id}</div>
            </div>
          ),
        }
      case 'node_started':
        return {
          color: 'gray',
          dot: <LoadingOutlined />,
          children: (
            <div className="workflow-event">
              <div className="workflow-event__title">{event.node_name}</div>
              <div className="workflow-event__meta">节点开始 · {event.node_type}</div>
            </div>
          ),
        }
      case 'node_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: (
            <div className="workflow-event">
              <div className="workflow-event__title">{event.node_name}</div>
              <div className="workflow-event__meta">节点完成</div>
              <div className="workflow-event__output">
                {formatOutputValue(event.output).substring(0, 180)}
              </div>
            </div>
          ),
        }
      case 'node_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: (
            <div className="workflow-event workflow-event--failed">
              <div className="workflow-event__title">{event.node_name}</div>
              <div className="workflow-event__meta">节点失败</div>
              <div className="workflow-event__error">{event.error}</div>
            </div>
          ),
        }
      case 'tool_started':
        return {
          color: 'blue',
          dot: <ToolOutlined />,
          children: (
            <div className="workflow-event">
              <div className="workflow-event__title">调用工具：{event.tool_name}</div>
              <div className="workflow-event__meta">第 {event.round} 轮 · 调用中</div>
            </div>
          ),
        }
      case 'tool_completed':
        return {
          color: event.status === 'success' ? 'green' : 'red',
          dot: event.status === 'success' ? <CheckCircleOutlined /> : <CloseCircleOutlined />,
          children: (
            <div className={`workflow-event${event.status === 'error' ? ' workflow-event--failed' : ''}`}>
              <div className="workflow-event__title">工具返回：{event.tool_name}</div>
              <div className="workflow-event__meta">
                第 {event.round} 轮 · {event.status === 'success' ? '已返回模型' : '调用失败，已反馈模型'}
              </div>
            </div>
          ),
        }
      case 'execution_completed':
        return {
          color: 'green',
          dot: <CheckCircleOutlined />,
          children: <div className="workflow-event__title">执行完成</div>,
        }
      case 'execution_failed':
        return {
          color: 'red',
          dot: <CloseCircleOutlined />,
          children: (
            <div className="workflow-event workflow-event--failed">
              <div className="workflow-event__title">执行失败</div>
              <div className="workflow-event__error">{event.error}</div>
            </div>
          ),
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
      <div className="workflow-execution-page">
        <RouteHeader
          eyebrow="应用开发 / 工作流"
          title="执行工作流"
          backTo="/workflows"
          backLabel="返回工作流列表"
        />
        <Card className="workflow-panel workflow-loading-panel" bordered={false}>
          <Spin size="large" />
        </Card>
      </div>
    )
  }

  if (!workflow) {
    return (
      <div className="workflow-execution-page">
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
    <div className="workflow-execution-page">
      <RouteHeader
        eyebrow="应用开发 / 工作流"
        title={`执行工作流：${workflow.name}`}
        backTo="/workflows"
        backLabel="返回工作流列表"
        description={workflow.status === 'published' ? '实时观测节点进度与最终输出' : '当前工作流尚未发布，暂时无法执行'}
        extra={(
          <Space className="workflow-header-actions" size={12}>
            <Tag color={executionState.tone === 'failed' ? 'error' : executionState.tone === 'completed' ? 'success' : executionState.tone === 'running' ? 'processing' : undefined}>
              {executionState.label}
            </Tag>
            <Button onClick={() => navigate(`/workflows/${workflowId}/edit`)}>
              返回编辑
            </Button>
          </Space>
        )}
      />
      <div className="workflow-execution-grid">
        <main className="workflow-execution-primary">
          <Card className="workflow-panel workflow-input-panel" title="输入参数">
            <Form form={form} layout="vertical" onFinish={handleExecute}>
              <Form.Item
                label="输入数据"
                name="input_data"
                help='请输入 JSON，例如：{"query":"设计一个北京 3 日游的计划"}'
              >
                <Input.TextArea
                  className="workflow-json-input"
                  rows={5}
                  placeholder='{"key": "value"}'
                />
              </Form.Item>
              <div className="workflow-form-actions">
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
                  <Button icon={<StopOutlined />} onClick={handleCancel}>
                    取消执行
                  </Button>
                )}
              </div>
            </Form>
          </Card>

          <Card
            className="workflow-panel workflow-log-panel"
            title="执行日志"
            extra={executionEvents.length ? `${executionEvents.length} 个事件` : '等待运行'}
          >
            {executionEvents.length > 0 ? (
              <div className="workflow-timeline-wrap">
                <Timeline items={executionEvents.map(renderTimelineItem)} />
              </div>
            ) : (
              <Empty
                className="workflow-empty-state"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="运行后将在这里显示节点进度"
              />
            )}
          </Card>
        </main>

        <aside className="workflow-execution-aside">
          <Card
            className="workflow-panel workflow-result-panel"
            title="执行结果"
            extra={finalOutput ? <Tag color="success">已生成</Tag> : undefined}
          >
            {finalOutput ? (
              Object.keys(finalOutput).length > 0 ? (
                <div className="workflow-result-list">
                  {Object.entries(finalOutput).map(([key, value]) => (
                    <div className="workflow-result-row" key={key}>
                      <div className="workflow-result-key">{key}</div>
                      <pre>{formatOutputValue(value)}</pre>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty description="本次运行没有输出变量，请在结束节点中配置输出映射。" />
              )
            ) : (
              <Empty
                description={executing ? '正在等待最终输出' : '执行一次工作流，查看结构化结果。'}
              />
            )}
          </Card>

          <Card className="workflow-panel workflow-summary-panel" title="运行摘要">
            <div className="workflow-stat-grid">
              <div><span>节点</span><strong>{workflow.nodes.length}</strong></div>
              <div><span>连线</span><strong>{workflow.edges.length}</strong></div>
              <div><span>状态</span><strong>{workflow.status === 'published' ? '已发布' : '草稿'}</strong></div>
            </div>
          </Card>

          {error && (
            <Alert
              className="workflow-error-alert"
              type="error"
              title="执行失败"
              description={error}
              showIcon
              icon={<CloseCircleOutlined />}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

export default WorkflowExecution
