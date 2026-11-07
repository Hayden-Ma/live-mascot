from abc import ABC, abstractmethod
from typing import Any


class TTSEngine(ABC):
    """语音合成。返回 (音频地址或 data URL, 时长毫秒)；无音频时第一项为 None。"""

    @abstractmethod
    async def synth(self, text: str, voice: dict[str, Any] | None = None) -> tuple[str | None, int]:
        raise NotImplementedError
