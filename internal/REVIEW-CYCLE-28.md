# REVIEW — Cycle 28 war room (pin-store history reconciliation)

Six internal seats, blind, independent scores recorded
before discussion; seat rev-r6 held the forced-dissent slot.
Full seat texts in internal/cycle28-work/ (review-r1..r6.md,
rereview-r3/r5/r6.md). External seats: the blind brief is
internal/CROSS-CHECK-BRIEF-CYCLE-28.md; their reviews are the
parent's browser round, so this cycle's verdict is
PROVISIONAL until those findings are reconciled in.

## First round — SPLIT

- rev-r1 — SHIP 0.87 (core soundness: no reachable false
  negative or false refusal in the production composition;
  pure-function boundary weaknesses — id-based head excuse,
  duplicate journal ids/seqs unvalidated, supersede excuse
  binding thinner than claimed, dead constant
  _CONSUMPTION_REQUIRED_KEYS, unvalidated excuse-list types).
- rev-r2 — SHIP 0.85 (wiring: step (3b) placement verified on
  every path including supersede-resume; known-unadopted
  derivation cannot excuse an adopted ceremony; factory must
  NOT auto-wire — agreeing with the coordinator over coder
  seat B — with the honest cost that the runner passed no
  providers; adopt_returned residual noted).
- rev-r3 — FIX 0.60 (tests: genesis baseline had no control;
  both supersede-excuse branches beyond the id-present one
  untested — BLOCKING; genesis baseline untested through the
  adopter — BLOCKING; failing-first.md misdescribed test_17
  and claimed a pre-change run that could not have happened).
- rev-r4 — SHIP 0.87 (claims/docs: all added claim surfaces
  correctly wiring-conditioned, authority unchanged, claim-pin
  test_16 passes; two one-line nits — "proves" → "attests",
  and the ceremony docstring should name the adopter as the
  refusing layer).
- rev-r5 — FIX 0.60 (scope clean, no redesign, state
  untouched; RULING: the follow-up cannot close while no
  production caller wires the providers — trust/runner.py
  passed none, and the cycle-21 precedent does not carry
  because there the wiring existed. Required: wire the runner
  or carry the follow-up forward renamed.)
- rev-r6 (forced dissent) — FIX 0.42 (claim theatre: deployed
  behaviour identical to cycle 27; REPRODUCED BUG: the
  known-unadopted excuse compares authorisation ids, not the
  head entry — two journal entries sharing one id are both
  excused, including the non-head one; provider-supplied
  journal integrity rests on caller trust; genesis baseline
  unbounded as coded; directory-granularity restore after a
  genuine burn deadlocks with no repair procedure; anchoring
  was the honest branch).

## Fix round — reconciled fix list applied

- Head excuse binds to the head ENTRY (identity after the
  seq sort); journal validation refuses duplicate
  authorisation ids and duplicate seqs with SigningError
  (rev-r6's exact counterexample now raises; pinned by
  test_21). Excuse-list and genesis_baseline inputs are
  type-validated.
- Supersede excuse strengthened: a decision's abandoned
  target fields, when carried, must agree with the entry;
  a landed replacement record must match the decision's
  candidate pair when the decision carries one.
- Dead constant _CONSUMPTION_REQUIRED_KEYS removed; the
  redundant ID+PAIR branch removed and the docstring now
  states pair coverage is the operative coverage rule.
- Doc nits taken: "proves" → "attests" with the fabrication
  scope stated (head entry only); ceremony docstring names
  the adopter as the refusing layer; pin_adoption docstring
  gains the adopt_returned basis and the
  consumption-without-supersession-provider note.
- Tests 18 → 23: genesis-baseline control; test_06 in-test
  control; test_19 (candidate-pair supersede branch, with
  candidate-mismatch and abandoned-target-mismatch
  controls); test_20 (pair-covered supersede branch);
  test_21 (duplicate journal id/seq); integration test_19
  (wired genesis after pin loss is not refused by
  reconciliation); integration test_20 (runner
  _history_providers, fresh per call).
- failing-first.md rewritten: §1 states the whole file
  failed at import pre-change and no individual test ran;
  §2 describes the wired/unwired pair accurately, with the
  earlier misdescription acknowledged as corrected.
