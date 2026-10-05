# Changelog

> **状态**:in progress — 变更随发布节奏登记。隐私策略变更由 [PRIVACY.md](PRIVACY.md) 引用本文档。

## 格式计划

参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/):
- `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`

## 当前重要事件(临时登记)

- **2026-10-05** — 小白用户文档扩充(回应"是否需要用户手册"诉求): `FAQ.md` 从 3 题扩到 22 题,新增 6 章节(快速上手 / 环境配置 / 训练流程 / 进度追踪 / PCC 概念速通 / 隐私合规 / 性能费用),两类小白(技术小白 + 领域小白)都覆盖; `README.md` 新增 §"5 分钟入门路径(小白先看)",按用户画像 4 分流(领域熟/技术熟/完全小白/只看不练)+ 端到端 5 步流程图; `TROUBLESHOOTING.md` 从 10 条扩到 25 条,新增浏览器/前端、LLM、ASR 三章节(关键纠正: FunASR 已于 2026-09-06 迁到 Aliyun NLS,旧 FunASR 条目替换为 Aliyun NLS 项目类型 / Token / 录音保留策略三条);本次**未新增独立 USER_GUIDE.md**,理由: Pre-alpha 阶段 + README/INSTALL 已覆盖入门,过早投资独立手册会变 3 份互引文档无人维护;触发条件达成(README § Status 3 个 trigger)+ 准备公开发布时再抽 USER_GUIDE.md
- **2026-10-05** — `phase_b/tracker/csv_append.py` `upsert_session_row` 加模块级 dict cache(`Path → (header, rows, index_by_session_id)`),首次按 csv_path 加载一次,后续 upsert O(1) 查找 + O(n) 写盘;n 次 upsert 总成本 O(n) 而非原 O(n²);同时干掉原实现的两次完整读(第二次纯为 `replaced` 标志,白扫);新增公开 `flush_cache(csv_path=None)` 给 tests / 外部写盘场景;契约 `inserted` / `replaced` / `no_csv` 不变,`tests/phase_b/test_track_endpoint.py` 3 个 unit test + 4 个 endpoint test 不破
- **2026-10-05** — install + config + UI 收尾:`requirements.txt` + `INSTALL.md` § 4 改为两步安装(`pip install -r requirements.txt` + `pip install --no-deps --force-reinstall aliyun-nls==0.0.1`),跳过 aliyun-nls 0.0.1 列出的 matplotlib / pillow / fonttools / pycryptodome(~54MB)未使用 transitive deps,附 smoke test 命令验证;`_chart_output_path` 新增 `TRENDING_CHART_PATH` env var 支持(空 = 现有默认,绝对路径直接使用,相对路径相对仓库根,字面量 `{date}` 替换为当天日期);`.env.example` + `INSTALL.md` § 6 同步;`phase_b/config.py` Settings 新增 `trending_chart_path` 字段;`phase_b/wire/router.py` 加一行注释指向 `phase_b/rhythm/cpm.py` docstring 的 LLM think-time caveat;`phase_b/static/index.html` 标签 "平均 CPM" → "平均 CPM(含 LLM)",kpi 容器加 `title` 提示完整口径;`tests/phase_b/test_track_endpoint.py` 仍以 `monkeypatch` 覆盖,无破坏
- **2026-10-05** — 隐私加固:tracker 文件名 `progress/tracker-real-sessions.csv` 重命名为 `progress/tracker-sessions.csv`,去掉文件名中的"real-"标识(与 2026-10-04 路径改名保持一致);24 个引用文件 + `.env` `TRACKER_CSV` 配置同步更新;CSV 数据保留(原 4 行音频路径已自动同步到新路径);`PRIVACY.md` 加显眼"路径与文件名命名缘由"说明,`Last updated` 同步到 2026-10-05
- **2026-10-04** — 隐私加固:路径 `practice-logs/真人练习/` 重命名为 `practice-logs/sessions/`,去掉路径名中的"真人"标识(云同步 同步 / 备份脚本 / 错误日志(stack trace)可能泄漏真实练习标识);20 个引用文件 + `progress/tracker-real-sessions.csv` audio_path 列同步更新;历史 CHANGELOG 条目保留原路径以反映当时状态
- **2026-09-05** — Phase B 新用户体验修复(共 9 处),由 GitHub 视角的 install/boot/walkthrough 触发
  - `start.sh`:启动前 `lsof` 检查端口,被占则打印 PID + 给 `kill` / `PCC_LIVE_PORT=N` 两选一,新用户第一步不再 silent-break
  - `phase_b/coach/orchestrator.py`:`_build_system_prompt` 新增 `user_difficulty` 参数;UI 选的难度真正生效,mismatch 时 prompt 输出 `难度: N (用户选择) / persona 推荐: M`
  - `phase_b/wire/router.py`:`GET /api/personas` 从 `["vec-01", …]` 改为 `[{id, name, line, difficulty}, …]`,前端 dropdown 改显示 `陈锐 · 要结果…事业部总经理 · VEC 高管线 (难度 2)`;legacy `POST /api/session/{id}/audio` 加 `include_in_schema=False`
  - `phase_b/session/manager.py`:`end()` 顶部加 fast path —— 0 audio bytes 且 0 turn 时 unlink 三个产物文件 + skip rhythm + skip `tracker-real-sessions.csv` append(probe session 不再留底)
  - `phase_b/config.py` + `phase_b/session/manager.py`:`sessions_dir` 默认值从 `sessions/` 迁到 `practice-logs/真人练习/`,与 README/INSTALL 一致;`.env` + `.env.example` 同步
  - `INSTALL.md` + `README.md`:3 处 `python -m phase_b.server` 改为 `./start.sh`(`__` / `python -m phase_b` 备选);端口 8765 / `phase-b-env-setup` / `phase-b-spike-report` / `phase-b-github-research` / `phase-b-wireframe` 等 8 处 dead cross-reference 改为 `./plans/phase-b/X` 或引用 spike-report;INSTALL § 8 加中英文 port-in-use 故障排除小节
- **2026-09-04** — 真人练习材料整理:从 `progress/real-sessions/` + `progress/tracker-analysis-real-*` + `practice-logs/真人练习/analysis/` 合并到 `practice-logs/真人练习/<YYYY-MM-DD>-session-NN/`,按 session 分开
- **2026-09-04** — 三份完整评估报告按主流命名风格改名(`vec-XX-session-NN-vX-YYYY-MM-DD.md`),同步更新 `progress/校准三方对照-*.md` + `progress/prompts/deepseek-*.md` 引用
- **2026-08-31** — 启动真人独立管线:tracker-real-sessions.csv (95 列) + trending-chart-real.html(暖橙配色),与 AI persona 完全独立
