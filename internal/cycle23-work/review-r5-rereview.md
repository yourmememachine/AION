# Cycle 23 — War-room RE-REVIEW, seat rev-r5

Re-review of my first-round findings (review-r5.md, FIX 0.78)
against the fix round (working tree, uncommitted).

**Verdict: SHIP — 0.90 — CONDITIONAL on F2 (see commit-time
conditions below).**

## F1 — pin_adoption.py honest-scope docstring: DISCHARGED

Read the full module docstring in `trust/pin_adoption.py`.
The stale cycle-22 "No live run" paragraph is gone. The
"Honest scope" paragraph now reads, in substance exactly as
my corrected wording required: production code exercised
end-to-end in temp dirs against the real verifier subprocess,
and, since cycle 23, in a live run against a byte copy of the
real state/ directory (seq 13 → 16, two consumptions) in a
sandbox under a production-mode verifier home; the real
state/ directory itself has never been adopted against and is
not advanced by any of this; there is no production deployment
(no separate OS user; the wrapper launch is refused by
design). I checked the rest of the docstring for contradiction:
the reason-selection and `already_current`/TTL paragraphs make
no live-run or one-shot claim, and nothing elsewhere in the
docstring contradicts the cycle-23 scope. Clean.

## F3 — check_head supersede narrowed + docstring rewritten:
## CODE DISCHARGED; ratification discharged CONDITIONALLY
## (record condition stated below)

Verified in `trust/ledger.py` (`check_head` docstring and
body), not just in the diff summary:

- Exact scope as documented and as coded: candidate strictly
  ahead of head (`cand_seq > head_seq`), old pin behind head
  (`old_seq < head_seq`), the recovery exception does not fire
  (the supersede branch sits inside `if not recovery ...`),
  and candidate at/behind the head with a behind-head old pin
  still raises `HeadRegressionError`.
- `burned_unadopted` excluded: an explicit guard before the
  old-pin block raises `HeadRegressionError` for a
  non-recovery `burned_unadopted` envelope whose candidate is
  ahead of the head (candidate at the head target already
  raises `AlreadyConsumedError`, behind already raises head
  regression above it), and a `burned_unadopted` envelope
  against an empty journal now also refuses rather than being
  reclassified. A mismatched recovery envelope therefore never
  rides supersede and is never reclassified as a primary —
  the exact discrepancy my first round flagged (docstring said
  "NON-recovery", code tested position only) is closed from
  both sides: code now tests the reason, docstring now states
  the enforced scope.
- Journal-known old-pin hash binding as coded: the code
  collects every hash recorded for the old pin's seq (entries'
  `new_cycle_seq`/`new_payload_hash` and
  `old_cycle_seq`/`old_payload_hash`) and refuses if the
  claimed old hash matches none of them. Docstring states
  this accurately.
- Both named residuals are in the docstring, verbatim in
  substance: (i) an old-pin seq not recorded in the journal
  cannot be hash-checked by the verifier (it cannot observe
  the pin); adoption-side context binding in `PinStore.adopt`
  is named as the control. (ii) A resurfaced superseded pair
  adopted later can stall one sequence at
  `AlreadyConsumedError` before self-healing via the next
  supersede (r2-F4), with the mechanism spelled out. "No
  regression and no replay in either residual" is claimed and,
  on my reading of the code, justified.

Ratification judgement: my first-round concern was that a
verifier-side head-rule relaxation load-bearing for scenario
6's liveness pin had been introduced by the fix seat with no
ruling behind it. The narrowing materially shrinks the rule
(it can no longer be ridden by the very envelope class —
mismatched `burned_unadopted` — that made the original form
unsafe to leave unruled, and journal-known old pins are now
hash-bound), and the docstring now argues the rule, its
justification, and its residuals in the open instead of
describing a narrower rule than the code enforces. On the
CODE state, the concern is discharged. What remains is
purely the record: the coordinator's commitment to record
supersede as a designed ruling in Addendum 3 /
BUILD-CYCLE-23 and to put it to the external seats as its
own brief question. Those records are written after this
re-review, so my SHIP is conditional on them landing as
specified in the commit-time conditions below — if the
ruling is recorded as designed (not as a mere fix-seat
patch) and the external-seat question is actually posed,
the ratification concern is fully discharged; if either is
dropped, F3 reopens.

