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
import hashlib
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
from trust.errors import ShipRefused
from trust.ledger import ShipLedger
from trust.manifest import build_manifest
from trust.proofcarry import build_proof_artefact, record_ship_with_proof
from trust.release import build_release_record

KEY = make_signing_key(bytes(range(32, 64)))


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


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


if __name__ == "__main__":
    unittest.main()
