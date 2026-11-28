"""Acceptance tests for the Cycle 35 principle-engine measurement.

Three independent seed sets. Bars (merged external spec):
in-distribution 1.00; shifted lesson families 1.00 each; held-out
families >= 0.90 each with aggregate >= 0.95; traps at 1.00 safe
handling with zero false applications; false-refusal rate
<= 0.01; control reproduces baseline; memory never worse.

The one diagnosed residual, pinned here rather than hidden: the
shifted arithmetic family is an OPEN GAP. Public gen-1
expression episodes are all (a * b - c), on which operator
precedence and left-to-right evaluation coincide, so derivation
abstains on the tie (see the derivation audit assertion below).
In Cycle 34 this family was a no-lesson control by design; in
Cycle 35 derivation tried and abstained, and the record says
so. The fix round adds agreement-gated answering: the tied
candidates answer items they agree on and abstain on items they
disagree on. Every shifted arithmetic item is of the form
a + b * c, on which the candidates disagree, so the family
score equals the (zero) agreement fraction — asserted below as
a computed quantity, not a magic number. The four lesson
families carry the shifted tier to 1.00 each; the aggregate
including the open-gap family is 0.80 by that construction.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.transfer import generate_shifted
from memory.transfer35 import LESSON_FAMILIES, run_cycle35_measurement

_ARITH_RE = re.compile(r"What is ([0-9]+) \+ ([0-9]+) \* ([0-9]+)\?")

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

    def test_shifted_arithmetic_is_an_open_gap_with_agreement_gate(self):
        for seeds, r in zip(SEED_SETS, self.reports):
            audit = r["derivation_audit"]["clusters"]["expression"]
            self.assertEqual(audit["decision"], "abstain_tie")
            self.assertEqual(set(audit["tied"]),
                             {"eval_precedence", "eval_left_to_right"})
            self.assertTrue(audit["agreement_gated"])
            # The family is recorded as an open gap, not a control.
            gaps = {g["family"]: g for g in r["open_gaps"]}
            self.assertIn("arithmetic", gaps)
            self.assertEqual(gaps["arithmetic"]["status"], "open_gap")
            # The score equals the fraction of items the tied
            # candidates agree on (the gate answers those; the
            # rest fall back to the baseline, which scores 0 on
            # this family — the pre-fix pin). Computed from the
            # items, not hard-coded.
            items = [i for i in generate_shifted(seeds["shifted_seed"], 20)
                     if i["family"] == "arithmetic"]
            agree = 0
            for item in items:
                a, b, c = (int(x) for x in
                           _ARITH_RE.fullmatch(item["prompt"]).groups())
                if a + b * c == (a + b) * c:
                    agree += 1
            per_family = r["tiers"]["shifted"]["after"]["per_family"]
            self.assertEqual(per_family["arithmetic"],
                             agree / len(items))

    def test_engine_stats_reported_separately_from_accuracy(self):
        for r in self.reports:
            for tier in r["tiers"].values():
                stats = tier["engine"]
                self.assertIn("abstention_rate", stats)
                self.assertIn("selective_accuracy", stats)
                self.assertIn("refusal_taxonomy", stats)
            in_dist = r["tiers"]["in_distribution"]["engine"]
            self.assertEqual(in_dist["selective_accuracy"], 1.0)
            held = r["tiers"]["heldout"]["engine"]
            taxonomy = held["refusal_taxonomy"]
            if held["abstention_rate"] > 0:
                self.assertIn("insufficient_evidence", taxonomy)

    def test_traps_primary_metric_and_structural_transfer_split(self):
        for r in self.reports:
            traps = r["traps"]
            self.assertEqual(traps["primary_metric"],
                             "false_application_rate")
            squares = traps["structural_transfer"]["trap-squares"]
            self.assertEqual(squares["label"],
                             "Cross-Domain Structural Transfer")
            self.assertEqual(squares["end_to_end"], 1.0)
            self.assertIn("trap_refused",
                          traps["refusal_taxonomy"])

    def test_fresh_crosscheck_set(self):
        positive = ("fresh-last", "fresh-secondmin",
                    "fresh-nextgeo", "fresh-count")
        abstaining = ("fresh-coincide", "fresh-degenerate")
        for r in self.reports:
            per_family = r["fresh_crosscheck"]["per_family"]
            self.assertEqual(set(per_family),
                             set(positive) | set(abstaining))
            for family, m in per_family.items():
                self.assertEqual(m["false_applications"], 0, family)
                self.assertEqual(m["safe_handling"], 1.0, family)
            for family in positive:
                self.assertGreaterEqual(
                    per_family[family]["end_to_end"], 0.90, family)
            for family in abstaining:
                # The coincidence families must be abstained on,
                # never confidently answered by the stored
                # principle the samples cannot distinguish.
                self.assertEqual(
                    per_family[family]["applications"], 0, family)

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
