import asyncio
import os
import re
import time
from pathlib import Path
from typing import Awaitable, Callable

from ..schemas import BarrageMessage
from ..ws.hub import Hub
from .library import MusicLibrary, safe_filename
from .netease import NeteaseClient, NeteaseError, guess_ext
from .queue import Song, SongQueue

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# 点歌指令：点歌 / 点播 / 来一首，歌名可带书名号
_COMMAND = re.compile(r"^(?:点歌|点播|来一首)\s*[：:,，]?\s*(.*)$")
_QUOTES = str.maketrans("", "", "《》「」“”\"'")

_SONG_ERRORS = (
    "没找到这首歌，换个歌名试试～",
    "这首歌暂时没法播放，可能是版权或会员限制～",
)


class SongError(Exception):
    pass


class DuplicateSong(SongError):
    """这首歌已经在播放或歌单里，用固定话术回复，不走大模型。"""


def already_queued_reply(song_name: str) -> str:
    return f"《{song_name}》已经在歌单里了，请耐心等待。"


def parse_command(text: str) -> str | None:
    """匹配点歌指令，返回歌名（可能为空字符串）；不是点歌返回 None。"""
    matched = _COMMAND.match((text or "").strip())
    if not matched:
        return None
    return matched.group(1).translate(_QUOTES).strip()


