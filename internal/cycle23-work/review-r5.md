# Cycle 23 — War-room review, seat rev-r5 (BLIND)

Lens: WS4 crash-coverage quality + wording sweep.
Baseline 59a656a, working tree (cycle 23 uncommitted) as reviewed.
I did not read other reviewers' cycle-23 notes.

**Verdict: FIX — 0.78**

The crash engineering is genuinely strong: scenarios 1 and 7 are
real subprocess/SIGKILL tests with a sound synchronisation proof,
the seam/surgery classes are honestly labelled, and the live-run
test drives the exact R1 sequence and cannot pass with a dead
hook. What blocks SHIP is the wording/record layer this cycle was
explicitly charged with cleaning up: the adopter's own module
docstring still carries cycle 22's "No live run" claim, the
decision file still ends at the one-shot Addendum 2 while the code
cites a non-existent "Addendum 3", the deploy README's recovery
paragraph predates bounded recovery, and one production rule the
scenario-6 pin now depends on (check_head supersede) is in
neither DESIGN-FINAL R3 nor R4 and is described in its docstring
more narrowly than the code enforces. All fixes are small; none
requires redesign.

Tests I ran: `tests.test_trust_pin_adoption_crash` +
`tests.test_cycle23_live_run` — 12 tests OK; `tests.test_core_loop_hook`
— 11 tests OK.

---

## (1) Scenarios 1 and 7 — true subprocess / SIGKILL? YES, with one caveat each

### How the parent KNOWS the commit landed before SIGKILL (scenario 1)

The synchronisation is sound, and it is structural, not timing-based:

- The child's `dying_adopt` (`tests/cycle23_crash_child.py`,
  `_mode_burn`) wraps `PinStore.adopt`. In production order
  (`PinAdopter._reanchor`, trust/pin_adoption.py) `store.adopt` is
  step (5); step (4) is `reanchor_pin(...)`, inside which
  `consume_authorisation(authorisation)` is invoked
  (signing/pin_ceremony.py, in `reanchor_pin`) — i.e. the verifier's
  consumption commit completes *before* `reanchor_pin` returns the
  (pin, record) pair, and only then can `adopt` be called at all.
- `dying_adopt` fires only when `record is not None` (the ceremony
  path; the dense advance path passes `record=None` through to the
  real adopt), writes the pair file if configured, touches the
  `consumed` barrier, then sleeps forever. The barrier therefore
  cannot exist before the consumption commit: there is no other
  code path in the child that touches it.
- The parent (`test_scenario1_*`) waits for the barrier, asserts
  `proc.poll() is None` (child still alive, parked inside adopt),
  then `proc.kill()` (SIGKILL), then — critically — asserts the
  *post-kill state*, not just the barrier: consumption count is 2
  and the pin is still at seq 1 with history length 1.

Could it pass vacuously if the barrier raced? No. If the barrier
somehow appeared early (it cannot, per above), the post-kill
assertions on the verifier-owned consumption journal and the pin
store would fail, because both are read from the persistent
parties after the kill. If the child died before consuming, the
barrier never appears and `wait_barrier` fails the test after its
timeout. The kill is also genuinely a kill: the child is parked in
`time.sleep(60)` inside the adopt wrapper, so SIGKILL lands with
no cleanup, no finally, and no adopt — exactly the R4 death.

Caveat (minor): the barrier name `consumed` is slightly
over-specific in one respect — by the time it fires, the adopter
has also appended its own journal `consumed` line (step (5)
precedes `store.adopt` in `_reanchor`). That does not weaken the
test (the verifier commit is what R4 pins, and it strictly
precedes both), but the record should describe the death point as
"after verifier consumption commit and the adopter's consumed
journal line, before PinStore.adopt persists" rather than the
looser "post-consume / pre-adopt".

### Scenario 7 — true subprocess, barrier-synchronised; no SIGKILL (correctly)

Two `Popen` children in `race` mode each wrap `store.adopt` with
an announce-and-wait barrier (`at-adopt-<pid>`, wait until 2), so
both have captured the same old pin and reach the store's flock
CAS concurrently; both then run to completion and write outcome
files. SIGKILL is not used — correctly, since the datum is the
loser's surfaced refusal, which a kill would destroy. DESIGN-FINAL
R4's "(child process, barrier, SIGKILL)" parenthesis should be
read as applying the kill to the death case; the record should
say so explicitly so nobody later cites scenario 7 as a kill test
or faults it for lacking one.

