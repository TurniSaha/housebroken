"""Tier-2 judge tests with a deterministic mock runner (no real CLI calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from housebroken.check.judge import (
    J_COMPLIANT,
    J_UNCLEAR,
    J_VIOLATION,
    JudgeSpan,
    build_prompt,
    is_substantive,
    judge_rules,
    judge_span,
    make_span,
    rank_spans,
)


def _envelope(result_obj) -> str:
    """Wrap a verdict object the way `claude -p --output-format json` would."""
    inner = json.dumps(result_obj) if not isinstance(result_obj, str) else result_obj
    return json.dumps({"type": "result", "subtype": "success", "result": inner})


def _runner_returning(stdout):
    def runner(prompt, timeout_s):
        return stdout
    return runner


class TestVerdictDiscipline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.span = make_span("The agent wrote deeply nested spaghetti code here.",
                              "/t/sess.jsonl", 10, "2026-01-01T00:00:00Z")

    def _judge(self, stdout):
        return judge_span("Prefer simple code.", self.span,
                          runner=_runner_returning(stdout),
                          cache_dir=Path(self.tmp))

    def test_violation_with_valid_quote_is_verified(self):
        quote = "deeply nested spaghetti code"
        v = self._judge(_envelope({"verdict": "violation", "quote": quote,
                                   "reason": "nested spaghetti"}))
        self.assertEqual(v.outcome, J_VIOLATION)
        self.assertTrue(v.quote_verified)

    def test_violation_with_fabricated_quote_not_verified(self):
        v = self._judge(_envelope({"verdict": "violation",
                                   "quote": "a quote that is not in the span at all",
                                   "reason": "made up"}))
        self.assertEqual(v.outcome, J_VIOLATION)
        self.assertFalse(v.quote_verified)  # -> caller caps to SUSPECTED

    def test_compliant(self):
        v = self._judge(_envelope({"verdict": "compliant", "quote": "", "reason": "fine"}))
        self.assertEqual(v.outcome, J_COMPLIANT)

    def test_garbage_output_is_unclear(self):
        v = self._judge("this is not json at all")
        self.assertEqual(v.outcome, J_UNCLEAR)

    def test_timeout_or_none_is_unclear(self):
        v = self._judge(None)  # runner returns None on timeout / non-zero exit
        self.assertEqual(v.outcome, J_UNCLEAR)

    def test_tolerant_json_extraction(self):
        # Model wraps the object in prose despite instructions.
        inner = 'Sure! {"verdict":"compliant","quote":"","reason":"ok"} done'
        v = self._judge(_envelope(inner))
        self.assertEqual(v.outcome, J_COMPLIANT)


class TestCache(unittest.TestCase):
    def test_cache_hit_skips_runner(self):
        tmp = tempfile.mkdtemp()
        span = make_span("some span text", "/t.jsonl", 1, None)
        calls = {"n": 0}

        def counting_runner(prompt, timeout_s):
            calls["n"] += 1
            return _envelope({"verdict": "compliant", "quote": "", "reason": "ok"})

        v1 = judge_span("R", span, runner=counting_runner, cache_dir=Path(tmp))
        self.assertFalse(v1.cached)
        v2 = judge_span("R", span, runner=counting_runner, cache_dir=Path(tmp))
        self.assertTrue(v2.cached)
        self.assertEqual(calls["n"], 1)  # runner invoked once


class TestRedactionBeforePrompt(unittest.TestCase):
    def test_secret_never_enters_prompt(self):
        raw = "here is a key AKIAIOSFODNN7EXAMPLE in the output"
        span = make_span(raw, "/t.jsonl", 1, None)
        # make_span redacts on the way in.
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", span.text)
        prompt = build_prompt("Never leak secrets.", span)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", prompt)
        self.assertIn("<redacted:aws-key>", prompt)


class TestBudgetAndAggregation(unittest.TestCase):
    def test_budget_caps_live_calls(self):
        tmp = tempfile.mkdtemp()
        spans = [make_span(f"span number {i}", "/t.jsonl", i, None) for i in range(10)]
        calls = {"n": 0}

        def runner(prompt, timeout_s):
            calls["n"] += 1
            return _envelope({"verdict": "compliant", "quote": "", "reason": "ok"})

        candidates = {"r1": ("Rule one", spans)}
        judge_rules(candidates, runner=runner, budget=3, spans_per_rule=10,
                    cache_dir=Path(tmp), show_progress=False)
        self.assertLessEqual(calls["n"], 3)

    def test_verified_violation_wins_aggregation(self):
        tmp = tempfile.mkdtemp()
        span = make_span("clear bad nesting here", "/t.jsonl", 1, None)

        def runner(prompt, timeout_s):
            return _envelope({"verdict": "violation", "quote": "clear bad nesting",
                              "reason": "nested"})

        res = judge_rules({"r1": ("Rule", [span])}, runner=runner, budget=5,
                          cache_dir=Path(tmp), show_progress=False)
        j = res["r1"]
        self.assertIsNotNone(j.verified_violation)


class TestDepthFirst(unittest.TestCase):
    def test_conclusive_rule_stops_early_and_next_rule_reached(self):
        # With workers=1 (sequential), rule 1 concludes on span 1, rule 2 too.
        tmp = tempfile.mkdtemp()
        spans1 = [make_span(f"rule1 span {i} with content", "/t.jsonl", i, None) for i in range(5)]
        spans2 = [make_span(f"rule2 span {i} with content", "/t.jsonl", i, None) for i in range(5)]

        def runner(prompt, timeout_s):
            return _envelope({"verdict": "compliant", "quote": "", "reason": "ok"})

        res = judge_rules({"r1": ("Rule one", spans1), "r2": ("Rule two", spans2)},
                          runner=runner, budget=10, spans_per_rule=5, workers=1,
                          cache_dir=Path(tmp), show_progress=False)
        self.assertEqual(res["r1"].judged_spans, 1)
        self.assertEqual(res["r2"].judged_spans, 1)
        self.assertTrue(res["r1"].any_compliant)
        self.assertTrue(res["r2"].any_compliant)

    def test_coverage_counts_recorded(self):
        tmp = tempfile.mkdtemp()
        spans = [make_span(f"span {i} with real content here", "/t.jsonl", i, None)
                 for i in range(8)]

        def runner(prompt, timeout_s):
            return _envelope({"verdict": "unclear", "quote": "", "reason": "?"})

        res = judge_rules({"r1": ("Rule", spans)}, runner=runner, budget=100,
                          spans_per_rule=5, workers=1, cache_dir=Path(tmp),
                          show_progress=False)
        j = res["r1"]
        # Unclear never concludes -> judges up to the per-rule cap (5).
        self.assertEqual(j.judged_spans, 5)
        self.assertEqual(j.candidate_spans, 5)


class TestConcurrency(unittest.TestCase):
    def test_parallel_batch_judges_all_and_is_thread_safe(self):
        import threading
        tmp = tempfile.mkdtemp()
        spans = [make_span(f"span {i} distinct content here", "/t.jsonl", i, None)
                 for i in range(8)]
        seen = []
        lock = threading.Lock()

        def runner(prompt, timeout_s):
            with lock:
                seen.append(threading.current_thread().name)
            return _envelope({"verdict": "unclear", "quote": "", "reason": "?"})

        res = judge_rules({"r1": ("Rule", spans)}, runner=runner, budget=100,
                          spans_per_rule=8, workers=4, cache_dir=Path(tmp),
                          show_progress=False)
        # All 8 unclear spans judged; work ran on multiple worker threads.
        self.assertEqual(res["r1"].judged_spans, 8)
        self.assertGreater(len({n for n in seen}), 1)

    def test_budget_respected_under_concurrency(self):
        tmp = tempfile.mkdtemp()
        spans = [make_span(f"span {i} distinct content", "/t.jsonl", i, None)
                 for i in range(20)]
        calls = {"n": 0}
        import threading
        lock = threading.Lock()

        def runner(prompt, timeout_s):
            with lock:
                calls["n"] += 1
            return _envelope({"verdict": "unclear", "quote": "", "reason": "?"})

        judge_rules({"r1": ("Rule", spans)}, runner=runner, budget=6,
                    spans_per_rule=20, workers=4, cache_dir=Path(tmp),
                    show_progress=False)
        self.assertLessEqual(calls["n"], 6)


class TestSpanQuality(unittest.TestCase):
    def test_short_span_not_substantive(self):
        self.assertFalse(is_substantive("done."))

    def test_plan_narration_not_substantive(self):
        self.assertFalse(is_substantive("Let me start by reading the files and planning."))

    def test_concrete_decision_is_substantive(self):
        self.assertTrue(is_substantive(
            "I decided to reuse the existing parser because rewriting added risk "
            "for no benefit, so I kept the change minimal."))

    def test_code_block_is_substantive(self):
        self.assertTrue(is_substantive("Here is the fix:\n```python\ndef f():\n    return 1\n```"))

    def test_rank_puts_high_signal_first(self):
        low = make_span("Now I will look at the next thing to consider here.", "/t", 1, None)
        high = make_span("I fixed the bug because the loop was off by one; the diff is minimal.",
                         "/t", 2, None)
        ranked = rank_spans([low, high])
        self.assertEqual(ranked[0].text, high.text)


if __name__ == "__main__":
    unittest.main()
