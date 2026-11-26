# REVIEW — Cycle 31 war room

Six internal seats, blind, scores before discussion; R3 forced
dissent. External: internal/CROSS-CHECK-31.md.

First round — unanimous FIX (no split on the verdict, split on
severity):
- R1 correctness FIX 0.80; R2 error surface FIX 0.74; R3 forced
  dissent FIX 0.35; R4 safety/limits FIX 0.60; R5 tests FIX 0.82;
  R6 completeness FIX 0.78.
- Convergent findings: pinning preamble false for cycle-23 claims
  (R1/R3/R5); pickle gap claim false, empirically disproven
  (R1/R2); post-settlement re-verification overgeneralised —
  returned malformed/missing reasons discarded (R1/R2);
  force_reanchor audit omitted (R3/R4); limits omissions —
  opt-in defaults, by-value binding, manifest rebuild, ANOMALY
  terminality, false-park direction (R4); operability gaps —
  no runbook/operations/parameters (R6); stale-claim framing
  conflated recover() with the wrapper (R1/R3).

Fix round — reconciled: every finding above verified against
code by the coordinator (pickle and re-verification behaviour
re-run empirically) and applied to docs/RECOVERY-CONTRACT.md.
External seats' required additions (concurrency/atomicity
section, empty-list prominence, interface-vs-invocation framing,
partial-recovery semantics) applied in the same round.

Re-verification seat: SHIP (all seven scoped points pass,
58-test pin file re-run OK).

Final verdict: SHIP — full suite 1814 OK (skipped=28),
state hash unchanged.
