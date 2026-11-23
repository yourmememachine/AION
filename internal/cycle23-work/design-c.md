# Cycle 23 — Design C (operability seat): production integration of the ceremony line

Seat: DESIGN C. Scope: all five workstreams. This design writes no
production code; it is the build contract candidate for the war room.
Grounding: CROSS-CHECK-16 (GPT FIX 0.91 / Gemini FIX 0.84, split on
one-shot and on cycles 14–16), CROSS-CHECK-15, BUILD-CYCLE-22,
DECISION-CONSUMPTION-HEAD.md incl. Addendum 2, and the cycle-22 code
as read at commit 59a656a (1547 tests).

**Hard constraints honoured throughout:** cycles 14–16 are NOT
re-reviewed, NOT shipped, and NOT recorded in loop state by this
cycle. `core/loop.py` stays stdlib-only and network-free. No claim in
this design upgrades a research-mode or same-user result into a
production-deployment result.

**Headline choices (details and rejected alternatives per section):**

| WS | Choice |
|---|---|
| WS1 | Constructor-injected optional `cycle_hook` on `CoreLoop` (default `None` = today's behaviour bit-for-bit). Hook fires exactly once, after `save()`, only for a recorded cycle. Hook failure raises a new stdlib `PostCycleHookError` carrying the entry; state is **never** rolled back for a hook failure. Contract: *cycle recorded, pin pending, alert*. |
| WS2 | One provisioning script builds a disposable **production-mode** verifier home in a temp dir; bootstrap order is research-mode INIT ceremonies first, then mode flipped to production with all INIT flags absent. Same-user spawn only — this proves production *mode*, not production *deployment* (separate OS user is not provisioned on this VM and `production_client(launch="wrapper")` is refused by design). |
| WS3 | Consumption-journal schema v2 via **dual entry key-sets + positional monotonicity** (no top-level journal marker — rejected, §3.2). Lineage (`consumption_kind`, `recovery_of`, `recovery_depth`) is computed verifier-side; race-safety requires the *issuance* journal to record `recovery_of_authorisation_id` at authorise step 5b under the same dual-set versioning (§3.4 — flagged as the one scope addition the coordinator must ratify). **Recovery bounds re-ruled: bounded chain, depth cap 2** (§3.6). Pair-scan removed for v2 heads, kept as the v1-head fallback only. |
| WS4 | Seven crash/restart scenarios, each with a named injection method (subprocess SIGKILL at barrier files for true process death; state surgery for corruption/loss; the existing monkeypatch pattern only where cycle 22 already uses it). One new adopter behaviour falls out of the analysis: a `suspected_burn` journal line so a lost `authorised` line cannot dead-end recovery selection (§4.3). |
| WS5 | `record_ship` derives `expected_ledger_head` from the ship anchor when `anchor_path` is given; a caller-supplied head that disagrees with the anchor is **refused**, never silently overridden. Real anchors for `state/ship-ledger/` are **initialised this cycle** (pin-only, no state advance). Real `state/state.json` is **NOT advanced this cycle** (§5.4). |

**Operability thesis (this seat's weighting):** after cycle 23 the
operator's day-to-day surface is exactly three commands and two
artefact directories (§6). Everything else in this design exists to
make those three commands safe to run unattended-by-an-expert.

---

## WS1 — Loop integration + live run

### 1.1 The hook (the entire `core/loop.py` change)

`core/loop.py` is in `eval/gate.py`'s `PROTECTED_FILES`. The change
is therefore the smallest change that makes pinning unavoidable for
any cycle recorded through a hooked loop instance, and inert for
every existing caller.

**Change list — `core/loop.py` (only file touched in `core/`):**

1. New exception, stdlib only, near `InvalidTransition`:

   ```python
   class PostCycleHookError(Exception):
       """The cycle was recorded and persisted; the post-cycle hook
       failed. ``entry`` is the recorded history entry (a copy).
       The original hook exception is chained as __cause__."""
       def __init__(self, entry, message): ...
   ```

2. `CoreLoop.__init__(self, state_dir, *, cycle_hook=None)`:
   stores `self._cycle_hook = cycle_hook`. No validation beyond
   `callable()` check → `ValueError` at construction (fail at
   wiring time, not mid-cycle). Default `None` preserves every
   current call site (`CoreLoop(state_dir)` appears across the
   suite and in `trust/shipcheck.py` flows) with zero behaviour
   change.

3. In `run_one_cycle`, the current body ends with
   `self.save()` inside the `try:` whose `except BaseException`
   restores the in-memory snapshot. The hook must **not** live
   inside that `try`: a hook failure after a successful `save()`
   must not restore `self.state = snapshot`, because the on-disk
   state has already advanced — restoring memory would make the
   live object disagree with disk (the exact split-brain
   `save()`'s discipline exists to prevent) and a later `save()`
   from the restored object would silently un-record the cycle.
   Restructure minimally: keep the existing try/except for the
   mutation+save block unchanged; after it, replace
   `return copy.deepcopy(entry)` with:

   ```python
   result = copy.deepcopy(entry)
   if self._cycle_hook is not None:
       try:
           self._cycle_hook(copy.deepcopy(entry))
       except Exception as exc:
           raise PostCycleHookError(
               result, f"cycle {result['cycle_id']} recorded; "
               f"post-cycle hook failed: {exc}") from exc
   return result
   ```

   `BaseException` (KeyboardInterrupt/SystemExit) from the hook is
   deliberately **not** wrapped: process-control exceptions keep
   their semantics; the cycle is still recorded, and the operator
   runbook (§6) treats an interrupted driver as "pin pending"
   because the pin check in `verify_live_run.py` is state-based,
   not exit-code-based.

**Hook semantics, pinned:**

- **When:** after `save()` has fsynced and replaced `state.json`,
  before `run_one_cycle` returns. Exactly once per recorded cycle.
  Never on the idle path (`pick_next()` is `None` → return `None`,
  no hook call — pinning an unchanged state would mint a snapshot
  of nothing new and, on the ceremony path, waste an evidence
  bundle). Never from `scan()`/`approve()` saves (those are not
  cycles; a snapshot attests a *cycle's* state).
- **Argument:** a deep copy of the history entry (same object
  shape the caller receives). The hook gets no loop handle and no
  state dict: everything the adopter needs it reads from disk
  itself (`PinAdopter._read_consistent_pair` already re-reads
  state+calibration bytes from paths). This keeps `loop.py` free
  of any knowledge of pins, snapshots, or the verifier.
- **What the production hook does:** `trust/pin_adoption.py` gains
  `make_pin_hook(adopter) -> Callable[[dict], None]`, a closure
  that calls `adopter.snapshot_and_adopt()` and lets
  `PinAdoptionRefused` / `PinAdoptionBurned` propagate unchanged
  (the loop wraps them in `PostCycleHookError` with the entry
  attached at the loop layer; the adopter exceptions already
  carry `returned_pin`/`returned_record` where applicable, and
  `PostCycleHookError.__cause__` preserves them — the driver in
  §1.3 unwraps exactly one level).
- **Failure contract:** *cycle recorded, pin pending, alert.* The
  cycle is durable in `state.json`; the pin simply has not moved.
  This is safe because of an existing asymmetry: the pin attests
  state bytes, and state only moves forward — a later
  `snapshot_and_adopt()` (next hooked cycle, or the operator's
  retry command in §6) attests the then-current state, by
  `advance_pin` if dense or by ceremony if a gap opened. A hook
  failure can therefore never strand the system in a state where
  the *recorded* history is wrong; it can only leave the pin
  behind, which is the ceremony line's native, already-handled
  condition.
- **Idempotence on retry:** re-running the hook's work for an
  already-pinned state yields the adopter's existing
  `already_current` outcome (within the retained envelope's TTL)
  or a refusal — never a second consumption of the same target
  (consumption head + `_check_ceremony_history` both refuse).

**Rejected alternatives:**

- *Per-call hook parameter on `run_one_cycle(...)`.* Rejected:
  `record_ship` calls `run_one_cycle` internally (§1.2) and would
  silently bypass pinning unless every sanctioned caller remembers
  to pass the hook; constructor injection makes pinning a property
  of the loop instance, auditable at wiring time in one place.
- *Keep `run_one_cycle_and_pin` as the only integration (status
  quo).* Rejected: it is exactly the "loop never calls the
  adopter" defect both external seats named mandatory. It remains
  in `trust/pin_adoption.py` for test compatibility but is marked
  deprecated in its docstring; the production driver (§1.3) must
  not use it on a hooked loop (double adoption attempt: the
  wrapper's call would re-enter `snapshot_and_adopt`, which is
  safe — `already_current`/refusal — but wasteful and confusing
  in logs). The trust lint's existing allowlist entry for
  `("trust/pin_adoption.py", "run_one_cycle")` is unchanged.
- *Hook fires before `save()` / hook can veto the cycle.*
  Rejected: that inverts the forced ordering the adopter already
  documents ("a snapshot attests bytes that exist"). A pin for
  unpersisted state would attest bytes a crash could erase.

### 1.2 Interaction with `record_ship`

`record_ship` (trust/shipcheck.py) burns the decision, then calls
`loop.run_one_cycle(...)`, then re-verifies the manifest, then
finalises. With a hooked loop the sequence becomes:
burn → `run_one_cycle` records **and the hook pins** → manifest
re-verify → finalise. Two consequences must be designed for, not
discovered:

1. **Hook failure inside `record_ship`.** `record_ship` catches
   only `InvalidTransition` around `run_one_cycle`.
   `PostCycleHookError` therefore propagates out of `record_ship`
   *after* the burn and *after* recording, with the ship-tx
   journal left at `BURN_PENDING`. That is recoverable by design:
   `recover_ship_tx` settles burn + unambiguously-recorded-cycle
   to `COMMITTED` without re-burning or re-running. **Design
   ruling:** do not add a catch in `record_ship` this cycle; the
   tx journal's non-terminal state *is* the alert artefact, and
   `recover_ship_tx` is the documented settlement path. The WS5
   sandbox proof (§5.3) includes this exact interleaving as a
   test. (Changing `record_ship`'s exception table is a larger
   protected-path change than the evidence justifies.)
2. **Pinning is not gated on finalise.** The pin may move for a
   cycle whose ship tx later parks at `ANOMALY` (tree drift).
   Acceptable and stated: the pin attests *loop state bytes*,
   which did change; the ship tx anomaly is about the *tree*, a
   different artefact. The build record must not describe a
   pinned cycle as a finalised ship.

### 1.3 The driver and the live run (sandbox)

**New files (operability surface, §6):**

- `ops/provision_verifier_home.py` — WS2 provisioning (§2.2),
  used by both WS2's e2e and this live run.
- `ops/run_pinned_loop.py` — the production driver: builds the
  adopter via `build_pin_adopter` (hence `production_client`
  only), constructs `CoreLoop(state_dir, cycle_hook=make_pin_hook(adopter))`,
  runs N cycles from caller-supplied coders/reviewers/delta JSON,
  prints one JSON line per cycle `{cycle_id, item_id, pin_outcome}`,
  exit codes: 0 all pinned; 3 a cycle recorded with pin pending
  (`PostCycleHookError` unwrapped and reported, never retried in
  the same invocation); 2 no cycle recorded (idle or pre-cycle
  refusal).
- `ops/verify_live_run.py` — read-only evidence checker (§1.4).

**Sandbox layout** (all under one temp root, e.g.
`mktemp -d`, mode 0700; **nothing under the repo's real `state/`**):

```
<sandbox>/
  state/                 # byte copy of real state/ (state.json seq 13,
                         #   calibration/calibration.json, ship-ledger/)
  pins/                  # PinStore dir (outside state/, per PinStore rule)
  verifier-home/         # WS2 production-mode home (§2)
  anchors/               # signing + budgets + consumption anchors
  evidence/              # == verifier's AION_CEREMONY_EVIDENCE_DIR
  keys/                  # gate key + ceremony seed + snapshot key (0600)
  registry/              # minimal EvalRegistry (see §2.2 step 3)
  run-log.jsonl          # driver output, one line per step below
```

**Keys the sandbox needs (all freshly generated, never fixtures):**
(i) verifier gate key via `signing.gate_decision.generate_key_file`;
(ii) ceremony seed via `generate_ceremony_key_file` (the loaders
refuse the RFC/test seeds and any seed byte-equal or
derivation-overlapping the gate key — provisioning uses
independent `secrets` draws via those two generators, which is
the discipline `_load_config`'s R9 checks assume); (iii) snapshot
signing key via `generate_key_file` placed **outside** both
`state/` and `pins/` (`build_pin_adopter` enforces
`forbidden_roots=(state_dir, pin_dir)`). The snapshot signer id
is a new provisioning decision — there is no pre-existing pin for
the real state, so genesis binds whatever signer id the sandbox
provisions (use `aion-snapshot-1`); §7 lists this as a blocker
for any *real-state* pinning, not for the sandbox.

**Exact live-run sequence** (driver steps; each step's expected
artefacts in §1.4). Backlog reality check: in the copied state,
`pick_next()` returns `ledger-head-anchoring` (leverage 6.5,
seq 20 — earliest of the four 6.5-leverage pending items). The
sandbox therefore records *that* item as its first cycle. This is
a copy; recording it there advances nothing real (see WS5 §5.4
for why the distinction matters and is safe).

0. **Genesis pin (no cycle).** `adopter.snapshot_and_adopt()` on
   the untouched copy (state seq 13, no pin file) →
   `initial_anchor` ceremony: authorise → consume → adopt.
   Proves the genesis path against the *real* state bytes +
   real calibration bytes, not fixture bytes.
1. **Dense advance.** One hooked cycle via `run_pinned_loop.py`
   (records sandbox cycle 14, item `ledger-head-anchoring`) →
   hook pins seq 14 by `advance_pin` (pin 13→14, no ceremony, no
   consumption). Proves the hook fires from inside
   `run_one_cycle`, including when reached through the plain
   driver.
2. **Unpinned cycles (gap creation).** Construct a *plain*
   `CoreLoop(state_dir)` (no hook — the operability escape hatch,
   and the reason the hook defaults off) and run 2 cycles
   (sandbox cycles 15, 16). Pin stays at 14. These use the
   driver's `--no-pin` mode, which is the same code path with
   `cycle_hook=None`; the run log records the mode explicitly so
   the gap is auditable, not accidental.
3. **Chain-gap recovery.** `adopter.snapshot_and_adopt()` directly
   (no new cycle) → candidate seq 16 vs pin 14 classifies
   `reanchor_required` → `chain_gap_recovery` ceremony →
   consumption #2 → pin at 16. Proves the gap created by real
   loop mechanics (not by hand-editing seq numbers) is recovered
   by the ceremony.
4. **Dense again.** One hooked cycle (sandbox cycle 17) →
   `advance_pin` 16→17. Proves the system returns to the cheap
   path after a ceremony and the pending journal shows the
   ceremony `adopted`.

Total verifier consumptions for the whole live run: **exactly
2** (genesis + gap). Any other count fails the run.

### 1.4 Evidence artefacts the live run leaves behind

`verify_live_run.py <sandbox>` checks and prints, read-only:

- `pins/snapshot-pin.json`: pin seq 17; history of exactly 2
  ceremony records (`initial_anchor` for 13, `chain_gap_recovery`
  14→16), each re-verified via `verify_ceremony_record` with pin
  context; pin == history-consistent head-or-later (17 advanced
  past the ceremony head 16 by `advance_pin`, which leaves no
  record — the checker asserts pin seq ≥ last record seq and, for
  seq 17, that the retained candidate side file's hash equals
  the pin hash).
- `pins/adoption-pending.jsonl`: both ceremonies reach phase
  `adopted`; no `authorised`/`consumed` line lacks its `adopted`.
- `pins/snapshot-candidate.json`: retained candidate == pin at 17.
- Verifier home: consumption journal length 2 (entries are v1
  shape in WS1's build order if WS3 lands after WS1 — the checker
  accepts either shape via `CeremonyConsumptionLedger`'s own
  loader, never by parsing JSON itself); signing ledger contains
  2 `sign` + 2 `consume` ceremony entries; consumption anchor
  `seq == 2` and `verify_anchor(...) == ()` for all three anchors.
- `state/state.json` in the sandbox: `cycle_seq == 17`, history
  items 14–17 present; the **real** `state/state.json` untouched
  (checker takes `--real-state` and asserts its sha256 equals the
  pre-run recorded hash — the runbook has the operator record it
  before starting).
- `run-log.jsonl`: steps 0–4 with outcomes
  `reanchored, advanced, unpinned×2, reanchored, advanced`.

### 1.5 WS1 tests (new/changed)

New file `tests/test_loop_pin_hook.py` (loop-level, no verifier):

1. `test_hook_fires_once_after_save_with_entry_copy` — hook
   observes state already on disk at seq N when called (reads
   `state.json` inside the hook and asserts), receives a copy
   (mutating it does not affect the returned entry or state).
2. `test_hook_absent_is_bit_identical_behaviour` — existing
   `test_loop.py` suite passes unmodified (asserted by the suite
   itself; this test pins `CoreLoop(dir)._cycle_hook is None`).
3. `test_hook_failure_raises_post_cycle_hook_error_state_kept` —
   hook raises `RuntimeError`; `PostCycleHookError` carries the
   entry, `__cause__` is the `RuntimeError`, on-disk
   `cycle_seq` advanced, in-memory `loop.state` agrees with disk
   (no snapshot restore), and a subsequent `save()` does not
   un-record the cycle.
4. `test_hook_not_fired_on_idle_or_scan_or_approve`.
5. `test_hook_base_exception_not_wrapped` — hook raising
   `KeyboardInterrupt` propagates as `KeyboardInterrupt`.
6. `test_non_callable_hook_refused_at_construction`.

Changed: `tests/test_trust_pin_adoption.py` gains
`test_10_hooked_loop_genesis_and_dense_advance` (real verifier
subprocess, research env as today — the production-mode variant
is WS2's test, §2.4) and `test_11_hooked_loop_hook_failure_is_pin_pending`
(adopter whose store dir is made read-only after genesis →
`PostCycleHookError`, cycle recorded, pin unmoved, next
`snapshot_and_adopt()` succeeds).

### 1.6 WS1 failure modes

| Failure | Behaviour | Recovery |
|---|---|---|
| Verifier down during hook ceremony | `PinAdoptionRefused`/`Burned` → wrapped `PostCycleHookError`; cycle stands | Next hooked cycle or §6 retry; if a consume may have landed, adopter's journal + WS3 lineage govern (§4) |
| Hook raises non-adopter bug (TypeError in closure) | Same wrap; pin pending | Fix code; state needs no repair — pinning is re-runnable |
| Driver killed mid-hook | Cycle recorded; pin unknown | `verify_live_run.py --check-pending` compares pin seq/hash to state seq snapshot hash; §6 runbook |
| Two drivers on one state dir | Loop has no cross-process lock (pre-existing); pin store CAS refuses the loser | Operability rule: one driver per state dir, stated in runbook; not a new interlock this cycle |

### 1.7 WS1 claim wording

**May claim:** "The production loop path pins every recorded
cycle: `CoreLoop` gained an optional post-cycle hook (default
off), the production driver wires it to `PinAdopter`, and a live
run against a byte copy of the real state (seq 13) exercised
genesis `initial_anchor`, a dense `advance_pin`, and a
`chain_gap_recovery` after two deliberately unpinned cycles, with
exactly two verifier consumptions."
**May not claim:** that the real `state/` is pinned (it is not —
the run is on a copy); that hook failure rolls back or blocks a
cycle (it does neither, by design); that pinning is enforced for
code that constructs a plain `CoreLoop` (the hook is opt-in at
wiring; enforcement is the driver's + lint's, as with the rest of
the sanctioned path).

---

## WS2 — Production-mode end-to-end

### 2.1 The full environment set

`production_client` (trust/wiring.py) validates a copy of the env
against `ALLOWED_ENV_KEYS` (19) and requires `REQUIRED_ENV_KEYS`
(9) non-empty, mode exactly `"production"`, and all INIT flags
absent/`""`/`"0"`. The verifier's `_load_config` additionally
requires, in production: `AION_CEREMONY_OPERATORS` non-empty,
`AION_CEREMONY_EVIDENCE_DIR`, `AION_CEREMONY_SIGNING_SEED_PATH`,
and — with the ceremony seed configured —
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH`. The disposable home must
therefore set **all 19 allowlisted keys except the three INIT
flags**, i.e. these 16:

| Key | Value in the disposable home |
|---|---|
| `AION_VERIFIER_KEY_PATH` | `<sb>/keys/gate.key` (0600, generated) |
| `AION_VERIFIER_SIGNER_ID` | `aion-verifier-1` (id grammar) |
| `AION_VERIFIER_ACTOR_ID` | `aion-verifier-actor-1` |
| `AION_REGISTRY_DIR` | `<sb>/registry` |
| `AION_VERIFIER_HOME` | `<sb>/verifier-home` |
| `AION_DEPLOYMENT_MODE` | `production` (steady state only; see bootstrap) |
| `AION_VERIFIER_PURPOSE` | `ship` |
| `AION_VERIFIER_TTL_SECONDS` | `900` |
| `AION_VERIFIER_PROPOSAL_BUDGET` / `AION_VERIFIER_IDENTITY_BUDGET` | defaults omitted→ but wiring allows absence; set `25`/`500` explicitly for reproducibility |
| `AION_ANCHOR_PATH` | `<sb>/anchors/signing.anchor.json` |
| `AION_BUDGETS_ANCHOR_PATH` | `<sb>/anchors/budgets.anchor.json` |
| `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` | `<sb>/anchors/consumption.anchor.json` |
| `AION_CEREMONY_OPERATORS` | `operator-1` (the adopter's `AION_PIN_OPERATOR_ID` must equal it) |
| `AION_CEREMONY_EVIDENCE_DIR` | `<sb>/evidence` |
| `AION_CEREMONY_SIGNING_SEED_PATH` | `<sb>/keys/ceremony.seed` (0600, generated) |

Plus the adopter-side env (NOT verifier allowlist, read by
`pin_adopter_config_from_env`): `AION_PIN_DIR`,
`AION_PIN_SIGNING_KEY_PATH`, `AION_PIN_SIGNER_ID`,
`AION_PIN_OPERATOR_ID`, `AION_PIN_EVIDENCE_DIR` (must resolve
equal to `AION_CEREMONY_EVIDENCE_DIR` — `build_pin_adopter`
refuses a mismatch). Out-of-band pins supplied as arguments, not
env: `expected_signer_id` (== env signer id), `expected_key_id`
(`key-<16 hex>` derived from the generated gate key at
provisioning time and printed once by the provisioning script
for the operator to record), `authorisation_public_key`
(derived from the generated ceremony seed at provisioning time;
the *seed* never leaves the verifier side — the provisioning
script derives the public key in the provisioning process and
emits only the public bytes/id into the run config).

All three anchor paths: absolute, pairwise distinct, resolved
outside `AION_VERIFIER_HOME`, not equal to the key path, not
inside the registry dir (`production_client` enforces each).

### 2.2 Provisioning steps (`ops/provision_verifier_home.py`)

Bootstrap order is forced by one fact: **production refuses
every INIT flag**, and anchors can only be created by an INIT
ceremony or `initialise_anchor`. So provisioning is a
two-phase act — bootstrap under research mode, then flip:

1. Create the layout (§1.3) with 0700 dirs. Refuse if any target
   path already exists (provisioning is genesis-only; a second
   run is an operator error, not an idempotent no-op).
2. Generate gate key + ceremony seed (§1.3). Verify the pair
   passes the same overlap checks `_load_config` performs by
   simply performing step 5's smoke invocation early — do not
   re-implement R9 in the script.
3. Create the registry: `EvalRegistry(<sb>/registry)` and add the
   three sealed fixture items (the ceremony modes never open the
   registry, but `_open_registry` is exercised by other modes and
   a production home with an unopenable registry is a broken
   home; the e2e in §2.3 includes one `gate`-adjacent smoke —
   `verify_envelope` on a self-signed envelope — to prove the
   home serves non-ceremony modes too).
4. **Bootstrap invocation set** (env identical to §2.1 except
   `AION_DEPLOYMENT_MODE=research` and the three INIT flags
   `=1`): invoke the verifier once per anchor need — in practice
   one `ceremony_consume`-free smoke request (any mode triggers
   `_load_config`, which performs all three anchor
   initialisations on empty ledgers: signing via
   `initialise_anchor`, budgets genesis-only, consumption
   empty-journal-only). Assert afterwards: three anchor files
   exist, each `seq == 0`, `verify_anchor(...) == ()` for all
   three journals. If the consumption or signing journal is
   non-empty at this point, bootstrap has been run against a
   used home — abort and delete the sandbox; there is no
   legitimate non-empty genesis here.
5. **Flip to production:** rewrite the env file with
   `AION_DEPLOYMENT_MODE=production` and the INIT keys *removed*
   (not set to `"1"`; `"0"`/absent both pass wiring, absence is
   cleaner). Smoke-invoke once: startup must succeed (this is
   the first moment production's fail-closed rules — operators,
   evidence, seed, all anchors present, no INIT — are all
   simultaneously satisfied).
6. Emit `run-config.json` (non-secret): all paths, signer ids,
   `expected_key_id`, ceremony public key (hex + `pub-…` id),
   anchor heads. This file is what the driver and the e2e test
   consume; it contains no key material.

**Rejected alternative:** provisioning anchors by calling
`trust.anchoring.initialise_anchor` directly from the script
instead of via verifier INIT invocations. Rejected: it would
create anchors the verifier itself never blessed at startup,
and the budgets anchor's file format is verifier-private
(`_write_budgets_anchor`, a different format from
`ledger-anchor/1`) — a script re-implementing it would drift.
The INIT-flag path is the verifier's own ceremony; use it.

### 2.3 The e2e flow

`tests/test_trust_production_e2e.py` (new) drives, in a temp dir:

1. Provision per §2.2 (script imported as a module; the script's
   `main()` is a thin wrapper so tests don't shell out).
2. Build the adopter **only** via `build_pin_adopter(env,
   expected_signer_id=…, expected_key_id=…,
   authorisation_public_key=…, signing_key_path=…,
   config=…)` — the first test in the suite where the adopter's
   client comes from `production_client`. (Cycle 22's harness
   note — research env + directly-built `VerifierClient` — is
   thereby retired for this path; the R12-pattern tests remain
   as unit coverage.)
3. Genesis: `snapshot_and_adopt()` on a fresh temp state →
   authorise (production verifier, step 5b not triggered) →
   consume (anchor advances *before* mirror, §WS2 asserts
   consumption anchor `seq == 1` immediately after) → adopt via
   `PinStore`. Assert outcome `reanchored`, reason
   `initial_anchor`.
4. One dense cycle through the WS1 hooked loop → `advanced`, no
   new consumption.
5. Negative probes against the same home (each must refuse and
   change nothing): (a) env with `AION_ANCHOR_INIT=1` →
   `production_client` raises `VerifierConfigError` before any
   spawn; (b) env with mode `research` → same; (c) delete the
   consumption anchor file → verifier startup
   `anchor_refused`/`verifier_misconfigured` surfaces through
   the client as a refusal on the next ceremony attempt, pin
   unmoved; (d) roll the consumption journal back one entry
   (restore the pre-consume byte copy the test kept) → startup
   anchor verification refuses (anchor ahead of journal).

### 2.4 What could block full production mode locally — precise list

1. **Separate OS user / wrapper routing: BLOCKED, out of scope.**
   Deployment (`deploy/verifier-identity/`) is not provisioned
   on this VM (no `aion-verifier` user, no root `runuser`), and
   `production_client(launch="wrapper")` is refused by design
   (backlog `verifier-wrapper-routing`). The e2e therefore runs
   the client's same-user spawn. Everything in WS2 proves
   production *mode* semantics (fail-closed config, mandatory
   anchors, INIT refusal) and proves **nothing** about user
   separation. Claim wording in §2.5 is scoped accordingly.
2. **Key placement vs forbidden roots:** `load_signing_key` /
   `load_ceremony_seed` refuse paths inside the repo and inside
   caller-named forbidden roots (registry dir; state/pin dirs
   for the snapshot key). Provisioning into a temp dir outside
   the repo satisfies this; provisioning under `~/workspace/ai`
   would refuse — the script asserts the sandbox root is not
   inside the repo checkout.
3. **Fixture-key refusal:** any seed/key equal to the refused
   test material refuses startup. The suite's existing fixtures
   use `bytes(range(32))`-family keys for the *snapshot* key
   (fine — that key never enters the verifier) but the WS2
   generators must be the real `generate_*_file` functions.
   Test asserts provisioning with a planted refused seed fails
   at step 5's smoke invocation, not silently.
4. **TTL:** envelope TTL hard cap 900 s end-to-end; the e2e is
   two verifier round-trips per ceremony on a loaded 1.5-CPU VM.
   No `now=` exists in the adopter flow (by design); a patho-
   logically slow test run could expire an envelope between
   authorise and consume → `PinAdoptionBurned`, recovery per
   WS3/WS4. The e2e marks this as the one acceptable flake
   source and retries the *whole genesis* once in a fresh
   sandbox rather than weakening any assertion.
5. **Registry digest coupling:** none for ceremony modes (they
   never open the registry) — stated so a future maintainer
   doesn't "fix" a non-dependency.

### 2.5 WS2 tests

New `tests/test_trust_production_e2e.py`: (1) provisioning
happy path incl. anchor seq-0 assertions; (2) provisioning
refuses a pre-existing home; (3) bootstrap against a dirtied
(non-empty) journal aborts; (4) production flip smoke passes,
research-mode steady state refused by `production_client`;
(5) genesis e2e §2.3 step 3 with anchor-seq assertions;
(6) dense advance step 4; (7a–d) the four negative probes.
Changed: `tests/test_verifier_deploy.py` allowlist counts
unchanged (no new env keys are introduced by this cycle — a
design goal; if the build finds itself wanting a 20th key, that
is a stop-and-re-rule event, not an edit).

### 2.6 WS2 claim wording

**May claim:** "A disposable production-mode verifier home can
be provisioned from scratch by one script (research-mode INIT
bootstrap, then production steady state), and the full ceremony
path — `production_client` → `build_pin_adopter` → authorise →
consume (consumption anchor advanced before the signing mirror)
→ `PinStore` adoption — runs end-to-end against it, including
refusal of INIT flags, mode downgrade, and consumption-anchor
deletion/rollback."
**May not claim:** production *deployment* (no separate OS user,
no wrapper routing — same-user spawn throughout); that the real
deployment is provisioned (it is not, on this VM); rollback
protection stronger than the anchored-append window every
anchored journal in this system carries.

---

## WS3 — Journal schema v2: recovery lineage, and the re-ruled recovery bound

This is the workstream seat-gemini's non-ratification turns on:
the journal must *say* what kind of consumption each entry is,
instead of `match_head_burn` inferring it by scanning for a
duplicate (old, new) pair. This section fixes the schema, the
versioning, the verifier-side lineage computation, and re-rules
the bound with lineage explicit.

### 3.1 The new fields (consumption journal)

`CeremonyConsumptionLedger` entries gain, in the v2 shape:

| Field | Type | Meaning |
|---|---|---|
| `consumption_kind` | `"primary"` \| `"recovery"` | What this consumption *is*. |
| `recovery_of` | hex64 authorisation_id, or `""` | For a recovery: the `authorisation_id` of the burn entry it recovers (the head entry at its authorise time). For a primary: `""` (the existing `old_payload_hash == ""` sentinel convention). |
| `recovery_depth` | int ≥ 0 | 0 for a primary; burn's depth + 1 for a recovery. |

`kind` stays `"consume"` for every entry — `kind` is the
HashChainJournal discriminator other code scopes on (the
signing-ledger mirror cross-check scopes on its own
`kind`/`format` pair and is untouched); overloading `kind` with
lineage would break that scoping for zero benefit. The signing
ledger's mirror entry shape is **unchanged**: lineage lives
only in the consumption journal, and §3.8's claim wording says
so (the mirror remains an anchored audit trace of the *fact* of
consumption, not of its lineage).

### 3.2 Versioning: dual key-sets + positional monotonicity

The obstacle is real: `HashChainJournal._load` enforces
`set(entry) == _ENTRY_KEYS | EXTRA_KEYS` exactly, and live v1
journals exist (in tests, in the WS1/WS2 sandboxes, and in any
provisioned home). Three candidate mechanisms:

- **(a) Widen `EXTRA_KEYS` to the union and make the three new
  fields optional.** Rejected: "optional security fields" is
  how lineage becomes caller-assertable by omission — a v2-era
  entry *without* lineage would be indistinguishable from a v1
  entry, and `match_head_burn` would be back to inference for
  exactly the entries that matter.
- **(b) Journal-level version marker** (top-level
  `{"v": "ceremony-consumptions/2", "entries": [...]}`).
  Rejected: the base loader's document-shape check
  (`set(data) != {"entries"}`) is shared by *every* journal
  (ship, signing, issuance, budgets-adjacent code); touching it
  widens the blast radius to journals this workstream doesn't
  own. Worse, the marker is a second source of truth that can
  disagree with the entries it labels (marker says 2, an entry
  lacks lineage → which wins?). A marker that must be
  cross-checked against every entry is not a versioning
  mechanism, it's a second validation problem.
- **(c) CHOSEN — per-entry dual key-sets with a positional
  rule.** The entry's own key set *is* its version, which is
  the only version statement that cannot disagree with the
  entry. Mechanism:
  1. `HashChainJournal` gains a class attribute
     `EXTRA_KEY_SETS: tuple[frozenset, ...] | None = None`.
     When `None` (every existing subclass), `_load` behaves
     exactly as today (`EXTRA_KEYS` single set). When set,
     `_load` accepts an entry iff its key set equals
     `_ENTRY_KEYS | s` for some `s in EXTRA_KEY_SETS`, and then
     calls a new no-op-by-default hook
     `self._validate_entry_progression(entries_so_far, entry)`
     which subclasses may override to refuse.
     This is a ~10-line change to the base loader, additive for
     all other journals, and covered by a regression test that
     every other journal class still refuses a foreign key set.
  2. `CeremonyConsumptionLedger.EXTRA_KEY_SETS = (V1, V2)` where
     V1 is today's `EXTRA_KEYS` and V2 is V1 ∪
     {`consumption_kind`, `recovery_of`, `recovery_depth`}.
     `EXTRA_KEYS` itself stays = V1 (any code reading it
     directly — e.g. `_append`'s callers — keeps working; see
     §3.3 for the append change).
  3. **Positional monotonicity** (the progression hook): once a
     v2-shaped entry appears, no later entry may be v1-shaped.
     A journal is therefore: a (possibly empty) v1 prefix, then
     a v2 suffix. There is no interleaving and no downgrade.
     Rationale: without this rule, "v1-shaped" becomes a
     lineage-laundering shape available at any height (option
     (a)'s defect in positional form).
  4. **Value validation in `_load`** for v2 entries (in the same
     hook): `consumption_kind ∈ {"primary","recovery"}`;
     `recovery_depth` is an int (not bool) ≥ 0;
     `consumption_kind == "primary"` ⟺ `recovery_of == ""` and
     `recovery_depth == 0`; `recovery` ⟹ `recovery_of` is hex64
     and `recovery_depth ≥ 1`. An entry failing these is
     `CorruptLedgerError` — the journal refuses to load, which
     refuses verifier startup for ceremony modes, fail-closed.
     (Lineage *chain* consistency — `recovery_of` actually
     naming the preceding burn — is a consume-time check,
     §3.5, not a load-time check: load validates shape, the
     predicate validates history. Conflating them would make
     `_load` depend on envelope semantics it doesn't have.)
  5. **Hash integrity is untouched for the v1 prefix:** v1
     entries keep their original bytes and hashes (the fields
     are *not* backfilled — backfilling would rewrite every
     `entry_hash` and break the anchored prefix the consumption
     anchor already pins). v2 entries hash over their full core
     including lineage, so a tampered `recovery_depth` breaks
     the chain exactly like any other field tamper.

  **Backward compatibility, stated as a testable sentence:** a
  v1 journal file written by cycle-22 code loads under cycle-23
  code, verifies against its existing consumption anchor
  unchanged, and its entries answer lineage queries as
  *unknown-kind, depth 0* (§3.5's v1 rule) — never as a guessed
  `"primary"`.

### 3.3 The append path

`CeremonyConsumptionLedger._append` is already overridden in
the subclass (chain-head plumbing). Cycle 23 changes
`append_consumption` only:

- Signature: `append_consumption(envelope, *, recorded_at,
  recovery_of=None)`. `recovery_of` is a **verifier-internal**
  parameter: it is supplied only by `trust/verifier_main.py`'s
  consume mode, from the issuance record (§3.4). It is never
  taken from the request body (the consume body is exactly
  `{"signed_authorisation"}` — unchanged) and never from the
  envelope (the envelope format is unchanged — no signing-module
  change, no envelope migration).
- Lineage derivation, inside the existing bounded reload-retry
  loop, on every attempt, from freshly reloaded entries:
  - `envelope.reason != "burned_unadopted"` → the append is a
    primary: `consumption_kind="primary"`, `recovery_of=""`,
    `recovery_depth=0`. If the caller passed a non-`None`
    `recovery_of` for a non-recovery envelope → `LedgerError`
    (inconsistent internal call; fail closed rather than record
    a lie).
  - `envelope.reason == "burned_unadopted"` → `recovery_of`
    must be non-`None` (a direct library caller who cannot
    supply the issuance-bound value gets a refusal, not a
    primary-labelled recovery — this is the "never
    caller-asserted" requirement enforced at the only library
    surface); the current head entry must satisfy
    `head.authorisation_id == recovery_of` (else
    `AlreadyConsumedError` — the burn this recovery was
    authorised against is no longer the head; see the race
    analysis in §3.5); depth = `head_depth + 1` where
    `head_depth` is the head's `recovery_depth` if the head is
    v2-shaped, else 0 (v1 head rule, §3.5); if depth > cap
    (§3.6) → `AlreadyConsumedError` (same outward class as every
    other predicate failure at consume; the oracle discipline of
    cycle 22 — one code, no sub-case detail — is preserved).
  - Every append from cycle-23 code is written **v2-shaped**,
    including primaries. The v1 prefix therefore ends at the
    first cycle-23 consumption in any journal, permanently.

### 3.4 The issuance-side binding (the one scope addition — needs coordinator ratification)

Lineage computed *only* at consume time has a race hole that
cycle 22's fix round already pinned as semantics: two recovery
authorisations may issue against the same burn; the first
consumption lands; the second must refuse
`AlreadyConsumedError`. With consume-time-only lineage, the
second envelope — presented after the first recovery landed —
would find the first *recovery* at the head, compute depth+1
against it, and land as a recovery-of-the-recovery it never was
authorised to be. Pair-scanning prevented this in v1 by
refusing any head with a duplicate pair behind it; removing
the scan without replacing that binding reopens the hole.

**Chosen fix:** bind the recovery target at *issuance*, in the
verifier's own journal. `CeremonyAuthorisationLedger` gains the
same dual-set versioning (§3.2 mechanism, reused verbatim): v2
issuance entries carry one extra field,
`recovery_of_authorisation_id` (hex64, or `""` for
non-recovery issuances). It is written by
`append_authorisation(signed, *, recorded_at,
recovery_of_authorisation_id="")` — but the *value* is computed
in `_mode_ceremony_authorise` at step 5b, from the same
`match_head_burn` result that already gates issuance: for
`burned_unadopted`, `recovery_of_authorisation_id =
burn["authorisation_id"]`; for every other reason, `""`, and
passing a non-empty value for a non-recovery reason is a
`LedgerError` at the ledger (internal inconsistency, fail
closed). The consume mode then reads the issuance entry it
already loads at step (6) (issuance presence + field match) and
passes `issued["recovery_of_authorisation_id"]` (or `""`→`None`
handling for v1 issuance entries, §3.5) into
`append_consumption(..., recovery_of=...)`.

Why this is verifier-side and not caller-asserted: both values
are produced inside the verifier process, from the verifier's
own journals, at the two commit points. The caller (adopter /
`reanchor_pin`) cannot influence either — it never sees the
field names. This is the same authority pattern as the
consumption head itself (DECISION-CONSUMPTION-HEAD).

**Rejected alternatives:** (i) *Bind `recovery_of` into the
signed envelope* — rejected: changes
`signing/ceremony_authorisation.py`'s payload projection, i.e.
a wire-format change to an externally-reviewed envelope, to
carry data only the verifier needs; the issuance journal is
the verifier's own notebook and is the right place. (ii)
*Timestamp ordering* (recovery envelope must be issued after
its burn's consumption) — rejected: cross-journal timestamp
comparison is exactly the fragile ordering evidence
`trust/shiptx.py`'s recovery rules refuse to trust. (iii)
*Keep the pair-scan as a second check alongside lineage* —
rejected as the primary mechanism (it is the blunt patch
seat-gemini refused to ratify), retained only as the v1-head
fallback (§3.5) where no lineage exists to consult.

**Scope honesty:** the task text scopes WS3 to the consumption
journal. This issuance-journal field is the minimum addition
that makes consumption lineage race-safe; it reuses the §3.2
mechanism rather than inventing a second one. If the war room
rejects the addition, the fallback design is: keep the
pair-scan *in addition* for v2 heads (lineage recorded and
visible, bound still one-shot-by-scan) — strictly weaker, and
§3.6's re-ruled bound then collapses back to one-shot. The
coordinator should treat "WS3 without §3.4" and "§3.6 depth
cap 2" as mutually exclusive.

### 3.5 `match_head_burn` and `check_head` under v2

`match_head_burn(entries, *, candidate, old_pin)` keeps its
signature and its exact-equality core (candidate == head
target, old pin == head old pin, with the no-pin shape rule).
What changes is the admissibility tail:

- **Head is v2-shaped:** the pair-scan is **not consulted**.
  Admissibility is: head's `consumption_kind` is `"primary"`
  (depth 0) → admissible (this is recovery depth 1); head is
  `"recovery"` with `recovery_depth < CAP` → admissible (depth
  head_depth+1 ≤ CAP); head is `"recovery"` with
  `recovery_depth == CAP` → `None` (cap reached; authorise
  refuses `ceremony_recovery_unproven`, consume refuses via
  `check_head` below). The returned entry is the head entry
  itself, now carrying its lineage, so step 5b records
  `recovery_of` from `head["authorisation_id"]` directly.
- **Head is v1-shaped (legacy journal, or a journal whose head
  predates cycle 23):** lineage is *unknown*, so the legacy
  rule applies unchanged — the pair-scan: if any earlier entry
  carries the same (old, new) pair, return `None`. This is
  deliberately conservative: a v1 head might itself be a
  recovery (cycle-22 recoveries are v1 entries), and the scan
  is the only evidence available. The first recovery granted
  against a v1 head is written v2 with depth 1 (v1 head counts
  as depth 0 — the only sound default, since the scan has
  already established the head is the *first* consumption of
  that pair). From that entry onward the journal is in the v2
  regime for that chain.
- **Mixed-journal subtlety, stated:** the v1 fallback keys off
  the *head entry's shape only*. A v2 entry deeper in the
  journal (from a different movement) does not change the
  rule for a v1 head — positional monotonicity (§3.2) already
  guarantees a v1 head implies an all-v1 journal, so this case
  cannot arise in a validly-loaded journal. The progression
  hook is what makes the head-shape test sufficient.

`check_head(entries, signed)` changes in exactly one place: the
`recovery` boolean. Today it is
`signed.reason == "burned_unadopted" and match_head_burn(...) is not None`.
Under v2 that expression *stays* — the predicate's internals
changed, the call doesn't — plus one added guard: when
`recovery` is true, `check_head` additionally requires that the
head entry's depth is < CAP (already inside `match_head_burn`'s
`None` result, so this is defence-in-depth documentation, not a
second rule) — no, precisely: **no added guard**; duplicating
the cap in two places invites drift. The one genuine addition
to `check_head` is a comment-level contract: for a
`burned_unadopted` envelope whose target sits *at* the head but
whose `match_head_burn` is `None` (cap reached, or v1
pair-scan refusal), the existing fall-through raises
`AlreadyConsumedError` — the desired outward behaviour, now
also the cap's outward behaviour, with no new error code and no
new oracle surface.

`append_consumption`'s §3.3 head-binding check
(`head.authorisation_id == recovery_of`) is the consume-side
enforcement of §3.4; `check_head` remains the pure predicate
over (entries, envelope) and does not need `recovery_of` —
authorisation-binding is a journal-vs-journal fact checked at
the commit point and at authorise 5b, not a head-rule. Stated
explicitly because a reviewer will ask why `check_head` doesn't
check it: `check_head`'s inputs don't include the issuance
journal, by design (cycle-21 R3 shape), and the commit loop
re-runs the binding check against fresh entries on every retry
attempt, which is where races are actually decided.

### 3.6 The re-ruled bound: bounded chain, depth cap 2

Options with lineage explicit:

- **(i) Keep one-shot, now schema-grounded** (a recovery entry's
  kind is visible, so a second recovery refuses because head
  kind == `"recovery"`). *Liveness:* a recovery that itself
  burns unadopted is terminal for the movement — the exact
  brick seat-gemini named. The movement is superseded by the
  next snapshot sequence (Addendum 2's accepted consequence),
  so the *system* stays live, but the *target* is dead and the
  operator's remedy is "wait for the next cycle and re-pin
  then" — which, under WS1's hooked loop, means the pin lags a
  full extra cycle after a double fault (consume OK → adopt
  crash → recovery consume OK → adopt crash). Double adopt
  crashes are not exotic: WS4's scenario list contains two
  distinct adopt-boundary crash points (pending-journal write,
  PinStore replace) plus plain process death. *Single-use:*
  strongest form — at most 2 consumptions per movement ever.
- **(ii) CHOSEN — bounded chain, depth cap 2.** A movement may
  be consumed at most 3 times total: the primary (depth 0) and
  up to two recoveries (depths 1, 2), each recovery authorised
  against the *immediately preceding* burn at the head, each
  with a new ceremony_id, new evidence, new authorisation_id,
  and the §3.4 issuance binding. *Why 2:* depth 1 covers the
  single adopt-boundary fault (the documented crash contract
  since cycle 21); depth 2 covers the double fault — recovery
  itself interrupted at the same boundary — which is the
  deepest failure sequence that is still *one incident* (one
  operator, one outage, one movement). A third interruption is
  no longer bad luck on one incident; it is evidence the
  adoption side is broken, and the correct response is to stop
  consuming verifier budget on this movement, fix adoption, and
  let the next snapshot sequence carry the pin forward — the
  movement-level brick remains as the backstop, exactly as
  under one-shot, but it now takes three independent adopt
  failures to reach it instead of two. Each recovery is a full
  operator ceremony (human-paced, evidence-bearing), so a cap
  of 2 is not a rate an automated attacker can spin: minting a
  recovery requires an allowlisted operator presentation and a
  verifier authorisation against the live head. *Single-use:*
  per-authorisation single-use is untouched (every
  authorisation_id consumes at most once, race shows exactly
  one success — §3.7 test). Target-level single-use is replaced
  by *target-level linear lineage*: multiple consumptions of
  one target exist only as one chain, each link bound to its
  predecessor's authorisation_id, visible in the schema,
  capped at 3 links. No fork is possible: a recovery must match
  the *head* entry exactly (candidate, old pin, and §3.4's
  authorisation binding), so two chains cannot branch from one
  burn — the race loser's binding names a non-head burn and
  refuses. No backwards movement: `check_head`'s non-recovery
  rules are untouched, and a recovery's candidate/old pin must
  equal the head's, so a recovery can never move the head
  anywhere but onto its own already-consumed target.
- **(iii) Unbounded chain with lineage visible.** Rejected:
  visibility is not a bound. An unbounded chain waives
  target-level single-use indefinitely (rev-r6's F1 defect,
  now *documented* instead of hidden — seat-gemini's objection
  was to the waiver, not only to its invisibility), and each
  link spends an operator ceremony, so the liveness gain over
  cap 2 is confined to scenarios that indicate a broken adopter.

**Supersession bookkeeping:** this ruling supersedes Addendum
2's one-shot rule *for v2-headed chains*. Addendum 2 remains
the correct description of v1 behaviour and of the v1-head
fallback. A new **Addendum 3** to DECISION-CONSUMPTION-HEAD.md
records the re-rule, the cap, and the §3.4 binding, in the same
style as Addenda 1–2 (dated, supersession stated, earlier text
left as history). The cycle-22 test that pins one-shot
semantics (`test_recovery_is_one_shot_second_recovery_refused`)
is re-pinned, not deleted (§3.7).

### 3.7 WS3 tests

Changed file `tests/test_trust_ceremony_consumption.py`:
`test_recovery_is_one_shot_second_recovery_refused` →
`test_recovery_chain_second_recovery_succeeds_third_refused_at_cap`:
original burn → recovery₁ authorises+consumes (entry asserts
`kind=recovery, depth=1, recovery_of=<original auth id>`) →
recovery₂ authorises+consumes (depth 2, `recovery_of` =
recovery₁'s auth id) → recovery₃ authorise refuses
`ceremony_recovery_unproven`. The existing race test
(`test_recovery_envelope_consumed_twice_refused` and the
concurrency tests) must pass **unmodified in outcome**: two
race authorisations against one burn → exactly one consumption
succeeds — now enforced by the §3.4 binding, asserted by
checking the loser's refusal is `ceremony_already_consumed`
and the journal contains exactly one recovery entry whose
`recovery_of` names the original burn.

New file `tests/test_trust_consumption_schema_v2.py`:

1. `test_v1_journal_loads_and_anchor_verifies_unchanged` —
   cycle-22-shaped fixture journal (built with v1 key set)
   loads; `verify_anchor` against a pre-computed anchor == ().
2. `test_first_v2_append_after_v1_prefix` — mixed journal
   loads; v1 hashes unchanged byte-for-byte; new entry v2.
3. `test_v1_entry_after_v2_entry_refused_at_load` — positional
   monotonicity (hand-built file, surgery).
4. `test_v2_value_validation` — each of: bad kind, depth bool,
   primary with non-empty `recovery_of`, recovery with depth 0
   → `CorruptLedgerError` at load.
5. `test_tampered_lineage_breaks_chain` — flip `recovery_depth`
   in the file → load refuses (hash mismatch).
6. `test_primary_append_writes_v2_shape_with_zero_lineage`.
7. `test_recovery_lineage_computed_not_caller_asserted` —
   `append_consumption` with a spurious `recovery_of` on a
   primary envelope → `LedgerError`; burned envelope with
   `recovery_of=None` → refusal; wrong `recovery_of` (names a
   non-head burn) → `AlreadyConsumedError`.
8. `test_issuance_journal_v2_binding` — authorise a recovery;
   issuance entry carries the burn's authorisation_id;
   non-recovery issuance carries `""`; v1 issuance entries load.
9. `test_race_two_recoveries_one_burn_exactly_one_consumption`
   (the §3.5/§3.4 race, multiprocess-barrier style per
   `test_trust_multiprocess_race.py` patterns).
10. `test_v1_head_pair_scan_fallback_still_one_shot` — all-v1
    journal with a duplicate pair at head → `match_head_burn`
    is `None`; all-v1 journal, clean head → recovery granted,
    written at depth 1 v2.
11. `test_depth_cap_at_consume_not_only_authorise` — authorise
    recovery₂, then land a competing recovery₂ (different
    ceremony) first; the pre-authorised envelope's consume now
    faces a depth-2 head → refuses (binding + cap both bite;
    asserts no depth-3 entry exists).
12. `test_other_journals_unaffected_by_dual_set_loader` —
    ship/signing/issuance-v1 key-set strictness regression:
    a foreign key in a ship entry still refuses at load.
13. `test_mirror_shape_unchanged` — signing-ledger mirror entry
    for a recovery consumption has the cycle-21/22 key set
    exactly (no lineage leakage into the mirror).

Docstring/wording updates (part of the build, per cycle-22's
wording sweep lesson): `CeremonyConsumptionLedger` docstring
(R10 paragraph gains the v2 lineage + cap statement),
`match_head_burn` docstring (pair-scan demoted to v1 fallback),
`pin_ceremony.py`'s crash-consistency paragraph (one-shot →
bounded chain, cap 2), `verifier_main.py` consume-mode
docstring (same), DECISION-CONSUMPTION-HEAD.md Addendum 3.

### 3.8 WS3 failure modes + claim wording

| Failure | Behaviour |
|---|---|
| Journal file from the future (v3 shape) | Load refuses (`CorruptLedgerError`) — unknown key set is corruption, not a version to negotiate |
| Lineage chain broken mid-journal (recovery_of names nothing) | Load succeeds (shape only); the *next* recovery against that head computes from the head entry alone; a dangling deeper `recovery_of` is audit-visible but not load-fatal — stated, because making load chase the whole chain would brick journals over historical entries no future decision depends on |
| Cap reached while pin still unadopted | Movement terminal; pin advances at next snapshot sequence via primary ceremony/advance — the §3.6 backstop, surfaced by `verify_live_run.py` as `movement_terminal` (§6) |
| §3.4 rejected by war room | Fallback in §3.4 applies; §3.6 cap collapses to one-shot; this must be re-ruled in DESIGN-FINAL, not silently merged |

**May claim:** "Consumption entries now record their kind and
recovery lineage (`consumption_kind`, `recovery_of`,
`recovery_depth`), computed by the verifier from its own
journals at the two commit points — never supplied by the
caller or carried in the envelope. Recovery is a bounded linear
chain: at most two recoveries (depth ≤ 2) per burned movement,
each bound at issuance to the exact burn it recovers; the
original burn stays burned, per-authorisation single-use and
the exactly-one-success race outcome are preserved, and v1
journals load and verify unchanged, with the legacy pair-scan
rule applying only while the head entry is v1-shaped."
**May not claim:** that lineage is anchored in the signing
ledger (the mirror carries no lineage); that recovery is
unbounded or that a capped-out movement can be recovered (it
cannot — it is superseded by the next sequence); that v1
entries have known kind (they are unknown-kind, conservatively
handled); target-level *absolute* single-use (replaced, openly,
by the bounded lineage above).

---

## WS4 — Crash/restart coverage across the multi-artifact boundary

### 4.1 Method taxonomy (choose per scenario, don't improvise)

- **SIGKILL-at-barrier (true process death):** a child-process
  driver (`tests/fixtures/pin_adoption_child.py`, new) runs the
  adopter against a test home; fault points are armed by env
  vars naming a barrier file: the child touches the barrier and
  sleeps; the parent waits for the barrier, sends SIGKILL,
  then restarts with a fresh child / in-process adopter on the
  same dirs. This is the only method that proves fsync/replace
  discipline rather than exception handling. Used for scenarios
  1, 2, 6.
- **State surgery (deterministic corruption/loss):** the test
  edits/deletes/truncates artefacts between two adopter
  instances. Used for scenarios 3, 4, and the discarded-pair
  half of 5. Surgery is honest here because the *restarted*
  code path — verified load, tolerant journal read — is what's
  under test, not the corruption's origin.
- **In-process fault injection (existing pattern):** PinStore's
  cycle-22 tests already monkeypatch fsync/replace (test_10a–d);
  scenario 7 (concurrency) uses the multiprocess barrier pattern
  from `test_trust_multiprocess_race.py`. No new production-code
  fault seams are introduced — **a test-only seam in production
  code is rejected** (it would ship an attack surface to prove a
  crash property the child-process method proves directly).

New file for all of WS4: `tests/test_trust_pin_adoption_crashes.py`
(+ the child fixture). Every scenario asserts the same global
invariants on restart: pin store loads verified or refuses
loudly (never silently repairs); consumption count is exactly
as specified; no `lost_pin` reason appears anywhere in the
pending journal or store history for an unmoved pin.

### 4.2 The seven scenarios

**S1 — Termination after consumption, before adoption.**
Injection: SIGKILL-at-barrier; barrier armed inside the child's
`PinStore.adopt` wrapper (child monkeypatches its own adopter's
store object — test-process patching, production code untouched)
*after* `reanchor_pin` has returned (consumption committed at
the verifier, journal phase `consumed` not yet appended — the
barrier sits between consume-return and adopt, the widest real
window). Restart state: consumption journal has the burn; pin
unmoved; pending journal's last phase for the ceremony is
`authorised` (the `consumed` line is post-`reanchor` in current
code — the test pins whichever phase the code actually wrote,
and the recovery must not depend on it). **Expected:** the
returned pair died with the process, so recovery is the
discarded-pair path: next `snapshot_and_adopt()` selects
`burned_unadopted` from the journal's unadopted `authorised`
line, re-presents the retained candidate identically, consumes
a depth-1 recovery (WS3), adopts. Final: pin at target,
consumptions == 2, store history has exactly the recovery
record.

**S2 — Termination during pending-journal persistence.**
Injection: SIGKILL-at-barrier armed in the child's
`_append_journal` *after* a partial line (half the JSON bytes,
no newline) is written and fsynced for the `authorised` phase.
Restart: `_read_journal` skips the unparseable tail line
(existing tolerant-read behaviour — this test is what promotes
that behaviour from implementation detail to pinned contract).
**Expected:** the burn is *not* detectable from the journal
(the `authorised` line is the lost one) — see §4.3 for the
required behaviour change this scenario forces; with §4.3
landed: the next attempt runs a primary-reason ceremony,
its consume is refused `ceremony_already_consumed` at the
verifier (the S1-style burn exists), the adopter records a
`suspected_burn` line from its own attempt facts, and the
*following* attempt selects `burned_unadopted` and recovers at
depth 1. The test asserts the full three-attempt arc and that
attempt 2's refusal burns nothing new (consumption count
unchanged by attempt 2).

**S3 — Pending-journal corruption (surgery).** Three sub-cases:
(a) garbage bytes appended mid-file; (b) a middle line replaced
with valid JSON of the wrong shape; (c) whole file deleted.
**Expected (all):** no exception escapes `_read_journal`;
journal treated as "no burns detected" for the corrupted
entries only (a); recovery selection falls back to §4.3's
`suspected_burn` mechanism if a consume refusal reveals a burn;
pin safety unaffected in all sub-cases (journal is
non-authoritative — the test asserts a corrupted journal can
never cause a *wrong* adoption, only a delayed one: with a
clean store + clean state, `snapshot_and_adopt()` either
advances normally or refuses, never ceremonies a false
recovery against a non-head target — the verifier's
`match_head_burn` is the backstop and the test proves it by
planting a *forged* unadopted-burn line naming a real past
target: authorise refuses `ceremony_recovery_unproven` because
the forged line's target is not the consumption head).

**S4 — Side-file (`snapshot-candidate.json`) loss (surgery).**
Setup: genesis + one dense advance (side file retained), then
delete the side file; state unchanged. **Expected, pinned:**
next `snapshot_and_adopt()` on unchanged state **refuses**
(`PinAdoptionRefused`, integrity class) — a fresh signing of
the same state bytes has a different `payload_hash`
(`signed_at` is in the payload), so it cannot reproduce the
pin, verification reports pin mismatch, and the adopter
correctly treats that as integrity failure, *not* as a ceremony
trigger and *not* as `already_current`. Consumptions unchanged,
pin unmoved. Liveness note, stated in the test docstring: the
pin unfreezes at the next state change (next cycle's dense
advance signs fresh and chains from the pin normally — the
test runs one bare cycle and asserts the advance then
succeeds). Corrupted (not just missing) side file: identical
expectations (`_read_retained_candidate` returns `None` on any
parse failure — pinned here).

**S5 — Restart with returned pair available vs discarded.**
Available: in-process `PinAdoptionBurned` (adopt made to fail
via a read-only pin dir, cycle-22 test_05's method), then a
**new `PinAdopter` instance** over the same dirs (fresh store
object, fresh client) calls `adopt_returned(pin, record,
expected_old_pin=…)` → succeeds, zero new consumptions, journal
gains `adopted`. Discarded: same burn, pair dropped; fresh
instance's `snapshot_and_adopt()` → depth-1 `burned_unadopted`
ceremony (cycle-22 test_05b's semantics, re-asserted at
instance-restart level and now asserting the v2 lineage fields
on the recovery entry). Both halves assert the store ends in
the identical state (same pin, same single history record
target — note the *records differ*: available-path keeps the
original record, discarded-path holds the recovery record;
the test asserts pin equality and history length 1 in both,
and does not pretend the histories are identical).

**S6 — Recovery-after-recovery burns (WS3 cap in action).**
Injection: SIGKILL-at-barrier at the adopt step, three times
in sequence: primary ceremony consumed → kill before adopt;
recovery₁ consumed (depth 1) → kill before adopt; recovery₂
consumed (depth 2) → this time adopt succeeds. **Expected:**
pin lands at the target; consumption journal shows exactly the
3-link chain with correct `recovery_of` linkage; a fourth
movement attempt is unnecessary (pin adopted) — and a separate
sub-case drives the cap: after recovery₂ is *also* killed
before adopt, the next authorise refuses
`ceremony_recovery_unproven` (cap), pin stays unmoved, and the
test asserts the documented backstop: one bare loop cycle
(new sequence) + `snapshot_and_adopt()` pins the *new* target
by a primary path, leaving the capped movement behind
permanently (its target never adopted, never consumable again).

**S7 — Concurrent adopter instances on one pin store.**
Injection: two child processes, barrier-synchronised to enter
`snapshot_and_adopt()` simultaneously on the same state/pin
dirs (genesis race and advance race as two sub-cases).
**Expected (genesis):** exactly one consumption, exactly one
store creation; the loser surfaces `PinAdoptionBurned` (its
consume refused already-consumed / its adopt CAS-refused) or
`PinAdoptionRefused` — the test accepts either class but
asserts the *state*: one pin, one history record, consumption
count 1, store loads verified, and the loser's exception is
not a raw `PinStoreBusy` escaping `snapshot_and_adopt`
(if `PinStoreBusy` can escape today, wrapping it as
`PinAdoptionRefused` is a WS4 build fix, listed in §8).
**Expected (advance race):** both attempt `advance_pin` of the
same successor; one adopts, the other gets the CAS
`PinMovedError` path → `PinAdoptionRefused`; pin == successor;
no consumption in either process.

### 4.3 The one behaviour change WS4 forces: `suspected_burn`

S2/S3 expose a real dead-end in cycle-22 code: recovery-reason
selection depends entirely on the pending journal's
`authorised` line surviving. If that line is lost, the adopter
retries with the primary reason forever, and every attempt's
consume refuses already-consumed without the adopter ever
learning *why* in a form it can act on. **Design:** when
`snapshot_and_adopt`'s ceremony attempt fails inside
`reanchor_pin` with the verifier's already-consumed refusal
*for its own candidate + old pin* (the client exception for
`ceremony_already_consumed` — the adopter must distinguish this
code from other consume failures; if the client does not expose
the code distinctly today, exposing it is part of this change),
the adopter appends a journal line
`{phase: "suspected_burn", ceremony_id, candidate_seq,
candidate_hash, old_cycle_seq, old_payload_hash}` built from
its *own* attempt facts, and `_find_unadopted_burn` treats a
`suspected_burn` line exactly like an `authorised` line for
reason selection. Soundness: the line is still only a
*detection aid* — the verifier's `match_head_burn` + §3.4
binding decide whether a recovery is real; a false
`suspected_burn` (e.g. the refusal was for a different target
consumed by someone else) yields an authorise refusal
(`ceremony_recovery_unproven`), after which the adopter must
not loop: one `suspected_burn`-driven recovery attempt per
suspected line, and if it refuses, the line is marked
`suspected_refuted` by appending a superseding line, returning
the adopter to primary-reason behaviour and surfacing a
`PinAdoptionRefused` to the operator. This is a bounded
two-step, not a retry loop. File: `trust/pin_adoption.py`
only; tests in §4.2 S2/S3 plus a unit test that a
`suspected_burn` line alone (no burn at the verifier) cannot
mint a recovery.

### 4.4 WS4 claim wording

**May claim:** "Crash/restart behaviour across the consumption
journal, pending journal, candidate side file, and pin store is
test-pinned for: death after consumption before adoption, death
mid-pending-journal-write, pending-journal corruption and loss,
side-file loss/corruption, returned-pair adoption after restart,
recovery chains up to the depth cap (and the cap's backstop),
and concurrent adopters on one store — each with its recovery
path or its pinned refusal."
**May not claim:** crash *atomicity* across the four artefacts
(there is none — there are four separate fsync domains and the
design's claim is recoverability, not atomicity); that a lost
pending journal is harmless in one step (recovery via
`suspected_burn` takes one extra refused attempt, by design);
that side-file loss is recoverable on unchanged state (it is a
pinned refusal until the state moves).

---

## WS5 — Ledger-head-anchoring completion

Backlog text: "Anchor ship/signing ledger heads outside
writable storage so ledger rollback or deletion is detectable
without a caller-supplied pin." Current state (verified by
reading): `trust/anchoring.py` kinds include `ship` and
`ship-tx`; `record_ship` **requires** a caller-supplied
`expected_ledger_head` and optionally verifies+updates a ship
anchor when `anchor_path` is passed; `recover_ship_tx` takes
both anchor paths optionally; `record_ship` never updates the
ship-tx anchor; and **no anchor files exist** for the repo's own
`state/ship-ledger/` (ship ledger at seq 4, head
`6911dff4…870` — the cycle-13 finalise; ship-tx journal at
6 entries).

### 5.1 (a) Anchor-derived head pinning on the sanctioned path

Change list — `trust/shipcheck.py` only (plus tests):

1. New helper:
   ```python
   def anchored_expected_head(ledger, anchor_path, *, kind="ship") -> str
   ```
   Runs `verify_anchor(ledger, anchor_path, kind=kind)`; any
   reasons → `ShipRefused` carrying them (same treatment as the
   existing pre-burn anchor verification). On success returns
   `anchoring.load_anchor(anchor_path)["head"]`. Note the
   semantics: the anchor pins a *prefix*; the derived head is
   the anchor's head, which may be *behind* the ledger's current
   head (staleness is not tampering). Therefore —
2. `record_ship` signature/semantics change: today it requires
   `expected_ledger_head` non-None and `check_ship` compares
   `ledger.head() != expected_ledger_head` (exact equality with
   the *current* head). Deriving the expected head from the
   anchor and feeding it into that exact-equality check would
   refuse every legitimate ship after any post-anchor ledger
   growth. The correct composition, and the one this design
   specifies: when `anchor_path` is provided, the anchor check
   **replaces** the caller-head requirement —
   - `expected_ledger_head is None` + `anchor_path` given →
     proceed: `verify_anchor` (prefix property: the anchored
     prefix must be *in* the current chain — rollback to a
     different history, truncation below the anchor, or
     deletion all fail this) is the rollback check; the exact
     current head is then *read from the ledger under the
     check* and passed to `check_ship` internally, so
     `check_ship`'s audit binding still pins the ship to the
     head that was actually audited.
   - Both given → **cross-check**: `verify_anchor` must pass
     *and* the caller-supplied head must equal the ledger's
     current head *and* the anchor's head must be a prefix of
     that chain (implied by verify). A caller head that
     disagrees with the current head refuses as today; a caller
     head equal to the current head but with a *failing* anchor
     refuses on the anchor. Neither input can override the
     other — that is the point of deriving from the anchor.
   - `expected_ledger_head` given, no `anchor_path` → legacy
     behaviour, retained for the existing test suite and for
     `check_ship`'s pure-check callers, but `record_ship`'s
     docstring now states this form is **not** the completed
     sanctioned path (it is exactly the caller-supplied-pin
     form the backlog item exists to retire).
   - Neither → the existing refusal stands.
3. **Ship-tx anchor update:** when `anchor_path` is provided,
   `record_ship` now also requires/accepts `tx_anchor_path`
   (new keyword, default `None` for compatibility) and, after
   the `COMMITTED` transition, advances the ship-tx anchor via
   `update_anchor(tx_journal, tx_anchor_path, kind="ship-tx")`
   alongside the existing ship-anchor update; failure of either
   update after commit raises the same "recorded and finalised
   but anchor update failed" `ShipRefused` class as today.
   Rationale: today the tx journal — the artefact
   `recover_ship_tx` reasons from — grows unanchored on the
   sanctioned path even when the ship ledger is anchored; that
   is half of the backlog item left undone. `recover_ship_tx`
   already accepts `tx_anchor_path`; the write side was missing.
4. `check_ship` itself is **unchanged** (it is a pure check; the
   derivation is a `record_ship`-layer concern). This keeps the
   large existing `test_trust_shipcheck.py` surface stable:
   only `record_ship`-level tests change.

**Rejected alternative:** *refuse a caller-supplied head
outright (delete the parameter).* Rejected: it breaks every
existing caller and test that pins a head for a *pure check*,
and cross-checking (both supplied → both must agree) is
strictly stronger than either alone for callers that have
both. The backlog's defect is that the caller pin was the
*only* option on the sanctioned path, not that it exists.

### 5.2 (b) Initialise + verify anchors for the real `state/ship-ledger/`

- **Location:** `state/anchors/ship.anchor.json` and
  `state/anchors/ship-tx.anchor.json`. `anchoring.py` refuses
  an anchor inside its journal's own directory; `state/anchors/`
  is outside `state/ship-ledger/` ✓. Honest qualifier (§5.5):
  on this VM `state/anchors/` is the same disk, same OS user,
  same rollback domain as `state/` itself — this placement
  satisfies the *code's* outside-the-journal-directory rule and
  makes rollback/deletion *detectable by any reader who trusts
  the anchor file's provenance*, but it is not the
  separate-storage form the backlog text aspires to. The build
  record must say so, and the anchor heads + seqs are therefore
  **also recorded in `internal/BUILD-CYCLE-23.md`** — the git
  history is, on this VM, the most rollback-resistant second
  copy available, and `verify_live_run.py` gains a
  `--check-ship-anchors` mode that compares the anchor files
  against the build-record values.
- **Initialisation:** both journals are non-empty, so this is
  the documented first-initialisation ceremony:
  `initialise_anchor(ledger, path, kind="ship",
  recorded_at=…, allow_nonempty_ceremony=True)` and likewise
  `kind="ship-tx"` for the tx journal. Preconditions the
  operator script (`ops/init_ship_anchors.py`, new, refuses to
  run if either anchor already exists) verifies *before*
  initialising: ship ledger loads and its head equals the head
  recorded in the cycle-13 build record lineage (the seq-4
  finalise head read from the current ledger,
  `6911dff4…870`); tx journal loads with 6 entries and no
  non-terminal transactions outstanding (a non-terminal tx at
  anchor-init time would be blessed mid-flight — refuse and
  run `recover_ship_tx` first if any exist). After
  initialising: `verify_anchor(...) == ()` for both, and the
  script prints both anchor dicts for transcription into the
  build record.
- **Steady state:** from initialisation on, every sanctioned
  ship uses §5.1's anchored form and advances both anchors;
  `verify_anchor` on both is added to the morning/health
  surface via `verify_live_run.py --check-ship-anchors`
  (read-only; a mismatch is an alert, never an auto-repair —
  `force_reanchor` remains a manual, audited operator act and
  is *not* wrapped by any script in this cycle).

### 5.3 (c) End-to-end proof in the WS1 sandbox

In the §1.3 sandbox (which contains a byte copy of
`state/ship-ledger/`):

1. Run `init_ship_anchors.py` against the *copy* → both anchors
   created at the copied heads (ship seq 4, ship-tx seq 6).
2. Build a real ship for the sandbox's cycle-14 recording (the
   `ledger-head-anchoring` item the sandbox loop picks first):
   manifest + release record + gate decision + attestation
   using the existing `test_trust_shipcheck.py` fixture
   *patterns* re-declared in a new integration test
   (`tests/test_trust_shipcheck_anchored.py`) — the sandbox
   proof is a test, not a manual run, so it stays green.
   Call `record_ship(..., anchor_path=…, tx_anchor_path=…)`
   with **no** `expected_ledger_head`. Assert: cycle recorded,
   tx `COMMITTED`, ship anchor advanced to the new head
   (seq 6: burn + finalise), ship-tx anchor advanced past 6.
3. **Rollback detection:** restore the copied ship ledger to
   its pre-ship bytes (seq 4) while leaving the anchors at
   their advanced values → a second `record_ship` attempt (any
   manifest) refuses pre-burn: `verify_anchor` reports
   `anchor_ahead_of_journal` (anchor seq 6 > journal length 4)
   → `ShipRefused`, tx journal gains no new transaction (the
   refusal precedes `begin` — §5.1's ordering keeps the
   existing preconditions before the tx opens; the test asserts
   the tx journal is byte-identical).
4. **Deletion detection:** delete the copied ship-ledger file
   entirely (loads as empty) → same refusal class
   (`anchor_ahead_of_journal` against the empty journal).
5. **Cross-check refusal:** call with the *correct* current
   head but a tampered anchor (head flipped) → refuses on the
   anchor even though the caller pin was right — the §5.1
   "neither overrides the other" property, test-pinned.
6. **Hook interleave (from §1.2):** repeat step 2 with the
   loop hooked and the hook made to fail → `record_ship`
   propagates `PostCycleHookError`, tx at `BURN_PENDING`;
   `recover_ship_tx(ledger, loop, root=…, anchor_path=…,
   tx_anchor_path=…)` settles it to `COMMITTED` and the anchors
   verify afterwards.

### 5.4 Should the REAL `state/state.json` advance this cycle? — Recommendation: NO

**Recommendation: initialise the real anchors (§5.2) this
cycle; do not run `record_ship` against the real state; the
real `state.json` stays at cycle_seq 13.**

Reasoning:

1. **Self-reference.** The pickable item *is*
   `ledger-head-anchoring`. Recording it means the first
   production use of anchor-derived pinning is the ship that
   records anchor-derived pinning's own completion — the
   evidence for the item would be produced by the mechanism the
   item builds, before any external seat has seen the
   mechanism. The sandbox proof (§5.3) demonstrates the path;
   the real recording should be executed *by* the proven path
   after reconciliation, not be its own proof.
2. **Standing practice + the held cycles.** Loop state has not
   advanced since cycle 13 precisely because recording waits
   for external reconciliation (BUILD-CYCLE-14's "Recording
   status" note is the template: built, reviewed, green — not
   recorded). Cycles 14–16 are HELD and must not be recorded;
   nothing about cycle 23's mandate lifts that. (Mechanically,
   `record_ship` records the *pickable backlog item*, not a
   build cycle — recording `ledger-head-anchoring` as loop
   cycle 14 would not itself record build cycles 14–16. But it
   would advance the shared state those held cycles' eventual
   re-review reasons about, and it would do so on a split
   external verdict. The conservative reading is the correct
   one.)
3. **Asymmetry of the two halves of §5.2/§5.4.** Anchor
   initialisation is *pin-only*: it writes two new files,
   touches no ledger and no state, is fully auditable
   (heads transcribed into the build record), and every day
   without it is a day the existing seq-4 ledger has no
   rollback witness. Its risk is blessing a wrong history —
   mitigated by the §5.2 precondition checks against the
   recorded cycle-13 head. Recording a cycle is *state
   mutation* under a held verdict — irreversible in the
   ledger's burn semantics. Do the reversible, protective half
   now; leave the irreversible half for the reconciled path.
4. **What unblocks recording, stated for the next cycle:**
   external reconciliation of cycle 23 (both seats on the
   WS3 re-rule and the WS5 mechanism), then a recording session
   that (i) re-verifies both real anchors, (ii) ships
   `ledger-head-anchoring` via §5.1's anchored `record_ship`
   as loop cycle 14, and (iii) takes up cycles 14–16's
   re-review as its own gated question — not as a side effect
   of this recording.

### 5.5 WS5 tests + claim wording

New `tests/test_trust_shipcheck_anchored.py`: §5.3 steps 2–6
as tests (6 tests), plus (7) `record_ship` with neither head
nor anchor still refuses (legacy guard intact); (8) legacy
caller-head-only form still works (back-compat pin).
Changed: `tests/test_trust_shiptx_anchoring.py` gains a test
that `record_ship` (not only manual `update_anchor`) advances
the tx anchor.

**May claim:** "The sanctioned ship path no longer requires a
caller-supplied ledger head: with an anchor path, `record_ship`
verifies the ship anchor (and cross-checks any supplied head
against it), advances both the ship and ship-transaction
anchors on commit, and refuses pre-burn — burning nothing — on
a rolled-back or deleted ledger, proven end-to-end in a sandbox
copy of the real ledgers. Anchors for the repo's own
ship ledgers were initialised (ship seq 4, ship-tx seq 6) with
their heads recorded in the build record."
**May not claim:** that the anchors live on separate storage
or under a separate OS user (they are in `state/anchors/` on
this VM — outside the journal directory, inside the same
rollback domain; the build-record transcription is the second
copy); that real loop state advanced (it did not — §5.4); that
`check_ship` changed (it did not); that a caller-supplied head
is rejected in all forms (the legacy form remains for pure
checks and back-compat, and is labelled non-sanctioned in the
docstring).

---

## 6. Operability summary — what the operator actually runs

After cycle 23 lands, the day-to-day surface is:

| Command | When | Effect / artefacts |
|---|---|---|
| `python3 ops/provision_verifier_home.py <dir>` | Once per new verifier home (sandbox or future deployment) | §2.2 layout + keys + bootstrap + production flip; emits `<dir>/run-config.json` |
| `python3 ops/run_pinned_loop.py --config <run-config.json> --state <state-dir> --cycles N --coders … --reviewers … --delta …` | Per build cycle | Hooked cycles; one JSON line per cycle; exit 3 = "cycle recorded, pin pending" (alert, §1.1 contract) |
| `python3 ops/verify_live_run.py <sandbox-or-state> [--check-pending] [--check-ship-anchors]` | After any driver run; in the morning check | Read-only verification of pin/journal/anchor consistency (§1.4, §5.2); prints `pin_pending`, `movement_terminal` (WS3 cap), or anchor mismatches as named conditions, never repairs |

Recovery runbook (one line each, all already-designed paths):
pin pending → re-run `run_pinned_loop.py --pin-only` (calls
`snapshot_and_adopt()` without a cycle); returned pair in hand →
`adopt_returned` via the same flag with the pair file the driver
wrote on `PinAdoptionBurned` (the driver serialises
`returned_pin`/`returned_record` + `expected_old_pin` to
`<pin_dir>/returned-pair.json` before exiting 3 — a small WS1
build addition that turns S5's "available" case into the
default rather than a programming exercise); movement terminal
(WS3 cap) → do nothing, next cycle's pin supersedes; anchor
mismatch → stop, human + `force_reanchor` only with a recorded
reason, never scripted.

Standing prohibitions the runbook states: never run two drivers
on one state dir; never hand-edit `state.json`, the pin store,
or any journal (every artefact in this design is written by
exactly one component, listed in §8); never set an INIT flag
outside `provision_verifier_home.py`'s bootstrap phase.

## 7. Blockers and open questions found while designing

1. **No snapshot signer exists for the real state.** Genesis in
   WS1 binds a *new* snapshot signer id/key. For the sandbox
   that's free; for any future real-state pinning it is a
   provisioning decision (key custody, signer id) that this
   cycle should record as taken-for-the-sandbox only.
2. **Production deployment remains unprovisioned** (§2.4.1):
   WS2 proves production mode under same-user spawn. Anyone
   reading cycle 23's claims as deployment claims is misreading
   them; §2.5's wording is the guard.
3. **§3.4's issuance-journal field is a scope addition** beyond
   WS3's letter (consumption journal). It is, in this seat's
   judgement, load-bearing for the depth-cap re-rule; the
   coordinator must ratify it explicitly or accept the §3.4
   fallback (lineage recorded, bound stays one-shot-by-scan).
4. **`record_ship` + hook interleave** (§1.2) leaves the ship-tx
   at `BURN_PENDING` on hook failure by design; if the war room
   prefers `record_ship` to catch `PostCycleHookError` and
   settle inline, that is a small change — but it must be
   chosen, not accidental.
5. **`PinStoreBusy` escaping `snapshot_and_adopt`** (S7) — if
   confirmed by the build seat's reading, the wrap into
   `PinAdoptionRefused` is a WS4 fix, listed in §8.
6. **Calibration bytes in the sandbox** are the real
   `state/calibration/calibration.json` (which also accumulates
   war-room scores). Snapshots bind its hash; any calibration
   write between WS1 step 0 and step 4 changes the bytes the
   pin attests — the live run must therefore run against the
   copy in one sitting, and the runbook says so. (On the copy,
   a mid-run calibration change would surface as candidate/
   state mismatch refusals, not corruption.)

## 8. Consolidated file change list

**Production code:**
- `core/loop.py` — WS1 hook (§1.1): `PostCycleHookError`,
  `cycle_hook` constructor param, post-save hook call. *Only
  production change to a Protected-Gate file; stdlib-only.*
- `trust/pin_adoption.py` — `make_pin_hook`; `suspected_burn`
  journal phase + reason-selection treatment (§4.3);
  `PinStoreBusy`→`PinAdoptionRefused` wrap if §7.5 confirms;
  `run_one_cycle_and_pin` docstring deprecation.
- `trust/ledger.py` — WS3: `EXTRA_KEY_SETS` +
  `_validate_entry_progression` hook in `HashChainJournal._load`;
  `CeremonyConsumptionLedger` v2 key set, lineage validation,
  `match_head_burn`/`check_head` re-rule, `append_consumption`
  lineage derivation; `CeremonyAuthorisationLedger` v2 key set
  (+`recovery_of_authorisation_id`), `append_authorisation`
  parameter.
- `trust/verifier_main.py` — WS3: authorise step 5b passes the
  burn's authorisation_id to `append_authorisation`; consume
  mode passes the issuance record's
  `recovery_of_authorisation_id` to `append_consumption`;
  docstring updates (§3.7).
- `trust/shipcheck.py` — WS5: `anchored_expected_head`,
  `record_ship` anchor-derived/cross-checked head semantics,
  `tx_anchor_path` + ship-tx anchor update (§5.1).
- `ops/provision_verifier_home.py`, `ops/run_pinned_loop.py`,
  `ops/verify_live_run.py`, `ops/init_ship_anchors.py` — new
  operator surface (§6, §5.2).

**Explicitly unchanged:** `signing/pin_ceremony.py`,
`signing/ceremony_authorisation.py` (envelope + reason grammar
untouched), `signing/pin_store.py`, `trust/anchoring.py`,
`trust/wiring.py`, the verifier env allowlist (19 keys),
`check_ship`, `eval/` (untouched, as every cycle).

**Tests:** new `tests/test_loop_pin_hook.py` (6),
`tests/test_trust_production_e2e.py` (7+4 probes),
`tests/test_trust_consumption_schema_v2.py` (13),
`tests/test_trust_pin_adoption_crashes.py` + child fixture (7
scenarios, S3/S7 with sub-cases), `tests/test_trust_shipcheck_anchored.py`
(8); changed `tests/test_trust_pin_adoption.py` (+2),
`tests/test_trust_ceremony_consumption.py` (one-shot test
re-pinned to cap semantics; race outcomes unchanged),
`tests/test_trust_shiptx_anchoring.py` (+1). Estimated +45
tests over the 1547 baseline, before war-room additions.

**Docs/records:** DECISION-CONSUMPTION-HEAD.md Addendum 3
(§3.6); BUILD-CYCLE-23.md carrying §1.7/§2.5/§3.8/§4.4/§5.5
claim wordings verbatim and the §5.2 anchor transcriptions;
real anchors created at `state/anchors/` (§5.2) — the only
write to real `state/` this design authorises.
