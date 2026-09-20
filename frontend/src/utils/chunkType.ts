/**
 * 分块类型的判定工具。
 *
 * **为什么单独成文件**：`isStructuredChunk` 要在「渲染组件」与「引用面板」之间共享，
 * 而 `react-refresh` 只允许组件文件导出组件（同一文件里再导出函数会让该模块的热更新
 * 退化为整页刷新）。这与 `utils/citation.ts` 的做法一致——判定逻辑放 `utils`，组件
 * 只负责渲染。
 *
 * 判据只有一处，是因为**它被两处消费且消费方式不同**：渲染组件据此选渲染分支
 * （表格按列、代码保换行），引用面板据此选**容器**（结构化块不能用 `<pre>`，
 * 正文快照必须用 `<pre>` 才能保住等宽与精确换行）。两处判据一分叉，就会出现
 * 「表格块被塞进 `<pre>`」这类渲染错乱。
 */

import type { ChunkType } from '@/types/knowledge'

/** 需要类型化渲染的块类型：纯文本输出会丢失结构 */
export const STRUCTURED_CHUNK_TYPES = ['table', 'code'] as const

/**
 * 该块类型是否需要类型化渲染。
 *
 * 对 `undefined` / `null` / 未知取值一律返回 `false`：引用对象的历史快照没有
 * `chunk_type` 键，按正文处理是唯一安全的回落。
 */
export function isStructuredChunk(chunkType?: ChunkType | string | null): boolean {
  return (STRUCTURED_CHUNK_TYPES as readonly string[]).includes(chunkType ?? '')
}
