# Cycle 23 — DESIGN-FINAL (coordinator rulings)

Date: 2026-11-23. Inputs: design-a.md, design-b.md, design-c.md
(all three seats designed all five workstreams), CROSS-CHECK-16,
CROSS-CHECK-15, BUILD-CYCLE-22. Baseline at cycle start
(59a656a): 1547 tests OK (skipped=28), coordinator-verified.
The rulings below are the build contract; losing positions are
recorded. Cycles 14–16 are NOT re-reviewed or shipped this
cycle. `eval/` is untouched. `core/loop.py` IS touched (R1) —
it is in the Protected Gate's PROTECTED_FILES; the change is
deliberate, minimal, reviewed integration work (the gate
protects against unauthorised self-modification of oversight,
not against a war-room-reviewed integration change), and the
review record must say so and review the loop diff
specifically.

## R1 — WS1: constructor-injected cycle hook (consensus)

- `core/loop.py`: `CoreLoop.__init__(self, state_dir, *,
  cycle_hook=None)` (keyword-only); read-only `cycle_hook`
  property. In `run_one_cycle`, AFTER the persistence
  try/except has completed (the cycle is saved; the snapshot
  restore path must not run for hook failures), if the entry
  is not None and a hook is set, call `hook(entry)` exactly
  once. Hook exceptions propagate UNWRAPPED. No new imports;
  the hook is an opaque callable; loop.py stays stdlib-only.
  Idle (None entry), scan, approve never fire the hook.
  Contract, stated in the loop docstring: "cycle recorded,
  pin pending, alert" — a hook failure never un-records the
  cycle and never corrupts state.
- `trust/pin_adoption.py`: new `pin_cycle_hook(adopter)`
  factory returning a callable(entry) -> AdoptionResult that
  calls `adopter.snapshot_and_adopt()` and, on
  PinAdoptionBurned / PinAdoptionRefused, attaches
  `.cycle_entry = entry` before re-raising (the
  run_one_cycle_and_pin contract, preserved).
  `run_one_cycle_and_pin` REFUSES a hooked loop (ValueError:
  double wiring) and its docstring is updated to say the hook
  is the integrated path and the driver remains for unhooked
  composition.
- `trust/shipcheck.py`: `record_ship` REFUSES a hooked loop
  (`loop.cycle_hook is not None`) with ShipRefused BEFORE the
  transaction opens (seat A's enforcement, over seat B's
  lint-only and seat C's tolerate-and-recover: a
  PinAdoptionBurned is a SigningError, not an
  InvalidTransition, and would strand the ship tx at
  BURN_PENDING with the cycle recorded — refuse instead).
  A lint-style test pins that record_ship's own loop usage in
  the suite stays hookless.
- Live run (test, seat 3): byte copy of the real `state/`
  (state.json seq 13 + calibration) into a sandbox; the WS2
  production home (R2); a fresh sandbox snapshot signing key.
  Exact sequence: (1) direct `snapshot_and_adopt()` → genesis
  `initial_anchor` ceremony at seq 13; (2) one HOOKED loop
  cycle → dense `advance_pin` to 14 (no consumption);
  (3) two hookless cycles → seq 15, 16 unpinned;
  (4) `snapshot_and_adopt()` → `chain_gap_recovery` ceremony
  to 16; (5) `snapshot_and_adopt()` → `already_current`.
  Sandbox cycles run through the public loop API only, with
  valid coders/reviewers/delta; the first sandbox cycle
  records whatever `pick_next()` returns on the copy
  (asserted, not assumed). The test asserts the REAL
  `state/state.json` sha256 is identical before/after. A
  research-mode execution is NOT citable as the live run.

## R2 — WS2: production-mode bootstrap (unanimous)

- No production code changes expected. If composition fails,
  that is a FINDING for the war room, not a silent fix.
- Provisioning harness (tests, seat 3; shared fixture module
  `tests/cycle23_harness.py`, not collected): disposable
  verifier home in a temp dir. Bootstrap order is forced by
  production's INIT refusal: ONE research-mode verifier
  invocation with all INIT flags set (deliberately malformed
  request so no mode body runs; assert the signing ledger
  gained no entries) initialises the anchors `_load_config`
  manages (signing, budgets, ceremony-consumption) on empty
  journals; then INIT keys are REMOVED, `AION_DEPLOYMENT_MODE`
  flips to `production`, and all steady-state env is the full
  allowlist (wiring-required keys + production-required
  ceremony keys: AION_CEREMONY_OPERATORS,
  AION_CEREMONY_EVIDENCE_DIR, AION_CEREMONY_SIGNING_SEED_PATH,
  AION_CEREMONY_CONSUMPTION_ANCHOR_PATH). `AION_PIN_*` adopter
  env is a SEPARATE mapping and must never enter the verifier
  env (negative-tested: production_client refuses it).
