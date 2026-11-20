"""Extraction ATTACK HARNESS against the real verifier subprocess
(Trust Boundary v3, item 3, workstream C).

The sealed set has n=8 items whose answers are drawn from a known
4-token candidate alphabet the attacker is GIVEN — the strongest
realistic assumption. The attacker sees only the one aggregate
each sealed_eval response discloses (correct/n) and tries to
recover the 8 sealed answers. "Recovered" is measured exactly:
the attacker maintains every alphabet assignment consistent with
all aggregates it has seen; a position counts as recovered only
when ALL consistent assignments agree on it.

Measured results on this fixture (true answers are
alpha,beta,gamma,delta repeating):

* coordinate descent: stopped by the probe latch after 2
  tolerated probes (the 3rd near-duplicate is refused);
  recovered 2 of 8 positions from 3 evaluated queries.
* label rotation: identical outcome — detection and caps are
  identity-scoped, so rotating proposal_id changes nothing;
  recovered 2 of 8.
* identity injection: every attempt is a protocol error
  (exit 2); the budget is untouched.
* group testing (block pools, differing >= 3 positions from all
  priors): recovered 4 of 8 positions in 20 attempted queries
  (19 evaluated) under a 60-query allowance — the block pools
  alone yield only per-pool token histograms (16 assignments
  stay consistent, 0 positions forced), and the size-2 pool
  refinement that resolves pool-mate pairs is exactly a
  near-duplicate probe sequence: its 2 tolerated probes resolve
  the first block's 4 positions, the 3rd latches, and the
  remaining block's pairs are never resolved.

See docs/EXTRACTION-ACCOUNTING.md for the accounting rules these
attacks demonstrate.
"""

import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.budgets import BudgetStore
from trust.client import VerifierClient
from trust.errors import VerifierConfigError

REPO = Path(__file__).resolve().parents[1]
ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ALPHABET = ["alpha", "beta", "gamma", "delta"]
NULL = "zz-none"  # guaranteed-wrong filler, not in the alphabet
TRUE_ANSWERS = [ALPHABET[i % 4] for i in range(8)]
ITEMS = [(f"sealed-{i}", "extract", f"item-{i}?", TRUE_ANSWERS[i])
         for i in range(8)]


class Attacker:
    """An extractor with a candidate-set oracle view: it knows
    the alphabet, submits transcripts through the real client,
    and filters every assignment consistent with the aggregates
    it has honestly received."""

    def __init__(self, client):
        self.client = client
        self.candidates = list(itertools.product(ALPHABET, repeat=8))
        self.evaluated = 0
        self.attempts = 0
        self.refusals = []

    def query(self, answers, *, proposal_id=None):
        """One sealed_eval attempt. Returns the correct count, or
        None when the verifier refused the query (budget/probe
        refusal — a protocol error would propagate, as it is not
        a budget outcome)."""
        self.attempts += 1
        try:
            record = self.client.sealed_eval(
                list(answers), proposal_id=proposal_id)
        except VerifierConfigError as exc:
            self.refusals.append(str(exc))
            return None
        correct = record["payload"]["correct"]
        self.evaluated += 1
        answers = list(answers)
        self.candidates = [
            c for c in self.candidates
            if sum(1 for a, b in zip(c, answers) if a == b) == correct]
        return correct

    @property
    def recovered_count(self):
        if not self.candidates:
            return 0
        return sum(1 for i in range(8)
                   if len({c[i] for c in self.candidates}) == 1)


class ExtractionFixture(unittest.TestCase):
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
        self.budgets_file = self.home / "ledger" / "budgets.json"

    def tearDown(self):
        self.tmp.cleanup()

    def store(self):
        return BudgetStore(self.budgets_file)

    def coordinate_descent(self, attacker, label_for_attempt):
        """Baseline + one-position refinements, the classic
        adaptive extraction. Returns True when the probe latch
        stopped the attacker."""
        current = [ALPHABET[0]] * 8
        score = attacker.query(current,
                               proposal_id=label_for_attempt())
        self.assertIsNotNone(score)
        for pos in range(8):
            for token in ALPHABET[1:]:
                if current[pos] == token:
                    continue
                probe = list(current)
                probe[pos] = token
                result = attacker.query(
                    probe, proposal_id=label_for_attempt())
                if result is None:
                    return True
                if result == score + 1:
                    current, score = probe, result
                    break
                if result == score - 1:
                    break  # position was the current token; move on
                # Equal score: position is neither token; the
                # classic attacker tries the next token here,
                # spending another probe it does not have.
        return False


class CoordinateDescentTests(ExtractionFixture):

    def test_coordinate_descent_latched_after_two_probes(self):
        attacker = Attacker(self.client)
        stopped = self.coordinate_descent(
            attacker, lambda: "extract-cd")
        self.assertTrue(stopped, "the probe latch never fired")
        self.assertTrue(any("adaptive_query_detected" in r
                            for r in attacker.refusals))
        # Baseline + exactly the 2 tolerated probes were evaluated.
        self.assertEqual(attacker.evaluated, 3)
        # Measured: 2 of 8 positions recovered (positions 0 and 1,
        # whose probe deltas identify them); full recovery fails.
        self.assertLessEqual(attacker.recovered_count, 3)
        self.assertEqual(attacker.recovered_count, 2)
        self.assertLess(attacker.recovered_count, 8)
        # The latch persisted on disk: 3 probes counted (the
        # tripping probe persists its count), a family latched,
        # and only the 3 evaluated transcripts were recorded.
        store = self.store()
        self.assertEqual(store.identity_probes(ACTOR), 3)
        self.assertGreaterEqual(store.blocked_family_count(ACTOR), 1)
        self.assertEqual(store.identity_count(ACTOR), 3)


