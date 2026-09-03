# Installation Guide

Last updated: 2026-09-03

> ⚠️ This document describes installation of the **planned** PCC Live Coach system. The actual code has not been released yet — these instructions will become executable once the first tagged version ships.
>
> The instructions below are based on the environment validation report ([phase-b-env-setup-2026-09-01.md](../../phase-b-env-setup-2026-09-01.md)) which proved the stack works end-to-end on macOS M-series with Python 3.9.

---

## 1. Requirements

### Hardware

- **CPU**: Apple Silicon (M1 / M2 / M3 / M4) recommended. Intel macOS works but is ~3× slower for FunASR.
- **RAM**: 8 GB minimum, 16 GB recommended (FunASR model loaded into memory).
- **Disk**: ~3 GB free (Python venv + FunASR model cache).
- **Microphone**: Any built-in or USB mic. Headset recommended to avoid echo with TTS playback.

### Software

- **macOS**: 13.0 Ventura or later (for Apple Silicon native PyTorch).
- **Python**: 3.9.6 or later (3.9 / 3.10 / 3.11 all tested in spike).
- **Git**: for cloning the repo.
- **ffmpeg**: required by librosa for audio I/O. Install with `brew install ffmpeg`.
- **Chrome or Safari**: for the browser frontend.

### Network (first run only)

- ~220 MB download from ModelScope hub for the FunASR `paraformer-zh-streaming` model.
- HuggingFace Hub access if you switch to a non-ModelScope model.
- Outbound HTTPS to your LLM endpoint (default: MiniMax API).
- Outbound HTTPS to your TTS endpoint (default: MiniMax T2A).

After the first run, STT works offline. LLM / TTS still require network unless self-hosted.

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

- FunASR pulls in ~25 transitive dependencies (torch, transformers, librosa, etc.). A venv keeps them isolated from your system Python.
- The venv is gitignored — no risk of accidentally committing torch (≈ 800 MB).

---

## 4. Install Python dependencies

When code is released, the project will ship a `pyproject.toml` (or `requirements.txt`):

```bash
pip install -e .
```

Until then, the spike validation used the following minimal dependency set (tested end-to-end on Python 3.9 + Apple Silicon):

```
funasr==1.4.11
torch==2.8.0
modelscope
huggingface_hub
librosa
soundfile
safetensors
sentencepiece
tensorboardx
tiktoken
transformers
umap-learn
websockets
jaconv
jamo
jieba
kaldiio
omegaconf
oss2
rapidfuzz
hydra-core
```

If `pip install funasr` fails in your environment (this was observed during the spike — see `phase-b-env-setup-2026-09-01.md` for the workaround), use `pip install --no-deps funasr` and install the rest manually.

---

## 5. Download the FunASR model (first run only)

The default ASR model is `paraformer-zh-streaming` from ModelScope. It is downloaded automatically the first time you run the server. To pre-download:

```bash
python -c "from funasr import AutoModel; m = AutoModel(model='paraformer-zh-streaming')"
```

The model is cached in `~/.cache/modelscope/` (~220 MB). Subsequent runs use the cache and require no network.

### Alternative models

If you want a different ASR model (e.g., for Cantonese, English, or code-switching), edit `config/asr.yaml` (planned):

```yaml
asr:
  model: "paraformer-zh-streaming"   # default
  # model: "paraformer-en-streaming" # English
  # model: "SenseVoiceSmall"         # multilingual, larger
```

