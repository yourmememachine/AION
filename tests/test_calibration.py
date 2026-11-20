"""Tests for the calibration log. Standard library only."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.calibration import (
    CalibrationError,
    CalibrationLog,
    CorruptCalibrationError,
    make_blind_entry,
    minority_report,
    reviewer_stats,
    score_entry_against_outcome,
    summarise_subject,
)

_counter = [0]


def entry(reviewer="rev-1", subject="subj-1", score=0.8):
    _counter[0] += 1
    return make_blind_entry(entry_id=f"cal-{_counter[0]}", subject_id=subject,
                            subject_ref="gate proposal v1",
                            reviewer_id=reviewer, score=score)


class TestBlindEntries(unittest.TestCase):
    def test_blind_entry_defaults_unscored(self):
        e = entry(score=0.8)
        self.assertEqual(e["phase"], "blind")
        self.assertIsNone(e["outcome"])
        self.assertIsNone(e["brier"])
        self.assertTrue(e["recorded_at"])

    def test_bad_scores_rejected(self):
        for bad in (1.5, -0.1, float("nan"), float("inf"), True):
            with self.assertRaises(CalibrationError):
                entry(score=bad)


class LogTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = CalibrationLog(self.dir)

    def tearDown(self):
        self.tmp.cleanup()


class TestLogRules(LogTestCase):
    def test_duplicate_reviewer_subject_rejected(self):
        self.log.record_blind(entry(reviewer="rev-1"))
        with self.assertRaises(CalibrationError):
            self.log.record_blind(entry(reviewer="rev-1"))
        self.assertEqual(len(self.log.entries_for_subject("subj-1")), 1)

    def test_score_after_discussion_close_rejected(self):
        self.log.record_blind(entry(reviewer="rev-1"))
        self.log.close_discussion("subj-1")
        with self.assertRaises(CalibrationError):
            self.log.record_blind(entry(reviewer="rev-2"))

    def test_close_discussion_twice_rejected(self):
        self.log.record_blind(entry(reviewer="rev-1"))
        self.log.close_discussion("subj-1")
        with self.assertRaises(CalibrationError):
            self.log.close_discussion("subj-1")

    def test_recorded_score_cannot_carry_outcome(self):
        e = entry()
        e["outcome"] = 1.0
        with self.assertRaises(CalibrationError):
            self.log.record_blind(e)

    def test_entries_survive_reload(self):
        self.log.record_blind(entry(reviewer="rev-1", score=0.3))
        self.log.record_blind(entry(reviewer="rev-2", score=0.6))
        reloaded = CalibrationLog(self.dir)
        entries = reloaded.entries_for_subject("subj-1")
        self.assertEqual(len(entries), 2)
        self.assertEqual({e["reviewer_id"] for e in entries},
                         {"rev-1", "rev-2"})


class TestOutcomeScoring(LogTestCase):
    def test_outcome_scoring_computes_errors_and_is_one_shot(self):
        e = entry(score=0.8)
        scored = score_entry_against_outcome(e, outcome=1.0)
        self.assertAlmostEqual(scored["absolute_error"], 0.2)
        self.assertAlmostEqual(scored["brier"], 0.04)
        self.assertAlmostEqual(scored["signed_error"], -0.2)
        self.assertIsNone(e["outcome"])  # original unmutated
        with self.assertRaises(CalibrationError):
            score_entry_against_outcome(scored, outcome=0.0)

    def test_record_outcome_for_subject_scores_all_its_entries_only(self):
        for rev in ("rev-1", "rev-2", "rev-3"):
            self.log.record_blind(entry(reviewer=rev, subject="subj-1"))
        other = entry(reviewer="rev-1", subject="subj-2")
        self.log.record_blind(other)
        scored = self.log.record_outcome_for_subject("subj-1", outcome=0.0)
        self.assertEqual(len(scored), 3)
        self.assertTrue(all(s["outcome"] == 0.0 for s in scored))
        remaining = self.log.entries_for_subject("subj-2")
        self.assertIsNone(remaining[0]["outcome"])
        with self.assertRaises(CalibrationError):
            self.log.record_outcome_for_subject("subj-1", outcome=0.5)

    def test_scored_log_survives_reload(self):
        self.log.record_blind(entry(reviewer="rev-1", score=0.8))
        self.log.close_discussion("subj-1")
        self.log.record_outcome_for_subject("subj-1", outcome=1.0)
        reloaded = CalibrationLog(self.dir)
        entries = reloaded.entries_for_subject("subj-1")
        self.assertAlmostEqual(entries[0]["brier"], 0.04)


class TestSummaries(unittest.TestCase):
    def test_summary_preserves_dissent_not_just_mean(self):
        entries = [entry(reviewer="rev-1", score=0.1),
                   entry(reviewer="rev-2", score=0.5),
                   entry(reviewer="rev-3", score=0.9)]
        summary = summarise_subject(entries)
        self.assertEqual(summary["scores"],
                         (("rev-1", 0.1), ("rev-2", 0.5), ("rev-3", 0.9)))
        self.assertAlmostEqual(summary["spread"], 0.8)
        self.assertAlmostEqual(summary["mean"], 0.5)
        self.assertEqual(summary["n"], 3)

    def test_reviewer_stats_downweights_confidently_wrong(self):
        def scored(reviewer, score, outcome):
            return score_entry_against_outcome(
                entry(reviewer=reviewer, score=score), outcome=outcome)

        entries = [scored("rev-a", 0.95, 0.0), scored("rev-b", 0.55, 0.0),
                   entry(reviewer="rev-c", score=0.5)]
        stats = reviewer_stats(entries)
        self.assertGreater(stats["rev-a"]["mean_brier"],
                           stats["rev-b"]["mean_brier"])
        self.assertLess(stats["rev-a"]["weight"], stats["rev-b"]["weight"])
        self.assertNotIn("rev-c", stats)  # unscored entries are excluded


class TestCorruption(LogTestCase):
    def test_corrupt_log_fails_closed_and_quarantines(self):
        self.log.record_blind(entry(reviewer="rev-1"))
        (self.dir / "calibration.json").write_text("{broken")
        with self.assertRaises(CorruptCalibrationError):
            CalibrationLog(self.dir)
        self.assertEqual(
            len(list(self.dir.glob("calibration.corrupt-*.json"))), 1)

    def test_tampered_score_detected_on_load(self):
        self.log.record_blind(entry(reviewer="rev-1", score=0.3))
        raw = json.loads((self.dir / "calibration.json").read_text())
        raw["entries"][0]["score"] = 0.99
        (self.dir / "calibration.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptCalibrationError):
            CalibrationLog(self.dir)

    def test_tampered_outcome_detected_on_load(self):
        self.log.record_blind(entry(reviewer="rev-1", score=0.8))
        self.log.record_outcome_for_subject("subj-1", outcome=1.0)
        raw = json.loads((self.dir / "calibration.json").read_text())
        # Flip the outcome and recompute the error fields consistently;
        # the sealed outcome hash must still catch it.
        raw["entries"][0]["outcome"] = 0.0
        raw["entries"][0]["signed_error"] = 0.8
        raw["entries"][0]["absolute_error"] = 0.8
        raw["entries"][0]["brier"] = 0.64
        (self.dir / "calibration.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptCalibrationError):
            CalibrationLog(self.dir)

    def test_tampered_discussion_stamp_detected_on_load(self):
        self.log.record_blind(entry(reviewer="rev-1", score=0.5))
        self.log.close_discussion("subj-1")
        raw = json.loads((self.dir / "calibration.json").read_text())
        raw["entries"][0]["discussion_started_at"] = "1970-01-01T00:00:00+00:00"
        raw["closed_subjects"]["subj-1"] = "1970-01-01T00:00:00+00:00"
        (self.dir / "calibration.json").write_text(json.dumps(raw))
        with self.assertRaises(CorruptCalibrationError):
            CalibrationLog(self.dir)


class TestDissentAndMinority(LogTestCase):
    def record(self, entry_id, reviewer, score, role="reviewer"):
        return self.log.record_blind(make_blind_entry(
            entry_id=entry_id, subject_id="cycle-x-build",
            subject_ref="build under review", reviewer_id=reviewer,
            score=score, role=role))

    def test_dissent_role_recorded_and_validated(self):
        entry = self.record("e1", "rev-1", 0.35, role="dissent")
        self.assertEqual(entry["role"], "dissent")
        with self.assertRaises(CalibrationError):
            self.record("e2", "rev-2", 0.5, role="captain")

    def test_minority_report_tracks_dissent_and_outcome(self):
        self.record("e1", "rev-1", 0.9)
        self.record("e2", "rev-2", 0.85)
        self.record("e3", "rev-3", 0.35, role="dissent")
        self.log.close_discussion("cycle-x-build")
        report = minority_report(self.log.entries_for_subject("cycle-x-build"))
        self.assertEqual([d["reviewer_id"] for d in report["minority"]],
                         ["rev-3"])
        self.assertEqual(report["dissent_seats"], ("rev-3",))
        self.assertIsNone(report["minority_mean_brier"])
        self.log.record_outcome_for_subject("cycle-x-build", outcome=1.0)
        report = minority_report(self.log.entries_for_subject("cycle-x-build"))
        self.assertEqual(report["outcome"], 1.0)
        self.assertGreater(report["minority_mean_brier"],
                           report["majority_mean_brier"])

    def test_entry_without_role_still_records(self):
        entry = make_blind_entry(entry_id="e1", subject_id="cycle-x-build",
                                 subject_ref="build", reviewer_id="rev-1",
                                 score=0.5)
        del entry["role"]
        recorded = self.log.record_blind(entry)
        self.assertEqual(recorded["role"], "reviewer")


if __name__ == "__main__":
    unittest.main()
