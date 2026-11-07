import { useEffect, useState } from 'react'

interface Props {
  url: string
  variant: 'gift' | 'round' | 'reaction'
  holdMs: number
  onDone: () => void
  count?: number
  holdKey?: number
}

export default function StickerBubble({
  url,
  variant,
  holdMs,
  onDone,
  count = 1,
  holdKey = 0,
}: Props) {
  const [leaving, setLeaving] = useState(false)

  // holdKey 变化（连送合并）时重新计时，保持展示并刷新角标
  useEffect(() => {
    setLeaving(false)
    const fadeTimer = window.setTimeout(() => setLeaving(true), holdMs)
    const doneTimer = window.setTimeout(onDone, holdMs + 450)
    return () => {
      window.clearTimeout(fadeTimer)
      window.clearTimeout(doneTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holdKey])

  return (
    <div className={`sticker-bubble ${variant} ${leaving ? 'leaving' : ''}`}>
      <div className="sticker-inner">
        <img src={url} alt="" />
        {variant === 'gift' && count > 1 && (
          <span className="sticker-count">×{count}</span>
        )}
      </div>
    </div>
  )
}
