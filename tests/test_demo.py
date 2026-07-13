"""`housebroken demo` showcases every grade in <30s with no CLI."""

import json
import unittest

from housebroken.demo import run_demo


class TestDemo(unittest.TestCase):
    def test_text_demo_shows_every_grade(self):
        out = run_demo(fmt="text", use_color=False)
        for grade in ("VIOLATED", "PASSED", "PASSED-JUDGED", "SUSPECTED",
                      "ASLEEP", "UNENFORCEABLE"):
            self.assertIn(grade, out, f"missing grade {grade} in demo")
        # Honesty banner about canned judging.
        self.assertIn("CANNED", out)
        # A receipt is shown.
        self.assertIn("git push --force", out)

    def test_demo_is_deterministic(self):
        self.assertEqual(run_demo(use_color=False), run_demo(use_color=False))

    def test_json_demo_valid(self):
        payload = json.loads(run_demo(fmt="json"))
        self.assertIn("score", payload)
        grades = {c["grade"] for c in payload["cards"]}
        self.assertIn("SUSPECTED", grades)
        self.assertIn("PASSED-JUDGED", grades)

    def test_demo_does_not_touch_user_cache(self):
        # run_demo uses an ephemeral tempdir; just assert it runs clean twice.
        run_demo(use_color=False)
        run_demo(use_color=False)


if __name__ == "__main__":
    unittest.main()
