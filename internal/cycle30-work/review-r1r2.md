# Cycle 30 — war-room review, seats R1 (correctness) and R2 (tests)

Blind review. Sources: `internal/CROSS-CHECK-BRIEF-CYCLE-30.md`,
`internal/cycle30-work/design-final.md`, `coder-a-trace.md`,
`coder-b-tests.md`, `coder-c-adversarial.md`, the diff to
`tests/test_trust_supersede_adopter.py` (new
`test_wired_resume_repends_after_head_moves_ahead` + optional
`wired=False` kwarg on `make_adopter`), and the production code
paths the test exercises (`trust/pin_adoption.py`,
`trust/history_reconciliation.py`, `trust/runner.py`).
Independently re-ran the new test standalone: passes (unittest,
2.2s). No production code changed in this cycle — confirmed by
the diff (test file only, +100/−2).

---

## R1 — correctness

**Verdict: SHIP — score 0.88**

### What checks out

1. **The mechanism the test claims to exercise is the mechanism
   that actually runs.** Trace of the final wired attempt:
   `snapshot_and_adopt` step 3b reconciliation runs before
   `_reanchor`'s resume intercept. Reconciliation disposition
   per entry, candidate (5, candidate hash):
   - genesis @1 — relevant (`1 < 5`), pair-covered by the store
     history;
   - abandoned burn @3 — relevant (`3 < 5`), not pair-covered,
     excused only by `_supersede_excused`'s candidate-pair
     branch: the journaled decision's `abandoned_authorisation_id`
     matches the @3 entry and its candidate pair equals the
     candidate under attempt (verified against
     `history_reconciliation.py` `_supersede_excused`);
   - mover @7 — not relevant (`7` is neither `< 5` nor `== 5`),
     so moving the head strictly ahead introduces no new
     refusal, exactly as designed.
   The resume intercept then matches the retained pending
   (same candidate seq+hash + old pin), the `supersede_decided`
   phase routes `_resume_pending` consume-first with
   `pre_commit_fallthrough=True`, the single consume refuses
   pre-commit against head @7 (candidate behind head), falls
   through to the approval lookup in the same attempt, finds
   none, and re-raises `PinSupersessionPendingApproval` for the
   retained envelope. Every asserted count maps to this trace:
   authorise 0 (no fresh ceremony), supersede 0 (no new
   decision), consume 1 (the pre-commit refusal), consumptions
   3 and supersessions 1 unchanged, pin @1.
2. **The wired forwarding is faithful to production.** The
   `wired=True` branch builds both providers via
   `consumption_entries_provider_from_home` /
   `supersession_entries_provider_from_home` on
   `self.home / "ledger"` — the same provider constructors and
   the same ledger-home convention the runner's
   `_history_providers` uses. It is not a stub or a hand-rolled
   provider. Default `wired=False` leaves every existing caller
   byte-equivalent in behaviour.
3. **The seeded state is a legitimate retained-pending state,
   with one scoping condition (below).** The pend itself is
   produced by the real flow, not constructed: genesis, one
   genuine burn (pair discarded), state @5, one unwired attempt
   raising pending — the single-burn premise coder B flagged
   for failing-first verification is exercised and asserted
   (`candidate_seq == 5`, consumptions == 2) before any seeding.
   The decision is a real verifier decision
   (`client2.ceremony_supersede` against a real approver-minted
   artefact bound to the retained envelope), not a fabricated
   ledger entry. The hand-appended `supersede_decided` journal
   line simulates "earlier attempt journaled the decision then
   died before consume" — this is the established F1 precedent
   in the same suite (`test_supersede_decided_entry_resumes_…`
   uses the identical construction), and the line is a
   detection aid the code reads, not authority the test forges.
4. **Head-mover construction is sound.** The @7 entry is
   consumed directly at client level with its old pin bound to
   the then-head pair (@3) — the same concurrent-actor mover
   pattern as the existing `_consume_fresh_envelope_at_head`,
   generalised to a sequence strictly ahead of the candidate
   instead of at it (the at-sequence variant would be a
   relevant fork and would refuse, per coder B §4). It does not
   touch the pin store, so pin @1 throughout is coherent.

### Findings (none blocking)

- **R1-F1 (claim wording, minor).** The justified claim is the
  conditional one in `design-final.md`: *fresh* wired attempts
  cannot reach pending (pinned in cycles 28–29), and a retained
  pending in this reconciliation-clean, decided state re-pends
  on a wired resume. The test does **not** show — and coder C
  §2e shows cannot be shown — that such a pending state arises
  inside a composition wired from genesis; the seed pend here
  was created unwired. The cycle record must close the
  follow-up in the conditional form ("resume-only, given a
  retained pending"), not the unscoped slogan. The brief and
  design-final already use the scoped form; keep it that way
  in the build record.
- **R1-F2 (concurrent-actor residual does not block).** Coder
  C's §6 interleaving (external burn between reconciliation
  and consume) is outside the sequential model the follow-up
  asked about, the pend it produces is the designed safe stop
  rather than a silent landing or burn, and closing it needs
  cross-process atomicity — a separate design change. Record
  it as its own open item; do not hold cycle 30 or the
  follow-up closure on it.
