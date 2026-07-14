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
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|")
_INLINE_EMPH = re.compile(r"[*_`]+")
_CHECKBOX = re.compile(r"^\[[ xX]\]\s*")

# A bold/emphasized leading label followed by a colon: `**Approve**: ...`,
# `_note_: ...`. These are definition/label rows, not directives.
_LABEL_BULLET = re.compile(r"^\s*[*_`]{1,3}[^*_`]{1,40}[*_`]{1,3}\s*:\s+\S")
# A leading `token` — description / token — description glossary/legend entry
# (em dash or " - " after a short lead-in, describing a thing rather than
# commanding an action).
_GLOSSARY_DASH = re.compile(r"^\s*[`*_]?\S[^—]{0,40}?[`*_]?\s+—\s+\S")

# Imperative signal: a leading verb, a modal/negation, or an ALL-CAPS directive.
_IMPERATIVE_LEADS = frozenset(
    """always never no do don't dont use avoid prefer ensure make keep write run
    add remove delete check verify validate handle fix commit push plan default
    skip stop find search fail follow require include exclude enable disable
    treat trust update act be provide return name split extract organize
    document test refactor review ask tell answer respond only when before after
    match lead read call minimize maximize enable disable rotate reject accept
    parse wrap store cache log limit scope define declare implement enforce
    sanitize escape reserve pin bind""".split()
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


def _starts_with_verb(text: str) -> bool:
    """The FIRST word is an imperative lead verb. Stricter than _looks_imperative
    (no anywhere-in-line modal scan) — used where a mid-sentence "always/should"
    would be a false signal (e.g. glossary detection: "... (always applied)")."""
    words = text.split()
    if not words:
        return False
    return words[0].strip(".,:;`*_").lower() in _IMPERATIVE_LEADS


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


def _is_rule_shaped(text: str, candidate: str = "") -> bool:
    """Reject fragments that are not actually rules.

    Filters the dominant parser false-positives: list/section intros that end in
    a colon, path/config scaffolding lines, placeholder-template fragments,
    definition/label rows (`**Approve**: ...`), and glossary/legend entries
    (`` `common/` — language-agnostic principles``). A real rule is a
    sentence-ish directive, not a label, a definition, or a file path.

    ``candidate`` is the pre-cleaned line (emphasis markers intact); when given
    it lets us detect bold-label and glossary shapes that vanish after cleaning.
    """
    stripped = text.rstrip()
    # List/section intro ("MANDATORY review triggers:", "Default flow:").
    if stripped.endswith(":"):
        return False
    # Definition/label row: `**Approve**: No CRITICAL...` -> "Approve: ...".
    if candidate and _LABEL_BULLET.match(candidate):
        return False
    # Glossary/legend entry: `` `common/` — language-agnostic principles``.
    # Only when the pre-dash lead-in is a NOUN/label, not an imperative — a real
    # rule ("Always use parameterized queries — never ...") uses the dash for
    # emphasis and must be kept.
    if candidate and _GLOSSARY_DASH.match(candidate):
        parts = re.split(r"\s+—\s+", _clean(candidate), maxsplit=1)
        # Glossary only if NEITHER side STARTS with a verb. "Minimize ... —
        # prefer ..." is a rule; "`common/` — language-agnostic principles
        # (always applied)" is a legend (the mid-phrase "always" must not count).
        if not any(_starts_with_verb(p) for p in parts):
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


# Headings whose numbered lists are how-to procedures, not rule catalogs. A
# numbered item under one of these is a step ("Run test - it should FAIL"),
# not a standalone gradeable rule.
_PROCEDURE_HEADING = re.compile(
    r"\b(workflow|protocol|process|steps?|procedure|how to|response|"
    r"troubleshoot|checklist|flow|sequence|cycle|loop)\b",
    re.IGNORECASE,
)


def _is_procedure_substep(raw_line: str, heading_path: tuple[str, ...],
                          after_colon_intro: bool) -> bool:
    """True if an ordered-list item is a procedure step, not a rule.

    Signals: the item is numbered (checked against the RAW line, before the list
    marker is stripped) AND (it sits under a procedure-ish heading, or it
    directly follows a ``...:`` intro line that opened the list). Terse
    parenthetical/dashed step narration ("Run test - it should FAIL",
    "Write minimal implementation (GREEN)") is the target.
    """
    if not _ORDERED.match(raw_line):
        return False
    # Only the unambiguous case: a numbered item directly under a "...:" intro
    # that opened the list. (A procedure-ish HEADING alone is too broad — real
    # rule catalogs live under "Workflow"/"Process" headings too.)
    return after_colon_intro


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
    after_colon_intro = False  # previous non-blank line was a "...:" list intro
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
            after_colon_intro = False
            continue

        if _TABLE_ROW.match(raw) or raw.lstrip().startswith(">"):
            continue

        if not raw.strip():
            continue  # blank line: keep after_colon_intro so intro+blank+list works

        bm = _BULLET.match(raw)
        candidate = bm.group(1) if bm else raw.strip()
        text = _clean(candidate)
        raw_text = _semi_clean(candidate)

        # A non-list line ending in ":" opens a procedure/enumeration; its
        # numbered items are steps, not rules. Track it, then move on.
        if not bm and text.rstrip().endswith(":"):
            after_colon_intro = True
            continue

        if not text or len(text) < 4:
            after_colon_intro = False
            continue

        # Drop non-rule fragments: list/section intros ("MANDATORY triggers:"),
        # path/config lines, placeholder scaffolding, definition/label rows, and
        # glossary entries. These are the dominant parser false-positives.
        if not _is_rule_shaped(text, candidate):
            continue

        # Numbered how-to steps are procedure narration, not gradeable rules.
        if _is_procedure_substep(raw, tuple(t for _, t in heading_stack),
                                 after_colon_intro):
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
