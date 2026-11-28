"""Tests for the canary self-modification manager. Stdlib only."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import GateDecision, VerifierAttestation, evaluate_self_change
from selfmod.canary import (
    MAX_FILES_PER_CHANGE,
    CanaryError,
    CanaryManager,
    ChangeProposal,
    CorruptJournalError,
    FileChange,
    NeedsRecoveryError,
    _candidate_root_hash,
    canonicalise_path,
)

BUILDERS = ["b-1", "b-2", "b-3"]
REVIEWERS = ["r-1", "r-2", "r-3", "r-4", "r-5", "r-6"]
SEALED_HASH = hashlib.sha256(b"sealed-manifest").hexdigest()


def make_decision(proposal_id, changes, *, accepted=True):
    root_hash = _candidate_root_hash(list(changes))
    if not accepted:
        return GateDecision(False, proposal_id, ("regression",), (), (),
                            "r-1", "2026-01-01T00:00:00+00:00", (),
                            f"content-hash:{root_hash}")
    att = VerifierAttestation("r-1", "approve", SEALED_HASH, True,
                              "sealed run ref", "2026-01-01T00:00:00+00:00")
    return evaluate_self_change(
        proposal_id=proposal_id, builder_ids=BUILDERS, reviewer_ids=REVIEWERS,
        baseline_public={"bench-a": 0.5}, candidate_public={"bench-a": 0.5},
        baseline_sealed={"bench-s": 0.5}, candidate_sealed={"bench-s": 0.9},
        capability_baseline={"cap-a": 0.7}, capability_candidate={"cap-a": 0.7},
        attestation=att, expected_sealed_hash=SEALED_HASH,
        evaluated_at="2026-01-01T00:00:00+00:00",
        changed_paths=[c.path for c in changes],
        verifier_note=f"content-hash:{root_hash}")


def proposal(pid="prop-1", changes=None, author="seat-9"):
    if changes is None:
        changes = (FileChange("mod.py", b"print('v2')\n"),)
    return ChangeProposal(pid, author, tuple(changes))


class CanaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "tree"
        self.root.mkdir()
        (self.root / "mod.py").write_bytes(b"print('v1')\n")
        (self.root / "keep.py").write_bytes(b"keep = 1\n")
        self.journal = base / "journal"
        self.mgr = CanaryManager(self.root, self.journal)

    def tearDown(self):
        self.tmp.cleanup()

    def stage_default(self, pid="prop-1", changes=None):
        p = proposal(pid, changes)
        return self.mgr.stage(p, make_decision(pid, p.changes))

    def commit_default(self, pid="prop-1", changes=None):
        self.stage_default(pid, changes)
        self.mgr.mark_verified(pid)
        return self.mgr.commit(pid)


class TestValidation(CanaryCase):
    def test_bad_proposal_id_rejected(self):
        p = ChangeProposal("Bad Id!", "seat-9", (FileChange("mod.py", b"x"),))
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-1", p.changes))

    def test_empty_change_rejected(self):
        p = ChangeProposal("prop-1", "seat-9", ())
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-1", (FileChange("a.py", b"x"),)))

    def test_non_bytes_payload_rejected(self):
        p = proposal(changes=(FileChange("mod.py", "text-not-bytes"),))
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-1", (FileChange("mod.py", b"x"),)))

    def test_deletion_refused_in_v1(self):
        p = proposal(changes=(FileChange("mod.py", None),))
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-1", (FileChange("mod.py", b"x"),)))

    def test_duplicate_paths_after_canonicalisation_rejected(self):
        changes = (FileChange("mod.py", b"a"), FileChange("./mod.py", b"b"))
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(changes=changes),
                           make_decision("prop-1", (FileChange("mod.py", b"a"),)))

    def test_traversal_and_absolute_paths_rejected(self):
        for bad in ("../evil.py", "a/../../evil.py", "/abs.py", "a\\..\\evil.py"):
            with self.assertRaises(CanaryError):
                canonicalise_path(bad)

    def test_noop_change_rejected(self):
        changes = (FileChange("mod.py", b"print('v1')\n"),)
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(changes=changes),
                           make_decision("prop-1", changes))

    def test_file_budget_rejected(self):
        changes = tuple(FileChange(f"f{i}.py", b"x") for i in range(MAX_FILES_PER_CHANGE + 1))
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(changes=changes),
                           make_decision("prop-1", changes))

    def test_oversize_file_rejected(self):
        changes = (FileChange("big.py", b"x" * (64 * 1024 + 1)),)
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(changes=changes),
                           make_decision("prop-1", changes))

    def test_canonicalise_collapses_spellings(self):
        self.assertEqual(canonicalise_path("./a//b.py"), "a/b.py")
        self.assertEqual(canonicalise_path("a\\b.py"), "a/b.py")
        self.assertEqual(canonicalise_path("core/./loop.py"), "core/loop.py")


class TestProtected(CanaryCase):
    def _stage_path(self, path):
        changes = (FileChange(path, b"evil"),)
        return self.mgr.stage(proposal(changes=changes),
                              make_decision("prop-1", changes))

    def test_eval_path_rejected(self):
        with self.assertRaises(CanaryError):
            self._stage_path("eval/gate.py")

    def test_core_loop_rejected(self):
        with self.assertRaises(CanaryError):
            self._stage_path("core/loop.py")

    def test_core_loop_dot_spelling_rejected(self):
        with self.assertRaises(CanaryError):
            self._stage_path("core/./loop.py")

    def test_eval_traversal_spelling_rejected(self):
        with self.assertRaises(CanaryError):
            canonicalise_path("x/../eval/gate.py")

    def test_selfmod_path_rejected_local_policy(self):
        with self.assertRaises(CanaryError):
            self._stage_path("selfmod/canary.py")

    def test_state_path_rejected_local_policy(self):
        with self.assertRaises(CanaryError):
            self._stage_path("state/state.json")


class TestDecisionBinding(CanaryCase):
    def test_rejected_decision_refused(self):
        p = proposal()
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-1", p.changes, accepted=False))

    def test_decision_for_other_proposal_refused(self):
        p = proposal()
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, make_decision("prop-9", p.changes))

    def test_decision_bound_to_other_bytes_refused(self):
        p = proposal()
        other = make_decision("prop-1", (FileChange("mod.py", b"different"),))
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, other)

    def test_forged_dataclass_lookalike_refused(self):
        class Fake:
            accepted = True
            proposal_id = "prop-1"
            reasons = ()
            regressions = ()
            forgetting_failures = ()
            protected_violations = ()
            verifier_id = "r-1"
            verifier_note = "content-hash:x"
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(), Fake())

    def test_inconsistent_accepted_decision_refused(self):
        p = proposal()
        root_hash = _candidate_root_hash(list(p.changes))
        bad = GateDecision(True, "prop-1", ("regression",), (), (), "r-1",
                           "2026-01-01T00:00:00+00:00", (),
                           f"content-hash:{root_hash}")
        with self.assertRaises(CanaryError):
            self.mgr.stage(p, bad)

    def test_proposal_id_single_use(self):
        self.stage_default()
        self.mgr.rollback("prop-1", "changed mind")
        with self.assertRaises(CanaryError):
            self.stage_default()


class TestStaging(CanaryCase):
    def test_stage_leaves_live_tree_byte_identical(self):
        before = (self.root / "mod.py").read_bytes()
        self.stage_default()
        self.assertEqual((self.root / "mod.py").read_bytes(), before)
        self.assertEqual(self.mgr.status()["state"], "STAGED")

    def test_canary_copy_has_candidate_bytes(self):
        self.stage_default()
        canary_file = self.journal / "canary" / "prop-1" / "mod.py"
        self.assertEqual(canary_file.read_bytes(), b"print('v2')\n")
        self.assertEqual((self.journal / "canary" / "prop-1" / "keep.py").read_bytes(),
                         b"keep = 1\n")

    def test_one_at_a_time(self):
        self.stage_default()
        p2 = proposal("prop-2", (FileChange("keep.py", b"keep = 2\n"),))
        with self.assertRaises(CanaryError):
            self.mgr.stage(p2, make_decision("prop-2", p2.changes))

    def test_commit_without_verify_refused(self):
        self.stage_default()
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")

    def test_unknown_proposal_refused(self):
        with self.assertRaises(CanaryError):
            self.mgr.mark_verified("nope-1")


class TestCommit(CanaryCase):
    def test_commit_applies_modify_and_create(self):
        changes = (FileChange("mod.py", b"print('v2')\n"),
                   FileChange("newdir/new.py", b"new = 1\n"))
        result = self.commit_default(changes=changes)
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v2')\n")
        self.assertEqual((self.root / "newdir/new.py").read_bytes(), b"new = 1\n")
        self.assertEqual(set(result.applied), {"mod.py", "newdir/new.py"})
        self.assertEqual(self.mgr.history()[-1]["state"], "COMMITTED")

    def test_double_commit_refused(self):
        self.commit_default()
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")

    def test_drift_blocks_commit_and_writes_nothing(self):
        self.stage_default()
        self.mgr.mark_verified("prop-1")
        (self.root / "mod.py").write_bytes(b"drifted\n")
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"drifted\n")

    def test_new_file_appearing_blocks_commit(self):
        changes = (FileChange("fresh.py", b"fresh = 1\n"),)
        self.stage_default(changes=changes)
        self.mgr.mark_verified("prop-1")
        (self.root / "fresh.py").write_bytes(b"squatter\n")
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "fresh.py").read_bytes(), b"squatter\n")

    def test_second_proposal_after_commit_allowed(self):
        self.commit_default()
        p2 = proposal("prop-2", (FileChange("keep.py", b"keep = 2\n"),))
        self.mgr.stage(p2, make_decision("prop-2", p2.changes))
        self.assertEqual(self.mgr.status()["proposal_id"], "prop-2")


class TestRollback(CanaryCase):
    def test_rollback_from_staged_leaves_live_untouched(self):
        self.stage_default()
        self.mgr.rollback("prop-1", "not wanted")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")
        self.assertEqual(self.mgr.history()[-1]["state"], "ROLLED_BACK")

    def test_rollback_after_commit_restores_bytes_and_removes_create(self):
        changes = (FileChange("mod.py", b"print('v2')\n"),
                   FileChange("newdir/new.py", b"new = 1\n"))
        self.commit_default(changes=changes)
        self.mgr.rollback("prop-1", "regression in the wild")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")
        self.assertFalse((self.root / "newdir/new.py").exists())
        self.assertFalse((self.root / "newdir").exists())

    def test_rollback_terminal_proposal_refused(self):
        self.stage_default()
        self.mgr.rollback("prop-1", "first")
        with self.assertRaises(CanaryError):
            self.mgr.rollback("prop-1", "second")

    def test_abort_from_staged(self):
        self.stage_default()
        self.mgr.abort("prop-1", "superseded")
        self.assertEqual(self.mgr.history()[-1]["state"], "ABORTED")
        self.assertIsNone(self.mgr.status())


class TestJournal(CanaryCase):
    def test_journal_survives_reconstruct(self):
        self.stage_default()
        mgr2 = CanaryManager(self.root, self.journal)
        self.assertEqual(mgr2.status()["proposal_id"], "prop-1")
        self.assertEqual(mgr2.status()["state"], "STAGED")

    def test_corrupt_journal_fails_closed_and_quarantines(self):
        self.stage_default()
        (self.journal / "journal.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(CorruptJournalError):
            CanaryManager(self.root, self.journal)
        self.assertTrue(list(self.journal.glob("journal.corrupt-*.json")))

    def test_tampered_journal_digest_fails_closed(self):
        self.commit_default()
        data = json.loads((self.journal / "journal.json").read_text(encoding="utf-8"))
        data["entries"][-1]["verifier_id"] = "r-9"
        (self.journal / "journal.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CorruptJournalError):
            CanaryManager(self.root, self.journal)

    def test_snapshot_tamper_detected_on_rollback(self):
        self.commit_default()
        snap = self.journal / "snapshots" / "prop-1" / "mod.py"
        snap.write_bytes(b"tampered\n")
        with self.assertRaises(CorruptJournalError):
            self.mgr.rollback("prop-1", "try rollback")

    def test_history_returns_deep_copies(self):
        self.stage_default()
        hist = self.mgr.history()
        hist[0]["state"] = "HACKED"
        self.assertEqual(self.mgr.history()[0]["state"], "STAGED")


class TestRecovery(CanaryCase):
    def test_mid_commit_crash_requires_and_allows_recovery(self):
        self.stage_default()
        self.mgr.mark_verified("prop-1")
        # Simulate a crash: journal left in COMMITTING, one file applied.
        entry = self.mgr._latest_entry("prop-1")
        self.mgr._transition(entry, "COMMITTING", applied_files=["mod.py"])
        (self.root / "mod.py").write_bytes(b"print('v2')\n")
        with self.assertRaises(NeedsRecoveryError):
            CanaryManager(self.root, self.journal)
        # Recovery goes through the public classmethod entry point —
        # no object.__new__ bypass (review cycle-5 F2).
        result = CanaryManager.recover_journal(self.root, self.journal)
        self.assertEqual(result["state"], "ROLLED_BACK")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")
        mgr2 = CanaryManager(self.root, self.journal)
        self.assertIsNone(mgr2.status())
        self.assertEqual(mgr2.history()[-1]["reason"], "crash_recovery")

    def test_recover_with_nothing_pending_refused(self):
        with self.assertRaises(CanaryError):
            self.mgr.recover()

    def test_journal_dir_inside_tree_refused(self):
        with self.assertRaises(CanaryError):
            CanaryManager(self.root, self.root / "journal")


class TestReviewFixes(CanaryCase):
    """Regression tests for the cycle-5 review findings."""

    def test_canary_tamper_refused_before_any_live_write(self):
        self.stage_default()
        self.mgr.mark_verified("prop-1")
        (self.journal / "canary" / "prop-1" / "mod.py").write_bytes(b"EVIL\n")
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")
        self.assertEqual(self.mgr.status()["state"], "VERIFIED")

    def test_canary_symlink_refused(self):
        self.stage_default()
        self.mgr.mark_verified("prop-1")
        canary_file = self.journal / "canary" / "prop-1" / "mod.py"
        canary_file.unlink()
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_bytes(b"SECRET\n")
        os.symlink(outside, canary_file)
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")

    def test_mode_only_drift_refused(self):
        self.stage_default()
        self.mgr.mark_verified("prop-1")
        os.chmod(self.root / "mod.py", 0o777)
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")

    def test_bare_protected_names_refused(self):
        for name in ("eval", "selfmod", ".git", "state"):
            with self.assertRaises(CanaryError):
                self._stage_one(name)

    def _stage_one(self, path):
        changes = (FileChange(path, b"x = 1\n"),)
        return self.mgr.stage(proposal(changes=changes),
                              make_decision("prop-1", changes))

    def test_preexisting_empty_dir_survives_rollback(self):
        (self.root / "preempty").mkdir()
        changes = (FileChange("preempty/new.py", b"new = 1\n"),)
        self.commit_default(changes=changes)
        self.mgr.rollback("prop-1", "undo")
        self.assertFalse((self.root / "preempty/new.py").exists())
        self.assertTrue((self.root / "preempty").is_dir())

    def test_failed_stage_leaves_no_orphans_and_id_retryable(self):
        blocker = self.journal / "canary" / "prop-1"
        blocker.mkdir(parents=True)
        with self.assertRaises(CanaryError):
            self.stage_default()
        self.assertFalse((self.journal / "snapshots" / "prop-1").exists())
        # The blocker pre-existed this attempt, so cleanup preserves it
        # (verification-round F4); removing it makes the id retryable.
        self.assertTrue(blocker.exists())
        blocker.rmdir()
        self.stage_default()
        self.assertEqual(self.mgr.status()["state"], "STAGED")

    def test_mid_commit_os_failure_wraps_and_rolls_back(self):
        changes = (FileChange("mod.py", b"print('v2')\n"),
                   FileChange("keep.py", b"keep = 2\n"))
        self.stage_default(changes=changes)
        self.mgr.mark_verified("prop-1")
        original = self.mgr._write_file_atomic
        calls = {"n": 0}

        def flaky(target, data, mode):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("injected disk failure")
            return original(target, data, mode)

        self.mgr._write_file_atomic = flaky
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "mod.py").read_bytes(), b"print('v1')\n")
        self.assertEqual((self.root / "keep.py").read_bytes(), b"keep = 1\n")
        self.assertEqual(self.mgr.history()[-1]["state"], "ROLLED_BACK")

    def test_missing_snapshot_is_typed_corruption(self):
        self.commit_default()
        snap = self.journal / "snapshots" / "prop-1" / "mod.py"
        snap.unlink()
        with self.assertRaises(CorruptJournalError):
            self.mgr.rollback("prop-1", "try rollback")


class TestVerificationRound2(CanaryCase):
    """Regression tests for the verification-round findings."""

    def test_fifo_in_tree_refused_not_hung(self):
        os.mkfifo(self.root / "myfifo")
        with self.assertRaises(CanaryError):
            self.stage_default()

    def test_canary_parent_symlink_refused(self):
        changes = (FileChange("sub/file.py", b"v = 2\n"),)
        (self.root / "sub").mkdir()
        (self.root / "sub/file.py").write_bytes(b"v = 1\n")
        self.stage_default(changes=changes)
        self.mgr.mark_verified("prop-1")
        canary_sub = self.journal / "canary" / "prop-1" / "sub"
        outside = Path(self.tmp.name) / "outside_sub"
        outside.mkdir()
        (outside / "file.py").write_bytes(b"v = 2\n")  # bytes match!
        import shutil as _sh
        _sh.rmtree(canary_sub)
        os.symlink(outside, canary_sub)
        with self.assertRaises(CanaryError):
            self.mgr.commit("prop-1")
        self.assertEqual((self.root / "sub/file.py").read_bytes(), b"v = 1\n")

    def test_stage_reserves_journal_headroom(self):
        import selfmod.canary as canary_mod
        original = canary_mod.MAX_JOURNAL_ENTRIES
        canary_mod.MAX_JOURNAL_ENTRIES = 4  # lifecycle needs 1 file + 5
        try:
            with self.assertRaises(CanaryError):
                self.stage_default()
        finally:
            canary_mod.MAX_JOURNAL_ENTRIES = original

    def test_lifecycle_transitions_exempt_from_soft_cap(self):
        import selfmod.canary as canary_mod
        self.stage_default()
        original = canary_mod.MAX_JOURNAL_ENTRIES
        # Soft cap exactly at the current entry count: verify, commit
        # and its transitions must still complete (hard cap governs).
        canary_mod.MAX_JOURNAL_ENTRIES = len(self.mgr.journal["entries"])
        try:
            result = None
            self.mgr.mark_verified("prop-1")
            result = self.mgr.commit("prop-1")
            self.assertEqual(result.applied, ("mod.py",))
            self.mgr.rollback("prop-1", "still journaled past soft cap")
            self.assertEqual(self.mgr.history()[-1]["state"], "ROLLED_BACK")
        finally:
            canary_mod.MAX_JOURNAL_ENTRIES = original

    def test_preexisting_snapshot_content_preserved_on_failed_stage(self):
        snap = self.journal / "snapshots" / "prop-1"
        snap.mkdir(parents=True)
        (snap / "sentinel.txt").write_bytes(b"do not delete\n")
        with self.assertRaises(CanaryError):
            self.stage_default()
        self.assertEqual((snap / "sentinel.txt").read_bytes(), b"do not delete\n")


class TestSymlinks(CanaryCase):
    def test_symlink_target_path_refused(self):
        outside = Path(self.tmp.name) / "outside.py"
        outside.write_bytes(b"outside\n")
        os.symlink(outside, self.root / "link.py")
        changes = (FileChange("link.py", b"pwned\n"),)
        with self.assertRaises(CanaryError):
            self.mgr.stage(proposal(changes=changes),
                           make_decision("prop-1", changes))


if __name__ == "__main__":
    unittest.main()
