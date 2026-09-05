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
- 🔒 **Privacy-first** — FunASR speech recognition runs **locally on your CPU**. Audio never leaves your machine.
- 🧠 **Aligned with existing pcc-assessor** — rhythm features feed back into your existing 37-marker evaluation pipeline
- 🌐 **Browser-based** — works in Chrome / Safari, no installation beyond Python

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
│  ├─ Audio ingest → STT queue                              │
│  ├─ FunASR iic/SenseVoiceSmall (local, CPU)          │
│  ├─ STT text → LLM (HTTP streaming)                       │
│  ├─ LLM stream → TTS (WebSocket streaming)                │
│  ├─ fsmn-vad barge-in: client speaks → stop TTS + LLM  │
│  └─ Rhythm feature extraction (silence / CPM / barge-in)   │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  Persistence (files, no traditional database)              │
│  ├─ Real practice audio: practice-logs/真人练习/*.mp3     │
│  ├─ Per-session artifacts: practice-logs/真人练习/<YYYY-MM-DD>-session-NN/ │
│  └─ Append to existing progress/tracker-real-sessions.csv │
└──────────────────────────────────────────────────────────┘
```

---

## Status

> ⚠️ **Phase B code is shipped but not enabled.** Backend (`phase_b/`, 2311 LoC) and frontend (`phase_b/static/`, 614 LoC) are committed and runnable via `./start.sh`, but product stability has not been validated against the parent project's trigger conditions (see below). Expect rough edges if you try it today.

- ✅ Technical spike complete — see [spike report](../../phase-b-spike-report-2026-09-01.md) · [GitHub research delta](../../phase-b-github-research-2026-09-01.md)
- ✅ Environment validated — FunASR 1.4.11 on Python 3.9 + CPU torch, RTF 0.029 on M3 Pro
- ✅ HTTP API validated — `/v1/audio/transcriptions` returns correct text for real client audio
- ✅ MCP server validated — funasr_mcp.py imports and exposes `transcribe(audio_path, language="auto")` tool
- ✅ Wireframe — see [phase-b-wireframe-2026-09-03.html](../../phase-b-wireframe-2026-09-03.html) (3 pages, static HTML, no JS)
- ⚠️ Backend code — `phase_b/` (26 .py files, 2311 LoC) + 9 test files under `tests/phase_b/`. **Shipped, not enabled.**
- ⚠️ Frontend code — `phase_b/static/` (index.html + app.js + styles.css, 614 LoC). **Shipped, not enabled.**

**Why "shipped but not enabled"?** The parent project spec ([`PCC-陪练与评估-Agent-设计方案.html`](../../../../PCC-陪练与评估-Agent-设计方案.html)) defines trigger conditions for activating Phase B:

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

- [INSTALL.md](INSTALL.md) — environment setup, venv, FunASR model download
- [DEPLOY.md](DEPLOY.md) — local deployment, ports, firewall, model cache
- [PRIVACY.md](PRIVACY.md) — privacy guarantees, MiniMax LLM exception
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

- FunASR by Alibaba DAMO Academy — MIT License
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
- 🔒 **隐私优先** —— FunASR 语音识别**在你 CPU 上本地执行**,从不离开你的机器
- 🧠 **与现有 pcc-assessor 对齐** —— 节奏特征反馈到现有的 37 标记评估流水线
- 🌐 **基于浏览器** —— Chrome / Safari 直接使用,只需装 Python

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
│  ├─ 音频接收 → STT 队列                                  │
│  ├─ FunASR iic/SenseVoiceSmall (本地, CPU)          │
│  ├─ STT 文本 → LLM (HTTP 流式)                           │
│  ├─ LLM 流 → TTS (WebSocket 流式)                        │
│  ├─ fsmn-vad barge-in: 客户说话 → 停 TTS + 取消 LLM    │
│  └─ 节奏特征提取 (沉默 / CPM / 打断)                     │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  持久化层 (文件,无传统数据库)                             │
│  ├─ 真人练习音频: practice-logs/真人练习/*.mp3          │
│  ├─ 逐场派生产物: practice-logs/真人练习/<YYYY-MM-DD>-session-NN/          │
│  └─ 追加到现有 progress/tracker-real-sessions.csv         │
└──────────────────────────────────────────────────────────┘
```

---

## 当前状态

> ⚠️ **Phase B 代码已写但暂未启用。** 后端(`phase_b/`,2311 行)+ 前端(`phase_b/static/`,614 行)已提交且可通过 `./start.sh` 启动,但产品稳定性未根据母项目触发条件(见下)验证。如果你现在试用,预计会遇到边缘情况。

- ✅ 技术 spike 完成 — 详见 [spike 报告](../../phase-b-spike-report-2026-09-01.md) · [GitHub 调研追加](../../phase-b-github-research-2026-09-01.md)
- ✅ 环境已验证 — FunASR 1.4.11 + Python 3.9 + CPU torch,M3 Pro 上 RTF 0.029
- ✅ HTTP API 已验证 — `/v1/audio/transcriptions` 对真实客户音频返回正确文本
- ✅ MCP server 已验证 — funasr_mcp.py import OK,暴露 `transcribe(audio_path, language="auto")` 工具
- ✅ Wireframe — 详见 [phase-b-wireframe-2026-09-03.html](../../phase-b-wireframe-2026-09-03.html)(3 页静态 HTML)
- ⚠️ 后端代码 — `phase_b/`(26 个 .py 文件,2311 行)+ `tests/phase_b/` 下 9 个测试文件。**已写、未启用。**
- ⚠️ 前端代码 — `phase_b/static/`(index.html + app.js + styles.css,614 行)。**已写、未启用。**

**为什么"已写但未启用"?** 母项目 spec ([`PCC-陪练与评估-Agent-设计方案.html`](../../../../PCC-陪练与评估-Agent-设计方案.html)) 定义了 Phase B 启动的触发条件:

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
python -m phase_b.server
# 浏览器打开 http://127.0.0.1:8000
```

完整说明见 [INSTALL.md](INSTALL.md) 和 [DEPLOY.md](DEPLOY.md)。

---

## 文档

- [INSTALL.md](INSTALL.md) —— 环境设置、venv、FunASR 模型下载
- [DEPLOY.md](DEPLOY.md) —— 本地部署、端口、防火墙、模型缓存
- [PRIVACY.md](PRIVACY.md) —— 隐私保证、MiniMax LLM 例外说明
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

- FunASR by Alibaba DAMO Academy —— MIT 许可
- PyTorch —— BSD-3-Clause
- FastAPI —— MIT

---

## 维护者

项目作者 · 个人维护者 · 无组织关联