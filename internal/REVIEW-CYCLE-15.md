# REVIEW — Cycle 15: snapshot pin ceremony war room

Blind internal reviewers (scores given before reconciliation;
only seats actually run this cycle are listed — no fabricated
seats). External seats seat-gpt / seat-gemini: VACANT this run
(brief at internal/CROSS-CHECK-BRIEF-CYCLE-15.md), so the
verdict is PROVISIONAL and cycle 14's split stays unresolved
until both seats review cycles 14+15 together.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r2 | adversarial / safety | 0.50 | FIX |
| rev-r3 (seat 15) | forced dissent | 0.35 | FIX |
| rev-r5 | test quality / integration | 0.82 | FIX (test-only) |

Reconciled verdict: **SHIP, PROVISIONAL** — every code finding
below was fixed and re-verified in the fix rounds (signing
suites 76 tests OK); rev-r3's structural dissent is preserved,
not overridden, and is the reason the verdict stays provisional
beyond the vacant external seats.

## Findings and dispositions

- rev-r2 F1 HIGH → CLOSED. Reason relabelling defeated both
  gates (lost_pin/corrupted_pin accepted with a present pin for
  routine advances and gap jumps). Fix: with a usable pin
  present the only ceremony reason is chain_gap_recovery.
- rev-r2 F2 → CLOSED. snapshot_id added to the self-derived
  evidence blocklist.
- rev-r2 F3 → CLOSED. advance_pin compares the pin's captured
  key_id/signer_id bindings to the candidate.
- rev-r2 F4 → CLOSED. verify_ceremony_record re-validates
  reason allowlist, hex64 evidence, forward movement, non-bool
  sequences and id formats, in addition to hash + MAC.
- rev-r2 F5 → CLOSED. Pins are captured once via .get into
  locals; advance_pin returns the captured pin, never a re-read.
- rev-r3 #3/#4 → CLOSED in code. Pin+1 unchained candidates are
  refused as integrity failures; chain_gap_recovery requires a
  strict verification result of exactly ("chain_gap",).
- rev-r3 #1/#2/#5/#6 → PRESERVED as stated limits (docstring):
  evidence independence is non-equality only; the returned pin
  carries no re-anchor marker (pin-format change = future
  work); operator authorisation is in-process and the MAC is
  symmetric. The dissent's stronger design (quorum signatures,
  typed provenance-bound evidence, marker chained into the pin)
  is recorded as the bar for any production adoption.
- rev-r5 → CLOSED. Branch tests added for unknown_key,
  calibration-hash evidence, malformed pins, corrupted_pin,
  classification duplicates and list input.

## Verification

- Signing suites: 76 tests OK (61 snapshot + 15 ceremony).
- Full suite, final tree: **1177 tests, OK (skipped=26)**
  (baseline 1162 → +15; pre-fix full run was 1175).
- Loop-state recording deferred to the signed ship path
  (cycle-14 precedent); no commit/push from this run.

Verdict: **SHIP, PROVISIONAL** (external seats vacant;
rev-r3 dissent preserved; cycles 14+15 to return to both
external seats together per CROSS-CHECK-8).
