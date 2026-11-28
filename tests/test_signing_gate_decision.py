"""Tests for MAC-authenticated (signed) gate decisions.

Standard library only. Pins the review red-team list: field flips,
transplants, note-segment swaps, alg/key confusion, expiry, replay
against another entry, and the strict commit_signed path.
"""

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import GateDecision, Regression, VerifierAttestation
from memory.store import MemoryError, MemoryStore, content_hash_for, decide_write
from signing import (
    SigningError,
    attestation_hash_for,
    commit_signed,
    decision_payload,
    envelope_from_json,
    envelope_to_json,
    generate_key_file,
    key_id_for,
    load_signing_key,
    make_signing_key,
    payload_hash_for,
    self_test,
    sign_gate_decision,
    verify_signed_decision,
)

KEY = make_signing_key(bytes(range(32, 64)))
OTHER_KEY = make_signing_key(b"\xff" * 32)
NOW = "2026-11-20T12:00:00+00:00"
HASH = "a" * 64
SEALED = "b" * 64

BUILDERS = ["seat-9", "seat-10", "seat-11"]
REVIEWERS = ["seat-1", "seat-2", "seat-3", "seat-4", "seat-5", "seat-6"]


def attestation(**over):
    base = dict(verifier_id="seat-3", decision="approve", sealed_hash=SEALED,
                reward_hacking_checked=True, evidence_ref="sealed-run-1",
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
        baseline_public={"bench-a": 0.5}, candidate_public={"bench-a": 0.6},
        baseline_sealed={"bench-s": 0.5}, candidate_sealed={"bench-s": 0.7},
        capability_baseline={"cap-a": 0.5},
        capability_candidate={"cap-a": 0.5},
        attestation=attestation(), expected_sealed_hash=SEALED)
    base.update(over)
    return base


def accepted_decision(entry_fields=None, **over):
    return decide_write(entry_fields=entry_fields or fields(),
                        **gate_kwargs(**over))


def rejected_decision():
    return decide_write(
        entry_fields=fields(),
        **gate_kwargs(candidate_sealed={"bench-s": 0.4}))


def sign(decision, **kw):
    kw.setdefault("signer_id", "gate-signer")
    kw.setdefault("now", NOW)
    return sign_gate_decision(decision, signing_key=KEY, **kw)


class KeyTests(unittest.TestCase):
    def test_key_id_is_derived_and_stable(self):
        self.assertEqual(key_id_for(bytes(range(32, 64))), KEY.key_id)
        self.assertTrue(KEY.key_id.startswith("key-"))

    def test_short_key_refused(self):
        with self.assertRaises(SigningError):
            make_signing_key(b"too-short")

    def test_repr_never_leaks_key_bytes(self):
        self.assertNotIn(KEY.key.hex(), repr(KEY))
        self.assertIn(KEY.key_id, repr(KEY))

    def test_generate_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            made = generate_key_file(path)
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            loaded = load_signing_key(path)
            self.assertEqual(loaded.key_id, made.key_id)
            self.assertEqual(loaded.key, made.key)

    def test_generate_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            generate_key_file(path)
            with self.assertRaises(SigningError):
                generate_key_file(path)

    def test_load_refuses_broad_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            generate_key_file(path)
            os.chmod(path, 0o644)
            with self.assertRaises(SigningError):
                load_signing_key(path)

    def test_load_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real.key"
            generate_key_file(real)
            link = Path(tmp) / "link.key"
            link.symlink_to(real)
            with self.assertRaises(SigningError):
                load_signing_key(link)

    def test_load_refuses_forbidden_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            os.chmod(repo, 0o755)
            path = repo / "gate.key"
            generate_key_file(path)
            with self.assertRaises(SigningError):
                load_signing_key(path, forbidden_roots=[repo])
            with self.assertRaises(SigningError):
                generate_key_file(repo / "other.key", forbidden_roots=[repo])

    def test_load_refuses_non_hex_and_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.key"
            path.write_text("not-hex-at-all\n")
            os.chmod(path, 0o600)
            with self.assertRaises(SigningError):
                load_signing_key(path)
            path.write_text("abcd\n")
            with self.assertRaises(SigningError):
                load_signing_key(path)


