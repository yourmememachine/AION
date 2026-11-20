"""Tests for signing/state_snapshot.py (cycle 10, signed-state).

The snapshot attests the exact bytes of the loop state and,
optionally, the calibration log (the per-seat vote record). The
signer recomputes every bound fact from the raw bytes; these
tests pin the happy path, the tamper cases, the rollback pin,
the calibration binding, the strict parser and the honest limits
(a forged envelope made with the key verifies — HMAC is
symmetric, and the suite asserts that limit rather than letting
it be silently upgraded into a claim).
"""

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import (
    SigningError,
    make_signing_key,
    sign_state_snapshot,
    snapshot_envelope_from_dict,
    snapshot_envelope_from_json,
    snapshot_envelope_to_dict,
    snapshot_envelope_to_json,
    verify_signed_snapshot,
)
from signing.state_snapshot import (
    calibration_hash_for,
    parse_state_bytes,
    self_test,
    state_hash_for,
)

KEY = make_signing_key(bytes(range(32, 64)))
OTHER_KEY = make_signing_key(b"\xff" * 32)
SIGNER = "seat-3"
NOW = "2026-11-20T12:00:00+00:00"


def state_bytes(cycle_seq=2, history=None, **over):
    if history is None:
        history = [
            {"cycle_id": 1, "item_id": "core-loop-v1",
             "completed_at": "2026-11-20T05:11:13+00:00"},
            {"cycle_id": 2, "item_id": "eval-gate-calibration",
             "completed_at": "2026-11-20T06:02:19+00:00"},
        ][:cycle_seq]
    doc = {
        "schema_version": 1, "cycle_seq": cycle_seq, "phase": "SCAN",
        "backlog": [], "history": history, "deltas": [],
        "history_pruned": 0, "deltas_pruned": 0, "current_item_id": None,
    }
    doc.update(over)
    return json.dumps(doc, sort_keys=True).encode()


CAL_BYTES = json.dumps({
    "schema_version": 1,
    "entries": [{"reviewer_id": "rev-r1", "score": 0.9,
                 "entry_hash": "a" * 64}],
    "closed_subjects": {}, "closed_digest": "b" * 64,
}, sort_keys=True).encode()


def sign(state=None, **kw):
    kw.setdefault("signing_key", KEY)
    kw.setdefault("signer_id", SIGNER)
    kw.setdefault("now", NOW)
    return sign_state_snapshot(
        state_bytes() if state is None else state, **kw)


class ParseTests(unittest.TestCase):
    def test_parse_extracts_facts(self):
        facts = parse_state_bytes(state_bytes())
        self.assertEqual(facts.cycle_seq, 2)
        self.assertEqual(facts.history_len, 2)
        self.assertEqual(facts.last_cycle_id, 2)
        self.assertEqual(facts.last_item_id, "eval-gate-calibration")
        self.assertEqual(facts.state_sha256, state_hash_for(state_bytes()))

    def test_parse_empty_history(self):
        facts = parse_state_bytes(state_bytes(cycle_seq=0, history=[]))
        self.assertIsNone(facts.last_cycle_id)
        self.assertIsNone(facts.last_item_id)

    def test_parse_rejects_malformed(self):
        bad = [
            b"not json",
            b"[1,2]",
            state_bytes(schema_version=2),
            state_bytes(cycle_seq=True),
            state_bytes(cycle_seq=-1),
            state_bytes(cycle_seq=5),  # != last history cycle
            state_bytes(cycle_seq=1, history=[]),  # empty but seq > 0
            b'{"schema_version":1,"schema_version":1}',
            b'{"schema_version":1,"cycle_seq":NaN,"history":[]}',
            state_bytes(history=[{"cycle_id": 2, "item_id": "x"},
                                 {"cycle_id": 2, "item_id": "y"}]),
            state_bytes(history=[{"cycle_id": 1, "item_id": "Bad Id!"}]),
            state_bytes(history=[{"cycle_id": True, "item_id": "x"}]),
            "text-not-bytes",
            b"x" * (5 * 1024 * 1024 + 1),
        ]
        for blob in bad:
            with self.assertRaises(SigningError, msg=repr(blob)[:60]):
                parse_state_bytes(blob)


