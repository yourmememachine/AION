"""Tests for trust.proofcarry — proof artefacts for a change
(cycle 32). Every test runs against small fake base/post trees
in a temp directory, never the real repo.
"""

import base64
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing.gate_decision import _canonical, _sha256
from trust.errors import ShipRefused
from trust.proofcarry import (
    ProofError,
    build_proof_artefact,
    changed_files,
    record_ship_with_proof,
    tree_hash,
    verify_proof_artefact,
)


def recompute_hash(artefact):
    core = {k: v for k, v in artefact.items() if k != "artefact_hash"}
    artefact["artefact_hash"] = _sha256(_canonical(core))
    return artefact

CHECK = (
    "import pathlib, sys\n"
    "content = pathlib.Path('module.py').read_text()\n"
    "if 'good' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "print('bad')\n"
    "sys.exit(1)\n"
)

ALWAYS_PASS_CHECK = (
    "import sys\n"
    "print('ok-fixed')\n"
    "sys.exit(0)\n"
)

# Passes on both the base ('bad') and post ('good') contents,
# fails when module.py is missing or holds neither marker.
LENIENT_CHECK = (
    "import pathlib, sys\n"
    "try:\n"
    "    content = pathlib.Path('module.py').read_text()\n"
    "except OSError:\n"
    "    sys.exit(1)\n"
    "if 'good' in content or 'bad' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "sys.exit(1)\n"
)

SCOPE = ["module.py", "check.py"]


def make_tree(root: Path, module_content: str, check: str = CHECK):
    root.mkdir(parents=True)
    (root / "module.py").write_text(module_content)
    (root / "check.py").write_text(check)
    return root


def invariant(**over):
    inv = {
        "id": "inv-1",
        "description": "module holds the good marker",
        "argv": [sys.executable, "check.py"],
        "scope": "new",
    }
    inv.update(over)
    return inv


class ProofCarryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name) / "base"
        post = Path(self.tmp.name) / "post"
        self.base = make_tree(base, "VALUE = 'bad'\n")
        self.post = make_tree(post, "VALUE = 'good'\n")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **over):
        kw = dict(change_id="change-1", base_root=self.base,
                  post_root=self.post, scope_paths=SCOPE,
                  invariants=[invariant()],
                  created_at="2026-11-26T00:00:00+00:00")
        kw.update(over)
        return build_proof_artefact(**kw)

    def verify(self, artefact, **over):
        kw = dict(base_root=self.base, post_root=self.post)
        kw.update(over)
        return verify_proof_artefact(artefact, **kw)

    def test_happy_path_accept(self):
        artefact = self.build()
        self.assertEqual(artefact["format"], "proof-artefact/1")
        self.assertEqual(self.verify(artefact), ())
        self.assertEqual(
            self.verify(artefact, expected_change_id="change-1"), ())

    def test_tree_hash_and_changed_files(self):
        self.assertEqual(tree_hash(self.post, SCOPE),
                         tree_hash(self.post, list(reversed(SCOPE))))
        self.assertNotEqual(tree_hash(self.base, SCOPE),
                            tree_hash(self.post, SCOPE))
        changed = changed_files(self.base, self.post, SCOPE)
        self.assertEqual([c["path"] for c in changed], ["module.py"])
        self.assertIsNotNone(changed[0]["base_sha256"])
        self.assertIsNotNone(changed[0]["post_sha256"])

    def test_tamper_post_tree_refused(self):
        artefact = self.build()
        (self.post / "module.py").write_text("VALUE = 'good-tampered'\n")
        reasons = self.verify(artefact)
        self.assertIn("post_tree_mismatch", reasons)

    def test_artefact_bound_to_different_change(self):
        artefact = self.build()
        reasons = self.verify(artefact, expected_change_id="change-2")
        self.assertIn("change_id_mismatch", reasons)

    def test_vacuous_check_refused(self):
        base = make_tree(Path(self.tmp.name) / "vbase",
                         "VALUE = 'bad'\n", check=ALWAYS_PASS_CHECK)
        post = make_tree(Path(self.tmp.name) / "vpost",
                         "VALUE = 'good'\n", check=ALWAYS_PASS_CHECK)
        artefact = build_proof_artefact(
            change_id="change-v", base_root=base, post_root=post,
            scope_paths=SCOPE, invariants=[invariant()])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertTrue(
            "check_vacuous:inv-1" in reasons
            or "check_not_discriminating:inv-1" in reasons, reasons)

    def test_non_discriminating_new_invariant_refused(self):
        base = make_tree(Path(self.tmp.name) / "nbase",
                         "VALUE = 'bad'\n", check=LENIENT_CHECK)
        post = make_tree(Path(self.tmp.name) / "npost",
                         "VALUE = 'good'\n", check=LENIENT_CHECK)
        inv = invariant(mutation={"path": "module.py",
                                  "content_b64": None})
        artefact = build_proof_artefact(
            change_id="change-n", base_root=base, post_root=post,
            scope_paths=SCOPE, invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("check_not_discriminating:inv-1", reasons)
        self.assertNotIn("check_vacuous:inv-1", reasons)

    def test_missing_invariant_evidence_refused(self):
        artefact = self.build()
        broken = copy.deepcopy(artefact)
        broken["evidence"] = []
        # Recompute the self-hash so the artefact reaches the
        # step-5 cross-validation (a hash mismatch returns
        # alone, before any execution or cross-check).
        recompute_hash(broken)
        reasons = self.verify(broken)
        self.assertIn("evidence_missing:inv-1", reasons)

    def test_stale_replay_refused(self):
        artefact = self.build()
        # A second change lands on the post tree after the
        # artefact was built; the old artefact no longer binds it.
        (self.post / "module.py").write_text("VALUE = 'good'\n# v2\n")
        reasons = self.verify(artefact)
        self.assertIn("post_tree_mismatch", reasons)

    def test_evidence_tamper_breaks_artefact_hash(self):
        artefact = self.build()
        broken = copy.deepcopy(artefact)
        original = broken["evidence"][0]["stdout_sha256"]
        broken["evidence"][0]["stdout_sha256"] = (
            "0" * 64 if original != "0" * 64 else "1" * 64)
        reasons = self.verify(broken)
        self.assertIn("artefact_hash_mismatch", reasons)

    def test_malformed_artefact_returns_alone(self):
        self.assertEqual(self.verify({"nope": True}),
                         ("artefact_malformed",))
        self.assertEqual(self.verify("not-a-dict"),
                         ("artefact_malformed",))

    # --- Fix-round regression tests (F12 / F15) ---

    def _sentinel_argv(self, sentinel):
        return [sys.executable, "-c",
                f"open({str(sentinel)!r}, 'w').write('ran')"]

    def test_sentinel_argv_never_executed_on_hash_tamper(self):
        artefact = self.build()
        sentinel = Path(self.tmp.name) / "sentinel-a.txt"
        broken = copy.deepcopy(artefact)
        broken["invariants"][0]["argv"] = self._sentinel_argv(sentinel)
        # No hash recompute: the tamper breaks the self-hash.
        reasons = self.verify(broken)
        self.assertEqual(reasons, ("artefact_hash_mismatch",))
        self.assertFalse(sentinel.exists())

    def test_base_tree_tamper_refused(self):
        artefact = self.build()
        (self.base / "module.py").write_text("VALUE = 'bad-other'\n")
        reasons = self.verify(artefact)
        self.assertIn("base_tree_mismatch", reasons)

    def test_changed_files_trimmed_refused_and_not_executed(self):
        artefact = self.build()
        sentinel = Path(self.tmp.name) / "sentinel-c.txt"
        broken = copy.deepcopy(artefact)
        broken["changed_files"] = []
        broken["invariants"][0]["argv"] = self._sentinel_argv(sentinel)
        recompute_hash(broken)
        reasons = self.verify(broken)
        self.assertIn("post_tree_mismatch", reasons)
        self.assertFalse(sentinel.exists())

    def test_noop_mutation_invalid(self):
        artefact = self.build()
        broken = copy.deepcopy(artefact)
        post_bytes = (self.post / "module.py").read_bytes()
        broken["invariants"][0]["mutation"] = {
            "path": "module.py",
            "content_b64": base64.b64encode(post_bytes).decode("ascii"),
        }
        recompute_hash(broken)
        reasons = self.verify(broken)
        self.assertIn("mutation_invalid:inv-1", reasons)

    def test_probe_cannot_run_on_base_not_discriminating(self):
        base = Path(self.tmp.name) / "pbase"
        post = Path(self.tmp.name) / "ppost"
        base.mkdir(parents=True)
        post.mkdir(parents=True)
        (base / "module.py").write_text("VALUE = 'bad'\n")
        (post / "module.py").write_text("VALUE = 'good'\n")
        probe = (
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "print('ok-fixed')\n"
            "sys.exit(0 if 'good' in content else 1)\n"
        )
        probe_path = post / "probe.py"
        probe_path.write_text(probe)
        os.chmod(probe_path, 0o755)
        scope = ["module.py", "probe.py"]
        inv = {
            "id": "inv-probe",
            "description": "module holds the good marker",
            "argv": ["./probe.py"],
            "scope": "new",
            "mutation": {
                "path": "module.py",
                "content_b64": base64.b64encode(
                    b"VALUE = 'bad'\n").decode("ascii"),
            },
        }
        artefact = build_proof_artefact(
            change_id="change-p", base_root=base, post_root=post,
            scope_paths=scope, invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("check_not_discriminating:inv-probe", reasons)

    def test_root_kwarg_guard(self):
        artefact = self.build()
        with self.assertRaises(ProofError) as ctx:
            record_ship_with_proof(
                object(), base_root=self.base, post_root=self.post,
                artefact=artefact, root=self.post)
        self.assertEqual(str(ctx.exception),
                         "root is supplied by record_ship_with_proof")

    def test_mutation_deleting_own_check_script_invalid(self):
        inv = invariant(mutation={"path": "check.py",
                                  "content_b64": None})
        artefact = self.build(invariants=[inv])
        reasons = self.verify(artefact)
        self.assertIn("mutation_invalid:inv-1", reasons)
        self.assertNotEqual(reasons, ())

    def test_mechanism_field_required_and_exact(self):
        # The check-carrying name travels inside the artefact,
        # bound by artefact_hash (dissent condition 5): a missing
        # or renamed mechanism is malformed even with the hash
        # recomputed, so the disclosure cannot be stripped.
        artefact = self.build()
        self.assertEqual(artefact["mechanism"], "check-carrying/1")
        for bad in (None, "proof-carrying/1", ""):
            forged = copy.deepcopy(artefact)
            if bad is None:
                del forged["mechanism"]
            else:
                forged["mechanism"] = bad
            recompute_hash(forged)
            self.assertEqual(self.verify(forged),
                             ("artefact_malformed",), bad)

    def test_record_ship_with_proof_refuses_before_delegating(self):
        artefact = self.build()
        stub_loop = object()

        class Exploding:
            # Any use record_ship would make of this value
            # (attribute access, calling, hashing into a check)
            # raises; merely passing it as a kwarg is inert, so
            # reaching the raise proves delegation happened.
            def __getattr__(self, name):
                raise AssertionError("record_ship must not be called")

            def __call__(self, *a, **k):
                raise AssertionError("record_ship must not be called")

        with self.assertRaises(ShipRefused) as ctx:
            record_ship_with_proof(
                stub_loop, base_root=self.base, post_root=self.post,
                artefact=artefact, expected_change_id="other-change",
                manifest=Exploding(), signed=Exploding(),
                signing_key=Exploding(), ledger=Exploding(),
                coders=(), reviewers=(), delta={})
        self.assertTrue(
            str(ctx.exception).startswith("proof_refused:"),
            str(ctx.exception))
        self.assertIn("change_id_mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
