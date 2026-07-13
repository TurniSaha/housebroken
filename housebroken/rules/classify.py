"""Rule checkability classifier (SPEC §3.1, five classes).

Every parsed rule is sorted into exactly one class. The class decides which
deterministic checker (if any) compiles it, and drives the honesty of the
report — the class is shown next to every grade.

Classes:
  forbidden-action   prohibits a concrete action ("never use X", "no Y")
                     -> deterministic literal / emoji checks (check/detect.py)
  required-sequence  mandates an ordering ("run tests before committing")
                     -> deterministic ordering checks (check/sequence.py)
  output-format      constrains a produced artifact ("conventional commits",
                     "answer in bullet points") -> check/output_format.py
  behavioral-prose   a judgeable disposition ("prefer simplicity", "act like a
                     senior engineer") -> Tier-2 judge candidate
  unenforceable      vibes with no observable behavior -> surfaced as a finding

Order of precedence matters: a rule that both prohibits and sequences is scored
by its strongest deterministic signal. We test forbidden-action, then
required-sequence, then output-format, then behavioral-prose, else unenforceable.
"""

from __future__ import annotations

import re

from housebroken.rules.parse import Rule

FORBIDDEN_ACTION = "forbidden-action"
REQUIRED_SEQUENCE = "required-sequence"
OUTPUT_FORMAT = "output-format"
BEHAVIORAL_PROSE = "behavioral-prose"
UNENFORCEABLE = "unenforceable"

# The three deterministic (mechanically checkable) classes.
CHECKABLE_CLASSES = frozenset({FORBIDDEN_ACTION, REQUIRED_SEQUENCE, OUTPUT_FORMAT})
ALL_CLASSES = (
    FORBIDDEN_ACTION,
    REQUIRED_SEQUENCE,
    OUTPUT_FORMAT,
    BEHAVIORAL_PROSE,
    UNENFORCEABLE,
)

# ---- forbidden-action -------------------------------------------------------
_PROHIBITION = re.compile(
    r"\b(never|do not|don['’]?t|dont|no longer|must not|shall not|avoid|"
    r"not allowed|do NOT)\b",
    re.IGNORECASE,
)
_NO_PREFIX = re.compile(r"^\s*no\s+\w", re.IGNORECASE)

# ---- required-sequence ------------------------------------------------------
# An ordering obligation: a "do A before/after B" or "always X before Y" shape.
_SEQUENCE = re.compile(
    r"\b(before|after|first|then|prior to|once .* (?:pass|complete)|"
    r"until .* (?:pass|green))\b",
    re.IGNORECASE,
)
# Action verbs that make a sequence rule about observable tool activity.
_SEQUENCE_ACTIONS = re.compile(
    r"\b(test|tests|commit|committing|push|pushing|build|lint|type[- ]?check|"
    r"run|review|plan|verify)\b",
    re.IGNORECASE,
)

# ---- output-format ----------------------------------------------------------
# No trailing \b so plurals match ("bullet points", "code blocks").
_OUTPUT_FORMAT = re.compile(
    r"\b(conventional commit|commit message|bullet[- ]?point|bullet[- ]?form|"
    r"markdown|format|title case|capitali[sz]e|emoji|prefix|heading|"
    r"code block|code fence|fenced|json|yaml|table)",
    re.IGNORECASE,
)

# ---- behavioral-prose vs unenforceable --------------------------------------
# Behavioral prose still expresses a disposition a judge could assess against
# concrete spans. Unenforceable is pure vibe with no observable hook.
_BEHAVIORAL = re.compile(
    r"\b(prefer|simplic\w+|senior|clean|readable|idiomatic|concise|thorough|"
    r"careful|explicit|maintainable|robust|pragmatic|minimal|clear|"
    r"root cause|small|cohesive|handle errors|comprehensive)\b",
    re.IGNORECASE,
)
# A rule with an imperative verb + an observable object is at least behavioral,
# not pure vibe. Very short vibe lines ("Act like a senior engineer.") without
# any observable object fall to unenforceable only if nothing else matched.
# An actionable imperative directive (a judge can assess adherence). Broad on
# purpose: a line that survived the parser's imperative gate and names a concrete
# action is behavioral-prose, not unenforceable vibe. Unenforceable is reserved
# for admitted lines with no actionable verb at all.
_HAS_VERB = re.compile(
    r"\b(use|write|run|add|remove|check|verify|ensure|handle|keep|make|follow|"
    r"validate|document|test|review|prefer|avoid|split|extract|organize|"
    r"provide|push|pull|enable|disable|address|fix|update|include|exclude|"
    r"apply|generate|create|delete|move|rename|configure|set|store|log|catch|"
    r"raise|return|name|scope|wrap|escape|sanitize|cache|batch|stream|"
    r"default|skip|stop|start|search|find|read|call|report|surface|treat|"
    r"trust|plan|refactor|implement|design|choose|pick|limit|require)\b",
    re.IGNORECASE,
)


def classify(rule: Rule) -> str:
    text = rule.text

    # 1. forbidden-action — strongest, cheapest deterministic signal.
    if _PROHIBITION.search(text) or _NO_PREFIX.match(text):
        # A prohibition phrased as a format rule ("no emojis") is still handled
        # by the forbidden-action checker (it owns the emoji check), so keep it.
        return FORBIDDEN_ACTION

    # 2. required-sequence — an ordering obligation over observable actions.
    if _SEQUENCE.search(text) and _SEQUENCE_ACTIONS.search(text):
        return REQUIRED_SEQUENCE

    # 3. output-format — constrains a produced artifact's shape.
    if _OUTPUT_FORMAT.search(text):
        return OUTPUT_FORMAT

    # 4. behavioral-prose — judgeable disposition.
    if _BEHAVIORAL.search(text):
        return BEHAVIORAL_PROSE

    # 5. Fallback: a rule with a real imperative verb + object is behavioral
    #    (a judge can look for adherence); otherwise it is unenforceable vibe.
    if _HAS_VERB.search(text) and len(text.split()) >= 4:
        return BEHAVIORAL_PROSE

    return UNENFORCEABLE
