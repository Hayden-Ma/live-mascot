import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator

try:
    # 优先使用旧版接口：Fleck 服务端在新版 asyncio 客户端下偶发只收到第一帧
    from websockets import connect as ws_connect
except ImportError:
    from websockets.asyncio.client import connect as ws_connect

from ..schemas import BarrageMessage, BarrageType


def _ci_get(obj: Any, key: str) -> Any:
    """大小写不敏感地取字段，兼容不同版本的 BarrageGrab 输出。"""
    if not isinstance(obj, dict):
        return None
    if key in obj:
        return obj[key]
    lowered = key.lower()
    for k, v in obj.items():
        if isinstance(k, str) and k.lower() == lowered:
            return v
    return None


def _pick(obj: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for key in path:
            cur = _ci_get(cur, key)
            if cur is None:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


class BarrageGrabSource:
    """连接 BarrageGrab 的本地 WebSocket，把它的 JSON 转成 BarrageMessage。

    BarrageGrab 默认地址 ws://127.0.0.1:8888，消息形如：
        {"Type": "WebcastChatMessage", "Data": {...}}
    这里同时兼容 Type/type、Data/data，并对字段做多路径兜底。
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:8888",
        reconnect_seconds: float = 5.0,
        debug_raw: bool = False,
        handle_like: bool = False,
        debug_limit: int = 200,
        receive_timeout_seconds: float = 45.0,
    ) -> None:
        self.ws_url = ws_url
        self.reconnect_seconds = reconnect_seconds
        self.debug_raw = debug_raw
        self.handle_like = handle_like
        self.debug_limit = debug_limit
        self.receive_timeout_seconds = receive_timeout_seconds
        self._debug_count = 0
        # 诊断计数：收到多少帧、解析出多少条消息（供 /api/dev/status 观察）
        self.frames = 0
        self.yielded = 0
        # 礼物连击去重：抖音在连击结束时会把最后一个单位再发一条
        # （RepeatEnd=1，TotalCount 不变但 MsgId 不同），按 MsgId 去重拦不住。
        # key = (user_id, gift_name) -> (total_count, repeat_end, ts)
        self._gift_progress: dict[tuple[str, str], tuple[int, int, float]] = {}

    async def stream(self) -> AsyncIterator[BarrageMessage]:
        while True:
            try:
                async with ws_connect(
                    # BarrageGrab 的 Fleck 服务器不回 pong，开启 ping 会导致
                    # 连接每 ~40s 被判超时掐断，故禁用心跳，靠 TCP 读错误兜底
                    self.ws_url, ping_interval=None, max_size=None
                ) as ws:
                    print(f"[barrage] connected: {self.ws_url}")
                    # 用显式 recv + 超时重连：Fleck 在某些连接上会停止推送，
                    # async for 会一直挂着；超时后主动断开重连即可恢复。
                    while True:
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(), timeout=self.receive_timeout_seconds
                            )
                        except asyncio.TimeoutError:
                            print(
                                "[barrage] receive timeout, reconnect "
                                f"(frames={self.frames})"
                            )
                            break
                        except asyncio.CancelledError:
                            task = asyncio.current_task()
                            if task is not None and task.cancelling():
                                raise
                            # wait_for 取消 recv 时偶尔会把内部取消冒到外层，
                            # 当作超时重连即可，不能把整条弹幕任务带走
                            print("[barrage] recv cancelled, reconnect")
                            break
                        self.frames += 1
                        message = self._parse(raw)
                        if message is not None:
                            self.yielded += 1
                            yield message
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(
                    f"[barrage] disconnected: {exc!r}; "
                    f"retry in {self.reconnect_seconds}s"
                )
                await asyncio.sleep(self.reconnect_seconds)

    def _type_to_kind(self, raw: Any) -> BarrageType | None:
        # BarrageGrab 抖音消息用数字 Type：1 进场、3 弹幕、4 点赞、5 礼物
        if isinstance(raw, int) or (isinstance(raw, str) and raw.strip().isdigit()):
            code = int(raw)
            if code == 1:
                return BarrageType.ENTER
            if code == 3:
                return BarrageType.COMMENT
            if code == 4:
                return BarrageType.LIKE if self.handle_like else None
            if code == 5:
                return BarrageType.GIFT
            return None

        # 其他平台/版本可能用字符串类型
        low = str(raw or "").lower()
        if "chat" in low:
            return BarrageType.COMMENT
        if "gift" in low:
            return BarrageType.GIFT
        if "like" in low:
            return BarrageType.LIKE if self.handle_like else None
        if "member" in low or "enter" in low:
            return BarrageType.ENTER
        return None

    def _parse(self, raw: Any) -> BarrageMessage | None:
        try:
            payload = json.loads(raw)
        except Exception:
            if self._debug_enabled():
                print(f"[barrage] non-json: {str(raw)[:200]}")
            return None

        mtype_raw = _pick(payload, ("Type",), ("type",), ("MsgType",), ("method",))
        data = _pick(payload, ("Data",), ("data",)) or payload

        if self._debug_enabled():
            snippet = json.dumps(payload, ensure_ascii=False)[:400]
            print(f"[barrage] raw type={mtype_raw} {snippet}")

        kind = self._type_to_kind(mtype_raw)
        if kind is None:
            return None

        nick = _pick(
            data,
            ("User", "Nickname"),
            ("User", "NickName"),
            ("user", "nickname"),
            ("nickname",),
            ("NickName",),
        ) or "观众"
        uid = _pick(
            data,
            ("User", "IdStr"),
            ("User", "Id"),
            ("User", "SecUid"),
            ("user", "id"),
            ("userId",),
            ("user_id",),
        ) or nick
        msg_id = _pick(
            data,
            ("Common", "MsgIdStr"),
            ("Common", "MsgId"),
            ("MsgId",),
            ("msgId",),
            ("msg_id",),
        ) or f"bg-{uuid.uuid4().hex}"

        if kind == BarrageType.COMMENT:
            text = _pick(data, ("Content",), ("content",), ("Text",)) or ""
            text = str(text).strip()
            if not text:
                return None
            return BarrageMessage(
                msg_id=str(msg_id),
                type=kind,
                user_id=str(uid),
                nick=str(nick),
                text=text,
                priority=0,
            )

        if kind == BarrageType.LIKE:
            try:
                like_count = int(_pick(data, ("Count",), ("count",)) or 0)
            except (TypeError, ValueError):
                like_count = 0
            try:
                like_total = int(_pick(data, ("Total",), ("total",)) or 0)
            except (TypeError, ValueError):
                like_total = 0
            # 点赞消息的 MsgId 有时是 0，直接去重会把后续点赞全部丢掉
            if not msg_id or str(msg_id) in ("0", "None"):
                msg_id = f"like-{uuid.uuid4().hex}"
            return BarrageMessage(
                msg_id=str(msg_id),
                type=kind,
                user_id=str(uid),
                nick=str(nick),
                text="点赞了",
                like_count=max(1, like_count),
                like_total=max(0, like_total),
                priority=4,
            )

        if kind == BarrageType.GIFT:
            gift_name = _pick(
                data,
                ("Gift", "Name"),
                ("Gift", "Describe"),
                ("gift", "name"),
                ("GiftName",),
                ("giftName",),
            ) or "礼物"

            # 连击收尾去重：抖音结束连击时会再发一条 RepeatEnd=1 的消息，
            # TotalCount 不变（MsgId 却是新的），不去重就会被当成第二件礼物。
            try:
                total = int(_pick(data, ("TotalCount",), ("totalCount",)) or 0)
            except (TypeError, ValueError):
                total = 0
            try:
                repeat_end = int(_pick(data, ("RepeatEnd",), ("repeatEnd",)) or 0)
            except (TypeError, ValueError):
                repeat_end = 0

            key = (str(uid), str(gift_name))
            now = time.monotonic()
            prev = self._gift_progress.get(key)
            duplicate_end = (
                prev is not None
                and total > 0
                and repeat_end == 1       # 本条是连击收尾消息
                and prev[1] == 0          # 上一条还不是收尾消息（连击进行中）
                and total <= prev[0]      # 礼物数量没有增长
                and now - prev[2] < 10.0  # 仍在同一次连击的时间窗内
            )
            if duplicate_end:
                # 这条不携带新增礼物，只用来告诉下游「本次连击结束了」，
                # 不能再当成一次新礼物去道谢。
                self._gift_progress[key] = (prev[0], 1, now)
            elif total > 0:
                self._gift_progress[key] = (total, repeat_end, now)
                if len(self._gift_progress) > 500:
                    cutoff = now - 60.0
                    self._gift_progress = {
                        k: v for k, v in self._gift_progress.items() if v[2] >= cutoff
                    }

            # 抖音连击时 RepeatCount 是本次连击的累计数量（1、2、4、8…），
            # 合并时取最大值即可，不能把几条累加。
            count = 0 if duplicate_end else 1
            for raw_count in (() if duplicate_end else (
                _pick(data, ("RepeatCount",), ("repeatCount",)),
                _pick(data, ("TotalCount",), ("totalCount",)),
                _pick(data, ("GiftCount",)),
                _pick(data, ("count",)),
            )):
                try:
                    value = int(raw_count)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    count = value
                    break
            return BarrageMessage(
                msg_id=str(msg_id),
                type=kind,
                user_id=str(uid),
                nick=str(nick),
                gift_name=str(gift_name),
                gift_count=count,
                gift_combo_end=repeat_end == 1,
                priority=10,
            )

        return BarrageMessage(
            msg_id=str(msg_id),
            type=BarrageType.ENTER,
            user_id=str(uid),
            nick=str(nick),
            text="进入了直播间",
            priority=5,
        )

    def _debug_enabled(self) -> bool:
        if not self.debug_raw or self._debug_count >= self.debug_limit:
            return False
        self._debug_count += 1
        return True
