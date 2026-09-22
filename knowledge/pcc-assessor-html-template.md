---
name: pcc-assessor-html-template
description: |
  pcc-assessor HTML 报告骨架模板(v4.1+ 硬规则)。固化 12 章节顺序(其中 2 个可选) + CSS 风格
  + 占位符语法 + 可选章节显式标注;让 pcc-assessor agent 每次只填值不动结构。
  v4.1.3 起 § 7 PCC 考官模拟判定 整章删,核心内容(实际口径 / 一票否决 / 通过概率)分散到
  § 2 整体评级 callout + § 3 末尾 PCC 实际口径 callout。
  v4.1.4 起 `## → Tracker 转交` 机器接口段**不**写入 HTML 报告文件(只走 agent 间通信)。
type: template
spec_version: v4.1.4
last_updated: 2026-09-22
---

# pcc-assessor HTML 报告骨架模板

## 1. 用途与硬规则

pcc-assessor agent 在生成 HTML 报告时,**必须**按本模板的 12 章节顺序 + 占位符语法产出。不允许:
- 重排章节顺序
- 改变章节命名
- 自由发挥 CSS 风格
- 跳过任一"必有"章节
- 保留"v3 vs v4 对比"等过渡章节(那是 v4 升级产物,不是常驻章节)
- 重新引入已删除的 § 7 PCC 考官模拟判定 整章(v4.1.3 起删除,内容分散)

允许:
- 可选章节(§ 10 跨场趋势 / § 11 翻车复盘)按显式条件出现
- 占位符填值
- KPI 数值随 transcript 变化
- 判定文字随 transcript 变化

## 2. CSS 风格固化(按场次类型)

CSS 调色板按本场类型二选一,**不允许**自由配色:

| 场次类型 | 主色 | accent | muted | 用途 |
|----------|------|--------|-------|------|
| AI persona 模拟场 | `#2b6cb0` 蓝 | `--accent: #2b6cb0` | `#5b6473` | practice-logs/AI陪练/ 下所有报告 |
| 真人陪练场 | `#d97706` 暖橙 | `--accent: #d97706` | `#78350f` | others-sessions/ 与 practice-logs/真人练习/ |

**判断方式**:`persona_id` 存在(`vec-XX` / `voc-XX` / `vic-XX`)= AI 场;`persona_id` 为空或 `real_client_*` = 真人场。

## 3. 章节顺序(固定 12 个,其中 2 个可选)

```
[header]                   ① KPI 行(7 个卡片)
[card] 元信息               ② meta-grid + 整体评级 callout(含 PCC 通过概率 + 一票否决 + 综合判定)
[card] 必命中项检查         ③ 7 条 must-marker 大表 + 末尾 PCC 实际口径换算 callout(△ = not pass)
[card] 37 条 markers 全表   ④ 按能力分组(能力 3/4/5/6/7/8),保留 rowspan 分组
[card] 结构性降档规则       ⑤ 5 条 vec-08 三方校准规则表
[grid-2]                   ⑥ 能力维度分布表 + 雷达图
                            (空右侧)判定构成柱状图
[card] 可打磨 △ 清单       ⑦ 8 条 △ 按标点/一句/流程/思维 4 级分类(修补说明格式见 § 7.5)
[card] 主要优势与失守      ⑧ grid-2 双列 ✓优势 / ✗失守
[card] 下一步练习建议       ⑨ P0/P1/P2/P3 优先级表
[card] 跨场趋势           ⑩ 可选 IF persona_id 已存在 ≥ 2 场
[card] 翻车复盘 / 关键转折点  ⑪ 可选 IF N_MUST_FAIL >= 2(必命中 ✘ ≥ 2)
[footer]                   ⑫ 数据来源 + vN + 生成日期
```

