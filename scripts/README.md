# GPU 服务器 TTS 部署（CosyVoice2）

自部署的开源 TTS，替代/兜底云端 TTS。服务跑在 4090 服务器上，本地 Windows 后端通过 HTTP 调用。

## 拓扑

```
backend (Windows)  --HTTP-->  127.0.0.1:45100  --SSH 隧道-->  GPU 服务器:45100 (uvicorn)
                                                              └─ CosyVoice2-0.5B (RTX 4090)
```

服务器防火墙只开放了 SSH 端口，所以用 `scripts/ssh_tunnel.cjs` 做本地端口转发。

## 服务器环境

| 项 | 值 |
|---|---|
| 地址 | 项目根目录 `.env` 的 `REMOTE_HOST:REMOTE_PORT`（校园网/VPN 内，不写进代码） |
| SSH 账号 | `.env` 的 `REMOTE_USER`（`.env` 已被 gitignore） |
| 系统 | Ubuntu 22.04.5，驱动 570.211.01 |
| GPU | RTX 4090 24G |
| conda 环境 | `~/miniconda3/envs/tts`（Python 3.10） |
| 代码 | `~/tts/CosyVoice`（gitee 镜像 `gitee.com/mirrors/CosyVoice`） |
| 模型 | `~/tts/models/CosyVoice2-0.5B`（ModelScope `iic/CosyVoice2-0.5B`，约 5.3G） |
| 服务 | `~/tts/server.py`（FastAPI，端口 45100） |
| 日志 | `~/tts/server.log` |

服务器网络限制：GitHub 不通（用 gitee/gitcode 镜像），HuggingFace 不通（用 ModelScope），
pip 用阿里云做普通包、`download.pytorch.org` 拉 torch/CUDA 包（阿里云的 torch 速度只有 ~0.5MB/s）。

## 启停

> SSH 主机、端口、账号、密码统一在项目根目录 `.env` 的 `REMOTE_HOST` / `REMOTE_PORT` /
> `REMOTE_USER` / `REMOTE_PASSWORD` 中配置，`remote*.cjs`、`ssh_tunnel*.cjs` 和
> `ssh_tunnel_keepalive.ps1` 都会自动读取；`.env` 已在 `.gitignore` 中，不要提交。

服务器上启动推理服务：

```bash
cd ~/tts/CosyVoice
source ~/miniconda3/bin/activate tts
PYTHONPATH=$HOME/tts/CosyVoice uvicorn server:app --app-dir $HOME/tts --host 0.0.0.0 --port 45100
```

本地开隧道（保持窗口开着即可）：

```bash
node scripts/ssh_tunnel.cjs 45100 45100
```

多端口 + 自动重连的稳定版（推荐长期挂机，用密钥免密）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ssh_tunnel_keepalive.ps1
```

> 断线原因：客户端和服务端都没配 keepalive，校园网/VPN 的 NAT 会把几小时无流量的
> TCP 连接回收；Windows 休眠、切换 Wi-Fi 也会让连接失效。上面的脚本用
> `ServerAliveInterval=30` 保活，并在断开后 5 秒自动重连。

接口自检：

```bash
curl http://127.0.0.1:45100/health
curl http://127.0.0.1:45100/voices
```

## 后端配置

`backend/config.yaml`：

```yaml
tts:
  engine: cosyvoice      # 或 minimax（云端）
  cosyvoice:
    base_url: http://127.0.0.1:45100
    voice: bubu
    speed: 1.0
```

## 换音色 / 克隆声音

在服务器上建目录，放 **3~10 秒干净人声**（无 BGM、无混响）+ 该段音频的逐字稿：

```bash
mkdir -p ~/tts/voices/<音色名>
cp <你的参考音频>.wav ~/tts/voices/<音色名>/ref.wav
printf '参考音频里逐字念的内容' > ~/tts/voices/<音色名>/ref.txt
```

然后重启推理服务（启动时会把每个音色的参考特征预编码缓存）。
角色包里 `voice.voice_id` 填同名即可，见 `characters/bubu/character.yaml`。

> 注意：参考音频**必须裁剪到真正的起音点**，开头的气口、上一句的尾音、静音都会被零样本克隆学进去，
> 表现为每句合成音频开头多出一个「啊」之类的音节。裁剪方法是按能量找到第一段持续发声的位置再切。
> 逐字稿也要与裁剪后的音频严格对应。

当前音色 `yier`：参考音频来自抖音视频，先用 Demucs 剥离 BGM，再截取 11.7~15.6s
（台词「其实很简单，输入文字就可以合成了」）。`voices/default` 是官方 demo 音，仅用于预热。

## 人声分离（素材带 BGM 时）

服务器 tts 环境已装 demucs 4.0.1，权重缓存在 `~/.cache/torch/hub/checkpoints/`：

```bash
source ~/miniconda3/bin/activate tts
cd ~/tts/voice_src
demucs -n htdemucs -d cuda --two-stems=vocals src.wav
# 输出: sep/htdemucs/src/vocals.wav（人声）、no_vocals.wav（伴奏）
```

16 秒素材在 4090 上约 2 秒。本地无需安装任何东西；权重 84MB 由本机下载后上传。

## 文件传输辅助脚本

```bash
# 上传（Git Bash 下必须加 MSYS_NO_PATHCONV=1，否则 /home/... 会被转成 Windows 路径）
MSYS_NO_PATHCONV=1 node scripts/remote_put.cjs 本地文件 /home/<REMOTE_USER>/目标路径

# 下载
MSYS_NO_PATHCONV=1 node scripts/remote_get.cjs /home/<REMOTE_USER>/源路径 本地路径
```

## 性能参考（4090，CosyVoice2-0.5B，fp32）

| 指标 | 数值 |
|---|---|
| 显存占用 | ~2.5 GB |
| 模型加载 | ~12 s（常驻，不重复加载） |
| RTF | 0.45 ~ 0.55（3.6 s 音频约 1.8 s 生成） |
| 流式首包 | ~1.65 s |
| 短句（4 字） | ~0.85 s |

瓶颈在自回归 LLM 解码（约 55 token/s）。要压延迟的下一步：

1. **vLLM** 跑 LLM 部分（仓库自带 `cosyvoice/vllm/`），预计 3~5 倍加速；
2. `load_trt=True` 用 TensorRT 加速 flow decoder；
3. 高频台词预渲染缓存（最有效，命中即 0 延迟）。

## 已知限制

- **中文数字/符号没有正则化**：`wetext` 模型需要 ModelScope 登录态，当前未启用（日志里 `no frontend is avaliable`）。含金额、编号的台词建议后端先转成中文读法。
- ONNX speech tokenizer 首次调用会初始化，启动预热已覆盖。
- 服务为单进程 + 串行锁，适合单直播间；多并发需做请求排队或起多实例。
