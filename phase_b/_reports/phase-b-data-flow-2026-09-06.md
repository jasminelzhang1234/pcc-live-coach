# Phase B 数据流速查(2026-09-06)

> 给开发者和用户用的"phase B 文件在哪 / 数据流向哪"快速参考。
> 配套设计:[`docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md`](../../docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md)

## TL;DR — 对话结束后,数据落在这

一场对话(real-2026-09-06-08)结束后,以下文件会被自动写入:

| 内容 | 路径 | 何时写 |
|---|---|---|
| 完整对话 transcript | `practice-logs/sessions/dialogues/real-2026-09-06-08.jsonl` | 每个 turn 实时 append |
| 整场录音(用户全程 PCM) | `practice-logs/sessions/raw/real-2026-09-06-08.wav` | 每个 binary frame 实时 append |
| 每句节奏特征(CPM/沉默/打断) | `practice-logs/sessions/rhythm/real-2026-09-06-08.jsonl` | session.end() 时一次性提取 |
| 训练追踪 +1 行 | `progress/tracker-real-sessions.csv` | session.end() 时 append(已存在则覆盖) |
| 成长曲线 html | `progress/trending-chart-real-2026-09-*.html` | tracker 追加后**手动重跑**(v2 改成按钮触发) |

## Phase B 服务端架构

```text
[浏览器] (mic 16kHz int16 mono PCM, binary WS frames)
   ↓ ws://127.0.0.1:8765/ws/session/{id}
[FastAPI router]
   ↓ worker.feed(pcm)
[ASRWorker] (phase_b/asr/asr_worker.py)
   ↓ AliyunASRClient.feed → nls.send_audio
[阿里云 NLS] WS: wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1
   ↓ on_result_changed / on_sentence_end 回调
[AliyunASRClient] 把 SDK 事件转统一 schema(partial / done / error)
   ↓ async for ev in client.events()
[ASRWorker._pump_loop] 把事件 push 到内部 queue
   ↓ async for ev in worker.events()
[router.pump_asr] 发 partial 给浏览器 + is_utterance_end=True 时触发 auto-submit
   ↓
[router.submit_turn] 创建 run_one_turn() task
   ↓
[Coach Orchestrator] run_turn()
   ├→ LLM (MiniMax M3 chat completion)              ← phase_b/llm/minimax_client.py
   ├→ TTS (MiniMax T2A v2 WebSocket 流式)           ← phase_b/tts/minimax_tts.py
   └→ reply_text + reply_end + binary PCM chunks 发回浏览器
[recorder.write_dialogue / write_audio] 持续落盘
[session.manager.end()] 关闭 ws + 提取 rhythm 特征 + 追加 tracker.csv
```

## 关键文件清单

### 后端代码

| 模块 | 文件 | 职责 |
|---|---|---|
| FastAPI app | `phase_b/server.py` | app factory + 静态 mount |
| REST routes | `phase_b/wire/router.py` | `/api/personas` `/api/session/*` |
| WebSocket | `phase_b/wire/router.py` | `/ws/session/{id}` 全 pipeline |
| ASR 适配 | `phase_b/asr/aliyun_client.py` | aliyun SDK → 统一 partial schema |
| ASR worker | `phase_b/asr/asr_worker.py` | 包 AliyunASRClient,保持旧 event 契约 |
| Session 管理 | `phase_b/session/manager.py` | 创建 / 结束 / rhythm 提取 |
| 录音 recorder | `phase_b/session/recorder.py` | dialogue / raw / rhythm 三路 jsonl+wav |
| LLM 客户端 | `phase_b/llm/minimax_client.py` | MiniMax M3 OpenAI 兼容 chat |
| TTS 客户端 | `phase_b/tts/minimax_tts.py` | MiniMax T2A v2 WS 流式 PCM |
| 节奏特征 | `phase_b/rhythm/turn_features.py` | CPM / 5.5 沉默 / 6.6 打断 / barge-in |
| 配置 | `phase_b/config.py` | dataclass Settings + _load_dotenv |
| 训练追踪 | `phase_b/tracker/csv_append.py` | 追加到 tracker-real-sessions.csv |

### 前端代码

| 文件 | 职责 |
|---|---|
| `phase_b/static/index.html` | 三页面:page-entry / page-session / page-dashboard |
| `phase_b/static/app.js` | 全部前端逻辑 |
| `phase_b/static/audio_state.js` | barge-in 检测状态机 |

### 数据落点

| 类别 | 路径 |
|---|---|
| AI persona 模拟对话 | `practice-logs/AI 练习/{dialogues,raw,rhythm}/` |
| 真人练习对话 | `practice-logs/sessions/{dialogues,raw,rhythm}/` |
| AI 训练追踪 | `progress/tracker.csv` |
| 真人追踪 | `progress/tracker-real-sessions.csv`(暖色 trending chart) |
| 真人成长曲线 | `progress/trending-chart-real-2026-09-*.html` |
| PCC 评估结果 | `assessments/<session_id>.json`(待 v2 实现) |

### 配置 / 环境

| 文件 | 用途 |
|---|---|
| `.env`(gitignored) | 真实凭证,**直接覆盖** shell env |
| `.env.example` | 模板,提交进 git |
| `phase_b/config.py` | dataclass Settings + _load_dotenv |

