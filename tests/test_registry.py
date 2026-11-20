"""Tests for the benchmark registry. Standard library only."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import (
    CorruptRegistryError,
    EvalRegistry,
    EvaluationError,
    TamperDetectedError,
    compare_gains,
)

VERIFIER = "verifier-1"
BUILDER = "builder-1"


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.reg = EvalRegistry(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def add_pair(self):
        self.reg.add_public_item("pub-1", "geo", "Capital of France?", "paris")
        self.reg.add_sealed_item("sec-1", "geo", "Capital of Japan?", "tokyo",
                                 actor=VERIFIER)


class TestPublicSet(RegistryTestCase):
    def test_public_item_roundtrip(self):
        self.reg.add_public_item("pub-1", "geo", "Capital of France?", "paris")
        item = self.reg.get_public_item("pub-1")
        self.assertEqual(item["prompt"], "Capital of France?")
        self.assertEqual(item["expected"], "paris")
        self.assertEqual(len(item["content_hash"]), 64)

    def test_duplicate_id_across_sets_rejected(self):
        self.reg.add_public_item("same-1", "geo", "Q?", "a")
        with self.assertRaises(ValueError):
            self.reg.add_sealed_item("same-1", "geo", "Q2?", "b", actor=VERIFIER)

    def test_public_evaluation_scores_and_normalises(self):
        self.reg.add_public_item("pub-1", "geo", "Capital of France?", "paris")
        self.reg.add_public_item("pub-2", "geo", "Capital of Spain?", "madrid")
        report = self.reg.run_public_evaluation(
            BUILDER, lambda prompt: " Paris " if "France" in prompt else "x")
        self.assertEqual(report["n"], 2)
        self.assertEqual(report["correct"], 1)
        self.assertEqual(report["score"], 0.5)
        self.assertEqual(report["version"], 2)

    def test_empty_set_evaluation_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.run_public_evaluation(BUILDER, lambda prompt: "x")
        with self.assertRaises(ValueError):
            self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "x")


class TestSealedSet(RegistryTestCase):
    def test_metadata_exposes_no_content(self):
        self.add_pair()
        meta = self.reg.list_sealed_metadata(VERIFIER)
        self.assertEqual(len(meta), 1)
        self.assertEqual(set(meta[0].keys()), {"id", "domain", "content_hash"})
        blob = json.dumps(meta)
        self.assertNotIn("tokyo", blob)
        self.assertNotIn("Capital of Japan", blob)

    def test_no_method_returns_sealed_content(self):
        self.add_pair()
        report = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        self.assertEqual(report["score"], 1.0)
        self.assertNotIn("tokyo", json.dumps(report))
        self.assertTrue(self.reg.verify_sealed_integrity(VERIFIER))
        self.assertEqual(len(self.reg.sealed_manifest_hash(VERIFIER)), 64)

    def test_sealed_access_is_logged_in_order(self):
        self.add_pair()
        self.reg.list_sealed_metadata(VERIFIER)
        self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        kinds = [e["kind"] for e in self.reg.access_log()]
        self.assertEqual(kinds, ["add", "metadata", "evaluate"])
        seqs = [e["seq"] for e in self.reg.access_log()]
        self.assertEqual(seqs, [1, 2, 3])

    def test_scorer_failure_is_wrapped_and_access_still_logged(self):
        self.add_pair()

        def boom(prompt):
            raise RuntimeError("boom")

        with self.assertRaises(EvaluationError):
            self.reg.run_sealed_evaluation(VERIFIER, boom)
        kinds = [e["kind"] for e in self.reg.access_log()]
        self.assertIn("evaluate", kinds)

    def test_scorer_returning_non_text_rejected(self):
        self.add_pair()
        with self.assertRaises(EvaluationError):
            self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: 42)

    def test_rotate_changes_content_and_bumps_version(self):
        self.add_pair()
        before = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        self.reg.rotate_sealed_item("sec-1", "Capital of Italy?", "rome",
                                    actor=VERIFIER)
        after = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "rome")
        self.assertEqual(after["score"], 1.0)
        self.assertEqual(after["version"], before["version"] + 1)
        with self.assertRaises(ValueError):
            self.reg.compare_reports(before, after, before, after)

    def test_verify_empty_sealed_set_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.verify_sealed_integrity(VERIFIER)

    def test_sealed_report_carries_manifest_hash(self):
        self.add_pair()
        report = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        self.assertEqual(report["manifest_hash"],
                         self.reg.sealed_manifest_hash(VERIFIER))

    def test_compare_reports_manifest_mismatch_rejected(self):
        self.add_pair()
        before = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "x")
        after = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        pub = {"set": "public", "score": 0.5, "version": 1}
        pub2 = {"set": "public", "score": 0.6, "version": 1}
        forged = dict(after)
        forged["manifest_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            self.reg.compare_reports(pub, pub2, before, forged)

    def test_returned_metadata_is_a_copy(self):
        self.add_pair()
        meta = self.reg.list_sealed_metadata(VERIFIER)
        meta[0]["content_hash"] = "0" * 64
        self.assertTrue(self.reg.verify_sealed_integrity(VERIFIER))


class TestTamperAndPersistence(RegistryTestCase):
    def test_tampered_sealed_content_detected_on_load(self):
        self.add_pair()
        raw = json.loads((self.dir / "registry.json").read_text())
        raw["sealed_items"][0]["expected"] = "osaka"
        (self.dir / "registry.json").write_text(json.dumps(raw))
        with self.assertRaises(TamperDetectedError):
            EvalRegistry(self.dir)

    def test_access_log_tamper_detected_on_load(self):
        self.add_pair()
        raw = json.loads((self.dir / "registry.json").read_text())
        raw["access_log"][0]["actor"] = "mallory-1"
        (self.dir / "registry.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.dir)

    def test_corrupt_file_fails_closed_and_quarantines(self):
        self.add_pair()
        (self.dir / "registry.json").write_text("{not json")
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.dir)
        quarantined = list(self.dir.glob("registry.corrupt-*.json"))
        self.assertEqual(len(quarantined), 1)

    def test_state_survives_reload(self):
        self.add_pair()
        self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        reloaded = EvalRegistry(self.dir)
        self.assertEqual(len(reloaded.access_log()), 2)
        report = reloaded.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        self.assertEqual(report["score"], 1.0)


class TestCompareGains(unittest.TestCase):
    def test_both_improved_accepts(self):
        out = compare_gains(0.5, 0.7, 0.5, 0.6)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["reason"], "both_improved")

    def test_public_only_gain_rejected(self):
        out = compare_gains(0.5, 0.9, 0.5, 0.5)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "public_only")

    def test_sealed_regression_rejected_despite_public_gain(self):
        out = compare_gains(0.5, 0.9, 0.5, 0.49)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "regression")

    def test_no_gain_rejected(self):
        out = compare_gains(0.5, 0.5, 0.5, 0.5)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "no_gain")

    def test_min_delta_threshold(self):
        out = compare_gains(0.5, 0.53, 0.5, 0.53, min_delta=0.05)
        self.assertFalse(out["accepted"])
        out = compare_gains(0.5, 0.55, 0.5, 0.55, min_delta=0.05)
        self.assertTrue(out["accepted"])

    def test_invalid_scores_rejected(self):
        for bad in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.assertRaises(ValueError):
                compare_gains(bad, 0.5, 0.5, 0.5)


class TestEvaluationIntegrity(RegistryTestCase):
    def test_scorer_cannot_mutate_sealed_set_mid_evaluation(self):
        self.add_pair()
        calls = []

        def mutating_scorer(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                self.reg.rotate_sealed_item(
                    "sec-1", "Capital of Italy?", "pwned", actor="attacker-1")
            return "pwned"

        with self.assertRaises(EvaluationError):
            self.reg.run_sealed_evaluation(VERIFIER, mutating_scorer)

    def test_scorer_cannot_add_items_mid_evaluation(self):
        self.add_pair()

        def adding_scorer(prompt):
            self.reg.add_sealed_item("sec-2", "geo", "Q?", "a",
                                     actor="attacker-1")
            return "tokyo"

        with self.assertRaises(EvaluationError):
            self.reg.run_sealed_evaluation(VERIFIER, adding_scorer)

    def test_version_rollback_detected_on_load(self):
        self.add_pair()
        raw = json.loads((self.dir / "registry.json").read_text())
        raw["sealed_version"] = 99
        (self.dir / "registry.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.dir)

    def test_item_deletion_detected_on_load(self):
        self.add_pair()
        raw = json.loads((self.dir / "registry.json").read_text())
        raw["sealed_items"] = []
        (self.dir / "registry.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.dir)

    def test_unknown_keys_rejected_on_load(self):
        self.add_pair()
        raw = json.loads((self.dir / "registry.json").read_text())
        raw["sealed_items"][0]["note"] = "smuggled"
        (self.dir / "registry.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.dir)

    def test_forged_report_rejected_by_compare_reports(self):
        self.add_pair()
        before = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "x")
        after = self.reg.run_sealed_evaluation(VERIFIER, lambda prompt: "tokyo")
        pub = {"set": "public", "score": 0.5, "version": 1, "n": 1,
               "correct": 0}
        pub["score"] = 0.0
        pub2 = {"set": "public", "score": 1.0, "version": 1, "n": 1,
                "correct": 1}
        forged = dict(after)
        forged["n"] = 500
        forged["correct"] = 0  # score 1.0 contradicts correct/n
        with self.assertRaises(ValueError):
            self.reg.compare_reports(pub, pub2, before, forged)
        bool_version = dict(after)
        bool_version["version"] = True
        with self.assertRaises(ValueError):
            self.reg.compare_reports(pub, pub2, before, bool_version)


class TestCrossInstance(RegistryTestCase):
    def test_stale_instance_cannot_overwrite_newer_state(self):
        self.add_pair()
        other = EvalRegistry(self.dir)
        other.rotate_sealed_item("sec-1", "Capital of Italy?", "rome",
                                 actor="seat-9")
        with self.assertRaises(CorruptRegistryError):
            self.reg.add_public_item("pub-2", "math", "What is 1+1?", "2")
        reloaded = EvalRegistry(self.dir)
        self.assertEqual(reloaded.run_sealed_evaluation(
            VERIFIER, lambda prompt: "rome")["score"], 1.0)

    def test_cross_instance_mutation_during_evaluation_detected(self):
        self.add_pair()
        other = EvalRegistry(self.dir)

        def scorer(prompt):
            other.rotate_sealed_item("sec-1", "Capital of Italy?", "rome",
                                     actor="seat-9")
            return "tokyo"

        with self.assertRaises(EvaluationError):
            self.reg.run_sealed_evaluation(VERIFIER, scorer)

    def test_scorer_evaluation_error_does_not_leak_prompt(self):
        self.add_pair()

        def scorer(prompt):
            raise EvaluationError(f"scorer saw: {prompt}")

        with self.assertRaises(EvaluationError) as ctx:
            self.reg.run_sealed_evaluation(VERIFIER, scorer)
        self.assertNotIn("Capital of Japan", str(ctx.exception))


class TestConcurrentInstances(RegistryTestCase):
    def test_racing_saves_never_silently_lose_a_write(self):
        import threading
        for i in range(200):
            self.reg.add_public_item(f"bulk-{i}", "math", f"Q{i}?", "a")
        first = EvalRegistry(self.dir)
        second = EvalRegistry(self.dir)
        barrier = threading.Barrier(2)
        results = {}

        def add(instance, item_id, key):
            barrier.wait()
            try:
                instance.add_public_item(item_id, "math", "Q?", "a")
                results[key] = "ok"
            except CorruptRegistryError:
                results[key] = "refused"

        threads = [
            threading.Thread(target=add, args=(first, "race-a", "a")),
            threading.Thread(target=add, args=(second, "race-b", "b")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly one writer wins; the other is refused loudly. A silent
        # lost update (both "ok", one item missing) must never happen.
        self.assertEqual(sorted(results.values()), ["ok", "refused"])
        reloaded = EvalRegistry(self.dir)
        present = {it["id"] for it in reloaded.list_public_items()}
        self.assertEqual(len({"race-a", "race-b"} & present), 1)


class TestSharedInstanceThreads(RegistryTestCase):
    def test_two_threads_sharing_one_instance_lose_nothing(self):
        import threading
        for i in range(100):
            self.reg.add_public_item(f"bulk-{i}", "math", f"Q{i}?", "a")
        barrier = threading.Barrier(2)
        errors = []

        def add(item_id):
            barrier.wait()
            try:
                self.reg.add_public_item(item_id, "math", "Q?", "a")
            except Exception as exc:  # noqa: BLE001 - recorded for assert
                errors.append(exc)

        threads = [threading.Thread(target=add, args=("thread-a",)),
                   threading.Thread(target=add, args=("thread-b",))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        present = {it["id"] for it in EvalRegistry(self.dir).list_public_items()}
        self.assertTrue({"thread-a", "thread-b"} <= present)

    def test_race_survives_lockfile_deletion(self):
        # The lock lives on the registry directory, not on a lockfile:
        # deleting .registry.lock (or any file in the directory) during
        # a race must not split it.
        import threading
        for i in range(100):
            self.reg.add_public_item(f"bulk-{i}", "math", f"Q{i}?", "a")
        first, second = EvalRegistry(self.dir), EvalRegistry(self.dir)
        barrier = threading.Barrier(3)
        stop = threading.Event()
        results = {}

        def deleter():
            barrier.wait()
            while not stop.is_set():
                try:
                    (self.dir / ".registry.lock").unlink()
                except FileNotFoundError:
                    pass

        def add(instance, item_id, key):
            barrier.wait()
            try:
                instance.add_public_item(item_id, "math", "Q?", "a")
                results[key] = "ok"
            except CorruptRegistryError:
                results[key] = "refused"

        threads = [threading.Thread(target=deleter),
                   threading.Thread(target=add, args=(first, "race-a", "a")),
                   threading.Thread(target=add, args=(second, "race-b", "b"))]
        for t in threads:
            t.start()
        for t in threads[1:]:
            t.join()
        stop.set()
        threads[0].join()
        self.assertEqual(sorted(results.values()), ["ok", "refused"])
        present = {it["id"] for it in EvalRegistry(self.dir).list_public_items()}
        self.assertEqual(len({"race-a", "race-b"} & present), 1)


class TestGoldenSet(RegistryTestCase):
    def test_golden_add_evaluate_and_metadata(self):
        self.reg.add_golden_item("gold-1", "math", "What is 2+2?", "4",
                                 actor=VERIFIER)
        meta = self.reg.list_golden_metadata(VERIFIER)
        self.assertEqual(set(meta[0].keys()), {"id", "domain", "content_hash"})
        report = self.reg.run_golden_evaluation(VERIFIER, lambda prompt: "4")
        self.assertEqual(report["set"], "golden")
        self.assertEqual(report["score"], 1.0)

    def test_golden_items_cannot_be_rotated(self):
        self.reg.add_golden_item("gold-1", "math", "What is 2+2?", "4",
                                 actor=VERIFIER)
        with self.assertRaises(ValueError):
            self.reg.rotate_sealed_item("gold-1", "What is 3+3?", "6",
                                        actor=VERIFIER)

    def test_golden_empty_evaluation_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.run_golden_evaluation(VERIFIER, lambda prompt: "4")


if __name__ == "__main__":
    unittest.main()
