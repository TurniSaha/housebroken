"""required-sequence checker tests."""

import unittest

from housebroken.check.sequence import (
    SEQ_TESTS_BEFORE_COMMIT,
    SEQ_UNCOMPILED,
    SequenceChecker,
    compile_sequence_rule,
)
from housebroken.rules.parse import Rule
from housebroken.transcript import ToolCall


def _rule(text):
    return Rule(id="seq", source="s", line_no=1, heading_path=(), text=text, raw_text=text)


def _bash(cmd, line=1):
    return ToolCall(name="Bash", input={"command": cmd}, timestamp="2026-01-01T00:00:00Z",
                    session_id="s", file="/t/sess.jsonl", line_no=line)


class TestSequenceCompile(unittest.TestCase):
    def test_tests_before_commit_compiles(self):
        c = compile_sequence_rule(_rule("Run the test suite before committing."))
        self.assertEqual(c.check_class, SEQ_TESTS_BEFORE_COMMIT)

    def test_non_sequence_does_not_compile(self):
        c = compile_sequence_rule(_rule("Prefer simplicity over cleverness."))
        self.assertEqual(c.check_class, SEQ_UNCOMPILED)


class TestSequenceCheck(unittest.TestCase):
    def setUp(self):
        self.rule = _rule("Run the test suite before committing.")
        self.check = compile_sequence_rule(self.rule)

    def test_commit_without_prior_test_is_violation(self):
        chk = SequenceChecker([self.check])
        chk.observe(_bash("git commit -m 'x'", line=5))
        chk.finish_session()
        receipts = chk.receipts_for(self.rule.id)
        self.assertEqual(len(receipts), 1)
        self.assertIn("no prior test run", receipts[0].span)
        self.assertEqual(receipts[0].line_no, 5)

    def test_test_then_commit_is_clean(self):
        chk = SequenceChecker([self.check])
        chk.observe(_bash("pytest -q"))
        chk.observe(_bash("git commit -m 'x'"))
        chk.finish_session()
        self.assertEqual(len(chk.receipts_for(self.rule.id)), 0)

    def test_session_boundary_resets_gate(self):
        chk = SequenceChecker([self.check])
        # Session 1: a test run satisfies the gate.
        chk.observe(_bash("pytest"))
        chk.observe(_bash("git commit -m 'a'"))
        chk.finish_session()
        # Session 2: a commit with no test in THIS session must be flagged.
        chk.observe(_bash("git commit -m 'b'", line=9))
        chk.finish_session()
        self.assertEqual(len(chk.receipts_for(self.rule.id)), 1)


if __name__ == "__main__":
    unittest.main()
