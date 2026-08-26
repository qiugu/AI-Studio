import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Typography,
  Descriptions,
  Tag,
  Button,
  Space,
  InputNumber,
  Popconfirm,
  message,
  Spin,
  Statistic,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getTenant,
  updateTenant,
  setTenantQuota,
  deleteTenant,
} from '@/api/admin'
import type { AdminTenant } from '@/types/api'

const { Title } = Typography

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [tenant, setTenant] = useState<AdminTenant | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [maxUsers, setMaxUsers] = useState<number>(10)
  const [maxModels, setMaxModels] = useState<number>(5)

  const fetchDetail = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await getTenant(id)
      const data = res.data ?? null
      setTenant(data)
      setMaxUsers(data?.max_users ?? 10)
      setMaxModels(data?.max_models ?? 5)
    } catch {
      // interceptor
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchDetail()
  }, [fetchDetail])

  const handleSaveQuota = async () => {
    if (!id) return
    setSaving(true)
    try {
      await setTenantQuota(id, { max_users: maxUsers, max_models: maxModels })
      message.success('配额已更新')
      fetchDetail()
    } catch {
      // interceptor
    } finally {
      setSaving(false)
    }
  }

  const handleToggleStatus = async (next: boolean) => {
    if (!id) return
    try {
      await updateTenant(id, { status: next })
      message.success(next ? '已启用' : '已禁用')
      fetchDetail()
    } catch {
      // interceptor
    }
  }

  const handleDelete = async () => {
    if (!id) return
    try {
      await deleteTenant(id)
      message.success('租户已注销')
      navigate('/admin/tenants')
    } catch {
      // interceptor
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => navigate('/admin/tenants')}>返回列表</Button>
      </Space>

      <Spin spinning={loading}>
        <Title level={4}>{tenant?.name}</Title>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card title="基本信息">
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="租户 ID">{tenant?.id}</Descriptions.Item>
                <Descriptions.Item label="描述">{tenant?.description || '—'}</Descriptions.Item>
                <Descriptions.Item label="套餐">
                  <Tag color="blue">{tenant?.plan}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={tenant?.status ? 'success' : 'error'}>
                    {tenant?.status ? '正常' : '已禁用'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="系统初始租户">
                  {tenant?.is_system_init ? '是' : '否'}
                </Descriptions.Item>
              </Descriptions>
              <Space style={{ marginTop: 16 }}>
                <Button onClick={() => handleToggleStatus(!tenant?.status)}>
                  {tenant?.status ? '禁用租户' : '启用租户'}
                </Button>
              </Space>
            </Card>
          </Col>

          <Col xs={24} lg={12}>
            <Card title="配额修改">
              <Space direction="vertical" style={{ width: '100%' }}>
                <Statistic title="当前用户数" value={tenant?.usage?.user_count ?? 0} />
                <Statistic title="当前模型数" value={tenant?.usage?.model_count ?? 0} />
                <div>
                  <div style={{ marginBottom: 4 }}>最大用户数</div>
                  <InputNumber
                    min={1}
                    value={maxUsers}
                    onChange={(v) => setMaxUsers(v ?? 1)}
                    style={{ width: '100%' }}
                  />
                </div>
                <div>
                  <div style={{ marginBottom: 4 }}>最大模型数</div>
                  <InputNumber
                    min={0}
                    value={maxModels}
                    onChange={(v) => setMaxModels(v ?? 0)}
                    style={{ width: '100%' }}
                  />
                </div>
                <Button type="primary" loading={saving} onClick={handleSaveQuota}>
                  保存配额
                </Button>
              </Space>
            </Card>
          </Col>
        </Row>

        <Card title="危险操作" style={{ marginTop: 16 }} bordered={false}>
          <Space>
            <Popconfirm
              title="确认注销该租户？"
              description="将级联软删除其全部业务数据（保留审计与计费数据），此操作不可恢复。"
              onConfirm={handleDelete}
              okText="确认注销"
              okButtonProps={{ danger: true }}
              cancelText="取消"
            >
              <Button danger>注销租户</Button>
            </Popconfirm>
          </Space>
        </Card>
      </Spin>
    </div>
  )
}
