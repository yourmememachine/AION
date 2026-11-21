# REVIEW — Cycle 14: snapshot chain-gap enforcement war room

Six blind internal reviewers, drawn from pods that did not
build the item; scores locked in
state/calibration/calibration.json (subject `cycle-14-build`,
rev-r3 recorded with the `dissent` role) BEFORE reconciliation.
External seats (seat-gpt, seat-gemini): the blind brief
(internal/CROSS-CHECK-BRIEF-CYCLE-14.md) was prepared with no
internal verdicts in it, but neither seat could be reached from
this detached scheduled run (no browser session available to
it). Both are recorded VACANT — not as passes — and the verdict
below is PROVISIONAL until they review the brief. An external
approval never overrides an internal FIX.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 (seat 1) | scope fidelity vs the item | 0.95 | SHIP |
| rev-r2 (seat 3) | adversarial / safety | 0.85 | FIX |
| rev-r3 (seat 15) | whole item (forced dissent) | 0.64 | FIX |
| rev-r4 (seat 2) | docstring honesty | 0.92 | SHIP |
| rev-r5 (seat 14) | test quality | 0.90 | SHIP |
| rev-r6 (seat 6) | integration & regression | 0.95 | SHIP |
| re-verify (fresh seat) | fix-round re-probe | 0.90 | SHIP |

Reconciled verdict: **SHIP, PROVISIONAL** — every defect
finding is closed and re-verified; the one remaining FIX is
the forced dissent's policy objection, preserved in full below
and NOT overridden. Following the cycle-12 precedent (dissent
preserved, ship provisional, final recording left to the owner
path), loop-state recording is not performed by this run (see
BUILD-CYCLE-14.md, Recording status).

## Principal findings and dispositions

- **rev-r2 MEDIUM-LOW → CLOSED.** The pin mapping was re-read
  on every comparison branch; a dict subclass returning
  cycle_seq 1,1,1,1,10 on successive reads fell through
  rollback / pin_mismatch / chain_discontinuity / chain_gap to
  `()` through the strict wrapper — the exact pass cycle 14
  exists to refuse (deterministic probe). Fix: each pin field
  is captured once into locals and all validation/comparison
  uses only the locals. Regression pinned
  (`test_inconsistent_read_pin_cannot_fall_through_to_pass`).
  The fresh re-verification seat rebuilt the attack
  independently: at every flip threshold the result is
  `snapshot_rolled_back` or `chain_gap`, never `()`; a
  verification now consumes exactly 2 `cycle_seq` reads.
- **Re-verification residual → CLOSED.** Validation used
  `.get` while the first fix's capture used `[]` / `in`, so an
  accessor-splitting mapping could be validated as one pin and
  compared as another. Fix: one accessor (`.get`, with a
  sentinel for optional bindings), one read per field, locals
  only. Regression pinned
  (`test_get_accessor_flip_cannot_split_validation_from_capture`).
  The seat's remaining observation stands as a limit, not a
  defect: a pin actively substituted with the candidate itself
  passes coherently — the pin must never be reconstructed from
  the snapshot being verified (module docstring, pre-existing).
- **rev-r5 hardening → LANDED.** (1) pin+2 whose prev points
  directly at the pin (the most attacker-shaped variant) now
  pinned; (2) large-jump test tightened to the exact tuple;
  (3) dedup asserted on the real path (pin with both key_id
  and signer_id wrong at gap distance →
  `("pin_mismatch", "chain_gap")`).
- **rev-r4 minors → noted, not landed.** The module
  docstring's "can no longer be laundered into a pin advance"
  rests on the caller honouring advance-only-on-`()` (true
  within the docstring's stated boundary; no pin machinery
  exists in code yet); "one verified snapshot" vs the wrapper's
  "taken and verified" is an under-specification, not an
  over-claim. Both stand as written.
- **rev-r1 / rev-r6:** no findings. rev-r6 grep-verified zero
  production callers, flag containment (sole `True` call site
  is the strict wrapper), exports unchanged, and independently
  ran the full suite green.

## The forced dissent (rev-r3, seat 15) — preserved, not averaged away

Score 0.64, verdict FIX. Its case, in its own structure:

1. Refusal conflates a proven attestation (MAC, bindings,
   signer all valid) with an unproven history; `()`-or-fail
   collapses the two. The unbuilt middle position — accept the
   attestation, refuse the pin advance (quarantine) — stops
   the cycle-12 laundering harm without bricking attestation.
2. The deadlock is guaranteed eventually, not an edge case:
   hourly loop, ordinary downtime, and intermediates aged past
   TTL (max 48h) cannot be replayed — catch-up becomes
   permanently impossible, where a flag degrades gracefully.
3. Shipping refusal before `snapshot-pin-ceremony` inverts the
   dependency order: the item that makes the ceremony
   load-bearing ships while the ceremony stays unscheduled.
4. The threat stopped is narrow (an honest-but-careless
   non-key-holder caller); a loud flag stops that actor
   equally, and a flag-ignoring caller keeps the bare-verify
   bypass — so the refusal buys little over a flag.
5. No production caller exists, so the one-snapshot-per-cycle
   cadence assumption is unvalidated; a flag is the reversible
   choice while that evidence is absent.

What would change the dissent's mind: (a) the pin ceremony
shipped, giving the deadlock a supported exit; (b) a supported
quarantine path in the API (separable warning channel or an
accept-without-pin-advance option); (c) evidence of a real
consumer on the assumed cadence.

Coordinator reconciliation: the dissent's honesty points are
fully met (it says so itself: no over-claim found, the
reason-not-exception shape is right, the naming is honest).
Its mechanism point is partially answered in this cycle: the
wrapper docstring now states the precise supported reading of
a sole `("chain_gap",)` — every attestation binding passed,
pin must not advance — which is the quarantine semantics
expressible in this API, where pin advancement is the caller's
act and a returned reason is the only channel. Points 2, 3 and
5 are sequencing/scope judgments for the owner: they are why
this verdict is PROVISIONAL, why loop-state recording is left
to the owner's path, and why `snapshot-pin-ceremony` (backlog
seq 35) is now the more urgent follow-on. The dissent is NOT
recorded as resolved.

## Verification summary

- Module suite: 61 tests OK (44 baseline, +13 cycle, +4 fix
  round).
- Full suite, final tree (coordinator run): **1162 tests, OK
  (skipped=26)** — the 26 skips are deployment-gated live
  tests (deployment not provisioned in this run). One
  re-verification-seat full run reported a single unnamed
  non-signing failure, green on immediate rerun; both
  coordinator full runs were green.
- Calibration: blind scores recorded for `cycle-14-build` and
  `cycle-14-fixround`; discussions closed; outcomes unscored
  pending the provisional verdict's resolution.

Verdict: **SHIP, PROVISIONAL** (external seats vacant;
rev-r3 dissent preserved; loop-state recording deferred to
the main chat's signed ship path — pick_next currently returns
`ledger-head-anchoring`).
