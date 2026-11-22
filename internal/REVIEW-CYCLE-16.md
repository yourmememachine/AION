# REVIEW — Cycle 16: pin ceremony hardening war room

Blind internal reviewers (scores before reconciliation).
External seats seat-gpt / seat-gemini: VACANT this run (brief
at internal/CROSS-CHECK-BRIEF-CYCLE-16.md), so the verdict is
PROVISIONAL and cycles 14+15 remain held pending their review
of cycles 14+15+16 together.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | integration / correctness | 0.84 | FIX |
| rev-r2 | adversarial / safety | 0.72 | FIX |
| rev-r3 (seat 15) | forced dissent | 0.42 | FIX |
| rev-r5 | test quality | 0.74 | FIX (test-only) |
| rev-r6 | consumer / API contract | 0.90 | SHIP |

Reconciled verdict: **SHIP, PROVISIONAL** — all code findings
below were fixed and re-verified in the fix round (signing
suites 189 OK; full suite 1187 OK, skipped=26). rev-r3's
structural dissent is preserved, not overridden: this cycle
must not be read as clearing the cycles 14+15 external gate,
and the gating items (independent operator authority,
authenticated evidence provenance, atomic pin+record
persistence, ceremony key separation) remain OPEN — the first
two await Dilip's decision on extending the Protected Gate's
scope.

## Findings and dispositions

- rev-r1 F1 / rev-r3 #6 / rev-r6 F3 → CLOSED. Pin-context
  `None` ambiguity: sentinel default per side; explicit
  `expected_old_pin=None` asserts an absent old pin; supplying
  only one side asserts nothing about the other. Tested.
- rev-r1 F3 / rev-r6 F4 → CLOSED. Malformed context pins now
  report `pin_context_mismatch` instead of raising.
- rev-r1 F2 / rev-r2 F5 → CLOSED. `strict_reasons` must be a
  list/tuple and is captured once; dict/set shapes refused.
- rev-r2 F4 → CLOSED. Forked histories (same target sequence,
  different hashes) are refused.
- rev-r2 F1/F2/F3, rev-r3 #2/#3/#4/#5/#7 → CLOSED as claims,
  OPEN as capabilities. Docstring downgraded at the claim
  sites: history protections hold only under a complete
  caller-supplied history (opt-in consistency check over
  same-key-attested records — not rollback/replay protection);
  binding claim qualified to pins carrying bindings; no-pin
  reasons receive no recomputation; no-context verification
  proves issuance only. Making history mandatory/anchored
  needs the persistence + authority work that is owner-gated.
- rev-r5 → CLOSED. Isolated tests added: stale signed_at
  (message-isolated), equal-seq history head, forked history,
  re-MACed one-step record (exact `("not_a_gap_reanchor",)`),
  replay isolated by message, context variants, binding-absent
  minimal pin pinned as known behaviour.
- rev-r6 suite caveat → CLOSED. The one full-suite failure
  (sealed-eval contention, untouched by this diff) passes in
  isolation and in both coordinator full runs: flake.

## Verification

- Pin ceremony suite: 25 tests OK. Signing suites: 189 OK.
- Full suite, final tree: **1187 tests, OK (skipped=26)**
  (baseline 1177 → +10).
- No commit/push from this run; loop-state recording deferred
  to the signed ship path (cycles 14/15 precedent).

Verdict: **SHIP, PROVISIONAL** (external seats vacant; rev-r3
dissent preserved; cycles 14+15+16 to return to both external
seats together; authority/provenance items await Dilip's
Protected Gate decision).
