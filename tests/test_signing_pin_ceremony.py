"""Tests for signing/pin_ceremony.py (cycle 15).

The ceremony is the recovery path cycle 14's chain-gap refusal
requires: authorised, evidence-bound, MAC-audited re-anchoring.
These tests pin the happy paths, every refusal condition, the
caller classification contract, and the adversarial shapes
(ceremony-as-bypass, self-derived evidence, backwards moves,
tampered audit records).
"""
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import SigningError, make_signing_key
from signing.pin_ceremony import (
    advance_pin, classify_verification, reanchor_pin,
    verify_ceremony_record)
from signing.state_snapshot import sign_state_snapshot

KEY = make_signing_key(bytes(range(32, 64)))
SIGNER = "seat-3"
NOW = "2026-11-20T12:00:00+00:00"
OPERATOR = "operator-1"
AUTH = ["operator-1", "operator-2"]
EVIDENCE = "e" * 64


def state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq, "phase": "SCAN",
           "backlog": [], "history": history, "deltas": [],
           "history_pruned": 0, "deltas_pruned": 0, "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


CAL = b'{"log":1}'


def snap(seq, prev=""):
    return sign_state_snapshot(state_bytes(seq), signing_key=KEY,
                               signer_id=SIGNER, calibration_bytes=CAL,
                               prev_snapshot_hash=prev, now=NOW)


def pin_of(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "key_id": s.key_id, "signer_id": s.signer_id}


def reanchor(old, cand, **kw):
    kw.setdefault("signing_key", KEY)
    kw.setdefault("state_bytes", state_bytes(cand.cycle_seq))
    kw.setdefault("calibration_bytes", CAL)
    kw.setdefault("expected_signer_id", SIGNER)
    kw.setdefault("operator_id", OPERATOR)
    kw.setdefault("authorised_operators", AUTH)
    kw.setdefault("reason", "chain_gap_recovery")
    if kw["reason"] == "chain_gap_recovery":
        kw.setdefault("strict_reasons", ("chain_gap",))
    kw.setdefault("evidence_hash", EVIDENCE)
    kw.setdefault("now", NOW)
    return reanchor_pin(old, cand, **kw)


class ClassifyTests(unittest.TestCase):
    def test_classification_contract(self):
        self.assertEqual(classify_verification(()), "ok")
        self.assertEqual(classify_verification(("chain_gap",)),
                         "reanchor_required")
        for bad in [("expired",), ("chain_gap", "expired"),
                    ("signature_mismatch",), ("pin_mismatch",)]:
            self.assertEqual(classify_verification(bad),
                             "integrity_failure", bad)


class AdvanceTests(unittest.TestCase):
    def test_advance_one_step(self):
        a, b = snap(1), None
        b = snap(2, prev=a.payload_hash)
        self.assertEqual(advance_pin(pin_of(a), b, ()), pin_of(b))

    def test_advance_idempotent_same(self):
        a = snap(1)
        self.assertEqual(advance_pin(pin_of(a), a, ()), pin_of(a))

    def test_advance_refusals(self):
        a = snap(1)
        gap = snap(3, prev="f" * 64)
        unchained = snap(2, prev="f" * 64)
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), gap, ())
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), unchained, ())
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), snap(2, prev=a.payload_hash),
                        ("chain_gap",))


