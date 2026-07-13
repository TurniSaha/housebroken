"""Discovery: locate rules files and session transcripts.

Defaults target a standard Claude Code layout under ``--claude-dir`` (default
``~/.claude``):

  rules:       <claude-dir>/CLAUDE.md  and  <claude-dir>/rules/**/*.md
  transcripts: <claude-dir>/projects/*/*.jsonl

Explicit ``--rules`` / ``--transcripts`` paths (files or directories) override
the auto-discovery for that category. Transcripts are returned newest-first and
filtered to a trailing ``--days`` window by file mtime.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Discovery:
    claude_dir: Path
    rules_files: tuple[Path, ...]
    transcripts: tuple[Path, ...]  # newest-first, already windowed


def default_claude_dir(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def _collect_md(root: Path) -> list[Path]:
    """All markdown files under root (recursive), sorted for stable order."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def find_rules_files(claude_dir: Path, explicit: list[str] | None = None) -> tuple[Path, ...]:
    if explicit:
        out: list[Path] = []
        for item in explicit:
            p = Path(item).expanduser()
            if p.is_dir():
                out.extend(_collect_md(p))
            elif p.is_file():
                out.append(p)
        # dedupe preserving order
        seen: set[Path] = set()
        uniq = []
        for p in out:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                uniq.append(p)
        return tuple(uniq)

    out = []
    top = claude_dir / "CLAUDE.md"
    if top.is_file():
        out.append(top)
    out.extend(_collect_md(claude_dir / "rules"))
    return tuple(out)


def _collect_jsonl(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.glob("*/*.jsonl") if p.is_file()]


def find_transcripts(
    claude_dir: Path,
    explicit: list[str] | None = None,
    days: int = 14,
    now: float | None = None,
) -> tuple[Path, ...]:
    if explicit:
        paths: list[Path] = []
        for item in explicit:
            p = Path(item).expanduser()
            if p.is_dir():
                paths.extend(q for q in p.rglob("*.jsonl") if q.is_file())
            elif p.is_file():
                paths.append(p)
    else:
        paths = _collect_jsonl(claude_dir / "projects")

    now = time.time() if now is None else now
    cutoff = now - days * 86400 if days and days > 0 else None

    windowed = []
    for p in paths:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if cutoff is not None and mtime < cutoff:
            continue
        windowed.append((mtime, p))

    windowed.sort(key=lambda t: t[0], reverse=True)
    return tuple(p for _, p in windowed)


def discover(
    claude_dir: str | None = None,
    rules: list[str] | None = None,
    transcripts: list[str] | None = None,
    days: int = 14,
) -> Discovery:
    cdir = default_claude_dir(claude_dir)
    return Discovery(
        claude_dir=cdir,
        rules_files=find_rules_files(cdir, rules),
        transcripts=find_transcripts(cdir, transcripts, days=days),
    )
