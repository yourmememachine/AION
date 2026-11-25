# BUILD CYCLE 28 — pin-store history reconciliation (detection)

**Summary (claim scope):** Cycle 28 closes the follow-up
`pin-store-history-reconciliation` at its detection scope:
the pin-store ceremony history is now reconciled against the
verifier's externally anchored consumption journal at
adoption time, and an unaccounted journal entry relevant to
the candidate refuses the attempt with the deterministic
code `pin_store_history_incomplete` — incompleteness is
detected and refused, not silent. Detection is ACTIVE in the
production composition (trust/runner.py wires both journal
providers). Design record: internal/cycle28-work/
design-final.md (including the pre-build coder reconciliation
rulings). War room: six internal seats, one fix round, three
re-review seats (internal/REVIEW-CYCLE-28.md); verdict SHIP
PROVISIONAL on the external seats — the blind brief is
internal/CROSS-CHECK-BRIEF-CYCLE-28.md and the external
round is the parent's to run and reconcile.

Baseline: cycle-27 tree at 1785 tests OK (skipped=28),
coordinator-verified at cycle start. Internal round final:
1808 tests OK (skipped=28) — +23 new tests in
tests/test_cycle28_history_reconciliation.py, no existing
test modified. EXTERNAL FIX ROUND final: **1812 tests OK
(skipped=28)** — +4 crash-injection tests (test_22–25, file
now 27 tests); existing tests modified in the fix round,
each with its reason recorded in-test: cycle-28 test_09 and
test_10 (encoded the removed beyond-head excuse reach) and
tests/test_trust_runner.py's supersession-pending shape
(the one production-wired flow that relied on that reach;
now pins the narrowed refusal, exit 6). Suite run note:
pytest is not installed in this environment, so the final
full run used a unittest loader harness over the same
unittest-style test files (1812 run, 0 failures, 0 errors,
skipped=28), uncontended. Real `state/state.json` not
advanced (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
verified identical before/after). `eval/` untouched. No git
commit in this run — the parent verifies and commits.

## What was built

- `trust/history_reconciliation.py` (new): pure
  `find_missing_history` + refusing `reconcile_history`.
  A consumption entry is missing iff it is relevant to the
  candidate (strictly behind it, or at its sequence with a
  different hash) and unaccounted for: pair coverage (the
  operative rule — subsumes the same-id case and the
  primary/recovery pair), a fully bound supersession excuse
  (abandoned id matches, abandoned target fields agree when
  carried, and the replacement side has landed by id+pair,
  by pair coverage, or as the candidate under attempt), or
  the known-unadopted head excuse (binds to the head ENTRY;
  duplicate journal authorisation ids / seqs refuse
  outright). Genesis baseline for no-pin attempts.
  Malformed inputs refuse with SigningError, never skip.
  Provider helpers build fresh-loading journal providers
  from a verifier home (composition seam, cycle-25 warning
  carried in the docstring).
- `trust/pin_adoption.py`: optional provider kwargs on
  PinAdopter (default None = pre-cycle-28 behaviour, no
  claim) and pass-through on build_pin_adopter (the factory
  never derives them from env); step (3b) in
  snapshot_and_adopt reconciles after candidate selection,
  before anything is persisted, authorised or consumed;
  known-unadopted ids derived solely from the pending
  journal's genuine burns; provider failure fails closed as
  PinAdoptionRefused, the reconciliation refusal propagates
  unwrapped with its code. EXTERNAL FIX ROUND (seat-gpt FIX
  0.91; seat-gemini SHIP 0.84, same scenario, non-blocking):
  the known-unadopted head excuse is narrowed to a candidate
  AT the head entry's own sequence — its beyond-head reach
  silently excused an adopted record's disappearance in the
  compound adopted-line-loss + store-restore state, which is
  indistinguishable from a genuine burn at this layer. Four
  crash-injection tests (test_22–25) pin the scenarios both
  external seats named; record:
  internal/cycle28-work/fix-round-gpt.md.
- `trust/runner.py`: the production composition now wires
  both providers in main() via _history_providers(
  verifier_env) (fix round, war-room demand); a missing
  AION_VERIFIER_HOME refuses with the runner's structured
  config refusal naming the variable.
- Docstrings: pin_store.py and pin_ceremony.py each gain a
  cycle-28 sentence naming the detection and its code
  (authority claims unchanged; claim-pin test_16 passes);
  pin_adoption.py gains the reconciliation paragraph
  including the adopt_returned basis and the
  consumption-without-supersession-provider note.

