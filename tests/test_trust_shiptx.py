"""Tests for trust.shiptx + its record_ship integration
(Trust Boundary v2, mandate item 4): the durable ship
transaction state machine.

Pins: the happy path walks all six states in order; illegal
transitions raise; a crash injected at EVERY record_ship step
(burn raising after it succeeded, the loop raising before and
after recording, post-record manifest drift, finalise raising
before and after it succeeded, a hard stop between burn and
record) settles — via recover_ship_tx — at exactly ONE
consistent terminal outcome; a consumed decision can never be
replayed; recovery is idempotent and never re-burns or re-runs
a cycle.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trust.shipcheck as shipcheck_module
from core.loop import CoreLoop
from eval.gate import GateDecision, VerifierAttestation
from signing import (
    PURPOSE_SHIP,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
from signing.gate_decision import _canonical, _sha256
from trust.errors import ShipRefused
from trust.ledger import LedgerError, ShipLedger
from trust.manifest import ManifestDiff, build_manifest
from trust.release import build_release_record
from trust.shipcheck import record_ship, recover_ship_tx
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
    derive_tx_id,
)

KEY = make_signing_key(bytes(range(32, 64)))


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


NOW = _ts(0)
ATTESTED = _ts(-10)
SATT_AT = _ts(-5)
SEALED = "b" * 64
PROPOSAL = "prop-ship"
ITEM = "store-enforced-signed-commits"
CODERS = ["seat-1", "seat-2", "seat-3"]
REVIEWERS = ["rev-r1", "rev-r2", "rev-r3", "rev-r4", "rev-r5", "rev-r6"]
DELTA = {"metric": "tests_passing", "before": 1, "after": 2,
         "evidence_ref": "fixture run", "verifier": "rev-r1"}
HAPPY_WALK = [PREPARED, AUTHORISATION_VERIFIED, BURN_PENDING,
              CYCLE_RECORDED, POST_RECORD_VERIFIED, COMMITTED]


def make_tree(root: Path):
    (root / "core").mkdir(parents=True)
    (root / "core" / "a.py").write_text("A = 1\n")
    (root / "eval").mkdir()
    (root / "eval" / "gate.py").write_text("GATE = True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (root / "internal").mkdir()
    (root / "internal" / "REVIEW.md").write_text("# review\n")
    return root


class TxFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = make_tree(base / "repo")
        self.home = base / "verifier-home"
        self.ledger = ShipLedger(self.home)
        self.loop = CoreLoop(base / "loop-state")
        self.loop.scan([{"id": ITEM, "title": "fixture ship item",
                         "leverage": 5.0}])
        self.manifest = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        self.att = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="war-room-cycle-8",
            attested_at=ATTESTED)
        self.satt = sign_attestation(
            self.att, signing_key=KEY, signer_id="seat-3",
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            now=SATT_AT)
        self.envelope = self._envelope()

    def tearDown(self):
        self.tmp.cleanup()

    def _envelope(self, **over):
        decision = GateDecision(
            accepted=True, proposal_id=PROPOSAL, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=NOW,
            protected_violations=(),
            verifier_note=f"content-hash:{self.manifest.manifest_hash}")
        kw = dict(signing_key=KEY, signer_id="verifier-svc",
                  attestation=self.att, signed_attestation=self.satt,
                  gate_inputs_hash=self.manifest.manifest_hash,
                  purpose=PURPOSE_SHIP, now=NOW)
        kw.update(over)
        return sign_gate_decision(decision, **kw)

    def record(self, **over):
        kw = dict(root=self.root, manifest=self.manifest,
                  signed=self.envelope, signing_key=KEY,
                  ledger=self.ledger, coders=CODERS,
                  reviewers=REVIEWERS, delta=DELTA,
                  expected_attestation=self.satt,
                  expected_ledger_head=self.ledger.head())
        kw.update(over)
        loop = kw.pop("loop", self.loop)
        if "release" not in kw:
            import hashlib
            if not loop.state_path.exists():
                loop.scan([])
            kw["release"] = build_release_record(
                self.manifest, self.envelope,
                expected_cycle_id=loop.state["cycle_seq"] + 1,
                pre_ship_cycle_seq=loop.state["cycle_seq"],
                pre_ship_state_sha256=hashlib.sha256(
                    loop.state_path.read_bytes()).hexdigest())
        return record_ship(loop, **kw)

    # -- tx helpers ---------------------------------------------------

    def journal(self):
        return ShipTxJournal(self.home)

    def tx_id(self):
        return derive_tx_id(self.envelope.decision_id,
                            self.manifest.manifest_hash)

    def tx_states(self):
        return [e["to_state"] for e in self.journal().entries()
                if e["tx_id"] == self.tx_id()]

    def tx_state(self):
        return self.journal().state(self.tx_id())

    def recover(self, **kw):
        kw.setdefault("recorded_at", NOW)
        return recover_ship_tx(self.ledger, self.loop, **kw)

    def ledger_kinds(self):
        return [e["kind"] for e in self.ledger.entries()]

    def assert_not_replayable(self):
        burns = self.ledger_kinds().count("burn")
        with self.assertRaises(ShipRefused):
            self.record()
        self.assertEqual(self.ledger_kinds().count("burn"), burns)


class TxJournalUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "home"
        self.journal = ShipTxJournal(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tx_id_derivation_matches_recomputation(self):
        expected = _sha256(_canonical({
            "v": "ship-tx/1", "decision_id": "d-1",
            "manifest_hash": "a" * 64}))
        self.assertEqual(derive_tx_id("d-1", "a" * 64), expected)
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.assertEqual(tx_id, expected)
        # A fresh instance over the same directory derives and
        # finds the identical transaction.
        again = ShipTxJournal(self.dir)
        self.assertEqual(again.state(tx_id), PREPARED)
        self.assertEqual(
            again.begin("d-1", "p-1", "a" * 64, NOW), tx_id)

    def test_begin_is_idempotent(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.assertEqual(
            self.journal.begin("d-1", "p-1", "a" * 64, NOW), tx_id)
        self.assertEqual(len(self.journal.entries()), 1)
        self.assertEqual(self.journal.state(tx_id), PREPARED)
        summary = self.journal.transaction(tx_id)
        self.assertEqual(summary["item_id"], "item-1")
        self.assertEqual(summary["cycle_id"], "")

    def test_happy_walk_in_order(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx_id, BURN_PENDING, NOW)
        self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                cycle_id=7, item_id="item-1")
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        entry = self.journal.transition(tx_id, COMMITTED, NOW)
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        entries = self.journal.entries()
        self.assertEqual([e["to_state"] for e in entries],
                         HAPPY_WALK)
        self.assertEqual([e["from_state"] for e in entries],
                         [""] + HAPPY_WALK[:-1])
        self.assertEqual(entry["cycle_id"], 7)
        summary = self.journal.transaction(tx_id)
        self.assertEqual(summary["cycle_id"], 7)
        self.assertEqual(summary["decision_id"], "d-1")

    def test_begin_gate_applies_to_empty_item(self):
        # Fix round 2, H1(a): the one-in-flight gate is NOT
        # skipped for the default empty item_id — all
        # empty-item transactions share one slot. (Chosen over
        # refusing empty item_id outright: journal-level
        # callers legitimately open item-less transactions;
        # record_ship always passes a non-empty item.)
        self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        with self.assertRaises(LedgerError):
            self.journal.begin("d-2", "p-1", "c" * 64, NOW)
        # A named item is a different slot and opens fine.
        self.journal.begin("d-3", "p-1", "d" * 64, NOW,
                           item_id="item-1")
        # Once the empty-item tx is terminal the slot frees.
        tx1 = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(tx1, REFUSED_PRE_BURN, NOW)
        self.journal.begin("d-2", "p-1", "c" * 64, NOW)
        self.assertEqual(len(self.journal.transactions()), 3)

    def test_transition_item_rebind_raises(self):
        # Fix round 2, H1(b): a CYCLE_RECORDED transition cannot
        # re-bind a transaction to a different item than the one
        # it was begun with.
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx_id, BURN_PENDING, NOW)
        entries_before = len(self.journal.entries())
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                    cycle_id=7, item_id="item-2")
        self.assertEqual(self.journal.state(tx_id), BURN_PENDING)
        self.assertEqual(len(self.journal.entries()),
                         entries_before)
        # The begun item (or no item) is accepted.
        self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                cycle_id=7, item_id="item-1")
        self.assertEqual(
            self.journal.transaction(tx_id)["item_id"], "item-1")

    def test_transition_binds_empty_begun_item_only_via_gate(self):
        # H1(b), empty-begun case: a supplied item at
        # CYCLE_RECORDED must pass the one-in-flight gate for
        # that item at that moment.
        holder = self.journal.begin("d-h", "p-1", "b" * 64, NOW,
                                    item_id="item-1")
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx_id, BURN_PENDING, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                    cycle_id=5, item_id="item-1")
        self.assertEqual(self.journal.state(tx_id), BURN_PENDING)
        # Once the holder is terminal, the gate passes and the
        # transaction binds the item.
        self.journal.transition(holder, REFUSED_PRE_BURN, NOW)
        self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                cycle_id=5, item_id="item-1")
        self.assertEqual(
            self.journal.transaction(tx_id)["item_id"], "item-1")

    def test_gate_fires_at_authorisation_verified_first_binding(self):
        # Fix round 3, S1 (rev-r3): an item-less transaction
        # bound item-1 by supplying item_id on the
        # AUTHORISATION_VERIFIED transition — no gate check
        # fired on non-CYCLE transitions, so its later
        # CYCLE_RECORDED saw the carried item already set,
        # skipped the gate branch, and it walked to COMMITTED
        # while the legitimate item-1 holder was still
        # BURN_PENDING. The gate must fire at the FIRST binding,
        # whichever transition that is.
        holder = self.journal.begin("d-h", "p-1", "b" * 64, NOW,
                                    item_id="item-1")
        self.journal.transition(holder, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(holder, BURN_PENDING, NOW)
        intruder = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        entries_before = len(self.journal.entries())
        with self.assertRaises(LedgerError):
            self.journal.transition(
                intruder, AUTHORISATION_VERIFIED, NOW,
                item_id="item-1")
        # Nothing appended, nothing bound, no progress made.
        self.assertEqual(self.journal.state(intruder), PREPARED)
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "")
        self.assertEqual(len(self.journal.entries()),
                         entries_before)
        self.assertNotEqual(self.journal.state(intruder), COMMITTED)
        self.assertEqual(self.journal.state(holder), BURN_PENDING)
        # After the holder reaches a terminal state, the same
        # legitimate binding passes the gate and the intruder —
        # now the item's only live transaction — walks the
        # happy path to COMMITTED.
        self.journal.transition(holder, REFUSED_PRE_BURN, NOW)
        self.journal.transition(
            intruder, AUTHORISATION_VERIFIED, NOW, item_id="item-1")
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "item-1")
        self.journal.transition(intruder, BURN_PENDING, NOW)
        self.journal.transition(intruder, CYCLE_RECORDED, NOW,
                                cycle_id=5, item_id="item-1")
        self.journal.transition(intruder, POST_RECORD_VERIFIED, NOW)
        self.journal.transition(intruder, COMMITTED, NOW)
        self.assertEqual(self.journal.state(intruder), COMMITTED)

    def test_gate_fires_at_burn_pending_first_binding(self):
        # Fix round 3, S1b: the same bypass, binding one step
        # later — the item-less transaction walks
        # AUTHORISATION_VERIFIED item-less, then supplies
        # item_id at BURN_PENDING. The gate must fire there too.
        holder = self.journal.begin("d-h", "p-1", "b" * 64, NOW,
                                    item_id="item-1")
        self.journal.transition(holder, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(holder, BURN_PENDING, NOW)
        intruder = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(intruder, AUTHORISATION_VERIFIED, NOW)
        entries_before = len(self.journal.entries())
        with self.assertRaises(LedgerError):
            self.journal.transition(intruder, BURN_PENDING, NOW,
                                    item_id="item-1")
        self.assertEqual(self.journal.state(intruder),
                         AUTHORISATION_VERIFIED)
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "")
        self.assertEqual(len(self.journal.entries()),
                         entries_before)
        self.assertNotEqual(self.journal.state(intruder), COMMITTED)
        self.assertEqual(self.journal.state(holder), BURN_PENDING)
        # After the holder is terminal, the BURN_PENDING binding
        # passes and the walk completes legitimately.
        self.journal.transition(holder, REFUSED_PRE_BURN, NOW)
        self.journal.transition(intruder, BURN_PENDING, NOW,
                                item_id="item-1")
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "item-1")
        self.journal.transition(intruder, CYCLE_RECORDED, NOW,
                                cycle_id=5, item_id="item-1")
        self.journal.transition(intruder, POST_RECORD_VERIFIED, NOW)
        self.journal.transition(intruder, COMMITTED, NOW)
        self.assertEqual(self.journal.state(intruder), COMMITTED)

    def test_gate_fires_at_any_first_binding_transition(self):
        # Fix round 3, generality of S1/S1b: the gate is not a
        # per-state special case. A first binding attempted on
        # a terminal-bound transition (REFUSED_PRE_BURN from
        # PREPARED) is gated exactly like the happy-path states.
        holder = self.journal.begin("d-h", "p-1", "b" * 64, NOW,
                                    item_id="item-1")
        intruder = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(intruder, REFUSED_PRE_BURN, NOW,
                                    item_id="item-1")
        self.assertEqual(self.journal.state(intruder), PREPARED)
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "")
        self.journal.transition(holder, REFUSED_PRE_BURN, NOW)
        self.journal.transition(intruder, REFUSED_PRE_BURN, NOW,
                                item_id="item-1")
        self.assertEqual(self.journal.state(intruder),
                         REFUSED_PRE_BURN)
        self.assertEqual(
            self.journal.transaction(intruder)["item_id"], "item-1")

    def test_itemless_cycle_recorded_refused_while_holder_live(self):
        # Fix round 3, S2 (rev-r3): an item-less transaction
        # journaled CYCLE_RECORDED with NO item_id at all — the
        # gate never engaged, the item stayed "", and it walked
        # to COMMITTED claiming a cycle while another item's
        # holder was live. Policy chosen (see the trust.shiptx
        # module docstring): item-less CYCLE_RECORDED is
        # REFUSED — a recorded cycle belongs to an item by
        # definition, and record_ship always supplies one.
        holder = self.journal.begin("d-h", "p-1", "b" * 64, NOW,
                                    item_id="item-1")
        self.journal.transition(holder, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(holder, BURN_PENDING, NOW)
        intruder = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(intruder, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(intruder, BURN_PENDING, NOW)
        entries_before = len(self.journal.entries())
        with self.assertRaises(LedgerError):
            self.journal.transition(intruder, CYCLE_RECORDED, NOW,
                                    cycle_id=5)
        # The intruder is stuck at BURN_PENDING, item-less and
        # cycle-less; it did not reach COMMITTED.
        self.assertEqual(self.journal.state(intruder), BURN_PENDING)
        summary = self.journal.transaction(intruder)
        self.assertEqual(summary["item_id"], "")
        self.assertEqual(summary["cycle_id"], "")
        self.assertEqual(len(self.journal.entries()),
                         entries_before)
        self.assertEqual(self.journal.state(holder), BURN_PENDING)
        # After the holder is terminal the item-less form is
        # STILL refused (the policy is unconditional), but the
        # legitimate form — supplying the item at
        # CYCLE_RECORDED, passing the now-open gate — works and
        # walks to COMMITTED.
        self.journal.transition(holder, REFUSED_PRE_BURN, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(intruder, CYCLE_RECORDED, NOW,
                                    cycle_id=5)
        self.journal.transition(intruder, CYCLE_RECORDED, NOW,
                                cycle_id=5, item_id="item-1")
        self.journal.transition(intruder, POST_RECORD_VERIFIED, NOW)
        self.journal.transition(intruder, COMMITTED, NOW)
        self.assertEqual(self.journal.state(intruder), COMMITTED)

    def test_itemless_cycle_recorded_refused_even_with_no_holder(self):
        # S2 policy pin: the refusal is not merely a gate
        # against live holders. Even alone in the journal, an
        # item-less CYCLE_RECORDED is refused; supplying the
        # item at that transition is the legitimate form.
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx_id, BURN_PENDING, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                    cycle_id=1)
        self.assertEqual(self.journal.state(tx_id), BURN_PENDING)
        self.journal.transition(tx_id, CYCLE_RECORDED, NOW,
                                cycle_id=1, item_id="item-1")
        self.assertEqual(self.journal.state(tx_id), CYCLE_RECORDED)
        self.assertEqual(
            self.journal.transaction(tx_id)["item_id"], "item-1")

    def test_transition_duplicate_cycle_claim_raises(self):
        # Fix round 2, N1(i): a cycle_id already journaled by
        # another transaction cannot be claimed again — even by
        # a transaction naming its OWN item, and even after the
        # first transaction is terminal.
        tx1 = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                 item_id="item-1")
        self.journal.transition(tx1, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx1, BURN_PENDING, NOW)
        self.journal.transition(tx1, CYCLE_RECORDED, NOW,
                                cycle_id=9, item_id="item-1")
        self.journal.transition(tx1, POST_RECORD_VERIFIED, NOW)
        self.journal.transition(tx1, COMMITTED, NOW)
        tx2 = self.journal.begin("d-2", "p-1", "c" * 64, NOW,
                                 item_id="item-2")
        self.journal.transition(tx2, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx2, BURN_PENDING, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx2, CYCLE_RECORDED, NOW,
                                    cycle_id=9, item_id="item-2")
        self.assertEqual(self.journal.state(tx2), BURN_PENDING)
        # A fresh cycle for its own item is fine.
        self.journal.transition(tx2, CYCLE_RECORDED, NOW,
                                cycle_id=10, item_id="item-2")

    def test_illegal_transitions_raise(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW)
        for target in (COMMITTED, CYCLE_RECORDED, BURN_PENDING,
                       POST_RECORD_VERIFIED, PREPARED):
            with self.assertRaises(LedgerError):
                self.journal.transition(tx_id, target, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, "NOT-A-STATE", NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition("f" * 64, REFUSED_PRE_BURN, NOW)
        self.assertEqual(self.journal.state(tx_id), PREPARED)
        self.assertEqual(len(self.journal.entries()), 1)
        # CYCLE_RECORDED without a cycle id is illegal too.
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.journal.transition(tx_id, BURN_PENDING, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, CYCLE_RECORDED, NOW)
        # Terminal states are final.
        self.journal.transition(tx_id, REFUSED_PRE_BURN, NOW)
        with self.assertRaises(LedgerError):
            self.journal.transition(tx_id, AUTHORISATION_VERIFIED,
                                    NOW)


class RecordShipTxTests(TxFixture):
    def test_happy_path_walks_all_six_states(self):
        entry = self.record()
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(self.tx_states(), HAPPY_WALK)
        self.assertEqual(self.tx_state(), COMMITTED)
        self.assertTrue((self.home / "ship-tx.json").exists())
        summary = self.journal().transaction(self.tx_id())
        self.assertEqual(summary["cycle_id"], 1)
        self.assertEqual(summary["item_id"], ITEM)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        # The tx <-> ledger binding recomputes from the burn.
        burn = self.ledger.entries()[0]
        self.assertEqual(
            derive_tx_id(burn["decision_id"], burn["manifest_hash"]),
            self.tx_id())

    def test_pre_burn_refusal_lands_refused_pre_burn(self):
        (self.root / "core" / "a.py").write_text("A = 2\n")
        with self.assertRaises(ShipRefused):
            self.record()
        self.assertEqual(self.tx_states(),
                         [PREPARED, REFUSED_PRE_BURN])
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.recover(), [])  # already terminal

    def test_loop_refusal_after_burn_lands_aborted_spent(self):
        bad_delta = dict(DELTA, verifier="seat-1")  # a builder
        with self.assertRaises(ShipRefused) as ctx:
            self.record(delta=bad_delta)
        self.assertIn("spent", str(ctx.exception))
        self.assertEqual(self.tx_states(),
                         [PREPARED, AUTHORISATION_VERIFIED,
                          BURN_PENDING, ABORTED_SPENT])
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assertEqual(self.recover(), [])  # already terminal
        self.assert_not_replayable()

    def test_second_attempt_after_commit_refused_tx_unchanged(self):
        self.record()
        entries_before = len(self.journal().entries())
        with self.assertRaises(ShipRefused) as ctx:
            self.record()
        self.assertIn("decision_already_consumed",
                      ctx.exception.reasons)
        self.assertEqual(self.tx_state(), COMMITTED)
        self.assertEqual(len(self.journal().entries()),
                         entries_before)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])


class CrashRecoveryTests(TxFixture):
    def test_crash_burn_raises_after_succeeding(self):
        orig_burn = self.ledger.burn

        def burn_then_crash(**kw):
            orig_burn(**kw)
            raise RuntimeError("crash after burn")

        with mock.patch.object(self.ledger, "burn", burn_then_crash):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), BURN_PENDING)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assertEqual(self.loop.state["history"], [])
        outcomes = self.recover()
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ABORTED_SPENT])
        self.assertEqual(self.tx_state(), ABORTED_SPENT)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assert_not_replayable()

    def test_crash_hard_stop_between_burn_and_record(self):
        with mock.patch.object(
                self.loop, "run_one_cycle",
                side_effect=RuntimeError("hard stop")):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), BURN_PENDING)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assertEqual(self.loop.state["history"], [])
        self.assertEqual([o["to_state"] for o in self.recover()],
                         [ABORTED_SPENT])
        self.assertEqual(self.tx_state(), ABORTED_SPENT)
        self.assert_not_replayable()

    def test_crash_after_cycle_recorded_before_tx_update(self):
        orig_cycle = self.loop.run_one_cycle

        def cycle_then_crash(*args):
            orig_cycle(*args)
            raise RuntimeError("crash after record")

        with mock.patch.object(self.loop, "run_one_cycle",
                               cycle_then_crash):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), BURN_PENDING)
        self.assertEqual(len(self.loop.state["history"]), 1)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        # Recovery completes the paperwork; it must not re-run
        # the cycle to do so. CHANGED (Trust Boundary fix round):
        # recovery is now given root=self.root — without a root it
        # may no longer finalise an unfinalised burn blind, and
        # would park this tx at ANOMALY instead of COMMITTED
        # (see tests/test_trust_shiptx_recovery.py).
        with mock.patch.object(
                self.loop, "run_one_cycle",
                side_effect=AssertionError("recovery re-ran a cycle")):
            outcomes = self.recover(root=self.root)
        self.assertEqual([o["to_state"] for o in outcomes],
                         [COMMITTED])
        self.assertEqual(self.tx_states(),
                         [PREPARED, AUTHORISATION_VERIFIED,
                          BURN_PENDING, CYCLE_RECORDED,
                          POST_RECORD_VERIFIED, COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        finalise = self.ledger.entries()[1]
        self.assertEqual(finalise["cycle_id"], 1)
        self.assertEqual(len(self.loop.state["history"]), 1)
        self.assert_not_replayable()

    def test_crash_post_record_manifest_drift(self):
        real_verify = shipcheck_module.verify_manifest
        calls = {"n": 0}

        def verify_then_drift(root, manifest):
            calls["n"] += 1
            if calls["n"] == 1:  # the check_ship verification
                return real_verify(root, manifest)
            diff = ManifestDiff()
            diff.added.append("core/a.py")
            return diff

        with mock.patch.object(shipcheck_module, "verify_manifest",
                               verify_then_drift):
            with self.assertRaises(ShipRefused) as ctx:
                self.record()
        self.assertIn("drifted", str(ctx.exception))
        # The cycle IS recorded, so the tx parks at CYCLE_RECORDED
        # with the burn unfinalised — the anomaly signal — until
        # recovery settles it. CHANGED (Trust Boundary fix round):
        # recovery must RE-VERIFY before finalising, so it is
        # given root=self.root; the drift in this test was a mock
        # inside record_ship only, the on-disk tree still rebuilds
        # to the tx's manifest_hash, so re-verification passes and
        # the tx commits. A tree that actually drifted on disk
        # parks at ANOMALY instead — pinned in
        # tests/test_trust_shiptx_recovery.py.
        self.assertEqual(self.tx_state(), CYCLE_RECORDED)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assertEqual(len(self.loop.state["history"]), 1)
        self.assertEqual(
            [o["to_state"] for o in self.recover(root=self.root)],
            [COMMITTED])
        self.assertEqual(self.tx_state(), COMMITTED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        self.assert_not_replayable()

    def test_pre_burn_manifest_drift_refuses_cleanly(self):
        def always_drift(root, manifest):
            diff = ManifestDiff()
            diff.added.append("core/a.py")
            return diff

        with mock.patch.object(shipcheck_module, "verify_manifest",
                               always_drift):
            with self.assertRaises(ShipRefused):
                self.record()
        self.assertEqual(self.tx_state(), REFUSED_PRE_BURN)
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.loop.state["history"], [])

    def test_crash_finalise_raises(self):
        with mock.patch.object(
                self.ledger, "finalise",
                side_effect=RuntimeError("crash at finalise")):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.assertEqual(len(self.loop.state["history"]), 1)
        self.assertEqual([o["to_state"] for o in self.recover()],
                         [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        self.assert_not_replayable()

    def test_crash_finalise_raises_after_succeeding(self):
        orig_finalise = self.ledger.finalise

        def finalise_then_crash(**kw):
            orig_finalise(**kw)
            raise RuntimeError("crash after finalise")

        with mock.patch.object(self.ledger, "finalise",
                               finalise_then_crash):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertEqual(self.tx_state(), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        self.assertEqual([o["to_state"] for o in self.recover()],
                         [COMMITTED])
        # No second finalise was appended by recovery.
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])
        self.assertEqual(self.tx_state(), COMMITTED)

    def test_crash_at_prepared_authorised_and_burn_pending(self):
        journal = self.journal()
        tx_id = journal.begin(
            decision_id=self.envelope.decision_id,
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            recorded_at=NOW, item_id=ITEM)
        self.assertEqual(tx_id, self.tx_id())
        # Crash at PREPARED, no burn anywhere: safe refusal.
        self.assertEqual([o["to_state"] for o in self.recover()],
                         [REFUSED_PRE_BURN])
        # Fresh transactions crashed later, still pre-burn.
        for reach in (AUTHORISATION_VERIFIED, BURN_PENDING):
            other = ShipTxJournal(Path(self.tmp.name) / f"h-{reach}")
            other_ledger = ShipLedger(Path(self.tmp.name)
                                      / f"h-{reach}")
            tid = other.begin("d-crash", "p-crash", "c" * 64, NOW,
                              item_id="never-recorded")
            other.transition(tid, AUTHORISATION_VERIFIED, NOW)
            if reach == BURN_PENDING:
                other.transition(tid, BURN_PENDING, NOW)
            outcomes = other.recover(other_ledger, self.loop,
                                     recorded_at=NOW)
            self.assertEqual([o["to_state"] for o in outcomes],
                             [REFUSED_PRE_BURN])
            self.assertEqual(other_ledger.entries(), [])

    def test_recovery_is_idempotent(self):
        orig_cycle = self.loop.run_one_cycle

        def cycle_then_crash(*args):
            orig_cycle(*args)
            raise RuntimeError("crash")

        with mock.patch.object(self.loop, "run_one_cycle",
                               cycle_then_crash):
            with self.assertRaises(RuntimeError):
                self.record()
        # CHANGED (fix round): recovery needs root= to re-verify
        # before finalising an unfinalised burn; see
        # test_crash_after_cycle_recorded_before_tx_update.
        first = self.recover(root=self.root)
        self.assertEqual([o["to_state"] for o in first], [COMMITTED])
        tx_entries = len(self.journal().entries())
        ledger_entries = len(self.ledger.entries())
        self.assertEqual(self.recover(), [])
        self.assertEqual(len(self.journal().entries()), tx_entries)
        self.assertEqual(len(self.ledger.entries()), ledger_entries)
        self.assertEqual(self.tx_state(), COMMITTED)


if __name__ == "__main__":
    unittest.main()
