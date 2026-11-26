"""Cycle 32 claim pin — the proof-artefact claim is narrowed
to the enforced property.

A proof artefact shows that its declared invariants were
executed against the exact bound tree contents, passed there,
and failed on the pre-change tree (for new invariants) and on
a mutated tree. It shows nothing about undeclared properties
and is not a proof of general correctness. The canonical
CLAIM sentence must appear verbatim in
trust/proofcarry.py, and the over-claim phrases below must
not appear there.

The banned list is chosen against the CLAIM text itself:
the CLAIM contains "not a proof of general correctness",
so the bans target the affirmative over-claim spellings
("proof of correctness for", "proves the change is
correct", ...) that do not collide with that negation.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

CLAIM = (
    "A proof artefact establishes only this: the invariants "
    "it declares were executed by the independent checker "
    "against the exact tree contents bound in the artefact, "
    "each declared check passed on that tree, and each check "
    "was shown to fail on the pre-change tree (for invariants "
    "declared new) and on a mutated tree. It establishes "
    "nothing about properties the change did not declare, "
    "and it is not a proof of general correctness.")

BANNED_PHRASES = (
    "proves the change is correct",
    "guarantees correctness",
    "formally verified",
    "mathematically proven",
    "proof of correctness for",
    "proves correctness",
    "proven correct",
    "correctness is guaranteed",
    "verified to be correct",
)

CLAIM_FILE = "trust/proofcarry.py"


def _normalised(path):
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


class TestCycle32ClaimPin(unittest.TestCase):

    def test_no_overclaim_phrases_in_proofcarry(self):
        text = _normalised(REPO / CLAIM_FILE).lower()
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(
                    phrase, text,
                    f"{CLAIM_FILE} states the over-claim "
                    f"phrase {phrase!r}")

    def test_no_overclaim_phrases_in_design_final(self):
        text = _normalised(
            REPO / "internal" / "cycle32-work"
            / "design-final.md").lower()
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(
                    phrase, text,
                    f"design-final.md states the over-claim "
                    f"phrase {phrase!r}")

    def test_banned_phrases_do_not_collide_with_claim(self):
        # Guard the pin itself: if a banned phrase were a
        # substring of the CLAIM, the two pins would be
        # unsatisfiable together.
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, CLAIM.lower())

    def test_claim_sentence_present_verbatim(self):
        # Case-insensitive, whitespace-normalised (mirrors
        # tests/test_cycle26_claim_pin.py): a module may adapt
        # the sentence's initial capital where grammar
        # requires it; the substance must be verbatim. The
        # module defines CLAIM as adjacent string literals, so
        # the quote characters that split the sentence in the
        # source are removed before the search — what is
        # pinned is the sentence itself, not the literal
        # layout. The imported-constant test below pins the
        # exact value independently of source layout.
        canonical = re.sub(r"\s+", " ", CLAIM).lower()
        raw = (REPO / CLAIM_FILE).read_text(encoding="utf-8")
        text = re.sub(r"\s+", " ", raw.replace('"', ""))
        self.assertIn(canonical, text.lower())

    def test_claim_constant_matches_canonical_text(self):
        from trust.proofcarry import CLAIM as module_claim
        self.assertEqual(
            re.sub(r"\s+", " ", module_claim).strip(), CLAIM)


if __name__ == "__main__":
    unittest.main()
