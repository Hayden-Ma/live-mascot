import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import ChatFeed from './components/ChatFeed'
import CharacterStage from './components/CharacterStage'
import MusicPanel from './components/MusicPanel'
import QuickActions from './components/QuickActions'
import SpeechBubble from './components/SpeechBubble'
import StickerBubble from './components/StickerBubble'
import { useSocket } from './hooks/useSocket'
import type { Character, ChatItem, HeartBurst, SongInfo, SpeakSegment } from './types'

let chatSeq = 0
const nextChatId = () => `c${++chatSeq}`
let eventSeq = 0
const nextEventId = () => `e${++eventSeq}`

const HEART_EMOJI = ['❤️', '💖', '💕', '💗', '🧡', '💛']

export default function App() {
  const [character, setCharacter] = useState<Character | null>(null)
  const [chat, setChat] = useState<ChatItem[]>([])
  const [queue, setQueue] = useState<SpeakSegment[]>([])
  const [current, setCurrent] = useState<SpeakSegment | null>(null)
  const [typed, setTyped] = useState('')
  const [speaking, setSpeaking] = useState(false)
  const [audioBlocked, setAudioBlocked] = useState(false)
  const [stageScale, setStageScale] = useState(1)
  const [giftSticker, setGiftSticker] = useState<{
    url: string
    key: number
    count: number
    holdKey: number
    gift: string
    nick: string
  } | null>(null)
  const [roundSticker, setRoundSticker] = useState<{ url: string; key: number } | null>(null)
  // 关键词互动表情（弹幕提到「跳舞」「杂技」等时，像礼物一样播放对应图片）
  const [reactSticker, setReactSticker] = useState<{ url: string; key: number } | null>(null)
  const [nowPlaying, setNowPlaying] = useState<SongInfo | null>(null)
  const [songQueue, setSongQueue] = useState<SongInfo[]>([])

  // 点赞爱心雨
  const [hearts, setHearts] = useState<HeartBurst[]>([])

  const stickerKey = useRef(0)
  const typeTimer = useRef<number | null>(null)
  const holdTimer = useRef<number | null>(null)
  const bubbleTimer = useRef<number | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const musicRef = useRef<HTMLAudioElement | null>(null)
  const currentSongRef = useRef<string | null>(null)
  const likePending = useRef(0)
  const likeTimer = useRef<number | null>(null)

  useEffect(() => {
    fetch('/api/character')
      .then((res) => res.json())
      .then(setCharacter)
      .catch(() => {})
  }, [])

  // 页面刷新后恢复当前歌单（正在播放的会从头重放，后端按播放时长兜底切歌）
  useEffect(() => {
    fetch('/api/music/status')
      .then((res) => res.json())
      .then((data) => {
        if (!data || data.enabled === false) return
        setNowPlaying(data.current ?? null)
        setSongQueue(data.queue ?? [])
        if (data.current?.url) playSong(data.current)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    return () => {
      if (typeTimer.current) window.clearInterval(typeTimer.current)
      if (holdTimer.current) window.clearTimeout(holdTimer.current)
      if (bubbleTimer.current) window.clearTimeout(bubbleTimer.current)
      if (likeTimer.current) window.clearTimeout(likeTimer.current)
      audioRef.current?.pause()
      musicRef.current?.pause()
    }
  }, [])

  // 固定 1080x1920（9:16）设计画布，整体等比缩放适配窗口
  useEffect(() => {
    const fit = () =>
      setStageScale(Math.min(window.innerWidth / 1080, window.innerHeight / 1920))
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])

  // 每隔 20 秒在桌面小气泡里随机播一个氛围表情
  useEffect(() => {
    const list = character?.round_stickers ?? []
    if (list.length === 0) return
    const timer = window.setInterval(() => {
      const url = list[Math.floor(Math.random() * list.length)]
      stickerKey.current += 1
      setRoundSticker({ url, key: stickerKey.current })
    }, 20000)
    return () => window.clearInterval(timer)
  }, [character])

  const status = useSocket(`ws://${location.host}/ws`, {
    chat: (data) => {
      const nick = data.user?.nick ?? '?'
      setChat((prev) =>
        [
          ...prev,
          { id: nextChatId(), nick, text: data.text ?? '', kind: 'chat' as const },
        ].slice(-80),
      )
    },
    like: (data) => {
      const nick = data.user?.nick ?? '熊友'
      const count = Math.max(1, Number(data.count) || 1)
      queueLike(count)
      setChat((prev) =>
        [
          ...prev,
          {
            id: nextChatId(),
            nick,
            text: `点亮了 ${count} 个小心心`,
            kind: 'chat' as const,
          },
        ].slice(-80),
      )
    },
    gift: (data) => {
      const nick = data.user?.nick ?? '?'
      const giftName = data.gift ?? ''
      const count = data.count ?? 1

      if (data.merged) {
        // 连送合并：只更新正在展示的同一礼物，不重复播放/道谢
        setGiftSticker((prev) => {
          if (!prev || prev.gift !== giftName || prev.nick !== nick) return prev
          return { ...prev, count, holdKey: prev.holdKey + 1 }
        })
        return
      }

      setChat((prev) =>
        [
          ...prev,
          {
            id: nextChatId(),
            nick,
            text: `送出 ${giftName} x${count}`,
            kind: 'gift' as const,
          },
        ].slice(-80),
      )

      // 命中的礼物播对应表情，没命中的统一播默认感谢表情
      const url = character?.stickers?.[giftName] ?? character?.default_gift_sticker
      if (url) {
        stickerKey.current += 1
        setGiftSticker({
          url,
          key: stickerKey.current,
          count,
          holdKey: 0,
          gift: giftName,
          nick,
        })
      }
    },
    sticker: (data) => {
      const url = data.url as string | undefined
      if (!url) return
      stickerKey.current += 1
      setReactSticker({ url, key: stickerKey.current })
    },
    speak: (data) => {
      const segments: SpeakSegment[] = (data.segments ?? []).map((s: any) => ({
        text: s.text ?? '',
        audio: s.audio ?? null,
        duration_ms: s.duration_ms ?? 1500,
        id: data.id,
        nick: data.user?.nick ?? '',
        emotion: data.emotion ?? 'neutral',
        show_text: data.show_text !== false,
      }))
      setQueue((prev) => [...prev, ...segments])
    },
    song_queue: (data) => {
      setNowPlaying(data.current ?? null)
      setSongQueue(data.queue ?? [])
      if (data.current) currentSongRef.current = data.current.key
    },
    song_start: (data) => {
      const song: SongInfo | null = data.song ?? null
      setNowPlaying(song)
      currentSongRef.current = song?.key ?? null
      if (song?.url) playSong(song)
    },
    song_end: (data) => {
      const song: SongInfo | null = data.song ?? null
      if (!song || currentSongRef.current === song.key) {
        currentSongRef.current = null
        setNowPlaying(null)
      }
    },
  })

  useEffect(() => {
    if (speaking || queue.length === 0) return
    const [segment, ...rest] = queue
    setQueue(rest)
    playSegment(segment)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue, speaking])

  function clearTimers() {
    if (typeTimer.current) {
      window.clearInterval(typeTimer.current)
      typeTimer.current = null
    }
    if (holdTimer.current) {
      window.clearTimeout(holdTimer.current)
      holdTimer.current = null
    }
  }

  function finishSegment() {
    holdTimer.current = window.setTimeout(() => {
      // 主播说完话，把伴奏音量恢复正常
      if (musicRef.current) musicRef.current.volume = 1
      setSpeaking(false)
      // 气泡多停一会儿再消失，避免话音刚落就空屏
      if (bubbleTimer.current) window.clearTimeout(bubbleTimer.current)
      bubbleTimer.current = window.setTimeout(() => setCurrent(null), 6000)
    }, 220)
  }

  // 歌曲播完/播放出错后通知后端切下一首
  function reportSongFinished(songKey: string) {
    fetch('/api/music/finished', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_id: songKey }),
    }).catch(() => {})
  }

  function playSong(song: SongInfo) {
    musicRef.current?.pause()
    musicRef.current = null
    if (!song?.url) return

    const audio = new Audio(song.url)
    musicRef.current = audio
    audio.volume = 1
    audio.onended = () => reportSongFinished(song.key)
    audio.onerror = () => reportSongFinished(song.key)
    audio.play().then(
      () => setAudioBlocked(false),
      // 浏览器要求先有用户交互，显示「点击启用声音」按钮
      () => setAudioBlocked(true),
    )
  }

  // 用户点击后同时解锁主播语音和歌曲播放
  function unlockAudio() {
    setAudioBlocked(false)
    if (musicRef.current) {
      musicRef.current.volume = 1
      musicRef.current.play().catch(() => {})
    }
  }

  // 无音频时的兜底：按估算时长逐字显示
  function playByDuration(segment: SpeakSegment) {
    const duration = segment.duration_ms || 1500
    const step = Math.max(24, duration / Math.max(1, segment.text.length))
    let index = 0
    typeTimer.current = window.setInterval(() => {
      index += 1
      setTyped(segment.text.slice(0, index))
      if (index >= segment.text.length) {
        if (typeTimer.current) {
          window.clearInterval(typeTimer.current)
          typeTimer.current = null
        }
        finishSegment()
      }
    }, step)
  }

  // 只出声不弹字的语音（进场欢迎）：没有音频时静默等待估算时长
  function waitSilently(segment: SpeakSegment) {
    typeTimer.current = window.setTimeout(() => {
      typeTimer.current = null
      finishSegment()
    }, segment.duration_ms || 1500)
  }

  function playSegment(segment: SpeakSegment) {
    const showText = segment.show_text !== false
    if (showText) {
      setCurrent(segment)
      setTyped('')
    }
    setSpeaking(true)
    clearTimers()
    if (bubbleTimer.current) {
      window.clearTimeout(bubbleTimer.current)
      bubbleTimer.current = null
    }
    audioRef.current?.pause()
    audioRef.current = null
    // 主播说话时压低伴奏，避免音乐盖住人声
    if (musicRef.current) musicRef.current.volume = 0.25

    if (!segment.audio) {
      if (showText) {
        playByDuration(segment)
      } else {
        waitSilently(segment)
      }
      return
    }

    const audio = new Audio(segment.audio)
    audioRef.current = audio
    // 文字进度跟随真实音频进度
    audio.ontimeupdate = () => {
      if (!showText || !audio.duration || !Number.isFinite(audio.duration)) return
      const ratio = Math.min(1, audio.currentTime / audio.duration)
      setTyped(segment.text.slice(0, Math.floor(ratio * segment.text.length)))
    }
    audio.onended = () => {
      audioRef.current = null
      if (showText) setTyped(segment.text)
      finishSegment()
    }
    audio.onerror = () => {
      audioRef.current = null
      if (showText) {
        playByDuration(segment)
      } else {
        waitSilently(segment)
      }
    }
    audio.play().then(
      () => setAudioBlocked(false),
      () => {
        // 浏览器自动播放策略拦截：退回静默播放，等用户点击后再出声
        audioRef.current = null
        setAudioBlocked(true)
        if (showText) {
          playByDuration(segment)
        } else {
          waitSilently(segment)
        }
      },
    )
  }

  // 点赞先在本地攒一小会儿，再一起放爱心，避免连续点赞刷爆 DOM
  function queueLike(count: number) {
    likePending.current += count
    if (likeTimer.current) return
    likeTimer.current = window.setTimeout(() => {
      likeTimer.current = null
      const amount = likePending.current
      likePending.current = 0
      if (amount > 0) spawnHearts(amount)
    }, 450)
  }

  function spawnHearts(amount: number) {
    const count = Math.min(12, Math.max(4, Math.round(amount / 5) + 2))
    const batch: HeartBurst[] = Array.from({ length: count }, () => ({
      id: nextEventId(),
      x: 6 + Math.random() * 88,
      size: 30 + Math.random() * 34,
      delay: Math.random() * 0.35,
      duration: 2.4 + Math.random() * 1.2,
      emoji: HEART_EMOJI[Math.floor(Math.random() * HEART_EMOJI.length)],
      rotate: -18 + Math.random() * 36,
      drift: -70 + Math.random() * 140,
    }))
    setHearts((prev) => [...prev.slice(-60), ...batch])
    const ids = new Set(batch.map((heart) => heart.id))
    window.setTimeout(() => {
      setHearts((prev) => prev.filter((heart) => !ids.has(heart.id)))
    }, 5200)
  }

  const title = character?.display_name ?? '一二'
  const background = character?.art?.background
  // 默认隐藏弹幕栏；调试时在地址后排 ?chat=1 可打开
  const showChat = new URLSearchParams(location.search).get('chat') === '1'

  return (
    <div className="app">
      <div
        className="stage"
        style={{ transform: `translate(-50%, -50%) scale(${stageScale})` }}
      >
        {background && (
          <>
            <div className="scene-bg" style={{ backgroundImage: `url(${background})` }} />
            <div className="scene-shade" />
          </>
        )}

        <QuickActions />

        <div className="top-right">
          <MusicPanel current={nowPlaying} queue={songQueue} />
        </div>

        <CharacterStage
          speaking={speaking}
          name={title}
          art={character?.art?.idle}
        />

        <div className="heart-layer" aria-hidden="true">
          {hearts.map((heart) => (
            <span
              key={heart.id}
              className="floating-heart"
              style={
                {
                  left: `${heart.x}%`,
                  fontSize: `${heart.size}px`,
                  animationDelay: `${heart.delay}s`,
                  animationDuration: `${heart.duration}s`,
                  '--rot': `${heart.rotate}deg`,
                  '--drift': `${heart.drift}px`,
                } as CSSProperties
              }
            >
              {heart.emoji}
            </span>
          ))}
        </div>

        {giftSticker && (
          <StickerBubble
            key={`gift-${giftSticker.key}`}
            url={giftSticker.url}
            variant="gift"
            holdMs={3000}
            count={giftSticker.count}
            holdKey={giftSticker.holdKey}
            onDone={() => setGiftSticker(null)}
          />
        )}
        {reactSticker && (
          <StickerBubble
            key={`reaction-${reactSticker.key}`}
            url={reactSticker.url}
            variant="reaction"
            holdMs={4000}
            onDone={() => setReactSticker(null)}
          />
        )}
        {roundSticker && (
          <StickerBubble
            key={`round-${roundSticker.key}`}
            url={roundSticker.url}
            variant="round"
            holdMs={2400}
            onDone={() => setRoundSticker(null)}
          />
        )}

        <SpeechBubble text={typed} nick={current?.nick ?? ''} visible={!!current} />

        {showChat && <ChatFeed items={chat} title={title} status={status} />}
        {audioBlocked && (
          <button className="audio-unlock" onClick={unlockAudio}>
            点击启用声音
          </button>
        )}
      </div>
    </div>
  )
}
