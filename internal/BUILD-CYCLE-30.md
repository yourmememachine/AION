# BUILD CYCLE 30 — wired pending is resume-only (sequential), pinned

**Summary (claim scope):** Cycle 30 closes the cycle-29 follow-up
"wired-pending-reachability" in its scoped form. Three blind coder
traces agree no fresh wired attempt can reach supersession-pending
in the sequential composition (beyond-head refuses exit 6 at
reconciliation; at-head exact pair recovers exit 0; rival hash
burns; genesis excluded from the supersede shape; the only seam
implies a retained pending entry — resume by definition). The new
test pins the previously unpinned resume half: a retained pending
(single-burn seed @5, real journaled decision bound to the retained
envelope, head moved strictly ahead @7) RE-PENDS on one wired
no-approval attempt, for the same envelope.

Baseline 1813 tests OK (skipped=28). Final: **1814 tests OK
(skipped=28)** — +1 test, test-harness only (CountingClient records
consumed authorisation ids; make_adopter gains wired=False default
with counting reconciliation providers). No production code
changed. Real state/state.json untouched (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
identical before/after). eval/ untouched.

## Fix round (R5)
- Counting providers assert reconciliation actually ran wired
  (both providers consulted ≥1) — the wired-specific pin.
- consumed_authorisation_ids == [retained envelope id] proves the
  single consume presented the retained envelope.
- Vacuous report_written assertion replaced: report file present
  with bytes unchanged (this branch does not rewrite it).

## Open follow-ups (carried)
- concurrent-actor interleaving: a second actor burning between
  reconciliation and consume could produce a genuine fresh pend —
  outside the sequential model; closing it needs a cross-process
  atomicity design. Separate open item, per all seats.
- Canonical cap-burn pending REFUSES wired resume (unexcused
  non-head cap entries) — retained pendings in general are not
  claimed to resume wired.
- _stop_at_pending re-pend branch and runner exit-7 / cycle-step
  exit-5 surfaces remain code-only.
- pin-store head anchoring; reconciliation repair for wholesale
  pin-directory loss; operator-authentication-channel; cycles
  17+18 recovery-contract document.

## Staffing
15 coders, 5 pods of 3: Pod A (1,5,8) runner trace; Pod B (2,6,7)
test inventory/design; Pod C (9,10,11) test construction; Pod D
(3,4,15) claims/records; Pod E (12,13,14) brief/update. Three coder
seats ran as delegated blind agents. War room: 6 internal seats
(R6 forced dissent) + 2 external seats — internal/REVIEW-CYCLE-30.md,
internal/CROSS-CHECK-30.md.

## Self-improvement delta
A two-cycle-old inference ("resume re-pends wired") is now either
pinned (single-burn decided shape) or explicitly disproven for the
canonical cap-burn shape — the follow-up closed by narrowing the
claim to what evidence supports, not by broadening the test.
Scorecard: Action+Guardrails evidence strengthened; no capability
% change claimed on a test-only cycle.
