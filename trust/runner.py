"""Production entry point for the pin adopter + hooked loop.

Run as ``python3 -m trust.runner`` with NO command-line
arguments. All configuration comes from the environment,
validated in full before any construction; refusals name the
variable, never its value, and go to stderr as one JSON line.
That no-value-echo guarantee is scoped to the structured
outcome lines (exits 0/2/3/4/5/6/7): exit 1 is the unexpected-
failure path and prints a traceback on stderr, which may
include exception messages — no no-echo guarantee is made
for tracebacks.

Honesty qualifier: this is a production entry point for
production MODE under same-user spawn; it is NOT deployment
evidence. No separate OS user exists on this machine, the
wrapper launch remains refused by design, and nothing here
claims a deployment boundary this host does not provide.

Known limitation: ``CoreLoop``'s cycle method invokes the
cycle hook and discards its return value, so a cycle step's
summary line claims only that the cycle was recorded and the
hook fired without raising — it does NOT claim an adoption
outcome for cycle steps. Pin state is reported authoritatively
only by adopt steps (and by later runs).

The plan file names coders/reviewers/verdict/delta only; it
cannot name paths, keys, operators or env. All authority stays
in the environment plus the out-of-band pins, so a plan file
is not a credential and needs no signature.

Exit codes (the runner's own; verifier subprocess exit codes
are captured by the client and surfaced as exceptions, never
as this process's exit code):

  0  every step executed
  2  configuration refusal (nothing executed, nothing on stdout)
  3  an adopt step was refused (PinAdoptionRefused)
  4  an adopt step burned an authorisation (PinAdoptionBurned)
  5  a cycle step recorded its cycle but its hook failed:
     cycle recorded, pin pending
  6  a cycle step was refused before recording, the loop state
     was corrupt at construction, or an adopt step failed with
     a store/signing refusal outside the typed adoption errors
  7  an adopt step stopped at supersession pending independent
     approval (PinSupersessionPendingApproval, cycle 25): the consume
     was refused pre-commit, no supersession decision was
     requested, and the movement completes only on a later run
     that can present an out-of-band approval artefact. A cycle
     step whose hook stops this way reports under exit 5 (cycle
     recorded, pin pending) with adoption_error naming
     PinSupersessionPendingApproval.
  1  unexpected failure (traceback on stderr)
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from core.loop import CoreLoop, CorruptStateError, InvalidTransition
from signing.ceremony_authorisation import (
    CeremonyPublicKey,
    public_key_id_for,
)
from signing.gate_decision import SigningError
from signing.pin_store import PinStoreError
from trust.history_reconciliation import (
    consumption_entries_provider_from_home,
    supersession_entries_provider_from_home,
)
from trust.pin_adoption import (
    PinAdopterConfig,
    PinAdoptionBurned,
    PinAdoptionRefused,
    PinSupersessionPendingApproval,
    build_pin_adopter,
    pin_adopter_config_from_env,
    pin_cycle_hook,
)
from trust.wiring import ALLOWED_ENV_KEYS

_MAX_PLAN_BYTES = 256 * 1024
_CEREMONY_HEX_RE = re.compile(r"[0-9a-f]{64}")
_ENV_VAR_RE = re.compile(r"(AION_[A-Z0-9_]+)")

_VAR_STATE_DIR = "AION_RUNNER_STATE_DIR"
_VAR_PLAN_PATH = "AION_RUNNER_PLAN_PATH"
_VAR_SIGNER = "AION_RUNNER_EXPECTED_SIGNER_ID"
_VAR_KEY = "AION_RUNNER_EXPECTED_KEY_ID"
_VAR_CEREMONY_HEX = "AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX"


class _ConfigRefusal(Exception):
    def __init__(self, variable, detail):
        super().__init__(f"{variable}: {detail}")
        self.variable = variable
        self.detail = detail


def _refuse(variable, detail):
    raise _ConfigRefusal(variable, detail)


@dataclass(frozen=True)
class RunnerConfig:
    state_dir: Path
    plan_path: Path
    expected_signer_id: str
    expected_key_id: str
    ceremony_public_key: CeremonyPublicKey


def _required_text(env, name):
    value = env.get(name)
    if not isinstance(value, str) or not value.strip():
        _refuse(name, "required and must be non-empty")
    return value


def _required_abs_path(env, name):
    value = _required_text(env, name)
    if not Path(value).is_absolute():
        _refuse(name, "must be an absolute path")
    return Path(value)


def _validate_runner_env(env) -> RunnerConfig:
    state_dir = _required_abs_path(env, _VAR_STATE_DIR)
    plan_path = _required_abs_path(env, _VAR_PLAN_PATH)
    signer = _required_text(env, _VAR_SIGNER)
    key_id = _required_text(env, _VAR_KEY)
    hex_text = env.get(_VAR_CEREMONY_HEX)
    if not isinstance(hex_text, str) or not hex_text.strip():
        _refuse(_VAR_CEREMONY_HEX, "required and must be non-empty")
    if not _CEREMONY_HEX_RE.fullmatch(hex_text):
        _refuse(
            _VAR_CEREMONY_HEX,
            "must be exactly 64 lowercase hex characters "
            "(32 raw bytes)")
    raw = bytes.fromhex(hex_text)
    pub = CeremonyPublicKey(
        public_key=raw, key_id=public_key_id_for(raw))
    return RunnerConfig(
        state_dir=state_dir, plan_path=plan_path,
        expected_signer_id=signer, expected_key_id=key_id,
        ceremony_public_key=pub)


def _plan_refuse(detail):
    _refuse(_VAR_PLAN_PATH, detail)


def _no_dupes(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(_value):
    raise ValueError("non-finite number")


def _validate_delta(delta, where):
    if not isinstance(delta, dict):
        _plan_refuse(f"{where}: delta must be an object")
    if set(delta) != {"metric", "before", "after",
                      "evidence_ref", "verifier"}:
        _plan_refuse(
            f"{where}: delta must have exactly the keys metric, "
            "before, after, evidence_ref, verifier")
    for field in ("metric", "evidence_ref", "verifier"):
        if not isinstance(delta[field], str):
            _plan_refuse(f"{where}: delta {field} must be a string")
    for field in ("before", "after"):
        value = delta[field]
        if isinstance(value, bool) \
                or not isinstance(value, (int, float)):
            _plan_refuse(
                f"{where}: delta {field} must be a finite number")
        try:
            finite = math.isfinite(value)
        except (OverflowError, ValueError):
            # A huge int (e.g. 10**400) is a valid JSON number
            # but overflows conversion to float inside
            # math.isfinite; that is a plan refusal, not a
            # crash. The value itself is never echoed.
            finite = False
        if not finite:
            _plan_refuse(
                f"{where}: delta {field} must be a finite number")


def _validate_plan(doc):
    if not isinstance(doc, dict) or set(doc) != {"steps"}:
        _plan_refuse(
            "top level must be an object with exactly the key steps")
    steps = doc["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        _plan_refuse("steps must be a list of 1 to 100 step objects")
    for index, step in enumerate(steps):
        where = f"step {index}"
        if not isinstance(step, dict) or len(step) != 1:
            _plan_refuse(
                f"{where}: a step must be an object with exactly "
                "one key (adopt or cycle)")
        if "adopt" in step:
            if step["adopt"] is not True:
                _plan_refuse(f"{where}: adopt must be exactly true")
            continue
        if "cycle" not in step:
            _plan_refuse(f"{where}: unknown step key")
        cycle = step["cycle"]
        if not isinstance(cycle, dict) or set(cycle) != {
                "coders", "reviewers", "verdict", "verify_passed",
                "delta"}:
            _plan_refuse(
                f"{where}: cycle must be an object with exactly "
                "the keys coders, reviewers, verdict, "
                "verify_passed, delta")
        for field in ("coders", "reviewers"):
            value = cycle[field]
            if not isinstance(value, list) \
                    or not all(isinstance(v, str) for v in value):
                _plan_refuse(
                    f"{where}: cycle {field} must be a list of "
                    "strings")
        if not isinstance(cycle["verdict"], str):
            _plan_refuse(f"{where}: cycle verdict must be a string")
        if not isinstance(cycle["verify_passed"], bool):
            _plan_refuse(
                f"{where}: cycle verify_passed must be a boolean")
        _validate_delta(cycle["delta"], where)
    return steps


def _load_plan(plan_path: Path):
    try:
        raw = plan_path.read_bytes()
    except OSError:
        _plan_refuse("plan file is unreadable")
    if len(raw) > _MAX_PLAN_BYTES:
        _plan_refuse("plan file exceeds the 256 KiB cap")
    try:
        doc = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_no_dupes,
            parse_constant=_reject_constant)
    except Exception:
        _plan_refuse("plan file is not well-formed UTF-8 JSON")
    return _validate_plan(doc)


def _check_state_layout(state_dir: Path):
    if not (state_dir / "state.json").is_file():
        _refuse(
            _VAR_STATE_DIR,
            "state layout missing: state.json is not a file in "
            "the state dir (refusing to bootstrap fresh state)")
    if not (state_dir / "calibration" / "calibration.json").is_file():
        _refuse(
            _VAR_STATE_DIR,
            "state layout missing: calibration/calibration.json "
            "is not a file in the state dir")


def _factory_refusal(exc):
    """Convert a factory exception into a config refusal. The
    variable is recovered from the exception's leading variable
    name when it carries one (the wiring/adopter idiom names the
    variable, never its value); the detail never echoes the
    exception message."""
    match = _ENV_VAR_RE.search(str(exc))
    variable = match.group(1) if match else "build_pin_adopter"
    _refuse(variable, f"factory refusal ({type(exc).__name__})")


def _emit(line: dict):
    print(json.dumps(line, sort_keys=True), flush=True)


def _stderr_line(line: dict):
    print(json.dumps(line, sort_keys=True), file=sys.stderr,
          flush=True)


def _history_providers(verifier_env):
    """Build the cycle-28 history-reconciliation provider pair
    from the runner's verifier env. AION_VERIFIER_HOME is a
    required, allowlisted key for the verifier env the factory
    consumes, but it is not validated upstream of this call, so
    its absence refuses HERE with the runner's structured
    config refusal (naming the variable), never a bare KeyError
    traceback. The providers are lazy closures: building them
    touches no disk; each call loads its journal fresh. Returns
    (consumption_provider, supersession_provider)."""
    home = verifier_env.get("AION_VERIFIER_HOME")
    if not isinstance(home, str) or not home:
        _refuse("AION_VERIFIER_HOME",
                "required for the runner's history-"
                "reconciliation providers and must be non-empty")
    return (consumption_entries_provider_from_home(home),
            supersession_entries_provider_from_home(home))


def main() -> int:
    if sys.argv[1:]:
        _stderr_line({
            "error": "config_refusal", "variable": "argv",
            "detail": "trust.runner takes no command-line "
                      "arguments; configuration is environment "
                      "only"})
        return 2
    try:
        rc = _validate_runner_env(os.environ)
        steps = _load_plan(rc.plan_path)
        _check_state_layout(rc.state_dir)
        verifier_env = {k: v for k, v in os.environ.items()
                        if k in ALLOWED_ENV_KEYS}
        try:
            pin_env = pin_adopter_config_from_env(os.environ)
        except Exception as exc:
            _factory_refusal(exc)
        config = PinAdopterConfig(
            state_path=rc.state_dir / "state.json",
            calibration_path=rc.state_dir / "calibration"
            / "calibration.json",
            pin_dir=pin_env.pin_dir,
            snapshot_signer_id=pin_env.snapshot_signer_id,
            expected_snapshot_signer_id=pin_env.snapshot_signer_id,
            operator_id=pin_env.operator_id,
            expected_verifier_signer_id=rc.expected_signer_id,
            evidence_dir=pin_env.evidence_dir,
            supersession_approval_path=
            pin_env.supersession_approval_path)
        # Cycle 28: the runner is the composition layer that
        # legitimately holds the verifier home (it built
        # verifier_env from its own environment), so it — not
        # the factory, and not the adopter — supplies the
        # history-reconciliation providers. Detection is
        # therefore ON in the production composition: every
        # adoption attempt reconciles the pin-store history
        # against the verifier's consumption journal
        # (trust/history_reconciliation.py).
        consumption_provider, supersession_provider = \
            _history_providers(verifier_env)
        try:
            adopter = build_pin_adopter(
                verifier_env,
                expected_signer_id=rc.expected_signer_id,
                expected_key_id=rc.expected_key_id,
                authorisation_public_key=rc.ceremony_public_key,
                signing_key_path=pin_env.signing_key_path,
                config=config,
                consumption_entries_provider=consumption_provider,
                supersession_entries_provider=supersession_provider)
        except Exception as exc:
            _factory_refusal(exc)
    except _ConfigRefusal as exc:
        _stderr_line({
            "error": "config_refusal", "variable": exc.variable,
            "detail": exc.detail})
        return 2

    try:
        loop = CoreLoop(
            rc.state_dir, cycle_hook=pin_cycle_hook(adopter))
    except CorruptStateError:
        _stderr_line({
            "error": "step_refused", "variable": _VAR_STATE_DIR,
            "detail": "persisted state cannot be trusted "
                      "(CorruptStateError)"})
        return 6
    except Exception:
        traceback.print_exc()
        return 1

    for index, step in enumerate(steps):
        if "adopt" in step:
            try:
                result = adopter.snapshot_and_adopt()
            except PinAdoptionRefused as exc:
                _emit({"step": index, "kind": "adopt",
                       "outcome": "adoption_refused",
                       "error": type(exc).__name__})
                return 3
            except PinAdoptionBurned as exc:
                _emit({"step": index, "kind": "adopt",
                       "outcome": "adoption_burned",
                       "error": type(exc).__name__})
                return 4
            except PinSupersessionPendingApproval as exc:
                _emit({"step": index, "kind": "adopt",
                       "outcome": "supersession_pending",
                       "error": type(exc).__name__,
                       "authorisation_id": exc.authorisation_id,
                       "ceremony_id": exc.ceremony_id,
                       "candidate_seq": exc.candidate_seq,
                       "candidate_hash": exc.candidate_hash,
                       "old_cycle_seq": exc.old_cycle_seq,
                       "old_payload_hash": exc.old_payload_hash,
                       "report_written": exc.report_written})
                return 7
            except (SigningError, PinStoreError) as exc:
                _emit({"step": index, "kind": "adopt",
                       "outcome": "step_refused",
                       "error": type(exc).__name__})
                return 6
            except Exception:
                traceback.print_exc()
                return 1
            _emit({
                "step": index, "kind": "adopt",
                "outcome": result.outcome,
                "pin_seq": result.pin["cycle_seq"],
                "pin_hash": result.pin["payload_hash"],
                "record_reason": result.record.reason
                if result.record is not None else None})
            continue
        cycle = step["cycle"]
        try:
            entry = loop.run_one_cycle(
                cycle["coders"], cycle["reviewers"],
                cycle["verdict"], cycle["verify_passed"],
                cycle["delta"])
        except (PinAdoptionBurned, PinAdoptionRefused,
                PinSupersessionPendingApproval) as exc:
            recorded = getattr(exc, "cycle_entry", None) or {}
            _emit({
                "step": index, "kind": "cycle",
                "outcome": "cycle_recorded_pin_pending",
                "cycle_id": recorded.get("cycle_id"),
                "item_id": recorded.get("item_id"),
                "adoption_error": type(exc).__name__})
            return 5
        except (InvalidTransition, ValueError, CorruptStateError,
                SigningError, PinStoreError) as exc:
            _emit({"step": index, "kind": "cycle",
                   "outcome": "step_refused",
                   "error": type(exc).__name__})
            return 6
        except Exception:
            traceback.print_exc()
            return 1
        if entry is None:
            _emit({"step": index, "kind": "cycle",
                   "outcome": "idle"})
        else:
            _emit({
                "step": index, "kind": "cycle",
                "outcome": "recorded",
                "cycle_id": entry["cycle_id"],
                "item_id": entry["item_id"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
