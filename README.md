# PCC Live Coach — Real-time Voice Practice for PCC Marker Training

> ⚠️ **Pre-alpha / Experimental.** This project is under active development and has not been released publicly yet. Functionality is incomplete and may change without notice.

> ⚠️ **NOT an ICF-certified tool.** The evaluation criteria are derived from a single real PCC supervision transcript and are not officially sanctioned by the International Coaching Federation (ICF). Do not use outputs for ICF credentialing applications. See [DISCLAIMER.md](DISCLAIMER.md).

---

## What is this?

**PCC Live Coach** is a local, privacy-first, browser-based practice tool for coaches preparing for the ICF Professional Certified Coach (PCC) credential. It runs on your machine, speaks with you in real time, and gives you objective measurements of three PCC markers that are difficult to assess from text alone:

- **5.5** — Coach allows for silence, pause, or reflection
- **6.6** — Coach allows client to finish without interrupting
- **7.6** — Coach asks clear, direct, primarily open-ended questions, one at a time, with rhythm

These three markers share a property: **they require audio**. Text-based practice (Phase A of the parent project) cannot tell you whether you let a 4-second silence breathe, or whether you interrupted your client at second 22 of their story. This tool exists to fill that gap.

It is **not** a substitute for real client practice hours. ICF requires submitted recordings from real clients, not AI personas. See [DISCLAIMER.md](DISCLAIMER.md).

---

## Highlights

- 🎙️ **Real-time voice conversation** with AI persona clients (built from your existing persona library)
- 📊 **Objective rhythm metrics** — silence duration, CPM (characters per minute), barge-in detection, question length, inter-question pause
- 🔒 **Privacy by configuration** — STT / LLM / TTS are independently switchable endpoints; self-host any of them to keep data on your machine. Default STT (Aliyun NLS) and LLM/TTS (MiniMax) are cloud-hosted — see [PRIVACY.md](PRIVACY.md).
- 🧠 **Aligned with existing pcc-assessor** — rhythm features feed back into your existing 37-marker evaluation pipeline
- 🌐 **Browser-based** — works in Chrome / Safari, no installation beyond Python

---

## LLM provider flexibility

The default LLM endpoint (`https://api.minimaxi.com/v1`, model `MiniMax-M3`) is a **placeholder** — the code uses the standard OpenAI Chat Completions API, so any OpenAI-compatible endpoint works. Switch by editing `.env`:

| Provider | `LLM_BASE_URL` | Privacy |
|---|---|---|
| **MiniMax API** (default) | `https://api.minimaxi.com/v1` | Cloud — text sent to MiniMax |
| **OpenAI** | `https://api.openai.com/v1` | Cloud — text sent to OpenAI |
| **DeepSeek** | `https://api.deepseek.com/v1` | Cloud — text sent to DeepSeek |
| **Azure OpenAI** | `https://<resource>.openai.azure.com/openai/deployments/<dep>` | Cloud — text sent to Azure |
| **Ollama** (local) | `http://127.0.0.1:11434/v1` | **Fully offline** |
| **LM Studio** (local) | `http://127.0.0.1:1234/v1` | **Fully offline** |
| **vLLM** (local) | `http://127.0.0.1:8000/v1` | **Fully offline**, GPU-accelerated |
| **OpenRouter / OneAPI** | `https://openrouter.ai/api/v1` | Cloud — aggregates many providers |

