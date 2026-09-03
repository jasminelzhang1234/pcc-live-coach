# Disclaimer

Last updated: 2026-09-03

## 1. Not an ICF-certified tool

This software is **not certified, endorsed, or affiliated with the International Coaching Federation (ICF)**. The PCC marker evaluation criteria used by this tool are derived from a **single real PCC supervision transcript** that was used as a calibration baseline. The criteria are an **estimate**, calibrated by the maintainer against one supervision case, and are **not** an official ICF standard.

ICF has never publicly disclosed the minimum number of markers required per competency. ICF's official documentation describes only that markers "must be demonstrated" without quantitative thresholds. Therefore:

- All ✔ / △ / ✘ judgments produced by this tool are **estimates**, not official ICF evaluations.
- **Do not** submit outputs from this tool as part of any ICF credentialing application.
- **Do not** use this tool's evaluations to claim PCC competency, MCC competency, or any other ICF credential.
- Pass or fail judgments from this tool do **not** correspond to ICF pass or fail criteria.

If you are preparing for an ICF credentialing exam, please consult ICF's official resources, an ICF-accredited coach training program, and a PCC / MCC-certified mentor.

## 2. Not a substitute for real client practice

ICF requires that credentialing applications include recordings of sessions with **real clients**, not AI personas. This tool exists to help you practice the **rhythm** dimension of coaching (5.5 / 6.6 / 7.6) — three markers that are difficult to assess from text alone. It is **not**:

- A replacement for real coaching hours.
- A replacement for mentor coaching.
- A replacement for ICF-accredited training programs.
- A substitute for the ICF credentialing exam itself.

Use this tool to practice between real client sessions, not instead of them.

## 3. AI personas ≠ real clients

Personas in `personas/` are constructed from real supervision transcripts and follow reaction rule tables. They are **not** human. They cannot:

- Surprise you with novel emotional reactions.
- Push back in ways the persona designer did not anticipate.
- Match the depth and unpredictability of real human distress.
- Provide the relational learning that only comes from real human connection.

Treat persona practice as a sandbox for **rhythm mechanics**, not as preparation for emotional complexity.

## 4. No warranty

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. See [LICENSE](LICENSE) for the full Apache-2.0 disclaimer text.

The maintainer makes no representation that:

- The tool will function without error.
- The tool's evaluations are accurate or reliable.
- The tool is suitable for any particular purpose.
- The tool will continue to be maintained, updated, or available.

## 5. No liability

In no event shall the maintainer be liable for any claim, damages, or other liability arising from, out of, or in connection with the use of, or inability to use, this software. See [LICENSE](LICENSE) for the full Apache-2.0 limitation of liability text.

Specifically:

- If this tool evaluates you as ✘ and you lose confidence in your coaching — that is not the maintainer's liability.
- If this tool's ASR misrecognizes words and you train on incorrect transcripts — that is not the maintainer's liability.
- If you submit this tool's output to ICF and your application is rejected — that is not the maintainer's liability.
- If you use this tool with real client material and the client data is exposed — see [PRIVACY.md](PRIVACY.md), but the responsibility is yours.

## 6. Speech recognition accuracy

