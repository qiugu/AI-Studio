/**
 * 流式请求工具 - 使用 fetch + ReadableStream，支持中断请求
 */

import { getToken } from './auth'

/**
 * 流式响应回调函数类型
 */
export interface StreamCallbacks {
  onContent?: (content: string) => void // 收到内容块时的回调
  onComplete?: (fullContent: string, conversationId?: number) => void // 流式完成时的回调
  onError?: (error: string, errorCode?: string) => void // 错误时的回调
}

/**
 * SSE 数据类型
 */
interface SSEData {
  content?: string
  conversation_id?: number
  error?: string
  error_code?: string
}

/**
 * 创建流式请求
 *
 * @param url - 请求 URL（相对路径，如 /api/agent/agents/1/chat/stream）
 * @param body - 请求体
 * @param callbacks - 回调函数
 * @returns AbortController - 用于中断请求
 */
export function createStreamRequest(
  url: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks
): AbortController {
  const controller = new AbortController()
  const token = getToken()

  // 构建 headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  // 发起 fetch 请求
  fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        // 处理 HTTP 错误
        const errorData = await response.json().catch(() => ({ message: response.statusText }))
        const errorMessage = errorData.message || errorData.detail || `HTTP ${response.status}`
        callbacks.onError?.(errorMessage, `HTTP_${response.status}`)
        return
      }

      // 读取 ReadableStream
      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError?.('无法获取响应流')
        return
      }

      const decoder = new TextDecoder()
      let fullContent = ''
      let conversationId: number | undefined
      let buffer = '' // 用于处理跨数据块的 SSE 消息

      try {
        while (true) {
          const { done, value } = await reader.read()

          if (done) {
            // 流式结束
            callbacks.onComplete?.(fullContent, conversationId)
            break
          }

          // 解码数据块
          const chunk = decoder.decode(value, { stream: true })
          buffer += chunk

          // 解析 SSE 格式的数据（event: xxx\n data: xxx\n\n）
          // SSE 消息以双换行符分隔
          const messages = buffer.split('\n\n')
          buffer = messages.pop() || '' // 保留最后一个不完整的消息

          for (const message of messages) {
            if (!message.trim()) continue

            const lines = message.split('\n')
            let eventType = ''
            let dataStr = ''

            for (const line of lines) {
              if (line.startsWith('event: ')) {
                eventType = line.substring(7).trim()
              } else if (line.startsWith('data: ')) {
                dataStr = line.substring(6).trim()
              }
            }

            if (dataStr) {
              try {
                const data: SSEData = JSON.parse(dataStr)

                // 根据事件类型处理
                if (eventType === 'message' || !eventType) {
                  // 内容块
                  if (data.content) {
                    fullContent += data.content
                    callbacks.onContent?.(data.content)
                  }
                } else if (eventType === 'done') {
                  // 流式完成
                  if (data.conversation_id) {
                    conversationId = data.conversation_id
                  }
                  callbacks.onComplete?.(fullContent, conversationId)
                  return
                } else if (eventType === 'error') {
                  // 错误事件
                  callbacks.onError?.(data.error || '模型调用失败', data.error_code)
                  return
                }
              } catch (e) {
                // JSON 解析失败，忽略
                console.warn('Failed to parse SSE data:', dataStr, e)
              }
            }
          }
        }
      } catch (error: unknown) {
        if (error instanceof Error && error.name === 'AbortError') {
          // 用户主动中断
          console.log('Stream request aborted by user')
        } else {
          const errorMessage = error instanceof Error ? error.message : '流式读取失败'
          callbacks.onError?.(errorMessage)
        }
      }
    })
    .catch((error: unknown) => {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Stream request aborted by user')
      } else {
        const errorMessage = error instanceof Error ? error.message : '请求失败'
        callbacks.onError?.(errorMessage)
      }
    })

  return controller
}

/**
 * 创建阻塞式请求（非流式）
 *
 * @param url - 请求 URL
 * @param body - 请求体
 * @returns Promise<Record<string, unknown>>
 */
export async function createBlockingRequest(
  url: string,
  body: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const token = getToken()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ message: response.statusText }))
    throw new Error(errorData.message || errorData.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * 工作流 SSE 事件类型
 */
export type SSEWorkflowEvent =
  | { type: 'execution_started'; execution_id: number; workflow_id: number }
  | { type: 'node_started'; node_id: number; node_name: string; node_type: string }
  | { type: 'node_completed'; node_id: number; node_name: string; output: Record<string, unknown> }
  | { type: 'node_failed'; node_id: number; node_name: string; error: string }
  | { type: 'execution_completed'; execution_id: number; output: Record<string, unknown> }
  | { type: 'execution_failed'; execution_id: number; error: string }

/**
 * 工作流流式请求回调函数类型
 */
export interface WorkflowStreamCallbacks {
  onEvent: (event: SSEWorkflowEvent) => void // 收到事件时的回调
  onError?: (error: string) => void // 错误时的回调
}

/**
 * 创建工作流流式请求
 *
 * @param url - 请求 URL
 * @param options - fetch 选项（method, body, headers 等）
 * @param callbacks - 回调函数
 * @returns AbortController - 用于中断请求
 */
export function createWorkflowStreamRequest(
  url: string,
  options: RequestInit,
  callbacks: WorkflowStreamCallbacks
): AbortController {
  const controller = new AbortController()
  const token = getToken()

  // 构建 headers
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) || {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  // 发起 fetch 请求
  fetch(url, {
    ...options,
    headers,
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        // 处理 HTTP 错误
        const errorData = await response.json().catch(() => ({ message: response.statusText }))
        const errorMessage = errorData.message || errorData.detail || `HTTP ${response.status}`
        callbacks.onError?.(errorMessage)
        return
      }

      // 读取 ReadableStream
      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError?.('无法获取响应流')
        return
      }

      const decoder = new TextDecoder()
      let buffer = '' // 用于处理跨数据块的 SSE 消息

      try {
        while (true) {
          const { done, value } = await reader.read()

          if (done) {
            // 流式结束
            break
          }

          // 解码数据块
          const chunk = decoder.decode(value, { stream: true })
          buffer += chunk

          // 解析 SSE 格式的数据（event: xxx\n data: xxx\n\n）
          // SSE 消息以双换行符分隔
          const messages = buffer.split('\n\n')
          buffer = messages.pop() || '' // 保留最后一个不完整的消息

          for (const message of messages) {
            if (!message.trim()) continue

            const lines = message.split('\n')
            let eventType = ''
            let dataStr = ''

            for (const line of lines) {
              if (line.startsWith('event: ')) {
                eventType = line.substring(7).trim()
              } else if (line.startsWith('data: ')) {
                dataStr = line.substring(6).trim()
              }
            }

            if (dataStr) {
              try {
                const data = JSON.parse(dataStr)

                // 构造事件对象
                const event = {
                  type: eventType,
                  ...data,
                } as SSEWorkflowEvent

                callbacks.onEvent(event)
              } catch (e) {
                // JSON 解析失败，忽略
                console.warn('Failed to parse SSE data:', dataStr, e)
              }
            }
          }
        }
      } catch (error: unknown) {
        if (error instanceof Error && error.name === 'AbortError') {
          // 用户主动中断
          console.log('Workflow stream request aborted by user')
        } else {
          const errorMessage = error instanceof Error ? error.message : '流式读取失败'
          callbacks.onError?.(errorMessage)
        }
      }
    })
    .catch((error: unknown) => {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Workflow stream request aborted by user')
      } else {
        const errorMessage = error instanceof Error ? error.message : '请求失败'
        callbacks.onError?.(errorMessage)
      }
    })

  return controller
}