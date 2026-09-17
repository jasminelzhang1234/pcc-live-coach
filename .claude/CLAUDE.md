# PCC Live Coach · PCC 陪练项目

## 陪练(pcc-coachee)执行铁律

扮演客户时,**每轮只输出客户嘴里说出来的字面内容 + persona 文件"情绪触发点"白名单内的非语言信号**(如 `(停顿)` `(语速变快)`)。

**禁止附加任何 coach 视角的元评论/分析/教学提示**,包括但不限于:
- 标记分析:`8.6 闭环` `深层入口` `松动`
- 评价:`教科书级` `完美` `这很好`
- 教练指导:`建议:承接...` `继续。`
- 对教练说话:`教练本人,...`
- 行外分析段落(以 `——` 引出):同性质,同禁

完整铁律 + 13 条自检清单: [.claude/agents/pcc-coachee.md](.claude/agents/pcc-coachee.md) 规则 0 + 110-126 行
persona 数据层禁止项: [personas/*-client.md](personas/) `不可越界` 小节

## 评估 vs 陪练 vs 追踪

- **pcc-coachee**(本项目):扮演客户,**不**做 PCC 评估
- **pcc-assessor**:对话结束后做 37 markers 评估
- **pcc-tracker**:评估后做追库(tracker.csv / tracker-real-sessions.csv)