- The e2e is the first suite test where the adopter's client
  comes from `production_client` via `build_pin_adopter`:
  genesis ceremony + dense advance + one recovery, end-to-end
  in production mode against the disposable home.
- Claim scope (B1): this proves production MODE under
  same-user spawn on this VM. It does NOT prove production
  DEPLOYMENT: no separate OS user exists here and
  `production_client(launch="wrapper")` is refused by design.
  The 28 deployment-gated skips stay skipped.

## R3 — WS3: schema v2 + bounded recovery chains, cap 2 (unanimous on the bound; A/C mechanism)

Supersedes DECISION-CONSUMPTION-HEAD Addendum 2's one-shot
ruling (Addendum 3 records this; the external seats are asked
to ratify the re-rule — seat-gpt ratified one-shot, so the
brief must flag the change explicitly).

- Versioning seam: `HashChainJournal` gains
  `_allowed_entry_key_sets()` returning
  `(frozenset(_ENTRY_KEYS | EXTRA_KEYS),)` by default;
  `_load` accepts an entry iff its key set is in the allowed
  sets. Default behaviour is byte-identical for every
  existing journal (pinned by the existing suites).
- `CeremonyConsumptionLedger`: allowed sets = v1 (current
  EXTRA_KEYS) and v2 (v1 + {"consumption_kind", "recovery_of",
  "recovery_depth"}); POSITIONAL MONOTONICITY: once a v2
  entry appears, a later v1 entry is corrupt. v1 entries are
  never rewritten or normalised (their hashes are
  anchor-covered). New appends are always v2. v2 fields are
  value-validated at load: consumption_kind ∈
  {"primary", "recovery"}; primary ⇔ recovery_depth == 0 ⇔
  recovery_of == ""; recovery ⇔ recovery_depth ∈
  1..MAX_RECOVERY_DEPTH and recovery_of is a non-empty
  authorisation id. `kind` stays "consume".
- `MAX_RECOVERY_DEPTH = 2` (named constant in
  trust/ledger.py): a movement is consumable at most 3 times
  — primary + 2 recoveries. Depth 1 covers a single adopt
  fault; depth 2 one full incident's double fault; a third
  interruption indicates a broken adopter, so the
  movement-terminal backstop stays. Exhaustion is never a
  deadlock: the next snapshot sequence takes a primary
  `chain_gap_recovery` (test-pinned).
- Issuance binding (A/C, load-bearing): the
  `CeremonyAuthorisationLedger` gets the same dual-set
  treatment with v2 = v1 + {"recovery_of"} (same positional
  monotonicity). In verifier_main's `ceremony_authorise`,
  step (5b) already computes the burn match for
  `burned_unadopted`; the mode passes that match's
  authorisation_id into `append_authorisation(...,
  recovery_of=...)` ("" for non-recovery reasons). The
  binding is verifier-computed from its own journal — never
  read from the request (request key set unchanged; envelope
  format unchanged). The signing-ledger mirror is NOT
  widened.
