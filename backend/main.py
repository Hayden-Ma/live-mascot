import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

# Windows 控制台默认 GBK：弹幕昵称里的 emoji 会让 print 抛 UnicodeEncodeError，
# 进而打断弹幕读循环。强制 UTF-8 输出（start_backend.bat 已设置，这里兜底）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .barrage.fake import FakeBarrageSource
from .character.loader import load_character
from .llm.base import LLMClient
from .llm.stub import StubLLM
from .pipeline.queue import Pipeline
from .schemas import BarrageMessage, BarrageType
from .tts.base import TTSEngine
from .tts.silent import SilentTTS
from .ws.hub import Hub

BASE_DIR = Path(__file__).resolve().parent
# 自动读取项目根目录的 .env（网易云 Cookie 等），无需手动加 --env-file
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR.parent / ".env")
except ImportError:
    pass
_config = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))

_character = load_character(_config["app"]["character"])


def _build_tts() -> TTSEngine:
    tts_cfg = _config.get("tts") or {}
    engine = tts_cfg.get("engine", "silent")
    if engine == "cosyvoice":
        from .tts.cosyvoice import CosyVoiceTTS

        cfg = tts_cfg.get("cosyvoice") or {}
        voice_id = (_character.get("voice") or {}).get("cosyvoice") or cfg.get("voice", "default")
        return CosyVoiceTTS(
            base_url=cfg["base_url"],
            voice=voice_id,
            speed=float(cfg.get("speed", 1.0)),
        )
    if engine == "minimax":
        from .tts.minimax import MinimaxTTS

        cfg = tts_cfg.get("minimax") or {}
        voice_id = (_character.get("voice") or {}).get("minimax") or cfg.get("voice_id", "")
        return MinimaxTTS(
            api_key=os.environ.get(cfg.get("api_key_env", "MINIMAX_API_KEY"), ""),
            group_id=os.environ.get(cfg.get("group_id_env", "MINIMAX_GROUP_ID"), "")
            or cfg.get("group_id", ""),
            model=cfg.get("model", "speech-2.8-turbo"),
            voice_id=voice_id,
            speed=float(cfg.get("speed", 1.0)),
            base_url=cfg.get("base_url", "https://api.minimax.chat/v1/t2a_v2"),
            concurrency=int(cfg.get("concurrency", 1)),
            min_interval=float(cfg.get("min_interval", 0.8)),
            max_retries=int(cfg.get("max_retries", 2)),
        )
    return SilentTTS()


def _build_llm() -> LLMClient:
    llm_cfg = _config.get("llm") or {}
    provider = llm_cfg.get("provider", "stub")
    if provider == "openai":
        from .llm.openai_compat import OpenAICompatibleLLM

        cfg = llm_cfg.get("openai") or {}
        base_url = cfg.get("base_url") or ""
        model = cfg.get("model") or ""
        if not base_url or not model:
            print("[llm] openai 配置不完整，回退到 stub")
            return StubLLM()
        return OpenAICompatibleLLM(
            base_url=base_url,
            api_key=os.environ.get(cfg.get("api_key_env", "LLM_API_KEY"), ""),
            model=model,
            temperature=float(cfg.get("temperature", 0.8)),
            max_tokens=int(cfg.get("max_tokens", 200)),
        )
    return StubLLM()


def _build_keyword_stickers():
    """关键词互动表情：弹幕提到图片名（或别名）时播放对应图片。"""
    cfg = _config.get("stickers") or {}
    if not cfg.get("enabled", True):
        return None
    kw = cfg.get("keyword") or {}
    from .character.keyword_stickers import KeywordStickers

    return KeywordStickers(
        character_id=_character["id"],
        directory=str(kw.get("dir", "tigger")),
        cooldown_seconds=float(kw.get("cooldown_seconds", 4.0)),
    )


hub = Hub()
pipeline = Pipeline(
    hub=hub,
    llm=_build_llm(),
    tts=_build_tts(),
    persona=_character.get("persona", ""),
    config=_config["pipeline"],
    keyword_stickers=_build_keyword_stickers(),
)
def _build_barrage_source():
    cfg = _config.get("barrage") or {}
    if cfg.get("source", "fake") == "barragegrab":
        from .barrage.barragegrab import BarrageGrabSource

        bg = cfg.get("barragegrab") or {}
        return BarrageGrabSource(
            ws_url=bg.get("ws_url", "ws://127.0.0.1:8888"),
            reconnect_seconds=float(bg.get("reconnect_seconds", 5.0)),
            debug_raw=bool(bg.get("debug_raw", False)),
            handle_like=bool(bg.get("handle_like", False)),
            receive_timeout_seconds=float(bg.get("receive_timeout_seconds", 45.0)),
        )
    return FakeBarrageSource()


