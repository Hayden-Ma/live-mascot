import asyncio

from .base import TTSEngine


class SilentTTS(TTSEngine):
    """P0 占位：不生成音频，只按时长估算，前端口型/气泡按 duration_ms 播放。

    后续接云端 TTS 时，用真实音频地址替换第一个返回值即可。
    """

    async def synth(self, text: str, voice: dict | None = None) -> tuple[str | None, int]:
        duration = max(800, min(6000, int(len(text) * 180)))
        await asyncio.sleep(0.1)
        return None, duration
