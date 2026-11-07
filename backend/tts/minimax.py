import asyncio
import base64
import time
from typing import Any

import httpx

from .base import TTSEngine

_RATE_LIMIT_CODE = 1002


def _estimate_ms(text: str) -> int:
    return max(800, min(8000, int(len(text) * 200)))


class MinimaxTTS(TTSEngine):
    """MiniMax 语音合成，返回 data URL，前端可直接播放。

    内置节流与限流重试：并发数、最小请求间隔可配，避免触发 RPM 限制。
    """

    def __init__(
        self,
        api_key: str,
        group_id: str = "",
        model: str = "speech-2.8-turbo",
        voice_id: str = "",
        speed: float = 1.0,
        base_url: str = "https://api.minimax.chat/v1/t2a_v2",
        timeout: float = 30.0,
        concurrency: int = 1,
        min_interval: float = 0.8,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.group_id = group_id
        self.model = model
        self.voice_id = voice_id
        self.speed = speed
        self.base_url = base_url
        self.min_interval = max(0.0, min_interval)
        self.max_retries = max(0, max_retries)
        self._client = httpx.AsyncClient(timeout=timeout)
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._pace_lock = asyncio.Lock()
        self._last_request = 0.0

    async def _pace(self) -> None:
        async with self._pace_lock:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _post(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"GroupId": self.group_id} if self.group_id else None
        async with self._sem:
            await self._pace()
            resp = await self._client.post(
                self.base_url, json=payload, headers=headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def synth(self, text: str, voice: dict[str, Any] | None = None) -> tuple[str | None, int]:
        if not text.strip():
            return None, 0

        voice_id = (voice or {}).get("voice_id") or self.voice_id
        if not self.api_key or not voice_id:
            print("[tts] minimax 缺少 api_key 或 voice_id")
            return None, _estimate_ms(text)

        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": self.speed,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        data: dict | None = None
        for attempt in range(self.max_retries + 1):
            try:
                data = await self._post(payload)
            except Exception as exc:
                print(f"[tts] minimax 请求失败: {exc!r}")
                if attempt < self.max_retries:
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                return None, _estimate_ms(text)

            base_resp = data.get("base_resp") or {}
            code = base_resp.get("status_code", 0)
            if code == 0:
                break
            if code == _RATE_LIMIT_CODE and attempt < self.max_retries:
                wait = 1.0 * (attempt + 1)
                print(f"[tts] minimax 限流，{wait:.1f}s 后重试 ({attempt + 1}/{self.max_retries})")
                await asyncio.sleep(wait)
                continue
            print(f"[tts] minimax 返回错误: {base_resp}")
            return None, _estimate_ms(text)

        if data is None:
            return None, _estimate_ms(text)

        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            print("[tts] minimax 返回空音频")
            return None, _estimate_ms(text)

        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError:
            print("[tts] minimax 音频不是 hex 编码")
            return None, _estimate_ms(text)

        extra = data.get("extra_info") or {}
        duration_ms = int(extra.get("audio_length") or _estimate_ms(text))
        audio = "data:audio/mp3;base64," + base64.b64encode(audio_bytes).decode()
        return audio, duration_ms

    async def aclose(self) -> None:
        await self._client.aclose()