- Consume: the mode reads the issuance entry by
  authorisation_id (membership already cross-checked) and
  threads its `recovery_of` into `check_head` /
  `append_consumption`, which derive lineage INSIDE the
  retry loop from freshly reloaded entries:
  - reason != burned_unadopted → kind "primary",
    recovery_of "", depth 0.
  - reason == burned_unadopted → the recovery exception
    fires IFF the bound recovery_of equals the CURRENT head
    entry's authorisation_id AND candidate + old pin exactly
    equal the head's target/old (match_head_burn semantics)
    AND head depth < MAX_RECOVERY_DEPTH. The new entry is
    kind "recovery", recovery_of = bound id, depth = head
    depth + 1.
  - Head depth derivation: v2 head → its recovery_depth;
    v1 head → derived by the pair-scan, which SURVIVES ONLY
    as this v1 derivation (exact under cycles 21–22 history:
    a v1 pair occurs at most twice; first occurrence = depth
    0, second = depth 1). The pair-scan is deleted as the
    ruling mechanism for v2 heads.
  - Bound burn no longer head (the race loser) →
    AlreadyConsumedError (candidate == head target, not a
    recovery). Depth cap reached with the bound burn at head
    → AlreadyConsumedError (the movement is consumed to its
    cap). Exactly-one-success under concurrency is preserved
    and race-tested (GPT's cycle-22 requirement: the race
    test must show exactly one consumption lands for two
    authorisations bound to the SAME burn; a fresh recovery
    bound to the WINNER's burn may then land at depth+1).
- Authorise step (5b) also refuses
  (`ceremony_recovery_unproven`) when the matched burn's
  derived depth >= MAX_RECOVERY_DEPTH — never issue an
  envelope that cannot consume.
- `match_head_burn` keeps its signature (authorise 5b and
  consume both use it for burn identification); its one-shot
  pair-scan clause is removed and replaced by the depth
  derivation above. Docstrings rewritten to the v2 ruling
  (the cycle-22 wording sweep discipline applies: no stale
  one-shot claims anywhere, including pin_ceremony.py's
  residual summary if it states one-shot).

## R4 — WS4: crash/restart coverage (B's method rules; one production change)

- Method rules: the post-consume/pre-adopt death case and
  the concurrent-adopters case MUST be true subprocess tests
  (child process, barrier, SIGKILL). State-surgery cases
  (corruption/loss) are labelled as such. Any monkeypatch/
  seam-based test class is named *SeamTests and may not be
  cited as crash coverage. No production fault seams.
- The seven scenarios, pinned outcomes:
  1. Death after consumption, before adoption (subprocess):
     restart completes via `adopt_returned` (pair retained
     by the caller) OR, pair discarded, via a fresh
     `burned_unadopted` recovery at depth 1 — both pinned.
  2. Death during pending-journal persistence (torn last
     line): journal reads skip the torn tail; behaviour
     degrades to refusal/liveness loss, NEVER unsafe
     movement. (Program order — authorised-line append
     completes before consume begins — makes
     consume-committed-without-authorised-line impossible;
     the test pins the torn-tail read behaviour.)
  3. Pending-journal corruption (garbage mid-file): same
     degradation class as (2); F4.2 stays open as a named
     residual (detection can be lost; burn validity cannot).
  4. Side-file (snapshot-candidate.json) loss on unchanged
     state: PinAdoptionRefused (a fresh signing cannot
     reproduce the pin's hash); pin resumes on the next
     cycle. NOT a lost_pin ceremony.
  5. Restart with returned pair available vs discarded:
     available → adopt_returned, no new consumption;
     discarded → burned_unadopted recovery, one new
     consumption, no lost_pin anywhere.
  6. Recovery-after-recovery-burns under cap 2: depth 1 burn
     unadopted → depth 2 recovery lands; depth 2 burn
     unadopted → movement terminal (AlreadyConsumedError /
     ceremony_recovery_unproven), liveness resumes at the
     next snapshot sequence via primary chain_gap_recovery.
  7. Concurrent adopter instances on one pin store
     (subprocess, barrier): exactly one adoption lands; the
     loser surfaces PinStoreBusy/PinMovedError as a refusal
     (PinAdoptionRefused on the advance path), never a
     corrupt or double-adopted store; store verifies after.
- ONE production change (seat C's detection line, scoped by
  the coordinator): `PinAdopter._reanchor` appends a journal
  line with phase "authorise_pending" (ceremony_id,
  candidate seq/hash, old-pin projection; NO envelope)
  BEFORE the authorise call. It is a detection/audit aid
  only: it does NOT count as a burn in `_unadopted_burns`,
  and a pending line with no authorised line pins the
  behaviour "next attempt proceeds with a fresh primary
  ceremony" (nothing could have consumed — program order).
  The war room may strike this change if it judges it noise;
  if struck, scenario 2's record must say why detection was
  rejected.

## R5 — WS5: anchored recording path + real anchors; real state NOT advanced (unanimous)

- `trust/shipcheck.py`: new `anchored_record_ship(loop, *,
  root, manifest, signed, signing_key, ledger, coders,
  reviewers, delta, release, anchor_path, tx_anchor_path,
  expected_signer_id=None, expected_attestation=None,
  recorded_at="")`. It takes NO expected_ledger_head
  parameter — its absence is the cross-check. It verifies
  BOTH anchors and requires CURRENCY: each anchor's recorded
  head/count must equal the ledger's CURRENT head/length (a
  merely-verifying stale prefix anchor refuses — deriving
  the head from a prefix would be circular). The expected
  head is derived from the ship anchor and passed to
  `record_ship` (which still verifies + advances the ship
  anchor post-finalise); after record_ship returns
  COMMITTED, the wrapper advances the ship-tx anchor with
  `update_anchor` (record_ship's diff stays minimal: the R1
  hooked-loop refusal + a docstring line naming
  anchored_record_ship as the production recording path).
  If both a caller head and an anchor were ever supplied,
  neither overrides the other — the anchored path simply
  has no caller-head input.
- Sandbox proof (seat 2 tests): in a temp state/ledger copy,
  record a real cycle through anchored_record_ship end-to-
  end; then roll the ship ledger back one entry → the next
  anchored attempt refuses at anchor verification, pre-burn,
  nothing spent; delete the ledger → refused as
  anchor_missing_established_ledger class. Tx-anchor
  currency is asserted after the recording.
- REAL anchors initialised this cycle (seat 2, operator
  act): `state/anchors/ship.anchor.json` (kind "ship") and
  `state/anchors/ship-tx.anchor.json` (kind "ship-tx")
  against the real `state/ship-ledger/`, via
  `initialise_anchor` with its nonempty-ledger ceremony,
  after verifying the preconditions from design A (ship
  ledger entries + head transcribed into BUILD-CYCLE-23;
  tx journal all-terminal). Anchor files live OUTSIDE the
  ledger dir and are committed to git — joint ledger+anchor
  rollback is then detectable against git history. Claim
  capped at exactly that: same-disk, same-user; NOT
  "outside writable storage" in the deployment sense.
  A currency tripwire test asserts the real anchors verify
  CURRENT against the real ledgers (it is supposed to fail
  if a future recording forgets the anchor advance).
- REAL `state/state.json` is NOT advanced this cycle
  (unanimous, three independent reasons on record in the
  designs: recording cycle 23's item as loop cycle 14 while
  14–16 are HELD falsifies loop history ordering;
  self-reference — the manifest cannot cover a tree that
  includes its own recording cycle's record; cycle 23 is
  provisional and its WS3 re-rules a SPLIT external decision,
  so recording its item done before ratification repeats
  what the 14–16 hold prevents). WS5 completion claim is
  therefore: the anchored, caller-pin-free recording path
  exists, is proven end-to-end in the sandbox, and the real
  ledgers' heads are anchored and tripwired. The precise
  remaining blocker for recording cycles 14+ in the real
  state — per-cycle signed ship packages (manifest +
  decision + attestation + release) for each cycle in
  order, gated on cycles 14–16 external re-review — is
  recorded in BUILD-CYCLE-23.

## File ownership (disjoint)

- Seat 1 (WS3): trust/ledger.py, trust/verifier_main.py,
  tests/test_trust_consumption_schema_v2.py (new); re-pins in
  tests/test_signing_ceremony_recovery.py,
  tests/test_trust_ceremony_consumption.py (one-shot tests
  re-pinned to cap-2 semantics, citing Addendum 3).
- Seat 2 (WS1 + WS5 + R4 production change): core/loop.py,
  trust/pin_adoption.py, trust/shipcheck.py,
  tests/test_core_loop_hook.py (new),
  tests/test_cycle23_ship_anchors.py (new, incl. the real-
  anchor tripwire), state/anchors/*.json (new, real act).
- Seat 3 (WS2 + WS4 tests + live run): tests/cycle23_harness.py
  (new, shared, not collected), tests/test_trust_production_e2e.py,
  tests/test_cycle23_live_run.py, tests/test_trust_pin_adoption_crash.py
  (+ a non-collected child helper). NO production code; gaps
  are reported as findings, not silently fixed.
- API names are fixed by this contract so seats build in
  parallel: `CoreLoop(state_dir, *, cycle_hook=None)`,
  `pin_cycle_hook(adopter)`, `anchored_record_ship(...)`,
  `MAX_RECOVERY_DEPTH`, journal phase "authorise_pending".