**§ 2 整体评级 callout 内容规范**(v4.1.3 加):
- 整体评级结论(达标 / 边缘 / 未达标)+ 关键数据 + 1-2 句滑动弧线总结
- **PCC 通过/不通过综合判定**(原 § 7 内容):4 维列表(总数过线 / 必命中过 / 一票否决触发 / 能力平衡)
- **PCC 通过概率估算**(原 § 7 内容):数字 + 公式推导(基础分 + 罚分 + 可打磨 △ 奖励)

**§ 3 末尾 PCC 实际口径换算 callout 内容规范**(v4.1.3 加):
- 一句话声明:**PCC 评估者对每条 marker 只给 pass / not pass — △ 在 ICF 考试中算 not pass**
- 一票否决 4 项检查清单(合约没锁 / 替客户决定 / 替客户总结 / 必命中 7/7)+ 本场触发状态

**章节命名固定**(h2 标题文字必须字面一致):
- `对话元信息` / `必命中项检查(7 条,任一 ✘ = 一票否决)` / `37 条 Markers 全表`
- `结构性降档规则命中情况` / `能力维度分布`
- `可打磨 △ 清单` / `主要优势与失守` / `下一步练习建议`
- `跨场趋势({persona_id} · {start_date} → {end_date})` [可选]
- `翻车复盘 / 关键转折点(必命中 ✘ {N_MUST_FAIL} · 触发条件:必命中 ≥ 2)` [可选]
- `footer`: `数据来源 + KB 版本 v{N} + pcc-assessor(Claude) + 生成日期`

**§ 7 PCC 考官模拟判定 整章删除理由**(v4.1.3):
- 31 行 marker 表与 § 4 37 markers 全表完全重复(同一份 ✔/△/✘ 重新打包)
- 能力维度 pass 率表与 § 6 能力维度分布表完全重复
- 综合判定 + 通过概率已搬至 § 2 整体评级 callout
- PCC 实际口径换算(△ = not pass)+ 一票否决检查已搬至 § 3 末尾 callout

**翻车复盘章节内容规范**(v4.1.1 加):
- 关键转折点表(R 轮次 / 教练动作 / 客户反应 / 模式识别)
- 一票否决 marker 详情 + 必命中 3 失守的链式影响
- 能力 4 信任与安全的底层失守证据(无具体才能认可 / 无同理回应 / 无教练个性化)
- 防守模式表(后半段 catchphrase + 单字回应频率)
- 历史轨迹诊断(本 persona 跨场趋势)
- 一段观察:底层信任 + 觉察未建立,poc 反复不会突破

## 4. KPI 行(7 个卡片,固定)

```html
<div class="kpi"><div class="kpi-label">严格命中率(主)</div><div class="kpi-value">{PCT_STRICT}</div><div class="kpi-sub">{N_STRICT} / 37</div></div>
<div class="kpi"><div class="kpi-label">复合命中率(辅助)</div><div class="kpi-value" style="font-size:18px;opacity:0.7;">{PCT_COMPOSITE}</div><div class="kpi-sub">({N_STRICT}+0.5×{N_PARTIAL})/37</div></div>
<div class="kpi"><div class="kpi-label">✔ 严格</div><div class="kpi-value">{N_STRICT}</div></div>
<div class="kpi"><div class="kpi-label">△ 边缘</div><div class="kpi-value">{N_PARTIAL}</div></div>
<div class="kpi"><div class="kpi-label">✘ 失守</div><div class="kpi-value" style="color:#fff;">{N_FAIL}</div></div>
<div class="kpi"><div class="kpi-label">必命中✘</div><div class="kpi-value">{N_MUST_FAIL}</div><div class="kpi-sub">{MUST_FAIL_DETAIL}</div></div>
<div class="kpi"><div class="kpi-label">PCC 通过概率</div><div class="kpi-value">≈{PCT_PCC_PASS}%</div><div class="kpi-sub">v{N} 公式估算</div></div>
```

## 5. 占位符总表

