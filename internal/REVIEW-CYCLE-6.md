# INTERNAL — War Room Record, Build Cycle 6 (do not publish)

Six reviewer seats, none of them authors of the code under review
(all 15 scientist seats coded this cycle in 5 pods of 3, so review
seats are fresh rev-r1..rev-r6, the cycle-3/4/5 pattern). Blind pass
first; R2 held the assigned dissent role.

Reviewer seats: R1 Journal Correctness, R2 Adversarial (dissent),
R3 Gate Binding, R4 Lifecycle/State Machine, R5 Integration/Tests,
R6 Honesty/Docs.

## Blind verdicts (as reported)
- R1 — FIX, 0.93. CRITICAL: no locking / no reload-before-save —
  stale instances silently overwrite; double consume across
  instances. HIGH: replay enforces no state machine (crafted
  hash-valid journal resurrects a consumed proposal; bogus-kind
  entry burns an id). HIGH: _record_leg prefix filter records
  never-authorisable legs and bricks the slot. MEDIUM-HIGH: _append
  mutates before save with no rollback (phantom entries duplicate
  on retry). Plus owner-in-builders, _validate type gaps, error
  leaks, cap arithmetic.
- R2 (dissent) — FIX, high. CRITICAL: double-consume / lost updates
  (two different valid receipts); journal deletion/rewrite erases
  consumption (disclosed class); total forgery with zero credentials
  (disclosed, still blocking as a claim limit). HIGH: the two judges
  disagree — eval/gate.py's protected check does not canonicalise
  (core/./loop.py evades) and does not cover oversight/ (a protected
  file itself: queued as gate-path-canonicalisation, BLOCKED on
  owner approval, NOT edited this cycle). HIGH: bad legs recorded
  then brick; consume() never reads real files and the receipt
  lacked expiry (receipt fields added; file-reading apply remains
  the future caller's duty, stated in the build record). MEDIUM:
  pure evaluate authorises fabricated requests (now documented
  advisory-only + request invariants added). Owner-in-builders.
- R3 — FIX, 0.92. HIGH: future-dated attestation recorded, later
  becomes valid and consumable. MEDIUM: no attested_at <= expiry
  check; record filter misses reward_hacking_not_checked,
  missing_independence_note, attestation_before_request and
  bad_{kind}_id (name mismatch); leg evidence/independence text not
  _check_text-validated (zero-width-only text authorised). LOW:
  pure-function request invariants; deny-filter inconsistency.
- R4 — FIX, 0.92. HIGH: invalid external leg journaled and bricks
  (same root as R1/R3); temporally invalid/expired legs accepted;
  revoke() never materialises expiry (call-order-dependent terminal
  state). MEDIUM: evaluate()/status() report authorized=True after
  CONSUMED. LOW: deny re-record not idempotent; read paths mutate
  via lazy expiry (kept, documented).
- R5 — FIX (tests only), 0.90. No code defect found on its probes;
  29/29 new + 357 full at its check. Findings: digest check, owner-
  as-builder, package exports, attestation timing, bound-expiry,
  independence note, journal caps all untested — several mutations
  survived. Fix list was tests.
- R6 — FIX, ~0.90. HIGH: "single-use and final / burned forever /
  one-active" unqualified under concurrency (same root as R1/R2);
  journal lifetime cap undocumented and the demanded compaction
  does not exist. MEDIUM: "digest-sealed / deletions detected"
  overstated (unkeyed, in-file); timestamps are caller-asserted, not
  only host-asserted; no-deletion undocumented and inconsistently
  enforced (consume TypeError). LOW: burn scope, one-active and
  all-paths-protected only in fragments.

## Reconciled fix list (all implemented, pinned by tests)
1. Concurrency: mutators hold an flock on the journal directory and
   re-check the on-disk (seq, head) before saving; a stale manager
   fails closed. Verified with a real 4-process race: exactly one
   winner. (R1/R2/R6 F1)
2. Journal replay validation: known kinds only, valid proposal ids,
   first entry must be requested, no entries after a terminal state,
   legs at most once, denied requires a leg, consumed requires both
   legs — later strengthened to both APPROVE legs. (R1 F2, V1 2M)
3. _record_leg rejects on ANY reason attributable to the incoming
   leg (enumerated, not prefix-matched): binding, identity,
   reward-hacking, independence note, text validity, attestation
   timing (before-request / in-future / after-expiry), leg expired.
   Deny exempt only from reward-hacking/independence. A rejected leg
   never occupies the slot. (R1/R2/R3/R4)
4. _append rolls back in-memory state on pre-commit save failure;
   retry lands exactly once. (R1 F4; edges closed in round 2)
5. evaluate()/status() treat CONSUMED as terminal: authorized=False
   with terminal_consumed. (R4 F4)
6. revoke() materialises expiry first; terminal outcome is no
   longer call-order dependent. (R4 F3)
7. Deny re-record is idempotent (identical leg returns before the
   terminal check). (R4 F5)
8. create_request refuses the owner among builder_ids; pure
   evaluate also yields owner_approval_actor_forbidden. (R1/R2/R4)
9. Error normalisation: candidate None at consume and mismatched
   candidate/preimage key sets raise ApprovalError, never TypeError
   or KeyError. (R2/R6, R1 F8)
10. Receipt carries effective_expires_at and preimage_hash. (R2 F6)
11. evaluate_approvals validates request invariants (builders >= 3
    distinct, TTL window, hex64 hashes, non-empty paths, text) and
    is documented advisory-only; attestation_after_expiry added;
    _check_text applied to leg evidence/independence fields.
    (R2 F7, R3 F2/F4/F5)
12. Docstring reconciled: journal caps (~49 cycles, no compaction
    yet), caller/host-asserted timestamps, recompute caveat for the
    unkeyed chain/digest (incl. outright deletion), no-deletion,
    burn at any terminal, all-paths-protected, one-active + lazy
    expiry, single-machine flock qualification. (R6)
13. Tests: +22 pinning tests in the fix round (stale manager, bad
    legs, timing, replay crafting, used-id mismatch, save-failure
    rollback, exports, owner-in-builders, receipt fields, states).
    (R5)

## Verification rounds
Round 1: V2 (adversarial) SHIP high — 66+7 probes, all nine fix
classes verified live, 4-process race clean. V3 (honesty/tests)
SHIP ~0.90 — claims accurate, totals confirmed, mutation spot-checks
pinned. V1 (journal/lifecycle) FIX 0.90 — two blockers in the
claimed rollback fix itself: 4D deny was two non-atomic appends (a
crash between them bricks the active slot; re-record could never
complete it) and 4E post-replace dir-fsync failure left memory and
disk in disagreement.
Round 2 fixes: DENIED is derived from the recorded deny leg in
_rebuild and in replay validation — one atomic append, no separate
denied entry; _append treats os.replace as the commit point and
reconciles from disk when the disk head matches the new entry;
replay requires both approve legs before consumed. +4 tests (51
total). V1b SHIP high — 38/38 probes incl. fault injection at every
append point on create/record/consume, crafted-journal controls.
One non-blocking note stands: replay still accepts a legacy denied
entry after an approve leg (fails closed; inside the disclosed
forgery class) — tighten in a later cycle.

Final verdict: RECONCILED SHIP — unanimous after verification
(all six blind FIX seats' findings verified closed or explicitly
queued as protected/owner-gated backlog). Full suite after all
rounds: 379 tests, all passing (328 before the cycle).

## Calibration (X4)
Blind ship-confidence scores locked in state/calibration for
subject cycle-6-build: R1 0.07, R2 0.10 (dissent role), R3 0.08,
R4 0.08, R5 0.10, R6 0.10. (FIX seats reported confidence in their
FIX verdict; the recorded score is 1 minus that, i.e. confidence
the build should ship as-is — low scores were accurate: the blind
build had real critical findings.) Outcome recorded after ship: 1.0.
Minority note: no seat shipped blind; the dissent seat's forgery
finding is a disclosed design limit whose closure is the next
backlog item (signed-gate-decisions), not a defect of this build.
