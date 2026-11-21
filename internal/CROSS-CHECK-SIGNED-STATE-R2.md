# External war-room seats — signed-state delta round (cycle 12)

Date: 2026-11-20 ~06:52–06:55 MST (browser sessions on the user's
Google sign-in). Brief: internal/CROSS-CHECK-BRIEF-SIGNED-STATE-DELTA.md
(blind; no internal verdicts or scores). Round 1 record:
internal/CROSS-CHECK-SIGNED-STATE.md (both seats FIX; findings
adopted as code/documentation there and in the cycle-10 fix rounds).

## seat-gpt — FIX, 0.91

1. [HIGH] Future-dated signed_at may bypass the 48 h freshness
   bound (a signature 30 days ahead passing anti-backdate and a
   negative-age check). Asked for −300 s ≤ now − signed_at ≤ 48 h
   enforcement with boundary tests; stated it would move to SHIP
   WITH DOCUMENTED LIMITATIONS if rejection + boundary tests are
   confirmed, subject to finding 2.
2. [MEDIUM] Timestamp consistency needs an explicit invariant
   (last_completed_at vs final history entry, empty-history null,
   chronological consistency, normalised-instant comparisons);
   wants a correctly-MACed mutually-inconsistent envelope to
   return malformed_payload.
3. [MEDIUM] Capture consistency is improved but not atomic
   (declared open limit; not an independent ship blocker).
4. [LOW] Immediate-successor chaining is not complete chain
   verification (declared limit; not a ship blocker).
5. [LOW] Pin persistence is an external security dependency;
   wants the contract to cover advancement authorisation,
   monotonicity, and lost/corrupt-pin recovery.
Closed in its assessment: payload validation, malformed-input
resilience, parser completeness, calibration ambiguity,
anti-backdate in the builder, immediate-successor chaining. It
noted it reviewed the change description and claimed
demonstrations, not source.

## seat-gemini — FIX, 0.78

1. [Medium] Unpinned / non-advancing chaining leaves multi-step
   gaps unchecked (pin+2; converges with rev-r2's dissent).
2. [Medium] sign_state_files read-check-read leaves a post-check
   mutation window (calibration after its read; state after the
   second read).
3. [Low–Medium] Re-derivation guard may not cover hostile Python
   objects on other verify paths; future signed_at bounding
   (converges with seat-gpt's HIGH).
4. [Low] b"" refusal vs whitespace/invalid calibration payloads;
   confirm calibration_bytes=None at verify is not a wildcard.
Confirmed as held up: shared payload re-derivation, full history
walk, honest non-goals and the test-seam fix.

## Reconciliation (coordinator, against the code)

- gpt-1: REFUTED by code — verify_signed_snapshot appends
  signed_in_future when signed_at > now + 300 s skew and expired
  at the MAC-bound expires_at (TTL ≤ 48 h re-derived in the
  builder); a +30-day signature is refused immediately. The
  requested boundary tests were added this cycle
  (test_future_signed_at_skew_boundary: −300 s pass, −301 s
  refuse, +30 days refuse). By the seat's own stated condition
  this item is closed.
- gpt-2: CLOSED in substance — the signer derives
  last_completed_at from the final history entry; the parser
  enforces non-decreasing history timestamps; comparisons use
  parsed normalised instants; and this cycle's internal fix
  (empty history carrying last_completed_at, rev-r1) removes the
  one mutually-inconsistent shape that verified. A correctly-MACed
  envelope with history_len > last_cycle_id likewise returns
  malformed_payload now (internal rev-r1/rev-r4 probes).
- gpt-3 / gpt-4 / gemini-1: declared limits, not closures —
  capture atomicity stays an open limit; chain completeness is
  queued as backlog snapshot-chain-gap-enforcement (6.5) with
  rev-r2's dissent preserved in REVIEW-CYCLE-12.md.
- gpt-5: pin contract already states placement, advancement-only-
  after-clean-verify, and never-reconstruct; the ceremony is
  queued as backlog snapshot-pin-ceremony (4.0).
- gemini-2: REFUTED for the attested bytes — sign_state_files
  signs the exact buffers it read; post-read file mutation cannot
  change the attested pair. The coexistence residual is declared
  in the module docstring.
- gemini-3: assessed not-adopted — supported entry points
  reconstruct envelopes from JSON primitives via the strict
  parser; the payload guard converts type hostility to
  malformed_payload; future-signed_at bounding exists (see gpt-1).
- gemini-4: by design — the calibration binding is the whole-file
  hash, never parsed by this module (a whitespace file is a
  bindable, if useless, log; the calibration loader itself is
  strict). Verify with expected_calibration_bytes=None performs
  no calibration comparison unless require_calibration is set —
  the documented envelope-only convention; the strict wrapper
  requires the bytes.

Cycle verdict remains **PROVISIONAL** until the external seats
re-review this cycle's delta (round 3). Neither seat's FIX blocks
recording under the project's precedent (cycles 8–11 recorded
provisional; external findings reconciled here with code evidence,
and no external approval can override an internal FIX — the
internal room's FIX items were closed in code this cycle).
