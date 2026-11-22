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


LATER = "2026-11-20T13:00:00+00:00"


def snap_at(seq, prev="", when=LATER):
    return sign_state_snapshot(state_bytes(seq), signing_key=KEY,
                               signer_id=SIGNER, calibration_bytes=CAL,
                               prev_snapshot_hash=prev, now=when)


class Cycle16HardeningTests(unittest.TestCase):
    def _first_ceremony(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        new_pin, rec = reanchor(pin_of(a), cand)
        return a, cand, new_pin, rec

    def test_forged_strict_reasons_wrong_pin_binding_refused(self):
        # The caller-supplied ("chain_gap",) is not trusted: with a
        # pin carrying a different signer binding, the recomputed
        # strict result is not a sole chain_gap and the ceremony
        # refuses, where cycle 15 would have proceeded.
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        bad_pin = pin_of(a)
        bad_pin["signer_id"] = "evil-9"
        with self.assertRaises(SigningError):
            reanchor(bad_pin, cand)

    def test_gap_prev_is_pin_refused(self):
        a = snap(1)
        cand = snap(4, prev=a.payload_hash)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand)

    def test_strict_reasons_corpus_never_typeerror(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        for bad in ["chain_gap", 42, ("chain_gap", "chain_gap"),
                    ("chain_gap", "expired")]:
            with self.assertRaises(SigningError, msg=repr(bad)):
                reanchor(pin_of(a), cand, strict_reasons=bad)

    def test_history_evidence_reuse_refused_fresh_accepted(self):
        _a, cand, new_pin, rec = self._first_ceremony()
        nxt = snap_at(7, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER,
                     ceremony_history=[rec])
        pin2, rec2 = reanchor(new_pin, nxt, now=LATER,
                              evidence_hash="d" * 64,
                              ceremony_history=[rec])
        self.assertEqual(pin2, pin_of(nxt))
        self.assertEqual(verify_ceremony_record(rec2, signing_key=KEY),
                         ())

    def test_history_tampered_and_duplicate_evidence_refused(self):
        _a, _c, new_pin, rec = self._first_ceremony()
        nxt = snap_at(7, prev="f" * 64)
        tampered = replace(rec, operator_id="operator-2")
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[tampered])
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[rec, rec])
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history="not-a-history")
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[object()])

    def test_history_replayed_target_and_behind_head_refused(self):
        a, cand, _pin, rec = self._first_ceremony()
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        behind = snap_at(3, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), behind, now=LATER,
                     evidence_hash="d" * 64, ceremony_history=[rec])

    def test_history_empty_and_absent_unchanged(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _, rec = reanchor(pin_of(a), cand, ceremony_history=[])
        self.assertEqual(verify_ceremony_record(rec, signing_key=KEY),
                         ())

    def test_one_step_record_never_verifies_clean(self):
        _a, _c, _p, rec = self._first_ceremony()
        one_step = replace(rec, new_cycle_seq=rec.old_cycle_seq + 1)
        self.assertIn("not_a_gap_reanchor",
                      verify_ceremony_record(one_step, signing_key=KEY))

    def test_record_pin_context(self):
        a, cand, _p, rec = self._first_ceremony()
        self.assertEqual(
            verify_ceremony_record(
                rec, signing_key=KEY, expected_old_pin=pin_of(a),
                expected_new_pin=pin_of(cand)), ())
        other = snap(5, prev="f" * 64)
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(
                rec, signing_key=KEY, expected_old_pin=pin_of(a),
                expected_new_pin=pin_of(other)))

    def test_fix_round_cycle16(self):
        from signing.pin_ceremony import _mac, _payload_hash
        a, cand, new_pin, rec = self._first_ceremony()
        # Replayed target, isolated by its refusal message.
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        self.assertIn("already a ceremonied target", str(cm.exception))
        # Stale candidate, isolated: signed before the history's
        # latest ceremony, refused by the predates check itself.
        stale = snap_at(7, prev="f" * 64,
                        when="2026-11-20T11:55:00+00:00")
        with self.assertRaises(SigningError) as cm:
            reanchor(new_pin, stale, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        self.assertIn("predates the latest ceremony",
                      str(cm.exception))
        # Equal-seq / different-hash against the history head.
        rival = snap_at(4, prev="a" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), rival, now=LATER,
                     evidence_hash="d" * 64, ceremony_history=[rec])
        self.assertIn("abandon higher attested work",
                      str(cm.exception))
        # Forked history: two verified records, same target seq,
        # different hashes.
        _, rec2 = reanchor(None, rival, reason="initial_anchor",
                           evidence_hash="b" * 64, now=LATER)
        nxt = snap_at(7, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(new_pin, nxt, now=LATER,
                     evidence_hash="c" * 64,
                     ceremony_history=[rec, rec2])
        self.assertIn("history is forked", str(cm.exception))
        # A validly MACed one-step record: exactly one reason.
        one = replace(rec, new_cycle_seq=rec.old_cycle_seq + 1)
        ph = _payload_hash(one.payload())
        one = replace(one, payload_hash=ph,
                      signature=_mac(KEY.key, ph, KEY.key_id))
        self.assertEqual(verify_ceremony_record(one, signing_key=KEY),
                         ("not_a_gap_reanchor",))
        # Context: each side independent; explicit absent-old
        # assertion; malformed context reports, never raises.
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=KEY,
                                   expected_new_pin=pin_of(cand)), ())
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(rec, signing_key=KEY,
                                   expected_old_pin=None))
        _, rec_init = reanchor(None, snap(2), reason="initial_anchor",
                               evidence_hash="b" * 64)
        self.assertEqual(
            verify_ceremony_record(rec_init, signing_key=KEY,
                                   expected_old_pin=None), ())
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(
                rec, signing_key=KEY,
                expected_new_pin={"cycle_seq": "x",
                                  "payload_hash": "z"}))
        # Binding-absent pin: known, pinned behaviour — a minimal
        # pin carries no bindings for the recomputation to bind.
        minimal = {"cycle_seq": a.cycle_seq,
                   "payload_hash": a.payload_hash}
        pin3, _ = reanchor(minimal, cand, evidence_hash="c" * 64)
        self.assertEqual(pin3, pin_of(cand))
        # strict_reasons must be a list/tuple, captured once.
        for bad in [{"chain_gap": 1}, {"chain_gap"}]:
            with self.assertRaises(SigningError, msg=repr(bad)):
                reanchor(pin_of(a), cand, strict_reasons=bad)


if __name__ == "__main__":
    unittest.main()
