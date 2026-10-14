/**
 * Agent列表页面
 */

import { useState, useEffect, useCallback } from 'react'
import { Card, Button, Space, Popconfirm, Spin, Empty, Tag, Select, Tooltip, message } from 'antd'
import { DeleteOutlined, EditOutlined, RobotOutlined, MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as agentApi from '@/api/agent'
import { type Agent, type AgentStatus } from '@/types/agent'
import Pagination from '@/components/Pagination'
import { summarizeBoundTools } from './agentToolBinding'
import { usePermission } from '@/hooks/usePermission'

export default function AgentList() {
  const navigate = useNavigate()
  const { check } = usePermission()
  const canCreate = check('agent', 'create')
  const canUpdate = check('agent', 'update')
  const canDelete = check('agent', 'delete')
  const canChat = check('agent', 'chat')
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<AgentStatus | undefined>()

  const loadAgents = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await agentApi.listAgents(page, pageSize, statusFilter)
      setAgents(data.items)
      setTotal(data.total)
    } catch (error) {
      console.error('Failed to load agents:', error)
      message.error('加载Agent列表失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter])

  useEffect(() => {
    // 首屏列表加载属于与远端 API 的同步；状态更新发生在请求完成后。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAgents()
  }, [loadAgents])

  const handleDeleteAgent = async (agentId: string) => {
    try {
      await agentApi.deleteAgent(agentId)
      message.success('Agent已删除')
      loadAgents()
    } catch (error) {
      console.error('Failed to delete agent:', error)
      message.error('删除Agent失败')
    }
  }

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const getStatusColor = (status: AgentStatus) => {
    switch (status) {
      case 'published':
        return 'green'
      case 'draft':
        return 'orange'
      case 'archived':
        return 'default'
      default:
        return 'default'
    }
  }

  const canAct = (agent: Agent, action: string, fallback: boolean) =>
    agent.allowed_actions ? agent.allowed_actions.includes(action) : fallback

  return (
    <>
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between' }}>
        <h2>Agent管理</h2>
        <Space>
          {canUpdate && <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 120 }}
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
          >
            <Select.Option value="draft">草稿</Select.Option>
            <Select.Option value="published">已发布</Select.Option>
            <Select.Option value="archived">已归档</Select.Option>
          </Select>}
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/create')}>
              创建Agent
            </Button>
          )}
        </Space>
      </div>

      <Spin spinning={loading}>
        {agents.length === 0 ? (
          <Empty description="暂无Agent" />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
            {agents.map((agent) => (
              <Card
                key={agent.id}
                hoverable
                actions={[
                  ...(canAct(agent, 'chat', canChat)
                    ? [<MessageOutlined key="chat" onClick={() => navigate(`/agents/${agent.id}/chat`)} />]
                    : []),
                  ...((canAct(agent, 'update', canUpdate) || canAct(agent, 'delete', canDelete))
                    ? [
                        ...(canAct(agent, 'update', canUpdate)
                          ? [<EditOutlined key="edit" onClick={() => navigate(`/agents/${agent.id}/edit`)} />]
                          : []),
                        ...(canAct(agent, 'delete', canDelete)
                          ? [
                              <Popconfirm
                                key="delete"
                                title="确定删除该Agent吗？"
                                onConfirm={() => handleDeleteAgent(agent.id)}
                                okText="确定"
                                cancelText="取消"
                              >
                                <DeleteOutlined />
                              </Popconfirm>,
                            ]
                          : []),
                      ]
                    : []),
                ]}
              >
                <Card.Meta
                  avatar={<RobotOutlined style={{ fontSize: '32px', color: 'var(--app-color-primary)' }} />}
                  title={agent.name}
                  description={
                    <div>
                      <div style={{ marginBottom: '8px' }}>{agent.description || '暂无描述'}</div>
                      <Tag color={getStatusColor(agent.status)}>{agent.status}</Tag>
                      {agent.tools && agent.tools.length > 0 && (
                        <Tooltip
                          title={
                            <div>
                              {summarizeBoundTools(agent.tools).map((item, index) => (
                                <div key={`${item.plugin}${item.action}${index}`}>
                                  {item.plugin}
                                  {item.action ? ` → ${item.action}` : ''}
                                </div>
                              ))}
                            </div>
                          }
                        >
                          <Tag color="blue">{agent.tools.length}个工具</Tag>
                        </Tooltip>
                      )}
                    </div>
                  }
                />
              </Card>
            ))}
          </div>
        )}
      </Spin>

      <Pagination
        current={page}
        pageSize={pageSize}
        total={total}
        onChange={handlePageChange}
      />
    </>
  )
}
