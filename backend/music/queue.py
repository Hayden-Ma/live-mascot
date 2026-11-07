from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


@dataclass
class Song:
    key: str
    song_id: str
    name: str
    artist: str
    duration_ms: int
    path: Path
    source: str = "netease"
    requested_by: str = ""
    requested_by_id: str = ""

    @property
    def url(self) -> str:
        return f"/music/{quote(self.path.name)}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "song_id": self.song_id,
            "name": self.name,
            "artist": self.artist,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "requested_by": self.requested_by,
            "url": self.url,
        }


@dataclass
class SongQueue:
    """点歌队列：去重、每人待播上限、礼物插队。"""

    max_size: int = 8
    per_user_pending: int = 1
    _items: list[Song] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self._items)

    def snapshot(self) -> list[dict]:
        return [song.to_dict() for song in self._items]

    def has_key(self, key: str) -> bool:
        return any(song.key == key for song in self._items)

    def pending_of_user(self, user_id: str) -> int:
        return sum(1 for song in self._items if song.requested_by_id == user_id)

    def add(self, song: Song) -> tuple[bool, str]:
        if self.has_key(song.key):
            return False, "这首已经在队列里啦"
        if len(self._items) >= self.max_size:
            return False, "点歌队列满啦，等一会儿再点吧"
        if self.pending_of_user(song.requested_by_id) >= self.per_user_pending:
            return False, "你点的歌还在排队，等它播完再点吧"
        self._items.append(song)
        return True, ""

    def pop(self) -> Song | None:
        if not self._items:
            return None
        return self._items.pop(0)

    def promote_user(self, user_id: str) -> Song | None:
        """礼物插队：把该观众排队中的第一首移到最前面。"""
        for index, song in enumerate(self._items):
            if song.requested_by_id == user_id:
                if index == 0:
                    return None
                self._items.insert(0, self._items.pop(index))
                return song
        return None
