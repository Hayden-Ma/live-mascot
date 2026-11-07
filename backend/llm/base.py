from abc import ABC, abstractmethod


class LLMClient(ABC):
    """对话生成。P0 返回整段文本，后续接云端时改为流式分句。"""

    @abstractmethod
    async def reply(self, nick: str, text: str, persona: str) -> str:
        raise NotImplementedError