source = _build_barrage_source()

# 点歌服务：本地曲库在 E 盘缓存目录，解析 VIP 地址依赖本地 NeteaseCloudMusicApi
_music_cfg = _config.get("music") or {}
_music_dir = Path(str(_music_cfg.get("cache_dir", "E:/stream-music"))).expanduser()
music = None
if _music_cfg.get("enabled", True):
    from .music.service import MusicService

    music = MusicService(hub=hub, config=_music_cfg)
    music.say = pipeline.say
    pipeline.music = music


async def _feed_barrage() -> None:
    while True:
        try:
            async for message in source.stream():
                pipeline.submit(message)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            # 读循环没被真正取消，只是内部超时/断连，继续重建连接
            print("[barrage] feed cancelled, restarting")
            await asyncio.sleep(1)
        except Exception as exc:
            # source.stream 内部已有重连；这里兜底 submit/_parse 抛出的异常，
            # 避免单条脏数据把整个弹幕任务打死
            print(f"[barrage] feed error: {exc!r}")
            await asyncio.sleep(3)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_netease_api() -> None:
    """后端启动时确保本地网易云接口在跑；已在运行则直接跳过。"""
    cfg = _config.get("music") or {}
    if not cfg.get("enabled", True) or not cfg.get("auto_start", True):
        return

    api_base = str(cfg.get("api_base", "http://127.0.0.1:3000"))
    parsed = urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3000
    if host not in ("127.0.0.1", "localhost"):
        return
    if _port_open(host, port):
        return

    node = shutil.which("node")
    if not node:
        print("[music] 未找到 node，无法自动启动网易云接口")
        return
    script = BASE_DIR.parent / "scripts" / "start_netease.cjs"
    if not script.exists():
        print(f"[music] 网易云启动脚本不存在: {script}")
        return

    log_dir = BASE_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_handle = (log_dir / "netease-api.log").open("ab")
    try:
        subprocess.Popen(
            [node, str(script)],
            cwd=str(BASE_DIR.parent),
            env={**os.environ, "PORT": str(port)},
            stdout=log_handle,
            stderr=log_handle,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        print(f"[music] 已自动启动网易云接口（端口 {port}）")
    except Exception as exc:
        print(f"[music] 自动启动网易云接口失败: {exc!r}")
    finally:
        log_handle.close()


def _report_task_end(task: asyncio.Task) -> None:
    """任务异常结束时打印原因，避免弹幕读循环静默消失。"""
    try:
        error = task.exception()
    except asyncio.CancelledError as exc:
        error = exc
    print(
        f"[task] {task.get_name()} finished: "
        f"cancelled={task.cancelled()} error={error!r}"
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(_ensure_netease_api)
    tasks = [
        asyncio.create_task(pipeline.run(), name="pipeline"),
        asyncio.create_task(_feed_barrage(), name="barrage-feed"),
    ]
    if music is not None:
        tasks.append(asyncio.create_task(music.run(), name="music"))
    for task in tasks:
        task.add_done_callback(_report_task_end)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if music is not None:
            await music.close()


app = FastAPI(lifespan=lifespan)
app.mount(
    "/characters",
    StaticFiles(directory=BASE_DIR.parent / "characters"),
    name="characters",
)
if music is not None and _music_dir.exists():
    app.mount("/music", StaticFiles(directory=_music_dir), name="music")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "character": _character["id"]}


@app.get("/api/character")
async def get_character() -> dict:
    return _character


class InjectBody(BaseModel):
    nick: str = "测试用户"
    text: str = "布布你好呀"
    type: str = "comment"
    count: int = 1


@app.post("/api/dev/inject")
async def inject(body: InjectBody) -> dict:
    """调试用：手动注入一条弹幕/进场/点赞/礼物，走完整的流水线。"""
    try:
        barrage_type = BarrageType(body.type)
    except ValueError:
        barrage_type = BarrageType.COMMENT

    if barrage_type == BarrageType.GIFT:
        fields: dict = {
            "gift_name": body.text,
            "gift_count": max(1, body.count),
            "priority": 10,
        }
    elif barrage_type == BarrageType.ENTER:
        fields = {"text": "进入了直播间", "priority": 5}
    elif barrage_type == BarrageType.LIKE:
        fields = {
            "text": "点赞了",
            "like_count": max(1, body.count),
            "priority": 4,
        }
    else:
        fields = {"text": body.text, "priority": 0}

    message = BarrageMessage(
        msg_id=f"dev-{time.time_ns()}",
        type=barrage_type,
        user_id=body.nick,
        nick=body.nick,
        **fields,
    )
    pipeline.submit(message)
    return {"ok": True}


class SayBody(BaseModel):
    nick: str = "嘉宜姐姐"
    text: str = "泼天的富贵哗啦啦的来，那熊家多攒点熊熊币，给布布备个小礼物～"


@app.post("/api/dev/say")
async def dev_say(body: SayBody) -> dict:
    """调试用：不经过 LLM/TTS，直接把一句话推给前端气泡。"""
    duration = max(1500, len(body.text) * 200)
    await hub.broadcast(
        {
            "type": "speak",
            "id": f"dev-say-{time.time_ns()}",
            "user": {"nick": body.nick},
            "emotion": "happy",
            "segments": [{"text": body.text, "audio": None, "duration_ms": duration}],
        }
    )
    return {"ok": True}


@app.get("/api/dev/barrage_probe")
async def barrage_probe(seconds: float = 8.0) -> dict:
    """调试用：用后端的 event loop 直接连 BarrageGrab，观察消息是否持续到达。"""
    from websockets import connect as ws_connect

    start = time.monotonic()
    received = 0
    types: dict[str, int] = {}
    try:
        async with ws_connect(
            "ws://127.0.0.1:8888", ping_interval=None, max_size=None
        ) as ws:
            while time.monotonic() - start < seconds:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                received += 1
                try:
                    payload = json.loads(raw)
                    key = str(payload.get("Type"))
                    types[key] = types.get(key, 0) + 1
                except Exception:
                    pass
    except Exception as exc:
        return {"ok": False, "error": repr(exc), "received": received}
    return {"ok": True, "received": received, "types": types}


@app.get("/api/dev/status")
async def dev_status() -> dict:
    """调试用：观察弹幕连接、流水线队列和互动限流状态。"""
    feed = next(
        (task for task in asyncio.all_tasks() if task.get_name() == "barrage-feed"),
        None,
    )
    return {
        "barrage_connected": getattr(source, "frames", 0) > 0,
        "frames": getattr(source, "frames", None),
        "yielded": getattr(source, "yielded", None),
        "queue": pipeline._queue.qsize(),
        "like_total": pipeline._like_total,
        "last_enter_submitted": pipeline._last_enter_submitted,
        "last_welcome_spoken": pipeline._last_welcome_spoken,
        "last_like_thanked": pipeline._last_like_thanked,
        "feed_task_done": feed.done() if feed is not None else None,
        "feed_task_exists": feed is not None,
        "tasks": {
            task.get_name(): task.done()
            for task in asyncio.all_tasks()
            if task.get_name() in ("pipeline", "barrage-feed", "music")
        },
    }


class DemoSongQueueBody(BaseModel):
    current: str = "孤单北半球"
    artist: str = "呦呦鹿鸣"
    queue: list[str] = Field(
        default_factory=lambda: ["告别的车站", "童话", "一二唱&布布客串唱歌"]
    )


@app.post("/api/dev/song_queue")
async def dev_song_queue(body: DemoSongQueueBody) -> dict:
    """调试用：只广播一份假歌单给前端，不触碰真实点歌服务。"""

    def song(name: str, index: int) -> dict:
        return {
            "key": f"demo-{index}",
            "song_id": f"demo-{index}",
            "name": name,
            "artist": body.artist if index == 0 else "熊友点的",
            "duration_ms": 214000 if index == 0 else 0,
            "source": "demo",
            "requested_by": "" if index == 0 else "布布",
            "url": "",
        }

    await hub.broadcast(
        {
            "type": "song_queue",
            "current": song(body.current, 0),
            "queue": [song(name, index + 1) for index, name in enumerate(body.queue)],
        }
    )
    return {"ok": True}


class MusicFinishedBody(BaseModel):
    song_id: str


@app.post("/api/music/finished")
async def music_finished(body: MusicFinishedBody) -> dict:
    """前端播放结束后回调，用于切到下一首。"""
    if music is not None:
        music.mark_finished(body.song_id)
    return {"ok": True}


@app.get("/api/music/status")
async def music_status() -> dict:
    if music is None:
        return {"enabled": False, "current": None, "queue": []}
    return music.snapshot()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)


# 前端构建产物（frontend/ npm run build 生成）。
# 放在最后注册：/api、/ws、/characters 等路由优先匹配。
_FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