## REST API 一览

| Method | Path | 用途 | 状态 |
|---|---|---|---|
| GET | `/api/health` | 健康检查 | ✅ 已有 |
| GET | `/api/personas` | 列出 persona | ✅ 已有 |
| GET | `/api/personas/{id}` | 单个 persona | ✅ 已有 |
| POST | `/api/session/start` | 开启一场 | ✅ 已有 |
| GET | `/api/session/{id}` | session 元数据 | ✅ 已有 |
| POST | `/api/session/{id}/audio` | 推 raw PCM(legacy) | ✅ 已有 |
| POST | `/api/session/{id}/end` | 主动结束 | ✅ 已有 |
| GET | `/api/session/{id}/rhythm` | 节奏 KPI + 逐句 | ✅ 已有 |
| GET | `/api/session/{id}/transcript` | 完整 transcript | 🆕 v2 待加 |
| GET | `/api/session/{id}/audio` | serve wav | 🆕 v2 待加 |
| POST | `/api/session/{id}/assess` | 跑 PCC 评估 | 🆕 v2 待加 |
| POST | `/api/session/{id}/track` | 追加训练追踪 | 🆕 v2 待加 |

## WS 协议(浏览器 ↔ 服务端)

**浏览器 → server:**
| 类型 | 字段 | 含义 |
|---|---|---|
| binary | int16 mono 16kHz PCM | 持续 mic 流 |
| text | `{"cmd":"speak"}` | 手动提交(legacy / debug) |
| text | `{"cmd":"barge_in"}` | 打断当前回复 |
| text | `{"cmd":"end"}` | 结束会话 |
| text | `{"cmd":"ping"}` | 心跳 |

**server → 浏览器:**
| event | 字段 | 含义 |
|---|---|---|
| `ready` | session_id, persona_id | WS 已连 |
| `asr_ready` | — | ASR 模型加载完 |
| `partial` | text, audio_ms, latency_ms, is_utterance_end | ASR partial/final |
| `reply_text` | text, turn | LLM 回复(用于 transcript) |
| `reply_end` | turn | TTS 播完 |
| `barge_in_stopped` | turn | 回复被打断 |
| `warn` | msg | 软警告(如空 transcript 提交) |
| `ended` | session_id, turn_count, barge_in_count | 会话结束 |
| `error` | stage, error | 错误 |

## S2S 集成踩坑(历史教训)

> 这些是 2026-09-06 第一次成功跑通 phase B 端到端时踩的坑,记录下来免得未来重复。

### 1. Aliyun ASR SDK 字段嵌套(2026-09-06)

aliyun NLS 服务端返回的 JSON 是嵌套结构:

```json
{
  "header": {"name": "TranscriptionResultChanged", "status": 20000000, ...},
  "payload": {
    "index": 1, "time": 480,
    "result": "第一次遇",
    "confidence": 0.79, ...
  }
}
```

但 aliyun-nls SDK 0.0.1 版本的 Python SDK 不解析字段,只透传字符串。在 `phase_b/asr/aliyun_client.py` 里必须手动 `data["payload"]["result"]`,不是 `data["result"]`。

之前 bug 是写错成 `data.get("result")`,永远拿 None,所以 transcript 永远是空字符串。**直接导致 phase B 端到端从未成功过一次**(2026-09-05 之前的"对话"全靠前端默认 placeholder)。

### 2. config.py .env 不覆盖 shell env(2026-09-06)

`phase_b/config.py` 的 `_load_dotenv` 原本写法:

```python
if key and key not in os.environ:    # ❌ shell 有就跳过
    os.environ[key] = value
```

后果:shell 里有一个**过期**的 `LLM_API_KEY`(来自其他项目),覆盖了 `.env` 里正确的新 key,导致 MiniMax 401 Unauthorized。

已改为 `.env` 永远覆盖 shell(项目级 `.env` 才是 source of truth)。

### 3. dashboard JS 崩溃:`activeSession` 提前置 null

`teardownSession()` 把 `activeSession = null`,但同一段 `case "ended"` 代码还在读 `activeSession.id`,TypeError 让整个 dashboard JS 崩溃,表格留空。

**修法**:在 teardown 前先把 session_id 存到本地变量。

### 4. server "ended" event 没带 session_id

前端用 `obj.session_id || activeSession.id` 取 session_id,但 server 只发了 `event/turn_count/barge_in_count`,没有 `session_id`。

**修法**:server 加 `"session_id": session_id` 字段。

## 验收清单

跑完 dashboard v2 实施后,跑这套 checklist:

- [ ] 真人对话后,`practice-logs/sessions/dialogues/` 有新 jsonl
- [ ] 真人对话后,`practice-logs/sessions/raw/` 有新 wav
- [ ] 真人对话后,`practice-logs/sessions/rhythm/` 有新 jsonl(非空)
- [ ] 真人对话后,`progress/tracker-real-sessions.csv` 行数 +1
- [ ] `progress/trending-chart-real-*.html` 在 24h 内有更新(自动生成)
- [ ] `progress/trending-chart-*.html`(AI 暖色)和 `progress/trending-chart-real-*.html`(真人暖色)**互不混合**
- [ ] AI persona 模拟对话不会写入 `真人练习/` 或 `tracker-real-sessions.csv`
