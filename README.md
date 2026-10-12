# PCC Live Coach — PCC Marker Practice (text mode on by default, voice mode requires setup)

> ⚠️ **Pre-alpha / Experimental.** This project is under active development and has not been released publicly yet. Functionality is incomplete and may change without notice.

> ⚠️ **NOT an ICF-certified tool.** The evaluation criteria are derived from a single real PCC supervision transcript and are not officially sanctioned by the International Coaching Federation (ICF). Do not use outputs for ICF credentialing applications. See [DISCLAIMER.md](DISCLAIMER.md).

---

## What is this?

**PCC Live Coach** is a PCC exam prep practice tool for coaches preparing for the ICF Professional Certified Coach (PCC) credential. It supports **two complementary modes** — text mode is available now and covers most of the training, voice mode adds the audio-only dimensions.

| | Text mode (default) | Voice mode (Phase B, in preparation) |
|---|---|---|
| **Status** | ✅ Available now | ⚠️ Code shipped, awaiting trigger conditions (≥10 real-coach sessions + structural issues resolved + remaining gaps in 5.5/6.6/7.6) |
| **How you practice** | Type messages in VS Code Claude Code, switching to the `pcc-coachee` agent | Speak into your mic in a browser; STT/LLM/TTS pipeline runs on your machine |
| **Time to first session** | ~30 seconds (if VS Code + Claude Code are already installed) | ~30 minutes (Python venv + Aliyun NLS account + `.env` + microphone) |
| **PCC markers covered** | 34 of 37 (everything except 5.5, 6.6, 7.6) | All 37 (adds the 3 audio-only markers) |
| **Privacy** | Text only; swap to local LLM (Ollama / LM Studio / vLLM) for fully offline | Default cloud (Aliyun NLS + MiniMax); any of STT/LLM/TTS can be swapped to local |

### 30-second text-mode quickstart

1. Open VS Code with the Claude Code extension.
2. Switch to the `pcc-coachee` agent (full SOP: [personas/README.md § 配套练习 SOP](personas/README.md)).
3. Type: `开始陪练,选 vec-08` (or pick your own; see [personas/README.md](personas/README.md) — easy difficulty-1 starters: vec-06 / vec-08 / voc-05).

No Python, no `.env`, no Aliyun account, no microphone. The `pcc-coachee` agent reads its persona file and starts the roleplay. When the coach ends the session, type `全评` to hand off to the `pcc-assessor` agent for a 37-marker HTML report.

For voice mode setup, see [INSTALL.md](INSTALL.md).

It is **not** a substitute for real client practice hours. ICF requires submitted recordings from real clients, not AI personas. See [DISCLAIMER.md](DISCLAIMER.md).

---

## Highlights

