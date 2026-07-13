"""Markdown -> tuple of frozen Rule objects.

A rule is an imperative bullet or a short imperative line under a heading scope.
This is deliberately an 80% parser, not a markdown AST: bullets and standalone
imperative lines are the common shape of real CLAUDE.md / rules files.

We capture, per rule:
  - a stable id (hash of source-relative path + normalized text)
  - source file + 1-based line number
  - heading path (the stack of ``#`` headings above the line)
  - raw text (the line, list marker and inline emphasis stripped)

Skipped: fenced code blocks, tables, blockquotes, headings themselves, and
lines with no imperative signal (kept short to avoid turning prose into rules).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|")
_INLINE_EMPH = re.compile(r"[*_`]+")
_CHECKBOX = re.compile(r"^\[[ xX]\]\s*")

# Imperative signal: a leading verb, a modal/negation, or an ALL-CAPS directive.
_IMPERATIVE_LEADS = frozenset(
    """always never no do don't dont use avoid prefer ensure make keep write run
    add remove delete check verify validate handle fix commit push plan default
    skip stop find search fail follow require include exclude enable disable
    treat trust update act be provide return name split extract organize
    document test refactor review ask tell answer respond only when before after
    match lead read call""".split()
)
_MODAL = re.compile(
    r"\b(must|should|shall|never|always|do not|don't|no longer|avoid|ensure|"
    r"require[sd]?|prefer)\b",
    re.IGNORECASE,
)
_ALLCAPS_DIRECTIVE = re.compile(r"\b[A-Z]{3,}\b")


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    source: str  # absolute path
    line_no: int  # 1-based
    heading_path: tuple[str, ...]
    text: str  # cleaned rule text (emphasis/backticks stripped, for display)
    raw_text: str = ""  # bullet-stripped but backticks preserved (for token extraction)

    @property
    def scope(self) -> str:
        return " › ".join(self.heading_path) if self.heading_path else ""


def _clean(text: str) -> str:
    text = _CHECKBOX.sub("", text.strip())
    text = _INLINE_EMPH.sub("", text)
    return text.strip()


def _semi_clean(text: str) -> str:
    """Strip checkbox/list residue but KEEP backticks (needed for literal tokens)."""
    return _CHECKBOX.sub("", text.strip()).strip()


def _looks_imperative(text: str) -> bool:
    if not text:
        return False
    words = text.split()
    if not words:
        return False
    first = words[0].strip(".,:;").lower()
    if first in _IMPERATIVE_LEADS:
        return True
    if _MODAL.search(text):
        return True
    # An ALL-CAPS directive word early in a short line ("ALWAYS ...", "MANDATORY").
    if len(words) <= 20 and _ALLCAPS_DIRECTIVE.search(" ".join(words[:4])):
        return True
    return False


def _is_rule_shaped(text: str) -> bool:
    """Reject fragments that are not actually rules.

    Filters the dominant parser false-positives: list/section intros that end in
    a colon, path/config scaffolding lines, and placeholder-template fragments.
    A real rule is a sentence-ish directive, not a label or a file path.
    """
    stripped = text.rstrip()
    # List/section intro ("MANDATORY review triggers:", "Default flow:").
    if stripped.endswith(":"):
        return False
    # Placeholder-template scaffolding ("owner/<name>", "set default branch ...").
    if "<name>" in text or "<" in text and ">" in text and "/" in text:
        return False
    # A lone path or slash-heavy config fragment (few words, mostly a path).
    words = text.split()
    if len(words) <= 6 and text.count("/") >= 2:
        return False
    # A single ALL-CAPS-or-Titlecase label with no verb ("Default flow", "Approve").
    if len(words) <= 3 and not any(w.islower() for w in words):
        return False
    return True


def _rule_id(source: str, text: str) -> str:
    basename = Path(source).name
    h = hashlib.sha1(f"{basename}::{text.lower()}".encode("utf-8")).hexdigest()
    return h[:12]


def parse_file(path: str | Path) -> tuple[Rule, ...]:
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ()

    rules: list[Rule] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    in_fence = False
    fpath = str(p)

    for idx, raw in enumerate(lines, start=1):
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        hm = _HEADING.match(raw)
        if hm:
            level = len(hm.group(1))
            title = _clean(hm.group(2))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            continue

        if _TABLE_ROW.match(raw) or raw.lstrip().startswith(">"):
            continue

        bm = _BULLET.match(raw)
        candidate = bm.group(1) if bm else raw.strip()
        text = _clean(candidate)
        raw_text = _semi_clean(candidate)
        if not text or len(text) < 4:
            continue

        # Drop non-rule fragments: list/section intros ("MANDATORY triggers:"),
        # path/config lines, and placeholder-heavy scaffolding. These are the
        # dominant parser false-positives and they pollute the class stats.
        if not _is_rule_shaped(text):
            continue

        # Require an imperative signal (both bullets and bare lines) to avoid
        # slurping prose paragraphs and enumerations.
        if not _looks_imperative(text):
            continue

        heading_path = tuple(t for _, t in heading_stack)
        rules.append(
            Rule(
                id=_rule_id(fpath, text),
                source=fpath,
                line_no=idx,
                heading_path=heading_path,
                text=text,
                raw_text=raw_text,
            )
        )

    return tuple(rules)


def parse_files(paths: list[str] | tuple[str, ...] | list[Path]) -> tuple[Rule, ...]:
    out: list[Rule] = []
    seen: set[str] = set()
    for path in paths:
        for rule in parse_file(path):
            if rule.id in seen:
                continue
            seen.add(rule.id)
            out.append(rule)
    return tuple(out)
