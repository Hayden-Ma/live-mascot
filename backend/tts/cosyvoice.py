import base64
import io
import wave
from typing import Any

import httpx

from .base import TTSEngine


def _wav_duration_ms(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return int(wav.getnframes() / wav.getframerate() * 1000)


class CosyVoiceTTS(TTSEngine):
    """调用 GPU 服务器上的 CosyVoice2 服务，返回 data URL。

    服务端部署见 scripts/remote_tts_server.py。
    """

    def __init__(
        self,
        base_url: str,
        voice: str = "default",
        speed: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        self.voice = voice
        self.speed = speed
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def synth(self, text: str, voice: dict[str, Any] | None = None) -> tuple[str | None, int]:
        voice_id = (voice or {}).get("voice_id") or self.voice
        resp = await self._client.post(
            "/tts", json={"text": text, "voice": voice_id, "speed": self.speed}
        )
        resp.raise_for_status()

        duration_ms = int(float(resp.headers.get("X-Audio-Seconds", "0")) * 1000)
        if duration_ms <= 0:
            duration_ms = _wav_duration_ms(resp.content)

        audio = "data:audio/wav;base64," + base64.b64encode(resp.content).decode()
        return audio, duration_ms

    async def aclose(self) -> None:
        await self._client.aclose()
