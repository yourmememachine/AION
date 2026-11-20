"""Tests for MemoryStore(signed_only=True) — the opt-in strict
mode from cycle 7. Default stores are byte-for-byte the cycle-4
behaviour (the existing suites pin that); a signed_only store
refuses plain commit_write and accepts only the envelope-verified
commit_signed path.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import VerifierAttestation
from memory.store import MemoryError, MemoryStore, decide_write
from signing import commit_signed, make_signing_key, sign_gate_decision

KEY = make_signing_key(bytes(range(32, 64)))
NOW = "2026-11-20T12:00:00+00:00"
SEALED = "b" * 64
BUILDERS = ["seat-9", "seat-10", "seat-11"]
REVIEWERS = ["seat-1", "seat-2", "seat-3", "seat-4", "seat-5", "seat-6"]


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


def accepted_decision(entry_fields):
    return decide_write(
        entry_fields=entry_fields, builder_ids=BUILDERS,
        reviewer_ids=REVIEWERS,
        baseline_public={"bench-a": 0.5},
        candidate_public={"bench-a": 0.6},
        baseline_sealed={"bench-s": 0.5},
        candidate_sealed={"bench-s": 0.7},
        capability_baseline={"cap-a": 0.5},
        capability_candidate={"cap-a": 0.5},
        attestation=VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="sealed-run-1",
            attested_at="2026-11-20T11:00:00+00:00"),
        expected_sealed_hash=SEALED)


class SignedOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_store_still_accepts_plain_commits(self):
        store = MemoryStore(self.dir)
        entry = store.commit_write(fields(), accepted_decision(fields()))
        self.assertEqual(entry["id"], "lesson-reverse")
        self.assertFalse(store.signed_only)

    def test_signed_only_refuses_plain_commit(self):
        store = MemoryStore(self.dir, signed_only=True)
        before = store.state_digest()
        with self.assertRaises(MemoryError):
            store.commit_write(fields(), accepted_decision(fields()))
        self.assertEqual(store.state_digest(), before)
        self.assertTrue(store.signed_only)

    def test_signed_only_accepts_commit_signed(self):
        store = MemoryStore(self.dir, signed_only=True)
        decision = accepted_decision(fields())
        envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="gate-signer",
            attestation=VerifierAttestation(
                verifier_id="seat-3", decision="approve",
                sealed_hash=SEALED, reward_hacking_checked=True,
                evidence_ref="sealed-run-1",
                attested_at="2026-11-20T11:00:00+00:00"),
            now=NOW)
        entry = commit_signed(store, fields(), envelope,
                              signing_key=KEY, now=NOW)
        self.assertEqual(entry["id"], "lesson-reverse")

    def test_state_digest_epoch_binding(self):
        # The decision is made against a snapshot of the store;
        # committing against a moved store is refused (by the
        # store, under its lock: MemoryError), committing against
        # the snapshot succeeds.
        store = MemoryStore(self.dir, signed_only=True)
        snapshot = store.state_digest()
        decision = accepted_decision(fields())
        envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="gate-signer",
            attestation=VerifierAttestation(
                verifier_id="seat-3", decision="approve",
                sealed_hash=SEALED, reward_hacking_checked=True,
                evidence_ref="sealed-run-1",
                attested_at="2026-11-20T11:00:00+00:00"),
            now=NOW)
        with self.assertRaises(MemoryError):
            commit_signed(store, fields(), envelope, signing_key=KEY,
                          now=NOW, expected_state_digest="0" * 64)
        entry = commit_signed(store, fields(), envelope,
                              signing_key=KEY, now=NOW,
                              expected_state_digest=snapshot)
        self.assertEqual(entry["id"], "lesson-reverse")

    def test_signed_only_flag_must_be_bool(self):
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir, signed_only="yes")

    def test_mode_is_persisted_and_plain_open_refused(self):
        # Trust Boundary v2 supersedes the cycle-7/8 stated limit:
        # the mode IS persisted in the memory file (covered by the
        # state digest), so a plain store over a signed_only
        # directory refuses to open at all. The full semantics —
        # ratchet, audited migration, legacy files, hand-flip
        # detection — are pinned in test_memory_security_mode.py.
        store = MemoryStore(self.dir, signed_only=True)
        decision = accepted_decision(fields())
        envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="gate-signer",
            attestation=VerifierAttestation(
                verifier_id="seat-3", decision="approve",
                sealed_hash=SEALED, reward_hacking_checked=True,
                evidence_ref="sealed-run-1",
                attested_at="2026-11-20T11:00:00+00:00"),
            now=NOW)
        commit_signed(store, fields(), envelope, signing_key=KEY,
                      now=NOW)
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)
        reopened = MemoryStore(self.dir, signed_only=True)
        self.assertTrue(reopened.signed_only)
        self.assertEqual(reopened.security_mode, "signed_only")


if __name__ == "__main__":
    unittest.main()
