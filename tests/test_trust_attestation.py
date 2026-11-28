"""Unit tests for the sealed-eval attestation (trust/attestation)
— score-exactness pins from the cycle-8 review.

The signed payload stores correct/n, never the presented score;
a presented score that differs at all was not the signed score.
The pre-fix tolerance check (abs diff > 1e-9) let NaN through
(every NaN comparison is False) and crashed on huge ints.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import SigningError, make_signing_key
from trust.attestation import scope_root_for, sign_eval_attestation, \
    verify_eval_attestation

KEY = make_signing_key(bytes(range(96, 128)))


def report(score=1.0, correct=2, n=2):
    return {"set": "sealed", "version": 3, "n": n, "correct": correct,
            "score": score, "manifest_hash": "a" * 64,
            "evaluated_at": "2026-11-20T12:00:00+00:00"}


def sign(rep):
    return sign_eval_attestation(
        rep, signing_key=KEY, signer_id="verifier-svc",
        actor="verifier-actor", registry_digest="b" * 64,
        answers_hash="c" * 64, now="2026-11-20T12:00:00+00:00")


class ScoreExactnessTests(unittest.TestCase):
    def test_exact_score_signs_and_verifies(self):
        record = sign(report())
        self.assertEqual(verify_eval_attestation(
            record, signing_key=KEY,
            now="2026-11-20T12:05:00+00:00"), ())

    def test_nan_score_refused_at_sign(self):
        with self.assertRaises(SigningError):
            sign(report(score=float("nan")))

    def test_huge_int_score_refused_at_sign_not_crash(self):
        with self.assertRaises(SigningError):
            sign(report(score=10 ** 400, correct=1, n=3))

    def test_inexact_score_refused_at_sign(self):
        with self.assertRaises(SigningError):
            sign(report(score=0.9999999995, correct=2, n=2))

    def test_transplanted_score_fails_verify(self):
        record = sign(report())
        record["payload"]["score"] = 0.0
        reasons = verify_eval_attestation(
            record, signing_key=KEY, now="2026-11-20T12:05:00+00:00")
        self.assertNotEqual(reasons, ())
        self.assertIn("malformed_payload", reasons)


class ScopeBindingTests(unittest.TestCase):
    """LOW-3: the signed payload carries the budget scope the
    evaluation ran under, MAC-bound like every other field."""

    def test_default_scope_is_unscoped(self):
        record = sign(report())
        self.assertEqual(record["payload"]["scope"], "unscoped")
        self.assertEqual(verify_eval_attestation(
            record, signing_key=KEY,
            now="2026-11-20T12:05:00+00:00"), ())

    def test_scope_carried_and_checked(self):
        record = sign_eval_attestation(
            report(), signing_key=KEY, signer_id="verifier-svc",
            actor="verifier-actor", registry_digest="b" * 64,
            answers_hash="c" * 64, now="2026-11-20T12:00:00+00:00",
            scope="prop-1:baseline")
        self.assertEqual(record["payload"]["scope"], "prop-1:baseline")
        self.assertEqual(verify_eval_attestation(
            record, signing_key=KEY, expected_scope="prop-1:baseline",
            now="2026-11-20T12:05:00+00:00"), ())
        reasons = verify_eval_attestation(
            record, signing_key=KEY, expected_scope="prop-2:baseline",
            now="2026-11-20T12:05:00+00:00")
        self.assertIn("scope_mismatch", reasons)

    def test_transplanted_scope_fails_verify(self):
        record = sign_eval_attestation(
            report(), signing_key=KEY, signer_id="verifier-svc",
            actor="verifier-actor", registry_digest="b" * 64,
            answers_hash="c" * 64, now="2026-11-20T12:00:00+00:00",
            scope="prop-1:baseline")
        record["payload"]["scope"] = "prop-2:baseline"
        reasons = verify_eval_attestation(
            record, signing_key=KEY, now="2026-11-20T12:05:00+00:00")
        self.assertNotEqual(reasons, ())

    def test_scope_root_strips_one_role_suffix(self):
        self.assertEqual(scope_root_for("prop-1:baseline"), "prop-1")
        self.assertEqual(scope_root_for("prop-1:candidate"), "prop-1")
        self.assertEqual(scope_root_for("prop-1"), "prop-1")
        self.assertEqual(scope_root_for("unscoped"), "unscoped")


class ClaimLedgerTests(unittest.TestCase):
    """append_claim ledgers a claim UNSIGNED: kind "claim",
    accepted=False always, decision_id == payload_hash == the
    sha256 of the canonical claim document, and no sign entry."""

    def test_append_claim_entry_shape(self):
        import tempfile
        from pathlib import Path as _Path
        from signing.gate_decision import _canonical, _sha256
        from trust.ledger import SigningLedger
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SigningLedger(_Path(tmp) / "home")
            doc = {"v": "trust-claim/1", "proposal_id": "prop-1",
                   "attestation": {
                       "verifier_id": "seat-3", "decision": "approve",
                       "sealed_hash": "a" * 64,
                       "reward_hacking_checked": True,
                       "evidence_ref": "fabricated",
                       "attested_at": "2026-11-20T12:00:00+00:00"}}
            entry = ledger.append_claim(
                doc, recorded_at="2026-11-20T12:01:00+00:00",
                signer_id="seat-3")
            expected = _sha256(_canonical(doc))
            self.assertEqual(entry["kind"], "claim")
            self.assertEqual(entry["format"], "claim")
            self.assertEqual(entry["purpose"], "claim")
            self.assertFalse(entry["accepted"])
            self.assertEqual(entry["decision_id"], expected)
            self.assertEqual(entry["payload_hash"], expected)
            self.assertEqual(entry["proposal_id"], "prop-1")
            self.assertEqual(
                [e for e in ledger.entries() if e["kind"] == "sign"],
                [])
            self.assertFalse(ledger.has_envelope(expected))


if __name__ == "__main__":
    unittest.main()
