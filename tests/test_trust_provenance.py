"""Attack demonstrations for the evaluator provenance chain
(Trust Boundary v3, item 1; spec: docs/PROVENANCE.md).

Chain under attack: trusted registry -> trusted evaluation
configuration -> controlled evaluation execution -> authenticated
score record -> independently derived decision -> signed
attestation.

Every test drives the REAL verifier (subprocess via
trust/client.py, reusing the fixture patterns of
tests/test_trust_verifier.py; raw-protocol subprocess calls where
the exit code itself is the assertion). Every attack must FAIL —
refusal, no signature issued — and each test asserts the signing
ledger gained no attestation/gate signature from the attack.
The predicate probes (h) are the exception that proves the rule:
there issuance succeeds by design, and the test asserts the
DERIVED decision and its ledger shape instead.

Fixture discipline mirrors test_trust_verifier.py: fake registry
+ generated key in a temp verifier-home; the builder side (this
test process) holds the key only to VERIFY outcomes and to craft
test-side artefacts, exactly as a key-holding consumer would.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.factory import assess_gap
from eval.registry import EvalRegistry, _content_hash, _state_digest
from signing import generate_key_file
from trust.attestation import answers_hash_for, registry_digest_for, \
    sign_eval_attestation, verify_eval_attestation
from trust.client import VerifierClient
from trust.errors import VerifierConfigError, VerifierProtocolError
from trust.ledger import SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ATTESTER = "seat-3"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
ALL_CORRECT = [expected for *_x, expected in ITEMS]
REPO_ROOT = Path(__file__).resolve().parents[1]


def recent(minutes=5):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes)).isoformat()


class ProvenanceFixture(unittest.TestCase):
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

    # -- harness helpers (patterns from test_trust_verifier.py) ----

    def attester(self, **env_over):
        """The issuing identity: same key, ledger home and registry
        as the fixture, configured under the seat-3 signer id, so
        eval records' signer matches the attestation issuer."""
        env = dict(self.env, AION_VERIFIER_SIGNER_ID=ATTESTER)
        env.update(env_over)
        return VerifierClient(
            verifier_env=env, expected_signer_id=ATTESTER,
            expected_key_id=self.key.key_id)

    def attester_env(self, **env_over):
        env = dict(self.env, AION_VERIFIER_SIGNER_ID=ATTESTER)
        env.update(env_over)
        return env

    def eval_records(self, baseline_answers, candidate_answers,
                     *, proposal_id="prop-v1", client=None):
        attester = client or self.attester()
        return (attester.sealed_eval(
                    baseline_answers,
                    proposal_id=f"{proposal_id}:baseline"),
                attester.sealed_eval(
                    candidate_answers,
                    proposal_id=f"{proposal_id}:candidate"))

    def ledger_entries(self):
        return SigningLedger(self.home / "ledger").entries()

    def sign_entries(self):
        return [e for e in self.ledger_entries() if e["kind"] == "sign"]

    def attestation_signs(self):
        return [e for e in self.sign_entries()
                if e["format"] in ("verifier-attestation",
                                   "gate-decision")]

    def assert_no_new_signatures(self, signs_before):
        """The attack gained the ledger no signature of any kind —
        in particular no attestation/gate signature."""
        self.assertEqual(self.sign_entries(), signs_before)
        self.assertEqual(
            [e for e in self.attestation_signs()
             if e not in [s for s in signs_before
                          if s["format"] in ("verifier-attestation",
                                             "gate-decision")]],
            [])

    def registry_log_len(self):
        return len(EvalRegistry(self.registry_dir).access_log())

    def raw(self, mode, body, env=None):
        """One raw verifier subprocess; returns the CompletedProcess
        so the test can assert the exit code itself."""
        full_env = {"PATH": "/usr/bin:/bin",
                    "PYTHONPATH": str(REPO_ROOT)}
        full_env.update(env if env is not None
                        else self.attester_env())
        doc = {"v": "trust-request/1", "request_id": "req-prov1",
               "mode": mode, "body": body}
        return subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=json.dumps(doc).encode(), capture_output=True,
            timeout=30, cwd=str(REPO_ROOT), env=full_env)

    def issue(self, baseline, candidate, **over):
        kwargs = dict(proposal_id="prop-v1", baseline_eval=baseline,
                      candidate_eval=candidate,
                      public_baseline_score=0.5,
                      public_candidate_score=0.6)
        kwargs.update(over)
        return self.attester().issue_attestation(**kwargs)


