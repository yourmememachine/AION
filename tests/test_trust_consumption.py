"""Tests for single-use consumption of sealed-eval records at
attestation issuance (Trust Boundary v3, item 3, workstream A)
and the budgets-anchor INIT guard (workstream B).

Consumption: issue_attestation verifies two ledgered sealed-eval
records and now CONSUMES both (SigningLedger
.try_consume_eval_records) atomically with the check, before
signing, even when the derived decision is "reject". The gate
path must NOT consume — its evidence_ref flow legitimately
re-presents the records.

Fixture discipline mirrors tests/test_trust_verifier.py: fake
registry + generated key in a temp verifier-home; the builder
side holds the key only to verify outcomes test-side.
"""

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]


def recent(minutes=5):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes)).isoformat()


class ConsumptionFixture(unittest.TestCase):
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

    def eval_records(self, baseline_answers, candidate_answers,
                     *, proposal_id="prop-v1"):
        attester = self.attester()
        return (attester.sealed_eval(
                    baseline_answers,
                    proposal_id=f"{proposal_id}:baseline"),
                attester.sealed_eval(
                    candidate_answers,
                    proposal_id=f"{proposal_id}:candidate"))

    def issue(self, baseline, candidate, *, proposal_id="prop-v1",
              public_before=0.5, public_after=0.6):
        return self.attester().issue_attestation(
            proposal_id=proposal_id, baseline_eval=baseline,
            candidate_eval=candidate,
            public_baseline_score=public_before,
            public_candidate_score=public_after)

    def consumption_entries(self):
        ledger = SigningLedger(self.home / "ledger")
        return [e for e in ledger.entries()
                if e["kind"] == "consume"]

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


class ConsumptionTests(ConsumptionFixture):

    def test_same_pair_twice_second_issuance_refused(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)
        signed = self.issue(baseline, candidate)
        self.assertEqual(signed["attestation"]["decision"], "approve")
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, candidate)
        self.assertIn("eval_evidence_consumed", str(ctx.exception))

    def test_record_reused_across_different_pairs_refused(self):
        # Baseline consumed by a first issuance; pairing the SAME
        # baseline record with a FRESH candidate must still refuse.
        # Transcripts are pairwise far (>= 3 differing positions
        # where the 3-item set allows) so budget probe detection
        # is not what refuses anything here.
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], ["nope", "9", "nope-2"])
        self.issue(baseline, candidate)
        fresh_candidate = self.attester().sealed_eval(
            ["x1", "x2", "3.14"], proposal_id="prop-v1:candidate")
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, fresh_candidate)
        self.assertIn("eval_evidence_consumed", str(ctx.exception))

    def test_concurrent_issuance_exactly_one_succeeds(self):
        # Two verifier subprocesses race issue_attestation on the
        # SAME pair. Exactly one may sign; the other must be
        # refused eval_evidence_consumed. This outcome holds
        # whether the processes truly overlap (the loser's
        # optimistic-concurrency retry reload finds the pair
        # consumed) or merely interleave (the loser's fresh load
        # finds it consumed) — there is no interleaving in which
        # both succeed.
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)

        def attempt(_i):
            try:
                signed = self.issue(baseline, candidate)
                return ("ok", signed["attestation"]["decision"])
            except VerifierConfigError as exc:
                return ("refused", str(exc))

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        oks = [o for o in outcomes if o[0] == "ok"]
        refused = [o for o in outcomes if o[0] == "refused"]
        self.assertEqual(len(oks), 1, outcomes)
        self.assertEqual(len(refused), 1, outcomes)
        self.assertIn("eval_evidence_consumed", refused[0][1])
        # And exactly one consumption pair landed in the ledger.
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_consumption_entries_shape(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)
        self.issue(baseline, candidate)
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 2)
        by_hash = {e["payload_hash"]: e for e in entries}
        self.assertEqual(set(by_hash),
                         {baseline["payload_hash"],
                          candidate["payload_hash"]})
        for record_hash, entry in by_hash.items():
            self.assertEqual(entry["decision_id"], record_hash)
            self.assertEqual(entry["format"], "eval-consumption")
            self.assertEqual(entry["purpose"],
                             "attestation-consumption")
            self.assertEqual(entry["proposal_id"], "prop-v1")
            self.assertFalse(entry["accepted"])
            self.assertEqual(entry["signer_id"], "seat-3")

    def test_gate_flow_still_works_with_consumed_records(self):
        # Issue (consumes both records), then present the SAME
        # records at the gate via the attestation's evidence_ref
        # flow: the gate must accept end-to-end. Gate reuse is
        # safe because the records are bound to this one
        # attestation by evidence_ref + scope + signer checks.
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)
        signed = self.issue(baseline, candidate)
        self.assertEqual(len(self.consumption_entries()), 2)
        body = self.gate_body()
        body["attestation"] = signed["attestation"]
        body["signed_attestation"] = signed
        body["eval_evidence"] = {"baseline": baseline,
                                 "candidate": candidate}
        body["baseline_sealed"] = {
            "sealed": baseline["payload"]["score"]}
        body["candidate_sealed"] = {
            "sealed": candidate["payload"]["score"]}
        outcome = self.client.gate(body)
        self.assertTrue(outcome.accepted)
        # The gate itself consumed nothing further.
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_reject_decision_issuance_still_consumes(self):
        # Sealed regression derives a reject; the evidence was
        # spent either way, so a second issuance of the same pair
        # is refused even though the first only produced a reject.
        baseline, candidate = self.eval_records(
            RIGHT, ["wrong", "wrong", "wrong"])
        signed = self.issue(baseline, candidate,
                            public_before=0.5, public_after=0.5)
        self.assertEqual(signed["attestation"]["decision"], "reject")
        self.assertEqual(len(self.consumption_entries()), 2)
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, candidate,
                       public_before=0.5, public_after=0.5)
        self.assertIn("eval_evidence_consumed", str(ctx.exception))


class LedgerConsumeUnitTests(unittest.TestCase):
    """Direct unit tests for the ledger method's retry contract."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "ledger"

    def ledger(self):
        return SigningLedger(self.dir)

    def test_consume_then_reconsume_returns_false(self):
        ledger = self.ledger()
        self.assertTrue(ledger.try_consume_eval_records(
            ["a" * 64, "b" * 64], proposal_id="prop-v1",
            signer_id="seat-3", recorded_at=recent()))
        self.assertFalse(ledger.try_consume_eval_records(
            ["a" * 64, "c" * 64], proposal_id="prop-v1",
            signer_id="seat-3", recorded_at=recent()))
        # The refused second call appended nothing for "c"*64.
        consumed = [e["payload_hash"] for e in ledger.entries()
                    if e["kind"] == "consume"]
        self.assertEqual(sorted(consumed), ["a" * 64, "b" * 64])

    def test_stale_instance_retries_and_sees_consumption(self):
        # Two ledger instances loaded from the same snapshot: the
        # first consumes; the second's save hits the journal's
        # optimistic-concurrency check, reloads, and must report
        # the pair as consumed rather than double-consume it.
        first = self.ledger()
        stale = self.ledger()
        self.assertTrue(first.try_consume_eval_records(
            ["a" * 64, "b" * 64], proposal_id="prop-v1",
            signer_id="seat-3", recorded_at=recent()))
        self.assertFalse(stale.try_consume_eval_records(
            ["a" * 64, "b" * 64], proposal_id="prop-v1",
            signer_id="seat-3", recorded_at=recent()))
        consumed = [e for e in self.ledger().entries()
                    if e["kind"] == "consume"]
        self.assertEqual(len(consumed), 2)


if __name__ == "__main__":
    unittest.main()
