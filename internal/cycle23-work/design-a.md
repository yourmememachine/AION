# Cycle 23 — Design A (DESIGN SEAT A)

Scope: production integration of the ceremony line. Five
workstreams, convergent from both external seats
(CROSS-CHECK-16): WS1 loop integration + live run, WS2
production-mode end-to-end, WS3 consumption-journal schema
v2 with explicit recovery lineage and a re-ruled recovery
bound, WS4 crash/restart coverage across the multi-artifact
boundary, WS5 ledger-head-anchoring completion.

Hard constraints honoured throughout: cycles 14–16 are NOT
re-reviewed, NOT shipped, and NOT recorded in loop state by
anything in this design. `core/loop.py` is in the Protected
Gate's `PROTECTED_FILES` (mirrored in
`trust/pathpolicy.py:GATE_PROTECTED_FILES`); its change is
minimal, stdlib-only, no-network, and changes no existing
behaviour when the new option is unused. No production
test-only fault seam is added anywhere: WS4 injects faults
from tests, subprocesses, and filesystem surgery only.

Baseline: commit 59a656a, 1547 tests OK (skipped=28). Every
workstream below ends with the full suite green and the skip
count still 28 (the deployment-gated set; nothing in this
cycle provisions the real deployment, so nothing un-skips).

Facts this design is grounded in (verified by reading the
code, not the briefs):

- `CoreLoop.run_one_cycle` (core/loop.py:417) persists the
  cycle in a single `save()` inside a try/except that rolls
  back in-memory state on failure, then returns a deepcopy of
  the history entry; it returns `None` when idle. `save()`
  (loop.py:304) is write/fsync/replace/dir-fsync.
- `PinAdopter.snapshot_and_adopt` (trust/pin_adoption.py)
  already implements capture → classify → advance / ceremony
  / refuse, the computed reason, `PinAdoptionBurned` (with
  returned pair) / `PinAdoptionRefused`, `adopt_returned`,
  and the driver `run_one_cycle_and_pin`, whose documented
  contract is already "cycle recorded, pin pending, alert".
  What is missing is only a sanctioned way for the loop
  itself to invoke it, and a live run.
- `record_ship` (trust/shipcheck.py) also calls
  `loop.run_one_cycle`, catches only `InvalidTransition`
  around it, and drives a `ShipTxJournal` state machine
  (PREPARED → … → COMMITTED) around the call. This makes the
  loop hook's interaction with `record_ship` a real hazard,
  specified in §1.3.
- `HashChainJournal._load` (trust/ledger.py:121) enforces
  `set(data) == {"entries"}` at the top level and
  `set(entry) == _ENTRY_KEYS | EXTRA_KEYS` per entry
  (_ENTRY_KEYS = {seq, kind, recorded_at, prev_hash,
  entry_hash}). Any key-set change is therefore a load-time
  format decision for every journal subclass, and rewriting
  existing entries is impossible without breaking their
  `entry_hash` chain and every anchor prefix that names them.
- `CeremonyConsumptionLedger` (ledger.py:693): EXTRA_KEYS =
  {authorisation_id, ceremony_id, operator_id,
  old_cycle_seq, old_payload_hash, new_cycle_seq,
  new_payload_hash, evidence_hash, consumed_at};
  `match_head_burn` (ledger.py:792) is head-only and
  implements one-shot by scanning earlier entries for the
  same (old, new) pair; `check_head` (ledger.py:837) grants
  the `burned_unadopted` scoped exception only through
  `match_head_burn`; `append_consumption` (ledger.py:912)
  re-checks single-use + head rules inside a bounded
  reload-retry loop — the commit point.
- Authorise step 5b (trust/verifier_main.py:2516) proves a
  `burned_unadopted` recovery via `match_head_burn` and
  refuses with the single code `ceremony_recovery_unproven`;
  consume (`_mode_ceremony_consume`, verifier_main.py:2597)
  checks issuance presence at step (6) via
  `CeremonyAuthorisationLedger.find_by_authorisation_id`,
  head rules at (7), and commits at (8) in the order
  append → consumption-anchor → mirror → signing-anchor.
- Real state (read 2026-11-23): `state/state.json` at
  cycle_seq 13 (sha256
  86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39),
  calibration at `state/calibration/calibration.json`
  (sha256 242c9f05ac2e433544eb19e5e37e752ff51ab1d8a8b11bd228ba131145993e93);
  `pick_next()` on the real backlog returns
  `ledger-head-anchoring` (leverage 6.5, seq 20 — highest
  leverage, lowest seq among the 6.5 ties).
  `state/ship-ledger/ship-ledger.json` has 4 entries, head
  6911dff48f3e325255acf3c490908cf8917c3e121f8cd998a80f88d2ab572870,
  last kind `finalise`; `ship-tx.json` has 6 entries. No
  anchor files exist for either.

---

## WS1 — Loop integration + live run

### 1.1 The hook: exact change to core/loop.py

One constructor parameter, one attribute, one property, one
call site. Nothing else in the file changes; no new imports
(the file stays stdlib-only — it already is — and gains no
network, subprocess, or signing/trust import; the hook is an
opaque callable the loop never inspects).

```python
def __init__(self, state_dir, *, cycle_hook=None):
    if cycle_hook is not None and not callable(cycle_hook):
        raise ValueError("cycle_hook must be callable or None")
    self.state_dir = Path(state_dir)
    self.state_dir.mkdir(parents=True, exist_ok=True)
    self.state_path = self.state_dir / "state.json"
    self._cycle_hook = cycle_hook
    self.state = self._load()

@property
def cycle_hook(self):
    """The injected post-cycle hook, or None. Read-only:
    record_ship consults it (§1.3)."""
    return self._cycle_hook
```

In `run_one_cycle`, after the existing try/except block (i.e.
after `save()` has succeeded and the state is durable) and
before `return copy.deepcopy(entry)`:

```python
if self._cycle_hook is not None:
    self._cycle_hook(copy.deepcopy(entry))
return copy.deepcopy(entry)
```

(The existing final line already returns a deepcopy; the
build seat restructures it to compute the return value once.)

Rejected alternatives:

- **Subclass / wrapper loop in trust/**: a `PinningLoop`
  subclass outside the protected file avoids touching
  loop.py at all, but then the sanctioned object is no longer
  `CoreLoop` — every existing caller (`record_ship`, the
  drivers, the tests) constructs `CoreLoop`, and a subclass
  invites silent divergence between "the loop" and "the
  pinning loop". The mandate from both external seats is to
  wire the adopter into `core/loop.py`; a 6-line injected
  hook is smaller and more honest than a parallel class.
- **Hook inside the try block, before `save()`**: the pin
  attests state bytes; a snapshot taken before the cycle is
  durable attests bytes that may never exist on disk if
  `save()` then fails. Post-save is the only sound position
  (it is also the ordering `run_one_cycle_and_pin` already
  documents: "the cycle persists in state BEFORE the pin can
  move").
- **Loop catches hook exceptions and returns a status**: the
  loop cannot classify `PinAdoptionBurned` vs
  `PinAdoptionRefused` without importing signing (forbidden:
  layering + protected-file minimality). Classification is
  the caller's job; the loop's contract is mechanical
  (§1.2).

### 1.2 Hook semantics (the contract, to be written into the loop.py docstring)

1. **When it fires**: exactly once per *recorded* cycle,
   after `save()` has fsync'd and replaced `state.json`, with
   a deepcopy of the history entry as the sole argument. It
   does not fire when `run_one_cycle` returns `None` (idle),
   when any gate refuses (nothing persisted), or from
   `scan`/`approve` (they persist but record no cycle).
2. **Return value**: ignored. The hook signals outcomes only
   by raising.
3. **When it raises**: the exception propagates out of
   `run_one_cycle` unchanged (not wrapped, not swallowed).
   The cycle is already durable on disk and in
   `self.state`; there is NO rollback — un-saving a recorded
   cycle would falsify loop history, the same ruling
   `run_one_cycle_and_pin` already carries. The caller-visible
   contract is exactly: **"cycle recorded, pin pending,
   alert"**. The return entry is lost to the caller in this
   case, which is why the production adapter (§1.4) attaches
   it to the exception as `.cycle_entry` before re-raising —
   the adapter receives the entry as its argument, so no
   information is actually lost on the sanctioned path.
4. **Re-entrancy**: the hook must not call `run_one_cycle`,
   `scan`, or `approve` on the same loop instance (the
   adopter never does — it only reads state/calibration
   bytes). Stated in the docstring; not enforced in code
   (enforcement would be a re-entrancy flag + a new exception
   type in a protected file — disproportionate).
5. **Persistence of configuration**: none. The hook is
   constructor-injected per process, in memory only. The
   state-file schema is unchanged (no `schema_version` bump,
   no new state keys) — a hookless process reading a state
   file written by a hooked process sees identical bytes
   semantics.

### 1.3 Interaction with record_ship (normative)

`record_ship` calls `loop.run_one_cycle` between its burn
and its post-record manifest re-verification/finalise, and
catches only `InvalidTransition` there. If the loop it is
handed had a pin hook:

- verifier/network I/O (two verifier subprocess calls on the
  ceremony path) would execute *inside* an open ship
  transaction, between BURN_PENDING and CYCLE_RECORDED; and
- a `PinAdoptionBurned`/`PinAdoptionRefused` (both
  `SigningError`, not `InvalidTransition`) would escape
  `record_ship`'s handler, leaving the transaction stranded
  at BURN_PENDING with the cycle in fact recorded — the
  worst of both worlds (recovery would then have to settle a
  transaction whose cycle exists but whose finalise never
  ran, from evidence that looks like a crash).

Ruling: **the two configurations are mutually exclusive, and
the exclusion is enforced, not just documented.**

- `trust/shipcheck.py::record_ship` gains one pre-transaction
  guard, placed with the existing precondition refusals
  (before `tx_journal.begin`, so nothing is spent and no
  transaction is opened):

  ```python
  if getattr(loop, "cycle_hook", None) is not None:
      raise ShipRefused(
          "record_ship refuses a loop with a cycle_hook: pin "
          "adoption must not run inside a ship transaction; "
          "ship through a hookless loop and pin afterwards")
  ```

  (`getattr` with a default keeps duck-typed loop doubles in
  older tests working; `CoreLoop` always has the property.)
- Symmetrically, `run_one_cycle_and_pin` (trust/pin_adoption.py)
  gains a guard at entry: if `getattr(loop, "cycle_hook",
  None) is not None: raise ValueError(...)` — the driver and
  the hook are two wirings of the same step; using both would
  call `snapshot_and_adopt` twice per cycle (the second call
  would return `already_current` at best and re-present a
  retained envelope pointlessly). Fail fast instead.
- The sanctioned production composition is therefore:
  *interactive/driver path* — hooked loop, **or**
  `run_one_cycle_and_pin` on a hookless loop; *ship path* —
  hookless loop through `record_ship`, and pin adoption run
  as a separate step after `record_ship` returns (the WS5
  wrapper in §5.2 does exactly this ordering when both are
  wanted).

### 1.4 The production adapter (trust/pin_adoption.py)

```python
def pin_cycle_hook(adopter):
    """Return a CoreLoop cycle_hook that pins each recorded
    cycle through ``adopter``. On PinAdoptionBurned /
    PinAdoptionRefused the history entry the hook received
    is attached as ``.cycle_entry`` and the exception
    propagates: the caller's contract is 'cycle recorded,
    pin pending, alert' (the same contract
    run_one_cycle_and_pin documents)."""
    def _hook(entry):
        try:
            adopter.snapshot_and_adopt()
        except (PinAdoptionBurned, PinAdoptionRefused) as exc:
            exc.cycle_entry = entry
            raise
    return _hook
```

`PinAdoptionBurned`/`PinAdoptionRefused` already carry a
`cycle_entry = None` slot pattern on the burned class
(pin_adoption.py: `self.cycle_entry = None`); the refused
class gains the same attribute initialised to `None` so the
adapter can attach uniformly. No other adopter change.

### 1.5 The live run (sandbox copy of real state)

The live run is a *run*, not a test: a scripted, logged
execution against a byte-copy of the real `state/`, using
the WS2 production-mode verifier home. Artefacts:

- Script: `internal/cycle23-work/live_run.py` (operator-run,
  not production code; it imports production modules only).
- Run log: `internal/cycle23-work/LIVE-RUN-23.md`, written by
  the operator seat from the script's printed transcript:
  every step's outcome, pin values, consumption counts, and
  the before/after hashes of the REAL state files.

Sandbox layout (all under a fresh temp root, e.g.
`internal/cycle23-work/live-run/` — gitignored scratch, not
committed):

```
live-run/
  state/            # cp -r of real state/ (state.json seq 13 + calibration/)
  pins/             # PinStore dir (PinAdopterConfig.pin_dir)
  keys/             # snapshot signing key file (see below)
  home/ anchors/ registry/ evidence/   # the WS2 disposable
                    # production verifier deployment (§2),
                    # provisioned FIRST and reused here
```

Keys/homes the sandbox needs (no real key material exists or
is used):

- **Verifier home**: the WS2 disposable production home
  (§2.2): gate signing key via `generate_key_file`, ceremony
  seed via `generate_ceremony_key_file`, all three anchors
  bootstrapped, `AION_DEPLOYMENT_MODE=production`. The live
  run deliberately consumes the WS2 deployment rather than a
  research home — that is what makes it a *production* live
  run and answers seat-gemini's "research-mode harness"
  defect on the live-run axis as well as the test axis.
- **Snapshot signing key**: a fresh key file in
  `live-run/keys/` via the same generator the pin-adoption
  tests use (`generate_key_file`), loaded by
  `build_pin_adopter` with `forbidden_roots=(state_dir,
  pin_dir)` satisfied by construction (keys/ is a sibling of
  both). `snapshot_signer_id` is a sandbox id (e.g.
  `live-run-signer`); `expected_snapshot_signer_id` equals it.
- **Operator**: `operator_id` must be a member of the WS2
  home's `AION_CEREMONY_OPERATORS`; the adopter's
  `AION_PIN_OPERATOR_ID` and `PinAdopterConfig.operator_id`
  use that same id. Evidence dir = the verifier's
  `AION_CEREMONY_EVIDENCE_DIR` (build_pin_adopter refuses a
  mismatch — by design, exercised here for real).
- **Out-of-band pins** for `build_pin_adopter`: the WS2
  provisioning manifest's `expected_signer_id`, gate
  `expected_key_id`, and ceremony `CeremonyPublicKey` (§2.2
  step 6) — read from the manifest file the provisioning
  step wrote, not re-derived from key files at run time.

Exact cycle sequence (the copy's backlog is used as-is; no
hand edits — `pick_next` on the copy returns
`ledger-head-anchoring` first, then the next 6.5-leverage
items in seq order; the picked item ids are recorded in the
log and are *sandbox history only* — see §5.4 for why this
does not record anything in the real loop):

| Step | Action | Expected outcome |
|---|---|---|
| 0 | Hash real `state/state.json`, calibration, both ship-ledger files; hash the copies; assert equal. Construct `CoreLoop(live-run/state, cycle_hook=pin_cycle_hook(adopter))`. | Copy verified byte-identical; pin store empty (`read_all` → `(None, ())`). |
| 1 | `adopter.snapshot_and_adopt()` directly (no cycle yet). | **Genesis `initial_anchor` ceremony**: authorise → consume → adopt. Pin = {cycle_seq 13, hash of the seq-13 snapshot}. Consumption journal: exactly 1 entry, kind per WS3 = primary. PinStore history: 1 record, reason `initial_anchor`. |
| 2 | `loop.run_one_cycle(coders, reviewers, "reconciled", True, delta)` via the hooked loop. | Cycle 14 recorded in the COPY; hook fires; candidate seq 14 = pin 13 + 1 with prev link = pin hash → classify `ok` → **`advance_pin` dense step, NO ceremony**: consumption count still 1, history still 1 record, pin = {14, …}. |
| 3 | Two cycles on a *hookless* `CoreLoop` over the same copy (fresh instance, no hook), same participant/delta shape. | Cycles 15, 16 recorded; pin still {14, …}; consumption count still 1. (This is the "run 2 cycles unpinned then pin" gap construction.) |
| 4 | `adopter.snapshot_and_adopt()`. | Candidate seq 16 vs pin 14 → classify `reanchor_required` → **`chain_gap_recovery` ceremony** → pin = {16, …}; consumption count 2; history 2 records, second reason `chain_gap_recovery`. |
| 5 | `adopter.snapshot_and_adopt()` again, state unchanged. | `already_current`; no new consumption, no pin write (PinStore file bytes unchanged). |
| 6 | Re-verify: `PinStore.read_all` verifies; consumption journal entries match the two ceremonies; re-hash the REAL state files and assert identical to step 0. | Real state untouched, proven by hash, stated in the log. |

Participants/delta for steps 2–3: three distinct coder ids,
six distinct reviewer ids disjoint from coders, verdict
`"reconciled"`, `verify_passed=True`, and a delta with
`after > before` whose `verifier` is one of the reviewers —
the loop's own gates, unmodified. Ids are sandbox-local
(e.g. `live-coder-1..3`, `live-rev-1..6`) and the log says so:
these are mechanical cycles to move `cycle_seq`, not a
representation that the picked items were reviewed.

Failure handling during the run: any step deviating from the
expected outcome stops the run; the log records where. The
sandbox is disposable — no recovery is attempted against it
beyond what WS4's tests already prove; a failed run is
re-provisioned from step 0 (real state re-copied), never
repaired in place.

### 1.6 WS1 file/function change list

| File | Change |
|---|---|
| `core/loop.py` | `CoreLoop.__init__` gains keyword-only `cycle_hook=None` + validation + attribute; read-only `cycle_hook` property; one hook call in `run_one_cycle` after the persistence try/except; class/`run_one_cycle` docstrings gain the §1.2 contract. (~15 lines total.) |
| `trust/pin_adoption.py` | New `pin_cycle_hook(adopter)`; `PinAdoptionRefused` gains `cycle_entry = None` slot (class-level init in `__init__` mirroring `PinAdoptionBurned`); `run_one_cycle_and_pin` gains the hooked-loop `ValueError` guard + docstring cross-reference. |
| `trust/shipcheck.py` | `record_ship` gains the §1.3 pre-transaction `ShipRefused` guard + module-docstring note. |
| `internal/cycle23-work/live_run.py` | New run script (not production code). |
| `internal/cycle23-work/LIVE-RUN-23.md` | New run log (produced by the run, reviewed by the war room). |

### 1.7 WS1 tests (new)

`tests/test_core_loop_hook.py` (new file, loop-level, no
verifier):

1. `test_hook_fires_once_after_save_with_entry` — hook
   receives the entry; inside the hook, `state.json` on disk
   already contains the cycle (assert by re-reading the file).
2. `test_hook_not_fired_when_idle` — empty backlog → `None`,
   zero hook calls.
3. `test_hook_not_fired_on_gate_refusal` — split verdict →
   `InvalidTransition`, zero hook calls, state unchanged.
4. `test_hook_exception_propagates_cycle_stays_recorded` —
   hook raises a sentinel; the sentinel (identity, not a
   wrapper) propagates; a fresh `CoreLoop` on the dir shows
   the cycle in history and the item done.
5. `test_hookless_default_is_byte_identical_behaviour` — a
   cycle run without a hook produces the same state-file
   bytes shape as baseline (keys/schema unchanged; compare
   parsed structure + `schema_version`).
6. `test_non_callable_hook_refused_at_construction`.
7. `test_scan_and_approve_do_not_fire_hook`.
8. `test_hook_receives_a_copy` — hook mutates its argument;
   stored history is unaffected.

`tests/test_trust_pin_adoption.py` (additions):

9. `test_09_hooked_loop_genesis_then_dense_advance` — hooked
   loop over the existing fixture: first cycle pins via
   ceremony, second advances with no new consumption.
10. `test_10_hooked_loop_burn_attaches_cycle_entry` — adopter
    whose store.adopt fails post-consume (existing
    fault-injection pattern) driven through the hook:
    `PinAdoptionBurned.cycle_entry` is the recorded entry and
    the loop state on disk contains the cycle.
11. `test_11_driver_refuses_hooked_loop` —
    `run_one_cycle_and_pin` on a hooked loop raises
    `ValueError` before running anything.

`tests/test_trust_shipcheck.py` (addition):

12. `test_record_ship_refuses_hooked_loop_pre_burn` —
    `ShipRefused`, ship ledger unchanged, and NO ship-tx
    transaction was opened (tx journal entry count unchanged).

### 1.8 WS1 failure-mode analysis

- *Hook raises after save* → cycle recorded, pin pending;
  alerting is the caller's (the exception IS the alert on the
  sanctioned path, with `.cycle_entry` attached). Next
  process start: pin is behind state; `snapshot_and_adopt`
  classifies the gap and ceremonies/advances then. No state
  is unrecoverable.
- *Hook hangs / verifier down* → the ceremony path raises
  `PinAdoptionRefused` (existing test_06 pattern) or the
  subprocess call fails; pin unchanged; cycle stands.
- *Process killed while the hook runs* → indistinguishable
  from "hook never ran" plus possibly a burned authorisation
  (WS4 case C1 covers the consume-committed variant). The pin
  store and loop state are each individually atomic; the pair
  is reconciled by the next `snapshot_and_adopt`, by design.
- *Hooked loop handed to record_ship* → refused pre-burn
  (§1.3); nothing spent, no transaction opened.
- *Double wiring (driver + hook)* → refused at driver entry.

### 1.9 WS1 claim wording

May claim afterwards: "CoreLoop can be constructed with an
injected post-cycle hook; on the sanctioned composition a
recorded cycle's snapshot is pinned through the production
PinAdopter, and a pin failure surfaces as 'cycle recorded,
pin pending' with the cycle entry attached. A live run
against a byte-copy of the real state (cycle_seq 13)
exercised a genesis initial_anchor ceremony, a dense
advance_pin step, and a chain_gap_recovery ceremony against
a production-mode verifier home; the real state files are
hash-identical before and after."
May NOT claim: that the real `state/state.json` is pinned
(it is not — no pin store exists for the real state dir, and
creating one is a production act gated on deployment
provisioning, §5.4); that the sandbox cycles record real
work items (they are mechanical cycles on a copy); that the
hook makes loop+pin atomic (it explicitly does not — the
boundary is reconciled, not transactional).

---

## WS2 — Production-mode end-to-end

### 2.1 The full env set

Two disjoint mappings. Mixing them is a construction error:
`build_pin_adopter` passes its `env` argument to
`production_client`, which refuses any key outside
`ALLOWED_ENV_KEYS` — so the `AION_PIN_*` variables must never
be in the verifier mapping, and `pin_adopter_config_from_env`
reads them from a separate mapping. The e2e harness keeps
them in two dicts from the start.

**Verifier env** (keys from `trust/wiring.py`:
`ALLOWED_ENV_KEYS`, 19; `REQUIRED_ENV_KEYS`, 9):

| Key | Required by | Value in the disposable deployment |
|---|---|---|
| `AION_VERIFIER_KEY_PATH` | wiring REQUIRED | `<root>/keys/gate.key` (generated, 0600) |
| `AION_VERIFIER_SIGNER_ID` | wiring REQUIRED | e.g. `aion-verifier-e2e` |
| `AION_VERIFIER_ACTOR_ID` | wiring REQUIRED | e.g. `verifier-actor` |
| `AION_REGISTRY_DIR` | wiring REQUIRED | `<root>/registry` (an `EvalRegistry`, §2.2) |
| `AION_VERIFIER_HOME` | wiring REQUIRED | `<root>/home` |
| `AION_DEPLOYMENT_MODE` | wiring REQUIRED | exactly `production` (after bootstrap, §2.2) |
| `AION_ANCHOR_PATH` | wiring REQUIRED | `<root>/anchors/signing.anchor.json` |
| `AION_BUDGETS_ANCHOR_PATH` | wiring REQUIRED | `<root>/anchors/budgets.anchor.json` |
| `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` | wiring REQUIRED | `<root>/anchors/ceremony-consumption.anchor.json` |
| `AION_CEREMONY_OPERATORS` | verifier startup (production + ceremony) | the adopter's operator id, comma list |
| `AION_CEREMONY_EVIDENCE_DIR` | verifier startup (production) | `<root>/evidence` |
| `AION_CEREMONY_SIGNING_SEED_PATH` | verifier startup (production) | `<root>/keys/ceremony.seed` |
| `AION_VERIFIER_TTL_SECONDS` | optional | unset (default 900; ceremony TTL is hard-capped at 900 regardless) |
| `AION_VERIFIER_PURPOSE` | optional | unset (default memory-commit; the ceremony modes do not consult purpose — the e2e does not exercise `gate`, §2.4) |
| `AION_VERIFIER_PROPOSAL_BUDGET` / `AION_VERIFIER_IDENTITY_BUDGET` | optional | unset (defaults) |
| `AION_ANCHOR_INIT` / `AION_BUDGETS_ANCHOR_INIT` / `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` | bootstrap ONLY | `1` during §2.2 step 5 only; **absent** thereafter (wiring refuses any value other than `""`/`"0"` in a production client env, and `_load_config` refuses them in production mode — two independent layers) |

**Adopter env** (`pin_adopter_config_from_env`, 5 keys, all
required there): `AION_PIN_DIR`, `AION_PIN_SIGNING_KEY_PATH`,
`AION_PIN_SIGNER_ID`, `AION_PIN_OPERATOR_ID`,
`AION_PIN_EVIDENCE_DIR` (must resolve equal to the verifier's
`AION_CEREMONY_EVIDENCE_DIR` — `build_pin_adopter` refuses
otherwise).

### 2.2 Provisioning steps (exact order)

Root: a fresh temp dir (`tempfile.mkdtemp`, mode 0700),
denoted `<root>`. Nothing under `/var`, no root, no OS user
(§2.4 blocker B1).

1. **Directories**: `<root>/{home,keys,anchors,registry,
   evidence,pins,snapkeys,state}`; state gets the fixture
   state + calibration (for the test) or the live-run copy
   (for WS1).
2. **Gate key**: `generate_key_file(<root>/keys/gate.key)`
   (the helper the existing suites use). Record its
   `key_id`.
3. **Ceremony seed**: `generate_ceremony_key_file(<root>/
   keys/ceremony.seed)`; derive the `CeremonyPublicKey` via
   `ceremony_public_key_for`. The seed file never leaves the
   provisioning step's hands except as the verifier's env
   path — the adopter never sees it.
4. **Registry**: construct `EvalRegistry(<root>/registry)`
   and seal the standard fixture items (mirroring
   `test_trust_pin_adoption.py`'s fixture). The ceremony
   modes never read registry items, but `_load_config` /
   client construction is exercised against a real registry
   in every other suite, and an absent/empty registry dir is
   an untested shape — do not improvise one.
5. **Anchor bootstrap (the INIT ceremonies)** — the ordering
   constraint: production mode refuses all three INIT flags
   in `_load_config`, and `production_client` refuses them
   in the env, so bootstrap CANNOT go through either
   production surface. It is a direct verifier-subprocess
   act in research mode, performed once, before any
   production client exists:
   - env = verifier env but `AION_DEPLOYMENT_MODE=research`
     and all three `*_INIT=1`, all three anchor paths set;
   - invoke the verifier subprocess once with mode
     `ceremony_consume` and body `{}`. `_load_config` runs
     before mode dispatch and performs all three
     initialisations as side effects on empty journals:
     signing anchor via `initialise_anchor` (empty signing
     ledger), budgets anchor via the genesis-head pin (empty
     budget store — the only head INIT may pin), consumption
     anchor via `initialise_anchor` (empty consumption
     journal). The mode itself then refuses the malformed
     body — expected, and asserted as such (exit code /
     `malformed_request`); the bootstrap's success criterion
     is the anchor files, not the mode result.
   - Assert: all three anchor files exist; signing and
     consumption anchors are `{seq: 0, head: GENESIS}`;
     budgets anchor pins the genesis head.
   - Rejected alternative: calling `trust.anchoring.
     initialise_anchor` directly from the provisioning
     script for all three. It works for signing/consumption
     but NOT for budgets — the budgets anchor is a different
     format (a bare head-hash file written by
     `_write_budgets_anchor`, initialised only inside
     `_load_config`). One bootstrap mechanism (the verifier's
     own `_load_config`) for all three keeps the e2e honest:
     it proves the verifier itself accepts the bootstrapped
     state at the next step.
   - Rejected alternative: bootstrap in production mode with
     INIT — refused by design at two layers; any design that
     needs it is wrong.
6. **Provisioning manifest**: the provisioning step writes
   `<root>/provisioning.json` (outside the verifier home):
   `{signer_id, gate_key_id, ceremony_public_key (the
   envelope-dict form), snapshot_signer_id, operator_id}`.
   This file is the e2e's out-of-band channel: WS1/WS2
   consumers read pins from it, never from the key/seed
   files. (In a real deployment this manifest is the
   operator's provisioning record; here the harness plays
   the operator.)
7. **Steady state**: strip the three INIT keys entirely,
   set `AION_DEPLOYMENT_MODE=production`. Every subsequent
   verifier invocation is through `production_client` /
   `build_pin_adopter` only.

### 2.3 The e2e flow

In `tests/test_trust_production_e2e.py`, over the §2.2
deployment with a small fixture state (2 backlog items):

1. Construct the adopter ONLY via `build_pin_adopter(
   verifier_env, expected_signer_id=…, expected_key_id=…,
   authorisation_public_key=…, signing_key_path=<snapshot
   key>, config=…)` with pins from `provisioning.json` and
   adopter values from `pin_adopter_config_from_env(
   adopter_env)`. Assert the client's deployment-mode
   expectation is production (a verifier reporting any other
   mode is refused by the client at response time — exercise
   by asserting a successful first call, which performs that
   check).
2. **authorise → consume → adopt**: `snapshot_and_adopt()` on
   the genesis state → outcome `reanchored`, reason
   `initial_anchor`; assert in the verifier home: issuance
   journal +1, consumption journal +1 (WS3: kind primary),
   signing ledger has both mirror entries; all three anchors
   advanced appropriately (consumption anchor seq 1;
   signing anchor advanced by the mirror appends).
3. Dense step: one loop cycle (hookless driver) →
   `advanced`, zero new consumptions.
4. Gap step: two bare cycles, then `snapshot_and_adopt()` →
   `chain_gap_recovery` ceremony end-to-end in production
   mode; consumption anchor seq 2.
5. Startup-refusal probes (each a fresh `production_client`
   call, i.e. a fresh verifier subprocess through
   `_load_config`): (a) delete the consumption anchor file →
   any mode refuses `anchor_refused`
   (`anchor_missing_established_ledger` class); (b) roll the
   consumption journal back to its pre-step-4 bytes →
   refused at startup (anchor ahead / head not in chain);
   (c) re-add any INIT key to the env → `production_client`
   itself raises `VerifierConfigError` before spawning
   anything.

### 2.4 What could block full production mode locally (blocker list)

- **B1 — No OS-user separation.** `deploy/verifier-identity/
  setup.sh` is root-only and creates the `aion-verifier`
  system user; deployment is not provisioned on this VM (the
  28 skipped tests are exactly this gate). The disposable
  deployment is therefore *same-user* production mode:
  `production_client`'s only launch mode is the same-user
  spawn (`launch="wrapper"` is refused by the factory
  itself). The env/mode/anchor discipline is fully
  production; the OS boundary is not. This is a claim-scoping
  blocker, not a functional one — §2.5 wording carries it.
- **B2 — INIT bootstrap cannot use production surfaces**
  (by design, two layers). Handled by §2.2 step 5's ordering;
  if a future change makes `_load_config` refuse research
  mode with ceremony keys configured, the bootstrap breaks
  loudly at provisioning time, not silently — acceptable.
- **B3 — Registry/actor surface.** `_load_config` requires
  the registry dir and actor id; the e2e provisions a real
  `EvalRegistry`. The `gate`/`sealed_eval` modes are NOT
  exercised in production mode by this cycle (purpose unset);
  if the war room wants them, that is a scope addition, not
  a blocker for the ceremony line.
- **B4 — Seed/key permission discipline.** The seed loader's
  owner-only permission predicate and uid check (cycle 21)
  apply to the disposable seed file: the harness must create
  it 0600 under the current uid (the generators do). A
  harness that copies a seed with loose permissions fails
  closed — noted so the build seat does not "fix" it by
  loosening the check.
- **B5 — TTL.** Envelope TTL is hard-capped at 900 s and a
  ceremony needs two verifier windows inside it
  (authorise, consume). In-process e2e is nowhere near this;
  stated for the live-run operator (do not pause between
  steps 1/4 of §1.5 for >15 min).

No production-code change is expected for WS2. If the build
finds one necessary (e.g. `build_pin_adopter` cannot be
composed as §2.3 step 1 describes), that is a *finding* to
surface to the war room, not a silent fix: the workstream's
purpose is to discover exactly that.

### 2.5 WS2 file list + tests

Files: `tests/test_trust_production_e2e.py` (new, ~7 tests:
provisioning/bootstrap assertions, flow steps 2–4 as three
tests, refusal probes 5a/5b/5c as three tests — some may
share one fixture class with per-test temp roots because
probes mutate the deployment);
`internal/cycle23-work/provision_disposable.py` (the §2.2
provisioning as a reusable script, used by both the test
fixture — via import of its function form — and the WS1 live
run). No production files change.

Claim wording — may claim: "The full ceremony path
(authorise → consume → adopt via `build_pin_adopter` /
`production_client`, all anchors configured and verified at
every startup) runs end-to-end in production mode against a
disposable verifier home, including startup refusal on a
deleted or rolled-back consumption anchor." May NOT claim:
"production deployment" without the same-user qualifier
(B1); OS-level separation; wrapper-routed launch; anything
about the `gate`/`sealed_eval` modes in production.

---

## WS3 — Journal schema v2: recovery lineage, re-ruled bounds

This is the workstream seat-gemini's non-ratification turns
on: the journal must *say* what kind of consumption each
entry is, instead of the pair-scan inferring it. It also
supersedes DECISION-CONSUMPTION-HEAD Addendum 2's one-shot
ruling — by war-room re-ruling on the new schema, recorded
as Addendum 3 (§3.7), and put to the external seats as a
ruling to ratify, exactly as one-shot was.

### 3.1 Versioning design

Constraints: `_load` enforces an exact top-level shape
(`{"entries"}`) shared by every journal subclass, and an
exact per-entry key set. Live v1 journals exist (the real
verifier-home format in tests across the suite; the format
must not brick them — every existing test journal is v1).

Design:

1. **Generalise the base check by one seam.**
   `HashChainJournal` gains:

   ```python
   def _allowed_entry_key_sets(self) -> tuple:
       """Exact key sets a loaded entry may carry. Default:
       the single historical set. Subclasses with a versioned
       schema return every version's set; _load accepts an
       entry iff its keys equal one of them."""
       return (_ENTRY_KEYS | set(self.EXTRA_KEYS),)
   ```

   and `_load`'s per-entry check becomes
   `set(entry) not in self._allowed_entry_key_sets()`.
   Every other subclass's behaviour is byte-for-byte
   unchanged (their tuple has one element, the same set).
   Top-level shape is NOT touched.

2. **Consumption journal v2 keys.** `CeremonyConsumptionLedger`
   gains:

   ```python
   EXTRA_KEYS_V2 = EXTRA_KEYS | {
       "consumption_kind", "recovery_of", "recovery_depth"}
   ```

   and overrides `_allowed_entry_key_sets` to return
   `(v1_set, v2_set)`. New entries are ALWAYS written v2
   (the `_append` call in `append_consumption` passes the
   three new fields). v1 entries are never rewritten,
   migrated, or re-hashed — a migration would invalidate
   their `entry_hash` chain positions and every anchor
   prefix naming them (the consumption anchor pins
   (seq, head) prefixes of exactly this chain). Mixed
   v1/v2 journals are legal forever; readers must handle
   both (§3.3's depth derivation is the only place the
   distinction matters).

3. **Field semantics** (all three always present in v2, so
   the exact-set discipline is preserved — no optional keys):
   - `consumption_kind`: `"primary"` | `"recovery"`.
     (`kind` stays `"consume"` — it is the journal-entry kind
     in the shared base vocabulary; overloading it would
     break every `entry["kind"] == "consume"` scan, including
     the signing-mirror cross-check's scoping. Rejected:
     `kind="recovery-consume"`.)
   - `recovery_of`: for a recovery, the `authorisation_id`
     of the consumption entry it recovers (the burn proven at
     authorise, §3.2); for a primary, `""` — the empty-string
     sentinel, matching the existing `old_payload_hash == ""`
     convention for the no-pin shape.
   - `recovery_depth`: `0` for a primary; for a recovery,
     the burn's depth + 1 (§3.3). A non-negative int; `_load`
     gains value validation for v2 entries in the ledger's
     own `_validate_entry` hook — see (4).
   - Value validation: the base `_load` checks keys and the
     hash chain only. v2 entries with `consumption_kind`
     outside the two literals, a negative/non-int
     `recovery_depth`, or `consumption_kind == "primary"`
     with `recovery_of != ""` / `recovery_depth != 0` must
     refuse load (a journal the verifier cannot interpret
     fails closed, like every other corruption). Implement as
     a second small seam: `HashChainJournal._validate_entry(
     entry, position)` — default no-op, called from `_load`
     after the key-set check; `CeremonyConsumptionLedger`
     overrides it for v2-shaped entries. (Hash recomputation
     already guarantees the fields are what the writer wrote;
     this check guarantees the *writer's* values are in the
     legal vocabulary, which is what makes lineage
     load-bearing rather than decorative.)

4. **Issuance journal binding (the load-bearing half).**
   Lineage must bind the recovery to the burn that was
   *proven at authorise*, or the consume-side race in §3.4
   cannot be decided. The envelope format does NOT change
   (no new payload field — rejected: it would version the
   signed envelope, `verify_ceremony_record`,
   `reanchor_pin`, the client, and every retained envelope,
   to carry a fact the verifier can record itself).
   Instead, `CeremonyAuthorisationLedger` gets the same
   versioned treatment: `EXTRA_KEYS_V2 = EXTRA_KEYS |
   {"recovery_of"}`, `_allowed_entry_key_sets` returns both,
   and `append_authorisation(self, signed, *, recorded_at,
   recovery_of="")` writes v2 entries from this cycle on.
   The value is supplied ONLY by `_mode_ceremony_authorise`
   from its own step-5b result (§3.2) — it is computed inside
   the verifier process from the consumption journal, never
   read from the request body (the body's exact key set is
   unchanged; a body carrying `recovery_of` is malformed).
   For non-`burned_unadopted` issuance, `recovery_of=""`.

Rejected versioning alternatives:

- **Journal-level version marker** (top-level `"version"`
  key or a sidecar file): the top-level exact-shape check is
  shared by all journals — widening it widens every
  journal's format for one subclass's need; a sidecar is
  non-authoritative, separately rollback-able, and can
  disagree with the entries it describes. Per-entry
  versioning is self-describing and hash-bound: each entry's
  version is inside its own `entry_hash`. Chosen.
- **Always-v2 with v1 rejection + a migration tool**:
  bricks live journals at load until migrated, and migration
  rewrites hashes (see above). Rejected unconditionally.
- **Encode lineage in existing fields** (e.g. overload
  `evidence_hash` or ceremony_id grammar): corrupts fields
  other checks bind to. Rejected.

### 3.2 Lineage computation — verifier-side, at the two commit points

**At authorise** (`_mode_ceremony_authorise`, step 5b —
verifier_main.py): `match_head_burn` already returns the
burn entry or `None`. Capture it: `burn_entry = burn` (the
existing local). After signing, the commit calls
`append_authorisation(signed, recorded_at=…,
recovery_of=burn_entry["authorisation_id"] if reason ==
burned_unadopted else "")`. No other authorise behaviour
changes; step 5b's single refusal code
(`ceremony_recovery_unproven`) and its no-oracle property
are untouched — the binding adds no new refusal and no new
output.

**At consume** (`_mode_ceremony_consume`): step (6) already
loads the issuance entry (`issued`). The mode reads
`issued.get("recovery_of", "")` (v1 issuance entries have no
such key → `""`) and passes it as the *binding* into both
the step-(7) `check_head` call and the step-(8)
`append_consumption` call (§3.4 signatures). Inside
`append_consumption`'s reload-retry loop, after `check_head`
passes against the fresh entries, lineage is computed from
those same fresh entries:

```python
if envelope.reason == "burned_unadopted" and binding:
    burn = match_head_burn(entries, candidate=…, old_pin=…)
    # check_head has just established burn is not None and
    # burn["authorisation_id"] == binding (§3.4)
    kind, rec_of, depth = "recovery", binding, \
        _depth_of(entries, burn) + 1
else:
    kind, rec_of, depth = "primary", "", 0
```

and the `_append` call passes
`consumption_kind=kind, recovery_of=rec_of,
recovery_depth=depth`. Because computation happens inside
the retry loop against the snapshot the append extends —
and `_save`'s under-flock freshness check refuses if that
snapshot moved — a lineage value can never be computed from
one journal state and committed onto another.

Direct (non-mode) callers of `append_consumption` /
`check_head` — i.e. tests — pass the binding explicitly;
the default is `""`, which disables the recovery exception
(fail-closed: an unbound `burned_unadopted` envelope is
treated as an ordinary at-head consumption and refused
`AlreadyConsumedError`). This is a deliberate behaviour
note for the ledger's docstring: the recovery exception is
a property of the integrated verifier path, as the
cycle-21 decision already scoped the head guarantee.

### 3.3 Depth derivation (incl. the v1 rule)

```python
@staticmethod
def _depth_of(entries, entry) -> int:
    """Recovery depth of ``entry`` within ``entries`` (the
    full journal prefix ending at or before entry is NOT
    assumed — entries is the whole journal; entry is
    identified by authorisation_id)."""
    if "recovery_depth" in entry:            # v2: authoritative
        return entry["recovery_depth"]
    # v1: the entry predates lineage. Under the rules every
    # v1 entry was written under (cycles 21–22), a movement's
    # (old,new) pair occurs at most twice — a primary and its
    # one-shot recovery — so the count of EARLIER same-pair
    # entries is the entry's exact depth (0 or 1), not an
    # estimate.
    pair = (entry["old_cycle_seq"], entry["old_payload_hash"],
            entry["new_cycle_seq"], entry["new_payload_hash"])
    depth = 0
    for earlier in entries:
        if earlier is entry or \
                earlier["authorisation_id"] == \
                entry["authorisation_id"]:
            break
        if (earlier["old_cycle_seq"], earlier["old_payload_hash"],
                earlier["new_cycle_seq"], earlier["new_payload_hash"]) == pair:
            depth += 1
    return depth
```

(Implementation detail for the build seat: iterate by index
to make "earlier" exact; the sketch above fixes semantics,
not the loop spelling.) For v2 entries the stored field is
authoritative and the pair count is NEVER consulted — a test
(§3.6 T9) pins a journal where the two disagree (hand-built
via the ledger's own append path in a scratch journal) and
requires the field to win. This is the sense in which the
pair-scan is *demoted*: it survives only as the v1 depth
derivation, fenced to entries that carry no lineage.

### 3.4 match_head_burn and check_head under v2

`match_head_burn(entries, *, candidate, old_pin)` — signature
unchanged (both call sites keep working). New semantics:

1. Head-match on (candidate, old_pin) exactly as today.
2. **Depth gate** (replaces the one-shot pair-scan): return
   the head entry only if `_depth_of(entries, head) <
   MAX_RECOVERY_DEPTH` (§3.5: the head burn must still have
   recovery budget). A primary head (depth 0) and a depth-1
   recovery head both pass; a depth-2 head does not.
3. The pair-scan loop is deleted.

`check_head(entries, signed, *, recovery_of="")` — the
recovery exception becomes:

```python
recovery = False
if signed.reason == "burned_unadopted" and recovery_of:
    burn = match_head_burn(entries, candidate=signed.candidate,
                           old_pin=signed.old_pin)
    recovery = burn is not None \
        and burn["authorisation_id"] == recovery_of
```

Everything else in `check_head` is unchanged. Consequences,
each pinned by a test in §3.6:

- The exception now names the exact burn the envelope was
  authorised against. A second pre-authorised recovery whose
  burn was the ORIGINAL entry, racing a first recovery that
  has already landed, finds the head is now the winner's
  entry (`authorisation_id != recovery_of`) → no exception →
  candidate at head seq+hash → `AlreadyConsumedError`.
  **Exactly one of the racers consumes** — seat-gpt's
  preserved property, now by binding rather than by
  one-shot.
- A *fresh* recovery authorised after the winner landed
  proves step 5b against the winner's entry (it is the
  head), binds `recovery_of` to the winner's
  authorisation_id, and consumes as depth 2. This is the
  bounded chain working as intended.
- An envelope authorised against a burn that is no longer
  head (any later consumption landed) gets no exception:
  head-only matching is preserved.
- `burn["ceremony_id"] == ceremony_id` self-recovery refusal
  at authorise step 5b is unchanged.

`append_consumption(self, envelope, *, recorded_at,
recovery_of="")` — new keyword, threaded to `check_head`
and to the lineage computation (§3.2). Single-use by
`authorisation_id` is checked first, as today, so the
same-envelope race still yields exactly one success and one
`AlreadyConsumedError`.

The signing-ledger mirror (`SigningLedger.
append_ceremony_consumption`) is NOT widened: the mirror is
an audit trace of the consumption fact; lineage lives in
the consumption journal (authority) and the issuance
journal (binding). Stated as an accepted scope line in the
ledger docstring — a mirror reader can join on
`authorisation_id` to both.

### 3.5 The re-ruling: bounded chains, MAX_RECOVERY_DEPTH = 2

**Ruling proposed: option (ii), bounded chains with
`MAX_RECOVERY_DEPTH = 2`** — a constant on
`CeremonyConsumptionLedger`. A movement (one (old → new)
pair) may be consumed at most 3 times in total: the primary
consumption (depth 0) plus at most two recoveries (depths
1, 2), each recovery requiring all of: reason
`burned_unadopted`; a fresh ceremony_id and a fresh evidence
bundle (issuance single-use unchanged); an operator on the
verifier's protected list; the burn it recovers being the
journal HEAD at both authorise (step 5b) and consume
(check_head, inside the commit loop); and the binding of
§3.2. The original burn stays permanently burned throughout
— no entry is ever removed, amended, or un-consumed; a
recovery is a new consumption of a *new authorisation*
whose target happens to equal the burned target.

Why cap 2:

- The fault model is crash/adoption failure, not adversarial
  iteration: depth 1 covers consume-committed/adopt-failed;
  depth 2 covers the recovery itself suffering the same
  fault. Two independent faults of the same rare class is
  the plausible envelope; a third points at a systematically
  broken adopter, where refusing and forcing diagnosis is
  the correct behaviour, not a liveness bug.
- Exhaustion is never a system deadlock: it bricks only that
  exact snapshot *target*. The loop keeps cycling (the pin
  is not an input to `run_one_cycle`), and the next cycle's
  snapshot is a NEW candidate (seq+1) whose adoption is a
  primary `chain_gap_recovery` ceremony — untouched by the
  exhausted movement's depth. Liveness of the pin resumes at
  the next sequence by a path that already exists. (Pinned
  by WS4 case C6b.)
- Each depth multiplies the window in which the head target
  can be re-consumed under fresh authorisations. Cap 2 keeps
  the total re-consumption surface at 3 per movement —
  small enough to audit by eye in the journal, which is now
  possible precisely because lineage is explicit.

Option (i) — keep one-shot, now schema-grounded — rejected:
it keeps the exact liveness defect seat-gemini named (a
recovery that itself burns unadopted bricks the movement)
after the schema excuse for it is gone. One-shot was a
patch for indistinguishability; with lineage recorded and
the binding closing the race, the patch's cost buys nothing.

Option (iii) — unbounded chains — rejected: target-level
single-use would rest on operator patience. An unbounded
chain lets a listed operator keep one movement's target
consumable indefinitely (each link is individually
legitimate), the journal grows without bound on one head,
and the audit question "how many times was this target
consumed?" gets an unbounded answer. The depth cap is what
makes "single-use, with bounded recovery" a checkable
property of the journal rather than a policy hope.

Preserved invariants (each test-pinned, §3.6): exactly-one
consumption per authorisation_id under concurrency;
exactly-one success in the two-recovery race (binding);
original burn permanently burned (no code path removes or
amends entries — append-only is untouched); no forked or
backwards movement (`check_head`'s non-recovery rules are
byte-unchanged; the exception still requires exact
candidate + old-pin equality with the head).

### 3.6 WS3 tests

New file `tests/test_trust_consumption_schema_v2.py`:

1. `test_v1_journal_loads_unchanged` — a v1-only journal
   (built with the pre-v2 field set via direct `_append`)
   loads; entries round-trip; `head_target` correct.
2. `test_mixed_journal_loads_and_appends_v2` — v1 entries
   followed by a v2 append; the v1 entries' hashes/bytes are
   untouched (compare serialised prefix before/after).
3. `test_v2_entry_shape_and_primary_lineage` — a primary
   `append_consumption` writes `consumption_kind="primary"`,
   `recovery_of=""`, `recovery_depth=0`.
4. `test_unknown_key_set_refused` — an entry with a v2 set
   plus one extra key, and an entry missing one v2 key, both
   refuse load (`CorruptLedgerError`).
5. `test_v2_value_validation` — `consumption_kind="bogus"`;
   `recovery_depth=-1`; primary with `recovery_of` set:
   each refuses load.
6. `test_other_journals_unaffected` — `ShipLedger` /
   `SigningLedger` still refuse an entry carrying the v2
   consumption keys (their allowed sets did not widen).
7. `test_recovery_lineage_computed_verifier_side` — through
   the real verifier subprocess (the
   `test_trust_ceremony_consumption.py` fixture pattern):
   burn a target unadopted, authorise a recovery, consume;
   the consumption entry has kind `recovery`,
   `recovery_of` = the burn's authorisation_id, depth 1;
   the issuance entry for the recovery carries the same
   `recovery_of`; the primary's issuance entry carries `""`.
8. `test_caller_cannot_assert_lineage` — a ceremony_authorise
   body containing `recovery_of` is `malformed_request`; a
   direct `append_consumption` without a binding refuses a
   `burned_unadopted` at-head envelope with
   `AlreadyConsumedError`.
9. `test_v2_depth_field_wins_over_pair_count` — §3.3's
   disagreement journal: stored depth governs
   `match_head_burn`'s gate.
10. `test_v1_recovery_depth_derivation` — a v1 journal with
    a primary + one-shot recovery pair: `_depth_of` returns
    0 and 1 respectively; a recovery bound to the v1
    recovery entry is refused by the depth gate only when
    the cap is reached (with cap 2, a v1 depth-1 head still
    admits one v2 recovery, written at depth 2 — the
    migration seam working).

In `tests/test_trust_ceremony_consumption.py` (re-pins and
additions — the file's one-shot chain test is re-pinned, as
cycle 22 re-pinned cycle 21's):

11. `test_recovery_chain_to_depth_two_then_exhausted` —
    burn → recovery-1 burns → recovery-2 authorises and
    consumes (depth 2) → recovery-3 authorise refuses
    `ceremony_recovery_unproven`; a hand-presented recovery-3
    envelope (signed directly with the seed, the file's
    existing pattern) refuses consume
    `ceremony_already_consumed`.
12. `test_racing_recoveries_exactly_one_consumes` — two
    recovery authorisations issued against the same burn
    (both pass step 5b while it is head); both consume
    attempts run (sequentially and, in a second variant, from
    two threads against the ledger directly): exactly one
    success, exactly one `AlreadyConsumedError`; journal
    gains exactly one entry. (This replaces cycle 22's
    one-shot race expectation with the binding-based one —
    same observable, different mechanism, stated in the test
    docstring.)
13. `test_recovery_binds_named_burn_not_any_head` — recovery
    authorised against burn A; an unrelated consumption lands
    (head moves); the recovery's consume refuses (head
    regression class) even though its target pair still
    exists in the journal.
14. Concurrency preservation: the existing same-envelope
    concurrent-consume test (exactly one success) must pass
    unmodified.

### 3.7 WS3 records and wording

- `internal/DECISION-CONSUMPTION-HEAD.md` gains **Addendum
  3**, recording: schema v2, lineage fields, the binding via
  the issuance journal, `MAX_RECOVERY_DEPTH = 2`, the
  supersession of Addendum 2's one-shot ruling (Addendum 2
  stays as history, exactly as Addendum 1 treated the
  original text), and the v1 depth-derivation rule.
- Docstring sweep (the cycle-22 lesson: wording is part of
  the build): `CeremonyConsumptionLedger`'s class docstring
  (one-shot paragraph rewritten), `match_head_burn` /
  `check_head` docstrings, `signing/pin_ceremony.py`'s
  residual summary where it states one-shot, and the
  adopter's reason-selection comment in
  `trust/pin_adoption.py` (its computed-reason logic is
  unchanged — it still selects `burned_unadopted` from its
  pending journal — but any "one-shot" wording there is
  updated).

Claim wording — may claim: "Every consumption entry records
its kind and, for recoveries, the authorisation it recovers
and its depth, computed by the verifier at the commit point
from its own journals; recovery is bounded at depth 2 per
movement, with the bound enforced at authorise and at
consume against the bound burn; v1 journals load and verify
unchanged." May NOT claim: that one-shot still holds (it is
superseded — any external material citing Addendum 2 must
cite Addendum 3); that lineage is mirrored in the signing
ledger (it is not, §3.4); that the external seats have
ratified the re-ruling (that is the cycle-23 brief's
question, as one-shot was cycle 22's).

### 3.8 WS3 file/function change list

| File | Change |
|---|---|
| `trust/ledger.py` | `HashChainJournal`: `_allowed_entry_key_sets()` + `_validate_entry()` seams, `_load` uses them. `CeremonyConsumptionLedger`: `EXTRA_KEYS_V2`, `_allowed_entry_key_sets`, `_validate_entry`, `MAX_RECOVERY_DEPTH = 2`, `_depth_of`, `match_head_burn` re-ruled (pair-scan deleted, depth gate added), `check_head(…, recovery_of="")`, `append_consumption(…, recovery_of="")` computing and writing lineage. `CeremonyAuthorisationLedger`: `EXTRA_KEYS_V2`, `_allowed_entry_key_sets`, `append_authorisation(…, recovery_of="")`. |
| `trust/verifier_main.py` | Authorise: capture step-5b burn entry; pass `recovery_of` to `append_authorisation`. Consume: read binding from the issuance entry at step (6); pass to `check_head` (7) and `append_consumption` (8). No new refusal codes, no body-shape changes. |
| `internal/DECISION-CONSUMPTION-HEAD.md` | Addendum 3 (records only). |
| Docstrings per §3.7 | `trust/ledger.py`, `signing/pin_ceremony.py`, `trust/pin_adoption.py` wording only. |

### 3.9 WS3 failure-mode analysis

- *v2 writer, v1 reader* (mixed-version processes during a
  rollout): a pre-v2 verifier process loading a journal with
  v2 entries refuses (`wrong keys`) — fail-closed, no silent
  misread. Acceptable: the verifier is one deployment unit;
  stated here so nobody "fixes" it by loosening v1.
- *Binding lost* (issuance journal rolled back — it is
  unanchored, the narrowed `ceremony-journal-anchoring`
  follow-up): a recovery envelope whose issuance entry is
  gone already refuses at consume step (6)
  (`ceremony_not_issued`); a rolled-back-to-v1 issuance entry
  yields binding `""` → no exception → `AlreadyConsumed`.
  Both fail closed; lineage can be lost by rollback but
  cannot be *forged forward* by it (a forged binding would
  need a forged issuance entry whose payload/ceremony/
  evidence fields match a real signed envelope, inside the
  verifier home — the intact-home assumption, unchanged).
- *Depth gate at authorise vs consume skew*: a recovery
  authorised at depth d may find the head moved by consume
  time — handled by head-only matching + binding, refused,
  envelope burns (the standing "failed consume burns the
  issuance pair" liveness figure, unchanged).
- *Hand-built journals in tests* with recomputed hashes can
  carry lying lineage — true of every field in every journal
  in this system; the journal lives in the verifier home and
  its integrity anchor is the consumption anchor. Not a new
  surface.

---

## WS4 — Crash/restart coverage across the multi-artifact boundary

The boundary: loop `state.json` ↔ PinStore
`snapshot-pin.json` ↔ pending journal `adoption-pending.jsonl`
↔ side file `snapshot-candidate.json` ↔ verifier-home
journals/anchors. Injection methods, in order of preference:
**(S) state surgery** — perform a prefix of the real flow,
then edit/delete/truncate files exactly as a crash or disk
fault would leave them, then restart with fresh objects;
**(F) in-process fault injection** — subclass/wrapper around
`PinStore` or the client in the test only (the existing
test_05 pattern; no production seam); **(K) subprocess
kill** — a child process running the real flow is
`SIGKILL`ed at a barrier for the two cases where in-process
injection cannot prove the process boundary (C1, C2b).
Child helper: `tests/crash_child_pin_adoption.py` (not
`test_`-prefixed, so discovery ignores it), parameterised by
argv: fixture root + barrier name; it touches a barrier file
and waits, or proceeds past a named point and `os._exit`s.
New test file: `tests/test_trust_pin_adoption_crash.py`,
reusing the `test_trust_pin_adoption.py` fixture shape
(research-mode client is fine HERE — WS4 is about the
adopter-side boundary, and WS2 covers production mode; using
the production fixture for C7's two-process case only where
noted).

| # | Case | Injection | Pinned expected behaviour |
|---|---|---|---|
| C1 | Process termination **after consumption, before adoption** | (K) Child runs the ceremony path and is killed after the verifier's consume returns but before `PinStore.adopt` (child calls the consumer + `reanchor_pin` via a barrier: it signals "consumed" by writing a marker the parent waits on, parent kills before adopt). | Consumption journal: exactly 1 entry (the burn). Pin store: unchanged (pin file bytes identical). Restart (fresh `PinAdopter` + fresh `CoreLoop` on the same dirs): the returned pair is lost with the process, so recovery is the pending-journal path — `snapshot_and_adopt` computes `burned_unadopted`, runs a recovery ceremony (WS3: depth 1, `recovery_of` = the burn), adopts. Assert: 2 consumptions total, second entry's lineage correct, pin at target, original authorisation re-presented to consume refuses `ceremony_already_consumed`. |
| C2a | Torn **pending-journal** write (crash mid-append) | (S) After a completed `authorised` journal append, truncate the file mid-line (drop the last k bytes so the final line is invalid JSON). | `_read_journal` skips the torn line (existing behaviour, now pinned): if the torn line was `authorised`, burn detection is lost → next attempt takes the primary path → the verifier refuses the consume (`AlreadyConsumed`) → `PinAdoptionBurned` with NO returned pair → the movement waits for the next snapshot sequence, where a primary `chain_gap_recovery` succeeds. Assert: no duplicate consumption ever occurs; refusal class is Burned, not a crash; journal is not "repaired" or rewritten by the read path. |
| C2b | Kill **during** pending-journal persistence | (K) Child loops `snapshot_and_adopt` attempts on a gap state; parent kills at a random point after the barrier; repeat 5 iterations over fresh fixtures. | After each kill: pending journal parses as ≥0 complete lines + at most one torn tail; pin store passes `read_all` verification; consumption count equals the number of ceremonies the verifier actually committed (cross-checked against the verifier home, never against the journal's own claim). |
| C3 | **Pending-journal corruption** (whole file) | (S) Overwrite `adoption-pending.jsonl` with non-UTF-8 garbage; separately, with valid JSON lines of the wrong shape. | Both read as "no burns detected" (detection aid semantics): behaviour reduces to C2a's lost-detection path — fail-closed at the verifier, zero extra consumptions, `PinAdoptionBurned`. The test's load-bearing assertion: **adopter-journal corruption can cost liveness, never integrity** — consumption count and pin are exactly as the verifier/store dictate. |
| C4 | **Side-file loss** (`snapshot-candidate.json`) | (S) Advance once (side file written), delete the side file, attempt `snapshot_and_adopt` on unchanged state; then run one more cycle and attempt again. | Unchanged state: `PinAdoptionRefused` (a fresh signing cannot reproduce the pinned hash; `already_current` is unreachable without a retained envelope — the documented TTL/retention limit, now pinned as expected behaviour, nothing persisted, no consumption). After the new cycle: dense advance succeeds normally (prev link = pin hash). Assert pin store bytes unchanged by the refused attempt. |
| C5a | Restart with **returned pair available** | (F)+(S) Drive consume-committed/adopt-failed in-process (test_05 pattern) capturing `PinAdoptionBurned.returned_pin/record`; discard ALL objects; build fresh `PinAdopter`/`PinStore` on the same dirs; call `adopt_returned`. | Adoption succeeds with **zero new consumptions** (count unchanged), pin at target, history gains the record; a subsequent `snapshot_and_adopt` reports `already_current`. |
| C5b | Restart with **returned pair discarded** | (S) As C5a but the pair is dropped (only dirs survive). | Fresh `snapshot_and_adopt` → recovery ceremony under `burned_unadopted` (never `lost_pin` — assert the record's reason and the consumption entry's lineage: kind recovery, depth 1); total consumptions 2; pin at target. (Extends test_05b across a full object restart.) |
| C6a | **Recovery-after-recovery burns** (within WS3 bound) | (F) Fault-inject `PinStore.adopt` to fail for the primary ceremony AND for recovery-1 (fail-first-2 wrapper), succeed for recovery-2. | Recovery-2 consumes at depth 2 and adopts; journal lineage chain: primary depth 0 → recovery depth 1 (`recovery_of` = primary's authorisation) → recovery depth 2 (`recovery_of` = recovery-1's authorisation); pin at target; total consumptions 3. |
| C6b | **Recovery exhaustion** (WS3 bound reached) | (F) As C6a with fail-first-3. | Recovery-3 authorise refuses `ceremony_recovery_unproven` (adopter surfaces `PinAdoptionRefused`); consumptions stay 3; THEN one more loop cycle lands and `snapshot_and_adopt` succeeds via a primary `chain_gap_recovery` for the new candidate — the exhaustion-is-not-a-deadlock proof (§3.5). |
| C7 | **Concurrent adopter instances**, same pin store | (K) Two child processes, barrier-synchronised, both run `snapshot_and_adopt` on the same gap-state fixture dirs (production fixture optional; research acceptable). | Exactly one child reports `reanchored`; the loser raises `PinAdoptionBurned` (its consumption may have committed — `PinMovedError` path) or `PinAdoptionRefused`. Invariants asserted by the parent: pin store verifies (`read_all`), history has no duplicate targets and no fork (`_check_consistency` passes by construction of the verified load), consumption count ∈ {1, 2} and every consumption's target is the same movement, final pin = the target. No child hangs (flock is bounded by the store's existing busy behaviour). |

Cross-cutting assertion for every case: after the scenario,
a fresh `PinStore.read_all` and a fresh consumption-ledger
load both verify, and the loop state file parses under a
fresh `CoreLoop` — i.e. no case leaves any artefact in a
state its own loader refuses (except C3's journal, which is
*defined* to be skippable garbage — the assertion there is
that reads tolerate it, per its detection-aid contract).

Failure-mode note (design-level, not a test): C2a/C3 expose
the known rev-r6 F4.2 residual — recovery liveness depends
on the adopter's unanchored local pending journal. WS4 pins
the *consequence* (liveness loss, never integrity loss) as
tested behaviour. Anchoring the pending journal is NOT in
this cycle's scope; the claim wording (§6) must not imply
the residual is closed.

Claim wording — may claim: "Crash/restart behaviour across
the loop state, pin store, pending journal, side file, and
verifier journals is covered by named tests C1–C7, including
process-kill injection; in every case the failure resolves
as refusal or bounded recovery, never as a duplicate
consumption or a corrupted store." May NOT claim: that the
pending journal is trustworthy evidence a ceremony did not
happen (it is a detection aid; C2a/C3 pin exactly that
limit), or that crash-atomicity spans the boundary (the
design reconciles; it does not transact).

---

## WS5 — Ledger-head-anchoring completion

Backlog item (verbatim): "Anchor ship/signing ledger heads
outside writable storage so ledger rollback or deletion is
detectable without a caller-supplied pin". Current gap, from
the code: `record_ship` REQUIRES a caller-supplied
`expected_ledger_head` (shipcheck.py) and only verifies +
updates a ship anchor when `anchor_path` is passed;
`recover_ship_tx` takes anchor paths optionally; nothing in
the repo's own operation passes either, and no anchor files
exist for `state/ship-ledger/`. The "signing ledger" half of
the title is already served on the verifier side by
`AION_ANCHOR_PATH` (kind `signing`, mandatory in production,
§2) — WS5's scope is the loop-side ledgers in
`state/ship-ledger/`: kinds `ship` and `ship-tx`, for which
`trust/anchoring.py` already has everything needed
(`initialise_anchor` with its established-ledger ceremony,
`verify_anchor`, `update_anchor`). No anchoring.py change.

### 5.1 (a) Anchor-derived head pinning on the sanctioned path

New function in `trust/shipcheck.py`:

```python
def anchored_record_ship(loop, *, root, manifest, signed,
                         signing_key, ledger, coders, reviewers,
                         delta, release=None,
                         expected_signer_id=None,
                         expected_attestation=None,
                         recorded_at="",
                         ship_anchor_path, tx_anchor_path) -> dict:
    """record_ship with the ledger head derived from the
    ship anchor instead of supplied by the caller. …"""
```

Semantics, in order:

1. **Hook guard inherited**: `record_ship`'s §1.3 guard
   applies (the wrapper calls `record_ship`; a hooked loop
   refuses there, pre-burn).
2. **Derive, don't accept**: the wrapper takes NO
   `expected_ledger_head` parameter. It loads the ship
   anchor (`trust.anchoring.load_anchor`) and reloads the
   ledger, then requires the anchor to name the ledger's
   CURRENT head exactly:
   - `verify_anchor(ledger, ship_anchor_path, kind="ship")`
     must return `()` — this alone tolerates a *stale* anchor
     (an older prefix verifies), so the wrapper additionally
     requires `anchor["seq"] == len(ledger.entries())` and
     `anchor["head"] == ledger.head()`. A stale anchor
     refuses with `ShipRefused("ship anchor is stale: …;
     advance it with update_anchor as an operator act, or
     recover_ship_tx — refusing to derive a head pin from a
     prefix")`. Rationale: deriving `expected_ledger_head`
     from the ledger itself would be circular (the pin would
     certify whatever the ledger currently says); deriving
     it from the anchor is non-circular only when the anchor
     independently names the same current head — equality of
     an outside-the-ledger value with the ledger's head IS
     the check. A caller-supplied head passed to plain
     `record_ship` remains available for legacy/test callers,
     but the sanctioned path no longer accepts one: on this
     path there is nothing for a caller to supply, so there
     is nothing to cross-check — the parameter's absence is
     the cross-check. (Rejected: keeping an optional
     caller head and cross-checking it against the anchor —
     a parameter that can only ever refuse or agree adds an
     oracle and a confusion surface, and its agreement case
     proves nothing the anchor didn't.)
   - Same currency check for the tx journal against
     `tx_anchor_path` (kind `ship-tx`): `ShipTxJournal`
     reload + `verify_anchor` + seq/head equality. A
     rolled-back tx journal (which `recover_ship_tx` would
     otherwise read as evidence) refuses the ship before
     anything is spent.
   Both verifications happen BEFORE `record_ship` is
   called, hence before any transaction is opened or burn
   attempted: an anchor refusal leaves the tx journal
   byte-unchanged (asserted in tests, §5.3 T5).
3. **Delegate**: call `record_ship(..., expected_ledger_head=
   anchor["head"], anchor_path=ship_anchor_path)` — reusing
   the existing pre-burn anchor verification and the
   post-finalise ship-anchor `update_anchor` unchanged.
4. **Advance the tx anchor**: after `record_ship` returns
   (transaction COMMITTED, tx journal grown), call
   `update_anchor(tx_journal, tx_anchor_path, kind="ship-tx",
   recorded_at=stamp)`. Failure raises `ShipRefused` with
   the same shape as the existing ship-anchor post-commit
   failure ("cycle N recorded and decision … finalised, but
   the ship-tx anchor update failed: …") — the cycle stands,
   the stale tx anchor refuses the NEXT anchored ship until
   an operator advances it, which is the designed loud
   failure, not a silent gap. (`record_ship` itself does not
   grow this duty: it does not own the tx anchor today —
   `recover_ship_tx` only verifies it — and the wrapper is
   the composition point. Rejected: teaching `record_ship`
   a `tx_anchor_path` parameter; it would leave TWO
   sanctioned paths with different anchoring behaviour.)
5. `recover_ship_tx` callers in operations pass both anchor
   paths from now on (they already accept them); the
   wrapper's docstring states the pairing. No signature
   change there.

Module docstring of shipcheck.py gains a paragraph: the
sanctioned path is now `anchored_record_ship`; plain
`record_ship`'s caller-supplied head is the legacy form, and
its own docstring's "why the cycle records should pin the
head" passage is updated to name the wrapper. The trust
lint's counted allowlist is unaffected (no new
`run_one_cycle` call site: the wrapper calls `record_ship`,
which holds the existing one).

### 5.2 (b) Initialise + verify anchors for the real state/ship-ledger

Placement: `state/anchors/ship.anchor.json` and
`state/anchors/ship-tx.anchor.json` — a sibling directory of
`state/ship-ledger/`. Checks: `_check_outside_journal`
requires the anchor outside the journal's own directory —
`state/anchors/` satisfies it for both journals (their
directory is `state/ship-ledger/`). Rejected placements:
inside `state/ship-ledger/` (refused by the code and defeats
the purpose); inside the verifier home (wrong trust domain —
these are loop-side ledgers; and the WS2 home is disposable);
outside the repo (not provisioned on this VM, unversioned,
and the operator act must be reviewable in the repo's own
record).

Honesty about "outside writable storage": on this VM the
anchors are same-user writable, like everything else. What
the placement + git gives, precisely: the anchor files are
committed to the repo, so (i) rollback or deletion of a
ledger ALONE is detected by `verify_anchor` against the
working-tree anchor; (ii) joint rollback of ledger + anchor
in the working tree is detected against the committed anchor
(`git diff` / a fresh checkout) — the pin ultimately lives
in git history. The claim in §5.5 is worded to exactly this
strength and no further; true off-machine pinning remains a
deployment property (as with the verifier anchors, whose
"outside the home" is an OS-boundary property only once
provisioned).

The ceremony (an operator act performed once in this cycle,
scripted in `internal/cycle23-work/initialise_state_anchors.py`
and logged in the build record):

1. **Pre-ceremony verification** (all must pass, all logged):
   - ship ledger loads; 4 entries; head =
     6911dff48f3e325255acf3c490908cf8917c3e121f8cd998a80f88d2ab572870;
     last entry kind `finalise` (no dangling burn).
   - ship-tx journal loads; 6 entries; every transaction in
     a terminal state (read via `ShipTxJournal` — a
     non-terminal tx would mean an unsettled ship, and
     anchoring over it would bless an anomaly).
   - Cross-checks against independent records: the ship
     ledger file's git history (`git log --follow --
     state/ship-ledger/ship-ledger.json`) shows no rewrite;
     the head is consistent with the build records that cite
     ship-ledger state (BUILD-CYCLE-8's record pins an
     earlier head in this chain — verify the current chain
     *contains* that prefix via `_chain_prefixes`, i.e. the
     anchored history extends, not replaces, the recorded
     one). If any check fails: STOP, no ceremony, escalate —
   initialising over an unverified established ledger is
     exactly the laundering `allow_nonempty_ceremony` warns
     about.
2. **Ceremony**: `initialise_anchor(ship_ledger,
   state/anchors/ship.anchor.json, kind="ship",
   recorded_at=…, allow_nonempty_ceremony=True)` and the
   same for the tx journal with kind `"ship-tx"`. The flag
   is the documented established-ledger ceremony; the
   operator assertion it encodes ("this history is the true
   one") is discharged by step 1's checks, which are listed
   in the build record next to the resulting anchor
   (seq, head) pairs.
3. **Post-ceremony verification**: `verify_anchor` returns
   `()` for both; the wrapper's currency check (§5.1 step 2)
   passes for both; both files committed with the cycle.
4. **Operational consequence, stated in the build record**:
   from this point, any `record_ship` against the real
   ledgers that bypasses the anchored path leaves the
   anchors stale, and the next anchored ship refuses until
   an operator advances them. That friction is intended:
   the anchored path is the sanctioned path.

### 5.3 (c) End-to-end proof in the WS1 sandbox

In `tests/test_trust_shipcheck_anchored.py`, reusing the
existing shipcheck test fixtures (manifest builder, signed
ship decision, release record — the `test_trust_shipcheck.py`
helpers) over a temp state + temp ledger dir:

- T1 `test_anchored_ship_records_and_advances_both_anchors`:
  initialise both anchors on a fixture ledger with history
  (allow_nonempty), run `anchored_record_ship` for the
  fixture item → cycle recorded; ship anchor advanced to the
  post-finalise head; tx anchor advanced to the post-COMMIT
  tx head; both `verify_anchor` clean and current.
- T2 `test_ledger_rollback_detected_pre_burn`: after T1's
  ship, restore the ship ledger file to its pre-ship bytes
  (rollback by one finalise) → `anchored_record_ship` for a
  second decision refuses `ShipRefused`; assert NOTHING was
  spent: no new burn, and the tx journal gained no
  transaction (the wrapper refused before delegating).
- T3 `test_ledger_deletion_detected`: delete the ship
  ledger file (loads as empty) → refusal
  (`anchor_ahead_of_journal` class via the currency check);
  nothing spent.
- T4 `test_tx_journal_rollback_detected`: roll back only
  `ship-tx.json` → refusal pre-burn; ship ledger unchanged.
- T5 `test_stale_anchor_refused_not_silently_derived`:
  append a legitimate burn+finalise via plain `record_ship`
  with a caller head (bypassing the wrapper) → the ship
  anchor is now stale → `anchored_record_ship` refuses with
  the stale-anchor message (this pins §5.1's anti-circularity
  rule: the wrapper never derives a pin from a prefix).
- T6 `test_caller_head_parameter_absent`: inspect the
  wrapper's signature — no `expected_ledger_head` parameter
  exists (a signature test, so the parameter cannot quietly
  return).
- T7 `test_recovery_with_anchors`: crash a ship mid-way
  (existing recover fixtures), `recover_ship_tx(…,
  anchor_path=…, tx_anchor_path=…)` settles it; and with the
  ledger rolled back, recovery parks/refuses per the
  existing anchor classification (no new behaviour — the
  test pins that the real-path pairing works).

And the WS1 live-run sandbox (§1.5) reuses its COPY of the
ship ledger for one additional logged step 7: initialise
anchors on the copy, run one `anchored_record_ship` for a
real (sandbox) cycle with full ship artefacts, then truncate
the copy's ledger and show the anchored path refusing. This
is a log artefact, duplicating T1/T2 at run scale; the tests
are the gate, the run is the demonstration.

### 5.4 (d) Should the REAL state/state.json advance this cycle? — NO

Recommendation: **cycle 23 initialises the real anchors
(§5.2) but does NOT record any cycle in the real loop state.
The `ledger-head-anchoring` item stays `pending` in the real
backlog; recording it is a follow-up ship after external
reconciliation of cycle 23.** Reasoning:

1. **Self-reference**: recording an item requires a signed
   ship decision over a manifest of the final tree plus a
   release record binding the pre-ship state. Cycle 23's
   tree includes cycle 23's own build record, tests, and
   this design's descendants — the manifest can only be
   finalised once the cycle's content is frozen, and the
   recording would itself be a state change the cycle
   reports. Prior cycles solved this by recording in a
   *later* ship; nothing about WS5 changes that arithmetic.
2. **Provisional status**: cycle 23 ships provisionally
   pending the external seats (the standing rule; cycles
   14–16 are held on exactly this). Recording
   `ledger-head-anchoring` as `done` in the real loop would
   assert completion of an item whose WS3 component
   *re-rules a split external decision* — the precise claim
   the external seats have not yet ratified. If they FIX,
   the loop would carry a `done` for a superseded design.
   The anchors, by contrast, assert only facts about
   *existing* history (verifiable today, §5.2 step 1) and
   remain true regardless of the cycle-23 verdict.
3. **Sequence integrity**: the real history is cycles 1–13.
   The held build cycles' work is not in the loop backlog as
   items to record out of order — the loop records ITEMS in
   `pick_next` order, and `ledger-head-anchoring` happens to
   be pickable now, but picking it records "this item is
   done", full stop. There is no partial-credit entry. The
   item becomes honestly recordable the moment cycle 23 is
   reconciled; the follow-up ship then records it as loop
   cycle 14 through `anchored_record_ship` — which is also
   the first production use of the wrapper against the real
   ledgers, a cleaner proof than bundling it into the
   provisional cycle.
4. **The sandbox already proves the path** (§5.3 + §1.5
   step 7): the only thing deferring the real recording
   loses is simultaneity, and simultaneity is what the
   provisional rule exists to prevent.

Rejected alternative — record it in-cycle: it would make
cycle 23 the first cycle whose loop recording precedes its
external reconciliation, inverting the standing practice for
exactly the cycle that re-opens a split external ruling.
The war room should not accept that inversion silently; if
Dilip or the room wants it, it is a separate recorded
decision, not a design default.

### 5.5 WS5 claim wording

May claim: "Ship and ship-tx ledger heads for the repo's own
state are anchored outside the ledger directory and
committed; the sanctioned ship path derives its ledger-head
pin from the ship anchor (it accepts no caller-supplied
head), refuses on a stale, rolled-back, or deleted ledger
before spending anything, and advances both anchors as part
of the ship. Rollback of the real ship ledger alone is now
detectable; joint ledger+anchor rollback is detectable
against the committed anchor." May NOT claim: "outside
writable storage" in the strong sense (same-user VM, §5.2 —
the backlog title's wording is aspirational until deployment
provisioning); that the `ledger-head-anchoring` backlog item
is recorded/done in the real loop (it is not, §5.4); that
plain `record_ship` is anchor-safe (its caller-supplied head
remains the legacy form).

---

## 6. Consolidated change list

**Production code (5 files):**

| File | WS | Change |
|---|---|---|
| `core/loop.py` | 1 | Optional `cycle_hook` (constructor, property, one post-save call, docstring contract). Protected-file change: minimal, stdlib-only. |
| `trust/pin_adoption.py` | 1 | `pin_cycle_hook()`; `cycle_entry` slot on `PinAdoptionRefused`; hooked-loop guard in `run_one_cycle_and_pin`; wording touch for WS3 (§3.7). |
| `trust/shipcheck.py` | 1, 5 | Hooked-loop guard in `record_ship`; new `anchored_record_ship`; docstring updates. |
| `trust/ledger.py` | 3 | Key-set/version seams on `HashChainJournal`; consumption-journal schema v2 + lineage + depth cap; issuance-journal v2 binding field. |
| `trust/verifier_main.py` | 3 | Authorise: capture + record the 5b binding. Consume: thread the binding into head check + commit. No new codes, no body changes. |

**Records / state (no code):** `internal/DECISION-CONSUMPTION-HEAD.md`
Addendum 3; `state/anchors/ship.anchor.json` +
`state/anchors/ship-tx.anchor.json` (real ceremony, §5.2);
`internal/cycle23-work/` run + provisioning artefacts
(`live_run.py`, `provision_disposable.py`,
`initialise_state_anchors.py`, `LIVE-RUN-23.md`).

**Tests (4 files touched/created):** `tests/test_core_loop_hook.py`
(new, 8); `tests/test_trust_pin_adoption.py` (+3);
`tests/test_trust_shipcheck.py` (+1);
`tests/test_trust_production_e2e.py` (new, ~7);
`tests/test_trust_consumption_schema_v2.py` (new, 10);
`tests/test_trust_ceremony_consumption.py` (2 re-pins + 2 new);
`tests/test_trust_pin_adoption_crash.py` (new, C1–C7 ≈ 10 test
methods) + `tests/crash_child_pin_adoption.py` (helper, not
collected). Expected total ≈ 1547 + ~41 new, minus 0 removed
(the 2 re-pins replace expectations in place), skipped=28.

**Explicit non-changes:** `signing/pin_ceremony.py` (wording
only, §3.7), `signing/ceremony_authorisation.py` (envelope
format untouched), `signing/pin_store.py` (untouched),
`trust/anchoring.py` (untouched — WS5 reuses it whole),
`trust/wiring.py` (untouched), the deploy wrapper and its
19-key allowlist (untouched), `state/state.json` and
`state/ship-ledger/*` contents (untouched — anchors are new
files beside them).

## 7. Global failure-mode summary

The cycle's theme is reconciliation over transaction: no
workstream makes two artefacts atomic. WS1 leaves loop and
pin reconcilable by the next adoption attempt; WS3 leaves
lineage forgeable only by an attacker already inside the
verifier home (the intact-home assumption, unchanged since
cycle 21); WS4 pins that every crash at the boundary
resolves as refusal or bounded recovery, with liveness —
never integrity — as the only currency paid; WS5 makes
ledger rollback loud at the next sanctioned ship rather
than impossible. The two named residuals that survive this
cycle, stated for the brief: (R-a) the adopter's pending
journal is unanchored, so burn *detection* (not burn
validity) can be lost with it (WS4 C2a/C3); (R-b) the
issuance journal remains unanchored (the narrowed
`ceremony-journal-anchoring` follow-up), so the WS3 binding
inherits its rollback posture — fail-closed in every
rollback shape §3.9 enumerates, but a rolled-back issuance
journal can still cost a recovery its binding. Neither
residual is new; WS3/WS4 make both more precisely bounded,
and the cycle-23 brief must carry both verbatim.

## 8. What this design asks the war room / external seats to rule on

1. WS3's re-ruling (bounded chains, depth cap 2, binding via
   the issuance journal) as the successor to Addendum 2's
   one-shot — the seat-gemini ratification question.
2. WS5 §5.4's recommendation (anchors now, real recording
   after reconciliation) — an internal ruling; the external
   brief should state it as taken, not ask permission for it.
3. Item (3)'s unqualified closure remains the external
   question for the cycle-23 brief; this design's position
   is that WS1+WS2+WS4 close the integration/crash gaps both
   seats named, and WS3+WS5 close the schema and anchoring
   gaps — but closure is the seats' call, and cycles 14–16
   stay held until they make it.
