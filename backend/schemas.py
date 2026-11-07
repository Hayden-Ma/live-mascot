from enum import Enum

from pydantic import BaseModel


class BarrageType(str, Enum):
    COMMENT = "comment"
    GIFT = "gift"
    ENTER = "enter"
    LIKE = "like"


class BarrageMessage(BaseModel):
    msg_id: str
    type: BarrageType = BarrageType.COMMENT
    user_id: str
    nick: str
    text: str = ""
    gift_name: str | None = None
    gift_count: int = 1
    # 礼物连击的最后一条消息（抖音在收尾时会再发一条 RepeatEnd=1）
    gift_combo_end: bool = False
    # 点赞消息：本条消息的新增点赞数 / 直播间累计点赞数
    like_count: int = 0
    like_total: int = 0
    # 数值越大越先处理：礼物 10、进场 5、点赞 4、普通弹幕 0
    priority: int = 0