class SignVerifyTests(unittest.TestCase):
    def test_happy_roundtrip(self):
        signed = sign(calibration_bytes=CAL_BYTES)
        self.assertEqual(signed.calibration_sha256,
                         calibration_hash_for(CAL_BYTES))
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_state_bytes=state_bytes(),
            expected_calibration_bytes=CAL_BYTES,
            expected_signer_id=SIGNER, now=NOW)
        self.assertEqual(reasons, ())

    def test_self_test(self):
        self.assertTrue(self_test(KEY))

    def test_unbound_calibration_by_default(self):
        signed = sign()
        self.assertEqual(signed.calibration_sha256, "")
        self.assertEqual(
            verify_signed_snapshot(signed, signing_key=KEY, now=NOW), ())
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, require_calibration=True, now=NOW)
        self.assertIn("calibration_unbound", reasons)

    def test_empty_calibration_bytes_refused(self):
        # None means unbound; b"" is malformed, not a second
        # spelling of it (external seat, cycle 10).
        with self.assertRaises(SigningError):
            sign(calibration_bytes=b"")

    def test_tampered_state_detected(self):
        signed = sign()
        other = state_bytes(cycle_seq=2, history=[
            {"cycle_id": 1, "item_id": "core-loop-v1",
             "completed_at": "2026-11-20T05:11:13+00:00"},
            {"cycle_id": 2, "item_id": "different-item",
             "completed_at": "2026-11-20T06:02:19+00:00"}])
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_state_bytes=other, now=NOW)
        self.assertIn("state_mismatch", reasons)

    def test_tampered_calibration_detected(self):
        signed = sign(calibration_bytes=CAL_BYTES)
        tampered = CAL_BYTES.replace(b"0.9", b"0.1")
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY,
            expected_calibration_bytes=tampered, now=NOW)
        self.assertIn("calibration_mismatch", reasons)

    def test_wrong_key_and_tampered_signature(self):
        signed = sign()
        reasons = verify_signed_snapshot(
            signed, signing_key=OTHER_KEY, now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)
        forged = replace(signed, signature="0" * 64)
        reasons = verify_signed_snapshot(forged, signing_key=KEY, now=NOW)
        self.assertIn("signature_mismatch", reasons)

    def test_tampered_payload_field_detected(self):
        signed = sign()
        forged = replace(signed, prev_snapshot_hash="f" * 64)
        reasons = verify_signed_snapshot(forged, signing_key=KEY, now=NOW)
        self.assertIn("payload_hash_mismatch", reasons)
        # An internally inconsistent tamper fails even earlier, at
        # payload re-derivation (war-room cycle 10 fix round).
        forged = replace(signed, cycle_seq=99)
        reasons = verify_signed_snapshot(forged, signing_key=KEY, now=NOW)
        self.assertIn("malformed_payload", reasons)

    def test_signer_and_purpose_mismatch(self):
        signed = sign()
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_signer_id="seat-9", now=NOW)
        self.assertIn("signer_mismatch", reasons)
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_purpose="ship", now=NOW)
        self.assertIn("purpose_mismatch", reasons)

    def test_expiry_and_future(self):
        signed = sign(ttl_seconds=60)
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, now="2026-11-20T12:02:00+00:00")
        self.assertIn("expired", reasons)
        future = sign(now="2026-11-20T13:00:00+00:00")
        reasons = verify_signed_snapshot(future, signing_key=KEY, now=NOW)
        self.assertIn("signed_in_future", reasons)

    def test_sign_refuses_pre_state_timestamp(self):
        with self.assertRaises(SigningError):
            sign(now="2026-11-20T05:00:00+00:00")

    def test_sign_rejects_caller_asserted_facts(self):
        # There is no parameter to assert cycle_seq or hashes: the
        # signer derives them. A malformed state is refused at sign.
        with self.assertRaises(SigningError):
            sign(state=b"{}")
        with self.assertRaises(SigningError):
            sign(ttl_seconds=30)
        with self.assertRaises(SigningError):
            sign(prev_snapshot_hash="not-hex")

    def test_chaining(self):
        first = sign()
        second = sign(prev_snapshot_hash=first.payload_hash)
        self.assertEqual(second.prev_snapshot_hash, first.payload_hash)
        self.assertEqual(
            verify_signed_snapshot(second, signing_key=KEY, now=NOW), ())

    def test_forged_with_key_verifies_documented_limit(self):
        # HMAC is symmetric: a "forgery" made with the key itself
        # verifies. This pins the documented limit so it can never
        # be silently upgraded into a non-repudiation claim.
        forged = sign_state_snapshot(
            state_bytes(), signing_key=KEY, signer_id="anyone", now=NOW)
        self.assertEqual(
            verify_signed_snapshot(forged, signing_key=KEY, now=NOW), ())
        reasons = verify_signed_snapshot(
            forged, signing_key=KEY, expected_signer_id=SIGNER, now=NOW)
        self.assertIn("signer_mismatch", reasons)


