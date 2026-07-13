"""required-sequence checker (SPEC §3.1): ordering obligations within a session.

The canonical shape is "do A before B" — e.g. "run tests before committing".
We compile such a rule into (trigger_event, gate_event) predicates and scan a
single session's ordered event stream: if a trigger (the thing that must be
preceded, e.g. a commit) occurs with no satisfying gate (a passing test run)
earlier in the same session, that is a violation with two receipts — the
offending trigger and the note that no prior gate was seen.

Precision over recall: we only compile the sequence shapes we can recognize
concretely (currently the tests-before-commit family). Everything else stays
uncompiled and is reported as needs-a-richer-checker, never flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from housebroken.check.detect import Receipt
from housebroken.rules.classify import REQUIRED_SEQUENCE, classify
from housebroken.rules.parse import Rule
from housebroken.transcript import Event, ToolCall

SEQ_TESTS_BEFORE_COMMIT = "seq-tests-before-commit"
SEQ_UNCOMPILED = "uncheckable-for-now"

# Recognize a "tests before commit/push" obligation.
_TESTS = re.compile(r"\btest|\bpytest\b|\bunittest\b|\bspec\b", re.I)
_COMMIT = re.compile(r"\bcommit|\bpush\b", re.I)
_BEFORE = re.compile(r"\bbefore\b|\bprior to\b|\bfirst\b", re.I)

# A commit action in a Bash command.
_COMMIT_CMD = re.compile(r"\bgit\s+(commit|push)\b")
# A test-run action in a Bash command.
_TEST_CMD = re.compile(
    r"\b(pytest|unittest|go\s+test|cargo\s+test|npm\s+test|npm\s+run\s+test|"
    r"jest|vitest|python\s+-m\s+unittest|make\s+test|tox)\b"
)


@dataclass(frozen=True, slots=True)
class CompiledSequence:
    rule: Rule
    check_class: str  # SEQ_TESTS_BEFORE_COMMIT | SEQ_UNCOMPILED

    @property
    def compiled(self) -> bool:
        return self.check_class == SEQ_TESTS_BEFORE_COMMIT


def compile_sequence_rule(rule: Rule) -> CompiledSequence:
    if classify(rule) != REQUIRED_SEQUENCE:
        return CompiledSequence(rule, SEQ_UNCOMPILED)
    t = rule.text
    if _TESTS.search(t) and _COMMIT.search(t) and _BEFORE.search(t):
        return CompiledSequence(rule, SEQ_TESTS_BEFORE_COMMIT)
    return CompiledSequence(rule, SEQ_UNCOMPILED)


def compile_sequence_rules(rules) -> tuple[CompiledSequence, ...]:
    return tuple(compile_sequence_rule(r) for r in rules)


class SequenceChecker:
    """Per-session ordering checker.

    Feed one session's events in order via ``observe``; call ``finish_session``
    at the session boundary to reset ordering state. ``results`` aggregates
    receipts across sessions.
    """

    def __init__(self, checks: tuple[CompiledSequence, ...] | list[CompiledSequence]):
        self._checks = tuple(c for c in checks if c.compiled)
        self._all = tuple(checks)
        self._receipts: dict[str, list[Receipt]] = {c.rule.id: [] for c in self._all}
        self._seen_passing_test = False  # within the current session

    def observe(self, ev: Event) -> None:
        if not isinstance(ev, ToolCall):
            return
        cmd = ev.command()
        if not cmd:
            return
        if _TEST_CMD.search(cmd):
            # We cannot see exit codes deterministically; treat a test-run as a
            # satisfied gate. (The judge tier could refine pass/fail; precision-first
            # here means we do not fabricate a failing-run claim.)
            self._seen_passing_test = True
            return
        if _COMMIT_CMD.search(cmd) and not self._seen_passing_test:
            for c in self._checks:
                self._receipts[c.rule.id].append(
                    Receipt(
                        session_file=ev.file,
                        line_no=ev.line_no,
                        timestamp=ev.timestamp,
                        span=f"commit with no prior test run in session: {cmd[:120]}",
                        rule_text=c.rule.text,
                    )
                )

    def finish_session(self) -> None:
        self._seen_passing_test = False

    def receipts_for(self, rule_id: str) -> tuple[Receipt, ...]:
        return tuple(self._receipts.get(rule_id, ()))

    def compiled_rule_ids(self) -> frozenset[str]:
        return frozenset(c.rule.id for c in self._checks)
