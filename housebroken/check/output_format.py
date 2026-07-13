"""output-format checker (SPEC §3.1): constraints on produced artifacts.

M2 compiles the two highest-value, precision-safe format rules:

  conventional-commits  — a rule demanding conventional commit messages is
    checked against the -m argument of `git commit` calls. A commit message
    that does not start with a conventional type prefix (feat/fix/docs/...)
    is a violation, receipt = the offending message.

  no-emoji-output — delegated to the forbidden-action emoji check (owned by
    detect.py); not re-implemented here to avoid double-counting.

Everything else in the output-format class stays uncompiled (needs the judge or
a richer artifact checker) and is reported honestly, never flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from housebroken.check.detect import Receipt
from housebroken.rules.classify import OUTPUT_FORMAT, classify
from housebroken.rules.parse import Rule
from housebroken.transcript import Event, ToolCall

FMT_CONVENTIONAL_COMMITS = "fmt-conventional-commits"
FMT_UNCOMPILED = "uncheckable-for-now"

_CONVENTIONAL_RULE = re.compile(r"conventional commit", re.I)
# Conventional commit prefix: type(scope)!: subject
_CONV_PREFIX = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^)]+\))?!?:\s",
)
# Extract the -m / --message argument of a git commit command.
_COMMIT_MSG = re.compile(
    r"git\s+commit\b[^\n]*?\s(?:-m|--message)\s*(?:=\s*)?"
    r"(?:\"([^\"]*)\"|'([^']*)')"
)
_IS_COMMIT = re.compile(r"\bgit\s+commit\b")


@dataclass(frozen=True, slots=True)
class CompiledFormat:
    rule: Rule
    check_class: str

    @property
    def compiled(self) -> bool:
        return self.check_class == FMT_CONVENTIONAL_COMMITS


def compile_format_rule(rule: Rule) -> CompiledFormat:
    if classify(rule) != OUTPUT_FORMAT:
        return CompiledFormat(rule, FMT_UNCOMPILED)
    if _CONVENTIONAL_RULE.search(rule.text):
        return CompiledFormat(rule, FMT_CONVENTIONAL_COMMITS)
    return CompiledFormat(rule, FMT_UNCOMPILED)


def compile_format_rules(rules) -> tuple[CompiledFormat, ...]:
    return tuple(compile_format_rule(r) for r in rules)


def _commit_messages(cmd: str) -> list[str]:
    out = []
    for m in _COMMIT_MSG.finditer(cmd):
        msg = m.group(1) if m.group(1) is not None else m.group(2)
        if msg is not None:
            out.append(msg)
    return out


class OutputFormatChecker:
    """Scans commit messages for conventional-commit adherence."""

    def __init__(self, checks: tuple[CompiledFormat, ...] | list[CompiledFormat]):
        self._checks = tuple(c for c in checks if c.compiled)
        self._all = tuple(checks)
        self._receipts: dict[str, list[Receipt]] = {c.rule.id: [] for c in self._all}

    def observe(self, ev: Event) -> None:
        if not self._checks or not isinstance(ev, ToolCall):
            return
        cmd = ev.command()
        if not cmd or not _IS_COMMIT.search(cmd):
            return
        for msg in _commit_messages(cmd):
            if not _CONV_PREFIX.match(msg.strip()):
                for c in self._checks:
                    self._receipts[c.rule.id].append(
                        Receipt(
                            session_file=ev.file,
                            line_no=ev.line_no,
                            timestamp=ev.timestamp,
                            span=f"non-conventional commit message: {msg[:100]!r}",
                            rule_text=c.rule.text,
                        )
                    )

    def receipts_for(self, rule_id: str) -> tuple[Receipt, ...]:
        return tuple(self._receipts.get(rule_id, ()))

    def compiled_rule_ids(self) -> frozenset[str]:
        return frozenset(c.rule.id for c in self._checks)
