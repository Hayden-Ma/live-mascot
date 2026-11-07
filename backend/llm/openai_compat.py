import httpx

from .base import LLMClient

_FALLBACK = "嗯……熊家刚刚走神啦，你再跟熊家说一遍好不好呀？"


class OpenAICompatibleLLM(LLMClient):
    """OpenAI Chat Completions 兼容客户端。

    可对接 MiniMax、DeepSeek、豆包方舟、Ollama、vLLM 等，
    只需改 config 里的 base_url / model / api_key_env。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.8,
        max_tokens: int = 200,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=timeout)

    async def reply(self, nick: str, text: str, persona: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": persona},
                {"role": "user", "content": f"{nick}说：{text}"},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        # 本地 Ollama/vLLM 通常无需鉴权
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[llm] 请求失败: {exc!r}")
            return _FALLBACK

        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            print(f"[llm] 返回错误: {base_resp}")
            return _FALLBACK

        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
        content = content.strip()
        return content or _FALLBACK

    async def aclose(self) -> None:
        await self._client.aclose()
