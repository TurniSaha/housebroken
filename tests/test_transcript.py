"""Parser robustness + normalization tests (stdlib unittest only)."""

import tempfile
import unittest
from pathlib import Path

from housebroken.transcript import (
    AssistantMsg,
    ToolCall,
    UserMsg,
    _Counter,
    stream_events,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_session.jsonl"


def _write(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return tmp.name


class TestRobustness(unittest.TestCase):
    def test_malformed_and_truncated_never_crash(self):
        path = _write([
            '{"type": "user", "message": {"role": "user", "content": "hi"}}',
            "not json at all {{{",
            '{"type": "assistant", "message": {"role": "assist',  # truncated
            "",  # blank
            "42",  # valid json but not an object
            '{"type": "mode", "mode": "default"}',  # known noise
            '{"type": "totally-unknown-record"}',  # unknown type
        ])
        c = _Counter()
        events = list(stream_events(path, counter=c))
        # Only the first line is a real message.
        self.assertEqual(c.user_msgs, 1)
        self.assertEqual(c.malformed_lines, 2)  # "not json" + truncated
        self.assertIn("mode", c.skipped_types)
        self.assertIn("totally-unknown-record", c.skipped_types)
        self.assertIn("<<non-object>>", c.skipped_types)  # the bare 42
        self.assertEqual(len(events), 1)

    def test_missing_file_would_raise_but_bad_content_does_not(self):
        path = _write(['{"garbage": true}', '{"type": 123}'])
        c = _Counter()
        events = list(stream_events(path, counter=c))
        self.assertEqual(events, [])
        # {"garbage":true} has no type -> skipped as <<notype>>
        self.assertIn("<<notype>>", c.skipped_types)


class TestNormalization(unittest.TestCase):
    def test_fixture_yields_expected_events(self):
        c = _Counter()
        events = list(stream_events(FIXTURE, counter=c))
        tool_calls = [e for e in events if isinstance(e, ToolCall)]
        assistant = [e for e in events if isinstance(e, AssistantMsg)]
        users = [e for e in events if isinstance(e, UserMsg)]

        # Two Bash commits/pushes + one Edit anchor in the fixture.
        self.assertEqual(len(tool_calls), 3)
        self.assertEqual(sum(1 for tc in tool_calls if tc.name == "Bash"), 2)
        self.assertTrue(any("--no-verify" in tc.command() for tc in tool_calls))
        # Receipts need real coordinates.
        for tc in tool_calls:
            self.assertTrue(tc.file.endswith("synthetic_session.jsonl"))
            self.assertGreater(tc.line_no, 0)
            self.assertTrue(tc.timestamp and tc.timestamp.startswith("2026-"))
            self.assertEqual(tc.session_id, "0000fixture-0000-0000-0000-000000000001")

        self.assertGreaterEqual(len(assistant), 1)
        self.assertGreaterEqual(len(users), 2)
        # The deliberately malformed fixture line is counted.
        self.assertEqual(c.malformed_lines, 1)

    def test_str_content_becomes_text_block(self):
        path = _write(['{"type":"user","message":{"role":"user","content":"just text"}}'])
        events = list(stream_events(path))
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], UserMsg)
        self.assertEqual(events[0].text, "just text")


if __name__ == "__main__":
    unittest.main()
