"""Graceful-degradation tests: no CLI, empty/huge/malformed history."""

import json
import os
import resource
import tempfile
import unittest
from pathlib import Path

from housebroken.check.judge import cli_available
from housebroken.rules.parse import parse_file
from housebroken.score import NEEDS_JUDGE, scan

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "fixtures" / "synthetic_rules.md"
SESSION = ROOT / "fixtures" / "synthetic_session.jsonl"


class TestNoCLI(unittest.TestCase):
    def test_cli_absent_when_path_scrubbed(self):
        old = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/nonexistent-bin-dir-xyz"
            self.assertFalse(cli_available())
        finally:
            os.environ["PATH"] = old

    def test_scan_without_judge_leaves_needs_judge(self):
        rules = parse_file(RULES)
        result = scan(rules, (SESSION,), rules_files=1, use_judge=False)
        prose = [c for c in result.cards if c.rule_class == "behavioral-prose"]
        self.assertTrue(all(c.grade == NEEDS_JUDGE for c in prose))


class TestEmptyHistory(unittest.TestCase):
    def test_no_transcripts(self):
        rules = parse_file(RULES)
        result = scan(rules, (), rules_files=1)
        self.assertEqual(result.sessions, 0)
        # No traceback; every rule still gets a card.
        self.assertEqual(len(result.cards), len(rules))

    def test_empty_dir_discovers_nothing(self):
        from housebroken.discover import find_transcripts
        empty = Path(tempfile.mkdtemp())
        self.assertEqual(find_transcripts(empty, days=14), ())


class TestExcludeProject(unittest.TestCase):
    def test_session_in_project_matches_encoded_path(self):
        from housebroken.score import _session_in_project
        # Claude Code encodes cwd slashes as dashes in the project dir name.
        tpath = "/home/u/.claude/projects/-home-u-myproj/abc.jsonl"
        self.assertTrue(_session_in_project(tpath, "/home/u/myproj"))
        self.assertFalse(_session_in_project(tpath, "/home/u/other"))

    def test_no_exclude_is_false(self):
        from housebroken.score import _session_in_project
        self.assertFalse(_session_in_project("/any/path.jsonl", None))


class TestMalformed(unittest.TestCase):
    def test_all_garbage_file_does_not_crash(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        tmp.write("not json\n{broken\n\x00\x01\x02\n42\n")
        tmp.close()
        rules = parse_file(RULES)
        result = scan(rules, (Path(tmp.name),), rules_files=1)
        self.assertEqual(result.sessions, 1)
        self.assertGreaterEqual(result.stats.malformed_lines, 1)


class TestHugeHistory(unittest.TestCase):
    def test_100mb_jsonl_streams_without_blowing_memory(self):
        # Generate ~100MB of valid tool-call records on the fly.
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        rec = {
            "type": "assistant", "sessionId": "s", "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "git status  # " + "x" * 200}}]},
        }
        line = json.dumps(rec) + "\n"
        target_bytes = 100 * 1024 * 1024
        written = 0
        while written < target_bytes:
            tmp.write(line)
            written += len(line)
        tmp.close()

        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rules = parse_file(RULES)
        result = scan(rules, (Path(tmp.name),), rules_files=1, use_judge=False)
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # Completed over a 100MB file.
        self.assertEqual(result.sessions, 1)
        self.assertGreater(result.stats.tool_calls, 100000)
        # Memory growth must be far below the file size — streaming, not loading.
        # ru_maxrss is bytes on macOS, KB on Linux; normalize to MB conservatively.
        growth = after - before
        unit_mb = 1024 * 1024 if os.uname().sysname == "Darwin" else 1024
        growth_mb = growth / unit_mb
        self.assertLess(growth_mb, 60, f"memory grew {growth_mb:.0f}MB over a 100MB file")
        os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
