import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Modal,
  Drawer,
  Form,
  Input,
  Checkbox,
  Typography,
  Card,
  Badge,
  Spin,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SafetyOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { listRoles, createRole, updateRole, deleteRole, listPermissions, setRolePermissions } from '@/api/role'
import type { Role, Permission } from '@/types/api'

const { Title } = Typography

export default function Roles() {
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Role | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  // 权限矩阵抽屉
  const [permDrawer, setPermDrawer] = useState<{ open: boolean; role: Role | null }>({
    open: false,
    role: null,
  })
  const [checkedPerms, setCheckedPerms] = useState<string[]>([])
  const [savingPerms, setSavingPerms] = useState(false)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [rolesRes, permsRes] = await Promise.all([
        listRoles({ page: 1, page_size: 200 }),
        listPermissions(),
      ])
      setRoles(rolesRes.data?.items ?? [])
      setPermissions(permsRes.data ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ status: true })
    setModalOpen(true)
  }

  const openEdit = (record: Role) => {
    setEditing(record)
    form.resetFields()
    form.setFieldsValue({ name: record.name, description: record.description, status: record.status })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (editing) {
        await updateRole(editing.id, values)
        message.success('更新成功')
      } else {
        await createRole(values)
        message.success('创建成功')
      }
      setModalOpen(false)
      fetchAll()
    } catch {
      // interceptor
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (record: Role) => {
    if (record.code.startsWith('tenant_admin')) {
      message.error('内置管理员角色不可删除')
      return
    }
    try {
      await deleteRole(record.id)
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor
    }
  }

  const openPermMatrix = (record: Role) => {
    setPermDrawer({ open: true, role: record })
    setCheckedPerms(record.permissions.map((p) => p.id))
  }

  const handleSavePerms = async () => {
    if (!permDrawer.role) return
    setSavingPerms(true)
    try {
      await setRolePermissions(permDrawer.role.id, { permission_ids: checkedPerms })
      message.success('权限已保存')
      setPermDrawer({ open: false, role: null })
      fetchAll()
    } catch {
      // interceptor
    } finally {
      setSavingPerms(false)
    }
  }

  // 按 resource 分组权限
  const groupedPerms = permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    ;(acc[p.resource] ||= []).push(p)
    return acc
  }, {})

  const columns: ColumnsType<Role> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '编码', dataIndex: 'code', key: 'code', render: (v) => <Tag>{v}</Tag> },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v) => v || '—' },
    {
      title: '权限数',
      dataIndex: 'permissions',
      key: 'permissions',
      render: (ps: Permission[]) => <Badge count={ps.length} showZero color="#1677ff" />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: boolean) => <Badge status={s ? 'success' : 'default'} text={s ? '启用' : '禁用'} />,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Button
            size="small"
            icon={<SafetyOutlined />}
            onClick={() => openPermMatrix(record)}
          />
          <Popconfirm
            title="确认删除该角色？"
            onConfirm={() => handleDelete(record)}
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
        <Title level={4} style={{ margin: 0 }}>角色权限</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增角色
        </Button>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={roles}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title={editing ? '编辑角色' : '新增角色'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 运营人员" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <Form.Item name="status" label="状态" valuePropName="checked">
            <Checkbox>启用</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={`权限矩阵 - ${permDrawer.role?.name ?? ''}`}
        width={460}
        open={permDrawer.open}
        onClose={() => setPermDrawer({ open: false, role: null })}
        extra={
          <Button type="primary" loading={savingPerms} onClick={handleSavePerms}>
            保存
          </Button>
        }
      >
        <Spin spinning={loading}>
          {Object.entries(groupedPerms).map(([resource, perms]) => (
            <div key={resource} style={{ marginBottom: 20 }}>
              <Typography.Text strong>{resource}</Typography.Text>
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {perms.map((p) => (
                  <Checkbox
                    key={p.id}
                    checked={checkedPerms.includes(p.id)}
                    onChange={(e) => {
                      setCheckedPerms((prev) =>
                        e.target.checked
                          ? [...prev, p.id]
                          : prev.filter((id) => id !== p.id)
                      )
                    }}
                  >
                    {p.action}
                    {p.description ? `（${p.description}）` : ''}
                  </Checkbox>
                ))}
              </div>
            </div>
          ))}
        </Spin>
      </Drawer>
    </div>
  )
}
