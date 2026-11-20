"""Standalone issuance racer: ONE issue_attestation attempt, run
as its own OS process (Trust Boundary v3.1, item 3 — the
multi-PROCESS consumption race).

Usage:  python tests/fixtures/issuance_racer.py <spec.json>

The spec is a single JSON file naming everything the attempt
needs:

    {
      "verifier_env":          { ... verifier environment ... },
      "expected_signer_id":    "seat-3",
      "expected_key_id":       "<key id the client pins>",
      "baseline_path":         "<JSON file: baseline eval record>",
      "candidate_path":        "<JSON file: candidate eval record>",
      "proposal_id":           "prop-v1",
      "public_baseline_score": 0.5,
      "public_candidate_score": 0.6,
      "output_path":           "<where the outcome JSON goes>",
      "start_gate_path":       "<file whose existence releases us>"
    }

Behaviour: poll for the start-gate file (about every 20 ms, up to
~30 s) so a test can launch several racers and release them
simultaneously by creating the gate file; on gate timeout write
{"outcome": "gate_timeout", "error": ...} instead of attempting.
Then build a trust.client.VerifierClient (repo root on sys.path)
from the spec's env/pins and attempt issue_attestation exactly
once. The outcome file is the result:

    {"outcome": "ok",      "decision": "<derived decision>"}
    {"outcome": "refused", "error": "<exception text>"}

The process exits 0 always and never hangs: the bounded gate
wait plus the client's own verifier timeout bound the run, and
even a broken spec exits 0 (with the failure on stderr) rather
than crashing the launching test with a bare nonzero exit.
"""

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from trust.client import VerifierClient  # noqa: E402

GATE_TIMEOUT_SECONDS = 30.0
GATE_POLL_SECONDS = 0.02


def _write_outcome(output_path, outcome):
    path = Path(output_path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(outcome))
    tmp.replace(path)


def main(argv):
    if len(argv) != 2:
        print("usage: issuance_racer.py <spec.json>", file=sys.stderr)
        return 0
    spec = json.loads(Path(argv[1]).read_text())
    output_path = spec["output_path"]
    gate = Path(spec["start_gate_path"])
    deadline = time.monotonic() + GATE_TIMEOUT_SECONDS
    while not gate.exists():
        if time.monotonic() >= deadline:
            _write_outcome(output_path, {
                "outcome": "gate_timeout",
                "error": f"start gate {gate} did not appear within "
                         f"{GATE_TIMEOUT_SECONDS}s"})
            return 0
        time.sleep(GATE_POLL_SECONDS)
    try:
        baseline = json.loads(Path(spec["baseline_path"]).read_text())
        candidate = json.loads(Path(spec["candidate_path"]).read_text())
        client = VerifierClient(
            verifier_env=spec["verifier_env"],
            expected_signer_id=spec["expected_signer_id"],
            expected_key_id=spec["expected_key_id"])
        signed = client.issue_attestation(
            proposal_id=spec["proposal_id"],
            baseline_eval=baseline,
            candidate_eval=candidate,
            public_baseline_score=spec["public_baseline_score"],
            public_candidate_score=spec["public_candidate_score"])
        outcome = {"outcome": "ok",
                   "decision": signed["attestation"]["decision"]}
    except Exception as exc:  # the refusal text IS the result
        outcome = {"outcome": "refused", "error": str(exc)}
    _write_outcome(output_path, outcome)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # never hang, never exit nonzero
        print(f"issuance_racer: {exc}", file=sys.stderr)
        sys.exit(0)
