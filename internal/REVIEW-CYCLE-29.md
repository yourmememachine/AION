# REVIEW — Cycle 29 war room (wired at-sequence attempt)

Six internal seats, blind, independent scores before
discussion; seat R6 held the forced-dissent slot. External
seats via blind brief internal/CROSS-CHECK-BRIEF-CYCLE-29.md
(record: internal/CROSS-CHECK-29.md).

## First round — SPLIT

- R1 correctness — SHIP 0.88 (exact pair, relevance/excuse
  never consulted, recovery landing all verified in code;
  minor: depth-0 phrasing imprecise and unpinned).
- R2 tests — SHIP 0.92 (non-vacuous: pend/refuse/burn
  counterfactuals each go red; minor: record_reason not
  asserted, head old side not asserted).
- R3 claims — FIX 0.80 (core correction accurate and
  history-preserving; closing sentence overstates: beyond-head
  refusal is shape-specific, resume path re-pends without a
  fresh verifier refusal; dangling BUILD-CYCLE-29 reference).
- R4 scope/safety — SHIP 0.95 (test-only, real state isolated
  and hash-asserted; no fix items).
- R5 adversarial — FIX 0.78 (pin_hash proves candidate
  identity, not lineage; missing record_reason and the third
  entry's consumption_kind/recovery_of/recovery_depth).
- R6 forced dissent — FIX 0.35 (follow-up re-scoped by the
  builders; wired pending coverage still zero; correction
  incomplete across cycle-28 surfaces; universal "only"
  claim unproven).

## Fix round — reconciled

- Assertions added: record_reason == "burned_unadopted";
  head old_cycle_seq == 13; third entry consumption_kind ==
  "recovery", recovery_depth == 1, recovery_of == head
  authorisation_id, old/new seq 13/15. (R1/R2/R5)
- Comment corrected: depth phrasing ("head burn at derived
  depth 0; recovery lands at depth 1") and the closing
  universal replaced by a scoped claim; the beyond-head
  refusal stated as shape-specific. (R1/R3/R6)
- Records landed: this file, internal/BUILD-CYCLE-29.md,
  internal/CROSS-CHECK-29.md; correction pointers appended
  (not rewrites) to internal/BUILD-CYCLE-28.md and
  internal/cycle28-work/fix-round-gpt.md. (R3/R6)
- R6 item (2) disposition: a genuinely wired fresh pending
  test was NOT added, because the seats' own tracing (coder
  seat A, R3) shows the fresh wired pending reach is not
  established for any shape post-cycle-28 — manufacturing
  one is not possible without a design change. Instead the
  follow-up stays OPEN, renamed: "wired-pending-reachability"
  — determine, by design, whether a fresh wired attempt
  should be able to reach the supersession-pending stop
  (reconciliation currently refuses the unaccounted
  beyond-head shapes that the unwired pending flow was built
  for), or whether pending is resume-only in the wired
  composition. This is a design question, not a coverage
  gap that a test alone can close.
- R6 item (4) disposition: decision-free recovery landing of
  an exact-pair head burn is not cycle-29's invention — the
  burned_unadopted recovery mechanism (bounded depth,
  lineage-bound, verifier-checked) predates cycle 28 and is
  pinned by the crash/recovery suites; cycle 29 pins its
  wired composition. External seat-gemini raised the same
  condition and it is recorded in BUILD-CYCLE-29.md.

## External seats

- seat-gpt — SHIP 0.94 (pin-and-correct is the right
  closure; do not change production code to manufacture the
  claimed transition; keep reachability claims scoped).
- seat-gemini — SHIP 0.88 (same closure, conditional on
  recovery-at-head being intended design — see disposition
  above; refusal distinction partial, contrasted via the
  sibling beyond-head exit-6 test in the same file).

## Final verdict

SHIP — reconciled: all FIX seats' code/record items applied
and re-verified (both sibling runner tests green with the
new assertions); R6's remaining point is carried as the
open renamed follow-up above, not hidden. External seats
SHIP and are reconciled (their scoping caveats match the
narrowed comment). Full suite total in BUILD-CYCLE-29.md.
