"""Serialisation ambiguity battery — Trust Boundary v3, item 6
(external seats seat-gpt F8 / seat-gemini parser point).

POD E split:
  seat-13 — WIRE layer: raw bytes into the real verifier
            subprocess, plus trust.protocol.strict_loads directly.
  seat-14 — MODE bodies: bodies through the real verifier's five
            modes, plus the equivalence controls.
  seat-15 — ARTEFACT dicts: library level (eval attestation
            records, gate-decision envelopes, attestation
            envelopes) with no subprocess.

Refusal, for this battery, means exactly one of: verifier exit 2
or 3 with an error document, a verify_* reasons tuple that is
non-empty, or a SigningError / ProtocolError exception — AND, for
every verifier case, NO new "sign" entry in the signing ledger
(snapshot before / after). A signed gate REJECTION is a signature,
so it is never counted as a refusal here.

Equivalence controls are the deliberate exception, and are
labelled as such in their class: two spellings of the SAME value
(int 1 vs float 1.0, 0.1 vs 1e-1, reordered payload keys, an int
score whose value equals correct/n) must produce the SAME
outcome — canonicalisation normalises value spellings, it does
not (and must not) invent a semantic difference. Those controls
may sign, exactly as the equivalent honest request would.

Finding summary (this cycle): no layer accepted an ambiguous
spelling with a different security outcome. strict_loads already
rejected duplicate keys / non-finite numbers; the battery proves
that strictness reaches the wire end-to-end (nested objects
included) and that the mode key-set checks and the artefact
from_dict / verify type checks do not reopen it. In particular
the eval-attestation int-score case pins the actual behaviour:
verify_eval_attestation REBUILDS the payload with score =
correct/n (a float), so a presented score of int 1 for a 1.0
record verifies — the numeric spelling of the score in the
presented dict is not part of the signed artefact, only its
value is, because the canonical rebuilt payload is identical.
"""

import copy
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import GateDecision, Regression, VerifierAttestation
from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.attestation import (
    attestation_envelope_from_dict,
    attestation_envelope_from_json,
    attestation_envelope_to_dict,
    sign_attestation,
    verify_signed_attestation,
)
from signing.gate_decision import (
    envelope_from_dict,
    envelope_to_dict,
    sign_gate_decision,
    verify_signed_decision,
)
from trust import protocol
from trust.attestation import (
    answers_hash_for,
    sign_eval_attestation,
    verify_eval_attestation,
)
from trust.client import VerifierClient
from trust.ledger import SigningLedger
from trust.manifest import ManifestError
from trust.release import ReleaseRecord, release_from_json

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
ANSWERS = [expected for *_x, expected in ITEMS]
REPO = Path(__file__).resolve().parents[1]
# Cyrillic small letter o (U+043E): a homoglyph for ASCII "o".
HOMOGLYPH_ID = "pr\u043ep-v1"
NON_ASCII_DIGIT_TS = "\u0662\u0660\u0662\u0666-11-20T12:15:00+00:00"


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

    # -- helpers -----------------------------------------------------

    def sign_count(self):
        ledger_file = self.home / "ledger" / "signing-ledger.json"
        if not ledger_file.exists():
            return 0
        return len([e for e in SigningLedger(self.home / "ledger")
                    .entries() if e["kind"] == "sign"])

    def run_raw(self, raw, env_override=None):
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        env.update(self.env)
        if env_override:
            env.update(env_override)
        return subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=env)

    def run_body(self, mode, body, env_override=None):
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        return self.run_raw(raw, env_override), request_id

    def assert_refusal_no_new_sign(self, result, before, msg=""):
        """Exit 2/3, an error document on stdout, ledger unmoved."""
        self.assertIn(result.returncode, (2, 3),
                      msg=f"{msg} rc={result.returncode} "
                          f"out={result.stdout!r}")
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error", msg=msg)
        self.assertIsInstance(doc["error"]["code"], str)
        self.assertTrue(doc["error"]["code"], msg=msg)
        self.assertEqual(self.sign_count(), before, msg=msg)

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

    def attester(self):
        return VerifierClient(
            verifier_env=dict(self.env,
                              AION_VERIFIER_SIGNER_ID="seat-3"),
            expected_signer_id="seat-3",
            expected_key_id=self.key.key_id)

    def derived_attestation(self, *, baseline_answers,
                            candidate_answers, public_before,
                            public_after, proposal_id="prop-v1"):
        attester = self.attester()
        baseline = attester.sealed_eval(
            baseline_answers, proposal_id=f"{proposal_id}:baseline")
        candidate = attester.sealed_eval(
            candidate_answers, proposal_id=f"{proposal_id}:candidate")
        signed = attester.issue_attestation(
            proposal_id=proposal_id, baseline_eval=baseline,
            candidate_eval=candidate,
            public_baseline_score=public_before,
            public_candidate_score=public_after)
        return signed, baseline, candidate


