"""Barrier-synchronised multi-PROCESS sealed_eval contention
(Trust Boundary v3.1, fix round 2, C1).

Regression test for the sealed_eval staleness hole: the
snapshot retry covered the metadata/manifest reads, but the
evaluate save on the snapshot instance was NOT retried, so
under tight multi-process contention a competitor save landing
between snapshot and evaluate surfaced as a nondeterministic
registry_untrusted refusal. The fix retries the evaluation on
FRESH registry instances (budget still recorded exactly once,
before the loop).

This file races N=10 independent OS processes, released
simultaneously by a ready/go-file barrier, each evaluating a
DISTINCT transcript (differing from every other transcript at
ALL positions, so budget replay / near-duplicate detection
cannot interfere) against one shared registry / key / verifier
home through the real VerifierClient. Every worker must
succeed, ZERO outcomes may be registry_untrusted, and the
shared budget identity's recorded usage must equal exactly N
— one recorded query per successful eval, never one per retry.
Fix round 3 extends the assertions to the signing ledger: its
eval-attestation entries must also number exactly N, with N
distinct payload hashes — one per successful eval, so the
ledger-append retry neither loses nor duplicates a record.

Worker discipline: the owned-files constraint for this fix
round allows no new fixture file, so this module doubles as
its own worker — run as ``<this file> worker <spec.json>`` it
performs one barrier-waited sealed_eval and writes an outcome
JSON, mirroring tests/fixtures/issuance_racer.py's contract.
Fixture setup mirrors tests/test_trust_multiprocess_race.py,
with the deployment mode pinned to research and generous query
budgets configured so budgets never interfere with the race:
the budget identity is the verifier's configured actor
(trust/verifier_main.py records under config.actor), shared by
every worker, so the identity cap must accommodate all N evals.
"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.budgets import BudgetStore
from trust.client import VerifierClient
from trust.ledger import SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
N_ITEMS = 20
ITEMS = [(f"sealed-{i:02d}", "contention", f"question {i}?",
          f"expected-{i}") for i in range(N_ITEMS)]
N_WORKERS = 10
SELF = Path(__file__).resolve()


def transcript_for(worker_index):
    """A transcript differing from every other worker's at ALL
    positions (worker tag in every answer), so no two transcripts
    are replays or near-duplicates of each other. All answers are
    wrong against the fixture set (score 0.0); the score VALUE is
    not what this test races — presence of a score is."""
    return [f"w{worker_index}-answer-{j}" for j in range(N_ITEMS)]


# -- worker mode (this file, re-executed per process) ----------------


def _write_outcome(output_path, outcome):
    path = Path(output_path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(outcome))
    tmp.replace(path)


def _worker_main(spec_path):
    """One barrier-waited sealed_eval. Exits 0 always; the
    outcome file is the result, exactly as in issuance_racer."""
    try:
        spec = json.loads(Path(spec_path).read_text())
        output_path = spec["output_path"]
        # Ready/go barrier: announce readiness, then poll for
        # the go file so the launching test can release every
        # worker at the same instant.
        Path(spec["ready_path"]).touch()
        go = Path(spec["go_path"])
        deadline = time.monotonic() + 30.0
        while not go.exists():
            if time.monotonic() >= deadline:
                _write_outcome(output_path, {
                    "outcome": "gate_timeout",
                    "error": "go file did not appear within 30s"})
                return 0
            time.sleep(0.005)
        try:
            client = VerifierClient(
                verifier_env=spec["verifier_env"],
                expected_signer_id=spec["expected_signer_id"],
                expected_key_id=spec["expected_key_id"])
            record = client.sealed_eval(
                spec["answers"], proposal_id=spec["proposal_id"])
            outcome = {"outcome": "ok",
                       "score": record["payload"]["score"]}
        except Exception as exc:  # the refusal text IS the result
            outcome = {"outcome": "refused", "error": str(exc)}
        _write_outcome(output_path, outcome)
    except Exception as exc:  # never hang, never exit nonzero
        print(f"sealed_eval worker: {exc}", file=sys.stderr)
    return 0


# -- test fixture ------------------------------------------------------


class SealedEvalContentionFixture(unittest.TestCase):
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
            # Generous budgets: the shared budget identity (the
            # configured actor) must accommodate every worker's
            # eval, and per-worker proposal scopes stay far from
            # their cap, so budgets cannot interfere with the race.
            "AION_VERIFIER_PROPOSAL_BUDGET": "1000",
            "AION_VERIFIER_IDENTITY_BUDGET": "1000",
        }
        self.race_dir = base / "race"
        self.race_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_contention(self, n_workers):
        """Launch n_workers worker processes, wait until every
        one has signalled ready, release them together via the
        go file, and return the list of outcome dicts."""
        go_path = self.race_dir / "go"
        self.assertFalse(go_path.exists())
        launched = []
        for i in range(n_workers):
            tag = f"worker-{i}"
            spec = {
                "verifier_env": self.env,
                "expected_signer_id": SIGNER,
                "expected_key_id": self.key.key_id,
                "answers": transcript_for(i),
                "proposal_id": f"contention-{i}",
                "output_path": str(self.race_dir / f"{tag}-outcome.json"),
                "ready_path": str(self.race_dir / f"{tag}.ready"),
                "go_path": str(go_path),
            }
            spec_path = self.race_dir / f"{tag}-spec.json"
            spec_path.write_text(json.dumps(spec))
            proc = subprocess.Popen(
                [sys.executable, str(SELF), "worker", str(spec_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            launched.append((tag, proc, Path(spec["output_path"]),
                             Path(spec["ready_path"])))
        # Barrier: every worker must be waiting before release.
        deadline = time.monotonic() + 30.0
        while not all(ready.exists() for _t, _p, _o, ready in launched):
            if time.monotonic() >= deadline:
                for _t, proc, _o, _r in launched:
                    proc.kill()
                self.fail("workers did not all signal ready in 30s")
            time.sleep(0.005)
        go_path.touch()  # release all workers simultaneously
        outcomes = []
        for tag, proc, outcome_path, _ready in launched:
            try:
                _out, err = proc.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.fail(f"worker {tag} did not finish in 90s")
            self.assertEqual(proc.returncode, 0,
                             f"worker {tag} stderr: {err!r}")
            self.assertTrue(outcome_path.exists(),
                            f"worker {tag} wrote no outcome file")
            outcomes.append(json.loads(outcome_path.read_text()))
        return outcomes


class SealedEvalContentionTests(SealedEvalContentionFixture):

    def test_ten_processes_distinct_transcripts_all_succeed(self):
        outcomes = self.run_contention(N_WORKERS)
        self.assertEqual(len(outcomes), N_WORKERS)
        # ZERO registry_untrusted anywhere — the C1 regression.
        for outcome in outcomes:
            self.assertNotIn("registry_untrusted",
                             outcome.get("error", ""), outcomes)
        # Every worker succeeded with a score present.
        oks = [o for o in outcomes if o["outcome"] == "ok"]
        self.assertEqual(len(oks), N_WORKERS, outcomes)
        for outcome in oks:
            self.assertIn("score", outcome)
            self.assertEqual(outcome["score"], 0.0)
        # The budget was recorded exactly once per successful
        # eval under the shared identity — retries inside the
        # verifier never re-record.
        store = BudgetStore(
            self.home / "ledger" / "budgets.json",
            per_proposal_cap=1000, per_identity_cap=1000)
        self.assertEqual(store.identity_count(ACTOR), N_WORKERS)
        # The signing ledger holds exactly one eval-attestation
        # entry per successful eval — the ledger-append retry
        # (fix round 3) must land each record exactly once:
        # no record lost to a lost append race, and no record
        # double-appended by a retry of an append that had in
        # fact landed.
        eval_entries = [
            entry for entry in SigningLedger(
                self.home / "ledger").entries()
            if entry.get("kind") == "sign"
            and entry.get("format") == "sealed-eval"]
        self.assertEqual(len(eval_entries), N_WORKERS, eval_entries)
        self.assertEqual(
            len({entry["payload_hash"] for entry in eval_entries}),
            N_WORKERS, eval_entries)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        sys.exit(_worker_main(sys.argv[2]))
    unittest.main()
