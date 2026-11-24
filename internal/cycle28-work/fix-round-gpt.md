# Cycle 28 — fix round (external seats)

External verdicts on the blind brief
(internal/CROSS-CHECK-BRIEF-CYCLE-28.md):

- seat-gpt — **FIX 0.91**. Q1 blocking: the known-unadopted
  head excuse is an assertion, not proof. Scenario: authorisation
  A consumed (consumption-journal head) → movement adopted and
  recorded in pin-store history → pending journal still lists A
  as unadopted → pin-store document restored to a pre-A
  generation → later attempt beyond A reconciles: A is head +
  in `known_unadopted_authorisation_ids` → excused → the exact
  record whose disappearance should be detected is silently
  excused. Demanded: evidence a successfully adopted
  authorisation cannot remain eligible for the excuse, with
  crash-injection tests (interrupted cleanup, independent
  pending-journal rollback). Q2 accepted with condition: audit
  that every production adoption entry point wires the
  providers. Q3: reconciliation was the right branch, no anchor
  demanded.
- seat-gemini — **SHIP 0.84** (targeted follow-up hardening).
  Independently constructed the SAME stale-pending head
  scenario (adopted ceremony still listed in the pending
  journal; store restored to a pre-adoption generation; head
  entry excused despite the missing record) but rated it
  non-blocking, noting the excuse is head-only so it cannot
  mask gaps behind the head, and suggesting pending-journal
  lifecycle tightening. Accepted wiring-dependent detection
  (same unwired-caller caution as seat-gpt's Q2 condition) and
  agreed reconciliation was the right branch over a head
  anchor.

Convergence: both external seats constructed the same
scenario. Per the standing rule, an external SHIP does not
override a FIX — seat-gpt's FIX governs, the cycle stayed
PROVISIONAL/FIX, and this round closes the scenario both
seats named.

## Code check of the excuse's source (verified in-tree)

`trust/pin_adoption.py` appends pending-journal phases in the
order consumed → `store.adopt()` → "adopted"; the adopted
append's OSError is deliberately swallowed (reanchor path
~lines 1353–1365, main path ~1756–1778, `adopt_returned`
~1798) because the journal is a detection aid, never
authority. `_genuine_burn_entries()` excludes ceremonies whose
merged phases include "adopted", and
`_known_unadopted_authorisation_ids()` derives solely from
it. Consequences:

- A store-document-only restore with an INTACT pending
  journal does NOT excuse A (its slot carries "adopted").
- The residual hole is COMPOUND: adopted-line loss (crash in
  the adopt→adopted window / swallowed OSError / pending-
  journal rollback to a pre-adopted generation) COMBINED with
  a store-document restore to a pre-A generation. Then A's
  slot reads as a genuine burn, A is the consumption head,
  and a beyond-A candidate is excused. At the reconciliation
  layer this state is indistinguishable from a genuine burn
  by any evidence the pending journal carries — the excuse's
  premise (consumed, never adopted) is exactly what the lost
  line would have attested. No corroborating guard inside
  this layer can separate the two; the sound fix is to narrow
  the excuse's reach (below).

## Reproduction (failing-first, pre-fix behaviour recorded
## BEFORE the code change)

New integration tests in
tests/test_cycle28_history_reconciliation.py (test_22–25),
run against the pre-fix tree:

- (a) test_22 — successful gap adoption to seq 3, adopted
  pending line stripped (the fault-injected/lost append),
  store restored to the genesis generation, state at seq 4,
  wired attempt: **HOLE REPRODUCED** — no
  HistoryReconciliationRefused; reconciliation excused A and
  the attempt proceeded into the ceremony, stopping as
  PinSupersessionPendingApproval. Pure-function shape also
  reproduced: head entry + known-unadopted + candidate seq 5
  (beyond the head's seq 3) → find_missing_history returned
  () (excused).
- (b) test_23 — store-document-only restore, pending journal
  intact: **already refuses** pin_store_history_incomplete
  naming A (pre-fix PASS). The parent code check above is
  confirmed by test.
- (c) test_24 — independent pending-journal rollback to its
  pre-A generation COMBINED with the store restore: **already
  refuses** naming A (A is not known-unadopted by any
  surviving evidence; pre-fix PASS). test_25 — pending-journal
  rollback ALONE, store intact: A's store record pair-covers
  A's journal entry, reconciliation does not refuse, the
  contiguous seq-4 candidate advances (pre-fix PASS).

So the only excused-and-wrong case is (a): adopted-line loss
combined with a store restore, excused for a candidate
BEYOND the head entry.

## Fix (smallest sound change)

Narrow the known-unadopted head excuse in
`find_missing_history` (trust/history_reconciliation.py): the
excuse now applies only when the head entry's
`new_cycle_seq` EQUALS the candidate sequence — i.e. the
attempt is a rival/recovery movement AT the head burn's own
sequence, which cannot adopt past the head without the
verifier's consumption-head rules forcing that burn's
recovery (pair coverage) or a bound supersession decision
(which then excuses via the supersession rule on the resume
attempt). A candidate strictly BEYOND the head entry is
never excused by this rule: adopting past an unaccounted
head is exactly the movement detection must refuse.

Why not keep the beyond reach: check of legitimate flows —
the excuse's beyond reach had no production flow that
ADOPTS past a head burn without recovery/supersession (the
verifier's head rules forbid that adoption regardless); its
effect was to let the attempt proceed to the downstream
supersession-pending stop instead of refusing — and in the
compound-restore state that same reach silently excused an
adopted record's disappearance. CORRECTION to this round's
first flow check: one production-wired flow DID rely on the
beyond reach to reach that stop —
tests/test_trust_runner.py's supersession-pending shape
(genuine 13→15 burn, candidate 16) failed on the narrowed
tree (exit 6 instead of 7). At the reconciliation layer the
genuine-burn state and the compound-restore state are
identical in every source available (store document,
pending journal, consumption journal), so no corroborating
guard inside the layer can keep one and refuse the other;
per the fix mandate the GPT scenario must refuse, so the
runner test was updated with the change and reason recorded
in-test: the wired adopt step in that shape now refuses
pin_store_history_incomplete (exit 6), and a beyond-head
genuine burn becomes an operator-reconciliation residual
(named in BUILD-CYCLE-28.md). The supersession-pending flow
remains reachable for a candidate AT the head burn's own
sequence (at-sequence excuse retained; supersession suites
cover the flow). Within cycle 28 the two pure tests that
encoded the beyond reach (test_09, test_10) are likewise
updated with the narrowing recorded — claim narrowing, not
silent weakening: the claim is now "a known-unadopted head
excuses only a candidate at its own sequence; beyond it, an
unaccounted head refuses".

This also fully answers seat-gemini's hardening suggestion:
rather than tightening the pending journal's lifecycle (the
journal remains a non-authoritative detection aid whose
adopted append may still be lost), the excuse no longer
trusts that journal for the beyond-head reach at all.

Post-fix expectations: test_22 refuses
pin_store_history_incomplete naming A; test_23/24/25
unchanged; test_09/test_10 updated to the narrowed claim.

## Post-fix results (recorded after the change)

- test_22 now REFUSES pin_store_history_incomplete naming A
  (the GPT scenario is closed); test_23/24/25 pass unchanged;
  test_09/test_10 pass on the narrowed claim.
- First full-suite run on the narrowed tree: 1812 run, 1
  failure — tests/test_trust_runner.py's
  supersession-pending shape, the production-wired flow
  discussed in the correction above. That test was updated
  (renamed, reason recorded in-test) to pin the narrowed
  refusal. Second full-suite run: **1812 run, 0 failures,
  0 errors, skipped=28** (unittest loader harness — pytest
  is not installed in this environment; the test files are
  unittest-style). Cycle-28 module: 27 tests OK.
- Real state/state.json sha256 verified unchanged after all
  runs: 86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39.
- No git commit/push in this round.

## Q2 audit — production construction sites

Enumerated every construction of PinAdopter /
build_pin_adopter outside tests:

- `trust/runner.py` main() — the production composition:
  builds via build_pin_adopter WITH both providers from
  `_history_providers(verifier_env)` (cycle-28 fix round).
  WIRED.
- `trust/pin_adoption.py` build_pin_adopter itself — factory:
  pass-through only, never derives providers from env
  (cycle-25 separation). It makes no completeness claim on
  its own; its one production caller is the runner, above.
- Direct `PinAdopter(...)` constructions: NONE in production
  code — all remaining sites are tests / crash-child harness
  (tests/, tests/cycle23_crash_child.py), which are
  non-production and several intentionally pin the unwired
  behaviour (cycle-28 test_17).

Conclusion: every production adoption entry point wires the
providers; no unwired production path exists, and no
additional wiring change was needed in this round.
