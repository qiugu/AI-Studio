import { describe, it, expect, vi } from 'vitest'
import { executePromptSave, type PromptSaveDeps } from './promptSave'
import type { PromptVersion, PromptUpdateRequest } from '@/types/prompt'

function makeVersion(versionNumber: number, id = 'vid-1'): PromptVersion {
  return {
    id,
    prompt_id: 'p1',
    version_number: versionNumber,
    content: 'content',
    variables: [],
    is_current: false,
    created_by: null,
    created_at: null,
  }
}

function makeDeps(overrides: Partial<PromptSaveDeps> = {}): PromptSaveDeps {
  return {
    updatePrompt: vi.fn(async () => undefined),
    createVersion: vi.fn(async () => ({ data: makeVersion(2) })),
    activateVersion: vi.fn(async () => ({ data: makeVersion(2) })),
    ...overrides,
  }
}

const baseMeta: PromptUpdateRequest = {
  name: 'n',
  description: 'd',
  category: 'c',
  tags: ['t'],
  status: 'draft',
}

describe('executePromptSave', () => {
  it('新建（isEdit=false）返回 skip，不走编辑编排', async () => {
    const deps = makeDeps()
    const res = await executePromptSave({
      promptId: 'p1',
      isEdit: false,
      contentChanged: true,
      metadata: baseMeta,
      content: 'x',
      deps,
    })
    expect(res.skip).toBe(true)
    expect(deps.updatePrompt).not.toHaveBeenCalled()
    expect(deps.createVersion).not.toHaveBeenCalled()
  })

  it('内容未改：仅调用 updatePrompt，不建版本', async () => {
    const deps = makeDeps()
    const res = await executePromptSave({
      promptId: 'p1',
      isEdit: true,
      contentChanged: false,
      metadata: baseMeta,
      content: 'x',
      deps,
    })
    expect(res.skip).toBe(false)
    expect(res.message).toBe('保存成功')
    expect(deps.updatePrompt).toHaveBeenCalledTimes(1)
    expect(deps.createVersion).not.toHaveBeenCalled()
    expect(deps.activateVersion).not.toHaveBeenCalled()
  })

  it('内容已改：updatePrompt + createVersion + activateVersion 全部执行', async () => {
    const deps = makeDeps()
    const res = await executePromptSave({
      promptId: 'p1',
      isEdit: true,
      contentChanged: true,
      metadata: baseMeta,
      content: 'new content',
      deps,
    })
    expect(deps.updatePrompt).toHaveBeenCalledTimes(1)
    expect(deps.createVersion).toHaveBeenCalledTimes(1)
    expect(deps.activateVersion).toHaveBeenCalledTimes(1)
    expect(res.message).toContain('v2')
  })

  it('激活失败：捕获并提示，不向上抛出（元数据与新版本均已落库）', async () => {
    const deps = makeDeps({
      activateVersion: vi.fn(async () => {
        throw new Error('network')
      }),
    })
    const res = await executePromptSave({
      promptId: 'p1',
      isEdit: true,
      contentChanged: true,
      metadata: baseMeta,
      content: 'new content',
      deps,
    })
    expect(deps.updatePrompt).toHaveBeenCalledTimes(1)
    expect(deps.createVersion).toHaveBeenCalledTimes(1)
    expect(res.message).toBe('已保存，但新版本启用失败，请在详情页重试')
    expect(res.version?.version_number).toBe(2)
  })
})
