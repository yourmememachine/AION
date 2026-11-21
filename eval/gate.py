"""Safety gate for proposed self-changes.

Mostly standard library only, pure functions, no I/O — with one
stated exception: the protected-path check (check_protected_paths)
lazily imports the shared path policy (trust.pathpolicy,
path-policy/1) inside the function, so the gate judges the
canonical spelling of each path. The rest of the gate stays
stdlib-only, pure and I/O-free. A change is accepted only
if every check passes at once:

- no benchmark regresses, in the public suite or the sealed suite
  (any drop counts; the only tolerance is float arithmetic noise);
- a forgetting check against the capability snapshot passes;
- at least one sealed benchmark strictly improves (a gain must appear
  on the sealed set, not only in public);
- one named verifier, who is a reviewer and not one of the builders,
  attests approval over the sealed results, bound by the hash of those
  results, with the reward-hacking check recorded as done;
- the change does not touch protected scope: the evaluation package
  and the cycle state machine judge every change, so they are never
  valid targets of one (checked when changed_paths is supplied).

Trusted inputs, stated plainly: this gate checks the CONSISTENCY of the
score maps and attestation it is given. It does not run any evaluation
itself and cannot prove the numbers came from a real sealed run. The
caller must supply the true capability snapshot (taken at the last
accepted change), must compute expected_sealed_hash from the benchmark
registry's sealed manifest hash, and must obtain the attestation from
the named verifier. Ids are plain strings: disjoint builder/reviewer
ids do not by themselves prove independent people or models — that
independence is a property of the process around this gate, not of
this code.

Malformed input raises GateInputError. A well-formed change that fails
a check does not raise: it returns a GateDecision with accepted=False
and every failure reason collected.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

FLOAT_TOL = 1e-9
EPSILON = 0.0
MIN_BUILDERS = 3
MIN_REVIEWERS = 6
SUITES = ("public", "sealed", "capability")

# Protected scope: the evaluator, this gate, the calibration log and the
# cycle state machine are the judges of every change, so no self-change
# may target them. A change that edits its own judge can fake any gain.
PROTECTED_PREFIXES = ("eval/",)
PROTECTED_FILES = ("core/loop.py",)


def check_protected_paths(changed_paths) -> tuple:
    """The subset of changed paths that fall inside protected scope.

    Judged on the CANONICAL spelling of each path under
    path-policy/1 (trust.pathpolicy.canonicalise), lazily imported
    here to avoid an import cycle; offenders are returned as their
    canonical spelling. A non-string or empty/blank entry, and any
    spelling that cannot be canonicalised, raises GateInputError —
    a refusal, never a silent pass.
    """
    if isinstance(changed_paths, (str, bytes)) or not isinstance(
            changed_paths, (list, tuple)):
        raise GateInputError("changed_paths must be a list of paths")
    # Function-local import (Protected Gate proposal, Round-C
    # correction): a module-level import of trust.pathpolicy cycles
    # (trust/__init__ -> shipcheck -> signing.gate_decision ->
    # eval.gate, and gate -> trust.pathpolicy -> oversight -> gate).
    from trust.pathpolicy import canonicalise as _policy_canonicalise
    offenders = []
    for raw in changed_paths:
        # path-policy/1 adoption (Protected Gate Rule proposal,
        # internal/PROTECTED-GATE-PROPOSAL.md): judge the
        # canonical spelling, and refuse spellings that have
        # none — an uncanonicalisable path is malformed input,
        # never an unprotected one.
        if not isinstance(raw, str) or not raw.strip():
            raise GateInputError(
                "changed path must be non-empty text")
        try:
            path = _policy_canonicalise(raw)
        except ValueError as exc:
            raise GateInputError(
                f"changed path is not canonicalisable: {raw!r}"
            ) from exc
        if path in PROTECTED_FILES or any(
                path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            offenders.append(path)
    return tuple(offenders)

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


class GateInputError(ValueError):
    """Raised when gate input is malformed."""


@dataclass(frozen=True)
class Regression:
    suite: str
    benchmark_id: str
    baseline: float
    candidate: float
    delta: float


@dataclass(frozen=True)
class VerifierAttestation:
    verifier_id: str
    decision: str
    sealed_hash: str
    reward_hacking_checked: bool
    evidence_ref: str
    attested_at: str


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    proposal_id: str
    reasons: tuple
    regressions: tuple
    forgetting_failures: tuple
    verifier_id: str | None
    evaluated_at: str
    protected_violations: tuple = ()
    verifier_note: str = ""


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise GateInputError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_score_map(values, field: str) -> dict:
    if not isinstance(values, dict) or not values:
        raise GateInputError(f"{field} must be a non-empty score map")
    out = {}
    for key, value in values.items():
        _check_id(key, f"{field} benchmark id")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateInputError(f"{field}[{key}] must be a number")
        try:
            score = float(value)
        except OverflowError as exc:
            raise GateInputError(f"{field}[{key}] must be finite") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise GateInputError(f"{field}[{key}] must be a finite score in [0, 1]")
        out[key] = score
    return out


def _check_participants(values, field: str, minimum: int) -> list:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise GateInputError(f"{field} must be a list of ids")
    out = [_check_id(v, f"{field} entry") for v in values]
    if len(set(out)) < minimum:
        raise GateInputError(f"{field} requires at least {minimum} distinct ids")
    return out


def check_no_regression(baseline, candidate, *, suite: str,
                        epsilon: float = EPSILON) -> tuple:
    """Per-benchmark drops beyond float noise, as Regression entries."""
    if suite not in SUITES:
        raise GateInputError(f"unknown suite: {suite}")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise GateInputError("epsilon must be a number")
    if float(epsilon) != 0.0:
        raise GateInputError("epsilon must be 0.0: any drop is a regression")
    baseline = _check_score_map(baseline, f"{suite} baseline")
    candidate = _check_score_map(candidate, f"{suite} candidate")
    failures = []
    for benchmark_id in sorted(set(baseline) | set(candidate)):
        base = baseline.get(benchmark_id)
        cand = candidate.get(benchmark_id)
        if base is None:
            raise GateInputError(
                f"candidate adds unbaselined benchmark: {benchmark_id}")
        if cand is None:
            failures.append(Regression(suite, benchmark_id, base, 0.0, -base))
        elif cand < base - FLOAT_TOL:
            failures.append(Regression(suite, benchmark_id, base, cand, cand - base))
    return tuple(failures)


def check_forgetting(capability_baseline, capability_candidate, *,
                     tolerance: float = EPSILON) -> tuple:
    """Compare current capability probes against the supplied snapshot.

    The snapshot is trusted input: the caller supplies the scores frozen
    at the last accepted change. This function checks the comparison,
    not the provenance of the snapshot.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise GateInputError("tolerance must be a number")
    if float(tolerance) != 0.0:
        raise GateInputError("tolerance must be 0.0: any drop is forgetting")
    return check_no_regression(capability_baseline, capability_candidate,
                               suite="capability")


