# BUILD CYCLE 29 — wired at-sequence attempt: recovery, not pending

**Summary (claim scope):** Cycle 29 closes the cycle-28
fix-round follow-up "wired at-sequence pending composition
test" by correcting its premise. A failing-first probe
asserted the cycle-28 claim (an at-sequence candidate "can
still enter the supersession-pending flow") and failed:
the wired at-sequence attempt after a single head burn
LANDS as a burned_unadopted recovery, exit 0. The new test
pins that actual behaviour in the production composition
(trust/runner.py), and the cycle-28 claim is corrected by
appended pointers in the cycle-28 records, not rewrites.
Design: internal/cycle29-work/design-final.md. War room:
internal/REVIEW-CYCLE-29.md (6 internal seats, fix round,
R6 dissent carried as an open follow-up); external seats
SHIP (seat-gpt 0.94, seat-gemini 0.88) —
internal/CROSS-CHECK-29.md.

Baseline: cycle-28 tree at 1812 tests OK (skipped=28).
Final: **1813 tests OK (skipped=28)** — +1 new test in
tests/test_trust_runner.py, no production code changed,
no existing test logic modified (the sibling beyond-head
test's comment was corrected, assertions untouched).
Suite note: the first full run reported 1 failure whose
name was lost to output truncation; a second, uncontended
full run is clean (1813, 0 failures). The lost failure is
recorded here, not hidden; its pattern is consistent with
the load-related flakes recorded in cycle 28, but that
attribution is a judgement, not a proof. Real
state/state.json not advanced (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
identical before/after). eval/ untouched. No git commit in
this run — the parent verifies and commits.

## What was built

- tests/test_trust_runner.py:
  test_adopt_step_at_head_burn_sequence_recovers_is_exit_0.
  Shape: genesis adopt @13; hookless cycles to 15; one
  held-lock adopt burns 13->15 (exit 4, consumption 2, pin
  13); a plain wired adopt with the candidate at seq 15
  (the head burn's own sequence) exits 0, reanchored,
  record_reason burned_unadopted, pin_hash == head
  new_payload_hash; consumption 2->3 with the third entry
  pinned as consumption_kind recovery, recovery_depth 1,
  recovery_of == head authorisation_id, old/new 13/15;
  supersession ledger empty; no pending-supersession.json;
  pin history length 2; real state untouched.
- Claim correction in the sibling beyond-head test comment
  (CORRECTED in cycle 29) and appended correction pointers
  in internal/BUILD-CYCLE-28.md and
  internal/cycle28-work/fix-round-gpt.md.

## Why recovery is the intended behaviour (design basis)

The burned_unadopted recovery mechanism predates cycle 28:
a consumed-but-unadopted movement may be re-presented
identically and lands through a bounded, lineage-bound,
verifier-checked recovery (depth cap, recovery_of binding),
pinned by the crash/recovery suites. An exact-pair
at-sequence candidate is that mechanism's canonical input.
The head entry is not relevant to history reconciliation
at the exact pair (relevance at a sequence requires a
different hash), so the known-unadopted excuse is never
consulted and no supersession decision is needed. External
seat-gemini's condition — that this be intended design,
not a silent bypass — is met on that basis.

## Open follow-up (carried, not closed)

wired-pending-reachability (from R6's dissent): post-cycle-28,
no fresh wired shape is established that reaches the
supersession-pending stop — reconciliation refuses the
unaccounted beyond-head shapes the unwired pending flow was
built for, and the resume path re-pends without a fresh
verifier refusal. Whether a fresh wired attempt should be
able to reach pending (a reconciliation design change), or
pending is resume-only in the wired composition, is a
design question for a future war room. Also carried:
pin-store head anchoring, reconciliation repair procedure
for wholesale pin-directory loss,
operator-authentication-channel, cycles 17+18
recovery-contract document.

## Staffing

15 coders, 5 pods of 3: Pod A (1, 5, 8) shape/correctness
analysis; Pod B (2, 6, 7) reconciliation tracing; Pod C
(9, 10, 11) test construction; Pod D (3, 4, 15) claims and
records; Pod E (12, 13, 14) brief and pending update. Three
coder seats ran as delegated blind agents (correctness /
tests / adversarial) and their reconciliation re-scoped the
cycle before building. War room: 6 internal seats (R6
forced dissent) + 2 external seats, fix round applied and
re-verified.

## Self-improvement delta

A claim that had survived two review rounds ("at-sequence
can still enter pending") was killed by a failing-first
probe in the production composition, and the correction is
now pinned by a test that would go red if the behaviour
changed in either direction (pend or refuse). The war
room's dissent also produced a sharper open question —
wired pending reachability — stated as a design question
instead of being papered over as coverage.
Scorecard: Action+Guardrails evidence strengthened
(wired composition behaviour pinned at the boundary);
no capability % change claimed on a test-only cycle.
