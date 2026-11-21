# CROSS-CHECK BRIEF — Cycle 14: snapshot chain-gap enforcement

Blind brief for the external reviewer seats (seat-gpt, seat-gemini).
It states what was built, the design decisions, and the test
evidence. It deliberately contains NO internal reviewers' scores
or verdicts.

## What was built

Backlog item `snapshot-chain-gap-enforcement` (leverage 6.5):
enforce snapshot chain continuity beyond a pin's immediate
successor in the strict wrapper.

Background: `signing/state_snapshot.py` signs snapshots of the
loop state + calibration log. A caller may pin the newest
snapshot it trusts (`expected_pin = {"cycle_seq", "payload_hash"}`,
held outside the state directory). Before this cycle:

- `cycle_seq < pin` → `snapshot_rolled_back`
- `cycle_seq == pin`, different hash → `pin_mismatch`
- `cycle_seq == pin + 1`, `prev_snapshot_hash != pin hash` →
  `chain_discontinuity`
- `cycle_seq > pin + 1` → **no check at all**: a seq-3 snapshot
  chained to garbage verified `()` against a seq-1 pin, even
  through the strict wrapper `verify_snapshot_for_state`. A
  caller advancing its pin on `()` laundered the missing seq-2
  snapshot into its trusted pin.

Change (all in `signing/state_snapshot.py`, no other production
file touched):

1. `verify_signed_snapshot` gains a private keyword
   `_enforce_chain_gap=False`. Inside the existing pin block —
   after the pin's shape validation and after the `pin + 1`
   branch — a new `elif` appends the reason `chain_gap` when the
   flag is set and `signed.cycle_seq > pin cycle_seq + 1`.
2. `verify_snapshot_for_state` (the strict wrapper) passes
   `_enforce_chain_gap=True`. Bare verification is unchanged:
   it remains an envelope/rollback check and still tolerates the
   gap, now stated explicitly in its docstring.
3. Docstrings updated: module docstring (strict wrapper narrows
   the completeness limit; the refusal assumes one verified
   snapshot per cycle; a missed or expired intermediate deadlocks
   strict catch-up until an external pin ceremony — backlog item
   `snapshot-pin-ceremony`, not yet implemented — re-anchors the
   pin), bare-verify docstring (no gap enforcement here), strict
   wrapper docstring (enforcement, the cost, and that pruned
   *state* history is unaffected — only unobserved *snapshot*
   sequences are refused).

## Design decisions to scrutinise

- **Reason, not exception, and a new name.** `chain_gap` is a
  returned reason (the snapshot is authentic but unverifiable at
  that distance), distinct from `chain_discontinuity`: at
  pin + 2 the discontinuity is unprovable, not proven — the
  verifier holds only the candidate's `prev_snapshot_hash`
  (naming the unseen intermediate) and the pin's hash, never the
  intermediate itself. Even a candidate whose `prev` correctly
  names the real intermediate is refused: correctness at that
  distance is unobservable from (candidate, pin) alone.
- **Placement inside the pin block** reuses the existing pin
  validation (dict shape, key subset, non-bool int `cycle_seq`,
  hex64 `payload_hash`) so malformed pins raise the same
  `SigningError` as before and the gap arithmetic can never run
  on unvalidated input; the final dedup (`dict.fromkeys`) is
  inherited.
- **Strict wrapper only.** No production caller of either verify
  function exists in the repo (grep-verified); the bare function
  is a documented envelope-only check whose gap tolerance is
  pinned by a pre-existing test (`test_newer_than_pin_passes`),
  which still passes.

## Declared limits (not claimed as fixed)

- A caller using bare `verify_signed_snapshot` can still ignore
  the gap; nothing forces the strict wrapper.
- The pin is caller-supplied and unauthenticated: re-basing a
  pin from the candidate envelope itself defeats the check and
  is detectable only by pin-handling discipline outside this
  module. Joint rollback of state + snapshots + pin remains
  undetectable in-deployment.
- A key holder can mint a perfectly chained pin + 1 successor
  over a fabricated well-formed history (HMAC is symmetric);
  stepwise laundering by a key holder is not addressed.
- Pin advancement/replacement/lost-pin recovery is NOT solved;
  `snapshot-pin-ceremony` remains open, and this enforcement
  makes it more urgent, not less.

## Test evidence

- New `Cycle14ChainGapTests` (13 tests) in
  `tests/test_signing_state_snapshot.py`: pin same-seq passes;
  pin + 1 correctly chained passes; pin + 2 refused with exactly
  `("chain_gap",)` both with a correct `prev` naming the unseen
  intermediate and with a garbage `prev`; large jump refused;
  gap co-reports with `calibration_mismatch` exactly once;
  pin + 1 forked reports `chain_discontinuity` only; older
  reports `snapshot_rolled_back` only; same-seq wrong hash
  reports `pin_mismatch` only; pin-seq-0 boundaries (seq 1 is a
  successor, seq 2 is a gap); bare verify still returns `()` at
  pin + 2 (scope pin); pruned single-entry state at seq 5 passes
  against a seq-4 pin and reports `chain_gap` against a seq-3
  pin; seven malformed-pin shapes raise `SigningError` through
  the strict wrapper.
- Module suite: 57 tests, all passing (44 before this cycle).
- Full-suite total: recorded in internal/BUILD-CYCLE-14.md once
  the coordinator run completes.

## Questions for the external seats

1. Is `chain_gap` as a returned reason (not an exception) the
   right failure shape for the strict path?
2. Does refusing even a correctly-linked pin + 2 candidate
   over-refuse any legitimate flow the brief has not named?
3. Does any docstring sentence over-claim what the enforcement
   proves?
