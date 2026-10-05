# Installation Guide

Last updated: 2026-10-05

> ✅ **Phase B end-to-end works as of 2026-09-06** (browser → Aliyun NLS ASR → MiniMax LLM → MiniMax TTS → browser). Code is shipped but **not enabled** by default — see [README § Status](./README.md#status) for the activation trigger conditions.
>
> 🆕 **ASR is Aliyun NLS** (Alibaba Cloud 智能语音交互, project type **实时语音识别**). Before installing, register an Aliyun account, create a NLS project, and obtain AppKey + AccessKey ID/Secret. Full guide: [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md).
>
> 📂 **Where session artifacts land:** see [`phase_b/_reports/phase-b-data-flow-2026-09-06.md`](./phase_b/_reports/phase-b-data-flow-2026-09-06.md) (transcripts / audio / rhythm / tracker files).

---

## 1. Requirements

### Hardware

- **CPU**: Any modern x86_64 or Apple Silicon. STT runs in the cloud (Aliyun NLS); no local inference is performed, so RAM/CPU requirements are modest.
- **RAM**: 4 GB minimum, 8 GB recommended.
- **Disk**: ~500 MB free (Python venv + audio cache).
- **Microphone**: Any built-in or USB mic. Headset recommended to avoid echo with TTS playback.

### Software

- **macOS**: 13.0 Ventura or later (for Apple Silicon native PyTorch).
- **Python**: 3.9.6 or later (3.9 / 3.10 / 3.11 all tested in spike).
- **Git**: for cloning the repo.
- **ffmpeg**: required by librosa for audio I/O. Install with `brew install ffmpeg`.
- **Chrome or Safari**: for the browser frontend.

### Network

- Outbound **WSS** to your **STT endpoint** (default: `wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1` — Aliyun NLS streaming).
- Outbound HTTPS to your **LLM endpoint** (default: MiniMax API).
- Outbound **WSS** to your **TTS endpoint** (default: MiniMax T2A WebSocket).

If you self-host LLM/TTS/STT, only `127.0.0.1` traffic is required and no data leaves your machine. See [PRIVACY.md](./PRIVACY.md).

---

## 2. Clone the repo

```bash
git clone https://github.com/<your-username>/pcc-live-coach.git
cd pcc-live-coach
```

> The repo is currently **private**. After Phase B ships and the maintainer marks it public, switch to the public URL.

---

## 3. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
```

### Why a venv?

- Keeps FastAPI / uvicorn / aliyun-nls isolated from system Python.
- The venv is gitignored — no risk of committing the SDK cache.

---

## 4. Install Python dependencies

Install runtime deps from `requirements.txt`:

```bash
pip install -r requirements.txt
```

The full set (kept lean after the 2026-09-06 FunASR → Aliyun swap):

```
fastapi==0.128.8
uvicorn==0.39.0
websockets==15.0.1
httpx==0.28.1
python-multipart==0.0.20
aliyun-nls==0.0.1
alibabacloud-nls-cloud-meta20190228==1.0.0
```

> ⚠️ `aliyun-nls==0.0.1` transitively pulls matplotlib / pillow / fonttools / pycryptodome (~54 MB) that this project does not actually use. The project only `import`s `nls` / `alibabacloud_nls_cloud_meta20190228.client` / `alibabacloud_tea_openapi.models` — none of those need the heavy four. To skip them at install time, run a two-step install instead of plain `pip install -r requirements.txt`:
>
> ```bash
> pip install -r requirements.txt
> pip install --no-deps --force-reinstall aliyun-nls==0.0.1
> ```
>
> Then verify with a one-liner (must print `OK`):
>
> ```bash
> python -c "import nls; from alibabacloud_nls_cloud_meta20190228.client import Client; from alibabacloud_tea_openapi import models; print('OK')"
> ```
>
> If the smoke test fails, fall back to the default install + `pip uninstall matplotlib pillow fonttools pycryptodome` to reclaim disk.

---

## 5. Configure Aliyun NLS credentials (default STT)

STT is **Aliyun NLS** (project type **实时语音识别**, not "一句话识别"). Before `.env` will work, register and obtain three credentials. Full walkthrough: [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md).

In short:

1. Sign up at [aliyun.com](https://www.aliyun.com) and complete real-name verification.
2. Activate **智能语音交互** at [nls-portal.console.aliyun.com](https://nls-portal.console.aliyun.com/) (pay-as-you-go billing).
3. Create a project with **项目类型 = 实时语音识别** and copy the **AppKey**.
4. In [RAM 控制台](https://ram.console.aliyun.com/), create a sub-user with OpenAPI access; grant `AliyunNLSFullAccess`. Copy **AccessKey ID** + **AccessKey Secret** (shown once).
5. Put the three values into `.env` (see next section).

Pricing (2026-09 reference): 0.0008 元/秒 ≈ 2.88 元/小时, with a monthly free tier (~20 000 calls — verify on aliyun.com for current terms).

---

## 6. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys (`.env` is gitignored):

```bash
cp .env.example .env
$EDITOR .env
```

Full template (matches [`./.env.example`](./.env.example)):

```bash
# --- Server ---
PCC_LIVE_HOST=127.0.0.1
PCC_LIVE_PORT=8765
PCC_LIVE_LOG_LEVEL=info
# Set to 1 to allow binding 0.0.0.0 (LAN exposure). Default 0 = refuse.
PCC_LIVE_ALLOW_LAN=0

# --- LLM (MiniMax or any OpenAI-compatible endpoint) ---
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=
LLM_MODEL=MiniMax-M3
LLM_TIMEOUT_S=30
LLM_MAX_TOKENS=1000
LLM_TEMPERATURE=0.6

# --- TTS (MiniMax T2A WebSocket) ---
TTS_WS_URL=wss://api.minimaxi.com/ws/v1/t2a_v2
TTS_API_KEY=
TTS_MODEL=speech-2.6-hd
TTS_VOICE=male-qn-jingying
TTS_SAMPLE_RATE=16000
TTS_TIMEOUT_S=30

# --- ASR (阿里云实时语音识别 — see §5) ---
ALIYUN_ASR_APPKEY=
ALIYUN_ACCESS_KEY_ID=
ALIYUN_ACCESS_KEY_SECRET=

# --- Audio / Rhythm / Paths ---
AUDIO_SAMPLE_RATE=16000
AUDIO_FRAME_MS=30
AUDIO_CHANNELS=1
SILENCE_THRESHOLD_MS=2000
CPM_SLOW=120
CPM_IDEAL_LOW=150
CPM_IDEAL_HIGH=200
CPM_FAST=280
BARGE_IN_DEBOUNCE_MS=500
PERSONAS_DIR=personas
SESSIONS_DIR=practice-logs/sessions
TRACKER_CSV=progress/tracker-sessions.csv
# Trending chart output. Empty = default per-day file under progress/.
# Absolute path = used as-is. Relative = resolved against repo root.
# Literal "{date}" is substituted with today's YYYY-MM-DD.
# Example: reports/trending-{date}.html
# TRENDING_CHART_PATH=
```

> ⚠️ **Never commit `.env` to git.** It contains your API keys. The repo's `.gitignore` excludes it by default.

### Supported LLM providers

The LLM client uses the standard OpenAI Chat Completions API (`POST /chat/completions` with `Authorization: Bearer ...`), so **any OpenAI-compatible endpoint** works. The default is MiniMax (placeholder); switch by editing the three `LLM_*` env vars:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` example | Privacy |
|---|---|---|---|
| **MiniMax API** (default) | `https://api.minimaxi.com/v1` | `MiniMax-M3` | Cloud — text sent to MiniMax |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` | Cloud — text sent to OpenAI |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | Cloud — text sent to DeepSeek |
| **Azure OpenAI** | `https://<resource>.openai.azure.com/openai/deployments/<dep>` | `<deployment-name>` | Cloud — text sent to Azure |
| **Ollama** (local) | `http://127.0.0.1:11434/v1` | `qwen2.5:14b` | **Fully offline** |
| **LM Studio** (local) | `http://127.0.0.1:1234/v1` | any local model | **Fully offline**, GUI-based |
| **vLLM** (local) | `http://127.0.0.1:8000/v1` | any served model | **Fully offline**, GPU-accelerated |
| **OpenRouter / OneAPI** | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` | Cloud — aggregates many providers |

`LLM_API_KEY` can be any non-empty string for local providers (Ollama / LM Studio / vLLM do not check it).

### Self-hosted LLM (optional, for full privacy)

To run **completely offline**, point `LLM_BASE_URL` at a local OpenAI-compatible endpoint (e.g., [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), [vLLM](https://github.com/vllm-project/vllm)):

```bash
LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama default
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=not-used                      # any non-empty string
```

In self-hosted mode, no conversation text leaves your machine. See [PRIVACY.md](PRIVACY.md) for details.

---

## 7. Verify installation

```bash
# Check Python deps
python -c "import fastapi, uvicorn, aliyun_nls; print('OK')"

# Start the server
./start.sh                       # 推荐 — 自动检查端口/venv/.env
# 或: python -m phase_b

# Open browser to http://127.0.0.1:8765
```

Expected log output (first session only — Aliyun NLS model loads lazily on first WS connect):

```
[INFO] phase_b: server listening on http://127.0.0.1:8765
[INFO] phase_b.config: STT=aliyun-nls  LLM=https://api.minimaxi.com/v1 (MiniMax-M3)  TTS=wss://api.minimaxi.com/ws/v1/t2a_v2 (speech-2.6-hd)
[INFO] ws <session-id> connecting
[INFO] ws <session-id> accepted
[INFO] ws <session-id> sent ready
```

---

## 8. Troubleshooting

### Port 8765 already in use

`./start.sh` now refuses to start when the port is bound and prints the holder's PID. Two common cases:

1. **Previous run was not stopped cleanly** (terminal closed, logout, crash):
   ```bash
   lsof -nP -iTCP:8765 -sTCP:LISTEN      # find the PID
   kill <pid>                             # then ./start.sh again
   ```
2. **You want two servers side-by-side** (dev + prod, or test new code):
   ```bash
   PCC_LIVE_PORT=8766 ./start.sh
   ```

### `pip install aliyun-nls` fails or hangs

The Aliyun SDK has only been validated on Python 3.9+. Workarounds:

1. Use `--no-deps` and install dependencies manually.
2. Use a fresh venv — system Python may have conflicting packages.
3. If you're on Apple Silicon, ensure you're using a native arm64 Python (not Rosetta). Run `python -c "import platform; print(platform.machine())"` and confirm it prints `arm64`.

### Aliyun NLS connection fails (`InvalidToken` / 4xx)

The three `.env` credentials must all be set; missing or mistyped values produce auth errors. See [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md) for the full registration checklist. Common mistakes:

- Project type is "**一句话识别**" instead of "**实时语音识别**" → STT session never opens.
- Sub-account lacks `AliyunNLSFullAccess` → 403 Forbidden.
- `.env` `LLM_*` keys accidentally placed in `ALIYUN_*` slots (or vice versa) → start.sh boots but the server reports config-parse errors at first STT request.

### Microphone not detected in browser

1. Check that you granted microphone permission to `127.0.0.1`.
2. In Chrome, open `chrome://settings/content/microphone` and verify the site is allowed.
3. Test your mic at [mic.testsite.com](https://www.onlinemictest.com) first.

### TTS audio is choppy / laggy

1. Use a wired headset (Bluetooth adds ~200 ms latency).
2. Reduce TTS model to `speech-2.6-turbo` (lower quality, faster).
3. Check `LOG_LEVEL=debug` for network timing.

### `ModuleNotFoundError` on first start

Dependencies weren't installed into the active Python. Run from the project root:

```bash
.venv/bin/pip install -r requirements.txt
```

`./start.sh` already uses `.venv/bin/python` directly, so venv activation is not required.

### `Refusing to bind 0.0.0.0`

By default the server binds to `127.0.0.1` only (LAN exposure refused to avoid leaking audio). To bind `0.0.0.0` (e.g. when running on a remote machine and accessing from another device):

```bash
PCC_LIVE_ALLOW_LAN=1 ./start.sh
```

### `tracker.csv` rows truncated to ~95 columns when edited

The Edit tool truncates very long single-line edits (the tracker.csv schema is 87 columns + extras). Append new session rows via:

```bash
python -m phase_b.tracker.csv_append ...
```

instead of editing the CSV by hand. See memory `edit-tool-long-csv-truncation`.

---

## 9. Updating

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt --upgrade
```

Aliyun NLS is a managed cloud endpoint — no local model to upgrade. To roll credentials, edit `.env` and restart with `./start.sh`.

---

<br/>
<br/>

# 安装指南

最后更新:2026-10-05

> ✅ **Phase B 端到端已可用(2026-09-06 起)**(浏览器 → Aliyun NLS ASR → MiniMax LLM → MiniMax TTS → 浏览器)。代码已提交但**默认未启用** —— 激活触发条件见 [README § Status](./README.md#status)。
>
> 🆕 **ASR 是 Aliyun NLS**(阿里云智能语音交互,项目类型**实时语音识别**)。安装前请先注册阿里云账号、建 NLS 项目、拿到 AppKey + AccessKey ID/Secret。完整指南:[`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md)。
>
> 📂 **会话产物落点:** 见 [`phase_b/_reports/phase-b-data-flow-2026-09-06.md`](./phase_b/_reports/phase-b-data-flow-2026-09-06.md)(transcript / 录音 / rhythm / tracker 文件位置)。

---

## 1. 需求

### 硬件

- **CPU**: 现代 x86_64 或 Apple Silicon 均可。STT 运行在云端(Aliyun NLS),不做本地推理,所以 RAM/CPU 要求不高。
- **内存**: 最低 4 GB,推荐 8 GB。
- **磁盘**: ~500 MB 可用空间(Python venv + 音频缓存)。
- **麦克风**: 任何内置或 USB 麦克风。推荐使用耳机以避免与 TTS 播放产生回声。

### 软件

- **macOS**: 13.0 Ventura 或更高(为了 Apple Silicon 原生 PyTorch)
- **Python**: 3.9.6 或更高(3.9 / 3.10 / 3.11 都在 spike 中测试过)
- **Git**: 用于克隆仓库
- **ffmpeg**: librosa 处理音频 I/O 需要。通过 `brew install ffmpeg` 安装
- **Chrome 或 Safari**: 浏览器前端

### 网络

- 出站 **WSS** 到你的 **STT 端点**(默认:`wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1` —— Aliyun NLS 流式)
- 出站 HTTPS 到你的 **LLM 端点**(默认:MiniMax API)
- 出站 **WSS** 到你的 **TTS 端点**(默认:MiniMax T2A WebSocket)

如果你自托管 LLM/TTS/STT,只需要 `127.0.0.1` 流量,数据不离开你的机器。详见 [PRIVACY.md](./PRIVACY.md)。

---

## 2. 克隆仓库

```bash
git clone https://github.com/<your-username>/pcc-live-coach.git
cd pcc-live-coach
```

> 仓库当前是**私有的**。Phase B 发布且维护者将其标记为公开后,切换到公开 URL。

---

## 3. 创建 Python 虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
```

### 为什么用 venv?

- 隔离 FastAPI / uvicorn / aliyun-nls 与系统 Python
- venv 被 gitignore —— 避免意外提交 SDK 缓存

---

## 4. 安装 Python 依赖

从 `requirements.txt` 装运行时依赖:

```bash
pip install -r requirements.txt
```

完整依赖清单(2026-09-06 FunASR → Aliyun 换栈后已精简):

```
fastapi==0.128.8
uvicorn==0.39.0
websockets==15.0.1
httpx==0.28.1
python-multipart==0.0.20
aliyun-nls==0.0.1
alibabacloud-nls-cloud-meta20190228==1.0.0
```

> ⚠️ `aliyun-nls==0.0.1` 会顺带拉入 matplotlib / pillow / fonttools / pycryptodome(~54 MB),本项目不实际用到。代码里只 `import nls` / `from alibabacloud_nls_cloud_meta20190228.client import Client` / `from alibabacloud_tea_openapi import models`,都不依赖那四个包。跳过它们的安装方式(两步法):
>
> ```bash
> pip install -r requirements.txt
> pip install --no-deps --force-reinstall aliyun-nls==0.0.1
> ```
>
> 装完用一行 smoke test 验证(必须输出 `OK`):
>
> ```bash
> python -c "import nls; from alibabacloud_nls_cloud_meta20190228.client import Client; from alibabacloud_tea_openapi import models; print('OK')"
> ```
>
> smoke test 失败的话,退回默认安装 + `pip uninstall matplotlib pillow fonttools pycryptodome` 回收空间。

---

## 5. 配置阿里云 NLS 凭证(默认 STT)

STT 是 **Aliyun NLS**(项目类型**实时语音识别**,不要选"一句话识别")。`.env` 跑通前,需先注册并拿到三个凭证。完整 walkthrough:[`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md)。

