import React, { useState, useEffect } from 'react'
import { Table, Button, Space, Tag, message, Popconfirm, Card } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, PlayCircleOutlined, CheckOutlined, InboxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listWorkflows, deleteWorkflow, publishWorkflow, archiveWorkflow } from '../../api/workflow'
import type { Workflow, WorkflowStatus } from '../../types/workflow'
import { usePagination } from '../../hooks/usePagination'

const WorkflowList: React.FC = () => {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | undefined>()
  const { data, loading, setData, setLoading, onChange, total, current, pageSize } = usePagination<Workflow>()

  const fetchWorkflows = async () => {
    setLoading(true)
    try {
      const result = await listWorkflows({
        page: current,
        page_size: pageSize,
        status: statusFilter,
      })
      setData(result.data)
    } catch (error) {
      message.error('获取工作流列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchWorkflows()
  }, [current, pageSize, statusFilter])

  const handleDelete = async (workflowId: string) => {
    try {
      await deleteWorkflow(workflowId)
      message.success('工作流已删除')
      fetchWorkflows()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handlePublish = async (workflowId: string) => {
    try {
      await publishWorkflow(workflowId)
      message.success('工作流已发布')
      fetchWorkflows()
    } catch (error) {
      message.error('发布失败')
    }
  }

  const handleArchive = async (workflowId: string) => {
    try {
      await archiveWorkflow(workflowId)
      message.success('工作流已归档')
      fetchWorkflows()
    } catch (error) {
      message.error('归档失败')
    }
  }

  const getStatusTag = (status: WorkflowStatus) => {
    const statusConfig = {
      draft: { color: 'default', text: '草稿' },
      published: { color: 'success', text: '已发布' },
      archived: { color: 'warning', text: '已归档' },
    }
    const config = statusConfig[status]
    return <Tag color={config.color}>{config.text}</Tag>
  }

  const columns: ColumnsType<Workflow> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 300,
      ellipsis: true,
    },
    {
      title: '节点数',
      dataIndex: 'nodes',
      key: 'nodes',
      width: 100,
      render: (nodes: any[]) => nodes?.length || 0,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: WorkflowStatus) => getStatusTag(status),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (time: string) => new Date(time).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/workflows/${record.id}/edit`)}
          >
            编辑
          </Button>
          {record.status === 'draft' && (
            <Button
              type="link"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handlePublish(record.id)}
            >
              发布
            </Button>
          )}
          {record.status === 'published' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => navigate(`/workflows/${record.id}/execute`)}
              >
                执行
              </Button>
              <Button
                type="link"
                size="small"
                icon={<InboxOutlined />}
                onClick={() => handleArchive(record.id)}
              >
                归档
              </Button>
            </>
          )}
          <Popconfirm
            title="确定删除此工作流吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="工作流列表"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/workflows/create')}
        >
          创建工作流
        </Button>
      }
    >
      <Space style={{ marginBottom: 16 }}>
        <span>状态筛选：</span>
        <Button
          type={statusFilter === undefined ? 'primary' : 'default'}
          onClick={() => setStatusFilter(undefined)}
        >
          全部
        </Button>
        <Button
          type={statusFilter === 'draft' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('draft')}
        >
          草稿
        </Button>
        <Button
          type={statusFilter === 'published' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('published')}
        >
          已发布
        </Button>
        <Button
          type={statusFilter === 'archived' ? 'primary' : 'default'}
          onClick={() => setStatusFilter('archived')}
        >
          已归档
        </Button>
      </Space>

      <Table
        columns={columns}
        dataSource={data?.items || []}
        rowKey="id"
        loading={loading}
        pagination={{
          current: current,
          pageSize,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          onChange: onChange,
        }}
      />
    </Card>
  )
}

export default WorkflowList