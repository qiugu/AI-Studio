// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import PluginConfig from './PluginConfig'

const {
  getPluginMock,
  getPluginConfigMock,
  listEndpointsMock,
  navigateMock,
} = vi.hoisted(() => ({
  getPluginMock: vi.fn(),
  getPluginConfigMock: vi.fn(),
  listEndpointsMock: vi.fn(),
  navigateMock: vi.fn(),
}))

vi.mock('@/api/plugin', () => ({
  getPlugin: getPluginMock,
  getPluginConfig: getPluginConfigMock,
  updatePluginConfig: vi.fn(),
  listEndpoints: listEndpointsMock,
  addEndpoint: vi.fn(),
  updateEndpoint: vi.fn(),
  deleteEndpoint: vi.fn(),
  importEndpoints: vi.fn(),
  testPlugin: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ id: 'plugin-1' }),
}))

vi.mock('@/components/JsonEditor', () => ({
  default: ({ label, value = '', onChange, id }: { label?: string; value?: string; onChange?: (value: string) => void; id?: string }) => (
    <div data-testid="plugin-json-editor">
      <span>{label ?? 'JSON 编辑器'}</span>
      <textarea id={id} value={value} onChange={(event) => onChange?.(event.target.value)} />
    </div>
  ),
}))

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: () => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver

  getPluginMock.mockResolvedValue({
    data: {
      id: 'plugin-1',
      tenant_id: 'tenant-1',
      name: '企业搜索',
      source_type: 'http',
      version: '1.0.0',
      description: '帮助 Agent 查找企业内部资料',
      config_schema: null,
      api_spec: { servers: [{ url: 'https://search.example.com' }] },
      status: 'active',
      is_public: false,
      endpoints: [],
    },
  })
  getPluginConfigMock.mockResolvedValue({ data: { items: [] } })
  listEndpointsMock.mockResolvedValue({ data: [] })
})

afterEach(cleanup)

describe('PluginConfig guided setup', () => {
  it('用四步流程说明如何把插件交给 Agent 使用', async () => {
    render(<PluginConfig />)

    expect(await screen.findByRole('heading', { name: '让企业搜索开始工作' })).toBeTruthy()
    expect(screen.getAllByText('连接服务').length).toBeGreaterThan(0)
    expect(screen.getAllByText('添加能力').length).toBeGreaterThan(0)
    expect(screen.getByText('试用一次')).toBeTruthy()
    expect(screen.getByText('给 Agent 使用')).toBeTruthy()
    expect(screen.getByRole('button', { name: /去 Agent 开启使用/ })).toBeTruthy()
  })

  it('没有自定义表单时也提供普通的连接输入', async () => {
    render(<PluginConfig />)

    expect(await screen.findByLabelText('服务地址')).toBeTruthy()
    expect(screen.getByLabelText('访问密钥')).toBeTruthy()
    expect(screen.getByLabelText('附加请求头')).toBeTruthy()
    expect(screen.getAllByTestId('plugin-json-editor').length).toBeGreaterThan(0)
    expect(screen.getByText('其他连接设置')).toBeTruthy()
  })
})