- **R1-F3 (scope honesty confirmed).** The design's stated
  non-coverage is accurate: this pins only the consume-first
  fall-through re-raise. The `_stop_at_pending` re-pend inside
  `_consume_retained` and the runner exit-7 / cycle-step
  exit-5 surfaces remain code-only, and nothing in the test
  or brief overclaims them.

---

## R2 — tests

**Verdict: SHIP — score 0.85**

### Assertion-by-assertion

No assertion is vacuous, and the discriminating set is strong:

- `assertRaises(PinSupersessionPendingApproval)` on the wired
  attempt discriminates against the two failure modes that
  matter: reconciliation refusal would raise
  `HistoryReconciliationRefused`, and a burn/landing would
  raise `PinAdoptionBurned` / return a result.
- `repend.authorisation_id == pending.authorisation_id` plus
  `candidate_seq == 5` pins "same retained envelope" — a fresh
  pend at the same sequence would carry a new authorisation id
  and fail this.
- `consume_calls == 1` is the sharpest assertion in the test:
  it distinguishes the consume-first fall-through branch from
  the plain no-approval re-raise in `_resume_pending`, which
  consumes 0 times (cf. the second attempt in
  `test_deadlock_stops_at_pending_without_approval`, asserted
  0/0/0). If the decided short-circuit regressed to a direct
  re-raise, this test goes red.
- `authorise_calls == 0` / `supersede_calls == 0` kill the
  fresh-ceremony and new-decision escapes respectively.
- Count invariants (consumptions stay 3, supersessions stay 1,
  pin stays @1) kill landing and double-decision regressions.
- Setup is asserted, not assumed: burn head @3, consumptions
  == 2 after the seed pend, supersessions == 1 after the real
  decision, head `new_cycle_seq == 7` and consumptions == 3
  after the mover. If the single-burn premise were false the
  seed `assertRaises` fails loudly at step 0, as coder B
  required — the test does not silently fall back to the cap
  burn (which coder B showed would refuse wired resume).

### Findings (none blocking)

- **R2-F1 (`report_written` is weak, minor).** On this branch
  `_resume_pending` sets `report_written =
  pending_report_path.is_file()` — the report file is the one
  written by the original unwired `_stop_at_pending`, retained
  on disk, not rewritten by the wired attempt. So
  `assertTrue(repend.report_written)` proves presence, not
  re-writing, and would pass even if the fall-through path
  never touched the report. The brief's phrasing "pending
  report still written" overstates it slightly; "still
  present" is the accurate claim. Non-blocking: report
  presence is the operator-visible contract on a re-raise,
  and coder B §3.3 already documented this re-raise/re-stop
  distinction. Recommend the build record use the "still
  present" wording.
- **R2-F2 (wired-ness is exercised but not isolated, minor).**
  For this particular shape the wired and unwired resumes
  converge on identical observable outcomes, so deleting the
  `wired=True` argument would not turn this test red — its
  regression sensitivity is to the reconciliation logic (a
  break in the candidate-pair excuse or relevance rule turns
  it red via `HistoryReconciliationRefused`), not to the
  fixture flag itself. That is acceptable for a positive-path
  pin at this scope and matches the cycle-28 wired-adopter
  precedent, but a future negative control (e.g. the same
  resume with the decision removed, asserting wired refusal)
  would close the gap. Follow-up, not a fix for this cycle.
- **R2-F3 (small omissions, informational).** The re-pend's
  `candidate_hash` / `old_cycle_seq` are not asserted;
  `authorisation_id` equality already binds the envelope, so
  this costs no discriminating power. No full-suite result is
  recorded yet (the brief defers it to after review) — the
  ship record must carry it; the new test passes standalone
  as verified by this seat.

### Residual question from the brief

Should the concurrent-actor residual block closing the
follow-up? **No** (agreeing with R1-F2): it is outside the
sequential wired model, produces the designed pending stop,
and needs a separate atomicity design. Close
`wired-pending-reachability` in the conditional form, with
the interleaving carried as a distinct open item.

---

## Reconciliation (R1 + R2)

Both seats SHIP independently, no FIX verdicts, no split.
Non-blocking notes for the build record: use the conditional
claim wording (R1-F1), say "report still present" not "still
written" (R2-F1), carry the concurrent-actor interleaving as
a separate open item (R1-F2), and record the full-suite total
when run (R2-F3).
