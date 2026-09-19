---
type: versioning-metadata
target_agent: pcc-assessor
current_version: v4.1.1
published_versions: [v0, v1, v2, v3, v4, v4.0.1, v4.1.0, v4.1.1]
last_updated: 2026-09-19
---

# pcc-assessor 版本元数据(单一真相源)

> ⚠️ **pcc-assessor agent 启动时必读此文件**(vN 解析优先级最高,见 `.claude/agents/pcc-assessor.md` § vN 自检步骤)
>
> 这是 pcc-assessor 行为规范版本的**唯一权威 metadata 文件**。`.claude/agents/pcc-assessor.md` 的版本史小节是 git 历史 + 教学用副本,以本文件为准。

## 当前默认

**vN 默认 = `v4.1.1`**(2026-09-19)

## 已发布版本(完整 changelog)

| vN | 日期 | 变更类型 | 触发源 | 关键变更 |
|---|---|---|---|---|
| v0 | 2026-08-22 前 | baseline | 项目初版 | 37 markers + 必命中项 + 结构性降档(初版) |
| v1 | 2026-08-22 | 累积(KB 规则) | vec-08 三方校准 | KB 修订 5 条核心规则 |
| v2 | 2026-08-24 | 累积(反偏松) | 4 个真人案例 + 真人督导师 | 8 条反偏松规则(8.2/7.5/8.3/6.5/8.8/3.4/5.2/6.7) |
| v3 | 2026-08-30 | 累积(反偏松) | 真人案例 06 + 真人督导师(观察员二号)| 第 9 条反偏松规则(6.7/8.2/8.3 "教练替客户先列总结" 模式 B)|
| **v4** | **2026-09-11** | **范式转变** | **09-10 撞分事故** + ICF PCC 实际口径校准 | PCC 实际口径换算(△ = not pass)+ 严格命中率 ✔/37 主指标 + 通过线 74% + 可打磨 △ 四级分类 + 公开版脱敏(389→734 行)|
| **v4.0.1** | **2026-09-14** | **行为加固(规则不变)** | **caller 错误触发**(vec-02 s01 prompt 显式要 .md + 沿用 v3)| HTML-only 硬规则 + v4 default 硬规则 + caller override 拒绝;KB 判定规则不变 |
| **v4.1.0** | **2026-09-14** | **行为加固(规则不变)** | **结构不稳定触发**(vec-07 s01 / Angela 2026-09-08 / vec-02 v4 三场章节顺序 + CSS 风格不一致 + "v3 vs v4 对比"过渡残留)| 新建 `knowledge/pcc-assessor-html-template.md` 固化 12 章节顺序 + CSS 按场次类型(AI 蓝 / 真人橙)+ 占位符 + 可选章节显式标注;spec 加"调 template 产报告"硬规则 + 文末骨架精简并指向 template 文件;KB 判定规则完全不变 |
| **v4.1.1** | **2026-09-19** | **行为加固(可选章节结构固化)** | **vec-02 s04 翻车复盘显式需求**(必命中 ✘ 3,一票否决触发,需要在结构层显式承载"翻车复盘 / 关键转折点"段,而非塞进 § 9 主要优势与失守)| template § 3 新增 [card] ⑫ 翻车复盘 / 关键转折点(可选 IF `N_MUST_FAIL >= 2`);footer 改成 ⑬;章节总数 12 → 13(其中 3 个可选);KB 判定规则完全不变 |

## 变更类型分类(供未来 v5 决策参考)

| 类型 | 含义 | 典型触发 | 频率 |
|---|---|---|---|
| **baseline** | 初版 | 项目启动 | 仅 1 次 |
| **累积** | 在上一版基础上加 1-N 条规则,KB 实质内容变 | 数据驱动(三方校准 / 真人案例 / 真人督导师)| 早期 1-2 天 1 次,稳定期 1-2 周 1 次 |
| **范式转变** | 算法 / 报告格式 / 脱敏 等非 KB 规则变化 | 用户撞分事故 / 外部标准对齐 / 公开化需求 | 1-2 月 1 次 |
| **行为加固** | KB 规则不变,只加固 agent 行为 | caller 错误 / 工具调用漏洞 | 不定期 |

## vN 解析规则(agent 必读,优先级最高)

```
1. 默认值 = frontmatter.current_version
2. 显式 override 接受条件(BOTH 必须满足):
   - 上下文是"reeval 同一份 transcript"(关键词:reeval / 重跑 / 用旧 KB)
   - 显式 vN ∈ frontmatter.published_versions 列表
3. 拒绝(任一):
   - caller 措辞模糊("沿用 vec-07 v3 的 v3"/"按 v3 模式") → 走默认值 + 标依据
   - caller 自相矛盾("vN = 当前 KB,沿用 v3") → 走默认值 + 标依据
   - caller 显式说"vN"但不在 published_versions 列表里 → 拒绝 + 解释(可能是 v5+ 未来版)
   - caller 显式说"v5"或更新(不在列表里) → 拒绝 + 解释(v5 尚未发布)
4. 落盘 metadata 必须标:
   - 实际用的 vN
   - 解析依据(如"v4.0.1(默认)"/"v3(caller reeval 上下文 + 显式 v3)"/"v4.0.1(caller 措辞模糊 → 走默认)")
```

## 文件更新规则(升 vN 时必做 5 步)

1. 改本文件 `frontmatter.current_version` 字段
2. 改本文件 `frontmatter.published_versions` 列表(加新 vN)
3. 改本文件"已发布版本"表加新行
4. 同步更新 `.claude/agents/pcc-assessor.md` 的版本史小节(供 git 历史 + 教学)
5. 同步更新所有引用 vN 的 agent(pcc-coachee / pcc-tracker — 见"agent 间引用同步清单")
6. 跑 `scripts/sync_agents.py` 镜像到 `.github/agents/`

## agent 间引用同步清单

升 vN 时必检下列引用,统一更新:

| 引用位置 | 当前值 | 来源 |
|---|---|---|
| `.claude/agents/pcc-assessor.md` § 版本史 | v4.1.0(本文件后)| spec 副本 |
| `.claude/agents/pcc-assessor.md` § 输出格式 vN | v4.1.0(本文件后)| spec 副本 |
| `knowledge/pcc-assessor-html-template.md` | v4.1.0 配套 template | template 文件 |
| `.claude/agents/pcc-coachee.md` 转交块 | **v3(过期!需修)** | coachee spec |
| `.claude/agents/pcc-tracker.md` schema eval_version | v2.5(tracker 内部 schema,非 KB 版本)| tracker spec |

## 加载策略

- **本地环境**(本文件存在)→ pcc-assessor 启动时 Read,frontmatter 解析作为 vN 真相源
- **clone-only 环境**(本文件不存在,如公开 GitHub 仓)→ 降级到 `.claude/agents/pcc-assessor.md` § 版本史硬编码列表(spec 内置 v0-v4.0.1 副本)
- 不报错,降级路径不破坏公开版可读性
