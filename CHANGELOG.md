# Changelog

> **状态**:in progress — 变更随发布节奏登记。隐私策略变更由 [PRIVACY.md](PRIVACY.md) 引用本文档。

## 格式计划

参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/):
- `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`

## 当前重要事件(临时登记)

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
