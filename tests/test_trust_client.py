"""Tests for trust.client transport behaviour, using fixture
verifier processes via the client's module parameter (a legitimate
deployment knob — alternative verifier builds — not a test
backdoor; production code contains no fault injection).

Pins the failure-mode table's client half: every failure raises,
nothing defaults to acceptance, a killed/timed-out verifier
yields no partial result, and the client is key-free by
construction (meta-test).
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.client import VerifierClient
from trust.errors import (
    VerifierConfigError,
    VerifierError,
    VerifierProtocolError,
    VerifierTimeout,
    VerifierUnavailable,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TESTS_DIR = Path(__file__).resolve().parent


def fixture_client(module, **kw):
    kw.setdefault("pythonpath_extra", (TESTS_DIR,))
    return VerifierClient(module=module, **kw)


class TransportTests(unittest.TestCase):
    def test_timeout_kills_and_raises(self):
        client = fixture_client("fixtures.sleeper_verifier",
                                timeout_seconds=0.5)
        start = time.monotonic()
        with self.assertRaises(VerifierTimeout):
            client.gate({})
        self.assertLess(time.monotonic() - start, 5.0)

    def test_crash_is_unavailable(self):
        client = fixture_client("fixtures.crash_verifier")
        with self.assertRaises(VerifierUnavailable):
            client.gate({})

    def test_unhandled_exit_code_is_unavailable(self):
        client = fixture_client("fixtures.exit_verifier")
        with self.assertRaises(VerifierUnavailable):
            client.gate({})

    def test_garbage_output_is_protocol_error(self):
        client = fixture_client("fixtures.garbage_verifier")
        with self.assertRaises(VerifierProtocolError):
            client.gate({})

    def test_oversize_output_is_protocol_error(self):
        client = fixture_client("fixtures.oversize_verifier")
        with self.assertRaises(VerifierProtocolError):
            client.gate({})

    def test_wrong_echo_is_protocol_error(self):
        client = fixture_client("fixtures.wrong_echo_verifier")
        with self.assertRaises(VerifierProtocolError):
            client.gate({})

    def test_partial_output_then_death_is_an_error(self):
        client = fixture_client("fixtures.partial_verifier")
        with self.assertRaises(VerifierError):
            client.gate({})

    def test_stderr_flood_still_maps_the_error(self):
        client = fixture_client("fixtures.flood_verifier")
        with self.assertRaises(VerifierProtocolError) as ctx:
            client.gate({})
        self.assertIn("test_flood", str(ctx.exception))

    def test_missing_module_is_unavailable_not_raw(self):
        client = fixture_client("fixtures.does_not_exist")
        with self.assertRaises(VerifierUnavailable):
            client.gate({})

    def test_partial_output_is_config_error_family(self):
        # Exit 3 with an unparseable error document still maps to
        # the config family, never to a returned outcome.
        client = fixture_client("fixtures.partial_verifier")
        with self.assertRaises(VerifierConfigError):
            client.verify_envelope({"x": 1})


class NewModeSurfaceTests(unittest.TestCase):
    def test_attest_method_replaced(self):
        self.assertFalse(hasattr(VerifierClient, "attest"))
        self.assertTrue(hasattr(VerifierClient, "submit_claim"))
        self.assertTrue(hasattr(VerifierClient, "issue_attestation"))

    def test_submit_claim_transport_failure_raises(self):
        client = fixture_client("fixtures.garbage_verifier")
        with self.assertRaises(VerifierProtocolError):
            client.submit_claim({}, proposal_id="prop-1")

    def test_issue_attestation_transport_failure_raises(self):
        client = fixture_client("fixtures.crash_verifier")
        with self.assertRaises(VerifierUnavailable):
            client.issue_attestation(
                proposal_id="prop-1", baseline_eval={},
                candidate_eval={}, public_baseline_score=0.5,
                public_candidate_score=0.6)


_NO_MODE_VERIFIER = '''
"""Fake verifier: well-formed ok responses, NO deployment_mode."""
import json
import sys


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    doc = {"v": "trust-response/1",
           "request_id": request["request_id"],
           "mode": request["mode"], "status": "ok",
           "result": {"valid": True, "reasons": []}, "error": None}
    sys.stdout.write(json.dumps(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class ModePinTests(unittest.TestCase):
    """Client deployment-mode pin against the REAL verifier in
    research mode (fixture idiom mirrors
    tests/test_trust_mode_contract.py: fake registry + generated
    key in a temp verifier-home)."""

    ACTOR = "verifier-actor"
    SIGNER = "verifier-svc"
    ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
             ("sealed-2", "algebra", "3*3?", "9"),
             ("sealed-3", "geo", "pi~?", "3.14")]
    ANSWERS = [expected for *_x, expected in ITEMS]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in self.ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": self.SIGNER,
            "AION_VERIFIER_ACTOR_ID": self.ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def real_client(self, **kw):
        kw.setdefault("verifier_env", self.env)
        kw.setdefault("expected_signer_id", self.SIGNER)
        kw.setdefault("expected_key_id", self.key.key_id)
        return VerifierClient(**kw)

    def test_invalid_pin_refused_at_construction(self):
        with self.assertRaises(VerifierConfigError):
            VerifierClient(expected_deployment_mode="staging")

    def test_pinned_research_client_succeeds_and_observes(self):
        client = self.real_client(expected_deployment_mode="research")
        self.assertIsNone(client.observed_deployment_mode)
        record = client.sealed_eval(self.ANSWERS)
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(client.observed_deployment_mode, "research")

    def test_pinned_production_against_research_verifier_refused(self):
        client = self.real_client(
            expected_deployment_mode="production")
        with self.assertRaises(VerifierProtocolError):
            client.sealed_eval(self.ANSWERS)
        self.assertEqual(client.observed_deployment_mode, "research")

    def test_pinned_client_refuses_verifier_omitting_mode(self):
        fake_dir = Path(self.tmp.name) / "fake-verifier"
        fake_dir.mkdir()
        (fake_dir / "fake_no_mode_verifier.py").write_text(
            _NO_MODE_VERIFIER)
        client = VerifierClient(
            module="fake_no_mode_verifier",
            pythonpath_extra=(fake_dir,),
            expected_deployment_mode="research")
        with self.assertRaises(VerifierProtocolError):
            client.verify_envelope({"x": 1})
        self.assertIsNone(client.observed_deployment_mode)

    def test_unpinned_client_still_observes_mode(self):
        client = self.real_client()
        record = client.sealed_eval(self.ANSWERS)
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(client.observed_deployment_mode, "research")


class KeyFreeMetaTests(unittest.TestCase):
    def test_client_module_has_no_key_access(self):
        source = (Path(__file__).resolve().parents[1]
                  / "trust" / "client.py").read_text()
        self.assertNotIn("load_signing_key", source)
        self.assertNotIn("AION_VERIFIER_KEY_PATH", source)
        self.assertNotIn("sign_gate_decision", source)
        self.assertNotIn("make_signing_key", source)


if __name__ == "__main__":
    unittest.main()
