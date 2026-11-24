"""WS2 production-mode end-to-end tests (cycle 23, DESIGN-FINAL
R2): the first suite where the pin adopter is built via
``build_pin_adopter`` — i.e. its verifier client comes from
``trust.wiring.production_client`` — against a disposable
production verifier home provisioned by
``tests/cycle23_harness.py`` (research INIT bootstrap, then
INIT stripped and AION_DEPLOYMENT_MODE=production).

Claim scope (R2/B1): this proves production MODE under
same-user spawn on this VM. It does NOT prove production
DEPLOYMENT (no separate OS user exists here;
production_client(launch="wrapper") is refused by design).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cycle23_harness import (
    CAL, OPERATOR, SIGNER, SNAP_SIGNER, provision_production_home,
)
from core.loop import CoreLoop
from signing.pin_store import PinStore
from trust.anchoring import verify_anchor
from trust.errors import VerifierConfigError
from trust.ledger import CeremonyConsumptionLedger
from trust.pin_adoption import (
    PinAdopterConfig,
    PinAdoptionBurned,
    build_pin_adopter,
)
from trust.wiring import production_client

CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


class ProductionE2EFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = provision_production_home(base / "prod-home")
        # State side.
        self.state_dir = base / "state"
        self.loop = CoreLoop(self.state_dir)
        cal_dir = self.state_dir / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_path = cal_dir / "calibration.json"
        self.calibration_path.write_bytes(CAL)
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        self.adopter = self._build_adopter(self.home.env)
        self._item_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _build_adopter(self, env):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.home.evidence_dir)
        return build_pin_adopter(
            env, expected_signer_id=SIGNER,
            expected_key_id=self.home.verifier_key_id,
            authorisation_public_key=self.home.pub,
            signing_key_path=self.home.snapshot_key_path,
            config=config)

    def scan_items(self, n):
        start = self._item_seq
        items = [{"id": f"item-{start + i}",
                  "title": f"Production item {start + i}",
                  "leverage": float(n - i)}
                 for i in range(1, n + 1)]
        self._item_seq = start + n
        self.loop.scan(items)

    def bare_cycle(self):
        return self.loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)

    def consumption_entries(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return ledger.entries()

    def read_store(self):
        return self.store.read_all(
            signing_key=self.home.snapshot_key)


class ProductionE2ETests(ProductionE2EFixture):

    def test_genesis_dense_advance_and_burned_recovery(self):
        # Genesis: initial_anchor ceremony in production mode.
        self.scan_items(1)
        self.bare_cycle()
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "initial_anchor")
        self.assertEqual(result.pin["cycle_seq"], 1)
        self.assertEqual(len(self.consumption_entries()), 1)
        # The production verifier reports its mode on responses;
        # the client pins the expectation to "production".
        self.assertEqual(
            self.adopter._client.observed_deployment_mode,
            "production")
        # Dense advance: two cycles, pin moves, no new ceremony.
        self.scan_items(2)
        for expected_seq in (2, 3):
            self.bare_cycle()
            result = self.adopter.snapshot_and_adopt()
            self.assertEqual(result.outcome, "advanced")
            self.assertEqual(result.pin["cycle_seq"], expected_seq)
            self.assertIsNone(result.record)
        self.assertEqual(len(self.consumption_entries()), 1)
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 3)
        self.assertEqual(len(history), 1)
        # One burned_unadopted recovery, end to end: gap state,
        # a ceremony whose adoption fails after consumption
        # (pair discarded), then a fresh attempt that recovers
        # under reason burned_unadopted.
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        old_pin, _history = self.read_store()
        # Fix-seat correction (cycle 23): the fault seam must
        # patch the ADOPTER's own store — build_pin_adopter
        # constructs its own PinStore over pin_dir, a different
        # instance from the fixture's self.store, so patching
        # self.store.adopt never fired and the burn simulation
        # was inert (masked until now by the pin-namespace
        # failure at genesis). No assertion is changed; the
        # simulated adopt failure now actually happens, as the
        # test's comments always described.
        real_adopt = self.adopter._store.adopt
        state = {"armed": True}

        def flaky_adopt(new_pin, record=None, **kw):
            if record is not None and state["armed"]:
                state["armed"] = False
                raise OSError("simulated adopt failure")
            return real_adopt(new_pin, record, **kw)

        self.adopter._store.adopt = flaky_adopt
        try:
            with self.assertRaises(PinAdoptionBurned):
                self.adopter.snapshot_and_adopt()
            recovered = self.adopter.snapshot_and_adopt()
        finally:
            self.adopter._store.adopt = real_adopt
        self.assertEqual(recovered.outcome, "reanchored")
        self.assertEqual(recovered.record.reason, "burned_unadopted")
        self.assertEqual(recovered.pin["cycle_seq"], 5)
        # genesis + burn + recovery = 3 consumptions.
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[-1].get("consumption_kind"),
                         "recovery")
        self.assertEqual(entries[-1].get("recovery_depth"), 1)
        pin, history = self.read_store()
        self.assertEqual(pin, recovered.pin)
        self.assertEqual(len(history), 2)
        self.assertNotIn("lost_pin", [r.reason for r in history])
        # The consumption anchor is current against the journal
        # after production-mode consumptions.
        reasons = verify_anchor(
            CeremonyConsumptionLedger(self.home.verifier_home),
            self.home.anchor_paths["consumption"],
            kind="ceremony-consumption")
        self.assertEqual(reasons, ())

    def test_adopter_env_key_in_verifier_env_refused(self):
        # AION_PIN_* adopter variables must never enter the
        # verifier env mapping: production_client refuses any
        # non-allowlisted key before a client exists.
        env = dict(self.home.env)
        env["AION_PIN_DIR"] = str(self.pin_dir)
        with self.assertRaises(VerifierConfigError) as cm:
            production_client(
                env, expected_signer_id=SIGNER,
                expected_key_id=self.home.verifier_key_id,
                authorisation_public_key=self.home.pub)
        self.assertIn("AION_PIN_DIR", str(cm.exception))
        with self.assertRaises(VerifierConfigError):
            self._build_adopter(env)

    def test_init_flag_in_production_env_refused(self):
        # INIT ceremony flags are forbidden in production steady
        # state, for any of the anchor families.
        for flag in ("AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_INIT",
                     "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT",
                     "AION_CEREMONY_ISSUANCE_ANCHOR_INIT",
                     "AION_CEREMONY_SUPERSESSION_ANCHOR_INIT"):
            env = dict(self.home.env)
            env[flag] = "1"
            with self.assertRaises(VerifierConfigError) as cm:
                production_client(
                    env, expected_signer_id=SIGNER,
                    expected_key_id=self.home.verifier_key_id,
                    authorisation_public_key=self.home.pub)
            self.assertIn(flag, str(cm.exception))


class CeremonyPinNamespaceTests(unittest.TestCase):
    """Fix-seat tests (cycle 23): the ceremony pin check must
    use the ceremony public-key namespace (pub-<16 hex>), NOT
    the gate HMAC key pin (key-<16 hex>).

    A client pinned with the gate key- id AND a ceremony
    public key must ACCEPT a ceremony envelope issued under
    that public key — the production wiring mandates the
    key- form, so the old generic _check_pins refused every
    correctly issued production ceremony. An envelope under
    a DIFFERENT pub key id must be refused. The verifier is
    stubbed at the transport (_run) so these tests pin the
    CLIENT's pin logic in isolation; the production e2e above
    proves the same path end-to-end against the real verifier.
    """

    def _minted_envelope(self, signing_key):
        from signing.ceremony_authorisation import (
            ceremony_authorisation_envelope_to_dict,
            sign_ceremony_authorisation,
        )
        signed = sign_ceremony_authorisation(
            signing_key=signing_key, signer_id=SIGNER,
            operator_id=OPERATOR, ceremony_id="ceremony-pin-001",
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash="e" * 64, evidence_ref="case-file-1")
        return ceremony_authorisation_envelope_to_dict(signed)

    def _call(self, client, envelope):
        client._run = lambda mode, body: {
            "signed_authorisation": envelope}
        return client.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id="ceremony-pin-001",
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash="e" * 64, evidence_ref="case-file-1")

    def test_gate_pin_plus_ceremony_pub_accepts_envelope(self):
        import hashlib
        from signing.ceremony_authorisation import (
            _make_ceremony_signing_key,
            ceremony_public_key_for,
        )
        from trust.client import VerifierClient
        signing_key = _make_ceremony_signing_key(
            hashlib.sha256(b"cycle23 fix seat pin test").digest())
        pub = ceremony_public_key_for(signing_key)
        self.assertTrue(pub.key_id.startswith("pub-"))
        envelope = self._minted_envelope(signing_key)
        client = VerifierClient(
            verifier_env={}, expected_signer_id=SIGNER,
            # The GATE pin: key- namespace, deliberately NOT
            # the ceremony envelope's pub- id.
            expected_key_id="key-0123456789abcdef",
            authorisation_public_key=pub)
        returned = self._call(client, envelope)
        self.assertEqual(
            returned["authorisation_id"], envelope["authorisation_id"])

    def test_envelope_under_different_pub_key_refused(self):
        import hashlib
        from signing.ceremony_authorisation import (
            _make_ceremony_signing_key,
            ceremony_public_key_for,
        )
        from trust.client import VerifierClient
        from trust.errors import VerifierProtocolError
        signing_key = _make_ceremony_signing_key(
            hashlib.sha256(b"cycle23 fix seat pin test").digest())
        other_key = _make_ceremony_signing_key(
            hashlib.sha256(b"cycle23 fix seat other key").digest())
        other_pub = ceremony_public_key_for(other_key)
        self.assertNotEqual(other_pub.key_id, signing_key.key_id)
        envelope = self._minted_envelope(signing_key)
        client = VerifierClient(
            verifier_env={}, expected_signer_id=SIGNER,
            expected_key_id="key-0123456789abcdef",
            authorisation_public_key=other_pub)
        with self.assertRaises(VerifierProtocolError) as cm:
            self._call(client, envelope)
        self.assertIn("unexpected key", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