# ---------------------------------------------------------------------
# seat-13 — wire layer
# ---------------------------------------------------------------------

class WireStrictLoadsDirectTests(unittest.TestCase):
    """protocol.strict_loads alone: every ambiguous spelling is a
    ProtocolError before any mode code runs."""

    def assert_protocol_error(self, raw):
        with self.assertRaises(protocol.ProtocolError, msg=repr(raw[:60])):
            protocol.strict_loads(raw, cap=protocol.MAX_REQUEST_BYTES,
                                  what="request")

    def test_valid_document_is_the_control(self):
        doc = protocol.strict_loads(b'{"a": 1}', cap=1024, what="x")
        self.assertEqual(doc, {"a": 1})

    def test_duplicate_keys_at_every_depth(self):
        self.assert_protocol_error(b'{"a": 1, "a": 2}')
        self.assert_protocol_error(b'{"body": {"a": 1, "a": 2}}')
        self.assert_protocol_error(
            b'{"body": {"attestation": {"decision": "approve",'
            b' "decision": "reject"}}}')

    def test_unicode_escape_duplicate_is_post_decode_duplicate(self):
        # "\u0061nswers" decodes to "answers": the pair hook sees
        # the DECODED keys, so escape spelling cannot smuggle a
        # second copy of a known field past duplicate detection.
        self.assert_protocol_error(
            b'{"answers": ["4"], "\\u0061nswers": ["9"]}')

    def test_non_finite_spellings(self):
        for raw in (b'{"a": NaN}', b'{"a": Infinity}',
                    b'{"a": -Infinity}', b'{"a": 1e999}',
                    b'{"a": -1e999}'):
            self.assert_protocol_error(raw)

    def test_concatenated_and_trailing_data(self):
        self.assert_protocol_error(b'{"a": 1} {"b": 2}')
        self.assert_protocol_error(b'{"a": 1} garbage')
        self.assert_protocol_error(b'{"a": 1}\n{"b": 2}\n')

    def test_bom_and_invalid_utf8(self):
        self.assert_protocol_error(b'\xef\xbb\xbf{"a": 1}')
        self.assert_protocol_error(b'\xff\xfe{"a": 1}')
        self.assert_protocol_error(b'{"a": "\xff"}')

    def test_extreme_nesting_is_protocol_error_not_crash(self):
        depth = 20000
        self.assert_protocol_error(b"[" * depth + b"]" * depth)


class WireVerifierTests(VerifierFixture):
    """The same spellings as raw bytes into the REAL verifier
    subprocess: exit 2, error document, no new signature."""

    def valid_raw(self, mode="sealed_eval", body=None):
        if body is None:
            body = {"answers": ANSWERS}
        request_id = protocol.new_request_id()
        return protocol.encode_request(request_id, mode, body), request_id

    def check(self, raw, label):
        before = self.sign_count()
        result = self.run_raw(raw)
        self.assert_refusal_no_new_sign(result, before, msg=label)
        self.assertEqual(result.returncode, 2, msg=label)

    def test_duplicate_key_top_level(self):
        raw, _rid = self.valid_raw("gate", self.gate_body())
        dup = raw.replace(b'"mode":"gate"', b'"mode":"gate","mode":"gate"')
        self.assertNotEqual(dup, raw)
        self.check(dup, "top-level duplicate")

    def test_duplicate_key_inside_body(self):
        raw, _rid = self.valid_raw()
        dup = raw.replace(b'"answers":', b'"answers":["x"],"answers":', 1)
        self.assertNotEqual(dup, raw)
        self.check(dup, "body duplicate")

    def test_duplicate_key_inside_nested_attestation(self):
        raw, _rid = self.valid_raw("gate", self.gate_body())
        dup = raw.replace(b'"decision":"approve"',
                          b'"decision":"reject","decision":"approve"')
        self.assertNotEqual(dup, raw)
        self.check(dup, "nested attestation duplicate")

    def test_unicode_escape_duplicate_via_wire(self):
        raw = (b'{"v":"trust-request/1","request_id":"req-esc1",'
               b'"mode":"sealed_eval","body":{"answers":["4","9","3.14"],'
               b'"\\u0061nswers":["x","y","z"]}}')
        self.check(raw, "unicode-escape duplicate")

    def test_non_finite_literals_via_wire(self):
        raw, _rid = self.valid_raw("gate", self.gate_body())
        self.assertIn(b'"bench-a":0.5', raw)
        for spelling in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            mutated = raw.replace(b'"bench-a":0.5',
                                  b'"bench-a":' + spelling, 1)
            self.check(mutated, f"non-finite {spelling!r}")

    def test_two_concatenated_documents(self):
        raw, _rid = self.valid_raw()
        self.check(raw + raw, "concatenated documents")

    def test_trailing_garbage(self):
        raw, _rid = self.valid_raw()
        self.check(raw + b"garbage", "trailing garbage")

    def test_utf8_bom_prefix(self):
        raw, _rid = self.valid_raw()
        self.check(b"\xef\xbb\xbf" + raw, "BOM prefix")

    def test_invalid_utf8_bytes(self):
        raw, _rid = self.valid_raw()
        mutated = raw.replace(b'"4"', b'"\xff"', 1)
        self.assertNotEqual(mutated, raw)
        self.check(mutated, "invalid UTF-8")

    def test_extreme_nesting_depth(self):
        depth = 20000
        raw = (b'{"v":"trust-request/1","request_id":"req-deep",'
               b'"mode":"sealed_eval","body":{"answers":'
               + b"[" * depth + b"]" * depth + b"}}")
        before = self.sign_count()
        result = self.run_raw(raw)
        self.assert_refusal_no_new_sign(result, before, msg="deep nesting")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"Traceback", result.stdout)


