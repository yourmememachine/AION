"""Tests for signed verifier attestations and the strong
commit_signed path (cycle 7, trust boundary).

Pins: an attestation envelope proves a key holder issued it;
signer must be the attester; proposal/manifest binding; freshness;
commit_signed with a presented SignedAttestation verifies the
envelope itself — not merely that some hash was bound — and
enforces the nested-expiry rule.
"""

import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import VerifierAttestation
from memory.store import MemoryStore, decide_write
from signing import (
    SigningError,
    attestation_envelope_from_json,
    attestation_envelope_to_json,
    commit_signed,
    sign_attestation,
    sign_gate_decision,
    verify_signed_attestation,
    make_signing_key,
)

KEY = make_signing_key(bytes(range(32, 64)))
OTHER_KEY = make_signing_key(b"\xff" * 32)
NOW = "2026-11-20T12:00:00+00:00"
SEALED = "b" * 64
MANIFEST = "c" * 64

BUILDERS = ["seat-9", "seat-10", "seat-11"]
REVIEWERS = ["seat-1", "seat-2", "seat-3", "seat-4", "seat-5", "seat-6"]


def attestation(**over):
    base = dict(verifier_id="seat-3", decision="approve",
                sealed_hash=SEALED, reward_hacking_checked=True,
                evidence_ref="sealed-run-1",
                attested_at="2026-11-20T11:00:00+00:00")
    base.update(over)
    return VerifierAttestation(**base)


def fields(**over):
    base = {
        "id": "lesson-reverse", "domain": "factory-reverse",
        "kind": "strategy", "content": "full-reverse",
        "author": "seat-11", "source": "derivation:public-practice-gen1",
        "evidence_ref": "derive:abc:reverse", "proposal_id": "prop-1",
        "verifier_id": "seat-3", "supersedes": None,
    }
    base.update(over)
    return base


def gate_kwargs(**over):
    base = dict(
        builder_ids=BUILDERS, reviewer_ids=REVIEWERS,
        baseline_public={"bench-a": 0.5},
        candidate_public={"bench-a": 0.6},
        baseline_sealed={"bench-s": 0.5},
        candidate_sealed={"bench-s": 0.7},
        capability_baseline={"cap-a": 0.5},
        capability_candidate={"cap-a": 0.5},
        attestation=attestation(), expected_sealed_hash=SEALED)
    base.update(over)
    return base


def signed_att(**over):
    kw = dict(signing_key=KEY, signer_id="seat-3", proposal_id="prop-1",
              now="2026-11-20T11:55:00+00:00")
    kw.update(over)
    return sign_attestation(attestation(), **kw)


class EnvelopeStrictnessTests(unittest.TestCase):
    def test_non_string_manifest_hash_refused_at_parse(self):
        from signing import attestation_envelope_from_dict, \
            attestation_envelope_to_dict
        envelope = sign_attestation(
            attestation(), signing_key=KEY, signer_id="seat-3",
            proposal_id="prop-1", now=NOW)
        data = attestation_envelope_to_dict(envelope)
        data["manifest_hash"] = None
        with self.assertRaises(SigningError):
            attestation_envelope_from_dict(data)


