import { Card, Row, Col, Statistic, Typography } from 'antd'
import {
  TeamOutlined,
  ThunderboltOutlined,
  CodeOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'

const { Title } = Typography

export default function Dashboard() {
  return (
    <div>
      <Title level={4}>仪表盘</Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="用户数" value={0} prefix={<TeamOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="Agent 数" value={0} prefix={<ThunderboltOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="Prompt 数" value={0} prefix={<CodeOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="知识库数" value={0} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}