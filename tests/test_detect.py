"""Forbidden-action detection: violation found with correct receipt, no false positive."""

import tempfile
import unittest
from pathlib import Path

from housebroken.check.detect import (
    CHECK_LITERAL,
    ForbiddenActionChecker,
    compile_rules,
)
from housebroken.rules.parse import parse_file, parse_files
from housebroken.transcript import _Counter, stream_events

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "fixtures" / "synthetic_rules.md"
SESSION = ROOT / "fixtures" / "synthetic_session.jsonl"


def _run(rules, session_path):
    checks = compile_rules(rules)
    checker = ForbiddenActionChecker(checks)
    for ev in stream_events(session_path, counter=_Counter()):
        checker.observe(ev)
    return {r.rule.text: r for r in checker.results()}


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.rules = parse_file(RULES)
        self.results = _run(self.rules, SESSION)

    def test_no_verify_violation_with_receipt(self):
        r = next(v for k, v in self.results.items() if "--no-verify" in k)
        self.assertTrue(r.violated)
        self.assertEqual(len(r.receipts), 1)
        rc = r.receipts[0]
        # Receipt carries the exact offending command + coordinates.
        self.assertIn("--no-verify", rc.span)
        self.assertIn("git commit", rc.span)
        self.assertTrue(rc.session_file.endswith("synthetic_session.jsonl"))
        self.assertGreater(rc.line_no, 0)
        self.assertTrue(rc.timestamp.startswith("2026-"))
        self.assertIn("--no-verify", rc.rule_text)

    def test_benign_commit_not_flagged(self):
        # The clean `git commit -m 'feat: add parser'` must NOT create a receipt.
        r = next(v for k, v in self.results.items() if "--no-verify" in k)
        for rc in r.receipts:
            self.assertNotIn("feat: add parser", rc.span)

    def test_emoji_rule_flags_emoji_output(self):
        r = next((v for k, v in self.results.items() if "emoji" in k.lower()), None)
        self.assertIsNotNone(r)
        self.assertTrue(r.violated)

    def test_git_push_force_no_false_positive(self):
        # No `git push --force` occurs in the fixture -> checked but clean.
        r = next((v for k, v in self.results.items() if "--force" in k), None)
        self.assertIsNotNone(r)
        self.assertEqual(r.check_class, CHECK_LITERAL)
        self.assertFalse(r.violated)

    def test_prose_rule_not_compiled(self):
        # "Act like a senior engineer." is not a forbidden-action; not checked.
        r = next((v for k, v in self.results.items() if "senior engineer" in k), None)
        self.assertIsNotNone(r)
        self.assertFalse(r.checked)

    def test_mention_in_prose_is_not_a_command_match(self):
        # A rules-style transcript that only *mentions* --no-verify in prose text
        # must not trigger the command checker (precision guard).
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write(
            '{"type":"assistant","sessionId":"s","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"assistant","content":[{"type":"text",'
            '"text":"I will not pass --no-verify to git."}]}}\n'
        )
        tmp.close()
        results = _run(self.rules, tmp.name)
        r = next(v for k, v in results.items() if "--no-verify" in k)
        self.assertFalse(r.violated)  # prose mention != a Bash command


if __name__ == "__main__":
    unittest.main()