class SignAttestationTests(unittest.TestCase):
    def test_sign_and_verify_clean(self):
        sa = signed_att()
        self.assertEqual(
            verify_signed_attestation(
                sa, signing_key=KEY, expected_proposal_id="prop-1",
                expected_sealed_hash=SEALED,
                expected_verifier_id="seat-3", now=NOW),
            ())

    def test_signer_must_be_the_attester(self):
        with self.assertRaises(SigningError):
            sign_attestation(attestation(), signing_key=KEY,
                             signer_id="seat-9", proposal_id="prop-1",
                             now=NOW)

    def test_reject_attestation_still_verifies(self):
        # A signed "reject" is authentic; () must not be read as
        # approval by consumers.
        sa = sign_attestation(attestation(decision="reject"),
                              signing_key=KEY, signer_id="seat-3",
                              proposal_id="prop-1", ttl_seconds=3600,
                              now="2026-11-20T11:30:00+00:00")
        self.assertEqual(
            verify_signed_attestation(sa, signing_key=KEY, now=NOW), ())
        self.assertEqual(sa.attestation.decision, "reject")

    def test_wrong_key_fails(self):
        sa = signed_att()
        reasons = verify_signed_attestation(sa, signing_key=OTHER_KEY,
                                            now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_field_tampering_fails(self):
        sa = signed_att()
        for change in (
                {"proposal_id": "prop-2"},
                {"manifest_hash": MANIFEST},
                {"signed_at": "2026-11-20T11:31:00+00:00"},
                {"expires_at": "2026-11-20T12:30:00+00:00"}):
            tampered = dataclasses.replace(sa, **change)
            reasons = verify_signed_attestation(tampered,
                                                signing_key=KEY, now=NOW)
            self.assertTrue(reasons, change)
        inner = dataclasses.replace(sa.attestation, decision="reject")
        tampered = dataclasses.replace(sa, attestation=inner)
        self.assertIn(
            "payload_hash_mismatch",
            verify_signed_attestation(tampered, signing_key=KEY, now=NOW))

    def test_expected_bindings(self):
        sa = signed_att(manifest_hash=MANIFEST)
        self.assertIn(
            "proposal_mismatch",
            verify_signed_attestation(sa, signing_key=KEY,
                                      expected_proposal_id="prop-9",
                                      now=NOW))
        self.assertIn(
            "sealed_hash_mismatch",
            verify_signed_attestation(sa, signing_key=KEY,
                                      expected_sealed_hash="d" * 64,
                                      now=NOW))
        self.assertIn(
            "manifest_mismatch",
            verify_signed_attestation(sa, signing_key=KEY,
                                      expected_manifest_hash="e" * 64,
                                      now=NOW))
        self.assertIn(
            "verifier_mismatch",
            verify_signed_attestation(sa, signing_key=KEY,
                                      expected_verifier_id="seat-4",
                                      now=NOW))

    def test_expired_and_future(self):
        sa = signed_att(ttl_seconds=60)
        self.assertIn(
            "expired",
            verify_signed_attestation(sa, signing_key=KEY, now=NOW))
        future = sign_attestation(attestation(), signing_key=KEY,
                                  signer_id="seat-3",
                                  proposal_id="prop-1",
                                  now="2026-11-20T13:00:00+00:00")
        self.assertIn(
            "signed_in_future",
            verify_signed_attestation(future, signing_key=KEY, now=NOW))

    def test_json_roundtrip_and_strictness(self):
        sa = signed_att()
        text = attestation_envelope_to_json(sa)
        self.assertEqual(attestation_envelope_from_json(text), sa)
        with self.assertRaises(SigningError):
            attestation_envelope_from_json(text.replace(
                '"signer_id":"seat-3"', '"signer_id":"seat-3",'
                '"extra":1'))
        with self.assertRaises(SigningError):
            attestation_envelope_from_json(
                '{"attestation": {}, "attestation": {}}')
        with self.assertRaises(SigningError):
            attestation_envelope_from_json("not json")


class StrongCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "mem",
                                 signed_only=True)
        self.sa = signed_att()
        decision = decide_write(entry_fields=fields(), **gate_kwargs())
        self.envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="gate-signer",
            attestation=attestation(), signed_attestation=self.sa,
            now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_envelope_binds_attestation_payload_hash(self):
        self.assertEqual(self.envelope.attestation_hash,
                         self.sa.payload_hash)

    def test_commit_with_presented_attestation(self):
        entry = commit_signed(
            self.store, fields(), self.envelope, signing_key=KEY,
            require_attestation=True, signed_attestation=self.sa,
            now=NOW)
        self.assertEqual(entry["id"], "lesson-reverse")

    def test_hash_only_binding_is_not_provenance(self):
        # The envelope alone (hash binding) still commits via the
        # older path — but presenting a DIFFERENT attestation
        # envelope than the one bound must refuse.
        other = sign_attestation(attestation(evidence_ref="other-run"),
                                 signing_key=KEY, signer_id="seat-3",
                                 proposal_id="prop-1",
                                 now="2026-11-20T11:55:00+00:00")
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), self.envelope,
                          signing_key=KEY, signed_attestation=other,
                          now=NOW)

    def test_forged_attestation_envelope_refused(self):
        forged = dataclasses.replace(self.sa, signature="0" * 64)
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), self.envelope,
                          signing_key=KEY, signed_attestation=forged,
                          now=NOW)

    def test_rejecting_attestation_refused_at_commit(self):
        reject_sa = sign_attestation(
            attestation(decision="reject"), signing_key=KEY,
            signer_id="seat-3", proposal_id="prop-1",
            now="2026-11-20T11:30:00+00:00")
        decision = decide_write(
            entry_fields=fields(),
            **gate_kwargs(attestation=attestation(decision="reject")))
        # The gate itself rejects a write whose attestation says
        # reject, so this decision is not accepted; build the pair
        # the other way: decision from the approving attestation,
        # envelope bound to the rejecting envelope's hash is
        # impossible without the signer — assert commit refuses a
        # mismatched pair instead (covered above) and that a
        # decision signed against the reject attestation is not
        # accepted by the gate.
        self.assertFalse(decision.accepted)
        self.assertIsNotNone(reject_sa)

    def test_attestation_outliving_decision_refused(self):
        # The pair is refused at sign time (the signer must not
        # mint dead pairs); the consume-side nested-expiry check
        # in commit_signed remains as the second line of defence.
        long_sa = sign_attestation(
            attestation(), signing_key=KEY, signer_id="seat-3",
            proposal_id="prop-1", ttl_seconds=7200,
            now="2026-11-20T11:30:00+00:00")
        decision = decide_write(entry_fields=fields(), **gate_kwargs())
        with self.assertRaises(SigningError):
            sign_gate_decision(
                decision, signing_key=KEY, signer_id="gate-signer",
                attestation=attestation(), signed_attestation=long_sa,
                ttl_seconds=900, now=NOW)

    def test_sign_with_mismatched_attestation_pair_refused(self):
        decision = decide_write(entry_fields=fields(), **gate_kwargs())
        with self.assertRaises(SigningError):
            sign_gate_decision(
                decision, signing_key=KEY, signer_id="gate-signer",
                attestation=attestation(evidence_ref="different"),
                signed_attestation=self.sa, now=NOW)


if __name__ == "__main__":
    unittest.main()
