# Build record — Cycle 23: production integration of the ceremony line

Date: 2026-11-23. Mandate: CROSS-CHECK-16 — both external
seats converged on production integration as the remaining
gap (seat-gpt FIX 0.91 against unconditional closure only;
seat-gemini FIX 0.84, one-shot not ratified, cycles 14–16
held). This cycle: wired the adopter into the loop, ran it
live, stood up production MODE end-to-end, replaced the
one-shot pair-scan with a versioned lineage schema and a
re-ruled recovery bound, covered the crash/restart
boundary, and completed the anchored recording path for
the ship ledger. Cycles 14–16 were NOT re-reviewed or
shipped; `eval/` is untouched; the real `state/state.json`
was NOT advanced (WS5 ruling, below). Cycle 23 is
PROVISIONAL pending the external seats on
CROSS-CHECK-BRIEF-CYCLE-23.md.

## Headline claims — with their qualifiers, in substance

The adopter is integrated into the loop: `CoreLoop` takes
a constructor-injected `cycle_hook`, and
`trust.pin_adoption.pin_cycle_hook` pins every recorded
cycle's snapshot through the `PinAdopter`. The composition
is proven in production MODE (via `production_client` /
`build_pin_adopter`, same-user spawn, disposable verifier
home) and in a live run against a BYTE COPY of the real
`state/` directory: pin 13 → 14 (hooked advance) → gap
ceremony to 16, exactly 2 consumptions, real state hash
unchanged. Qualifiers that stay attached: the only callers
of `pin_cycle_hook` / `build_pin_adopter` in the tree are
still tests — there is no non-test production entry point
constructing a hooked loop yet, so "zero production
callers" is dead as a wiring claim but a caller-count
caveat survives; the real state dir was not advanced; and
production MODE under same-user spawn is not production
DEPLOYMENT (no separate OS user on this VM; the wrapper
launch is refused by design). Item (3)'s scoped form is
unchanged from cycle 22 except as WS3/WS5 below change it.

## Design process

3 coder seats designed together (design-a/b/c in
internal/cycle23-work/) — notably, all three independently
chose bounded recovery chains at depth cap 2 and the
per-entry dual key-set versioning. Coordinator rulings
R1–R5 in internal/cycle23-work/DESIGN-FINAL.md are the
build contract. Build in disjoint file ownership (3
seats) + a coordinator-commissioned fix seat for two
build-phase findings. War room: 6 reviewer seats, blind
scores locked in state/calibration/calibration.json
(subject `cycle-23-review`) before reconciliation, one
forced-dissent seat (rev-r6). First round split (2 SHIP /
4 FIX) → fix round → re-review (subject
`cycle-23-rereview`) → two targeted rev-r1 strengthenings
→ reconciled unanimous SHIP. Detail: REVIEW-CYCLE-23.md.

## Workstream 1 — loop integration + live run (R1)

- `core/loop.py` (PROTECTED FILE — see the review
  record): keyword-only `cycle_hook=None`, read-only
  property, one call after the persistence try/except with
  the recorded entry; hook exceptions propagate unwrapped;
  no new imports. Contract: "cycle recorded, pin pending,
  alert". The full loop diff is reproduced in
  REVIEW-CYCLE-23.md.
- `trust/pin_adoption.py`: `pin_cycle_hook(adopter)`
  (attaches `.cycle_entry` to PinAdoptionBurned/Refused);
  `run_one_cycle_and_pin` refuses a hooked loop (double
  wiring). `trust/shipcheck.py`: `record_ship` refuses a
  hooked loop with ShipRefused BEFORE the transaction
  opens (a PinAdoptionBurned is not an InvalidTransition
  and would strand the ship tx at BURN_PENDING).
