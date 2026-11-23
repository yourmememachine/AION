# War-room review record — Cycle 21

Date: 2026-11-23. Subject: cycle-21 working tree
(Ed25519 differential validation + seed hygiene;
verifier-owned monotonic consumption head). Build record:
BUILD-CYCLE-21.md. Design contract and reconciliation
rulings: internal/cycle21-work/DESIGN-FINAL.md (incl. its
post-review addendum). Seat notes:
internal/cycle21-work/review-r{1..6}.md and
review-r{1..6}-rereview.md.

## Staffing

3 coder seats designed together (design-a/b/c +
cross-critiques; coordinator rulings R1–R12), then built
in disjoint file ownership. 6 reviewer seats from other
pods, blind scores locked in
state/calibration/calibration.json (subject
`cycle-21-review`) BEFORE reconciliation; one forced-
dissent seat (rev-r6). External seats seat-gpt /
seat-gemini: VACANT at internal close — the cycle verdict
is PROVISIONAL until they are seated on
CROSS-CHECK-BRIEF-CYCLE-21.md.

## Blind scores (locked)

| seat | verdict | score | headline |
|---|---|---|---|
| rev-r1 | FIX | 0.87 | crash/race test traceability; deploy README |
| rev-r2 | SHIP | 0.93 | setuid/sticky predicate; openssl probe; message-flip |
| rev-r3 | FIX | 0.78 | HIGH-1 stderr oracle at the consume mode; head() trap |
| rev-r4 | SHIP | 0.90 | spy coverage gaps |
| rev-r5 | FIX | 0.80 | wording only — stale text, residual labelling |
| rev-r6 (dissent) | FIX | 0.58 | claim gate: F1–F7 (below) |

## Fix round

All code findings closed (detail in BUILD-CYCLE-21.md):
the stderr oracle (rev-r3 HIGH-1) — verification-failure
classes are now byte-identical on stdout AND stderr with
a single refusal code; head() → head_target() +
polymorphic contract test; forced-interleave race and
post-mirror kill-point tests; README and docstring
narrowing incl. numeric liveness figures; predicate
tightening; capability probe; stale-text cleanups.
One ratified deviation: rev-r1 LOW-1 — R9 relation (7)
read both ways (adds refusals only, disclosed in a code
comment, carries its own test). Recorded interpretations
(no code): temporal verify reasons map to
`ceremony_authorisation_expired`, all others to
`ceremony_authorisation_invalid`; consumption retry
exhaustion surfaces `ledger_failed` (issuance precedent);
rev-r2's independent openssl re-probe discharges rev-r6
flip condition (6) in substance.

## Re-review scores (subject `cycle-21-rereview`)

| seat | verdict | score |
|---|---|---|
| rev-r1 | SHIP | 0.94 |
| rev-r2 | SHIP | 0.95 |
| rev-r3 | SHIP | 0.92 |
| rev-r4 | SHIP | 0.92 |
| rev-r5 | SHIP | 0.94 |
| rev-r6 (dissent) | FIX (narrowed) | 0.72 |

## Verdict

**SHIP (internal, reconciled) — PROVISIONAL** on the
external seats, and subject to rev-r6's claim gate below:
item (3) is not described as closed, and cycles 14–16
re-review does not start, until seat-gpt and seat-gemini
accept the scoping. Full suite at commit: 1472 tests OK
(skipped=28).

## Dissent preserved — rev-r6 (forced dissent), re-review position

rev-r6 narrows but does NOT flip: "The dissent NARROWS
but STANDS. It does not flip to SHIP… What remains is not
code polish: condition (3) is unbuilt by admission,
condition (1) is unmet by construction, and condition (4)
is a pre-commitment about documents that do not exist
yet… A named follow-up is a promise, not a path."

Its findings and dispositions:

- **F1 — no production caller of reanchor_pin exists.**
  NOT closable by code inside this cycle's scope. The
  claim is scoped instead: the integrated path is built
  and exercised end-to-end in tests; the guarantee binds
  the first adopter that wires as specified. Put to the
  external seats explicitly.
- **F2 — head() trap.** CLOSED, verified independently by
  rev-r6 (rename + polymorphic contract test run by the
  seat itself: 32-test consume suite OK).
- **F3 — qualifiers must travel with every item-(3)
  summary.** Discharged in the records: the qualifier
  wording is carried in substance in the headline of
  BUILD-CYCLE-21.md and of the external brief, and the
  DECISION-CONSUMPTION-HEAD.md "Why" sentence was amended
  so the intact-home / unanchored-journal qualifier is
  part of the sentence's claim.
- **F4 — burned-but-unmoved recovery requires the
  lost_pin label.** NOT built; named follow-up
  `burned-but-unmoved-recovery-reason` (the reason grammar
  is shared with issuance and is not changed inside a fix
  round). Acceptable as a deferral ONLY under provisional
  status; put to the external seats as an open item.
- **F5 / condition (6) — non-builder re-probe of the
  openssl pairs.** MET IN SUBSTANCE: rev-r2's independent
  full-table re-probe (51 rows, zero mismatches) is
  recorded in review-r2.md. Literal caveat preserved: the
  recording lives in the review record, not the test
  file; rev-r6 accepts the review record as equivalent
  provenance.
- **F6 — dependency on provisional cycle-17/18
  behaviour.** Recorded: rev-r6 itself found no cycle-21
  dependency on it; the dependency runs the other way.
- **F7 — liveness figures.** MET: the mode docstring
  states the figures numerically (900 s TTL cap, two
  verifier-availability windows, per-failure burn cost);
  BUILD-CYCLE-21.md repeats them in numeric form.

rev-r6's flip conditions (verbatim substance): "(1)
Seat-gpt and seat-gemini see cycle 21 with the R5 claim
wording, the R10 residual, and F4 as an open item, and
accept them as discharging CROSS-CHECK-14 item (3) —
including explicit acceptance of the F4 deferral, or
`burned-but-unmoved-recovery-reason` lands and is tested
end-to-end. (2) The brief headline and BUILD-CYCLE-21.md
carry the (4) wording in substance, the liveness figures
in numeric form, and the DECISION-CONSUMPTION-HEAD.md
'Why' sentence is amended with the intact-home qualifier.
(3) Until 1 and 2: the internal record stays PROVISIONAL,
item (3) is not described as closed, and 14–16 re-review
does not start. Meet 1–2 and this seat flips to SHIP
without a further code round."

Condition (2) is discharged by this record set.
Condition (1) is the external seats' to give.
