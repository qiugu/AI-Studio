import { useEffect, useRef, useState } from 'react'
import { getToken } from '@/utils/auth'
import type { SSEMessageEvent, SSEDoneEvent, SSEErrorEvent } from '@/types/agent'

interface UseSSEOptions {
  url: string
  onMessage?: (event: SSEMessageEvent) => void
  onDone?: (event: SSEDoneEvent) => void
  onError?: (event: SSEErrorEvent) => void
  onComplete?: () => void
}

interface UseSSEResult {
  isConnected: boolean
  error: string | null
  connect: () => void
  disconnect: () => void
}

/**
 * SSE Hook - 用于订阅Server-Sent Events
 */
export function useSSE(options: UseSSEOptions): UseSSEResult {
  const { url, onMessage, onDone, onError, onComplete } = options
  const eventSourceRef = useRef<EventSource | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const connect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    // 获取token并添加到URL参数
    const token = getToken()
    if (!token) {
      setError('No token found')
      return
    }
    const urlWithToken = `${url}?token=${token}`

    const eventSource = new EventSource(urlWithToken)
    eventSourceRef.current = eventSource
    setIsConnected(true)
    setError(null)

    eventSource.onopen = () => {
      setIsConnected(true)
      setError(null)
    }

    eventSource.onerror = () => {
      setIsConnected(false)
      setError('Connection error')
      eventSource.close()
      if (onComplete) {
        onComplete()
      }
    }

    eventSource.addEventListener('message', (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as SSEMessageEvent
        if (onMessage) {
          onMessage(data)
        }
      } catch (e) {
        console.error('Failed to parse SSE message:', e)
      }
    })

    eventSource.addEventListener('done', (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as SSEDoneEvent
        if (onDone) {
          onDone(data)
        }
        setIsConnected(false)
        eventSource.close()
        if (onComplete) {
          onComplete()
        }
      } catch (e) {
        console.error('Failed to parse SSE done event:', e)
      }
    })

    eventSource.addEventListener('error', (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as SSEErrorEvent
        setError(data.error)
        if (onError) {
          onError(data)
        }
        setIsConnected(false)
        eventSource.close()
        if (onComplete) {
          onComplete()
        }
      } catch (e) {
        console.error('Failed to parse SSE error event:', e)
      }
    })
  }

  const disconnect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsConnected(false)
    }
  }

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [])

  return {
    isConnected,
    error,
    connect,
    disconnect,
  }
}