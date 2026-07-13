"""output-format checker tests (conventional commits)."""

import unittest

from housebroken.check.output_format import (
    FMT_CONVENTIONAL_COMMITS,
    OutputFormatChecker,
    compile_format_rule,
)
from housebroken.rules.parse import Rule
from housebroken.transcript import ToolCall


def _rule(text):
    return Rule(id="fmt", source="s", line_no=1, heading_path=(), text=text, raw_text=text)


def _bash(cmd):
    return ToolCall(name="Bash", input={"command": cmd}, timestamp="2026-01-01T00:00:00Z",
                    session_id="s", file="/t/sess.jsonl", line_no=1)


class TestFormatCompile(unittest.TestCase):
    def test_conventional_commits_compiles(self):
        c = compile_format_rule(_rule("Use conventional commit messages."))
        self.assertEqual(c.check_class, FMT_CONVENTIONAL_COMMITS)


class TestFormatCheck(unittest.TestCase):
    def setUp(self):
        self.rule = _rule("Use conventional commit messages.")
        self.check = compile_format_rule(self.rule)

    def _run(self, cmd):
        chk = OutputFormatChecker([self.check])
        chk.observe(_bash(cmd))
        return chk.receipts_for(self.rule.id)

    def test_non_conventional_message_flagged(self):
        r = self._run("git commit -m 'wip stuff'")
        self.assertEqual(len(r), 1)
        self.assertIn("wip stuff", r[0].span)

    def test_conventional_message_clean(self):
        self.assertEqual(len(self._run("git commit -m 'feat: add parser'")), 0)

    def test_conventional_with_scope_clean(self):
        self.assertEqual(len(self._run("git commit -m 'fix(cli): handle empty input'")), 0)

    def test_double_quoted_message(self):
        r = self._run('git commit -m "broke the build"')
        self.assertEqual(len(r), 1)

    def test_non_commit_command_ignored(self):
        self.assertEqual(len(self._run("git status")), 0)


if __name__ == "__main__":
    unittest.main()
