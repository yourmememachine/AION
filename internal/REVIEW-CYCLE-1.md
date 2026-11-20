# INTERNAL — Review Cycle 1 Record (do not publish)

## Seats (blind first pass, then cross-critique by coordinator)
1. Correctness / state machine — verdict FIX
2. Persistence / corruption — verdict FIX
3. Governance gates / bypass — verdict FIX
4. Adversarial / injection — verdict FIX (3 blockers verified by execution)
5. Tests quality — verdict FIX (22/22 pass but mutation-survivable)
6. Simplicity / extensibility — verdict FIX

## Cross-critique / reconciliation
All six converged, unanimous FIX — no split verdict to reconcile.
Convergent findings (raised independently by 3+ seats):
- Public transition() walks to SHIP with zero gates (Seats 1, 3, 6).
- Mid-cycle persisted phases brick the loop: no resume/abort (Seats 1, 2, 6).
- _validate is top-level only; crafted state loads and bypasses every
  gate/cap/approval (Seats 1, 2, 3, 4).
- External-scan items self-approve via caller-supplied approved flag,
  incl. truthy string "false" (Seats 1, 2, 3, 4).
- Delta need not improve, evidence is unchecked free text, verifier need
  not be a reviewer (Seats 1, 3, 4, 6).
- scan() is non-atomic: rejected batch prefixes persist later (Seats 1, 2, 4, 5).
- Identity is raw string equality: aliases, string-as-list, coder==reviewer
  all pass (Seats 1, 3, 4).
Disagreement was scope only: Seat 3/4 asked for signed state / per-seat votes
(cryptographic governance); Seats 2/6 argued for keeping v1 small.
Reconciled: deep validation + separation of duties in v1; signing, hash
chains, frozen benchmarks and per-seat vote records deferred to backlog
(they were on the adversarial seat's own v2 list in the build discussion).

## Reconciled fix list (applied this cycle)
F1. Remove public phase walking. A cycle is computed in memory and persisted
    in ONE atomic save; phase on disk is always SCAN between cycles, so a
    crash can never strand the loop mid-cycle. DONE removed from PHASES
    (it is a history outcome, not a persisted phase); history entries record
    the phase sequence traversed.
F2. Deep validation of every backlog/history/delta entry on load AND save,
    incl. caps, duplicate ids/hashes, cycle_seq == last history cycle_id,
    bool rejected for ints, current_item_id checked.
F3. Non-finite closure: parse_float rejects inf (1e999), dumps uses
    allow_nan=False, derived delta change must be finite.
F4. Approval is a separate step: scan() never approves external_scan items;
    approve(item_id, approver) records the approver. Internal items are
    approved by intake.
F5. Participants: must be real lists of valid ids, distinct, coders and
    reviewers disjoint, delta verifier must be a reviewer (hence not a
    builder), seat lists capped at 15.
F6. Delta must improve (after > before) with metric, evidence_ref, verifier.
F7. scan() is all-or-nothing: validate the whole batch before mutating;
    run_one_cycle snapshots and rolls back on any failure.
F8. Ids use fullmatch; text rejects control / zero-width / bidi-override
    characters; title dedup hash uses NFKC + casefold; leverage bounded
    0..1000.
F9. Lifetime caps no longer halt the loop: backlog cap counts open items
    only; history/deltas prune oldest beyond 200 with a pruned counter.
F10. Dead .bak removed (it was never read); directory fsync after replace;
    load checks file size via stat before reading; pick_next returns a copy.
F11. Tests added for: external approval via API, approve() flow, gate
    no-side-effects (memory + disk), batch atomicity, crafted-state load,
    delta regression/overflow, identity alias/string/overlap, unicode dedup,
    trailing-newline id, text caps, non-SCAN start guard.

## Verification round (same 6 seats, after fixes)
- Seats 1, 2, 5, 6: SHIP (32/32 tests at that point).
- Seat 3: FIX — persisted delta verifier was not checked against that
  cycle's reviewers on load; cycle_seq could run ahead of history.
  Fixed: reviewers-by-cycle check + strict cycle_seq equality; approve()
  rollback added. Test added.
- Seat 4: FIX — crafted-state status/history disagreement, empty
  approved_by, and no backlog cap on load; plus minors (invisible-char
  filter gaps, huge-int OverflowError, approve() on done items, homoglyph
  dedup noted). Fixed all three majors and the cheap minors; homoglyph
  dedup deferred (needs a confusables table, not a v1 fix).
  Tests added for all three majors.
- Final: 36/36 tests pass. Reconciled verdict: SHIP (local foundation only;
  nothing pushed anywhere). Remaining known limit, stated honestly:
  deep validation checks consistency, not authenticity — anyone with
  state-file write access can fabricate a self-consistent history.
  Signing/hash-chaining is the deferred fix, already in the backlog.

## Deferred to backlog (next cycle candidates)
- Signed/hash-chained state and per-seat vote records.
- Frozen benchmark suite for delta metrics; baseline continuity per metric.
- Concurrency: single-writer lock between processes.
- Lesson context delimiting when lessons are fed to future cycles.
- Ageing/fairness for high-leverage backlog starvation.
