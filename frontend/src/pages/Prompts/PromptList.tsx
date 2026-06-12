import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Select,
  Typography,
  Badge,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listPrompts, deletePrompt } from '@/api/prompt'
import type { Prompt, PromptStatus } from '@/types/prompt'

const { Title } = Typography

const STATUS_COLORS: Record<PromptStatus, string> = {
  draft: 'default',
  published: 'success',
  archived: 'warning',
}

const STATUS_LABELS: Record<PromptStatus, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

export default function PromptList() {
  const navigate = useNavigate()
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<{ category?: string; status?: string }>({})

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listPrompts({ page: 1, page_size: 100, ...filters })
      setPrompts(res.data?.items ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const handleDelete = async (id: number) => {
    try {
      await deletePrompt(id)
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const columns: ColumnsType<Prompt> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      render: (cat) => cat ? <Tag>{cat}</Tag> : '—',
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[] | null) =>
        tags?.length ? tags.map((t) => <Tag key={t}>{t}</Tag>) : '—',
    },
    {
      title: '变量',
      key: 'variables',
      render: (_, record) => {
        const vars = record.current_version?.variables ?? []
        return vars.length ? vars.map((v) => <Tag color="blue" key={v}>{`{{${v}}}`}</Tag>) : '—'
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: PromptStatus) => (
        <Badge status={STATUS_COLORS[status] as any} text={STATUS_LABELS[status]} />
      ),
    },
    {
      title: '版本',
      key: 'version',
      render: (_, record) =>
        record.current_version ? `v${record.current_version.version_number}` : '—',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/prompts/${record.id}`)}
          />
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/prompts/${record.id}/edit`)}
          />
          <Popconfirm
            title="确认删除此 Prompt？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
          >
            <Button size="small" icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>Prompt 管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/prompts/new')}
        >
          新建 Prompt
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选分类"
          allowClear
          style={{ width: 160 }}
          options={[
            { value: 'system', label: '系统提示' },
            { value: 'user', label: '用户指令' },
            { value: 'few-shot', label: 'Few-shot' },
            { value: 'chain', label: '链式调用' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, category: v }))}
        />
        <Select
          placeholder="筛选状态"
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'draft', label: '草稿' },
            { value: 'published', label: '已发布' },
            { value: 'archived', label: '已归档' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
        />
      </Space>

      <Table
        columns={columns}
        dataSource={prompts}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </div>
  )
}
