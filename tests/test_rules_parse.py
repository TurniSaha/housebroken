"""Rule parsing tests against the synthetic rules file."""

import unittest
from pathlib import Path

from housebroken.rules.classify import FORBIDDEN_ACTION, classify
from housebroken.rules.parse import parse_file

RULES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_rules.md"


class TestRuleParse(unittest.TestCase):
    def setUp(self):
        self.rules = parse_file(RULES)
        self.texts = [r.text for r in self.rules]

    def test_extracts_imperative_bullets(self):
        joined = " || ".join(self.texts)
        self.assertIn("Never use --no-verify when committing or pushing.", self.texts)
        self.assertTrue(any("git push --force" in t for t in self.texts))
        self.assertTrue(any("No emojis" in t for t in self.texts))

    def test_heading_scope_captured(self):
        nv = next(r for r in self.rules if "--no-verify" in r.text)
        self.assertIn("Git hygiene", nv.heading_path)

    def test_ids_are_stable_and_unique(self):
        ids = [r.id for r in self.rules]
        self.assertEqual(len(ids), len(set(ids)))
        # Re-parse -> identical ids (stable hash).
        again = [r.id for r in parse_file(RULES)]
        self.assertEqual(ids, again)

    def test_prose_not_slurped_as_rule(self):
        # The intro sentence "These are fully synthetic rules ..." is prose.
        self.assertFalse(any("fully synthetic rules used" in t for t in self.texts))

    def test_forbidden_classification(self):
        nv = next(r for r in self.rules if "--no-verify" in r.text)
        self.assertEqual(classify(nv), FORBIDDEN_ACTION)


class TestRuleShapeFilter(unittest.TestCase):
    """The _is_rule_shaped guard drops non-rule fragments."""

    def _parse_lines(self, body):
        import tempfile
        from housebroken.rules.parse import parse_file
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(body)
        tmp.close()
        return [r.text for r in parse_file(tmp.name)]

    def test_colon_intro_dropped(self):
        texts = self._parse_lines("## H\n\n- MANDATORY review triggers:\n- Always run the linter.\n")
        self.assertNotIn("MANDATORY review triggers:", texts)
        self.assertTrue(any("run the linter" in t for t in texts))

    def test_path_placeholder_fragment_dropped(self):
        texts = self._parse_lines("## H\n\n- canonical: some-org/<name> (created by a script)\n")
        self.assertEqual(texts, [])

    def test_short_allcaps_label_dropped(self):
        texts = self._parse_lines("## H\n\n- TODO Items\n- Always verify the build first.\n")
        self.assertNotIn("TODO Items", texts)

    def test_definition_label_bullet_dropped(self):
        # `- **Approve**: No CRITICAL...` is a label->value pair, not a directive.
        body = (
            "## Approval Criteria\n\n"
            "- **Approve**: No CRITICAL or HIGH issues\n"
            "- **Warning**: Only HIGH issues (merge with caution)\n"
            "- **Block**: CRITICAL issues found\n"
            "- Always run the full test suite before approving.\n"
        )
        texts = self._parse_lines(body)
        self.assertNotIn("Approve: No CRITICAL or HIGH issues", texts)
        self.assertNotIn("Warning: Only HIGH issues (merge with caution)", texts)
        self.assertNotIn("Block: CRITICAL issues found", texts)
        # The genuine directive on the same list survives.
        self.assertTrue(any("run the full test suite" in t for t in texts))

    def test_glossary_dash_description_dropped(self):
        # `- `common/` — language-agnostic principles` is a legend entry.
        body = (
            "## Layout\n\n"
            "- `common/` — language-agnostic principles (always applied)\n"
            "- `<language>/` — language-specific extensions of common/\n"
            "- Always keep rules under 400 lines.\n"
        )
        texts = self._parse_lines(body)
        self.assertFalse(any("language-agnostic principles" in t for t in texts))
        self.assertFalse(any("language-specific extensions" in t for t in texts))
        self.assertTrue(any("under 400 lines" in t for t in texts))

    def test_numbered_procedure_substeps_dropped(self):
        # Steps inside a numbered how-to are procedure narration, not standalone
        # rules to grade an agent against.
        body = (
            "## TDD workflow\n\n"
            "MANDATORY workflow:\n"
            "1. Write test first (RED)\n"
            "2. Run test - it should FAIL\n"
            "3. Write minimal implementation (GREEN)\n"
            "4. Run test - it should PASS\n"
        )
        texts = self._parse_lines(body)
        self.assertNotIn("Run test - it should FAIL", texts)
        self.assertNotIn("Run test - it should PASS", texts)
        self.assertNotIn("Write minimal implementation (GREEN)", texts)

    def test_security_response_substeps_dropped(self):
        body = (
            "## Security Response Protocol\n\n"
            "If security issue found:\n"
            "1. STOP immediately\n"
            "2. Fix incrementally\n"
            "3. Rotate any exposed secrets\n"
        )
        texts = self._parse_lines(body)
        self.assertNotIn("STOP immediately", texts)
        self.assertNotIn("Fix incrementally", texts)

    def test_real_imperative_bullets_still_kept(self):
        # Guard against over-tightening: ordinary rules must survive.
        body = (
            "## Rules\n\n"
            "- Never use the --force flag when pushing to a shared branch.\n"
            "- Always run tests before committing.\n"
            "- Use conventional commit messages.\n"
            "1. Never hardcode secrets in source code.\n"
        )
        texts = self._parse_lines(body)
        self.assertTrue(any("--force flag" in t for t in texts))
        self.assertTrue(any("run tests before committing" in t for t in texts))
        self.assertTrue(any("conventional commit messages" in t for t in texts))
        self.assertTrue(any("hardcode secrets" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
