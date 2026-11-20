# INTERNAL — War Room Record, Build Cycle 3 (do not publish)

Six reviewer seats, none of them authors of the code under review
(code authors of record: seat-3, seat-4, seat-15, Pod D). Blind pass
first: each seat probed the code independently and returned a verdict
and confidence before any discussion. Scores are locked in the
calibration log (subject "cycle-3-build"); dissent is preserved
below, not averaged away.

Reviewer seats: R1 seat-1 (Pod A), R2 seat-5 (Pod A, assigned
dissent), R3 seat-2 (Pod B), R4 seat-9 (Pod C), R5 seat-12 (Pod E),
R6 seat-6 (Pod B).

## Blind verdicts (as recorded, before fixes)
- R1 Registry Correctness — SHIP, 0.90. Verified metadata-only
  returns, freshness-guard behaviour inherited from the registry,
  retirement replay (old scorer 1.00 → 0.00), duplicate rejection.
  Minors: register/retire not atomic; stale domain after rotation;
  low-entropy seed brute-force not stated at the factory; no
  determinism pin; one gap test name overclaims its branch;
  count = MAX_BATCH untested.
- R2 Adversarial (dissent) — FIX, 0.30. Blockers as framed: anyone
  holding a seed regenerates the whole sealed batch including
  answers (B1); low-entropy families are guessable and parity is a
  coin flip (B2); the default retirement seed was derivable from
  the old seed (B3). Majors: seed has no strength floor and the
  registry's access log never sees factory regeneration (M1);
  cross-seed prompt collisions under identical ids (M2);
  retirement-seed predictability (M3). Minors: no batch provenance
  in the registry; the attempts cap can raise on legitimate large
  batches at high generations.
- R3 Gap Semantics — SHIP, 0.82. Majors: a sealed regression was
  masked by the public_only_gain reason label (M1); gap-flag
  boundary semantics differed from compare_gains without a stated
  rule (M2); a claimed NaN-threshold hole (M3 — NOT reproduced by
  the coordinator: NaN and infinite thresholds are rejected by the
  shipped isfinite check; pinned by a new regression test).
  Minors: gap_widened_by signedness undocumented; both-scores-fall
  case unlabelled.
- R4 Answer Correctness — SHIP, 0.97. 3,248 items across
  generations 0–14 independently re-solved, zero wrong answers;
  family windows and answer normalisation verified. Minors:
  prompt wording asymmetries across families; negative results
  are possible and worth a pinned test.
- R5 Integration/Tests — FIX, 0.86. Majors: a mid-batch failure
  leaves a half-registered / half-retired generation with no
  signal (F-a); metadata domain goes stale after rotation (F-b).
  Minors: determinism not pinned against runtime drift (F-c);
  factory sits inside the gate's protected scope — correct, but
  the implication belongs in this record (F-d); count boundary
  untested (F-e); exports untested through the package (F-f).
- R6 Honesty/Docs — SHIP, 0.86. Docstring claims verified almost
  everywhere. Findings: domain-after-rotation unstated (M-1);
  half-retirement unstated (M-2); gap threshold strictness and
  reason precedence unstated (m-3/m-4); retirement-seed
  predictability unstated (m-5); determinism claim unqualified
  across runtimes (m-6); seed-custody limit present but not
  pointed at brute-force of low-entropy seeds (m-7).

## Reconciliation of R2's blockers
B1/B2/M1 are real properties, but they are the accepted custody
model of the whole evaluation design, not a defect this cycle
introduced: the registry file itself stores sealed prompts and
answers readable by any same-user process (cycle 2, limit A9,
accepted and documented there). The factory is verifier-side only.
What cycle 3 owed — and had not paid — was stating this at the
factory itself, in full. Paid by fix F5 below. B3/M3 (derivable
retirement seed) WAS a new defect introduced this cycle and is
fixed in code (F2), not just documented. R2's dissent stands in
the calibration log and will be scored against the outcome.

## Reconciled fix list (one list, all applied)
- F1 (R5 F-a, R1, R6 M-2): register_batch and retire_generation
  pre-flight the whole batch before the first write (id clashes,
  missing retirement targets), so bad input fails with nothing
  written; the remaining mid-batch I/O failure window is stated
  plainly in the module docstring as an accepted residual.
  Regression tests: partial clash writes nothing; retiring an
  unregistered generation writes nothing.
- F2 (R2 B3/M3): retire_generation now requires an explicit
  new_seed, different from the retired seed; the derived default
  is removed. Tests updated and added.
- F3 (R3 M1, R6 m-4): assess_gap reason precedence — a sealed
  regression is never masked by another label; it takes the
  reason field first. New test: public gain + sealed drop reports
  sealed_regression while the gaming flag still fires.
