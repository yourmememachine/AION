# Design B — Cycle 23: production integration of the ceremony line

Seat: DESIGN SEAT B. Status: design only — no production code in
this document's commit. Sources read in full before designing:
`internal/CROSS-CHECK-16.md`, `internal/CROSS-CHECK-15.md`,
`internal/BUILD-CYCLE-22.md`, `internal/DECISION-CONSUMPTION-HEAD.md`
(incl. Addendum 2), `trust/ledger.py`, `trust/verifier_main.py`
(`_load_config`, `ceremony_authorise` step 5b, `ceremony_consume`),
`signing/ceremony_authorisation.py`, `signing/pin_ceremony.py`
(`reanchor_pin`), `core/loop.py`, `trust/pin_adoption.py`,
`signing/pin_store.py`, `trust/shipcheck.py`, `trust/anchoring.py`,
`trust/wiring.py`. Ground facts verified against the tree, not
assumed: HEAD is cycle 22, commit `59a656a`, 1547 tests;
`state/state.json` is at `cycle_seq` 13; `pick_next()` on the real
backlog returns `ledger-head-anchoring` (leverage 6.5, seq 20,
approved, pending); the real ship ledger at `state/ship-ledger/`
holds 4 entries (`ship-ledger.json`) and 6 (`ship-tx.json`) and has
**no anchor files anywhere**; `core/loop.py` is in the Protected
Gate's `PROTECTED_FILES` (`eval/gate.py`, mirrored in
`trust/pathpolicy.py:GATE_PROTECTED_FILES`).

## 0. Rulings up front (the five decisions this design makes)

1. **WS1 hook shape:** `CoreLoop` gains ONE optional constructor
   keyword, `on_cycle_persisted=None`. No new method, no new
   import, no signature change to `run_one_cycle`. The hook fires
   after `save()` inside `run_one_cycle`, exactly once per
   persisted cycle, and its exceptions propagate with the cycle
   entry attached (`.cycle_entry`), mirroring the existing
   `run_one_cycle_and_pin` contract. Default `None` is
   byte-for-byte the cycle-22 behaviour.
2. **WS2 bootstrap order:** anchors are initialised by ONE
   research-mode config-load invocation against an empty,
   disposable verifier home (all three `*_INIT=1`, a deliberately
   malformed request body so no mode body ever runs), then the
   mode is flipped to `production` and every INIT flag removed
   before any real request. Production never sees an INIT flag.
3. **WS3 recovery bounds — RE-RULED: bounded chains, depth cap 2.**
   With lineage explicit in the schema (WS3), recovery is no
   longer one-shot: a movement `(old, new)` may be consumed at
   most 3 times — one `primary` (depth 0) and up to two
   `recovery` consumptions (depth 1, depth 2), each verifier-
   derived, each pointing `recovery_of` at the head burn it
   recovers. This supersedes Addendum 2's one-shot ruling and its
   race paragraph; §3.6 states exactly what changes and what
   external re-ratification is owed. The cap is a single named
   constant (`MAX_RECOVERY_DEPTH = 2`) so re-ruling back to
   one-shot is a one-line change plus test re-pins, not a redesign.
4. **WS4 fault layers:** at least two of the seven scenarios
   (consume-then-die, concurrent adopters) MUST be true
   subprocess tests. In-process monkeypatch tests are labelled
   seam tests in their class names and may not be cited as crash
   coverage — a patched `PinStore.adopt` proves exception
   mapping, not crash behaviour.
5. **WS5 real state:** initialise the real ship / ship-tx anchors
   this cycle (additive, git-audited, does not touch
   `state.json`); do **NOT** advance real `state/state.json`.
   Recording cycle 23 as loop cycle 14 while cycles 14–16 are
   HELD and unrecorded would falsify the loop's history. Full
   reasoning in §5.5.

**Non-goals, restated so the build cannot drift:** cycles 14–16
are not re-reviewed, not shipped, not recorded. `eval/` is
untouched. The issuance journal (`ceremony-authorisations.json`)
is not anchored this cycle (follow-up
`ceremony-journal-anchoring` stays open, narrowed as cycle 22
left it). No deployment is provisioned on this VM: WS2's
"production" is the verifier's `AION_DEPLOYMENT_MODE=production`
with mandatory anchoring, run same-user in a temp dir — §2.5
names what that does and does not prove.

---

## WS1 — Loop integration + live run

### 1.1 The problem, precisely

`trust/pin_adoption.py:run_one_cycle_and_pin` already implements
the correct ordering (cycle persists, then pin) as an external
driver, and `core/loop.py` never calls it. Seat-gemini's defect
("zero live loop wiring") is not that the driver is missing — it
is that the *loop itself* has no sanctioned attachment point, so
any production entry point must remember to wrap it, and the one
sanctioned ship path (`trust/shipcheck.py:record_ship`) calls
`loop.run_one_cycle` directly and would silently bypass a
wrapper-only convention. The fix must therefore live in
`CoreLoop` — but `core/loop.py` is Protected Gate scope, so the
change is the smallest one that creates a real attachment point.

### 1.2 The change to `core/loop.py` (the ONLY change to that file)

```python
def __init__(self, state_dir, *, on_cycle_persisted=None):
    ...
    if on_cycle_persisted is not None and not callable(on_cycle_persisted):
        raise ValueError("on_cycle_persisted must be callable or None")
    self._on_cycle_persisted = on_cycle_persisted
```

And inside `run_one_cycle`, the current tail is:

```python
            self.save()
        except BaseException:
            self.state = snapshot
            raise
        return copy.deepcopy(entry)
```

It becomes:

```python
            self.save()
        except BaseException:
            self.state = snapshot
            raise
        if self._on_cycle_persisted is not None:
            try:
                self._on_cycle_persisted(copy.deepcopy(entry))
            except BaseException as exc:
                exc.cycle_entry = copy.deepcopy(entry)
                raise
        return copy.deepcopy(entry)
```

That is the entire diff: ~10 lines, stdlib only (no new imports —
`copy` is already imported), no network, no new file I/O in the
loop itself. The Protected Gate consequence must be stated in
the build record: this change is itself a protected-file change
and goes through the normal gate like any other; the design does
not ask for an exemption.

**Hook semantics (normative):**

