"""Report card rendering: text (ANSI), markdown, and JSON.

The real M2 report per SPEC §6: an housebroken score, per-rule grades with the
check class shown next to each, receipts under violations, ASLEEP token math,
and a KEEP/REWRITE/DELETE verdict roll-up.
"""

from __future__ import annotations

import json

from housebroken.score import (
    ASLEEP,
    DELETE,
    KEEP,
    NEEDS_CHECK,
    NEEDS_JUDGE,
    PASSED,
    PASSED_JUDGED,
    REWRITE,
    SUSPECTED,
    UNENFORCEABLE_G,
    VIOLATED,
    RuleCard,
    ScanResult,
)

_GRADE_ORDER = {
    VIOLATED: 0, SUSPECTED: 1, ASLEEP: 2, PASSED: 3, PASSED_JUDGED: 4,
    NEEDS_JUDGE: 5, NEEDS_CHECK: 6, UNENFORCEABLE_G: 7,
}

_GLYPH = {
    VIOLATED: "✗",
    SUSPECTED: "!",
    PASSED: "✓",
    PASSED_JUDGED: "✓",
    ASLEEP: "~",
    NEEDS_JUDGE: "?",
    NEEDS_CHECK: "·",
    UNENFORCEABLE_G: "?",
}
_COLOR = {
    VIOLATED: "31",
    SUSPECTED: "33",
    PASSED: "32",
    PASSED_JUDGED: "32",
    ASLEEP: "33",
    NEEDS_JUDGE: "36",
    NEEDS_CHECK: "90",
    UNENFORCEABLE_G: "35",
}


def _short(text: str, width: int = 58) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def _human_tokens(n: int) -> str:
    if n >= 1000:
        return f"~{n / 1000:.0f}k tokens"
    return f"~{n} tokens"


