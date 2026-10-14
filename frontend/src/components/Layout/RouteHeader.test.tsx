// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import RouteHeader from './RouteHeader'

describe('RouteHeader', () => {
  it('returns to the owning module without relying on browser history', () => {
    render(
      <MemoryRouter initialEntries={['/agents/agent-1/chat']}>
        <Routes>
          <Route
            path="/agents/agent-1/chat"
            element={<RouteHeader title="Agent 对话" backTo="/agents" backLabel="返回 Agent 列表" />}
          />
          <Route path="/agents" element={<div>Agent 列表</div>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: '返回 Agent 列表' }))

    expect(screen.getByText('Agent 列表')).toBeTruthy()
  })

  it('supports a compact workbench header without a decorative eyebrow', () => {
    render(
      <MemoryRouter>
        <RouteHeader
          compact
          title="超级旅游助手"
          description="Agent 对话"
          eyebrow="应用开发 / Agent"
          backTo="/agents"
          backLabel="返回 Agent 列表"
        />
      </MemoryRouter>,
    )

    const heading = screen.getByRole('heading', { name: '超级旅游助手' })
    expect(heading.closest('.route-header--compact')).toBeTruthy()
    expect(screen.getByText('Agent 对话')).toBeTruthy()
    expect(screen.queryByText('应用开发 / Agent')).toBeNull()
  })
})
