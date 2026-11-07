import { useEffect, useRef, useState } from 'react'

export type ConnectionStatus = 'connecting' | 'open' | 'closed'
export type MessageHandler = (data: Record<string, any>) => void

export function useSocket(url: string, handlers: Record<string, MessageHandler>) {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  useEffect(() => {
    let socket: WebSocket | null = null
    let stopped = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      socket = new WebSocket(url)
      socket.onopen = () => setStatus('open')
      socket.onclose = () => {
        setStatus('closed')
        if (!stopped) retryTimer = setTimeout(connect, 1500)
      }
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handlersRef.current[data.type]?.(data)
        } catch {
          // 忽略非法消息
        }
      }
    }

    connect()

    return () => {
      stopped = true
      if (retryTimer) clearTimeout(retryTimer)
      socket?.close()
    }
  }, [url])

  return status
}
