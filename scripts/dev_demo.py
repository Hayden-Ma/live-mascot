"""竖屏直播间的联调演示脚本：往本地后端注入假歌单、进场、点赞和主播气泡。

用法（后端已在 12121 端口运行时）：
    .venv/Scripts/python.exe -X utf8 scripts/dev_demo.py
"""

import time

import httpx

API = "http://127.0.0.1:12121"
client = httpx.Client(timeout=10)


def post(path: str, payload: dict) -> None:
    response = client.post(API + path, json=payload)
    print(f"{path} -> {response.status_code} {response.text}")


post("/api/dev/song_queue", {})
time.sleep(1.0)

# 第一次进场会触发欢迎语音，等它播完
post("/api/dev/inject", {"type": "enter", "nick": "嘉宜姐姐"})
time.sleep(5.5)

# 第一次点赞会触发道谢语音，等它播完
post("/api/dev/inject", {"type": "like", "nick": "北北！", "count": 8})
time.sleep(4.5)

# 主播气泡（不走 LLM/TTS）
post(
    "/api/dev/say",
    {
        "nick": "嘉宜姐姐",
        "text": "泼天的富贵哗啦啦的来，泼天的富贵？那熊家多攒点熊熊币，给布布备个小礼物～",
    },
)
time.sleep(8.5)

# 欢迎/点赞语音都在冷却期，这里只触发前端动画，适合截图验收
post("/api/dev/inject", {"type": "enter", "nick": "小咪·"})
time.sleep(0.3)
post("/api/dev/inject", {"type": "like", "nick": "北北！", "count": 12})
print("demo ready")
