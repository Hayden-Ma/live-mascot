import asyncio
import random
import re
import time
from collections import defaultdict

from ..llm.base import LLMClient
from ..schemas import BarrageMessage, BarrageType
from ..tts.base import TTSEngine
from ..ws.hub import Hub

# 在句末标点后切分，便于逐句合成、边播边出字幕
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])")

# 只有「布布 + 位置类关键词」同时出现才强制回答去向，
# 其余提到布布的弹幕正常交给 LLM 自由发挥
_BUBU_LOCATION = re.compile(r"在哪里|在哪|去哪了|在什么地方")
_BUBU_REPLIES = (
    "布布出去打工赚熊熊币啦～要晚一点才回来哦。",
    "布布在别的地方睡觉觉呢～熊家也有一点想他啦。",
)

# 进场欢迎 / 点赞道谢的随机话术（语音按间隔限流，避免刷屏烧 TTS）
_WELCOME_REPLIES = (
    "欢迎熊友{nick}来到熊家的小屋，快坐到软乎乎的毯子上呀！",
    "哎呀，熊友{nick}回来啦，熊家给你留了小蛋糕哦！",
    "熊友{nick}欢迎欢迎，熊家好想你呀！",
)
_LIKE_REPLIES = (
    "谢谢熊友们的点赞，熊家心里甜甜的！",
    "收到好多小心心啦，熊家开心得转圈圈～",
    "点赞的熊友都是熊家的好朋友，谢谢你们呀！",
)


def forced_bubu_reply(text: str) -> str | None:
    if "布布" not in text or not _BUBU_LOCATION.search(text):
        return None
    return random.choice(_BUBU_REPLIES)


