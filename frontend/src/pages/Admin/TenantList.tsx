import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Modal,
  Form,
  Input,
  Select,
  Typography,
  Card,
  Badge,
} from 'antd'
import { PlusOutlined, EyeOutlined, StopOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import {
  listTenants,
  createTenant,
  updateTenant,
  deleteTenant,
} from '@/api/admin'
import type { AdminTenant, TenantCreateRequest } from '@/types/api'

const { Title } = Typography

export default function TenantList() {
  const navigate = useNavigate()
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listTenants({ page: 1, page_size: 200 })
      setTenants(res.data?.items ?? [])
    } catch {
      // interceptor
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({ plan: 'free', max_users: 10, max_models: 5 })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      await createTenant(values as TenantCreateRequest)
      message.success('租户创建成功')
      setModalOpen(false)
      fetchAll()
    } catch {
      // interceptor
    } finally {
      setSubmitting(false)
    }
  }

  const handleToggleStatus = async (record: AdminTenant, next: boolean) => {
    try {
      await updateTenant(record.id, { status: next })
      message.success(next ? '已启用' : '已禁用')
      fetchAll()
    } catch {
      // interceptor
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteTenant(id)
      message.success('租户已注销')
      fetchAll()
    } catch {
      // interceptor
    }
  }

  const columns: ColumnsType<AdminTenant> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '套餐',
      dataIndex: 'plan',
      key: 'plan',
      render: (p: string) => <Tag color="blue">{p}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: boolean) => <Badge status={s ? 'success' : 'error'} text={s ? '正常' : '已禁用'} />,
    },
    {
      title: '用量',
      key: 'usage',
      render: (_, r) => (
        <Space size={4}>
          <Tag>用户 {r.usage?.user_count ?? 0}</Tag>
          <Tag>模型 {r.usage?.model_count ?? 0}</Tag>
          <Tag>Agent {r.usage?.agent_count ?? 0}</Tag>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/admin/tenants/${record.id}`)} />
          <Button
            size="small"
            icon={<StopOutlined />}
            onClick={() => handleToggleStatus(record, !record.status)}
          >
            {record.status ? '禁用' : '启用'}
          </Button>
          <Popconfirm
            title="确认注销该租户？将级联软删除其全部业务数据。"
            onConfirm={() => handleDelete(record.id)}
            okText="注销"
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
        <Title level={4} style={{ margin: 0 }}>租户管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建租户
        </Button>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={tenants}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title="新建租户"
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="租户名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 Acme 公司" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="plan" label="套餐" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'free', label: 'free' },
                { value: 'pro', label: 'pro' },
                { value: 'enterprise', label: 'enterprise' },
              ]}
            />
          </Form.Item>
          <Space>
            <Form.Item name="max_users" label="最大用户数" rules={[{ required: true }]}>
              <Input type="number" style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="max_models" label="最大模型数" rules={[{ required: true }]}>
              <Input type="number" style={{ width: 130 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
