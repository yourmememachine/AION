"""Cycle 32 demo — proof-carrying self-improvement prototype.

Builds a temp base tree (A = 1) and post tree (A = 2, plus a
check script at the tree root), builds a proof artefact over
the change, and shows the independent checker:

1. ACCEPT the artefact against the untouched trees;
2. REFUSE it after the post tree is tampered with;
3. REFUSE a vacuous artefact whose check passes everywhere
   (it proves nothing: it does not fail on the pre-change
   tree or on the mutated tree).

Run: python3 tests/cycle32_demo.py
Output is saved alongside this script in demo-output.txt.
"""

import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust.proofcarry import build_proof_artefact, verify_proof_artefact

CHANGE_ID = "cycle32-demo-change"
SCOPE_PATHS = ["core/a.py", "check_a.py"]

CHECK_SCRIPT = (
    "import pathlib\n"
    "import sys\n"
    "\n"
    'text = (pathlib.Path(__file__).resolve().parent\n'
    '        / "core" / "a.py").read_text(encoding="utf-8")\n'
    'if "A = 2" in text:\n'
    '    print("A_IS_2")\n'
    "    sys.exit(0)\n"
    'print("A_NOT_2")\n'
    "sys.exit(1)\n"
)


def make_tree(root: Path, a_value: int):
    (root / "core").mkdir(parents=True)
    (root / "core" / "a.py").write_text(f"A = {a_value}\n")
    (root / "check_a.py").write_text(CHECK_SCRIPT)
    return root


def real_invariants():
    return [{
        "id": "a-is-2",
        "description": "core/a.py declares A = 2",
        "argv": [sys.executable, "check_a.py"],
        "scope": "new",
        "mutation": {
            "path": "core/a.py",
            "content_b64": base64.b64encode(b"A = 1\n").decode("ascii"),
        },
    }]


def vacuous_invariants():
    return [{
        "id": "always-passes",
        "description": "a check that passes on every tree",
        "argv": [sys.executable, "-c", "print('ok')"],
        "scope": "new",
        "mutation": {
            "path": "core/a.py",
            "content_b64": base64.b64encode(b"A = 1\n").decode("ascii"),
        },
    }]


def report(label, reasons):
    verdict = "ACCEPTED" if not reasons else "REFUSED"
    print(f"{label}: {verdict} reasons={tuple(reasons)!r}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        base_root = make_tree(base / "base-repo", 1)
        post_root = make_tree(base / "post-repo", 2)

        artefact = build_proof_artefact(
            change_id=CHANGE_ID, base_root=base_root,
            post_root=post_root, scope_paths=SCOPE_PATHS,
            invariants=real_invariants(),
            created_at="2026-11-26T00:00:00+00:00")
        print(f"artefact format={artefact.get('format')!r} "
              f"change_id={artefact.get('change_id')!r}")

        reasons = verify_proof_artefact(
            artefact, base_root=base_root, post_root=post_root,
            expected_change_id=CHANGE_ID)
        report("verify untouched post tree", reasons)

        (post_root / "core" / "a.py").write_text("A = 3\n")
        reasons = verify_proof_artefact(
            artefact, base_root=base_root, post_root=post_root,
            expected_change_id=CHANGE_ID)
        report("verify tampered post tree", reasons)

        # Restore the post tree, then try a vacuous check: it
        # passes on the post tree but also on the base and
        # mutated trees, so it carries no proof.
        (post_root / "core" / "a.py").write_text("A = 2\n")
        vacuous = build_proof_artefact(
            change_id=CHANGE_ID, base_root=base_root,
            post_root=post_root, scope_paths=SCOPE_PATHS,
            invariants=vacuous_invariants(),
            created_at="2026-11-26T00:00:00+00:00")
        reasons = verify_proof_artefact(
            vacuous, base_root=base_root, post_root=post_root,
            expected_change_id=CHANGE_ID)
        report("verify vacuous check", reasons)


if __name__ == "__main__":
    main()