For **fully offline** operation, choose a local provider (Ollama / LM Studio / vLLM). No conversation text leaves your machine. See [INSTALL.md § Self-hosted LLM](INSTALL.md#self-hosted-llm-optional-for-full-privacy) and [PRIVACY.md § Supported LLM providers](PRIVACY.md#supported-llm-providers).

---

## Architecture (planned)

```
┌──────────────────────────────────────────────────────────┐
│  Browser (Chrome / Safari)                                │
│  ├─ Web Audio API: 16kHz PCM microphone capture           │
│  ├─ WebSocket client: bidirectional stream to backend    │
│  └─ Web Audio playback: TTS audio stream                  │
└────────────────────┬─────────────────────────────────────┘
                     │ WebSocket (wss://)
┌────────────────────▼─────────────────────────────────────┐
│  FastAPI / WebSocket server (single process, ~600 LoC)    │
│  ├─ Audio ingest → Aliyun NLS WS (configurable STT)       │
│  ├─ STT partial → LLM (HTTP streaming, MiniMax M3)        │
│  ├─ LLM stream → TTS (MiniMax T2A WS, streaming PCM)      │
│  ├─ Auto-submit on utterance_end + barge-in (cancel turn) │
│  └─ Rhythm extraction (silence / CPM / barge-in)          │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  Persistence (files, no traditional database)              │
│  ├─ Practice audio: practice-logs/sessions/*.mp3          │
│  ├─ Per-session artifacts: practice-logs/sessions/<YYYY-MM-DD>-session-NN/ │
│  └─ Append to existing progress/tracker-sessions.csv │
└──────────────────────────────────────────────────────────┘
```

---

## Status

> ⚠️ **Phase B code is shipped but not enabled.** Backend (`phase_b/`, 3546 LoC) and frontend (`phase_b/static/`, 1067 LoC) are committed and runnable via `./start.sh`, but product stability has not been validated against the parent project's trigger conditions (see below). Expect rough edges if you try it today.

- ✅ STT swap landed — FunASR → Aliyun NLS streaming WebSocket (2026-09-06). Real-time partial + sentence-end trigger now drives auto-submit. See [data-flow report](./phase_b/_reports/phase-b-data-flow-2026-09-06.md).
- ✅ End-to-end voice pipeline — first real session `real-2026-09-06-08` produced dialogue JSONL + raw wav + rhythm features (no transcript placeholders).
- ✅ Dashboard v2 — three pages (entry / session / dashboard) with KPI tiles, inline audio playback, transcript table, trending-chart regen, and PCC 37-marker assessment button (2026-10-04).
- ✅ XSS hardening — `textContent` replaces `innerHTML` in transcript render (2026-10-04).
- ⚠️ Backend code — `phase_b/` (28 .py files, 3546 LoC) + 18 test files under `tests/phase_b/`. **Shipped, not enabled.**
- ⚠️ Frontend code — `phase_b/static/` (index.html + app.js + audio_state.js + styles.css, 1067 LoC). **Shipped, not enabled.**

**Why "shipped but not enabled"?** The parent project spec ([`PCC-陪练与评估-Agent-设计方案.html`](./PCC-陪练与评估-Agent-设计方案.html)) defines trigger conditions for activating Phase B:

1. ≥10 complete real-coach practice sessions
2. Structural problems (issue clarification, closing design, cognitive breakthrough) consistently resolved
3. Remaining weaknesses concentrated in 5.5 / 6.6 / 7.6

We are at 1 real session. Conditions are not yet met — the code is committed so the launch process stays well-understood, but it should not be treated as a production-ready product.

---

## Quick start

```bash
# One-shot launcher (activates venv, checks .env, opens browser):
./start.sh
# or, on Mac, double-click start.command in Finder.
```

For full instructions, see [INSTALL.md](INSTALL.md) and [DEPLOY.md](DEPLOY.md).

---

## Documentation

- [INSTALL.md](INSTALL.md) — environment setup, venv, Aliyun NLS credentials (default STT)
- [DEPLOY.md](DEPLOY.md) — local deployment, ports, firewall, model cache
- [PRIVACY.md](PRIVACY.md) — privacy guarantees, configurable LLM endpoint
- [DISCLAIMER.md](DISCLAIMER.md) — ICF boundary, no warranty, no liability
- [FAQ.md](FAQ.md) — common questions
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common errors and workarounds
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — community norms
- [LICENSE](LICENSE) — Apache-2.0

---

## License

Apache License 2.0. See [LICENSE](LICENSE).

Third-party attributions:

- Aliyun NLS Python SDK (`aliyun-nls`) — Apache-2.0 (default STT endpoint)
- PyTorch — BSD-3-Clause
- FastAPI — MIT

---

## Maintainer

项目作者 · Individual maintainer · No organization affiliation

---

<br/>
<br/>

# PCC Live Coach — ICF PCC 标记训练的实时语音练习工具

> ⚠️ **预发布 / 实验性。** 本项目处于活跃开发阶段,尚未公开发布。功能不完整,可能随时变更。

> ⚠️ **不是 ICF 认证工具。** 评估标准来自一份真实 PCC 督导录音的本地校准,未经国际教练联合会(ICF)官方批准。**不得**用于 ICF 认证申请。详见 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 这是什么?

**PCC Live Coach** 是一个本地化、隐私优先、基于浏览器的练习工具,服务于备考 ICF 专业认证教练(PCC)的人群。它在你的机器上运行,与你说实时语音对话,并给出三项目前很难仅凭文本来评估的 PCC 标记的客观测量:

- **5.5** — 教练允许沉默、停顿或反思
- **6.6** — 教练让客户把话说完而不打断
- **7.6** — 教练提问清晰、直接、以开放式为主、一次一个、有节奏

这三项标记有一个共同点:**它们需要音频**。仅凭文字练习(母项目的 Phase A)无法告诉你是否给一段 4 秒的沉默留了呼吸空间,也无法告诉你是否在客户说话第 22 秒时打断。本工具的存在就是为了填补这个空白。

**它不能替代真实客户的练习时长。** ICF 要求提交的录音来自真实客户,而不是 AI 人格。详见 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 核心特性

- 🎙️ **实时语音对话** —— 与 AI 人格客户对话(基于你现有的人格库)
- 📊 **客观节奏指标** —— 沉默时长、CPM(每分钟字数)、打断检测、问题长度、问题间隔
- 🔒 **按配置保隐私** —— STT / LLM / TTS 端点可独立切换;自托管任一端点即可让数据留在本地。默认 STT(Aliyun NLS)与 LLM/TTS(MiniMax)均为云端 —— 详见 [PRIVACY.md](PRIVACY.md)。
- 🧠 **与现有 pcc-assessor 对齐** —— 节奏特征反馈到现有的 37 标记评估流水线
- 🌐 **基于浏览器** —— Chrome / Safari 直接使用,只需装 Python

---

## LLM provider 灵活性

默认 LLM 端点(`https://api.minimaxi.com/v1`,模型 `MiniMax-M3`)是**占位符** —— 代码使用标准 OpenAI Chat Completions API,因此任何 OpenAI 兼容端点都可以工作。通过编辑 `.env` 切换:

| Provider | `LLM_BASE_URL` | 隐私 |
|---|---|---|
| **MiniMax API**(默认) | `https://api.minimaxi.com/v1` | 云端 —— 文本发往 MiniMax |
| **OpenAI** | `https://api.openai.com/v1` | 云端 —— 文本发往 OpenAI |
| **DeepSeek** | `https://api.deepseek.com/v1` | 云端 —— 文本发往 DeepSeek |
| **Azure OpenAI** | `https://<resource>.openai.azure.com/openai/deployments/<dep>` | 云端 —— 文本发往 Azure |
| **Ollama**(本地) | `http://127.0.0.1:11434/v1` | **完全离线** |
| **LM Studio**(本地) | `http://127.0.0.1:1234/v1` | **完全离线** |
| **vLLM**(本地) | `http://127.0.0.1:8000/v1` | **完全离线**,GPU 加速 |
| **OpenRouter / OneAPI** | `https://openrouter.ai/api/v1` | 云端 —— 聚合多家 provider |

要实现**完全离线**运行,选择本地 provider(Ollama / LM Studio / vLLM)。对话文本不会离开你的机器。详见 [INSTALL.md § 自托管 LLM](INSTALL.md#自托管-llm可选完全隐私) 和 [PRIVACY.md § 支持的 LLM providers](PRIVACY.md#支持的-llm-providers)。

---

## 架构(计划中)

```
┌──────────────────────────────────────────────────────────┐
│  浏览器 (Chrome / Safari)                                 │
│  ├─ Web Audio API: 16kHz PCM 麦克风采集                  │
│  ├─ WebSocket 客户端:与后端双向流                        │
│  └─ Web Audio 播放:TTS 音频流                            │
└────────────────────┬─────────────────────────────────────┘
                     │ WebSocket (wss://)
┌────────────────────▼─────────────────────────────────────┐
│  FastAPI / WebSocket server (单进程,~600 行 Python)       │
│  ├─ 音频接收 → Aliyun NLS WS (可配置 STT)                │
│  ├─ STT partial → LLM (HTTP 流式,MiniMax M3)            │
│  ├─ LLM 流 → TTS (MiniMax T2A WS,流式 PCM)              │
│  ├─ utterance_end 自动提交 + barge-in(取消当前轮次)      │
│  └─ 节奏特征提取 (沉默 / CPM / 打断)                     │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  持久化层 (文件,无传统数据库)                             │
│  ├─ 练习音频: practice-logs/sessions/*.mp3                │
│  ├─ 逐场派生产物: practice-logs/sessions/<YYYY-MM-DD>-session-NN/          │
│  └─ 追加到现有 progress/tracker-sessions.csv         │
└──────────────────────────────────────────────────────────┘
```

---

## 当前状态

> ⚠️ **Phase B 代码已写但暂未启用。** 后端(`phase_b/`,3546 行)+ 前端(`phase_b/static/`,1067 行)已提交且可通过 `./start.sh` 启动,但产品稳定性未根据母项目触发条件(见下)验证。如果你现在试用,预计会遇到边缘情况。

- ✅ STT 切换落地 —— FunASR → Aliyun NLS 流式 WebSocket(2026-09-06)。实时 partial + 句尾触发自动提交。详见 [data-flow 报告](./phase_b/_reports/phase-b-data-flow-2026-09-06.md)。
- ✅ 端到端语音管线 —— 首场真人对话 `real-2026-09-06-08` 完整产出 dialogue JSONL + raw wav + rhythm 特征(非占位 transcript)。
- ✅ Dashboard v2 —— 三页面(entry / session / dashboard),含 KPI 卡、内嵌音频播放、transcript 表、trending chart 重生成、PCC 37-marker 评估按钮(2026-10-04)。
- ✅ XSS 加固 —— transcript 渲染 `innerHTML` 换 `textContent`(2026-10-04)。
- ⚠️ 后端代码 —— `phase_b/`(28 个 .py 文件,3546 行)+ `tests/phase_b/` 下 18 个测试文件。**已写、未启用。**
- ⚠️ 前端代码 —— `phase_b/static/`(index.html + app.js + audio_state.js + styles.css,1067 行)。**已写、未启用。**

**为什么"已写但未启用"?** 母项目 spec ([`PCC-陪练与评估-Agent-设计方案.html`](./PCC-陪练与评估-Agent-设计方案.html)) 定义了 Phase B 启动的触发条件:

1. Phase A 已完成 ≥10 场完整真人陪练
2. tracker 显示结构性问题(议题澄清、结尾设计、认知突破)已稳定解决
3. 剩余差距集中在 5.5 / 6.6 / 7.6(只有实时语音才能练的维度)

当前状态:**1 场真人陪练**(2026-08-31)。条件未满足。代码已提交是为了发布流程清晰可控,但**不应视为生产就绪产品**。

---

## 快速开始(代码已写、暂未启用)

代码发布后,本节将包含:

```bash
git clone <你的私有仓库>
cd pcc-live-coach
python -m venv .venv
source .venv/bin/activate
pip install -e .
./start.sh                       # 或 python -m phase_b
# 浏览器打开 http://127.0.0.1:8765
```

完整说明见 [INSTALL.md](INSTALL.md) 和 [DEPLOY.md](DEPLOY.md)。

---

## 文档

- [INSTALL.md](INSTALL.md) —— 环境设置、venv、Aliyun NLS 凭证(默认 STT)
- [DEPLOY.md](DEPLOY.md) —— 本地部署、端口、防火墙、模型缓存
- [PRIVACY.md](PRIVACY.md) —— 隐私保证、可配置的 LLM 端点
- [DISCLAIMER.md](DISCLAIMER.md) —— ICF 边界、不作担保、责任限制
- [FAQ.md](FAQ.md) —— 常见问题
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) —— 常见错误与解决方案
- [CONTRIBUTING.md](CONTRIBUTING.md) —— 如何贡献
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) —— 社区规范
- [LICENSE](LICENSE) —— Apache-2.0

---

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE)。

第三方致谢:

- Aliyun NLS Python SDK(`aliyun-nls`)—— Apache-2.0(默认 STT 端点)
- PyTorch —— BSD-3-Clause
- FastAPI —— MIT

---

## 维护者

项目作者 · 个人维护者 · 无组织关联