class PinTests(unittest.TestCase):
    def test_rollback_against_pin(self):
        old = sign(state=state_bytes(cycle_seq=1))
        new = sign(state=state_bytes())
        pin = {"cycle_seq": new.cycle_seq, "payload_hash": new.payload_hash}
        reasons = verify_signed_snapshot(
            old, signing_key=KEY, expected_pin=pin, now=NOW)
        self.assertIn("snapshot_rolled_back", reasons)
        self.assertEqual(
            verify_signed_snapshot(new, signing_key=KEY,
                                   expected_pin=pin, now=NOW), ())

    def test_pin_mismatch_same_sequence(self):
        signed = sign()
        pin = {"cycle_seq": signed.cycle_seq, "payload_hash": "f" * 64}
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_pin=pin, now=NOW)
        self.assertIn("pin_mismatch", reasons)

    def test_newer_than_pin_passes(self):
        # A snapshot more than one sequence past the pin is not
        # chain-checked against it (documented gap rule); the
        # immediate successor IS checked — see FixRoundTests.
        signed = sign()
        pin = {"cycle_seq": 0, "payload_hash": "f" * 64}
        self.assertEqual(
            verify_signed_snapshot(signed, signing_key=KEY,
                                   expected_pin=pin, now=NOW), ())

    def test_malformed_pin_raises(self):
        signed = sign()
        with self.assertRaises(SigningError):
            verify_signed_snapshot(
                signed, signing_key=KEY, expected_pin={"cycle_seq": 1},
                now=NOW)


class EnvelopeTests(unittest.TestCase):
    def test_json_roundtrip(self):
        signed = sign(calibration_bytes=CAL_BYTES)
        back = snapshot_envelope_from_json(snapshot_envelope_to_json(signed))
        self.assertEqual(back, signed)
        self.assertEqual(
            verify_signed_snapshot(back, signing_key=KEY, now=NOW), ())

    def test_dict_roundtrip_and_strictness(self):
        signed = sign()
        data = snapshot_envelope_to_dict(signed)
        self.assertEqual(snapshot_envelope_from_dict(data), signed)
        extra = dict(data, extra=1)
        with self.assertRaises(SigningError):
            snapshot_envelope_from_dict(extra)
        missing = {k: v for k, v in data.items() if k != "signature"}
        with self.assertRaises(SigningError):
            snapshot_envelope_from_dict(missing)
        bad = dict(data, signature="zz")
        with self.assertRaises(SigningError):
            snapshot_envelope_from_dict(bad)
        bad = dict(data, cycle_seq="2")
        with self.assertRaises(SigningError):
            snapshot_envelope_from_dict(bad)

    def test_json_rejects_duplicates_and_constants(self):
        raw = ('{"state_sha256": "%s", "state_sha256": "%s"}'
               % ("a" * 64, "a" * 64))
        with self.assertRaises(SigningError):
            snapshot_envelope_from_json(raw)
        with self.assertRaises(SigningError):
            snapshot_envelope_from_json('{"x": NaN}')


