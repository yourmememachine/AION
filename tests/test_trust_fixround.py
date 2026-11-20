"""Fix-round tests — Trust Boundary v3 war-room fixes:

  S1 (HIGH)   sealed_eval must refuse proposal_ids whose scope
              root fails signing's id grammar, before any budget
              is recorded or anything is signed.
  S3 (MEDIUM) issue_attestation must validate proposal_id BEFORE
              consuming the single-use eval pair.
  S2 (HIGH)   the key-free client must validate a sealed_eval
              record against the REBUILT canonical payload, so a
              score re-spelled as int 1 is accepted exactly as
              verify_eval_attestation accepts it.
  S6 (LOW)    attestation / manifest / release JSON loaders must
              refuse non-finite float tokens (1e999) in the parser
              layer via a parse_float hook.

Fixture discipline mirrors tests/test_trust_verifier.py: fake
registry + generated key in a temp verifier-home; the builder
side holds the key only to verify outcomes test-side.
"""

import copy
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import VerifierAttestation
from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.attestation import (
    attestation_envelope_from_json,
    attestation_envelope_to_json,
    sign_attestation,
)
from trust.attestation import (
    sign_eval_attestation,
    verify_eval_attestation,
)
from trust.client import VerifierClient
from trust.errors import VerifierProtocolError
from trust.ledger import SigningLedger
from trust.manifest import ManifestError, build_manifest, manifest_from_json
from trust.release import build_release_record, release_from_json

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]
# Cyrillic small letter o (U+043E): a homoglyph for ASCII "o".
HOMOGLYPH_ID = "pr\u043ep-v1"


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

    def attester(self):
        return VerifierClient(
            verifier_env=dict(self.env, AION_VERIFIER_SIGNER_ID="seat-3"),
            expected_signer_id="seat-3",
            expected_key_id=self.key.key_id)

    def sign_count(self):
        ledger_file = self.home / "ledger" / "signing-ledger.json"
        if not ledger_file.exists():
            return 0
        return len([e for e in SigningLedger(self.home / "ledger")
                    .entries() if e["kind"] == "sign"])

    def budgets_bytes(self):
        budgets = self.home / "ledger" / "budgets.json"
        return budgets.read_bytes() if budgets.exists() else None

    def consumption_entries(self):
        ledger_file = self.home / "ledger" / "signing-ledger.json"
        if not ledger_file.exists():
            return []
        return [e for e in SigningLedger(self.home / "ledger").entries()
                if e["kind"] == "consume"]

    def eval_records(self, baseline_answers, candidate_answers,
                     *, proposal_id="prop-v1"):
        attester = self.attester()
        return (attester.sealed_eval(
                    baseline_answers,
                    proposal_id=f"{proposal_id}:baseline"),
                attester.sealed_eval(
                    candidate_answers,
                    proposal_id=f"{proposal_id}:candidate"))


# ---------------------------------------------------------------------
# (1) S1 — sealed_eval scope grammar
# ---------------------------------------------------------------------

class SealedEvalScopeTests(VerifierFixture):

    BAD_SCOPES = (
        "prop\nFORGED",          # newline + uppercase
        HOMOGLYPH_ID,            # Cyrillic homoglyph
        "prop:forged",           # colon, no legitimate role suffix
        "prop-v1:baseline:extra",  # colon beyond one role suffix
        "X:baseline",            # uppercase root with role suffix
        "Prop-V1",               # uppercase
        "a" * 65,                # root over the 64-char grammar cap
        "A" * 100,               # over-long AND uppercase
    )

    def test_bad_scopes_refused_nothing_signed_no_budget(self):
        for bad in self.BAD_SCOPES:
            with self.subTest(bad=bad):
                signs_before = self.sign_count()
                budgets_before = self.budgets_bytes()
                with self.assertRaises(VerifierProtocolError):
                    self.client.sealed_eval(RIGHT, proposal_id=bad)
                self.assertEqual(self.sign_count(), signs_before)
                self.assertEqual(self.budgets_bytes(), budgets_before)

    def test_valid_proposal_id_still_works(self):
        record = self.client.sealed_eval(RIGHT, proposal_id="prop-v1")
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(record["payload"]["scope"], "prop-v1")
        self.assertEqual(
            verify_eval_attestation(record, signing_key=self.key), ())

    def test_valid_role_suffixed_scope_still_works(self):
        # The evidence flow's legitimate pair scopes:
        # "<proposal>:baseline" / "<proposal>:candidate" carry the
        # SAME root grammar plus one role suffix and must not be
        # refused by the S1 check.
        record = self.client.sealed_eval(
            ["4", "wrong", "wrong"], proposal_id="prop-v1:baseline")
        self.assertEqual(record["payload"]["scope"], "prop-v1:baseline")
        self.assertEqual(
            verify_eval_attestation(record, signing_key=self.key), ())

    def test_absent_proposal_id_default_scope_still_works(self):
        record = self.client.sealed_eval(RIGHT)
        self.assertEqual(record["payload"]["scope"], "unscoped")


