import asyncio
from pathlib import Path
from urllib.parse import urlparse

import httpx


class NeteaseError(Exception):
    """网易云接口异常，message 会直接播报给观众。"""


class NeteaseClient:
    """自部署 NeteaseCloudMusicApi 的轻量客户端。

    搜歌不需要登录；解析 VIP/高音质地址需要 Cookie，
    Cookie 从环境变量读取后以请求头透传。
    """

    def __init__(self, base_url: str, cookie: str = "", timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie = cookie
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Cookie": self.cookie} if self.cookie else {}

    async def login_status(self) -> dict:
        try:
            resp = await self._client.get(
                f"{self.base_url}/login/status", headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise NeteaseError(f"网易云服务不可用：{exc!r}") from exc

    async def search(self, keyword: str, limit: int = 5) -> list[dict]:
        try:
            resp = await self._client.get(
                f"{self.base_url}/cloudsearch",
                params={"keywords": keyword, "type": 1, "limit": limit},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise NeteaseError(f"网易云搜索失败：{exc!r}") from exc

        songs = ((data.get("result") or {}).get("songs")) or []
        results: list[dict] = []
        for song in songs:
            artists = song.get("ar") or song.get("artists") or []
            artist_name = " / ".join(
                str(a.get("name")) for a in artists if isinstance(a, dict) and a.get("name")
            )
            duration_ms = song.get("dt") or song.get("duration") or 0
            results.append(
                {
                    "id": str(song.get("id") or ""),
                    "name": str(song.get("name") or "").strip(),
                    "artist": artist_name,
                    "duration_ms": int(duration_ms or 0),
                }
            )
        return [r for r in results if r["id"] and r["name"]]

    async def song_url(self, song_id: str, level: str) -> str | None:
        """解析播放地址。

        网易云偶发返回 -460「网络环境存在风险」，属于瞬时风控，
        重试通常即可成功；这里每个音质重试几次，高音质仍拿不到再回退 standard。
        """
        last_error: Exception | None = None
        for try_level in (level, "standard"):
            for attempt in range(3):
                try:
                    resp = await self._client.get(
                        f"{self.base_url}/song/url/v1",
                        params={"id": song_id, "level": try_level},
                        headers=self._headers,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data") or []
                except Exception as exc:
                    # -460 等风控错误：短暂退避后重试同一音质
                    last_error = exc
                    await asyncio.sleep(0.3 + attempt * 0.5)
                    continue
                if data and data[0].get("url"):
                    return str(data[0]["url"])
                # 请求成功但地址为空：多半是版权/会员限制，换下一个音质
                last_error = None
                break
        if last_error is not None:
            raise NeteaseError(f"获取播放地址失败：{last_error!r}")
        return None

    async def download(self, url: str, dest: Path) -> int:
        """下载到临时文件，校验大小后原子替换；返回文件大小。"""
        tmp = dest.with_suffix(dest.suffix + ".part")
        total = 0
        try:
            async with self._client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://music.163.com/",
                },
                timeout=40.0,
            ) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "text" in content_type:
                    raise NeteaseError("下载返回了文本内容，可能被版权限制")
                with tmp.open("wb") as handle:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        handle.write(chunk)
                        total += len(chunk)
        except NeteaseError:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise NeteaseError(f"下载失败：{exc!r}") from exc

        if total < 30_000:
            tmp.unlink(missing_ok=True)
            raise NeteaseError("下载内容过小，可能没有播放权限")
        tmp.replace(dest)
        return total

    async def close(self) -> None:
        await self._client.aclose()


def guess_ext(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"} else ".mp3"