Each model has its own download size and license terms. See the [FunASR model zoo](https://www.modelscope.cn/models?page=1&tasks=auto-speech-recognition).

---

## 6. Configure environment variables

Create a `.env` file in the project root (gitignored):

```bash
# LLM endpoint (default: MiniMax)
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=<your-key-here>
LLM_MODEL=MiniMax-M3

# TTS endpoint (default: MiniMax T2A)
TTS_BASE_URL=wss://api.minimaxi.com/ws/v1/t2a_v2
TTS_API_KEY=<your-key-here>
TTS_MODEL=speech-2.6-hd
TTS_VOICE=male-qn-jingying

# Server
HOST=127.0.0.1
PORT=8765
LOG_LEVEL=info
```

> ⚠️ **Never commit `.env` to git.** It contains your API keys. The repo's `.gitignore` excludes it by default.

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

Once the code ships:

```bash
# Check Python deps
python -c "import funasr, torch, fastapi, websockets; print('OK')"

# Check FunASR model is downloaded
ls ~/.cache/modelscope/hub/  # should contain paraformer-zh-streaming

# Start the server (planned command)
python -m pcc_live_coach.server

# Open browser to http://127.0.0.1:8765
```

Expected log output:

```
[INFO] FunASR model loaded: paraformer-zh-streaming
[INFO] LLM endpoint: https://api.minimaxi.com/v1 (model=MiniMax-M3)
[INFO] TTS endpoint: wss://api.minimaxi.com/ws/v1/t2a_v2 (model=speech-2.6-hd)
[INFO] Server listening on http://127.0.0.1:8765
```

---

## 8. Troubleshooting

### `pip install funasr` fails or hangs

This was the main obstacle during the spike. Workarounds:

1. Use `--no-deps` and install dependencies manually (see Section 4).
2. Use a fresh venv — system Python may have conflicting packages.
3. If you're on Apple Silicon, ensure you're using a native arm64 Python (not Rosetta). Run `python -c "import platform; print(platform.machine())"` and confirm it prints `arm64`.

### FunASR model download is slow or fails

ModelScope's main endpoint is in China. If you're outside China and the download is slow:

1. Set `MODELSCOPE_ENDPOINT=https://www.modelscope.cn` (default).
2. If still slow, manually download from [modelscope.cn](https://www.modelscope.cn/) and place in `~/.cache/modelscope/hub/`.

### Microphone not detected in browser

1. Check that you granted microphone permission to `127.0.0.1`.
2. In Chrome, open `chrome://settings/content/microphone` and verify the site is allowed.
3. Test your mic at [mic.testsite.com](https://www.onlinemictest.com) first.

### TTS audio is choppy / laggy

1. Use a wired headset (Bluetooth adds ~200 ms latency).
2. Reduce TTS model to `speech-2.6-turbo` (lower quality, faster).
3. Check `LOG_LEVEL=debug` for network timing.

---

## 9. Updating

```bash
git pull
source .venv/bin/activate
pip install -e . --upgrade
```

FunASR models do not auto-update. To upgrade the ASR model:

```bash
rm -rf ~/.cache/modelscope/hub/paraformer-zh-streaming
python -c "from funasr import AutoModel; m = AutoModel(model='paraformer-zh-streaming')"
```

---

<br/>
<br/>

# 安装指南

最后更新:2026-09-03

> ⚠️ 本文档描述**计划中**的 PCC Live Coach 系统安装步骤。实际代码尚未发布 —— 这些说明将在第一个标记版本发布后变为可执行。
>
> 以下说明基于环境验证报告([phase-b-env-setup-2026-09-01.md](../../phase-b-env-setup-2026-09-01.md)),该报告证明该技术栈在 macOS M 系列 + Python 3.9 上端到端可用。

---

## 1. 需求

### 硬件

- **CPU**: 推荐 Apple Silicon (M1 / M2 / M3 / M4)。Intel macOS 可用,但 FunASR 慢约 3 倍。
- **内存**: 最低 8 GB,推荐 16 GB(FunASR 模型加载到内存)。
- **磁盘**: ~3 GB 可用空间(Python venv + FunASR 模型缓存)。
- **麦克风**: 任何内置或 USB 麦克风。推荐使用耳机以避免与 TTS 播放产生回声。

### 软件

- **macOS**: 13.0 Ventura 或更高(为了 Apple Silicon 原生 PyTorch)
- **Python**: 3.9.6 或更高(3.9 / 3.10 / 3.11 都在 spike 中测试过)
- **Git**: 用于克隆仓库
- **ffmpeg**: librosa 处理音频 I/O 需要。通过 `brew install ffmpeg` 安装
- **Chrome 或 Safari**: 浏览器前端

### 网络(仅首次运行)

- 从 ModelScope hub 下载 ~220 MB 的 FunASR `paraformer-zh-streaming` 模型
- 如果切换到非 ModelScope 模型,需要 HuggingFace Hub 访问
- 你的 LLM 端点的出站 HTTPS(默认:MiniMax API)
- 你的 TTS 端点的出站 HTTPS(默认:MiniMax T2A)

首次运行后,STT 可离线工作。LLM / TTS 仍需要网络,除非自托管。

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

- FunASR 拉入约 25 个传递依赖(torch、transformers、librosa 等)。venv 保持它们与系统 Python 隔离
- venv 被 gitignore —— 避免意外提交 torch(约 800 MB)

---

## 4. 安装 Python 依赖

代码发布后,项目将附带 `pyproject.toml`(或 `requirements.txt`):

```bash
pip install -e .
```

在那之前,spike 验证使用了以下最小依赖集(在 Python 3.9 + Apple Silicon 上端到端测试):

```
funasr==1.4.11
torch==2.8.0
modelscope
huggingface_hub
librosa
soundfile
safetensors
sentencepiece
tensorboardx
tiktoken
transformers
umap-learn
websockets
jaconv
jamo
jieba
kaldiio
omegaconf
oss2
rapidfuzz
hydra-core
```

如果 `pip install funasr` 在你的环境中失败(spike 期间观察到 —— 详见 `phase-b-env-setup-2026-09-01.md` 的解决方案),使用 `pip install --no-deps funasr` 并手动安装其余依赖。

---

## 5. 下载 FunASR 模型(仅首次运行)

默认 ASR 模型是 ModelScope 的 `paraformer-zh-streaming`。它在你第一次运行服务器时自动下载。要预下载:

```bash
python -c "from funasr import AutoModel; m = AutoModel(model='paraformer-zh-streaming')"
```

模型缓存在 `~/.cache/modelscope/`(~220 MB)。后续运行使用缓存,不需要网络。

### 替代模型

如果你想要不同的 ASR 模型(例如粤语、英语、中英混合),编辑 `config/asr.yaml`(计划中):

```yaml
asr:
  model: "paraformer-zh-streaming"   # 默认
  # model: "paraformer-en-streaming" # 英语
  # model: "SenseVoiceSmall"         # 多语言,更大
```

每个模型都有自己的下载大小和许可条款。详见 [FunASR 模型库](https://www.modelscope.cn/models?page=1&tasks=auto-speech-recognition)。

---

## 6. 配置环境变量

在项目根目录创建 `.env` 文件(被 gitignore):

```bash
# LLM 端点(默认:MiniMax)
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=<your-key-here>
LLM_MODEL=MiniMax-M3

# TTS 端点(默认:MiniMax T2A)
TTS_BASE_URL=wss://api.minimaxi.com/ws/v1/t2a_v2
TTS_API_KEY=<your-key-here>
TTS_MODEL=speech-2.6-hd
TTS_VOICE=male-qn-jingying

# 服务器
HOST=127.0.0.1
PORT=8765
LOG_LEVEL=info
```

> ⚠️ **永远不要将 `.env` 提交到 git。** 它包含你的 API 密钥。仓库的 `.gitignore` 默认排除它。

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

代码发布后:

```bash
# 检查 Python 依赖
python -c "import funasr, torch, fastapi, websockets; print('OK')"

# 检查 FunASR 模型已下载
ls ~/.cache/modelscope/hub/  # 应包含 paraformer-zh-streaming

# 启动服务器(计划中的命令)
python -m pcc_live_coach.server

# 浏览器打开 http://127.0.0.1:8765
```

预期日志输出:

```
[INFO] FunASR model loaded: paraformer-zh-streaming
[INFO] LLM endpoint: https://api.minimaxi.com/v1 (model=MiniMax-M3)
[INFO] TTS endpoint: wss://api.minimaxi.com/ws/v1/t2a_v2 (model=speech-2.6-hd)
[INFO] Server listening on http://127.0.0.1:8765
```

---

## 8. 故障排除

### `pip install funasr` 失败或挂起

这是 spike 期间遇到的主要障碍。解决方案:

1. 使用 `--no-deps` 并手动安装依赖(见第 4 节)
2. 使用全新 venv —— 系统 Python 可能有冲突包
3. 如果你在 Apple Silicon 上,确保使用原生 arm64 Python(不是 Rosetta)。运行 `python -c "import platform; print(platform.machine())"` 确认输出 `arm64`

### FunASR 模型下载慢或失败

ModelScope 的主要端点在中国。如果你在国外且下载慢:

1. 设置 `MODELSCOPE_ENDPOINT=https://www.modelscope.cn`(默认)
2. 如果仍然慢,手动从 [modelscope.cn](https://www.modelscope.cn/) 下载并放到 `~/.cache/modelscope/hub/`

### 浏览器未检测到麦克风

1. 检查你是否给 `127.0.0.1` 授了麦克风权限
2. 在 Chrome 中,打开 `chrome://settings/content/microphone` 并确认站点被允许
3. 先在 [onlinemictest.com](https://www.onlinemictest.com) 测试麦克风

### TTS 音频断断续续/有延迟

1. 使用有线耳机(蓝牙增加约 200 ms 延迟)
2. 将 TTS 模型降级到 `speech-2.6-turbo`(质量更低,更快)
3. 检查 `LOG_LEVEL=debug` 的网络时序

---

## 9. 更新

```bash
git pull
source .venv/bin/activate
pip install -e . --upgrade
```

FunASR 模型不会自动更新。要升级 ASR 模型:

```bash
rm -rf ~/.cache/modelscope/hub/paraformer-zh-streaming
python -c "from funasr import AutoModel; m = AutoModel(model='paraformer-zh-streaming')"
```