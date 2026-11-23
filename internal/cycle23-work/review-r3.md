# Cycle 23 — War-room review, seat rev-r3 (BLIND)

Lens: WS1 + WS5, and the Protected File question (`core/loop.py` ∈
Protected Gate `PROTECTED_FILES`). Baseline 59a656a, working-tree diff
read in full. Scope files read: DESIGN-FINAL (R1+R5), `core/loop.py`
diff + `run_one_cycle` body, `trust/pin_adoption.py`
(`pin_cycle_hook`, `run_one_cycle_and_pin`, `authorise_pending` line),
`trust/shipcheck.py` (`record_ship`, `anchored_record_ship`),
`trust/anchoring.py` (`verify_anchor`/`update_anchor` semantics),
`state/anchors/*.json` + `state/ship-ledger/` (verified independently,
below), `tests/test_core_loop_hook.py`,
`tests/test_cycle23_ship_anchors.py`.

**Verdict: SHIP — score 0.92**

Targeted suites run by this seat: `tests.test_core_loop_hook` +
`tests.test_cycle23_ship_anchors` — 17 tests, OK.

## (1) The loop diff — minimal, semantics preserved, exactly-once

The diff is 34 lines: docstrings, a keyword-only `cycle_hook=None`
parameter, a read-only property, and two lines of behaviour
(`if self._cycle_hook is not None: self._cycle_hook(copy.deepcopy(entry))`)
placed AFTER the persistence try/except. No new imports; loop stays
stdlib-only; the hook is opaque.

- **Hook = None ⇒ prior behaviour preserved.** The only new runtime
  effect is one attribute, the property, and a None-check that falls
  through to the identical `return copy.deepcopy(entry)`. All gates,
  the snapshot/restore path, pruning, and delta handling are untouched
  (verified line-by-line against the pre-diff body).
- **Deepcopy discipline is correct and actually improved in one
  respect:** the hook receives its OWN `copy.deepcopy(entry)`, distinct
  from the copy returned to the caller and from the object stored in
  `state["history"]`. A hook that mutates its argument can corrupt
  neither stored state nor the caller's return value.
- **Exception paths:** the hook call sits outside the try/except, so a
  hook failure does NOT trigger the snapshot restore — the cycle stays
  recorded on disk, the exception propagates unwrapped. This matches
  the stated contract ("cycle recorded, pin pending, alert") and is
  pinned by `test_hook_exception_propagates_and_cycle_stays_recorded`
  (fresh loop over the same dir sees cycle_seq 1).
- **Exactly once, all paths:** there is exactly one hook call site,
  reached only after a successful save. Idle (`pick_next()` → None)
  returns before it; gate refusals raise before it; a failed save
  raises through the except before it. History/deltas pruning happens
  inside the try, before the save, and the local `entry` reference
  survives pruning — a pruned cycle still fires exactly once with the
  correct entry. `scan`/`approve` never fire it. A caller retrying
  after a hook exception starts the NEXT cycle (state already
  persisted, phase back at SCAN), so no entry can be fired twice.

## (2) Protected-file justification — sound

`eval/gate.py`'s protection is an authorisation gate, not an
immutability proof: `check_protected_paths` flags protected paths in a
proposal's changed-path set so the gate decision/attestation must
carry them as `protected_violations` — i.e. the mechanism exists to
force exactly the explicit, reviewed acknowledgement this cycle
provides. DESIGN-FINAL names the touch, its reason, and mandates this
specific review of the loop diff; the change is a generic,
dependency-free integration seam (no trust/signing imports enter
loop.py — the protection's purpose, keeping oversight logic out of the
loop's unilateral reach, is not weakened: the loop gains no knowledge
of what the hook does). An agent self-modifying its oversight
unilaterally would be the violation; a three-design-seat,
coordinator-ruled, war-room-reviewed seam is the process the gate
exists to enforce. Justification accepted. (Note for the record: when
cycle 23 is eventually recorded, `core/loop.py` must appear in that
ship's changed paths and be carried as a protected violation in the
gate decision — R5's deferral of the real recording keeps that
obligation intact, not evaded.)

## (3) record_ship hooked-loop refusal — truly pre-side-effect

The refusal is the FIRST statement of `record_ship`, before the
`expected_ledger_head`/`release` checks, before `ShipTxJournal`
construction, before `tx_journal.begin(...)`, before any ledger read
or burn. It uses `getattr(loop, "cycle_hook", None)`, so duck-typed
hookless loops are unaffected. The test pins it with manifest/signed/
release = None (proving nothing downstream is touched): no
`ship-tx.json` created, ledger empty, loop history empty. The design
rationale is also correct on the merits: a hook failure inside
`run_one_cycle` (PinAdoptionBurned is a SigningError, not
InvalidTransition) would escape record_ship's InvalidTransition
handler and strand the tx at BURN_PENDING — refusing is the right
call over tolerate-and-recover.

## (4) anchored_record_ship — currency check and tx-anchor advance