- **When it fires:** after `save()` has returned (state bytes
  fsync'd and `os.replace`d — the exact bytes `PinAdopter.
  _read_consistent_pair` will read from disk), before
  `run_one_cycle` returns, exactly once per persisted cycle.
- **When it never fires:** idle return (`pick_next()` is `None`
  → returns `None` before the hook site); any gate refusal
  (`InvalidTransition`, delta validation); any `save()` failure
  (the `except` path restores the snapshot and re-raises before
  the hook site). It does NOT fire for `scan()` or `approve()`
  saves — those are not cycle completions, and pinning a
  non-cycle state would attest a `cycle_seq` the snapshot
  discipline does not mean. (Rejected alternative: fire on every
  `save()`. It would pin mid-backlog states, produce candidates
  whose `cycle_seq` duplicates the previous cycle's, and force
  the adopter to special-case them. The pin attests *cycle
  snapshots*; backlog edits are not cycles.)
- **Argument:** one positional argument, a deep copy of the
  history entry (same object `run_one_cycle` returns). The hook
  gets no state dict and no `CoreLoop` reference: everything the
  adopter needs is on disk by construction, and handing the hook
  the live `self.state` would invite it to mutate unvalidated
  state. Return value is ignored.
- **On hook exception:** the cycle is already persisted and is
  NOT rolled back (un-saving a shipped cycle would falsify loop
  history — the `run_one_cycle_and_pin` precedent). The
  exception propagates unchanged except that the loop attaches
  `.cycle_entry` (a deep copy of the entry) to it before
  re-raising, so a caller that catches at the top level can
  always name the recorded-but-unpinned cycle. Contract wording,
  to be copied into the `__init__` docstring: **"cycle recorded,
  pin pending, alert"** — the caller's duty is to surface the
  failure; the pin catches up on the next attempt (dense advance
  if one cycle behind, ceremony if more).
- **Reentrancy:** the hook must not call `run_one_cycle`,
  `scan`, or `approve` on the same loop (the hook runs outside
  the snapshot/restore block, so a reentrant `save()` would
  persist state the outer call believes it owns). This is a
  documented caller obligation, stated in the docstring; it
  cannot be enforced in-process and the design does not pretend
  otherwise. `PinAdopter.snapshot_and_adopt` satisfies it: it
  reads files and writes only the pin store.
- **Idempotence of effect:** firing the adopter's
  `snapshot_and_adopt` as the hook is safe against double
  invocation for the same state (unchanged state →
  `already_current` within the retained envelope's TTL, integrity
  refusal after it — cycle 22's documented behaviour), but the
  design rule is still **exactly one wiring per process** (§1.3).

**Rejected alternatives:**

- *Call the adopter from inside `run_one_cycle` by importing
  `trust.pin_adoption`.* Rejected: it makes `core/loop.py`
  import the trust layer (inverting the dependency the trust
  lint polices), breaks stdlib-only, and puts network/subprocess
  code (the verifier client spawn) inside the Protected Gate's
  most sensitive file. The hook keeps the loop ignorant of what
  a pin is.
- *Leave `core/loop.py` untouched; bless `run_one_cycle_and_pin`
  as the wiring.* Rejected: that is cycle 22's state, and both
  external seats named it as the defect. A convention every
  caller must remember is not integration.
- *A hook registry / list of hooks.* Rejected: one hook, one
  responsibility. A list invites ordering ambiguity (which hook
  sees the cycle first, what a mid-list failure means) for no
  current need.

### 1.3 Interaction with `record_ship` and `run_one_cycle_and_pin`

Three callers can now reach `run_one_cycle`: `record_ship`
(sanctioned ship path), `run_one_cycle_and_pin` (cycle-22
driver), and any loop constructed with the hook. The rules:

1. **A loop passed to `record_ship` MUST be constructed without
   the hook.** `record_ship` burns a ship decision, records the
   cycle, and finalises; if the hook also fired the adopter
   mid-`record_ship`, a pin failure would surface inside a ship
   transaction whose state machine has no state for "cycle
   recorded, finalise pending, pin failed" — it would strand the
   tx at `CYCLE_RECORDED` for a reason unrelated to the ship.
   Pin adoption for shipped cycles happens as a separate,
   subsequent step driven by the ship's caller, not inside the
   transaction. Enforcement: a test constructs a hooked loop,
   passes it to `record_ship`, and asserts the hook did not fire
   is *impossible* to guarantee from inside `record_ship` (it
   cannot see the hook) — so the rule is discharged by (a) a
   docstring paragraph in `record_ship`, and (b) a lint-style
   test asserting `trust/shipcheck.py` never constructs
   `CoreLoop` (it receives one), which is already true today.
   Honest scope: this is convention + test, not a runtime guard,
   and the claim wording in §1.6 says so.
2. **`run_one_cycle_and_pin` is deprecated, not deleted.** It
   stays for its existing tests, gains a docstring line: "Do not
   combine with a hooked loop: the hook and this driver would
   both attempt adoption for one cycle." Double adoption is
   fail-closed (second attempt is `already_current` or an
   integrity refusal) but noisy and, after the retained
   envelope's TTL, indistinguishable from a real integrity
   failure — exactly the kind of false alarm that trains
   operators to ignore refusals.
3. The production entry point (new, §1.4) constructs the loop
   with `on_cycle_persisted=adopter.snapshot_and_adopt`-shaped
   callable — specifically a small closure that takes the entry
   argument and calls `adopter.snapshot_and_adopt()`, because the
   hook passes an entry the adopter does not need. The closure
   lives in `trust/pin_adoption.py`, NOT in `core/loop.py`.

### 1.4 New production entry point

New function in `trust/pin_adoption.py`:

```python
def hooked_loop(state_dir, adopter) -> CoreLoop:
    """Construct the production loop: a CoreLoop whose every
    persisted cycle is pinned through ``adopter`` before
    run_one_cycle returns. The hook ignores the entry argument
    (the adopter re-reads state from disk — the bytes that
    exist, not the bytes the caller remembers)."""
```

And `PinAdoptionBurned`/`PinAdoptionRefused` raised through the
hook already carry the right types; the loop attaches
`.cycle_entry`, so the adopter does not need to. One adjustment
in `pin_adoption.py`: `PinAdoptionBurned.__init__` already sets
`self.cycle_entry = None` — the loop's attachment overwrites it
after propagation. The build must add a test proving the
attachment survives (the loop sets it on the exception object
the hook raised, which is the same object the caller catches).

### 1.5 The live run (sandbox copy of real state)

**Adversarial preface — how a "live run" proves nothing.** Three
failure shapes must be designed out before the run means
anything: (a) running against a *synthetic* state (fresh
`cycle_seq` 0 backlog) proves the machinery, not the integration
with the real state's shape — the real state has 13 cycles of
history, blocked items, and a specific pick order; (b) hand-
picking which backlog items the sandbox cycles record (editing
state, calling internals) proves a script, not the loop; (c)
running the adopter against a research-mode verifier and then
describing the run as "production integration" — the run's claim
inherits the verifier mode it actually used. The run below is
specified against all three.

**Setup:**

- `cp -a state/ <sandbox>/state/` (byte copy: `state.json` at
  `cycle_seq` 13, `calibration/calibration.json`, and
  `state/ship-ledger/` — the ship ledger copy is for WS5 §5.4,
  the pin flow does not read it). The real `state/` is never
  opened for writing by the run; a pre/post SHA-256 of every
  file under real `state/` is recorded in the run log and must
  be identical.
- Pin dir: `<sandbox>/pin/` (outside the sandbox state dir —
  `PinStore` enforces this). No pin file exists at start: the
  first adoption is genesis, as in production first use.
- Verifier home: **the WS2 disposable production-mode home**
  (§2) — the live run depends on WS2's harness landing first.
  If WS2 slips, the run may be executed against a research-mode
  home for debugging, but that execution is NOT the recorded
  live run and may not be cited as one.
- Keys the sandbox needs (all generated fresh into `<sandbox>/`,
  none inside the repo — `_check_key_path` refuses repo paths):
  1. snapshot signing key (HMAC, `signing/gate_decision`
     discipline, 0600) — the `PinAdopter`'s `signing_key`; its
     `signer_id` / `key_id` become `AION_PIN_SIGNER_ID` and the
     config's snapshot signer pins.
  2. verifier HMAC key + ceremony seed (WS2 provisioning, §2.3):
     independent random draws, neither on a refused list.
  3. `CeremonyPublicKey` derived from the ceremony seed,
     supplied to `build_pin_adopter` out-of-band (in the run
     script, read from the seed file it just generated — the
     script is the operator here, and the run log says so).
- Evidence dir: shared adopter/verifier dir under `<sandbox>/`
  (the `build_pin_adopter` evidence-dir equality check requires
  adopter `AION_PIN_EVIDENCE_DIR` == verifier
  `AION_CEREMONY_EVIDENCE_DIR` after resolution).
- Operator: one operator id, allowlisted in the verifier env,
  used as `AION_PIN_OPERATOR_ID`.

**Exact cycle sequence** (driven only through the public loop
API — `run_one_cycle` on the hooked loop, plus deliberate
unhooked cycles where stated; seats are synthetic sandbox ids
satisfying the loop's gates: ≥3 coders, ≥6 reviewers, disjoint,
delta verifier ∈ reviewers ∉ coders; the delta metric is
`tests_passing` with the sandbox run's own before/after counts
and `evidence_ref` naming the run log — the run log must state
plainly that these sandbox cycles are integration exercises
recorded against a COPY, not project cycles):

| Step | Action | Expected pin outcome |
|---|---|---|
| 1 | Hooked `run_one_cycle` (records `ledger-head-anchoring` — whatever `pick_next` returns; the log asserts the item id equals a fresh `pick_next()` on the copy, never a hand choice) | Pin store created by **genesis `initial_anchor` ceremony**: consume at the production verifier, adopt, pin at `cycle_seq` 14. Assert: pin store file exists, `read_all` verifies, consumption journal in the WS2 home has exactly 1 entry, kind lineage (WS3) `primary`/depth 0. |
| 2 | Hooked `run_one_cycle` (next pick) | **Dense `advance_pin` step**: pin 14 → 15, outcome `advanced`, NO new consumption entry (advance never touches the verifier), candidate retained in `snapshot-candidate.json`. |
| 3 | Two cycles on an UNHOOKED loop over the same sandbox state dir (hook absent by construction — a second `CoreLoop(state_dir)` with no hook) | State advances 15 → 17; pin still 15. Assert pin store bytes unchanged across both cycles. |
| 4 | One `adopter.snapshot_and_adopt()` attempt (the catch-up a restarted hooked process would make; equivalently a hooked cycle — the design uses the direct attempt so the ceremony is attributable to the gap, not to a new cycle) | **`chain_gap_recovery` ceremony**: strict result `("chain_gap",)`, consume, adopt, pin at 17. Assert: consumption journal now 2 entries; ceremony record in pin history has `gap_from_seq=16, gap_to_seq=16`; pin history length 2 (genesis + gap), the advance at step 2 correctly leaving no ceremony record. |
| 5 | Repeat `snapshot_and_adopt()` on unchanged state | `already_current` (within retained-envelope TTL). Assert no new consumption, pin bytes unchanged. |

Assertions after the run: sandbox `state.json` `cycle_seq` 17;
real `state/` hashes unchanged; the full verifier-side journals
(authorisations, consumptions, signing ledger) in the WS2 home
reconcile 1:1 with the pin history (2 consumptions, 2
authorisations, mirror entries present). The run is scripted as
a test (below), not performed by hand — a hand run is not
reproducible evidence.

### 1.6 WS1 claim wording

- **May claim:** "The production loop pins every persisted cycle
  through `PinAdopter`: `CoreLoop` fires an injected hook after
  each cycle's save, and a scripted live run against a byte copy
  of the real state (cycle_seq 13 → 17) exercised genesis
  `initial_anchor`, a dense advance, and a `chain_gap_recovery`
  ceremony against a production-mode verifier, with the real
  state tree hash-identical before and after."
- **May NOT claim:** that the real state's pin exists (no pin
  store exists for real `state/` after this cycle — the sandbox
  pin attests a copy that has since diverged); that shipped
  cycles via `record_ship` are pinned (the hook is excluded from
  that path by convention + lint test, §1.3); that sandbox cycles
  are project cycles 14–17 (they are integration exercises on a
  copy and are never recorded in real state).

### 1.7 WS1 file/function changes

- `core/loop.py`: `CoreLoop.__init__` (new keyword + validation +
  docstring contract), `CoreLoop.run_one_cycle` (hook site).
  Nothing else.
- `trust/pin_adoption.py`: new `hooked_loop(...)`;
  `run_one_cycle_and_pin` docstring (deprecation/combination
  warning). No behaviour change.
- `trust/shipcheck.py`: `record_ship` docstring paragraph
  (hookless-loop requirement). No behaviour change.
- New `tests/test_loop_pin_hook.py`: hook fires once per
  persisted cycle with a deep-copied entry; does not fire on
  idle, on gate refusal, on `save()` failure (fault-injected
  `save`), or on `scan`/`approve`; hook exception propagates
  with `.cycle_entry` attached and state remains persisted
  (reload shows the cycle); non-callable hook refused at
  construction; default-`None` loop is behaviour-identical
  (existing `tests/test_loop.py` must pass unmodified — that is
  itself the regression assertion).
- New `tests/test_cycle23_live_run.py`: the §1.5 sequence as a
  subprocess-free integration test over a copied real state
  (skips if `state/state.json` is absent); asserts the table's
  outcomes and the real-tree hash invariance. This test is the
  live run's durable form; the build record cites its output.
- `tests/test_trust_lint.py`: no change expected (the hook calls
  no watched constructor); if the lint counts the closure in
  `pin_adoption.py` differently, the allowlist entry for
  `run_one_cycle` in that file is updated with its reason, as in
  cycle 22's mechanical fix.

---

## WS2 — Production-mode end-to-end

### 2.1 What "production-mode end-to-end" means here

A disposable verifier home in a temp dir, configured with
`AION_DEPLOYMENT_MODE=production`, all anchors in place, driven
exclusively through `trust.wiring.production_client` (via
`build_pin_adopter`) — authorise → consume → adopt — with the
client's `expected_deployment_mode="production"` pin active, so
a verifier that answers in any other mode is refused by the
client at response time. This is the first time the production
factory's full path runs: cycle 22's adopter tests used a
research-mode client, so `production_client`'s validations
(allowlist, INIT refusal, anchor placement/distinctness, signer
and key pins) have never been exercised against a live ceremony.

### 2.2 The full env set

From `trust/wiring.py` (`ALLOWED_ENV_KEYS`, 19 names — the
wrapper's allowlist in `deploy/verifier-identity/run-verifier.sh`
governs) and `trust/verifier_main.py:_load_config`'s production
rules. The e2e env contains exactly these, no more (an extra key
is a wiring refusal, and the test asserts that):

| Key | Required by | Value in the harness |
|---|---|---|
| `AION_VERIFIER_KEY_PATH` | wiring + verifier | `<tmp>/keys/verifier.key` (0600, outside repo) |
| `AION_VERIFIER_SIGNER_ID` | wiring + verifier | harness signer id; == `expected_signer_id` pin |
| `AION_VERIFIER_ACTOR_ID` | wiring + verifier | harness actor id |
| `AION_REGISTRY_DIR` | wiring + verifier | `<tmp>/registry/` (provisioned, §2.4) |
| `AION_VERIFIER_HOME` | wiring + verifier | `<tmp>/verifier-home/` |
| `AION_DEPLOYMENT_MODE` | wiring + verifier | exactly `production` |
| `AION_ANCHOR_PATH` | wiring (required) + verifier (production-required) | `<tmp>/anchors/signing.anchor.json` |
| `AION_BUDGETS_ANCHOR_PATH` | wiring (required) + verifier (production-required) | `<tmp>/anchors/budgets.anchor.json` |
| `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` | wiring (required) + verifier (production + ceremony seed ⇒ required) | `<tmp>/anchors/consumption.anchor.json` |
| `AION_CEREMONY_OPERATORS` | verifier (production-required; wiring-allowlisted, deliberately not wiring-required) | the one harness operator id |
| `AION_CEREMONY_EVIDENCE_DIR` | verifier (production-required) | `<tmp>/evidence/` (== adopter evidence dir) |
| `AION_CEREMONY_SIGNING_SEED_PATH` | verifier (production-required) | `<tmp>/keys/ceremony.seed` (0600, outside repo) |

Deliberately ABSENT: `AION_ANCHOR_INIT`,
`AION_BUDGETS_ANCHOR_INIT`,
`AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` (wiring refuses any value
other than absent/empty/`"0"`; the verifier refuses `"1"` in
production — the harness omits them entirely, the cleanest
spelling of "off"). Optional and omitted: `AION_VERIFIER_TTL_SECONDS`
(default 900 stands), `AION_VERIFIER_PURPOSE` (default
`memory-commit`; the ceremony modes do not consult it),
`AION_VERIFIER_PROPOSAL_BUDGET` / `AION_VERIFIER_IDENTITY_BUDGET`
(defaults stand). The adopter's own `AION_PIN_*` variables
(`trust/pin_adoption.py:pin_adopter_config_from_env`) are a
separate namespace and must NOT appear in the verifier env —
`production_client` would refuse them as unallowlisted, and the
harness asserts exactly that refusal in a negative test.

### 2.3 Provisioning steps (bootstrap order is the design)

Production refuses every INIT flag, and `_load_config` requires
all three anchors to verify before any mode runs — so a
production home cannot bootstrap itself. The order below is
forced; each step names the check that proves it landed.

1. **Directories:** `<tmp>/keys` (0700), `<tmp>/verifier-home`,
   `<tmp>/registry`, `<tmp>/evidence`, `<tmp>/anchors` — anchors
   outside the verifier home and pairwise distinct (wiring and
   `_load_config` both enforce; a placement mistake is a startup
   refusal, which the harness treats as a provisioning bug, not
   a test result).
2. **Keys, independent draws:** verifier HMAC key via
   `signing/gate_decision`'s key-file discipline; ceremony seed
   via `generate_ceremony_key_file` (O_EXCL, 0600, refuses
   overwrite); snapshot key likewise. Independence is not
   asserted by the harness — it is *checked by the verifier
   itself* at startup: byte-equality, the refused-test-seed
   lists, and the cycle-21 derivation-overlap relations (seed ==
   sha256(key), key == ceremony public key, etc.) all refuse as
   `verifier_misconfigured`. The harness additionally asserts
   none of the three secrets is a refused test value, so a
   provisioning accident is caught even in the research
   bootstrap step (which runs the same `_load_config` checks).
3. **Anchor bootstrap — ONE research-mode config-load
   invocation.** With the home still empty (no ledgers, no
   budget store), invoke the verifier once with
   `AION_DEPLOYMENT_MODE=research` and all three INIT flags
   `"1"`, sending a deliberately malformed request (unknown
   mode). `_load_config` runs before mode dispatch: it
   initialises the signing anchor (empty ledger only), the
   budgets anchor (genesis head only — the INIT guard refuses a
   non-genesis store), and the consumption anchor (empty journal
   only), then the request itself fails as malformed. Assert
   afterwards: three anchor files exist, each at seq 0 / genesis
   head; the signing ledger is still empty and no signature was
   issued (the bootstrap invocation must leave NO `sign` entries
   anywhere — if a future refactor makes malformed requests
   reach a mode, this assertion catches the bootstrap becoming
   a signing event).
   *Rejected alternative:* call `trust.anchoring.initialise_anchor`
   directly from a provisioning script for signing + consumption
   and use the verifier only for budgets. It works, but it
   splits the ceremony across two mechanisms and the budgets
   anchor's bespoke format (verifier_main's own
   `_write_budgets_anchor`, not `trust/anchoring.py`) makes the
   split permanent knowledge every operator must carry. One
   invocation through the verifier's own config path exercises
   the exact code production startup will run.
   *Also rejected:* provisioning the home in production mode
   with INIT flags "just for the first run" — both layers refuse
   it, and designing around a refusal the system makes on
   purpose would be the cycle's worst signal.
4. **Flip to production:** same env, `AION_DEPLOYMENT_MODE=
   production`, INIT flags removed. First production invocation
   is a no-op-shaped request the harness controls (the WS2 e2e
   flow's first `ceremony_authorise` doubles as it). Assert the
   response carries `deployment_mode: "production"` (the client
   enforces this; a mismatch is a client refusal, which the
   harness surfaces as a failure, not a skip).

### 2.4 The registry blocker, named precisely

`AION_REGISTRY_DIR` must open as a valid `EvalRegistry`
(`_load_config` → `_open_registry` refuses `registry_untrusted`
otherwise). The ceremony modes never read registry content, but
config load constructs paths against it and gate modes require
it, so the home is not provisionable without one. The harness
provisions a minimal registry using `eval/registry.py`'s own
construction in the temp dir (the same fixture approach as the
existing trust tests). This is a harness artefact, not a
deployment registry, and the claim wording (§2.6) does not
extend to registry content.

### 2.5 What could block full production mode locally — complete list

1. **Separate OS user / wrapper routing: BLOCKED, out of scope
   by design.** `deploy/verifier-identity/run-verifier.sh`
   requires root and an `aion-verifier` OS user; neither exists
   on this VM, and `production_client(launch="wrapper")` is
   refused by the factory itself (no command hook —
   `verifier-wrapper-routing` backlog). The e2e therefore uses
   the same-user spawn (`launch="same-user"`). Consequence,
   stated in the claim: production *mode* (config discipline,
   mandatory anchoring, INIT refusal, client mode pin) is
   proven; the deployment-grade trust boundary (separate uid,
   root-owned env file) is NOT, and nothing in this cycle may
   describe the temp-dir home as a deployment.
2. **Key/seed placement:** `_check_key_path` refuses paths
   inside the repo and inside caller-named forbidden roots
   (registry dir). A temp dir satisfies this; any attempt to
   provision inside `~/workspace/ai` fails closed — the harness
   lives entirely under the system temp dir for this reason.
3. **Anchor placement:** all three anchors must resolve outside
   the verifier home, be pairwise distinct, not equal the key
   path, not inside the registry dir (wiring checks all of
   these pre-spawn). Satisfiable in temp; listed because a
   naive harness that puts anchors "next to the home" as
   siblings passes, but one that puts them *in* the home fails —
   the harness asserts the refusal once (negative test) so the
   placement rule is proven live, not just documented.
4. **The 28 skipped tests stay skipped.** The deploy-gated set
   ("deployment not provisioned on this machine") is gated on
   the real deployment (root + signer user + env file), not on
   anything WS2 builds. WS2 must not un-skip them against the
   temp home: they test the *deployment's* shape, and pointing
   them at a same-user temp home would manufacture green.

### 2.6 WS2 e2e flow and claim wording

Flow (one test, `tests/test_cycle23_production_e2e.py`):
provision per §2.3 → `build_pin_adopter(env, ...)` (which calls
`production_client` — assert the returned client's deployment-
mode expectation is `"production"`) → genesis
`snapshot_and_adopt()` against a small fixture state →
`initial_anchor` ceremony completes authorise → consume → adopt
entirely in production mode → assert all three anchors advanced
past genesis (signing anchor via the issuance mirror, consumption
anchor via the consumption, budgets anchor untouched at genesis
— no sealed-eval queries occurred, and the test asserts it did
not move, proving anchor updates are event-driven, not
ceremonial) → one dense advance → one refusal probe: replay the
genesis envelope's consumption through the client and assert
`ceremony_already_consumed`. Negative tests: production env with
any INIT flag → wiring refusal before spawn; env with an
`AION_PIN_*` key added → wiring refusal; anchors relocated
inside the home → wiring refusal; research-mode env passed to
`build_pin_adopter` → wiring refusal (`AION_DEPLOYMENT_MODE`
must be exactly `"production"`).

- **May claim:** "The ceremony line runs end-to-end in
  production mode: `production_client` + `build_pin_adopter`,
  mandatory anchors initialised by a documented bootstrap
  ceremony and verified at every startup, authorise → consume →
  adopt completing with the client's production-mode pin
  enforced."
- **May NOT claim:** production *deployment* (no separate OS
  user, no wrapper routing, same-user spawn in a temp dir);
  rollback protection beyond the anchored journals' stated
  position (the append→anchor window stands, §3/decision
  addendum); anything about the 28 deployment-gated skips.

### 2.7 WS2 file/function changes

- No production-code changes are required by this design:
  `trust/wiring.py`, `trust/verifier_main.py`,
  `trust/pin_adoption.py` already contain every mechanism. If
  the build finds one that is missing, that is a design defect
  to report back, not a gap to fill silently.
- New `tests/test_cycle23_production_e2e.py`: provisioning
  helper (module-level, reusable by WS1's live-run test and
  WS4's subprocess tests — one harness, three consumers, so the
  three workstreams cannot drift into three different notions
  of "production home"), the flow test, and the four negative
  tests above.
- `internal/BUILD-CYCLE-23.md` (build seat's, not this design):
  records the bootstrap ceremony as an operator act with its
  assertions, per §2.3 step 3.

---

## WS3 — Journal schema v2: recovery lineage

### 3.1 The defect, in Gemini's terms and in the code's

`CeremonyConsumptionLedger.EXTRA_KEYS` carries no reason, kind,
or lineage field. A recovery consumption is byte-indistinguishable
from the burn it recovers, so cycle 22's one-shot rule had to be
implemented as an inference — `match_head_burn` scans all earlier
entries for the head's `(old, new)` pair. Inference over a schema
that cannot express the fact is the defect: the journal cannot
answer "was this consumption a recovery, and of what?" — the
first question any auditor asks it. WS3 makes the journal able
to answer, then re-rules the bounds on the explicit fact.

### 3.2 Versioning: per-entry v1/v2 key sets (the load-bearing choice)

The constraint is mechanical: `HashChainJournal._load` enforces
`set(entry) == _ENTRY_KEYS | EXTRA_KEYS` for **every** entry, and
`_save` serialises `self._entries` verbatim. Three candidate
versionings:

- **(a) Widen `EXTRA_KEYS` in place.** Every existing v1 entry
  instantly fails the exact-key-set check → `CorruptLedgerError`
  on load → every live journal (the WS2 home's, every test
  fixture's, any future real home's) bricks the moment the code
  ships. Rejected unconditionally; this is the "migration that
  bricks live journals" failure the brief warns about, and it
  would fire at verifier *startup*, i.e. as a total ceremony
  outage.
- **(b) Journal-level version marker** (`{"v": "…/2", "entries":
  [...]}`) with whole-file migration on first v2 append.
  Rejected: `_load`'s top-level shape check (`set(data) ==
  {"entries"}`) is shared by every journal subclass; and a
  whole-file rewrite at first append creates a window where old
  code reading the migrated file bricks, plus a crash question
  (migrate-then-append is two commits pretending to be one).
- **(c) Per-entry versioning by exact key set — CHOSEN.** The
  consumption ledger accepts exactly two entry shapes:
  v1 = `_ENTRY_KEYS | EXTRA_KEYS_V1` (today's set), v2 =
  `_ENTRY_KEYS | EXTRA_KEYS_V2` (v1 set + the three lineage
  fields). Mixed files are valid forever: v1 entries are never
  rewritten, v2 entries are appended after them, and the hash
  chain is untouched because each entry's `entry_hash` was
  computed over exactly the fields it carries.

Implementation, kept inside the one subclass:

- `trust/ledger.py:HashChainJournal` gains ONE extension point:
  a method `_entry_key_sets()` returning a tuple of acceptable
  exact key sets, defaulting to `(frozenset(_ENTRY_KEYS |
  EXTRA_KEYS),)`, and `_load` checks membership in that tuple
  instead of equality with the single set. Every other subclass
  is behaviour-identical (its tuple has one element). This is
  the minimal base-class touch; the alternative (overriding
  `_load` wholesale in the subclass) duplicates the chain
  verification logic and invites the copy to drift from the
  base's — rejected.
- `CeremonyConsumptionLedger` overrides `_entry_key_sets()` to
  return both sets, and gains accessors that interpret a v1
  entry's missing lineage as its only possible meaning:
  `consumption_kind` → `"primary"`, `recovery_of` → `""`,
  `recovery_depth` → `0`. **Accessors interpret; nothing
  normalises.** Loaded entries are stored and re-saved byte-
  identically (a normalising load would change what `_save`
  writes for old entries and break their `entry_hash` on the
  next load — the design names this trap explicitly because it
  is the obvious implementation and it is wrong).
- v2 entry validation beyond key set (in the subclass's load
  path, via a new `_validate_entry(entry)` hook the base calls
  after the hash check — or, if the build prefers no second
  hook, inside `_entry_key_sets`' consumer… the design's
  requirement is the *checks*, the build seat may place them in
  the subclass `_load` wrapper): `consumption_kind ∈
  {"primary", "recovery"}`; `recovery_depth` is an int ≥ 0, not
  bool; `recovery_of` is `""` iff kind is `primary` (and depth
  0), else a hex64-shaped authorisation id… — note
  `authorisation_id` values are `_sha256` hex64 digests, so the
  check is the existing `_check_hex64` shape; a `primary` entry
  with nonzero depth or non-empty `recovery_of`, and a
  `recovery` entry with empty `recovery_of` or depth 0, are
  `CorruptLedgerError` at load. A journal that lies about
  lineage in a structurally impossible way is corrupt, not
  creative.

### 3.3 The v2 fields and where they are computed

`EXTRA_KEYS_V2 = EXTRA_KEYS_V1 | {"consumption_kind",
"recovery_of", "recovery_depth"}`. `kind` stays `"consume"` —
the lineage is a property of the consumption, not a new entry
kind (a new kind would fork every consumer that scans
`kind == "consume"`, including the signing-ledger mirror
cross-check's scoping discipline).

Computation is **verifier-side only**, inside
`CeremonyConsumptionLedger.append_consumption`'s bounded
reload-retry loop, recomputed on every attempt from the freshly
reloaded entries (the issuance-race lesson: lineage computed
from a stale snapshot could point at the wrong predecessor after
a competitor lands):

- Envelope reason ≠ `burned_unadopted` → `("primary", "", 0)`.
- Envelope reason == `burned_unadopted` → the burn entry is the
  one the shared predicate (§3.4) matches against the current
  entries: `consumption_kind = "recovery"`,
  `recovery_of = burn["authorisation_id"]`,
  `recovery_depth = lineage_depth(burn) + 1`, where
  `lineage_depth` reads the burn's own accessor-interpreted
  depth (v1 burn ⇒ 0). If the predicate matches nothing,
  `check_head` has already refused before the append is
  attempted — `append_consumption` asserts this ordering by
  re-running `check_head` first, as today.
- **No new parameter reaches `append_consumption`, and no field
  of the envelope asserts lineage.** The envelope does not carry
  these fields (its shape is unchanged — a v3 envelope is out of
  scope), the caller cannot supply them, and
  `trust/verifier_main.py`'s consume mode needs no change at
  all: it calls `append_consumption` and the ledger derives
  lineage from (envelope.reason, journal state). Authorise step
  5b changes only in that it calls the same shared predicate
  (§3.4) — its position, its single refusal code
  (`ceremony_recovery_unproven`), and its oracle discipline are
  unchanged. One subtlety the build must honour: step 5b and
  consume must derive the *same* burn for the same journal
  state, which is why both call one predicate function rather
  than two implementations of the rule.

### 3.4 `match_head_burn` and `check_head` under v2

`match_head_burn(entries, *, candidate, old_pin)` keeps its
signature and its exact-equality core (candidate == head target,
old pin == head old pin, with the no-pin shape handled as
today). The pair-scan is replaced by a lineage dispatch on the
HEAD entry:

- **Head is v2:** return the head iff `consumption_kind ==
  "primary"` and depth < `MAX_RECOVERY_DEPTH`, OR
  `consumption_kind == "recovery"` and `recovery_depth <
  MAX_RECOVERY_DEPTH`. I.e. any head whose depth is below the
  cap can ground one more recovery; a head at the cap cannot.
  No scan of earlier entries occurs — the head's own fields are
  the whole proof. (For depth-0 primary heads this reduces to
  cycle 22's first-recovery case; the scan is gone because the
  ambiguity it compensated for is gone.)
- **Head is v1:** the cycle-22 pair-scan applies verbatim (no
  earlier identical pair ⇒ match; an earlier identical pair ⇒
  None). A v1 head carries no lineage, so the blunt rule is the
  only sound one for it — and under it a v1 head can ground at
  most one recovery, exactly as today. The recovery that lands
  over a v1 head is written as v2 with depth 1 (its predecessor
  interprets as depth 0), so **the pair-scan becomes unreachable
  after the first v2 recovery lands over any movement**; it
  survives only for journals whose head is still v1. The code
  keeps it, clearly commented as the v1 fallback, with a test
  pinning that a v2 head never takes the scan path (constructed
  by hand-writing a journal whose head is v2-primary with an
  earlier identical pair — a state the live rules cannot
  produce, proving the dispatch is by head version, not by
  scan outcome).

`check_head` changes only in its `recovery` computation: it
calls the same predicate (as today) — the AlreadyConsumed /
HeadRegressionError mapping, the candidate-at-head and old-pin
rules, and the scoped-exception structure are unchanged. The
docstring's one-shot paragraph is rewritten to the §3.5 ruling.

### 3.5 The re-ruling: bounded chains, depth cap 2

**Ruling: `MAX_RECOVERY_DEPTH = 2`.** A movement may be
consumed at most three times: primary (depth 0), recovery
(depth 1), recovery (depth 2). A depth-2 head grounds nothing;
authorise refuses `ceremony_recovery_unproven`, consume refuses
via the predicate, and the movement is terminal — liveness
resumes at the next snapshot sequence, whose candidate differs
and whose movement is a new movement.

Analysis of the three options:

- **(i) One-shot, schema-grounded.** Sound, and now honestly
  expressible (head kind == primary). But it keeps the exact
  liveness defect Gemini named: a recovery that itself burns
  unadopted *bricks the movement*. When does a recovery burn
  unadopted? In precisely the crash window WS4 tests: consume
  committed, process dies or the returned pair is lost before
  adoption. That is not an exotic path — it is the expected
  failure mode of the whole ceremony design, and under one-shot
  two consecutive crashes on the same movement (kill after
  consume; recovery consume; disk-full on adopt) end the
  movement. The adopter's `adopt_returned` path covers the
  pair-available case with no consumption at all; one-shot
  leaves the pair-lost case with a single second chance.
- **(ii) Bounded chains, cap 2 — CHOSEN.** Each additional
  recovery is independently authorised (new ceremony_id, new
  evidence artefact, allowlisted operator, TTL-bound envelope,
  burn proof against the then-current head), lands only over
  the exact head it recovers, and is lineage-visible: the chain
  primary → depth 1 → depth 2 is a linked list in the journal
  (`recovery_of` names the predecessor's authorisation_id), so
  an auditor reads the whole story without inference.
  Single-use is preserved in its meaningful form: no
  authorisation is ever consumed twice (unchanged), no target
  is consumed by a *primary* twice (unchanged — a primary
  envelope over a consumed target still gets
  AlreadyConsumedError), and total consumptions per movement
  are hard-bounded at 3, after which the refusal is permanent
  and provable from the journal alone. Cap 2 rather than 1
  (= one-shot) for the double-crash reason above; cap 2 rather
  than 3+ because each recovery is an operator act with a fresh
  evidence burden, and a movement that has burned three
  consumptions has a operational problem (crashing adopter,
  failing store) that a fourth ceremony would paper over —
  the correct response at the cap is fixing the adopter, and
  the next cycle's snapshot restores liveness by construction.
- **(iii) Depth cap + wall-clock/evidence escalation** (e.g.
  depth ≥ 2 requires a second operator). Rejected: no second-
  operator credential exists in this system (operator identity
  is allowlist eligibility, not authentication — inventing a
  two-operator rule would dress that limit up as a control),
  and no requirement from either external seat asks for it.

**Race consequence, stated as a supersession.** Cycle 22's
Addendum 2 ruled that of two race-authorised recoveries against
one burn, the first consumption lands and the second refuses
AlreadyConsumedError. Under bounded chains that paragraph is
**superseded**: both envelopes were legitimately authorised
against the burn while it was head; the first lands as depth
`d+1`; the second, at consume time, faces a head that is the
first recovery — same `(old, new)` pair, depth `d+1 < 2` — and
lands as depth `d+2` with `recovery_of` naming the first
recovery's authorisation_id (the head it actually consumed
over, recorded truthfully at commit, §3.3). This is safe
because both landings are independently authorised, target-
identical, and journal-visible; it is bounded because the cap
counts them. What is NOT permitted, and a test pins: a third
racer (or a second racer when the burn was already depth 1 and
the first racer took it to the cap) refuses. The GPT seat's
preserved requirement — "exactly one consumption succeeds under
concurrency" — is honoured in the form that protects value:
for a single authorisation_id (single-use, unchanged) and for
primary consumptions of one target (unchanged). The design
flags the recovery-race change explicitly for the external
seats rather than smuggling it under "exactly-one" wording
that no longer means what cycle 22 meant.

**Preserved invariants (each gets a test, §3.7):** original burn
permanently burned (its authorisation_id can never re-consume);
no forked movement (every recovery's `(old, new)` equals its
predecessor's — enforced by the predicate's exact equality);
no backwards movement (head rules unchanged); a recovery can
never ground a *different* movement (predicate binds candidate
+ old pin exactly); lineage is never caller-asserted (§3.3).

**Documentation debt this ruling creates (build must pay it):**
`internal/DECISION-CONSUMPTION-HEAD.md` gains Addendum 3
recording the supersession of Addendum 2 (Addendum 2 stays as
history, as Addendum 1 did); the `match_head_burn` and
`check_head` docstrings, the `CeremonyConsumptionLedger` class
docstring, and `signing/pin_ceremony.py`'s crash-consistency
paragraphs that state one-shot semantics are rewritten; cycle
22's `OneShotRecoveryTests` and the re-pinned chain test in
`tests/test_trust_ceremony_consumption.py` are re-pinned to
bounded semantics with the supersession named in the test
docstrings — not silently edited.

### 3.6 WS3 claim wording

- **May claim:** "Consumption journal entries (schema v2) record
  verifier-derived recovery lineage — kind, predecessor
  authorisation, depth — with v1 entries verifying unchanged;
  recovery is bounded at depth 2 per movement, each recovery
  independently authorised and lineage-linked, and the bound is
  provable from the journal alone."
- **May NOT claim:** that bounded chains are externally ratified
  (seat-gpt ratified ONE-SHOT; seat-gemini demanded the schema,
  not this cap — the re-ruling goes to both seats in the cycle
  23 brief as a ruling to ratify or reject, and until they
  reconcile, cycle 23 is provisional on this point); that v1
  entries carry lineage (they are interpreted as primary/depth
  0, which is the only reading their shape supports — a v1 head
  still falls back to the pair-scan); that lineage proves
  adoption failed (the verifier still cannot observe adoption;
  it proves a recovery was authorised and consumed against a
  recorded burn, nothing about the pin store).

### 3.7 WS3 file/function changes and tests

- `trust/ledger.py`: `HashChainJournal._entry_key_sets()` +
  `_load` membership check; `CeremonyConsumptionLedger`:
  `EXTRA_KEYS_V1`/`EXTRA_KEYS_V2`, `_entry_key_sets()` override,
  lineage validation at load, `lineage_of(entry)` accessor
  (static), `match_head_burn` lineage dispatch (pair-scan kept
  as `_match_head_burn_v1` fallback), `append_consumption`
  lineage derivation inside the retry loop, `MAX_RECOVERY_DEPTH
  = 2` module-level constant beside `_APPEND_RETRY_ATTEMPTS`,
  docstring rewrites.
- `trust/verifier_main.py`: no logic change (step 5b and consume
  call the shared predicate/ledger as today) — the build must
  verify this by running the existing ceremony suites unmodified
  except the re-pins in §3.5; if a change there proves necessary
  it is reported as a design miss.
- New `tests/test_trust_consumption_schema_v2.py`: (1) a v1
  journal file (fixture bytes) loads and verifies under v2 code;
  (2) appending a v2 entry to it preserves the v1 entries
  byte-identically (reload + raw-byte prefix comparison);
  (3) malformed lineage (primary with depth 1, recovery with
  empty `recovery_of`, depth as bool, unknown kind) →
  CorruptLedgerError at load; (4) mixed v1/v2 hash chain
  verifies end-to-end; (5) lineage is derived, not asserted —
  `append_consumption` given a `burned_unadopted` envelope over
  a v1 burn writes depth 1 / `recovery_of` == burn's id, and
  there is no API surface to pass lineage in (signature
  inspection test, in the suite's existing style); (6) depth
  chain: primary → recovery 1 → recovery 2 land, recovery 3
  refuses at authorise (`ceremony_recovery_unproven`) and at
  consume (`check_head` predicate None); (7) v1-head fallback:
  pair-scan still refuses a second recovery over a v1 head with
  an earlier identical pair; (8) v2-head dispatch: hand-built
  v2-primary head with an earlier identical pair still matches
  (scan not consulted); (9) race: two recoveries authorised
  against one burn both land (depths 1, 2, linked), a third
  refuses AlreadyConsumed/at-cap; (10) concurrency: N threads
  consuming the SAME authorisation — exactly one success
  (GPT's preserved test, restated for v2); (11) signing-ledger
  mirror unchanged (mirror entry shape untouched — v2 fields do
  NOT propagate to the mirror; the mirror stays an audit trace
  in the existing shape, and a test asserts its key set).

---

## WS4 — Crash/restart coverage across the multi-artifact boundary

### 4.0 Method rules (read before the table)

The boundary under test spans four artefacts written by three
writers at different times: the verifier's consumption journal
(+ its anchor), the adopter's pending journal
(`adoption-pending.jsonl`), the candidate side file
(`snapshot-candidate.json`), and the pin store
(`snapshot-pin.json`). A test proves crash behaviour only if the
fault is injected at the layer where the crash would actually
occur:

- **Subprocess kill** (`os._exit` in a child driving the real
  flow, or SIGKILL from the parent) is the only honest injection
  for "process termination" claims. The child uses the WS2
  harness (production home) and the WS1 hooked flow.
- **State surgery** (parent rewrites/truncates/deletes an
  artefact between child runs) is the honest injection for
  corruption/loss claims — deterministic, and it models exactly
  the on-disk states a crash can leave, because every writer
  here is write-fsync-replace or append-fsync.
- **In-process seams** (monkeypatched `PinStore.adopt`,
  stubbed client) test exception *mapping* only. Classes using
  them are named `*SeamTests` and the build record may not cite
  them as crash coverage. Cycle 22 already has seam-level
  coverage of consume-committed/adopt-failed; WS4's new value is
  the subprocess and surgery layers, and duplicating seam tests
  under a "crash" label is the wrong-layer failure this
  workstream exists to avoid.

Every scenario pins: the artefact states after the fault, the
behaviour of the NEXT attempt (refusal vs recovery, and through
which named path), and the invariant that no scenario produces
a forked, backwards, or silently-repaired pin.

### 4.1 The seven scenarios

**S1 — Termination after consumption, before adoption.**
Injection: subprocess child runs `snapshot_and_adopt()` against
a pin store in a directory the parent makes read-only *by
pre-arrangement* is timing-fragile — instead the child drives
`reanchor_pin` directly with the production consumer (the
documented integrated wiring), prints the returned
`(pin, record)` as JSON to stdout, flushes, then `os._exit(42)`
without adopting. Parent asserts: consumption journal has the
entry (lineage `primary`, depth 0); pin store file does not
exist (genesis case) / is byte-unchanged (non-genesis case);
anchor advanced past the consumption.
Expected next attempt: (a) pair available (parent captured
stdout) → `adopt_returned` lands it with **zero new
consumptions** (journal length asserted); (b) pair discarded →
covered by S5b.

**S2 — Termination during pending-journal persistence.**
The journal append is `open("ab")` + one `write` + fsync; a kill
mid-write leaves a truncated final line. Injection: surgery —
truncate the last line of `adoption-pending.jsonl` mid-JSON
(and a variant: truncate to zero bytes mid-line leaving invalid
UTF-8). Expected: `_read_journal` skips the truncated tail (its
documented detection-aid semantics), no exception escapes
`snapshot_and_adopt`, and behaviour degrades honestly: if the
truncated line was the `authorised` line for a real burn, the
burn is NOT detected, the next attempt selects the primary
reason, and the verifier refuses it (candidate == consumed head
⇒ consume-side AlreadyConsumed / authorise-side the primary
path proceeds but `reanchor_pin`'s consume raises) →
`PinAdoptionBurned`/`Refused` surfaces, pin unmoved. Pinned
assertion: refusal, never a second primary consumption of the
target, never a crash in the adopter itself. The test docstring
must state the residual plainly: burn detection depends on an
unanchored local journal (cycle 22's carried minor F4.2); the
verifier's journal remains authoritative and an operator can
reconstruct the pending journal from it — automating that
reconstruction is NOT built here (rejected: silent self-healing
from a second source would hide journal loss, the exact event
an operator should see).

**S3 — Pending-journal corruption (whole file).**
Injection: surgery — replace the journal with (variants) random
bytes, valid JSONL of wrong-shaped objects, and a line whose
`phase` field is a non-string. Expected: identical to S2's
degraded path (merge logic ignores non-dict/unparseable lines;
wrong-shaped dicts merge harmlessly because `_unadopted_burns`
matches on exact candidate/old-pin fields). No refusal is
*caused* by the corruption itself; the failure, if any, arrives
as the S2 verifier refusal. Assert the pin store is never read
as damaged because the journal is — the artefacts' failure
domains are separate, and a test that lets journal corruption
touch the store would be testing a coupling that must not exist.

**S4 — Side-file (`snapshot-candidate.json`) loss.**
Injection: surgery — complete a dense advance (side file
written), delete the side file, attempt `snapshot_and_adopt()`
on unchanged state. Expected, pinned exactly: a fresh signing
of the same state bytes has a different `payload_hash`
(`signed_at` is in the payload — the cycle-22 disclosed reason
retention exists), so strict verification against the pin gives
`pin_mismatch`, classification `integrity_failure`,
`PinAdoptionRefused`, **no ceremony attempted, no consumption,
pin store byte-identical**. This is a liveness limit, stated in
the test and the claim wording: `already_current` on unchanged
state is only reachable while a retained candidate (journal or
side file) survives; losing both retentions while the state
does not change strands the adopter until the next cycle
changes the state — at which point the new candidate is a
normal advance/ceremony against the pin and nothing is blocked.
Rejected alternative: treating side-file loss as `lost_pin`
and re-anchoring by ceremony. A ceremony candidate must still
be the pinned snapshot to be `already_current`, and a fresh
candidate at the same seq with a different hash is a *fork at
the head sequence*, which `check_head` and the pin store both
refuse — the "recovery" would be refused by every layer
downstream, so building the attempt would only manufacture a
burned authorisation. Refusal at classification is the honest
behaviour.

**S5 — Restart with returned pair available vs discarded.**
Two halves, both subprocess restart (new child process, same
dirs — proving no in-memory state carries the recovery):
(a) *Available:* parent passes the S1-captured pair to
`adopt_returned` in the new process. Expected: adoption lands,
journal gains the `adopted` line, consumption count unchanged,
pin verifies.
(b) *Discarded:* new process runs `snapshot_and_adopt()` fresh.
Expected: pending journal (written by the dead process,
re-read from disk) yields the unadopted burn; reason computed
`burned_unadopted`; the retained candidate envelope from the
journal's `authorised` line is re-presented (same seq + hash —
a fresh signing could not match the burn); authorise step 5b
proves against the consumption head; second consumption lands
with WS3 lineage `recovery`, depth 1, `recovery_of` == the
original burn's authorisation_id; adoption lands. Assert
`lost_pin` appears nowhere (journal, envelope reason, record
reason).

**S6 — Recovery-after-recovery burns (WS3 bounds).**
Scripted sequence (in-process against the real verifier
subprocess is sufficient here — the fault is *repeated* S1/S5b
outcomes, and each burn is produced by the real
discard-the-pair path, not by patching): burn primary (discard
pair) → recovery 1 consumes (discard pair) → recovery 2
consumes (discard pair) → recovery 3: authorise refuses
`ceremony_recovery_unproven` (head at depth cap); even with a
hand-built envelope, consume refuses via the predicate.
Expected terminal behaviour: movement dead, pin unmoved
throughout, and the NEXT state sequence pins normally (advance
or ceremony for the new movement succeeds) — the liveness-
resumes assertion that justifies the cap. Also pin the
adopted-target guard: if recovery 2's pair is instead adopted,
a further `burned_unadopted` attempt against the adopted target
is refused by history (`already a ceremonied target`) and by
the pin-binding in `PinStore.adopt` — the cycle-22 "worst case
is a redundant re-consumption of the identical target" becomes,
under WS3, "worst case is a bounded, lineage-visible
re-consumption", and the test asserts the bound is what stops
it, not luck.

**S7 — Concurrent adopter instances on one pin store.**
Injection: two subprocesses run `snapshot_and_adopt()`
simultaneously against the same pin store + WS2 home, released
by a barrier file. Outcomes are nondeterministic in *which*
process wins, so assertions are over the disjunction, never a
chosen winner: exactly one pin-store document exists and
verifies; its history has no fork and no duplicate target;
consumptions in the verifier journal are exactly those the
winner(s) legitimately made (genesis race: both may authorise,
at most… the consumption head serialises them — the loser of a
genesis race consumes only if its candidate equals the head
target, which a distinct fresh signing prevents, so assert
consumptions ≤ 2 and every consumption's target == the adopted
pin target or the retained-candidate target); the loser exits
with `PinStoreBusy`, `PinMovedError`-derived
`PinAdoptionRefused`/`Burned`, or `already_current` — never an
unhandled traceback, never a torn store (parent re-opens the
store with `read_all` after both exit; a torn write would fail
verification there). A second, deterministic variant runs the
two adopters sequentially interleaved at the `PinStore.adopt`
level (subprocess A captures pin, B adopts, A adopts with stale
`expected_old_pin` ⇒ `PinMovedError`, nothing written by A).

### 4.2 WS4 claim wording

- **May claim:** "Crash/restart behaviour across the
  consumption-journal / pending-journal / side-file / pin-store
  boundary is covered by subprocess and state-surgery tests for
  the seven named scenarios, with pinned refusal-vs-recovery
  outcomes."
- **May NOT claim:** power-loss durability (no fsync semantics
  are re-proven here; the tests inherit the writers' existing
  fsync discipline and inject process death, not machine
  death); that pending-journal loss is recoverable automatically
  (it degrades to refusal, §S2 — detection depends on an
  unanchored local journal, cycle 22's F4.2 residual, still
  open); seam tests as crash tests (§4.0).

### 4.3 WS4 file/function changes and tests

- No production-code changes required by this design. (If S2/S3
  expose an exception escaping `_read_journal`, that is a bug
  fix to report, not a design change: the documented semantics
  already promise tolerant reads.)
- New `tests/test_cycle23_crash_restart.py`: S1–S7 as above,
  subprocess helpers shared with the WS2 harness
  (`tests/test_cycle23_production_e2e.py`'s provisioning
  function, imported — one harness rule from §2.7), child driver
  under `tests/fixtures/` (a small script driving
  `reanchor_pin`/`PinAdopter` from env-named dirs, in the style
  of the existing crash-lab fixtures in
  `tests/test_trust_crashlab.py`, whose patterns the build
  should follow rather than reinvent).
- Existing seam tests in `tests/test_trust_pin_adoption.py` are
  renamed/relabelled only if the build touches them; otherwise
  the build record lists which existing tests are seam-level so
  the WS4 claim (§4.2) rests on the new file alone.

---

## WS5 — Ledger-head-anchoring completion

### 5.1 Current state, exactly

`trust/anchoring.py` already supports kinds `signing`, `ship`,
`ship-tx`, `ceremony-consumption`. `record_ship`
(`trust/shipcheck.py`) **requires** a caller-supplied
`expected_ledger_head` and, when `anchor_path` is passed,
additionally verifies the ship anchor pre-burn and updates it
post-finalise. `recover_ship_tx` takes `anchor_path` /
`tx_anchor_path` optionally and never advances either anchor.
`record_ship` never touches the ship-tx anchor at all, even
though it writes the tx journal on every attempt. And no anchor
files exist for the repo's own `state/ship-ledger/` (ship: 4
entries, head seq 4; ship-tx: 6 entries, head seq 6). The
backlog item's wording is the spec: "detectable **without a
caller-supplied pin**" — today the sanctioned path's rollback
detection rests on exactly such a pin.

### 5.2 (a) Anchor-derived head pinning on the sanctioned path

Change to `trust/shipcheck.py:record_ship`:

- New keyword `tx_anchor_path=None`.
- When `anchor_path` is provided, the expected ship-ledger head
  is **derived from the anchor file** — the caller's value stops
  being evidence. One subtlety drives the exact rule:
  `check_ship` compares `expected_ledger_head` against the
  ledger's *current* head, while `verify_anchor` alone accepts
  an anchor naming any *prefix* (a stale anchor is valid but not
  current). Derivation therefore requires currency:
  1. `anchor_path` provided ⇒ `verify_anchor(ledger,
     anchor_path, kind="ship")` must return `()` (existing
     behaviour, kept, pre-burn).
  2. **The anchor must be current at ship time** (new
     strictness): `anchor.seq == len(ledger.entries())` and
     `anchor.head == ledger.head()`, else refuse pre-burn with
     `ShipRefused("ship ledger anchor is stale: …")`. A stale
     anchor means the ledger grew without its anchor update —
     either a forgotten update (an operator runs `update_anchor`
     as a deliberate, visible act if the growth is legitimate)
     or a rollback-and-regrow; the ship path does not guess
     which. Effective `expected_ledger_head = anchor.head`,
     passed to `check_ship` in place of any caller value.
  3. A caller-supplied `expected_ledger_head` alongside
     `anchor_path` is **cross-checked**: supplied and unequal to
     the anchor's head ⇒ refuse pre-burn (`ShipRefused`);
     supplied and equal ⇒ it adds nothing, and the build record
     notes the redundancy. With an anchor present, a
     caller-supplied head is never the *source* of the
     expectation.
- When `anchor_path` is absent, current behaviour is preserved
  (caller-supplied head required) for back-compat with existing
  tests and callers — but `record_ship`'s docstring marks that
  form **legacy/unanchored**: it detects rollback only against
  a head the caller obtained out-of-band, and the backlog item
  is completed by the anchored form becoming the sanctioned
  one. Rejected alternative: refuse unanchored `record_ship`
  outright this cycle. It would break every existing shipcheck
  test's call shape and, more importantly, conflate "the item
  is complete" with "the old form is deleted" — the item asks
  for detection without a caller pin to *exist* on the
  sanctioned path, and §5.4's proof uses it; deletion is a
  later cleanup once all callers are anchored.
- `tx_anchor_path`, when provided: verified pre-burn against
  the tx journal (`kind="ship-tx"`, same current-at-ship
  strictness), and **updated after the COMMITTED transition**
  (and after the ship anchor update), closing the gap where
  `record_ship` writes a journal it never anchors. Anchor
  update failure post-commit raises `ShipRefused` naming the
  recorded cycle, mirroring the existing ship-anchor failure
  wording — the cycle stands, the anchor lag is the anomaly.
  When absent: no tx verification/update (today's behaviour),
  docstring-noted.

`check_ship` itself is unchanged (it stays a pure check whose
head parameter means "the head the caller audited against" —
derivation is `record_ship`'s job, as the release/ledger checks
already are).

### 5.3 (b) Initialise + verify anchors for the real `state/ship-ledger`

- Location: `state/anchors/ship.anchor.json` and
  `state/anchors/ship-tx.anchor.json`. Placement analysis:
  `trust/anchoring.py` refuses an anchor inside the journal's
  own directory (`state/ship-ledger/`) — `state/anchors/` is
  outside it, satisfying the module. Honest scope, stated
  wherever the anchors are described: on this VM the anchors
  live in the same repo and the same writable storage as the
  ledgers. They detect rollback/deletion by any process that
  rewrites the ledger but not the anchors (the realistic
  in-repo accident/bug class, and the class the backlog item
  names — "outside writable storage" is the item's aspiration;
  this cycle delivers outside-the-ledger-directory, git-
  committed, and says so). Off-machine anchor storage is a
  deployment act and remains out of scope, exactly as with the
  verifier anchors. Rejected: anchors beside `state.json` in
  `state/` root — same trust properties, worse discoverability;
  a dedicated `state/anchors/` dir names the pattern for the
  signing anchor when it joins them.
- Initialisation: `initialise_anchor(ledger, path, kind="ship",
  recorded_at=<now>, allow_nonempty_ceremony=True)` and the
  `ship-tx` twin — the established-ledger ceremony flag, because
  both ledgers are non-empty (seq 4 and 6). This is an operator
  act asserting the current histories are the true ones; the
  assertion's audit trail is (i) this design, (ii) the cycle 23
  build record naming the exact heads pinned, and (iii) the git
  commit adding the anchor files (the repo's history is the
  audit chain `initialise_anchor` itself does not keep — the
  build record must say that `force_reanchor`'s audit file is
  NOT created by initialisation, so nobody later mistakes its
  absence for evidence no re-pin happened; if a re-pin ever
  does happen, `verify_reanchor_audit` discipline applies from
  then on).
- Verification: `verify_anchor(...) == ()` for both, asserted in
  a test that runs against the real files
  (`tests/test_cycle23_ship_anchors.py`, read-only against
  `state/`) and in the build record. The test is a tripwire: any
  future ledger append that forgets its anchor update leaves
  the anchor a stale-but-valid prefix (verify still `()`), so
  the test additionally asserts `anchor.seq == len(entries)` —
  currency, not just validity — for the real files. That
  currency assertion is what makes a forgotten update fail the
  suite instead of passing silently.

### 5.4 (c) End-to-end proof in the WS1 sandbox

In the WS1 sandbox (which already copies `state/ship-ledger/`):
initialise sandbox ship + ship-tx anchors (same ceremony, on
the copies) → build a manifest + release + signed ship decision
for the sandbox's next cycle using the existing shipcheck test
machinery (`tests/test_trust_shipcheck.py` fixtures — manifest
over a temp tree, the item being the sandbox loop's actual
`pick_next()`, which on the copied backlog is
`ledger-head-anchoring` itself) → `record_ship(...,
anchor_path=<sandbox ship anchor>, tx_anchor_path=<sandbox
tx anchor>)` with **no** `expected_ledger_head` argument →
assert: cycle recorded in the sandbox loop, burn + finalise in
the sandbox ship ledger, tx at COMMITTED, both anchors advanced
to the new heads. Then the rollback proof: restore the sandbox
`ship-ledger.json` from its pre-ship copy (anchor files left at
the advanced heads) → a second `record_ship` attempt refuses
pre-burn with the anchor reasons (`anchor_ahead_of_journal` /
`anchor_head_not_in_chain` per the exact truncation) and the tx
journal shows no new transaction — nothing burned, nothing
recorded. Also assert the cross-check refusal: `record_ship`
with `anchor_path` AND a deliberately wrong
`expected_ledger_head` refuses pre-burn.

Note the interplay the proof must respect: `record_ship` calls
`loop.run_one_cycle` — the loop it receives must be the
hookless one (§1.3 rule 1), and the sandbox's pin flow (§1.5)
uses its own hooked loop over the same state dir sequentially,
never concurrently. The sandbox script orders them: WS1 pin
sequence first, WS5 ship proof second, each opening fresh
`CoreLoop` instances over the sandbox state as it then stands.
(If the ship proof's recorded cycle changes `cycle_seq` after
the pin sequence, the pin is one behind — the proof asserts
exactly that lag rather than hiding it, and a final
`snapshot_and_adopt()` dense-advance closes it, re-exercising
§1.5 step 2's path. The build may simplify by running the ship
proof in its own sandbox copy; the design's requirement is the
assertions, not the sharing.)

### 5.5 (d) Should the REAL `state/state.json` advance this cycle? NO.

Recommendation: **initialise the real anchors (§5.3); do not
record anything in the real loop this cycle.** Reasoning:

1. **The history would lie.** Loop history is a sequence:
   `cycle_seq` 14 is the next entry, and its `item_id` would be
   `ledger-head-anchoring` (the pickable item). But cycles 14,
   15, 16 *happened* — they were built, reviewed, and are HELD
   pending external re-review. Recording cycle 23's item as
   loop cycle 14 does not merely skip them; it asserts in the
   project's own signed-state lineage that the 14th recorded
   cycle was ledger-head-anchoring, and leaves 14–16's builds
   permanently unrecordable in order (their items are not the
   pickable ones, and `record_ship` refuses a mismatched item).
   A state file that cannot represent what happened is worse
   than a state file that is behind.
2. **The standing practice is explicit and recent.**
   BUILD-CYCLE-14's recording-status section set the pattern:
   loop state is not advanced by a build run; recording waits
   for the signed ship path in the main flow, and cycles 14–22
   have all followed it. Cycle 23 breaking the pattern for its
   own item — the one item whose completion is *about* the
   recording machinery — would be self-dealing in appearance
   and in fact.
3. **The external gate is unreconciled.** CROSS-CHECK-16 leaves
   item (3) open in unqualified form and 14–16 HELD. Recording
   is a ship-shaped act; doing it for cycle 23 while the seats
   are split on the precondition cycles inverts the order the
   seats imposed (integration first, then re-review, then
   recording catches up in order).
4. **Nothing is blocked by waiting.** §5.3's anchor
   initialisation — the part that makes future rollback
   *detectable* — does not require recording. When external
   reconciliation lands, the catch-up recording of 14, 15, 16,
   … in order becomes a defined procedure (each through
   `record_ship` with anchor-derived pinning, anchors advancing
   per §5.2), and cycle 23's own item is recorded when its turn
   in that sequence comes. The build record should state this
   expected order so the future procedure is not re-invented.

What the build record may say: "ledger-head-anchoring is
*built and proven* (anchor-derived pinning on the sanctioned
path; real ledgers anchored and currency-tested); its loop
recording awaits the ordered catch-up after external
reconciliation, like cycles 14–22 before it." The backlog item
stays `pending` in real state — as it has while being built
since cycle 14, per that cycle's own honest note.

### 5.6 WS5 claim wording

- **May claim:** "Ship and ship-tx ledger heads are anchored
  outside their ledger directory; the sanctioned ship path
  derives its expected head from the anchor (a caller-supplied
  head is cross-checked, never authoritative, when an anchor is
  present); rollback of the ship ledger is detected pre-burn in
  an end-to-end sandbox proof; the real ledgers' anchors are
  initialised, verified, and currency-tested."
- **May NOT claim:** rollback protection against an actor who
  can rewrite `state/anchors/` as well as the ledgers (same
  repo, same storage — §5.3's scope); that the unanchored
  `record_ship` form is gone (it is legacy, preserved, §5.2);
  that cycle 23 (or any of 14–22) is recorded in loop state
  (§5.5).

### 5.7 WS5 file/function changes and tests

- `trust/shipcheck.py`: `record_ship` — `tx_anchor_path`
  keyword; anchor-currency strictness + head derivation +
  caller-head cross-check when `anchor_path` is present;
  tx-anchor verify/update; docstring updates (sanctioned =
  anchored form; legacy form marked). `check_ship` unchanged.
  `recover_ship_tx` unchanged.
- New real files: `state/anchors/ship.anchor.json`,
  `state/anchors/ship-tx.anchor.json` (operator ceremony, §5.3).
- New `tests/test_cycle23_ship_anchors.py`: real-file verify +
  currency tripwire (read-only).
- `tests/test_trust_shipcheck.py`: new cases — anchor-derived
  head accepted with no caller head; wrong caller head +
  anchor ⇒ pre-burn refusal, nothing burned; stale anchor ⇒
  pre-burn refusal; tx anchor advanced on commit; tx anchor
  mismatch ⇒ refusal; legacy form (no anchor, caller head)
  still works (back-compat pin).
- WS5 sandbox proof lives in
  `tests/test_cycle23_live_run.py` (§1.7) as its second half or
  a sibling test using the same copied-state fixture.

---

## 6. Consolidated build order and dependency notes

1. **WS3 first** (schema + predicate + re-ruling): WS4's S5/S6
   assertions and WS1's live-run lineage assertions are written
   against v2 semantics; building them against one-shot and
   re-pinning later wastes the war room's time.
2. **WS2 harness second**: WS1's recorded live run and WS4's
   subprocess tests both consume its provisioning helper.
3. **WS1 hook + live run third** (depends on 1, 2).
4. **WS5 code (5.2) then sandbox proof then real anchor
   ceremony (5.3) last**: the real anchors should be
   initialised by the *final* code, and the currency tripwire
   test lands in the same commit as the anchor files so the
   suite is never green-with-stale-anchors by accident.
5. External brief for cycle 23 must put three rulings to the
   seats explicitly: the WS3 bounded-chain re-ruling (against
   GPT's ratified one-shot — the brief must quote Addendum 2 and
   its supersession, not summarise it away), the WS1 hook as the
   answer to "loop does not call it", and the WS5 §5.5
   no-recording recommendation. Cycles 14–16 are not in the
   brief as a question this cycle.

## 7. Global failure-mode summary (what this design most fears)

- A v2 load path that normalises v1 entries in memory and
  bricks journals on the next save (§3.2's named trap).
- A live run cited beyond its mode: research-mode execution
  wearing production wording (§1.5, §2.6).
- Hook + `record_ship` double-wiring stranding a ship
  transaction (§1.3) — mitigated by convention + lint, and the
  mitigation's weakness is stated, not hidden.
- Seam tests cited as crash tests (§4.0).
- Anchor initialisation for the real ledgers performed
  *before* §5.2 lands, leaving the currency tripwire asserting
  against code that cannot advance the tx anchor — build order
  §6.4 exists to prevent exactly this.
- The bounded-chain re-ruling being read as a minor tweak: it
  reverses a war-room ruling that one external seat ratified.
  The design makes it deliberately, on Gemini's liveness
  argument plus WS4's crash evidence, and flags it for
  re-ratification instead of burying it in a schema change.
