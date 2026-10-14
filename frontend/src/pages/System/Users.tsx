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
  Switch,
  Typography,
  Card,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  listUsers,
  createUser,
  updateUser,
  deleteUser,
} from '@/api/user'
import { listRoles } from '@/api/role'
import type { User, Role } from '@/types/api'

const { Title } = Typography

function askCurrentPassword(title: string): Promise<string | null> {
  return new Promise((resolve) => {
    let password = ''
    Modal.confirm({
      title,
      content: (
        <Input.Password
          autoFocus
          placeholder="请输入当前登录密码"
          onChange={(event) => { password = event.target.value }}
        />
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: () => resolve(password || null),
      onCancel: () => resolve(null),
    })
  })
}

export default function Users() {
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [usersRes, rolesRes] = await Promise.all([
        listUsers({ page: 1, page_size: 200, search: search || undefined }),
        listRoles({ page: 1, page_size: 200 }),
      ])
      setUsers(usersRes.data?.items ?? [])
      setRoles(rolesRes.data?.items ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    void Promise.resolve().then(() => fetchAll())
  }, [fetchAll])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ status: true })
    setModalOpen(true)
  }

  const openEdit = (record: User) => {
    setEditing(record)
    form.resetFields()
    form.setFieldsValue({
      email: record.email,
      status: record.status,
      role_ids: record.roles.map((r) => r.id),
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (editing) {
        const rest = { ...values }
        delete rest.email
        const currentRoleIds = editing.roles.map((r) => r.id).sort()
        const nextRoleIds = [...(values.role_ids ?? [])].sort()
        const roleChanged = JSON.stringify(currentRoleIds) !== JSON.stringify(nextRoleIds)
        if (editing.status !== values.status || roleChanged) {
          const currentPassword = await askCurrentPassword('修改成员状态或角色需要验证当前密码')
          if (!currentPassword) return
          rest.current_password = currentPassword
        }
        await updateUser(editing.id, rest)
        message.success('更新成功')
      } else {
        await createUser(values)
        message.success('创建成功')
      }
      setModalOpen(false)
      fetchAll()
    } catch {
      // interceptor handles error toast; 表单校验错误不会进入 catch
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    const currentPassword = await askCurrentPassword('删除成员需要验证当前密码')
    if (!currentPassword) return
    try {
      await deleteUser(id, currentPassword)
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleToggleStatus = async (record: User, checked: boolean) => {
    const currentPassword = await askCurrentPassword('修改成员状态需要验证当前密码')
    if (!currentPassword) return
    try {
      await updateUser(record.id, { status: checked, current_password: currentPassword })
      message.success('状态已更新')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const columns: ColumnsType<User> = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '昵称', dataIndex: 'nickname', key: 'nickname', render: (v) => v || '—' },
    {
      title: '角色',
      dataIndex: 'roles',
      key: 'roles',
      render: (rs: Role[]) =>
        rs.length ? rs.map((r) => <Tag key={r.id}>{r.name}</Tag>) : <Tag>无</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: boolean, record) => (
        <Switch
          checked={status}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          onChange={(v) => handleToggleStatus(record, v)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v) => (v ? new Date(v).toLocaleString() : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            aria-label="编辑"
            title="编辑资料"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          />
          <Popconfirm
            title="确认删除该用户？"
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
        <Title level={4} style={{ margin: 0 }}>用户管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增用户
        </Button>
      </div>

      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索邮箱 / 昵称"
            allowClear
            onSearch={(v) => setSearch(v)}
            style={{ width: 260 }}
          />
        </Space>
        <Table
          columns={columns}
          dataSource={users}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title={editing ? '编辑用户' : '新增用户'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input disabled={!!editing} placeholder="user@example.com" />
          </Form.Item>
          {!editing && (
            <Form.Item name="nickname" label="昵称">
              <Input placeholder="可选" />
            </Form.Item>
          )}
          {!editing && (
            <Form.Item
              name="password"
              label="初始密码"
              rules={[{ required: true, message: '请输入初始密码' }]}
            >
              <Input.Password placeholder="仅用于创建账号" />
            </Form.Item>
          )}
          <Form.Item name="role_ids" label={editing ? '角色' : '初始角色'}>
            <Select
              mode="multiple"
              placeholder={editing ? '选择角色' : '选择角色（可选）'}
              options={roles.map((r) => ({ value: r.id, label: r.name }))}
            />
          </Form.Item>
          <Form.Item name="status" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