- 💬 **Text-mode coaching available now** — switch to the `pcc-coachee` agent in VS Code Claude Code and start a 45-min roleplay in 30 seconds (covers 34/37 PCC markers, zero install)
- 🎙️ **Voice mode opt-in** — `phase_b/` WebSocket pipeline ready; always opt-in (requires Aliyun account + `.env` + microphone). Docs frame it as "experimental" until ≥10 real-coach sessions are logged (see [Status](#status))
- 📊 **Objective rhythm metrics** — silence duration, CPM (characters per minute), barge-in detection, question length, inter-question pause (voice mode only)
- 🔒 **Privacy by configuration** — STT / LLM / TTS are independently switchable endpoints; self-host any of them to keep data on your machine. Default STT (Aliyun NLS) and LLM/TTS (MiniMax) are cloud-hosted — see [PRIVACY.md](PRIVACY.md).
- 🧠 **Aligned with existing pcc-assessor** — both text and voice sessions feed into the same 37-marker evaluation pipeline (text-mode SOP: [personas/README.md](personas/README.md))
- 🌐 **Browser-based voice UI** — Chrome / Safari for voice mode; text mode needs only VS Code + Claude Code (no Python required)

---

## 5 分钟入门路径(小白先看)

> 如果你不确定从哪儿开始,按你的画像走下面 5 条路径之一:

| 你是谁 | 先看 | 然后 |
|---|---|---|
| **我现在就要练,什么都不想装** | （无需阅读其他文档）— VS Code + Claude Code → 切到 `pcc-coachee` agent → 输入 `开始陪练,选 vec-08`。30 秒上场,覆盖 34/37 个 markers | 完整 SOP 见 [personas/README.md § 30 秒上手](personas/README.md) |
| **PCC 备考教练(领域熟、技术小白)** | [FAQ.md § PCC 概念速通](FAQ.md#pcc-概念速通领域小白) — 5 分钟搞懂 37 markers / 5.5-6.6-7.6 是什么 | 文字版先跑(见上方↑),再考虑语音版 → [INSTALL.md § 1-7](INSTALL.md) |
| **开发者(技术熟、领域小白)** | [FAQ.md § PCC 概念速通](FAQ.md#pcc-概念速通领域小白) — 看 ICF PCC 评估口径 | 文字版先跑(见上方↑),再换本地 LLM 全离线([INSTALL.md § Self-hosted LLM](INSTALL.md#self-hosted-llm-optional-for-full-privacy)) |
| **完全小白(技术 + 领域都不熟)** | [FAQ.md](FAQ.md) 通读一遍(~10 分钟) | 文字版先跑(无需任何 install) → 唤 `pcc-assessor` 看评估 → 再考虑语音版 |
| **只想看现状 / 不准备上手** | [Status § Two modes: text now / voice in preparation](#status) | 文字版立即可用,语音版等 3 个 trigger condition |

### 真实使用流程

> 💡 **文字版(今天就能用,推荐路径)**:VS Code + Claude Code → 切到 `pcc-coachee` agent → 输入 `开始陪练,选 vec-08`。详见 [What is this? § 30-second text-mode quickstart](#what-is-this)。

语音版流程(代码已写、默认未启用):

```
① 装环境 (INSTALL § 1-4)        ~10 分钟
② 拿 Aliyun NLS 三件套          ~15 分钟 (要去阿里云控制台开项目 + 子账号)
③ 填 .env 跑 ./start.sh          ~1 分钟
④ 浏览器选 persona 开练          45 分钟一场
⑤ 收场后唤 pcc-assessor 评估     ~5 分钟 (出 HTML 报告 + tracker CSV 追加)
```

> ⚠️ **Pre-alpha 提醒**:项目自我定位未公开发布。文字版(Phase A)今天就能用,语音版(Phase B)代码已提交但默认未启用 —— 别把语音版当生产工具用。

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

> ⚠️ **Voice mode always requires per-user setup** — Aliyun account + `.env` + microphone — so it cannot be auto-enabled for new users. Backend (`phase_b/`, 3546 LoC) and frontend (`phase_b/static/`, 1067 LoC) are committed and runnable via `./start.sh`, but voice mode is **opt-in for everyone, always**. Text mode is the default path.

- ✅ STT swap landed — FunASR → Aliyun NLS streaming WebSocket (2026-09-06). Real-time partial + sentence-end trigger now drives auto-submit. See [data-flow report](./phase_b/_reports/phase-b-data-flow-2026-09-06.md).
- ✅ End-to-end voice pipeline — first real session `real-2026-09-06-08` produced dialogue JSONL + raw wav + rhythm features (no transcript placeholders).
- ✅ Dashboard v2 — three pages (entry / session / dashboard) with KPI tiles, inline audio playback, transcript table, trending-chart regen, and PCC 37-marker assessment button (2026-10-04).
- ✅ XSS hardening — `textContent` replaces `innerHTML` in transcript render (2026-10-04).
- ⚠️ Backend code — `phase_b/` (28 .py files, 3546 LoC) + 18 test files under `tests/phase_b/`. **Shipped, opt-in only.**
- ⚠️ Frontend code — `phase_b/static/` (index.html + app.js + audio_state.js + styles.css, 1067 LoC). **Shipped, opt-in only.**

**Why text mode first?** Two reasons.

**1. Per-user setup cost.** Voice mode requires Aliyun account + 3 cloud keys in `.env` + a microphone. That is per-user configuration that cannot be done by the project on someone's behalf. So voice mode will always be opt-in — even after the project itself considers it mature.

**2. Maturity milestone.** Independent of (1), the project tracks a separate milestone: **after ≥10 real-coach practice sessions** are logged, voice mode graduates from "experimental opt-in (for the brave)" to "recommended opt-in (for most users)" in user-facing docs. This is a documentation/messaging milestone — it does **not** change the per-user setup requirement. Currently at **1 of 10** (2026-08-31). Until the threshold is crossed, voice mode is framed as experimental.

In summary — text mode is the default. Voice mode is always opt-in, and is currently framed as experimental until the 10-session milestone is reached.

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

## Bus factor

**This project has a bus factor of 1.** Only the original author deeply understands the full codebase (the persona system, the WebSocket pipeline, the PCC marker scoring, and the agent contracts in `.claude/agents/`). If you are forking this:

- Start with [`CLAUDE.md`](CLAUDE.md) — it describes the architecture, the
  iron rules (e.g. the pcc-coachee agent's "don't break character" rule), and
  the dependency surface.
- Read `.claude/agents/pcc-coachee.md` and `.claude/agents/pcc-assessor.md`
  before changing the persona pipeline or the marker scoring logic.
- The `personas/vec-01.md` (and its `-client.md` companion) is the canonical
  example of how a persona is structured; copy that shape for new ones.
- Tagged release points: `git tag pcc-v1.0` (and onward) mark known-good
  snapshots — start there if you want a stable base.

PRs are welcome; the maintainer reviews within ~1 week. If the maintainer
goes dark for >1 month, treat this as an unmaintained project and fork.

---

<br/>
<br/>

# PCC Live Coach — PCC 标记训练工具(文字版默认可用,语音版需要配置)

> ⚠️ **预发布 / 实验性。** 本项目处于活跃开发阶段,尚未公开发布。功能不完整,可能随时变更。

> ⚠️ **不是 ICF 认证工具。** 评估标准来自一份真实 PCC 督导录音的本地校准,未经国际教练联合会(ICF)官方批准。**不得**用于 ICF 认证申请。详见 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 这是什么?

**PCC Live Coach** 是给备考国际认证教练(ICF PCC)的陪练工具。它提供**两种互补模式** —— 文字版今天就能用、覆盖大部分训练维度,语音版补上仅靠音频才能评估的 3 个 markers。

| | 文字陪练(默认模式) | 语音陪练(Phase B,筹备中) |
|---|---|---|
| **状态** | ✅ 立即可用 | ⚠️ 代码已写,等待触发条件(≥10 场真人陪练 + 结构性问题已稳定解决 + 剩余差距集中在 5.5/6.6/7.6) |
| **怎么练** | 在 VS Code Claude Code 里切到 `pcc-coachee` agent,打字对话 | 浏览器 + 麦克风,本机起 STT/LLM/TTS 管线 |
| **首次上手时间** | ~30 秒(假设 VS Code + Claude Code 已经装好) | ~30 分钟(Python venv + Aliyun NLS 账号 + `.env` + 麦克风) |
| **覆盖 markers** | 34/37 个(除 5.5、6.6、7.6 外全部) | 37/37 全部(多出 3 个音频专属 markers) |
| **隐私** | 只走文字;换本地 LLM(Ollama / LM Studio / vLLM)可完全离线 | 默认云端(Aliyun NLS + MiniMax);三件套可独立切换到本地 |

### 30 秒文字版试玩

1. 打开 VS Code + Claude Code 扩展
2. 切到 `pcc-coachee` agent(完整 SOP 见 [personas/README.md § 配套练习 SOP](personas/README.md))
3. 输入:`开始陪练,选 vec-08`(或自选,推荐难度 1 起点:vec-06 / vec-08 / voc-05,详见 [personas/README.md](personas/README.md))

零 Python、零 `.env`、零阿里云账号、零麦克风。`pcc-coachee` agent 读 persona 文件开始扮演。教练结束会话后,输入 `全评` 自动转 `pcc-assessor` agent 出 37 marker HTML 报告。

要装语音版见 [INSTALL.md](INSTALL.md)。

**它不能替代真实客户的练习时长。** ICF 要求提交的录音来自真实客户,而不是 AI 人格。详见 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 核心特性

- 💬 **文字版陪练今天就能用** —— 在 VS Code Claude Code 里切到 `pcc-coachee` agent,30 秒开 45 分钟一场(覆盖 34/37 个 PCC markers,零安装)
- 🎙️ **语音版 opt-in** —— `phase_b/` WebSocket 管线已写好,始终 opt-in(需阿里云账号 + `.env` + 麦克风);累计 ≥10 场真人陪练前定位为"实验性"(见 [当前状态](#当前状态))
- 📊 **客观节奏指标** —— 沉默时长、CPM(每分钟字数)、打断检测、问题长度、问题间隔(仅语音版)
- 🔒 **按配置保隐私** —— STT / LLM / TTS 端点可独立切换;自托管任一端点即可让数据留在本地。默认 STT(Aliyun NLS)与 LLM/TTS(MiniMax)均为云端 —— 详见 [PRIVACY.md](PRIVACY.md)。
- 🧠 **与现有 pcc-assessor 对齐** —— 文字版和语音版都会进入同一套 37 marker 评估流水线(文字版 SOP 见 [personas/README.md](personas/README.md))
- 🌐 **基于浏览器的语音版前端** —— Chrome / Safari 支持;文字版只需 VS Code + Claude Code,无需 Python

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

> ⚠️ **语音版始终需要用户配置** —— 阿里云账号 + `.env` + 麦克风 —— 所以没法为新用户自动开。后端(`phase_b/`,3546 行)+ 前端(`phase_b/static/`,1067 行)已提交且可通过 `./start.sh` 启动,但**语音版对所有人始终是 opt-in**。文字版是默认路径。

- ✅ STT 切换落地 —— FunASR → Aliyun NLS 流式 WebSocket(2026-09-06)。实时 partial + 句尾触发自动提交。详见 [data-flow 报告](./phase_b/_reports/phase-b-data-flow-2026-09-06.md)。
- ✅ 端到端语音管线 —— 首场真人对话 `real-2026-09-06-08` 完整产出 dialogue JSONL + raw wav + rhythm 特征(非占位 transcript)。
- ✅ Dashboard v2 —— 三页面(entry / session / dashboard),含 KPI 卡、内嵌音频播放、transcript 表、trending chart 重生成、PCC 37-marker 评估按钮(2026-10-04)。
- ✅ XSS 加固 —— transcript 渲染 `innerHTML` 换 `textContent`(2026-10-04)。
- ⚠️ 后端代码 —— `phase_b/`(28 个 .py 文件,3546 行)+ `tests/phase_b/` 下 18 个测试文件。**已写,仅 opt-in。**
- ⚠️ 前端代码 —— `phase_b/static/`(index.html + app.js + audio_state.js + styles.css,1067 行)。**已写,仅 opt-in。**

**为什么先文字版?** 两个原因。

**1. 用户配置成本。** 语音版需要阿里云账号 + `.env` 里 3 个云端 key + 麦克风。这部分是项目没法替每个用户做的。所以**语音版永远需要用户配置**,即使项目自身认为它成熟了。

**2. 成熟度里程碑。** 与(1)无关,项目另外追踪一个:**累计 ≥10 场真人陪练后**,语音版在用户文档里的定位从"实验性 opt-in(给勇者)"升级为"推荐性 opt-in(给多数用户)"。这是文档/说法的里程碑 —— **不**改变用户配置要求。当前 1 / 10 场(2026-08-31),在那之前语音版被定位为实验性。

总结 —— 文字版是默认;语音版始终 opt-in,在 10 场里程碑达成前定位为实验性。

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