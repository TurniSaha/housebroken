"""Applicability engine (SPEC §3.1 P3): asleep vs. never-violated.

A rule that never came up in a session did not "pass" — it was irrelevant. This
module compiles a lightweight applicability trigger for each rule and evaluates,
per session, whether the rule's subject matter was ever in play.

  applicable-in-session  = the trigger fired on at least one event of the session
  PASSED  = applicable in >=1 session AND no violation anywhere
  ASLEEP  = applicable in 0 sessions across the window

Triggers are deliberately broad (recall-oriented): being "applicable" only
gates whether we grade a rule as PASSED vs ASLEEP; a violation still requires a
precise receipt from a checker. Over-triggering costs a rule its ASLEEP status,
not a false accusation, so the asymmetry is safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from housebroken.rules.parse import Rule
from housebroken.transcript import AssistantMsg, Event, ToolCall, UserMsg

# Topic keyword -> the event evidence that makes a rule "in play".
_GIT_RE = re.compile(r"\bgit\b|\bcommit|\bpush|\bbranch|\bmerg|\brebase", re.I)
_TEST_RE = re.compile(r"\btest|\bpytest\b|\bunittest\b|\bcoverage\b|\bspec\b", re.I)
_BUILD_RE = re.compile(r"\bbuild\b|\bcompile\b|\bmake\b|\bcargo\b|\bnpm\b|\btsc\b", re.I)
_SECRET_RE = re.compile(r"\bsecret|\btoken|\bpassword|\bcredential|\bapi[- ]?key|\benv\b", re.I)
_SQL_RE = re.compile(r"\bsql\b|\bquery|\bselect\b|\binsert\b|\bdatabase\b|\btable\b", re.I)
_DEP_RE = re.compile(r"\bdependenc|\bpackage|\bnpm install|\bpip install|\bimport\b|\bcrate\b", re.I)


@dataclass(frozen=True, slots=True)
class Trigger:
    """When does a rule's subject matter count as 'in play' for a session?"""

    tool_names: frozenset[str]  # applicable if any of these tools was called
    command_re: re.Pattern | None  # applicable if a Bash command matches
    text_re: re.Pattern | None  # applicable if any assistant/user text matches
    always: bool = False  # rule applies to every session (universal disposition)

    def fires(self, ev: Event) -> bool:
        if self.always:
            return True
        if isinstance(ev, ToolCall):
            if ev.name in self.tool_names:
                return True
            if self.command_re is not None:
                cmd = ev.command()
                if cmd and self.command_re.search(cmd):
                    return True
        elif isinstance(ev, (AssistantMsg, UserMsg)):
            if self.text_re is not None and self.text_re.search(ev.text):
                return True
        return False


_EMPTY = frozenset()


def compile_trigger(rule: Rule) -> Trigger:
    """Derive a broad applicability trigger from a rule's text.

    Universal dispositions (no concrete topic) get ``always=True`` so they are
    never scored ASLEEP — a rule like "prefer simplicity" is always in play.
    """
    text = rule.text

    topic_res: list[re.Pattern] = []
    tools: set[str] = set()
    cmd_res: list[re.Pattern] = []

    if _GIT_RE.search(text):
        topic_res.append(_GIT_RE)
        cmd_res.append(re.compile(r"\bgit\b"))
    if _TEST_RE.search(text):
        topic_res.append(_TEST_RE)
        cmd_res.append(re.compile(r"\btest|\bpytest\b|\bunittest\b"))
    if _BUILD_RE.search(text):
        topic_res.append(_BUILD_RE)
        cmd_res.append(_BUILD_RE)
    if _SECRET_RE.search(text):
        topic_res.append(_SECRET_RE)
    if _SQL_RE.search(text):
        topic_res.append(_SQL_RE)
    if _DEP_RE.search(text):
        topic_res.append(_DEP_RE)
        cmd_res.append(re.compile(r"\b(npm|pip|cargo|yarn|pnpm)\b"))

    # File-touch tools imply a rule about editing/writing code is in play.
    _CODE_RE = re.compile(r"\bcode\b|\bfile\b|\bfunction\b|\bmodule\b|\bnest|\bmutat", re.I)
    if _CODE_RE.search(text):
        tools |= {"Edit", "Write", "MultiEdit", "NotebookEdit"}
        topic_res.append(_CODE_RE)

    if not topic_res and not tools:
        # No concrete topic hook -> universal disposition, always applicable.
        return Trigger(_EMPTY, None, None, always=True)

    combined_text = (
        re.compile("|".join(f"(?:{r.pattern})" for r in topic_res), re.I)
        if topic_res
        else None
    )
    combined_cmd = (
        re.compile("|".join(f"(?:{r.pattern})" for r in cmd_res), re.I)
        if cmd_res
        else None
    )
    return Trigger(frozenset(tools), combined_cmd, combined_text, always=False)