class ReanchorTests(unittest.TestCase):
    def test_gap_recovery_happy(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        new_pin, rec = reanchor(pin_of(a), cand)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual((rec.gap_from_seq, rec.gap_to_seq), (2, 3))
        self.assertEqual(verify_ceremony_record(rec, signing_key=KEY), ())

    def test_initial_anchor(self):
        cand = snap(2)
        new_pin, rec = reanchor(None, cand, reason="initial_anchor")
        self.assertEqual(new_pin, pin_of(cand))
        self.assertIsNone(rec.gap_from_seq)

    def test_lost_pin_recovery(self):
        cand = snap(3)
        _, rec = reanchor(None, cand, reason="lost_pin")
        self.assertEqual(rec.reason, "lost_pin")

    def test_refusals(self):
        a, cand = snap(2), snap(5, prev="f" * 64)
        cases = [
            dict(operator_id="operator-9"),               # unauthorised
            dict(reason="routine_bypass"),                # bad reason
            dict(evidence_hash="xyz"),                    # malformed evidence
            dict(evidence_hash=cand.payload_hash),        # self-derived
            dict(evidence_hash=cand.state_sha256),        # self-derived
            dict(expected_signer_id="seat-9"),            # signer mismatch
            dict(calibration_bytes=b'{"log":2}'),         # calibration mismatch
        ]
        for kw in cases:
            with self.assertRaises(SigningError, msg=str(kw)):
                reanchor(pin_of(a), cand, **kw)

    def test_no_backwards_or_same_seq_replace(self):
        a = snap(3)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), snap(2))
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), snap(3, prev="f" * 64))

    def test_ceremony_not_for_normal_advance(self):
        a = snap(1)
        nxt = snap(2, prev=a.payload_hash)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), nxt)

    def test_reason_pin_coherence(self):
        cand = snap(2)
        with self.assertRaises(SigningError):
            reanchor(pin_of(snap(1)), cand, reason="initial_anchor")
        with self.assertRaises(SigningError):
            reanchor(None, cand, reason="chain_gap_recovery")

    def test_tampered_candidate_refused(self):
        a = snap(1)
        cand = replace(snap(4, prev="f" * 64), cycle_seq=4,
                       signature="0" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand)

    def test_fix_round_cycle15(self):
        # Forced-dissent: pin+1 fork must not ride the ceremony.
        a = snap(1)
        fork = snap(2, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), fork, reason="lost_pin")
        # Forced-dissent: gap recovery gated on a real chain_gap.
        cand = snap(4, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, strict_reasons=None)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, strict_reasons=("expired",))
        # rev-r5 branches: calibration-hash evidence, wrong key,
        # malformed old pin, corrupted_pin happy path.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand,
                     evidence_hash=cand.calibration_sha256)
        with self.assertRaises(SigningError):
            reanchor({"cycle_seq": "x", "payload_hash": "z"}, cand)
        _, rec = reanchor(None, snap(3), reason="corrupted_pin")
        other = make_signing_key(b"\xff" * 32)
        self.assertEqual(verify_ceremony_record(rec, signing_key=other),
                         ("unknown_key", "signature_mismatch"))
        # classify: duplicates and list input are not reanchor_required.
        self.assertEqual(classify_verification(("chain_gap", "chain_gap")),
                         "integrity_failure")
        self.assertEqual(classify_verification(["chain_gap"]),
                         "reanchor_required")

    def test_rev_r2_round(self):
        a = snap(1)
        nxt = snap(2, prev=a.payload_hash)
        gap = snap(4, prev="f" * 64)
        # F1: relabelling cannot launder a jump or a routine advance.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), nxt, reason="lost_pin")
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), gap, reason="corrupted_pin")
        # F2: snapshot_id is candidate-derived evidence.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), gap, evidence_hash=gap.snapshot_id)
        # F3: advance_pin honours the pin's signer binding.
        bad_pin = pin_of(a)
        bad_pin["signer_id"] = "evil-9"
        with self.assertRaises(SigningError):
            advance_pin(bad_pin, nxt, ())
        # F4: a signed record violating ceremony invariants fails.
        _, rec = reanchor(pin_of(a), gap)
        bad_rec = replace(rec, reason="lost_pin")
        self.assertIn("invalid_reason",
                      verify_ceremony_record(bad_rec, signing_key=KEY))

    def test_audit_record_tamper_detected(self):
        _, rec = reanchor(None, snap(2), reason="initial_anchor")
        bad = replace(rec, operator_id="operator-2")
        self.assertIn("payload_hash_mismatch",
                      verify_ceremony_record(bad, signing_key=KEY))
        bad2 = replace(rec, signature="0" * 64)
        self.assertIn("signature_mismatch",
                      verify_ceremony_record(bad2, signing_key=KEY))


if __name__ == "__main__":
    unittest.main()