def segment(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    return parts or [text]


class Pipeline:
    """弹幕 -> 去重/限流/优先级排队 -> LLM -> 分句 TTS -> 广播给前端。"""

    def __init__(
        self,
        hub: Hub,
        llm: LLMClient,
        tts: TTSEngine,
        persona: str,
        config: dict,
        keyword_stickers=None,
    ) -> None:
        self.hub = hub
        self.llm = llm
        self.tts = tts
        self.persona = persona
        self.config = config
        # 关键词表情（如「跳舞」「杂技」）；命中后像礼物一样推图给前端
        self.keyword_stickers = keyword_stickers
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = 0
        self._seen: set[str] = set()
        self._last_user: dict[str, float] = defaultdict(float)
        # 进场/点赞的语音限流时间戳：视觉互动全部广播，只有语音按间隔限流
        self._last_enter_submitted = 0.0
        self._last_welcome_spoken = 0.0
        self._last_like_thanked = 0.0
        self._like_total = 0
        # 同一观众 5 秒内同种礼物的合并记录：key = user_id|gift_name
        self._recent_gifts: dict[str, dict] = {}
        # 由 main 注入的点歌服务；用于指令拦截、礼物插队和 LLM 上下文
        self.music = None

    def submit(self, msg: BarrageMessage) -> None:
        now = time.monotonic()
        if msg.msg_id in self._seen:
            return
        if msg.type == BarrageType.ENTER:
            if not self.config.get("handle_enter", False):
                return
            # 真实直播间进场非常密集，按间隔抽样交给前端展示，避免刷屏
            interval = float(self.config.get("enter_display_interval_seconds", 2.0))
            if now - self._last_enter_submitted < interval:
                return
            self._last_enter_submitted = now
        if msg.type == BarrageType.COMMENT:
            is_song = self.music is not None and self.music.is_command(msg.text)
            if not is_song:
                if now - self._last_user[msg.user_id] < self.config["user_cooldown_seconds"]:
                    return
                if self._queue.qsize() >= self.config["max_queue"]:
                    return
            else:
                # 点歌指令比普通弹幕优先，且不受普通队列上限约束
                msg.priority = max(msg.priority, 9)

        if len(self._seen) > 5000:
            self._seen.clear()
        self._seen.add(msg.msg_id)
        self._last_user[msg.user_id] = now

        self._seq += 1
        # PriorityQueue 是小顶堆，取负号让高优先级先出
        self._queue.put_nowait((-msg.priority, self._seq, now, msg))

    async def run(self) -> None:
        while True:
            _, _, enqueued_at, msg = await self._queue.get()
            age = time.monotonic() - enqueued_at
            is_song = self.music is not None and self.music.is_command(msg.text)
            if age > self.config["stale_drop_seconds"] and msg.priority < 10 and not is_song:
                continue
            try:
                await self._handle(msg, enqueued_at)
            except Exception as exc:  # 单条失败不能拖垮整条流水线
                print(f"[pipeline] handle error: {exc!r}")

    def _prune_recent_gifts(self, now: float, window: float) -> None:
        if len(self._recent_gifts) < 200:
            return
        expired = [k for k, v in self._recent_gifts.items() if now - v["ts"] >= window]
        for k in expired:
            self._recent_gifts.pop(k, None)

    async def _handle(self, msg: BarrageMessage, arrived_at: float) -> None:
        show_text = True
        if msg.type == BarrageType.GIFT:
            window = float(self.config.get("gift_merge_seconds", 5.0))
            key = f"{msg.user_id}|{msg.gift_name}"
            record = self._recent_gifts.get(key)
            # 合并窗口必须按「消息到达时间」算：礼物进来后要排队等上一条的
            # TTS 合成和播报（常常超过 5 秒），若按处理时间算，同一次连击会被
            # 当成一条条新礼物，反复道谢。
            within_window = record is not None and arrived_at - record["ts"] < window
            # 连击还没结束（没收到 RepeatEnd）时，即使两条消息间隔较久也继续合并，
            # 但最多跨 30 秒，避免异常数据导致永远不再道谢。
            combo_ongoing = (
                record is not None
                and record.get("combo")
                and arrived_at - record["ts"] < 30.0
            )

            if within_window or combo_ongoing:
                # 同一观众连送同种礼物：只累计数量，不重复播放、不重复道谢。
                if msg.gift_count > 0:
                    # 抖音的 RepeatCount 是连击累计数量，取最大值而非相加
                    record["count"] = max(record["count"], msg.gift_count)
                record["ts"] = arrived_at
                record["combo"] = not msg.gift_combo_end
                await self.hub.broadcast(
                    {
                        "type": "gift",
                        "user": {"nick": msg.nick},
                        "gift": msg.gift_name,
                        "count": record["count"],
                        "merged": True,
                    }
                )
                return

            # 连击收尾的重复消息（没有可合并的记录）直接丢弃，避免空道谢
            if msg.gift_count <= 0:
                return

            self._recent_gifts[key] = {
                "ts": arrived_at,
                "count": msg.gift_count,
                "combo": not msg.gift_combo_end,
            }
            self._prune_recent_gifts(arrived_at, window)
            await self.hub.broadcast(
                {
                    "type": "gift",
                    "user": {"nick": msg.nick},
                    "gift": msg.gift_name,
                    "count": msg.gift_count,
                    "merged": False,
                }
            )
            # 只有点过歌的观众再送「棒棒糖」才触发插队
            promoted = (
                await self.music.promote_user(msg.user_id)
                if self.music and "棒棒糖" in (msg.gift_name or "")
                else None
            )
            if promoted:
                reply = (
                    f"谢谢{msg.nick}的{msg.gift_name}！"
                    f"已经把点的《{promoted}》插到最前面啦～"
                )
            else:
                reply = f"谢谢{msg.nick}的{msg.gift_name}，熊家好开心呀！"
        elif msg.type == BarrageType.ENTER:
            # 进场只做语音欢迎，不在画面上弹欢迎条/弹幕
            now = time.monotonic()
            cooldown = float(self.config.get("welcome_cooldown_seconds", 45.0))
            if (
                not self.config.get("welcome_voice", True)
                or now - self._last_welcome_spoken < cooldown
                # 弹幕/点歌已经积压时先不抢麦
                or self._queue.qsize() > 3
            ):
                return
            self._last_welcome_spoken = now
            reply = random.choice(_WELCOME_REPLIES).format(nick=msg.nick)
            # 进场欢迎只出声音，不在画面上弹字
            show_text = False
        elif msg.type == BarrageType.LIKE:
            count = max(1, msg.like_count)
            if msg.like_total > 0:
                self._like_total = max(self._like_total, msg.like_total)
            else:
                self._like_total += count
            await self.hub.broadcast(
                {
                    "type": "like",
                    "user": {"nick": msg.nick},
                    "count": count,
                    "total": self._like_total,
                }
            )
            now = time.monotonic()
            interval = float(self.config.get("like_thank_interval_seconds", 60.0))
            if (
                not self.config.get("like_voice", True)
                or now - self._last_like_thanked < interval
            ):
                return
            self._last_like_thanked = now
            reply = random.choice(_LIKE_REPLIES)
        else:
            if self.music and self.music.is_command(msg.text):
                # 点歌指令交给点歌服务处理（后台下载，不阻塞后续弹幕）
                asyncio.create_task(
                    self.music.handle_request(msg), name=f"music-{msg.msg_id}"
                )
                return

            await self.hub.broadcast(
                {"type": "chat", "user": {"nick": msg.nick}, "text": msg.text}
            )
            hint = self.music.now_playing_hint() if self.music else ""
            prompt_text = msg.text
            if hint:
                prompt_text += f"\n（直播间此刻正在播放{hint}，你可以顺便聊聊这首歌）"
            # 关键词命中表情图片：先推给前端播放，再正常生成回复配合
            sticker = (
                self.keyword_stickers.match(msg.text) if self.keyword_stickers else None
            )
            if sticker:
                await self.hub.broadcast(
                    {
                        "type": "sticker",
                        "name": sticker.name,
                        "url": sticker.url,
                        "user": {"nick": msg.nick},
                    }
                )
                prompt_text += sticker.prompt_hint()
            reply = forced_bubu_reply(msg.text) or await self.llm.reply(
                msg.nick, prompt_text, self.persona
            )

        segments = await self._build_segments(reply)
        await self.hub.broadcast(
            {
                "type": "speak",
                "id": msg.msg_id,
                "user": {"nick": msg.nick},
                "emotion": "happy" if msg.type != BarrageType.COMMENT else "neutral",
                "show_text": show_text,
                "segments": segments,
            }
        )

        # 等这一条完整播完，再读取下一条；不额外加固定间隔
        total_ms = sum(segment["duration_ms"] for segment in segments)
        print(f"[pipeline] reply to {msg.nick} ({total_ms}ms)")
        await asyncio.sleep(total_ms / 1000)

    async def _build_segments(self, reply: str) -> list[dict]:
        # 短回复整段合成一次，减少请求数、避免触发 TTS 限流；长回复才按句拆分
        sentences = [reply] if len(reply) <= 80 else segment(reply)
        spoken = await asyncio.gather(
            *(self.tts.synth(sentence) for sentence in sentences),
            return_exceptions=True,
        )
        segments = []
        for sentence, result in zip(sentences, spoken):
            if isinstance(result, Exception):
                print(f"[pipeline] tts error: {result!r}")
                audio, duration = None, max(800, len(sentence) * 200)
            else:
                audio, duration = result
            segments.append({"text": sentence, "audio": audio, "duration_ms": duration})
        return segments

    async def say(self, nick: str, text: str) -> None:
        """点歌服务等外部模块借用主播的声音播报一句话。"""
        segments = await self._build_segments(text)
        await self.hub.broadcast(
            {
                "type": "speak",
                "id": f"say-{time.time_ns()}",
                "user": {"nick": nick},
                "emotion": "happy",
                "segments": segments,
            }
        )
        total_ms = sum(segment["duration_ms"] for segment in segments)
        await asyncio.sleep(total_ms / 1000)