def render_text(scan: ScanResult, use_color: bool = True) -> str:
    def c(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if use_color else s

    lines: list[str] = ["", (
        f"Read {scan.rules_files} rules file(s) ({scan.rules_parsed} rules) · "
        f"replayed {scan.sessions} session(s) / {scan.stats.events} events"
    )]
    if scan.stats.malformed_lines:
        lines.append(
            f"  (skipped {scan.stats.malformed_lines} malformed line(s); "
            f"{sum(scan.stats.skipped_types.values())} non-message record(s))"
        )
    lines.append("")
    lines.append(c("1", f"  HOUSEBROKEN REPORT ── score {scan.score}%"))
    lines.append("")

    cards = sorted(
        scan.cards,
        key=lambda k: (_GRADE_ORDER.get(k.grade, 9), -len(k.receipts)),
    )
    for card in cards:
        glyph = _GLYPH.get(card.grade, "·")
        col = _COLOR.get(card.grade, "0")
        label = f"{glyph} {card.grade}"
        head = f"  {c(col, label):<22} \"{_short(card.rule.text)}\""
        if card.grade == VIOLATED:
            suffix = f"  {c('31', f'{len(card.receipts)}×')}  [{card.rule_class}]"
        elif card.grade == SUSPECTED:
            suffix = f"  {c('33', 'unverified')}  [judge {card.judged_spans}/{card.candidate_spans}]"
        elif card.grade == PASSED_JUDGED:
            suffix = f"  (judged {card.judged_spans}/{card.candidate_spans} spans)  [{card.rule_class}]"
        elif card.grade == PASSED:
            suffix = f"  (applicable {card.applicable_sessions}×)  [{card.rule_class}]"
        elif card.grade == ASLEEP:
            suffix = f"  {_human_tokens(card.wasted_tokens)} wasted  [{card.rule_class}]"
        else:
            suffix = f"  [{card.rule_class}]"
        lines.append(head + suffix)

        if card.grade in (VIOLATED, SUSPECTED) and card.receipts:
            rc = card.receipts[0]
            ts = rc.timestamp or "?"
            session = rc.session_file.split("/")[-1]
            lines.append(f"      └ {ts} {session}:{rc.line_no}")
            lines.append(f"        {c('33', _short(rc.span, 72))}")
        if card.judge_reason and card.grade in (VIOLATED, SUSPECTED):
            lines.append(c("90", f"        ↳ judge: {_short(card.judge_reason, 66)}"))
        if card.grade == NEEDS_JUDGE and card.judge_reason:
            lines.append(c("90", f"        ↳ {_short(card.judge_reason, 66)}"))
        if card.verdict == REWRITE and card.suggestion:
            lines.append(c("90", f"        ↳ REWRITE: {_short(card.suggestion, 68)}"))

    # If the judge ran but nothing met the evidence bar, say so once — and frame
    # the conservatism as the trust feature it is.
    sampled = sum(c.judged_spans for c in scan.cards if c.grade == NEEDS_JUDGE)
    concluded = any(c.grade in (PASSED_JUDGED, SUSPECTED) for c in scan.cards)
    if sampled and not concluded:
        lines.append("")
        lines.append(c(
            "90",
            f"  judge: {sampled} spans sampled, no verdict met the evidence bar — "
            f"housebroken never accuses without a receipt",
        ))

    v = {KEEP: 0, REWRITE: 0, DELETE: 0}
    for card in scan.cards:
        v[card.verdict] = v.get(card.verdict, 0) + 1
    lines.append("")
    lines.append(
        f"  Verdicts: {c('32', f'KEEP {v[KEEP]}')} · "
        f"{c('33', f'REWRITE {v[REWRITE]}')} · "
        f"{c('31', f'DELETE {v[DELETE]}')}"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _card_dict(card: RuleCard) -> dict:
    return {
        "rule_id": card.rule.id,
        "text": card.rule.text,
        "source": card.rule.source,
        "line_no": card.rule.line_no,
        "heading_path": list(card.rule.heading_path),
        "class": card.rule_class,
        "grade": card.grade,
        "verdict": card.verdict,
        "applicable_sessions": card.applicable_sessions,
        "wasted_tokens": card.wasted_tokens,
        "suggestion": card.suggestion,
        "judge_reason": card.judge_reason,
        "judged_spans": card.judged_spans,
        "candidate_spans": card.candidate_spans,
        "receipts": [
            {
                "session_file": r.session_file,
                "line_no": r.line_no,
                "timestamp": r.timestamp,
                "span": r.span,
                "rule_text": r.rule_text,
            }
            for r in card.receipts
        ],
    }


def render_json(scan: ScanResult) -> str:
    payload = {
        "score": scan.score,
        "rules_files": scan.rules_files,
        "rules_parsed": scan.rules_parsed,
        "sessions": scan.sessions,
        "events": scan.stats.events,
        "malformed_lines": scan.stats.malformed_lines,
        "class_counts": scan.class_counts,
        "grade_counts": scan.grade_counts,
        "cards": [_card_dict(c) for c in scan.cards],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_markdown(scan: ScanResult) -> str:
    out = [f"# Housebroken report — score {scan.score}%", ""]
    out.append(
        f"Read {scan.rules_files} rules files ({scan.rules_parsed} rules), "
        f"replayed {scan.sessions} sessions / {scan.stats.events} events."
    )
    out.append("")
    out.append("| Grade | Rule | Class | Detail |")
    out.append("|---|---|---|---|")
    cards = sorted(scan.cards, key=lambda k: (_GRADE_ORDER.get(k.grade, 9), -len(k.receipts)))
    for card in cards:
        detail = ""
        if card.grade == VIOLATED:
            detail = f"{len(card.receipts)}×"
        elif card.grade == PASSED:
            detail = f"applicable {card.applicable_sessions}×"
        elif card.grade == ASLEEP:
            detail = _human_tokens(card.wasted_tokens) + " wasted"
        text = card.rule.text.replace("|", "\\|")
        out.append(f"| {card.grade} | {_short(text, 70)} | {card.rule_class} | {detail} |")
    out.append("")
    v = {KEEP: 0, REWRITE: 0, DELETE: 0}
    for card in scan.cards:
        v[card.verdict] = v.get(card.verdict, 0) + 1
    out.append(f"**Verdicts:** KEEP {v[KEEP]} · REWRITE {v[REWRITE]} · DELETE {v[DELETE]}")
    out.append("")
    return "\n".join(out)
