import { useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Button,
  Badge,
  Typography,
  Space,
  Popconfirm,
  message,
  Empty,
  Spin,
  Tag,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listProviders, deleteProvider } from '@/api/ai-model'
import type { AIProvider } from '@/types/ai-model'
import ConnectionTestModal from './ConnectionTestModal'

const { Title, Text } = Typography

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  azure: 'Azure OpenAI',
  zhipu: '智谱 AI',
  baichuan: '百川 AI',
  ollama: 'Ollama',
  custom: '自定义',
}

export default function ProviderList() {
  const navigate = useNavigate()
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [testModal, setTestModal] = useState<{ open: boolean; providerId: number }>({
    open: false,
    providerId: 0,
  })

  const fetchProviders = async () => {
    setLoading(true)
    try {
      const res = await listProviders({ page: 1, page_size: 100 })
      setProviders(res.data?.items ?? [])
    } catch {
      message.error('加载供应商列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProviders()
  }, [])

  const handleDelete = async (id: number) => {
    try {
      await deleteProvider(id)
      message.success('删除成功')
      fetchProviders()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || '删除失败')
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>AI 供应商管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/providers/new')}
        >
          新增供应商
        </Button>
      </div>

      {providers.length === 0 ? (
        <Empty description="暂无供应商，点击右上角添加" />
      ) : (
        <Row gutter={[16, 16]}>
          {providers.map((provider) => (
            <Col key={provider.id} xs={24} sm={12} lg={8} xl={6}>
              <Card
                hoverable
                actions={[
                  <ThunderboltOutlined
                    key="test"
                    title="连接测试"
                    onClick={() => setTestModal({ open: true, providerId: provider.id })}
                  />,
                  <EditOutlined
                    key="edit"
                    title="编辑"
                    onClick={() => navigate(`/providers/${provider.id}/edit`)}
                  />,
                  <Popconfirm
                    key="delete"
                    title="确认删除此供应商？"
                    description="删除后该供应商下的模型将无法使用"
                    onConfirm={() => handleDelete(provider.id)}
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                  >
                    <DeleteOutlined title="删除" style={{ color: '#ff4d4f' }} />
                  </Popconfirm>,
                ]}
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text strong style={{ fontSize: 16 }}>{provider.name}</Text>
                    <Badge
                      status={provider.status ? 'success' : 'default'}
                      text={provider.status ? '启用' : '禁用'}
                    />
                  </div>
                  <Tag color="blue">{PROVIDER_LABELS[provider.provider_type] ?? provider.provider_type}</Tag>
                  {provider.api_base_url && (
                    <Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                      {provider.api_base_url}
                    </Text>
                  )}
                  <Text type={provider.has_api_key ? 'success' : 'warning'} style={{ fontSize: 12 }}>
                    {provider.has_api_key ? 'API Key 已配置' : 'API Key 未配置'}
                  </Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <ConnectionTestModal
        open={testModal.open}
        providerId={testModal.providerId}
        onClose={() => setTestModal({ open: false, providerId: 0 })}
      />
    </div>
  )
}
