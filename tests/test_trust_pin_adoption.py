"""Integration tests for trust/pin_adoption.py (cycle 22,
design C §8.2): the full pin-adoption flow against the REAL
verifier subprocess, in temp dirs only.

Honest harness note (design C §8.2): ``build_pin_adopter``
builds its client only via ``production_client``, which
requires mode ``production`` + anchors; this harness env is
the consumption suite's RESEARCH env, so — except for the
config-refusal case, which exercises the factory itself — the
adopter under test is constructed around a directly built
``VerifierClient`` (the R12 pattern: real verifier subprocess,
real consumer, fixture wiring), exactly as
``test_trust_ceremony_consumption.py`` does. Fixtures are
re-declared here, not imported, so this file runs standalone.
State side: a real ``CoreLoop`` in a temp state dir plus a real
calibration file at ``<state_dir>/calibration/calibration.json``.
Live clock end-to-end; no ``now=`` is passed anywhere (the flow
has none to pass).
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from signing.pin_store import PinStore
from trust.client import VerifierClient
from trust.ledger import CeremonyConsumptionLedger
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
    PinAdoptionBurned,
    PinAdoptionRefused,
    build_pin_adopter,
    pin_adopter_config_from_env,
    run_one_cycle_and_pin,
)

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
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


class PinAdoptionFixture(unittest.TestCase):
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
        # State side.
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

    def _make_adopter(self, client, **config_over):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.evidence_dir)
        if config_over:
            from dataclasses import replace as _replace
            config = _replace(config, **config_over)
        return PinAdopter(client=client, store=self.store,
                          signing_key=SNAP_KEY, config=config,
                          authorisation_public_key=self.pub)

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

    def consumption_count(self):
        ledger = CeremonyConsumptionLedger(self.home / "ledger")
        return len(ledger.entries())

    def read_store(self):
        return self.store.read_all(signing_key=SNAP_KEY)

    def genesis(self):
        self.scan_items(1)
        entry, result = self.wrapped_cycle()
        self.assertEqual(result.outcome, "reanchored")
        return entry, result


class PinAdoptionIntegrationTests(PinAdoptionFixture):

    def test_01_genesis_initial_anchor(self):
        _entry, result = self.genesis()
        self.assertEqual(result.record.reason, "initial_anchor")
        pin_path = self.pin_dir / "snapshot-pin.json"
        self.assertTrue(pin_path.is_file())
        self.assertNotIn(self.state_dir,
                         pin_path.resolve().parents)
        pin, history = self.read_store()
        self.assertEqual(pin, result.pin)
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0], result.record)
        self.assertEqual(self.consumption_count(), 1)

    def test_02_advance_path_no_ceremony_burn(self):
        self.genesis()
        self.scan_items(3)
        for expected_seq in (2, 3, 4):
            _entry, result = self.wrapped_cycle()
            self.assertEqual(result.outcome, "advanced")
            self.assertEqual(result.pin["cycle_seq"], expected_seq)
            self.assertIsNone(result.record)
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 4)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.consumption_count(), 1)

    def test_03_gap_ceremony_then_already_current(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 3)
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.record.gap_from_seq, 2)
        self.assertEqual(result.record.gap_to_seq, 2)
        pin, history = self.read_store()
        self.assertEqual(pin, result.pin)
        self.assertEqual(len(history), 2)
        self.assertEqual(self.consumption_count(), 2)
        # Second attempt on unchanged state: already_current,
        # NO new consumption.
        again = self.adopter.snapshot_and_adopt()
        self.assertEqual(again.outcome, "already_current")
        self.assertEqual(again.pin, pin)
        self.assertEqual(self.consumption_count(), 2)

    def test_04_integrity_failure_persists_nothing(self):
        self.genesis()
        self.scan_items(1)
        self.bare_cycle()
        pin_bytes = self.store.path.read_bytes()
        consumption_before = self.consumption_count()
        journal_before = self.adopter.pending_journal_path.read_bytes()
        evidence_before = sorted(
            p.name for p in self.evidence_dir.iterdir())
        # (a) signer mismatch: expected_snapshot_signer_id pin
        # names a different signer than the snapshot's.
        mismatched = self._make_adopter(
            self.client, expected_snapshot_signer_id="other-signer")
        with self.assertRaises(PinAdoptionRefused):
            mismatched.snapshot_and_adopt()
        self.assertEqual(self.store.path.read_bytes(), pin_bytes)
        # No ceremony was started: the pending journal and the
        # evidence dir are exactly as before the attempt.
        self.assertEqual(
            self.adopter.pending_journal_path.read_bytes(),
            journal_before)
        self.assertEqual(
            sorted(p.name for p in self.evidence_dir.iterdir()),
            evidence_before)
        self.assertEqual(self.consumption_count(), consumption_before)
        # (b) state bytes that fail parse_state_bytes.
        self.loop.state_path.write_bytes(b"this is not state json")
        with self.assertRaises(PinAdoptionRefused):
            self.adopter.snapshot_and_adopt()
        self.assertEqual(self.store.path.read_bytes(), pin_bytes)
        self.assertEqual(
            self.adopter.pending_journal_path.read_bytes(),
            journal_before)
        self.assertEqual(self.consumption_count(), consumption_before)

    def test_05_consume_committed_adopt_failed_then_adopt_returned(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        old_pin, _history = self.read_store()
        consumption_before = self.consumption_count()
        real_adopt = self.store.adopt

        def flaky_adopt(new_pin, record=None, **kw):
            if record is not None:
                raise OSError("simulated adopt failure")
            return real_adopt(new_pin, record, **kw)

        self.store.adopt = flaky_adopt
        try:
            with self.assertRaises(PinAdoptionBurned) as cm:
                self.adopter.snapshot_and_adopt()
        finally:
            self.store.adopt = real_adopt
        burned = cm.exception
        self.assertIsNotNone(burned.returned_pin)
        self.assertIsNotNone(burned.returned_record)
        # Pin file still at the old pin; the burn is real (+1).
        pin, history = self.read_store()
        self.assertEqual(pin, old_pin)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.consumption_count(),
                         consumption_before + 1)
        # adopt_returned succeeds with NO new consumption.
        result = self.adopter.adopt_returned(
            burned.returned_pin, burned.returned_record,
            expected_old_pin=old_pin)
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(self.consumption_count(),
                         consumption_before + 1)
        pin, history = self.read_store()
        self.assertEqual(pin, burned.returned_pin)
        self.assertEqual(history[-1], burned.returned_record)

    def test_05b_discarded_pair_fresh_ceremony_no_lost_pin(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        consumption_before = self.consumption_count()
        real_adopt = self.store.adopt
        state = {"armed": True}

        def flaky_adopt(new_pin, record=None, **kw):
            if record is not None and state["armed"]:
                state["armed"] = False
                raise OSError("simulated adopt failure")
            return real_adopt(new_pin, record, **kw)

        self.store.adopt = flaky_adopt
        try:
            with self.assertRaises(PinAdoptionBurned):
                self.adopter.snapshot_and_adopt()
            # Pair discarded: a fresh snapshot_and_adopt performs
            # a NEW ceremony (new ceremony_id, new evidence, a
            # second consumption) and succeeds — recovery without
            # lost_pin anywhere.
            result = self.adopter.snapshot_and_adopt()
        finally:
            self.store.adopt = real_adopt
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "burned_unadopted")
        self.assertEqual(self.consumption_count(),
                         consumption_before + 2)
        _pin, history = self.read_store()
        self.assertNotIn("lost_pin", [r.reason for r in history])
        artefacts = sorted(self.evidence_dir.glob("pin-evidence-*"))
        self.assertEqual(len(artefacts), 3)

    def test_06_verifier_down_ceremony_path_raises_pin_unchanged(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        pin_bytes = self.store.path.read_bytes()
        down = VerifierClient(
            module="trust.no_such_verifier_module",
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        down_adopter = self._make_adopter(down)
        with self.assertRaises(PinAdoptionRefused):
            down_adopter.snapshot_and_adopt()
        self.assertEqual(self.store.path.read_bytes(), pin_bytes)
        _pin, history = self.read_store()
        self.assertEqual(len(history), 1)

    def test_07_evidence_independence_and_intent(self):
        _entry, genesis_result = self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        result = self.adopter.snapshot_and_adopt()
        hashes = []
        for record in (genesis_result.record, result.record):
            artefact = self.evidence_dir / f"pin-evidence-{record.ceremony_id}"
            self.assertTrue(artefact.is_file())
            digest = hashlib.sha256(artefact.read_bytes()).hexdigest()
            self.assertEqual(digest, record.evidence_hash)
            hashes.append(digest)
        self.assertNotEqual(hashes[0], hashes[1])
        gap_bundle = (self.evidence_dir
                      / f"pin-evidence-{result.record.ceremony_id}")
        self.assertIn("gap_from_seq=2", gap_bundle.read_text())

    def test_08_config_refusals(self):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir, snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR, expected_verifier_signer_id=SIGNER,
            evidence_dir=self.evidence_dir)
        # (a) Evidence-dir mismatch, visible in the env.
        env = dict(self.env)
        env["AION_CEREMONY_EVIDENCE_DIR"] = str(self.base / "elsewhere")
        with self.assertRaises(SigningError) as cm:
            build_pin_adopter(
                env, expected_signer_id=SIGNER,
                expected_key_id="key-0123456789abcdef",
                authorisation_public_key=self.pub,
                signing_key_path=self.base / "snap.key",
                config=config)
        self.assertIn("AION_PIN_EVIDENCE_DIR", str(cm.exception))
        # (b) Signing key path inside the state dir -> loader
        # refusal (production env so the factory reaches the
        # loader).
        prod_env = {
            "AION_VERIFIER_KEY_PATH": str(self.base / "keys" / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.base / "registry"),
            "AION_VERIFIER_HOME": str(self.base / "verifier-home"),
            "AION_DEPLOYMENT_MODE": "production",
            "AION_ANCHOR_PATH": str(self.base / "anchors" / "s.json"),
            "AION_BUDGETS_ANCHOR_PATH":
                str(self.base / "anchors" / "b.json"),
            "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH":
                str(self.base / "anchors" / "c.json"),
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
        }
        with self.assertRaises(SigningError):
            build_pin_adopter(
                prod_env, expected_signer_id=SIGNER,
                expected_key_id="key-0123456789abcdef",
                authorisation_public_key=self.pub,
                signing_key_path=self.state_dir / "snap.key",
                config=config)
        # (c) Missing operator id.
        from dataclasses import replace as _replace
        no_operator = _replace(config, operator_id="")
        with self.assertRaises(SigningError) as cm:
            build_pin_adopter(
                prod_env, expected_signer_id=SIGNER,
                expected_key_id="key-0123456789abcdef",
                authorisation_public_key=self.pub,
                signing_key_path=self.base / "snap.key",
                config=no_operator)
        self.assertIn("OPERATOR", str(cm.exception))
        # (d) pin_adopter_config_from_env: complete + refusals.
        good = pin_adopter_config_from_env({
            "AION_PIN_DIR": str(self.pin_dir),
            "AION_PIN_SIGNING_KEY_PATH": str(self.base / "snap.key"),
            "AION_PIN_SIGNER_ID": SNAP_SIGNER,
            "AION_PIN_OPERATOR_ID": OPERATOR,
            "AION_PIN_EVIDENCE_DIR": str(self.evidence_dir)})
        self.assertEqual(good.pin_dir, self.pin_dir)
        with self.assertRaises(SigningError) as cm:
            pin_adopter_config_from_env({
                "AION_PIN_DIR": str(self.pin_dir)})
        self.assertIn("AION_PIN_", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