# ---------------------------------------------------------------------
# seat-14 — mode bodies via the verifier
# ---------------------------------------------------------------------

class ModeBodyRefusalTests(VerifierFixture):

    def check_body(self, mode, body, label, env_override=None):
        before = self.sign_count()
        result, _rid = self.run_body(mode, body, env_override)
        self.assert_refusal_no_new_sign(result, before, msg=label)
        return result

    def test_unknown_extra_field_in_each_of_the_five_modes(self):
        attestation = self.gate_body()["attestation"]
        cases = [
            ("gate", self.gate_body(extra_field=1)),
            ("sealed_eval", {"answers": ANSWERS, "extra_field": 1}),
            ("verify_envelope", {"envelope": {}, "expected": {},
                                 "extra_field": 1}),
            ("submit_claim", {"attestation": attestation,
                              "proposal_id": "prop-v1",
                              "extra_field": 1}),
            ("issue_attestation",
             {"proposal_id": "prop-v1", "baseline_eval": {},
              "candidate_eval": {}, "public_baseline_score": 0.5,
              "public_candidate_score": 0.6, "extra_field": 1}),
        ]
        for mode, body in cases:
            with self.subTest(mode=mode):
                self.check_body(mode, body, f"extra field in {mode}")

    def test_unknown_field_inside_nested_attestation_object(self):
        body = self.gate_body()
        body["attestation"] = dict(body["attestation"], extra_field=1)
        self.check_body("gate", body, "attestation extra field")

    def test_manifest_hash_null_on_ship_config_refuses(self):
        # null is not "missing", and neither is acceptable on a
        # ship-purpose config: both refuse, nothing signs.
        self.check_body(
            "gate", self.gate_body(manifest_hash=None),
            "manifest_hash null (ship)",
            env_override={"AION_VERIFIER_PURPOSE": "ship"})

    def test_manifest_hash_missing_on_ship_config_refuses(self):
        self.check_body(
            "gate", self.gate_body(), "manifest_hash missing (ship)",
            env_override={"AION_VERIFIER_PURPOSE": "ship"})

    def test_signed_attestation_null_refuses(self):
        self.check_body("gate", self.gate_body(signed_attestation=None),
                        "signed_attestation null")

    def test_gate_public_scores_bool_and_string_refuse(self):
        for bad in (True, "0.5"):
            with self.subTest(bad=bad):
                self.check_body(
                    "gate",
                    self.gate_body(baseline_public={"bench-a": bad}),
                    f"gate public score {bad!r}")

    def test_issue_public_scores_bool_and_string_refuse(self):
        # _public_score runs before the eval records are verified,
        # so dummy records isolate the score spelling itself.
        for bad in (True, "0.5"):
            with self.subTest(bad=bad):
                self.check_body(
                    "issue_attestation",
                    {"proposal_id": "prop-v1", "baseline_eval": {},
                     "candidate_eval": {},
                     "public_baseline_score": bad,
                     "public_candidate_score": 0.6},
                    f"issue public score {bad!r}")

    def test_answers_with_bool_number_or_null_refuse(self):
        for bad in (True, 1, 0.5, None):
            with self.subTest(bad=bad):
                self.check_body(
                    "sealed_eval",
                    {"answers": [bad, "9", "3.14"]},
                    f"answer entry {bad!r}")

    def test_proposal_id_spellings_refuse_at_gate_and_submit_claim(self):
        attestation = self.gate_body()["attestation"]
        for bad_id in ("Prop-V1", HOMOGLYPH_ID, "p" * 65):
            with self.subTest(bad_id=bad_id):
                self.check_body(
                    "gate", self.gate_body(proposal_id=bad_id),
                    f"gate proposal_id {bad_id!r}")
                self.check_body(
                    "submit_claim",
                    {"attestation": attestation, "proposal_id": bad_id},
                    f"submit_claim proposal_id {bad_id!r}")

    def test_expected_purpose_null_in_verify_envelope_refuses(self):
        # Already guarded in verifier_main; pinned here: null does
        # not mean "any purpose".
        self.check_body(
            "verify_envelope",
            {"envelope": {}, "expected": {"purpose": None}},
            "expected.purpose null")

    def test_verify_envelope_reports_tampered_accepted_as_verdict(self):
        # Artefact crossover: a gate envelope dict whose
        # "accepted" was rewritten to int 1 reaches verify_envelope
        # and comes back as a non-empty-reasons verdict (the
        # refusal form for this mode), never valid.
        outcome = self.client.gate(self.gate_body(
            candidate_sealed={"bench-s": 0.4}))
        from signing import envelope_to_dict
        data = envelope_to_dict(outcome.envelope)
        data["decision"]["accepted"] = 1
        before = self.sign_count()
        verdict = self.client.verify_envelope(data)
        self.assertFalse(verdict.valid)
        self.assertTrue(verdict.reasons)
        self.assertEqual(self.sign_count(), before)


