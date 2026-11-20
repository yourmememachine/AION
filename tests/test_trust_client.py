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
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
