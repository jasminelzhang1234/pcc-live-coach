# FAQ — 小白用户常问

> **状态**:in progress — 内容随代码状态同步更新。
>
> **面向人群**:两类小白都覆盖
> - **技术小白** — 不熟 Python / venv / .env / 命令行
> - **领域小白** — 不熟 ICF PCC 37 markers / 5.5-6.6-7.6 评估口径
>
> 如果这里没答到,看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 排错 → [INSTALL.md](INSTALL.md) 安装 → [README.md](README.md) 总览。

---

## 快速上手(技术小白)

- **Q:Mac 用户怎么启动?** — Finder 里双击 `start.command`,或在终端跑 `./start.sh`。脚本会自动激活 `.venv`、检查 `.env`、开浏览器。不要直接 `python -m phase_b.server`,绕过端口检查会 silent-break。
- **Q:启动后浏览器空白?** — 打开 [http://127.0.0.1:8765](http://127.0.0.1:8765) 看是否监听;终端会打印 `Uvicorn running on http://127.0.0.1:8765`。空白多半是 `.env` 缺凭据(后端启动失败但端口还没释放)。
- **Q:默认端口 8765 被占了?** — `start.sh` 现在会主动 `lsof` 检查并提示;或手动设 `PCC_LIVE_PORT=8766 ./start.sh` 换端口(浏览器地址也要改)。
- **Q:必须用 Chrome 吗?** — Chrome / Safari 都行。Firefox 没测过,不保证。

## 环境配置(技术小白)

- **Q:怎么注册 Aliyun NLS 拿到 3 个 key?** — 阿里云控制台开"智能语音交互"项目,**项目类型必须选"实时语音识别"**(不是"一句话识别",否则 WebSocket 协议不通),拿 AppKey;再到 [RAM 控制台](https://ram.console.aliyun.com/) 建子账号勾 `AliyunNLSFullAccess`,拿 AccessKey ID + Secret。完整图解: [`phase_b/_reports/aliyun-asr-setup-2026-09-06.md`](phase_b/_reports/aliyun-asr-setup-2026-09-06.md)。三个 key 分别填 `.env` 的 `ALIYUN_ASR_APPKEY` / `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`。
- **Q:怎么换 LLM provider?** — 改 `.env` 三件套:`LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL`。默认是 [MiniMax API](https://api.minimaxi.com/v1),代码走 OpenAI Chat Completions 协议,**任何 OpenAI 兼容端点都能切**:OpenAI / DeepSeek / Azure OpenAI / OpenRouter / OneAPI 改 URL + Key 即可。本地用 Ollama / LM Studio / vLLM 时 `LLM_API_KEY` 填任意非空字符串(它们不校验)。完整 provider 表: [README § LLM provider flexibility](README.md#llm-provider-flexibility)。
- **Q:想完全离线、不让对话出本机怎么办?** — 三件套全换本地:
  ```
  LLM_BASE_URL=http://127.0.0.1:11434/v1     # Ollama
  LLM_MODEL=qwen2.5:14b                       # 或你跑的任意模型
  LLM_API_KEY=not-used                        # 任意非空
  ```
  TTS 和 ASR 也可换自托管(详见 [PRIVACY.md § Supported providers](PRIVACY.md)),但配置更复杂,目前最常见的是 LLM 走本地、TTS/ASR 仍走云端(对话文字不出本机,但语音特征会上云)。
- **Q:`.env` 改了为什么不生效?** — 必须**重启** `./start.sh` 才重载。脚本不会 hot-reload 配置。
- **Q:`LLM_API_KEY` 报错 `401 Unauthorized`?** — 默认 MiniMax Key 没填;或本地 provider 时填成了 `not-used`(本地不校验,但云端会拒)。

## 训练流程(领域小白)

- **Q:怎么跑一场 session?** — 终端跑 `./start.sh` 起后端 → 浏览器打开 `127.0.0.1:8765` → dropdown 选 persona → 开始录音对话。结束点 dashboard "结束 session" 按钮。详情 [INSTALL.md § 8 跑通后](INSTALL.md#8-跑通后)。
- **Q:第一次练,选哪个 persona?** — 难度 1 系列,3 个温和起点: **vec-06 温亦(区域总经理)** / **vec-08 沈彦(新晋经理)** / **voc-05 范琳(新妈妈)**。挑一个跟你的真实客户画像最像的。完整表见 [personas/README.md](personas/README.md)。
- **Q:练哪个能练到 5.5 / 6.6 / 7.6(音频三大项)?** — 这三项必须在**真人或 AI 语音对话**里练,文本看不出沉默节奏/打断/提问语速。具体 persona 训练重点见 [personas/README.md](personas/README.md) "训练重点" 列。
- **Q:怎么评估一场 session?** — 文本逐字稿准备好后,在 Claude Code 里唤起 `pcc-assessor` agent,它会按 37 markers 逐条判定并出 HTML 报告。命令见 [`.claude/agents/pcc-assessor.md`](.claude/agents/pcc-assessor.md)。
- **Q:真人练习 vs AI persona 区别?** — 真人录音单独走 `progress/tracker-sessions.csv` + 暖橙配色趋势图(`progress/trending-chart-*.html`),AI persona 走标准 tracker。路径重命名缘由:避免真人标识泄漏到云同步/错误日志/stack trace —— 详见 [PRIVACY.md](PRIVACY.md)。
- **Q:练了一场但 tracker CSV 没新增?** — 检查 session 是否真的有 audio bytes;0 audio + 0 turn 的 probe session 会被 `phase_b/session/manager.py` fast-path 跳过,不落盘。
- **Q:我不想装任何东西,能现在就练吗?** — 能,用文字版:VS Code + Claude Code → 切到 `pcc-coachee` agent → 输入 `开始陪练,选 vec-08`。零 Python、零 `.env`、零阿里云账号、零麦克风,30 秒上场。覆盖 34/37 个 PCC markers(除 5.5 / 6.6 / 7.6 这 3 个音频专属)。完整 SOP 见 [personas/README.md § 配套练习 SOP](personas/README.md)。
- **Q:文字版能练到哪些?** — 议程澄清(3.x)、同理(4.x)、开放式提问(5.x 除 5.5)、情绪调频(6.x 除 6.6)、身份层探问(7.x 除 7.6)、会话闭环(8.x),共 **34/37 个 markers**。失分重灾区都在这里。完整 persona 训练对照见 [personas/README.md](personas/README.md) "按训练能力找 persona" 表。
- **Q:文字版和语音版是什么关系?** — 不是替代,是互补。文字版覆盖结构与情绪层(34/37),语音版额外加 3 个只能靠音频评估的维度:留白节奏(5.5)、不打断(6.6)、口语问题节奏(7.6)。建议:文字版稳定通过后再考虑语音版。
- **Q:语音版是默认启用的吗?** — **不是。** 语音版需要每个用户自己配置(阿里云账号 + `.env` 里 3 个 key + 麦克风),项目没法替你做,所以**永远 opt-in**。项目内部有一个独立的"实验性 → 推荐性"过渡:**≥10 场真人陪练**达成后,文档里把语音版从"实验性 opt-in"升级为"推荐性 opt-in"。当前 1/10,所以现在文档里还是"实验性"。详见 [README.md § Status](README.md#status)。

## 进度追踪(领域小白)

- **Q:tracker CSV 怎么读?** — 95 列宽表(主指标 + 37 marker 命中 + 节奏特征),[progress/tracker-sessions.csv](progress/tracker-sessions.csv)。列含义在 [`.claude/agents/pcc-tracker.md`](.claude/agents/pcc-tracker.md)。
- **Q:怎么看趋势图?** — `progress/trending-chart-<YYYY-MM-DD>.html`(默认按当天日期生成),浏览器打开即可。AI persona 走冷蓝配色、真人走暖橙配色,图例区分。
- **Q:CSV 行被截断 / Edit 工具报错?** — 95 列长行 Edit 工具不友好。走 `python3 -m phase_b.tracker.csv_append` 追加,不要手动编辑长行。

## PCC 概念速通(领域小白)

- **Q:37 个 PCC markers 是什么?** — ICF(国际教练联合会)PCC 认证评估用的 37 条行为指标,覆盖 8 大能力(建立协议/共同创造关系/有效沟通/培养学习成长等)。完整定义: [knowledge/pcc-markers-2025.md](knowledge/pcc-markers-2025.md)。
- **Q:为什么一定需要音频?文本不是更快吗?** — **5.5(允许沉默 / 停顿 / 反思)**、**6.6(允许客户说完不打断)**、**7.6(清晰直接主要开放式提问,一次一个,有节奏)** 这三项需要听**语速 / 沉默时长 / 打断时刻**才能判 —— 文本要么看不出来要么精度不够。本工具专门填这个 gap。原文说明: [README.md § What is this?](README.md#what-is-this)。
- **Q:5.5 / 6.6 / 7.6 在 37 markers 里是什么关系?** — 都是第 5 / 6 / 7 大能力下的具体行为指标,**写作风格要求的是字面命中**(沉默多久算 5.5、提几个问题算 7.6)。具体阈值见 [knowledge/competency-rules.md](knowledge/competency-rules.md)。
- **Q:这套评估准吗?** — ⚠️ **不是 ICF 官方工具**。判定规则来自一份真实的 PCC 督导录音转写,非 ICF 背书。**不能用于 ICF 正式申请**。完整边界: [DISCLAIMER.md](DISCLAIMER.md)。

## 隐私 / 合规(两类小白都该看)

- **Q:我的对话会被送到哪里?** — 默认:音频特征 → Aliyun NLS(上海 region) / 文本 → MiniMax API / 语音合成 → MiniMax T2A。**三方云服务都看得到对话内容**。完整数据流: [PRIVACY.md](PRIVACY.md)。要全程不联网,见上面"完全离线"那条。
- **Q:录音文件存多久?** — 默认 30 天(`AUDIO_RETENTION_DAYS=30`),服务器每次启动时清理过期文件。设 `0` 永久保留,负数禁用清理。规则: [PRIVACY.md § 6.5](PRIVACY.md)。
- **Q:能拿这个练的内容去申请 ICF PCC 吗?** — **不能**。ICF 要求**真人客户录音**,AI persona 不算。DISCLAIMER.md 写得很清楚。

## 性能 / 费用

- **Q:跑一场 45 分钟 session 大概多少 token?** — 客户端 ~3000-5000 input / 2000-4000 output(persona 短答 + 沉默触发);服务端 LLM think-time 单轮约 200 tokens(M3)。详细报表: `progress/token-spending-report-<YYYY-MM-DD>.html`。
- **Q:本地 Ollama 起 session 卡?** — 默认 `LLM_TIMEOUT_S=30`;本地模型慢的话调大 `.env` 的 `LLM_TIMEOUT_S`,或换小模型(qwen2.5:7b / llama3.1:8b)。

---

## 还没找到答案?

按这个顺序找:

1. 报错信息 → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. 安装/启动/凭据 → [INSTALL.md](INSTALL.md)
3. 隐私/合规/合规 → [PRIVACY.md](PRIVACY.md) + [DISCLAIMER.md](DISCLAIMER.md)
4. 部署/上线 → [DEPLOY.md](DEPLOY.md)
5. 都不是 → 在 GitHub Issues 搜 / 提 issue