class SignVerifyTests(unittest.TestCase):
    def test_roundtrip_verifies_clean(self):
        signed = sign(accepted_decision(), attestation=attestation())
        self.assertEqual(
            verify_signed_decision(signed, signing_key=KEY, now=NOW), ())

    def test_rejected_decision_also_signs_and_verifies(self):
        signed = sign(rejected_decision())
        self.assertFalse(signed.decision.accepted)
        self.assertEqual(
            verify_signed_decision(signed, signing_key=KEY, now=NOW), ())

    def test_attestation_hash_binds_attestation(self):
        signed = sign(accepted_decision(), attestation=attestation())
        self.assertEqual(signed.attestation_hash,
                         attestation_hash_for(attestation()))
        other = sign(accepted_decision(),
                     attestation=attestation(evidence_ref="sealed-run-2"))
        self.assertNotEqual(signed.payload_hash, other.payload_hash)

    def test_golden_vector_payload_hash_is_pinned(self):
        # Byte-for-byte canonicalisation pin: any drift in field set,
        # ordering or float rendering breaks this vector loudly.
        decision = GateDecision(
            accepted=True, proposal_id="prop-1", reasons=(),
            regressions=(), forgetting_failures=(), verifier_id="seat-3",
            evaluated_at="2026-11-20T00:00:00+00:00",
            verifier_note="content-hash:" + HASH)
        payload = decision_payload(
            decision, signer_id="gate-signer", key_id=KEY.key_id,
            signed_at=NOW, expires_at="2026-11-20T14:00:00+00:00",
            attestation_hash=attestation_hash_for(attestation()))
        self.assertEqual(payload["v"], "signed-gate-decision/1")
        self.assertEqual(payload["verifier_note"], "content-hash:" + HASH)
        # Literal pin: any canonicalisation drift (field set, ordering,
        # float rendering, domain/alg strings) changes this hash and
        # breaks the suite loudly instead of drifting silently.
        self.assertEqual(
            payload_hash_for(payload),
            "9c1dc6156cab66b442c1beb5e0a9769544a594fe41b8b1bfce808d3fd4a1ca27")
        again = decision_payload(
            decision, signer_id="gate-signer", key_id=KEY.key_id,
            signed_at=NOW, expires_at="2026-11-20T14:00:00+00:00",
            attestation_hash=attestation_hash_for(attestation()))
        self.assertEqual(payload_hash_for(payload), payload_hash_for(again))

    def test_wrong_key_fails(self):
        signed = sign(accepted_decision())
        reasons = verify_signed_decision(signed, signing_key=OTHER_KEY, now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_expired_envelope_fails(self):
        signed = sign(accepted_decision(), ttl_seconds=60)
        reasons = verify_signed_decision(
            signed, signing_key=KEY, now="2026-11-20T12:02:00+00:00")
        self.assertIn("expired", reasons)

    def test_signed_in_future_fails(self):
        signed = sign(accepted_decision())
        reasons = verify_signed_decision(
            signed, signing_key=KEY, now="2026-11-20T11:00:00+00:00")
        self.assertIn("signed_in_future", reasons)

    def test_purpose_mismatch_fails(self):
        signed = sign(accepted_decision(), purpose="canary-commit")
        reasons = verify_signed_decision(signed, signing_key=KEY, now=NOW)
        self.assertIn("purpose_mismatch", reasons)

    def test_proposal_expectation_mismatch_fails(self):
        signed = sign(accepted_decision())
        reasons = verify_signed_decision(
            signed, signing_key=KEY, expected_proposal_id="prop-2", now=NOW)
        self.assertIn("proposal_mismatch", reasons)

    def test_ttl_bounds_enforced(self):
        with self.assertRaises(SigningError):
            sign(accepted_decision(), ttl_seconds=30)
        with self.assertRaises(SigningError):
            sign(accepted_decision(), ttl_seconds=999999)

    def test_self_test_passes(self):
        self.assertTrue(self_test(KEY))


class TamperTests(unittest.TestCase):
    """Red-team list: every mutation must fail verification."""

    def setUp(self):
        self.signed = sign(accepted_decision(), attestation=attestation())

    def verify(self, signed):
        return verify_signed_decision(signed, signing_key=KEY, now=NOW)

    def test_accepted_flip_fails(self):
        forged = dataclasses.replace(
            self.signed,
            decision=dataclasses.replace(self.signed.decision, accepted=False))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_reason_removal_fails(self):
        signed = sign(rejected_decision())
        forged = dataclasses.replace(
            signed, decision=dataclasses.replace(
                signed.decision, reasons=(), accepted=True))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_note_tail_swap_fails(self):
        forged = dataclasses.replace(
            self.signed, decision=dataclasses.replace(
                self.signed.decision,
                verifier_note=self.signed.decision.verifier_note + "; forged"))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_note_binding_segment_swap_fails(self):
        forged = dataclasses.replace(
            self.signed, decision=dataclasses.replace(
                self.signed.decision,
                verifier_note="content-hash:" + "c" * 64))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_verifier_swap_fails(self):
        forged = dataclasses.replace(
            self.signed,
            decision=dataclasses.replace(self.signed.decision,
                                         verifier_id="seat-4"))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_regression_row_tamper_fails(self):
        reg = Regression("sealed", "bench-s", 0.5, 0.4, -0.1)
        decision = dataclasses.replace(
            self.signed.decision, accepted=False, reasons=("regression",),
            regressions=(reg,))
        signed = sign(decision)
        forged = dataclasses.replace(
            signed, decision=dataclasses.replace(
                signed.decision, regressions=()))
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_signature_truncation_fails(self):
        forged = dataclasses.replace(
            self.signed, signature=self.signed.signature[:32])
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_payload_hash_field_tamper_fails(self):
        forged = dataclasses.replace(self.signed, payload_hash="0" * 64)
        reasons = self.verify(forged)
        self.assertIn("payload_hash_mismatch", reasons)

    def test_key_id_swap_fails(self):
        forged = dataclasses.replace(self.signed, key_id=OTHER_KEY.key_id)
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_expiry_extension_fails(self):
        forged = dataclasses.replace(
            self.signed, expires_at="2027-01-01T00:00:00+00:00")
        # The extended window is outside the TTL bounds no signer
        # would emit, so verification refuses it as malformed; a
        # within-bounds extension fails the MAC instead (next test).
        self.assertIn("malformed_payload", self.verify(forged))

    def test_expiry_extension_within_bounds_fails_mac(self):
        forged = dataclasses.replace(
            self.signed, expires_at="2026-11-20T13:30:00+00:00")
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_entry_binding_check_catches_cross_entry_port(self):
        other_fields = fields(id="lesson-other", content="other-lesson")
        reasons = verify_signed_decision(
            self.signed, signing_key=KEY,
            expected_entry_content_hash=content_hash_for(other_fields),
            now=NOW)
        self.assertIn("entry_binding_mismatch", reasons)

    def test_entry_binding_check_passes_for_own_entry(self):
        reasons = verify_signed_decision(
            self.signed, signing_key=KEY,
            expected_entry_content_hash=content_hash_for(fields()), now=NOW)
        self.assertEqual(reasons, ())

    def test_nonfinite_regression_rejected_at_signing(self):
        reg = Regression("sealed", "bench-s", 0.5, float("nan"), 0.0)
        decision = dataclasses.replace(
            self.signed.decision, regressions=(reg,))
        with self.assertRaises(SigningError):
            sign(decision)


class EnvelopeJsonTests(unittest.TestCase):
    def setUp(self):
        self.signed = sign(accepted_decision(), attestation=attestation())

    def test_json_roundtrip_verifies(self):
        restored = envelope_from_json(envelope_to_json(self.signed))
        self.assertEqual(restored, self.signed)
        self.assertEqual(
            verify_signed_decision(restored, signing_key=KEY, now=NOW), ())

    def test_json_tamper_fails_verification(self):
        data = json.loads(envelope_to_json(self.signed))
        data["decision"]["verifier_id"] = "seat-4"
        restored = envelope_from_json(json.dumps(data))
        reasons = verify_signed_decision(restored, signing_key=KEY, now=NOW)
        self.assertIn("signature_mismatch", reasons)

    def test_unknown_envelope_key_rejected(self):
        data = json.loads(envelope_to_json(self.signed))
        data["extra"] = "nope"
        with self.assertRaises(SigningError):
            envelope_from_json(json.dumps(data))

    def test_unknown_decision_key_rejected(self):
        data = json.loads(envelope_to_json(self.signed))
        data["decision"]["extra"] = "nope"
        with self.assertRaises(SigningError):
            envelope_from_json(json.dumps(data))

    def test_duplicate_keys_rejected(self):
        text = envelope_to_json(self.signed)
        dup = text.replace('"signer_id"', '"signer_id"', 1)
        dup = '{"signer_id": "gate-signer", ' + dup[1:]
        with self.assertRaises(SigningError):
            envelope_from_json(dup)

    def test_nonfinite_number_rejected(self):
        # Structurally valid envelope whose regression carries 1e999:
        # the parse_float guard itself must be what rejects it.
        data = json.loads(envelope_to_json(sign(rejected_decision())))
        data["decision"]["regressions"] = [{
            "suite": "sealed", "benchmark_id": "bench-s",
            "baseline": 0.5, "candidate": 0.4, "delta": -0.1}]
        text = json.dumps(data).replace('"baseline": 0.5',
                                        '"baseline": 1e999')
        with self.assertRaises(SigningError):
            envelope_from_json(text)
        with self.assertRaises(SigningError):
            envelope_from_json('{"x": NaN}')


class CommitSignedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = MemoryStore(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_signed_commit_happy_path(self):
        entry_fields = fields()
        signed = sign(accepted_decision(entry_fields),
                      attestation=attestation())
        entry = commit_signed(self.store, entry_fields, signed,
                              signing_key=KEY, now=NOW)
        self.assertEqual(entry["id"], "lesson-reverse")
        fresh = MemoryStore(self.dir)
        self.assertEqual(len(fresh.retrieve()), 1)

    def test_handbuilt_unsigned_decision_cannot_use_strict_path(self):
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), accepted_decision(),
                          signing_key=KEY, now=NOW)
        self.assertEqual(self.store.retrieve(), [])

    def test_forged_envelope_commits_nothing(self):
        signed = sign(accepted_decision(), attestation=attestation())
        forged = dataclasses.replace(
            signed, decision=dataclasses.replace(
                signed.decision, verifier_note="content-hash:" + "c" * 64))
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), forged,
                          signing_key=KEY, now=NOW)
        self.assertEqual(self.store.retrieve(), [])

    def test_signed_decision_for_other_entry_commits_nothing(self):
        signed = sign(accepted_decision(), attestation=attestation())
        other = fields(id="lesson-other", domain="other-domain",
                       proposal_id="prop-1")
        with self.assertRaises(SigningError):  # entry_binding_mismatch
            commit_signed(self.store, other, signed,
                          signing_key=KEY, now=NOW)
        self.assertEqual(self.store.retrieve(), [])

    def test_signed_reject_commits_nothing(self):
        signed = sign(rejected_decision())
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), signed,
                          signing_key=KEY, now=NOW)
        self.assertEqual(self.store.retrieve(), [])

    def test_expired_envelope_commits_nothing(self):
        signed = sign(accepted_decision(), ttl_seconds=60)
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), signed, signing_key=KEY,
                          now="2026-11-20T13:00:00+00:00")
        self.assertEqual(self.store.retrieve(), [])

    def test_wrong_key_commits_nothing(self):
        signed = sign(accepted_decision())
        with self.assertRaises(SigningError):
            commit_signed(self.store, fields(), signed,
                          signing_key=OTHER_KEY, now=NOW)
        self.assertEqual(self.store.retrieve(), [])

    def test_double_present_commits_once(self):
        entry_fields = fields()
        signed = sign(accepted_decision(entry_fields))
        commit_signed(self.store, entry_fields, signed,
                      signing_key=KEY, now=NOW)
        with self.assertRaises(MemoryError):
            commit_signed(self.store, entry_fields, signed,
                          signing_key=KEY, now=NOW)
        self.assertEqual(len(self.store.retrieve()), 1)

    def test_plain_path_unchanged_for_legacy_callers(self):
        # Compat: the unsigned path still exists (caller discipline);
        # the strict path is additive, exactly as designed.
        entry = self.store.commit_write(fields(), accepted_decision())
        self.assertEqual(entry["seq"], 1)


