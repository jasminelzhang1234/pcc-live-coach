# .claude/agents/ — Claude Code subagent 入口(源)

本目录存放 Claude Code subagent 定义,被 Claude Code IDE/CLI 自动加载。
在 Claude Code 里可直接这样调用:

```
> 使用 pcc-assessor 全评 transcripts/2025-08-20-session-01.md
> 用 pcc-coachee 开始陪练 vec-08
```

## 文件清单

| 文件 | 角色 | 镜像 |
|---|---|---|
| `pcc-assessor.md` | PCC 表现评估考官 | [.github/agents/pcc-assessor.agent.md](../../.github/agents/pcc-assessor.agent.md) |
| `pcc-coachee.md` | PCC 教练陪练客户 | [.github/agents/pcc-coachee.agent.md](../../.github/agents/pcc-coachee.agent.md) |
| `pcc-tracker.md` | 训练追踪 + 派单 | [.github/agents/pcc-tracker.agent.md](../../.github/agents/pcc-tracker.agent.md) |

## 双份策略

`.github/agents/` 与 `.claude/agents/` 内容一致,只有两处差异:

| 维度 | `.github/agents/` | `.claude/agents/` |
|---|---|---|
| 文件后缀 | `<name>.agent.md` | `<name>.md` |
| 工具名 | `['read', 'glob']` | `['Read', 'Glob']` |
| 消费者 | GitHub Copilot VS Code | Claude Code IDE/CLI |

## 单一事实源 + 自动同步

**.claude/agents/ 是 single source of truth**(2026-09-11 起,v4 隐私脱敏工作流确立)。

本目录文件由 [scripts/sync_agents.py](../../scripts/sync_agents.py) 镜像到 `.github/agents/`。
**不要手动修改 `.github/agents/*.agent.md`** —— 改完会在下一次同步时被覆盖。

```bash
# 重新生成 .github/agents/(从 .claude 推)
python3 scripts/sync_agents.py

# 仅检查是否漂移(适合 pre-commit / CI)
python3 scripts/sync_agents.py --check
```

## 工作流

1. 改 `.claude/agents/<name>.md`(源)
2. 跑 `python3 scripts/sync_agents.py`
3. 提交两个目录的变更

## 未来方向:MCP 化

当前双份文件是临时方案。下一轮迭代会把两个 agent 包装成一个 MCP server,
这样 Claude Code 和 GitHub Copilot 都通过 MCP 消费同一份代码,
不再需要同步脚本。详见项目根目录的 plan 文档(待起草)。
