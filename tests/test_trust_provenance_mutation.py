"""Provenance one-at-a-time dependency-mutation demo
(Trust Boundary v3.1, item 7; CROSS-CHECK-5 item 7).

The provenance chain binds an attestation to EVERY dependency
it was derived from: the live registry manifest, the signing
key, the signer identity, the signing ledger's record of the
eval records, and the pair's ledger order. This file starts
from a genuinely valid setup — a control test proves the
unmutated pair issues successfully — and then mutates exactly
ONE dependency per test. Each mutation must refuse issuance
(VerifierConfigError carrying the specific code), sign nothing,
and consume nothing: consumption happens only after pair
verification, so a refused issuance leaves the pair unspent.

Relationship to tests/test_trust_provenance.py (checked before
writing):
* (a) is a STRENGTHENED DUPLICATE of the provenance file's
  registry-growth case (test_records_from_registry_v1_refused_
  after_registry_grows): same scenario — a legitimate registry
  growth after evaluation; this version additionally pins the
  refusal code (eval_evidence_unverifiable) and zero
  consumption, where the provenance file's version asserts
  only the exception type (and no new signatures).
* (b)–(f) are distinct from the provenance file's cases.
  (b) is deliberately NOT the provenance file's in-place
  registry.json tamper nor its foreign-registry candidate
  (different item ids, single foreign record): here BOTH
  records are minted against registry copy A and issuance is
  pointed at a separately built registry copy B with the SAME
  item ids and one differing expected answer.
* (c) is the inverse direction of the provenance cross-key
  case: there foreign records are presented to this key's
  verifier; here this service's own records are presented to a
  verifier configured with a DIFFERENT key file.
* (d) signer-identity mutation, (e) empty-ledger presentation
  and (f) pair-order swap have no counterpart in the provenance
  file.

Fixture discipline mirrors tests/test_trust_provenance.py, with
the deployment mode pinned explicitly from the start:
AION_DEPLOYMENT_MODE=research, and no anchors configured —
the demo runs in research mode against an unanchored
deployment; the provenance bindings it exercises are
mode-independent (the same checks run in production mode
before any production-only gate).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ATTESTER = "seat-3"
OTHER_SIGNER = "seat-9"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]
BASELINE_ANSWERS = ["4", "wrong", "wrong"]


class MutationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
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

    def tearDown(self):
        self.tmp.cleanup()

    # -- harness helpers ----------------------------------------------

    def attester(self, env_over=None, *, signer=ATTESTER, key_id=None):
        """Issuing client: seat-3 by default, same key/ledger/
        registry as the fixture unless env_over mutates exactly
        one of them. Pins follow the mutated configuration, so a
        refusal can only come from the verifier, never from a
        client-side pin mismatch on a success path."""
        env = dict(self.env, AION_VERIFIER_SIGNER_ID=signer)
        if env_over:
            env.update(env_over)
        return VerifierClient(
            verifier_env=env, expected_signer_id=signer,
            expected_key_id=self.key.key_id if key_id is None
            else key_id)

    def eval_records(self, *, proposal_id="prop-v1"):
        attester = self.attester()
        return (attester.sealed_eval(
                    BASELINE_ANSWERS,
                    proposal_id=f"{proposal_id}:baseline"),
                attester.sealed_eval(
                    RIGHT,
                    proposal_id=f"{proposal_id}:candidate"))

    def issue(self, baseline, candidate, client=None,
              *, proposal_id="prop-v1"):
        return (client or self.attester()).issue_attestation(
            proposal_id=proposal_id, baseline_eval=baseline,
            candidate_eval=candidate,
            public_baseline_score=0.5, public_candidate_score=0.6)

    def ledger_dir(self):
        return self.home / "ledger"

    def entries(self, ledger_dir=None):
        return SigningLedger(ledger_dir or self.ledger_dir()).entries()

    def sign_entries(self, ledger_dir=None):
        return [e for e in self.entries(ledger_dir)
                if e["kind"] == "sign"]

    def attestation_signs(self, ledger_dir=None):
        return [e for e in self.sign_entries(ledger_dir)
                if e["format"] == "verifier-attestation"]

    def consumption_entries(self, ledger_dir=None):
        return [e for e in self.entries(ledger_dir)
                if e["kind"] == "consume"]

    def assert_refused_clean(self, baseline, candidate, code, *,
                             client=None, ledger_dir=None,
                             detail=None):
        """Issuance of the pair via client must refuse with the
        specific code, add no signature of any kind to the
        relevant ledger, and consume nothing. When `detail` is
        given, the refusal's DETAIL substring is pinned as well:
        the code eval_evidence_unverifiable is overloaded across
        cases (a)–(d), so the code alone does not prove that
        THIS case's mutated dependency caused the refusal — the
        discriminating detail substring does."""
        signs_before = self.sign_entries(ledger_dir)
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, candidate, client=client)
        self.assertIn(code, str(ctx.exception))
        if detail is not None:
            self.assertIn(detail, str(ctx.exception))
        self.assertEqual(self.sign_entries(ledger_dir), signs_before)
        self.assertEqual(self.consumption_entries(ledger_dir), [])
        return str(ctx.exception)


class ControlTests(MutationFixture):
    """The unmutated setup genuinely issues: every mutation test
    below differs from THIS by exactly one dependency."""

    def test_control_unmutated_pair_issues(self):
        baseline, candidate = self.eval_records()
        signed = self.issue(baseline, candidate)
        self.assertEqual(signed["attestation"]["decision"], "approve")
        self.assertEqual(len(self.attestation_signs()), 1)
        self.assertEqual(len(self.consumption_entries()), 2)


class DependencyMutationTests(MutationFixture):

    def test_a_registry_grows_after_evaluation_refused(self):
        baseline, candidate = self.eval_records()
        # Single mutation: a 4th sealed item is added through the
        # registry's own API AFTER the pair was minted, so the
        # live manifest no longer matches the records' binding.
        registry = EvalRegistry(self.registry_dir)
        registry.add_sealed_item("sealed-4", "algebra", "1+1?", "2",
                                 "test-actor")
        self.assertNotEqual(registry.sealed_manifest_hash(ACTOR),
                            self.manifest_hash)
        self.assert_refused_clean(
            baseline, candidate, "eval_evidence_unverifiable",
            detail="bound to a different sealed manifest")

    def test_b_issuance_against_swapped_registry_copy_refused(self):
        baseline, candidate = self.eval_records()
        # Registry copy B: built legitimately through the API with
        # the SAME item ids/domains/prompts, but sealed-1's
        # expected answer differs — so B's manifest differs from
        # the manifest both records are bound to.
        other_dir = self.base / "registry-b"
        other = EvalRegistry(other_dir)
        for item_id, domain, prompt, expected in ITEMS:
            other.add_sealed_item(
                item_id, domain, prompt,
                "5" if item_id == "sealed-1" else expected,
                "test-actor")
        self.assertNotEqual(other.sealed_manifest_hash(ACTOR),
                            self.manifest_hash)
        self.assertEqual(baseline["payload"]["manifest_hash"],
                         self.manifest_hash)
        # Single mutation: only the attester env's registry
        # pointer moves from A to B. Key, signer and ledger home
        # are unchanged, so the records are MAC-valid and
        # ledgered — the manifest binding alone refuses.
        client = self.attester(
            env_over={"AION_REGISTRY_DIR": str(other_dir)})
        self.assert_refused_clean(
            baseline, candidate, "eval_evidence_unverifiable",
            client=client,
            detail="bound to a different sealed manifest")

    def test_c_different_key_file_refused(self):
        baseline, candidate = self.eval_records()
        home2 = self.base / "verifier-home-2"
        home2.mkdir()
        home2.chmod(0o700)
        key2 = generate_key_file(home2 / "gate.key")
        self.assertNotEqual(key2.key_id, self.key.key_id)
        # Single mutation: the issuing verifier loads a DIFFERENT
        # key file under the SAME signer id (same registry, same
        # ledger home — the records ARE ledgered there, so only
        # the MAC/key binding can refuse them).
        client = self.attester(
            env_over={"AION_VERIFIER_KEY_PATH": str(home2 / "gate.key")},
            key_id=key2.key_id)
        self.assert_refused_clean(
            baseline, candidate, "eval_evidence_unverifiable",
            client=client,
            detail="failed verification: "
                   "unknown_key,signature_mismatch")

    def test_d_different_signer_id_refused(self):
        baseline, candidate = self.eval_records()
        # Single mutation: the issuing verifier is configured with
        # a different signer id than the records' signer (seat-3).
        # Same key, same registry, same ledger home.
        client = self.attester(signer=OTHER_SIGNER)
        self.assert_refused_clean(
            baseline, candidate, "eval_evidence_unverifiable",
            client=client,
            detail="failed verification: signer_mismatch")

    def test_e_empty_ledger_home_refused_not_ledgered(self):
        baseline, candidate = self.eval_records()
        home_b = self.base / "verifier-home-b"
        home_b.mkdir()
        home_b.chmod(0o700)
        ledger_b = home_b / "ledger"
        # Single mutation: the pair — minted and ledgered in home
        # A — is presented to a verifier whose home B has an EMPTY
        # signing ledger. Same key, same signer, same registry:
        # MAC, signer and manifest all verify, so the refusal is
        # precisely the missing ledger entries.
        client = self.attester(
            env_over={"AION_VERIFIER_HOME": str(ledger_b)})
        signs_a_before = self.sign_entries()
        self.assert_refused_clean(baseline, candidate,
                                  "eval_record_not_ledgered",
                                  client=client, ledger_dir=ledger_b)
        # Nothing was signed or consumed in home A either.
        self.assertEqual(self.sign_entries(), signs_a_before)
        self.assertEqual(self.consumption_entries(), [])

    def test_f_swapped_pair_order_refused(self):
        baseline, candidate = self.eval_records()
        # Single mutation: the pair is presented in reverse —
        # candidate as baseline, baseline as candidate. Both
        # records verify individually, but the baseline record
        # must precede the candidate in the signing ledger, and
        # here the presented "baseline" was ledgered AFTER the
        # presented "candidate". The verifier's actual code for
        # this is eval_evidence_out_of_order.
        signs_before = self.sign_entries()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(candidate, baseline)
        self.assertIn("eval_evidence_out_of_order",
                      str(ctx.exception))
        self.assertEqual(self.sign_entries(), signs_before)
        self.assertEqual(self.consumption_entries(), [])


if __name__ == "__main__":
    unittest.main()
