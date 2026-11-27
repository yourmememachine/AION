"""Cycle 32-PROOF fix round 2 — failing-first tests for the
war-room items R1/R2 (1)-(4) on the first fix round:

(1) the harness import closure must include submodules named
    by `from package import submodule`;
(2) record_ship_with_proof must re-run the unscoped-change
    check against the SNAPSHOT before delegating, not only
    against the live trees;
(3) the whole-tree diff must not skip a .pyc file merely
    because of its suffix — only __pycache__ members are
    ignorable;
(4) the step-8 crash signatures must treat NameError and
    AttributeError harness breaks as crashes, not as the
    check noticing the mutation.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trust.proofcarry as pc
from trust.errors import ShipRefused

from test_cycle32_proof_ship import ProofShipFixture


class FromImportClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "tree"
        (self.root / "helpers").mkdir(parents=True)
        (self.root / "check.py").write_text(
            "from helpers import util\n"
            "print(util.VALUE)\n")
        (self.root / "helpers" / "__init__.py").write_text("")
        (self.root / "helpers" / "util.py").write_text("VALUE = 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_from_package_import_submodule_in_closure(self):
        deps = pc._harness_dependencies(
            [sys.executable, "check.py"], self.root)
        self.assertIn("helpers/util.py", deps)

    def test_from_import_plain_name_not_invented_as_module(self):
        (self.root / "check.py").write_text(
            "from helpers import VALUE\nprint(VALUE)\n")
        (self.root / "helpers" / "__init__.py").write_text("VALUE = 1\n")
        deps = pc._harness_dependencies(
            [sys.executable, "check.py"], self.root)
        self.assertNotIn("helpers/VALUE.py", deps)


class WholeTreePycTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name) / "base"
        post = Path(self.tmp.name) / "post"
        for root in (base, post):
            root.mkdir(parents=True)
            (root / "module.py").write_text("VALUE = 1\n")
        (post / "evil.pyc").write_bytes(b"\x42\x0d\x0d\x0a payload")
        self.base, self.post = base, post

    def tearDown(self):
        self.tmp.cleanup()

    def test_root_level_pyc_visible_to_whole_tree_diff(self):
        changed = pc._whole_tree_changed_paths(self.base, self.post)
        self.assertIn("evil.pyc", changed)

    def test_root_level_pyc_is_unscoped_change(self):
        unscoped = pc._unscoped_changes(
            self.base, self.post, ["module.py"])
        self.assertIn("evil.pyc", unscoped)

    def test_pycache_pyc_still_ignored(self):
        cache = self.post / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_bytes(b"cached")
        changed = pc._whole_tree_changed_paths(self.base, self.post)
        self.assertNotIn("__pycache__/module.cpython-312.pyc", changed)


class CrashMarkerTests(unittest.TestCase):
    def test_attribute_error_is_harness_crash(self):
        self.assertTrue(pc._harness_crash_in_stderr(
            b"Traceback ...\nAttributeError: 'X' has no attribute 'y'\n"))

    def test_name_error_is_harness_crash(self):
        self.assertTrue(pc._harness_crash_in_stderr(
            b"Traceback ...\nNameError: name 'util' is not defined\n"))

    def test_plain_assertion_is_not_harness_crash(self):
        self.assertFalse(pc._harness_crash_in_stderr(
            b"AssertionError: expected good marker\n"))


class SnapshotUnscopedRecheckTests(ProofShipFixture):
    def test_unscoped_change_found_only_on_snapshot_refuses(self):
        real = pc._unscoped_changes
        calls = {"n": 0}

        def flaky(base_root, post_root, scope_paths):
            calls["n"] += 1
            if calls["n"] == 1:
                return real(base_root, post_root, scope_paths)
            return ("docs/evil.md",)

        with mock.patch.object(pc, "_unscoped_changes", flaky):
            with self.assertRaises(ShipRefused):
                self.record_with_proof()
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(self.ledger.entries(), [])


if __name__ == "__main__":
    unittest.main()