class ConfigSubstitutionTests(ProvenanceFixture):
    """(a) The verifier's registry copy is the configuration: change
    it after records are issued and the records no longer bind."""

    def _rewrite_registry(self, mutate):
        path = self.registry_dir / "registry.json"
        data = json.loads(path.read_text())
        mutate(data)
        # Recompute the state digest so the registry still VALIDATES
        # on load: the refusal below must come from the manifest
        # binding, not from tamper detection on a sloppy edit.
        data["state_digest"] = _state_digest(data)
        path.write_text(json.dumps(data))

    def test_tampered_expected_answer_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        signs_before = self.sign_entries()

        def tamper(data):
            item = data["sealed_items"][0]
            item["expected"] = "5"
            item["content_hash"] = _content_hash(
                item["id"], item["domain"], item["prompt"],
                item["expected"])
        self._rewrite_registry(tamper)
        # Sanity: the tampered registry is internally valid and its
        # manifest really did change.
        registry = EvalRegistry(self.registry_dir)
        self.assertNotEqual(registry.sealed_manifest_hash(ACTOR),
                            self.manifest_hash)
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, candidate)
        self.assert_no_new_signatures(signs_before)

    def test_removed_sealed_item_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        signs_before = self.sign_entries()
        self._rewrite_registry(
            lambda data: data["sealed_items"].__setitem__(
                slice(None),
                [it for it in data["sealed_items"]
                 if it["id"] != "sealed-2"]))
        registry = EvalRegistry(self.registry_dir)
        self.assertNotEqual(registry.sealed_manifest_hash(ACTOR),
                            self.manifest_hash)
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, candidate)
        self.assert_no_new_signatures(signs_before)

    def test_records_from_registry_v1_refused_after_registry_grows(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        signs_before = self.sign_entries()
        # A LEGITIMATE registry change: a fourth sealed item is
        # registered through the registry's own API. The manifest
        # moves; records bound to the old manifest are stale
        # evidence and must not derive an attestation.
        registry = EvalRegistry(self.registry_dir)
        registry.add_sealed_item("sealed-4", "algebra", "1+1?", "2",
                                 "test-actor")
        self.assertNotEqual(registry.sealed_manifest_hash(ACTOR),
                            self.manifest_hash)
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, candidate)
        self.assert_no_new_signatures(signs_before)


class CrossRegistryTests(ProvenanceFixture):
    """(b) Records signed against a DIFFERENT registry (different
    manifest) presented to this registry's verifier."""

    OTHER_ITEMS = [("other-1", "algebra", "5+5?", "10"),
                   ("other-2", "algebra", "2*6?", "12"),
                   ("other-3", "geo", "sqrt16?", "4")]

    def test_cross_registry_candidate_refused(self):
        other_dir = Path(self.tmp.name) / "registry2"
        other = EvalRegistry(other_dir)
        for item_id, domain, prompt, expected in self.OTHER_ITEMS:
            other.add_sealed_item(item_id, domain, prompt, expected,
                                  "test-actor")
        # Same key, same signer, SAME ledger home: the foreign
        # record is MAC-valid and ledgered, so the manifest binding
        # is the only thing that can (and must) refuse it.
        other_client = VerifierClient(
            verifier_env=self.attester_env(
                AION_REGISTRY_DIR=str(other_dir)),
            expected_signer_id=ATTESTER,
            expected_key_id=self.key.key_id)
        baseline, _own_candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        foreign_candidate = other_client.sealed_eval(
            [e for *_x, e in self.OTHER_ITEMS],
            proposal_id="prop-v1:candidate")
        self.assertNotEqual(
            foreign_candidate["payload"]["manifest_hash"],
            self.manifest_hash)
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, foreign_candidate)
        self.assert_no_new_signatures(signs_before)


