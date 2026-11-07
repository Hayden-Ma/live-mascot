"""
CosyVoice2 推理服务（部署在 GPU 服务器上，供本地 backend 调用）。

启动:
    source ~/miniconda3/bin/activate tts
    cd ~/tts && uvicorn server:app --host 0.0.0.0 --port 45100

接口:
    GET  /health          -> 模型与显存状态
    GET  /voices          -> 可用音色列表
    POST /tts             -> {text, voice, speed} 返回 wav (audio/wav)
    POST /tts/stream      -> 同上，返回 chunked PCM s16le/24kHz/mono

音色目录: voices/<name>/ref.wav + ref.txt（3~10 秒参考音频及逐字稿）
"""
import io
import logging
import os
import threading

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from cosyvoice.cli.cosyvoice import CosyVoice2

MODEL_DIR = os.environ.get("COSYVOICE_MODEL", os.path.expanduser("~/tts/models/CosyVoice2-0.5B"))
VOICE_DIR = os.environ.get("COSYVOICE_VOICES", os.path.expanduser("~/tts/voices"))
SAMPLE_RATE = 24000

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cosyvoice")

app = FastAPI(title="CosyVoice2 TTS")
_engine: CosyVoice2 | None = None
_lock = threading.Lock()  # 串行化 GPU 推理
_load_lock = threading.Lock()  # 防止并发重复加载模型


@app.on_event("startup")
def _startup() -> None:
    # 启动时就把模型和音色加载好，避免首个请求触发加载、也避免并发加载竞态
    _load_engine()


def _voice_info(name: str) -> dict | None:
    """音色目录结构: voices/<name>/ref.wav + ref.txt"""
    d = os.path.join(VOICE_DIR, name)
    ref, txt = os.path.join(d, "ref.wav"), os.path.join(d, "ref.txt")
    if not (os.path.exists(ref) and os.path.exists(txt)):
        return None
    return {"id": name, "ref": ref, "text": open(txt, encoding="utf-8").read().strip()}


def _load_engine() -> CosyVoice2:
    global _engine
    if _engine is not None:
        return _engine
    with _load_lock:
        if _engine is None:
            eng = CosyVoice2(MODEL_DIR, load_jit=False, load_trt=False, fp16=False)
            # 预编码参考音频并缓存，后续请求省掉 prompt 特征提取
            names = [n for n in os.listdir(VOICE_DIR)] if os.path.isdir(VOICE_DIR) else []
            for name in names:
                info = _voice_info(name)
                if info:
                    eng.add_zero_shot_spk(info["text"], info["ref"], name)
                    log.info("voice cached: %s", name)
            _engine = eng  # 全部就绪后再发布，避免并发请求拿到半初始化的实例
            # 预热
            for name in names:
                info = _voice_info(name)
                if info:
                    with _lock:
                        for _ in _synthesize("你好。", info, 1.0):
                            pass
            log.info("model loaded: %s", MODEL_DIR)
    return _engine


def _synthesize(text: str, voice: dict, speed: float, stream: bool = False):
    yield from _engine.inference_zero_shot(
        text, "", "", stream=stream, speed=speed, zero_shot_spk_id=voice["id"]
    )


def _to_wav(chunks) -> tuple[bytes, int]:
    audio = torch.cat([c["tts_speech"] for c in chunks], dim=1)  # [1, T]
    buf = io.BytesIO()
    torchaudio.save(buf, audio, SAMPLE_RATE, format="wav")
    return buf.getvalue(), audio.shape[1]


class TTSRequest(BaseModel):
    text: str
    voice: str = "default"
    speed: float = 1.0


@app.get("/health")
def health() -> dict:
    ok = _engine is not None
    return {
        "ok": ok,
        "model": os.path.basename(MODEL_DIR),
        "cuda": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "vram_mb": round(torch.cuda.memory_allocated() / 1024**2) if ok else 0,
    }


@app.get("/voices")
def voices() -> dict:
    names = []
    if os.path.isdir(VOICE_DIR):
        names = [n for n in os.listdir(VOICE_DIR) if _voice_info(n)]
    return {"voices": names}


@app.post("/tts")
def tts(req: TTSRequest) -> Response:
    _load_engine()
    voice = _voice_info(req.voice)
    if voice is None:
        raise HTTPException(404, f"音色不存在: {req.voice}")
    if not req.text.strip():
        raise HTTPException(400, "text 为空")
    import time as _t

    started = _t.perf_counter()
    with _lock:
        wav, samples = _to_wav(_synthesize(req.text, voice, req.speed))
    elapsed = _t.perf_counter() - started
    audio_seconds = samples / SAMPLE_RATE
    return Response(
        wav,
        media_type="audio/wav",
        headers={
            "X-Audio-Seconds": f"{audio_seconds:.3f}",
            "X-RtF": f"{elapsed / max(audio_seconds, 1e-6):.3f}",
            "X-Gen-Seconds": f"{elapsed:.3f}",
        },
    )


@app.post("/tts/stream")
def tts_stream(req: TTSRequest) -> StreamingResponse:
    _load_engine()
    voice = _voice_info(req.voice)
    if voice is None:
        raise HTTPException(404, f"音色不存在: {req.voice}")

    def gen():
        with _lock:  # 简化：整句独占 GPU
            for chunk in _synthesize(req.text, voice, req.speed, stream=True):
                pcm = (chunk["tts_speech"].clamp(-1, 1) * 32767).to(torch.int16)
                yield pcm.numpy().tobytes()

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(SAMPLE_RATE)},
    )