| 占位符 | 来源 | 必填 |
|--------|------|------|
| `{SESSION_DATE}` | transcript 文件名或日期声明 | ✔ |
| `{PERSONA_ID}` | `vec-XX` / `voc-XX` / `vic-XX` / `real_*` | ✔(真人场为 `real_*`) |
| `{PERSONA_NAME}` | persona 文件化名字段 | ✔ |
| `{COACH_NAME}` | 教练真名 / 角色 | ✔ |
| `{SESSION_TYPE}` | `AI persona 模拟陪练` / `真人陪练` / `others-sessions` | ✔ |
| `{N_STRICT}` | 判定表 ✔ 数 | ✔ |
| `{N_PARTIAL}` | 判定表 △ 数 | ✔ |
| `{N_FAIL}` | 判定表 ✘ 数 | ✔ |
| `{PCT_STRICT}` | `N_STRICT / 37 * 100`,一位小数 | ✔ |
| `{PCT_COMPOSITE}` | `(N_STRICT + 0.5*N_PARTIAL) / 37 * 100` | ✔ |
| `{N_MUST_FAIL}` | 必命中 7 项中 ✘ 数 | ✔ |
| `{MUST_FAIL_DETAIL}` | 必命中 ✘ 的 marker ID(如 `3.4 一票否决`) | ✔ |
| `{PCT_PCC_PASS}` | v4 公式算出的 PCC 通过概率 0-100 整数 | ✔ |
| `{vN}` | pcc-assessor-versions.md current_version | ✔ |
| `{JUDGE_MAIN}` | 评估者标识(Claude v{N} / GPT-5.6 / DeepSeek V4 Flash) | ✔ |
| `{JUDGE_2}` | second judge 或 `-` | ✔ |

## 6. 可选章节标注

模板里有 2 个章节是可选的,其他必须出现:

```
<!-- IF persona_id 已存在 ≥ 2 场(查 tracker.csv / tracker-real-sessions.csv) -->
[card] 跨场趋势
<!-- END IF -->

<!-- IF {N_MUST_FAIL} >= 2(必命中 ✘ ≥ 2,触发一票否决临近) -->
[card] 翻车复盘 / 关键转折点
<!-- END IF -->
```

**严禁保留**:`v3 vs v4 对比小节` 在 v4.1+ 是过期产物。2026-11 起必须从所有报告移除。

## 7. ⑧ 可打磨 △ 清单修补说明格式规范(v4.1.2 固化)

每条 △ 的"修补说明"列必须包含**两部分原文**(不可省略、不可缩写、不可只写补句不写原问):

### 7.1 格式模板

```
<strong>原 R{N} 教练{问|说|邀请}:</strong>"{原文全文}" → <strong>修补:</strong>{补句说明,内含锚定到具体内容}
```

- **前半段**(`<strong>原 R{N} 教练...:</strong>"{原文全文}"`)— 必须写明:
  - 引用轮次(精确到 R 几,引用范围允许,如 `R20-R30 想象法套路`)
  - 教练动作类型(`问` / `说` / `邀请` / `偏单方面宣告` 等)
  - **原教练句全文**(一字不改,包括错别字、标点、斜杠等瑕疵)
- **后半段**(`<strong>修补:</strong>{...}`)— 必须锚定:
  - 补句中所有模糊指代(`这件事` / `这个说法` / `那儿` / `你懂的`)必须**锚定到具体内容**
  - 锚定来源:客户原话(R 几 + 内容)/ 教练原评价(R 几 + 内容)/ 议题(R6 / R7 议程建立时确认的议题)
  - 锚定方式:用引号直接引用原内容 + R 几编号,不允许"那件事"等指代

### 7.2 锚定指代清单(常见 → 必须锚定)

