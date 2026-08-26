import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Typography,
  Card,
  Select,
  DatePicker,
  Input,
  message,
} from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { listAuditLogs } from '@/api/audit'
import type { AuditLog } from '@/types/api'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

const ACTION_COLORS: Record<string, string> = {
  POST: 'green',
  PUT: 'blue',
  PATCH: 'gold',
  DELETE: 'red',
}

const RESOURCE_OPTIONS = [
  'ai-models',
  'providers',
  'prompts',
  'knowledge',
  'agent',
  'workflows',
  'users',
  'roles',
  'system',
  'admin',
  'audit',
]

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<{
    action?: string
    resource?: string
    user_id?: string
    range?: [dayjs.Dayjs, dayjs.Dayjs] | null
  }>({ range: null })

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAuditLogs({
        page,
        page_size: 20,
        action: filters.action,
        resource: filters.resource,
        user_id: filters.user_id || undefined,
        start_time: filters.range?.[0]?.toISOString(),
        end_time: filters.range?.[1]?.toISOString(),
      })
      setLogs(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      // interceptor
    } finally {
      setLoading(false)
    }
  }, [page, filters])

  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  const handleExport = () => {
    if (!logs.length) {
      message.warning('暂无数据可导出')
      return
    }
    const header = ['时间', '操作', '资源', '资源ID', '路径', '状态', '用户', '耗时(ms)', 'IP']
    const rows = logs.map((l) => [
      l.created_at ?? '',
      l.action,
      l.resource,
      l.resource_id ?? '',
      l.path,
      String(l.status_code),
      l.user_id ?? '',
      String(l.duration_ms),
      l.ip_address ?? '',
    ])
    const csv = [header, ...rows]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit_logs_${dayjs().format('YYYYMMDD_HHmmss')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const columns: ColumnsType<AuditLog> = useMemo(
    () => [
      {
        title: '时间',
        dataIndex: 'created_at',
        key: 'created_at',
        render: (v) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—'),
      },
      {
        title: '操作',
        dataIndex: 'action',
        key: 'action',
        render: (a: string) => <Tag color={ACTION_COLORS[a] ?? 'default'}>{a}</Tag>,
      },
      { title: '资源', dataIndex: 'resource', key: 'resource' },
      { title: '资源ID', dataIndex: 'resource_id', key: 'resource_id', render: (v) => v || '—' },
      { title: '路径', dataIndex: 'path', key: 'path', ellipsis: true },
      {
        title: '状态',
        dataIndex: 'status_code',
        key: 'status_code',
        render: (s: number) => <Tag color={s < 400 ? 'success' : 'error'}>{s}</Tag>,
      },
      { title: '用户', dataIndex: 'user_id', key: 'user_id', render: (v) => v || '—' },
      { title: '耗时', dataIndex: 'duration_ms', key: 'duration_ms', render: (v) => `${v}ms` },
    ],
    []
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>审计日志</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchLogs}>
            刷新
          </Button>
          <Button icon={<DownloadOutlined />} onClick={handleExport}>
            导出 CSV
          </Button>
        </Space>
      </div>

      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            placeholder="操作类型"
            allowClear
            style={{ width: 140 }}
            options={['POST', 'PUT', 'PATCH', 'DELETE'].map((a) => ({ value: a, label: a }))}
            onChange={(v) => setFilters((f) => ({ ...f, action: v }))}
          />
          <Select
            placeholder="资源"
            allowClear
            showSearch
            style={{ width: 160 }}
            options={RESOURCE_OPTIONS.map((r) => ({ value: r, label: r }))}
            onChange={(v) => setFilters((f) => ({ ...f, resource: v }))}
          />
          <Input
            placeholder="用户 ID"
            style={{ width: 220 }}
            allowClear
            onChange={(e) => setFilters((f) => ({ ...f, user_id: e.target.value }))}
          />
          <RangePicker
            showTime
            onChange={(v) =>
              setFilters((f) => ({ ...f, range: v as [dayjs.Dayjs, dayjs.Dayjs] | null }))
            }
          />
        </Space>

        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          仅记录写操作（POST / PUT / PATCH / DELETE），数据按时间倒序展示。
        </Text>

        <Table
          columns={columns}
          dataSource={logs}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            onChange: (p) => setPage(p),
          }}
        />
      </Card>
    </div>
  )
}
