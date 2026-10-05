# Roadmap / 决策归档

> **目的**:记录已经**砍掉** / **改方向** / **合并** 的字段、端点、模块,以及当时为什么这么决定。
> 防止 6 个月后自己看着 git blame 问"这是谁砍的?为啥砍?"。

---

## 什么时候往这里写?

满足以下任一条件,在删/改的同一个 PR 里 append 一条,不要拖:

- 删除了 Settings 字段、env var、CSV 列、API 字段、UI schema key
- 删除了端点、CLI 命令、模块、agent tool
- 改了 PCC marker / KPI / dashboard 指标语义(指标"看起来一样"但口径变了也算)
- 替换了底层依赖(STT / TTS / LLM / SDK),前一代的字段要记录"已换掉"

格式:见下文模板。

---

## 字段 / 模块移除记录

<!-- 按时间倒序写(新条目在上)。 -->

### 2026-09-26 · Phase B 85% 参考线 — chart 视觉元素移除

- **commit**: `d60fc71 chore(chart): 移除 Phase B 85% 参考线(主图横线 + 雷达圈)`
- **删除内容**:
  - 主图 ① 的 `y=85%` 横线 + 文字标签
  - 雷达图 ③ 的 85% 参考圈
  - `scripts/gen_trending_chart.py` 头部 docstring `⑤ Phase B 状态` 段
- **理由**:Phase B 概念在当前阶段不再适用,标签和参考线都失去语义,留着误导读者。
- **影响面**:仅 chart 文件,无数据契约变化。

### 2026-09-08 · FunASR-era 配置字段 — Settings + .env + ctor 全面清理

- **commit**: `5821022 chore(phase_b): remove FunASR-era dead tests + back-compat surface`
- **删除内容**(共 5+5+3 处):
  - `phase_b/config.py` Settings 字段:`asr_model` / `vad_model` / `punc_model` / `chunk_ms` / `language`
  - 5 个对应 env var:`FUNASR_MODEL` / `FUNASR_VAD_MODEL` / `FUNASR_PUNC_MODEL` / `FUNASR_CHUNK_MS` / `FUNASR_LANGUAGE`
  - `phase_b/asr/asr_worker.py` ctor 参数 `model` / `chunk_ms` / `language` + 4 个 dead `self.*` 属性 + `clear_buffer()` no-op
  - `phase_b/rhythm/barge_in.py` `client_interruption_by_coach_ms()` (永远返回 0,只是 schema 占位)
  - `phase_b/rhythm/turn_features.py` 对 `client_interruption_by_coach_ms` 的 import + 2 处调用 + docstring example
- **理由**:2026-09-06 换栈到 Aliyun NLS 后,这些字段没有任何代码路径还在读,留着只是给配置文档 / `.env` / `_DOTENV_OVERRIDE_KEYS` 加噪音。
- **影响面**:删了 5 个 env var,任何 `.env` 里还留着旧 key 的部署都不会报错(被忽略),但维护时要清掉。

---

## 模板

复制下面这段填到上面:

```markdown
### YYYY-MM-DD · 一句话标题

- **commit**: `<sha> <commit subject>`
- **删除内容**:
  - 模块路径一(列具体字段 / 端点 / 函数)
  - 模块路径二
- **理由**:一句话讲当时为什么砍(读 commit message 抓要点即可)。
- **影响面**:是否影响 .env / CSV schema / API 契约。
```

---

## 关联

- 移除历史 / 改名历史通常也能在 [CHANGELOG.md](../CHANGELOG.md) 找到,但 CHANGELOG 是按时间流水记"做了什么",本文档按"砍了什么 + 为什么"组织——互补,不重复。
- 每次删除 PR 的 commit message **至少要含 `why` 段**,否则回头写本文档会没原料。