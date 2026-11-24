"""Cycle 28 tests: pin-store history reconciliation against the
verifier consumption journal (follow-up
``pin-store-history-reconciliation``, REREVIEW-14-16 §2/§6).

The store history is a non-authoritative, restoration-lossy
replica; the consumption journal is the sole authoritative
ceremony audit history. These tests pin DETECTION: a journal
entry behind the candidate that the store cannot account for
(by id+pair, by pair coverage, by a bound supersession
decision, or as the known-unadopted journal head) refuses with
the deterministic code ``pin_store_history_incomplete``.

Pure-function tests mint genuine PinCeremonyRecords through
the real ``reanchor_pin`` (the test_signing_pin_store fixture
pattern; no hand-MACed records). Integration tests use the
test_trust_pin_adoption fixture pattern (real verifier
subprocess, research env, temp dirs only).
"""

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
    sign_ceremony_authorisation,
)
from signing.pin_ceremony import reanchor_pin
from signing.pin_store import PinStore
from trust.client import VerifierClient
from trust.history_reconciliation import (
    HistoryReconciliationRefused,
    consumption_entries_provider_from_home,
    find_missing_history,
    reconcile_history,
    supersession_entries_provider_from_home,
)
from trust.ledger import CeremonyConsumptionLedger
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
    PinAdoptionRefused,
    run_one_cycle_and_pin,
)

SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
VERIFIER_SIGNER = "verifier-svc"
OPERATOR = "operator-1"
CAL = b'{"log":1}'

FAKE_AUTH = "b" * 64
FAKE_HASH = "c" * 64


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


def cons_entry(seq, *, authorisation_id, ceremony_id="ceremony-x",
               old_seq=None, old_hash="", new_seq, new_hash,
               evidence_hash="d" * 64):
    return {"seq": seq, "authorisation_id": authorisation_id,
            "ceremony_id": ceremony_id,
            "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
            "new_cycle_seq": new_seq, "new_payload_hash": new_hash,
            "evidence_hash": evidence_hash}


def entry_of_record(seq, rec):
    return cons_entry(
        seq, authorisation_id=rec.authorisation_id,
        ceremony_id=rec.ceremony_id, old_seq=rec.old_cycle_seq,
        old_hash=rec.old_payload_hash, new_seq=rec.new_cycle_seq,
        new_hash=rec.new_payload_hash, evidence_hash=rec.evidence_hash)


class RecordFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.seed_key = generate_ceremony_key_file(base / "ceremony.seed")
        self.pub = ceremony_public_key_for(self.seed_key)
        self._cid = 0
        self._ev = 0

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, seq, prev=""):
        from signing.state_snapshot import sign_state_snapshot
        return sign_state_snapshot(
            state_bytes(seq), signing_key=SNAP_KEY,
            signer_id=SNAP_SIGNER, calibration_bytes=CAL,
            prev_snapshot_hash=prev)

    def mint_record(self, old_pin, cand, *, history=(), reason=None):
        self._cid += 1
        self._ev += 1
        evidence = hashlib.sha256(
            f"c28-evidence-{self._ev}".encode()).hexdigest()
        reason = reason or (
            "chain_gap_recovery" if old_pin is not None
            else "initial_anchor")
        auth = sign_ceremony_authorisation(
            signing_key=self.seed_key, signer_id=VERIFIER_SIGNER,
            operator_id=OPERATOR,
            ceremony_id=f"c28-ceremony-{self._cid}",
            reason=reason,
            old_pin=None if old_pin is None else {
                "cycle_seq": old_pin["cycle_seq"],
                "payload_hash": old_pin["payload_hash"]},
            candidate={"cycle_seq": cand.cycle_seq,
                       "payload_hash": cand.payload_hash,
                       "signer_id": cand.signer_id,
                       "key_id": cand.key_id},
            evidence_hash=evidence,
            evidence_ref=f"c28-evidence-{self._ev}")
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

    def genesis_and_gap(self):
        """(pin1, rec1, rec4): genesis to seq 1, gap ceremony
        1 -> 4."""
        pin1, rec1 = self.mint_record(None, self.snap(1))
        cand4 = self.snap(4, prev="f" * 64)
        pin4, rec4 = self.mint_record(pin1, cand4, history=(rec1,))
        return pin1, rec1, pin4, rec4


