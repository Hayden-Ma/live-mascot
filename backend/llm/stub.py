import asyncio
import random

from .base import LLMClient

_TEMPLATES = [
    "{nick}好呀，刚刚在听你说话呢，{echo}这个熊家也想聊聊！",
    "收到收到，{nick}说「{echo}」，熊家觉得好有意思呀。",
    "{nick}，你这么一说，熊家都要笑出声啦。",
    "嗯嗯，{nick}说的{echo}，熊家记下啦。",
]


class StubLLM(LLMClient):
    """P0 占位：不调模型，按模板回一句，用来验证分句、TTS、前端播放链路。"""

    async def reply(self, nick: str, text: str, persona: str) -> str:
        await asyncio.sleep(0.3)
        template = random.choice(_TEMPLATES)
        return template.format(nick=nick, echo=text[:12])
