"""Fail-closed deployment-mode contract + effective-mode
reporting — Trust Boundary v3.1, items 1 and 5-support.

The contract under test:

* AION_DEPLOYMENT_MODE is REQUIRED. Missing, empty, unknown or
  malformed (whitespace-padded, wrongly-cased) values refuse
  startup: exit 3, error code "deployment_mode_refused", and
  nothing is signed. There is no default mode — research is
  entered only when explicitly configured.
* Responses emitted AFTER config load succeeds carry the
  effective mode in an optional top-level "deployment_mode"
  field (ok results and mode-level refusals alike); pre-config
  responses (malformed requests, config refusals including the
  mode contract itself) carry NO such field — the absence is
  itself the signal.
* trust.protocol tolerates the field on decode, validates it
  when present, and keeps documents without it valid (older
  fixtures / fake verifiers).

Fixture discipline mirrors ProductionModeSpecTests /
tests/test_trust_verifier.py: fake registry + generated key in
a temp verifier-home, the real verifier invoked as a
subprocess.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust import protocol
from trust.ledger import SigningLedger

REPO = Path(__file__).resolve().parents[1]
ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
ANSWERS = [expected for *_x, expected in ITEMS]


class DeploymentModeContractTests(unittest.TestCase):
    """Direct verifier invocation against a temp-dir fixture.
    The base env deliberately carries NO AION_DEPLOYMENT_MODE:
    each test sets (or omits) it explicitly."""

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
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(REPO),
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers -----------------------------------------------------

    def run_verifier(self, env_override=None, *, body=None,
                     mode="sealed_eval"):
        env = dict(self.env)
        if env_override:
            env.update(env_override)
        if body is None:
            body = {"answers": ANSWERS}
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=env)
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        return result, request_id, doc

    def sign_count(self):
        ledger_file = self.home / "ledger" / "signing-ledger.json"
        if not ledger_file.exists():
            return 0
        return len([e for e in SigningLedger(self.home / "ledger")
                    .entries() if e["kind"] == "sign"])

    def assert_mode_refused(self, env_override, label):
        result, _rid, doc = self.run_verifier(env_override)
        self.assertEqual(
            result.returncode, 3,
            msg=f"{label}: rc={result.returncode} doc={doc!r} "
                f"stderr={result.stderr!r}")
        self.assertEqual(doc["status"], "error", msg=label)
        self.assertEqual(doc["error"]["code"],
                         "deployment_mode_refused", msg=label)
        self.assertIn("explicit", doc["error"]["detail"], msg=label)
        self.assertIn("fail-closed", doc["error"]["detail"], msg=label)
        # A config refusal is pre-config: no effective mode was
        # ever established, so the field must be absent.
        self.assertNotIn("deployment_mode", doc, msg=label)
        self.assertEqual(self.sign_count(), 0, msg=label)

    # -- seat-1: the fail-closed mode contract ------------------------

    def test_missing_mode_refused(self):
        self.assert_mode_refused({}, "missing mode")

    def test_empty_mode_refused(self):
        self.assert_mode_refused({"AION_DEPLOYMENT_MODE": ""},
                                 "empty mode")

    def test_unknown_mode_refused(self):
        self.assert_mode_refused({"AION_DEPLOYMENT_MODE": "staging"},
                                 "unknown mode")

    def test_whitespace_and_case_variants_refused(self):
        # No stripping, no case-folding: only the exact spellings
        # "production" / "research" are modes at all.
        for spelling in (" production", "production ", " research",
                         "Production", "RESEARCH", "Research"):
            with self.subTest(spelling=spelling):
                self.assert_mode_refused(
                    {"AION_DEPLOYMENT_MODE": spelling},
                    f"malformed mode {spelling!r}")

    def test_pre_config_refusal_carries_no_deployment_mode(self):
        _result, _rid, doc = self.run_verifier({})
        self.assertEqual(doc["error"]["code"],
                         "deployment_mode_refused")
        self.assertNotIn("deployment_mode", doc)

    def test_explicit_production_without_anchor_path_refused(self):
        # Existing production behaviour, unchanged: production
        # keeps its mandatory-anchoring gate (exit 3, nothing
        # signed). The refusal happens inside config load, so it
        # is a pre-config response and carries no mode field.
        result, _rid, doc = self.run_verifier(
            {"AION_DEPLOYMENT_MODE": "production"})
        self.assertEqual(result.returncode, 3,
                         msg=f"doc={doc!r}")
        self.assertEqual(doc["status"], "error")
        self.assertNotIn("deployment_mode", doc)
        self.assertEqual(self.sign_count(), 0)

    # -- seat-3: effective-mode reporting -----------------------------

    def test_explicit_research_runs_and_reports_mode(self):
        # Explicit "research" is the authorised path to research
        # mode: unanchored sealed_eval runs, and the ok response
        # reports the effective mode from inside the verifier.
        result, request_id, doc = self.run_verifier(
            {"AION_DEPLOYMENT_MODE": "research"})
        self.assertEqual(
            result.returncode, 0,
            msg=f"stderr={result.stderr.decode('utf-8', 'replace')}")
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["deployment_mode"], "research")
        self.assertEqual(
            doc["result"]["attestation"]["payload"]["score"], 1.0)
        self.assertEqual(self.sign_count(), 1)
        # The client-side decoder accepts the field too.
        decoded = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(decoded["deployment_mode"], "research")
        self.assertEqual(decoded["result"], doc["result"])

    def test_mode_level_refusal_after_config_carries_mode(self):
        # Wrong answer count in research mode is a mode-level
        # refusal (exit 2) raised AFTER config load succeeded, so
        # the error document reports the effective mode.
        result, _rid, doc = self.run_verifier(
            {"AION_DEPLOYMENT_MODE": "research"},
            body={"answers": ["4", "9"]})
        self.assertEqual(result.returncode, 2, msg=f"doc={doc!r}")
        self.assertEqual(doc["status"], "error")
        self.assertEqual(doc["error"]["code"],
                         "answer_count_mismatch")
        self.assertEqual(doc["deployment_mode"], "research")
        self.assertEqual(self.sign_count(), 0)


class ProtocolDeploymentModeTests(unittest.TestCase):
    """Unit tests for the optional deployment_mode field in
    trust.protocol: round-trip with and without it, and refusal
    of a bogus value on decode (and on encode)."""

    def test_roundtrip_without_field_stays_valid(self):
        raw = protocol.encode_response(
            "req-1", "sealed_eval", "ok", result={"x": 1})
        doc = protocol.decode_response(
            raw, expected_request_id="req-1",
            expected_mode="sealed_eval")
        self.assertNotIn("deployment_mode", doc)
        self.assertEqual(doc["result"], {"x": 1})

    def test_roundtrip_with_field(self):
        for mode_value in ("production", "research"):
            with self.subTest(deployment_mode=mode_value):
                raw = protocol.encode_response(
                    "req-1", "sealed_eval", "ok", result={"x": 1},
                    deployment_mode=mode_value)
                doc = protocol.decode_response(
                    raw, expected_request_id="req-1",
                    expected_mode="sealed_eval")
                self.assertEqual(doc["deployment_mode"], mode_value)

    def test_roundtrip_error_document_with_field(self):
        raw = protocol.encode_response(
            "req-1", "sealed_eval", "error",
            error=("answer_count_mismatch", "2 for 3"),
            deployment_mode="research")
        doc = protocol.decode_response(
            raw, expected_request_id="req-1",
            expected_mode="sealed_eval")
        self.assertEqual(doc["deployment_mode"], "research")
        self.assertEqual(doc["error"]["code"],
                         "answer_count_mismatch")

    def test_encode_refuses_bogus_field_value(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.encode_response(
                "req-1", "sealed_eval", "ok", result={},
                deployment_mode="staging")

    def test_decode_refuses_bogus_field_value(self):
        doc = {"v": protocol.RESPONSE_VERSION,
               "request_id": "req-1", "mode": "sealed_eval",
               "status": "ok", "result": {}, "error": None,
               "deployment_mode": "staging"}
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode_response(
                protocol.dumps(doc), expected_request_id="req-1",
                expected_mode="sealed_eval")

    def test_decode_still_refuses_other_unknown_keys(self):
        doc = {"v": protocol.RESPONSE_VERSION,
               "request_id": "req-1", "mode": "sealed_eval",
               "status": "ok", "result": {}, "error": None,
               "deployment_mode": "research", "surprise": 1}
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode_response(
                protocol.dumps(doc), expected_request_id="req-1",
                expected_mode="sealed_eval")


if __name__ == "__main__":
    unittest.main()
