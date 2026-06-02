import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Switch,
  Popconfirm,
  message,
  Select,
  Typography,
  Badge,
  Tooltip,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listModels, deleteModel, listProviders } from '@/api/ai-model'
import type { AIModel, AIProvider, ModelType } from '@/types/ai-model'

const { Title } = Typography

const MODEL_TYPE_COLORS: Record<ModelType, string> = {
  chat: 'blue',
  embedding: 'green',
  image: 'purple',
  audio: 'orange',
  rerank: 'cyan',
}

export default function ModelList() {
  const navigate = useNavigate()
  const [models, setModels] = useState<AIModel[]>([])
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<{
    model_type?: string
    provider_id?: number
    include_public: boolean
  }>({ include_public: false })

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [modelsRes, providersRes] = await Promise.all([
        listModels({ page: 1, page_size: 200, ...filters }),
        listProviders({ page: 1, page_size: 100 }),
      ])
      setModels(modelsRes.data?.items ?? [])
      setProviders(providersRes.data?.items ?? [])
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
      await deleteModel(id)
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const providerMap = Object.fromEntries(providers.map((p) => [p.id, p.name]))

  const columns: ColumnsType<AIModel> = [
    {
      title: '模型标识',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space>
          <span>{name}</span>
          {record.tenant_id === null && <Tag color="gold">公共</Tag>}
        </Space>
      ),
    },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '类型',
      dataIndex: 'model_type',
      key: 'model_type',
      render: (type: ModelType) => (
        <Tag color={MODEL_TYPE_COLORS[type] ?? 'default'}>{type}</Tag>
      ),
    },
    {
      title: '供应商',
      dataIndex: 'provider_id',
      key: 'provider_id',
      render: (id) => providerMap[id] ?? `Provider #${id}`,
    },
    {
      title: '输入价格',
      dataIndex: 'unit_price_input',
      key: 'unit_price_input',
      render: (price) => (price ? `$${price}/1K` : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status) => (
        <Badge status={status ? 'success' : 'default'} text={status ? '启用' : '禁用'} />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => {
        const isPublic = record.tenant_id === null
        return (
          <Space>
            <Tooltip title={isPublic ? '公共模型不可编辑' : '编辑'}>
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={isPublic}
                onClick={() => navigate(`/ai-models/${record.id}/edit`)}
              />
            </Tooltip>
            <Popconfirm
              title="确认删除此模型？"
              onConfirm={() => handleDelete(record.id)}
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              disabled={isPublic}
            >
              <Tooltip title={isPublic ? '公共模型不可删除' : '删除'}>
                <Button
                  size="small"
                  icon={<DeleteOutlined />}
                  danger
                  disabled={isPublic}
                />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>AI 模型管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/ai-models/new')}
        >
          新增模型
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选类型"
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'chat', label: '对话' },
            { value: 'embedding', label: 'Embedding' },
            { value: 'image', label: '图像' },
            { value: 'audio', label: '音频' },
            { value: 'rerank', label: 'Rerank' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, model_type: v }))}
        />
        <Select
          placeholder="筛选供应商"
          allowClear
          style={{ width: 180 }}
          options={providers.map((p) => ({ value: p.id, label: p.name }))}
          onChange={(v) => setFilters((f) => ({ ...f, provider_id: v }))}
        />
        <Space>
          <span>显示公共模型</span>
          <Switch
            checked={filters.include_public}
            onChange={(v) => setFilters((f) => ({ ...f, include_public: v }))}
          />
        </Space>
      </Space>

      <Table
        columns={columns}
        dataSource={models}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </div>
  )
}