class SealedEvalScopeSpellingTests(VerifierFixture):
    """Sealed-eval scope (proposal_id) spellings: the scope is a
    budget / evidence binding, not free text, so it must obey the
    id grammar (Trust Boundary v3 fix round: verifier_main
    validates it before any budget is recorded or any evaluation
    runs). Every case is a refusal through the REAL verifier:
    exit 2/3 with an error document, NOTHING signed, and no
    budget recorded — the budgets store bytes are snapshotted
    around each case, because a refusal that still burned budget
    would be a silent denial-of-service against the scope."""

    def budgets_snapshot(self):
        budgets_file = self.home / "ledger" / "budgets.json"
        if not budgets_file.exists():
            return None
        return budgets_file.read_bytes()

    def test_sealed_eval_proposal_id_spellings_refuse(self):
        for bad_id in ("prop\nFORGED", HOMOGLYPH_ID, "X:baseline",
                       "PROP-V1", "p" * 65):
            with self.subTest(bad_id=bad_id):
                before_sign = self.sign_count()
                before_budgets = self.budgets_snapshot()
                result, _rid = self.run_body(
                    "sealed_eval",
                    {"answers": ANSWERS, "proposal_id": bad_id})
                self.assert_refusal_no_new_sign(
                    result, before_sign,
                    msg=f"sealed_eval proposal_id {bad_id!r}")
                self.assertEqual(self.budgets_snapshot(),
                                 before_budgets,
                                 msg=f"budget recorded for {bad_id!r}")


