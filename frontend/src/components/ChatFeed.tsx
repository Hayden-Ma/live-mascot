import { useEffect, useRef } from 'react'
import type { ChatItem } from '../types'

interface Props {
  items: ChatItem[]
  title: string
  status: string
}

const STATUS_LABEL: Record<string, string> = {
  open: '已连接',
  connecting: '连接中',
  closed: '已断开',
}

export default function ChatFeed({ items, title, status }: Props) {
  const listRef = useRef<HTMLUListElement>(null)

  // 有新弹幕时自动滚到底部，让列表自己往下走
  useEffect(() => {
    const list = listRef.current
    if (!list) return
    list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' })
  }, [items])

  return (
    <aside className="chat-feed">
      <header>
        <span className="dot" data-status={status} />
        <h2>{title} 的直播间</h2>
        <span className="conn">{STATUS_LABEL[status] ?? status}</span>
      </header>
      <ul ref={listRef}>
        {items.map((item) => (
          <li key={item.id} className={`chat-item ${item.kind}`}>
            <span className="nick">{item.nick}</span>
            <span className="text">{item.text}</span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