class CrossKeyTests(ProvenanceFixture):
    """(c) Records produced by a verifier with a different signing
    key: same registry, same signer id, same manifest — the MAC /
    key-id binding is what must refuse them."""

    def test_cross_key_candidate_refused(self):
        home2 = Path(self.tmp.name) / "verifier-home-2"
        home2.mkdir()
        home2.chmod(0o700)
        key2 = generate_key_file(home2 / "gate.key")
        self.assertNotEqual(key2.key_id, self.key.key_id)
        foreign = VerifierClient(
            verifier_env=self.attester_env(
                AION_VERIFIER_KEY_PATH=str(home2 / "gate.key"),
                AION_VERIFIER_HOME=str(home2 / "ledger")),
            expected_signer_id=ATTESTER, expected_key_id=key2.key_id)
        baseline, _own_candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        foreign_candidate = foreign.sealed_eval(
            ALL_CORRECT, proposal_id="prop-v1:candidate")
        # The foreign record is well-formed and bound to THIS
        # registry's manifest — under the wrong key.
        self.assertEqual(foreign_candidate["payload"]["manifest_hash"],
                         self.manifest_hash)
        self.assertNotEqual(
            verify_eval_attestation(foreign_candidate,
                                    signing_key=self.key), ())
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, foreign_candidate)
        self.assert_no_new_signatures(signs_before)

    def test_cross_key_candidate_ledgered_in_shared_home_refused_for_mac(self):
        # Strengthened (c): the foreign record is LEDGERED in the
        # SAME ledger home the verifying verifier uses — issued by
        # a second verifier sharing that home but holding a
        # different key — so ledger-absence cannot be the reason
        # for refusal. The refusal must be the MAC/signature one.
        home2 = Path(self.tmp.name) / "verifier-home-2"
        home2.mkdir()
        home2.chmod(0o700)
        key2 = generate_key_file(home2 / "gate.key")
        self.assertNotEqual(key2.key_id, self.key.key_id)
        foreign = VerifierClient(
            verifier_env=self.attester_env(
                AION_VERIFIER_KEY_PATH=str(home2 / "gate.key")),
            # NOTE: no AION_VERIFIER_HOME override — the foreign
            # verifier shares this fixture's ledger home.
            expected_signer_id=ATTESTER, expected_key_id=key2.key_id)
        # Only the baseline comes from this service: issuing this
        # service's own candidate first would make the foreign
        # ALL_CORRECT transcript a byte-identical budget replay in
        # the SHARED budget store, and it would never be issued.
        baseline = self.attester().sealed_eval(
            ["4", "wrong", "wrong"], proposal_id="prop-v1:baseline")
        foreign_candidate = foreign.sealed_eval(
            ALL_CORRECT, proposal_id="prop-v1:candidate")
        self.assertEqual(foreign_candidate["payload"]["manifest_hash"],
                         self.manifest_hash)
        # Pin the isolation: the foreign record IS present in the
        # shared signing ledger as a sealed-eval sign entry, so a
        # ledger check on it would PASS.
        self.assertIn(
            foreign_candidate["payload_hash"],
            [e["payload_hash"] for e in self.sign_entries()
             if e["format"] == "sealed-eval"])
        # Test-side pin of the exact verification reasons under
        # this service's key: unknown key id, then MAC mismatch.
        self.assertEqual(
            verify_eval_attestation(foreign_candidate,
                                    signing_key=self.key),
            ("unknown_key", "signature_mismatch"))
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, foreign_candidate)
        # The specific code/detail _verify_eval_record returns for
        # MAC failure — and NOT the ledger-absence code.
        self.assertIn("eval_evidence_unverifiable", str(ctx.exception))
        self.assertIn(
            "an eval record failed verification: "
            "unknown_key,signature_mismatch", str(ctx.exception))
        self.assertNotIn("eval_record_not_ledgered", str(ctx.exception))
        self.assert_no_new_signatures(signs_before)