class EquivalenceControlTests(VerifierFixture):
    """Controls, NOT refusals: same value, different spelling —
    the derived outcome must be identical. These may sign, as the
    equivalent honest request would. Transcripts for the
    issue_attestation pairs are pairwise distance-3 apart so the
    budget store's adaptive-probe detection (identity-scoped)
    does not conflate an equivalence run with a replay probe."""

    def test_missing_signed_attestation_is_not_null(self):
        # Control for the null case above: a gate body with NO
        # signed_attestation key at all is well-formed — on a
        # regression it earns a signed rejection. Missing != null.
        outcome = self.client.gate(self.gate_body(
            candidate_sealed={"bench-s": 0.4}))
        self.assertFalse(outcome.accepted)
        self.assertIn("regression", outcome.envelope.decision.reasons)

    def test_gate_public_score_int_1_matches_float_1_0(self):
        def run(value):
            outcome = self.client.gate(self.gate_body(
                baseline_public={"bench-a": value},
                candidate_sealed={"bench-s": 0.4}))
            return outcome.envelope.decision
        as_int = run(1)
        as_float = run(1.0)
        self.assertFalse(as_int.accepted)
        self.assertEqual(as_int.accepted, as_float.accepted)
        self.assertEqual(as_int.reasons, as_float.reasons)
        self.assertEqual(as_int.regressions, as_float.regressions)
        self.assertEqual(as_int.regressions[0].baseline, 1.0)

    def test_gate_public_score_0_1_matches_1e_minus_1_raw_wire(self):
        # Raw spellings: the client's encoder would render both
        # floats as "0.1", so this pair goes in as literal bytes.
        # candidate_public is set below the spelled baseline so
        # the public regression row carries the spelled value.
        body = self.gate_body(candidate_public={"bench-a": 0.05},
                              candidate_sealed={"bench-s": 0.4})
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, "gate", body)
        self.assertIn(b'"bench-a":0.5', raw)
        decisions = []
        for spelling in (b"0.1", b"1e-1"):
            mutated = raw.replace(b'"bench-a":0.5',
                                  b'"bench-a":' + spelling, 1)
            # A fresh request id per run, matching the spelling run.
            doc = protocol.decode_request(mutated)
            result = self.run_raw(protocol.encode_request(
                protocol.new_request_id(), "gate", doc["body"]))
            self.assertEqual(result.returncode, 0)
            resp = protocol.strict_loads(
                result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
                what="response")
            self.assertEqual(resp["status"], "ok")
            signed = envelope_from_dict(resp["result"]["envelope"])
            decisions.append(signed.decision)
        self.assertFalse(decisions[0].accepted)
        self.assertEqual(decisions[0].reasons, decisions[1].reasons)
        self.assertEqual(decisions[0].regressions,
                         decisions[1].regressions)
        self.assertEqual(decisions[0].regressions[0].baseline, 0.1)

    def test_issue_public_score_int_1_matches_float_1_0(self):
        signed_a, base_a, cand_a = self.derived_attestation(
            baseline_answers=["a1", "a2", "a3"],
            candidate_answers=["4", "x2", "x3"],
            public_before=1, public_after=1)
        signed_b, base_b, cand_b = self.derived_attestation(
            baseline_answers=["b1", "b2", "b3"],
            candidate_answers=["y1", "9", "y3"],
            public_before=1.0, public_after=1.0)
        self.assertEqual(base_a["payload"]["score"],
                         base_b["payload"]["score"])
        self.assertEqual(cand_a["payload"]["score"],
                         cand_b["payload"]["score"])
        self.assertEqual(signed_a["attestation"]["decision"],
                         signed_b["attestation"]["decision"])
        self.assertEqual(signed_a["attestation"]["decision"], "approve")

    def test_issue_public_score_0_1_matches_1e_minus_1(self):
        signed_c, _bc, _cc = self.derived_attestation(
            baseline_answers=["c1", "c2", "c3"],
            candidate_answers=["z1", "z2", "3.14"],
            public_before=0.1, public_after=0.1)
        signed_d, _bd, _dd = self.derived_attestation(
            baseline_answers=["d1", "d2", "d3"],
            candidate_answers=["4", "w2", "w3"],
            public_before=1e-1, public_after=1e-1)
        self.assertEqual(signed_c["attestation"]["decision"],
                         signed_d["attestation"]["decision"])
        self.assertEqual(signed_c["attestation"]["decision"], "approve")


# ---------------------------------------------------------------------
# seat-15 — artefact dicts, library level
# ---------------------------------------------------------------------

KEY15 = make_signing_key(bytes(range(32, 64)))
NOW15 = "2026-11-20T12:00:00+00:00"
LATER15 = "2026-11-20T12:05:00+00:00"


def _eval_record():
    report = {"set": "sealed", "version": 3, "n": 2, "correct": 2,
              "score": 1.0, "manifest_hash": "a" * 64,
              "evaluated_at": NOW15}
    return sign_eval_attestation(
        report, signing_key=KEY15, signer_id="verifier-svc",
        actor="verifier-actor", registry_digest="b" * 64,
        answers_hash="c" * 64, now=NOW15)


def _gate_signed():
    decision = GateDecision(
        accepted=False, proposal_id="prop-1", reasons=("regression",),
        regressions=(Regression("sealed", "bench-s", 1.0, 0.4, -0.6),),
        forgetting_failures=(), verifier_id="seat-3",
        evaluated_at=NOW15, verifier_note="")
    return sign_gate_decision(decision, signing_key=KEY15,
                              signer_id="gate-signer", now=NOW15)


def _att_signed():
    attestation = VerifierAttestation(
        verifier_id="seat-3", decision="approve", sealed_hash="b" * 64,
        reward_hacking_checked=True, evidence_ref="sealed-run-1",
        attested_at="2026-11-20T11:00:00+00:00")
    return sign_attestation(attestation, signing_key=KEY15,
                            signer_id="seat-3", proposal_id="prop-1",
                            now=NOW15)