The default speech recognition model ([FunASR paraformer-zh-streaming](https://github.com/modelscope/FunASR)) achieves ~4.2% Word Error Rate on standard Mandarin benchmarks. Real-world accuracy varies with audio quality, accents, domain vocabulary, and background noise. Common failure modes include:

- English technical terms ("CEO", "OKR", "AI") may be misrecognized.
- Proper nouns may be hallucinated.
- Numbers may be transcribed incorrectly.
- Background noise may insert phantom words.

**Do not trust transcript output verbatim.** When in doubt, replay the audio.

## 7. No medical, psychological, or therapeutic claims

This tool is for **coaching skills practice** only. It does not provide:

- Medical advice.
- Psychological counseling.
- Psychotherapy.
- Mental health treatment.
- Crisis intervention.

If you are experiencing a mental health crisis, contact a licensed professional or local emergency services.

## 8. Use at your own risk

By using this tool, you acknowledge and agree to the terms in this disclaimer. If you do not agree, do not use the tool.

---

<br/>
<br/>

# 免责声明

最后更新:2026-09-03

## 1. 非 ICF 认证工具

本软件**未经国际教练联合会(ICF)认证、背书或关联**。本工具使用的 PCC 标记评估标准来自**一份真实 PCC 督导录音**,用作校准基线。这些标准是**估算值**,由维护者针对一份督导案例校准,**不是** ICF 官方标准。

ICF 从未公开披露每项能力所需的最低标记数量。ICF 的官方文件仅描述标记"必须展现",没有定量门槛。因此:

- 本工具产出的所有 ✔ / △ / ✘ 判断都是**估算**,不是 ICF 官方评估。
- **不要**将本工具的产出作为任何 ICF 认证申请的一部分提交。
- **不要**使用本工具的评估来声称具备 PCC 能力、MCC 能力或任何其他 ICF 资质。
- 本工具的通过或不通过判断**不对应** ICF 的通过或不通过标准。

如果你正在准备 ICF 认证考试,请参考 ICF 官方资源、ICF 认证的教练培训项目,以及 PCC / MCC 认证导师的指导。

## 2. 不能替代真实客户练习

ICF 要求认证申请包含**真实客户**(而非 AI 人格)的会谈录音。本工具的存在是为了帮助你练习教练的**节奏**维度(5.5 / 6.6 / 7.6)——这三个标记很难仅凭文本来评估。它**不是**:

- 真实教练时长的替代品
- 导师教练的替代品
- ICF 认证培训项目的替代品
- ICF 认证考试本身的替代品

在真实客户会谈之间使用本工具练习,而不是用它代替。

## 3. AI 人格 ≠ 真实客户

`personas/` 中的人格是根据真实督导录音构建的,并遵循反应规则表。它们**不是**人。它们无法:

- 用新颖的情绪反应让你惊讶
- 以人格设计者未预料的方式抵抗你
- 匹配真实人类痛苦的深度和不可预测性
- 提供只有真实人际连接才能带来的关系学习

将人格练习视为**节奏机制**的沙盒,而非情感复杂性的准备。

## 4. 无担保

本软件按"原样"提供,不做任何明示或暗示的担保,包括但不限于适销性、特定目的适用性和非侵权的担保。完整 Apache-2.0 免责声明见 [LICENSE](LICENSE)。

维护者不保证:

- 工具无错误运行
- 工具的评估准确或可靠
- 工具适合任何特定目的
- 工具将继续被维护、更新或可用

## 5. 无责任

在任何情况下,维护者均不对因使用、或无法使用本软件而引起的任何索赔、损害或其他责任负责。完整 Apache-2.0 责任限制条款见 [LICENSE](LICENSE)。

具体来说:

- 如果本工具将你评估为 ✘ 并因此失去对教练能力的信心 — 这不是维护者的责任
- 如果本工具的 ASR 错误识别单词,你在错误转写上训练 — 这不是维护者的责任
- 如果你将本工具的产出提交给 ICF 但申请被拒 — 这不是维护者的责任
- 如果你使用本工具处理真实客户材料且客户数据被泄露 — 详见 [PRIVACY.md](PRIVACY.md),但责任在你

## 6. 语音识别准确度

默认语音识别模型([FunASR paraformer-zh-streaming](https://github.com/modelscope/FunASR))在标准普通话基准上达到约 4.2% WER(词错误率)。真实场景准确度因音频质量、口音、领域词汇和背景噪音而异。常见失败模式包括:

- 英语技术术语("CEO"、"OKR"、"AI")可能被错误识别
- 专有名词可能被幻觉生成
- 数字可能被错误转写
- 背景噪音可能插入幻影词

**不要盲目信任转写输出。** 有疑问时,回放音频。

## 7. 无医疗、心理或治疗声称

本工具仅用于**教练技能练习**。它不提供:

- 医疗建议
- 心理咨询
- 心理治疗
- 心理健康治疗
- 危机干预

如果你正在经历心理健康危机,请联系有执照的专业人员或当地紧急服务。

## 8. 自担风险

使用本工具即表示你承认并同意本免责声明中的条款。如果你不同意,请不要使用本工具。