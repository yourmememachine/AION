# War-room review record — Cycle 22

Date: 2026-11-23. Subject: cycle-22 working tree (honest
recovery reason `burned_unadopted`; consumption-journal
anchoring; first production pin adopter). Build record:
BUILD-CYCLE-22.md. Design contract:
internal/cycle22-work/DESIGN-FINAL.md (R1–R4), plus the
fix-round rulings recorded below and in
internal/DECISION-CONSUMPTION-HEAD.md Addendum 2. Seat
notes: internal/cycle22-work/review-r{1..6}.md and
review-r{1..6}-rereview.md.

## Staffing

3 coder seats designed together (design-a/b/c +
cross-critiques; coordinator rulings R1–R4), then built
in disjoint file ownership. 6 reviewer seats from other
pods, blind scores locked in
state/calibration/calibration.json (subject
`cycle-22-review`) BEFORE reconciliation; one forced-
dissent seat (rev-r6). External seats seat-gpt /
seat-gemini: VACANT at internal close — the cycle verdict
is PROVISIONAL until they are seated on
CROSS-CHECK-BRIEF-CYCLE-22.md.

## Blind scores (locked)

| seat | verdict | score | headline |
|---|---|---|---|
| rev-r1 | SHIP | 0.88 | WS1 sound; race outcome specified but not test-pinned |
| rev-r2 | FIX | 0.89 | commit order + mutation verified independently; stale R10 wording in ledger/pin_ceremony docstrings |
| rev-r3 | FIX | 0.70 | pin store: adopt() binds nothing to the store's actual pin (splice); no prospective consistency check (self-brick) |
| rev-r4 | SHIP | 0.92 | adopter wiring, computed reason, mandatory cases all pass; three low nits |
| rev-r5 | FIX | 0.78 | wording only: R10 docstring, deploy README false passages, §8 claim wording incomplete |
| rev-r6 (dissent) | FIX | 0.70 | recovery exception self-perpetuating; window residual; adopter has no live caller; records not yet written |

## Fix round

All findings addressed (detail in BUILD-CYCLE-22.md):
pin-store context binding (expected_old_pin /
expected_new_pin) + prospective consistency check, with
mutation-checked regression tests for rev-r3's three
executed counterexamples; the one-shot recovery rule in
match_head_burn (rev-r6 F1), pinned at unit level and
end-to-end through the real verifier; the full wording
sweep (rev-r2 / rev-r5) with the external seats'
replacement wording carried in substance; adopter nits
(rev-r4 F1/F2/F4) and the exact test_05b count (rev-r6
F5); the two-recoveries race test-pinned in its tightened
form (rev-r1 F1).

Two coordinator rulings inside the fix round:

- **Genesis shape rule.** The pin-store fix first
  whitelisted genesis reasons (initial_anchor / lost_pin
  only). That dead-ends genesis recovery: a no-pin
  `burned_unadopted` record is precisely the recovery for
  a genesis burn whose adoption failed before the store
  file existed, and such a record can exist only if the
  verifier already proved and consumed the burn. Ruling:
  genesis admits any record whose old side is ABSENT and
  refuses any with-pin record — the defect rev-r3 proved
  (P1) was a shape violation, not a reason violation.
  rev-r3 upheld the ruling on re-review with independent
  probes.
- **One-shot supersession, stated explicitly.** The
  one-shot rule overrules two positions in this cycle's
  own design record: DESIGN-FINAL R1's iterated recovery
  chain (design-A §6.2) and §4.4.5's race outcome (both
  pre-authorised recoveries consume and land). Under
  one-shot, both race authorisations may be issued against
  the original burn; the first consumption lands; the
  second is refused AlreadyConsumedError. A recovery that
  itself burns unadopted is terminal for that movement;
  liveness resumes at the next snapshot sequence. The
  supersession is recorded in DECISION-CONSUMPTION-HEAD.md
  Addendum 2 and put to the external seats as a ruling to
  ratify.

## Re-review scores (subject `cycle-22-rereview`)

| seat | verdict | score |
|---|---|---|
| rev-r1 | SHIP | 0.92 |
| rev-r2 | SHIP | 0.96 |
| rev-r3 | SHIP | 0.96 |
| rev-r4 | SHIP | 0.97 |
| rev-r5 | SHIP | 0.96 |
| rev-r6 (dissent) | SHIP | 0.88 |

## Verdict

**SHIP (internal, reconciled unanimous) — PROVISIONAL**
on the external seats. Full suite at commit: 1547 tests
OK (skipped=28). Cycles 14–16 remain HELD: this verdict
does not release them; only external reconciliation on
CROSS-CHECK-BRIEF-CYCLE-22.md can do that.

## Dissent preserved — rev-r6 (forced dissent)

First round FIX 0.70. Its findings and dispositions:

- **F1 (HIGH) — self-perpetuating recovery exception.**
  CLOSED by the one-shot rule; rev-r6 ran six scratch
  break attempts against the fixed predicate (non-adjacent
  duplicate, re-burn after advance, genesis second
  recovery, foreign old pin, head-advanced race, stale
  recovery) — all refused.
- **F2 (HIGH) — mirror gap narrowed, not closed (the
  append→anchor window).** Accepted via the claim-
  downgrade branch: the window is disclosed as an
  unprotected residual in the code docstrings, the deploy
  README, the decision addendum, and the external brief;
  characterisation tests pin it as a characterisation, not
  a guarantee. Whether the narrowed claim closes item (3)
  is the external seats' judgement to make.
- **F3 (HIGH) — adopter has zero live callers; harness is
  research-mode.** Accepted via the claim-downgrade
  branch: the claim everywhere is "first production
  adopter built and wired as specified"; no live run
  against `state/state.json` is claimed, and the brief
  puts the point to the external seats explicitly.
- **F4 (MEDIUM) — burn proof scope.** Step (5b) validation
  verified (no unproven-label path found). Carried minors,
  non-blocking, recorded as open: F4.1 — offline
  `verify_ceremony_record` proves issuance/shape, not a
  burn (documented at the function); F4.2 — adopter
  recovery liveness depends on its unanchored local
  pending journal.
- **F5 (MEDIUM) — WS3 deviations.** Judged caches, not
  bypasses (retained envelopes re-verified every attempt);
  the weakened test_05b assertion is now an exact count.
- **F6 (MEDIUM) — records/verifiability.** Discharged at
  commit time: BUILD-CYCLE-22.md (with the full-suite
  total and the R2 mutation result), this record, and
  CROSS-CHECK-BRIEF-CYCLE-22.md all land in the cycle-22
  commit, the brief carrying the window residual, the
  no-live-run adopter wording, and the one-shot
  supersession. rev-r6's re-review SHIP is expressly
  conditional on that landing, and this record notes the
  condition is met by the commit that contains it.
- **F7 (LOW/clean) — diff hygiene.** Confirmed: all files
  in R1–R3 scope, eval/ untouched, allowlist 17→19
  consistent.

rev-r6 re-review position (SHIP 0.88): "F1 one-shot:
FIXED and unbroken… F2/F3: accepted via the downgrade
branch… One commit-time requirement held: [the three
records] — my SHIP covers the commit only if all three
land in it… Cycles 14–16 remain gated on external
reconciliation — this internal SHIP does not release
them."