简述:

1. 在 [aliyun.com](https://www.aliyun.com) 注册并完成实名认证。
2. 在 [nls-portal.console.aliyun.com](https://nls-portal.console.aliyun.com/) 开通**智能语音交互**(按量付费)。
3. 创建项目,**项目类型 = 实时语音识别**,复制 **AppKey**。
4. 在 [RAM 控制台](https://ram.console.aliyun.com/) 创建子账号(OpenAPI 访问),授予 `AliyunNLSFullAccess`。复制 **AccessKey ID** + **AccessKey Secret**(只显示一次)。
5. 三个值填入 `.env`(见下节)。

价格参考(2026-09 时点):0.0008 元/秒 ≈ 2.88 元/小时,每月免费额度约 2 万次调用(以 aliyun.com 官网为准)。

---

## 6. 配置环境变量

复制 `.env.example` 到 `.env` 并填入你的 key(`.env` 被 gitignore):

```bash
cp .env.example .env
$EDITOR .env
```

完整模板(对应 [`./.env.example`](./.env.example)):

```bash
# --- Server ---
PCC_LIVE_HOST=127.0.0.1
PCC_LIVE_PORT=8765
PCC_LIVE_LOG_LEVEL=info
# Set to 1 to allow binding 0.0.0.0 (LAN exposure). Default 0 = refuse.
PCC_LIVE_ALLOW_LAN=0

# --- LLM (MiniMax or any OpenAI-compatible endpoint) ---
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=
LLM_MODEL=MiniMax-M3
LLM_TIMEOUT_S=30
LLM_MAX_TOKENS=1000
LLM_TEMPERATURE=0.6

# --- TTS (MiniMax T2A WebSocket) ---
TTS_WS_URL=wss://api.minimaxi.com/ws/v1/t2a_v2
TTS_API_KEY=
TTS_MODEL=speech-2.6-hd
TTS_VOICE=male-qn-jingying
TTS_SAMPLE_RATE=16000
TTS_TIMEOUT_S=30

# --- ASR (阿里云实时语音识别 — 见 §5) ---
ALIYUN_ASR_APPKEY=
ALIYUN_ACCESS_KEY_ID=
ALIYUN_ACCESS_KEY_SECRET=

# --- Audio / Rhythm / Paths ---
AUDIO_SAMPLE_RATE=16000
AUDIO_FRAME_MS=30
AUDIO_CHANNELS=1
SILENCE_THRESHOLD_MS=2000
CPM_SLOW=120
CPM_IDEAL_LOW=150
CPM_IDEAL_HIGH=200
CPM_FAST=280
BARGE_IN_DEBOUNCE_MS=500
PERSONAS_DIR=personas
SESSIONS_DIR=practice-logs/sessions
TRACKER_CSV=progress/tracker-sessions.csv
# 趋势图输出位置。空 = progress/ 下每天一个新文件。
# 绝对路径 = 直接使用。相对路径 = 相对于仓库根目录。
# 字面量 "{date}" 会被替换成今天的 YYYY-MM-DD。
# 例:reports/trending-{date}.html
# TRENDING_CHART_PATH=
```

> ⚠️ **永远不要将 `.env` 提交到 git。** 它包含你的 API 密钥。仓库的 `.gitignore` 默认排除它。

### 支持的 LLM providers

LLM 客户端使用标准 OpenAI Chat Completions API(`POST /chat/completions` + `Authorization: Bearer ...`),因此**任何 OpenAI 兼容端点**都可以工作。默认是 MiniMax(占位符);通过编辑三个 `LLM_*` 环境变量切换:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` 示例 | 隐私 |
|---|---|---|---|
| **MiniMax API**(默认) | `https://api.minimaxi.com/v1` | `MiniMax-M3` | 云端 —— 文本发往 MiniMax |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` | 云端 —— 文本发往 OpenAI |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | 云端 —— 文本发往 DeepSeek |
| **Azure OpenAI** | `https://<resource>.openai.azure.com/openai/deployments/<dep>` | `<deployment-name>` | 云端 —— 文本发往 Azure |
| **Ollama**(本地) | `http://127.0.0.1:11434/v1` | `qwen2.5:14b` | **完全离线** |
| **LM Studio**(本地) | `http://127.0.0.1:1234/v1` | 任意本地模型 | **完全离线**,基于 GUI |
| **vLLM**(本地) | `http://127.0.0.1:8000/v1` | 任意已服务模型 | **完全离线**,GPU 加速 |
| **OpenRouter / OneAPI** | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` | 云端 —— 聚合多家 provider |

对于本地 provider(Ollama / LM Studio / vLLM),`LLM_API_KEY` 可以是任意非空字符串(它们不校验)。

### 自托管 LLM(可选,完全隐私)

要**完全离线运行**,将 `LLM_BASE_URL` 指向本地 OpenAI 兼容端点(例如 [Ollama](https://ollama.com)、[LM Studio](https://lmstudio.ai)、[vLLM](https://github.com/vllm-project/vllm)):

```bash
LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama 默认
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=not-used                      # 任意非空字符串
```

在自托管模式下,没有对话文本离开你的机器。详见 [PRIVACY.md](PRIVACY.md)。

---

## 7. 验证安装

```bash
# 检查 Python 依赖
python -c "import fastapi, uvicorn, aliyun_nls; print('OK')"

# 启动服务器
./start.sh                       # 推荐 — 自动检查端口/venv/.env
# 或: python -m phase_b

# 浏览器打开 http://127.0.0.1:8765
```

预期日志输出(Aliyun NLS 模型在首个 WS 连接时按需加载):

```
[INFO] phase_b: server listening on http://127.0.0.1:8765
[INFO] phase_b.config: STT=aliyun-nls  LLM=https://api.minimaxi.com/v1 (MiniMax-M3)  TTS=wss://api.minimaxi.com/ws/v1/t2a_v2 (speech-2.6-hd)
[INFO] ws <session-id> connecting
[INFO] ws <session-id> accepted
[INFO] ws <session-id> sent ready
```

---

## 8. 故障排除

### 端口 8765 已被占用

`./start.sh` 现在会在端口被占时拒绝启动,并打印占用进程的 PID。两个常见情况:

1. **上一次未正常停止**(终端关闭、登出、崩溃):
   ```bash
   lsof -nP -iTCP:8765 -sTCP:LISTEN      # 找到 PID
   kill <pid>                              # 然后重新 ./start.sh
   ```
2. **想同时跑两个 server**(开发+生产、或新旧代码对比):
   ```bash
   PCC_LIVE_PORT=8766 ./start.sh
   ```

### `pip install aliyun-nls` 失败或挂起

Aliyun SDK 仅在 Python 3.9+ 上验证过。解决方案:

1. 使用 `--no-deps` 并手动安装依赖
2. 使用全新 venv —— 系统 Python 可能有冲突包
3. 如果你在 Apple Silicon 上,确保使用原生 arm64 Python(不是 Rosetta)。运行 `python -c "import platform; print(platform.machine())"` 确认输出 `arm64`

### Aliyun NLS 连接失败(`InvalidToken` / 4xx)

三个 `.env` 凭证必须都填;缺值或拼错都会报鉴权错。完整注册清单见 [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](./phase_b/_reports/aliyun-asr-setup-2026-09-06.md)。常见错误:

- 项目类型选了"**一句话识别**"而不是"**实时语音识别**" → STT session 起不来
- 子账号没授予 `AliyunNLSFullAccess` → 403 Forbidden
- `.env` 中 `LLM_*` 与 `ALIYUN_*` 串槽 → start.sh 启动 OK,但首次 STT 请求时报 config-parse 错

### 浏览器未检测到麦克风

1. 检查你是否给 `127.0.0.1` 授了麦克风权限
2. 在 Chrome 中,打开 `chrome://settings/content/microphone` 并确认站点被允许
3. 先在 [onlinemictest.com](https://www.onlinemictest.com) 测试麦克风

### TTS 音频断断续续/有延迟

1. 使用有线耳机(蓝牙增加约 200 ms 延迟)
2. 将 TTS 模型降级到 `speech-2.6-turbo`(质量更低,更快)
3. 检查 `LOG_LEVEL=debug` 的网络时序

### 启动后报 `ModuleNotFoundError`

依赖没装到当前 Python。在项目根目录运行:

```bash
.venv/bin/pip install -r requirements.txt
```

`./start.sh` 已直接用 `.venv/bin/python`,无需激活 venv。

### 拒绝绑定 0.0.0.0

默认只绑 `127.0.0.1`(为防止音频泄漏到 LAN,默认拒绝外网暴露)。如需绑 `0.0.0.0`(例如远端机器上跑、另一台设备访问):

```bash
PCC_LIVE_ALLOW_LAN=1 ./start.sh
```

### 编辑 `tracker.csv` 时被截断到 ~95 列

Edit 工具对超长单行编辑会截断(tracker.csv schema 共 87 列 + 附加字段)。追加新 session 行用:

```bash
python -m phase_b.tracker.csv_append ...
```

不要手编 CSV。详见 memory `edit-tool-long-csv-truncation`。

---

## 9. 更新

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt --upgrade
```

Aliyun NLS 是托管云端点 —— 本地没有模型要升。轮换凭证时改 `.env` 然后 `./start.sh` 重启即可。