# BUILD CYCLE 31 — cycles 17+18 recovery-contract document

**Summary:** The carried follow-up "cycles 17+18 recovery-contract
document" is closed. `docs/RECOVERY-CONTRACT.md` states the
ship-tx recovery contract as the code implements it today,
reconciling three blind coder traces (correctness, error surface,
adversarial limits). Document only — no production code changed.
Baseline and final: **1814 tests OK (skipped=28)**. Real
state/state.json untouched (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
identical before/after). eval/ untouched.

## Corrections the traces forced (not in the 17/18 records)
- Cycle 23 wired the write half: `anchored_record_ship` verifies
  both anchors with a currency requirement and advances the tx
  anchor after COMMITTED — but it is unexported, has no non-test
  caller, and raises ShipRefused post-COMMITTED on advance failure.
  Tx-anchor advancement in production is orphaned; the recovery
  half remains unwired (recover accepts tx_anchor_path, no in-tree
  caller supplies it).
- Post-settlement re-verification discards RETURNED non-park
  reasons: a mid-recovery swap to a malformed/missing anchor is
  silently ignored. New open item.
- Recovery never checks the force_reanchor audit
  (check_reanchor_audit never passed on the recovery path).
- Draft errors caught in review and fixed: pickle claim about the
  plain AnchorError branch was false (outcomes survive via
  __dict__); pinning preamble overclaimed; citations off by one.

## Fix round
All internal seats and both external seats returned FIX; the
reconciled fix list (preamble, pickle correction, re-verification
gap, force_reanchor limit, opt-in/default-None statement,
by-value and manifest-rebuild limits, ANOMALY terminality,
false-park direction, Operating section, concurrency/atomicity
section, advancement-orphan framing) was applied and a
re-verification seat passed all seven scoped points (SHIP).
Records: internal/REVIEW-CYCLE-31.md, internal/CROSS-CHECK-31.md,
work in internal/cycle31-work/.

## Open follow-ups (carried)
- Post-settlement returned-failure surface (new this cycle).
- Production recovery caller passing tx_anchor_path.
- Non-[] surface for carrier-less evidence (design decision).
- Pin-store head anchoring; pin-directory-loss reconciliation;
  operator-authentication-channel; concurrent-actor interleaving.

## Staffing
15 coders, 5 pods of 3: Pod A (1,5,8) correctness trace; Pod B
(2,6,7) error-surface trace; Pod C (9,10,11) adversarial/limits
trace; Pod D (3,4,15) drafting/records; Pod E (12,13,14)
brief/update. Three coder seats ran as delegated blind agents.
War room: 6 internal seats (R3 forced dissent) + 2 external
seats + 1 re-verification seat.

## Self-improvement delta
Two draft claims the coordinator believed (pickle loss,
test-pinning) were disproven by reviewers' empirical checks —
the cycle's lesson is recorded in the document itself: evidenced
by code/tests, never "pinned" by assertion. Scorecard:
Action+Guardrails evidence strengthened (recovery contract now
operator-readable); no capability % change claimed on a
documentation cycle.
