"""Unit tests for signing/ceremony_authorisation.py (cycle 19).

The envelope unit half of seat B's test plan: payload projection
refusals (reason allowlist, reason/pin coherence, gap-only
sequence relation, evidence non-equality), the REASONS mirror
drift pin against signing.pin_ceremony, sign/verify round trip,
each verify reason in the 16-term vocabulary, serialisation
strictness, and authorisation_id derivation.
"""

import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import signing.pin_ceremony as pin_ceremony
from signing import (
    SigningError,
    make_signing_key,
)
from signing.ceremony_authorisation import (
    CEREMONY_AUTHORISATION_TTL_MAX_SECONDS,
    REASONS,
    _NO_PIN_REASONS,
    SignedCeremonyAuthorisation,
    authorisation_id_for,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_from_json,
    ceremony_authorisation_envelope_to_dict,
    ceremony_authorisation_envelope_to_json,
    ceremony_authorisation_payload,
    sign_ceremony_authorisation,
    verify_ceremony_authorisation,
)
from signing.gate_decision import SigningKey

VERIFIER_KEY = make_signing_key(bytes(range(1, 33)))
OTHER_KEY = make_signing_key(bytes(range(101, 133)))
NOW = "2026-11-28T10:00:00+00:00"
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
EVIDENCE_HASH = "c" * 64
CANDIDATE = {"cycle_seq": 47, "payload_hash": CAND_HASH,
             "signer_id": "snapshot-svc",
             "key_id": "key-0123456789abcdef"}
OLD_PIN = {"cycle_seq": 41, "payload_hash": OLD_HASH}


def mint(**over):
    kwargs = dict(
        signing_key=VERIFIER_KEY, signer_id="verifier-svc",
        operator_id="operator-uma",
        ceremony_id="ceremony-2026-11-28-001",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN),
        candidate=dict(CANDIDATE), evidence_hash=EVIDENCE_HASH,
        evidence_ref="case-file-1", now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def payload_kwargs(**over):
    kwargs = dict(
        signer_id="verifier-svc", key_id=VERIFIER_KEY.key_id,
        operator_id="operator-uma",
        ceremony_id="ceremony-2026-11-28-001",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN),
        candidate=dict(CANDIDATE), evidence_hash=EVIDENCE_HASH,
        evidence_ref="case-file-1", signed_at=NOW,
        expires_at="2026-11-28T10:15:00+00:00")
    kwargs.update(over)
    return kwargs


class MirrorDriftTests(unittest.TestCase):
    def test_reasons_mirror_matches_pin_ceremony(self):
        # The mirror exists because importing pin_ceremony from
        # ceremony_authorisation would be circular; this pin is
        # what keeps the copy honest.
        self.assertEqual(REASONS, pin_ceremony.REASONS)
        self.assertEqual(_NO_PIN_REASONS,
                         pin_ceremony._NO_PIN_REASONS)


class PayloadProjectionTests(unittest.TestCase):
    def test_payload_shape(self):
        payload = ceremony_authorisation_payload(**payload_kwargs())
        self.assertEqual(payload["v"],
                         "signed-ceremony-authorisation/1")
        self.assertEqual(payload["alg"], "hmac-sha256")
        self.assertEqual(payload["purpose"],
                         "pin-ceremony-authorisation")
        self.assertEqual(set(payload["old_pin"]),
                         {"cycle_seq", "payload_hash"})
        self.assertEqual(set(payload["candidate"]),
                         {"cycle_seq", "payload_hash", "signer_id",
                          "key_id"})

    def test_unknown_reason_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(reason="whatever"))

    def test_no_pin_reason_with_pin_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(reason="lost_pin"))

    def test_gap_reason_without_pin_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(old_pin=None))

    def test_no_pin_reason_without_pin_ok(self):
        payload = ceremony_authorisation_payload(**payload_kwargs(
            reason="initial_anchor", old_pin=None))
        self.assertIsNone(payload["old_pin"])

    def test_gap_relation_refusals(self):
        for seq in (41, 40, 42):  # equal, backwards, +1 chained
            with self.assertRaises(SigningError, msg=f"seq {seq}"):
                ceremony_authorisation_payload(**payload_kwargs(
                    candidate=dict(CANDIDATE, cycle_seq=seq)))

    def test_pin_shape_refusals(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                old_pin=dict(OLD_PIN, key_id="key-x")))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                candidate=dict(CANDIDATE, extra=1)))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                candidate=dict(CANDIDATE, cycle_seq=True)))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                old_pin=dict(OLD_PIN, cycle_seq=-1)))

    def test_evidence_non_equality(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                evidence_hash=CAND_HASH))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                evidence_hash=OLD_HASH))

    def test_evidence_ref_refusals(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(evidence_ref=""))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(evidence_ref="x" * 2001))

    def test_window_over_hard_cap_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                expires_at="2026-11-28T10:15:01+00:00"))


