# Troubleshooting

> **状态**:stub — 详细内容待写。

## 启动错误

- **`ModuleNotFoundError`**:venv 没激活,或没跑 `pip install -e .`
- **`port 8765 already in use`**:`PCC_LIVE_PORT=8766 python -m pcc_live_coach.server` 换一个
- **`Refusing to bind 0.0.0.0`**:默认拒绝 LAN 暴露;设 `PCC_LIVE_ALLOW_LAN=1` 才会放开

## 模型错误

- **FunASR 加载失败**:检查 `~/.cache/modelscope/` 是否完整(~220 MB)
- **whisper 链接断**(Mac):`brew reinstall whisper`,或 `arch -arm64 brew reinstall whisper`(Apple Silicon)

## 评估脚本错误

- **CSV 95 列截断**:Edit 工具对长行不友好,走 `python3 -m phase_b.tracker.csv_append`(详见 memory `edit-tool-long-csv-truncation`)
- **hook 触发失败**:检查 `.claude/settings.json` 里 `PostToolUse` 钩子路径是否正确
