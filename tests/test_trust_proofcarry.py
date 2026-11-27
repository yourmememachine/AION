"""Tests for trust.proofcarry — proof artefacts for a change
(cycle 32). Every test runs against small fake base/post trees
in a temp directory, never the real repo.
"""

import base64
import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trust.proofcarry as pc
import trust.shipcheck
from signing.gate_decision import _canonical, _sha256
from trust.errors import ShipRefused
from trust.proofcarry import (
    CLAIM,
    ProofError,
    _expand_scope,
    _expand_whole_tree,
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


DIRTY_CHECK = (
    "import pathlib, sys\n"
    "p = pathlib.Path('module.py')\n"
    "content = p.read_text()\n"
    "p.write_text(content + '# dirty\\n')\n"
    "if 'good' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "sys.exit(1)\n"
)

BASE_DIRTY_CHECK = (
    "import pathlib, sys\n"
    "p = pathlib.Path('module.py')\n"
    "content = p.read_text()\n"
    "if 'good' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "p.write_text(content + '# dirty\\n')\n"
    "sys.exit(1)\n"
)

MUTATION_DIRTY_CHECK = (
    "import pathlib, sys\n"
    "p = pathlib.Path('module.py')\n"
    "content = p.read_text()\n"
    "if 'good' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "if 'mutated' in content:\n"
    "    p.write_text(content + '# dirty\\n')\n"
    "sys.exit(1)\n"
)

MARKER_CHECK = (
    "import pathlib, sys\n"
    "pathlib.Path('scratch-marker.txt').write_text('x')\n"
    "content = pathlib.Path('module.py').read_text()\n"
    "if 'good' in content:\n"
    "    print('ok-fixed')\n"
    "    sys.exit(0)\n"
    "sys.exit(1)\n"
)


class FixRoundTests(unittest.TestCase):
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

    # --- §12.6: CLAIM ---

    def test_claim_constant_is_narrowed_text(self):
        expected = (
            "A proof artefact establishes only this: the invariants "
            "it declares were executed by the independent checker "
            "against the exact tree contents bound in the artefact, "
            "each declared check passed on that tree, and each check "
            "was shown to fail on the pre-change tree (for invariants "
            "declared new) and on a mutated tree. The binding covers "
            "tree contents only: checks run as ordinary subprocesses "
            "with the checker's privileges and inherited environment, "
            "and the execution environment, the interpreter, and "
            "anything outside the tree a check reads or writes are "
            "not bound by the artefact. It establishes nothing about "
            "properties the change did not declare, and it is not a "
            "proof of general correctness.")
        self.assertEqual(" ".join(CLAIM.split()), expected)

    # --- §12.1 / §12.2: wrapper with a fake delegate ---

    def _fake_ship(self, artefact, delegate=None):
        journal = Path(self.tmp.name) / "journal"
        journal.mkdir(parents=True, exist_ok=True)
        manifest = types.SimpleNamespace(manifest_hash="f" * 64)
        ledger = types.SimpleNamespace(journal_dir=journal)
        captured = {}
        if delegate is None:
            def delegate(loop, *, root, **kw):
                captured["root"] = Path(root)
                captured["exists_during"] = Path(root).exists()
                captured["is_live"] = Path(root) == self.post
                return {"cycle_id": 7, "item_id": "item-9"}
        return manifest, ledger, captured, delegate

    def _call_wrapper(self, artefact, delegate, manifest, ledger):
        with mock.patch.object(trust.shipcheck, "record_ship", delegate):
            return record_ship_with_proof(
                object(), base_root=self.base, post_root=self.post,
                artefact=artefact, manifest=manifest, ledger=ledger,
                signed=object(), signing_key=object(), coders=(),
                reviewers=(), delta={})

    def test_unscoped_change_refused_before_delegation(self):
        artefact = self.build()
        (self.post / "extra.txt").write_text("outside scope\n")
        called = []

        def delegate(loop, *, root, **kw):
            called.append(root)
            return {"cycle_id": 7, "item_id": "item-9"}

        manifest, ledger, _c, _d = self._fake_ship(artefact)
        with self.assertRaises(ShipRefused) as ctx:
            self._call_wrapper(artefact, delegate, manifest, ledger)
        self.assertEqual(ctx.exception.reasons, ("unscoped_changes",))
        self.assertEqual(called, [])
        self.assertFalse(
            (ledger.journal_dir / "proof-bindings.jsonl").exists())

    def test_unscoped_addition_and_deletion_refused(self):
        artefact = self.build()
        manifest, ledger, _c, _d = self._fake_ship(artefact)

        def delegate(loop, *, root, **kw):
            raise AssertionError("must not delegate")

        (self.post / "added.txt").write_text("new outside scope\n")
        with self.assertRaises(ShipRefused) as ctx:
            self._call_wrapper(artefact, delegate, manifest, ledger)
        self.assertEqual(ctx.exception.reasons, ("unscoped_changes",))
        (self.post / "added.txt").unlink()
        (self.base / "gone.txt").write_text("only in base\n")
        with self.assertRaises(ShipRefused) as ctx:
            self._call_wrapper(artefact, delegate, manifest, ledger)
        self.assertEqual(ctx.exception.reasons, ("unscoped_changes",))

    def test_unscoped_pycache_difference_ignored(self):
        artefact = self.build()
        cache = self.post / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_bytes(b"\x00\x01")
        manifest, ledger, captured, delegate = self._fake_ship(artefact)
        entry = self._call_wrapper(artefact, delegate, manifest, ledger)
        self.assertEqual(entry["cycle_id"], 7)
        self.assertTrue(captured["exists_during"])

    def test_scoped_ship_writes_proof_binding(self):
        artefact = self.build()
        manifest, ledger, captured, delegate = self._fake_ship(artefact)
        entry = self._call_wrapper(artefact, delegate, manifest, ledger)
        # Delegated the snapshot, never the live tree; snapshot
        # removed after the delegate returned.
        self.assertFalse(captured["is_live"])
        self.assertTrue(captured["exists_during"])
        self.assertFalse(captured["root"].exists())
        self.assertEqual(entry["proof_artefact_hash"],
                         artefact["artefact_hash"])
        self.assertEqual(entry["proof_post_tree_hash"],
                         artefact["post_tree_hash"])
        lines = (ledger.journal_dir / "proof-bindings.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(set(record), {
            "cycle_id", "item_id", "change_id", "manifest_hash",
            "artefact_hash", "post_tree_hash", "recorded_at"})
        self.assertEqual(record["cycle_id"], entry["cycle_id"])
        self.assertEqual(record["item_id"], entry["item_id"])
        self.assertEqual(record["change_id"], artefact["change_id"])
        self.assertEqual(record["manifest_hash"], manifest.manifest_hash)
        self.assertEqual(record["artefact_hash"],
                         artefact["artefact_hash"])
        self.assertEqual(record["post_tree_hash"],
                         artefact["post_tree_hash"])

    def test_proof_binding_failure_ship_stands(self):
        artefact = self.build()
        manifest, ledger, _c, delegate = self._fake_ship(artefact)
        with mock.patch.object(pc, "_append_proof_binding",
                               side_effect=OSError("disk full")):
            with self.assertRaises(ShipRefused) as ctx:
                self._call_wrapper(artefact, delegate, manifest, ledger)
        self.assertIn(
            "cycle 7 recorded and the decision finalised, "
            "but the proof binding failed", str(ctx.exception))
        self.assertEqual(ctx.exception.reasons, ())

    def test_snapshot_removed_after_delegate_refusal(self):
        artefact = self.build()
        manifest, ledger, captured, _d = self._fake_ship(artefact)

        def refusing(loop, *, root, **kw):
            captured["root"] = Path(root)
            raise ShipRefused("delegate refused")

        with self.assertRaises(ShipRefused):
            self._call_wrapper(artefact, refusing, manifest, ledger)
        self.assertFalse(captured["root"].exists())
        self.assertFalse(
            (ledger.journal_dir / "proof-bindings.jsonl").exists())

    def test_wrapper_requires_ledger_and_manifest(self):
        artefact = self.build()
        with self.assertRaises(ProofError):
            record_ship_with_proof(
                object(), base_root=self.base, post_root=self.post,
                artefact=artefact)

    # --- §12.3: scratch isolation / side effects ---

    def _hand_built_dirty_artefact(self):
        base = make_tree(Path(self.tmp.name) / "dbase",
                         "VALUE = 'bad'\n", check=DIRTY_CHECK)
        post = make_tree(Path(self.tmp.name) / "dpost",
                         "VALUE = 'good'\n", check=DIRTY_CHECK)
        post_hash = tree_hash(post, SCOPE)
        artefact = {
            "format": "proof-artefact/1",
            "mechanism": "check-carrying/1",
            "change_id": "change-dirty",
            "created_at": "2026-11-26T00:00:00+00:00",
            "scope_paths": sorted(SCOPE),
            "base_tree_hash": tree_hash(base, SCOPE),
            "post_tree_hash": post_hash,
            "changed_files": changed_files(base, post, SCOPE),
            "invariants": [{
                "id": "inv-1",
                "description": "module holds the good marker",
                "argv": [sys.executable, "check.py"],
                "scope": "new",
                "mutation": {
                    "path": "module.py",
                    "content_b64": base64.b64encode(
                        b"VALUE = 'bad'\n").decode("ascii"),
                },
            }],
            "evidence": [{
                "invariant_id": "inv-1",
                "tree_hash": post_hash,
                "exit_code": 0,
                "stdout_sha256": _sha256(b"ok-fixed\n"),
                "stderr_sha256": _sha256(b""),
            }],
        }
        recompute_hash(artefact)
        return artefact, base, post

    def test_check_side_effect_refused(self):
        artefact, base, post = self._hand_built_dirty_artefact()
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertEqual(reasons, ("check_side_effect:inv-1",))

    def test_base_probe_side_effect_voids_run(self):
        base = make_tree(Path(self.tmp.name) / "bbase",
                         "VALUE = 'bad'\n", check=BASE_DIRTY_CHECK)
        post = make_tree(Path(self.tmp.name) / "bpost",
                         "VALUE = 'good'\n", check=BASE_DIRTY_CHECK)
        artefact = build_proof_artefact(
            change_id="change-b", base_root=base, post_root=post,
            scope_paths=SCOPE, invariants=[invariant()])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("check_side_effect:inv-1", reasons)
        self.assertNotIn("check_not_discriminating:inv-1", reasons)

    def test_mutation_probe_side_effect_voids_run(self):
        base = make_tree(Path(self.tmp.name) / "mbase",
                         "VALUE = 'bad'\n", check=MUTATION_DIRTY_CHECK)
        post = make_tree(Path(self.tmp.name) / "mpost",
                         "VALUE = 'good'\n", check=MUTATION_DIRTY_CHECK)
        inv = invariant(mutation={
            "path": "module.py",
            "content_b64": base64.b64encode(
                b"VALUE = 'mutated'\n").decode("ascii")})
        artefact = build_proof_artefact(
            change_id="change-m", base_root=base, post_root=post,
            scope_paths=SCOPE, invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("check_side_effect:inv-1", reasons)
        self.assertNotIn("check_vacuous:inv-1", reasons)
        self.assertNotIn("mutation_invalid:inv-1", reasons)

    def test_builder_side_effect_raises(self):
        base = make_tree(Path(self.tmp.name) / "sbase",
                         "VALUE = 'bad'\n", check=DIRTY_CHECK)
        post = make_tree(Path(self.tmp.name) / "spost",
                         "VALUE = 'good'\n", check=DIRTY_CHECK)
        with self.assertRaises(ProofError) as ctx:
            build_proof_artefact(
                change_id="change-s", base_root=base, post_root=post,
                scope_paths=SCOPE, invariants=[invariant()])
        self.assertIn("check_side_effect:inv-1", str(ctx.exception))

    def test_builder_and_checker_leave_live_trees_untouched(self):
        base = make_tree(Path(self.tmp.name) / "lbase",
                         "VALUE = 'bad'\n", check=MARKER_CHECK)
        post = make_tree(Path(self.tmp.name) / "lpost",
                         "VALUE = 'good'\n", check=MARKER_CHECK)
        before_base = _expand_whole_tree(base)
        before_post = _expand_whole_tree(post)
        artefact = build_proof_artefact(
            change_id="change-l", base_root=base, post_root=post,
            scope_paths=SCOPE, invariants=[invariant()])
        self.assertEqual(
            verify_proof_artefact(artefact, base_root=base,
                                  post_root=post), ())
        self.assertFalse((base / "scratch-marker.txt").exists())
        self.assertFalse((post / "scratch-marker.txt").exists())
        self.assertEqual(_expand_whole_tree(base), before_base)
        self.assertEqual(_expand_whole_tree(post), before_post)

    # --- §12.4: mutation rules ---

    def test_mutation_out_of_scope_invalid(self):
        for root in (self.base, self.post):
            (root / "other.txt").write_text("same in both\n")
        inv = invariant(mutation={
            "path": "other.txt",
            "content_b64": base64.b64encode(b"different\n").decode("ascii")})
        artefact = self.build(invariants=[inv])
        sentinel = Path(self.tmp.name) / "sentinel-o.txt"
        broken = copy.deepcopy(artefact)
        broken["invariants"][0]["argv"] = [
            sys.executable, "-c",
            f"open({str(sentinel)!r}, 'w').write('ran')"]
        recompute_hash(broken)
        reasons = self.verify(broken)
        self.assertIn("mutation_invalid:inv-1", reasons)
        self.assertFalse(sentinel.exists())

    def _import_tree(self, name, files):
        root = Path(self.tmp.name) / name
        root.mkdir(parents=True)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return root

    def test_mutation_transitive_import_invalid(self):
        check = (
            "import pathlib, sys\n"
            "import helpers.util\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "if helpers.util.VALUE == 'util-good' and 'good' in content:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n")
        scope = ["module.py", "check.py", "helpers"]
        for target_path, mutated in (
                ("helpers/util.py", "VALUE = 'util-bad'\n"),
                ("helpers/__init__.py", "# changed\n")):
            with self.subTest(target=target_path):
                files = {
                    "module.py": "VALUE = 'good'\n",
                    "check.py": check,
                    "helpers/__init__.py": "",
                    "helpers/util.py": "VALUE = 'util-good'\n",
                }
                post = self._import_tree(
                    f"ipost-{target_path.replace('/', '_')}", files)
                files["module.py"] = "VALUE = 'bad'\n"
                base = self._import_tree(
                    f"ibase-{target_path.replace('/', '_')}", files)
                inv = invariant(mutation={
                    "path": target_path,
                    "content_b64": base64.b64encode(
                        mutated.encode()).decode("ascii")})
                artefact = build_proof_artefact(
                    change_id="change-i", base_root=base, post_root=post,
                    scope_paths=scope, invariants=[inv])
                reasons = verify_proof_artefact(
                    artefact, base_root=base, post_root=post)
                self.assertIn("mutation_invalid:inv-1", reasons)

    def test_mutation_relative_import_invalid(self):
        check = (
            "import pathlib, sys\n"
            "import pkg\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "if pkg.VALUE == 'pkg-good' and 'good' in content:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n")
        files = {
            "module.py": "VALUE = 'good'\n",
            "check.py": check,
            "pkg/__init__.py": "from .util import VALUE\n",
            "pkg/util.py": "VALUE = 'pkg-good'\n",
        }
        post = self._import_tree("rpost", files)
        files = dict(files, **{"module.py": "VALUE = 'bad'\n"})
        base = self._import_tree("rbase", files)
        inv = invariant(mutation={
            "path": "pkg/util.py",
            "content_b64": base64.b64encode(
                b"VALUE = 'pkg-bad'\n").decode("ascii")})
        artefact = build_proof_artefact(
            change_id="change-r", base_root=base, post_root=post,
            scope_paths=["module.py", "check.py", "pkg"],
            invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("mutation_invalid:inv-1", reasons)

    def test_mutation_of_imported_data_file_still_valid(self):
        check = (
            "import pathlib, sys\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "data = pathlib.Path('data.txt').read_text()\n"
            "if 'good' in content and 'expected' in data:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n")
        scope = ["module.py", "check.py", "data.txt"]
        base = make_tree(Path(self.tmp.name) / "dbase2",
                         "VALUE = 'bad'\n", check=check)
        post = make_tree(Path(self.tmp.name) / "dpost2",
                         "VALUE = 'good'\n", check=check)
        for root in (base, post):
            (root / "data.txt").write_text("expected\n")
        inv = invariant(mutation={
            "path": "data.txt",
            "content_b64": base64.b64encode(b"other\n").decode("ascii")})
        artefact = build_proof_artefact(
            change_id="change-data", base_root=base, post_root=post,
            scope_paths=scope, invariants=[inv])
        self.assertEqual(
            verify_proof_artefact(artefact, base_root=base,
                                  post_root=post), ())

    def test_mutation_dynamic_import_crash_is_invalid_not_noticing(self):
        check = (
            "import importlib, pathlib, sys\n"
            "name = pathlib.Path('config.txt').read_text().strip()\n"
            "mod = importlib.import_module(name)\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "if mod.VALUE == 'dyn' and 'good' in content:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n")
        scope = ["module.py", "check.py", "config.txt", "dynmod.py"]
        base = make_tree(Path(self.tmp.name) / "ybase",
                         "VALUE = 'bad'\n", check=check)
        post = make_tree(Path(self.tmp.name) / "ypost",
                         "VALUE = 'good'\n", check=check)
        for root in (base, post):
            (root / "config.txt").write_text("dynmod\n")
            (root / "dynmod.py").write_text("VALUE = 'dyn'\n")
        inv = invariant(mutation={
            "path": "config.txt",
            "content_b64": base64.b64encode(
                b"nonexistent_mod\n").decode("ascii")})
        artefact = build_proof_artefact(
            change_id="change-y", base_root=base, post_root=post,
            scope_paths=scope, invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("mutation_invalid:inv-1", reasons)
        self.assertNotIn("check_vacuous:inv-1", reasons)

    def test_mutation_semantic_crash_word_refused_conservatively(self):
        # DECIDED conservative direction (§12.4.3): a semantic
        # failure whose stderr contains a crash-marker word is
        # refused mutation_invalid; this false refusal is by
        # design, not a bug.
        check = (
            "import pathlib, sys\n"
            "content = pathlib.Path('module.py').read_text()\n"
            "data = pathlib.Path('data.txt').read_text()\n"
            "if 'good' in content and 'expected' in data:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "if 'good' in content:\n"
            "    print('ImportError: data rejected', file=sys.stderr)\n"
            "sys.exit(1)\n")
        scope = ["module.py", "check.py", "data.txt"]
        base = make_tree(Path(self.tmp.name) / "cbase",
                         "VALUE = 'bad'\n", check=check)
        post = make_tree(Path(self.tmp.name) / "cpost",
                         "VALUE = 'good'\n", check=check)
        for root in (base, post):
            (root / "data.txt").write_text("expected\n")
        inv = invariant(mutation={
            "path": "data.txt",
            "content_b64": base64.b64encode(b"other\n").decode("ascii")})
        artefact = build_proof_artefact(
            change_id="change-c", base_root=base, post_root=post,
            scope_paths=scope, invariants=[inv])
        reasons = verify_proof_artefact(
            artefact, base_root=base, post_root=post)
        self.assertIn("mutation_invalid:inv-1", reasons)

    def test_long_argv_expression_element_verifies(self):
        # Regression: a ~300-char `python -c` expression element
        # must seed nothing in the harness closure (design
        # 12.4.2), not raise OSError ENAMETOOLONG out of
        # verify step 5 -- the checker never raises for a
        # schema-valid artefact. The script builds the checked
        # filename dynamically so the argv string net does not
        # (correctly) classify the mutation target as harness.
        long_script = (
            "import pathlib, sys\n"
            "content = pathlib.Path('mod' + 'ule.py').read_text()\n"
            "if 'good' in content:\n"
            "    print('ok-fixed')\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n"
            "# " + "p" * 280 + "\n")
        self.assertGreater(len(long_script), 300)
        inv = invariant(argv=[sys.executable, "-c", long_script])
        artefact = self.build(invariants=[inv])
        reasons = self.verify(artefact)
        self.assertIsInstance(reasons, tuple)
        self.assertEqual(reasons, ())

    def test_long_argv_element_alongside_real_seed_closure_works(self):
        # A long inert element next to a real script seed: the
        # seed is still found, the long element seeds nothing,
        # and nothing raises.
        long_element = "z" * 300
        self.assertEqual(
            pc._harness_dependencies(
                [sys.executable, "check.py", long_element], self.post),
            {"check.py"})
        self.assertEqual(
            pc._harness_dependencies(
                ["deep/" + "d" * 300 + "/x.py", long_element],
                self.post),
            set())
        # End to end: the extra argv element is inert for the
        # script (it ignores trailing args), the artefact
        # verifies, and a mutation of the seeded script is
        # still classified harness-invalid.
        inv = invariant(argv=[sys.executable, "check.py", long_element])
        artefact = self.build(invariants=[inv])
        self.assertEqual(self.verify(artefact), ())
        inv_harness = invariant(
            argv=[sys.executable, "check.py", long_element],
            mutation={"path": "check.py", "content_b64": None})
        artefact_harness = self.build(invariants=[inv_harness])
        self.assertIn("mutation_invalid:inv-1",
                      self.verify(artefact_harness))

    # --- §12.5: tree hasher pins ---

    def test_symlink_variants_refused(self):
        # (i) symlinked file inside a scoped directory
        root = self._import_tree("s1", {"pkg/real.py": "x = 1\n"})
        os.symlink(root / "pkg" / "real.py", root / "pkg" / "link.py")
        with self.assertRaises(ProofError):
            tree_hash(root, ["pkg"])
        # (ii) symlinked directory inside a scoped directory
        root = self._import_tree(
            "s2", {"pkg/realdir/mod.py": "x = 1\n", "pkg/top.py": "y\n"})
        os.symlink(root / "pkg" / "realdir", root / "pkg" / "linkdir")
        with self.assertRaises(ProofError):
            tree_hash(root, ["pkg"])
        # (iii) scope path whose intermediate component is a symlink
        root = self._import_tree("s3", {"realdir/mod.py": "x = 1\n"})
        os.symlink(root / "realdir", root / "linkdir")
        with self.assertRaises(ProofError):
            tree_hash(root, ["linkdir/mod.py"])
        # (iv) scope path naming a symlink directly
        root = self._import_tree("s4", {"real.py": "x = 1\n"})
        os.symlink(root / "real.py", root / "link.py")
        with self.assertRaises(ProofError):
            tree_hash(root, ["link.py"])

    def test_noncanonical_scope_spellings_refused(self):
        for bad in ("a//b", "a/./b", "a/../b", "/abs", "a/", "a\\b", ""):
            with self.subTest(spelling=bad):
                with self.assertRaises(ProofError):
                    self.build(scope_paths=[bad])
                artefact = self.build()
                artefact["scope_paths"] = [bad]
                recompute_hash(artefact)
                self.assertEqual(self.verify(artefact),
                                 ("artefact_malformed",))

    def test_overlapping_scopes_deduplicated(self):
        root = self._import_tree(
            "ov", {"pkg/mod.py": "x = 1\n", "pkg/other.py": "y = 2\n"})
        entries = _expand_scope(root, ["pkg", "pkg/mod.py", "pkg"])
        paths = [e["path"] for e in entries]
        self.assertEqual(paths.count("pkg/mod.py"), 1)
        self.assertEqual(tree_hash(root, ["pkg", "pkg/mod.py"]),
                         tree_hash(root, ["pkg"]))

    def test_mode_not_bound_by_tree_hash(self):
        # §12.5 DECIDED: entries bind content hash + size only,
        # not mode; mode is bound by the ship manifest in
        # composition, deliberately not by proof-tree/1.
        before = tree_hash(self.post, SCOPE)
        os.chmod(self.post / "module.py", 0o755)
        self.assertEqual(tree_hash(self.post, SCOPE), before)

    def test_fresh_construction_reproduces_hashes(self):
        artefacts = []
        pairs = []
        for name in ("f1", "f2"):
            base = make_tree(Path(self.tmp.name) / f"{name}base",
                             "VALUE = 'bad'\n")
            post = make_tree(Path(self.tmp.name) / f"{name}post",
                             "VALUE = 'good'\n")
            pairs.append((base, post))
            artefacts.append(build_proof_artefact(
                change_id="change-f", base_root=base, post_root=post,
                scope_paths=SCOPE, invariants=[invariant()],
                created_at="2026-11-26T00:00:00+00:00"))
        self.assertEqual(artefacts[0], artefacts[1])
        for artefact, (base, post) in zip(artefacts, pairs):
            self.assertEqual(
                verify_proof_artefact(artefact, base_root=base,
                                      post_root=post), ())


if __name__ == "__main__":
    unittest.main()
