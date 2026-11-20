import re
import tempfile
import unittest
from pathlib import Path

from eval.factory import (
    FAMILY_NAMES,
    FactoryError,
    active_families,
    assess_gap,
    generate_batch,
    register_batch,
    retire_generation,
)
from eval.registry import EvalRegistry

ACTOR = "verifier-1"


class GenerationTests(unittest.TestCase):
    def test_deterministic_same_inputs(self):
        a = generate_batch("seed-a", 2, 10)
        b = generate_batch("seed-a", 2, 10)
        self.assertEqual(a, b)

    def test_different_seed_differs(self):
        a = generate_batch("seed-a", 2, 10)
        b = generate_batch("seed-b", 2, 10)
        self.assertNotEqual([i.prompt for i in a], [i.prompt for i in b])

    def test_different_generation_differs(self):
        a = generate_batch("seed-a", 1, 10)
        b = generate_batch("seed-a", 2, 10)
        self.assertNotEqual([i.prompt for i in a], [i.prompt for i in b])

    def test_ids_and_domains(self):
        batch = generate_batch("s", 3, 5)
        for i, item in enumerate(batch):
            self.assertEqual(item.item_id, f"factory-g3-{i:03d}")
            self.assertTrue(item.domain.startswith("factory-"))
            self.assertIn(item.family, FAMILY_NAMES)
            self.assertEqual(item.generation, 3)

    def test_prompts_unique_in_batch(self):
        batch = generate_batch("s", 0, 40)
        self.assertEqual(len({i.prompt for i in batch}), 40)

    def test_active_families_rotate(self):
        self.assertEqual(len(active_families(0)), 5)
        self.assertNotEqual(active_families(0), active_families(1))
        self.assertEqual(active_families(0), active_families(len(FAMILY_NAMES)))

    def test_distribution_shifts_with_generation(self):
        # Generations 0 and 7 share the same family window, but numeric
        # ranges grow with the generation, so generation 7 produces
        # subtract-multiply answers beyond generation 0's ceiling
        # (30*30-2 = 898 at generation 0).
        def max_numeric(gen):
            vals = []
            for seed in ("shift-a", "shift-b", "shift-c"):
                for item in generate_batch(seed, gen, 40):
                    if item.family == "subtract-multiply":
                        vals.append(int(item.expected))
            return max(vals) if vals else 0
        self.assertLessEqual(max_numeric(0), 898)
        self.assertGreater(max_numeric(7), 898)

    def test_answers_are_correct(self):
        # Every family must be verified, across generations covering
        # every active window; an unhandled family fails the test
        # rather than being silently skipped (war-room fix F9).
        seen = set()
        for gen in range(len(FAMILY_NAMES)):
            for item in generate_batch("verify", gen, 40):
                seen.add(item.family)
                if item.family == "arithmetic":
                    m = re.fullmatch(r"What is (\d+) \+ (\d+) \* (\d+)\?",
                                     item.prompt)
                    a, b, c = (int(x) for x in m.groups())
                    self.assertEqual(item.expected, str(a + b * c))
                elif item.family == "subtract-multiply":
                    m = re.fullmatch(r"What is (\d+) \* (\d+) - (\d+)\?",
                                     item.prompt)
                    a, b, c = (int(x) for x in m.groups())
                    self.assertEqual(item.expected, str(a * b - c))
                elif item.family == "reverse":
                    m = re.fullmatch(r"Reverse the string '([a-z]+)'\.",
                                     item.prompt)
                    self.assertEqual(item.expected, m.group(1)[::-1])
                elif item.family == "largest":
                    nums = [int(x) for x in re.findall(r"\d+", item.prompt)]
                    self.assertEqual(item.expected, str(max(nums)))
                elif item.family == "sequence":
                    nums = [int(x) for x in re.findall(r"\d+", item.prompt)]
                    step = nums[1] - nums[0]
                    self.assertEqual(item.expected, str(nums[-1] + step))
                elif item.family == "nth-word":
                    m = re.fullmatch(
                        r"What is word number (\d+) in this list: "
                        r"([a-z ]+)\?", item.prompt)
                    k, words = int(m.group(1)), m.group(2).split()
                    self.assertEqual(item.expected, words[k - 1])
                elif item.family == "parity":
                    n = int(re.search(r"Is (\d+)", item.prompt).group(1))
                    self.assertEqual(item.expected,
                                     "even" if n % 2 == 0 else "odd")
                else:
                    self.fail(f"unhandled family: {item.family}")
        self.assertEqual(seen, set(FAMILY_NAMES))

    def test_pinned_batch_detects_stream_drift(self):
        # Exact pin: if a runtime change ever alters the generation
        # stream, this test fails instead of silently shifting every
        # sealed batch. Values recorded from the shipped code.
        batch = generate_batch("seed-a", 0, 6)
        self.assertEqual(
            [(i.prompt, i.expected) for i in batch[:3]],
            [("Reverse the string 'goxvfev'.", "vefvxog"),
             ("Reverse the string 'psoebrws'.", "swrbeosp"),
             ("What is the largest number in this list: 98, 99, 5, 2?",
              "99")])
        batch2 = generate_batch("seed-a", 2, 6)
        self.assertEqual(batch2[0].prompt,
                         "What is word number 4 in this list: charlie "
                         "india foxtrot kilo bravo alpha lima?")
        self.assertEqual(batch2[0].expected, "kilo")

    def test_count_upper_boundary(self):
        self.assertEqual(len(generate_batch("s", 0, 100)), 100)

    def test_negative_answers_representable(self):
        # Drive the family directly over many seeds: a*b - c can go
        # negative, and the expected string must carry the sign.
        import random as _random
        from eval.factory import _fam_subtract_multiply
        found = False
        for s in range(2000):
            _, expected = _fam_subtract_multiply(_random.Random(s), 0)
            if expected.startswith("-"):
                found = True
                break
        self.assertTrue(found)

    def test_bad_inputs(self):
        for args in [("", 0, 1), ("s", -1, 1), ("s", 0, 0), ("s", 0, 101),
                     ("s p", 0, 1), ("s", 1.5, 1), ("s", 0, True)]:
            with self.assertRaises(FactoryError, msg=str(args)):
                generate_batch(*args)


class RegistryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = EvalRegistry(Path(self.tmp.name) / "reg")

    def test_register_returns_metadata_only(self):
        meta = register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        self.assertEqual(len(meta), 6)
        for entry in meta:
            self.assertEqual(set(entry), {"id", "domain", "content_hash"})

    def test_registered_items_evaluate_perfectly_with_answers(self):
        batch = generate_batch("seed-a", 0, 6)
        register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        answers = {it.prompt: it.expected for it in batch}
        report = self.registry.run_sealed_evaluation(
            ACTOR, lambda prompt: answers[prompt])
        self.assertEqual(report["score"], 1.0)
        self.assertEqual(report["n"], 6)

    def test_registered_items_reject_wrong_answers(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        report = self.registry.run_sealed_evaluation(
            ACTOR, lambda prompt: "not the answer")
        self.assertEqual(report["score"], 0.0)

    def test_retire_rotates_content_and_old_answers_fail(self):
        batch = generate_batch("seed-a", 0, 6)
        register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        before = {m["id"]: m["content_hash"]
                  for m in self.registry.list_sealed_metadata(ACTOR)}
        retire_generation(self.registry, ACTOR, "seed-a", 0, 6,
                          new_seed="seed-b")
        after = {m["id"]: m["content_hash"]
                 for m in self.registry.list_sealed_metadata(ACTOR)}
        self.assertEqual(set(before), set(after))
        for item_id in before:
            self.assertNotEqual(before[item_id], after[item_id])
        old_answers = {it.prompt: it.expected for it in batch}
        # A scorer replaying memorised prompts now faces new prompts.
        report = self.registry.run_sealed_evaluation(
            ACTOR, lambda prompt: old_answers.get(prompt, "stale"))
        self.assertLess(report["score"], 1.0)

    def test_duplicate_registration_rejected(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 4)
        with self.assertRaises(ValueError):
            register_batch(self.registry, ACTOR, "seed-a", 0, 4)

    def test_partial_clash_writes_nothing(self):
        # One id of the batch is already taken by a public item: the
        # pre-flight must reject the whole batch before any write.
        batch = generate_batch("seed-a", 0, 6)
        clash = batch[3]
        self.registry.add_public_item(clash.item_id, clash.domain,
                                      clash.prompt, clash.expected)
        with self.assertRaises(FactoryError):
            register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        self.assertEqual(self.registry.list_sealed_metadata(ACTOR), [])

    def test_retire_unregistered_generation_writes_nothing(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 4)
        before = {m["id"]: m["content_hash"]
                  for m in self.registry.list_sealed_metadata(ACTOR)}
        with self.assertRaises(FactoryError):
            retire_generation(self.registry, ACTOR, "seed-a", 1, 4,
                              new_seed="seed-b")
        after = {m["id"]: m["content_hash"]
                 for m in self.registry.list_sealed_metadata(ACTOR)}
        self.assertEqual(before, after)

    def test_retire_requires_distinct_explicit_seed(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 4)
        with self.assertRaises(FactoryError):
            retire_generation(self.registry, ACTOR, "seed-a", 0, 4,
                              new_seed="seed-a")
        with self.assertRaises(TypeError):
            retire_generation(self.registry, ACTOR, "seed-a", 0, 4)

    def test_retire_with_wrong_seed_rejected_and_writes_nothing(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        before = {m["id"]: m["content_hash"]
                  for m in self.registry.list_sealed_metadata(ACTOR)}
        with self.assertRaises(FactoryError):
            retire_generation(self.registry, ACTOR, "wrong-seed", 0, 6,
                              new_seed="seed-b")
        after = {m["id"]: m["content_hash"]
                 for m in self.registry.list_sealed_metadata(ACTOR)}
        self.assertEqual(before, after)

    def test_retire_keeps_registered_domain(self):
        register_batch(self.registry, ACTOR, "seed-a", 0, 6)
        before = {m["id"]: m["domain"]
                  for m in self.registry.list_sealed_metadata(ACTOR)}
        retire_generation(self.registry, ACTOR, "seed-a", 0, 6,
                          new_seed="seed-b")
        after = {m["id"]: m["domain"]
                 for m in self.registry.list_sealed_metadata(ACTOR)}
        self.assertEqual(before, after)

    def test_bad_actor_rejected(self):
        with self.assertRaises(FactoryError):
            register_batch(self.registry, "bad actor!", "seed-a", 0, 4)


class GapTests(unittest.TestCase):
    def test_public_only_gain_flagged(self):
        out = assess_gap(0.5, 0.8, 0.5, 0.5)
        self.assertTrue(out["gaming_suspected"])
        self.assertEqual(out["reason"], "public_only_gain")

    def test_both_improve_not_flagged(self):
        out = assess_gap(0.5, 0.7, 0.5, 0.65)
        self.assertFalse(out["gaming_suspected"])
        self.assertEqual(out["reason"], "no_flag")

    def test_gap_widening_flagged(self):
        out = assess_gap(0.5, 0.9, 0.5, 0.6, widen_threshold=0.05)
        self.assertTrue(out["gaming_suspected"])

    def test_pure_gap_widening_reason(self):
        # Both sets improve, sealed by less: the widening branch alone.
        out = assess_gap(0.5, 0.9, 0.5, 0.6, widen_threshold=0.05)
        self.assertEqual(out["reason"], "gap_widened")

    def test_gap_at_exact_threshold_not_flagged(self):
        out = assess_gap(0.5, 0.9, 0.5, 0.65, widen_threshold=0.25)
        self.assertAlmostEqual(out["gap_widened_by"], 0.25)
        self.assertFalse(out["gaming_suspected"])
        self.assertEqual(out["reason"], "no_flag")

    def test_sealed_regression_not_masked_by_public_gain(self):
        out = assess_gap(0.5, 0.9, 0.6, 0.5)
        self.assertEqual(out["reason"], "sealed_regression")
        self.assertTrue(out["gaming_suspected"])

    def test_sealed_regression_noted_without_gaming_flag(self):
        out = assess_gap(0.5, 0.5, 0.6, 0.5, widen_threshold=10.0)
        self.assertEqual(out["reason"], "sealed_regression")
        self.assertFalse(out["gaming_suspected"])

    def test_regression_fields_reported_independently(self):
        out = assess_gap(0.6, 0.5, 0.6, 0.5)
        self.assertTrue(out["sealed_regression"])
        self.assertTrue(out["public_regression"])
        self.assertFalse(out["gaming_suspected"])
        out = assess_gap(0.5, 0.7, 0.5, 0.6)
        self.assertFalse(out["sealed_regression"])
        self.assertFalse(out["public_regression"])

    def test_nan_and_inf_threshold_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(FactoryError):
                assess_gap(0.5, 0.5, 0.5, 0.5, widen_threshold=bad)

    def test_no_change_no_flag(self):
        out = assess_gap(0.5, 0.5, 0.5, 0.5)
        self.assertFalse(out["gaming_suspected"])

    def test_bad_scores_rejected(self):
        for args in [(-0.1, 0.5, 0.5, 0.5), (0.5, 1.1, 0.5, 0.5),
                     (0.5, 0.5, "x", 0.5), (True, 0.5, 0.5, 0.5)]:
            with self.assertRaises(FactoryError, msg=str(args)):
                assess_gap(*args)
        with self.assertRaises(FactoryError):
            assess_gap(0.5, 0.5, 0.5, 0.5, widen_threshold=-1)


class ExportTests(unittest.TestCase):
    def test_package_exports_factory_surface(self):
        import eval
        for name in ("generate_batch", "register_batch",
                     "retire_generation", "assess_gap",
                     "active_families", "FactoryError", "GeneratedItem",
                     "FAMILY_NAMES"):
            self.assertTrue(hasattr(eval, name), name)


if __name__ == "__main__":
    unittest.main()
