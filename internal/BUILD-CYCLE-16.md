# BUILD — Cycle 16: pin ceremony hardening

Item: the convergent next-trust-cycle scope from CROSS-CHECK-9
(cycles 14+15 external seats), restricted to what is closable
inside `signing/pin_ceremony.py`. Items (1) independent operator
authority and (2) authenticated evidence provenance are NOT
built: they need a protected source / owner decision (Dilip's
decision on extending the Protected Gate's scope is pending),
and this cycle does not pretend otherwise. No protected paths
touched (eval/, core/, oversight/ unchanged).

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15). Three design seats
reported before code (recorded in this run's working notes):
- Pod C (9, 10, 11) implementation: `_candidate_relation`,
  history head fold, single clock capture, shared sole-chain-gap
  predicate.
- Pod D (3, 4, 15) adversarial: found the strongest fix —
  `strict_reasons` was trusted, never recomputed or bound to the
  pin/candidate; also the one-step record asymmetry in
  `verify_ceremony_record`.
- Pod B (2, 6, 7) caller contract: exact invariants of all four
  public functions, the minimal backwards-compatible
  `ceremony_history` keyword, and the test constraints (history
  must be per-call, never global — existing tests reuse one
  evidence constant).
Pods A (1, 5, 8) and E (12, 13, 14) design angles are folded
into the same scope decision: module shape unchanged, zero
production callers affected (grep-verified by rev-r6).

War room: 5 live blind reviewer seats (rev-r1 0.84 FIX,
rev-r2 0.72 FIX, rev-r3 forced dissent 0.42 FIX, rev-r5 0.74
FIX test-only, rev-r6 0.90 SHIP) + fix round; see
REVIEW-CYCLE-16.md. External seats seat-gpt / seat-gemini:
VACANT this detached run (brief at
internal/CROSS-CHECK-BRIEF-CYCLE-16.md), so the verdict is
PROVISIONAL and cycles 14+15 stay held.

## What was built

1. Recomputed eligibility: for `chain_gap_recovery`,
   `reanchor_pin` recomputes the strict result via
   `verify_snapshot_for_state` against the captured pin and
   requires the supplied `strict_reasons` (list/tuple, captured
   once) to equal the recomputed `("chain_gap",)` exactly.
   `_is_sole_chain_gap` is the one shared eligibility atom for
   `classify_verification` and `reanchor_pin`.
2. `_candidate_relation` is the only sequence arithmetic;
   `gap_prev_is_pin` (gap-distance candidate whose prev names
   the pin) is refused as an integrity failure.
3. Optional `ceremony_history`: records must verify; evidence
   reuse (within history or against this ceremony), replayed
   targets, forked histories (same target seq, different hash),
   candidates behind the history head, and candidates predating
   the latest ceremony are refused. History can only refuse.
4. `verify_ceremony_record`: one-step records report
   `not_a_gap_reanchor`; optional per-side pin context with a
   sentinel default (explicit `expected_old_pin=None` asserts
   an absent old pin); malformed context reports
   `pin_context_mismatch` instead of raising.
5. Single clock capture (`moment`) for recomputation, bare
   verification and `performed_at`.
6. Docstring claims downgraded where the war room required:
   binding claim qualified to pins that carry bindings; history
   protections stated to hold only under a complete
   caller-supplied history; no-context record verification
   stated to prove issuance only; no-pin reasons stated to
   receive no recomputation.

## Tests

- tests/test_signing_pin_ceremony.py: 25 tests (15 prior + 9
  cycle-16 + 1 fix-round test with isolated stale / equal-seq
  head / forked history / re-MACed one-step / context cases).
- Signing suites: 189 tests OK.
- Full suite, final tree: **1187 tests, OK (skipped=26)**
  (baseline 1177 → +10). rev-r6's single contention-test
  failure was re-run in isolation: OK — a flake under parallel
  load, also green in both coordinator full runs.

## Recording status

Loop state NOT advanced (signed ship path, as cycles 14/15);
no commit, no push from this run — the verdict is provisional,
and cycles 14+15+16 go back to both external seats together.

## Self-improvement delta

tests_passing 1177 → 1187 (coordinator full-suite run on the
final tree; verifier: the war room's non-builder seats).
Process lesson: never trust a caller-supplied verdict tuple
when the verdict can be recomputed from captured inputs —
and a check that passes vacuously when its input is withheld
must say so at the claim site, not only in a limits section.