class EvalAttestationArtefactTests(unittest.TestCase):

    def test_payload_key_reorder_still_verifies_control(self):
        # Canonicalisation stability (control, not a refusal):
        # dict insertion order is not part of the signed artefact.
        record = _eval_record()
        reordered = {
            "signature": record["signature"],
            "payload_hash": record["payload_hash"],
            "payload": dict(reversed(list(record["payload"].items()))),
        }
        self.assertEqual(verify_eval_attestation(
            reordered, signing_key=KEY15, now=LATER15), ())

    def test_score_int_1_matches_float_1_0_control(self):
        # Pinned actual behaviour (control): the verifier REBUILDS
        # the payload with score = correct/n, so int 1 and float
        # 1.0 canonicalise to the identical signed payload and the
        # record verifies. The spelling is not part of the signed
        # artefact; the VALUE is — a different value (next test)
        # is a refusal.
        record = _eval_record()
        record["payload"]["score"] = 1
        self.assertEqual(verify_eval_attestation(
            record, signing_key=KEY15, now=LATER15), ())

    def test_score_wrong_type_or_value_refuses(self):
        for bad in ("1.0", True, None, 0.5):
            with self.subTest(bad=bad):
                record = _eval_record()
                record["payload"]["score"] = bad
                reasons = verify_eval_attestation(
                    record, signing_key=KEY15, now=LATER15)
                self.assertTrue(reasons)
                self.assertIn("malformed_payload", reasons)

    def test_unknown_keys_refuse(self):
        record = _eval_record()
        record["extra"] = 1
        with self.assertRaises(SigningError):
            verify_eval_attestation(record, signing_key=KEY15, now=LATER15)
        record = _eval_record()
        record["payload"]["extra"] = 1
        with self.assertRaises(SigningError):
            verify_eval_attestation(record, signing_key=KEY15, now=LATER15)

    def test_numeric_fields_beyond_score_wrong_spelling_refuses(self):
        # The score is not the only numeric field whose spelling
        # is pinned: n, correct and version are ints in the signed
        # payload, rebuilt verifier-side with exact type checks
        # (bool is not an int; a float with an integral value is
        # not an int either). Every re-spelling is therefore a
        # malformed_payload refusal, never a silent coercion.
        for field, bad in (("n", 2.0), ("n", True),
                           ("correct", True), ("correct", 2.0),
                           ("version", 3.0), ("version", True)):
            with self.subTest(field=field, bad=bad):
                record = _eval_record()
                record["payload"][field] = bad
                reasons = verify_eval_attestation(
                    record, signing_key=KEY15, now=LATER15)
                self.assertTrue(reasons)
                self.assertIn("malformed_payload", reasons)

    def test_timestamp_spellings_verify_control(self):
        # Equivalence controls, NOT refusals: evaluated_at is
        # value-bound via _normalise_time, so the space
        # separator, the "Z" suffix and a +01:00 offset spelling
        # of the SAME instant (12:00 UTC) all rebuild to the
        # identical canonical payload the signature was issued
        # over, and the record verifies.
        for spelling in ("2026-11-20 12:00:00+00:00",
                         "2026-11-20T12:00:00Z",
                         "2026-11-20T13:00:00+01:00"):
            with self.subTest(spelling=spelling):
                record = _eval_record()
                record["payload"]["evaluated_at"] = spelling
                self.assertEqual(verify_eval_attestation(
                    record, signing_key=KEY15, now=LATER15), ())


