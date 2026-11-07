from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

from .loader import CHARACTERS_DIR

_STICKER_EXTS = {".gif", ".png", ".webp", ".jpg", ".jpeg"}

# 匹配前统一去掉量词/语气词，让「跳个舞」「跳支舞」也能命中「跳舞」。
# 只影响用于比对的文本，不影响日志与提示词里的原文。
_FILLER_CHARS = set("个支首场次下一点些曲的啦呀啊吧呢吗嘛哦噢喔咯呗哈嗯么")


def normalize(text: str) -> str:
    return "".join(
        ch for ch in text.lower() if ch.isalnum() and ch not in _FILLER_CHARS
    )


@dataclass(frozen=True)
class StickerHit:
    name: str
    url: str

    def prompt_hint(self) -> str:
        return f"\n（熊友提到了「{self.name}」，你正在播放{self.name}的表情包，用一两句话配合互动）"


class KeywordStickers:
    """弹幕关键词 -> 表情图片。

    只扫描 characters/<角色>/stickers/<directory>/ 下的图片，图片文件名即关键词；
    可在同目录放 keywords.yaml 追加别名：

        跳舞: [舞蹈, 跳起来]

    命中后像收到礼物一样把图片推给前端播放。
    """

    def __init__(
        self,
        character_id: str,
        directory: str = "tigger",
        cooldown_seconds: float = 4.0,
    ) -> None:
        self.character_id = character_id
        self.directory = directory
        self.cooldown_seconds = cooldown_seconds
        self._last_at = 0.0
        # (归一化关键词, 图片名, url)，长关键词优先，避免短词抢先命中
        self._keywords: list[tuple[str, str, str]] = []
        self._load()

    @property
    def base_dir(self) -> Path:
        return CHARACTERS_DIR / self.character_id / "stickers" / self.directory

    def _load(self) -> None:
        base = self.base_dir
        if not base.is_dir():
            print(f"[stickers] 关键词图片目录不存在: {base}")
            return

        aliases = self._load_aliases(base / "keywords.yaml")
        entries: list[tuple[str, str, str]] = []
        names: set[str] = set()
        for f in sorted(base.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _STICKER_EXTS:
                continue
            name = f.stem
            names.add(name)
            url = (
                f"/characters/{quote(self.character_id)}"
                f"/stickers/{quote(f'{self.directory}/{f.name}')}"
            )
            for word in [name, *aliases.get(name, [])]:
                key = normalize(word)
                if key:
                    entries.append((key, name, url))

        entries.sort(key=lambda item: len(item[0]), reverse=True)
        self._keywords = entries
        print(
            f"[stickers] 已加载 {len(names)} 个关键词表情"
            f"（{self.directory}/，共 {len(entries)} 个关键词）"
        )

    @staticmethod
    def _load_aliases(path: Path) -> dict[str, list[str]]:
        if not path.is_file():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            print(f"[stickers] 别名文件解析失败: {exc!r}")
            return {}
        aliases: dict[str, list[str]] = {}
        for name, words in data.items():
            if isinstance(words, str):
                words = [words]
            if isinstance(words, list):
                aliases[str(name)] = [str(w) for w in words]
        return aliases

    def match(self, text: str) -> StickerHit | None:
        """命中返回图片信息；冷却期内的重复命中直接忽略。"""
        if not self._keywords or not text:
            return None
        now = time.monotonic()
        if now - self._last_at < self.cooldown_seconds:
            return None
        norm = normalize(text)
        if not norm:
            return None
        for key, name, url in self._keywords:
            if key in norm:
                self._last_at = now
                return StickerHit(name=name, url=url)
        return None
