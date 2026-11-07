interface Props {
  text: string
  nick: string
  visible: boolean
}

export default function SpeechBubble({ text, nick, visible }: Props) {
  if (!visible) return null
  return (
    <div className="bubble-wrap">
      <div className="bubble">
        <div className="bubble-text">
          {nick && <span className="bubble-name">「{nick}」</span>}
          <span className="bubble-content">{text}</span>
        </div>
      </div>
      <span className="bubble-tail" aria-hidden="true" />
    </div>
  )
}
