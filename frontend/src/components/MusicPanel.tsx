import type { SongInfo } from '../types'

interface Props {
  current: SongInfo | null
  queue: SongInfo[]
}

function formatDuration(ms: number) {
  if (!ms) return ''
  const total = Math.round(ms / 1000)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export default function MusicPanel({ current, queue }: Props) {
  const upcoming = queue.slice(0, 3)
  return (
    <aside className="music-panel">
      <header className="music-header">
        <h3>一二的点歌台</h3>
        <span className="music-live">
          <i />
          直播中
        </span>
      </header>

      {current ? (
        <div className="music-now">
          <div className="music-now-info">
            <div className="music-name">《{current.name}》</div>
            <div className="music-meta">
              {current.artist || '未知歌手'}
              {current.requested_by ? ` · ${current.requested_by} 点的` : ''}
              {current.duration_ms ? ` · ${formatDuration(current.duration_ms)}` : ''}
            </div>
          </div>
          <span className="music-play" aria-hidden="true">
            ▶
          </span>
        </div>
      ) : (
        <div className="music-now empty">
          <div className="music-now-info">
            <div className="music-name">还没有歌在唱哦</div>
            <div className="music-meta">评论「点歌 + 歌名」就能点歌啦</div>
          </div>
          <span className="music-play muted" aria-hidden="true">
            ♪
          </span>
        </div>
      )}

      {upcoming.length > 0 && (
        <ul className="music-queue">
          {upcoming.map((song, index) => (
            <li key={song.key}>
              <span className="queue-index">{index + 1}</span>
              <span className="queue-name">《{song.name}》</span>
              <span className="queue-artist">{song.artist || '未知歌手'}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="music-add">+ 添加音乐</div>

      <div className="music-rules">
        评论「点歌+歌名」 · 🍭 棒棒糖可插队 · 排队 {queue.length} 首
      </div>
    </aside>
  )
}