class FixRoundTests(unittest.TestCase):
    """War-room cycle 10 fix round: every finding pinned."""

    def test_payload_builder_validates_facts(self):
        from signing.state_snapshot import StateFacts, state_snapshot_payload
        bad_facts = StateFacts(
            state_sha256="a" * 64, schema_version=999, cycle_seq=99,
            history_len=999, last_cycle_id=1, last_item_id="Bad Id!",
            last_completed_at="not-a-time")
        with self.assertRaises(SigningError):
            state_snapshot_payload(
                bad_facts, signer_id=SIGNER, key_id=KEY.key_id,
                signed_at=NOW, expires_at="2026-11-20T12:15:00+00:00")

    def test_handbuilt_inconsistent_envelope_fails_verify(self):
        signed = sign()
        forged = replace(signed, cycle_seq=99)
        reasons = verify_signed_snapshot(forged, signing_key=KEY, now=NOW)
        self.assertIn("malformed_payload", reasons)

    def test_envelope_from_dict_rejects_bad_facts(self):
        data = snapshot_envelope_to_dict(sign())
        for field, value in (("cycle_seq", -5), ("history_len", -1),
                             ("state_schema_version", 999),
                             ("last_item_id", 123),
                             ("last_item_id", "Bad Id!"),
                             ("last_completed_at", "garbage"),
                             ("last_completed_at", 12345),
                             ("calibration_sha256", None),
                             ("prev_snapshot_hash", False)):
            bad = dict(data, **{field: value})
            with self.assertRaises(SigningError, msg=f"{field}={value!r}"):
                snapshot_envelope_from_dict(bad)

    def test_verify_never_crashes_on_weird_fields(self):
        signed = sign()
        weird = replace(signed, last_item_id=b"\xff\xfe-bytes")
        reasons = verify_signed_snapshot(weird, signing_key=KEY, now=NOW)
        self.assertEqual(reasons, ("malformed_payload",))
        weird = replace(signed, last_item_id=float("nan"))
        reasons = verify_signed_snapshot(weird, signing_key=KEY, now=NOW)
        self.assertEqual(reasons, ("malformed_payload",))

    def test_signed_before_state_is_unconditional(self):
        # Hand-built via the payload builder: the builder itself
        # now refuses, so no envelope can carry the condition.
        from signing.state_snapshot import StateFacts, state_snapshot_payload
        facts = parse_state_bytes(state_bytes())
        with self.assertRaises(SigningError):
            state_snapshot_payload(
                facts, signer_id=SIGNER, key_id=KEY.key_id,
                signed_at="2026-11-20T05:00:00+00:00",
                expires_at="2026-11-20T05:15:00+00:00")

    def test_parser_validates_every_completed_at(self):
        blob = state_bytes(history=[
            {"cycle_id": 1, "item_id": "core-loop-v1",
             "completed_at": "GARBAGE!!"},
            {"cycle_id": 2, "item_id": "eval-gate-calibration",
             "completed_at": "2026-11-20T06:02:19+00:00"}])
        with self.assertRaises(SigningError):
            parse_state_bytes(blob)
        # Non-decreasing order: an early cycle stamped after the
        # last one (rev-r2 re-verification) is malformed too.
        blob = state_bytes(history=[
            {"cycle_id": 1, "item_id": "core-loop-v1",
             "completed_at": "2027-01-01T00:00:00+00:00"},
            {"cycle_id": 2, "item_id": "eval-gate-calibration",
             "completed_at": "2026-11-20T06:02:19+00:00"}])
        with self.assertRaises(SigningError):
            parse_state_bytes(blob)

    def test_expected_prev_snapshot_hash(self):
        first = sign()
        second = sign(prev_snapshot_hash=first.payload_hash)
        self.assertEqual(
            verify_signed_snapshot(
                second, signing_key=KEY,
                expected_prev_snapshot_hash=first.payload_hash,
                now=NOW), ())
        reasons = verify_signed_snapshot(
            second, signing_key=KEY,
            expected_prev_snapshot_hash="f" * 64, now=NOW)
        self.assertIn("prev_snapshot_mismatch", reasons)

    def test_pin_successor_must_chain_to_pin(self):
        first = sign(state=state_bytes(cycle_seq=1))
        pin = {"cycle_seq": 1, "payload_hash": first.payload_hash}
        good = sign(prev_snapshot_hash=first.payload_hash)
        self.assertEqual(
            verify_signed_snapshot(good, signing_key=KEY,
                                   expected_pin=pin, now=NOW), ())
        forked = sign(prev_snapshot_hash="f" * 64)
        reasons = verify_signed_snapshot(
            forked, signing_key=KEY, expected_pin=pin, now=NOW)
        self.assertIn("chain_discontinuity", reasons)

    def test_pin_strictness(self):
        signed = sign()
        with self.assertRaises(SigningError):
            verify_signed_snapshot(
                signed, signing_key=KEY, now=NOW,
                expected_pin={"cycle_seq": -1, "payload_hash": "f" * 64})
        with self.assertRaises(SigningError):
            verify_signed_snapshot(
                signed, signing_key=KEY, now=NOW,
                expected_pin={"cycle_seq": 1, "payload_hash": "f" * 64,
                              "surprise": 1})
        pin = {"cycle_seq": signed.cycle_seq,
               "payload_hash": signed.payload_hash,
               "key_id": "key-0000000000000000"}
        reasons = verify_signed_snapshot(
            signed, signing_key=KEY, expected_pin=pin, now=NOW)
        self.assertIn("pin_mismatch", reasons)

    def test_cross_domain_envelopes_refused(self):
        from signing import envelope_from_dict as gate_from_dict
        from signing import envelope_to_dict as gate_to_dict
        from signing.gate_decision import sign_gate_decision
        from eval.gate import GateDecision
        decision = GateDecision(
            accepted=True, proposal_id="p1", reasons=(), regressions=(),
            forgetting_failures=(), verifier_id=None,
            evaluated_at=NOW, protected_violations=(), verifier_note="")
        gate_env = gate_to_dict(sign_gate_decision(
            decision, signing_key=KEY, signer_id=SIGNER, now=NOW))
        with self.assertRaises(SigningError):
            snapshot_envelope_from_dict(gate_env)
        snap_env = snapshot_envelope_to_dict(sign())
        with self.assertRaises(SigningError):
            gate_from_dict(snap_env)

    def test_strict_wrapper_requires_all_bindings(self):
        from signing.state_snapshot import verify_snapshot_for_state
        signed = sign(calibration_bytes=CAL_BYTES)
        pin = {"cycle_seq": signed.cycle_seq,
               "payload_hash": signed.payload_hash}
        self.assertEqual(
            verify_snapshot_for_state(
                signed, signing_key=KEY, state_bytes=state_bytes(),
                calibration_bytes=CAL_BYTES, expected_pin=pin,
                expected_signer_id=SIGNER, now=NOW), ())
        with self.assertRaises(SigningError):
            verify_snapshot_for_state(
                signed, signing_key=KEY, state_bytes=state_bytes(),
                calibration_bytes=None, expected_pin=pin,
                expected_signer_id=SIGNER, now=NOW)

    def test_sign_state_files_double_read(self):
        import tempfile
        from signing.state_snapshot import sign_state_files
        with tempfile.TemporaryDirectory() as tmp:
            sp = Path(tmp) / "state.json"
            cp = Path(tmp) / "calibration.json"
            sp.write_bytes(state_bytes())
            cp.write_bytes(CAL_BYTES)
            signed = sign_state_files(
                sp, cp, signing_key=KEY, signer_id=SIGNER, now=NOW)
            self.assertEqual(
                verify_signed_snapshot(
                    signed, signing_key=KEY,
                    expected_state_bytes=state_bytes(),
                    expected_calibration_bytes=CAL_BYTES, now=NOW), ())
            calls = {"n": 0}

            def flaky_reader(path):
                calls["n"] += 1
                if calls["n"] == 3:  # second state read differs
                    return state_bytes(cycle_seq=1)
                return Path(path).read_bytes()

            with self.assertRaises(SigningError):
                sign_state_files(
                    sp, cp, signing_key=KEY, signer_id=SIGNER, now=NOW,
                    _reader=flaky_reader)

    def test_state_hash_for_capped(self):
        with self.assertRaises(SigningError):
            state_hash_for(b"x" * (5 * 1024 * 1024 + 1))


class LiveStateTests(unittest.TestCase):
    def test_live_state_and_calibration_snapshot(self):
        # Expectations are derived from the live file itself, so
        # this test survives the cycle it ships in (rev-r6).
        root = Path(__file__).resolve().parents[1]
        state = (root / "state" / "state.json").read_bytes()
        cal = (root / "state" / "calibration"
               / "calibration.json").read_bytes()
        facts = parse_state_bytes(state)
        self.assertEqual(facts.cycle_seq, facts.last_cycle_id)
        self.assertGreaterEqual(facts.history_len, 9)
        signed = sign_state_snapshot(
            state, signing_key=KEY, signer_id=SIGNER,
            calibration_bytes=cal, now="2026-11-20T12:30:00+00:00")
        self.assertEqual(
            verify_signed_snapshot(
                signed, signing_key=KEY, expected_state_bytes=state,
                expected_calibration_bytes=cal,
                now="2026-11-20T12:30:00+00:00"), ())


if __name__ == "__main__":
    unittest.main()
