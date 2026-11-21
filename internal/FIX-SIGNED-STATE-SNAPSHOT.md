# Fix — live state snapshot test vs the anti-backdating guard

Date: 2026-11-20 (~06:25 MST baseline; fixed same morning).
Found by: parent's independent full-suite verification (1075 tests, 1 ERROR).
Failing test: `test_live_state_and_calibration_snapshot`
(`tests/test_signing_state_snapshot.py`, `LiveStateTests`).

## Root cause

The defect was in the **test**, not the module. The live test read the
real `state/state.json` and calibration log, derived its expectations
from the file (cycle_seq, history length) — but signed with a
**hard-coded** instant, `now="2026-11-20T12:30:00+00:00"`. When the
test was written (cycle 10), the live state's last history entry was
cycle 10, `completed_at 2026-11-20T12:04:11Z`, so 12:30Z was safely
after it. When cycle 11 (trust-boundary-v31-fixes) recorded at
`2026-11-20T13:21:41Z`, the hard-coded instant fell *before* the
state's last completed cycle by ~52 minutes — far beyond the guard's
300-second clock-skew allowance — and `sign_state_snapshot` refused,
exactly as designed: "signed_at precedes the state's last completed
cycle; refusing to attest a state from before it existed."

The module's guard is correct and was left untouched: it refuses iff
`signed_at < last_completed_at − CLOCK_SKEW_SECONDS (300)`, identically
in `sign_state_snapshot`, the payload builder, and verification
(`signed_before_state`). The test's own comment claimed it "survives
the cycle it ships in" because expectations were derived from the live
file — the signing instant was the one expectation that wasn't.

## Fix (tests/test_signing_state_snapshot.py only)

- `test_live_state_and_calibration_snapshot`: the signing/verification
  instant is now derived from the live file — `now =
  facts.last_completed_at`, the earliest moment this state can
  legitimately be attested. All original assertions unchanged
  (cycle_seq == last_cycle_id, history_len ≥ 9, strict verify == ()).
  Deterministic under any future cycle recordings.
- New `test_live_state_backdated_snapshot_refused`: signing the live
  state at `last_completed_at − (skew + 1s)` must raise SigningError —
  pins the refusal direction against the real file, so the guard
  cannot be weakened to make the roundtrip pass.
- New `test_sign_backdating_skew_boundary` (fixture): signing at
  exactly `last_completed_at − CLOCK_SKEW_SECONDS` succeeds; one
  second beyond raises. Pins the guard's boundary semantics.
- Imports added: `datetime/timedelta/timezone`,
  `CLOCK_SKEW_SECONDS` (from `signing.state_snapshot`).

No production code changed. `state/state.json` history untouched; no
protected path touched.

## Evidence

- Standalone reproduction before fix: the named test ERRORs with the
  exact SigningError above; after fix it passes.
- Module: `tests.test_signing_state_snapshot` — **40 tests, 10
  consecutive runs, all OK** (was 38 tests; +2 new).
- Full suite after fix: **1077 tests, OK** (1075 baseline + 2 new;
  the 1 ERROR is gone).

## Noticed, not fixed here

- Full-suite skip count is 25, not the 2 recorded at cycle 11: the
  VM's OS state was reset again (service restarted mid-session), so
  the `aion-verifier` OS user and `/etc/aion-verifier` no longer
  exist and the live production-deployment tests skip by design
  ("live deployment not provisioned"). Unrelated to this fix;
  re-provisioning via `deploy/verifier-identity/setup.sh` is an
  operator action for the parent to schedule.
