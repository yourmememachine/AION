"""Tests for the out-of-process verifier (trust.verifier_main +
trust.client against the REAL verifier) — cycle 7/8.

Fixture discipline: fake registry + generated key in a temp
verifier-home, fake-repo/verifier-home split throughout; the
builder side (this test process) holds the key only to VERIFY
outcomes test-side, exactly as a key-holding consumer would.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file, verify_signed_decision
from trust.attestation import answers_hash_for, verify_eval_attestation
from trust.client import VerifierClient
from trust.errors import (
    VerifierConfigError,
    VerifierProtocolError,
)
from trust.ledger import SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]


def recent(minutes=5):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes)).isoformat()


class VerifierFixture(unittest.TestCase):
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
        self.manifest_hash = registry.sealed_manifest_hash(ACTOR)
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)

    def tearDown(self):
        self.tmp.cleanup()

    def gate_body(self, **over):
        body = {
            "proposal_id": "prop-v1",
            "builder_ids": ["seat-9", "seat-10", "seat-11"],
            "reviewer_ids": ["seat-1", "seat-2", "seat-3", "seat-4",
                             "seat-5", "seat-6"],
            "baseline_public": {"bench-a": 0.5},
            "candidate_public": {"bench-a": 0.6},
            "baseline_sealed": {"bench-s": 0.5},
            "candidate_sealed": {"bench-s": 0.7},
            "capability_baseline": {"cap-a": 0.5},
            "capability_candidate": {"cap-a": 0.5},
            "attestation": {
                "verifier_id": "seat-3", "decision": "approve",
                "sealed_hash": self.manifest_hash,
                "reward_hacking_checked": True,
                "evidence_ref": "sealed-run-1",
                "attested_at": recent()},
            "changed_paths": None,
            "verifier_note": "",
        }
        body.update(over)
        return body

    # -- evidence-derived flow helpers --------------------------------
    # The attester is the same service (same key, same ledger home,
    # same registry) configured under the seat-3 identity: seat-3
    # is a reviewer, not a builder and not the gate signer, which
    # is exactly the separation the gate's signer-conflict checks
    # demand. sealed_eval runs under the attester identity too, so
    # the eval records' signer matches the attestation issuer.

    def attester(self):
        return VerifierClient(
            verifier_env=dict(self.env, AION_VERIFIER_SIGNER_ID="seat-3"),
            expected_signer_id="seat-3",
            expected_key_id=self.key.key_id)

    def eval_records(self, baseline_answers, candidate_answers,
                     *, proposal_id="prop-v1"):
        # Budget scoping (Trust Boundary v2): baseline and
        # candidate evals are distinct query scopes of one
        # proposal — an unchanged system legitimately produces a
        # candidate transcript identical to its baseline, which
        # must not read as a replay probe. The per-identity cap
        # remains the hard bound across scopes.
        attester = self.attester()
        return (attester.sealed_eval(
                    baseline_answers,
                    proposal_id=f"{proposal_id}:baseline"),
                attester.sealed_eval(
                    candidate_answers,
                    proposal_id=f"{proposal_id}:candidate"))

    def derived_attestation(self, *, baseline_answers=None,
                            candidate_answers=None,
                            public_before=0.5, public_after=0.6,
                            proposal_id="prop-v1"):
        """Run sealed_eval twice (baseline + candidate answers),
        then issue_attestation. Returns (signed_attestation_dict,
        baseline_record, candidate_record). Defaults: baseline
        gets one of three answers right (score 1/3), candidate
        gets all three (score 1.0) — a genuine sealed gain."""
        if baseline_answers is None:
            baseline_answers = ["4", "wrong", "wrong"]
        if candidate_answers is None:
            candidate_answers = [e for *_x, e in ITEMS]
        baseline, candidate = self.eval_records(
            baseline_answers, candidate_answers,
            proposal_id=proposal_id)
        signed = self.attester().issue_attestation(
            proposal_id=proposal_id, baseline_eval=baseline,
            candidate_eval=candidate,
            public_baseline_score=public_before,
            public_candidate_score=public_after)
        return signed, baseline, candidate

    def accepted_body(self, **over):
        """A gate body on the full signed path: a verifier-derived
        signed attestation plus the eval_evidence it was derived
        from, with the sealed maps set to the derived scores."""
        body = self.gate_body(**over)
        signed, baseline, candidate = self.derived_attestation(
            proposal_id=body["proposal_id"])
        body["attestation"] = signed["attestation"]
        body["signed_attestation"] = signed
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        body["baseline_sealed"] = {"sealed": baseline["payload"]["score"]}
        body["candidate_sealed"] = {"sealed": candidate["payload"]["score"]}
        return body

    def ship_signed_attestation(self, attestation, *, manifest_hash,
                                proposal_id="prop-v1"):
        """Test-side signing for the SHIP flow only. issue_attestation
        deliberately carries no build-manifest binding (its strict
        body has no manifest_hash), so a ship attestation bound to a
        build manifest is constructed here directly with the fixture
        key — the same way test_trust_shipcheck builds its fixtures.
        The gate must still verify the envelope it is presented."""
        from signing.attestation import (
            attestation_envelope_to_dict, sign_attestation)
        from eval.gate import VerifierAttestation
        att = VerifierAttestation(**attestation)
        return attestation_envelope_to_dict(sign_attestation(
            att, signing_key=self.key, signer_id="seat-3",
            proposal_id=proposal_id, manifest_hash=manifest_hash))

    def ship_accepted_body(self, manifest_hash):
        """An accepted-path ship gate body: derived eval evidence
        plus a ship attestation bound to the build manifest."""
        body = self.gate_body(manifest_hash=manifest_hash)
        signed, baseline, candidate = self.derived_attestation(
            proposal_id=body["proposal_id"])
        body["attestation"] = signed["attestation"]
        body["signed_attestation"] = self.ship_signed_attestation(
            signed["attestation"], manifest_hash=manifest_hash,
            proposal_id=body["proposal_id"])
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        body["baseline_sealed"] = {"sealed": baseline["payload"]["score"]}
        body["candidate_sealed"] = {"sealed": candidate["payload"]["score"]}
        return body


class GateModeTests(VerifierFixture):
    def test_gate_accept_end_to_end(self):
        outcome = self.client.gate(self.accepted_body())
        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.manifest_hash, self.manifest_hash)
        reasons = verify_signed_decision(
            outcome.envelope, signing_key=self.key,
            expected_gate_inputs_hash=outcome.gate_inputs_hash)
        self.assertEqual(reasons, ())
        self.assertTrue(outcome.envelope.attestation_hash)
        ledger = SigningLedger(self.home / "ledger")
        self.assertTrue(ledger.has_envelope(
            outcome.envelope.decision_id))

    def test_gate_signed_rejection_on_regression(self):
        outcome = self.client.gate(self.gate_body(
            candidate_sealed={"bench-s": 0.4}))
        self.assertFalse(outcome.accepted)
        self.assertIn("regression",
                      outcome.envelope.decision.reasons)
        self.assertEqual(verify_signed_decision(
            outcome.envelope, signing_key=self.key,
            expected_gate_inputs_hash=outcome.gate_inputs_hash), ())

    def test_gate_signed_rejection_on_protected_path(self):
        outcome = self.client.gate(self.gate_body(
            changed_paths=["eval/gate.py"]))
        self.assertFalse(outcome.accepted)
        self.assertTrue(
            outcome.envelope.decision.protected_violations)

    def test_gate_stale_attestation_is_signed_rejection(self):
        body = self.gate_body()
        body["attestation"] = dict(body["attestation"],
                                   sealed_hash="0" * 64)
        outcome = self.client.gate(body)
        self.assertFalse(outcome.accepted)
        self.assertIn("sealed_hash_mismatch",
                      outcome.envelope.decision.reasons)

    def test_gate_missing_attestation_is_signed_rejection(self):
        outcome = self.client.gate(self.gate_body(attestation=None))
        self.assertFalse(outcome.accepted)
        self.assertIn("missing_attestation",
                      outcome.envelope.decision.reasons)

    def test_gate_malformed_inputs_raise_not_sign(self):
        body = self.gate_body()
        body["reviewer_ids"] = ["seat-9"]  # overlaps a builder
        with self.assertRaises(VerifierProtocolError):
            self.client.gate(body)

    def test_gate_ship_purpose_binds_manifest(self):
        env = dict(self.env, AION_VERIFIER_PURPOSE="ship")
        client = VerifierClient(verifier_env=env,
                                expected_signer_id=SIGNER,
                                expected_key_id=self.key.key_id)
        outcome = client.gate(self.ship_accepted_body("d" * 64))
        self.assertEqual(outcome.envelope.purpose, "ship")
        self.assertEqual(outcome.gate_inputs_hash, "d" * 64)
        self.assertEqual(outcome.envelope.gate_inputs_hash, "d" * 64)

    def test_signer_conflict_refused(self):
        env = dict(self.env, AION_VERIFIER_SIGNER_ID="seat-9")
        client = VerifierClient(verifier_env=env)
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())


class SealedEvalTests(VerifierFixture):
    def test_sealed_eval_happy_and_verifiable(self):
        answers = [expected for *_x, expected in ITEMS]
        record = self.client.sealed_eval(answers)
        self.assertEqual(
            verify_eval_attestation(record, signing_key=self.key), ())
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(record["payload"]["manifest_hash"],
                         self.manifest_hash)
        self.assertEqual(record["payload"]["answers_hash"],
                         answers_hash_for(answers))

    def test_sealed_eval_wrong_answers_score_zero(self):
        record = self.client.sealed_eval(["x", "y", "z"])
        self.assertEqual(record["payload"]["score"], 0.0)
        self.assertEqual(
            verify_eval_attestation(record, signing_key=self.key), ())

    def test_sealed_eval_count_mismatch_is_protocol_error(self):
        with self.assertRaises(VerifierProtocolError):
            self.client.sealed_eval(["4", "9"])

    def test_attestation_transplant_fails(self):
        answers = [expected for *_x, expected in ITEMS]
        record = self.client.sealed_eval(answers)
        reasons = verify_eval_attestation(
            record, signing_key=self.key,
            expected_manifest_hash="e" * 64)
        self.assertIn("manifest_mismatch", reasons)
        reasons = verify_eval_attestation(
            record, signing_key=self.key,
            expected_answers_hash=answers_hash_for(["4", "9", "no"]))
        self.assertIn("answers_mismatch", reasons)

    def test_tampered_registry_refused(self):
        registry_file = next(self.registry_dir.glob("*.json"))
        data = json.loads(registry_file.read_text())
        data["sealed_items"][0]["expected"] = "hacked"
        registry_file.write_text(json.dumps(data))
        with self.assertRaises(VerifierConfigError):
            self.client.sealed_eval(
                [expected for *_x, expected in ITEMS])


class VerifyEnvelopeModeTests(VerifierFixture):
    def test_verify_envelope_roundtrip(self):
        from signing import envelope_to_dict
        outcome = self.client.gate(self.accepted_body())
        verdict = self.client.verify_envelope(
            envelope_to_dict(outcome.envelope),
            {"proposal_id": "prop-v1",
             "gate_inputs_hash": outcome.gate_inputs_hash})
        self.assertTrue(verdict.valid)
        verdict = self.client.verify_envelope(
            envelope_to_dict(outcome.envelope),
            {"proposal_id": "prop-other"})
        self.assertFalse(verdict.valid)
        self.assertIn("proposal_mismatch", verdict.reasons)

    def test_verify_envelope_malformed_is_verdict_not_error(self):
        verdict = self.client.verify_envelope({"x": 1})
        self.assertFalse(verdict.valid)
        self.assertEqual(verdict.reasons, ("malformed_envelope",))

    def test_verify_envelope_malformed_expected_is_protocol_error(self):
        from signing import envelope_to_dict
        outcome = self.client.gate(self.accepted_body())
        with self.assertRaises(VerifierProtocolError):
            self.client.verify_envelope(
                envelope_to_dict(outcome.envelope),
                {"entry_content_hash": "not-hex"})


class KeyConfigTests(VerifierFixture):
    def _client_with(self, **env_over):
        env = dict(self.env)
        env.update(env_over)
        return VerifierClient(verifier_env=env)

    def test_missing_key_file(self):
        client = self._client_with(
            AION_VERIFIER_KEY_PATH=str(self.home / "nope.key"))
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_missing_env(self):
        client = VerifierClient(verifier_env={})
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_world_readable_key_refused(self):
        (self.home / "gate.key").chmod(0o644)
        with self.assertRaises(VerifierConfigError):
            self.client.gate(self.gate_body())

    def test_known_test_key_refused(self):
        path = self.home / "test.key"
        path.write_text(bytes(range(32, 64)).hex() + "\n")
        path.chmod(0o600)
        client = self._client_with(AION_VERIFIER_KEY_PATH=str(path))
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())


class ProtocolFuzzTests(VerifierFixture):
    def _raw(self, raw: bytes):
        env = dict(self.env)
        full_env = {"PATH": "/usr/bin:/bin",
                    "PYTHONPATH": str(
                        Path(__file__).resolve().parents[1])}
        full_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(Path(__file__).resolve().parents[1]), env=full_env)

    def test_garbage_stdin_exit_2(self):
        result = self._raw(b"this is not json")
        self.assertEqual(result.returncode, 2)

    def test_duplicate_keys_exit_2(self):
        result = self._raw(
            b'{"v":"trust-request/1","v":"trust-request/1",'
            b'"request_id":"req-1","mode":"gate","body":{}}')
        self.assertEqual(result.returncode, 2)

    def test_request_supplied_signer_id_exit_2(self):
        body = self.gate_body()
        body["signer_id"] = "attacker"
        doc = {"v": "trust-request/1", "request_id": "req-1",
               "mode": "gate", "body": body}
        result = self._raw(json.dumps(doc).encode())
        self.assertEqual(result.returncode, 2)

    def test_oversize_stdin_exit_2(self):
        result = self._raw(b" " * ((1 << 20) + 10))
        self.assertEqual(result.returncode, 2)

    def test_deeply_nested_json_exit_2_not_crash(self):
        depth = 20000
        raw = (b'{"v":"trust-request/1","request_id":"req-1",'
               b'"mode":"gate","body":'
               + b"[" * depth + b"]" * depth + b"}")
        result = self._raw(raw)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"Traceback", result.stdout)


class FixPinTests(VerifierFixture):
    """Pins for the cycle-8 war-room fixes on the verifier."""

    def test_gate_empty_registry_refused(self):
        client = VerifierClient(verifier_env=dict(
            self.env,
            AION_REGISTRY_DIR=str(Path(self.tmp.name) / "fresh-reg")))
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_accept_without_signed_attestation_refused(self):
        # Eval evidence present and approving, but no signed
        # attestation envelope: attestation_required still bites.
        body = self.accepted_body()
        del body["signed_attestation"]
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.gate(body)
        self.assertIn("attestation_required", str(ctx.exception))

    def test_signer_among_reviewers_refused(self):
        client = VerifierClient(verifier_env=dict(
            self.env, AION_VERIFIER_SIGNER_ID="seat-3"))
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_ill_typed_attestation_is_protocol_error(self):
        body = self.gate_body()
        body["attestation"] = dict(body["attestation"],
                                   decision="maybe")
        with self.assertRaises(VerifierProtocolError):
            self.client.gate(body)

    def test_noncanonical_changed_paths_are_protocol_errors(self):
        for spelling in ("../eval/gate.py", "/eval/gate.py",
                         "a/../../eval/gate.py", "EVAL/gate.py",
                         "x/../core/loop.py"):
            with self.assertRaises(VerifierProtocolError,
                                   msg=spelling):
                self.client.gate(self.gate_body(
                    changed_paths=[spelling]))

    def test_relative_key_path_refused(self):
        client = VerifierClient(verifier_env=dict(
            self.env, AION_VERIFIER_KEY_PATH="relative.key"))
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_missing_verifier_home_refused(self):
        env = dict(self.env)
        del env["AION_VERIFIER_HOME"]
        client = VerifierClient(verifier_env=env)
        with self.assertRaises(VerifierConfigError):
            client.gate(self.gate_body())

    def test_sealed_eval_is_ledgered(self):
        self.client.sealed_eval(
            [expected for *_x, expected in ITEMS])
        ledger = SigningLedger(self.home / "ledger")
        formats = [e["format"] for e in ledger.entries()
                   if e["kind"] == "sign"]
        self.assertIn("sealed-eval", formats)

    def test_ship_attestation_bound_to_other_artifact_refused(self):
        # The presented signed attestation must be bound to THIS
        # ship's manifest at issuance, not merely to the proposal.
        env = dict(self.env, AION_VERIFIER_PURPOSE="ship")
        client = VerifierClient(verifier_env=env,
                                expected_signer_id=SIGNER,
                                expected_key_id=self.key.key_id)
        body = self.ship_accepted_body("d" * 64)
        body["signed_attestation"] = self.ship_signed_attestation(
            body["attestation"], manifest_hash="e" * 64)
        with self.assertRaises(VerifierProtocolError):
            client.gate(body)

    def test_issue_attestation_issued_and_ledgered(self):
        from signing.attestation import (
            attestation_envelope_from_dict, verify_signed_attestation)
        signed, _b, _c = self.derived_attestation()
        satt = attestation_envelope_from_dict(signed)
        self.assertEqual(verify_signed_attestation(
            satt, signing_key=self.key), ())
        self.assertEqual(satt.attestation.decision, "approve")
        self.assertEqual(satt.attestation.verifier_id, "seat-3")
        self.assertTrue(satt.attestation.reward_hacking_checked)
        self.assertEqual(satt.attestation.sealed_hash,
                         self.manifest_hash)
        ledger = SigningLedger(self.home / "ledger")
        formats = [e["format"] for e in ledger.entries()
                   if e["kind"] == "sign"]
        self.assertIn("verifier-attestation", formats)


class SubmitClaimTests(VerifierFixture):
    """(a) A fabricated approval claim yields NO signature."""

    def fabricated_claim(self):
        return {"verifier_id": "seat-3", "decision": "approve",
                "sealed_hash": self.manifest_hash,
                "reward_hacking_checked": True,
                "evidence_ref": "fabricated-run",
                "attested_at": recent()}

    def test_fabricated_approval_claim_yields_no_signature(self):
        result = self.client.submit_claim(
            self.fabricated_claim(), proposal_id="prop-v1")
        self.assertEqual(set(result), {"claim_id", "claim_hash"})
        self.assertEqual(result["claim_id"], result["claim_hash"])
        ledger = SigningLedger(self.home / "ledger")
        entries = ledger.entries()
        claims = [e for e in entries if e["kind"] == "claim"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["format"], "claim")
        self.assertEqual(claims[0]["purpose"], "claim")
        self.assertFalse(claims[0]["accepted"])
        self.assertEqual(claims[0]["decision_id"], result["claim_id"])
        self.assertEqual(claims[0]["payload_hash"],
                         result["claim_hash"])
        # No signature anywhere: not one sign entry of any format.
        self.assertEqual(
            [e for e in entries if e["kind"] == "sign"], [])
        self.assertFalse(ledger.has_envelope(result["claim_id"]))

    def test_claim_with_ill_formed_attestation_is_protocol_error(self):
        claim = self.fabricated_claim()
        claim["decision"] = "maybe"
        with self.assertRaises(VerifierProtocolError):
            self.client.submit_claim(claim, proposal_id="prop-v1")

    def test_attest_mode_no_longer_exists(self):
        from trust import protocol as trust_protocol
        self.assertNotIn("attest", trust_protocol.MODES)
        self.assertIn("submit_claim", trust_protocol.MODES)
        self.assertIn("issue_attestation", trust_protocol.MODES)
        self.assertFalse(hasattr(self.client, "attest"))


class IssueAttestationTests(VerifierFixture):
    """(b), (c), (e): the attestation is derived, never selected."""

    def test_derived_attestation_binds_evidence(self):
        signed, baseline, candidate = self.derived_attestation()
        att = signed["attestation"]
        self.assertEqual(att["decision"], "approve")
        self.assertEqual(
            att["evidence_ref"],
            f"eval:{baseline['payload_hash']}:"
            f"{candidate['payload_hash']}")
        self.assertEqual(att["sealed_hash"], self.manifest_hash)
        self.assertTrue(att["reward_hacking_checked"])

    def test_caller_selected_approval_fields_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"],
            [e for *_x, e in ITEMS])
        for extra in ({"decision": "approve"},
                      {"reward_hacking_checked": True}):
            body = {"proposal_id": "prop-v1",
                    "baseline_eval": baseline,
                    "candidate_eval": candidate,
                    "public_baseline_score": 0.5,
                    "public_candidate_score": 0.6}
            body.update(extra)
            with self.assertRaises(VerifierProtocolError, msg=extra):
                self.attester()._run("issue_attestation", body)

    def test_public_score_out_of_range_is_protocol_error(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        with self.assertRaises(VerifierProtocolError):
            self.attester().issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=candidate, public_baseline_score=0.5,
                public_candidate_score=1.5)

    def test_tampered_eval_record_refused_unsigned(self):
        import copy
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        tampered = copy.deepcopy(candidate)
        tampered["signature"] = "0" * 64
        ledger = SigningLedger(self.home / "ledger")
        signs_before = [e for e in ledger.entries()
                        if e["kind"] == "sign"
                        and e["format"] == "verifier-attestation"]
        with self.assertRaises(VerifierConfigError):
            self.attester().issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=tampered, public_baseline_score=0.5,
                public_candidate_score=0.6)
        ledger = SigningLedger(self.home / "ledger")
        signs_after = [e for e in ledger.entries()
                       if e["kind"] == "sign"
                       and e["format"] == "verifier-attestation"]
        self.assertEqual(signs_before, signs_after)

    def test_unledgered_eval_record_refused(self):
        from trust.attestation import sign_eval_attestation
        baseline, _candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        # A record MACed with the real key (the fixture holds it
        # test-side) but never issued through sealed_eval, so it
        # has no ledger entry: MAC-valid is not enough.
        forged = sign_eval_attestation(
            {"set": "sealed", "version": 1, "n": 3, "correct": 3,
             "score": 1.0, "manifest_hash": self.manifest_hash,
             "evaluated_at": recent()},
            signing_key=self.key, signer_id="seat-3", actor=ACTOR,
            registry_digest="b" * 64, answers_hash="c" * 64)
        self.assertEqual(
            verify_eval_attestation(forged, signing_key=self.key), ())
        with self.assertRaises(VerifierConfigError) as ctx:
            self.attester().issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=forged, public_baseline_score=0.5,
                public_candidate_score=0.6)
        self.assertIn("eval_record_not_ledgered", str(ctx.exception))

    def test_mismatched_manifest_records_refused(self):
        other_dir = Path(self.tmp.name) / "registry2"
        other = EvalRegistry(other_dir)
        other_items = [("other-1", "algebra", "5+5?", "10"),
                       ("other-2", "algebra", "2*6?", "12"),
                       ("other-3", "geo", "pi~?", "3.14")]
        for item_id, domain, prompt, expected in other_items:
            other.add_sealed_item(item_id, domain, prompt, expected,
                                  "test-actor")
        other_client = VerifierClient(
            verifier_env=dict(self.env,
                              AION_VERIFIER_SIGNER_ID="seat-3",
                              AION_REGISTRY_DIR=str(other_dir)),
            expected_signer_id="seat-3",
            expected_key_id=self.key.key_id)
        candidate_other = other_client.sealed_eval(
            [e for *_x, e in other_items])
        baseline, _c = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        with self.assertRaises(VerifierConfigError):
            self.attester().issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=candidate_other,
                public_baseline_score=0.5, public_candidate_score=0.6)

    def test_sealed_regression_derives_reject(self):
        # (e) The claim asked for approval (submitted as a claim
        # first); the derived attestation still says reject when
        # the sealed score regresses.
        self.client.submit_claim(
            {"verifier_id": "seat-3", "decision": "approve",
             "sealed_hash": self.manifest_hash,
             "reward_hacking_checked": True,
             "evidence_ref": "please-approve",
             "attested_at": recent()}, proposal_id="prop-v1")
        signed, _b, _c = self.derived_attestation(
            baseline_answers=[e for *_x, e in ITEMS],
            candidate_answers=["wrong", "wrong", "wrong"])
        self.assertEqual(signed["attestation"]["decision"], "reject")

    def test_gaming_gap_derives_reject(self):
        # Public score leaps while the sealed score is flat:
        # assess_gap flags gaming, so the derived decision rejects
        # even though the sealed score did not regress. The two
        # transcripts differ at every position (both score 1/3):
        # under identity-scoped budget detection a byte-identical
        # candidate transcript would be a replay and a
        # near-identical one a probe — neither is what this test
        # is about.
        signed, _b, _c = self.derived_attestation(
            baseline_answers=["4", "wrong", "wrong"],
            candidate_answers=["nope", "9", "nope-2"],
            public_before=0.5, public_after=0.9)
        self.assertEqual(signed["attestation"]["decision"], "reject")

    def test_self_paired_evidence_refused_at_issue_attestation(self):
        # HIGH-5a: one ledgered record presented as BOTH baseline
        # and candidate must not derive any attestation — not
        # even a signed reject.
        attester = self.attester()
        record = attester.sealed_eval(
            ["4", "wrong", "wrong"], proposal_id="prop-v1:baseline")
        ledger = SigningLedger(self.home / "ledger")
        signs_before = [e for e in ledger.entries()
                        if e["kind"] == "sign"
                        and e["format"] == "verifier-attestation"]
        with self.assertRaises(VerifierConfigError) as ctx:
            attester.issue_attestation(
                proposal_id="prop-v1", baseline_eval=record,
                candidate_eval=record, public_baseline_score=0.5,
                public_candidate_score=0.5)
        self.assertIn("eval_evidence_self_paired", str(ctx.exception))
        ledger = SigningLedger(self.home / "ledger")
        signs_after = [e for e in ledger.entries()
                       if e["kind"] == "sign"
                       and e["format"] == "verifier-attestation"]
        self.assertEqual(signs_before, signs_after)

    def test_out_of_order_evidence_refused_at_issue_attestation(self):
        # HIGH-5a: candidate ledgered BEFORE baseline — the pair
        # is presented in the right slots, but ledger order says
        # the candidate came first, so it cannot be evidence of
        # an improvement over that baseline.
        attester = self.attester()
        candidate = attester.sealed_eval(
            [e for *_x, e in ITEMS], proposal_id="prop-v1:candidate")
        baseline = attester.sealed_eval(
            ["4", "wrong", "wrong"], proposal_id="prop-v1:baseline")
        with self.assertRaises(VerifierConfigError) as ctx:
            attester.issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=candidate, public_baseline_score=0.5,
                public_candidate_score=0.6)
        self.assertIn("eval_evidence_out_of_order", str(ctx.exception))

    def test_cross_proposal_reissuance_refused(self):
        # LOW-3: records scored under prop-other's budget scopes
        # cannot be re-issued as an attestation for prop-v1.
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS],
            proposal_id="prop-other")
        with self.assertRaises(VerifierConfigError) as ctx:
            self.attester().issue_attestation(
                proposal_id="prop-v1", baseline_eval=baseline,
                candidate_eval=candidate, public_baseline_score=0.5,
                public_candidate_score=0.6)
        self.assertIn("eval_evidence_scope_mismatch",
                      str(ctx.exception))


class GateEvidenceTests(VerifierFixture):
    """(d) No accept without eval_evidence; derived scores govern."""

    def test_accept_without_eval_evidence_refused(self):
        body = self.accepted_body()
        del body["eval_evidence"]
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.gate(body)
        self.assertIn("evidence_required", str(ctx.exception))

    def test_derived_scores_govern_over_lying_caller_maps(self):
        # Records show a sealed REGRESSION (1.0 -> 0.0). The
        # caller maps lie (0.5 -> 0.9, would accept) and the
        # presented attestation approves (test-side signed, as
        # shipcheck fixtures are). The signed decision must be a
        # rejection driven by the DERIVED scores.
        baseline, candidate = self.eval_records(
            [e for *_x, e in ITEMS], ["wrong", "wrong", "wrong"])
        attestation = {
            "verifier_id": "seat-3", "decision": "approve",
            "sealed_hash": self.manifest_hash,
            "reward_hacking_checked": True,
            "evidence_ref": (f"eval:{baseline['payload_hash']}:"
                             f"{candidate['payload_hash']}"),
            "attested_at": recent()}
        body = self.gate_body(
            baseline_sealed={"sealed": 0.5},
            candidate_sealed={"sealed": 0.9},
            attestation=attestation)
        body["signed_attestation"] = self.ship_signed_attestation(
            attestation, manifest_hash="")
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        outcome = self.client.gate(body)
        self.assertFalse(outcome.accepted)
        self.assertIn("regression", outcome.envelope.decision.reasons)
        self.assertEqual(verify_signed_decision(
            outcome.envelope, signing_key=self.key,
            expected_gate_inputs_hash=outcome.gate_inputs_hash), ())

    def test_evidence_ref_mismatch_is_malformed(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        attestation = {
            "verifier_id": "seat-3", "decision": "approve",
            "sealed_hash": self.manifest_hash,
            "reward_hacking_checked": True,
            "evidence_ref": "eval:" + "a" * 64 + ":" + "b" * 64,
            "attested_at": recent()}
        body = self.gate_body(attestation=attestation)
        body["signed_attestation"] = self.ship_signed_attestation(
            attestation, manifest_hash="")
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        with self.assertRaises(VerifierProtocolError):
            self.client.gate(body)

    def test_tampered_eval_evidence_refused_unsigned(self):
        import copy
        body = self.accepted_body()
        body["eval_evidence"] = copy.deepcopy(body["eval_evidence"])
        body["eval_evidence"]["candidate"]["signature"] = "0" * 64
        with self.assertRaises(VerifierConfigError):
            self.client.gate(body)

    def _gate_body_with_evidence(self, baseline, candidate):
        attestation = {
            "verifier_id": "seat-3", "decision": "approve",
            "sealed_hash": self.manifest_hash,
            "reward_hacking_checked": True,
            "evidence_ref": (f"eval:{baseline['payload_hash']}:"
                             f"{candidate['payload_hash']}"),
            "attested_at": recent()}
        body = self.gate_body(attestation=attestation)
        body["signed_attestation"] = self.ship_signed_attestation(
            attestation, manifest_hash="")
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        return body

    def test_self_paired_evidence_refused_at_gate(self):
        # HIGH-5a at the gate: the same record as baseline AND
        # candidate is an unsigned refusal, never a signed gate
        # decision.
        baseline, _candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS])
        body = self._gate_body_with_evidence(baseline, baseline)
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.gate(body)
        self.assertIn("eval_evidence_self_paired", str(ctx.exception))

    def test_out_of_order_evidence_refused_at_gate(self):
        # HIGH-5a at the gate: candidate ledgered before baseline.
        attester = self.attester()
        candidate = attester.sealed_eval(
            [e for *_x, e in ITEMS], proposal_id="prop-v1:candidate")
        baseline = attester.sealed_eval(
            ["4", "wrong", "wrong"], proposal_id="prop-v1:baseline")
        body = self._gate_body_with_evidence(baseline, candidate)
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.gate(body)
        self.assertIn("eval_evidence_out_of_order", str(ctx.exception))

    def test_cross_scope_evidence_refused_at_gate(self):
        # rev-r2 verification minor: the gate checks the records'
        # proposal scope roots directly. Records scored under
        # prop-other's budget scope, presented at a prop-v1 gate
        # with a (test-side fabricated) prop-v1 attestation naming
        # them, refuse on scope grounds — defence in depth behind
        # the attestation's own proposal binding.
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], [e for *_x, e in ITEMS],
            proposal_id="prop-other")
        body = self._gate_body_with_evidence(baseline, candidate)
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.gate(body)
        self.assertIn("eval_evidence_scope_mismatch",
                      str(ctx.exception))

    def test_gate_inputs_hash_binds_evidence_records(self):
        # Two evidence pairs with IDENTICAL scores (baseline 1/3,
        # candidate 2/3 either way) but different transcripts —
        # hence different payload hashes — must yield different
        # gate_inputs_hashes. (Rewritten in the Trust Boundary v2
        # cycle: the original used a 1.0 candidate score, whose
        # transcript is unique, so the second pair was a budget
        # replay of the first; and the attestation is bound to
        # the gate's proposal, so both pairs must belong to
        # prop-v1 — distinct transcripts in each budget scope is
        # the only honest way to submit two pairs.)
        def make_body(baseline_answers, candidate_answers):
            signed, baseline, candidate = self.derived_attestation(
                baseline_answers=baseline_answers,
                candidate_answers=candidate_answers)
            body = self.gate_body()
            body["attestation"] = signed["attestation"]
            body["signed_attestation"] = signed
            body["eval_evidence"] = {"baseline": baseline,
                                     "candidate": candidate}
            body["baseline_sealed"] = {
                "sealed": baseline["payload"]["score"]}
            body["candidate_sealed"] = {
                "sealed": candidate["payload"]["score"]}
            return body

        # Second-pair transcripts are chosen far from every
        # first-pair transcript (and the pair's own baseline):
        # budget detection is identity-scoped, so a transcript
        # within two differing positions of a prior one counts
        # as a probe, and the third probe trips the latch. The
        # second candidate is the pair's single tolerated extra
        # probe (two differing positions vs the first candidate).
        first = self.client.gate(make_body(
            ["4", "wrong", "wrong"], ["4", "9", "wrong"]))
        second = self.client.gate(make_body(
            ["nope-a", "nope-b", "3.14"], ["nope-d", "9", "3.14"]))
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertNotEqual(first.gate_inputs_hash,
                            second.gate_inputs_hash)


if __name__ == "__main__":
    unittest.main()