def validate_verifier(attestation, *, builder_ids, reviewer_ids,
                      expected_sealed_hash) -> tuple:
    """Failure reasons for an attestation; () means the attestation is valid."""
    reasons = []
    if not isinstance(attestation, VerifierAttestation):
        return ("missing_attestation",)
    verifier = attestation.verifier_id
    if not isinstance(verifier, str) or not _ID_RE.fullmatch(verifier or ""):
        reasons.append("bad_verifier_id")
        verifier = None
    if verifier is not None:
        if verifier in builder_ids:
            reasons.append("verifier_is_builder")
        if verifier not in reviewer_ids:
            reasons.append("verifier_not_reviewer")
    if attestation.decision != "approve":
        reasons.append("verifier_did_not_approve")
    if attestation.reward_hacking_checked is not True:
        reasons.append("reward_hacking_not_checked")
    if (not isinstance(attestation.sealed_hash, str)
            or not _HEX64_RE.fullmatch(attestation.sealed_hash)):
        reasons.append("bad_sealed_hash")
    elif attestation.sealed_hash != expected_sealed_hash:
        reasons.append("sealed_hash_mismatch")
    if not isinstance(attestation.evidence_ref, str) or not attestation.evidence_ref.strip():
        reasons.append("missing_evidence_ref")
    if not isinstance(attestation.attested_at, str) or not attestation.attested_at.strip():
        reasons.append("missing_attested_at")
    else:
        try:
            datetime.fromisoformat(attestation.attested_at.replace("Z", "+00:00"))
        except ValueError:
            reasons.append("bad_attested_at")
    if (not isinstance(expected_sealed_hash, str)
            or not _HEX64_RE.fullmatch(expected_sealed_hash)):
        reasons.append("bad_expected_sealed_hash")
    return tuple(reasons)


