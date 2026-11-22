# REVIEW — Cycle 17: ship-tx journal anchoring war room

Blind internal reviewers (scores before reconciliation).
External seats seat-gpt / seat-gemini: VACANT this detached
run (brief at internal/CROSS-CHECK-BRIEF-CYCLE-17.md), so
the verdict is PROVISIONAL. Cycles 14+15+16 remain held on
the Protected Gate decision, untouched by this cycle.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | integration / correctness | 0.70 | FIX |
| rev-r2 | adversarial / safety | 0.58 | FIX |
| rev-r3 (seat 15) | forced dissent | 0.35 | FIX |
| rev-r5 | test quality | 0.72 | FIX (test-only) |
| rev-r6 | consumer / API contract | 0.92 | SHIP |
| re-verification seat | fix round | 0.97 | SHIP |

Reconciled verdict: **SHIP, PROVISIONAL** — every code
finding below was fixed and re-verified in the fix round
(targeted suites 231 OK; full suite 1228 OK, skipped=26).
rev-r3's structural dissent is preserved, not overridden:
this cycle is library/operator plumbing with no in-tree
caller yet, and it must not be read as clearing the cycles
14+15+16 external gate.

## Findings and dispositions

- rev-r1 F1 / rev-r2 F2 / rev-r3 #2 → CLOSED. Same-file
  guard compared lexical abspath strings; symlink (and
  hardlink) aliases dodged it and parked terminally. Guard
  now uses os.path.samefile with a resolved-path fallback;
  symlink-alias regression test added; the re-verification
  seat additionally reproduced the hardlink case itself.
- rev-r2 F1 / rev-r3 #1 → CLOSED. The guard suppressed only
  the tx-side verification, so sharing the TX anchor file
  still parked via the ship-side kind mismatch, and the
  same-file diagnosis string was dropped exactly when a park
  existed. Both verifications are now suppressed on a
  same-file diagnosis; both directions tested.
- rev-r1 F2 / rev-r2 F3 / rev-r3 #3 → CLOSED. The
  no-park-target raise fired only for zero transactions;
  an all-terminal journal with a forged tx anchor returned
  [] silently, contradicting the module docstring. Raise
  widened to "no non-terminal transaction", remedy stated;
  rev-r3's asymmetry question answered with the stated
  principle (the tx journal IS the pinned object; the ship
  ledger is a different file with its own consumers) in the
  code comment and this record.
- rev-r1 F4 / rev-r3 #6 → CLOSED. Park outcomes now carry
  `anchor_sources` naming which anchor produced each park
  reason; `reasons` keeps its bare legacy values.
- rev-r1 F3 → CLOSED. Anchor labelling now applies only
  when tx_anchor_path participates; a ship-only caller's
  error strings are byte-identical to pre-cycle-17 (verified
  by the re-verification seat).
- rev-r2 F4 → CLOSED as documented. The raise is fail-closed
  by design; both docstrings now state the remedy (correct
  anchor or audited force_reanchor) and shipcheck's contract
  names the exception.
- rev-r2 F5 → CLOSED. Both anchors are re-verified after
  the settlement loop; a park reason appearing only then
  raises AnchorError, settlements standing as journaled
  evidence. Identical repeat exceptions (e.g. the inside-dir
  placement error) are excluded — a bug in the first fix
  attempt, caught by the targeted suites and corrected.
  Residual window is documented, not hidden.
- rev-r2 F6 (residual, unkeyed pin) → ACCEPTED as the
  module's stated honest scope, unchanged from the signing /
  ship anchors; docstrings state it for the tx journal too.
- rev-r3 #5 → RECORDED, scope-honest. No production caller
  passes tx_anchor_path yet; docstrings and the build
  record say so in the present tense, and wiring the ship
  flow is the named follow-on cycle.
- rev-r5 → CLOSED. Discriminating wrapper tests (bogus
  anchor parks via recover_ship_tx; deleted journal raises
  through it), recovery-never-advances + caller update test,
  force_reanchor / reanchor-audit tests for kind="ship-tx",
  truncated-journal-with-live-tx park
  (anchor_ahead_of_journal), reverse kind-mismatch park,
  stronger inside-dir assertions, combined matrix incl.
  both-operator-errors labelling and ship-park source.
  rev-r5 also caught the brief's test count (29 claimed,
  30 written); corrected — final count 41 with the fix
  round, verified by the full-suite delta 1187 → 1228.

## Verification

- New suite: 41 tests OK. Targeted suites: 231 OK
  (skipped=1). Full suite, final tree: **1228 tests, OK
  (skipped=26)** (baseline 1187 → +41).
- No protected paths touched; no push from this run; loop
  state recording deferred to the signed ship path
  (cycles 14–16 precedent).

Verdict: **SHIP, PROVISIONAL** (external seats vacant;
rev-r3 dissent preserved; follow-on wiring cycle named).
