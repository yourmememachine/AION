"""Cycle 32 — proof-carrying ship integration (seat C).

End-to-end: a proof artefact built over a base -> post tree
pair gates trust.shipcheck.record_ship via
trust.proofcarry.record_ship_with_proof. The happy path
records the cycle through the real CoreLoop / ShipLedger /
signed-envelope fixture pattern of
tests/test_trust_shipcheck.py; tampering with the post tree
after the artefact was built refuses BEFORE the burn — the
ledger stays empty and the loop does not advance.

The proof claim itself is pinned separately in
tests/test_cycle32_claim_pin.py; this file pins only the
integration behaviour.
"""

import base64
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.gate import GateDecision, VerifierAttestation
from signing import (
    PURPOSE_SHIP,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
import trust.proofcarry as proofcarry
from trust.errors import ShipRefused
from trust.ledger import ShipLedger
from trust.manifest import build_manifest
from trust.proofcarry import build_proof_artefact, record_ship_with_proof
from trust.release import build_release_record
from trust.shiptx import ShipTxJournal

KEY = make_signing_key(bytes(range(32, 64)))


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


NOW = _ts(0)
ATTESTED = _ts(-10)
SATT_AT = _ts(-5)


def _refresh_clock():
    """Re-stamp the fixture clock (cycle 33): freshness checks
    use the host wall clock, so import-time stamps expire during
    a long test run; setUp re-stamps instead."""
    global NOW, ATTESTED, SATT_AT
    NOW = _ts(0)
    ATTESTED = _ts(-10)
    SATT_AT = _ts(-5)
SEALED = "b" * 64
PROPOSAL = "prop-proof-ship"
ITEM = "proof-carrying-self-improvement"
CHANGE_ID = "cycle32-change-1"
CODERS = ["seat-1", "seat-2", "seat-3"]
REVIEWERS = ["rev-r1", "rev-r2", "rev-r3", "rev-r4", "rev-r5", "rev-r6"]
DELTA = {"metric": "tests_passing", "before": 1, "after": 2,
         "evidence_ref": "fixture run", "verifier": "rev-r1"}
SCOPE_PATHS = ["core/a.py", "check_a.py"]

CHECK_SCRIPT = (
    "import pathlib\n"
    "import sys\n"
    "\n"
    'text = (pathlib.Path(__file__).resolve().parent\n'
    '        / "core" / "a.py").read_text(encoding="utf-8")\n'
    'if "A = 2" in text:\n'
    '    print("A_IS_2")\n'
    "    sys.exit(0)\n"
    'print("A_NOT_2")\n'
    "sys.exit(1)\n"
)


def make_tree(root: Path, a_value: int):
    (root / "core").mkdir(parents=True)
    (root / "core" / "a.py").write_text(f"A = {a_value}\n")
    (root / "check_a.py").write_text(CHECK_SCRIPT)
    (root / "eval").mkdir()
    (root / "eval" / "gate.py").write_text("GATE = True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (root / "internal").mkdir()
    (root / "internal" / "REVIEW.md").write_text("# review\n")
    return root


def make_invariants():
    return [{
        "id": "a-is-2",
        "description": "core/a.py declares A = 2",
        "argv": [sys.executable, "check_a.py"],
        "scope": "new",
        "mutation": {
            "path": "core/a.py",
            "content_b64": base64.b64encode(b"A = 1\n").decode("ascii"),
        },
    }]


class ProofShipFixture(unittest.TestCase):
    def setUp(self):
        _refresh_clock()
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.base_root = make_tree(base / "base-repo", 1)
        self.post_root = make_tree(base / "post-repo", 2)
        self.home = base / "verifier-home"
        self.ledger = ShipLedger(self.home)
        self.loop = CoreLoop(base / "loop-state")
        self.loop.scan([{"id": ITEM, "title": "fixture proof ship item",
                         "leverage": 5.0}])
        self.manifest = build_manifest(
            self.post_root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        self.att = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="war-room-cycle-32",
            attested_at=ATTESTED)
        self.satt = sign_attestation(
            self.att, signing_key=KEY, signer_id="seat-3",
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            now=SATT_AT)
        self.envelope = self._envelope()
        self.artefact = build_proof_artefact(
            change_id=CHANGE_ID, base_root=self.base_root,
            post_root=self.post_root, scope_paths=SCOPE_PATHS,
            invariants=make_invariants(), created_at=NOW)

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

    def _release(self):
        if not self.loop.state_path.exists():
            self.loop.scan([])  # materialise the initial state file
        return build_release_record(
            self.manifest, self.envelope,
            expected_cycle_id=self.loop.state["cycle_seq"] + 1,
            pre_ship_cycle_seq=self.loop.state["cycle_seq"],
            pre_ship_state_sha256=hashlib.sha256(
                self.loop.state_path.read_bytes()).hexdigest())

    def record_with_proof(self, **over):
        # No root kwarg: record_ship_with_proof supplies
        # root=post_root itself when it delegates to record_ship.
        kw = dict(base_root=self.base_root, post_root=self.post_root,
                  artefact=self.artefact, expected_change_id=CHANGE_ID,
                  manifest=self.manifest,
                  signed=self.envelope, signing_key=KEY,
                  ledger=self.ledger, coders=CODERS,
                  reviewers=REVIEWERS, delta=DELTA,
                  release=self._release(),
                  expected_attestation=self.satt,
                  expected_ledger_head=self.ledger.head())
        kw.update(over)
        loop = kw.pop("loop", self.loop)
        return record_ship_with_proof(loop, **kw)


class RecordShipWithProofTests(ProofShipFixture):
    def test_proof_gated_ship_records_cycle(self):
        entry = self.record_with_proof()
        self.assertEqual(entry["item_id"], ITEM)
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(self.loop.state["cycle_seq"], 1)
        kinds = [e["kind"] for e in self.ledger.entries()]
        self.assertEqual(kinds, ["burn", "finalise"])

    def test_tampered_post_tree_refused_before_burn(self):
        seq_before = self.loop.state["cycle_seq"]
        # Tamper AFTER the artefact was built in setUp: the
        # artefact binds the exact post-tree contents, so this
        # tree is no longer the tree the proof was made over.
        (self.post_root / "core" / "a.py").write_text("A = 3\n")
        with self.assertRaises(ShipRefused) as ctx:
            self.record_with_proof()
        self.assertIn("proof_refused", str(ctx.exception))
        # Nothing was burned and the loop did not advance.
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.loop.state["cycle_seq"], seq_before)
        self.assertEqual(self.loop.state["history"], [])


class _TamperPostTreeLoop(CoreLoop):
    """A CoreLoop whose run_one_cycle first tampers with the
    LIVE post tree, then records normally (design 12.2.3).

    This is the worst moment for the tamper: verification has
    already accepted the live tree, and the tamper lands while
    the cycle is being recorded. Against the pre-addendum
    wrapper (which delegated the live tree) record_ship's
    post-record re-verification saw the tamper and withheld
    finalise; against the snapshot composition the tamper
    cannot reach the shipped tree and the ship finalises."""

    tamper_target = None

    def run_one_cycle(self, *args, **kwargs):
        Path(self.tamper_target).write_bytes(b"tampered\n")
        return super().run_one_cycle(*args, **kwargs)


class FixRoundShipTests(ProofShipFixture):
    """Design 12.1.3 / 12.2.3: unscoped-change refusal,
    artefact-hash binding, and the snapshot composition."""

    @property
    def bindings_path(self):
        return self.ledger.journal_dir / "proof-bindings.jsonl"

    def _snapshot_of_ship_state(self):
        tx_path = self.ledger.journal_dir / "ship-tx.json"
        return (
            json.dumps(self.ledger.entries(), sort_keys=True),
            tx_path.read_bytes() if tx_path.exists() else None,
            self.loop.state_path.read_bytes(),
        )

    # -- 12.1.1 / 12.1.3: unscoped changes --------------------

    def test_unscoped_change_refused_before_burn(self):
        # One file outside scope_paths differs between base
        # and post (the artefact itself is valid over scope).
        (self.post_root / "eval" / "gate.py").write_text(
            "GATE = False\n")
        before = self._snapshot_of_ship_state()
        with self.assertRaises(ShipRefused) as ctx:
            self.record_with_proof()
        self.assertEqual(ctx.exception.reasons,
                         ("unscoped_changes",))
        self.assertEqual(self._snapshot_of_ship_state(), before)
        self.assertFalse(self.bindings_path.exists())

    def test_unscoped_addition_and_deletion_refused(self):
        added = self.post_root / "extra.py"
        added.write_text("EXTRA = 1\n")
        with self.assertRaises(ShipRefused) as ctx:
            self.record_with_proof()
        self.assertEqual(ctx.exception.reasons,
                         ("unscoped_changes",))
        added.unlink()
        (self.post_root / "eval" / "gate.py").unlink()
        with self.assertRaises(ShipRefused) as ctx:
            self.record_with_proof()
        self.assertEqual(ctx.exception.reasons,
                         ("unscoped_changes",))
        self.assertEqual(self.ledger.entries(), [])
        self.assertFalse(self.bindings_path.exists())

    def test_unscoped_pycache_difference_ignored(self):
        cache = self.post_root / "core" / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-311.pyc").write_bytes(b"\x00\x01\x02")
        entry = self.record_with_proof()
        self.assertEqual(entry["cycle_id"], 1)
        kinds = [e["kind"] for e in self.ledger.entries()]
        self.assertEqual(kinds, ["burn", "finalise"])

    # -- 12.1.2 / 12.1.3: the proof binding -------------------

    def test_scoped_ship_writes_proof_binding(self):
        entry = self.record_with_proof()
        self.assertEqual(entry["proof_artefact_hash"],
                         self.artefact["artefact_hash"])
        self.assertEqual(entry["proof_post_tree_hash"],
                         self.artefact["post_tree_hash"])
        lines = self.bindings_path.read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(set(record), {
            "cycle_id", "item_id", "change_id", "manifest_hash",
            "artefact_hash", "post_tree_hash", "recorded_at",
            "prev_binding_hash", "binding_hash"})
        self.assertEqual(record["cycle_id"], entry["cycle_id"])
        self.assertEqual(record["item_id"], entry["item_id"])
        self.assertEqual(record["change_id"],
                         self.artefact["change_id"])
        self.assertEqual(record["artefact_hash"],
                         self.artefact["artefact_hash"])
        self.assertEqual(record["post_tree_hash"],
                         self.artefact["post_tree_hash"])
        self.assertEqual(record["manifest_hash"],
                         self.manifest.manifest_hash)
        # The durable carrier is the bindings file, NOT the
        # persisted loop state: the on-disk history entry for
        # this cycle carries neither proof key.
        persisted = json.loads(
            self.loop.state_path.read_text(encoding="utf-8"))
        persisted_entry = next(
            e for e in persisted["history"]
            if e["cycle_id"] == entry["cycle_id"])
        self.assertNotIn("proof_artefact_hash", persisted_entry)
        self.assertNotIn("proof_post_tree_hash", persisted_entry)

    def test_proof_binding_failure_ship_stands(self):
        with mock.patch.object(
                proofcarry, "_append_proof_binding",
                side_effect=OSError("disk full")):
            with self.assertRaises(ShipRefused) as ctx:
                self.record_with_proof()
        self.assertIn(
            "recorded and the decision finalised, but the "
            "proof binding failed", str(ctx.exception))
        self.assertIn("cycle 1", str(ctx.exception))
        kinds = [e["kind"] for e in self.ledger.entries()]
        self.assertEqual(kinds, ["burn", "finalise"])
        self.assertEqual(self.loop.state["cycle_seq"], 1)
        self.assertEqual(len(self.loop.state["history"]), 1)

    # -- 12.2: snapshot composition ---------------------------

    def test_live_tamper_during_recording_is_harmless(self):
        loop = _TamperPostTreeLoop(self.loop.state_dir)
        loop.tamper_target = self.post_root / "core" / "a.py"
        entry = self.record_with_proof(loop=loop)
        self.assertEqual(entry["cycle_id"], 1)
        kinds = [e["kind"] for e in self.ledger.entries()]
        self.assertEqual(kinds, ["burn", "finalise"])
        tx_entries = ShipTxJournal(self.ledger.journal_dir).entries()
        self.assertEqual(tx_entries[-1]["to_state"], "COMMITTED")
        # The tamper really landed on the LIVE tree (the test
        # is not vacuous): its bytes differ from what the
        # shipped manifest recorded for that path.
        live_bytes = (self.post_root / "core" / "a.py").read_bytes()
        self.assertEqual(live_bytes, b"tampered\n")
        manifest_entry = next(
            f for f in self.manifest.files
            if f["path"] == "core/a.py")
        self.assertNotEqual(
            hashlib.sha256(live_bytes).hexdigest(),
            manifest_entry["sha256"])
        record = json.loads(self.bindings_path.read_text(
            encoding="utf-8").splitlines()[0])
        self.assertEqual(record["post_tree_hash"],
                         self.artefact["post_tree_hash"])

    def test_pre_call_tamper_refuses_before_burn(self):
        (self.post_root / "core" / "a.py").write_text("A = 3\n")
        with self.assertRaises(ShipRefused) as ctx:
            self.record_with_proof()
        self.assertIn("post_tree_mismatch", ctx.exception.reasons)
        self.assertEqual(self.ledger.entries(), [])
        self.assertFalse(self.bindings_path.exists())

    def test_snapshot_removed_after_ship_and_after_refusal(self):
        recorded = []
        original = proofcarry._snapshot_tree

        @contextlib.contextmanager
        def recording_snapshot(root):
            with original(root) as snapshot:
                recorded.append(snapshot)
                yield snapshot

        with mock.patch.object(proofcarry, "_snapshot_tree",
                               recording_snapshot):
            with mock.patch("trust.shipcheck.record_ship",
                            side_effect=ShipRefused("delegate boom")):
                with self.assertRaises(ShipRefused):
                    self.record_with_proof()
            self.assertEqual(len(recorded), 1)
            self.assertFalse(recorded[0].exists())
            entry = self.record_with_proof()
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(len(recorded), 2)
        self.assertFalse(recorded[1].exists())

    def test_manifest_built_before_live_change_refuses(self):
        # Flip ONLY the executable bit of a scoped file after
        # the manifest and artefact were built: proofcarry
        # does not bind mode (12.5), so W1/W4 pass, but the
        # snapshot carries the flipped bit and check_ship's
        # manifest comparison refuses inside record_ship,
        # pre-burn (the 12.2.1 residual, fail-closed).
        target = self.post_root / "core" / "a.py"
        os.chmod(target, os.stat(target).st_mode | 0o111)
        with self.assertRaises(ShipRefused):
            self.record_with_proof()
        self.assertEqual(self.ledger.entries(), [])
        self.assertFalse(self.bindings_path.exists())


if __name__ == "__main__":
    unittest.main()
