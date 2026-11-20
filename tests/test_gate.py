"""Tests for the self-change safety gate. Standard library only."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import (
    GateInputError,
    VerifierAttestation,
    check_forgetting,
    check_no_regression,
    check_protected_paths,
    evaluate_self_change,
)

BUILDERS = ["builder-1", "builder-2", "builder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
SEALED_HASH = "a" * 64

PUBLIC_BASE = {"bench-a": 0.5, "bench-b": 0.5}
SEALED_BASE = {"hidden-a": 0.5, "hidden-b": 0.5}
CAP_BASE = {"coding": 0.7, "reasoning": 0.6, "memory-recall": 0.8}


def attestation(**overrides):
    fields = dict(verifier_id="rev-1", decision="approve",
                  sealed_hash=SEALED_HASH, reward_hacking_checked=True,
                  evidence_ref="sealed run 7", attested_at="2026-11-19T00:00:00+00:00")
    fields.update(overrides)
    return VerifierAttestation(**fields)


def evaluate(**overrides):
    args = dict(
        proposal_id="proposal-1",
        builder_ids=BUILDERS,
        reviewer_ids=REVIEWERS,
        baseline_public=dict(PUBLIC_BASE),
        candidate_public=dict(PUBLIC_BASE),
        baseline_sealed=dict(SEALED_BASE),
        candidate_sealed=dict(SEALED_BASE),
        capability_baseline=dict(CAP_BASE),
        capability_candidate=dict(CAP_BASE),
        attestation=attestation(),
        expected_sealed_hash=SEALED_HASH,
    )
    args.update(overrides)
    return evaluate_self_change(**args)


class TestAccept(unittest.TestCase):
    def test_all_equal_with_one_sealed_gain_accepts(self):
        cand = dict(SEALED_BASE)
        cand["hidden-a"] = 0.6
        decision = evaluate(candidate_sealed=cand)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.verifier_id, "rev-1")

    def test_public_gain_plus_sealed_gain_accepts(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-a"] = 0.9
        sealed = dict(SEALED_BASE)
        sealed["hidden-b"] = 0.55
        decision = evaluate(candidate_public=pub, candidate_sealed=sealed)
        self.assertTrue(decision.accepted)


class TestRegression(unittest.TestCase):
    def test_single_public_regression_rejects(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-b"] = 0.499
        sealed = dict(SEALED_BASE)
        sealed["hidden-a"] = 0.9
        decision = evaluate(candidate_public=pub, candidate_sealed=sealed)
        self.assertFalse(decision.accepted)
        self.assertIn("regression", decision.reasons)
        self.assertEqual(decision.regressions[0].suite, "public")
        self.assertEqual(decision.regressions[0].benchmark_id, "bench-b")

    def test_single_sealed_regression_rejects_despite_public_gain(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-a"] = 0.9
        sealed = dict(SEALED_BASE)
        sealed["hidden-b"] = 0.45
        decision = evaluate(candidate_public=pub, candidate_sealed=sealed)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.regressions[0].suite, "sealed")

    def test_tiny_drop_still_rejects(self):
        sealed = dict(SEALED_BASE)
        sealed["hidden-a"] = 0.6
        sealed["hidden-b"] = 0.5 - 1e-6
        decision = evaluate(candidate_sealed=sealed)
        self.assertFalse(decision.accepted)
        self.assertIn("regression", decision.reasons)

    def test_missing_candidate_benchmark_is_regression_not_skip(self):
        sealed = {"hidden-a": 0.9}
        decision = evaluate(candidate_sealed=sealed)
        self.assertFalse(decision.accepted)
        missing = [r for r in decision.regressions
                   if r.benchmark_id == "hidden-b"]
        self.assertEqual(len(missing), 1)

    def test_unbaselined_candidate_benchmark_raises(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-new"] = 0.9
        with self.assertRaises(GateInputError):
            evaluate(candidate_public=pub)

    def test_check_no_regression_rejects_nonzero_epsilon(self):
        with self.assertRaises(GateInputError):
            check_no_regression(PUBLIC_BASE, PUBLIC_BASE, suite="public",
                                epsilon=0.01)


class TestNoSealedGain(unittest.TestCase):
    def test_public_only_gain_rejects(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-a"] = 0.9
        decision = evaluate(candidate_public=pub)
        self.assertFalse(decision.accepted)
        self.assertIn("no_sealed_gain", decision.reasons)

    def test_noop_change_rejects(self):
        decision = evaluate()
        self.assertFalse(decision.accepted)
        self.assertIn("no_sealed_gain", decision.reasons)


class TestForgetting(unittest.TestCase):
    def test_forgetting_drop_rejects_even_when_suites_pass(self):
        sealed = dict(SEALED_BASE)
        sealed["hidden-a"] = 0.7
        caps = dict(CAP_BASE)
        caps["memory-recall"] = 0.7
        decision = evaluate(candidate_sealed=sealed, capability_candidate=caps)
        self.assertFalse(decision.accepted)
        self.assertIn("forgetting", decision.reasons)
        self.assertEqual(decision.forgetting_failures[0].benchmark_id,
                         "memory-recall")
        self.assertEqual(decision.regressions, ())

    def test_check_forgetting_clean_snapshot_passes(self):
        self.assertEqual(check_forgetting(CAP_BASE, dict(CAP_BASE)), ())


class TestVerifier(unittest.TestCase):
    def test_builder_as_verifier_rejects(self):
        decision = evaluate(attestation=attestation(verifier_id="builder-1"))
        self.assertFalse(decision.accepted)
        self.assertIn("verifier_is_builder", decision.reasons)
        self.assertIn("verifier_not_reviewer", decision.reasons)

    def test_verifier_not_a_reviewer_rejects(self):
        decision = evaluate(attestation=attestation(verifier_id="outsider-1"))
        self.assertFalse(decision.accepted)
        self.assertIn("verifier_not_reviewer", decision.reasons)

    def test_wrong_sealed_hash_rejects(self):
        decision = evaluate(attestation=attestation(sealed_hash="b" * 64))
        self.assertFalse(decision.accepted)
        self.assertIn("sealed_hash_mismatch", decision.reasons)

    def test_no_reward_hacking_check_rejects(self):
        decision = evaluate(attestation=attestation(reward_hacking_checked=False))
        self.assertFalse(decision.accepted)
        self.assertIn("reward_hacking_not_checked", decision.reasons)

    def test_reject_attestation_rejects(self):
        decision = evaluate(attestation=attestation(decision="reject"))
        self.assertFalse(decision.accepted)
        self.assertIn("verifier_did_not_approve", decision.reasons)

    def test_unparseable_attested_at_rejects(self):
        decision = evaluate(attestation=attestation(attested_at="banana"))
        self.assertFalse(decision.accepted)
        self.assertIn("bad_attested_at", decision.reasons)

    def test_missing_attestation_rejects(self):
        decision = evaluate(attestation=None)
        self.assertFalse(decision.accepted)
        self.assertIn("missing_attestation", decision.reasons)
        self.assertIsNone(decision.verifier_id)


class TestInputValidation(unittest.TestCase):
    def test_nan_score_fails_closed(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-a"] = float("nan")
        with self.assertRaises(GateInputError):
            evaluate(candidate_public=pub)

    def test_empty_sealed_map_fails_closed(self):
        with self.assertRaises(GateInputError):
            evaluate(candidate_sealed={})

    def test_overlapping_builders_reviewers_raise(self):
        with self.assertRaises(GateInputError):
            evaluate(reviewer_ids=REVIEWERS[:-1] + ["builder-1"])

    def test_too_few_builders_raise(self):
        with self.assertRaises(GateInputError):
            evaluate(builder_ids=["builder-1", "builder-2"])

    def test_all_failures_collected_in_one_decision(self):
        pub = dict(PUBLIC_BASE)
        pub["bench-a"] = 0.4
        caps = dict(CAP_BASE)
        caps["coding"] = 0.6
        decision = evaluate(
            candidate_public=pub,
            capability_candidate=caps,
            attestation=attestation(verifier_id="outsider-1"))
        self.assertFalse(decision.accepted)
        self.assertIn("regression", decision.reasons)
        self.assertIn("forgetting", decision.reasons)
        self.assertIn("verifier_not_reviewer", decision.reasons)
        self.assertIn("no_sealed_gain", decision.reasons)


class TestProtectedPaths(unittest.TestCase):
    def _valid_change(self, **overrides):
        sealed = dict(SEALED_BASE)
        sealed["hidden-a"] = 0.7
        return evaluate(candidate_sealed=sealed, **overrides)

    def test_change_targeting_the_gate_itself_rejects(self):
        decision = self._valid_change(changed_paths=["eval/gate.py"])
        self.assertFalse(decision.accepted)
        self.assertIn("protected_path", decision.reasons)
        self.assertEqual(decision.protected_violations, ("eval/gate.py",))

    def test_change_targeting_evaluator_calibration_or_state_rejects(self):
        for path in ("eval/registry.py", "eval/calibration.py",
                     "core/loop.py"):
            decision = self._valid_change(changed_paths=["products/x.py", path])
            self.assertFalse(decision.accepted, path)
            self.assertEqual(decision.protected_violations, (path,))

    def test_dot_slash_and_backslash_paths_are_normalised(self):
        decision = self._valid_change(changed_paths=["./eval/gate.py"])
        self.assertFalse(decision.accepted)
        self.assertEqual(check_protected_paths(["eval\\gate.py"]),
                         ("eval/gate.py",))

    def test_unprotected_change_still_accepts(self):
        decision = self._valid_change(
            changed_paths=["products/demo.py", "core/helpers.py"])
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.protected_violations, ())

    def test_no_paths_supplied_skips_the_check(self):
        decision = self._valid_change()
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.protected_violations, ())


class TestVerifierNote(unittest.TestCase):
    def _valid_change(self, **overrides):
        sealed = dict(SEALED_BASE)
        sealed["hidden-a"] = 0.7
        return evaluate(candidate_sealed=sealed, **overrides)

    def test_note_recorded_in_decision(self):
        decision = self._valid_change(
            verifier_note="seat-9 verifies this round; rotated from seat-4, "
                          "different pod from all builders")
        self.assertIn("rotated", decision.verifier_note)

    def test_note_defaults_empty_and_is_validated(self):
        self.assertEqual(self._valid_change().verifier_note, "")
        with self.assertRaises(GateInputError):
            self._valid_change(verifier_note=123)


if __name__ == "__main__":
    unittest.main()
