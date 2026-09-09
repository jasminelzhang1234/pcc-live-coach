# Phase B 大扫除 — FunASR→Aliyun NLS 留下的死代码 / 死文档清仓

> 给 the maintainer · 2026-09-09 · 配套 2026-09-06 ASR 换栈决策(commit `116e268`)
>
> FunASR→Aliyun NLS 重构**功能层已干净**,但留下了 6 处 back-compat surface、5 个 FunASR 专属死测试、1 份重复 troubleshooting 文档、1 个未实施的视觉原型、1 个 923 MB 肿大的 venv。本报告记录 2026-09-08 单日清仓全过程 + 留给未来的 3 条 caveat。

---

## 0. 触发原因 + 时间线

| 时间 | 触发 |
|---|---|
| 2026-09-06 | ASR 切 Aliyun NLS,功能已通。但**故意**保留了 5 个 Settings 字段 + 3 个 ASRWorker ctor 参数 + `clear_buffer()` + `last_text` 哨兵 + `client_interruption_by_coach_ms()`,方便回滚 |
| 2026-09-07 | 一天生产运行稳定,无回滚诉求 → 回滚期结束 |
| 2026-09-08 上午 | 审计 phase_b/ 死代码 + 顺手发现 .venv 923 MB,排查出是 FunASR 残留 + shebang 全断 |
| 2026-09-08 下午-晚 | 5 个 commit 落地(见 §4) |
| 2026-09-09 | 本报告归档,branch `phase-b-cleanup-2026-09-08` |

---

## 1. 删了哪些 / 为什么 / 净行数

### 1.1 死代码(back-compat surface)

| 删的东西 | 文件 | 为什么是死代码 |
|---|---|---|
| `ASRWorker(model=..., chunk_ms=..., language=...)` 3 个 ctor 参数 | `phase_b/asr/asr_worker.py` | Aliyun NLS 不需要模型 / VAD / 切块大小 / 语言选择(全由 NLS 项目配置) |
| `ASRWorker.clear_buffer()` 方法 + `self._model_legacy/_chunk_ms/_language` 3 个 attr | 同上 | 商业 ASR 是流式 WebSocket,无 client buffer 可清 |
| `worker.last_text = ""` 哨兵 + 2 处 `worker.clear_buffer()` 调用 | `phase_b/wire/router.py` | 同上,clear_buffer 是 no-op,last_text 哨兵只服务于被删的死代码 |
| 5 个 Settings 字段(`asr_model/vad_model/punc_model/chunk_ms/language`)+ 5 处 `get_settings` 读取 | `phase_b/config.py` + `.env.example` | FunASR env vars + Settings 字段全无读取方 |
| `client_interruption_by_coach_ms(_coach_start_ms, _client_utterances)` 函数 + 2 处调用 | `phase_b/rhythm/barge_in.py` + `turn_features.py` | reply_end 时间戳未记录,该函数永远返回 0 |
| 注释里的 funasr/torch lazy import 提示 | `phase_b/__init__.py` | 换成更普适的"任何 caller 都可能没 basicConfig" |

**验证**:删完跑 `grep -rE "clear_buffer|last_text|client_interruption_by_coach|asr_model|asr_chunk_ms|FUNASR_MODEL" phase_b/` → 0 业务命中(只有 commit 历史)。

### 1.2 死测试(FunASR 专属)

| 文件 | 行数 | 为什么删 |
|---|---|---|
| `tests/phase_b/test_asr_trigger_decoding.py` | 455 | 测 FunASR 1.8s silence 触发逻辑,新栈无此概念 |
| `tests/phase_b/test_barge_in.py` | 334 | 测 `client_interruption_by_coach_ms`,函数已删 |
| `tests/phase_b/test_orchestrator.py` | 152 | 测 FunASR orchestrator pipeline |
| `tests/phase_b/test_asr_worker.py` | 77 | 测被删的 ctor 参数 |
| `tests/phase_b/test_tts_client.py` | 74 | 测 FunASR-era TTS client 路径,与现 TTS pipeline 不一致 |
| `tests/conftest.py` | 15 | 唯一的目的是 skip `test_asr_trigger_decoding` 和 `test_barge_in`,全删后自己也成孤儿 |

保留并小修的 3 个测试:
- `test_rhythm.py`(7 行改动)— 删 `client_interruption_by_coach_ms` 断言
- `test_rhythm_endpoint.py`(4 行改动)— 删同
- `test_auto_turn.py`(5 行改动)— 删 `worker.clear_buffer` 计数器断言(计数器是 mock 加的,真接口已无此方法)

### 1.3 死文档