| 模糊词 | 锚定方式 | 示例 |
|--------|---------|------|
| `这件事` | 引用客户原议题(R6/R7 已确认)| `为什么"判断一个人能不能用"这件事对你来说重要?` |
| `这个说法` | 引用教练原评价(R 几 + 内容)| `这个说法(关于你从"扛活"到"走一个方向"的变化)对你来说贴切吗?` |
| `那儿` | 引用 R 几已浮现的内容| `那要怎么才能到"扛活+方向"两个维度的状态?` |
| `你懂的` | 拆开为客户原话 + 情绪探索问句 | `"你懂的"那个感觉是什么?` |
| `如何评价自己` | 引用客户原标签(R 几)| `你怎么看自己是个"能专注业务、扛活+走方向"的人?` |

### 7.3 反例(不允许出现)

- ❌ `R8 后补一句"为什么这件事对你来说重要?"把"意思"换成"重要性"` — 缺原问全文 + 模糊指代
- ❌ `R20-R31 的想象法改成引用客户具体原话("你刚说的'扛活'")` — 缺原问全文 + 缺锚定机制
- ❌ `R36 评价后加"这个说法对你来说贴切吗?"` — 缺原评价全文 + 缺锚定
- ❌ `R48 后加"如何确保你做到呢?"` — 缺原问全文

### 7.4 触发源

- vec-02 s02 报告(2026-09-19)用户反馈:"修补说明部分的表达不清楚,原来的格式只写补句不写原问题全文"
- 配套 KB 判定规则完全不变,纯结构层固化

## 8. 历史

- 2026-09-14: 初版(vec-02 s01 / vec-07 s01 / Angela 2026-09-08 三场对比后总结)
  - vec-07 + Angela 用的是 v3 风格骨架(8 章节)
  - vec-02 v4 用了临时骨架(11 章节,带过渡章节)
  - 本模板统一到 12 章节 + 显式可选章节标注
  - 配套 pcc-assessor.md 升 v4.1.0,加"调 template 产报告"硬规则
- 2026-09-19: v4.1.1 翻车复盘章节固化(vec-02 s04 必命中 ✘ 3 → 一票否决 → 需要结构层显式承载关键转折点分析,不能塞进 § 9 主要优势与失守)
  - 章节总数 12 → 13(其中 3 个可选)
  - 新增 [card] ⑫ 翻车复盘 / 关键转折点,触发条件 `N_MUST_FAIL >= 2`
  - 章节内容规范见 § 3 末尾
  - 配套 pcc-assessor.md 升 v4.1.1,KB 判定规则完全不变
- 2026-09-19: v4.1.2 修补说明格式固化(vec-02 s02 用户反馈:⑧ 可打磨 △ 清单的"修补说明"只写补句不写原问全文,模糊指代无锚定)
  - 新增 § 7"⑧ 可打磨 △ 清单修补说明格式规范"(7.1 模板 / 7.2 锚定指代清单 / 7.3 反例 / 7.4 触发源)
  - § 3 章节顺序 ⑧ 描述补 "(修补说明格式见 § 7)"
  - 章节总数不变(仍是 13,其中 3 个可选),仅细化既有卡片列格式
  - 配套 pcc-assessor.md 升 v4.1.2,KB 判定规则完全不变
- 2026-09-20: v4.1.3 § 7 PCC 考官模拟判定 整章删除(vec-07 s01 用户反馈:§ 7 31 行 marker 表 + 能力维度 pass 率表 与 § 4 / § 6 完全重复)
  - 章节总数 13 → 12(其中 2 个可选),所有章节编号重排(⑧→⑦, ⑨→⑧, ⑩→⑨, ⑪→⑩, ⑫→⑪, ⑬→⑫)
  - § 7 删除后,核心内容分散:
    - PCC 通过/不通过综合判定 + 通过概率公式推导 → § 2 整体评级 callout(新增)
    - PCC 实际口径换算(△ = not pass)+ 一票否决检查 → § 3 末尾 callout(新增)
  - v3 vs v4 对比小节(过渡期)从可选章节列表移除(2026-09 起彻底过期)
  - 配套 pcc-assessor.md KB 判定规则完全不变,仅结构层简化