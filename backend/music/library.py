import difflib
import random
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# 支持的音频扩展名（缓存目录里手动放入的歌也会被索引）
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus"}

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def safe_filename(text: str, limit: int = 40) -> str:
    """去掉文件名里的非法字符，避免下载时写盘失败。"""
    cleaned = _ILLEGAL.sub("_", text).strip().replace("\n", " ")
    return cleaned[:limit] or "song"


def normalize(text: str) -> str:
    """用于模糊匹配：只保留中英文和数字，忽略大小写、空格与标点。"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", (text or "").lower())


@dataclass
class LibrarySong:
    key: str
    song_id: str
    name: str
    artist: str
    duration_ms: int
    path: Path
    source: str


class MusicLibrary:
    """本地曲库索引（SQLite），记录缓存歌曲与手动放入的音频文件。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(
            str(cache_dir / "library.db"), check_same_thread=False
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                key TEXT PRIMARY KEY,
                song_id TEXT DEFAULT '',
                name TEXT NOT NULL,
                artist TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                file_name TEXT NOT NULL,
                source TEXT DEFAULT 'netease',
                created_at REAL,
                last_used_at REAL
            )
            """
        )
        self._db.commit()

    def _row_to_song(self, row: tuple) -> LibrarySong:
        key, song_id, name, artist, duration_ms, file_name, source = row
        return LibrarySong(
            key=key,
            song_id=song_id or "",
            name=name,
            artist=artist or "",
            duration_ms=int(duration_ms or 0),
            path=self.cache_dir / file_name,
            source=source,
        )

    def add(
        self,
        *,
        song_id: str,
        name: str,
        artist: str,
        duration_ms: int,
        file_name: str,
        source: str = "netease",
    ) -> LibrarySong:
        key = f"netease:{song_id}" if source == "netease" and song_id else f"local:{file_name}"
        now = time.time()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO songs (key, song_id, name, artist, duration_ms, file_name,
                                   source, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    song_id=excluded.song_id,
                    name=excluded.name,
                    artist=excluded.artist,
                    duration_ms=excluded.duration_ms,
                    file_name=excluded.file_name,
                    source=excluded.source
                """,
                (key, song_id, name, artist, duration_ms, file_name, source, now, now),
            )
            self._db.commit()
        return LibrarySong(
            key=key,
            song_id=song_id,
            name=name,
            artist=artist,
            duration_ms=duration_ms,
            path=self.cache_dir / file_name,
            source=source,
        )

    def get_by_key(self, key: str) -> LibrarySong | None:
        with self._lock:
            row = self._db.execute(
                "SELECT key, song_id, name, artist, duration_ms, file_name, source "
                "FROM songs WHERE key = ?",
                (key,),
            ).fetchone()
        return self._row_to_song(row) if row else None

    def get_by_song_id(self, song_id: str) -> LibrarySong | None:
        if not song_id:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT key, song_id, name, artist, duration_ms, file_name, source "
                "FROM songs WHERE song_id = ?",
                (song_id,),
            ).fetchone()
        return self._row_to_song(row) if row else None

    def find(self, query: str, threshold: float = 0.55) -> LibrarySong | None:
        """按歌名/歌手做模糊匹配，命中返回最相似的一首。"""
        query_n = normalize(query)
        if not query_n:
            return None
        with self._lock:
            rows = self._db.execute(
                "SELECT key, song_id, name, artist, duration_ms, file_name, source "
                "FROM songs"
            ).fetchall()

        best: LibrarySong | None = None
        best_score = 0.0
        for row in rows:
            song = self._row_to_song(row)
            name_n = normalize(song.name)
            combined = normalize(f"{song.name}{song.artist}")
            if not name_n:
                continue
            if query_n == name_n:
                score = 1.0
            elif query_n in name_n or name_n in query_n:
                # 用户常带歌手名一起点歌，包含关系给高分
                score = 0.95
            else:
                score = max(
                    difflib.SequenceMatcher(None, query_n, name_n).ratio(),
                    difflib.SequenceMatcher(None, query_n, combined).ratio(),
                )
            if score > best_score:
                best_score = score
                best = song
        if best is None or best_score < threshold:
            return None
        return best if best.path.exists() else None

    def random_song(self, exclude_key: str = "") -> LibrarySong | None:
        """随机挑一首本地可播放的歌曲（用于空闲时的自动播放）。"""
        with self._lock:
            rows = self._db.execute(
                "SELECT key, song_id, name, artist, duration_ms, file_name, source "
                "FROM songs WHERE key != ?",
                (exclude_key,),
            ).fetchall()
        candidates = [
            song for song in (self._row_to_song(row) for row in rows) if song.path.exists()
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    def touch(self, key: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE songs SET last_used_at = ? WHERE key = ?", (time.time(), key)
            )
            self._db.commit()

    def prune(self, max_songs: int, keep_key: str = "") -> list[str]:
        """超出上限时按最久未使用淘汰，返回被删除的文件名。"""
        with self._lock:
            rows = self._db.execute(
                "SELECT key, file_name FROM songs ORDER BY last_used_at ASC"
            ).fetchall()
            overflow = len(rows) - max_songs
            if overflow <= 0:
                return []
            deleted: list[str] = []
            for key, file_name in rows:
                if overflow <= 0:
                    break
                if key == keep_key:
                    continue
                self._db.execute("DELETE FROM songs WHERE key = ?", (key,))
                deleted.append(file_name)
                overflow -= 1
            self._db.commit()
        for file_name in deleted:
            try:
                (self.cache_dir / file_name).unlink(missing_ok=True)
            except OSError as exc:
                print(f"[music] 删除缓存失败: {exc!r}")
        return deleted

    def scan_local_files(self) -> int:
        """把缓存目录里手动放入的音频文件登记进曲库（文件名按「歌手 - 歌名」解析）。"""
        indexed = 0
        with self._lock:
            known = {
                row[0]
                for row in self._db.execute("SELECT file_name FROM songs").fetchall()
            }
        for path in self.cache_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
                continue
            if path.name in known:
                continue
            stem = path.stem
            if " - " in stem:
                artist, name = stem.split(" - ", 1)
            else:
                artist, name = "", stem
            self.add(
                song_id="",
                name=name.strip(),
                artist=artist.strip(),
                duration_ms=0,
                file_name=path.name,
                source="local",
            )
            indexed += 1
        if indexed:
            print(f"[music] 本地曲库新增 {indexed} 首")
        return indexed

    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM songs").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()
