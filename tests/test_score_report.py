"""End-to-end scoring + report tests on the synthetic fixture."""

import json
import tempfile
import unittest
from pathlib import Path

from housebroken.report import render_json, render_markdown, render_text
from housebroken.rules.parse import parse_file
from housebroken.score import (
    ASLEEP,
    DELETE,
    NEEDS_JUDGE,
    PASSED,
    PASSED_JUDGED,
    SUSPECTED,
    VIOLATED,
    scan,
)

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "fixtures" / "synthetic_rules.md"
SESSION = ROOT / "fixtures" / "synthetic_session.jsonl"


class TestScan(unittest.TestCase):
    def setUp(self):
        rules = parse_file(RULES)
        self.result = scan(rules, (SESSION,), rules_files=1)
        self.by_text = {c.rule.text: c for c in self.result.cards}

    def test_every_grade_present(self):
        grades = {c.grade for c in self.result.cards}
        self.assertIn(VIOLATED, grades)
        self.assertIn(PASSED, grades)
        self.assertIn(ASLEEP, grades)
        self.assertIn(NEEDS_JUDGE, grades)

    def test_no_verify_violated_with_receipt(self):
        card = next(c for t, c in self.by_text.items() if "--no-verify" in t)
        self.assertEqual(card.grade, VIOLATED)
        self.assertTrue(card.receipts)
        self.assertIn("--no-verify", card.receipts[0].span)

    def test_sequence_violation(self):
        card = next(c for t, c in self.by_text.items() if "before committing" in t)
        self.assertEqual(card.grade, VIOLATED)
        self.assertEqual(card.rule_class, "required-sequence")

    def test_conventional_commit_violation(self):
        card = next(c for t, c in self.by_text.items() if "conventional commit" in t)
        self.assertEqual(card.grade, VIOLATED)

    def test_asleep_rule_has_token_cost_and_delete_verdict(self):
        card = next(c for t, c in self.by_text.items() if "no-ssl-verify" in t)
        self.assertEqual(card.grade, ASLEEP)
        self.assertGreater(card.wasted_tokens, 0)
        self.assertEqual(card.verdict, DELETE)

    def test_passed_rule_applicable(self):
        card = next(c for t, c in self.by_text.items() if "--force" in t)
        self.assertEqual(card.grade, PASSED)
        self.assertGreaterEqual(card.applicable_sessions, 1)

    def test_score_is_sane(self):
        self.assertGreaterEqual(self.result.score, 0)
        self.assertLessEqual(self.result.score, 100)


class TestRenderers(unittest.TestCase):
    def setUp(self):
        rules = parse_file(RULES)
        self.result = scan(rules, (SESSION,), rules_files=1)

    def test_text_renders_without_ansi_when_disabled(self):
        out = render_text(self.result, use_color=False)
        self.assertIn("HOUSEBROKEN REPORT", out)
        self.assertNotIn("\033[", out)

    def test_json_is_valid_and_stable(self):
        out = render_json(self.result)
        payload = json.loads(out)
        self.assertIn("score", payload)
        self.assertIn("cards", payload)
        # Stable: same input -> byte-identical output.
        self.assertEqual(out, render_json(self.result))

    def test_markdown_has_table(self):
        out = render_markdown(self.result)
        self.assertIn("| Grade |", out)
        self.assertIn("Verdicts:", out)

    def test_inconclusive_judge_line_framed_as_trust(self):
        # When the judge samples spans but nothing concludes, one honest line
        # appears framing the conservatism as the trust feature.
        rules = parse_file(RULES)
        runner = lambda p, t: json.dumps(
            {"type": "result",
             "result": json.dumps({"verdict": "unclear", "quote": "", "reason": "?"})})
        result = scan(rules, (SESSION,), rules_files=1, use_judge=True,
                      judge_runner=runner, judge_cache_dir=Path(tempfile.mkdtemp()))
        out = render_text(result, use_color=False)
        if any(c.judged_spans for c in result.cards
               if c.grade == "NEEDS-JUDGE"):
            self.assertIn("no verdict met the evidence bar", out)
            self.assertIn("never accuses without a receipt", out)


class TestRedactionReachesCard(unittest.TestCase):
    def test_secret_in_command_is_redacted_in_receipt(self):
        # A synthetic transcript where a forbidden flag rides alongside a secret.
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write(
            '{"type":"assistant","sessionId":"s","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash",'
            '"input":{"command":"git commit -m \\"wip\\" --no-verify # AKIAIOSFODNN7EXAMPLE"}}]}}\n'
        )
        tmp.close()
        rules = parse_file(RULES)
        result = scan(rules, (Path(tmp.name),), rules_files=1)
        card = next(c for c in result.cards if "--no-verify" in c.rule.text)
        self.assertTrue(card.receipts)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", card.receipts[0].span)


class TestJudgeIntegration(unittest.TestCase):
    """scan() folds the mock judge into behavioral-prose grades."""

    def _scan(self, runner):
        rules = parse_file(RULES)
        return scan(
            rules, (SESSION,), rules_files=1,
            use_judge=True, judge_runner=runner,
            judge_cache_dir=Path(tempfile.mkdtemp()),
        )

    def _envelope(self, obj):
        return json.dumps({"type": "result", "result": json.dumps(obj)})

    def test_compliant_judge_gives_passed_judged(self):
        # Only ANCHORABLE prose rules (topic maps to a concrete event, and the
        # fixture has that event) get judged; the compliant mock -> PASSED-JUDGED.
        runner = lambda p, t: self._envelope(
            {"verdict": "compliant", "quote": "", "reason": "fine"})
        result = self._scan(runner)
        judged = [c for c in result.cards if c.grade == PASSED_JUDGED]
        self.assertTrue(judged, "expected at least one PASSED-JUDGED anchorable rule")
        # Non-anchorable prose rules stay NEEDS-JUDGE with an honest note.
        needs = [c for c in result.cards
                 if c.rule_class == "behavioral-prose" and c.grade == NEEDS_JUDGE]
        for c in needs:
            self.assertTrue(c.judge_reason, "NEEDS-JUDGE rule should carry a note")

    def test_fabricated_quote_gives_suspected_not_violated(self):
        runner = lambda p, t: self._envelope(
            {"verdict": "violation", "quote": "THIS_IS_NOT_IN_ANY_SPAN_XYZ",
             "reason": "made up"})
        result = self._scan(runner)
        prose = [c for c in result.cards if c.rule_class == "behavioral-prose"]
        self.assertTrue(any(c.grade == SUSPECTED for c in prose))
        # SUSPECTED must never be counted as VIOLATED.
        self.assertFalse(any(c.grade == VIOLATED for c in prose))

    def test_no_judge_leaves_needs_judge(self):
        rules = parse_file(RULES)
        result = scan(rules, (SESSION,), rules_files=1, use_judge=False)
        prose = [c for c in result.cards if c.rule_class == "behavioral-prose"]
        self.assertTrue(all(c.grade == NEEDS_JUDGE for c in prose))


if __name__ == "__main__":
    unittest.main()
