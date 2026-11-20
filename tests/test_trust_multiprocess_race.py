"""Multi-PROCESS consumption race (Trust Boundary v3.1, item 3;
CROSS-CHECK-5 item 2/3).

The thread race in tests/test_trust_consumption.py shares one
interpreter; this file races INDEPENDENT OS processes instead:
each racer is tests/fixtures/issuance_racer.py launched via
subprocess.Popen on sys.executable, released simultaneously by
a start-gate file, attempting issue_attestation on the same
sealed-eval pair through the real verifier subprocess. Exactly
one process may sign; every loser must be refused with the
DETERMINISTIC code eval_evidence_consumed (the registry-retry /
precedence fix is what makes the code deterministic — a loser
must never surface a contention artefact such as ledger_failed
or registry_untrusted instead), exactly one consumption pair
may land in the signing ledger, and a later serial issuance of
the same pair is refused as consumed.

Fixture discipline mirrors tests/test_trust_consumption.py
(ConsumptionFixture), with the deployment mode pinned explicitly
from the start: AION_DEPLOYMENT_MODE=research.
"""

import json
import subprocess
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
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]
RACER = Path(__file__).resolve().parent / "fixtures" / "issuance_racer.py"

# Pair-B transcripts for the two-pair race: the budget store
# refuses a byte-identical transcript replay identity-wide and
# counts near-duplicates (<= 2 differing positions on this
# 3-item set) as probes, so pair B is built pairwise FAR from
# pair A and from itself — every transcript differs from every
# other at all 3 positions. Pair B therefore scores 0 -> 0;
# with flat public scores the derived decision is still approve.
PAIR_B_BASELINE = ["b-zero", "b-one", "b-two"]
PAIR_B_CANDIDATE = ["c-zero", "c-one", "c-two"]


