"""Tests for the core cycle loop. Standard library only."""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop, CorruptStateError, InvalidTransition

CODERS = ["coder-a", "coder-b", "coder-c"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {
    "metric": "tests_passing",
    "before": 0,
    "after": 21,
    "evidence_ref": "tests/test_loop.py run output",
    "verifier": "rev-1",
}


def item(item_id="task-1", title="Build the core loop", leverage=5):
    return {"id": item_id, "title": title, "leverage": leverage}


class LoopTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.loop = CoreLoop(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cycle(self, **overrides):
        args = dict(coders=CODERS, reviewers=REVIEWERS, verdict="reconciled",
                    verify_passed=True, delta=dict(DELTA))
        args.update(overrides)
        return self.loop.run_one_cycle(**args)


class TestHappyPath(LoopTestCase):
    def test_full_cycle_completes_and_marks_item_done(self):
        self.loop.scan([item()])
        entry = self.run_cycle()
        self.assertEqual(entry["item_id"], "task-1")
        self.assertEqual(entry["verdict"], "reconciled")
        self.assertEqual(self.loop.state["backlog"][0]["status"], "done")
        self.assertEqual(self.loop.state["phase"], "SCAN")  # ready for next cycle

    def test_full_cycle_increments_cycle_id_monotonically(self):
        self.loop.scan([item(), item("task-2", "Second task", 4)])
        first = self.run_cycle()
        second = self.run_cycle()
        self.assertEqual((first["cycle_id"], second["cycle_id"]), (1, 2))
        self.assertEqual(len(self.loop.state["history"]), 2)

    def test_empty_backlog_idles_without_crashing(self):
        self.assertIsNone(self.run_cycle())
        self.assertEqual(self.loop.state["phase"], "SCAN")
        self.assertEqual(self.loop.state["history"], [])


class TestPersistence(LoopTestCase):
    def test_state_roundtrip_preserves_all_fields(self):
        self.loop.scan([item()])
        self.run_cycle()
        reloaded = CoreLoop(self.dir)
        self.assertEqual(reloaded.state, self.loop.state)

    def test_saved_file_is_valid_json_with_expected_keys(self):
        self.loop.scan([item()])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        for key in ("schema_version", "cycle_seq", "phase", "backlog", "history", "deltas"):
            self.assertIn(key, data)

    def test_load_missing_file_creates_fresh_state(self):
        with tempfile.TemporaryDirectory() as other:
            fresh = CoreLoop(Path(other))
            self.assertEqual(fresh.state["cycle_seq"], 0)
            self.assertEqual(fresh.state["backlog"], [])

    def test_corrupt_state_fails_closed_and_quarantines(self):
        self.loop.scan([item()])
        (self.dir / "state.json").write_text('{"schema_version": 1, "cycl', encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)
        quarantined = list(self.dir.glob("state.corrupt-*.json"))
        self.assertEqual(len(quarantined), 1)

    def test_nan_in_state_is_rejected(self):
        self.loop.scan([item()])
        raw = (self.dir / "state.json").read_text(encoding="utf-8")
        (self.dir / "state.json").write_text(raw.replace('"cycle_seq": 0', '"cycle_seq": NaN'),
                                             encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)


class TestPhaseAndGates(LoopTestCase):
    def test_no_public_phase_walking(self):
        # Phase advancement is not a public operation; cycles run whole.
        self.assertFalse(hasattr(self.loop, "transition"))
        self.assertEqual(self.loop.state["phase"], "SCAN")

    def test_cycle_refuses_non_scan_start(self):
        self.loop.scan([item()])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        data["phase"] = "BUILD"
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        stranded = CoreLoop(self.dir)
        with self.assertRaises(InvalidTransition):
            stranded.run_one_cycle(CODERS, REVIEWERS, "reconciled", True, dict(DELTA))

    def test_build_requires_three_distinct_coders(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(coders=["only", "two"])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(coders=["same", "same", "same"])

    def test_review_requires_six_distinct_reviewers(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(reviewers=REVIEWERS[:5])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(reviewers=["one"] * 6)

    def test_split_verdict_blocks_cycle(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(verdict="split")
        self.assertEqual(self.loop.state["backlog"][0]["status"], "pending")

    def test_failed_verification_blocks_cycle(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(verify_passed=False)


class TestDelta(LoopTestCase):
    def test_self_improve_records_measurable_delta(self):
        self.loop.scan([item()])
        self.run_cycle()
        self.assertEqual(len(self.loop.state["deltas"]), 1)
        delta = self.loop.state["deltas"][0]
        self.assertEqual(delta["change"], 21)
        self.assertEqual(delta["cycle_id"], 1)
        self.assertTrue(delta["recorded_at"])

    def test_delta_without_evidence_is_rejected(self):
        self.loop.scan([item()])
        bad = dict(DELTA, evidence_ref="")
        with self.assertRaises((InvalidTransition, ValueError)):
            self.run_cycle(delta=bad)

    def test_delta_verifier_must_not_be_builder(self):
        self.loop.scan([item()])
        bad = dict(DELTA, verifier="coder-a")
        with self.assertRaises(InvalidTransition):
            self.run_cycle(delta=bad)

    def test_deltas_append_across_cycles(self):
        self.loop.scan([item(), item("task-2", "Second task", 4)])
        self.run_cycle()
        self.run_cycle(delta=dict(DELTA, before=21, after=25))
        self.assertEqual([d["cycle_id"] for d in self.loop.state["deltas"]], [1, 2])


class TestBacklog(LoopTestCase):
    def test_pick_next_returns_highest_leverage_fifo_on_ties(self):
        self.loop.scan([item("a", "Low", 1), item("b", "High first", 9),
                        item("c", "High second", 9)])
        self.assertEqual(self.loop.pick_next()["id"], "b")

    def test_pick_next_skips_done_and_unapproved_external(self):
        self.loop.scan([{"id": "ext-1", "title": "External idea", "leverage": 99,
                         "source_type": "external_scan"}])
        self.assertFalse(self.loop.state["backlog"][0]["approved"])
        self.loop.scan([item("task-9", "Internal task", 1)])
        self.assertEqual(self.loop.pick_next()["id"], "task-9")

    def test_duplicate_id_rejected_and_duplicate_title_deduped(self):
        self.loop.scan([item()])
        with self.assertRaises(ValueError):
            self.loop.scan([item("task-1", "A different title", 3)])
        added = self.loop.scan([item("task-2", "build  the CORE loop", 3)])
        self.assertEqual(added, 0)

    def test_traversal_style_id_rejected(self):
        for bad in ("../../etc", "/tmp/x", "a/b", "..", ""):
            with self.assertRaises(ValueError):
                self.loop.scan([{"id": bad, "title": "Bad id", "leverage": 1}])

    def test_empty_title_and_nonfinite_leverage_rejected(self):
        with self.assertRaises(ValueError):
            self.loop.scan([{"id": "ok-1", "title": "   ", "leverage": 1}])
        with self.assertRaises(ValueError):
            self.loop.scan([{"id": "ok-2", "title": "Fine", "leverage": math.inf}])


class TestReviewFixes(LoopTestCase):
    def test_external_item_cannot_self_approve_but_approve_works(self):
        for sneaky in (True, "false", 1):
            with tempfile.TemporaryDirectory() as other:
                loop = CoreLoop(Path(other))
                loop.scan([{"id": "ext-1", "title": "Sneaky idea", "leverage": 9,
                            "source_type": "external_scan", "approved": sneaky}])
                self.assertFalse(loop.state["backlog"][0]["approved"])
                self.assertIsNone(loop.pick_next())
                loop.approve("ext-1", "coordinator")
                self.assertEqual(loop.pick_next()["id"], "ext-1")
                self.assertEqual(loop.state["backlog"][0]["approved_by"], "coordinator")

    def test_string_participants_and_overlap_rejected(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(coders="abc")
        with self.assertRaises(InvalidTransition):
            self.run_cycle(coders=CODERS, reviewers=CODERS + ["rev-7", "rev-8", "rev-9"])

    def test_verifier_must_be_a_reviewer(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(delta=dict(DELTA, verifier="outsider"))

    def test_delta_regression_and_overflow_rejected(self):
        self.loop.scan([item()])
        with self.assertRaises(InvalidTransition):
            self.run_cycle(delta=dict(DELTA, before=10, after=10))
        with self.assertRaises(InvalidTransition):
            self.run_cycle(delta=dict(DELTA, before=-1e308, after=1e308))

    def test_failed_gate_leaves_memory_and_disk_unchanged(self):
        self.loop.scan([item()])
        before_bytes = (self.dir / "state.json").read_bytes()
        before_state = json.dumps(self.loop.state, sort_keys=True)
        with self.assertRaises(InvalidTransition):
            self.run_cycle(verdict="split")
        self.assertEqual((self.dir / "state.json").read_bytes(), before_bytes)
        self.assertEqual(json.dumps(self.loop.state, sort_keys=True), before_state)

    def test_failed_scan_batch_is_all_or_nothing(self):
        with self.assertRaises(ValueError):
            self.loop.scan([item("good-1", "Good item", 1),
                            {"id": "bad id!", "title": "Bad", "leverage": 1}])
        self.assertEqual(self.loop.state["backlog"], [])
        self.assertEqual(CoreLoop(self.dir).state["backlog"], [])

    def test_crafted_state_with_traversal_id_fails_closed(self):
        self.loop.scan([item()])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        data["backlog"][0]["id"] = "../../etc/passwd"
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)

    def test_trailing_newline_id_and_unicode_dedup(self):
        with self.assertRaises(ValueError):
            self.loop.scan([{"id": "task-1\n", "title": "Newline", "leverage": 1}])
        self.loop.scan([{"id": "cafe-1", "title": "Café plan", "leverage": 1}])
        added = self.loop.scan([{"id": "cafe-2", "title": "Café plan", "leverage": 2}])
        self.assertEqual(added, 0)

    def test_forged_delta_verifier_fails_closed_on_load(self):
        self.loop.scan([item()])
        self.run_cycle()
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        data["deltas"][0]["verifier"] = "outsider-1"
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)
        data["deltas"][0]["verifier"] = "rev-1"
        data["cycle_seq"] = 99
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)

    def test_crafted_done_status_without_history_fails_closed(self):
        self.loop.scan([item()])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        data["backlog"][0]["status"] = "done"
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)

    def test_crafted_external_approval_with_empty_approver_fails_closed(self):
        self.loop.scan([{"id": "ext-1", "title": "External idea", "leverage": 9,
                         "source_type": "external_scan"}])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        data["backlog"][0]["approved"] = True
        data["backlog"][0]["approved_by"] = ""
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)

    def test_crafted_open_backlog_over_cap_fails_closed(self):
        import hashlib
        import unicodedata as uni
        self.loop.scan([item()])
        data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        for n in range(2, 105):
            title = f"Crafted item {n}"
            norm = " ".join(uni.normalize("NFKC", title).casefold().split())
            data["backlog"].append({
                "id": f"craft-{n}", "title": title,
                "title_hash": hashlib.sha256(norm.encode()).hexdigest(),
                "leverage": 1, "status": "pending", "source_type": "internal",
                "approved": True, "approved_by": "intake", "seq": n})
        (self.dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            CoreLoop(self.dir)

    def test_oversize_title_rejected(self):
        with self.assertRaises(ValueError):
            self.loop.scan([{"id": "big-1", "title": "x" * 2001, "leverage": 1}])


if __name__ == "__main__":
    unittest.main()
