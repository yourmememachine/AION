"""Unit tests for signing/pin_store.py (cycle 22, design C §8.1).

Temp dirs only. Ceremony records are minted through the real
``reanchor_pin`` with a ledger-backed-shaped test consumer (a
plain callable — the R12 discipline for pure signing tests:
no hand-MACed records anywhere in this file).
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import signing.pin_store as pin_store_module
from signing import SigningError, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
    sign_ceremony_authorisation,
)
from signing.pin_ceremony import PinCeremonyRecord, reanchor_pin
from signing.pin_store import (
    PinMovedError,
    PinStore,
    PinStoreBusy,
    PinStoreError,
    ceremony_record_from_dict,
    ceremony_record_to_dict,
)
from signing.state_snapshot import sign_state_snapshot

SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
VERIFIER_SIGNER = "verifier-svc"
OPERATOR = "operator-1"
CAL = b'{"log":1}'


def state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq, "phase": "SCAN",
           "backlog": [], "history": history, "deltas": [],
           "history_pruned": 0, "deltas_pruned": 0,
           "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


def pin_of(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "key_id": s.key_id, "signer_id": s.signer_id}


class PinStoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.state_dir = base / "state"
        self.state_dir.mkdir()
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        self.seed_key = generate_ceremony_key_file(base / "ceremony.seed")
        self.pub = ceremony_public_key_for(self.seed_key)
        self._cid = 0
        self._ev = 0

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, seq, prev=""):
        return sign_state_snapshot(
            state_bytes(seq), signing_key=SNAP_KEY,
            signer_id=SNAP_SIGNER, calibration_bytes=CAL,
            prev_snapshot_hash=prev)

    def mint_record(self, old_pin, cand, *, history=(), reason=None):
        """Mint a genuine record through reanchor_pin."""
        self._cid += 1
        self._ev += 1
        evidence = hashlib.sha256(
            f"store-test-evidence-{self._ev}".encode()).hexdigest()
        reason = reason or (
            "chain_gap_recovery" if old_pin is not None
            else "initial_anchor")
        auth = sign_ceremony_authorisation(
            signing_key=self.seed_key, signer_id=VERIFIER_SIGNER,
            operator_id=OPERATOR,
            ceremony_id=f"store-ceremony-{self._cid}",
            reason=reason,
            old_pin=None if old_pin is None else {
                "cycle_seq": old_pin["cycle_seq"],
                "payload_hash": old_pin["payload_hash"]},
            candidate={"cycle_seq": cand.cycle_seq,
                       "payload_hash": cand.payload_hash,
                       "signer_id": cand.signer_id,
                       "key_id": cand.key_id},
            evidence_hash=evidence,
            evidence_ref=f"store-evidence-{self._ev}")
        new_pin, record = reanchor_pin(
            old_pin, cand, signing_key=SNAP_KEY,
            state_bytes=state_bytes(cand.cycle_seq),
            calibration_bytes=CAL, expected_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR, reason=reason,
            evidence_hash=evidence, authorisation=auth,
            authorisation_public_key=self.pub,
            expected_verifier_signer_id=VERIFIER_SIGNER,
            ceremony_history=history,
            consume_authorisation=lambda envelope: None,
            strict_reasons=("chain_gap",) if old_pin is not None
            else None)
        return new_pin, record

    def genesis(self):
        cand = self.snap(1)
        new_pin, record = self.mint_record(None, cand)
        self.store.adopt(new_pin, record, expected_old_pin=None,
                         signing_key=SNAP_KEY)
        return new_pin, record


class PinStoreTests(PinStoreFixture):

    def test_01_round_trip_genesis(self):
        new_pin, record = self.genesis()
        fresh = PinStore(self.pin_dir, state_dir=self.state_dir)
        pin, history = fresh.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin, new_pin)
        self.assertEqual(history, (record,))
        self.assertEqual(fresh.read_pin(signing_key=SNAP_KEY), new_pin)
        self.assertEqual(fresh.load_history(signing_key=SNAP_KEY),
                         (record,))
        # Serialisation round-trips exactly.
        self.assertEqual(
            ceremony_record_from_dict(ceremony_record_to_dict(record)),
            record)

    def test_02_fresh_pin_no_caching(self):
        pin1, _rec = self.genesis()
        self.assertEqual(self.store.read_pin(signing_key=SNAP_KEY), pin1)
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        pin2 = pin_of(cand2)
        self.store.adopt(pin2, record=None, expected_old_pin=pin1,
                         signing_key=SNAP_KEY)
        self.assertEqual(self.store.read_pin(signing_key=SNAP_KEY), pin2)
        self.assertNotEqual(pin1, pin2)

    def test_03_advance_preserves_history_ceremony_appends_one(self):
        pin1, rec1 = self.genesis()
        before = self.store.path.read_bytes()
        before_doc = json.loads(before)
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        self.store.adopt(pin_of(cand2), record=None,
                         expected_old_pin=pin1, signing_key=SNAP_KEY)
        after_doc = json.loads(self.store.path.read_bytes())
        self.assertEqual(after_doc["history"], before_doc["history"])
        # Ceremony adopt appends exactly one record.
        cand5 = self.snap(5, prev="f" * 64)
        pin5, rec5 = self.mint_record(
            pin_of(cand2), cand5, history=(rec1,))
        self.store.adopt(pin5, rec5, expected_old_pin=pin_of(cand2),
                         signing_key=SNAP_KEY)
        pin, history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin, pin5)
        self.assertEqual(history, (rec1, rec5))

    def test_04_cas_stale_expected_and_genesis_over_existing(self):
        pin1, _rec = self.genesis()
        before = self.store.path.read_bytes()
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        with self.assertRaises(PinMovedError):
            self.store.adopt(pin_of(cand2), record=None,
                             expected_old_pin=None,
                             signing_key=SNAP_KEY)
        stale = {"cycle_seq": 0, "payload_hash": "0" * 64}
        with self.assertRaises(PinMovedError):
            self.store.adopt(pin_of(cand2), record=None,
                             expected_old_pin=stale,
                             signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_05_non_regression_and_idempotent_noop(self):
        pin1, _rec = self.genesis()
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        pin2 = pin_of(cand2)
        self.store.adopt(pin2, record=None, expected_old_pin=pin1,
                         signing_key=SNAP_KEY)
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin1, record=None, expected_old_pin=pin2,
                             signing_key=SNAP_KEY)
        fork = dict(pin2, payload_hash="a" * 64)
        with self.assertRaises(PinStoreError):
            self.store.adopt(fork, record=None, expected_old_pin=pin2,
                             signing_key=SNAP_KEY)
        before = self.store.path.read_bytes()
        mtime = self.store.path.stat().st_mtime_ns
        self.store.adopt(pin2, record=None, expected_old_pin=pin2,
                         signing_key=SNAP_KEY)  # no-op
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.path.stat().st_mtime_ns, mtime)

    def test_06_record_binding_and_bad_mac_refused(self):
        pin1, rec1 = self.genesis()
        cand5 = self.snap(5, prev="f" * 64)
        _pin5, rec5 = self.mint_record(pin1, cand5, history=(rec1,))
        cand6 = self.snap(6, prev="e" * 64)
        before = self.store.path.read_bytes()
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin_of(cand6), rec5,
                             expected_old_pin=pin1,
                             signing_key=SNAP_KEY)
        bad = replace(rec5, signature="0" * 64)
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin_of(cand5), bad,
                             expected_old_pin=pin1,
                             signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_07_verified_load_tampering_refused_bytes_untouched(self):
        pin1, rec1 = self.genesis()
        doc = json.loads(self.store.path.read_bytes())
        doc["history"][0]["operator_id"] = "operator-2"
        tampered = json.dumps(doc).encode()
        self.store.path.write_bytes(tampered)
        with self.assertRaises(PinStoreError):
            self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), tampered)
        # Tampered pin: behind/at the history head with a
        # different hash.
        doc = json.loads(tampered)
        doc["history"][0] = ceremony_record_to_dict(rec1)
        doc["pin"] = dict(pin1, payload_hash="b" * 64)
        tampered2 = json.dumps(doc).encode()
        self.store.path.write_bytes(tampered2)
        with self.assertRaises(PinStoreError):
            self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), tampered2)
        # Duplicate evidence hash spliced on disk.
        doc = json.loads(tampered2)
        doc["pin"] = pin1
        doc["history"] = [ceremony_record_to_dict(rec1),
                          ceremony_record_to_dict(rec1)]
        self.store.path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(PinStoreError):
            self.store.read_all(signing_key=SNAP_KEY)
        # Forked targets: two genuine records, same new seq,
        # different hashes.
        cand_a = self.snap(4, prev="f" * 64)
        _pa, rec_a = self.mint_record(pin1, cand_a, history=(rec1,))
        cand_b = self.snap(4, prev="d" * 64)
        _pb, rec_b = self.mint_record(pin1, cand_b, history=(rec1,))
        self.assertNotEqual(rec_a.new_payload_hash,
                            rec_b.new_payload_hash)
        doc["history"] = [ceremony_record_to_dict(rec1),
                          ceremony_record_to_dict(rec_a),
                          ceremony_record_to_dict(rec_b)]
        doc["pin"] = _pa
        self.store.path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(PinStoreError):
            self.store.read_all(signing_key=SNAP_KEY)

    def test_08_corrupt_file_refused_on_read_and_adopt(self):
        pin1, _rec = self.genesis()
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        for payload in (
                b'{"v": "snapshot-pin-store/1", "pin": ',
                json.dumps({"v": "snapshot-pin-store/2",
                            "pin": None, "history": []}).encode(),
                b"x" * (pin_store_module.MAX_PIN_STORE_BYTES + 1)):
            self.store.path.write_bytes(payload)
            with self.assertRaises(PinStoreError):
                self.store.read_all(signing_key=SNAP_KEY)
            with self.assertRaises(PinStoreError):
                self.store.adopt(pin_of(cand2), record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
            self.assertEqual(self.store.path.read_bytes(), payload)

    def test_09_pin_dir_inside_or_equal_state_dir_refused(self):
        with self.assertRaises(PinStoreError):
            PinStore(self.state_dir / "pins", state_dir=self.state_dir)
        with self.assertRaises(PinStoreError):
            PinStore(self.state_dir, state_dir=self.state_dir)

    # -- crash points (design C §8.1 item 10) ------------------------------
    # Invariant in every crash test: pin and history are never
    # observed from different generations — a fresh read returns
    # the complete old generation or the complete new one.

    def _advance_attempt(self):
        pin1, rec1 = self.genesis()
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        return pin1, rec1, pin_of(cand2)

    def _assert_old_generation(self, pin1, rec1):
        pin, history = PinStore(
            self.pin_dir, state_dir=self.state_dir).read_all(
                signing_key=SNAP_KEY)
        self.assertEqual(pin, pin1)
        self.assertEqual(history, (rec1,))
        leftovers = [p.name for p in self.pin_dir.iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_10a_crash_inside_temp_write(self):
        pin1, rec1, pin2 = self._advance_attempt()
        real_mkstemp = pin_store_module.tempfile.mkstemp

        def full_device_mkstemp(*a, **kw):
            fd = os.open("/dev/full", os.O_WRONLY)
            return fd, str(self.pin_dir / ".snapshot-pin-full.tmp")

        with mock.patch.object(pin_store_module.tempfile, "mkstemp",
                               full_device_mkstemp):
            with self.assertRaises(OSError):
                self.store.adopt(pin2, record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
        self._assert_old_generation(pin1, rec1)

    def test_10b_crash_at_file_fsync(self):
        pin1, rec1, pin2 = self._advance_attempt()
        with mock.patch.object(os, "fsync",
                               side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                self.store.adopt(pin2, record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
        self._assert_old_generation(pin1, rec1)

    def test_10c_crash_at_replace(self):
        pin1, rec1, pin2 = self._advance_attempt()
        with mock.patch.object(os, "replace",
                               side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.store.adopt(pin2, record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
        self._assert_old_generation(pin1, rec1)

    def test_10d_crash_at_dir_fsync_after_replace_commits(self):
        # The rename is the commit point: a dir-fsync failure
        # after it is reported but NOT rolled back — a fresh
        # read returns the NEW document, whole.
        pin1, rec1, pin2 = self._advance_attempt()
        real_fsync = os.fsync
        calls = {"n": 0}

        def flaky_fsync(fd):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("dir fsync failed")
            return real_fsync(fd)

        with mock.patch.object(os, "fsync", flaky_fsync):
            with self.assertRaises(OSError):
                self.store.adopt(pin2, record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
        pin, history = PinStore(
            self.pin_dir, state_dir=self.state_dir).read_all(
                signing_key=SNAP_KEY)
        self.assertEqual(pin, pin2)
        self.assertEqual(history, (rec1,))

    def test_11_lock_busy_then_released(self):
        pin1, _rec = self.genesis()
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        import fcntl
        lock_fd = os.open(self.store.lock_path, os.O_CREAT | os.O_RDWR,
                          0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with self.assertRaises(PinStoreBusy):
                self.store.adopt(pin_of(cand2), record=None,
                                 expected_old_pin=pin1,
                                 signing_key=SNAP_KEY)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        self.store.adopt(pin_of(cand2), record=None,
                         expected_old_pin=pin1, signing_key=SNAP_KEY)
        self.assertEqual(self.store.read_pin(signing_key=SNAP_KEY),
                         pin_of(cand2))

    # -- rev-r3 regressions: adopt must bind the record to the
    # store's actual state and never write a document its own
    # verified load would refuse (F1/F2 counterexamples P1–P3).

    def _foreign_record_seq5(self, history=()):
        """A genuine chain_gap_recovery record whose old side is
        bound to a seq-3 pin this store has never held."""
        pin3 = pin_of(self.snap(3, prev="f" * 64))
        cand5 = self.snap(5, prev="e" * 64)
        return self.mint_record(pin3, cand5, history=history)

    def test_12_genesis_with_pin_record_refused(self):
        # P1: a with-pin record (chain_gap_recovery, old_seq=3)
        # must not create the store; genesis is for no-pin
        # (initial_anchor / lost_pin) records only.
        pin5, rec5 = self._foreign_record_seq5()
        self.assertEqual(rec5.reason, "chain_gap_recovery")
        self.assertEqual(rec5.old_cycle_seq, 3)
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin5, rec5, expected_old_pin=None,
                             signing_key=SNAP_KEY)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.store.read_all(signing_key=SNAP_KEY),
                         (None, ()))

    def test_13_old_side_mismatched_record_refused(self):
        # P2: a genuine record minted against a seq-3 pin must
        # not splice onto this store, whose pin sits at seq 1 —
        # the stored history would otherwise attest a ceremony
        # from seq 3 that never happened against this store.
        pin1, rec1 = self.genesis()
        pin5, rec5 = self._foreign_record_seq5(history=(rec1,))
        before = self.store.path.read_bytes()
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin5, rec5, expected_old_pin=pin1,
                             signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.read_all(signing_key=SNAP_KEY),
                         (pin1, (rec1,)))

    def test_14_readadopting_head_record_refused_store_usable(self):
        # P3: re-adopting the store's own head record at its own
        # target must refuse (already ceremonied / duplicate
        # evidence), not succeed and brick the store with a
        # document its own load then refuses forever.
        pin1, rec1 = self.genesis()
        before = self.store.path.read_bytes()
        with self.assertRaises(PinStoreError):
            self.store.adopt(pin1, rec1, expected_old_pin=pin1,
                             signing_key=SNAP_KEY)
        self.assertEqual(self.store.path.read_bytes(), before)
        # Still fully readable...
        self.assertEqual(self.store.read_all(signing_key=SNAP_KEY),
                         (pin1, (rec1,)))
        # ...and still adoptable.
        cand2 = self.snap(2, prev=pin1["payload_hash"])
        self.store.adopt(pin_of(cand2), record=None,
                         expected_old_pin=pin1, signing_key=SNAP_KEY)
        self.assertEqual(self.store.read_pin(signing_key=SNAP_KEY),
                         pin_of(cand2))

    def test_15_genesis_no_pin_burned_unadopted_creates_store(self):
        # Regression: a genesis (no-pin) ceremony that was
        # consumed but whose adoption failed before the store
        # file existed is recovered by a NO-PIN burned_unadopted
        # record adopted onto the still-missing file. Its old
        # side is absent, so the genesis SHAPE rule admits it
        # (a burned_unadopted record can only exist if the
        # verifier already proved the burn at authorise and
        # consumed it); the old reason whitelist refused it and
        # dead-ended that recovery path.
        cand = self.snap(1)
        new_pin, record = self.mint_record(
            None, cand, reason="burned_unadopted")
        self.assertEqual(record.reason, "burned_unadopted")
        self.assertIsNone(record.old_cycle_seq)
        self.assertEqual(record.old_payload_hash, "")
        self.assertFalse(self.store.path.exists())
        self.store.adopt(new_pin, record, expected_old_pin=None,
                         signing_key=SNAP_KEY)
        pin, history = PinStore(
            self.pin_dir, state_dir=self.state_dir).read_all(
                signing_key=SNAP_KEY)
        self.assertEqual(pin, new_pin)
        self.assertEqual(history, (record,))


if __name__ == "__main__":
    unittest.main()