class ExpiredRecordTests(ProvenanceFixture):
    """(d) A record expired at issuance time is refused.

    Manipulation, stated plainly: waiting out a real TTL would take
    at least the 60 s minimum signing window. Instead the genuine
    candidate's payload is re-dated test-side with the fixture key
    (which this process holds only as a key-holding consumer) to
    exactly the record a short-TTL (60 s) verifier would have
    issued two minutes ago: MAC-valid, bound to the same manifest,
    answers, registry digest and scope — and expired. The verifier
    must refuse it for the `expired` reason specifically, which is
    checked before ledger presence in _verify_eval_record.
    """

    def test_expired_candidate_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        payload = candidate["payload"]
        report = {"set": "sealed", "version": payload["version"],
                  "n": payload["n"], "correct": payload["correct"],
                  "score": payload["score"],
                  "manifest_hash": payload["manifest_hash"],
                  "evaluated_at": payload["evaluated_at"]}
        past = (datetime.now(timezone.utc)
                - timedelta(seconds=120)).isoformat()
        expired = sign_eval_attestation(
            report, signing_key=self.key, signer_id=ATTESTER,
            actor=ACTOR, registry_digest=payload["registry_digest"],
            answers_hash=payload["answers_hash"], ttl_seconds=60,
            now=past, scope=payload["scope"])
        # Test-side pin: expiry is the record's ONLY defect.
        self.assertEqual(
            verify_eval_attestation(expired, signing_key=self.key),
            ("expired",))
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, expired)
        self.assertIn("expired", str(ctx.exception))
        self.assert_no_new_signatures(signs_before)


