"""Tests for the cycle-23 R5 anchored ship recording path:
trust.shipcheck.anchored_record_ship, plus the real-anchor
tripwire over the live state/ship-ledger/.

Sandbox pattern (fixture re-declared from
tests/test_trust_shipcheck.py): a fake repo tree, a temp
CoreLoop, a verifier-home ship ledger, and BOTH anchors
initialised in a directory outside the ledger dir. The anchored
path takes no caller-supplied ledger head: it verifies both
anchors, requires them CURRENT (anchor head/seq == the
journal's current head/length), derives the expected head from
the ship anchor, delegates to record_ship, and advances the
ship-tx anchor afterwards.

The tripwire at the bottom asserts the REAL anchors
(state/anchors/ship.anchor.json, state/anchors/ship-tx.anchor.json)
verify CURRENT against the REAL ledgers. It is supposed to fail
if a future recording forgets an anchor advance.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.gate import GateDecision, VerifierAttestation
from signing import (
    PURPOSE_SHIP,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
from trust.anchoring import (
    initialise_anchor,
    load_anchor,
    update_anchor,
    verify_anchor,
)
from trust.errors import ShipRefused
from trust.ledger import ShipLedger
from trust.manifest import build_manifest
from trust.release import build_release_record
from trust.shipcheck import anchored_record_ship, record_ship
from trust.shiptx import ShipTxJournal

KEY = make_signing_key(bytes(range(32, 64)))
REPO = Path(__file__).resolve().parents[1]


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


NOW = _ts(0)
ATTESTED = _ts(-10)
SATT_AT = _ts(-5)
SEALED = "b" * 64
CODERS = ["seat-1", "seat-2", "seat-3"]
REVIEWERS = ["rev-r1", "rev-r2", "rev-r3", "rev-r4", "rev-r5", "rev-r6"]
DELTA = {"metric": "tests_passing", "before": 1, "after": 2,
         "evidence_ref": "fixture run", "verifier": "rev-r1"}


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


class AnchoredShipFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.base = base
        self.root = make_tree(base / "repo")
        self.home = base / "verifier-home"
        self.ledger = ShipLedger(self.home)
        self.tx = ShipTxJournal(self.home)
        self.anchor_dir = base / "anchors"
        self.ship_anchor = self.anchor_dir / "ship.anchor.json"
        self.tx_anchor = self.anchor_dir / "ship-tx.anchor.json"
        initialise_anchor(self.ledger, self.ship_anchor,
                          kind="ship", recorded_at=NOW)
        initialise_anchor(self.tx, self.tx_anchor,
                          kind="ship-tx", recorded_at=NOW)
        self.loop = CoreLoop(base / "loop-state")

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, item_id, proposal):
        """A full ship package (manifest + attestation + signed
        decision) for one item, and the item scanned into the
        loop."""
        self.loop.scan([{"id": item_id, "title": f"ship {item_id}",
                         "leverage": 5.0}])
        manifest = build_manifest(
            self.root, proposal_id=proposal, item_id=item_id,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        att = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="war-room-cycle-23",
            attested_at=ATTESTED)
        satt = sign_attestation(
            att, signing_key=KEY, signer_id="seat-3",
            proposal_id=proposal,
            manifest_hash=manifest.manifest_hash, now=SATT_AT)
        decision = GateDecision(
            accepted=True, proposal_id=proposal, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=NOW,
            protected_violations=(),
            verifier_note=f"content-hash:{manifest.manifest_hash}")
        envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="verifier-svc",
            attestation=att, signed_attestation=satt,
            gate_inputs_hash=manifest.manifest_hash,
            purpose=PURPOSE_SHIP, now=NOW)
        return manifest, satt, envelope

    def release_for(self, manifest, envelope):
        if not self.loop.state_path.exists():
            self.loop.scan([])  # materialise the initial state file
        return build_release_record(
            manifest, envelope,
            expected_cycle_id=self.loop.state["cycle_seq"] + 1,
            pre_ship_cycle_seq=self.loop.state["cycle_seq"],
            pre_ship_state_sha256=hashlib.sha256(
                self.loop.state_path.read_bytes()).hexdigest())

    def anchored(self, manifest, satt, envelope, **over):
        kw = dict(root=self.root, manifest=manifest, signed=envelope,
                  signing_key=KEY, ledger=self.ledger, coders=CODERS,
                  reviewers=REVIEWERS, delta=DELTA,
                  release=self.release_for(manifest, envelope),
                  anchor_path=self.ship_anchor,
                  tx_anchor_path=self.tx_anchor,
                  expected_attestation=satt)
        kw.update(over)
        return anchored_record_ship(self.loop, **kw)

    def assert_current(self, journal, anchor_path, kind):
        self.assertEqual(
            verify_anchor(journal, anchor_path, kind=kind), ())
        anchor = load_anchor(anchor_path)
        journal._reload()
        self.assertEqual(anchor["head"], journal.head())
        self.assertEqual(anchor["seq"], len(journal.entries()))


class AnchoredRecordShipTests(AnchoredShipFixture):

    def test_anchored_record_ship_end_to_end(self):
        manifest, satt, envelope = self.package("item-one", "prop-one")
        entry = self.anchored(manifest, satt, envelope)
        self.assertEqual(entry["item_id"], "item-one")
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual([e["kind"] for e in self.ledger.entries()],
                         ["burn", "finalise"])
        # Both anchors advanced and CURRENT after the recording:
        # ship anchor at seq 2 (advanced by record_ship), ship-tx
        # anchor at the tx journal's full length (advanced by
        # the wrapper).
        self.assert_current(self.ledger, self.ship_anchor, "ship")
        self.assertEqual(load_anchor(self.ship_anchor)["seq"], 2)
        self.assert_current(self.tx, self.tx_anchor, "ship-tx")
        self.tx._reload()
        self.assertEqual(load_anchor(self.tx_anchor)["seq"],
                         len(self.tx.entries()))
        self.assertGreater(len(self.tx.entries()), 0)
        txs = self.tx.transactions()
        self.assertEqual(txs[-1]["state"], "COMMITTED")

    def test_rolled_back_ledger_refuses_pre_burn(self):
        manifest, satt, envelope = self.package("item-one", "prop-one")
        self.anchored(manifest, satt, envelope)
        # Roll the ship ledger back one entry (drop the finalise)
        # on disk; the anchor still pins seq 2.
        path = self.home / "ship-ledger.json"
        data = json.loads(path.read_text())
        data["entries"] = data["entries"][:-1]
        path.write_text(json.dumps(data))
        rolled = ShipLedger(self.home)
        self.assertEqual(len(rolled.entries()), 1)
        tx_count = len(ShipTxJournal(self.home).entries())
        manifest2, satt2, envelope2 = self.package("item-two",
                                                   "prop-two")
        with self.assertRaises(ShipRefused):
            self.anchored(manifest2, satt2, envelope2,
                          ledger=rolled)
        # Pre-burn: nothing spent, no new transaction opened.
        self.assertEqual(len(ShipLedger(self.home).entries()), 1)
        self.assertEqual(len(ShipTxJournal(self.home).entries()),
                         tx_count)
        self.assertEqual(len(self.loop.state["history"]), 1)

    def test_deleted_ledger_refused(self):
        manifest, satt, envelope = self.package("item-one", "prop-one")
        self.anchored(manifest, satt, envelope)
        (self.home / "ship-ledger.json").unlink()
        fresh = ShipLedger(self.home)  # a missing journal loads empty
        self.assertEqual(fresh.entries(), [])
        tx_count = len(ShipTxJournal(self.home).entries())
        manifest2, satt2, envelope2 = self.package("item-two",
                                                   "prop-two")
        with self.assertRaises(ShipRefused):
            self.anchored(manifest2, satt2, envelope2, ledger=fresh)
        self.assertEqual(len(ShipTxJournal(self.home).entries()),
                         tx_count)
        self.assertEqual(len(self.loop.state["history"]), 1)

    def test_stale_prefix_ship_anchor_refused_as_not_current(self):
        # Record through the UNANCHORED path: the ledger grows
        # past its anchor, which still verifies as a prefix but
        # is not current — the anchored path must refuse rather
        # than derive the head from the stale prefix.
        manifest, satt, envelope = self.package("item-one", "prop-one")
        entry = record_ship(
            self.loop, root=self.root, manifest=manifest,
            signed=envelope, signing_key=KEY, ledger=self.ledger,
            coders=CODERS, reviewers=REVIEWERS, delta=DELTA,
            release=self.release_for(manifest, envelope),
            expected_attestation=satt,
            expected_ledger_head=self.ledger.head())
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(
            verify_anchor(self.ledger, self.ship_anchor, kind="ship"),
            ())  # stale prefix still verifies — that is the trap
        manifest2, satt2, envelope2 = self.package("item-two",
                                                   "prop-two")
        with self.assertRaises(ShipRefused) as cm:
            self.anchored(manifest2, satt2, envelope2)
        self.assertIn("ship_anchor_not_current", cm.exception.reasons)
        self.assertEqual(len(self.ledger.entries()), 2)
        self.assertEqual(len(self.loop.state["history"]), 1)

    def test_stale_prefix_tx_anchor_refused_as_not_current(self):
        # Same trap on the tx side: advance ONLY the ship anchor
        # after an unanchored recording; the tx anchor is a stale
        # prefix of the grown tx journal.
        manifest, satt, envelope = self.package("item-one", "prop-one")
        record_ship(
            self.loop, root=self.root, manifest=manifest,
            signed=envelope, signing_key=KEY, ledger=self.ledger,
            coders=CODERS, reviewers=REVIEWERS, delta=DELTA,
            release=self.release_for(manifest, envelope),
            expected_attestation=satt,
            expected_ledger_head=self.ledger.head())
        update_anchor(self.ledger, self.ship_anchor, kind="ship",
                      recorded_at=NOW)
        manifest2, satt2, envelope2 = self.package("item-two",
                                                   "prop-two")
        with self.assertRaises(ShipRefused) as cm:
            self.anchored(manifest2, satt2, envelope2)
        self.assertIn("ship-tx_anchor_not_current",
                      cm.exception.reasons)
        self.assertEqual(len(self.ledger.entries()), 2)


class RealAnchorTripwireTests(unittest.TestCase):
    """The real anchors must verify CURRENT against the real
    ledgers — this fails if a future recording forgets to
    advance an anchor (or a ledger is rolled back)."""

    def test_real_anchors_verify_current(self):
        ledger_dir = REPO / "state" / "ship-ledger"
        ledger = ShipLedger(ledger_dir)
        tx = ShipTxJournal(ledger_dir)
        for journal, name, kind in (
                (ledger, "ship.anchor.json", "ship"),
                (tx, "ship-tx.anchor.json", "ship-tx")):
            anchor_path = REPO / "state" / "anchors" / name
            self.assertTrue(anchor_path.is_file(),
                            f"real anchor missing: {anchor_path}")
            self.assertEqual(
                verify_anchor(journal, anchor_path, kind=kind), (),
                f"real {kind} anchor does not verify")
            anchor = load_anchor(anchor_path)
            journal._reload()
            self.assertEqual(anchor["head"], journal.head(),
                             f"real {kind} anchor head is stale")
            self.assertEqual(anchor["seq"], len(journal.entries()),
                             f"real {kind} anchor seq is stale")


if __name__ == "__main__":
    unittest.main()
