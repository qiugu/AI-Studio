import { useCallback, useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Typography, Spin, Space, Button } from 'antd'
import {
  TeamOutlined,
  ThunderboltOutlined,
  FundOutlined,
  ApiOutlined,
  BarChartOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { LineChart, BarChart } from '@/components/Charts'
import { getDashboard } from '@/api/audit'
import type { DashboardStats } from '@/types/api'
import { useAuthStore } from '@/stores/auth'

const { Title, Text } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<DashboardStats | null>(null)

  const fetchDashboard = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getDashboard()
      setStats(res.data ?? null)
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
  }, [fetchDashboard])

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        欢迎回来，{user?.nickname || user?.email || '用户'} 👋
      </Title>

      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic
                title="活跃用户"
                value={stats?.active_users ?? 0}
                prefix={<TeamOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic
                title="Agent 数"
                value={stats?.total_agents ?? 0}
                prefix={<ThunderboltOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic
                title="近 30 天 Token 消耗"
                value={stats?.total_tokens_30d ?? 0}
                prefix={<FundOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic
                title="近 30 天调用次数"
                value={stats?.total_calls_30d ?? 0}
                prefix={<ApiOutlined />}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={14}>
            <Card title="Token 消耗趋势（近 30 天）">
              <LineChart data={stats?.token_trend ?? []} valueKey="total_tokens" />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="Top 模型 Token 消耗">
              <BarChart data={stats?.top_models ?? []} valueKey="total_tokens" labelKey="key" />
            </Card>
          </Col>
        </Row>

        <Card title="快捷入口" style={{ marginTop: 16 }}>
          <Space wrap>
            <Button icon={<ThunderboltOutlined />} onClick={() => navigate('/agents')}>
              我的 Agent
            </Button>
            <Button icon={<BarChartOutlined />} onClick={() => navigate('/system/audit-logs')}>
              审计日志
            </Button>
            <Button icon={<TeamOutlined />} onClick={() => navigate('/system/users')}>
              用户管理
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => navigate('/knowledge')}>
              知识库
            </Button>
          </Space>
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">
              审计与监控数据每 30 天为一个统计周期，可在「系统管理 → 审计日志」中查看完整明细。
            </Text>
          </div>
        </Card>
      </Spin>
    </div>
  )
}