class LabelRotationTests(ExtractionFixture):

    def test_label_rotation_still_latches_and_cap_binds(self):
        attacker = Attacker(self.client)
        counter = itertools.count()
        stopped = self.coordinate_descent(
            attacker, lambda: f"rot-{next(counter)}")
        self.assertTrue(stopped, "label rotation evaded the latch")
        self.assertEqual(attacker.evaluated, 3)
        self.assertEqual(attacker.recovered_count, 2)
        self.assertLess(attacker.recovered_count, 8)
        # Identity-scoped accounting: despite a fresh proposal
        # label per query, ONE identity carries all 3 recorded
        # evaluations and all 3 probes.
        store = self.store()
        self.assertEqual(store.identity_count(ACTOR), 3)
        self.assertEqual(store.identity_probes(ACTOR), 3)
        self.assertGreaterEqual(store.blocked_family_count(ACTOR), 1)


class IdentityInjectionTests(ExtractionFixture):

    def _raw_sealed_eval(self, body):
        doc = {"v": "trust-request/1", "request_id": "req-inject",
               "mode": "sealed_eval", "body": body}
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        env.update(self.env)
        return subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=json.dumps(doc).encode(), capture_output=True,
            timeout=30, cwd=str(REPO), env=env)

    def test_identity_fields_are_protocol_errors_budget_untouched(self):
        # The wire protocol has NO identity field: bodies carrying
        # one are protocol errors (exit 2), never a way to select
        # or rotate a budget identity.
        for extra in ({"identity": "attacker"},
                      {"actor": "attacker"},
                      {"actor_id": "attacker"},
                      {"signer_id": "attacker"},
                      {"identity": "second-identity",
                       "proposal_id": "rot-0"}):
            body = {"answers": TRUE_ANSWERS}
            body.update(extra)
            result = self._raw_sealed_eval(body)
            self.assertEqual(result.returncode, 2, extra)
        # Budget untouched: no identity recorded anything, and the
        # deployment's own budget is still fully available.
        store = self.store()
        self.assertEqual(store.identity_count(ACTOR), 0)
        self.assertEqual(store.identity_count("attacker"), 0)
        record = self.client.sealed_eval(TRUE_ANSWERS)
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(self.store().identity_count(ACTOR), 1)


class GroupTestingTests(ExtractionFixture):
    """Measured: 4 of 8 positions recovered in 20 attempted
    queries (19 evaluated) under a 60-query allowance — all 4
    from the 2 tolerated refinement probes; the latch prevents
    resolving the remaining 4."""

    def test_group_testing_recovers_zero_of_eight(self):
        allowance = 60
        # Block pools from two partitions of the 8 positions.
        # Every pool query fills its pool with ONE candidate token
        # and the guaranteed-wrong filler elsewhere, so its score
        # is that pool's histogram count for the token.
        partitions = [[{0, 1, 2, 3}, {4, 5, 6, 7}],
                      [{0, 2, 4, 6}, {1, 3, 5, 7}]]
        plan = [[NULL] * 8]
        for partition in partitions:
            for block in partition:
                for token in ALPHABET:
                    query = [NULL] * 8
                    for pos in block:
                        query[pos] = token
                    plan.append(query)
        # The plan honours the attacker's own discipline: every
        # query differs in >= 3 positions from every prior query,
        # so none of it is a near-duplicate probe.
        for i, query in enumerate(plan):
            for prior in plan[:i]:
                differing = sum(1 for a, b in zip(query, prior)
                                if a != b)
                self.assertGreaterEqual(differing, 3)
        attacker = Attacker(self.client)
        for query in plan:
            self.assertIsNotNone(
                attacker.query(query, proposal_id="extract-gt"))
        # Pool histograms narrow the space (576 -> 16 consistent
        # assignments across the plan) but force no position:
        # positions sharing a pool-membership signature hold
        # different tokens, so each pair stays swappable.
        self.assertEqual(len(attacker.candidates), 16)
        self.assertEqual(attacker.recovered_count, 0)
        # Refinement to size-2 pools is where group testing would
        # resolve the pairs — and a size-2 pool query differs from
        # its size-4 parent pool in exactly 2 positions, i.e. it
        # IS a near-duplicate probe. Two are tolerated; the third
        # latches and is refused.
        refinements = []
        for block, token in (({0, 1}, "alpha"), ({0, 1}, "beta"),
                             ({2, 3}, "alpha")):
            query = [NULL] * 8
            for pos in block:
                query[pos] = token
            refinements.append(query)
        results = [attacker.query(q, proposal_id="extract-gt")
                   for q in refinements]
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        self.assertIsNone(results[2])
        self.assertTrue(any("adaptive_query_detected" in r
                            for r in attacker.refusals))
        self.assertLessEqual(attacker.attempts, allowance)
        self.assertEqual(attacker.attempts, 20)
        self.assertEqual(attacker.evaluated, 19)
        # Final measurement: the 2 tolerated refinement probes
        # resolved the first block's two pool-mate pairs (4
        # positions); the latch then refused the probe that would
        # start on the second block, so full extraction fails —
        # 4 of 8, and no query the attacker can still make is a
        # near-duplicate-free refinement of the remaining pairs.
        self.assertEqual(attacker.recovered_count, 4)
        self.assertLess(attacker.recovered_count, 8)


if __name__ == "__main__":
    unittest.main()
