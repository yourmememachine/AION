"""Unit tests for the Cycle 35 principle engine (memory/principles.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.heldout35 import fewshot_prompt
from memory.principles import (
    Principle,
    TransferMemoryEngine,
    derive_principles,
    features,
    induce_program,
    learn_from_failure,
    self_check_principle,
    sequence_diagnostics,
)
from eval.factory import generate_batch


class DiagnosticsTests(unittest.TestCase):
    def test_additive_detected(self):
        d = sequence_diagnostics([2, 5, 8, 11])
        self.assertTrue(d["sufficient_data"])
        self.assertTrue(d["additive"])
        self.assertFalse(d["multiplicative"])

    def test_multiplicative_detected(self):
        d = sequence_diagnostics([3, 6, 12, 24])
        self.assertTrue(d["multiplicative"])
        self.assertFalse(d["additive"])

    def test_constant_sequence_is_ambiguous(self):
        d = sequence_diagnostics([5, 5, 5, 5])
        self.assertTrue(d["additive"])
        self.assertTrue(d["multiplicative"])
        self.assertTrue(d["ambiguous"])

    def test_zero_blocks_ratio(self):
        d = sequence_diagnostics([0, 2, 4, 6])
        self.assertTrue(d["additive"])
        self.assertFalse(d["multiplicative"])

    def test_negative_ratio(self):
        d = sequence_diagnostics([3, -6, 12, -24])
        self.assertTrue(d["multiplicative"])
        self.assertFalse(d["additive"])

    def test_short_sequence_insufficient(self):
        d = sequence_diagnostics([1, 2])
        self.assertFalse(d["sufficient_data"])

    def test_float_tolerance(self):
        d = sequence_diagnostics([1.0, 1.1, 1.21, 1.331])
        self.assertTrue(d["multiplicative"])

    def test_neither(self):
        d = sequence_diagnostics([1, 4, 9, 16])
        self.assertFalse(d["additive"])
        self.assertFalse(d["multiplicative"])
        self.assertTrue(d["constant_second_difference"])


def _additive_principle():
    return Principle(
        id="seq-add", program=("extrap_add",), shape="sequence-next",
        ratio_mode="additive_diff",
        invariants=frozenset({"diag_additive"}),
        positives_features=[features([2, 4, 6, 8]),
                            features([10, 15, 20, 25])],
        n_pos=16, n_neg=0)


class GuardTests(unittest.TestCase):
    def test_trap_gets_named_failure_code(self):
        ok, passed, failed = self_check_principle(
            _additive_principle(), [3, 6, 12, 24, 48])
        self.assertFalse(ok)
        self.assertIn("trap_mismatch:multiplicative_progression", failed)

    def test_legitimate_sequence_passes(self):
        ok, passed, failed = self_check_principle(
            _additive_principle(), [100, 250, 400, 550])
        self.assertTrue(ok, failed)

    def test_sample_pair_contradiction(self):
        ok, passed, failed = self_check_principle(
            _additive_principle(), [3, 6, 12, 24],
            examples=[([2, 4, 8], 16), ([5, 10, 20], 40)])
        self.assertFalse(ok)
        self.assertIn("sample_pair_contradiction", failed)


class InductionTests(unittest.TestCase):
    def test_ambiguous_episodes_abstain(self):
        # last and max both fit both episodes; they disagree on query.
        episodes = [([1, 2], {}, 2), ([3, 4], {}, 4)]
        programs = induce_program(episodes, max_depth=1)
        predictions = set()
        for prog in programs:
            from memory.principles import run_program
            predictions.add(run_program(prog, [5, 1], {}))
        self.assertGreater(len(programs), 1)
        self.assertGreater(len(predictions), 1)

    def test_insufficient_examples_no_program(self):
        self.assertEqual(induce_program([([1, 2], {}, 2)], max_depth=2), [])

    def test_unique_program_found(self):
        episodes = [([3, 1, 4], {}, 1), ([10, 5, 8], {}, 5)]
        programs = induce_program(episodes, max_depth=1)
        self.assertIn(("min",), programs)


class FailureLearningTests(unittest.TestCase):
    def test_failure_teaches_excluder_and_generalises(self):
        # A precondition-free additive principle fires on a trap.
        p = Principle(
            id="seq-add-bare", program=("extrap_add",),
            shape="sequence-next", ratio_mode="additive_diff",
            invariants=frozenset(),
            positives_features=[features([2, 4, 6, 8]),
                                features([1, 3, 5, 7])],
            n_pos=8, n_neg=0)
        engine = TransferMemoryEngine(principles=[p])
        learn_from_failure(p, [3, 6, 12, 24])
        self.assertIn("const_ratio", p.excluders)
        refused = 0
        for start in range(1, 25):
            terms = [start * 2 ** i for i in range(5)]
            ok, _, failed = self_check_principle(p, terms)
            if not ok:
                refused += 1
        self.assertGreaterEqual(refused, 20)
        # Legitimate additive tasks still pass.
        ok, _, _ = self_check_principle(p, [7, 14, 21, 28])
        self.assertTrue(ok)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        batch = generate_batch("p2-public-7f3a91c2e4", 1, 100)
        items = [{"id": it.item_id, "prompt": it.prompt,
                  "expected": it.expected} for it in batch]
        cls.derived = derive_principles(items)
        cls.engine = TransferMemoryEngine(
            principles=cls.derived["principles"])

    def test_factory_sequence_solved_by_principle(self):
        a = self.engine.explain(
            "What is the next number in this sequence: 4, 9, 14, 19, ...?")
        self.assertEqual(a["answer"], "24")
        self.assertEqual(a["verdict"], "APPLY")

    def test_geometric_trap_refused_not_applied(self):
        a = self.engine.explain(
            "What is the next number in this sequence: 3, 6, 12, 24, 48, ...?")
        self.assertNotEqual(a["verdict"], "APPLY")
        self.assertIn("trap_mismatch:multiplicative_progression",
                      a["failure_codes"])

    def test_negative_additive_sequence_applies(self):
        a = self.engine.explain(
            "What is the next number in this sequence: 10, 4, -2, -8, ...?")
        self.assertEqual(a["answer"], "-14")
        self.assertEqual(a["verdict"], "APPLY")

    def test_alternating_trap_refused_by_guard_not_parser(self):
        a = self.engine.explain(
            "What is the next number in this sequence: 3, -6, 12, -24, 48, ...?")
        self.assertNotEqual(a["verdict"], "APPLY")
        self.assertIn("trap_mismatch:multiplicative_progression",
                      a["failure_codes"])

    def test_constant_sequence_answered_by_agreement(self):
        a = self.engine.explain(
            "What is the next number in this sequence: 5, 5, 5, 5, ...?")
        self.assertEqual(a["answer"], "5")
        self.assertEqual(a["verdict"], "APPLY")

    def test_fewshot_min_solved_by_induction(self):
        prompt = fewshot_prompt(
            [([3, 1, 4], 1), ([10, 5, 8], 5)], [7, 2, 9])
        self.assertEqual(self.engine.solve(prompt), "2")

    def test_fewshot_ambiguous_abstains(self):
        # min and last both fit both examples; they disagree on the
        # query, and no stored principle survives the sample check.
        prompt = fewshot_prompt([([2, 1], 1), ([4, 3], 3)], [1, 9])
        self.assertEqual(self.engine.solve(prompt), "")

    def test_coinciding_stored_principle_abstains(self):
        # In every example the last element is also the maximum, so
        # the stored max principle passes the sample check — but the
        # samples equally induce "last", and the two disagree on
        # the query. The engine must abstain, not apply max.
        prompt = fewshot_prompt(
            [([1, 3, 9], 9), ([2, 8, 10], 10), ([5, 6, 7], 7)],
            [9, 1, 4])
        self.assertEqual(self.engine.solve(prompt), "")

    def test_fewshot_single_example_abstains(self):
        prompt = fewshot_prompt([([3, 1, 4], 1)], [7, 2, 9])
        self.assertEqual(self.engine.solve(prompt), "")

    def test_corrupted_fewshot_abstains(self):
        self.assertEqual(
            self.engine.solve("Learn from examples: [1, => ?. Now solve: x"), "")

    def test_metamorphic_example_order_irrelevant(self):
        ex = [([3, 1, 4], 1), ([10, 5, 8], 5), ([7, 7, 2], 2)]
        p1 = fewshot_prompt(ex, [9, 4, 6])
        p2 = fewshot_prompt(ex[::-1], [9, 4, 6])
        self.assertEqual(self.engine.solve(p1), self.engine.solve(p2))
        self.assertEqual(self.engine.solve(p1), "4")

    def test_principle_digest_stable_and_distinct(self):
        ps = self.derived["principles"]
        self.assertTrue(ps)
        for p in ps:
            self.assertEqual(len(p.digest), 64)
        self.assertEqual(len({p.digest for p in ps}), len(ps))

    def test_derivation_audit_records_expression_tie(self):
        audit = self.derived["audit"]
        expr = audit["clusters"]["expression"]
        # Public gen-1 expressions are all (a * b - c): precedence and
        # left-to-right coincide there, so derivation must abstain.
        self.assertEqual(expr["decision"], "abstain_tie")


if __name__ == "__main__":
    unittest.main()