## F4 — scenario 4 lost_pin assertion: DISCHARGED

`test_scenario4_candidate_side_file_loss_refuses_then_unfreezes`
in `tests/test_trust_pin_adoption_crash.py` now reads the
store history (previously discarded unread) and asserts
explicitly, with a fix-round comment citing r5-F4:
`assertNotIn("lost_pin", [r.reason for r in history])`,
alongside pin still at seq 2 and consumption count still 1,
before the unfreeze advance to seq 3. The R4 outcome is now
pinned by a quoted assertion, not only by inference from the
consumption count.

## F6 — deploy README recovery paragraph: DISCHARGED

`deploy/verifier-identity/README.md`, "Burned-but-unmoved
recovery" paragraph now continues past the cycle-21/22 text:
recovery is a BOUNDED chain, not one-shot; a failed recovery
may itself be recovered under `burned_unadopted`; lineage is
recorded in the schema-v2 journal (`recovery_of`,
`recovery_depth`) up to `MAX_RECOVERY_DEPTH = 2` (a movement
consumable at most three times: primary + two recoveries);
at the cap the movement is terminal (authorise refuses an
unproven recovery, consume refuses the target as already
consumed); liveness resumes at the next snapshot sequence
via a fresh primary `chain_gap_recovery`, via the supersede
head rule when the pin sits behind the consumed head. This
matches the code and the cap-2 claim discipline. No
overclaim spotted.

## F7 — trust/README adopter mention: DISCHARGED

`trust/README.md` sanctioned-paths list now carries a Pin
adoption bullet: `PinAdopter` as the production adopter
capturing the pin from `PinStore`, dense advance or ceremony
+ adopt through the store; integration via the
constructor-injected cycle hook
(`CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))`,
with `record_ship` / `run_one_cycle_and_pin` refusing a
hooked loop); and `trust.shipcheck.anchored_record_ship` as
the production recording path (caller-pin-free, expected
head derived from verified current anchors). The scope
sentence is kept exact — "this proves production MODE under
same-user spawn on one machine (live run against a byte copy
of the real state dir); it is not a production deployment" —
so the omission is fixed without overclaiming.

## F2 — Addendum 3 + BUILD-CYCLE-23: OPEN (records item)

Not yet written at re-review time, as expected: the
coordinator writes these before commit. Following the
cycle-22 precedent (rev-r6's conditional SHIP), my SHIP is
CONDITIONAL on both records landing in the same commit as
the code (conditions below). This is the only open item
from my first round.

## Tests re-run

`python3 -m unittest tests.test_trust_pin_adoption_crash`:
11 tests, OK (13.4 s) — scenarios 1 (both pair fates), 7, 2
(both), 3 (both), 4 (with the new lost_pin assertion), 5
(both), 6 all pass.

## Commit-time conditions (all records, no code)

My SHIP is conditional on the commit containing:

1. **Addendum 3** in `internal/DECISION-CONSUMPTION-HEAD.md`
   recording: schema-v2 lineage, cap
   `MAX_RECOVERY_DEPTH = 2`, issuance-bound `recovery_of`,
   supersession of Addendum 2's one-shot rule, the external
   ratification state honestly stated (split/pending), AND
   the `check_head` supersede rule recorded as a designed
   ruling with its narrowed scope and both named residuals —
   not merely as a fix-seat patch.
2. **BUILD-CYCLE-23** carrying the WS4 labelling discipline
   from my first round §2 (crash coverage claimed for
   scenarios 1 and 7 only; 2–4 as state surgery; 5–6 as
   recovery-semantics pins via the seam), the F5 caveat
   (scenario 7's loser pinned as `PinAdoptionRefused`, cause
   `PinStoreBusy` vs `PinMovedError` not distinguished), the
   scenario-6 terminal-refusal disjunction not quoted as
   pinning a specific refusal surface, and the live-run
   qualifiers (no non-test production entry point constructs
   a hooked loop; real state dir not advanced; production
   mode, not production deployment).
3. The supersede rule put to the external seats as its own
   brief question, with their answers reconciled in the
   record before the cycle's verdict is called final
   (provisional until then, per standing process).

If 1–3 land as specified, this SHIP stands unconditionally.
If any is dropped or silently weakened, treat this verdict
as FIX on F2/F3-records.

**SHIP — 0.90 (conditional, per above).**