class FindMissingTests(RecordFixture):

    def test_01_middle_restoration_gap(self):
        _pin1, rec1, _pin4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        e3 = entry_of_record(3, rec4)
        missing = find_missing_history(
            (rec1, rec4), (e1, e2, e3),
            candidate_seq=5, candidate_hash=FAKE_HASH)
        self.assertEqual(missing, (e2,))
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            reconcile_history(
                (rec1, rec4), (e1, e2, e3),
                candidate_seq=5, candidate_hash=FAKE_HASH)
        self.assertEqual(ctx.exception.code,
                         "pin_store_history_incomplete")
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         (FAKE_AUTH,))

    def test_02_gap_at_head_behind_candidate_flags(self):
        _pin1, rec1, _pin4, _rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        missing = find_missing_history(
            (rec1,), (e1, e2), candidate_seq=4,
            candidate_hash=FAKE_HASH)
        self.assertEqual(missing, (e2,))

    def test_03_empty_journal(self):
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        self.assertEqual(find_missing_history(
            (rec1,), (), candidate_seq=4, candidate_hash=FAKE_HASH),
            ())
        self.assertEqual(reconcile_history(
            (rec1,), (), candidate_seq=4, candidate_hash=FAKE_HASH),
            ())

    def test_04_empty_history_nonempty_journal(self):
        e1 = cons_entry(1, authorisation_id="a" * 64,
                        new_seq=1, new_hash="1" * 64)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash="1" * 64,
                        new_seq=2, new_hash="2" * 64)
        missing = find_missing_history(
            (), (e1, e2), candidate_seq=3, candidate_hash=FAKE_HASH)
        self.assertEqual(missing, (e1, e2))
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            reconcile_history(
                (), (e1, e2), candidate_seq=3,
                candidate_hash=FAKE_HASH)
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         ("a" * 64, FAKE_AUTH))

    def test_05_deterministic_under_shuffle(self):
        entries = tuple(
            cons_entry(i, authorisation_id=f"{i}" * 64,
                       old_seq=i - 1 if i > 1 else None,
                       old_hash="" if i == 1 else f"{i - 1}" * 64,
                       new_seq=i, new_hash=f"{i}" * 64)
            for i in (1, 2, 3))
        shuffled = (entries[2], entries[0], entries[1])
        first = find_missing_history(
            (), shuffled, candidate_seq=4, candidate_hash=FAKE_HASH)
        second = find_missing_history(
            (), entries, candidate_seq=4, candidate_hash=FAKE_HASH)
        self.assertEqual(first, entries)
        self.assertEqual(first, second)

    def test_06_recovery_pair_coverage(self):
        pin1, rec1 = self.mint_record(None, self.snap(1))
        cand3 = self.snap(3, prev="f" * 64)
        _pa, rec_a = self.mint_record(pin1, cand3, history=(rec1,))
        _pb, rec_b = self.mint_record(pin1, cand3, history=(rec1,))
        self.assertNotEqual(rec_a.authorisation_id,
                            rec_b.authorisation_id)
        # Journal holds the ORIGINAL burn; the store holds the
        # recovery record over the identical pair.
        e_burn = entry_of_record(2, rec_a)
        e1 = entry_of_record(1, rec1)
        self.assertEqual(find_missing_history(
            (rec1, rec_b), (e1, e_burn), candidate_seq=4,
            candidate_hash=FAKE_HASH), ())
        # Control: without the recovery record in the store,
        # the same burn entry flags.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_burn), candidate_seq=4,
            candidate_hash=FAKE_HASH), (e_burn,))

    def test_07_supersede_excused_when_superseding_record_present(self):
        _pin1, rec1, _pin4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        decision = {
            "seq": 1, "abandoned_authorisation_id": FAKE_AUTH,
            "abandoned_ceremony_id": "ceremony-x",
            "new_authorisation_id": rec4.authorisation_id,
            "new_ceremony_id": rec4.ceremony_id,
            "candidate_cycle_seq": rec4.new_cycle_seq,
            "candidate_payload_hash": rec4.new_payload_hash}
        self.assertEqual(find_missing_history(
            (rec1, rec4), (e1, e2), (decision,),
            candidate_seq=5, candidate_hash=FAKE_HASH), ())

    def test_08_supersede_decision_without_landed_record_flags(self):
        _pin1, rec1, _pin4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        decision = {
            "seq": 1, "abandoned_authorisation_id": FAKE_AUTH,
            "new_authorisation_id": rec4.authorisation_id,
            "candidate_cycle_seq": rec4.new_cycle_seq,
            "candidate_payload_hash": rec4.new_payload_hash}
        # Store lacks the superseding record: the decision
        # alone excuses nothing.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), (decision,), candidate_seq=5,
            candidate_hash=FAKE_HASH), (e2,))
        # A decision abandoning a DIFFERENT entry excuses
        # nothing either (fully bound check).
        other = dict(decision, abandoned_authorisation_id="9" * 64)
        self.assertEqual(find_missing_history(
            (rec1, rec4), (e1, e2), (other,), candidate_seq=5,
            candidate_hash=FAKE_HASH), (e2,))

    def test_09_known_unadopted_head_excused_nonhead_not(self):
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        # Head + known-unadopted + candidate AT the head
        # entry's own sequence (a rival movement at seq 3):
        # excused.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), candidate_seq=3,
            candidate_hash=FAKE_HASH,
            known_unadopted_authorisation_ids=(FAKE_AUTH,)), ())
        # Same entry, no excuse list: flags (control).
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), candidate_seq=3,
            candidate_hash=FAKE_HASH), (e2,))
        # CLAIM NARROWED (fix round, seat-gpt FIX 0.91): a
        # candidate BEYOND the head entry is never excused by
        # this rule, even when the head is listed
        # known-unadopted — the beyond reach silently excused
        # an adopted record's disappearance in the compound
        # adopted-line-loss + store-restore state. The head
        # entry itself now flags for a beyond candidate.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), candidate_seq=4,
            candidate_hash=FAKE_HASH,
            known_unadopted_authorisation_ids=(FAKE_AUTH,)), (e2,))
        # Non-head entry named known-unadopted: NOT excused —
        # the head can only move past a burn via its recovery
        # (pair coverage) or supersession (bound decision).
        # (With the narrowing, the seq-4 head entry also flags
        # for the seq-5 candidate: neither is excused.)
        e3 = cons_entry(3, authorisation_id="7" * 64,
                        old_seq=3, old_hash="e" * 64,
                        new_seq=4, new_hash="8" * 64)
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2, e3), candidate_seq=5,
            candidate_hash=FAKE_HASH,
            known_unadopted_authorisation_ids=(FAKE_AUTH, "7" * 64)),
            (e2, e3))

    def test_10_candidates_own_burn(self):
        _pin1, rec1, _p4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e_own = entry_of_record(2, rec4)
        # At the candidate's own exact pair the burn is not
        # even relevant (not behind the candidate, same hash):
        # it is the recovery input for THIS candidate.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_own), candidate_seq=4,
            candidate_hash=rec4.new_payload_hash), ())
        # A rival candidate AT the burned target's sequence is
        # excused as the known-unadopted head (the adopter's
        # pending journal attests it was consumed, never
        # adopted); it still cannot adopt past the head without
        # the verifier's recovery/supersession rules.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_own), candidate_seq=4,
            candidate_hash=FAKE_HASH,
            known_unadopted_authorisation_ids=(
                rec4.authorisation_id,)), ())
        # CLAIM NARROWED (fix round, seat-gpt FIX 0.91): once
        # the candidate has moved PAST the burned target, the
        # burn flags even WITH the known-unadopted binding —
        # the beyond-head reach is removed.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_own), candidate_seq=5,
            candidate_hash=FAKE_HASH,
            known_unadopted_authorisation_ids=(
                rec4.authorisation_id,)), (e_own,))
        # Without the known-unadopted binding it flags: the
        # function does not guess that a head entry is a burn.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_own), candidate_seq=5,
            candidate_hash=FAKE_HASH), (e_own,))

    def test_11_entry_after_candidate_ignored(self):
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e_future = cons_entry(2, authorisation_id=FAKE_AUTH,
                              old_seq=1,
                              old_hash=rec1.new_payload_hash,
                              new_seq=6, new_hash="6" * 64)
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e_future), candidate_seq=4,
            candidate_hash=FAKE_HASH), ())

    def test_12_fork_at_and_behind_candidate_flags(self):
        _pin1, rec1, _p4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        # Fork AT the candidate sequence, different hash.
        e_fork = cons_entry(2, authorisation_id=FAKE_AUTH,
                            old_seq=1, old_hash=rec1.new_payload_hash,
                            new_seq=4, new_hash="9" * 64)
        self.assertEqual(find_missing_history(
            (rec1, rec4), (e1, e_fork), candidate_seq=4,
            candidate_hash=rec4.new_payload_hash), (e_fork,))
        # Fork BEHIND the candidate: journal attests a seq-4
        # movement the store's seq-4 record does not represent.
        self.assertEqual(find_missing_history(
            (rec1, rec4), (e1, e_fork), candidate_seq=5,
            candidate_hash=FAKE_HASH), (e_fork,))

    def test_13_genesis_baseline(self):
        e1 = cons_entry(1, authorisation_id="a" * 64,
                        new_seq=1, new_hash="1" * 64)
        self.assertEqual(find_missing_history(
            (), (e1,), candidate_seq=1, candidate_hash="1" * 64,
            genesis_baseline=True), ())
        self.assertEqual(reconcile_history(
            (), (e1,), candidate_seq=1, candidate_hash="1" * 64,
            genesis_baseline=True), ())
        # Control: identical inputs WITHOUT the baseline flag
        # flag the entry — the baseline is the excuse, not a
        # property of the inputs.
        self.assertEqual(find_missing_history(
            (), (e1,), candidate_seq=2, candidate_hash=FAKE_HASH),
            (e1,))

    def test_19_supersede_candidate_pair_branch(self):
        # The in-flight supersession: the decision's candidate
        # pair IS the candidate under attempt, and the
        # superseding record is not in the store yet (it is
        # the record this attempt will adopt).
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        decision = {
            "seq": 1, "abandoned_authorisation_id": FAKE_AUTH,
            "abandoned_new_cycle_seq": 3,
            "abandoned_new_payload_hash": "e" * 64,
            "new_authorisation_id": "9" * 64,
            "candidate_cycle_seq": 5,
            "candidate_payload_hash": FAKE_HASH}
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), (decision,), candidate_seq=5,
            candidate_hash=FAKE_HASH), ())
        # Control: a different candidate does not match the
        # decision's pair, so the abandoned entry flags.
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), (decision,), candidate_seq=5,
            candidate_hash="8" * 64), (e2,))
        # A decision whose abandoned target fields describe a
        # DIFFERENT movement excuses nothing even when its
        # candidate pair matches.
        wrong_abandoned = dict(
            decision, abandoned_new_payload_hash="7" * 64)
        self.assertEqual(find_missing_history(
            (rec1,), (e1, e2), (wrong_abandoned,),
            candidate_seq=5, candidate_hash=FAKE_HASH), (e2,))

    def test_20_supersede_pair_covered_branch(self):
        # The superseding movement landed via its RECOVERY
        # record: the decision's new_authorisation_id is not
        # in the store, but its candidate pair is pair-covered
        # (with the decision's superseding old side).
        _pin1, rec1, _p4, rec4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash=rec1.new_payload_hash,
                        new_seq=3, new_hash="e" * 64)
        decision = {
            "seq": 1, "abandoned_authorisation_id": FAKE_AUTH,
            "new_authorisation_id": "9" * 64,
            "candidate_cycle_seq": rec4.new_cycle_seq,
            "candidate_payload_hash": rec4.new_payload_hash,
            "superseding_old_cycle_seq": rec4.old_cycle_seq,
            "superseding_old_payload_hash": rec4.old_payload_hash}
        self.assertEqual(find_missing_history(
            (rec1, rec4), (e1, e2), (decision,), candidate_seq=5,
            candidate_hash=FAKE_HASH), ())

    def test_21_duplicate_journal_ids_and_seqs_refuse(self):
        # rev-r6 regression: two journal entries sharing one
        # authorisation id must refuse outright — reconciling
        # against them would let the head excuse leak onto the
        # non-head entry sharing the head's id.
        e1 = cons_entry(1, authorisation_id=FAKE_AUTH,
                        new_seq=1, new_hash="1" * 64)
        e2 = cons_entry(2, authorisation_id=FAKE_AUTH,
                        old_seq=1, old_hash="1" * 64,
                        new_seq=2, new_hash="2" * 64)
        with self.assertRaises(SigningError):
            find_missing_history(
                (), (e1, e2), candidate_seq=3,
                candidate_hash=FAKE_HASH,
                known_unadopted_authorisation_ids=(FAKE_AUTH,))
        e_dup_seq = cons_entry(1, authorisation_id="9" * 64,
                               old_seq=1, old_hash="1" * 64,
                               new_seq=2, new_hash="2" * 64)
        with self.assertRaises(SigningError):
            find_missing_history(
                (), (e1, e_dup_seq), candidate_seq=3,
                candidate_hash=FAKE_HASH)

    def test_14_malformed_inputs_refuse(self):
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        e1 = entry_of_record(1, rec1)
        # Non-record history entries (a dict with the right
        # keys must NOT count as coverage).
        with self.assertRaises(SigningError):
            find_missing_history(
                ({"authorisation_id": rec1.authorisation_id},),
                (e1,), candidate_seq=4, candidate_hash=FAKE_HASH)
        with self.assertRaises(SigningError):
            find_missing_history(
                ("a-string",), (e1,), candidate_seq=4,
                candidate_hash=FAKE_HASH)
        # Journal entry missing a required key.
        bad = dict(e1)
        del bad["authorisation_id"]
        with self.assertRaises(SigningError):
            find_missing_history(
                (rec1,), (bad,), candidate_seq=4,
                candidate_hash=FAKE_HASH)
        # Bool sequence (bool is an int subclass; True == 1
        # would silently re-target the entry).
        bad2 = dict(e1, new_cycle_seq=True)
        with self.assertRaises(SigningError):
            find_missing_history(
                (rec1,), (bad2,), candidate_seq=4,
                candidate_hash=FAKE_HASH)
        # Duplicate authorisation id in the store history.
        pin1b, rec1b = self.mint_record(None, self.snap(1))
        dup = replace(rec1b, authorisation_id=rec1.authorisation_id)
        with self.assertRaises(SigningError):
            find_missing_history(
                (rec1, dup), (e1,), candidate_seq=4,
                candidate_hash=FAKE_HASH)

    def test_15_id_match_pair_mismatch_flags(self):
        _pin1, rec1, _p4, _r4 = self.genesis_and_gap()
        # Journal entry reusing rec1's authorisation id for a
        # DIFFERENT movement: an id-only match excuses nothing.
        e_bad = cons_entry(1, authorisation_id=rec1.authorisation_id,
                           ceremony_id=rec1.ceremony_id,
                           old_seq=None, old_hash="",
                           new_seq=2, new_hash="2" * 64,
                           evidence_hash=rec1.evidence_hash)
        self.assertEqual(find_missing_history(
            (rec1,), (e_bad,), candidate_seq=3,
            candidate_hash=FAKE_HASH), (e_bad,))


