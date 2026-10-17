import { useCallback, useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Typography, Spin, Space, Button, List, Tag, Progress } from 'antd'
import {
  TeamOutlined,
  ThunderboltOutlined,
  FundOutlined,
  ApiOutlined,
  ToolOutlined,
  BarChartOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { LineChart, BarChart } from '@/components/Charts'
import { getDashboard } from '@/api/audit'
import type { DashboardStats } from '@/types/api'
import { useAuthStore } from '@/stores/auth'
import { canManageSystem } from '@/utils/permission'
import './Dashboard.css'

const { Title, Text } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  // 普通租户成员不展示「审计日志 / 用户管理」快捷入口，与侧边栏系统管理可见性保持一致
  const canManage = canManageSystem(user)
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
    void Promise.resolve().then(() => fetchDashboard())
  }, [fetchDashboard])

  return (
    <div className="dashboard-shell">
      <header className="dashboard-hero">
        <div>
          <span className="dashboard-hero__eyebrow">AI STUDIO / OPERATIONS</span>
          <Title level={2}>欢迎回来，{user?.nickname || user?.email || '用户'}</Title>
          <p>把 Agent 的推理、工具与知识调用，收束到一个可读、可追踪的运行面板。</p>
        </div>
        <div className="dashboard-hero__status"><span /> 近 30 天运行窗口</div>
      </header>

      <Spin spinning={loading}>
        <Row gutter={[16, 16]} className="dashboard-metrics">
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
          <Col xs={24} sm={12} lg={6}>
            <Card className="dashboard-metric dashboard-metric--tool">
              <Statistic
                title="工具调用次数"
                value={stats?.tool_calls_30d ?? 0}
                prefix={<ToolOutlined />}
              />
              <span className="dashboard-metric__caption">Agent 执行轨迹</span>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} className="dashboard-charts">
          <Col xs={24} lg={14}>
            <Card title="Token 消耗趋势" extra={<span className="dashboard-card-kicker">MODEL USAGE</span>}>
              <LineChart data={stats?.token_trend ?? []} valueKey="total_tokens" />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="Top 模型 Token 消耗" extra={<span className="dashboard-card-kicker">TOP MODELS</span>}>
              <BarChart data={stats?.top_models ?? []} valueKey="total_tokens" labelKey="key" />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} className="dashboard-tools">
          <Col xs={24} lg={10}>
            <Card className="dashboard-tool-health" title="工具健康度" extra={<span className="dashboard-card-kicker">TOOL HEALTH</span>}>
              <div className="dashboard-tool-health__body">
                <Progress
                  type="circle"
                  percent={stats?.tool_success_rate_30d ?? 0}
                  strokeColor="#52cfc8"
                  trailColor="#dceceb"
                  format={(percent) => `${percent}%`}
                />
                <div>
                  <strong>{stats?.tool_success_rate_30d ?? 0}%</strong>
                  <span>工具调用成功率</span>
                  <small>把失败也纳入观察，方便定位外部服务或知识检索异常。</small>
                </div>
              </div>
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card title="工具调用热度" extra={<span className="dashboard-card-kicker">TOP TOOLS</span>}>
              <BarChart data={stats?.top_tools ?? []} valueKey="call_count" labelKey="key" color="#52cfc8" />
            </Card>
          </Col>
        </Row>

        <Card className="dashboard-recent" title="最近工具调用" extra={<span className="dashboard-card-kicker">RECENT TRACE</span>}>
          <List
            dataSource={stats?.recent_tool_calls ?? []}
            locale={{ emptyText: '还没有工具调用记录' }}
            renderItem={(item) => (
              <List.Item>
                <div className="dashboard-recent__item">
                  <span className={`dashboard-recent__dot dashboard-recent__dot--${item.status}`} />
                  <div>
                    <strong>{item.tool}</strong>
                    <span>{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '刚刚'}</span>
                  </div>
                  <Tag color={item.status === 'success' ? 'success' : 'error'}>
                    {item.status === 'success' ? '成功' : '失败'}
                  </Tag>
                </div>
              </List.Item>
            )}
          />
        </Card>

        <Card className="dashboard-shortcuts" title="快捷入口">
          <Space wrap>
            <Button icon={<ThunderboltOutlined />} onClick={() => navigate('/agents')}>
              我的 Agent
            </Button>
            {canManage && (
              <Button icon={<BarChartOutlined />} onClick={() => navigate('/system/audit-logs')}>
                审计日志
              </Button>
            )}
            {canManage && (
              <Button icon={<TeamOutlined />} onClick={() => navigate('/system/users')}>
                用户管理
              </Button>
            )}
            <Button icon={<FileTextOutlined />} onClick={() => navigate('/knowledge')}>
              知识库
            </Button>
          </Space>
          {canManage && (
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">审计日志保留完整请求链路；当前面板额外聚合 Agent 工具执行轨迹。</Text>
            </div>
          )}
        </Card>
      </Spin>
    </div>
  )
}
