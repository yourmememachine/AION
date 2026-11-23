"""Cycle 26 claim pin — the supersession claim is narrowed to
the enforced property (CROSS-CHECK-19, seat-gpt FIX 0.91,
Option A).

The cycle-25 mechanism proves that supersession requires a
separately invoked, cryptographically independent approval
operation outside the adopter's automated recovery path. It
does NOT prove human deliberation, and the tree must not say
it does: the over-claim phrases that cycle 25 used
("deliberate separate act" and kin) are banned from the
supersession-claim source files, and the canonical narrowed
sentence must be present where the trust claim is stated.

History is exempt: internal/DECISION-CONSUMPTION-HEAD.md's
earlier addenda legitimately quote the superseded phrasing,
so for that file this pin asserts only that Addendum 6
exists and carries the canonical narrowing.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

CANONICAL_CLAIM = (
    "Supersession requires a separately invoked, "
    "cryptographically independent approval operation — a "
    "standalone tool invocation, with its own inputs, "
    "producing its own signed artefact under its own "
    "dedicated key — outside the adopter's automated "
    "recovery path. The mechanism does not establish that "
    "the invocation was performed by a human, nor that no "
    "other unattended automation invoked the tool.")

BANNED_PHRASES = (
    "deliberate separate act",
    "deliberate act",
    "human-paced act",
    "deliberate tool invocation",
    "deliberate approval act",
    "deliberate, separate approval act",
    "make the *act* deliberate",
    "deliberate transcription",
    "human-paced",
)

# Source files that state the supersession guarantee.
CLAIM_FILES = (
    "trust/supersession_approval.py",
    "trust/supersession_approval_tool.py",
    "trust/pin_adoption.py",
    "deploy/verifier-identity/README.md",
    "internal/cycle25-work/design-approval.md",
    "signing/pin_ceremony.py",
    "trust/runner.py",
)

# Files whose trust-claim text must carry the canonical
# sentence in substance (line wrapping is normalised away).
CANONICAL_FILES = (
    "trust/supersession_approval.py",
    "trust/pin_adoption.py",
)


def _normalised(path):
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


class TestCycle26ClaimPin(unittest.TestCase):

    def test_no_overclaim_phrases_in_claim_files(self):
        for rel in CLAIM_FILES:
            with self.subTest(file=rel):
                text = _normalised(REPO / rel).lower()
                for phrase in BANNED_PHRASES:
                    self.assertNotIn(
                        phrase, text,
                        f"{rel} still states the over-claim "
                        f"phrase {phrase!r}")

    def test_canonical_claim_present_in_claim_modules(self):
        # Case-insensitive: a module may adapt the sentence's
        # initial capital where grammar requires it (e.g.
        # after a colon); the substance must be verbatim.
        canonical = re.sub(r"\s+", " ", CANONICAL_CLAIM).lower()
        for rel in CANONICAL_FILES:
            with self.subTest(file=rel):
                self.assertIn(
                    canonical, _normalised(REPO / rel).lower())

    def test_decision_addendum_6_carries_the_narrowing(self):
        text = _normalised(
            REPO / "internal" / "DECISION-CONSUMPTION-HEAD.md")
        marker = "Addendum 6 — cycle 26: claim narrowed to " \
                 "the enforced property"
        self.assertIn(marker, text)
        addendum = text.split(marker, 1)[1]
        canonical = re.sub(r"\s+", " ", CANONICAL_CLAIM)
        self.assertIn(canonical, addendum)
        # Addendum 6 records that the old phrasing is
        # superseded as claim wording, mechanism unchanged.
        self.assertIn("SUPERSEDED as claim wording", addendum)
        self.assertIn("mechanism is unchanged", addendum)


if __name__ == "__main__":
    unittest.main()
