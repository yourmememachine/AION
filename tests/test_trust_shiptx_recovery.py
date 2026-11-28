"""Adversarial recovery tests for trust.shiptx / trust.shipcheck
(Trust Boundary v2 fix round): the war-room findings against the
original recovery.

Pins: H1 (another ship's cycle is never attributed to a crashed
transaction; one ship in flight per item), the fabricated-
provenance cases (recovery never journals AUTHORISATION_VERIFIED
or an unverified POST_RECORD_VERIFIED, and never finalises
blind), the deliberate-drift case, H2 (a post-burn transaction
whose burn is missing parks at ANOMALY and one poisoned
transaction never blocks the others), H3 (loop history is
consulted before REFUSED_PRE_BURN; ship-anchor failure parks at
ANOMALY), M1 (concurrent recovery/appends cannot corrupt the
hash chain), L2 (exact (cycle_id, item) match preferred;
item-only fallback only when unambiguous) and L3 (begin with a
different item for an existing tx raises).
"""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_trust_shiptx as _fixture_module

from trust.anchoring import initialise_anchor
from trust.errors import ShipRefused
from trust.ledger import LedgerError, ShipLedger
from trust.shipcheck import recover_ship_tx
from trust.shiptx import (
    ABORTED_SPENT,
    ANOMALY,
    AUTHORISATION_VERIFIED,
    BURN_PENDING,
    COMMITTED,
    CYCLE_RECORDED,
    POST_RECORD_VERIFIED,
    PREPARED,
    REFUSED_PRE_BURN,
    ShipTxJournal,
)

TxFixture = _fixture_module.TxFixture
NOW = _fixture_module.NOW


def _refresh_clock():
    """Re-stamp the fixture clock (cycle 33): NOW is copied from
    test_trust_shiptx at import time and goes stale during a long
    test run; refresh the source module and re-read its stamp."""
    global NOW
    _fixture_module._refresh_clock()
    NOW = _fixture_module.NOW
ITEM = _fixture_module.ITEM
PROPOSAL = _fixture_module.PROPOSAL


class StubLoop:
    """A loop stand-in carrying only the history recovery reads."""

    def __init__(self, history):
        self.state = {"history": list(history)}


