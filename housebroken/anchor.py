"""Anchor-event span selection for the Tier-2 judge.

The judge is only as good as the spans it sees. Selecting assistant *prose* by
topic-keyword match feeds the judge narration and status summaries — and, on a
project that talks about rules/judging, meta-discussion that keyword-matches
everything. The judge then answers "unclear" every time.

Fix: anchor candidate spans to CONCRETE EVENTS. For each behavioral-prose rule
we derive an anchor class — the kind of tool activity that would show the rule
being followed or broken (a code edit, a test run, a deploy command, …). A
candidate span is a WINDOW around an anchor event: the assistant text and tool
calls immediately before/after it, so the judge sees the agent *doing*
something with enough context to evaluate the rule.

Rules whose topic maps to no anchorable event class yield no spans — honest, and
itself interesting ("no substantive spans found in window").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from housebroken.transcript import AssistantMsg, Event, ToolCall

# Anchor classes: (rule-topic regex, predicate over an event).
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

_CODE_TOPIC = re.compile(
    r"\bcode\b|\bfunction\b|\bmodule\b|\bnest|\bmutat|\brefactor|\bclean\b|"
    r"\breadable|\bsimpl|\bsmall\b|\bsurgical|\bnaming|\bcomment|\bimmutab|"
    r"\berror\b|\bexception|\bvalidat|\bstyle\b|\bidiomatic|\bduplicat|\bdead code",
    re.IGNORECASE,
)
_TEST_TOPIC = re.compile(r"\btest|\bcoverage\b|\btdd\b|\bmock\b|\bassert", re.IGNORECASE)
_GIT_TOPIC = re.compile(r"\bcommit|\bpush|\bbranch|\bmerge|\bpull request|\bpr\b|\bdiff\b", re.IGNORECASE)
_DEPLOY_TOPIC = re.compile(r"\bdeploy|\bship|\brelease|\bproduction\b|\bprod\b|\brollout", re.IGNORECASE)
_REVIEW_TOPIC = re.compile(r"\breview|\bcritical\b|\bsecurit|\baudit\b|\bvulnerab", re.IGNORECASE)

_TEST_FILE = re.compile(r"(test_|_test\.|\.test\.|/tests?/|spec\.)", re.IGNORECASE)
_TEST_CMD = re.compile(r"\b(pytest|unittest|go test|cargo test|npm test|jest|vitest|tox)\b", re.IGNORECASE)
_GIT_CMD = re.compile(r"\bgit\s+(commit|push|merge|rebase|diff)\b", re.IGNORECASE)
_DEPLOY_CMD = re.compile(r"\b(deploy|kubectl|docker push|terraform apply|serverless deploy|"
                         r"gh workflow|ssm send-command|eb deploy)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AnchorSpec:
    """Which events anchor a rule's judge spans."""

    edit: bool = False  # any code-edit tool
    test: bool = False  # a test run or a test-file edit
    git: bool = False  # a git commit/push/etc
    deploy: bool = False  # a deploy-ish command
    file_re: re.Pattern | None = None  # optional file-path constraint on edits

    @property
    def anchorable(self) -> bool:
        return self.edit or self.test or self.git or self.deploy

    def is_anchor(self, ev: Event) -> bool:
        if not isinstance(ev, ToolCall):
            return False
        name = ev.name
        cmd = ev.command()
        if self.test:
            if name in EDIT_TOOLS and _TEST_FILE.search(_edit_path(ev)):
                return True
            if cmd and _TEST_CMD.search(cmd):
                return True
        if self.deploy and cmd and _DEPLOY_CMD.search(cmd):
            return True
        if self.git and cmd and _GIT_CMD.search(cmd):
            return True
        if self.edit and name in EDIT_TOOLS:
            if self.file_re is None or self.file_re.search(_edit_path(ev)):
                return True
        return False


def _edit_path(ev: ToolCall) -> str:
    inp = ev.input if isinstance(ev.input, dict) else {}
    for k in ("file_path", "path", "notebook_path"):
        v = inp.get(k)
        if isinstance(v, str):
            return v
    return ""


def derive_anchor(rule_text: str) -> AnchorSpec:
    """Map a behavioral-prose rule to the anchor events that would evidence it."""
    t = rule_text
    test = bool(_TEST_TOPIC.search(t))
    git = bool(_GIT_TOPIC.search(t))
    deploy = bool(_DEPLOY_TOPIC.search(t))
    # Review/security/quality rules are evidenced by code edits.
    edit = bool(_CODE_TOPIC.search(t) or _REVIEW_TOPIC.search(t))
    return AnchorSpec(edit=edit, test=test, git=git, deploy=deploy)


# ---- window extraction ------------------------------------------------------
WINDOW_CHARS = 1500  # per-span char budget for the anchor window
_WINDOW_RADIUS = 2  # events before/after the anchor to include


def _event_snippet(ev: Event) -> str:
    """A compact, human-readable one-liner for an event in a window."""
    if isinstance(ev, ToolCall):
        cmd = ev.command()
        if cmd:
            return f"[{ev.name}] {cmd}"
        path = _edit_path(ev)
        return f"[{ev.name}] {path}" if path else f"[{ev.name}]"
    if isinstance(ev, AssistantMsg):
        return f"assistant: {ev.text}"
    return ""


def build_window(events: list[Event], anchor_idx: int) -> str:
    """Assemble a redacted-ready text window around events[anchor_idx].

    Includes the anchor event plus up to _WINDOW_RADIUS events on each side,
    trimmed to WINDOW_CHARS. Redaction is applied by the caller (make_span).
    """
    lo = max(0, anchor_idx - _WINDOW_RADIUS)
    hi = min(len(events), anchor_idx + _WINDOW_RADIUS + 1)
    parts = []
    for i in range(lo, hi):
        snip = _event_snippet(events[i]).strip()
        if not snip:
            continue
        marker = "  ▶ " if i == anchor_idx else "    "
        parts.append(marker + snip)
    text = "\n".join(parts)
    if len(text) > WINDOW_CHARS:
        # Keep the anchor-centred middle.
        text = text[:WINDOW_CHARS] + " …"
    return text


def quotes_rule_verbatim(rule_text: str, span_text: str) -> bool:
    """True if the span appears to quote the rule text itself (meta-discussion).

    Down-ranks self-referential spans: a session ABOUT the rules (this project's
    own dev logs) rather than the agent's conduct. Heuristic: a long verbatim
    substring of the rule appears in the span.
    """
    r = rule_text.strip().lower()
    s = span_text.lower()
    if len(r) >= 20 and r in s:
        return True
    # A distinctive 6-word shingle of the rule appearing verbatim.
    words = r.split()
    for i in range(0, max(0, len(words) - 5)):
        shingle = " ".join(words[i:i + 6])
        if len(shingle) >= 25 and shingle in s:
            return True
    return False
