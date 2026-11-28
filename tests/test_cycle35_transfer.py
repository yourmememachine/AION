"""Acceptance tests for the Cycle 35 principle-engine measurement.

Three independent seed sets. Bars (merged external spec):
in-distribution 1.00; shifted lesson families 1.00 each; held-out
families >= 0.90 each with aggregate >= 0.95; traps at 1.00 safe
handling with zero false applications; false-refusal rate
<= 0.01; control reproduces baseline; memory never worse.

The one diagnosed residual, pinned here rather than hidden: the
shifted arithmetic family stays at 0.00. Public gen-1 expression
episodes are all (a * b - c), on which operator precedence and
left-to-right evaluation coincide, so derivation abstains on the
tie (see the derivation audit assertion below). The four lesson
families carry the shifted tier to 1.00 each; the aggregate
including the control family is 0.80 by that construction.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.transfer35 import LESSON_FAMILIES, run_cycle35_measurement

SEED_SETS = (
    {"public_seed": "p2-public-7f3a91c2e4",
     "sealed_seed": "p2-sealed-bb2002",
     "shifted_seed": "c34-shifted-51cd90aa",
     "heldout_seed": "c35-heldout-a1", "trap_seed": "c35-trap-a1"},
    {"public_seed": "c35-public-b2", "sealed_seed": "c35-sealed-b2",
     "shifted_seed": "c35-shifted-b2",
     "heldout_seed": "c35-heldout-b2", "trap_seed": "c35-trap-b2"},
    {"public_seed": "c35-public-c3", "sealed_seed": "c35-sealed-c3",
     "shifted_seed": "c35-shifted-c3",
     "heldout_seed": "c35-heldout-c3", "trap_seed": "c35-trap-c3"},
)


class Cycle35MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = [run_cycle35_measurement(**seeds)
                       for seeds in SEED_SETS]

    def test_in_distribution_perfect_on_all_seeds(self):
        for r in self.reports:
            self.assertEqual(
                r["tiers"]["in_distribution"]["after"]["score"], 1.0)

    def test_shifted_lesson_families_perfect(self):
        for r in self.reports:
            per_family = r["tiers"]["shifted"]["after"]["per_family"]
            for family in LESSON_FAMILIES:
                self.assertEqual(per_family[family], 1.0, family)

    def test_shifted_arithmetic_residual_is_the_diagnosed_tie(self):
        for r in self.reports:
            per_family = r["tiers"]["shifted"]["after"]["per_family"]
            self.assertEqual(per_family["arithmetic"], 0.0)
            audit = r["derivation_audit"]["clusters"]["expression"]
            self.assertEqual(audit["decision"], "abstain_tie")
            self.assertEqual(set(audit["tied"]),
                             {"eval_precedence", "eval_left_to_right"})

    def test_heldout_per_family_and_aggregate(self):
        for r in self.reports:
            tier = r["tiers"]["heldout"]
            self.assertGreaterEqual(tier["after"]["score"], 0.95)
            for family, score in tier["after"]["per_family"].items():
                self.assertGreaterEqual(score, 0.90, family)
                self.assertGreater(score, 0.0, family)

    def test_traps_safe_handling_perfect(self):
        for r in self.reports:
            for family, m in r["traps"]["per_family"].items():
                self.assertEqual(m["false_applications"], 0, family)
                self.assertEqual(m["safe_handling"], 1.0, family)

    def test_fewshot_traps_solved_without_false_applications(self):
        for r in self.reports:
            for family, m in r["traps_fewshot_metrics"].items():
                self.assertEqual(m["false_applications"], 0, family)
                self.assertGreaterEqual(m["end_to_end"], 0.90, family)

    def test_false_refusal_rate_within_bound(self):
        for r in self.reports:
            self.assertLessEqual(r["false_refusals"]["rate"], 0.01)

    def test_controls_and_never_worse(self):
        for r in self.reports:
            self.assertTrue(r["controls_ok"])
            self.assertTrue(r["never_worse_than_baseline"])

    def test_reports_contain_no_seeds(self):
        for seeds, r in zip(SEED_SETS, self.reports):
            blob = repr(r)
            for seed in seeds.values():
                self.assertNotIn(seed, blob)


if __name__ == "__main__":
    unittest.main()