- PRODUCTION WIRING (rev-r5/rev-r6's central demand):
  trust/runner.py — the composition layer that legitimately
  holds the verifier home — now builds both providers via
  _history_providers(verifier_env) in main() and passes them
  to build_pin_adopter. The factory still never derives
  providers (cycle-25 separation preserved; rev-r2's ruling
  stands where it applied). Re-review rr-r5 verified the
  runner suite (13 tests) green with reconciliation active
  end-to-end: genesis, chain_gap_recovery, genuine burn and
  supersession-pending outcomes unchanged.
- rr-r5's re-review found one new minor defect in the
  wiring: _history_providers indexed AION_VERIFIER_HOME
  directly, so a missing key would KeyError past the runner's
  structured config refusal. Fixed in the same round:
  absence now refuses via _refuse/_ConfigRefusal naming the
  variable, pinned by an assertion in integration test_20.

## Rulings recorded (rev-r6's remaining points)

- Genesis baseline bound: a genesis attempt against a
  non-empty journal cannot proceed as initial_anchor — the
  consumption head rules refuse initial_anchor outright
  against a non-empty journal, and signing/pin_ceremony.py
  requires an empty history for it — so baselining takes
  effect only through the attested-loss reasons
  (lost_pin / corrupted_pin / burned_unadopted) under the
  ceremony's own verifier authorisation. The attested reason
  lives in that layer; reconciliation is not the refuser
  (integration test_19). Verified in code by rr-r6.
- Directory-granularity restore after a genuine burn
  (rev-r6 4b): OPEN as a recorded residual, non-blocking.
  Wholesale pin-directory loss also loses the pending
  journal and with it the known-unadopted excuse, so a later
  attempt can refuse pin_store_history_incomplete with no
  in-system repair procedure. This is the detection failing
  closed, in the same class as the pre-existing
  corrupted-pin-store operator-recovery residual (cycle 14:
  operator removes/replaces the file out-of-band). It is an
  operability debt, named here, not a soundness hole.
- Provider trust: the production composition uses only the
  from-home helpers, which load through the ledger classes
  (hash chain recomputed on load); tail-truncation resistance
  rests on the journals' external anchors, verified at
  verifier startup (cycles 22/27). A caller-supplied provider
  returning a truncated journal is trusted as supplied —
  stated in the module docstring as the composition seam's
  trust assumption.
- Anchoring dissent (rev-r6 7, rev-r5 4): recorded as
  standing judgement dissent, non-blocking. The external
  pin-store head anchor remains a named open follow-up; it
  would additionally detect lost advance_pin movements,
  which leave no journal trace (also a named residual).

## Re-review

- rr-r3 — SHIP 0.95 (all findings closed, incl. both
  blocking test gaps; failing-first record corrected).
- rr-r5 — SHIP 0.86 (production wiring verified in main();
  follow-up can honestly close; its one new minor defect
  fixed in-round, above).
- rr-r6 (dissent re-check) — SHIP 0.85 (its FIX drivers —
  findings 1, 2, 5 — verified closed by adversarial re-run;
  4b residual and 7 anchoring dissent remain open as
  recorded, non-blocking).

## Final verdict

SHIP (PROVISIONAL on the external seats) — reconciled
unanimous after the fix round: the three SHIP seats'
findings were taken as fix items where they identified real
gaps, and all three FIX seats converted on re-review.
Final suite: recorded in internal/BUILD-CYCLE-28.md.
Real state/state.json not advanced (sha256 verified
identical before/after).

## External seats — verdicts and the GPT fix round

- seat-gpt — **FIX 0.91**. Q1 blocking: the known-unadopted
  head excuse is an assertion, not proof — authorisation A
  consumed (head) → adopted and recorded in the store →
  pending journal still lists A as unadopted → store restored
  to a pre-A generation → a beyond-A attempt excuses A, the
  exact record whose disappearance detection exists to
  catch. Demanded crash-injection evidence (interrupted
  cleanup, independent pending-journal rollback). Q2 accepted
  with the condition that every production adoption entry
  point be audited for provider wiring. Q3: reconciliation
  was the right branch, no anchor demanded.
- seat-gemini — **SHIP 0.84** (targeted follow-up hardening).
  Independently constructed the SAME stale-pending head
  scenario (adopted ceremony still listed in the pending
  journal; store restored to a pre-adoption generation; head
  entry excused despite the missing record) but rated it
  non-blocking, noting the excuse is head-only so it cannot
  mask gaps behind the head, and suggesting pending-journal
  lifecycle tightening. Accepted wiring-dependent detection
  (same unwired-caller caution as seat-gpt's Q2 condition)
  and agreed reconciliation was the right branch over a head
  anchor.

Convergence and governing verdict: both external seats
constructed the same scenario; per the standing rule an
external SHIP does not override a FIX, so seat-gpt's FIX
governed and the cycle stayed PROVISIONAL/FIX until this
round. Full record: internal/cycle28-work/fix-round-gpt.md.

### Fix round reconciliation (applied)

- Code check verified in-tree: the pending journal appends
  consumed → adopt → "adopted", the adopted append's OSError
  is deliberately swallowed, and the known-unadopted list
  derives from slots WITHOUT an adopted phase. So a
  store-only restore with an intact pending journal never
  excused A (pinned by new test_23, passing pre-fix); the
  hole is compound — adopted-line loss COMBINED with a store
  restore — and at the reconciliation layer that state is
  indistinguishable from a genuine burn, so no corroborating
  guard inside the layer can separate them.
- Reproduction, failing-first (pre-fix, recorded in
  fix-round-gpt.md before the change): test_22 (adopted-line
  stripped + store restored + beyond-A wired attempt) was
  silently excused and proceeded to
  PinSupersessionPendingApproval — hole confirmed. test_24
  (independent pending-journal rollback + store restore) and
  test_25 (pending rollback alone; store record pair-covers)
  behaved correctly pre-fix and are pinned unchanged.
- Fix: the known-unadopted head excuse is narrowed to a
  candidate AT the head entry's own sequence
  (`E.new_cycle_seq == candidate_seq`). A beyond-head
  candidate is never excused by this rule. Justification:
  the verifier's consumption-head rules already require a
  head burn to be recovered (pair coverage) or superseded
  (bound decision) before the head moves, so the beyond
  reach had no legitimate production flow that adopts past
  a burn — its only effect was proceeding to a downstream
  stop instead of refusing, and in the compound state it
  excused an adopted record's disappearance. An at-sequence
  candidate cannot adopt past the head either (the same
  head rules force recovery/supersession, and the resume
  attempt is then supersession-excused), so the retained
  reach cannot complete a silent adoption. Pure tests
  test_09/test_10 updated to the narrowed claim, with the
  change and reason recorded in-test — claim narrowing, not
  silent weakening. This also fully answers seat-gemini's
  hardening suggestion: instead of tightening the pending
  journal's lifecycle, the excuse no longer trusts that
  journal for the beyond-head reach at all.
- Q2 audit (detail in fix-round-gpt.md): the only production
  construction site is trust/runner.py main(), which wires
  both providers; build_pin_adopter is pass-through only and
  its sole production caller is the runner; no direct
  PinAdopter construction exists in production code (all
  remaining sites are tests/harness). No wiring change
  needed.
- Post-fix: test_22 refuses pin_store_history_incomplete
  naming A; the cycle-28 module is 27 tests OK; the full
  suite result and totals are recorded in
  internal/BUILD-CYCLE-28.md.

### Verdict after the fix round

The internal SHIP stands on the narrowed claim: the change
is a restriction (strictly more refusals, no new excuse),
the tests that encoded the removed reach were updated with
reasons (cycle-28 test_09/test_10, and the runner
supersession-pending test — the one production-wired flow
that relied on the beyond reach to reach its pending stop;
its update and the resulting beyond-head genuine-burn
operability residual are recorded in fix-round-gpt.md and
BUILD-CYCLE-28.md), and the scenario both external seats
named is closed by test_22. The cycle remains PROVISIONAL only on
the parent's external re-confirmation, if it chooses to run
one; seat-gemini's SHIP already covers the narrowed design
direction (its scenario is the one closed).

Fix-round re-review seat — SHIP 0.90: the narrowing is
implemented exactly as recorded, with no bypass found
(relevance, head-identity binding, duplicate refusal,
genesis baseline and the fully bound supersession excuse
all checked); test_22–25 pin the scenarios as claimed. One
non-blocking caveat, accepted as a follow-up: no test pins
the WIRED at-sequence candidate reaching supersession-
pending (the supersession suites cover the pending flow on
the unwired adopter; the at-sequence excuse is unit-pinned
by test_09/test_10). The runner test's comment was corrected
to state this precisely rather than claim the coverage
exists.
