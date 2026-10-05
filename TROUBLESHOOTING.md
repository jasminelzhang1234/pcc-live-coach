# Troubleshooting

> **状态**:in progress — 内容随代码状态同步更新。
>
> 排错顺序:报错信息对号入座 → 都没匹配看 [FAQ.md](FAQ.md) → 还没解决提 GitHub issue(附终端完整 log + `.env.example` 去敏版)。

---

## 启动错误

- **`ModuleNotFoundError`**:venv 没激活(终端前没 `(.venv)`),或没跑 `pip install -r requirements.txt`。
- **`port 8765 already in use`**:`./start.sh` 现在会主动 `lsof` 检查并提示;手动换端口 `PCC_LIVE_PORT=8766 ./start.sh`,浏览器地址同步改 8766。
- **`Refusing to bind 0.0.0.0`**:默认拒绝 LAN 暴露;只有要别人从同网段连才设 `PCC_LIVE_ALLOW_LAN=1`。**别为了"修这个问题"就放开 LAN**。
- **`start.sh: Permission denied`**:克隆下来的脚本没可执行权限,跑 `chmod +x start.sh start.command`。
- **Mac 报"无法打开 start.command,因为它来自身份不明的开发者"**:系统设置 → 隐私与安全性 → 点"仍要打开";或终端跑 `xattr -d com.apple.quarantine start.command`。
- **端口在监听但浏览器空白**:多半是后端启动失败但端口还没释放,看终端 log 里真正的 traceback(常见是 `.env` 缺 `ALIYUN_*` 三件套或 `LLM_API_KEY`)。
- **venv 找不到 / `source .venv/bin/activate` 报 No such file**:没跑 `python3 -m venv .venv`,参考 [INSTALL.md § 3](INSTALL.md#3-create-a-python-virtual-environment)。

---

## 语音 / ASR 错误

- **Aliyun NLS `InvalidToken` / 4xx**:子账号缺 `AliyunNLSFullAccess` 权限;或 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` 复制时多了空格。完整配置: [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](phase_b/_reports/aliyun-asr-setup-2026-09-06.md)。
- **Aliyun NLS 连接通但没识别结果**:项目类型选了"一句话识别"而不是"实时语音识别" —— WebSocket 协议不同,要重建项目。
- **录音文件被自动清理**:默认 `AUDIO_RETENTION_DAYS=30`,启动时清理过期。设 `0` 永久保留。规则: [PRIVACY.md § 6.5](PRIVACY.md)。
- **麦克风权限被拒(浏览器)**:Chrome 地址栏左边锁图标 → 网站设置 → 麦克风 → 允许;Safari:偏好设置 → 网站 → 麦克风。
- **TTS 没声音**:TTS 端点默认走云端,先检查 `.env` 的 `TTS_WS_URL` / `TTS_API_KEY`;浏览器 console 看 WebSocket 状态。
- **回声 / 对方听不清**:headset 代替扬声器,或调小 TTS 音量;别用笔记本自带麦 + 内放。

---

## LLM 错误

- **`401 Unauthorized`**:LLM API key 没填或失效;本地 Ollama / LM Studio 时填了真实云端 key 反而报错(本地不校验,填任意非空字符串)。
- **`LLM_TIMEOUT_S=30` 频繁超时(本地 Ollama 慢)**:调大 `.env` 的 `LLM_TIMEOUT_S=90`;或换小模型(qwen2.5:7b / llama3.1:8b)。
- **`model not found`(本地 Ollama)**:先 `ollama pull qwen2.5:14b` 拉模型,`.env` 的 `LLM_MODEL` 要和拉下来的 tag 一致。
- **MiniMax API 默认 key 过期**:填自己的 key;MiniMax 控制台 → API Keys 重新生成。
- **`.env` 改了不生效**:必须**重启** `./start.sh` 重载,脚本不会 hot-reload 配置。

---

## 评估 / Tracker 脚本错误

- **CSV 95 列截断 / Edit 工具失败**:长行 Edit 工具不友好,走 `python3 -m phase_b.tracker.csv_append` 追加。详见 `.claude/agents/pcc-tracker.md`。
- **`pcc-assessor` agent 启动后找不到 persona**:CSV / 报告路径不对;`PERSONAS_DIR` / `SESSIONS_DIR` / `TRACKER_CSV` 三个 env 路径不存在(检查 `.env` 拼写)。
- **`pcc-assessor` 报"`prior_sessions_count >= 1` 不满足"**:第一场 session 没存档 → 检查 `practice-logs/sessions/` 目录有没有当天日期子目录;有但 CSV 没追加 → 跑 `python3 -m phase_b.tracker.csv_append`。
- **hook 触发失败(commit / push 时)**:检查 `.claude/settings.json` 里 `PostToolUse` 钩子路径是否正确;敏感词 hook 见 [`.github/workflows/online-name-scan.yml`](.github/workflows/online-name-scan.yml)。

---

## 浏览器 / 前端错误

- **Console 报 `WebSocket connection failed`**:后端没起,或端口不一致;先 `curl http://127.0.0.1:8765/` 看响应。
- **Dashboard KPI 一直显示 `NaN`**:session 还没收到第一段 audio bytes;或 `LLM_MAX_TOKENS` 设太小被截断。
- **趋势图打不开**:HTML 是 self-contained,直接 file:// 打开;若 CSP 报错用 `python3 -m http.server 8000` 起本地静态服务。
- **中文显示方块字**:Chart 字体 fallback;改 `phase_b/static/styles.css` 字体栈(常见加 `PingFang SC` / `Microsoft YaHei`)。

---

## 还找不到?

1. 看完整终端 log + 浏览器 console + `.env` 去敏版
2. grep 仓库:[`phase_b/_reports/`](phase_b/_reports/) 有历次 spike / setup 报告
3. 提 GitHub issue,贴 [INSTALL.md](INSTALL.md) § 1 软硬件 + 复现步骤
