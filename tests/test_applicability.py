"""Applicability trigger tests."""

import unittest

from housebroken.applicability import compile_trigger
from housebroken.rules.parse import Rule
from housebroken.transcript import AssistantMsg, ToolCall


def _rule(text):
    return Rule(id="a", source="s", line_no=1, heading_path=(), text=text, raw_text=text)


def _bash(cmd):
    return ToolCall(name="Bash", input={"command": cmd}, timestamp=None,
                    session_id="s", file="/t.jsonl", line_no=1)


def _assistant(text):
    return AssistantMsg(text=text, timestamp=None, session_id="s", file="/t.jsonl", line_no=1)


class TestApplicability(unittest.TestCase):
    def test_git_rule_fires_on_git_command(self):
        trig = compile_trigger(_rule("Never use --force when pushing."))
        self.assertTrue(trig.fires(_bash("git push origin main")))
        self.assertFalse(trig.fires(_bash("ls -la")))

    def test_sql_rule_asleep_in_git_session(self):
        trig = compile_trigger(_rule("Never build SQL queries with string concatenation."))
        self.assertFalse(trig.fires(_bash("git commit -m x")))
        self.assertTrue(trig.fires(_assistant("here is the SQL query")))

    def test_universal_disposition_always_applicable(self):
        trig = compile_trigger(_rule("Prefer simplicity over cleverness."))
        self.assertTrue(trig.always)
        self.assertTrue(trig.fires(_bash("anything at all")))

    def test_code_rule_fires_on_edit_tool(self):
        trig = compile_trigger(_rule("Keep functions small and focused."))
        edit = ToolCall(name="Edit", input={}, timestamp=None, session_id="s",
                        file="/t.jsonl", line_no=1)
        self.assertTrue(trig.fires(edit))

    def test_test_rule_fires_on_pytest(self):
        trig = compile_trigger(_rule("Run the test suite before committing."))
        self.assertTrue(trig.fires(_bash("pytest -q")))


if __name__ == "__main__":
    unittest.main()
