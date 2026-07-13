"""housebroken CLI.

Default (no subcommand): discover rules + transcripts under ~/.claude, parse
and classify rules, replay transcripts per session through the deterministic
checkers + applicability engine, and print the report card. Exit 0 on success.
"""

from __future__ import annotations

import argparse
import sys

from housebroken import __version__
from housebroken.check.judge import (
    DEFAULT_JUDGE_BUDGET,
    DEFAULT_JUDGE_WORKERS,
    cli_available,
)
from housebroken.demo import run_demo
from housebroken.discover import discover
from housebroken.report import render_json, render_markdown, render_text
from housebroken.rules.parse import parse_files
from housebroken.score import scan


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="housebroken",
        description="Grade your AI agent against your own CLAUDE.md, with receipts.",
    )
    p.add_argument("--version", action="version", version=f"housebroken {__version__}")
    p.add_argument(
        "command",
        nargs="?",
        default="scan",
        choices=("scan", "demo"),
        help="'scan' (default) grades your real ~/.claude; 'demo' runs a bundled "
             "synthetic showcase (no CLAUDE.md or claude CLI needed)",
    )
    p.add_argument(
        "--claude-dir",
        metavar="DIR",
        help="root of the Claude Code config dir (default: ~/.claude)",
    )
    p.add_argument(
        "--rules",
        action="append",
        metavar="PATH",
        help="explicit rules file or dir (repeatable); overrides auto-discovery",
    )
    p.add_argument(
        "--transcripts",
        action="append",
        metavar="PATH",
        help="explicit transcript file or dir (repeatable); overrides auto-discovery",
    )
    p.add_argument(
        "--days",
        type=int,
        default=14,
        metavar="N",
        help="only replay transcripts modified in the last N days (default: 14)",
    )
    p.add_argument(
        "--format",
        choices=("text", "md", "json"),
        default="text",
        help="report format (default: text)",
    )
    p.add_argument(
        "--no-judge",
        action="store_true",
        help="skip the Tier-2 claude -p judge for behavioral-prose rules",
    )
    p.add_argument(
        "--judge-budget",
        type=int,
        default=DEFAULT_JUDGE_BUDGET,
        metavar="N",
        help=f"max live judge calls per run (cache hits are free) "
             f"(default: {DEFAULT_JUDGE_BUDGET})",
    )
    p.add_argument(
        "--judge-workers",
        type=int,
        default=DEFAULT_JUDGE_WORKERS,
        metavar="N",
        help=f"concurrent judge calls (default: {DEFAULT_JUDGE_WORKERS})",
    )
    p.add_argument(
        "--exclude-project",
        metavar="PATH",
        help="drop transcripts whose project cwd is under PATH from judge span "
             "selection (avoids self-referential meta-discussion)",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color in the text report",
    )
    return p


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "demo":
        sys.stdout.write(
            run_demo(fmt=args.format, use_color=not args.no_color)
        )
        return 0

    disc = discover(
        claude_dir=args.claude_dir,
        rules=args.rules,
        transcripts=args.transcripts,
        days=args.days,
    )

    if not disc.rules_files:
        print(
            "housebroken: no rules files found. Point at one with --rules PATH "
            "or check --claude-dir.",
            file=sys.stderr,
        )
        return 0

    rules = parse_files([str(p) for p in disc.rules_files])

    use_judge = not args.no_judge
    if use_judge and not cli_available():
        print(
            "housebroken: `claude` CLI not found on PATH — skipping the Tier-2 judge. "
            "Behavioral-prose rules will show NEEDS-JUDGE. Install the Claude Code "
            "CLI or pass --no-judge to silence this.",
            file=sys.stderr,
        )
        use_judge = False

    result = scan(
        rules,
        disc.transcripts,
        rules_files=len(disc.rules_files),
        use_judge=use_judge,
        judge_budget=args.judge_budget,
        judge_workers=args.judge_workers,
        exclude_project=args.exclude_project,
    )

    if args.format == "json":
        sys.stdout.write(render_json(result))
    elif args.format == "md":
        sys.stdout.write(render_markdown(result))
    else:
        sys.stdout.write(render_text(result, use_color=not args.no_color))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
