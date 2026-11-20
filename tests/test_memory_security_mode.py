"""Tests for the persisted security mode (Trust Boundary v2,
mandate item 3): the store's signed_only mode is persisted in the
memory file as "security_mode", covered by the state digest,
non-downgradable on open, and changeable only through the audited
MemoryStore.migrate_security_mode. Legacy files without the field
load as "unsigned" via the legacy digest computation and gain the
field on first save.
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
    MemoryStoreError,
    _legacy_state_digest,
    _state_digest,
    decide_write,
    verify_migration_audit,
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


def commit_one_signed(store):
    decision = accepted_decision(fields())
    envelope = sign_gate_decision(
        decision, signing_key=KEY, signer_id="gate-signer",
        attestation=VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="sealed-run-1",
            attested_at="2026-11-20T11:00:00+00:00"),
        now=NOW)
    return commit_signed(store, fields(), envelope,
                         signing_key=KEY, now=NOW)


def read_doc(memory_dir):
    return json.loads((Path(memory_dir) / "memory.json").read_text())


def write_doc(memory_dir, data):
    (Path(memory_dir) / "memory.json").write_text(json.dumps(data))


class PersistedModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"

    def tearDown(self):
        self.tmp.cleanup()

    def make_signed_store(self):
        store = MemoryStore(self.dir, signed_only=True)
        commit_one_signed(store)
        return store

    def test_new_signed_store_persists_mode(self):
        self.make_signed_store()
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "signed_only")

    def test_new_unsigned_store_persists_mode(self):
        store = MemoryStore(self.dir)
        store.commit_write(fields(), accepted_decision(fields()))
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "unsigned")

    def test_plain_open_of_signed_store_refuses(self):
        self.make_signed_store()
        with self.assertRaises(MemoryStoreError):
            MemoryStore(self.dir)
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)

    def test_plain_open_refused_even_before_any_commit(self):
        # The mode is persisted from construction: an empty
        # signed_only store that has saved once refuses plain opens.
        MemoryStore(self.dir, signed_only=True).save()
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)

    def test_signed_open_of_signed_store_works(self):
        self.make_signed_store()
        reopened = MemoryStore(self.dir, signed_only=True)
        self.assertTrue(reopened.signed_only)
        self.assertEqual(reopened.security_mode, "signed_only")
        self.assertEqual(len(reopened.retrieve()), 1)

    def test_hand_flip_signed_to_unsigned_detected(self):
        # Flip the persisted field by hand, leave the digest stale:
        # the digest covers the field, so load must refuse.
        self.make_signed_store()
        data = read_doc(self.dir)
        data["security_mode"] = "unsigned"
        write_doc(self.dir, data)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir, signed_only=True)

    def test_hand_flip_unsigned_to_signed_detected(self):
        store = MemoryStore(self.dir)
        store.commit_write(fields(), accepted_decision(fields()))
        data = read_doc(self.dir)
        data["security_mode"] = "signed_only"
        write_doc(self.dir, data)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir, signed_only=True)

    def test_invalid_mode_value_is_corruption_even_rehashed(self):
        # Even with a correctly recomputed digest, a mode outside
        # the two valid values is corruption, not a third mode.
        store = MemoryStore(self.dir)
        store.save()
        data = read_doc(self.dir)
        data["security_mode"] = "sometimes"
        data["state_digest"] = _state_digest(data)
        write_doc(self.dir, data)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_ratchet_up_persists_on_next_save(self):
        store = MemoryStore(self.dir)
        store.commit_write(fields(), accepted_decision(fields()))
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "unsigned")
        strict = MemoryStore(self.dir, signed_only=True)
        self.assertEqual(strict.security_mode, "signed_only")
        strict.save()
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "signed_only")
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)


class LegacyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"

    def tearDown(self):
        self.tmp.cleanup()

    def make_legacy_doc(self):
        """A valid pre-field memory document: no security_mode key,
        digest in the legacy computation."""
        store = MemoryStore(self.dir)
        store.commit_write(fields(), accepted_decision(fields()))
        data = read_doc(self.dir)
        del data["security_mode"]
        data["state_digest"] = _legacy_state_digest(data)
        write_doc(self.dir, data)
        return data

    def test_legacy_file_loads_as_unsigned(self):
        self.make_legacy_doc()
        store = MemoryStore(self.dir)
        self.assertFalse(store.signed_only)
        self.assertEqual(store.security_mode, "unsigned")
        self.assertEqual(len(store.retrieve()), 1)

    def test_legacy_file_gains_field_on_save(self):
        self.make_legacy_doc()
        store = MemoryStore(self.dir)
        store.save()
        data = read_doc(self.dir)
        self.assertEqual(data["security_mode"], "unsigned")
        self.assertEqual(data["state_digest"], _state_digest(data))
        # And it now loads under the new-format validation.
        self.assertEqual(len(MemoryStore(self.dir).retrieve()), 1)

    def test_legacy_file_opened_signed_ratchets(self):
        self.make_legacy_doc()
        strict = MemoryStore(self.dir, signed_only=True)
        strict.save()
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "signed_only")
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)

    def test_legacy_digest_does_not_validate_field_bearing_file(self):
        # A file that CARRIES the field must not validate under the
        # legacy computation: otherwise flipping the field and
        # rehashing legacy-style would bypass the mode entirely.
        self.make_legacy_doc()
        data = read_doc(self.dir)
        data["security_mode"] = "unsigned"
        data["state_digest"] = _legacy_state_digest(data)
        write_doc(self.dir, data)
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "mem"
        store = MemoryStore(self.dir, signed_only=True)
        commit_one_signed(store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_downgrade_without_reason_refused(self):
        for bad_reason in ("", "   ", None):
            with self.assertRaises(MemoryError):
                MemoryStore.migrate_security_mode(
                    self.dir, to_mode="unsigned", actor="operator-1",
                    reason=bad_reason)
        # Nothing moved: still signed_only, no audit journal.
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)
        self.assertEqual(verify_migration_audit(self.dir), [])

    def test_downgrade_without_actor_refused(self):
        with self.assertRaises(MemoryError):
            MemoryStore.migrate_security_mode(
                self.dir, to_mode="unsigned", actor="",
                reason="documented rollback")
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)

    def test_audited_downgrade_succeeds_and_flips_mode(self):
        entry = MemoryStore.migrate_security_mode(
            self.dir, to_mode="unsigned", actor="operator-1",
            reason="signed path retired for this store")
        self.assertEqual(entry["from_mode"], "signed_only")
        self.assertEqual(entry["to_mode"], "unsigned")
        self.assertEqual(entry["actor"], "operator-1")
        # The persisted mode flipped and plain opens work again.
        self.assertEqual(read_doc(self.dir)["security_mode"],
                         "unsigned")
        plain = MemoryStore(self.dir)
        self.assertFalse(plain.signed_only)
        self.assertEqual(len(plain.retrieve()), 1)
        # The audit journal verifies and holds exactly this entry.
        entries = verify_migration_audit(self.dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["entry_hash"], entry["entry_hash"])
        self.assertEqual(entries[0]["reason"],
                         "signed path retired for this store")

    def test_migration_chain_extends_across_round_trip(self):
        MemoryStore.migrate_security_mode(
            self.dir, to_mode="unsigned", actor="operator-1",
            reason="rollback for maintenance")
        MemoryStore.migrate_security_mode(
            self.dir, to_mode="signed_only", actor="operator-1",
            reason="maintenance complete")
        entries = verify_migration_audit(self.dir)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["prev_hash"],
                         entries[0]["entry_hash"])
        self.assertEqual(entries[1]["from_mode"], "unsigned")
        with self.assertRaises(MemoryError):
            MemoryStore(self.dir)

    def test_noop_migration_refused(self):
        with self.assertRaises(MemoryError):
            MemoryStore.migrate_security_mode(
                self.dir, to_mode="signed_only", actor="operator-1",
                reason="already there")
        self.assertEqual(verify_migration_audit(self.dir), [])

    def test_migration_of_missing_store_refused(self):
        with self.assertRaises(MemoryError):
            MemoryStore.migrate_security_mode(
                Path(self.tmp.name) / "nope", to_mode="unsigned",
                actor="operator-1", reason="nothing there")

    def test_bad_to_mode_refused(self):
        with self.assertRaises(MemoryError):
            MemoryStore.migrate_security_mode(
                self.dir, to_mode="sometimes", actor="operator-1",
                reason="nope")

    def test_tampered_audit_journal_fails_closed(self):
        MemoryStore.migrate_security_mode(
            self.dir, to_mode="unsigned", actor="operator-1",
            reason="rollback for maintenance")
        audit_path = self.dir / "migration-audit.json"
        data = json.loads(audit_path.read_text())
        data["entries"][0]["reason"] = "rewritten after the fact"
        audit_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            verify_migration_audit(self.dir)
        # And a further migration refuses rather than extending a
        # broken chain.
        with self.assertRaises(CorruptMemoryError):
            MemoryStore.migrate_security_mode(
                self.dir, to_mode="signed_only", actor="operator-1",
                reason="back up")


if __name__ == "__main__":
    unittest.main()
