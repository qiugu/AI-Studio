// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createStreamRequest, createWorkflowStreamRequest } from './streamRequest'
import type { SSEToolEvent } from '@/types/agent'

function streamResponse(...chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    { status: 200 }
  )
}

describe('createStreamRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reports an incomplete stream instead of completing with an empty reply', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(': ping\r\n\r\n')))

    await new Promise<void>((resolve, reject) => {
      createStreamRequest('/chat', { message: '你好' }, {
        onComplete: () => reject(new Error('不应把缺少 done 事件的空响应当作成功')),
        onError: (error, errorCode) => {
          try {
            expect(errorCode).toBe('STREAM_INCOMPLETE')
            expect(error).toContain('意外中断')
            resolve()
          } catch (assertionError) {
            reject(assertionError)
          }
        },
      })
    })
  })

  it('completes when EOF follows a valid done frame without a trailing blank line', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse('event: done\r\ndata: {"conversation_id":"c1"}')
      )
    )

    await new Promise<void>((resolve, reject) => {
      createStreamRequest('/chat', { message: '你好' }, {
        onComplete: (content, conversationId) => {
          try {
            expect(content).toBe('')
            expect(conversationId).toBe('c1')
            resolve()
          } catch (assertionError) {
            reject(assertionError)
          }
        },
        onError: (error) => reject(new Error(`不应报告流中断：${error}`)),
      })
    })
  })

  it('forwards tool lifecycle events while the assistant is working', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse(
          'event: tool_start\ndata: {"call_id":"run-1","tool":"knowledge-kb-1","input":{"query":"发布"},"status":"running"}\n\n',
          'event: tool_end\ndata: {"call_id":"run-1","tool":"knowledge-kb-1","output":"命中 3 条","status":"success"}\n\n',
          'event: done\ndata: {"conversation_id":"c1"}\n\n',
        ),
      ),
    )

    const starts: SSEToolEvent[] = []
    const ends: SSEToolEvent[] = []
    await new Promise<void>((resolve, reject) => {
      createStreamRequest('/chat', { message: '你好' }, {
        onToolStart: (event) => starts.push(event),
        onToolEnd: (event) => ends.push(event),
        onComplete: () => {
          try {
            expect(starts[0]).toMatchObject({ call_id: 'run-1', tool: 'knowledge-kb-1' })
            expect(ends[0]).toMatchObject({ call_id: 'run-1', status: 'success' })
            resolve()
          } catch (assertionError) {
            reject(assertionError)
          }
        },
        onError: (error) => reject(new Error(`不应报告工具流错误：${error}`)),
      })
    })
  })
})

describe('createWorkflowStreamRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('flushes the final execution event when the stream closes without a blank line', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse(
          'event: execution_completed\r\ndata: {"execution_id":"e1","output":{"result":42}}',
        ),
      ),
    )

    await new Promise<void>((resolve, reject) => {
      createWorkflowStreamRequest(
        '/workflows/w1/execute/stream',
        { method: 'POST', body: '{}' },
        {
          onEvent: (event) => {
            try {
              expect(event).toEqual({
                type: 'execution_completed',
                execution_id: 'e1',
                output: { result: 42 },
              })
              resolve()
            } catch (assertionError) {
              reject(assertionError)
            }
          },
          onError: (error) => reject(new Error(`不应报告工作流流错误：${error}`)),
        },
      )
    })
  })
})
