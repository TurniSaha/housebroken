"""Scoring engine: classifier + applicability + checkers -> graded rule cards.

This is the brain that produces the real report card. It replays transcripts
per session (ordering matters for required-sequence and applicability), runs the
deterministic checkers, and assigns each rule a grade, a verdict, and — for
asleep rules — an estimated wasted-token cost.

Grades:
  VIOLATED      a checker produced >=1 receipt
  PASSED        checkable + applicable in >=1 session + no receipts
  ASLEEP        checkable + applicable in 0 sessions in the window
  NEEDS-JUDGE   behavioral-prose (Tier-2 seam; no deterministic verdict in M2)
  UNENFORCEABLE the rule is vibe with no observable behavior

Verdicts (KEEP / REWRITE / DELETE) are heuristics over grade + class + text.
All spans are redacted before they land on a card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from housebroken.anchor import AnchorSpec, build_window, derive_anchor, quotes_rule_verbatim
from housebroken.applicability import Trigger, compile_trigger
from housebroken.check.detect import (
    ForbiddenActionChecker,
    Receipt,
    compile_rules,
)
from housebroken.check.judge import (
    DEFAULT_JUDGE_BUDGET,
    DEFAULT_JUDGE_WORKERS,
    DEFAULT_SPANS_PER_RULE,
    JudgeSpan,
    RuleJudgement,
    _default_runner,
    cli_available,
    judge_rules,
    make_span,
    rank_spans,
)
from housebroken.check.output_format import OutputFormatChecker, compile_format_rules
from housebroken.check.sequence import SequenceChecker, compile_sequence_rules
from housebroken.redact import redact
from housebroken.rules.classify import (
    BEHAVIORAL_PROSE,
    CHECKABLE_CLASSES,
    FORBIDDEN_ACTION,
    OUTPUT_FORMAT,
    REQUIRED_SEQUENCE,
    UNENFORCEABLE,
    classify,
)
from housebroken.rules.parse import Rule
from housebroken.transcript import ParseStats, _Counter, stream_events

# Grades.
VIOLATED = "VIOLATED"
PASSED = "PASSED"
ASLEEP = "ASLEEP"
NEEDS_JUDGE = "NEEDS-JUDGE"
UNENFORCEABLE_G = "UNENFORCEABLE"
# A checkable-CLASS rule for which no concrete checker compiled yet: we honestly
# cannot say PASSED (nothing ran). Distinct from ASLEEP (would-run but no
# applicable session) and from NEEDS-JUDGE (behavioral prose).
NEEDS_CHECK = "NEEDS-CHECK"
# Judge outcomes (behavioral-prose rules that the Tier-2 judge assessed):
PASSED_JUDGED = "PASSED-JUDGED"  # judge found compliance; counts toward score
SUSPECTED = "SUSPECTED"  # judge flagged a violation without a verifiable quote;
#                          shown distinctly, NEVER counted as VIOLATED, scored neutrally

# Verdicts.
KEEP = "KEEP"
REWRITE = "REWRITE"
DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class RuleCard:
    rule: Rule
    rule_class: str
    grade: str
    verdict: str
    receipts: tuple[Receipt, ...]
    applicable_sessions: int
    wasted_tokens: int  # estimated, ASLEEP only (else 0)
    suggestion: str  # tightened phrasing for REWRITE (else "")
    judge_reason: str = ""  # one-liner from the Tier-2 judge (SUSPECTED/judged)
    judged_spans: int = 0  # spans the judge assessed (judged classes only)
    candidate_spans: int = 0  # spans available to the judge (coverage display)


@dataclass(frozen=True, slots=True)
class ScanResult:
    cards: tuple[RuleCard, ...]
    rules_files: int
    rules_parsed: int
    sessions: int
    stats: ParseStats
    score: int  # 0-100 housebroken score
    class_counts: dict  # class -> count
    grade_counts: dict  # grade -> count


def estimate_tokens(rule: Rule) -> int:
    """~1 token per 4 chars of the rule text (the classic rough heuristic)."""
    return max(1, len(rule.text) // 4)


def _suggestion_for(rule: Rule, rule_class: str, grade: str) -> str:
    """A conservative tightened-phrasing suggestion for REWRITE verdicts."""
    if rule_class == UNENFORCEABLE:
        return (
            "State an observable behavior (a command, file, or output pattern) "
            "so the rule can be checked, or delete it."
        )
    if grade == ASLEEP:
        return "Scope this to a project where it applies, or delete it."
    if rule_class == BEHAVIORAL_PROSE:
        return (
            "Name the concrete action or artifact this should change so it can "
            "be verified rather than judged."
        )
    return ""


def _verdict_for(rule: Rule, rule_class: str, grade: str, applicable: int) -> str:
    # A rule that caught something (deterministically or via a verified judge
    # quote) is doing its job — KEEP it.
    if grade in (VIOLATED, PASSED, PASSED_JUDGED, SUSPECTED):
        return KEEP
    if grade == ASLEEP:
        return DELETE
    if grade == UNENFORCEABLE_G:
        return REWRITE  # vibe with no observable hook: tighten or delete
    # NEEDS_JUDGE (judge inconclusive/skipped) and NEEDS_CHECK (checkable but not
    # yet compiled) are legitimate rules awaiting a checker/judge — KEEP them.
    return KEEP


class _MultiChecker:
    """Fans one event out to all deterministic checkers."""

    def __init__(self, forbidden, sequence, fmt):
        self.forbidden = forbidden
        self.sequence = sequence
        self.fmt = fmt

    def observe(self, ev) -> None:
        self.forbidden.observe(ev)
        self.sequence.observe(ev)
        self.fmt.observe(ev)


def _session_in_project(transcript_path, project_dir: str | None) -> bool:
    """True if a transcript belongs to an excluded project directory.

    Claude Code encodes the project cwd into the per-project transcript dir name
    (slashes -> dashes). We match the encoded form against the excluded path so
    self-referential dev sessions can be dropped from judge span selection.
    """
    if not project_dir:
        return False
    encoded = project_dir.replace("/", "-")
    return encoded in str(transcript_path)


def scan(
    rules: tuple[Rule, ...],
    transcripts: tuple,
    rules_files: int,
    use_judge: bool = False,
    judge_runner=None,
    judge_budget: int = DEFAULT_JUDGE_BUDGET,
    spans_per_rule: int = DEFAULT_SPANS_PER_RULE,
    judge_cache_dir=None,
    judge_workers: int = DEFAULT_JUDGE_WORKERS,
    exclude_project: str | None = None,
) -> ScanResult:
    """Replay transcripts per session and produce graded rule cards.

    When ``use_judge`` is True and the `claude` CLI is available (or a
    ``judge_runner`` is injected for tests), behavioral-prose rules are judged
    over applicability-prefiltered, redacted candidate spans.
    """
    from housebroken.transcript import ToolCall  # local: avoid top cycle churn

    # Compile every checker family once.
    forbidden_checks = compile_rules(rules)
    forbidden = ForbiddenActionChecker(forbidden_checks)
    seq = SequenceChecker(compile_sequence_rules(rules))
    fmt = OutputFormatChecker(compile_format_rules(rules))
    multi = _MultiChecker(forbidden, seq, fmt)

    triggers: dict[str, Trigger] = {r.id: compile_trigger(r) for r in rules}
    applicable_sessions: dict[str, int] = {r.id: 0 for r in rules}

    # Behavioral-prose rules are the judge candidates. We anchor their candidate
    # spans to CONCRETE EVENTS (code edits, test runs, deploys, commits) matched
    # to each rule's topic, and window around the anchor so the judge sees the
    # agent DOING something — not narration. Rules whose topic anchors to no
    # event class yield no spans (honest NEEDS-JUDGE, noted on the card).
    judge_rule_ids = {r.id for r in rules if classify(r) == BEHAVIORAL_PROSE}
    judge_rule_text = {r.id: r.text for r in rules if r.id in judge_rule_ids}
    anchors: dict[str, AnchorSpec] = {
        rid: derive_anchor(judge_rule_text[rid]) for rid in judge_rule_ids
    }
    anchorable_ids = {rid for rid in judge_rule_ids if anchors[rid].anchorable}
    candidate_spans: dict[str, list[JudgeSpan]] = {rid: [] for rid in judge_rule_ids}
    collecting = use_judge and bool(anchorable_ids)
    pool_cap = max(spans_per_rule * 4, 8)  # bounded per-rule window pool

    exclude = str(Path(exclude_project).expanduser().resolve()) if exclude_project else None

    counter = _Counter()
    n_sessions = 0
    for tpath in transcripts:
        n_sessions += 1
        fired_this_session: set[str] = set()
        # Rolling event buffer for anchor windows (bounded, streaming-safe).
        buf: list = []
        session_excluded = _session_in_project(tpath, exclude)
        for ev in stream_events(tpath, counter=counter):
            multi.observe(ev)
            if collecting and not session_excluded:
                buf.append(ev)
                if len(buf) > 64:  # cap the rolling buffer
                    buf.pop(0)
                # When an anchor fires, window it for every rule it anchors.
                if isinstance(ev, ToolCall):
                    anchor_idx = len(buf) - 1
                    for rid in anchorable_ids:
                        if len(candidate_spans[rid]) >= pool_cap:
                            continue
                        if anchors[rid].is_anchor(ev):
                            window = build_window(buf, anchor_idx)
                            if len(window.strip()) >= 40 and not quotes_rule_verbatim(
                                judge_rule_text[rid], window
                            ):
                                candidate_spans[rid].append(
                                    make_span(window, ev.file, ev.line_no, ev.timestamp)
                                )
            for rid, trig in triggers.items():
                if rid not in fired_this_session and trig.fires(ev):
                    fired_this_session.add(rid)
        for rid in fired_this_session:
            applicable_sessions[rid] += 1
        seq.finish_session()

    # ---- run the Tier-2 judge over candidate spans (bounded, depth-first) --
    judgements: dict[str, RuleJudgement] = {}
    judge_active = use_judge and (judge_runner is not None or cli_available())
    if judge_active:
        # Order rules by PROMISE: most-applicable first, so a bounded budget is
        # spent judging the rules most likely to matter. rank_spans puts the
        # best (high-signal) spans first within each rule.
        ranked_ids = sorted(
            (rid for rid in judge_rule_ids if candidate_spans[rid]),
            key=lambda rid: applicable_sessions[rid],
            reverse=True,
        )
        candidates = {
            rid: (judge_rule_text[rid], rank_spans(candidate_spans[rid]))
            for rid in ranked_ids
        }
        if candidates:
            judgements = judge_rules(
                candidates,
                runner=judge_runner if judge_runner is not None else _default_runner,
                budget=judge_budget,
                spans_per_rule=spans_per_rule,
                cache_dir=judge_cache_dir,
                workers=judge_workers,
                # Live progress only for the real CLI path; quiet for injected
                # (test) runners.
                show_progress=judge_runner is None,
            )

    # ---- collect receipts per rule across all checker families -------------
    forbidden_results = {rr.rule.id: rr for rr in forbidden.results()}
    seq_ids = seq.compiled_rule_ids()
    fmt_ids = fmt.compiled_rule_ids()

    cards: list[RuleCard] = []
    class_counts: dict[str, int] = {}
    grade_counts: dict[str, int] = {}

    for rule in rules:
        rclass = classify(rule)
        class_counts[rclass] = class_counts.get(rclass, 0) + 1

        receipts: list[Receipt] = []
        checked = False
        if rule.id in forbidden_results:
            fr = forbidden_results[rule.id]
            if fr.checked:
                checked = True
            receipts.extend(fr.receipts)
        if rule.id in seq_ids:
            checked = True
            receipts.extend(seq.receipts_for(rule.id))
        if rule.id in fmt_ids:
            checked = True
            receipts.extend(fmt.receipts_for(rule.id))

        # Redact every span before it can reach a card.
        receipts = [
            Receipt(r.session_file, r.line_no, r.timestamp, redact(r.span),
                    redact(r.rule_text))
            for r in receipts
        ]

        applicable = applicable_sessions.get(rule.id, 0)

        grade = _grade(rclass, checked, bool(receipts), applicable)
        judge_reason = ""
        judged_spans = 0
        candidate_spans_n = 0

        # Fold in the Tier-2 judge for behavioral-prose rules.
        if grade == NEEDS_JUDGE and rule.id in judgements:
            jm = judgements[rule.id]
            judged_spans = jm.judged_spans
            candidate_spans_n = jm.candidate_spans
            grade, judge_receipt, judge_reason = _apply_judge(jm)
            if judge_receipt is not None:
                receipts = [judge_receipt]
        # Honest note for behavioral-prose rules the judge couldn't reach: no
        # anchorable event class, or no substantive window found.
        if grade == NEEDS_JUDGE and rule.id in judge_rule_ids and not judge_reason:
            if rule.id not in anchorable_ids:
                judge_reason = "no anchorable activity for this rule's topic"
            elif not candidate_spans.get(rule.id):
                judge_reason = "no substantive spans found in window"

        wasted = estimate_tokens(rule) * n_sessions if grade == ASLEEP else 0
        verdict = _verdict_for(rule, rclass, grade, applicable)
        suggestion = _suggestion_for(rule, rclass, grade) if verdict == REWRITE else ""

        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        cards.append(
            RuleCard(
                rule=rule,
                rule_class=rclass,
                grade=grade,
                verdict=verdict,
                receipts=tuple(receipts),
                applicable_sessions=applicable,
                wasted_tokens=wasted,
                suggestion=redact(suggestion),
                judge_reason=redact(judge_reason),
                judged_spans=judged_spans,
                candidate_spans=candidate_spans_n,
            )
        )

    score = _housebroken_score(grade_counts)
    return ScanResult(
        cards=tuple(cards),
        rules_files=rules_files,
        rules_parsed=len(rules),
        sessions=n_sessions,
        stats=counter.freeze(),
        score=score,
        class_counts=class_counts,
        grade_counts=grade_counts,
    )


def _apply_judge(judgement: RuleJudgement) -> tuple[str, "Receipt | None", str]:
    """Map a rule's judge verdicts to (grade, receipt-or-None, reason).

    Precedence: a verified violation (quote found in span) -> VIOLATED with a
    receipt; else a suspected violation (no verifiable quote) -> SUSPECTED with
    a receipt but never counted as a hard violation; else if any span was judged
    compliant -> PASSED-JUDGED; else NEEDS-JUDGE (judge was inconclusive/skipped).
    """
    verified = judgement.verified_violation
    if verified is not None and verified.span is not None:
        sp = verified.span
        return (
            VIOLATED,
            Receipt(sp.session_file, sp.line_no, sp.timestamp,
                    redact(verified.quote or sp.text[:200]),
                    ""),
            verified.reason,
        )
    suspected = judgement.suspected_violation
    if suspected is not None and suspected.span is not None:
        sp = suspected.span
        return (
            SUSPECTED,
            Receipt(sp.session_file, sp.line_no, sp.timestamp,
                    redact(sp.text[:200]), ""),
            suspected.reason,
        )
    if judgement.any_compliant:
        return (PASSED_JUDGED, None, "")
    return (NEEDS_JUDGE, None, "")


def _grade(rclass: str, checked: bool, has_receipts: bool, applicable: int) -> str:
    if has_receipts:
        return VIOLATED
    if rclass == UNENFORCEABLE:
        return UNENFORCEABLE_G
    if rclass == BEHAVIORAL_PROSE:
        return NEEDS_JUDGE
    # A checkable-CLASS rule that never compiled to a concrete check was not
    # actually verified — calling it PASSED would inflate the score dishonestly.
    if not checked:
        return NEEDS_CHECK
    # A concretely checked rule with no receipts: PASSED if it was applicable at
    # least once, else ASLEEP (its subject never came up in the window).
    if applicable > 0:
        return PASSED
    return ASLEEP


def _housebroken_score(grade_counts: dict) -> int:
    """Score over rules that got a real verdict (PASSED[-JUDGED] vs VIOLATED).

    Included in the ratio: PASSED, PASSED-JUDGED (judge found compliance), and
    VIOLATED (deterministic receipt OR a judge violation with a verified quote).
    Excluded (neither inflate nor deflate): SUSPECTED (unverified judge flag),
    NEEDS-JUDGE, NEEDS-CHECK, UNENFORCEABLE, ASLEEP — none is a settled
    pass/fail. If nothing was settled, score is 100.
    """
    passed = grade_counts.get(PASSED, 0) + grade_counts.get(PASSED_JUDGED, 0)
    violated = grade_counts.get(VIOLATED, 0)
    denom = passed + violated
    if denom == 0:
        return 100
    return round(100 * passed / denom)