# ---------------------------------------------------------------------
# (2) S3 — issue_attestation validates before consumption
# ---------------------------------------------------------------------

class IssueAttestationOrderingTests(VerifierFixture):

    def test_bad_proposal_id_refused_pair_not_consumed(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)
        for bad in ("Prop-V1", "prop v1", "p" * 65, "prop\nv1"):
            with self.subTest(bad=bad):
                with self.assertRaises(VerifierProtocolError):
                    self.attester().issue_attestation(
                        proposal_id=bad, baseline_eval=baseline,
                        candidate_eval=candidate,
                        public_baseline_score=0.5,
                        public_candidate_score=0.6)
                self.assertEqual(self.consumption_entries(), [])
        # The genuine pair survived every bad-spelling attempt: a
        # subsequent well-formed issuance with the SAME pair
        # succeeds (and only now consumes it).
        signed = self.attester().issue_attestation(
            proposal_id="prop-v1", baseline_eval=baseline,
            candidate_eval=candidate, public_baseline_score=0.5,
            public_candidate_score=0.6)
        self.assertEqual(signed["attestation"]["decision"], "approve")
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_burn_case_bad_scope_root_pair_not_consumed(self):
        # The literal burn case S3 names: the pair's scope ROOT is
        # itself the bad spelling, so the scope-root check passes
        # and only the late _check_id inside sign_attestation
        # would have caught it — after consumption. Such records
        # can no longer be minted via sealed_eval (S1), so they
        # are built test-side with the fixture key and ledgered
        # directly, as a pre-fix record would have been.
        ledger = SigningLedger(self.home / "ledger")
        records = []
        for scope, correct in (("BADPROP:baseline", 1),
                               ("BADPROP:candidate", 3)):
            record = sign_eval_attestation(
                {"set": "sealed", "version": 1, "n": 3,
                 "correct": correct, "score": correct / 3,
                 "manifest_hash": self.manifest_hash,
                 "evaluated_at": recent()},
                signing_key=self.key, signer_id="seat-3", actor=ACTOR,
                registry_digest="b" * 64, answers_hash="c" * 64,
                scope=scope)
            ledger.append_eval_attestation(record, recorded_at=recent())
            records.append(record)
        with self.assertRaises(VerifierProtocolError):
            self.attester().issue_attestation(
                proposal_id="BADPROP", baseline_eval=records[0],
                candidate_eval=records[1], public_baseline_score=0.5,
                public_candidate_score=0.6)
        self.assertEqual(self.consumption_entries(), [])


# ---------------------------------------------------------------------
# (3) S2 — client validates against the rebuilt canonical payload
# ---------------------------------------------------------------------