class GateEnvelopeArtefactTests(unittest.TestCase):

    def setUp(self):
        self.data = envelope_to_dict(_gate_signed())

    def assert_from_dict_refuses(self, data):
        with self.assertRaises(SigningError):
            envelope_from_dict(data)

    def test_unknown_keys_refuse(self):
        data = copy.deepcopy(self.data)
        data["extra"] = 1
        self.assert_from_dict_refuses(data)
        data = copy.deepcopy(self.data)
        data["decision"]["extra"] = 1
        self.assert_from_dict_refuses(data)

    def test_accepted_as_int_string_or_zero_refuses(self):
        for bad in (1, "true", 0):
            with self.subTest(bad=bad):
                data = copy.deepcopy(self.data)
                data["decision"]["accepted"] = bad
                self.assert_from_dict_refuses(data)

    def test_ttl_fields_as_floats_or_strings_refuse(self):
        # The signing API's ttl_seconds: only a real int in bounds.
        decision = _gate_signed().decision
        for bad_ttl in (900.0, "900", True):
            with self.subTest(bad_ttl=bad_ttl):
                with self.assertRaises(SigningError):
                    sign_gate_decision(
                        decision, signing_key=KEY15,
                        signer_id="gate-signer", ttl_seconds=bad_ttl,
                        now=NOW15)
        # The envelope's window fields: timestamps, not numbers.
        for field in ("signed_at", "expires_at"):
            for bad in (1760000000.0, 123):
                with self.subTest(field=field, bad=bad):
                    data = copy.deepcopy(self.data)
                    data[field] = bad
                    self.assert_from_dict_refuses(data)

    def test_regression_score_string_or_bool_refuses(self):
        for bad in ("0.5", True, None):
            with self.subTest(bad=bad):
                data = copy.deepcopy(self.data)
                data["decision"]["regressions"][0]["baseline"] = bad
                self.assert_from_dict_refuses(data)

    def test_regression_baseline_int_1_matches_float_control(self):
        # Same canonicalisation rule as the eval score (control):
        # _score normalises int 1 to float 1.0 before hashing.
        data = copy.deepcopy(self.data)
        data["decision"]["regressions"][0]["baseline"] = 1
        restored = envelope_from_dict(data)
        self.assertEqual(verify_signed_decision(
            restored, signing_key=KEY15, now=NOW15), ())

    def test_regression_delta_negative_zero_matches_positive_zero_control(
            self):
        # Equivalence control, NOT a refusal: _score normalises
        # -0.0 to +0.0 ("equal values, one payload"), so an
        # envelope whose regression delta is spelled -0.0
        # verifies against a signature issued over +0.0 — the
        # rebuilt payload is byte-identical either way.
        decision = GateDecision(
            accepted=False, proposal_id="prop-1",
            reasons=("regression",),
            regressions=(Regression("sealed", "bench-s", 0.5, 0.5, 0.0),),
            forgetting_failures=(), verifier_id="seat-3",
            evaluated_at=NOW15, verifier_note="")
        signed = sign_gate_decision(decision, signing_key=KEY15,
                                    signer_id="gate-signer", now=NOW15)
        data = envelope_to_dict(signed)
        data["decision"]["regressions"][0]["delta"] = -0.0
        restored = envelope_from_dict(data)
        self.assertEqual(verify_signed_decision(
            restored, signing_key=KEY15, now=NOW15), ())

    def test_regression_baseline_huge_int_refuses(self):
        # 10**400 is exactly the spelling the 2**53 exactness
        # guard in _score exists for: an int that large is not
        # exactly representable as a float, so envelope_from_dict
        # refuses it at payload re-derivation rather than letting
        # a rounded value stand in for the presented one.
        data = copy.deepcopy(self.data)
        data["decision"]["regressions"][0]["baseline"] = 10 ** 400
        self.assert_from_dict_refuses(data)


class AttestationEnvelopeArtefactTests(unittest.TestCase):

    def setUp(self):
        self.data = attestation_envelope_to_dict(_att_signed())

    def assert_from_dict_refuses(self, data):
        with self.assertRaises(SigningError):
            attestation_envelope_from_dict(data)

    def test_unknown_keys_refuse(self):
        data = copy.deepcopy(self.data)
        data["extra"] = 1
        self.assert_from_dict_refuses(data)
        data = copy.deepcopy(self.data)
        data["attestation"]["extra"] = 1
        self.assert_from_dict_refuses(data)

    def test_reward_hacking_checked_as_int_or_string_refuses(self):
        for bad in (1, "true", 0):
            with self.subTest(bad=bad):
                data = copy.deepcopy(self.data)
                data["attestation"]["reward_hacking_checked"] = bad
                self.assert_from_dict_refuses(data)

    def test_manifest_hash_null_refuses(self):
        data = copy.deepcopy(self.data)
        data["manifest_hash"] = None
        self.assert_from_dict_refuses(data)

    def test_expires_at_non_ascii_digits_refuses(self):
        data = copy.deepcopy(self.data)
        data["expires_at"] = NON_ASCII_DIGIT_TS
        self.assert_from_dict_refuses(data)

    def test_expires_at_timezone_naive_refuses(self):
        data = copy.deepcopy(self.data)
        data["expires_at"] = "2026-11-20T12:15:00"
        self.assert_from_dict_refuses(data)

    def test_expires_at_as_float_refuses(self):
        data = copy.deepcopy(self.data)
        data["expires_at"] = 1760000000.0
        self.assert_from_dict_refuses(data)

    def test_from_json_duplicate_and_non_finite_refuse(self):
        from signing.attestation import attestation_envelope_to_json
        raw = attestation_envelope_to_json(_att_signed())
        dup = raw.replace('"signer_id":"seat-3"',
                          '"signer_id":"seat-3","signer_id":"seat-3"', 1)
        self.assertNotEqual(dup, raw)
        with self.assertRaises(SigningError):
            attestation_envelope_from_json(dup)
        # NaN is rejected by the parse_constant hook; 1e999 parses
        # to inf and is then refused by the field type checks —
        # either way no usable envelope emerges from a non-finite
        # spelling.
        nan = raw.replace('"reward_hacking_checked":true',
                          '"reward_hacking_checked":NaN', 1)
        with self.assertRaises(SigningError):
            attestation_envelope_from_json(nan)
        huge = raw.replace('"manifest_hash":""',
                           '"manifest_hash":1e999', 1)
        self.assertNotEqual(huge, raw)
        with self.assertRaises(SigningError):
            attestation_envelope_from_json(huge)


