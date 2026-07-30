#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_PROJECT_ROOT = Path("/Users/mindset/Documents/Codex/2026-07-13/nih/work/DailyBrief-upstream")


def resolve_project_root(silent: bool = False) -> Path:
    candidates = []
    env_root = os.environ.get("DAILYBRIEF_CODEX_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(
        [
            Path.cwd(),
            Path.home() / "DailyBrief-Codex",
            Path.home() / "daily-brief",
            DEFAULT_PROJECT_ROOT,
        ]
    )
    for candidate in candidates:
        if is_dailybrief_project(candidate):
            return candidate.resolve()
    if silent:
        return candidates[0].resolve() if candidates else DEFAULT_PROJECT_ROOT
    checked = "\n".join(f"- {p}" for p in candidates)
    raise FileNotFoundError(
        "Could not find a DailyBrief-Codex project. Set DAILYBRIEF_CODEX_ROOT to the repo path.\n"
        f"Checked:\n{checked}"
    )


def is_dailybrief_project(path: Path) -> bool:
    package_json = path / "package.json"
    codex_script = path / "scripts" / "codex-daily.mjs"
    return package_json.exists() and codex_script.exists()


def run_daily() -> None:
    project_root = resolve_project_root()
    env = os.environ.copy()
    env.setdefault("LLM_BACKEND", "claude-cli")
    env.setdefault("CLAUDE_MODEL", "sonnet")
    env.setdefault("REPORT_LOCALE", "zh")
    env.setdefault("REPORT_TZ", "Asia/Shanghai")
    env.setdefault("OUTPUT_MARKDOWN", "true")
    result = subprocess.run(
        ["npm", "run", "codex:daily"],
        cwd=project_root,
        env=env,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def latest_date_dir() -> Path:
    project_root = resolve_project_root()
    reports = project_root / "daily_reports"
    if not reports.exists():
        raise FileNotFoundError(f"No daily_reports directory at {reports}")
    dates = sorted(p for p in reports.iterdir() if p.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", p.name))
    if not dates:
        raise FileNotFoundError(f"No dated reports under {reports}")
    return dates[-1]


def read_report(date_dir: Path) -> dict:
    date = date_dir.name
    json_path = date_dir / f"{date}.json"
    md_path = date_dir / f"{date}.md"
    html_path = date_dir / f"{date}.html"
    if not json_path.exists():
        raise FileNotFoundError(f"Missing {json_path}")
    report = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return {
        "date": date,
        "html_path": str(html_path),
        "markdown_path": str(md_path) if md_path.exists() else None,
        "title": report.get("hero_headline") or report.get("title") or "",
        "overview": report.get("daily_overview") or extract_section(markdown, "今日总览"),
        "tech": brief_titles(report.get("tech_briefs")),
        "finance": brief_titles(report.get("finance_briefs")),
        "politics": brief_titles(report.get("politics_briefs")),
        "market_signal": extract_market_signal(report, markdown),
    }


def brief_titles(items) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and item.get("title")]


def extract_section(markdown: str, heading: str) -> str:
    if not markdown:
        return ""
    pattern = re.compile(rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)", re.M | re.S)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def extract_market_signal(report: dict, markdown: str) -> str:
    trading = report.get("trading")
    if isinstance(trading, dict):
        for key in ("market_overview", "overview", "summary"):
            value = trading.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    section = extract_section(markdown, "市场行情")
    if section:
        return " ".join(section.split())[:260]
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or summarize DailyBrief-Codex.")
    parser.add_argument("--latest", action="store_true", help="Do not run; summarize latest existing report.")
    args = parser.parse_args()
    if not args.latest:
        run_daily()
    summary = read_report(latest_date_dir())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc), "project_root": str(resolve_project_root(silent=True))}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
