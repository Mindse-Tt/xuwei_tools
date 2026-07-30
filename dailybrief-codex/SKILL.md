---
name: dailybrief-codex
description: Run and summarize the user's local DailyBrief-Codex project. Use when the user asks to run DailyBrief, generate today's daily brief/news report, get the AI/finance/politics daily digest, check whether the daily report ran, open or locate the latest report, or debug DailyBrief-Codex failures. Chinese triggers include 日报, 每日简报, DailyBrief, 跑今天日报, 用 Codex 跑日报, 无 API Key 本地日报.
---

# DailyBrief Codex

## Overview

Use this skill to operate a local DailyBrief-Codex fork. Resolve the project root in this order:

```text
DAILYBRIEF_CODEX_ROOT env var
current working directory, if it is a DailyBrief-Codex repo
~/DailyBrief-Codex
~/daily-brief
the user's current installed path on this machine
```

The project is configured for local, API-key-free daily reports:

```text
Codex request -> npm run codex:daily -> local claude CLI backend -> HTML/Markdown/JSON report
```

## Quick Start

Prefer the bundled script:

```bash
python3 /Users/mindset/.codex/skills/dailybrief-codex/scripts/run_daily.py
```

When the DailyBrief-Codex repo is not in a default location, set:

```bash
export DAILYBRIEF_CODEX_ROOT=/absolute/path/to/DailyBrief-Codex
```

For a no-token validation or status-only request, parse the newest existing report:

```bash
python3 /Users/mindset/.codex/skills/dailybrief-codex/scripts/run_daily.py --latest
```

The script prints JSON containing:

- `date`
- `html_path`
- `markdown_path`
- `title`
- `overview`
- grouped headline lists for tech, finance, politics
- `market_signal` when available

## Workflow

1. Run `scripts/run_daily.py` unless the user only asked for status/latest.
2. If the run succeeds, summarize in Chinese:
   - 今日总览
   - 技术动态 3 条
   - 财经要点 3 条
   - 时政观察 2 条
   - 市场信号一句话 when present
   - absolute paths for HTML and Markdown
3. If the run fails, inspect:
   - `logs/daily-YYYY-MM-DD.log`
   - `logs/llm-calls.jsonl`
   - terminal output from the failed script
4. Do not delete `daily_reports/`, `logs/`, `.env.local`, or user output files while debugging.

## Known Notes

- A single source failure, especially LinuxDo behind Cloudflare, is non-fatal if the report still writes.
- The report normally costs about 30k LLM tokens in the local CLI backend, plus a small Codex summarization overhead.
- `codex-cli` is not the report backend right now; Codex orchestrates the run, while the report pipeline uses the verified local `claude-cli` backend.
- The user's DailyBrief-Codex fork is:

```text
https://github.com/Mindse-Tt/DailyBrief-Codex
```

- Standalone skill repository:

```text
https://github.com/Mindse-Tt/DailyBrief-Codex-Skill
```

- Tool collection entry:

```text
https://github.com/Mindse-Tt/xuwei_tools/tree/main/dailybrief-codex
```
