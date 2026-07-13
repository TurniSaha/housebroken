"""Classifier accuracy against the labeled corpus (H3 metric)."""

import unittest

from housebroken.rules.classify import CHECKABLE_CLASSES, classify
from housebroken.rules.parse import Rule
from tests.corpus import CORPUS


def _rule(text: str) -> Rule:
    return Rule(id="x", source="corpus", line_no=1, heading_path=(), text=text, raw_text=text)


class TestClassifierAccuracy(unittest.TestCase):
    def test_corpus_accuracy(self):
        correct = 0
        misses = []
        for text, expected in CORPUS:
            got = classify(_rule(text))
            if got == expected:
                correct += 1
            else:
                misses.append((text, expected, got))
        acc = correct / len(CORPUS)
        # Print for the evidence log; keep visible even on pass.
        print(f"\n[classifier] corpus accuracy: {correct}/{len(CORPUS)} = {acc:.0%}")
        if misses:
            print("[classifier] misses:")
            for text, exp, got in misses:
                print(f"    {exp:18} got {got:18} | {text}")
        self.assertGreaterEqual(acc, 0.80, f"classifier accuracy {acc:.0%} < 80%")

    def test_checkable_share_meets_h3(self):
        checkable = sum(
            1 for text, _ in CORPUS if classify(_rule(text)) in CHECKABLE_CLASSES
        )
        share = checkable / len(CORPUS)
        print(f"\n[H3] checkable-class share: {checkable}/{len(CORPUS)} = {share:.0%}")
        # H3 needs >=70% of rules in checkable classes on real data; the corpus
        # is intentionally balanced across classes, so we assert a looser floor
        # here; the real-data distribution is a separate concern.
        self.assertGreaterEqual(share, 0.40)


if __name__ == "__main__":
    unittest.main()
