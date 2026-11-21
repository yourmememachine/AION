# BUILD — Cycle 14: snapshot chain-gap enforcement

Item: backlog `snapshot-chain-gap-enforcement` (seq 34, leverage
6.5) — "Enforce snapshot chain continuity beyond a pin's immediate
successor in the strict wrapper (refuse or flag cycle_seq more
than one past the pin); rev-r2 dissent + both external seats,
cycle 12."

Origin: this scheduled run (2026-11-20 ~19:02 MST start). Tree
was clean at cycle 13 (commit 705c7be, 1145 tests); no competing
build was in flight (no file modified in the 2 hours before the
run, loop state at cycle 13).

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15), design round before
any code:

- Pod A (1 Chief, 5 Model Builder, 8 Compute): strict wrapper
  only; new distinct reason; O(1) check, no chain-walk.
- Pod B (2 AGI Science, 6 World Models, 7 Spatial): refusal in
  the strict wrapper closes the laundering gap for its
  consumers; legitimate-flow costs named (sporadic attestation,
  TTL deadlock, bootstrap) and docstring duties assigned.
- Pod C (9 Coding Agents, 10 Framework, 11 Open Models):
  implementation sketch taken verbatim in substance — private
  `_enforce_chain_gap` flag inside the existing pin block, so
  pin validation and reason dedup are reused, never duplicated.
- Pod D (3 Safety, 4 Scaling/Eval, 15 Future & Risk):
  adversarial map (bare-verify downgrade, pin re-basing,
  stepwise laundering, seq manipulation, key-holder limits) and
  the forced-dissent case for flag-over-refusal.
- Pod E (12 Robotics, 13 Voice, 14 Product): consumers — zero
  production callers of either verify function (grep-verified
  again by rev-r6); operator pin-advancement workflow; records
  inventory.

War room: 6 blind reviewers from other pods (rev-r1..rev-r6,
one forced-dissent seat) + 1 fresh re-verification seat for the
fix round. External seats: see REVIEW-CYCLE-14.md — the blind
brief is internal/CROSS-CHECK-BRIEF-CYCLE-14.md; neither
external seat could be reached from this detached scheduled run
(no browser session available to it), so both are recorded as
VACANT, not as passes, and the verdict stays PROVISIONAL.

## What was built (signing/state_snapshot.py only)

1. **Chain-gap enforcement.** `verify_signed_snapshot` gains a
   private keyword `_enforce_chain_gap=False`. Inside the pin
   block, after the pin+1 branch, a new `elif` appends the
   reason `chain_gap` when the flag is set and
   `signed.cycle_seq > pin_seq + 1`. `verify_snapshot_for_state`
   passes `_enforce_chain_gap=True`. Bare verification is
   unchanged by design and now says so in its docstring.
   Rationale for the name (Pods A/B/C/D convergent): at pin+2,
   discontinuity is unprovable, not proven — the verifier holds
   only the candidate's `prev_snapshot_hash` (naming the unseen
   intermediate) and the pin's hash, never the intermediate.
   A candidate whose `prev` correctly names the real
   intermediate is still refused: correctness at that distance
   is unobservable from (candidate, pin) alone.
2. **Pin capture hardening (fix round, rev-r2).** The pin block
   previously re-read the pin mapping on every branch; an
   inconsistent-read pin (values changing between reads) could
   fall through every branch to `()`. Each pin field is now
   read ONCE, via `.get` alone (sentinel for the optional
   key/signer bindings), captured into locals, and validation
   and every comparison use only the locals — closing both the
   branch fall-through and the validation↔capture accessor
   split the re-verification seat found in the first fix.
3. **Docstrings.** Module docstring: strict wrapper narrows
   the completeness limit; refusal assumes one verified
   snapshot per cycle; a missed/expired intermediate deadlocks
   strict catch-up until an external pin ceremony (backlog
   `snapshot-pin-ceremony`, not yet implemented) re-anchors the
   pin. Wrapper docstring: enforcement, the precise quarantine
   meaning of a sole `("chain_gap",)` result (every attestation
   binding passed; the pin must not advance), the cost, and
   that pruned *state* history is unaffected — only unobserved
   *snapshot* sequences are refused.

## Tests

- NEW `Cycle14ChainGapTests` (13) + `Cycle14FixRoundTests` (4)
  in tests/test_signing_state_snapshot.py: same-seq pass, pin+1
  chained pass, pin+2 refused with correct prev and with
  garbage prev, pin+2 with prev pointing AT the pin (rev-r5),
  large jump exact tuple, co-report dedup (incl. double
  pin_mismatch sources), pin+1 fork = chain_discontinuity only,
  rollback / pin_mismatch disambiguation, pin-seq-0 boundaries,
  bare-verify scope pin, pruned-state successor + gap pair,
  7 malformed-pin shapes raising SigningError, FlipDict
  fall-through regression (rev-r2), .get-flip regression
  (re-verification seat).
- Module suite: 44 → 61 tests, all OK.
- Full suite (coordinator, final tree): **1162 tests, OK
  (skipped=26)** — baseline 1145 → +17. The 26 skips are the
  deployment-gated live tests; the live verifier deployment is
  not provisioned in this run (as after past VM resets), so
  those tests skip by design. Honest note: the re-verification
  seat's first full-suite run reported 1 failure in an unnamed
  non-signing test, green on its immediate rerun; both
  coordinator full runs (1161 pre-hardening, 1162 final) were
  fully green.

## Recording status — read before assuming state

- Calibration: blind scores for subject `cycle-14-build`
  (rev-r1..rev-r6, rev-r3 as the dissent seat) and
  `cycle-14-fixround` (re-verification seat) are recorded and
  both discussions closed in state/calibration/calibration.json.
  Outcomes are NOT scored: the verdict is provisional.
- Loop state (state/state.json) is NOT advanced by this run.
  `CoreLoop.pick_next()` returns `ledger-head-anchoring` (same
  6.5 leverage, earlier insertion seq), and the signed ship
  path refuses a mismatched item; this run does not re-rank,
  force, or hand-edit loop state. Recording cycle 14 (and
  marking the backlog item done) is left to the main chat's
  signed ship path, as signed-state's recording was handled in
  earlier cycles. The backlog item therefore still reads
  `pending` in loop state while being built, reviewed and
  green in the tree — this record is the evidence.
- No commit and no push from this run (the 12-hour push job
  ships verified states only; the tree is left uncommitted for
  the recording step).

## Self-improvement delta

tests_passing 1145 → 1162 (coordinator full-suite run on the
final tree; verifier: the war room's non-builder seats).
Process lesson: a trust anchor must be read exactly once —
validation, capture and comparison split across repeated reads
of a caller-supplied mapping is a fall-through class, and the
finding seat's own inconsistent-read probe is now the standing
regression shape for any future pin/anchor handling.