Vacuity check: if one racer never reached adopt, the other would
hit the 120 s barrier timeout, surface `TimeoutError` as its
exception class, and the parent's exact partition assertion
(one `advanced`, one `exception == "PinAdoptionRefused"`) would
fail. The parent also re-reads and verifies the store afterwards
(pin seq 2, history 1, consumption count 1). Sound.

One weakening (F5, low): the loser assertion checks only the
exception *class name* `PinAdoptionRefused`, not that the refusal
wraps `PinStoreBusy`/`PinMovedError` specifically. R4's wording —
"the loser surfaces PinStoreBusy/PinMovedError as a refusal" —
is therefore pinned at the adopter-surface level, not at the
store-cause level. On the advance path any `PinStoreError` maps
to `PinAdoptionRefused`, so a loser refusing for a different
store reason would pass. Acceptable, but the record must not
claim the busy/moved cause itself was distinguished.

## (2) *SeamTests / surgery labelling — HONEST

- Module docstring of test_trust_pin_adoption_crash.py states the
  method rules up front: 1 and 7 are true subprocess; 2–4 are
  "STATE SURGERY … not crash coverage"; 5–6 "live in a *SeamTests
  class; they pin recovery semantics, not crash coverage."
- Class names match: `CrashSubprocessTests`,
  `CrashStateSurgeryTests` (docstring repeats "not crash
  coverage"), `RecoverySeamTests` (docstring repeats "may not be
  cited as crash coverage — scenario 1 above is the crash form
  of the same deaths").
- The child helper is named non-collected (`cycle23_crash_child.py`)
  and its docstring says the wrappers "interpose on timing, never
  on verdicts".
- No production fault seams were added: the only cycle-23
  production change in pin_adoption.py is the R4
  `authorise_pending` journal line (verified in the diff).

Condition for the record: BUILD-CYCLE-23 must preserve this
labelling when it summarises WS4 — citing scenarios 5–6 as
"recovery-semantics pins (seam)" and 2–4 as "state surgery", with
crash coverage claimed for 1 and 7 only. As of this review no
BUILD-CYCLE-23 exists, so there is nothing yet to fault, but
also nothing yet that carries the claim correctly (see F2).

## (3) Scenario outcomes — do they pin the R4 outcome or a lookalike?

Scenario-by-scenario:

- **1 retained pair — PINNED, strong.** Post-kill: consumptions 2,
  pin seq 1. Restart is a *fresh process* (`adopt-returned` child):
  outcome reanchored, pin_seq 3, consumptions still 2 (no new
  consumption), pin seq 3, history 2. State-after, not just types.
- **1 discarded pair — PINNED, strong.** Fresh adopter recovers
  with `record.reason == "burned_unadopted"`, exactly one new
  consumption whose entry is `consumption_kind == "recovery"`,
  `recovery_depth == 1`, pin seq 3, and `lost_pin` asserted absent
  from all history reasons.
- **2 torn tail — PINNED.** Torn `authorised` tail is skipped by
  the journal reader; restart reports `already_current`, then a
  dense advance lands; consumption count stays 1 throughout.
- **2 authorise_pending pin — PINNED, but note the division of
  labour.** The behavioural test fabricates an `authorise_pending`
  line with a *dummy* candidate hash (`"0"*64`), then asserts the
  next gap attempt lands as a fresh primary: outcome reanchored,
  `reason == "chain_gap_recovery"` (not burned_unadopted),
  consumptions 2. On its own this would be a weak pin — a pending
  line wrongly counted as a burn would still miss
  `_find_unadopted_burn` on the hash mismatch and proceed primary.
  The load-bearing pin is the companion unit test in
  tests/test_core_loop_hook.py (`test_authorise_pending_alone_is_not_a_burn`),
  which asserts `_unadopted_burns() == []` for a pending-only
  journal directly, hash-independently. Together they pin the R4
  rule; the crash file alone does not. The record should cite
  both, and ideally the fabricated line should carry the *real*
  candidate hash so the behavioural test stands alone.
- **3 mid-file corruption — PINNED (both halves).** Garbage at
  line 0: detection lost, behaviour degrades to
  already_current/advance only, consumptions stay 1. Corrupting
  the `authorised` line of a real unadopted burn: next attempt
  raises PinAdoptionBurned, pin stays seq 1, history 1,
  consumptions stay 2 — refusal, never unsafe movement; F4.2's
  "detection can be lost; burn validity cannot" is exactly what
  is asserted.
- **4 side-file loss — PINNED in substance, one explicit assertion
  missing (F4, low).** Asserts `PinAdoptionRefused` on unchanged
  state, pin still seq 2, consumptions still 1 (so no ceremony —
  hence no lost_pin ceremony — could have run), then the next
  cycle unfreezes via advance to seq 3. This pins the R4 outcome
  ("PinAdoptionRefused … NOT a lost_pin ceremony") by the
  consumption count, but unlike scenarios 1-discarded and
  5-discarded it never asserts `"lost_pin" not in history reasons`
  or that history length is unchanged (the history tuple is
  discarded unread). One-line fix; do it for symmetry so the
  record can quote the assertion rather than an inference.
- **5 pair available vs discarded — PINNED, strong.** Available:
  `adopt_returned` lands with consumptions unchanged at 2, and
  the store's pin/history are asserted *equal to the returned
  pair objects*. Discarded: burned_unadopted recovery, exactly
  one new consumption at depth 1, no lost_pin anywhere.
- **6 cap-2 chain — PINNED, with two qualifications.**
  (a) The movement's entries are asserted as the exact list
  `[("primary",0), ("recovery",1), ("recovery",2)]` — the R3/R4
  semantics, not a lookalike. The terminal attempt is asserted
  only as `assertRaises((PinAdoptionRefused, PinAdoptionBurned))`
  plus no-new-consumption and pin-unmoved: a disjunction that
  could in principle pass via an unrelated refusal. R4 allows
  either surface (authorise's ceremony_recovery_unproven →
  Refused, or consume's AlreadyConsumed → Burned), so the
  disjunction is defensible, but it is the weakest assertion in
  the file and the record should not quote it as pinning a
  specific refusal.
  (b) **F3 (medium): the liveness half of scenario 6 now depends
  on a production rule that is in neither R3 nor R4** — the
  `check_head` "supersede" exception in trust/ledger.py (a fresh
  primary whose candidate is strictly ahead of the head may pass
  a behind-head old pin), introduced by the fix seat after the
  original scenario recorded a deadlock. R4 scenario 6 does pin
  the *outcome* ("liveness resumes at the next snapshot sequence
  via primary chain_gap_recovery", including the discarded-pair
  path), so the fix serves the contract; but R3 specified the
  head rules exhaustively and R4 authorised exactly ONE
  production change (the authorise_pending line, in
  pin_adoption.py). A verifier-side relaxation of
  `check_head` is a second, unruled production change and must
  be explicitly ratified in BUILD-CYCLE-23 / the war-room record
  — including its docstring discrepancy: ledger.py's supersede
  paragraph (line ~1029) describes "a NON-recovery consumption",
  but the code path does not test the envelope's reason — it
  tests only candidate position (`cand_seq <= head_seq` refuses;
  otherwise pass), with lineage derivation separately labelling a
  binding-mismatched `burned_unadopted` envelope as
  primary-shaped. Either narrow the code to the docstring or
  rewrite the docstring to what is enforced, and argue the
  mismatched-recovery case explicitly.
- **7 concurrent adopters — PINNED** (see §1; cause-level caveat F5).

Journal merge logic (asked for explicitly): `_journal_ceremonies`
merges per ceremony_id with later lines overriding per-field
except that a field a later line omits survives — which is what
lets `candidate_envelope` (carried only on the `authorised` line)
survive the later `consumed`/`adopted` lines. `_unadopted_burns`
counts only phases ∩ {authorised, consumed} and excludes
adopted — so the new `authorise_pending` line neither creates a
burn nor, when merged into a ceremony that later authorises,
erases the envelope. The scenario-2/3 tests exercise the merge
end-to-end (torn tail, mid-file garbage, corrupted authorised
line) and the phase-set semantics are unit-pinned in
test_core_loop_hook.py. Correct as built.

## (4) Live-run test — drives the real R1 sequence; cannot pass with a dead hook

tests/test_cycle23_live_run.py, verified line by line against R1:

- Byte copy: `shutil.copytree(REAL_STATE_DIR, sandbox)`; probe
  asserts the copy starts at cycle_seq 13; pin store starts empty.
- Production home: `provision_production_home`
  (tests/cycle23_harness.py) — research-mode INIT invocation with
  all INIT flags, INIT keys then removed, mode flipped to
  production, full allowlist env; a *fresh* snapshot signing key
  is generated in the harness. The adopter is built via
  `build_pin_adopter` → `production_client` (the R2 composition).
- Sequence asserted exactly: (1) genesis `initial_anchor` at 13,
  consumptions 1; (2) one HOOKED cycle — expected item taken from
  `pick_next()` on the copy *before* the cycle and asserted equal
  to the recorded entry's item_id (asserted, not assumed, per R1),
  entry cycle_id 14, pin advanced to 14, history still 1,
  consumptions still 1 (dense advance, no consumption);
  (3) two hookless cycles to 15, 16, pin still 14, consumptions 1;
  (4) `chain_gap_recovery` with old 14 / new 16 / gap 15–15
  asserted on the record, consumptions 2; (5) `already_current`,
  record None, consumptions 2.
- Real-state hash: sha256 of the REAL `state/state.json` asserted
  identical before/after — exactly the R1 requirement (state.json
  only; the test does not hash the whole real tree, and R1 does
  not ask it to).

Could it pass if the hook never fired? **No.** After the hooked
cycle it asserts the pin is at seq 14; an unfired hook leaves the
pin at 13 and the test fails. It also asserts
`hooked.cycle_hook is not None` before running. The one thing it
does not assert is that the hook fired *exactly once* (a
double-fire on the dense path would be idempotent —
already_current/advance-to-same — and invisible here); exactly-once
is pinned in test_core_loop_hook.py, which is the right home for
it, but the record should cite that pairing rather than claiming
the live run alone proves exactly-once.

## (5) Wording sweep — stale / over-claiming passages

Searched the whole tree for "one-shot", "ONE-SHOT", "no live run",
"zero production callers", "not been run live" across code
docstrings, trust/README.md, deploy READMEs and docs/. Historical
records (BUILD-CYCLE-*, REVIEW-CYCLE-*, cycle-22 work files,
CROSS-CHECK briefs, DECISION Addendum 2) state one-shot / no-live-run
as *history* and must NOT be rewritten. The unrelated "one-shot
permit" in signing/gate_decision.py / memory/store.py is the
signed-commit permit — a different mechanism, not stale, not to
be touched. In current production code, trust/ledger.py's one-shot
mentions are correctly framed as superseded ("BOUNDED, not
one-shot"; "superseding the cycle-22 one-shot rule"). What remains:

### F1 (medium — must fix before ship): the adopter still claims no live run

`trust/pin_adoption.py:45-48` (module docstring, "Honest scope"):

> "this is production code exercised end-to-end in temp dirs
> against the real verifier subprocess. No live run against the
> live state dir happens here; the first live adoption is an
> ``initial_anchor`` ceremony gated on verifier provisioning
> (design C §4)."

This was cycle 22's claim and cycle 23 exists to retire it. The
live run has now happened — against a byte copy of the real
state, in a sandbox, under a production-mode home. Corrected
wording the record/docstring should carry:

> "Honest scope: production code exercised end-to-end in temp
> dirs against the real verifier subprocess, and, since cycle 23,
> in a live run against a byte copy of the real state/ directory
> (seq 13 → 16, two consumptions) in a sandbox under a
> production-mode verifier home. The real state/ directory itself
> has never been adopted against and is not advanced by any of
> this; there is no production deployment (no separate OS user;
> the wrapper launch is refused by design)."

### F2 (medium — record incomplete): Addendum 3 does not exist; BUILD-CYCLE-23 does not exist

`internal/DECISION-CONSUMPTION-HEAD.md` still ends at Addendum 2
(line 151: "recovery is one-shot"), which reads as the current
ruling to anyone who opens the decision file. The new code
honestly hedges — trust/ledger.py lines 648, 817, 981 cite
"Addendum 3, pending" — but DESIGN-FINAL R3 says Addendum 3
*records* the re-rule, and it has not been written. Until it is,
the tree's most authoritative decision document contradicts its
code. Fix: write Addendum 3 (schema v2 lineage, cap
MAX_RECOVERY_DEPTH = 2, issuance-bound recovery_of, supersession
of Addendum 2, external ratification still split/pending — GPT
ratified one-shot, Gemini demanded the schema) and BUILD-CYCLE-23
carrying the WS4 labelling conditions in §2 above.

### F6 (low): deploy README's recovery paragraph predates bounded recovery

`deploy/verifier-identity/README.md:286-296` ("Burned-but-unmoved
recovery", headed "Ceremony consumption (cycle 21)" + cycle-22
anchor paragraph) describes the burned_unadopted recovery with no
mention that, since cycle 23, a recovery whose own adoption fails
may itself be recovered, bounded at depth 2 via schema-v2 lineage,
nor the movement-terminal outcome at the cap. Nothing it says is
false (it never claimed one-shot), but as the operator-facing
deployment document it is now incomplete on exactly the failure
mode an operator will meet. Add the bounded-recovery sentences
with the same claim discipline (cap 2; terminal movement;
liveness at the next sequence).

### F7 (low): trust/README.md and docs/ say nothing about the adopter at all

No stale claim — an omission. trust/README.md's sanctioned-paths
list still ends at cycle-8-era paths and never mentions
PinAdopter, the cycle hook, or anchored_record_ship. Not a
ship-blocker for this cycle's claims (nothing there over-claims),
but the next reader will under-claim the system from its own
README. Recommend one sanctioned-path bullet in the fix round or
the record's follow-ups.

### The cycle-22 claim, restated accurately for cycle 23

Cycle 22's claim — "first production adopter built and wired as
specified; no live run" — was accurate then and stays as history.
The accurate cycle-23 claim is:

> The first production adopter is now integrated into the loop
> itself via a constructor-injected cycle hook
> (`CoreLoop(cycle_hook=pin_cycle_hook(adopter))`, with
> `record_ship` and `run_one_cycle_and_pin` refusing a hooked
> loop), composed end-to-end in production MODE through
> `production_client`/`build_pin_adopter` against a disposable
> verifier home, and exercised in a live run against a byte copy
> of the real state (genesis at seq 13, hooked advance to 14,
> gap recovery to 16; two consumptions; real state/state.json
> hash unchanged).

And its necessary qualifications, which the record must keep
attached: the only callers of `pin_cycle_hook`/`build_pin_adopter`
in the tree are tests — there is still **no non-test production
entry point** that constructs a hooked loop, so "zero production
callers" is dead as a claim about *wiring* (the wiring now lives
in production code, in core/loop.py) but a caller-count version
of the caveat survives and must not be silently dropped; the real
state directory was **not** advanced and no adoption has run
against it; and this proves production mode under same-user spawn
on this VM, **not** production deployment (28 deployment-gated
skips stay skipped). Any cycle-23 summary that says simply
"adopter wired and run live" without those three qualifiers
over-claims.

---

## Findings summary

- **F1 (medium)** trust/pin_adoption.py:45-48 — stale "No live
  run" honest-scope paragraph; corrected wording in §5.
- **F2 (medium)** DECISION-CONSUMPTION-HEAD.md — Addendum 3
  missing; decision file still presents one-shot as the ruling
  while code cites the addendum as pending. Write it (and
  BUILD-CYCLE-23 with the §2 labelling conditions).
- **F3 (medium)** trust/ledger.py check_head supersede — a
  verifier-side head-rule relaxation in neither R3 nor R4, now
  load-bearing for scenario 6's liveness pin; needs explicit
  war-room ratification in the record, and its "NON-recovery
  consumption" docstring does not match what the code tests
  (candidate position only).
- **F4 (low)** Scenario 4 — add the explicit
  `lost_pin`-absent / history-unchanged assertion (currently
  inferred from the consumption count).
- **F5 (low)** Scenario 7 — loser pinned as PinAdoptionRefused,
  not distinguished as PinStoreBusy vs PinMovedError; record
  must not claim the cause was distinguished.
- **F6 (low)** deploy/verifier-identity/README.md:286-296 —
  recovery paragraph predates bounded (cap-2) recovery.
- **F7 (low)** trust/README.md — no adopter/hook/anchored-path
  mention at all (omission, not over-claim).

Verified good, for the record: scenarios 1 & 7 are true
subprocess tests with non-vacuous synchronisation; seam/surgery
labelling is honest throughout; the authorise_pending production
change matches R4 exactly (journal merge + `_unadopted_burns`
phase semantics verified in code and pinned by tests); the
live-run test drives the full R1 sequence and fails if the hook
does not fire; ledger.py's one-shot wording is correctly
rewritten to bounded recovery.

**FIX, 0.78** — fix F1–F3 (wording/record/ratification only; no
redesign), F4–F7 may ride the same fix round.
