import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'

const { Content } = Layout

export default function AppLayout() {
  return (
    <Layout className="h-screen">
      <Sidebar />
      <Layout>
        <Header />
        <Content className="p-[24px]!">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
