# 阿里云智能语音交互(实时语音识别)— 手把手注册

> 2026-09-06 · 配套 phase_b 换栈决策(方案 2:商业 STT + MiniMax 栈)
>
> **重要:S2S 必须用"实时语音识别"(流式),不是"一句话识别"**。
> 一句话识别是用户说完一段再识别,S2S 需要边说边识别才能给出 partial 输出。注册项目时项目类型必须选 **"实时语音识别"**。

---

## 0. 你会拿到的三样东西

| 凭证 | 在哪拿 | 用途 |
|---|---|---|
| **阿里云账号** | 注册即得 | 主账号 |
| **AppKey** | NLS 控制台创建项目后 | 标识具体 ASR 项目,调用时必传 |
| **AccessKey ID + Secret** | RAM 控制台 | 鉴权签名,用来换 Token |

调用链路:`AccessKey ID/Secret` → 换短期 `Token`(24h 有效) → 用 `Token` + `AppKey` 调 ASR API。

---

## 1. 注册 + 实名认证(已有账号跳过)

1. 浏览器打开 [https://www.aliyun.com](https://www.aliyun.com)
2. 右上角 **"免费注册"** → 用手机号 + 支付宝/钉钉扫码
3. 注册成功后,右上角点头像 → **"实名认证"**
   - 个人认证:身份证 + 支付宝刷脸,5 分钟过
   - 企业认证:营业执照,1-3 个工作日

**不实名认证开不了语音服务**,必须做。

---

## 2. 开通智能语音交互服务

1. 登录后访问 [https://nls-portal.console.aliyun.com/](https://nls-portal.console.aliyun.com/)
   - 如果提示未开通,会跳到产品页
2. 点击 **"立即开通"** 或 **"管理控制台"**
3. 计费方式选 **"按量付费"**(前期用量小)
   - 也可以买资源包(更便宜),但按量付费无门槛
4. 开通完成

**价格参考**(2026-09 时点,实时语音识别):
- 0.0008 元/秒 = 0.048 元/分钟 = 2.88 元/小时
- 比 OpenAI gpt-realtime 便宜一个数量级
- free tier:每月 2 万次调用(具体看官网最新说明)

---

## 3. 创建项目 → 拿 AppKey

1. 在 NLS 控制台 → 左侧 **"全部项目"**
2. 右上角 **"创建项目"**:
   - **项目名称**:`pcc-live-coach` (随便起,你认得出就行)
   - **项目类型**:选 **"实时语音识别"** ⚠️ 不要选"一句话识别"
   - **语言**:中文(普通话)
   - **采样率**:16kHz
   - **音频格式**:PCM(裸流)
3. 点 **"确定"**
4. 创建完成后,列表里会显示新项目,**AppKey** 列就是你要的字符串
   - 复制下来备用,**形如 `abcdefgh1234`**

---

## 4. 创建 AccessKey(ID + Secret)

1. 访问 [https://ram.console.aliyun.com/](https://ram.console.aliyun.com/) (RAM 访问控制)
2. 左侧 **"身份管理"** → **"用户"**
3. 右上角 **"创建用户"**:
   - 登录名:自定义(如 `pcc-asr-user`)
   - 访问方式:**勾选"OpenAPI 调用访问"**
4. 创建完成后,**务必保存弹窗里的 AccessKey ID 和 Secret**:
   - AccessKey ID:`LTAI5t...`(大写字母开头)
   - AccessKey Secret:`xxxxxxxxxx`(只显示一次,关掉就找不回)

**不要用主账号的 AccessKey**(权限太大),用子账号更安全。

### 给子账号加权限

回到 RAM 控制台:

1. 用户列表 → 找到 `pcc-asr-user` → 点 **"添加权限"**
2. 搜索 **"AliyunNLSFullAccess"** 或 **"智能语音交互 full access"**
3. 勾选 → 确定

权限不够会报 403。

---

## 5. 测试一次(可选,但建议先跑通)

把下面 Python 脚本保存到 `phase_b/scripts/test_aliyun_asr.py`,填入你的三个凭证:

```python
import json
import time
import uuid
import hashlib
import hmac
import base64
import urllib.parse
import requests

ACCESS_KEY_ID = "LTAI5txxxxxxxxxx"      # 你的 AccessKey ID
ACCESS_KEY_SECRET = "xxxxxxxxxx"        # 你的 AccessKey Secret
APPKEY = "abcdefgh1234"                 # 你的 AppKey
AUDIO_FILE = "/tmp/test_16k.pcm"        # 一段 16kHz mono PCM 文件

# 1. 换 Token
def get_token():
    url = "https://nls-meta.cn-shanghai.aliyuncs.com/token"
    params = {
        "AccessKeyId": ACCESS_KEY_ID,
        "AccessKeySecret": ACCESS_KEY_SECRET,
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if "Token" not in data:
        raise RuntimeError(f"换 Token 失败: {data}")
    return data["Token"]["Id"], data["Token"]["ExpireTime"]

# 2. 一句话识别测试(短音频 < 60s)
def test_short_sentence():
    token, expire = get_token()
    print(f"Token 拿到,过期时间: {expire}")
    url = "https://nls-cn-shanghai.aliyuncs.com/stream/v1/asr"
    with open(AUDIO_FILE, "rb") as f:
        audio = f.read()
    params = {
        "appkey": APPKEY,
        "token": token,
        "format": "pcm",
        "sample_rate": 16000,
        "enable_intermediate_result": "false",
    }
    headers = {"Content-Type": "application/octet-stream"}
    r = requests.post(url, params=params, headers=headers, data=audio, timeout=30)
    print("响应:", r.json())

if __name__ == "__main__":
    test_short_sentence()
```

跑一下:

```bash
.venv/bin/python phase_b/scripts/test_aliyun_asr.py
```

成功的话应该返回 `{"status":20000000, "result":"你好世界"}` 之类的 JSON。

---

## 6. 填入 .env

`pcc-live-coach/.env` 加三行:

```bash
# 阿里云 ASR(2026-09-06 起替代 FunASR)
ALIYUN_ASR_APPKEY=abcdefgh1234
ALIYUN_ACCESS_KEY_ID=LTAI5txxxxxxxxxx
ALIYUN_ACCESS_KEY_SECRET=xxxxxxxxxx
```

⚠️ **不要把 `.env` 提交到 git**(已经在 `.gitignore` 里,但要确认)。

---

## 7. 下一步

等你拿到三样凭证后告诉我,我们:

1. 写 `phase_b/asr/aliyun_client.py`(RESTful 调用 + Token 缓存)
2. 改 `phase_b/asr/asr_worker.py` 拆掉 FunASR,改成调 aliyun_client
3. 拆 FunASR 特有的 3 项修复(单字过滤 / dedupe / overlap)— 商业 ASR 通常不需要
4. 跑一次端到端:浏览器说话 → STT → LLM → TTS → 浏览器播放
5. 跑通后更新 INSTALL.md 和 spike-report §11 决策回写

---

## 常见坑

| 问题 | 解决 |
|---|---|
| 报 `InvalidAccessKeyId` | AccessKey ID 输错了,或子账号没创建 |
| 报 `Token expired` | Token 默认 24h,会缓存自动续 |
| 报 `InvalidAppKey` | AppKey 输错了,或项目类型选成"一句话识别" |
| 报 `403` | RAM 没加 `AliyunNLSFullAccess` 权限 |
| 报 `Audio format not supported` | 音频不是 16kHz mono PCM,要重采样 |
| 中文识别全是乱码 | 检查 PCM 是 little-endian int16,不是 float32 |
| **SDK 0.0.1 收到事件但 result 字段读为空** | **见下面"S2S 集成踩坑"** |
| **MiniMax LLM 报 401 但 .env 看着对** | **见下面"S2S 集成踩坑"** |

---

## S2S 集成踩坑(2026-09-06 修好)

这两个 bug **直接导致 phase B 端到端从未成功过一次**,因为症状都是"看似工作但什么都不出"。

### Bug 1:Aliyun ASR SDK 0.0.1 字段嵌套

aliyun-nls SDK 0.0.1 的 Python SDK **不解析 JSON 字段**,只是把服务端消息字符串透传到回调函数。

服务端返回格式是**嵌套**的:

```json
{
  "header": {"name": "TranscriptionResultChanged", "status": 20000000, ...},
  "payload": {
    "index": 1, "time": 480,
    "result": "第一次遇",          ← 识别文字
    "confidence": 0.79
  }
}
```

**错误写法**(历史 bug):
```python
data = json.loads(msg)
text = (data.get("result") or "").strip()    # ❌ 永远是 None
```

**正确写法**:
```python
data = json.loads(msg)
payload = data.get("payload", {}) or {}
text = (payload.get("result") or "").strip()   # ✅ "第一次遇"
```

定位过程:服务端返回完整消息加 raw WebSocket 客户端能识别(用 `rstrip=True` 解码后的 `'第一次遇'`),证明是 SDK 回调后 client 解析错位。修复后 ASR partial 正常出现。

### Bug 2:`.env` 不覆盖 shell env,导致过期 key 静默胜出

`phase_b/config.py` 的 `_load_dotenv` 原本写法:

```python
if key and key not in os.environ:   # ❌ shell 有就跳过 .env
    os.environ[key] = value
```

后果:用户的 shell 里有**过期**的 `LLM_API_KEY`(来自其他项目),覆盖了 `.env` 里**正确**的新 key。MiniMax 返回 401 Unauthorized。修法: `.env` 永远覆盖 shell — 项目级 `.env` 是 source of truth。

```python
if key:
    os.environ[key] = value          # ✅ .env 优先
```

### 参考

完整 phase B 数据流速查 + 端到端数据落点见 [`phase_b/_reports/phase-b-data-flow-2026-09-06.md`](phase-b-data-flow-2026-09-06.md)。

---

## 来源

- [阿里云智能语音交互产品页](https://nls-portal.console.aliyuncs.com/)
- [RAM 访问控制](https://ram.console.aliyun.com/)
- [阿里云帮助中心 - 智能语音交互](https://help.aliyun.com/product/84428.html)