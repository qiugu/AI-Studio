import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'

const { Content } = Layout

/**
 * 应用外壳布局
 *
 * 高度契约（三者互相耦合，改动任一处都需重新审视另外两处）：
 *  1. 最外层 `<Layout className="h-screen">` 持有 100vh —— 外壳高度的唯一来源；
 *  2. `Sider` / `Header` 不参与滚动：Sider 之外由父级拉伸，Header 由 flex
 *     （`flex: 0 0 auto` + 64px）固定占位；
 *  3. `Content` 是**唯一**的滚动容器，也是子页面「可用高度」的基准。
 *
 * `overflow-auto` 是这里的关键：antd 的 `.ant-layout-content` 只有
 * `flex: auto` + `min-height: 0`，仅能保证它自身被压缩到剩余空间，**不负责**处置
 * 溢出的子内容。缺了 `overflow` 时溢出内容既不滚动也不裁剪，会以 `visible` 直接
 * 穿出外壳（长列表把 Header / Sider 的位置关系一起顶乱，且全程没有滚动条）。
 *
 * 另一个必要条件是全局样式里**不能**给 `.ant-layout` 加 `min-height: 100vh`：
 * 该选择器会同时命中此处的内层 `<Layout>`，覆盖掉 antd 自带的 `min-height: 0`，
 * 使内层无法收缩（详见 `src/styles/global.css` 的说明）。
 */

export default function AppLayout() {
  return (
    <Layout className="h-screen">
      <Sidebar />
      <Layout>
        <Header />
        <Content className="p-[24px]! overflow-auto">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
