/**
 * Agent列表页面
 */

import { useState, useEffect } from 'react'
import { Card, Button, Space, Popconfirm, Spin, Empty, Tag, Select, message } from 'antd'
import { DeleteOutlined, EditOutlined, RobotOutlined, MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as agentApi from '@/api/agent'
import { type Agent, type AgentStatus } from '@/types/agent'
import Pagination from '@/components/Pagination'

export default function AgentList() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<AgentStatus | undefined>()

  useEffect(() => {
    loadAgents()
  }, [page, pageSize, statusFilter])

  const loadAgents = async () => {
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
  }

  const handleDeleteAgent = async (agentId: number) => {
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

  return (
    <>
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between' }}>
        <h2>Agent管理</h2>
        <Space>
          <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 120 }}
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
          >
            <Select.Option value="draft">草稿</Select.Option>
            <Select.Option value="published">已发布</Select.Option>
            <Select.Option value="archived">已归档</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/create')}>
            创建Agent
          </Button>
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
                  <MessageOutlined key="chat" onClick={() => navigate(`/agents/${agent.id}/chat`)} />,
                  <EditOutlined key="edit" onClick={() => navigate(`/agents/${agent.id}/edit`)} />,
                  <Popconfirm
                    key="delete"
                    title="确定删除该Agent吗？"
                    onConfirm={() => handleDeleteAgent(agent.id)}
                    okText="确定"
                    cancelText="取消"
                  >
                    <DeleteOutlined />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  avatar={<RobotOutlined style={{ fontSize: '32px', color: '#1890ff' }} />}
                  title={agent.name}
                  description={
                    <div>
                      <div style={{ marginBottom: '8px' }}>{agent.description || '暂无描述'}</div>
                      <Tag color={getStatusColor(agent.status)}>{agent.status}</Tag>
                      {agent.tools && agent.tools.length > 0 && (
                        <Tag color="blue">{agent.tools.length}个工具</Tag>
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