## Honest residuals

- Wholesale pin-directory rollback after a genuine burn
  loses the pending journal and its excuse: a later attempt
  can refuse with no in-system repair procedure. The
  detection failing closed, in the class of the cycle-14
  corrupted-pin-store operator-recovery residual. Named in
  REVIEW-CYCLE-28.md as an open follow-up (operability).
- The external pin-store head anchor (the follow-up's other
  branch) remains unbuilt and named as a future follow-up;
  it would additionally detect lost `advance_pin` movements,
  which leave no consumption-journal trace and are therefore
  invisible to this check (the pin itself is their evidence).
- Provider trust: production uses only the from-home
  helpers (ledger loads recompute hash chains); a
  caller-supplied provider returning a truncated journal is
  trusted as supplied. Tail-truncation resistance rests on
  the journals' external anchors, verified at verifier
  startup (cycles 22/27).
- Direct/factory-built adopters without providers behave
  exactly as before this cycle and make no completeness
  claim (test_17 pins the unwired behaviour). Q2 audit
  (fix round): the only production construction site is
  trust/runner.py main(), which wires both providers; no
  direct PinAdopter construction exists in production code.
- Claim narrowed in the external fix round: a genuine head
  burn followed by a candidate strictly beyond the burn's
  sequence now refuses pin_store_history_incomplete (the
  known-unadopted excuse covers only an at-sequence
  candidate, which can still enter the supersession-pending
  flow). Because the candidate is always the current state,
  a genuine burn whose target the state has already passed
  can no longer enter that flow through the wired adopter:
  it refuses by name and has no in-system repair procedure —
  an operability narrowing accepted to close the
  compound-restore hole (the two states are indistinguishable
  at the reconciliation layer), recorded in
  internal/cycle28-work/fix-round-gpt.md. The runner test
  that pinned the old reach was updated with its reason
  recorded in-test.
- Evidence note (suite flakes): two coordinator full-suite
  runs under heavy parallel load (war-room agents running
  suites concurrently) each failed the same 21 ship-suite
  tests with `attestation_expired` (7 failures + 14 errors,
  test_trust_shipcheck / test_trust_shiptx*); the same suites
  pass standalone, and the coordinator's clean full-suite
  run on the final tree — nothing else active — is the
  1808 OK recorded above (312 s vs the failing runs' ~950 s).
  Attribution to load is a judgement from that pattern, not
  a proof; the failing runs are recorded here, not hidden.

## Staffing

15 coders, 5 pods of 3: Pod A (1, 5, 8) reconciliation core;
Pod B (2, 6, 7) adopter + runner wiring; Pod C (9, 10, 11)
adversarial tests (23); Pod D (3, 4, 15) docstring/claim
updates; Pod E (12, 13, 14) records and brief. Three coder
seats (core / wiring / tests) ran as delegated agents whose
blind critiques amended the design before building (recorded
in design-final.md). War room: 6 internal reviewer seats
from other pods than the slices' builders (rev-r6 forced
dissent), plus the two external seats via the blind brief
(pending the parent's round; verdict provisional until
reconciled).

## Self-improvement delta

The last silent hole in the ceremony audit story is now a
refusal: a restoration-thinned pin-store history was, before
this cycle, indistinguishable from a complete one at every
layer (the unwired attempt on the restored store stops as
ordinary supersession-pending, saying nothing about the
missing record — pinned by test_17); it now refuses at
adoption time, by name, with the missing authorisations
listed, in the production composition. The war room also
improved the mechanism itself: the forced-dissent seat's
reproduced duplicate-id counterexample and two seats'
production-wiring demand both landed as code, and the
re-review seats verified the fixes adversarially rather than
on summary. Remaining follow-ups (not holds):
pin-store head anchoring, lost-advance detection, a
reconciliation repair procedure for wholesale pin-directory
loss, operator-authentication-channel, and the cycles 17+18
recovery-contract document.

---

## Correction pointer (cycle 29)

The claim in this record that an at-sequence candidate "can still enter the supersession-pending flow" was tested in cycle 29 and is NOT composition-true for the wired exact-pair shape: it lands as a burned_unadopted recovery (exit 0). See internal/BUILD-CYCLE-29.md. This pointer is appended, not a rewrite; the original text stands as the historical record.