| 文件/目录 | 处理 | 为什么 |
|---|---|---|
| `TROUBLESHOOTING.md` | 删除,3 条真有效的合并到 `INSTALL.md §8`(EN+ZH 双语) | 与 INSTALL.md 大段重复;真正独有的 3 条都是 venv / CSV 工具问题,归 INSTALL 更自然 |
| `mockups/dashboard-v2.html` | 删除 | 300 行静态 HTML 原型,dashboard v2 spec 实际 UI 已在 `phase_b/static/`,原型已无参考价值 |
| `docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md` | 移至 `docs/superpowers/specs/archive/` + 改状态为 ✅ 已实施 + 删 3 处 `mockups/` 引用 + 改 `继承自:` 块链接 | spec 的设计意图已固化在代码里;但留档供未来追溯"为什么这么设计"。`archive/` 是项目自然归档位置 |

### 1.4 JS 测试入口(新增)

| 文件 | 处理 | 为什么 |
|---|---|---|
| `scripts/test-js.sh` | 新增 15 行 | `tests/phase_b/test_browser_audio_state.js` 早就在用 Node.js ≥18 内置 `node:test` runner,无任何 npm 依赖;但**没人能从根目录一键跑**。`test-js.sh` 只是 `exec node --test tests/phase_b/*.js`,配 `set -e` + `cd` 到根 |

**关键认知校正**:这文件不是"没 Node runner"——是 runner 内置,**只是没 wrapper**。详见 memory 待补条目。

### 1.5 venv 肿大 + shebang 全断(顺带修)

`.venv` 实情(2026-09-08 调查发现):
- 原名 `.venv-funasr-spike`(FunASR spike 期间建)
- 切 Aliyun 栈时被 `mv` 改名 `.venv`,但 **46 个 wrapper scripts**(pip / fastapi / funasr-realtime-server / 等)的 shebang 仍指 `.venv-funasr-spike/bin/python` 已删除路径
- `python --version` 正常(没 shebang),但 `pip` / `fastapi` 任何 wrapper 都 `No such file or directory`
- 长期靠 `python -m pip` 绕过 → pip 维护彻底荒废,堆了 13 个 FunASR 死包 + FunASR 强拉的 matplotlib/pillow/fonttools/pycryptodome(~54 MB)

修法:
```bash
sed -i '' 's|.venv-funasr-spike/bin/python|.venv/bin/python|g' .venv/bin/*
pip uninstall -y funasr funasr-realtime-server modelscope torch torchaudio ...
pip uninstall -y matplotlib pillow fonttools pycryptodome
```

结果:.venv 从 **923 MB → 146 MB**(省 **777 MB**)。83/83 pytest + 11 JS 测试 + 9 个生产模块 import 全部仍然通过。

> **任何 mv / rename `.venv` 后必 sed 修 shebang**,否则 wrapper 全炸但 `python` 看似正常,极其误导。详见 memory `venv-rename-breaks-shebangs`。

---

## 2. 净行数

```
 23 files changed, 104 insertions(+), 1525 deletions(-)
```

**净 -1421 行**。其中:

| 类别 | 删 | 增 |
|---|---:|---:|
| 死测试 + conftest | 1092 | 0 |
| mockup HTML | 300 | 0 |
| back-compat code + dead funcs | 50 | 0 |
| `.env.example` | 9 | 0 |
| `INSTALL.md` troubleshooting | 19(独立 md) | 60(并入 INSTALL,EN+ZH) |
| `requirements.txt` | 0 | 8 |
| `scripts/test-js.sh` | 0 | 15 |
| 文档归档 + 注释修正 + 测试修正 | 55 | 21 |

---

## 3. 关联的 5 个 commit(branch `phase-b-cleanup-2026-09-08`)

```
c8127fd chore(phase_b): remove FunASR-era dead tests + back-compat surface
0a9b57f chore(phase_b): add scripts/test-js.sh for browser audio state tests
f2ff09e chore(deps): add Aliyun ASR/TTS SDKs to requirements.txt
29e5102 docs: consolidate TROUBLESHOOTING.md into INSTALL.md §8
38395f8 docs: archive dashboard v2 spec + remove mockup
```

每个 commit 都独立可 revert,语义清晰:
- `chore` = 维护性改动(无功能影响)
- `docs` = 纯文档
- 5 个都遵循"一个 commit 一类改动"原则,避免未来 bisect 时把死代码删与 mockup 删混在一起

---

## 4. 验证状态

