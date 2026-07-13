"""Anchor-event span selection tests."""

import unittest

from housebroken.anchor import (
    AnchorSpec,
    build_window,
    derive_anchor,
    quotes_rule_verbatim,
)
from housebroken.transcript import AssistantMsg, ToolCall


def _bash(cmd, line=1):
    return ToolCall(name="Bash", input={"command": cmd}, timestamp=None,
                    session_id="s", file="/t.jsonl", line_no=line)


def _edit(path, line=1):
    return ToolCall(name="Edit", input={"file_path": path}, timestamp=None,
                    session_id="s", file="/t.jsonl", line_no=line)


def _msg(text):
    return AssistantMsg(text=text, timestamp=None, session_id="s", file="/t.jsonl", line_no=1)


class TestDeriveAnchor(unittest.TestCase):
    def test_code_rule_anchors_to_edits(self):
        a = derive_anchor("Prefer small, surgical changes over sweeping rewrites.")
        self.assertTrue(a.edit)
        self.assertTrue(a.anchorable)

    def test_test_rule_anchors_to_tests(self):
        a = derive_anchor("Always mock external services in unit tests.")
        self.assertTrue(a.test)

    def test_deploy_rule_anchors_to_deploy(self):
        a = derive_anchor("Verify the deploy succeeded before closing the ticket.")
        self.assertTrue(a.deploy)

    def test_vibe_rule_not_anchorable(self):
        a = derive_anchor("Have good taste.")
        self.assertFalse(a.anchorable)


class TestIsAnchor(unittest.TestCase):
    def test_edit_spec_matches_edit_tool(self):
        spec = AnchorSpec(edit=True)
        self.assertTrue(spec.is_anchor(_edit("src/app.py")))
        self.assertFalse(spec.is_anchor(_bash("ls")))

    def test_test_spec_matches_test_file_edit_and_test_cmd(self):
        spec = AnchorSpec(test=True)
        self.assertTrue(spec.is_anchor(_edit("tests/test_app.py")))
        self.assertTrue(spec.is_anchor(_bash("pytest -q")))
        self.assertFalse(spec.is_anchor(_edit("src/app.py")))

    def test_git_spec_matches_git_commit(self):
        spec = AnchorSpec(git=True)
        self.assertTrue(spec.is_anchor(_bash("git commit -m x")))
        self.assertFalse(spec.is_anchor(_bash("ls")))


class TestBuildWindow(unittest.TestCase):
    def test_window_includes_surrounding_context(self):
        events = [
            _msg("I will refactor the helper for clarity."),
            _edit("src/helper.py"),
            _bash("pytest"),
        ]
        window = build_window(events, anchor_idx=1)
        self.assertIn("refactor the helper", window)
        self.assertIn("[Edit] src/helper.py", window)
        self.assertIn("▶", window)  # anchor marker

    def test_window_char_budget_enforced(self):
        events = [_msg("x" * 5000), _edit("a.py")]
        window = build_window(events, anchor_idx=1)
        self.assertLessEqual(len(window), 1600)


class TestVerbatimDownrank(unittest.TestCase):
    def test_span_quoting_rule_is_flagged(self):
        rule = "Never use the force flag when pushing to a shared branch."
        span = "The rule says: Never use the force flag when pushing to a shared branch."
        self.assertTrue(quotes_rule_verbatim(rule, span))

    def test_unrelated_span_not_flagged(self):
        rule = "Prefer small, surgical changes over sweeping rewrites."
        span = "I edited the config file and restarted the service."
        self.assertFalse(quotes_rule_verbatim(rule, span))


if __name__ == "__main__":
    unittest.main()
