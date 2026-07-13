"""Tier-1 deterministic checker: the ``forbidden-action`` class, end to end.

Precision over recall. We only claim a violation when a concrete forbidden
token is literally present in a tool call's input (chiefly Bash command
strings) or in assistant text. Rules whose prohibition we cannot compile into a
literal token get class ``uncheckable-for-now`` and are reported, never flagged.

The extraction is a small deterministic table:

  1. Backtick / quoted literal after a prohibition word:
        "never use `--no-verify`"  -> token "--no-verify"  (surface: any)
  2. A recognized flag/command mentioned bare after a prohibition:
        "do not use git push --force" -> token "git push --force" if a flag or
        known command word is present (we require a `--flag` or a shell-ish
        token to avoid matching prose nouns).
  3. Emoji prohibition ("no emojis in output") -> match emoji in assistant text.

Every VIOLATED receipt carries: session file, line number, timestamp, the
offending span (the exact command / matched text), and the quoted rule text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from housebroken.rules.classify import FORBIDDEN_ACTION, classify
from housebroken.rules.parse import Rule
from housebroken.transcript import AssistantMsg, Event, ToolCall

# ---- checkability classes for a forbidden-action rule -----------------------
CHECK_LITERAL = "forbidden-literal"  # compiled to a concrete token match
CHECK_EMOJI = "forbidden-emoji"
CHECK_UNCOMPILED = "uncheckable-for-now"

# Where a compiled check looks.
SURFACE_COMMAND = "command"  # Bash / shell command strings in tool inputs
SURFACE_ASSISTANT = "assistant-text"

_PROHIBITION_WORD = re.compile(
    r"\b(never|do not|don['’]?t|dont|must not|shall not|avoid|no longer)\b",
    re.IGNORECASE,
)
# Backtick or quoted literal anywhere in the rule.
_QUOTED = re.compile(r"[`\"']([^`\"']{2,60})[`\"']")
# A bare shell flag like --no-verify or -f (2+ chars after dashes for long flags).
_BARE_FLAG = re.compile(r"(?<!\w)(--[a-z][a-z0-9-]{1,40}|-[a-zA-Z])(?!\w)")

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U00002190-\U000021FF"
    "\U0000FE00-\U0000FE0F"
    "]",
)
# Rule mentions emojis/emoji explicitly.
_EMOJI_RULE = re.compile(r"\bemoji", re.IGNORECASE)

# Tokens that look like literals but are too generic to match safely as bare
# substrings — skip compiling these to avoid false positives.
_TOO_GENERIC = frozenset({"-c", "-i", "-e", "-f", "-p", "-n", "-x", "-v", "-r"})


@dataclass(frozen=True, slots=True)
class Receipt:
    session_file: str
    line_no: int
    timestamp: str | None
    span: str  # the offending text (command / matched fragment)
    rule_text: str


@dataclass(frozen=True, slots=True)
class CompiledCheck:
    rule: Rule
    check_class: str  # CHECK_LITERAL | CHECK_EMOJI | CHECK_UNCOMPILED
    token: str | None  # literal to look for (CHECK_LITERAL)
    surface: str | None  # where to look (CHECK_LITERAL)

    @property
    def compiled(self) -> bool:
        return self.check_class in (CHECK_LITERAL, CHECK_EMOJI)


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: Rule
    check_class: str
    receipts: tuple[Receipt, ...]
    checked: bool  # True if a concrete check ran (compiled)

    @property
    def violated(self) -> bool:
        return bool(self.receipts)


# A flag-shaped bare word: has a double-dash, OR is a hyphenated lowercase
# identifier of 2+ segments (e.g. dangerously-skip-permissions).
_FLAGWORD = re.compile(r"(?<![\w`])((?:--)?[a-z][a-z0-9]*(?:-[a-z0-9]+){1,6})(?![\w`])")
# A bare hyphenated token IMMEDIATELY followed (within one optional word) by an
# explicit flag/option label. This tight adjacency is the precision signal that
# lets us trust a bare token: "dangerously-skip-permissions flag" matches;
# "re-invoke the ... command context" does not.
_TOKEN_THEN_LABEL = re.compile(
    r"(?<![\w`])((?:--)?[a-z][a-z0-9]*(?:-[a-z0-9]+){1,6})\s+"
    r"(?:\w+\s+)?(?:flag|option|argument|switch)\b",
    re.IGNORECASE,
)


def _token_is_matchable(tok: str) -> bool:
    if not tok or tok in _TOO_GENERIC or len(tok) < 3:
        return False
    if "..." in tok or "…" in tok:
        # Placeholder literal (e.g. "-c user.name=...") won't match real commands.
        return False
    # Require a flag/command shape: a double-dash flag, or a hyphenated literal.
    return tok.startswith("--") or ("-" in tok)


def _extract_token(rule_text: str) -> tuple[str | None, str | None]:
    """Return (token, surface) for a literal check, or (None, None).

    Operates on backtick-preserving text so `--no-verify` survives. Only accepts
    flag-shaped literals (double-dash flags or hyphenated identifiers) to keep
    precision high — a bare English word after "never" is never compiled.
    """
    m = _PROHIBITION_WORD.search(rule_text)
    if not m:
        return None, None
    tail = rule_text[m.end():]

    # 1. Backticked literal in the prohibition tail (highest confidence).
    q = _QUOTED.search(tail)
    if q:
        tok = q.group(1).strip()
        if _token_is_matchable(tok):
            return tok, SURFACE_COMMAND

    # 1b. A bare hyphenated token IMMEDIATELY labeled a flag/option (e.g.
    #     "Never use dangerously-skip-permissions flag"). The label must trail
    #     the token within one word — "re-invoke the ... command context" must
    #     NOT match, or prose hyphenated verbs would compile as false positives.
    lab = _TOKEN_THEN_LABEL.search(tail)
    if lab:
        tok = lab.group(1)
        if _token_is_matchable(tok):
            return tok, SURFACE_COMMAND

    # 2. A bare long flag ("do not use --no-verify"). We deliberately do NOT
    #    compile bare hyphenated English words (over-engineering, agent-fleet):
    #    they look flag-shaped but are prose, and matching them as command
    #    substrings would produce false accusations. Precision over recall — a
    #    genuine command literal is either --dash-flagged or backticked (case 1).
    f = _BARE_FLAG.search(tail)
    if f:
        tok = f.group(1)
        if tok.startswith("--") and _token_is_matchable(tok):
            return tok, SURFACE_COMMAND

    return None, None


def compile_rule(rule: Rule) -> CompiledCheck:
    """Compile one rule into a forbidden-action check (or mark it uncompiled)."""
    if classify(rule) != FORBIDDEN_ACTION:
        return CompiledCheck(rule, CHECK_UNCOMPILED, None, None)

    if _EMOJI_RULE.search(rule.text):
        return CompiledCheck(rule, CHECK_EMOJI, None, SURFACE_ASSISTANT)

    # Extract from raw_text (backticks preserved) so `--no-verify` survives.
    source_text = rule.raw_text or rule.text
    token, surface = _extract_token(source_text)
    if token is not None:
        return CompiledCheck(rule, CHECK_LITERAL, token, surface)

    return CompiledCheck(rule, CHECK_UNCOMPILED, None, None)


def compile_rules(rules: tuple[Rule, ...] | list[Rule]) -> tuple[CompiledCheck, ...]:
    return tuple(compile_rule(r) for r in rules)


# Commands whose whole purpose is to *inspect/print* text, not run the token.
# If the matched line is one of these, the token is being discussed, not invoked.
_INSPECTION_LEAD = re.compile(
    r"^\s*(echo|printf|cat|which|type|command\s+-v|grep|rg|sed|awk|"
    r"comm|diff|head|tail|less|more|man)\b"
)
# A line that is prose (ends with sentence punctuation, or contains markup) is a
# mention, not an invocation.
_PROSE_HINT = re.compile(r"</?[a-z]+>|[.!?](\s|$)|^\s*[*#-]\s|:\s*$")


def _line_of(cmd: str, idx: int) -> str:
    left = cmd.rfind("\n", 0, idx) + 1
    right = cmd.find("\n", idx)
    if right < 0:
        right = len(cmd)
    return cmd[left:right]


# Shell segment separators: the token's invocation is the segment it lives in,
# not the whole compound line. "a && which x; b" -> the segment is "which x".
_SEGMENT_SEP = re.compile(r"(&&|\|\||[;|&\n]|\$\()")


def _segment_of(cmd: str, idx: int) -> str:
    """Return the shell command segment (between separators) containing idx."""
    left = 0
    for m in _SEGMENT_SEP.finditer(cmd, 0, idx):
        left = m.end()
    rm = _SEGMENT_SEP.search(cmd, idx)
    right = rm.start() if rm else len(cmd)
    return cmd[left:right].strip()


def _within_quotes(line: str, tok_start_in_line: int) -> bool:
    """True if the position sits inside a single- or double-quoted string."""
    seg = line[:tok_start_in_line]
    return (seg.count("'") % 2 == 1) or (seg.count('"') % 2 == 1)


def _match_span(token: str, cmd: str) -> str | None:
    """Return a receipt span only if ``token`` is *invoked* as a real shell arg.

    The dominant false-positive mode on real transcripts is the token being
    *mentioned* — echoed into docs, quoted in a heredoc, wrapped in <code> or
    backticks, or listed by `which`/`grep`. Precision over recall: we accept a
    match only when it sits at shell-argument boundaries on a line that is a
    plausible command invocation and is not inside a quoted string, an
    inspection command, or prose.
    """
    start = 0
    n = len(token)
    while True:
        i = cmd.find(token, start)
        if i < 0:
            return None
        start = i + n
        before = cmd[i - 1] if i > 0 else " "
        after = cmd[i + n] if i + n < len(cmd) else " "
        if before.isalnum() or before in "_/.":
            continue
        if after.isalnum() or after in "-_/":
            continue

        line = _line_of(cmd, i)
        line_start = cmd.rfind("\n", 0, i) + 1
        pos_in_line = i - line_start
        segment = _segment_of(cmd, i)

        # Backtick / <code> markup around the token -> a mention.
        wl = cmd[max(0, i - 8):i]
        wr = cmd[i + n:i + n + 8]
        if "`" in wl or "`" in wr or "<code" in wl.lower() or "code>" in wr.lower():
            continue
        # Inside a quoted string (heredoc doc, echoed sentence) -> a mention.
        if _within_quotes(line, pos_in_line):
            continue
        # Inspection/printing command in this segment -> subject, not invoked.
        if _INSPECTION_LEAD.match(segment):
            continue
        # Prose line (markup, sentence punctuation, list/heading marker) -> mention.
        if _PROSE_HINT.search(line):
            continue

        s = max(0, i - 40)
        e = min(len(cmd), i + n + 40)
        return cmd[s:e].strip()


def _scan_event(check: CompiledCheck, ev: Event) -> Receipt | None:
    if check.check_class == CHECK_LITERAL:
        # Only genuine command executions count. Authored artifacts (Write bodies,
        # plans, task descriptions) that merely mention the token are not runs.
        if check.surface == SURFACE_COMMAND and isinstance(ev, ToolCall):
            cmd = ev.command()
            if not cmd:
                return None
            span = _match_span(check.token, cmd)
            if span is not None:
                return Receipt(ev.file, ev.line_no, ev.timestamp, span, check.rule.text)
        return None

    if check.check_class == CHECK_EMOJI and isinstance(ev, AssistantMsg):
        m = _EMOJI_RE.search(ev.text)
        if m:
            # Show a small window around the emoji as the span.
            start = max(0, m.start() - 30)
            end = min(len(ev.text), m.end() + 30)
            span = ev.text[start:end].replace("\n", " ")
            return Receipt(ev.file, ev.line_no, ev.timestamp, span, check.rule.text)
    return None


class ForbiddenActionChecker:
    """Replays an event stream once, scoring every compiled forbidden rule.

    Usage:
        checker = ForbiddenActionChecker(compiled_checks)
        for ev in events:            # single pass over the whole corpus
            checker.observe(ev)
        results = checker.results()
    """

    def __init__(self, checks: tuple[CompiledCheck, ...] | list[CompiledCheck]):
        self._checks = tuple(checks)
        self._receipts: dict[str, list[Receipt]] = {c.rule.id: [] for c in self._checks}

    def observe(self, ev: Event) -> None:
        for check in self._checks:
            if not check.compiled:
                continue
            r = _scan_event(check, ev)
            if r is not None:
                self._receipts[check.rule.id].append(r)

    def results(self) -> tuple[RuleResult, ...]:
        out = []
        for check in self._checks:
            receipts = tuple(self._receipts[check.rule.id])
            out.append(
                RuleResult(
                    rule=check.rule,
                    check_class=check.check_class,
                    receipts=receipts,
                    checked=check.compiled,
                )
            )
        return tuple(out)