class ClientRebuiltPayloadTests(VerifierFixture):

    def validate_via_client(self, record, answers):
        """Run the client's real sealed_eval validation over a
        canned transport result (the record a verifier — honest
        or re-spelling — returned for this transcript)."""
        client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)
        client._run = lambda mode, body: {"attestation": record}
        return client.sealed_eval(answers)

    def test_int_score_record_accepted_by_verify_and_client(self):
        genuine = self.client.sealed_eval(RIGHT)
        self.assertEqual(genuine["payload"]["score"], 1.0)
        # Re-spell the JSON: float 1.0 -> int 1, value unchanged.
        text = json.dumps(genuine)
        self.assertIn('"score": 1.0', text)
        respelled = json.loads(text.replace('"score": 1.0',
                                            '"score": 1'))
        self.assertIsInstance(respelled["payload"]["score"], int)
        # Key-holding verification accepts (existing pinned
        # behaviour) ...
        self.assertEqual(
            verify_eval_attestation(respelled, signing_key=self.key),
            ())
        # ... and now the first-party client accepts the SAME
        # record instead of rejecting it as hash-inconsistent.
        accepted = self.validate_via_client(respelled, RIGHT)
        self.assertEqual(accepted["payload_hash"],
                         genuine["payload_hash"])

    def test_wrong_correct_count_rejected_by_client(self):
        genuine = self.client.sealed_eval(RIGHT)
        tampered = copy.deepcopy(genuine)
        tampered["payload"]["correct"] = 2  # score still claims 1.0
        with self.assertRaises(VerifierProtocolError):
            self.validate_via_client(tampered, RIGHT)

    def test_rebuilt_hash_mismatch_rejected_by_client(self):
        genuine = self.client.sealed_eval(RIGHT)
        tampered = copy.deepcopy(genuine)
        tampered["payload"]["version"] = 999  # rebuilds, hash differs
        with self.assertRaises(VerifierProtocolError):
            self.validate_via_client(tampered, RIGHT)


# ---------------------------------------------------------------------
# (4) S6 — parse_float hooks refuse 1e999 in the parser layer
# ---------------------------------------------------------------------

class NonFiniteParserTests(unittest.TestCase):

    def assert_non_finite_refusal(self, exc_type, fn, text):
        with self.assertRaises(exc_type) as ctx:
            fn(text)
        # "non-finite" in the message proves the refusal came
        # from the parser's parse_float hook, not from a
        # downstream type check that happened to catch inf.
        self.assertIn("non-finite", str(ctx.exception))

    def test_attestation_envelope_from_json_rejects_1e999(self):
        key = make_signing_key(bytes(range(32, 64)))
        attestation = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash="b" * 64, reward_hacking_checked=True,
            evidence_ref="sealed-run-1",
            attested_at="2026-11-20T11:00:00+00:00")
        signed = sign_attestation(
            attestation, signing_key=key, signer_id="seat-3",
            proposal_id="prop-1", now="2026-11-20T12:00:00+00:00")
        raw = attestation_envelope_to_json(signed)
        # Control: the honest document loads.
        attestation_envelope_from_json(raw)
        huge = raw.replace('"manifest_hash":""', '"manifest_hash":1e999')
        self.assertNotEqual(huge, raw)
        self.assert_non_finite_refusal(
            SigningError, attestation_envelope_from_json, huge)

    def _manifest(self, root):
        (root / "core").mkdir(parents=True)
        (root / "core" / "a.py").write_text("A = 1\n")
        (root / "internal").mkdir()
        (root / "internal" / "REVIEW.md").write_text("# review\n")
        return build_manifest(
            root, proposal_id="prop-1", item_id="item-1",
            review_record_path="internal/REVIEW.md", stage="final",
            created_at="2026-11-20T00:00:00+00:00")

    def test_manifest_from_json_rejects_1e999(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(Path(tmp) / "repo")
            raw = manifest.to_json()
            manifest_from_json(raw)  # control
            huge = re.sub(r'"size":\d+', '"size":1e999', raw, count=1)
            self.assertNotEqual(huge, raw)
            self.assert_non_finite_refusal(
                ManifestError, manifest_from_json, huge)

    def test_release_from_json_rejects_1e999(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(Path(tmp) / "repo")
            record = build_release_record(
                manifest, None, expected_cycle_id=3,
                pre_ship_cycle_seq=2, pre_ship_state_sha256="a" * 64)
            raw = record.to_json()
            release_from_json(raw)  # control
            huge = raw.replace('"expected_cycle_id":3',
                               '"expected_cycle_id":1e999')
            self.assertNotEqual(huge, raw)
            self.assert_non_finite_refusal(
                ManifestError, release_from_json, huge)


if __name__ == "__main__":
    unittest.main()