class SignerMisuseTests(ProvenanceFixture):
    """(e) A caller-selected approval is a claim, never a signature;
    smuggled decision fields at issuance are a protocol error."""

    def test_submit_claim_approve_yields_claim_id_only(self):
        signs_before = self.sign_entries()
        result = self.client.submit_claim(
            {"verifier_id": ATTESTER, "decision": "approve",
             "sealed_hash": self.manifest_hash,
             "reward_hacking_checked": True,
             "evidence_ref": "fabricated-run",
             "attested_at": recent()}, proposal_id="prop-v1")
        # The response is a claim id/hash pair and nothing else.
        self.assertEqual(set(result), {"claim_id", "claim_hash"})
        self.assertEqual(result["claim_id"], result["claim_hash"])
        entries = self.ledger_entries()
        claims = [e for e in entries if e["kind"] == "claim"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["format"], "claim")
        self.assertFalse(claims[0]["accepted"])
        self.assertEqual(claims[0]["decision_id"], result["claim_id"])
        # No "sign" entry appeared — of any format, for any id.
        self.assertEqual(self.sign_entries(), signs_before)
        ledger = SigningLedger(self.home / "ledger")
        self.assertFalse(ledger.has_envelope(result["claim_id"]))

    def test_issue_attestation_smuggled_decision_fields_exit_2(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        signs_before = self.sign_entries()
        for spelling in ("decision", "approve",
                         "reward_hacking_checked", "caller_decision",
                         "attestation_decision", "verdict"):
            body = {"proposal_id": "prop-v1",
                    "baseline_eval": baseline,
                    "candidate_eval": candidate,
                    "public_baseline_score": 0.5,
                    "public_candidate_score": 0.6,
                    spelling: "approve"}
            result = self.raw("issue_attestation", body)
            self.assertEqual(result.returncode, 2, msg=spelling)
        self.assert_no_new_signatures(signs_before)


class ConfigInjectionTests(ProvenanceFixture):
    """(f) Configuration comes from the environment only. Bodies
    carrying config-shaped fields are protocol errors (exit 2) and
    spend nothing: no signature, no registry access."""

    CONFIG_FIELDS = ("signer_id", "key_path",
                     "AION_VERIFIER_KEY_PATH",
                     "AION_VERIFIER_SIGNER_ID",
                     "AION_VERIFIER_TTL_SECONDS",
                     "AION_REGISTRY_DIR", "actor", "registry_dir")

    def test_sealed_eval_config_fields_exit_2_and_spend_nothing(self):
        log_before = self.registry_log_len()
        signs_before = self.sign_entries()
        for field in self.CONFIG_FIELDS:
            body = {"answers": ALL_CORRECT,
                    "proposal_id": "prop-v1", field: "attacker"}
            result = self.raw("sealed_eval", body)
            self.assertEqual(result.returncode, 2, msg=field)
        self.assertEqual(self.registry_log_len(), log_before)
        self.assert_no_new_signatures(signs_before)

    def test_issue_attestation_config_fields_exit_2(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        log_before = self.registry_log_len()
        signs_before = self.sign_entries()
        for field in self.CONFIG_FIELDS:
            body = {"proposal_id": "prop-v1",
                    "baseline_eval": baseline,
                    "candidate_eval": candidate,
                    "public_baseline_score": 0.5,
                    "public_candidate_score": 0.6,
                    field: "attacker"}
            result = self.raw("issue_attestation", body)
            self.assertEqual(result.returncode, 2, msg=field)
        # The strict key-set check fires before the registry is
        # opened, so no registry access was spent either.
        self.assertEqual(self.registry_log_len(), log_before)
        self.assert_no_new_signatures(signs_before)


class ForgedRecordTests(ProvenanceFixture):
    """(g) Forged records: an edited score and a transplanted
    signature both break the payload-hash / MAC binding."""

    def test_edited_score_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ["nope", "9", "nope-2"])
        self.assertEqual(candidate["payload"]["score"], 1 / 3)
        forged = copy.deepcopy(candidate)
        forged["payload"]["score"] = 1.0
        self.assertNotEqual(
            verify_eval_attestation(forged, signing_key=self.key), ())
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, forged)
        self.assert_no_new_signatures(signs_before)

    def test_swapped_signature_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        forged = copy.deepcopy(candidate)
        forged["signature"] = baseline["signature"]
        reasons = verify_eval_attestation(forged, signing_key=self.key)
        self.assertIn("signature_mismatch", reasons)
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError):
            self.issue(baseline, forged)
        self.assert_no_new_signatures(signs_before)