class SignVerifyTests(unittest.TestCase):
    def test_round_trip(self):
        signed = mint()
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY,
                expected_signer_id="verifier-svc", now=NOW), ())

    def test_signer_need_not_equal_operator(self):
        # The structural divergence from attestation: the
        # verifier signs ABOUT the operator.
        signed = mint()
        self.assertNotEqual(signed.signer_id, signed.operator_id)
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY, now=NOW), ())

    def test_authorisation_id_derivation(self):
        signed = mint()
        self.assertEqual(
            signed.authorisation_id,
            authorisation_id_for(signed.payload_hash, signed.key_id))

    def test_ttl_default_and_hard_cap(self):
        signed = mint()
        start = datetime.fromisoformat(signed.signed_at)
        end = datetime.fromisoformat(signed.expires_at)
        self.assertEqual((end - start).total_seconds(), 900)
        capped = mint(ttl_seconds=172800)
        start = datetime.fromisoformat(capped.signed_at)
        end = datetime.fromisoformat(capped.expires_at)
        self.assertEqual((end - start).total_seconds(),
                         CEREMONY_AUTHORISATION_TTL_MAX_SECONDS)
        shorter = mint(ttl_seconds=120)
        start = datetime.fromisoformat(shorter.signed_at)
        end = datetime.fromisoformat(shorter.expires_at)
        self.assertEqual((end - start).total_seconds(), 120)

    def test_signature_mismatch(self):
        signed = mint()
        tampered = replace(signed, signature="0" * 64)
        reasons = verify_ceremony_authorisation(
            tampered, signing_key=VERIFIER_KEY, now=NOW)
        self.assertIn("signature_mismatch", reasons)

    def test_unknown_key(self):
        signed = mint()
        reasons = verify_ceremony_authorisation(
            signed, signing_key=OTHER_KEY, now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_key_id_inconsistent(self):
        bad_key = SigningKey(key_id="key-0000000000000000",
                             key=VERIFIER_KEY.key)
        self.assertEqual(
            verify_ceremony_authorisation(
                mint(), signing_key=bad_key, now=NOW),
            ("key_id_inconsistent",))

    def test_payload_hash_mismatch(self):
        signed = mint()
        tampered = replace(signed, payload_hash="d" * 64)
        reasons = verify_ceremony_authorisation(
            tampered, signing_key=VERIFIER_KEY, now=NOW)
        self.assertIn("payload_hash_mismatch", reasons)

    def test_authorisation_id_mismatch(self):
        signed = mint()
        tampered = replace(signed, authorisation_id="d" * 64)
        reasons = verify_ceremony_authorisation(
            tampered, signing_key=VERIFIER_KEY, now=NOW)
        self.assertIn("authorisation_id_mismatch", reasons)

    def test_malformed_payload_reason(self):
        signed = mint()
        tampered = replace(signed, evidence_ref="")
        reasons = verify_ceremony_authorisation(
            tampered, signing_key=VERIFIER_KEY, now=NOW)
        self.assertIn("malformed_payload", reasons)

    def test_binding_mismatches(self):
        signed = mint()
        cases = [
            ({"expected_signer_id": "other-svc"}, "signer_mismatch"),
            ({"expected_operator_id": "operator-x"},
             "operator_mismatch"),
            ({"expected_ceremony_id": "ceremony-x"},
             "ceremony_mismatch"),
            ({"expected_reason": "lost_pin"}, "reason_mismatch"),
            ({"expected_candidate": dict(CANDIDATE, cycle_seq=48)},
             "candidate_mismatch"),
            ({"expected_evidence_hash": "d" * 64},
             "evidence_mismatch"),
            ({"expected_evidence_ref": "other-ref"},
             "evidence_ref_mismatch"),
        ]
        for kwargs, reason in cases:
            reasons = verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY, now=NOW, **kwargs)
            self.assertIn(reason, reasons, msg=kwargs)

    def test_old_pin_sentinel_semantics(self):
        signed = mint()
        # Omitted: asserts nothing.
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY, now=NOW), ())
        # Exact dict: matches.
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY,
                expected_old_pin=dict(OLD_PIN), now=NOW), ())
        # Explicit None against a pin-carrying envelope: mismatch.
        reasons = verify_ceremony_authorisation(
            signed, signing_key=VERIFIER_KEY, expected_old_pin=None,
            now=NOW)
        self.assertIn("old_pin_mismatch", reasons)
        # Wrong pin: mismatch.
        reasons = verify_ceremony_authorisation(
            signed, signing_key=VERIFIER_KEY,
            expected_old_pin={"cycle_seq": 40,
                              "payload_hash": OLD_HASH}, now=NOW)
        self.assertIn("old_pin_mismatch", reasons)
        # And on a no-pin envelope, explicit None matches.
        no_pin = mint(reason="initial_anchor", old_pin=None)
        self.assertEqual(
            verify_ceremony_authorisation(
                no_pin, signing_key=VERIFIER_KEY,
                expected_old_pin=None, now=NOW), ())

    def test_expired_and_signed_in_future(self):
        signed = mint()
        later = (datetime.fromisoformat(NOW)
                 + timedelta(seconds=901)).isoformat()
        self.assertIn(
            "expired",
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY, now=later))
        earlier = (datetime.fromisoformat(NOW)
                   - timedelta(seconds=301)).isoformat()
        self.assertIn(
            "signed_in_future",
            verify_ceremony_authorisation(
                signed, signing_key=VERIFIER_KEY, now=earlier))

    def test_verify_rejects_non_envelope(self):
        with self.assertRaises(SigningError):
            verify_ceremony_authorisation(
                {"not": "an envelope"}, signing_key=VERIFIER_KEY,
                now=NOW)

    def test_domain_separation_from_attestation(self):
        # An attestation envelope dict is not a ceremony
        # authorisation envelope (strict key sets differ), and a
        # ceremony signature is MACed under its own domain.
        signed = mint()
        envelope = ceremony_authorisation_envelope_to_dict(signed)
        attestation_shaped = dict(envelope)
        attestation_shaped["attestation"] = attestation_shaped.pop(
            "operator_id")
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                attestation_shaped)