# -- PinAdopter integration -------------------------------------------------

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATORS = "operator-1,operator-2"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


class AdopterReconciliationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATORS,
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        self.state_dir = base / "state"
        self.loop = CoreLoop(self.state_dir)
        cal_dir = self.state_dir / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_path = cal_dir / "calibration.json"
        self.calibration_path.write_bytes(CAL)
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        self.adopter = self._make_adopter(self.client)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_adopter(self, client, **adopter_kw):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.evidence_dir)
        return PinAdopter(client=client, store=self.store,
                          signing_key=SNAP_KEY, config=config,
                          authorisation_public_key=self.pub,
                          **adopter_kw)

    def _wired_adopter(self):
        home = self.home / "ledger"
        return self._make_adopter(
            self.client,
            consumption_entries_provider=(
                consumption_entries_provider_from_home(home)),
            supersession_entries_provider=(
                supersession_entries_provider_from_home(home)))

    def scan_items(self, n):
        start = getattr(self, "_item_seq", 0)
        items = [{"id": f"item-{start + i}",
                  "title": f"Adoption item {start + i}",
                  "leverage": float(n - i)}
                 for i in range(1, n + 1)]
        self._item_seq = start + n
        self.loop.scan(items)

    def wrapped_cycle(self, adopter=None):
        return run_one_cycle_and_pin(
            self.loop, adopter or self.adopter, coders=CODERS,
            reviewers=REVIEWERS, verdict="reconciled",
            verify_passed=True, delta=DELTA)

    def bare_cycle(self):
        return self.loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)

    def consumption_entries(self):
        ledger = CeremonyConsumptionLedger(self.home / "ledger")
        return ledger.entries()

    def genesis(self):
        self.scan_items(1)
        _entry, result = self.wrapped_cycle()
        self.assertEqual(result.outcome, "reanchored")
        return result

    def restored_store_scenario(self):
        """Genesis to seq 1, gap ceremony to seq 3, then the
        pin-store file is restored to its genesis generation
        while the consumption journal keeps both entries.
        Returns (restored_bytes, gap_entry)."""
        self.genesis()
        genesis_bytes = self.store.path.read_bytes()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 3)
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(len(self.consumption_entries()), 2)
        gap_entry = self.consumption_entries()[-1]
        self.store.path.write_bytes(genesis_bytes)
        pin, history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertEqual(len(history), 1)
        self.scan_items(1)
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 4)
        return genesis_bytes, gap_entry