- F4 (R5 F-c, R1, R6 m-6): determinism pinned — an exact
  prompt/answer pin for two batches fails the suite if the
  runtime stream ever drifts; the docstring claim is scoped to
  the same CPython runtime.
- F5 (R2 B1/B2/M1, R6 m-7, R1): seed custody stated in full in the
  module docstring — seed holder regenerates answers offline and
  unlogged, low-entropy seeds are brute-forceable, seeds must be
  high-entropy and verifier-held; batch identity is (seed,
  generation), one batch per generation per registry.
- F6 (R6 M-1/m-3, R5 F-b, R3 M2): rotation keeps the registered
  domain — now documented and pinned by a test; the gap threshold
  is documented as strictly-greater, with a boundary test at
  exactly the threshold; gap_widened_by documented as signed.
- F7 (R3 M3): not reproduced — NaN/inf thresholds were already
  rejected; a regression test now pins it.
- F8 (R1/R5 minors, R4 minors): count = 100 boundary test;
  pure gap_widened reason test (the older test's branch claim was
  wrong — it exercised public-only gain); package-export smoke
  test; negative-answer test for subtract-multiply.
- Noted for the record (R5 F-d): eval/factory.py is inside the
  gate's protected scope (eval/), so no self-change may touch it;
  team build cycles under the owner's direction are not
  self-changes. No code change.

## Verification round
Full suite after fixes: 156 tests, all passing. Coordinator
re-probed: pre-flight clash leaves the sealed set empty;
unregistered retirement leaves all content hashes unchanged;
sealed-regression precedence and threshold boundary behave as
pinned.

## Addendum — late-arriving full reports (same blind pass)
The complete R1/R3/R5 reports landed after the reconciliation
above; they reviewed the pre-fix code, and most of their findings
are the ones already fixed by F1–F8 (their probes confirm the
fixes were necessary). Three items were new, plus one blocker
in R5's full report that the summary pass had missed:

- F9 (R5 BLOCKER): tests/test_factory.py's answer-correctness
  test silently skipped the subtract-multiply and nth-word
  families (no fail on an unhandled family), so a wrong expected
  answer there would have passed the suite. R4's independent
  6,000-item verification (full report: 0 mismatches across all
  7 families, generations 0–14) proves no live wrong answer
  existed. Fixed: the test now covers all 7 families across
  generations 0–6 and fails on any unhandled family.
- F10 (R1/R3 full reports): retire_generation now verifies the
  supplied seed against the registered content hashes (a
  wrong-seed retirement previously rotated blind) and rejects a
  replacement item identical to the retired one; assess_gap now
  returns explicit sealed_regression / public_regression fields
  and its docstring states it is a gaming flag, not a gain gate
  (accept/reject belongs to compare_gains and the safety gate);
  the metadata content-hash enumeration leak for low-entropy
  families is now stated in the factory docstring.
- R2 full report (arrived last, pre-fix code): its blockers are
  the seed-custody properties reconciled above (seed holder
  regenerates the batch; brute-force rests on seed entropy;
  family composition visible via metadata domains and content
  hashes — the enumeration leak already noted under F10). Its
  M2 (a different seed's batch silently rotated under colliding
  ids) is closed by the F10 seed-match verification, proven by
  test_retire_with_wrong_seed_rejected_and_writes_nothing. Its
  assess_gap items are the ones addressed by F3/F10. No further
  code change; the dissent stands as recorded.
- Count corrections (honesty): the factory test file as built
  held 21 tests, not 25 as first written in BUILD-CYCLE-3.md;
  the pre-factory suite counts 125 by file (loop 36, registry
  39, gate 31, calibration 19), not the 119 carried over from
  cycle 2's record — that record undercounted the registry
  file. Final verified totals at cycle 3 close: factory 35,
  total 160 tests, all passing. The core-loop delta recorded
  this cycle (119 → 156) used the inherited figures; this
  addendum is the correction of record, the state entry itself
  is not rewritten.

## Verdict
RECONCILED — SHIP. No seat's blocker survives reconciliation:
R2's custody blockers are the documented, previously accepted
design limit, now stated at the factory too; its one new defect
(derivable retirement seed) is fixed in code. R5's majors are
fixed or documented with tests. Dissent preserved above and in
the calibration log.

## Calibration (X4 dogfood)
Blind scores locked for subject cycle-3-build: R1 0.90,
R2 0.30 (dissent role), R3 0.82, R4 0.97, R5 0.86, R6 0.86.
Discussion closed before the outcome was recorded; outcome
recorded after the ship decision (1.0 = shipped after fixes).
