export interface Character {
  id: string
  display_name: string
  default_emotion?: string
  theme?: Record<string, string>
  art?: { idle?: string; background?: string }
  stickers?: Record<string, string>
  default_gift_sticker?: string
  round_stickers?: string[]
}

export interface ChatItem {
  id: string
  nick: string
  text: string
  kind: 'chat' | 'gift'
}

export interface Segment {
  text: string
  audio: string | null
  duration_ms: number
}

export interface SpeakSegment extends Segment {
  id: string
  nick: string
  emotion: string
  show_text?: boolean
}

export interface SongInfo {
  key: string
  song_id: string
  name: string
  artist: string
  duration_ms: number
  source: string
  requested_by: string
  url: string
}

export interface HeartBurst {
  id: string
  x: number
  size: number
  delay: number
  duration: number
  emoji: string
  rotate: number
  drift: number
}
