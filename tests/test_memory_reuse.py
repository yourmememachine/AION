"""Tests for the sealed reuse measurement (the P2 exit test)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.factory import generate_batch
from eval.gate import VerifierAttestation
from memory.reuse import (
    ReuseError,
    _check_floor,
    _per_family_map,
    run_reuse_measurement,
)
from memory.store import MemoryError, MemoryStore, decide_write

PUBLIC_SEED = "p2-public-7f3a91c2e4"
SEALED_SEED = "p2-sealed-bb2002"
GOLDEN_SEED = "p2-golden-09c4d6e2f1"
LESSON_FAMILIES = {"reverse", "largest", "sequence", "nth-word"}


def run_in(tmp):
    return run_reuse_measurement(
        Path(tmp) / "registry", Path(tmp) / "memory",
        public_seed=PUBLIC_SEED, sealed_seed=SEALED_SEED,
        golden_seed=GOLDEN_SEED, legacy_test_mode=True)


class ReuseMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.report = run_in(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_headline_sealed_gain_and_verdict_accepted(self):
        r = self.report
        self.assertGreater(r["sealed_after"]["correct"],
                           r["sealed_before"]["correct"])
        self.assertGreater(r["sealed_after"]["score"],
                           r["sealed_before"]["score"])
        self.assertTrue(r["verdict"]["accepted"])
        self.assertEqual(r["verdict"]["reason"], "both_improved")
        self.assertTrue(r["passed"])
        self.assertFalse(r["invalidated"], r["invalidation_reasons"])

    def test_public_gain_also_positive(self):
        r = self.report
        self.assertGreater(r["public_after"]["correct"],
                           r["public_before"]["correct"])
        self.assertGreater(r["verdict"]["public_delta"], 0)
        self.assertAlmostEqual(
            r["verdict"]["sealed_delta"],
            r["sealed_after"]["score"] - r["sealed_before"]["score"])

    def test_gain_magnitude_floor_not_exact(self):
        r = self.report
        self.assertGreaterEqual(
            r["sealed_after"]["score"] - r["sealed_before"]["score"], 0.20)

    def test_same_sealed_set_before_and_after(self):
        r = self.report
        self.assertEqual(r["sealed_before"]["n"], r["sealed_after"]["n"])
        self.assertEqual(r["sealed_before"]["version"],
                         r["sealed_after"]["version"])
        self.assertEqual(r["sealed_before"]["manifest_hash"],
                         r["sealed_after"]["manifest_hash"])
        self.assertEqual(r["manifest_hash"],
                         r["sealed_after"]["manifest_hash"])

    def test_control_empty_memory_rerun_equals_baseline(self):
        r = self.report
        control = r["controls"]["empty_memory"]
        self.assertEqual(control["correct"], r["sealed_before"]["correct"])
        self.assertEqual(control["score"], r["sealed_before"]["score"])

    def test_control_retrieval_disabled_equals_baseline(self):
        r = self.report
        control = r["controls"]["retrieval_disabled"]
        self.assertEqual(control["correct"], r["sealed_before"]["correct"])
        self.assertLess(control["correct"], r["sealed_after"]["correct"])

    def test_accepted_lessons_exactly_transferable_families(self):
        self.assertEqual(set(self.report["accepted_families"]),
                         LESSON_FAMILIES)
        self.assertEqual(len(self.report["accepted_families"]),
                         len(LESSON_FAMILIES))

    def test_no_lesson_for_non_transferable_families(self):
        audit = self.report["derivation_audit"]["families"]
        # Public-only family whose naive strategy is already correct:
        # derivation itself must decline it.
        self.assertEqual(audit["subtract-multiply"]["decision"],
                         "naive_best")
        proposed = {rec["family"] for rec in self.report["lessons"]}
        # Sealed-only (parity) and absent (arithmetic) families can
        # never be proposed: there is no public evidence for them.
        self.assertNotIn("parity", proposed)
        self.assertNotIn("arithmetic", proposed)

    def test_per_family_after_scores(self):
        after = self.report["per_family"]["sealed_after"]
        before = self.report["per_family"]["sealed_before"]
        for family in LESSON_FAMILIES:
            self.assertEqual(after[f"sealed-{family}"], 1.0, family)
            self.assertLess(before[f"sealed-{family}"], 1.0, family)
        # The untouched control family must not move.
        self.assertEqual(after["sealed-parity"], before["sealed-parity"])

    def test_sealed_evaluation_budget_is_small_and_reported(self):
        # baseline + one candidate pass per lesson + after + 2 controls
        self.assertEqual(self.report["sealed_evaluations"],
                         1 + len(self.report["lessons"]) + 1 + 2)
        self.assertLessEqual(self.report["sealed_evaluations"], 12)

    def test_report_contains_no_seeds(self):
        blob = repr(self.report)
        for seed in (PUBLIC_SEED, SEALED_SEED, GOLDEN_SEED):
            self.assertNotIn(seed, blob)


class ReuseDeterminismTests(unittest.TestCase):
    def test_two_full_runs_identical_numbers(self):
        with tempfile.TemporaryDirectory() as one, \
                tempfile.TemporaryDirectory() as two:
            first = run_in(one)
            second = run_in(two)
        for key in ("public_before", "public_after", "sealed_before",
                    "sealed_after"):
            self.assertEqual(
                (first[key]["n"], first[key]["correct"]),
                (second[key]["n"], second[key]["correct"]), key)
        self.assertEqual(first["verdict"], second["verdict"])
        self.assertEqual(first["accepted_families"],
                         second["accepted_families"])
        for key in ("empty_memory", "retrieval_disabled"):
            self.assertEqual(first["controls"][key]["correct"],
                             second["controls"][key]["correct"], key)


class QuarantineTests(unittest.TestCase):
    def test_default_call_raises_and_writes_nothing(self):
        # Trust Boundary v2: the legacy unsigned path is
        # quarantined. The default call must raise BEFORE any
        # commit — in fact before anything is created at all.
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry"
            mem = Path(tmp) / "memory"
            with self.assertRaises(ReuseError):
                run_reuse_measurement(
                    reg, mem,
                    public_seed=PUBLIC_SEED, sealed_seed=SEALED_SEED,
                    golden_seed=GOLDEN_SEED)
            self.assertFalse((mem / "memory.json").exists())
            self.assertFalse((reg / "registry.json").exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])


class ReuseSetupTests(unittest.TestCase):
    def test_dirty_registry_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry"
            reg.mkdir()
            (reg / "registry.json").write_text("{}")
            with self.assertRaises(ReuseError):
                run_in(tmp)

    def test_dirty_memory_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp) / "memory"
            mem.mkdir()
            (mem / "memory.json").write_text("{}")
            with self.assertRaises(ReuseError):
                run_in(tmp)

    def test_family_floor_rejects_absent_active_family(self):
        # R4 F1: the floor iterates the generation's ACTIVE families;
        # a family missing from the batch entirely counts as 0 items.
        batch = [item for item in generate_batch(SEALED_SEED, 2, 100)
                 if item.family != "parity"]
        with self.assertRaises(ReuseError):
            _check_floor(batch, 2, 100, "sealed")

    def test_prompt_overlap_seed_pair_refused(self):
        # This sealed seed shares 2 prompts with the shipped public
        # seed while passing every family floor — the run must
        # refuse on overlap, before anything is measured.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ReuseError):
                run_reuse_measurement(
                    Path(tmp) / "registry", Path(tmp) / "memory",
                    public_seed=PUBLIC_SEED,
                    sealed_seed="p2-sealed-51bd08e7a9",
                    golden_seed=GOLDEN_SEED, legacy_test_mode=True)

    def test_per_family_map_mismatch_raises(self):
        # R3 F3: a map that cannot reproduce the registry report
        # aborts the measurement instead of gating on bad maps.
        batch = generate_batch(SEALED_SEED, 2, 10)
        responses = {item.prompt: item.expected for item in batch}
        with self.assertRaises(ReuseError):
            _per_family_map(responses, batch,
                            {"correct": 0, "n": len(batch)}, "sealed")


class PoisonAfterMeasurementTests(unittest.TestCase):
    """A poisoned superseding lesson, proposed after a good one is
    committed, must be rejected by the gate and change nothing."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.report = run_in(cls.tmp.name)
        cls.memory_dir = Path(cls.tmp.name) / "memory"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_wrong_largest_strategy_rejected_store_unchanged(self):
        r = self.report
        store = MemoryStore(self.memory_dir)
        before = store.retrieve(domain="factory-largest")
        self.assertEqual(before[0]["content"], "scan-max")
        fields = {
            "id": "lesson-largest-poison",
            "domain": "factory-largest",
            "kind": "strategy",
            "content": "smallest",
            "author": "seat-11",
            "source": "derivation:public-practice-gen1",
            "evidence_ref": "derive:poison:largest",
            "proposal_id": "p2-poison-largest",
            "verifier_id": "seat-3",
            "supersedes": "lesson-largest",
        }
        pub = dict(r["per_family"]["public_after"])
        sealed = dict(r["per_family"]["sealed_after"])
        cand_pub = dict(pub, **{"pub-largest": 0.0})
        cand_sealed = dict(sealed, **{"sealed-largest": 0.0})
        attestation = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=r["manifest_hash"], reward_hacking_checked=True,
            evidence_ref="reuse-run:poison-check",
            attested_at="2026-11-20T00:00:00+00:00")
        decision = decide_write(
            entry_fields=fields,
            builder_ids=["seat-9", "seat-10", "seat-11"],
            reviewer_ids=["seat-1", "seat-2", "seat-3", "seat-4",
                          "seat-5", "seat-6"],
            baseline_public=pub, candidate_public=cand_pub,
            baseline_sealed=sealed, candidate_sealed=cand_sealed,
            capability_baseline=dict(sealed),
            capability_candidate=dict(sealed),
            attestation=attestation,
            expected_sealed_hash=r["manifest_hash"])
        self.assertFalse(decision.accepted)
        self.assertIn("regression", decision.reasons)
        with self.assertRaises(MemoryError):
            store.commit_write(fields, decision)
        after = store.retrieve(domain="factory-largest")
        self.assertEqual([e["id"] for e in after], ["lesson-largest"])
        self.assertEqual(after[0]["content"], "scan-max")


if __name__ == "__main__":
    unittest.main()
