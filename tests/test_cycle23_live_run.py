"""WS1 live run (cycle 23, DESIGN-FINAL R1): the production
pin adopter driven against a byte copy of the REAL ``state/``
directory (state.json at cycle_seq 13 + calibration), in a
sandbox, against the WS2 production verifier home
(``tests/cycle23_harness.py``). The real state directory is
never written: the test asserts its state.json sha256 is
identical before and after.

Exact sequence (R1):
  (1) snapshot_and_adopt() -> genesis initial_anchor at seq 13
  (2) one HOOKED cycle (CoreLoop(cycle_hook=pin_cycle_hook(
      adopter))) -> dense advance_pin to 14, no consumption
  (3) two hookless cycles -> seq 15, 16 unpinned
  (4) snapshot_and_adopt() -> chain_gap_recovery ceremony to 16
  (5) snapshot_and_adopt() -> already_current

Sandbox cycles run through the public loop API only. The
sandbox copy's backlog is the real backlog: pick_next()
returns its top item, which is asserted (recorded from the
copy before the cycle), never assumed.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cycle23_harness import OPERATOR, SIGNER, SNAP_SIGNER, \
    provision_production_home
from core.loop import CoreLoop
from signing.pin_store import PinStore
from trust.ledger import CeremonyConsumptionLedger
from trust.pin_adoption import (
    PinAdopterConfig,
    build_pin_adopter,
    pin_cycle_hook,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_STATE_DIR = REPO_ROOT / "state"
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 13, "after": 14,
         "evidence_ref": "cycle23-live-run", "verifier": "rev-1"}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LiveRunTests(unittest.TestCase):
    def setUp(self):
        self.real_state_hash_before = _sha256(
            REAL_STATE_DIR / "state.json")
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        # Byte copy of the real state dir; the real one is
        # never opened for writing.
        self.state_dir = base / "state"
        shutil.copytree(REAL_STATE_DIR, self.state_dir)
        self.home = provision_production_home(base / "prod-home")
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        config = PinAdopterConfig(
            state_path=self.state_dir / "state.json",
            calibration_path=self.state_dir / "calibration"
            / "calibration.json",
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.home.evidence_dir)
        self.adopter = build_pin_adopter(
            self.home.env, expected_signer_id=SIGNER,
            expected_key_id=self.home.verifier_key_id,
            authorisation_public_key=self.home.pub,
            signing_key_path=self.home.snapshot_key_path,
            config=config)

    def tearDown(self):
        self.tmp.cleanup()

    def consumption_count(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return len(ledger.entries())

    def read_store(self):
        return self.store.read_all(
            signing_key=self.home.snapshot_key)

    def test_live_run_sequence(self):
        # The sandbox copy starts exactly where the real state
        # is: cycle_seq 13.
        probe = CoreLoop(self.state_dir)
        self.assertEqual(probe.state["cycle_seq"], 13)
        pin, history = self.read_store()
        self.assertIsNone(pin)
        self.assertEqual(history, ())

        # (1) Genesis initial_anchor ceremony at seq 13.
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "initial_anchor")
        self.assertEqual(result.record.new_cycle_seq, 13)
        self.assertIsNone(result.record.old_cycle_seq)
        pin, history = self.read_store()
        self.assertEqual(pin, result.pin)
        self.assertEqual(pin["cycle_seq"], 13)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.consumption_count(), 1)

        # (2) One hooked cycle -> dense advance to 14. The item
        # recorded is whatever pick_next() returns on the copy.
        expected_item = CoreLoop(self.state_dir).pick_next()
        self.assertIsNotNone(expected_item)
        hooked = CoreLoop(
            self.state_dir,
            cycle_hook=pin_cycle_hook(self.adopter))
        self.assertIsNotNone(hooked.cycle_hook)
        entry = hooked.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["cycle_id"], 14)
        self.assertEqual(entry["item_id"], expected_item["id"])
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 14)
        self.assertEqual(len(history), 1)   # advance: no record
        self.assertEqual(self.consumption_count(), 1)

        # (3) Two hookless cycles -> 15, 16 unpinned.
        for expected_seq in (15, 16):
            loop = CoreLoop(self.state_dir)
            entry = loop.run_one_cycle(
                CODERS, REVIEWERS, "reconciled", True, DELTA)
            self.assertEqual(entry["cycle_id"], expected_seq)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 14)
        self.assertEqual(self.consumption_count(), 1)

        # (4) chain_gap_recovery ceremony to 16.
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.record.old_cycle_seq, 14)
        self.assertEqual(result.record.new_cycle_seq, 16)
        self.assertEqual(result.record.gap_from_seq, 15)
        self.assertEqual(result.record.gap_to_seq, 15)
        pin, history = self.read_store()
        self.assertEqual(pin, result.pin)
        self.assertEqual(pin["cycle_seq"], 16)
        self.assertEqual(len(history), 2)
        self.assertEqual(self.consumption_count(), 2)

        # (5) Unchanged state -> already_current, no consumption.
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "already_current")
        self.assertEqual(result.pin, pin)
        self.assertIsNone(result.record)
        self.assertEqual(self.consumption_count(), 2)

        # The REAL state was never touched.
        self.assertEqual(
            _sha256(REAL_STATE_DIR / "state.json"),
            self.real_state_hash_before)


if __name__ == "__main__":
    unittest.main()
