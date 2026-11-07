from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHARACTERS_DIR = ROOT / "characters"

_STICKER_EXTS = {".png", ".gif", ".webp", ".jpg", ".jpeg"}


def _sticker_url(character_id: str, relative: str) -> str:
    return f"/characters/{character_id}/stickers/{quote(relative)}"


def _scan_stickers(character_id: str) -> tuple[dict[str, str], list[str]]:
    """礼物表情包按文件名（= 礼物名）映射；round/ 下为随机氛围表情。"""
    base = CHARACTERS_DIR / character_id / "stickers"
    stickers: dict[str, str] = {}
    round_stickers: list[str] = []

    if base.is_dir():
        for f in sorted(base.iterdir()):
            if f.is_file() and f.suffix.lower() in _STICKER_EXTS:
                stickers[f.stem] = _sticker_url(character_id, f.name)

    round_dir = base / "round"
    if round_dir.is_dir():
        for f in sorted(round_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in _STICKER_EXTS:
                round_stickers.append(_sticker_url(character_id, f"round/{f.name}"))

    return stickers, round_stickers


def load_character(character_id: str) -> dict:
    path = CHARACTERS_DIR / character_id / "character.yaml"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("id", character_id)

    stickers, round_stickers = _scan_stickers(character_id)
    data["stickers"] = stickers
    data["round_stickers"] = round_stickers
    # 没有对应表情的礼物统一播这张图（默认取 stickers/感谢.gif）
    data["default_gift_sticker"] = stickers.get("感谢")
    return data
