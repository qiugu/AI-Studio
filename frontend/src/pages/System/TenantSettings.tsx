import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Typography,
  Descriptions,
  Progress,
  Button,
  Modal,
  Form,
  Input,
  message,
  Table,
  Tag,
  Spin,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getTenantSettings, updateTenantSettings } from '@/api/system'
import { listUsers } from '@/api/user'
import type { TenantSettings, User } from '@/types/api'

const { Title } = Typography

export default function TenantSettings() {
  const [settings, setSettings] = useState<TenantSettings | null>(null)
  const [members, setMembers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [settingsRes, membersRes] = await Promise.all([
        getTenantSettings(),
        listUsers({ page: 1, page_size: 200 }),
      ])
      setSettings(settingsRes.data ?? null)
      setMembers(membersRes.data?.items ?? [])
    } catch {
      // interceptor
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const openEdit = () => {
    form.resetFields()
    form.setFieldsValue({
      name: settings?.name,
      description: settings?.description ?? '',
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      await updateTenantSettings(values)
      message.success('保存成功')
      setModalOpen(false)
      fetchAll()
    } catch {
      // interceptor
    } finally {
      setSubmitting(false)
    }
  }

  const usage = settings?.usage
  const memberColumns: ColumnsType<User> = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '昵称', dataIndex: 'nickname', key: 'nickname', render: (v) => v || '—' },
    {
      title: '角色',
      dataIndex: 'roles',
      key: 'roles',
      render: (rs: User['roles']) =>
        rs.length ? rs.map((r) => <Tag key={r.id}>{r.name}</Tag>) : <Tag>无</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: boolean) => <Tag color={s ? 'success' : 'default'}>{s ? '启用' : '禁用'}</Tag>,
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>租户设置</Title>
      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              title="基本信息"
              extra={
                <Button type="link" onClick={openEdit}>
                  编辑
                </Button>
              }
            >
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="租户名称">{settings?.name}</Descriptions.Item>
                <Descriptions.Item label="描述">{settings?.description || '—'}</Descriptions.Item>
                <Descriptions.Item label="套餐">
                  <Tag color="blue">{settings?.plan}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={settings?.status ? 'success' : 'error'}>
                    {settings?.status ? '正常' : '已禁用'}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="配额使用情况">
              <div style={{ marginBottom: 16 }}>
                <div style={{ marginBottom: 4 }}>
                  用户数：{usage?.user_count ?? 0} / {settings?.max_users}
                </div>
                <Progress
                  percent={
                    settings?.max_users
                      ? Math.round(((usage?.user_count ?? 0) / settings.max_users) * 100)
                      : 0
                  }
                />
              </div>
              <div style={{ marginBottom: 16 }}>
                <div style={{ marginBottom: 4 }}>
                  模型数：{usage?.model_count ?? 0} / {settings?.max_models}
                </div>
                <Progress
                  percent={
                    settings?.max_models
                      ? Math.round(((usage?.model_count ?? 0) / settings.max_models) * 100)
                      : 0
                  }
                  strokeColor="#52c41a"
                />
              </div>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="Agent 数">{usage?.agent_count ?? 0}</Descriptions.Item>
                <Descriptions.Item label="知识库数">
                  {usage?.knowledge_base_count ?? 0}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        </Row>

        <Card title="成员列表" style={{ marginTop: 16 }}>
          <Table
            columns={memberColumns}
            dataSource={members}
            rowKey="id"
            pagination={{ pageSize: 20 }}
          />
        </Card>
      </Spin>

      <Modal
        title="编辑租户信息"
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="租户名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