- **Currency check correct.** For each journal it runs
  `verify_anchor` (prefix semantics) and THEN requires
  `anchor["head"] == journal.head()` and `anchor["seq"] ==
  len(journal.entries())` after `_reload()`. This closes exactly the
  stale-prefix trap `verify_anchor` deliberately permits, and the
  sandbox tests prove both sides: a stale-prefix ship anchor and a
  stale-prefix tx anchor each refuse with `*_anchor_not_current`,
  pre-burn, ledger and history unchanged.
- **Empty journal:** anchors at genesis (seq 0, GENESIS head) verify
  and ARE current (0 == len, genesis == head), so a first recording
  on fresh ledgers proceeds with expected head = genesis. Correct —
  genesis currency is not a false blessing, it names no history.
- **Anchor ahead:** `verify_anchor` returns
  `anchor_ahead_of_journal` → refused in the verify step, before the
  currency comparison. Correct.
- **Wrong ledger file:** kind is enforced by `verify_anchor`
  (`anchor_kind_mismatch`), so a swapped or same-path pair refuses;
  a same-kind anchor from a DIFFERENT ledger fails the prefix check
  (`anchor_head_not_in_chain`) for any non-empty journal, and for an
  empty journal the only transferable anchor is the universal genesis
  anchor, which pins nothing. No false derivation is possible.
- **Exactly-once tx advance, only after COMMITTED:** the wrapper
  calls `update_anchor(tx_journal, ...)` exactly once, only on
  record_ship's normal return — which happens only after the
  COMMITTED transition. `update_anchor` itself refuses a
  non-strictly-increasing seq, so a double advance cannot silently
  succeed. End-to-end test asserts both anchors current afterwards
  and the tx terminal at COMMITTED.
- **Tx-anchor update failure after commit:** honestly reported — the
  ShipRefused message states the cycle was recorded and the decision
  finalised, and names the anchor failure. The state is recoverable
  and fail-closed: the stale tx anchor makes the NEXT anchored
  attempt refuse at currency until an operator advances/re-pins the
  anchor (`update_anchor` will succeed against the valid prefix;
  `force_reanchor` is the audited fallback). No silent divergence.

  Minor observation (not a blocker): if record_ship's OWN ship-anchor
  `update_anchor` fails post-COMMITTED, record_ship raises and the
  wrapper never advances the tx anchor either — both anchors go stale
  together. The failure is still honestly messaged and currency-gated
  on the next attempt, and arguably fresher-together is the safer
  anomaly signal; recorded here so the behaviour is a known, not a
  surprise.

## (5) The real anchors — independently verified, tripwire can fail

Verified by this seat with a direct Python check against the real
files (not via the test): ship anchor seq 4 / head `6911dff4…`
verifies `()` and equals the real ship ledger's current head/length
(4 entries: burn, finalise, burn, finalise); ship-tx anchor seq 6 /
head `7679d7c1…` verifies `()` and equals the real tx journal's
current head/length (6 transitions, the single transaction
COMMITTED — the all-terminal precondition from the designs holds).
Both anchor files live outside the ledger dir, as anchoring requires.

The tripwire test is genuinely capable of failing: beyond
`verify_anchor == ()` (which a stale prefix would still pass), it
asserts head and seq EQUALITY with the live journals, plus anchor
file existence. A future recording that forgets an advance, a ledger
rollback, or a deleted anchor each trip a distinct assertion. It is
not a tautology.

## (6) Double-wiring — both compositions closed

`run_one_cycle_and_pin` refuses a hooked loop with ValueError as its
first statement, before any cycle runs (test pins: no cycle recorded,
no pin written). `record_ship` refuses a hooked loop pre-transaction,
and `anchored_record_ship` delegates to `record_ship`, inheriting the
refusal — there is no path by which a hooked loop reaches a burn.
The remaining compositions are single-wiring by construction: the
driver on an UNhooked loop (the documented legacy path), or the hook
alone. A manual `snapshot_and_adopt()` after a hooked cycle is not a
second wiring — adoption on an already-current pin is the adopter's
`already_current` no-op path, not a second burn.

## R4 spot-check (authorise_pending, in lens via pin_adoption)

The `authorise_pending` journal line is appended before the authorise
call, carries no envelope, and the test in test_core_loop_hook pins
that `_unadopted_burns()` ignores it — consistent with the program-
order argument (no authorised line ⇒ nothing could have consumed).
The relocation of `old_seq, old_hash = self._old_pin_projection(...)`
above the authorise call is behaviour-neutral (pure projection of the
already-read old pin).

## Residual notes

- TOCTOU between the wrapper's verify/load and record_ship is
  same-user/same-disk scope, identical to the scope R5 explicitly
  caps the real-anchor claim at; not a finding.
- The hook contract trusts the injected callable; a non-callable
  truthy hook raises TypeError post-save, which is contract-consistent
  (failure never un-records). No change requested.

**SHIP, 0.92.** The deduction is for the accumulated minor
observations (dual-stale-anchor path in (4), the standing obligation
in (2) that cycle 23's eventual recording must carry core/loop.py as
a protected violation) — neither blocks this cycle, whose own claim
is only that the path exists, is sandbox-proven, and the real heads
are anchored and tripwired. That claim is exactly met.
