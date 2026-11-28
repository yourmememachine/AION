"""Adversarial tests for the Trust Boundary v2 fix round:

- CRITICAL-1: MemoryStore._commit_gated on a signed_only store
  must refuse a hand-constructed unsigned GateDecision — the exact
  review probe — and must require the one-shot permit that only
  the verified signing.commit_signed path mints.
- Permit binding: a permit is single-use, bound to one entry's
  content hash and to the store instance that minted it.
- F2: the migration-audit journal is consulted on open — a
  tampered journal or a journal/store mode mismatch refuses the
  open. Journal deletion is the documented accepted residual and
  is pinned as such (the store opens; the docs, not this test's
  wishes, own that limit).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import VerifierAttestation
from memory.store import (
    CorruptMemoryError,
    MemoryError,
    MemoryStore,
    _SignedCommitPermit,
    _state_digest,
    content_hash_for,
    decide_write,
)
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


def other_fields():
    return fields(id="lesson-largest", domain="factory-largest",
                  proposal_id="prop-2", content="pick-largest")


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


def commit_one_signed(store, entry_fields=None):
    entry_fields = entry_fields or fields()
    envelope = sign_gate_decision(
        accepted_decision(entry_fields), signing_key=KEY,
        signer_id="gate-signer",
        attestation=VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="sealed-run-1",
            attested_at="2026-11-20T11:00:00+00:00"),
        now=NOW)
    return commit_signed(store, entry_fields, envelope,
                         signing_key=KEY, now=NOW)


class Critical1ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"
        self.store = MemoryStore(self.dir, signed_only=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_critical1_probe_refused(self):
        # The review probe, verbatim in spirit: a hand-constructed
        # unsigned GateDecision(accepted=True) whose verifier_note
        # carries the entry's CORRECT content hash (decide_write
        # stamps exactly that binding), presented directly to
        # _commit_gated on a signed_only store. No key, no envelope,
        # no verifier. Before the fix this committed.
        decision = accepted_decision(fields())
        self.assertTrue(decision.accepted)
        self.assertTrue(decision.verifier_note.startswith(
            f"content-hash:{content_hash_for(fields())}"))
        with self.assertRaises(MemoryError):
            self.store._commit_gated(fields(), decision)
        self.assertEqual(self.store.retrieve(), [])

    def test_explicit_none_permit_refused(self):
        with self.assertRaises(MemoryError):
            self.store._commit_gated(
                fields(), accepted_decision(fields()), permit=None)
        self.assertEqual(self.store.retrieve(), [])

    def test_forged_permit_object_refused(self):
        # Constructing a permit object with invented values does
        # not forge one: its nonce is not in the store's
        # outstanding set.
        forged = _SignedCommitPermit(
            "ab" * 32, content_hash_for(fields()), "cd" * 16)
        with self.assertRaises(MemoryError):
            self.store._commit_gated(
                fields(), accepted_decision(fields()), permit=forged)
        self.assertEqual(self.store.retrieve(), [])

    def test_verified_commit_signed_path_still_works(self):
        entry = commit_one_signed(self.store)
        self.assertEqual(entry["id"], "lesson-reverse")
        self.assertEqual(len(self.store.retrieve()), 1)

    def test_unsigned_store_direct_gated_commit_unchanged(self):
        # The unsigned path keeps working exactly as before: no
        # permit required off a signed store.
        plain_dir = Path(self.tmp.name) / "plain"
        plain = MemoryStore(plain_dir)
        entry = plain._commit_gated(fields(), accepted_decision(fields()))
        self.assertEqual(entry["seq"], 1)


class PermitBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"
        self.store = MemoryStore(self.dir, signed_only=True)

    def tearDown(self):
        self.tmp.cleanup()

    def mint(self, entry_fields):
        return self.store._mint_signed_commit_permit(
            content_hash_for(entry_fields))

    def test_permit_reuse_refused(self):
        permit = self.mint(fields())
        entry = self.store._commit_gated(
            fields(), accepted_decision(fields()), permit=permit)
        self.assertEqual(entry["seq"], 1)
        # Second presentation of the SAME permit, now for a fresh,
        # otherwise-valid entry: the nonce was consumed on first
        # use, so this must refuse on the permit, not on any other
        # check (distinct id/domain/proposal avoid every other
        # refusal reason).
        with self.assertRaises(MemoryError) as caught:
            self.store._commit_gated(
                other_fields(), accepted_decision(other_fields()),
                permit=permit)
        self.assertIn("permit", str(caught.exception))
        self.assertEqual(len(self.store.retrieve()), 1)

    def test_permit_for_different_content_hash_refused(self):
        permit = self.mint(fields())
        with self.assertRaises(MemoryError) as caught:
            self.store._commit_gated(
                other_fields(), accepted_decision(other_fields()),
                permit=permit)
        self.assertIn("permit", str(caught.exception))
        self.assertEqual(self.store.retrieve(), [])

    def test_permit_for_different_store_refused(self):
        other_dir = Path(self.tmp.name) / "other"
        other_store = MemoryStore(other_dir, signed_only=True)
        foreign = other_store._mint_signed_commit_permit(
            content_hash_for(fields()))
        with self.assertRaises(MemoryError) as caught:
            self.store._commit_gated(
                fields(), accepted_decision(fields()), permit=foreign)
        self.assertIn("permit", str(caught.exception))
        self.assertEqual(self.store.retrieve(), [])

    def test_permit_for_other_instance_same_directory_refused(self):
        # Store identity is per-instance: a second instance over
        # the SAME directory must not honour the first's permits.
        commit_one_signed(self.store)
        second = MemoryStore(self.dir, signed_only=True)
        permit = self.mint(other_fields())
        with self.assertRaises(MemoryError):
            second._commit_gated(
                other_fields(), accepted_decision(other_fields()),
                permit=permit)
        self.assertEqual(len(second.retrieve()), 1)


class MigrationJournalOnOpenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"
        store = MemoryStore(self.dir, signed_only=True)
        commit_one_signed(store)
        MemoryStore.migrate_security_mode(
            self.dir, to_mode="unsigned", actor="operator-1",
            reason="signed path retired for this store")

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_journal_opens_fine(self):
        plain = MemoryStore(self.dir)
        self.assertEqual(plain.security_mode, "unsigned")
        self.assertEqual(len(plain.retrieve()), 1)

    def test_tampered_journal_refuses_open(self):
        audit_path = self.dir / "migration-audit.json"
        data = json.loads(audit_path.read_text())
        data["entries"][0]["reason"] = "rewritten after the fact"
        audit_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir, signed_only=True)

    def test_broken_journal_json_refuses_open(self):
        (self.dir / "migration-audit.json").write_text("{not json")
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_journal_mode_mismatch_refuses_open(self):
        # Migrate back up: journal's final mode is now signed_only
        # and the file agrees. Then rewrite the file's persisted
        # mode to "unsigned" WITH a correctly recomputed digest —
        # the digest alone cannot catch this (unkeyed), but the
        # journal's final recorded mode disagrees, so open refuses.
        MemoryStore.migrate_security_mode(
            self.dir, to_mode="signed_only", actor="operator-1",
            reason="signed path restored")
        doc_path = self.dir / "memory.json"
        data = json.loads(doc_path.read_text())
        data["security_mode"] = "unsigned"
        data["state_digest"] = _state_digest(data)
        doc_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir, signed_only=True)

    def test_journal_deletion_is_the_documented_residual(self):
        # Accepted residual, pinned honestly: deleting the journal
        # removes what the open-time check consults, so the store
        # opens. The store docstring states this plainly; this test
        # exists so the behaviour is a recorded decision, not an
        # accident.
        (self.dir / "migration-audit.json").unlink()
        plain = MemoryStore(self.dir)
        self.assertEqual(len(plain.retrieve()), 1)


if __name__ == "__main__":
    unittest.main()
