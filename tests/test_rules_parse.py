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


if __name__ == "__main__":
    unittest.main()
