import type {
  PromptVersion,
  PromptUpdateRequest,
  PromptVersionCreateRequest,
} from '@/types/prompt'

/** 注入的 API 依赖，便于单元测试中使用 mock 替换。 */
export interface PromptSaveDeps {
  updatePrompt: (id: string, data: PromptUpdateRequest) => Promise<unknown>
  createVersion: (id: string, data: PromptVersionCreateRequest) => Promise<{ data: PromptVersion }>
  activateVersion: (id: string, versionId: string) => Promise<{ data: PromptVersion }>
}

export interface ExecutePromptSaveOptions {
  promptId: string
  isEdit: boolean
  /** 当前编辑内容与 Prompt 当前版本内容是否不同。 */
  contentChanged: boolean
  metadata: PromptUpdateRequest
  content: string
  deps: PromptSaveDeps
}

export interface ExecutePromptSaveResult {
  /** 为 true 时表示应走新建流程（createPrompt），本函数不处理。 */
  skip: boolean
  message: string
  version?: PromptVersion
}

/**
 * 编辑 Prompt 的保存编排。对用户只有一个语义：点「保存」= 全部保存。
 * 内部拆两步（由后端数据模型决定，prompts 表不存内容，内容只存 prompt_versions）：
 * 1. updatePrompt 保存名称/描述等基本信息（始终执行）；
 * 2. 内容有变化时 createVersion 生成新版本并 activateVersion 启用（后端接口要求两步）。
 */
export async function executePromptSave(
  opts: ExecutePromptSaveOptions,
): Promise<ExecutePromptSaveResult> {
  const { promptId, isEdit, contentChanged, metadata, content, deps } = opts

  // 新建分支不在此处理，交由组件走 createPrompt（v1 自动激活）
  if (!isEdit) {
    return { skip: true, message: '' }
  }

  await deps.updatePrompt(promptId, metadata)

  if (!contentChanged) {
    return { skip: false, message: '保存成功' }
  }

  const vRes = await deps.createVersion(promptId, { content })
  const version = vRes.data

  try {
    await deps.activateVersion(promptId, version.id)
  } catch {
    // 内容已落库为新版本，仅"启用"这一步失败；不向上抛，避免用户误以为什么都没保存
    return {
      skip: false,
      message: '已保存，但新版本启用失败，请在详情页重试',
      version,
    }
  }
  return {
    skip: false,
    message: `保存成功，已生成新版本 v${version.version_number}`,
    version,
  }
}
