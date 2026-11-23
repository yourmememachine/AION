"""Tests for the cycle-23 R1 loop hook: CoreLoop's
constructor-injected ``cycle_hook``, trust.pin_adoption's
``pin_cycle_hook`` factory, the run_one_cycle_and_pin hooked-loop
refusal, and record_ship's hooked-loop refusal.

The hook contract (core/loop.py docstrings): the hook fires
exactly once per recorded cycle, AFTER persistence — "cycle
recorded, pin pending, alert". A hook exception propagates
unwrapped and never un-records the cycle.

The pin-adoption integration fixture is re-declared here in the
research-mode client pattern of tests/test_trust_pin_adoption.py
(real verifier subprocess, directly built client), so this file
runs standalone.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop, InvalidTransition
from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from signing.pin_store import PinStore
from trust.client import VerifierClient
from trust.errors import ShipRefused
from trust.ledger import ShipLedger
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
    PinAdoptionBurned,
    pin_cycle_hook,
    run_one_cycle_and_pin,
)
from trust.shipcheck import record_ship

CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


def _loop_with_item(state_dir, hook=None):
    loop = CoreLoop(state_dir, cycle_hook=hook)
    loop.scan([{"id": "item-1", "title": "Hook item", "leverage": 1.0}])
    return loop


class LoopHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hook_fires_once_post_save_with_the_entry(self):
        seen = []
        disk_seqs = []

        def hook(entry):
            seen.append(entry)
            # Post-save: the state file on disk already carries
            # this cycle when the hook runs.
            disk = json.loads(
                (self.base / "state" / "state.json").read_bytes())
            disk_seqs.append(disk["cycle_seq"])

        loop = _loop_with_item(self.base / "state", hook=hook)
        entry = loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                                   True, DELTA)
        self.assertEqual(seen, [entry])
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(disk_seqs, [1])

    def test_hook_exception_propagates_and_cycle_stays_recorded(self):
        class HookBoom(Exception):
            pass

        def hook(entry):
            raise HookBoom("pin pending")

        loop = _loop_with_item(self.base / "state", hook=hook)
        with self.assertRaises(HookBoom):
            loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                               True, DELTA)
        # The contract: the cycle HAS the state on disk — a fresh
        # loop over the same dir sees it recorded.
        fresh = CoreLoop(self.base / "state")
        self.assertEqual(fresh.state["cycle_seq"], 1)
        self.assertEqual(len(fresh.state["history"]), 1)
        self.assertEqual(fresh.state["history"][0]["item_id"], "item-1")

    def test_hook_not_fired_on_idle(self):
        seen = []
        loop = CoreLoop(self.base / "state", cycle_hook=seen.append)
        self.assertIsNone(loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA))
        self.assertEqual(seen, [])

    def test_hook_not_fired_on_refusal(self):
        seen = []
        loop = _loop_with_item(self.base / "state", hook=seen.append)
        with self.assertRaises(InvalidTransition):
            loop.run_one_cycle(CODERS, REVIEWERS, "split", True, DELTA)
        with self.assertRaises(InvalidTransition):
            loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                               False, DELTA)
        self.assertEqual(seen, [])
        self.assertEqual(loop.state["cycle_seq"], 0)

    def test_default_no_hook_behaviour_unchanged(self):
        loop = _loop_with_item(self.base / "state")
        self.assertIsNone(loop.cycle_hook)
        entry = loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                                   True, DELTA)
        self.assertEqual(entry["cycle_id"], 1)
        self.assertEqual(loop.state["cycle_seq"], 1)

    def test_cycle_hook_property_is_read_only(self):
        loop = CoreLoop(self.base / "state", cycle_hook=lambda e: None)
        self.assertIsNotNone(loop.cycle_hook)
        with self.assertRaises(AttributeError):
            loop.cycle_hook = None


# -- pin_cycle_hook integration (research-mode fixture pattern) ----

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
CAL = b'{"log":1}'


class PinCycleHookFixture(unittest.TestCase):
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
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.evidence_dir)
        self.adopter = PinAdopter(
            client=self.client, store=self.store,
            signing_key=SNAP_KEY, config=config,
            authorisation_public_key=self.pub)
        self._item_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def scan_items(self, loop, n):
        items = []
        for _ in range(n):
            self._item_seq += 1
            items.append({"id": f"item-{self._item_seq}",
                          "title": f"Hook adoption item {self._item_seq}",
                          "leverage": 1.0})
        loop.scan(items)

    def hooked_loop(self):
        return CoreLoop(self.state_dir,
                        cycle_hook=pin_cycle_hook(self.adopter))

    def genesis_via_hook(self):
        loop = self.hooked_loop()
        self.scan_items(loop, 1)
        entry = loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                                   True, DELTA)
        self.assertEqual(entry["cycle_id"], 1)
        pin, history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].reason, "initial_anchor")
        return entry


class PinCycleHookTests(PinCycleHookFixture):

    def test_hook_drives_genesis_and_dense_advance(self):
        self.genesis_via_hook()
        loop = self.hooked_loop()
        self.scan_items(loop, 1)
        entry = loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                                   True, DELTA)
        self.assertEqual(entry["cycle_id"], 2)
        pin, history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertEqual(pin["cycle_seq"], 2)
        self.assertEqual(len(history), 1)  # advance: no new ceremony

    def test_burned_adoption_carries_cycle_entry(self):
        self.genesis_via_hook()
        # Two hookless cycles open a gap (pin at 1, state at 3).
        # A FRESH loop instance: self.loop's in-memory state
        # predates the hooked genesis and must not overwrite it.
        bare = CoreLoop(self.state_dir)
        self.scan_items(bare, 2)
        bare.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                           True, DELTA)
        bare.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                           True, DELTA)
        real_adopt = self.store.adopt

        def flaky_adopt(new_pin, record=None, **kw):
            if record is not None:
                raise OSError("simulated adopt failure")
            return real_adopt(new_pin, record, **kw)

        self.store.adopt = flaky_adopt
        try:
            loop = self.hooked_loop()
            self.scan_items(loop, 1)
            with self.assertRaises(PinAdoptionBurned) as cm:
                loop.run_one_cycle(CODERS, REVIEWERS, "reconciled",
                                   True, DELTA)
        finally:
            self.store.adopt = real_adopt
        # .cycle_entry attached by pin_cycle_hook, and the cycle
        # itself stayed recorded (the hook contract).
        self.assertIsNotNone(cm.exception.cycle_entry)
        self.assertEqual(cm.exception.cycle_entry["cycle_id"], 4)
        fresh = CoreLoop(self.state_dir)
        self.assertEqual(fresh.state["cycle_seq"], 4)

    def test_authorise_pending_alone_is_not_a_burn(self):
        # R4: the authorise_pending detection line (appended by
        # _reanchor BEFORE the authorise call) must not count as
        # an unadopted burn — only authorised/consumed phases do.
        self.adopter._append_journal({
            "phase": "authorise_pending",
            "ceremony_id": "pin-adopt-1-deadbeefcafe",
            "candidate_seq": 1, "candidate_hash": "a" * 64,
            "old_cycle_seq": None, "old_payload_hash": ""})
        self.assertEqual(self.adopter._unadopted_burns(), [])
        merged = self.adopter._journal_ceremonies()
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["phases"], {"authorise_pending"})

    def test_run_one_cycle_and_pin_refuses_hooked_loop(self):
        loop = self.hooked_loop()
        self.scan_items(loop, 1)
        with self.assertRaises(ValueError):
            run_one_cycle_and_pin(
                loop, self.adopter, coders=CODERS,
                reviewers=REVIEWERS, verdict="reconciled",
                verify_passed=True, delta=DELTA)
        # Nothing ran: no cycle recorded, no pin written.
        self.assertEqual(loop.state["cycle_seq"], 0)
        pin, _history = self.store.read_all(signing_key=SNAP_KEY)
        self.assertIsNone(pin)


class RecordShipHookRefusalTests(unittest.TestCase):
    """record_ship refuses a hooked loop BEFORE the transaction
    opens: no tx journal entry is created and nothing is burned.
    The refusal precedes any use of manifest/decision/release,
    so those are passed as None here — the pin is exactly that
    the state machine is never reached."""

    def test_record_ship_refuses_hooked_loop_pre_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "verifier-home"
            ledger = ShipLedger(home)
            loop = CoreLoop(base / "loop-state",
                            cycle_hook=lambda entry: None)
            loop.scan([{"id": "item-1", "title": "Ship item",
                        "leverage": 1.0}])
            with self.assertRaises(ShipRefused) as cm:
                record_ship(
                    loop, root=base, manifest=None, signed=None,
                    signing_key=None, ledger=ledger, coders=CODERS,
                    reviewers=REVIEWERS, delta=DELTA, release=None,
                    expected_ledger_head=ledger.head())
            self.assertIn("cycle_hook", str(cm.exception))
            self.assertFalse((home / "ship-tx.json").exists())
            self.assertEqual(ledger.entries(), [])
            self.assertEqual(loop.state["history"], [])


if __name__ == "__main__":
    unittest.main()
