---
name: pcc-assessor-html-template
description: |
  pcc-assessor HTML 报告骨架模板(v4.1+ 硬规则)。固化 12 章节顺序 + CSS 风格
  + 占位符语法 + 可选章节显式标注;让 pcc-assessor agent 每次只填值不动结构。
type: template
spec_version: v4.1.0
last_updated: 2026-09-14
---

# pcc-assessor HTML 报告骨架模板

## 1. 用途与硬规则

pcc-assessor agent 在生成 HTML 报告时,**必须**按本模板的 12 章节顺序 + 占位符语法产出。不允许:
- 重排章节顺序
- 改变章节命名
- 自由发挥 CSS 风格
- 跳过任一"必有"章节
- 保留"v3 vs v4 对比"等过渡章节(那是 v4 升级产物,不是常驻章节)

允许:
- 可选章节(§ 11 v3 vs v4 对比)按显式条件出现(IF vN == "v4" 一次性展示)
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

## 3. 章节顺序(固定 12 个)

```
[header]                   ① KPI 行(7 个卡片)
[card] 元信息               ② meta-grid + 整体评级 callout
[card] 必命中项检查         ③ 7 条 must-marker 大表(注:表头写"7 条",不要写"6 条")
[card] 37 条 markers 全表   ④ 按能力分组(能力 3/4/5/6/7/8),保留 rowspan 分组
[card] 结构性降档规则       ⑤ 5 条 vec-08 三方校准规则表
[grid-2]                   ⑥ 能力维度分布表 + 雷达图
                            (空右侧)判定构成柱状图
[card] PCC 考官模拟判定    ⑦ PCC 实际口径换算表(31 条)+ 能力 pass 率 + 通过概率
[card] 可打磨 △ 清单       ⑧ 8 条 △ 按标点/一句/流程/思维 4 级分类
[card] 主要优势与失守      ⑨ grid-2 双列 ✓优势 / ✗失守
[card] 下一步练习建议       ⑩ P0/P1/P2/P3 优先级表
[card] 跨场趋势           ⑪ 可选 IF persona_id 已存在 ≥ 2 场
[footer]                   ⑫ 数据来源 + vN + 生成日期
```

**章节命名固定**(h2 标题文字必须字面一致):
- `对话元信息` / `必命中项检查(7 条,任一 ✘ = 一票否决)` / `37 条 Markers 全表`
- `结构性降档规则命中情况` / `能力维度分布` / `PCC 考官模拟判定`
- `可打磨 △ 清单` / `主要优势与失守` / `下一步练习建议`
- `跨场趋势({persona_id} · {start_date} → {end_date})` [可选]
- `footer`: `数据来源 + KB 版本 v{N} + pcc-assessor(Claude) + 生成日期`

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

模板里只有 2 个章节是可选的,其他必须出现:

```
<!-- IF persona_id 已存在 ≥ 2 场(查 tracker.csv / tracker-real-sessions.csv) -->
[card] 跨场趋势
<!-- END IF -->

<!-- IF vN == "v4" AND 这是 v4 启用后首月(2026-09 → 2026-10) -->
[card] v3 vs v4 对比小节  ← 仅过渡期显示,过期后必须移除
<!-- END IF -->
```

**严禁保留**:`v3 vs v4 对比小节` 在 v4.1+ 是过期产物。2026-11 起必须从所有报告移除。

## 7. 历史

- 2026-09-14: 初版(vec-02 s01 / vec-07 s01 / Angela 2026-09-08 三场对比后总结)
  - vec-07 + Angela 用的是 v3 风格骨架(8 章节)
  - vec-02 v4 用了临时骨架(11 章节,带过渡章节)
  - 本模板统一到 12 章节 + 显式可选章节标注
  - 配套 pcc-assessor.md 升 v4.1.0,加"调 template 产报告"硬规则