class SerialisationTests(unittest.TestCase):
    def test_dict_round_trip(self):
        signed = mint()
        restored = ceremony_authorisation_envelope_from_dict(
            ceremony_authorisation_envelope_to_dict(signed))
        self.assertEqual(restored, signed)

    def test_json_round_trip(self):
        signed = mint()
        restored = ceremony_authorisation_envelope_from_json(
            ceremony_authorisation_envelope_to_json(signed))
        self.assertEqual(restored, signed)

    def test_no_pin_dict_round_trip(self):
        signed = mint(reason="lost_pin", old_pin=None)
        envelope = ceremony_authorisation_envelope_to_dict(signed)
        self.assertIsNone(envelope["old_pin"])
        self.assertEqual(
            ceremony_authorisation_envelope_from_dict(envelope),
            signed)

    def test_strict_key_sets(self):
        envelope = ceremony_authorisation_envelope_to_dict(mint())
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, extra=1))
        shrunk = dict(envelope)
        del shrunk["reason"]
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(shrunk)
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, old_pin=dict(OLD_PIN, key_id="k")))
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, candidate={"cycle_seq": 47}))

    def test_hex64_fields_enforced(self):
        envelope = ceremony_authorisation_envelope_to_dict(mint())
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, signature="zz"))

    def test_json_strictness(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json(
                '{"operator_id":"a","operator_id":"b"}')
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json("not json")
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json(42)


if __name__ == "__main__":
    unittest.main()