| 验证项 | 结果 |
|---|---|
| `pytest tests/` | **83/83 通过**(删了 5 个测试 = 88→83) |
| `bash scripts/test-js.sh` | **11 JS 测试通过**(Node.js ≥18 内置 runner,无 npm) |
| 9 个生产模块 import smoke test | 全通(`from phase_b.wire.router import api_router, session_start, session_assess, mount_websocket` 等) |
| `grep -rE "clear_buffer\|last_text\|client_interruption_by_coach\|asr_model\|asr_chunk_ms\|FUNASR_MODEL" phase_b/` | 0 业务命中 |
| `.venv` 大小 | 923 MB → **146 MB**(-777 MB) |
| `.venv/bin/pip --version` | 修复前:No such file / 修复后:正常 |

---

## 5. 留给未来读者的 3 条 caveat

### Caveat 1:**requirements.txt 现在含 aliyun SDK,不要再手动 pip install aliyun-nls**

`requirements.txt` 已固定:
```text
aliyun-nls==0.0.1
alibabacloud-nls-cloud-meta20190228==1.0.0
```

**不要再手动装别的版本**——0.0.1 是我们测通的,新版本字段协议可能又变(SDK 自己不解析 JSON,客户端要读 `payload.result` 而不是 `data.result`,见 [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](aliyun-asr-setup-2026-09-06.md) "S2S 集成踩坑")。

如果想省 ~54 MB,**装完后**手动卸载 4 个死代码:
```bash
pip uninstall -y matplotlib pillow fonttools pycryptodome
```
SDK 自己声明这些是运行时依赖,但本项目代码**真不用**。83 个 pytest + 11 JS 测试 + 9 个模块 import 全部通过,验证这 4 个真是死代码。详见 memory `aliyun-nls-overbroad-deps`。

> **未来升级 aliyun-nls 时**:先在 venv 装新版,跑测试 + 上面 4 个 import 检查,确认没把这 4 个升级回来再用。

### Caveat 2:**任何 mv/rename `.venv` 后必 sed 修 shebang**

症状很误导:`python --version` 正常 + `pip --version` 报 `No such file or directory` = 100% 是这个问题。详见 memory `venv-rename-breaks-shebangs`。

本次踩坑:`.venv` 实际是重命名后的 `.venv-funasr-spike`,46 个 wrapper 的 shebang 全错指,导致 `pip` 长期失效靠 `python -m pip` 绕过。

**修法**:
```bash
sed -i '' 's|原路径/bin/python|新路径/bin/python|g' .venv/bin/*
```

### Caveat 3:`ASRWorker` ctor 现在只接 `sample_rate`;不要把 `clear_buffer()` / `chunk_ms=` / `language=` 当"恢复参数"加回来

```python
# 当前真接口(2026-09-08 起)
worker = ASRWorker(sample_rate=16000)
```

**不要"为兼容性"加回**这些参数:
- `model=` — Aliyun NLS 不需要,模型在 NLS 项目里配
- `chunk_ms=` — 流式 ASR 不按 chunk 触发解码,服务端持续输出 partial
- `language=` — NLS 项目级别配置语言
- `clear_buffer()` — 流式 WebSocket 无 client buffer;要重置对话走 `await worker.stop()` + 新 task

如果未来真的需要本地 VAD 或离线兜底,**单独写一个新 ASRWorker 子类**,而不是把这堆参数塞回 Aliyun 版。

---

## 6. 顺带发现 + 处理(不在 5 个 commit 里但相关)

| 发现 | 处理 |
|---|---|
| `others-sessions/` 目录 | 已存在 git,本次不动 |
| `progress/` 目录 | 已存在 git,本次不动 |
| `.venv-1` 空目录(Sep 5 重建失败残留) | 已删(2026-09-08) |
| `.venv/pyc` 缓存 | 留,下次 install 不需要重生成 |
| 11 个 JS 测试未来再加 wrapper | 暂不,目前一个 `node:test` 文件已够,真扩到 3+ 个再扩 wrapper |

---

## 7. 未来读者速查

- **"为什么 phase_b/ 没 `clear_buffer`?"** — 商业 ASR 是流式 WebSocket,无 client buffer
- **"为什么 ASRWorker ctor 这么瘦?"** — Aliyun NLS 不需要模型 / 切块 / 语言参数,全在 NLS 项目侧配
- **"为什么 mockups/ 不见了?"** — 设计原型只服务设计期,实施完成(UI 在 `phase_b/static/`)后即弃;spec 已归档至 `docs/superpowers/specs/archive/`
- **"为什么 .venv 只有 146 MB?"** — FunASR 死包 + matplotlib 等 over-broad 依赖全清,见 `aliyun-nls-overbroad-deps` memory
- **"怎么跑 JS 测试?"** — `bash scripts/test-js.sh`(Node.js ≥18 内置 runner,无需 npm)
- **"为什么 requirements.txt 没写 aliyun-nls 的版本号限制?"** — 写了:`==0.0.1`,注释提醒可省 54MB
