# DailyBrief-Codex Skill

> 用 Codex 跑本地每日简报：默认不需要 LLM API Key，生成 HTML / Markdown / JSON，并把日报归档到桌面。

这是 [DailyBrief-Codex](https://github.com/Mindse-Tt/DailyBrief-Codex) 的 Skill 入口版本，适合放在 `xuwei_tools` 里作为一个可复用工具调用。

## 它和主项目是什么关系

| 位置 | 作用 |
|---|---|
| `Mindse-Tt/DailyBrief-Codex` | 完整项目：抓取、摘要、渲染、归档、日志、README 展示 |
| `xuwei_tools/dailybrief-codex` | Skill 包：告诉 Codex 怎么找到主项目、怎么运行、怎么验收和排错 |

简单说：**它们是一回事的两个层级**。主项目负责真正生成日报；这个目录负责把“怎么让 Codex 稳定调用它”封装成 Skill。

## 包含内容

```text
dailybrief-codex/
  SKILL.md                 # Codex 使用说明和触发规则
  agents/openai.yaml       # Agent 配置
  scripts/run_daily.py     # 运行 / 读取最新日报的辅助脚本
```

## 使用方式

把这个目录复制到 Codex skills 目录：

```bash
mkdir -p ~/.codex/skills
cp -R dailybrief-codex ~/.codex/skills/
```

如果主项目不在默认位置，设置：

```bash
export DAILYBRIEF_CODEX_ROOT=/absolute/path/to/DailyBrief-Codex
```

然后对 Codex 说：

```text
用 dailybrief-codex 跑今天日报并总结给我。
```

## 输出

日报会保存在主项目内：

```text
daily_reports/YYYY-MM-DD/YYYY-MM-DD.html
daily_reports/YYYY-MM-DD/YYYY-MM-DD.md
daily_reports/YYYY-MM-DD/YYYY-MM-DD.json
```

也会复制到桌面归档：

```text
~/Desktop/DailyBrief每日存档/YYYY-MM-DD.html
~/Desktop/DailyBrief每日存档/YYYY-MM-DD.md
~/Desktop/DailyBrief每日存档/YYYY-MM-DD.json
```

## 适合什么时候用

- 想每天让 Codex 帮你跑一份本地日报
- 想保留 HTML / Markdown / JSON 三种格式
- 想把日报归档到桌面，像 `AIHOT每日存档` 一样长期保存
- 想默认走本地 CLI 后端，不再单独配置 LLM API Key