class JournalRecoveryFixture(unittest.TestCase):
    def setUp(self):
        _refresh_clock()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.journal = ShipTxJournal(self.home)
        self.ledger = ShipLedger(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def walk(self, tx_id, *states, cycle_id=""):
        for state in states:
            kw = {}
            if state == CYCLE_RECORDED:
                kw["cycle_id"] = cycle_id
            self.journal.transition(tx_id, state, NOW, **kw)

    def burn(self, decision_id, manifest_hash):
        self.ledger.burn(decision_id=decision_id, proposal_id="p-1",
                         manifest_hash=manifest_hash,
                         payload_hash="e" * 64, recorded_at=NOW)

    def states_of(self, tx_id):
        return [e["to_state"] for e in self.journal.entries()
                if e["tx_id"] == tx_id]

    def ledger_kinds(self):
        return [e["kind"] for e in self.ledger.entries()]


class H1AttributionTests(JournalRecoveryFixture):
    def test_other_ships_cycle_is_never_attributed(self):
        # tx2 legitimately ships cycle 9 for the item and commits.
        tx2 = self.journal.begin("d-2", "p-1", "c" * 64, NOW,
                                 item_id="item-1")
        self.walk(tx2, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-2", "c" * 64)
        self.walk(tx2, CYCLE_RECORDED, cycle_id=9)
        self.journal.transition(tx2, POST_RECORD_VERIFIED, NOW)
        self.ledger.finalise(decision_id="d-2", cycle_id=9,
                             recorded_at=NOW)
        self.journal.transition(tx2, COMMITTED, NOW)
        # tx1 crashed at BURN_PENDING: burn journaled, no cycle.
        # (Began after tx2 committed, so the in-flight gate does
        # not fire; the legacy/bypassed interleaving is what
        # recovery must still refuse to misattribute.)
        tx1 = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                 item_id="item-1")
        self.walk(tx1, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        loop = StubLoop([{"cycle_id": 9, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual(
            [(o["tx_id"], o["to_state"]) for o in outcomes],
            [(tx1, ANOMALY)])
        self.assertEqual(self.journal.state(tx1), ANOMALY)
        # No false ship record: no finalise for d-1 at all, and
        # certainly not finalise(d-1, cycle 9).
        self.assertEqual(
            [e for e in self.ledger.entries()
             if e["kind"] == "finalise"
             and e["decision_id"] == "d-1"], [])
        self.assertEqual(self.journal.state(tx2), COMMITTED)

    def test_competing_live_transactions_make_cycle_ambiguous(self):
        # Two live transactions for one item cannot be opened via
        # begin any more; craft the second in a separate journal
        # home is not possible (same chain), so instead verify the
        # status helper directly: a live competitor for the item
        # makes the item-only candidate ambiguous.
        summary = {"tx_id": "t-1", "decision_id": "d-1",
                   "proposal_id": "p-1", "manifest_hash": "a" * 64,
                   "item_id": "item-1", "cycle_id": "",
                   "state": BURN_PENDING}
        other = dict(summary, tx_id="t-2", decision_id="d-2",
                     state=BURN_PENDING)
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, [{"cycle_id": 4, "item_id": "item-1"}],
            [summary, other], [])
        self.assertEqual((entry, status), (None, "ambiguous"))


class ProvenanceTests(JournalRecoveryFixture):
    def test_prepared_with_stray_burn_and_cycle_parks_anomaly(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.burn("d-1", "a" * 64)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        # Recovery journaled NO step it did not perform: no
        # AUTHORISATION_VERIFIED, no POST_RECORD_VERIFIED.
        self.assertEqual(self.states_of(tx_id), [PREPARED, ANOMALY])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_burn_pending_unfinalised_without_root_parks_anomaly(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(outcomes[0]["reasons"],
                         ["post_record_unverified"])
        self.assertEqual(self.states_of(tx_id),
                         [PREPARED, AUTHORISATION_VERIFIED,
                          BURN_PENDING, ANOMALY])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_cycle_recorded_without_root_parks_anomaly(self):
        # The deliberate-drift shape: cycle recorded, burn
        # deliberately unfinalised. Recovery without a root must
        # not finalise it.
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(self.ledger_kinds(), ["burn"])


class CycleClaimUniquenessTests(JournalRecoveryFixture):
    """Fix round 2, N1: one cycle_id, one transaction, one
    decision — enforced at the journal transition, in recovery's
    cycle attribution, and at ShipLedger.finalise."""

    def test_double_finalise_probe_cannot_commit_both(self):
        # The rev-r3 probe: tx1 legitimately recorded cycle 9
        # for item-1; tx2 (begun for item-2, never ran a cycle)
        # tried to journal CYCLE_RECORDED for cycle 9 with an
        # item override to item-1. The old code committed BOTH
        # transactions and the ledger ended with finalises
        # [(d-1, 9), (d-2, 9)] for one history entry.
        tx1 = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                 item_id="item-1")
        self.walk(tx1, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx1, CYCLE_RECORDED, cycle_id=9)
        self.journal.transition(tx1, POST_RECORD_VERIFIED, NOW)
        self.ledger.finalise(decision_id="d-1", cycle_id=9,
                             recorded_at=NOW)
        tx2 = self.journal.begin("d-2", "p-1", "c" * 64, NOW,
                                 item_id="item-2")
        self.walk(tx2, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-2", "c" * 64)
        # The rebind / rival-claim transition is refused outright.
        with self.assertRaises(LedgerError):
            self.journal.transition(tx2, CYCLE_RECORDED, NOW,
                                    cycle_id=9, item_id="item-1")
        self.assertEqual(self.journal.state(tx2), BURN_PENDING)
        self.assertNotIn(CYCLE_RECORDED, self.states_of(tx2))
        loop = StubLoop([{"cycle_id": 9, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        by_tx = {o["tx_id"]: o["to_state"] for o in outcomes}
        # tx1 commits on the at-POST_RECORD_VERIFIED exception;
        # tx2 has a burn and no cycle for ITS item: spent.
        self.assertEqual(by_tx, {tx1: COMMITTED,
                                 tx2: ABORTED_SPENT})
        finalises = [(e["decision_id"], e["cycle_id"])
                     for e in self.ledger.entries()
                     if e["kind"] == "finalise"]
        self.assertEqual(finalises, [("d-1", 9)])

    def test_ledger_finalise_rejects_other_decisions_cycle(self):
        self.burn("d-1", "a" * 64)
        self.burn("d-2", "c" * 64)
        self.ledger.finalise(decision_id="d-1", cycle_id=9,
                             recorded_at=NOW)
        with self.assertRaises(LedgerError):
            self.ledger.finalise(decision_id="d-2", cycle_id=9,
                                 recorded_at=NOW)
        # A different cycle for d-2 is fine, and the ledger
        # still holds exactly one finalise naming cycle 9.
        self.ledger.finalise(decision_id="d-2", cycle_id=10,
                             recorded_at=NOW)
        self.assertEqual(
            [e["decision_id"] for e in self.ledger.entries()
             if e["kind"] == "finalise" and e["cycle_id"] == 9],
            ["d-1"])

    def test_exact_path_rival_claims_are_ambiguous(self):
        summary = {"tx_id": "t-1", "decision_id": "d-1",
                   "proposal_id": "p-1", "manifest_hash": "a" * 64,
                   "item_id": "item-1", "cycle_id": 9,
                   "state": CYCLE_RECORDED}
        history = [{"cycle_id": 9, "item_id": "item-1"}]
        # Another transaction journaled the same cycle.
        rival_tx = dict(summary, tx_id="t-2", decision_id="d-2")
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, history, [summary, rival_tx], [])
        self.assertEqual((entry, status), (None, "ambiguous"))
        # Another decision's finalise names the same cycle.
        rival_fin = [{"kind": "finalise", "decision_id": "d-2",
                      "cycle_id": 9}]
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, history, [summary], rival_fin)
        self.assertEqual((entry, status), (None, "ambiguous"))
        # Its OWN finalise naming the cycle is not a rival.
        own_fin = [{"kind": "finalise", "decision_id": "d-1",
                    "cycle_id": 9}]
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, history, [summary], own_fin)
        self.assertEqual(status, "found")
        self.assertEqual(entry["cycle_id"], 9)


class OutOfOrderFinaliseTests(JournalRecoveryFixture):
    """Fix round 2, N2: the already-finalised exception applies
    ONLY at POST_RECORD_VERIFIED. Below it, a finalise present
    in the ledger with no journaled POST_RECORD_VERIFIED is
    contradictory evidence (record_ship finalises only after
    journaling that state), not a crash remnant."""

    def _out_of_order_tx(self, *, cycle_recorded):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        if cycle_recorded:
            self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        # The finalise lands directly on the ledger, out of
        # order, with no POST_RECORD_VERIFIED in the journal.
        self.ledger.finalise(decision_id="d-1", cycle_id=3,
                             recorded_at=NOW)
        return tx_id

    def test_burn_pending_out_of_order_finalise_parks_anomaly(self):
        tx_id = self._out_of_order_tx(cycle_recorded=False)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(outcomes[0]["reasons"],
                         ["finalise_before_post_record_verified"])
        # Recovery did NOT journal a verification it did not do.
        self.assertNotIn(POST_RECORD_VERIFIED,
                         self.states_of(tx_id))
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_cycle_recorded_out_of_order_finalise_parks_anomaly(self):
        tx_id = self._out_of_order_tx(cycle_recorded=True)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(outcomes[0]["reasons"],
                         ["finalise_before_post_record_verified"])
        self.assertEqual(self.states_of(tx_id),
                         [PREPARED, AUTHORISATION_VERIFIED,
                          BURN_PENDING, CYCLE_RECORDED, ANOMALY])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])


class OutOfOrderFinaliseRootTests(TxFixture):
    """N2's escape: with a root AND a passing manifest
    re-verification, recovery performed the verification
    itself, so it may journal POST_RECORD_VERIFIED for a
    below-POST_RECORD_VERIFIED transaction whose burn was
    finalised out of order, and commit it."""

    def setUp(self):
        super().setUp()
        _refresh_clock()

    def _out_of_order_tx(self, *, cycle_recorded):
        journal = self.journal()
        tx_id = journal.begin(
            decision_id=self.envelope.decision_id,
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            recorded_at=NOW, item_id=ITEM)
        journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        journal.transition(tx_id, BURN_PENDING, NOW)
        self.ledger.burn(
            decision_id=self.envelope.decision_id,
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            payload_hash=self.envelope.payload_hash,
            recorded_at=NOW)
        if cycle_recorded:
            journal.transition(tx_id, CYCLE_RECORDED, NOW,
                               cycle_id=1, item_id=ITEM)
        self.ledger.finalise(
            decision_id=self.envelope.decision_id, cycle_id=1,
            recorded_at=NOW)
        return tx_id

    def test_burn_pending_out_of_order_finalise_root_commits(self):
        tx_id = self._out_of_order_tx(cycle_recorded=False)
        loop = StubLoop([{"cycle_id": 1, "item_id": ITEM}])
        outcomes = recover_ship_tx(self.ledger, loop,
                                   recorded_at=NOW, root=self.root)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.journal().state(tx_id), COMMITTED)
        self.assertIn(POST_RECORD_VERIFIED, self.tx_states())
        # No second finalise: the out-of-order one stands.
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_cycle_recorded_out_of_order_finalise_root_commits(self):
        tx_id = self._out_of_order_tx(cycle_recorded=True)
        loop = StubLoop([{"cycle_id": 1, "item_id": ITEM}])
        outcomes = recover_ship_tx(self.ledger, loop,
                                   recorded_at=NOW, root=self.root)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.journal().state(tx_id), COMMITTED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])


class PoisonedTxIsolationTests(JournalRecoveryFixture):
    def test_missing_burn_post_burn_states_park_anomaly(self):
        # H2: ship ledger missing / rolled back — the burns for
        # these transactions simply do not exist.
        poison1 = self.journal.begin("d-p1", "p-1", "a" * 64, NOW,
                                     item_id="item-p1")
        self.walk(poison1, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.walk(poison1, CYCLE_RECORDED, cycle_id=3)
        poison2 = self.journal.begin("d-p2", "p-1", "b" * 64, NOW,
                                     item_id="item-p2")
        self.walk(poison2, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.walk(poison2, CYCLE_RECORDED, cycle_id=4)
        self.journal.transition(poison2, POST_RECORD_VERIFIED, NOW)
        healthy = self.journal.begin("d-h", "p-1", "c" * 64, NOW,
                                     item_id="item-h")
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-p1"},
                         {"cycle_id": 4, "item_id": "item-p2"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        by_tx = {o["tx_id"]: o["to_state"] for o in outcomes}
        self.assertEqual(by_tx, {poison1: ANOMALY,
                                 poison2: ANOMALY,
                                 healthy: REFUSED_PRE_BURN})
        # And recovery stays idempotent afterwards (the old code
        # raised LedgerError forever on the poisoned entries).
        self.assertEqual(
            self.journal.recover(self.ledger, loop,
                                 recorded_at=NOW), [])

    def test_one_txs_error_does_not_block_others(self):
        bad = self.journal.begin("d-bad", "p-1", "a" * 64, NOW,
                                 item_id="item-bad")
        self.walk(bad, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-bad", "a" * 64)
        self.walk(bad, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(bad, POST_RECORD_VERIFIED, NOW)
        good = self.journal.begin("d-good", "p-1", "c" * 64, NOW,
                                  item_id="item-good")
        self.walk(good, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-good", "c" * 64)
        self.walk(good, CYCLE_RECORDED, cycle_id=4)
        self.journal.transition(good, POST_RECORD_VERIFIED, NOW)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-bad"},
                         {"cycle_id": 4, "item_id": "item-good"}])
        real_finalise = self.ledger.finalise

        def flaky_finalise(**kw):
            if kw["decision_id"] == "d-bad":
                raise RuntimeError("finalise exploded")
            return real_finalise(**kw)

        with mock.patch.object(self.ledger, "finalise",
                               flaky_finalise):
            outcomes = self.journal.recover(self.ledger, loop,
                                            recorded_at=NOW)
        by_tx = {o["tx_id"]: o for o in outcomes}
        self.assertEqual(by_tx[good]["to_state"], COMMITTED)
        self.assertIn("error", by_tx[bad])
        self.assertEqual(by_tx[bad]["to_state"],
                         POST_RECORD_VERIFIED)
        self.assertEqual(self.journal.state(bad),
                         POST_RECORD_VERIFIED)
        # The failed transaction is retried by the next run.
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.journal.state(bad), COMMITTED)


class HistoryAndAnchorTests(JournalRecoveryFixture):
    def test_recorded_cycle_blocks_refused_pre_burn(self):
        # H3: no burn, but the loop DID record a cycle for the
        # item — that is a contradiction, not a clean refusal.
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED)
        loop = StubLoop([{"cycle_id": 2, "item_id": "item-1"}])
        outcomes = self.journal.recover(self.ledger, loop,
                                        recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(outcomes[0]["reasons"],
                         ["cycle_without_burn"])

    def _post_record_tx(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        return tx_id

    def test_missing_anchor_is_error_and_retry_succeeds(self):
        # CHANGED (Trust Boundary fix round 2, N3): this test
        # previously pinned that a MISSING anchor parked the tx
        # at terminal ANOMALY. That behaviour was indiscriminate:
        # a nonexistent anchor path is operator error (a typo'd
        # path, a ceremony not yet run), not rollback evidence,
        # and parking destroyed a transaction with complete
        # evidence. Now a missing anchor yields a non-destructive
        # error outcome, the tx is left in place, and a retry
        # with a valid anchor settles it.
        tx_id = self._post_record_tx()
        anchor_path = Path(self.tmp.name) / "ship-anchor.json"
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(
            self.ledger, loop, recorded_at=NOW,
            anchor_path=anchor_path)
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(outcomes[0]["to_state"],
                         POST_RECORD_VERIFIED)
        self.assertEqual(self.journal.state(tx_id),
                         POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        # Retry with a valid anchor: recovery proceeds.
        initialise_anchor(self.ledger, anchor_path, kind="ship",
                          recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, loop, recorded_at=NOW,
            anchor_path=anchor_path)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_malformed_anchor_is_error_not_anomaly(self):
        tx_id = self._post_record_tx()
        anchor_path = Path(self.tmp.name) / "ship-anchor.json"
        anchor_path.write_text("this is not an anchor\n")
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(
            self.ledger, loop, recorded_at=NOW,
            anchor_path=anchor_path)
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_malformed", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id),
                         POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_chain_mismatch_anchor_still_parks_anomaly(self):
        # N3's other half: a well-formed anchor whose head names
        # no prefix of the ledger chain IS rollback evidence and
        # still parks at ANOMALY.
        tx_id = self._post_record_tx()
        anchor_path = Path(self.tmp.name) / "ship-anchor.json"
        anchor_path.write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(
            self.ledger, loop, recorded_at=NOW,
            anchor_path=anchor_path)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertIn("anchor_head_not_in_chain",
                      outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_valid_anchor_lets_recovery_proceed(self):
        tx_id = self._post_record_tx()
        anchor_path = Path(self.tmp.name) / "ship-anchor.json"
        initialise_anchor(self.ledger, anchor_path, kind="ship",
                          recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        loop = StubLoop([{"cycle_id": 3, "item_id": "item-1"}])
        outcomes = self.journal.recover(
            self.ledger, loop, recorded_at=NOW,
            anchor_path=anchor_path)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])


class BeginGateTests(JournalRecoveryFixture):
    def test_begin_rejects_second_in_flight_for_same_item(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                           item_id="item-1")
        with self.assertRaises(LedgerError):
            self.journal.begin("d-2", "p-1", "c" * 64, NOW,
                               item_id="item-1")
        # A different item is fine, and once the first tx is
        # terminal the item is free again.
        self.journal.begin("d-3", "p-1", "d" * 64, NOW,
                           item_id="item-2")
        tx1 = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(tx1, REFUSED_PRE_BURN, NOW)
        self.journal.begin("d-2", "p-1", "c" * 64, NOW,
                           item_id="item-1")

    def test_begin_with_different_item_for_existing_tx_raises(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        with self.assertRaises(LedgerError):
            self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                               item_id="item-2")
        # Same item (or none) still rejoins idempotently.
        self.assertEqual(
            self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                               item_id="item-1"), tx_id)
        self.assertEqual(
            self.journal.transaction(tx_id)["item_id"], "item-1")

    def test_anomaly_is_terminal_and_reachable_from_prepared(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.journal.transition(tx_id, ANOMALY, NOW)
        self.assertEqual(self.journal.state(tx_id), ANOMALY)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, COMMITTED, NOW)


class RecordedCycleMatchTests(unittest.TestCase):
    def test_exact_match_preferred_over_item_fallback(self):
        summary = {"tx_id": "t-1", "decision_id": "d-1",
                   "proposal_id": "p-1", "manifest_hash": "a" * 64,
                   "item_id": "item-1", "cycle_id": 2,
                   "state": CYCLE_RECORDED}
        history = [{"cycle_id": 1, "item_id": "item-1"},
                   {"cycle_id": 2, "item_id": "item-1"}]
        entry = ShipTxJournal._recorded_cycle(summary, history)
        self.assertEqual(entry["cycle_id"], 2)

    def test_item_only_fallback_requires_uniqueness(self):
        summary = {"tx_id": "t-1", "decision_id": "d-1",
                   "proposal_id": "p-1", "manifest_hash": "a" * 64,
                   "item_id": "item-1", "cycle_id": "",
                   "state": BURN_PENDING}
        history = [{"cycle_id": 1, "item_id": "item-1"},
                   {"cycle_id": 2, "item_id": "item-1"}]
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, history, [summary], [])
        self.assertEqual((entry, status), (None, "ambiguous"))
        entry, status = ShipTxJournal._recorded_cycle_status(
            summary, history[:1], [summary], [])
        self.assertEqual(status, "found")
        self.assertEqual(entry["cycle_id"], 1)


class ConcurrencyTests(JournalRecoveryFixture):
    def test_concurrent_begins_keep_chain_valid(self):
        errors = []

        def worker(n):
            try:
                journal = ShipTxJournal(self.home)
                journal.begin(f"d-{n}", "p-1", f"{n:064x}", NOW,
                              item_id=f"item-{n}")
            except Exception as exc:  # noqa: BLE001 - collected
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,))
                   for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        reloaded = ShipTxJournal(self.home)  # chain validates
        self.assertEqual(len(reloaded.entries()), 8)
        self.assertEqual(
            [e["seq"] for e in reloaded.entries()],
            list(range(1, 9)))


class RecordShipGateIntegrationTests(TxFixture):
    def setUp(self):
        super().setUp()
        _refresh_clock()

    def test_record_ship_refused_while_item_in_flight(self):
        journal = self.journal()
        journal.begin("d-dangling", "p-other", "f" * 64, NOW,
                      item_id=ITEM)
        with self.assertRaises(ShipRefused):
            self.record()
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.loop.state["history"], [])

    def test_recovery_without_root_parks_cycle_recorded_anomaly(self):
        import trust.shipcheck as shipcheck_module
        from trust.manifest import ManifestDiff
        real_verify = shipcheck_module.verify_manifest
        calls = {"n": 0}

        def verify_then_drift(root, manifest):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_verify(root, manifest)
            diff = ManifestDiff()
            diff.added.append("core/a.py")
            return diff

        with mock.patch.object(shipcheck_module, "verify_manifest",
                               verify_then_drift):
            with self.assertRaises(ShipRefused):
                self.record()
        self.assertEqual(self.tx_state(), CYCLE_RECORDED)
        outcomes = self.recover()
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_recovery_with_root_and_real_drift_parks_anomaly(self):
        import trust.shipcheck as shipcheck_module
        from trust.manifest import ManifestDiff
        real_verify = shipcheck_module.verify_manifest
        calls = {"n": 0}

        def verify_then_drift(root, manifest):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_verify(root, manifest)
            diff = ManifestDiff()
            diff.added.append("core/a.py")
            return diff

        with mock.patch.object(shipcheck_module, "verify_manifest",
                               verify_then_drift):
            with self.assertRaises(ShipRefused):
                self.record()
        self.assertEqual(self.tx_state(), CYCLE_RECORDED)
        # The tree now ACTUALLY drifts on disk: the rebuilt
        # manifest cannot equal the transaction's hash.
        (self.root / "core" / "a.py").write_text("A = 2\n")
        outcomes = self.recover(root=self.root)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(outcomes[0]["reasons"],
                         ["post_record_reverify_failed"])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_concurrent_recovery_commits_exactly_once(self):
        orig_cycle = self.loop.run_one_cycle

        def cycle_then_crash(*args):
            orig_cycle(*args)
            raise RuntimeError("crash after record")

        with mock.patch.object(self.loop, "run_one_cycle",
                               cycle_then_crash):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), BURN_PENDING)
        errors = []
        results = []

        def worker():
            try:
                results.append(recover_ship_tx(
                    self.ledger, self.loop, recorded_at=NOW,
                    root=self.root))
            except Exception as exc:  # noqa: BLE001 - collected
                errors.append(exc)

        threads = [threading.Thread(target=worker)
                   for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        for outcome_list in results:
            for outcome in outcome_list:
                self.assertNotIn("error", outcome)
        self.assertEqual(self.tx_state(), COMMITTED)
        self.assertEqual(self.tx_states(),
                         _fixture_module.HAPPY_WALK)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        # The chain still validates on a fresh load.
        self.assertEqual(self.journal().state(self.tx_id()),
                         COMMITTED)
        self.assertEqual(ABORTED_SPENT, "ABORTED_SPENT")


if __name__ == "__main__":
    unittest.main()