class RaceFixture(unittest.TestCase):
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
        self.race_dir = base / "race"
        self.race_dir.mkdir()
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)

    def tearDown(self):
        self.tmp.cleanup()

    def attester_env(self):
        return dict(self.env, AION_VERIFIER_SIGNER_ID=ATTESTER)

    def attester(self):
        return VerifierClient(
            verifier_env=self.attester_env(),
            expected_signer_id=ATTESTER,
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

    # -- race harness -------------------------------------------------

    def _spec(self, tag, baseline, candidate, *, proposal_id,
              public_before, public_after, gate_path):
        baseline_path = self.race_dir / f"{tag}-baseline.json"
        candidate_path = self.race_dir / f"{tag}-candidate.json"
        baseline_path.write_text(json.dumps(baseline))
        candidate_path.write_text(json.dumps(candidate))
        spec = {
            "verifier_env": self.attester_env(),
            "expected_signer_id": ATTESTER,
            "expected_key_id": self.key.key_id,
            "baseline_path": str(baseline_path),
            "candidate_path": str(candidate_path),
            "proposal_id": proposal_id,
            "public_baseline_score": public_before,
            "public_candidate_score": public_after,
            "output_path": str(self.race_dir / f"{tag}-outcome.json"),
            "start_gate_path": str(gate_path),
        }
        spec_path = self.race_dir / f"{tag}-spec.json"
        spec_path.write_text(json.dumps(spec))
        return spec_path, Path(spec["output_path"])

    def run_race(self, jobs):
        """Launch every job's racer process first, THEN create the
        start gate so all of them are released together, wait for
        completion (bounded), and return {tag: outcome dict}.
        jobs: list of dicts with keys tag, baseline, candidate,
        proposal_id, public_before, public_after."""
        gate_path = self.race_dir / "start.gate"
        self.assertFalse(gate_path.exists())
        launched = []
        for job in jobs:
            spec_path, outcome_path = self._spec(
                job["tag"], job["baseline"], job["candidate"],
                proposal_id=job["proposal_id"],
                public_before=job["public_before"],
                public_after=job["public_after"],
                gate_path=gate_path)
            proc = subprocess.Popen(
                [sys.executable, str(RACER), str(spec_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            launched.append((job["tag"], proc, outcome_path))
        gate_path.touch()  # release all racers simultaneously
        outcomes = {}
        for tag, proc, outcome_path in launched:
            try:
                _out, err = proc.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.fail(f"racer {tag} did not finish in 90s")
            self.assertEqual(proc.returncode, 0,
                             f"racer {tag} stderr: {err!r}")
            self.assertTrue(outcome_path.exists(),
                            f"racer {tag} wrote no outcome file")
            outcomes[tag] = json.loads(outcome_path.read_text())
        return outcomes


class MultiprocessRaceTests(RaceFixture):

    def test_four_processes_one_pair_exactly_one_succeeds(self):
        baseline, candidate = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT)
        # Four independent processes, identical issuance specs
        # (same env, pair, proposal and scores; only the outcome
        # file differs, so no racer can overwrite another's result).
        jobs = [dict(tag=f"racer-{i}", baseline=baseline,
                     candidate=candidate, proposal_id="prop-v1",
                     public_before=0.5, public_after=0.6)
                for i in range(4)]
        outcomes = self.run_race(jobs)
        results = list(outcomes.values())
        oks = [o for o in results if o["outcome"] == "ok"]
        refused = [o for o in results if o["outcome"] == "refused"]
        self.assertEqual(len(oks), 1, outcomes)
        self.assertEqual(oks[0]["decision"], "approve")
        self.assertEqual(len(refused), 3, outcomes)
        for outcome in refused:
            # Deterministic post-fix: EVERY loser reports the
            # consumption refusal, never a contention artefact.
            self.assertIn("eval_evidence_consumed", outcome["error"],
                          outcomes)
        # Exactly one consumption pair landed in the ledger.
        self.assertEqual(len(self.consumption_entries()), 2)
        # And the pair stays spent for a later serial issuance.
        with self.assertRaises(VerifierConfigError) as ctx:
            self.issue(baseline, candidate)
        self.assertIn("eval_evidence_consumed", str(ctx.exception))

    def test_four_processes_two_disjoint_pairs_one_success_each(self):
        baseline_a, candidate_a = self.eval_records(
            ["4", "wrong", "wrong"], RIGHT, proposal_id="prop-race-a")
        baseline_b, candidate_b = self.eval_records(
            PAIR_B_BASELINE, PAIR_B_CANDIDATE,
            proposal_id="prop-race-b")
        jobs = [
            dict(tag="a-0", baseline=baseline_a, candidate=candidate_a,
                 proposal_id="prop-race-a",
                 public_before=0.5, public_after=0.6),
            dict(tag="a-1", baseline=baseline_a, candidate=candidate_a,
                 proposal_id="prop-race-a",
                 public_before=0.5, public_after=0.6),
            dict(tag="b-0", baseline=baseline_b, candidate=candidate_b,
                 proposal_id="prop-race-b",
                 public_before=0.5, public_after=0.5),
            dict(tag="b-1", baseline=baseline_b, candidate=candidate_b,
                 proposal_id="prop-race-b",
                 public_before=0.5, public_after=0.5),
        ]
        outcomes = self.run_race(jobs)
        for pair in ("a", "b"):
            results = [outcomes[f"{pair}-0"], outcomes[f"{pair}-1"]]
            oks = [o for o in results if o["outcome"] == "ok"]
            refused = [o for o in results if o["outcome"] == "refused"]
            self.assertEqual(len(oks), 1, outcomes)
            self.assertEqual(oks[0]["decision"], "approve")
            self.assertEqual(len(refused), 1, outcomes)
            self.assertIn("eval_evidence_consumed",
                          refused[0]["error"], outcomes)
        # One consumption pair per proposal: four entries total.
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 4)
        self.assertEqual(
            {e["proposal_id"] for e in entries},
            {"prop-race-a", "prop-race-b"})


if __name__ == "__main__":
    unittest.main()
