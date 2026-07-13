"""`housebroken demo` — a 30-second wow against a bundled synthetic fixture.

Runs the full pipeline over `fixtures/demo/` with a CANNED judge runner so a
stranger with no `claude` CLI and no transcript history still sees every grade,
including the two judged ones (PASSED-JUDGED and SUSPECTED). The output states
plainly that demo judging is canned.

100% synthetic content — the night-shift-agent-breaks-curfew story.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from housebroken.report import render_json, render_markdown, render_text
from housebroken.rules.parse import parse_files
from housebroken.score import scan

# Bundled inside the package so the demo ships in the wheel and runs from any cwd.
DEMO_DIR = Path(__file__).resolve().parent / "demo_fixtures"
DEMO_RULES = DEMO_DIR / "rules.md"
DEMO_SESSION = DEMO_DIR / "session.jsonl"


def _canned_runner(prompt: str, timeout_s: int) -> str:
    """Deterministic judge stand-in keyed to the demo rule+span (no CLI call).

    The prompt embeds both the rule and the evidence span; we branch on both so
    the demo lands one PASSED-JUDGED and one SUSPECTED.
    """
    # Isolate the RULE and EVIDENCE-SPAN sections using build_prompt's literal
    # labels, so we key the rule on rule text and the span on span text.
    lower = prompt.lower()
    try:
        rule_part = lower.split("rule:", 1)[1].split("evidence span", 1)[0]
        span_part = lower.split("evidence span (one thing", 1)[1].split(
            "decide whether", 1)[0]
    except IndexError:
        rule_part = span_part = lower
    rule_surgical = "surgical" in rule_part
    rule_clean = "readable" in rule_part
    span_surgical = "surgical change" in span_part or "no benefit for a hotfix" in span_part
    span_trustme = "trust me" in span_part or "reads much better" in span_part

    if rule_surgical and span_surgical:
        # A concrete, careful decision -> compliant (PASSED-JUDGED).
        verdict = {"verdict": "compliant", "quote": "",
                   "reason": "The agent scoped the edit to the single buggy function."}
    elif rule_clean and span_trustme:
        # An unverifiable "trust me, it's clean" claim -> violation the judge
        # cannot back with a quote from the span -> SUSPECTED.
        verdict = {"verdict": "violation",
                   "quote": "not a substring that appears verbatim in the span",
                   "reason": "Claims cleanliness but shows no verifiable evidence."}
    else:
        verdict = {"verdict": "unclear", "quote": "",
                   "reason": "The span does not concretely show the rule followed or broken."}
    return json.dumps({"type": "result", "result": json.dumps(verdict)})


def run_demo(fmt: str = "text", use_color: bool = True) -> str:
    rules = parse_files([str(DEMO_RULES)])
    # Ephemeral cache so the demo is reproducible and never touches the user's
    # real ~/.cache/housebroken.
    cache_dir = Path(tempfile.mkdtemp(prefix="housebroken-demo-"))
    result = scan(
        rules,
        (DEMO_SESSION,),
        rules_files=1,
        use_judge=True,
        judge_runner=_canned_runner,  # canned: no claude CLI needed
        judge_budget=50,
        judge_cache_dir=cache_dir,
    )
    if fmt == "json":
        return render_json(result)
    if fmt == "md":
        return render_markdown(result)

    banner = (
        "\n  housebroken demo — a bundled synthetic transcript (no CLAUDE.md or "
        "claude CLI needed).\n  The story: a night-shift agent breaks curfew. "
        "Judge verdicts here are CANNED for the demo.\n"
    )
    return banner + render_text(result, use_color=use_color)
