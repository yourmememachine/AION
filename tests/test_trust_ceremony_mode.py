"""Tests for the verifier's ceremony_authorise mode (cycle 19) —
real subprocess, following tests/test_trust_verifier.py fixture
discipline: fake registry + generated key in a temp verifier
home; the builder side holds the key only to verify outcomes
test-side.

Covered: unconfigured refusal (research), production startup
refusal without the env var, malformed env grammar, malformed
bodies burn nothing, invented operator refused unsigned +
unledgered, invented operator LIST refused as a strict-key-set
violation, listed operator issued + ledgered in BOTH stores,
ceremony_id reuse, evidence reuse across events, identical
re-presentation, the dual-append burn (post-commit failure
leaves the pair burned), and the TTL hard cap.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict,
    verify_ceremony_authorisation,
)
from trust import protocol
from trust.client import VerifierClient
from trust.errors import VerifierConfigError, VerifierProtocolError
from trust.ledger import CeremonyAuthorisationLedger, SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-uma"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
EVIDENCE_HASH = "c" * 64
REPO = Path(__file__).resolve().parents[1]


class CeremonyFixture(unittest.TestCase):
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
        self.ledger_home = self.home / "ledger"
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.ledger_home),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATOR + ",operator-backup",
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, **over):
        body = {
            "operator_id": OPERATOR,
            "ceremony_id": "ceremony-2026-11-28-001",
            "reason": "chain_gap_recovery",
            "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
            "candidate": {"cycle_seq": 47, "payload_hash": CAND_HASH,
                          "signer_id": "snapshot-svc",
                          "key_id": "key-0123456789abcdef"},
            "evidence_hash": EVIDENCE_HASH,
            "evidence_ref": "case-file-1",
        }
        body.update(over)
        return body

    def authorise(self, **over):
        body = self.body(**over)
        return self.client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])

    def raw(self, body, *, env_over=None, mode="ceremony_authorise"):
        env = dict(self.env)
        if env_over:
            env.update(env_over)
        full_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full_env.update(env)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=full_env)
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc

    def error_code(self, doc):
        return doc["error"]["code"] if doc and doc.get("error") \
            else None

    def ceremony_entries(self):
        if not (self.ledger_home
                / "ceremony-authorisations.json").exists():
            return []
        return CeremonyAuthorisationLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()


class CeremonyModeTests(CeremonyFixture):
    def test_listed_operator_issued_and_ledgered_in_both_stores(self):
        envelope = self.authorise()
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=self.key,
                expected_signer_id=SIGNER), ())
        self.assertEqual(signed.operator_id, OPERATOR)
        ceremony = self.ceremony_entries()
        self.assertEqual(len(ceremony), 1)
        self.assertEqual(ceremony[0]["kind"], "authorise")
        self.assertEqual(ceremony[0]["ceremony_id"],
                         "ceremony-2026-11-28-001")
        self.assertEqual(ceremony[0]["evidence_hash"], EVIDENCE_HASH)
        self.assertEqual(ceremony[0]["authorisation_id"],
                         signed.authorisation_id)
        self.assertEqual(ceremony[0]["operator_id"], OPERATOR)
        signing = [e for e in self.signing_entries()
                   if e["format"] == "ceremony-authorisation"]
        self.assertEqual(len(signing), 1)
        self.assertEqual(signing[0]["kind"], "sign")
        self.assertEqual(signing[0]["decision_id"],
                         signed.authorisation_id)
        # ceremony_id is documented into the proposal_id column.
        self.assertEqual(signing[0]["proposal_id"],
                         "ceremony-2026-11-28-001")
        self.assertEqual(signing[0]["purpose"],
                         "pin-ceremony-authorisation")
        self.assertTrue(signing[0]["accepted"])

    def test_no_pin_authorisation_issued(self):
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            reason="initial_anchor", old_pin=None,
            evidence_hash="d" * 64)
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertIsNone(signed.old_pin)
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, signing_key=self.key,
                expected_signer_id=SIGNER,
                expected_old_pin=None), ())

    def test_unconfigured_research_refusal(self):
        env = dict(self.env)
        del env["AION_CEREMONY_OPERATORS"]
        code, doc = self.raw(self.body(), env_over={
            "AION_CEREMONY_OPERATORS": ""})
        # Empty value == absent for the loader.
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operators_unconfigured")
        client = VerifierClient(
            verifier_env=env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)
        with self.assertRaises(VerifierConfigError):
            client.ceremony_authorise(
                operator_id=OPERATOR, ceremony_id="ceremony-x",
                reason="initial_anchor", old_pin=None,
                candidate=self.body()["candidate"],
                evidence_hash=EVIDENCE_HASH, evidence_ref="ref")
        # Mode-scoped fail-closed: other modes still work in the
        # same deployment.
        record = client.sealed_eval(["4", "9", "3.14"])
        self.assertIn("payload_hash", record)

    def test_production_startup_refusal_without_operators(self):
        code, doc = self.raw(self.body(), env_over={
            "AION_DEPLOYMENT_MODE": "production",
            "AION_CEREMONY_OPERATORS": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_config_grammar_refusals(self):
        bad_values = [
            OPERATOR + "," + OPERATOR,               # duplicate
            OPERATOR + ", operator-backup",          # whitespace
            OPERATOR + ",,operator-backup",          # empty segment
            OPERATOR + ",",                          # trailing comma
            "Operator-Uma",                          # bad grammar
            ",".join(f"operator-{i}" for i in range(65)),  # > 64
        ]
        for value in bad_values:
            code, doc = self.raw(self.body(), env_over={
                "AION_CEREMONY_OPERATORS": value})
            self.assertEqual(code, 3, msg=value)
            self.assertEqual(self.error_code(doc),
                             "verifier_misconfigured", msg=value)
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])

    def test_invented_operator_list_refused_as_malformed(self):
        body = self.body()
        body["authorised_operators"] = ["operator-mallory"]
        code, doc = self.raw(body)
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc), "malformed_request")
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])

    def test_invented_operator_refused_unsigned_unledgered(self):
        code, doc = self.raw(self.body(operator_id="operator-mallory"))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operator_not_authorised")
        self.assertIsNone(doc["result"])
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])
        with self.assertRaises(VerifierConfigError):
            self.authorise(operator_id="operator-mallory")

    def test_malformed_bodies_burn_nothing(self):
        bad_bodies = [
            self.body(evidence_hash=CAND_HASH),       # == candidate
            self.body(evidence_hash=OLD_HASH),        # == old pin
            self.body(candidate={"cycle_seq": 42,
                                 "payload_hash": CAND_HASH,
                                 "signer_id": "snapshot-svc",
                                 "key_id": "key-0123456789abcdef"}),
            self.body(reason="lost_pin"),             # pin + no-pin
            self.body(reason="chain_gap_recovery", old_pin=None),
            self.body(ceremony_id="-leading-dash"),
            self.body(evidence_hash="xyz"),
            self.body(evidence_ref=""),
        ]
        for body in bad_bodies:
            code, doc = self.raw(body)
            self.assertEqual(code, 2, msg=str(body))
            self.assertEqual(self.error_code(doc),
                             "malformed_request", msg=str(body))
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])

    def test_ceremony_id_reuse_refused(self):
        self.authorise()
        code, doc = self.raw(self.body(
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash="f" * 64))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)

    def test_evidence_reuse_across_events_refused(self):
        self.authorise()
        code, doc = self.raw(self.body(
            ceremony_id="ceremony-2026-11-28-777",
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"}))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)

    def test_identical_representation_refused(self):
        self.authorise()
        code, doc = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)
        self.assertEqual(
            len([e for e in self.signing_entries()
                 if e["format"] == "ceremony-authorisation"]), 1)

    def test_random_evidence_is_attributable_and_single_use(self):
        # Pins the honest limit: a random hex64 from a LISTED
        # operator IS issued — attributable, event-bound,
        # single-use — not artefact-verified.
        import secrets
        random_hash = secrets.token_hex(32)
        envelope = self.authorise(evidence_hash=random_hash)
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(signed.evidence_hash, random_hash)
        code, doc = self.raw(self.body(
            ceremony_id="ceremony-2026-11-28-003",
            evidence_hash=random_hash))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_reused")

    def test_dual_append_burn_on_post_commit_failure(self):
        # Corrupt the SIGNING ledger before the request: the
        # ceremony-journal append (commit point) lands, the
        # signing-ledger append fails, the envelope is withheld
        # with ledger_failed — and the pair stays burned, so a
        # re-presentation is refused at the anti-replay scan.
        self.ledger_home.mkdir(exist_ok=True)
        (self.ledger_home / "signing-ledger.json").write_text(
            "this is not a journal")
        code, doc = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertIsNone(doc["result"])
        self.assertEqual(len(self.ceremony_entries()), 1)
        code, doc = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")

    def test_ttl_hard_cap_over_configured_ttl(self):
        client = VerifierClient(
            verifier_env=dict(self.env,
                              AION_VERIFIER_TTL_SECONDS="172800"),
            expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)
        body = self.body()
        envelope = client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        window = (datetime.fromisoformat(signed.expires_at)
                  - datetime.fromisoformat(signed.signed_at))
        self.assertEqual(window.total_seconds(), 900)


FAKE_ECHO_MODULE = '''
import json
import os
import sys

from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_to_dict,
    sign_ceremony_authorisation,
)
from signing.gate_decision import load_signing_key

doc = json.loads(sys.stdin.read())
body = doc["body"]
key = load_signing_key(os.environ["AION_VERIFIER_KEY_PATH"])
candidate = dict(body["candidate"])
candidate["cycle_seq"] = candidate["cycle_seq"] + 5
signed = sign_ceremony_authorisation(
    signing_key=key,
    signer_id=os.environ["AION_VERIFIER_SIGNER_ID"],
    operator_id=body["operator_id"],
    ceremony_id=body["ceremony_id"], reason=body["reason"],
    old_pin=body["old_pin"], candidate=candidate,
    evidence_hash=body["evidence_hash"],
    evidence_ref=body["evidence_ref"])
resp = {"v": "trust-response/1", "request_id": doc["request_id"],
        "mode": doc["mode"], "status": "ok",
        "result": {"signed_authorisation":
                   ceremony_authorisation_envelope_to_dict(signed)},
        "error": None}
sys.stdout.write(json.dumps(resp))
'''


class CeremonyClientEchoTests(CeremonyFixture):
    def test_client_refuses_envelope_bound_to_another_event(self):
        fake_dir = Path(self.tmp.name) / "fake"
        fake_dir.mkdir()
        (fake_dir / "fake_verifier_echo.py").write_text(
            FAKE_ECHO_MODULE)
        client = VerifierClient(
            module="fake_verifier_echo", verifier_env=self.env,
            expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id,
            pythonpath_extra=(str(fake_dir),))
        body = self.body()
        with self.assertRaises(VerifierProtocolError) as ctx:
            client.ceremony_authorise(
                operator_id=body["operator_id"],
                ceremony_id=body["ceremony_id"],
                reason=body["reason"], old_pin=body["old_pin"],
                candidate=body["candidate"],
                evidence_hash=body["evidence_hash"],
                evidence_ref=body["evidence_ref"])
        self.assertIn("different event", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