class MusicService:
    """点歌业务：本地曲库 → 网易云搜索 → 下载入缓存 → 排队播放。"""

    def __init__(self, hub: Hub, config: dict) -> None:
        self.hub = hub
        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.cache_dir = Path(str(config.get("cache_dir", "E:/stream-music"))).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.library = MusicLibrary(self.cache_dir)
        self.library.scan_local_files()

        self.client = NeteaseClient(
            base_url=str(config.get("api_base", "http://127.0.0.1:3000")),
            cookie=os.environ.get(str(config.get("cookie_env", "NETEASE_COOKIE")), "")
            or str(config.get("cookie", "")),
        )
        self._cookie_env = str(config.get("cookie_env", "NETEASE_COOKIE"))
        self._cookie_fallback = str(config.get("cookie", ""))
        try:
            self._env_mtime = _ENV_FILE.stat().st_mtime
        except OSError:
            self._env_mtime = 0.0
        self.queue = SongQueue(
            max_size=int(config.get("max_queue", 8)),
            per_user_pending=int(config.get("per_user_pending", 1)),
        )

        self.say: Callable[[str, str], Awaitable[None]] | None = None
        self._current: Song | None = None
        self._last_key = ""
        self._finished: asyncio.Event | None = None
        self._has_songs = asyncio.Event()
        self._handle_lock = asyncio.Lock()
        self._last_request: dict[str, float] = {}

    # ---------- 对外接口 ----------

    def is_command(self, text: str) -> bool:
        return parse_command(text) is not None

    def now_playing(self) -> Song | None:
        return self._current

    def now_playing_hint(self) -> str:
        if not self._current:
            return ""
        return f"《{self._current.name}》{self._current.artist}".strip()

    def snapshot(self) -> dict:
        return {
            "enabled": self.enabled,
            "current": self._current.to_dict() if self._current else None,
            "queue": self.queue.snapshot(),
        }

    async def broadcast_queue(self) -> None:
        await self.hub.broadcast(
            {
                "type": "song_queue",
                "current": self._current.to_dict() if self._current else None,
                "queue": self.queue.snapshot(),
            }
        )

    async def promote_user(self, user_id: str) -> str | None:
        """礼物插队；返回被提前的歌名，供主播道谢时点名。"""
        song = self.queue.promote_user(user_id)
        if song is None:
            return None
        await self.broadcast_queue()
        return song.name

    def mark_finished(self, song_id: str) -> None:
        if self._current is None or self._current.key != song_id:
            return
        if self._finished is not None:
            self._finished.set()

    async def handle_request(self, msg: BarrageMessage) -> None:
        """处理一条点歌弹幕（后台任务，不阻塞弹幕流水线）。"""
        query = parse_command(msg.text)
        if query is None or not query:
            await self._notice("想听什么歌呀？发送「点歌 歌名」就可以啦")
            return
        if not self.enabled:
            return

        print(f"[music] 点歌请求: {msg.nick} -> {query}")
        self._refresh_cookie()

        async with self._handle_lock:
            now = time.monotonic()
            cooldown = float(self.config.get("user_cooldown_seconds", 30))
            last = self._last_request.get(msg.user_id, 0.0)
            if now - last < cooldown:
                await self._notice(f"{msg.nick} 点歌太频繁啦，等一会儿再点吧")
                return
            if self.queue.pending_of_user(msg.user_id) >= self.queue.per_user_pending:
                await self._notice("你点的歌还在排队，等它播完再点吧")
                return
            if len(self.queue) >= self.queue.max_size:
                await self._notice("点歌队列满啦，等一会儿再点吧")
                return

            self._last_request[msg.user_id] = now
            try:
                song = await self._resolve(query, msg)
            except DuplicateSong as exc:
                print(f"[music] 重复点歌: {msg.nick} -> {query}: {exc}")
                if self.say is not None:
                    asyncio.create_task(self.say(msg.nick, str(exc)))
                return
            except SongError as exc:
                print(f"[music] 点歌失败: {msg.nick} -> {query}: {exc}")
                await self._notice(str(exc))
                return
            except Exception as exc:  # 单次点歌失败不能影响直播间
                print(f"[music] 点歌失败: {exc!r}")
                await self._notice(_SONG_ERRORS[1])
                return

            if self.queue.has_key(song.key):
                reply = already_queued_reply(song.name)
                print(f"[music] 重复点歌: {msg.nick} -> {song.name}")
                if self.say is not None:
                    asyncio.create_task(self.say(msg.nick, reply))
                return

            ok, reason = self.queue.add(song)
            if not ok:
                await self._notice(reason)
                return

            self._has_songs.set()
            await self.broadcast_queue()
            ahead = len(self.queue) - 1 + (1 if self._current else 0)
            if ahead <= 0:
                reply = f"收到{msg.nick}点的《{song.name}》，马上播放～"
            else:
                reply = f"《{song.name}》已经排进歌单啦，前面还有{ahead}首～"
            await self._notice(f"【点歌】{msg.nick} 点了《{song.name}》- {song.artist}")
            if self.say is not None:
                # 播报不占用点歌锁，避免语音合成拖慢后续点歌
                asyncio.create_task(self.say(msg.nick, reply))

    async def run(self) -> None:
        """播放调度：依次播放队列里的歌，等前端播完回调后换下一首。"""
        while True:
            song = self.queue.pop()
            if song is None:
                # 没人点歌时从本地曲库随机挑一首，避免直播间一直安静
                song = self._pick_idle_song()
                if song is None:
                    self._has_songs.clear()
                    await self._has_songs.wait()
                    continue

            self._current = song
            self._last_key = song.key
            self.library.touch(song.key)
            self._finished = asyncio.Event()
            await self.broadcast_queue()
            await self.hub.broadcast(
                {"type": "song_start", "song": song.to_dict(), "url": song.url}
            )
            print(f"[music] 开始播放: {song.name} - {song.artist}")

            timeout = (song.duration_ms / 1000 if song.duration_ms else 240) + 20
            try:
                await asyncio.wait_for(self._finished.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                print(f"[music] 播放超时，跳过: {song.name}")

            self._finished = None
            self._current = None
            await self.hub.broadcast({"type": "song_end", "song": song.to_dict()})
            await self.broadcast_queue()

    async def close(self) -> None:
        await self.client.close()
        self.library.close()

    # ---------- 内部实现 ----------

    def _refresh_cookie(self) -> None:
        """修改 .env 后无需重启后端，下一次点歌时自动重新读取 Cookie。"""
        if load_dotenv is None:
            return
        try:
            mtime = _ENV_FILE.stat().st_mtime
        except OSError:
            return
        if mtime == self._env_mtime:
            return
        self._env_mtime = mtime
        try:
            load_dotenv(_ENV_FILE, override=True)
        except Exception:
            return
        cookie = os.environ.get(self._cookie_env, "") or self._cookie_fallback
        if cookie != self.client.cookie:
            self.client.cookie = cookie
            print("[music] 已从 .env 重新加载网易云 Cookie")

    async def _notice(self, text: str) -> None:
        await self.hub.broadcast(
            {"type": "chat", "user": {"nick": "点歌台"}, "text": text}
        )

    async def _resolve(self, query: str, msg: BarrageMessage) -> Song:
        """先查本地曲库，再走网易云搜索下载。"""
        threshold = float(self.config.get("local_match_threshold", 0.55))
        local = self.library.find(query, threshold)
        if local is not None:
            song = Song(
                key=local.key,
                song_id=local.song_id,
                name=local.name,
                artist=local.artist,
                duration_ms=local.duration_ms,
                path=local.path,
                source="local",
                requested_by=msg.nick,
                requested_by_id=msg.user_id,
            )
            self._ensure_not_playing(song)
            return song

        limit = int(self.config.get("search_limit", 5))
        results = await self.client.search(query, limit)
        if not results:
            raise SongError(_SONG_ERRORS[0])

        chosen = self._pick_result(results, query)
        max_seconds = float(self.config.get("max_duration_seconds", 420))
        duration_ms = int(chosen["duration_ms"] or 0)
        if duration_ms and duration_ms / 1000 > max_seconds:
            raise SongError("这首歌太长啦，换一首短一点的吧～")

        cached = self.library.get_by_song_id(chosen["id"])
        if cached is not None and cached.path.exists():
            song = Song(
                key=cached.key,
                song_id=cached.song_id,
                name=cached.name or chosen["name"],
                artist=cached.artist or chosen["artist"],
                duration_ms=cached.duration_ms or duration_ms,
                path=cached.path,
                source="local",
                requested_by=msg.nick,
                requested_by_id=msg.user_id,
            )
            self._ensure_not_playing(song)
            return song

        url = await self.client.song_url(chosen["id"], str(self.config.get("level", "exhigh")))
        if not url:
            raise SongError(_SONG_ERRORS[1])

        ext = guess_ext(url)
        file_name = (
            f"{safe_filename(chosen['name'])}-{safe_filename(chosen['artist'])}-"
            f"{chosen['id']}{ext}"
        )
        dest = self.cache_dir / file_name
        try:
            await self.client.download(url, dest)
        except NeteaseError as exc:
            raise SongError(str(exc)) from exc

        self.library.add(
            song_id=chosen["id"],
            name=chosen["name"],
            artist=chosen["artist"],
            duration_ms=duration_ms,
            file_name=file_name,
            source="netease",
        )
        self.library.prune(int(self.config.get("max_cache_songs", 200)), keep_key=f"netease:{chosen['id']}")

        song = Song(
            key=f"netease:{chosen['id']}",
            song_id=chosen["id"],
            name=chosen["name"],
            artist=chosen["artist"],
            duration_ms=duration_ms,
            path=dest,
            source="netease",
            requested_by=msg.nick,
            requested_by_id=msg.user_id,
        )
        self._ensure_not_playing(song)
        return song

    def _pick_idle_song(self) -> Song | None:
        """空闲时从本地曲库随机挑一首（不与上一首重复）。"""
        local = self.library.random_song(exclude_key=self._last_key)
        if local is None:
            # 曲库只有一首歌时允许重复播放
            local = self.library.random_song()
        if local is None:
            return None
        return Song(
            key=local.key,
            song_id=local.song_id,
            name=local.name,
            artist=local.artist,
            duration_ms=local.duration_ms,
            path=local.path,
            source=local.source,
        )

    def _ensure_not_playing(self, song: Song) -> None:
        if self._current is not None and self._current.key == song.key:
            raise DuplicateSong(already_queued_reply(song.name))

    def _pick_result(self, results: list[dict], query: str) -> dict:
        """优先选同名/开头相同的搜索结果，否则用第一条。"""
        from .library import normalize

        query_n = normalize(query)
        for item in results:
            if normalize(item["name"]) == query_n:
                return item
        for item in results:
            name_n = normalize(item["name"])
            if query_n in name_n or name_n in query_n:
                return item
        return results[0]
