"""Tests for trust.manifest — artifact-bound build manifests
(cycle 7). Every test runs against a fake repo tree in a temp
directory, never the real repo (except the golden vector, whose
tree is built byte-for-byte in the test itself).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust.manifest import (
    ManifestError,
    build_manifest,
    canonicalise_path,
    manifest_from_json,
    verify_manifest,
    write_manifest,
)

GOLDEN_MANIFEST_HASH = \
    "5123d710122b23052e245f57ae6e083ce65192a5fa7f189fe9320974d95262b1"
REVIEW = "internal/REVIEW.md"


def make_tree(root: Path):
    (root / "core").mkdir(parents=True)
    (root / "core" / "a.py").write_text("A = 1\n")
    (root / "eval").mkdir()
    (root / "eval" / "gate.py").write_text("GATE = True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (root / "internal").mkdir()
    (root / "internal" / "REVIEW.md").write_text("# review\n")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text("excluded\n")
    (root / "state").mkdir()
    (root / "state" / "state.json").write_text("{}\n")
    return root


def build(root, **over):
    kw = dict(proposal_id="prop-1", item_id="item-1",
              review_record_path=REVIEW, stage="final",
              created_at="2026-11-20T00:00:00+00:00")
    kw.update(over)
    return build_manifest(root, **kw)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_tree(Path(self.tmp.name) / "repo")

    def tearDown(self):
        self.tmp.cleanup()

    def test_golden_vector(self):
        m = build(self.root)
        self.assertEqual(m.manifest_hash, GOLDEN_MANIFEST_HASH)

    def test_build_and_verify_clean(self):
        m = build(self.root)
        self.assertTrue(verify_manifest(self.root, m).is_empty())
        paths = [f["path"] for f in m.files]
        self.assertEqual(paths, ["core/a.py", "eval/gate.py",
                                 "tests/test_a.py"])
        self.assertNotIn("docs/notes.md", paths)
        self.assertNotIn("state/state.json", paths)

    def test_roundtrip_through_json(self):
        m = build(self.root)
        m2 = manifest_from_json(m.to_json())
        self.assertEqual(m2, m)
        self.assertTrue(verify_manifest(self.root, m2).is_empty())

    def test_field_tamper_breaks_hash(self):
        m = build(self.root)
        doc = json.loads(m.to_json())
        doc["files"][0]["sha256"] = "0" * 64
        tampered = manifest_from_json(json.dumps(doc))
        diff = verify_manifest(self.root, tampered)
        self.assertTrue(diff.manifest_hash_mismatch)
        self.assertFalse(diff.is_empty())

    def test_content_swap_between_files_detected(self):
        m = build(self.root)
        a = (self.root / "core" / "a.py").read_text()
        b = (self.root / "eval" / "gate.py").read_text()
        (self.root / "core" / "a.py").write_text(b)
        (self.root / "eval" / "gate.py").write_text(a)
        diff = verify_manifest(self.root, m)
        self.assertEqual({c["path"] for c in diff.changed},
                         {"core/a.py", "eval/gate.py"})

    def test_added_file_any_extension_detected(self):
        m = build(self.root)
        (self.root / "core" / "evil.pth").write_text("import os\n")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.added, ["core/evil.pth"])
        (self.root / "core" / "evil.pth").unlink()
        (self.root / "signing").mkdir()
        (self.root / "signing" / "x.json").write_text("{}")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.added, ["signing/x.json"])

    def test_removed_and_renamed_detected(self):
        m = build(self.root)
        (self.root / "tests" / "test_a.py").rename(
            self.root / "tests" / "test_b.py")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.removed, ["tests/test_a.py"])
        self.assertEqual(diff.added, ["tests/test_b.py"])

    def test_excluded_roots_are_free_to_change(self):
        m = build(self.root)
        (self.root / "docs" / "notes.md").write_text("changed\n")
        (self.root / "state" / "state.json").write_text('{"x": 1}\n')
        (self.root / "docs" / "new.md").write_text("new\n")
        self.assertTrue(verify_manifest(self.root, m).is_empty())

    def test_review_record_edit_detected(self):
        m = build(self.root)
        (self.root / "internal" / "REVIEW.md").write_text("# edited\n")
        diff = verify_manifest(self.root, m)
        self.assertTrue(diff.review_record_mismatch)

    def test_reorder_and_reformat_still_verify(self):
        m = build(self.root)
        doc = json.loads(m.to_json())
        doc["files"] = list(reversed(doc["files"]))
        text = json.dumps(doc, indent=3)
        m2 = manifest_from_json(text)
        self.assertTrue(verify_manifest(self.root, m2).is_empty())

    def test_strict_load_refusals(self):
        m = build(self.root)
        doc = json.loads(m.to_json())
        doc["files"].append(dict(doc["files"][0]))
        with self.assertRaises(ManifestError):
            manifest_from_json(json.dumps(doc))
        doc = json.loads(m.to_json())
        doc["surprise"] = 1
        with self.assertRaises(ManifestError):
            manifest_from_json(json.dumps(doc))
        with self.assertRaises(ManifestError):
            manifest_from_json('{"v": NaN}')
        text = m.to_json()
        dup = text.replace('"stage":"final"',
                           '"stage":"final","stage":"final"', 1)
        with self.assertRaises(ManifestError):
            manifest_from_json(dup)

    def test_mtime_and_plain_chmod_do_not_break(self):
        m = build(self.root)
        target = self.root / "core" / "a.py"
        os.utime(target, (1_000_000, 1_000_000))
        os.chmod(target, 0o644)
        self.assertTrue(verify_manifest(self.root, m).is_empty())

    def test_executable_flip_detected(self):
        m = build(self.root)
        os.chmod(self.root / "core" / "a.py", 0o755)
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.executable_flips, ["core/a.py"])
        self.assertFalse(diff.is_empty())

    def test_pycache_shadow_refuses_build_and_invalidates(self):
        # A .pyc inside __pycache__ is a bytecode shadow: Python
        # may execute it instead of the authorised source, so its
        # mere presence refuses a build and invalidates a verify.
        cache = self.root / "core" / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-313.pyc").write_bytes(b"\x00\x01")
        with self.assertRaises(ManifestError):
            build(self.root)
        (cache / "a.cpython-313.pyc").unlink()
        m = build(self.root)
        self.assertTrue(verify_manifest(self.root, m).is_empty())
        (cache / "a.cpython-313.pyc").write_bytes(b"\x00\x01")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.pycache_shadows,
                         ["core/__pycache__/a.cpython-313.pyc"])
        self.assertFalse(diff.is_empty())

    def test_forged_timestamp_pyc_is_detected_as_shadow(self):
        # The war room's probe: bytecode compiled from different
        # source, header forged to the real source's mtime+size,
        # executes at import while the source never changes. The
        # manifest cannot bless the shadow's content — it refuses
        # the shadow's existence.
        import importlib.util
        import marshal
        import struct
        import time
        m = build(self.root)
        source = self.root / "core" / "a.py"
        stat = source.stat()
        evil_code = compile("A = 999\n", str(source), "exec")
        header = importlib.util.MAGIC_NUMBER + struct.pack(
            "<III", 0, int(stat.st_mtime), stat.st_size)
        cache = self.root / "core" / "__pycache__"
        cache.mkdir()
        tag = sys.implementation.cache_tag
        (cache / f"a.{tag}.pyc").write_bytes(
            header + marshal.dumps(evil_code))
        diff = verify_manifest(self.root, m)
        self.assertEqual(len(diff.pycache_shadows), 1)
        self.assertFalse(diff.is_empty())
        self.assertIsNotNone(time)

    def test_symlinked_pycache_directory_refused(self):
        # A SYMLINKED __pycache__ points the interpreter at
        # bytecode outside the tree — the shadow channel with a
        # narrower plant. It refuses a build, is reported by the
        # shadow scan, and refuses verification.
        from trust.manifest import _find_shadows
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
        os.symlink(outside, self.root / "core" / "__pycache__")
        with self.assertRaises(ManifestError):
            build(self.root)
        self.assertEqual(_find_shadows(self.root),
                         ["core/__pycache__"])
        clean = Path(self.tmp.name) / "clean"
        make_tree(clean)
        manifest = build(clean)
        os.symlink(outside, clean / "core" / "__pycache__")
        with self.assertRaises(ManifestError):
            verify_manifest(clean, manifest)

    def test_planted_pyc_outside_pycache_is_added_file(self):
        m = build(self.root)
        (self.root / "core" / "evil.pyc").write_bytes(b"\x00\x01")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.added, ["core/evil.pyc"])

    def test_symlink_refused(self):
        os.symlink(self.root / "eval" / "gate.py",
                   self.root / "core" / "link.py")
        with self.assertRaises(ManifestError):
            build(self.root)

    def test_fifo_refused(self):
        os.mkfifo(self.root / "core" / "pipe")
        with self.assertRaises(ManifestError):
            build(self.root)

    def test_case_collision_refused(self):
        (self.root / "core" / "A.py").write_text("A = 2\n")
        with self.assertRaises(ManifestError):
            build(self.root)

    def test_bucket_isolation(self):
        m = build(self.root)
        (self.root / "tests" / "test_a.py").write_text(
            "def test_a():\n    assert True\n")
        diff = verify_manifest(self.root, m)
        self.assertEqual(diff.bucket_mismatches, ["tests"])
        self.assertEqual([c["path"] for c in diff.changed],
                         ["tests/test_a.py"])

    def test_path_spellings_refused(self):
        for bad in ("core/../eval/gate.py", "/core/a.py", "core//a.py",
                    "core\\a.py", "core/./a.py", ""):
            with self.assertRaises(ManifestError, msg=bad):
                canonicalise_path(bad)

    def test_write_into_included_root_refused(self):
        m = build(self.root)
        with self.assertRaises(ManifestError):
            write_manifest(m, self.root, self.root / "core" / "m.json")
        out = write_manifest(m, self.root,
                             self.root / "state" / "trust" / "m.json")
        self.assertTrue(out.exists())

    def test_missing_root_and_missing_review_record(self):
        with self.assertRaises(ManifestError):
            build_manifest(Path(self.tmp.name) / "nope",
                           proposal_id="p", item_id="i",
                           review_record_path=REVIEW, stage="final")
        (self.root / "internal" / "REVIEW.md").unlink()
        with self.assertRaises(ManifestError):
            build(self.root)

    def test_caps_enforced(self):
        import trust.manifest as manifest_mod
        original = manifest_mod.MAX_TREE_FILES
        manifest_mod.MAX_TREE_FILES = 2
        try:
            with self.assertRaises(ManifestError):
                build(self.root)
        finally:
            manifest_mod.MAX_TREE_FILES = original


if __name__ == "__main__":
    unittest.main()
