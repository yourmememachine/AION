"""Cycle-32 real-change demo: builds a proof artefact for the
real cycle-32 change and verifies it.

Base tree: a `git archive` extraction of the ref given as
argv[1] (default "8e8234f") -- the tree before the cycle-32
files existed. Post tree: this repository's working root.
Writes internal/cycle32-work/demo-artefact.json and
internal/cycle32-work/demo-real-change.txt, the latter
recording the base ref and both verify outcomes (untouched
ACCEPTED, tampered REFUSED with reasons).

Run: python3 tests/cycle32_real_change_demo.py [base-ref]
"""
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust.proofcarry import build_proof_artefact, verify_proof_artefact

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "internal" / "cycle32-work"
CHANGE_ID = "cycle-32-proofcarry-prototype"
SCOPE_PATHS = [
    "trust/proofcarry.py",
    "tests/test_trust_proofcarry.py",
    "tests/test_cycle32_proof_ship.py",
    "tests/test_cycle32_claim_pin.py",
    "tests/cycle32_check.py",
    "tests/cycle32_suite_check.py",
]


def invariants():
    return [
        {
            "id": "proofcarry-module-present",
            "description": "trust/proofcarry.py exists in the "
                           "post tree and carries the "
                           "proof-artefact/1 format and the "
                           "record_ship_with_proof seam",
            "argv": [sys.executable, "tests/cycle32_check.py"],
            "scope": "new",
            "mutation": {"path": "trust/proofcarry.py",
                         "content_b64": None},
        },
        {
            "id": "cycle32-test-suites-pass",
            "description": "the cycle-32 test suites pass on "
                           "the post tree",
            "argv": [sys.executable, "tests/cycle32_suite_check.py"],
            "scope": "new",
            "mutation": {"path": "tests/test_cycle32_proof_ship.py",
                         "content_b64": None},
        },
    ]


def extract_base(ref, dest):
    proc = subprocess.run(
        ["git", "-C", str(REPO), "archive", ref],
        stdout=subprocess.PIPE, check=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def report(label, reasons):
    verdict = "ACCEPTED" if not reasons else "REFUSED"
    return f"{label}: {verdict} reasons={tuple(reasons)!r}"


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "8e8234f"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        base_root = extract_base(ref, Path(tmp) / "base")
        artefact = build_proof_artefact(
            change_id=CHANGE_ID, base_root=base_root,
            post_root=REPO, scope_paths=SCOPE_PATHS,
            invariants=invariants())
        artefact_path = OUT_DIR / "demo-artefact.json"
        artefact_path.write_text(
            json.dumps(artefact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        lines.append(
            f"artefact written: {artefact_path} change_id={CHANGE_ID}")
        lines.append(f"base ref: {ref}")
        lines.append(
            f"base_tree_hash={artefact['base_tree_hash']} "
            f"post_tree_hash={artefact['post_tree_hash']} "
            f"artefact_hash={artefact['artefact_hash']}")
        reasons = verify_proof_artefact(
            artefact, base_root=base_root, post_root=REPO,
            expected_change_id=CHANGE_ID)
        lines.append(report(
            "verify real change (untouched post tree)", reasons))
        # Tampered post tree: a scratch copy of the repo with
        # one comment appended to the module under proof.
        tampered = Path(tmp) / "tampered"
        shutil.copytree(
            REPO, tampered,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc"))
        module = tampered / "trust" / "proofcarry.py"
        module.write_text(
            module.read_text(encoding="utf-8") + "\n# tampered\n",
            encoding="utf-8")
        reasons = verify_proof_artefact(
            artefact, base_root=base_root, post_root=tampered,
            expected_change_id=CHANGE_ID)
        lines.append(report(
            "verify tampered post tree (one comment appended "
            "to the module)", reasons))
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "demo-real-change.txt").write_text(
        text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