class DecisionPredicateTests(ProvenanceFixture):
    """(h) The decision predicate, DEMONSTRATED through real
    sealed_eval records + issue_attestation — not just documented:
    approve iff sealed_after >= sealed_before AND NOT
    gap.gaming_suspected AND NOT gap.sealed_regression, with
    gap = assess_gap(..., widen_threshold=0.05).

    Issuance succeeds here by design (a derived reject is still a
    signed attestation), so instead of "no new signature" these
    tests assert exactly one new verifier-attestation sign entry
    whose ledgered `accepted` flag matches the derived decision.
    """

    def derive(self, baseline_answers, candidate_answers,
               public_before, public_after):
        baseline, candidate = self.eval_records(
            baseline_answers, candidate_answers)
        return self.derive_from_records(
            baseline, candidate, public_before, public_after)

    def derive_from_records(self, baseline, candidate,
                            public_before, public_after):
        signs_before = self.attestation_signs()
        signed = self.issue(baseline, candidate,
                            public_baseline_score=public_before,
                            public_candidate_score=public_after)
        new_signs = [e for e in self.attestation_signs()
                     if e not in signs_before]
        self.assertEqual(len(new_signs), 1)
        self.assertEqual(new_signs[0]["format"], "verifier-attestation")
        att = signed["attestation"]
        self.assertEqual(new_signs[0]["accepted"],
                         att["decision"] == "approve")
        self.assertTrue(att["reward_hacking_checked"])
        self.assertEqual(att["sealed_hash"], self.manifest_hash)
        self.assertEqual(
            att["evidence_ref"],
            f"eval:{baseline['payload_hash']}:"
            f"{candidate['payload_hash']}")
        return att

    def test_sealed_regression_with_public_gain_rejects(self):
        # Sealed 1.0 -> 0.0 while public rises: the
        # sealed_after >= sealed_before conjunct (and the
        # sealed_regression flag) both fail the predicate.
        att = self.derive(ALL_CORRECT, ["wrong", "wrong", "wrong"],
                          public_before=0.5, public_after=0.9)
        self.assertEqual(att["decision"], "reject")

    def test_public_only_gain_with_widening_gap_rejects(self):
        # Sealed flat at 1/3, public 0.5 -> 0.9: public_only_gain
        # (public_delta > 1e-9, sealed_delta <= 1e-9) and the gap
        # widens by 0.4 > 0.05, so gaming_suspected rejects even
        # though the sealed score did not regress. Transcripts
        # differ at every position so neither reads as a budget
        # replay/probe of the other.
        att = self.derive(["4", "wrong", "wrong"],
                          ["nope", "9", "nope-2"],
                          public_before=0.5, public_after=0.9)
        self.assertEqual(att["decision"], "reject")

    def test_clean_sealed_gain_approves(self):
        # Sealed 1/3 -> 1.0, public 0.5 -> 0.6: sealed gain, gap
        # narrows (widened < 0), no regression — approve.
        att = self.derive(["4", "wrong", "wrong"], ALL_CORRECT,
                          public_before=0.5, public_after=0.6)
        self.assertEqual(att["decision"], "approve")

    def test_widening_exactly_at_threshold_not_flagged_approves(self):
        # Boundary probe (j): sealed 1/3 -> 2/3, public delta set
        # to sealed_delta + 0.05 exactly, so the gap widens by
        # exactly the 0.05 threshold. assess_gap flags only
        # widened > threshold + EPSILON (0.05 + 1e-9), so this is
        # NOT flagged; with a real sealed gain (which also defeats
        # public_only_gain) the derived decision is approve.
        public_before = 0.4
        public_after = public_before + (2 / 3 - 1 / 3) + 0.05
        gap = assess_gap(public_before, public_after, 1 / 3, 2 / 3)
        self.assertFalse(gap["gaming_suspected"])
        self.assertEqual(gap["reason"], "no_flag")
        att = self.derive(["4", "wrong", "wrong"], ["4", "9", "wrong"],
                          public_before=public_before,
                          public_after=public_after)
        self.assertEqual(att["decision"], "approve")

    def test_widening_just_over_threshold_flagged_rejects(self):
        # Boundary probe (j): same sealed gain, but the gap widens
        # by 0.05 + 2e-9 — strictly more than threshold + EPSILON
        # (0.05 + 1e-9) — so gap_flag fires, gaming_suspected is
        # set, and the derived decision is reject despite the
        # sealed gain. The issuance response exposes no gap reason
        # (the attestation carries decision only), so the reason
        # is pinned test-side via assess_gap on the same numbers.
        public_before = 0.4
        public_after = public_before + (2 / 3 - 1 / 3) + 0.05 + 2e-9
        gap = assess_gap(public_before, public_after, 1 / 3, 2 / 3)
        self.assertTrue(gap["gaming_suspected"])
        self.assertEqual(gap["reason"], "gap_widened")
        att = self.derive(["4", "wrong", "wrong"], ["4", "9", "wrong"],
                          public_before=public_before,
                          public_after=public_after)
        self.assertEqual(att["decision"], "reject")

    def test_sealed_drop_1e_minus_10_rejects_via_ge_conjunct_not_regression(self):
        # Boundary probe (j): a sealed drop of 1e-10. It is
        # smaller than assess_gap's EPSILON (1e-9), so
        # sealed_regression is False and the gap reason is NOT
        # "sealed_regression"; but the decision predicate's
        # sealed_after >= sealed_before conjunct has no epsilon,
        # so the derived decision is still reject.
        #
        # Manipulation, stated plainly (same pattern as the
        # expired-record test): no feasible real sealed set can
        # produce a 1e-10 score step — real scores move in 1/n
        # steps — so the pair is crafted test-side with the
        # fixture key (held here only as a key-holding consumer)
        # at n = 10**10, correct counts differing by exactly 1,
        # bound to the LIVE manifest, scope and signer, and
        # ledgered test-side via SigningLedger so ledger presence
        # passes. Issuance itself goes through the real verifier
        # subprocess, which verifies, consumes and derives.
        n = 10 ** 10
        log = EvalRegistry(self.registry_dir).access_log()
        digest = registry_digest_for(
            manifest_hash=self.manifest_hash,
            sealed_version=log[-1]["sealed_version"],
            log_head=log[-1]["entry_hash"], log_seq=len(log))

        def crafted(correct, answers, scope):
            report = {"set": "sealed", "version": 3, "n": n,
                      "correct": correct, "score": correct / n,
                      "manifest_hash": self.manifest_hash,
                      "evaluated_at": recent()}
            return sign_eval_attestation(
                report, signing_key=self.key, signer_id=ATTESTER,
                actor=ACTOR, registry_digest=digest,
                answers_hash=answers_hash_for(answers), scope=scope)

        baseline = crafted(n // 2, ["baseline-transcript"],
                           "prop-v1:baseline")
        candidate = crafted(n // 2 - 1, ["candidate-transcript"],
                              "prop-v1:candidate")
        self.assertEqual(baseline["payload"]["score"], 0.5)
        self.assertAlmostEqual(
            baseline["payload"]["score"] - candidate["payload"]["score"],
            1e-10, delta=1e-12)
        self.assertEqual(
            verify_eval_attestation(baseline, signing_key=self.key), ())
        self.assertEqual(
            verify_eval_attestation(candidate, signing_key=self.key), ())
        ledger = SigningLedger(self.home / "ledger")
        ledger.append_eval_attestation(baseline, recorded_at=recent())
        ledger.append_eval_attestation(candidate, recorded_at=recent())
        # Pin the gap side on the exact scores the verifier will
        # derive: no gaming flag, no sealed regression, reason is
        # "no_flag" — NOT "sealed_regression". (The issuance
        # response exposes no reason field; the attestation
        # carries the decision only.)
        gap = assess_gap(0.5, 0.5, baseline["payload"]["score"],
                         candidate["payload"]["score"])
        self.assertFalse(gap["sealed_regression"])
        self.assertFalse(gap["gaming_suspected"])
        self.assertEqual(gap["reason"], "no_flag")
        att = self.derive_from_records(
            baseline, candidate, public_before=0.5, public_after=0.5)
        self.assertEqual(att["decision"], "reject")


class ReplayConsumptionTests(ProvenanceFixture):
    """(i) Replay attack: a genuine pair that already issued an
    attestation is presented again, unchanged. Consumption
    (Trust Boundary v3, item 3) must refuse the second issuance
    with eval_evidence_consumed and sign nothing new."""

    def test_replay_same_pair_refused_consumed_no_second_attestation(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ALL_CORRECT)
        signed = self.issue(baseline, candidate)
        self.assertEqual(signed["attestation"]["decision"], "approve")
        consumption = [e for e in self.ledger_entries()
                       if e["kind"] == "consume"]
        self.assertEqual(len(consumption), 2)
        signs_before_replay = self.sign_entries()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, candidate)
        self.assertIn("eval_evidence_consumed", str(ctx.exception))
        # No second attestation was signed: the ledger's sign
        # entries are exactly what they were before the replay.
        self.assertEqual(self.sign_entries(), signs_before_replay)
        self.assertEqual(
            len([e for e in self.ledger_entries()
                 if e["kind"] == "consume"]), 2)


if __name__ == "__main__":
    unittest.main()
