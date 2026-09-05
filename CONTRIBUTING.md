# Contributing

> **状态**:stub — 详细内容待写。

## 提 PR 之前

1. 跑 `pytest tests/`(必须全绿)
2. 跑 `ruff check .`(代码风格)
3. PR 描述:动机 / 改动 / 验证 / 关联 issue

## Commit message

- 走 conventional commits:`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`
- 例:`feat(coachee): 修启动越权(commit 8dd8999)`
- 涉及真人数据:`chore(real-sessions):` 而非 `feat(real-sessions):`,避免污染 git history

## Code style

- **Python**:PEP 8 + type hints
- **Markdown**:`#` 一级标题下空一行;链接用 `label`(方括号)+ 相对路径(圆括号)的 markdown 形式,不要用 backticks 包整段路径
- **引用其他 memory**:用 `[[name]]` 双链,缺失链接可以接受(标记待补充)

## 数据安全

- 任何真人练习材料(音频/转写/评估)放 `practice-logs/真人练习/<YYYY-MM-DD>-session-NN/`,已 `.gitignore`
- 不要 commit 真实姓名 / 公司 / 项目名