class AdopterReconciliationTests(AdopterReconciliationFixture):

    def test_16_restored_store_refuses_persists_nothing(self):
        restored_bytes, gap_entry = self.restored_store_scenario()
        wired = self._wired_adopter()
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            wired.snapshot_and_adopt()
        self.assertEqual(ctx.exception.code,
                         "pin_store_history_incomplete")
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         (gap_entry["authorisation_id"],))
        self.assertEqual(self.store.path.read_bytes(), restored_bytes)
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_17_no_provider_old_behaviour(self):
        # Pre-cycle-28 behaviour on the restored store, pinned
        # as-is: with the pin restored behind the consumption
        # head, the unwired adopter's fresh ceremony for seq 4
        # is supersede-shaped against the journal's seq-3 head
        # and stops as supersession-pending (the REREVIEW leg-4
        # shape) — crucially WITHOUT any history-completeness
        # signal: nothing in the outcome says the store is
        # missing the seq-3 record. That silence is the hole
        # test_16's wired refusal closes.
        from trust.pin_adoption import PinSupersessionPendingApproval
        _bytes, _gap = self.restored_store_scenario()
        with self.assertRaises(PinSupersessionPendingApproval):
            self.adopter.snapshot_and_adopt()
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_18_provider_matching_and_provider_failure(self):
        self.genesis()
        wired = self._wired_adopter()
        self.scan_items(1)
        _entry, result = self.wrapped_cycle(wired)
        self.assertEqual(result.outcome, "advanced")
        self.assertEqual(result.pin["cycle_seq"], 2)
        # Provider failure fails closed, never falls back.
        pin_bytes = self.store.path.read_bytes()

        def boom():
            raise RuntimeError("journal unreadable")

        broken = self._make_adopter(
            self.client, consumption_entries_provider=boom)
        self.scan_items(1)
        self.bare_cycle()
        with self.assertRaises(PinAdoptionRefused):
            broken.snapshot_and_adopt()
        self.assertEqual(self.store.path.read_bytes(), pin_bytes)
        malformed = self._make_adopter(
            self.client, consumption_entries_provider=lambda: [{}])
        with self.assertRaises(PinAdoptionRefused):
            malformed.snapshot_and_adopt()
        self.assertEqual(self.store.path.read_bytes(), pin_bytes)

    def test_19_wired_genesis_after_pin_loss_not_refused_by_reconciliation(self):
        # Genesis baseline through the adopter: the pin store
        # file is lost after a genesis consumption, so the
        # journal is non-empty when the wired adopter next
        # attempts (old pin None). Reconciliation must NOT be
        # the thing that refuses — whatever the ceremony layer
        # then decides about a genesis against a non-empty
        # journal is its own, pre-existing business.
        self.genesis()
        self.assertEqual(len(self.consumption_entries()), 1)
        self.store.path.unlink()
        wired = self._wired_adopter()
        try:
            wired.snapshot_and_adopt()
        except HistoryReconciliationRefused:
            self.fail(
                "genesis attempt refused by history "
                "reconciliation; the baseline wiring is wrong")
        except Exception:
            pass  # any other outcome is the ceremony layer's

    # -- Fix round (seat-gpt FIX 0.91): the known-unadopted head
    # excuse must not excuse an ADOPTED ceremony whose record
    # vanished in a store restore merely because the pending
    # journal lost the ceremony's "adopted" line. -------------

    def _adopted_gap_scenario(self):
        """Genesis to seq 1, gap ceremony A to seq 3 ADOPTED
        (store history holds A's record; the pending journal
        holds A's authorised/consumed/adopted lines), then the
        state advances to seq 4. Returns (genesis_store_bytes,
        pending_bytes_before_gap, gap_entry)."""
        self.genesis()
        genesis_bytes = self.store.path.read_bytes()
        pending_before = self.adopter.pending_journal_path.read_bytes()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 3)
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(len(self.consumption_entries()), 2)
        gap_entry = self.consumption_entries()[-1]
        pin, history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin["cycle_seq"], 3)
        self.assertEqual(len(history), 2)
        self.scan_items(1)
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 4)
        return genesis_bytes, pending_before, gap_entry

    def _strip_adopted_line(self, ceremony_id):
        path = self.adopter.pending_journal_path
        kept = []
        for line in path.read_bytes().decode("utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("ceremony_id") == ceremony_id \
                    and entry.get("phase") == "adopted":
                continue  # the lost append (crash / swallowed OSError)
            kept.append(line)
        path.write_bytes(("\n".join(kept) + "\n").encode("utf-8"))

    def test_22_compound_adopted_line_loss_plus_store_restore_refuses(self):
        # GPT scenario (a): A was adopted, but its "adopted"
        # pending-journal line is lost AND the store document
        # is restored to the pre-A generation. A is the
        # consumption head and the mutilated pending journal
        # still classifies A as a genuine (unadopted) burn, so
        # the head excuse must NOT silently excuse the exact
        # record whose disappearance detection exists to catch:
        # a beyond-A attempt must refuse
        # pin_store_history_incomplete naming A.
        genesis_bytes, _pending, gap_entry = self._adopted_gap_scenario()
        ceremony_id = gap_entry["ceremony_id"]
        self._strip_adopted_line(ceremony_id)
        self.store.path.write_bytes(genesis_bytes)
        wired = self._wired_adopter()
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            wired.snapshot_and_adopt()
        self.assertEqual(ctx.exception.code,
                         "pin_store_history_incomplete")
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         (gap_entry["authorisation_id"],))
        self.assertEqual(self.store.path.read_bytes(), genesis_bytes)
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_23_store_only_restore_intact_pending_refuses(self):
        # Scenario (b): store-document-only restore with the
        # pending journal INTACT — A's slot carries "adopted",
        # so A is not a genuine burn, is not known-unadopted,
        # and the missing record must refuse.
        genesis_bytes, _pending, gap_entry = self._adopted_gap_scenario()
        self.store.path.write_bytes(genesis_bytes)
        wired = self._wired_adopter()
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            wired.snapshot_and_adopt()
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         (gap_entry["authorisation_id"],))
        self.assertEqual(self.store.path.read_bytes(), genesis_bytes)

    def test_24_pending_journal_rollback_plus_store_restore_refuses(self):
        # Scenario (c), compound form: the pending journal is
        # independently rolled back to its pre-A generation (no
        # A lines at all) AND the store is restored pre-A. A is
        # then not known-unadopted by any evidence, so the
        # missing record must refuse.
        genesis_bytes, pending_before, gap_entry = \
            self._adopted_gap_scenario()
        self.adopter.pending_journal_path.write_bytes(pending_before)
        self.store.path.write_bytes(genesis_bytes)
        wired = self._wired_adopter()
        with self.assertRaises(HistoryReconciliationRefused) as ctx:
            wired.snapshot_and_adopt()
        self.assertEqual(ctx.exception.missing_authorisation_ids,
                         (gap_entry["authorisation_id"],))
        self.assertEqual(self.store.path.read_bytes(), genesis_bytes)

    def test_25_pending_journal_rollback_alone_store_record_covers(self):
        # Scenario (c), independent form: the pending journal
        # alone is rolled back to its pre-A generation while
        # the store document is INTACT — A's record is present
        # in the store history and pair-covers A's journal
        # entry, so reconciliation must NOT refuse; the
        # contiguous seq-4 candidate advances normally.
        _genesis, pending_before, _gap = self._adopted_gap_scenario()
        self.adopter.pending_journal_path.write_bytes(pending_before)
        wired = self._wired_adopter()
        result = wired.snapshot_and_adopt()
        self.assertEqual(result.outcome, "advanced")
        self.assertEqual(result.pin["cycle_seq"], 4)

    def test_20_runner_history_providers(self):
        # The production composition (trust/runner.py) builds
        # its providers through _history_providers; they must
        # return the real journal entries and load FRESH per
        # call (a provider built before genesis must see the
        # genesis entry afterwards).
        from trust.runner import _history_providers
        consumption_provider, supersession_provider = \
            _history_providers(
                {"AION_VERIFIER_HOME": str(self.home / "ledger")})
        self.assertEqual(consumption_provider(), [])
        self.assertEqual(supersession_provider(), [])
        self.genesis()
        entries = consumption_provider()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries, self.consumption_entries())
        # A verifier env without the home refuses with the
        # runner's structured config refusal, not a KeyError.
        from trust.runner import _ConfigRefusal
        with self.assertRaises(_ConfigRefusal):
            _history_providers({})


if __name__ == "__main__":
    unittest.main()