class ReviewFixTests(unittest.TestCase):
    """Pins for the cycle-7 review fix list (R1/R2/R4/R5/R6)."""

    def setUp(self):
        self.signed = sign(accepted_decision(), attestation=attestation())

    def verify(self, signed, **kw):
        kw.setdefault("now", NOW)
        return verify_signed_decision(signed, signing_key=KEY, **kw)

    # R4#1: no silent coercion into a predictable key
    def test_make_signing_key_rejects_non_bytes(self):
        for bad in (32, [0] * 32, "A" * 40, None, 3.5):
            with self.assertRaises(SigningError):
                make_signing_key(bad)

    # R1#1/R2#6: non-ASCII signature is a reason, never a TypeError
    def test_non_ascii_signature_returns_reason(self):
        forged = dataclasses.replace(self.signed, signature="é" * 64)
        self.assertIn("signature_mismatch", self.verify(forged))

    def test_non_hex_signature_returns_reason(self):
        forged = dataclasses.replace(self.signed, signature="z" * 64)
        self.assertIn("signature_mismatch", self.verify(forged))

    # R1#2: lone surrogates / invisible chars in the note are refused
    def test_surrogate_note_rejected_at_signing(self):
        decision = dataclasses.replace(
            self.signed.decision,
            verifier_note="content-hash:" + HASH + "\ud800")
        with self.assertRaises(SigningError):
            sign(decision)

    def test_invisible_char_note_rejected_at_signing(self):
        decision = dataclasses.replace(
            self.signed.decision,
            verifier_note="content-hash:" + HASH + " e")
        with self.assertRaises(SigningError):
            sign(decision)

    # R1#3/R2#7: nonsense fields no longer verify clean
    def test_garbage_evaluated_at_rejected_at_signing(self):
        decision = dataclasses.replace(
            self.signed.decision, evaluated_at="NOT-A-DATE")
        with self.assertRaises(SigningError):
            sign(decision)

    def test_garbage_regression_identifiers_rejected(self):
        reg = Regression(123, "bench-s", 0.5, 0.4, -0.1)
        decision = dataclasses.replace(
            self.signed.decision, regressions=(reg,))
        with self.assertRaises(SigningError):
            sign(decision)
        reg = Regression("sealed", {"x": 1}, 0.5, 0.4, -0.1)
        decision = dataclasses.replace(
            self.signed.decision, regressions=(reg,))
        with self.assertRaises(SigningError):
            sign(decision)

    def test_non_id_reason_rejected_at_signing(self):
        decision = dataclasses.replace(
            self.signed.decision, reasons=(123,))
        with self.assertRaises(SigningError):
            sign(decision)

    # R1#5: float exactness and -0.0 normalisation
    def test_huge_int_regression_rejected(self):
        reg = Regression("sealed", "bench-s", 10 ** 400, 0.4, -0.1)
        decision = dataclasses.replace(
            self.signed.decision, regressions=(reg,))
        with self.assertRaises(SigningError):
            sign(decision)

    def test_negative_zero_normalises_to_same_payload(self):
        def payload_for(delta):
            reg = Regression("sealed", "bench-s", 0.5, 0.5, delta)
            decision = dataclasses.replace(
                self.signed.decision, accepted=False,
                reasons=("regression",), regressions=(reg,))
            return decision_payload(
                decision, signer_id="gate-signer", key_id=KEY.key_id,
                signed_at=NOW, expires_at="2026-11-20T14:00:00+00:00")
        self.assertEqual(payload_hash_for(payload_for(-0.0)),
                         payload_hash_for(payload_for(0.0)))

    def test_out_of_range_score_rejected(self):
        reg = Regression("sealed", "bench-s", 1.5, 0.4, -0.1)
        decision = dataclasses.replace(
            self.signed.decision, regressions=(reg,))
        with self.assertRaises(SigningError):
            sign(decision)

    # R1#6: one instant, one envelope — Z and offset spellings agree
    def test_timestamp_spellings_canonicalise_identically(self):
        decision = accepted_decision()
        a = sign(decision, now="2026-11-20T12:00:00Z")
        b = sign(decision, now="2026-11-20T12:00:00+00:00")
        c = sign(decision, now="2026-11-20T13:00:00+01:00")
        self.assertEqual(a.payload_hash, b.payload_hash)
        self.assertEqual(a.payload_hash, c.payload_hash)
        self.assertEqual(a.signature, b.signature)

    # R5#2: decision_id is load-bearing and pinned
    def test_decision_id_tamper_isolated(self):
        forged = dataclasses.replace(self.signed, decision_id="0" * 64)
        self.assertEqual(self.verify(forged), ("decision_id_mismatch",))

    def test_decision_id_for_is_deterministic(self):
        from signing import decision_id_for
        self.assertEqual(
            decision_id_for(self.signed.payload_hash, KEY.key_id),
            self.signed.decision_id)

    # R5#3: gate_inputs_hash is covered both ways
    def test_gate_inputs_hash_roundtrip_and_tamper(self):
        signed = sign(accepted_decision(), gate_inputs_hash="e" * 64)
        self.assertEqual(self.verify(signed), ())
        forged = dataclasses.replace(signed, gate_inputs_hash="f" * 64)
        self.assertIn("signature_mismatch", self.verify(forged))
        reasons = self.verify(
            signed, expected_gate_inputs_hash="f" * 64)
        self.assertIn("gate_inputs_mismatch", reasons)

    # R1#7/R2#3: attestation expectations on the strict path
    def test_expected_attestation_hash(self):
        reasons = self.verify(
            self.signed,
            expected_attestation_hash=attestation_hash_for(
                attestation(evidence_ref="sealed-run-2")))
        self.assertIn("attestation_mismatch", reasons)
        self.assertEqual(self.verify(
            self.signed,
            expected_attestation_hash=self.signed.attestation_hash), ())

    def test_expected_signer_id(self):
        reasons = self.verify(self.signed, expected_signer_id="mallory-1")
        self.assertIn("signer_mismatch", reasons)

    def test_require_attestation_refuses_unattested(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = MemoryStore(Path(tmp.name))
        unattested = sign(accepted_decision())
        with self.assertRaises(SigningError):
            commit_signed(store, fields(), unattested, signing_key=KEY,
                          require_attestation=True, now=NOW)
        self.assertEqual(store.retrieve(), [])
        attested = sign(accepted_decision(), attestation=attestation())
        entry = commit_signed(store, fields(), attested, signing_key=KEY,
                              require_attestation=True, now=NOW)
        self.assertEqual(entry["seq"], 1)

    # R2#5: verify itself flags an inconsistent accept
    def test_inconsistent_accept_flagged_by_verify(self):
        decision = dataclasses.replace(
            self.signed.decision, reasons=("regression",))
        signed = sign(decision)
        self.assertIn("inconsistent_decision", self.verify(signed))

    # R2#8: commit_signed refuses a missing proposal id outright
    def test_commit_signed_missing_proposal_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = MemoryStore(Path(tmp.name))
        entry_fields = fields()
        del entry_fields["proposal_id"]
        with self.assertRaises(SigningError):
            commit_signed(store, entry_fields, self.signed,
                          signing_key=KEY, now=NOW)

    # R4#5: the verifier's own key must be internally consistent
    def test_inconsistent_verify_key_flagged(self):
        bad_key = dataclasses.replace(KEY, key=OTHER_KEY.key)
        reasons = verify_signed_decision(
            self.signed, signing_key=bad_key, now=NOW)
        self.assertEqual(reasons, ("key_id_inconsistent",))

    # R4: repo is a forbidden root by default; symlinked parent refused
    def test_key_inside_repo_refused_by_default(self):
        repo_file = Path(__file__).resolve().parents[1] / "gate.key"
        with self.assertRaises(SigningError):
            load_signing_key(repo_file)
        with self.assertRaises(SigningError):
            generate_key_file(repo_file)

    def test_symlinked_parent_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real"
            real_dir.mkdir()
            os.chmod(real_dir, 0o755)
            link_dir = Path(tmp) / "link"
            link_dir.symlink_to(real_dir, target_is_directory=True)
            with self.assertRaises(SigningError):
                generate_key_file(link_dir / "gate.key")

    def test_load_rejects_oversize_and_wrong_length_key_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            path.write_text((b"\x01" * 33).hex() + "\n")
            os.chmod(path, 0o600)
            with self.assertRaises(SigningError):
                load_signing_key(path)
            path.write_text("AB" * 32 + "\n")  # uppercase hex refused
            with self.assertRaises(SigningError):
                load_signing_key(path)

    def test_load_missing_file_is_signing_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SigningError):
                load_signing_key(Path(tmp) / "nope.key")

    # R4#8: empty now is malformed, not wall-clock
    def test_empty_now_rejected(self):
        with self.assertRaises(SigningError):
            sign(accepted_decision(), now="")
        with self.assertRaises(SigningError):
            self.verify(self.signed, now="")

    # R5#4: exact reason sets for the headline flips
    def test_accepted_flip_exact_reasons(self):
        forged = dataclasses.replace(
            self.signed,
            decision=dataclasses.replace(self.signed.decision,
                                         accepted=False))
        self.assertEqual(
            self.verify(forged),
            ("payload_hash_mismatch", "decision_id_mismatch",
             "signature_mismatch"))

    # R5#5: remaining field flips
    def test_field_flips_fail(self):
        flips = [
            dataclasses.replace(self.signed, signer_id="mallory-1"),
            dataclasses.replace(
                self.signed, decision=dataclasses.replace(
                    self.signed.decision, proposal_id="prop-2")),
            dataclasses.replace(
                self.signed, decision=dataclasses.replace(
                    self.signed.decision,
                    evaluated_at="2026-11-20T01:00:00+00:00")),
            dataclasses.replace(self.signed, attestation_hash="c" * 64),
            dataclasses.replace(
                self.signed, decision=dataclasses.replace(
                    self.signed.decision,
                    protected_violations=("eval/gate.py",))),
            dataclasses.replace(
                self.signed, decision=dataclasses.replace(
                    self.signed.decision,
                    forgetting_failures=(Regression(
                        "capability", "cap-a", 0.5, 0.4, -0.1),))),
        ]
        for forged in flips:
            self.assertIn("signature_mismatch", self.verify(forged))

    # R5#7: round-trip with non-empty collections, dict-level too
    def test_roundtrip_nonempty_collections(self):
        from signing import envelope_from_dict, envelope_to_dict
        signed = sign(rejected_decision(), attestation=attestation())
        self.assertTrue(signed.decision.regressions)
        restored = envelope_from_dict(envelope_to_dict(signed))
        self.assertEqual(restored, signed)
        restored_json = envelope_from_json(envelope_to_json(signed))
        self.assertEqual(restored_json, signed)
        self.assertEqual(self.verify(restored), ())

    def test_envelope_rejects_non_list_reasons(self):
        data = json.loads(envelope_to_json(self.signed))
        data["decision"]["reasons"] = 123
        with self.assertRaises(SigningError):
            envelope_from_json(json.dumps(data))
        data = json.loads(envelope_to_json(self.signed))
        data["decision"]["regressions"] = 123
        with self.assertRaises(SigningError):
            envelope_from_json(json.dumps(data))

    def test_envelope_rejects_non_hex_auth_fields(self):
        data = json.loads(envelope_to_json(self.signed))
        data["signature"] = 123
        with self.assertRaises(SigningError):
            envelope_from_json(json.dumps(data))

    def test_nested_duplicate_keys_rejected(self):
        text = envelope_to_json(self.signed)
        dup = text.replace('"accepted": true',
                           '"accepted": false, "accepted": true', 1)
        self.assertNotEqual(dup, text)
        with self.assertRaises(SigningError):
            envelope_from_json(dup)

    # R5#10: constants pinned
    def test_constants_pinned(self):
        import signing
        self.assertEqual(signing.ALG, "hmac-sha256")
        self.assertEqual(signing.DOMAIN, "signed-gate-decision-v1")
        self.assertEqual(signing.KEY_BYTES, 32)
        self.assertEqual(signing.CLOCK_SKEW_SECONDS, 300)
        self.assertEqual(signing.TTL_MIN_SECONDS, 60)
        self.assertEqual(signing.TTL_DEFAULT_SECONDS, 900)
        self.assertEqual(signing.TTL_MAX_SECONDS, 172800)
        self.assertEqual(signing.PURPOSE_MEMORY_COMMIT, "memory-commit")

    # R5#11/#12: validation branches and boundaries
    def test_sign_validation_branches(self):
        with self.assertRaises(SigningError):
            sign(accepted_decision(), signer_id="Bad Id")
        with self.assertRaises(SigningError):
            sign(accepted_decision(), ttl_seconds=True)
        with self.assertRaises(SigningError):
            sign(accepted_decision(), ttl_seconds=60.5)
        decision = dataclasses.replace(
            self.signed.decision, verifier_note="x" * 2001)
        with self.assertRaises(SigningError):
            sign(decision)
        decision = dataclasses.replace(
            self.signed.decision, accepted=1)
        with self.assertRaises(SigningError):
            sign(decision)

    def test_ttl_boundaries_sign_ok(self):
        sign(accepted_decision(), ttl_seconds=60)
        sign(accepted_decision(), ttl_seconds=172800)

    def test_skew_and_expiry_boundaries(self):
        signed = sign(accepted_decision(), ttl_seconds=3600)
        # exactly +300s future-dated: inside skew, verifies
        self.assertEqual(verify_signed_decision(
            signed, signing_key=KEY, now="2026-11-20T11:55:00+00:00"), ())
        reasons = verify_signed_decision(
            signed, signing_key=KEY, now="2026-11-20T11:54:59+00:00")
        self.assertIn("signed_in_future", reasons)
        # exactly at expiry: expired
        reasons = verify_signed_decision(
            signed, signing_key=KEY, now="2026-11-20T13:00:00+00:00")
        self.assertIn("expired", reasons)

    def test_verify_type_errors_raise_signing_error(self):
        with self.assertRaises(SigningError):
            verify_signed_decision("nope", signing_key=KEY, now=NOW)
        with self.assertRaises(SigningError):
            verify_signed_decision(self.signed, signing_key=b"x" * 32,
                                   now=NOW)
        with self.assertRaises(SigningError):
            self.verify(self.signed, expected_entry_content_hash="nope")

    def test_self_test_bad_key_returns_false(self):
        self.assertFalse(self_test("not-a-key"))
        self.assertFalse(self_test(OTHER_KEY, signer_id="Bad Id"))


if __name__ == "__main__":
    unittest.main()
