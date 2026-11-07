import asyncio
import random
import uuid
from typing import AsyncIterator

from ..schemas import BarrageMessage, BarrageType


class FakeBarrageSource:
    """P0 阶段用假数据驱动整条链路，便于先验证前端与流水线。"""

    def __init__(self, interval: tuple[float, float] = (2.0, 4.5), seed: int | None = None):
        self._interval = interval
        self._rand = random.Random(seed)
        self._users = ["小明", "阿桃", "云朵", "夜猫", "橘子", "大熊", "小鹿"]
        self._comments = [
            "布布晚上好",
            "今天好可爱呀",
            "你吃饭了吗",
            "唱首歌吧",
            "布布会什么才艺",
            "好想抱抱你",
            "你在干嘛呀",
        ]
        self._gifts = ["小心心", "玫瑰", "棒棒糖"]

    async def stream(self) -> AsyncIterator[BarrageMessage]:
        while True:
            await asyncio.sleep(self._rand.uniform(*self._interval))
            yield self._make()

    def _make(self) -> BarrageMessage:
        nick = self._rand.choice(self._users)
        roll = self._rand.random()

        if roll < 0.12:
            gift = self._rand.choice(self._gifts)
            count = self._rand.choice([1, 1, 5, 10])
            return BarrageMessage(
                msg_id=str(uuid.uuid4()),
                type=BarrageType.GIFT,
                user_id=nick,
                nick=nick,
                gift_name=gift,
                gift_count=count,
                priority=10,
            )

        if roll < 0.22:
            return BarrageMessage(
                msg_id=str(uuid.uuid4()),
                type=BarrageType.ENTER,
                user_id=nick,
                nick=nick,
                text="进入了直播间",
                priority=5,
            )

        if roll < 0.32:
            return BarrageMessage(
                msg_id=str(uuid.uuid4()),
                type=BarrageType.LIKE,
                user_id=nick,
                nick=nick,
                text="点赞了",
                like_count=self._rand.choice([1, 1, 2, 5, 10]),
                priority=4,
            )

        return BarrageMessage(
            msg_id=str(uuid.uuid4()),
            type=BarrageType.COMMENT,
            user_id=nick,
            nick=nick,
            text=self._rand.choice(self._comments),
            priority=0,
        )
