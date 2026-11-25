# Cycle 30 — Coder B (tests): pending-supersession reachability

Scope: analysis only. Sources: `tests/test_trust_runner.py` (the wired,
subprocess, production-composition suite), the pending-supersession suites
`tests/test_trust_supersede_adopter.py`,
`tests/test_trust_ceremony_supersede.py`,
`tests/test_trust_supersession_approval.py`,
`tests/test_cycle28_history_reconciliation.py`, and the code they exercise
(`trust/runner.py`, `trust/pin_adoption.py`, `trust/history_reconciliation.py`,
`trust/ledger.py`). No production or test code was changed.

## 1. Wired shapes that exist for "pending" in `test_trust_runner.py`

"Wired" = `python3 -m trust.runner` as a subprocess, byte copy of real
`state/`, production home from `tests/cycle23_harness.py`. The runner always
supplies the cycle-28 history-reconciliation providers
(`trust/runner.py` `_history_providers` → `build_pin_adopter(...,
consumption_entries_provider=…, supersession_entries_provider=…)`) and
never sets `AION_PIN_SUPERSESSION_APPROVAL_PATH` (`RunnerTests.base_env`),
so in this composition the approval inbox is `None`.

**No wired test reaches pending.** There is no test asserting exit 7, no
test asserting an adopt-step line with `outcome == "supersession_pending"`,
and no test asserting a cycle-step exit 5 with
`adoption_error == "PinSupersessionPendingApproval"`. The exit-7 branch
exists in code only (`trust/runner.py`, `PinSupersessionPendingApproval`
handler → line `supersession_pending`, `return 7`; cycle-step variant →
exit 5, same outcome family as a burn).

Every runner test, by shape:

| Test | Shape | Exit / outcome |
|---|---|---|
| `test_runner_replays_cycle23_live_run_shape` | genesis adopt @13, hooked cycle @14, gap, adopt → `chain_gap_recovery` @16, adopt → `already_current` | 0 |
| `test_adopt_step_refused_is_exit_3` | corrupt pin-store file, adopt | 3 `adoption_refused`, 0 consumptions |
| `test_adopt_step_burned_is_exit_4` | pin lock held, adopt (genesis ceremony consumes, `PinStore.adopt` fails) | 4 `adoption_burned`, 1 consumption, no pin |
| `test_cycle_step_hook_burn_is_exit_5_cycle_recorded` | pin lock held, cycle step | 5 `cycle_recorded_pin_pending`, `adoption_error=PinAdoptionBurned` — note: this is the only "pin pending" *wording* in the suite, and it is a burn, not supersession pending |
| `test_adopt_step_beyond_head_burn_refuses_incomplete_is_exit_6` | genesis @13, hookless to 15, held-lock burn 13→15, hookless to 16, adopt (candidate 16, strictly **beyond** head burn @15) | 6 `step_refused` / `HistoryReconciliationRefused`, consumptions stay 2, **supersession ledger asserted empty**, pin stays 13 |
| `test_adopt_step_at_head_burn_sequence_recovers_is_exit_0` | genesis @13, hookless to 15, held-lock burn 13→15, adopt (candidate 15, **at** head burn's own seq, exact pair) | 0 `reanchored` / `burned_unadopted`, recovery consume depth 1, `recovery_of` = head id, **supersession ledger empty and `pending-supersession.json` asserted absent** |
| `test_idle_cycle_step_is_exit_0` | backlog exhausted, cycle step | 0 `idle` |
| negatives (huge-int delta, missing/malformed ceremony key hex, missing `state.json`, malformed plan, split verdict, extra argv) | plan/config layer | 2 or 6, no pending involvement |

So the two shapes that were ever *expected* to pend are now pinned to the
two non-pending outcomes, and both pin the **absence** of pending
(empty supersession ledger; no report file in the at-head case).

## 2. Pending shapes that exist elsewhere — all unwired

- `tests/test_trust_supersede_adopter.py` — the full pending flow, direct
  in-process `PinAdopter` with **no reconciliation providers**
  (`make_adopter` passes no provider kwargs; default `None` = pre-cycle-28
  behaviour). `drive_to_pending()`: genesis @1, movement to @3 consumed to
  its recovery cap (primary + depth 1 + depth 2, every pair discarded),
  state to @5, one attempt → `PinSupersessionPendingApproval`
  (candidate 5, old 1, 1 consume attempt, 0 supersede calls, pending-journal
  `supersession_pending_approval` line, `pending-supersession/1` report).
  Re-pend is pinned there: a second no-approval attempt raises pending
  again with `authorise_calls == consume_calls == supersede_calls == 0`
  (`test_deadlock_stops_at_pending_without_approval`). Also pinned unwired:
  approved resume lands @5; ambiguous-decision and `supersede_decided`
  consume-first resumes land; head-move-after-decision re-pends twice and
  then completes @7 (`test_head_move_after_decision_…`); lost-consume-response
  resume converts to a genuine burn and recovers; wrong-binding approval is
  never presented; decision failure is burned, not retried.
- `tests/test_cycle28_history_reconciliation.py::test_17_no_provider_old_behaviour`
  — the other fresh-pending shape, also unwired by construction: restored
  store (genesis @1, gap @3 adopted, store restored to genesis generation,
  state @4) → unwired adopter pends. Its own comment calls the missing
  history signal "the hole test_16's wired refusal closes" — i.e. the wired
  twin of this exact shape is `test_16`, which **refuses**.
- `tests/test_trust_ceremony_supersede.py` and
  `tests/test_trust_supersession_approval.py` — verifier-ledger and
  approval-tool levels respectively (decision append/binding; artefact
  minted against a `pending-supersession/1` report file). Neither drives
  an adopter to the pending stop; neither is wired.
- Wired adopter-level pending-adjacent pins in the cycle-28 suite are all
  refusals or unit excuses, never a pending outcome: `test_16` / `test_22` /
  `test_23` / `test_24` (wired restored/compound shapes →
  `HistoryReconciliationRefused`, `pin_store_history_incomplete`),
  `test_09` / `test_10` (pure-function known-unadopted-head excuse, at-seq
  only, narrowed by the cycle-28 fix round), `test_19` / `test_20`
  (pure-function supersession excuse: bound decision whose candidate pair
  is the candidate under attempt, or whose new side has landed).

## 3. Is the "resume-only" claim supported?

Claim (from `internal/BUILD-CYCLE-29.md`, carried as the open follow-up
`wired-pending-reachability`, and stated in the beyond-head/at-head test
comments in `test_trust_runner.py`): post-cycle-28, no fresh wired shape
reaches the supersession-pending stop; pending in the wired composition
is reached only by the resume path re-pending.

**Supported — as a statement about fresh attempts, by pinned tests:**

1. Beyond-head fresh → exit 6, refused by reconciliation *before* any
   ceremony (runner test above; cycle-28 `test_09`/`test_10` pin the
   narrowed excuse at the function level: known-unadopted excuse is
   head-only **and** at-sequence-only since the seat-gpt FIX 0.91 round).
2. At-head fresh (exact pair) → exit 0 `burned_unadopted` recovery; the
   head entry is not even relevant to reconciliation (relevance at a
   sequence requires a different hash), the excuse is never consulted,
   and no decision is requested. Failing-first record:
   `internal/cycle29-work/failing-first.md` (probe expected 7, got 0).
3. Code order confirms there is no other fresh door: in
   `PinAdopter.snapshot_and_adopt`, reconciliation is step (3b), before
   classification and before `_reanchor`; the only fresh route to
   `_stop_at_pending` is `_reanchor`'s fresh ceremony receiving
   `CeremonySupersedeRequired`, which requires passing (3b) first.

**Not supported — as a statement that wired resume demonstrably re-pends:**

1. **No wired test exercises the resume path at all.** The re-pend
   behaviour is pinned only unwired (§2). BUILD-CYCLE-29's sentence
   "the resume path re-pends without a fresh verifier refusal" is a
   code-reading inference, not wired evidence.
2. **Resume is not a reconciliation bypass.** `_reanchor` intercepts a
   retained pending (`_find_pending_supersession`: exact candidate
   seq+hash + old pin, `supersession_pending_approval` phase present, no
   `adopted`/`consumed` phase) only *after* step (3b). A retained pending
   whose abandoned head entry is unexcused is refused
   (`HistoryReconciliationRefused`, runner exit 6) before the intercept
   is consulted. Concretely, the canonical unwired pending — the
   cap-burn deadlock — does **not** survive wired resume: its three
   consumption entries (primary/depth-1/depth-2, same pair, distinct
   authorisation ids, all `new_seq < candidate_seq`) are each relevant;
   a supersession decision excuses only the one entry whose id it
   abandons (the head), and the known-unadopted excuse reaches only the
   head entry at its own sequence. The other two entries flag.
3. **"Re-pend" on the no-approval resume branch is a re-raise, not a
   re-stop.** `_resume_pending` with no matching inbox approval raises
   `PinSupersessionPendingApproval` directly (`journal_persisted=True`
   hardcoded, `report_written = pending_report_path.is_file()`); it does
   not call `_stop_at_pending`, appends no journal line, and does not
   rewrite the report. The `_stop_at_pending` re-pend (new journal line +
   rewritten report) occurs only inside `_consume_retained`
   (`pre_commit_fallthrough=False`) on a pre-commit refusal
   (`CeremonySupersedeRequired` / `CeremonyHeadRegression`).
4. The cycle-step pending surface (runner exit 5 with
   `adoption_error == "PinSupersessionPendingApproval"`) is likewise
   code-only; no wired test covers it in either direction.

Net: "fresh cannot reach pending (wired)" — **pinned**. "Pending is
resume-only (wired)" — **plausible and consistent with the code, but
unpinned, and true only conditionally**: a wired resume re-pends only
from a reconciliation-clean retained state (see §4 for the one such
state the current rules admit).

## 4. Minimal test pinning resume-only re-pend

### Why the naive seedings fail (design constraints the test must respect)

- Seed via cap-burn `drive_to_pending` → wired resume refuses at (3b)
  on the two non-head cap entries (§3.2). Do not use it.
- Seed via restored-store (cycle-28 `test_17` shape) → abandoned entry
  is an *adopted* record's disappearance; wired twin already refuses
  (`test_22`–`test_24` family). Do not use it.
- The admitted shape needs **exactly one** uncovered relevant entry —
  the abandoned head — plus a **journaled supersession decision bound
  to the retained envelope**, because the decision is the only excuse
  that covers a beyond-head abandoned entry, and only via the
  candidate-pair branch (`test_19`: decision's candidate pair ==
  candidate under attempt). A single (non-cap) burn suffices for the
  fresh unwired pend: `supersede_head` (`trust/ledger.py`) requires only
  candidate strictly ahead of head, old pin behind head, hash binding —
  no cap condition. (Supported indirectly by `test_17`'s single-entry
  pend; still verify failing-first, step 0 below.)
- The re-pend trigger must not introduce a new unexcused relevant
  entry: move the head with a client-consumed envelope whose candidate
  sequence is **strictly ahead of** the pending candidate. Entries
  ahead of the candidate are never relevant (`test_11`), whatever
  their hash, and a client-level consume needs no adopter-journal
  entry. (The existing `_consume_fresh_envelope_at_head` mover in
  `test_trust_supersede_adopter.py` uses candidate seq == pending
  seq with a different hash — that *is* relevant as a fork and would
  refuse at (3b) in the wired composition; do not copy it as-is.)

### The test (wired-adopter level — minimal home)

Place it in `tests/test_trust_supersede_adopter.py` (the only fixture
with an approver-configured client, `client2`, and the decision-seeding
precedents), adding one constructor change: `make_adopter` gains
optional `consumption_entries_provider` /
`supersession_entries_provider` kwargs forwarded to `PinAdopter`,
built from the fixture's verifier home exactly as
`AdopterReconciliationFixture._wired_adopter` does in the cycle-28
suite. A runner-subprocess version is the same seeding transplanted
into `RunnerTests` plus a final `run_runner([{"adopt": True}])`
asserting exit 7 — strictly more machinery (in-process adopter/client
against a production home), so it is the stretch version, not the
minimal pin.

Steps (fixture seqs: pin @1, head @3, candidate @5):

0. Failing-first premise check: genesis; **one** `burn_once()`
   (movement 1→3, pair discarded — not `burn_movement_to_cap`);
   state to @5; unwired attempt raises
   `PinSupersessionPendingApproval`. If this instead lands or burns,
   the single-burn premise is false and the test stops here as a
   recorded negative — do not silently revert to the cap burn.
1. Seed the decided state (precedent:
   `test_supersede_decided_entry_resumes_consume_first_no_approval`):
   mint the approval into the inbox from the pending report
   (`mint_approval_into_inbox`), obtain the real decision via
   `client2.ceremony_supersede(OPERATOR, pending.envelope_dict,
   artefact)`, append the `supersede_decided` journal line via
   `adopter._append_journal({...})`, delete the inbox artefact
   (presented/spent). Assert supersession ledger == 1,
   consumptions == 2 (genesis + the single burn).
2. Move the head past the candidate (generalise
   `_consume_fresh_envelope_at_head` to candidate seq 7, hash
   `"d"*64`, old pin = current head pair @3): consume it directly
   via `self.client`. Assert consumptions == 3, head `new_cycle_seq`
   == 7, pin still @1, state still @5.
3. The pin — one wired attempt, no approval anywhere:
   `CountingClient(self.client2)` + wired `make_adopter(...)`;
   `snapshot_and_adopt()` raises `PinSupersessionPendingApproval`.

Expected assertions in step 3 (each one kills a different escape):

- `pending.candidate_seq == 5`, `pending.authorisation_id` ==
  retained envelope's id (the re-pend is for the *same* movement);
- `counting.authorise_calls == 0` and `counting.supersede_calls == 0`
  (no fresh ceremony, no new decision request — this is what makes
  it *resume*-only evidence, paired with §1's fresh-shape pins);
- consumptions still == 3 and supersession ledger still == 1
  (the consume-first attempt refused pre-commit against head @7 —
  candidate behind head — and consumed nothing; if a future change
  makes it land or burn, this test goes red);
- pin still @1; `pending-supersession.json` still present
  (`report_written` true on the raised exception).

Why it re-pends, mechanically: (3b) passes because genesis is
pair-covered, the abandoned @3 entry is supersession-excused by the
step-1 decision whose candidate pair is exactly (5, candidate hash)
(`test_19` branch), and the @7 mover is ahead of the candidate and
irrelevant (`test_11`). `_reanchor` then finds the retained pending;
`_resume_pending` runs consume-first (`supersede_decided` present),
the single consume refuses pre-commit, falls through to the approval
lookup in the same attempt, finds none, and re-raises pending —
the exact branch BUILD-CYCLE-29 asserted but no wired test has run.

Scope note for the record: this pins **one** re-pend branch
(consume-first fall-through → no-approval re-raise). It does not pin
the `_stop_at_pending` re-pend inside `_consume_retained`, nor the
runner exit-7 / cycle-step exit-5 surfaces; those remain code-only
until a runner-level version of this seeding is built.