def evaluate_self_change(*, proposal_id, builder_ids, reviewer_ids,
                         baseline_public, candidate_public,
                         baseline_sealed, candidate_sealed,
                         capability_baseline, capability_candidate,
                         attestation, expected_sealed_hash,
                         evaluated_at="", changed_paths=None,
                         verifier_note="") -> GateDecision:
    """Decide whether a proposed self-change may be kept.

    verifier_note records, in the caller's words, how verifier rotation
    and diversity were satisfied for this decision (for example: which
    reviewer took the verifier role this time, and how they differ from
    the builders and from the previous verifier). It is carried into
    the decision record verbatim; the gate does not judge its content.
    """
    if not isinstance(verifier_note, str) or len(verifier_note) > 2000:
        raise GateInputError("verifier_note must be text of at most 2000 chars")
    _check_id(proposal_id, "proposal id")
    builders = _check_participants(builder_ids, "builder_ids", MIN_BUILDERS)
    reviewers = _check_participants(reviewer_ids, "reviewer_ids", MIN_REVIEWERS)
    if set(builders) & set(reviewers):
        raise GateInputError("builders and reviewers must be disjoint")
    public_base = _check_score_map(baseline_public, "public baseline")
    public_cand = _check_score_map(candidate_public, "public candidate")
    sealed_base = _check_score_map(baseline_sealed, "sealed baseline")
    sealed_cand = _check_score_map(candidate_sealed, "sealed candidate")
    cap_base = _check_score_map(capability_baseline, "capability baseline")
    cap_cand = _check_score_map(capability_candidate, "capability candidate")

    protected = (check_protected_paths(changed_paths)
                 if changed_paths is not None else ())
    regressions = (check_no_regression(public_base, public_cand, suite="public")
                   + check_no_regression(sealed_base, sealed_cand, suite="sealed"))
    forgetting = check_forgetting(cap_base, cap_cand)
    verifier_reasons = validate_verifier(
        attestation, builder_ids=builders, reviewer_ids=reviewers,
        expected_sealed_hash=expected_sealed_hash)

    reasons = []
    if protected:
        reasons.append("protected_path")
    if regressions:
        reasons.append("regression")
    if forgetting:
        reasons.append("forgetting")
    sealed_gain = any(sealed_cand[k] > sealed_base[k] + FLOAT_TOL
                      for k in sealed_base if k in sealed_cand)
    if not sealed_gain:
        reasons.append("no_sealed_gain")
    reasons.extend(verifier_reasons)

    verifier_id = (attestation.verifier_id
                   if isinstance(attestation, VerifierAttestation) else None)
    return GateDecision(
        accepted=not reasons,
        proposal_id=proposal_id,
        reasons=tuple(reasons),
        regressions=tuple(regressions),
        forgetting_failures=tuple(forgetting),
        verifier_id=verifier_id,
        evaluated_at=evaluated_at,
        protected_violations=tuple(protected),
        verifier_note=verifier_note,
    )