class ReleaseRecordJsonTests(unittest.TestCase):
    """release_from_json is the one from_json surface the rest
    of this battery had not pinned: its duplicate-key hook must
    refuse exactly as the envelope parsers' hooks do."""

    def _release(self):
        return ReleaseRecord(
            proposal_id="prop-1", item_id="item-1",
            stage="provisional", manifest_hash="a" * 64,
            decision_id="", payload_hash="",
            review_record_hash="b" * 64, expected_cycle_id=1,
            pre_ship_cycle_seq=0, pre_ship_state_sha256="c" * 64)

    def test_release_from_json_roundtrip_is_the_control(self):
        release = self._release()
        self.assertEqual(release_from_json(release.to_json()), release)

    def test_release_from_json_duplicate_keys_refuse(self):
        raw = self._release().to_json()
        dup = raw.replace(
            '"proposal_id":"prop-1"',
            '"proposal_id":"prop-1","proposal_id":"prop-forged"', 1)
        self.assertNotEqual(dup, raw)
        with self.assertRaises(ManifestError):
            release_from_json(dup)


class UnicodeAnswerTests(unittest.TestCase):
    """rev-r6 S7: two different normalisations, pinned in both
    directions. The registry's SCORING is spelling-lenient —
    _normalise_answer applies NFKC + casefold, so NFC and NFD
    spellings of the same answer score identically. The signed
    BINDING is spelling-strict — answers_hash_for hashes the
    raw transcript with no normalisation, so the two spellings
    hash differently and a record bound to one does not verify
    against the other. That asymmetry is the fail-closed
    direction: leniency at scoring must not leak into binding."""

    NFC = "caf\u00e9"        # café, composed
    NFD = "cafe\u0301"       # café, e + combining acute

    def test_nfc_and_nfd_are_distinct_spellings(self):
        self.assertNotEqual(self.NFC, self.NFD)

    def test_nfc_nfd_score_identically_through_the_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = EvalRegistry(Path(tmp) / "registry")
            registry.add_sealed_item(
                "u-1", "lang", "the word for coffee-shop?", self.NFC,
                "test-actor")
            for spelling in (self.NFC, self.NFD):
                with self.subTest(spelling=ascii(spelling)):
                    report = registry.run_sealed_evaluation(
                        "test-actor", lambda prompt, s=spelling: s)
                    self.assertEqual(report["correct"], 1)
                    self.assertEqual(report["score"], 1.0)

    def test_answers_hash_binds_the_raw_transcript(self):
        nfc_hash = answers_hash_for([self.NFC])
        nfd_hash = answers_hash_for([self.NFD])
        self.assertNotEqual(nfc_hash, nfd_hash)
        # Fail-closed consequence, not just unequal hashes: a
        # record signed over the NFC transcript verifies against
        # the NFC hash and is an answers_mismatch against the
        # NFD spelling's hash.
        report = {"set": "sealed", "version": 3, "n": 2,
                  "correct": 2, "score": 1.0,
                  "manifest_hash": "a" * 64, "evaluated_at": NOW15}
        record = sign_eval_attestation(
            report, signing_key=KEY15, signer_id="verifier-svc",
            actor="verifier-actor", registry_digest="b" * 64,
            answers_hash=nfc_hash, now=NOW15)
        self.assertEqual(verify_eval_attestation(
            record, signing_key=KEY15,
            expected_answers_hash=nfc_hash, now=LATER15), ())
        reasons = verify_eval_attestation(
            record, signing_key=KEY15,
            expected_answers_hash=nfd_hash, now=LATER15)
        self.assertIn("answers_mismatch", reasons)


if __name__ == "__main__":
    unittest.main()