- Live run (tests/test_cycle23_live_run.py): byte copy of
  real `state/` (state.json seq 13 + calibration), WS2
  production home, fresh sandbox snapshot key. Sequence:
  genesis `initial_anchor` at 13 → one hooked cycle
  (records `ledger-head-anchoring`, the copy's pick_next)
  → dense advance to 14 → two hookless cycles (15, 16) →
  `chain_gap_recovery` ceremony to 16 → `already_current`.
  Exactly 2 consumptions; real `state/state.json` sha256
  identical before/after
  (86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39).

## Workstream 2 — production-mode end-to-end (R2)

- No production code changes were expected; composition
  FAILED at first, and the failure was reported as a
  finding (seat 3) and fixed by a coordinator-commissioned
  fix seat — it was not silently patched by the seat that
  found it, and it is not part of DESIGN-FINAL's original
  build scope: **the ceremony key-pin namespace collision**
  (trust/client.py). `production_client` mandates the gate
  key pin `key-<16 hex>`; `VerifierClient._check_pins`
  applied that one pin to ceremony envelopes, whose key id
  is the Ed25519 `pub-<16 hex>` — so a correctly
  gate-pinned production client refused EVERY production
  ceremony. The defect was latent since cycle 22 (whose
  adopter was exercised only through research-mode
  fixtures pinned with the `pub-` id). Fix:
  `_check_ceremony_pins` binds the ceremony response to
  the pinned `CeremonyPublicKey`'s key id + the signer
  pin; gate/attestation checks unchanged; refusal is
  explicit when no ceremony public key is pinned. Finding
  left open: `production_client` does not REQUIRE
  `authorisation_public_key` (a production client can be
  built that refuses all ceremonies locally).
- Harness (tests/cycle23_harness.py): disposable home;
  bootstrap is ONE research-mode invocation with all INIT
  flags set (production refuses INIT at two layers; the
  invocation's gate body refuses at its first key-set
  check before any signing/budget/ledger mutation — the
  harness asserts the signing ledger gained no entries and
  all three anchors exist), then INIT stripped, mode
  flipped to production. E2E (tests/
  test_trust_production_e2e.py): genesis ceremony + dense
  advances + a `burned_unadopted` recovery, all through
  `build_pin_adopter`; negative pins for `AION_PIN_*` in
  the verifier env and for each INIT flag.

## Workstream 3 — schema v2 + bounded recovery (R3)

Full ruling in DECISION-CONSUMPTION-HEAD.md Addendum 3,
which supersedes Addendum 2's one-shot rule. In brief:
per-entry v1/v2 key sets with positional monotonicity
(`HashChainJournal._allowed_entry_key_sets()` seam,
byte-identical default for all other journals); lineage
fields `consumption_kind` / `recovery_of` /
`recovery_depth`; the issuance journal records the
`recovery_of` binding at authorise step (5b) from the
verifier's own burn match; consume derives lineage inside
the retry loop; `MAX_RECOVERY_DEPTH = 2`; load-time
coherence (immediate-predecessor grounding, no primary
re-root, duplicate authorisation_ids corrupt, v1 pair
cap 2). The pair-scan survives only as the v1 head-depth
derivation. The SUPERSEDE rule (candidate strictly ahead
of the head may carry a behind-head old pin; never for
`burned_unadopted`; journal-known old-pin seqs are
hash-bound) is recorded as a designed ruling in Addendum
3 in plain words and put to the external seats as its own
brief question. Cycle-22 one-shot tests were re-pinned to
cap-2 semantics (citing Addendum 3); T8′'s third leg was
re-pinned to the supersede semantics by the coordinator
(the adoption-side context binding that protects the live
pin in that shape is now pinned composed, end-to-end, by
test_t8_composed_supersede_adopt_refusal_ahead_variant,
mutation-verified by rev-r2).

## Workstream 4 — crash/restart coverage (R4)

tests/test_trust_pin_adoption_crash.py +
tests/cycle23_crash_child.py. Labelling discipline (this
is the citable scope): TRUE CRASH coverage exists for
scenario 1 (subprocess, SIGKILL after the consumption
commit, before adoption — the barrier is downstream of
the verifier commit by construction) and scenario 7
(subprocess race on one pin store; the datum is the
loser's refusal, so no kill). Scenarios 2–4 are STATE
SURGERY (torn/corrupt pending journal, side-file loss).
Scenarios 5–6 are SEAM tests (RecoverySeamTests) pinning
recovery SEMANTICS, not crash behaviour. Scenario 7 pins
the PinAdoptionRefused surface, not the Busy-vs-Moved
cause (rev-r5 F5 caveat). Outcomes pinned per R4,
including: torn journal tails degrade to refusal/liveness
loss only; side-file loss on unchanged state is a
PinAdoptionRefused (never a `lost_pin` ceremony — now
asserted against the store history explicitly); cap-2
chain [primary, recovery 1, recovery 2] with the movement
terminal at the cap and liveness at the next sequence via
supersede. One production change: the `authorise_pending`
pending-journal line (detection aid only; never counts as
a burn), its append wrapped to PinAdoptionRefused on
OSError (fix round).

## Workstream 5 — ledger-head-anchoring (R5)

- `trust/shipcheck.py`: new `anchored_record_ship(...)` —
  the production recording path. It takes NO
  `expected_ledger_head` parameter; it verifies the ship
  and ship-tx anchors AND their currency (anchor head/seq
  must equal the journals' current head/length — a
  merely-verifying stale prefix refuses), derives the
  expected head from the ship anchor, delegates to
  `record_ship`, and advances the ship-tx anchor after
  COMMITTED. Sandbox proof: end-to-end recording, ledger
  rollback refused pre-burn with nothing spent, deleted
  ledger refused, stale-prefix anchors refused.
- REAL anchors initialised (operator act, this cycle):
  `state/anchors/ship.anchor.json` (kind "ship", seq 4,
  head 6911dff48f3e325255acf3c490908cf8917c3e121f8cd998a80f88d2ab572870)
  and `state/anchors/ship-tx.anchor.json` (kind "ship-tx",
  seq 6, head 7679d7c134d4c23b5509cb7dc5410c8f7a4d91794122ec1585fcdafa8ce09738)
  against the real `state/ship-ledger/` (ship ledger: 4
  entries — burn/finalise for cycle 8 and cycle 13; tx
  journal: 6 entries, single transaction, COMMITTED).
  Anchors live outside the ledger dir and are committed to
  git with this cycle: joint ledger+anchor rollback is
  detectable against git history. Claim capped at exactly
  that — same disk, same user; NOT "outside writable
  storage" in the deployment sense. A currency tripwire
  test guards the real anchors.
- The real `state/state.json` was NOT advanced.
  Remaining blocker for recording cycles 14+ in the real
  state, stated precisely: each cycle in order needs its
  own signed ship package (tree manifest + gate decision
  + verifier attestation + release record) presented to
  `anchored_record_ship`, and cycles 14–16 are HELD
  pending external re-review — recording cycle 23's item
  (`ledger-head-anchoring`, the pickable item) as loop
  cycle 14 ahead of them would falsify the loop's history
  ordering. When cycle 23 is eventually recorded,
  `core/loop.py` must appear in its changed paths as a
  protected-path item (rev-r3's standing obligation).

## Test totals

Baseline at cycle start (59a656a): 1547 OK (skipped=28).
Final full suite: **1620 tests OK (skipped=28)** —
`python3 -m unittest discover -s tests`, zero failures,
coordinator-run on the final tree. Skips are the
documented deployment-gated set (deployment not
provisioned on this machine).

## Open after cycle 23

- External seats on CROSS-CHECK-BRIEF-CYCLE-23.md: item
  (3) closure form; cap-2 ratification; the supersede
  rule as its own question; cycles 14–16 re-review.
- Named residuals: `recovery_of=None` sentinel binds
  direct in-process ledger callers (and any v1 issuance
  leftover) to the head burn — the verifier mode always
  threads an explicit value for v2 issuances (rev-r6
  dissent, preserved); the adopter's unanchored pending
  journal (F4.2 — detection can be lost, burn validity
  cannot); the issuance journal remains unanchored
  (follow-up `ceremony-journal-anchoring`, narrowed to it
  in cycle 22); `production_client` not requiring
  `authorisation_public_key`; no non-test entry point
  constructs a hooked loop yet; deployment not
  provisioned on this machine.
