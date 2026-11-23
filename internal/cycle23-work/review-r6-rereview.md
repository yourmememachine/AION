# Cycle 23 — rev-r6 (FORCED DISSENT) re-review of the fix round

Reviewer: rev-r6, dissent seat. Re-judged against the working tree
(fix round, uncommitted) and the coordinator's stated dispositions
for F1/F2. Verified in code: narrowed supersede + journal hash
binding in `trust/ledger.py::check_head` (docstring enumerates
residuals (i)/(ii)); F6(i) wrap in `trust/pin_adoption.py`;
`trust/verifier_main.py` consume threading (lines ~2790–2816);
cross-entry `_load` validation and `_derive_lineage` in
`trust/ledger.py`. Targeted re-run by this seat: schema-v2 +
ceremony consume + pin-adoption crash + pin ceremony = 130
tests, OK.

## VERDICT: SHIP — score 0.78 (was FIX 0.64)

This is an internal, provisional SHIP. It is explicitly
conditioned on the coordinator's records landing as stated
(see Preserved Dissent 1 — if they do not, this verdict is
void and FIX reinstates without a new review), and the cycle
remains provisional until both external seats answer, per the
standing external-seat rule.

---

## F1 — supersede: DISCHARGED via my own Required-#1, branch (ii), plus narrowing I did not demand

My first-round Required #1 offered two settlements: (i) narrow
to derived depth == MAX, or (ii) honestly re-rule the head as
verifier-monotonic-except-forward-supersede with non-regression
at `PinStore.adopt`, taken to a designed ruling + the external
seats as its own question. The coordinator took branch (ii),
and the fix round additionally narrowed the code in three ways
that remove the worst shapes I traced:

- `burned_unadopted` NEVER rides supersede and is never
  reclassified as primary (the `unrecoverable` path, below) —
  my objection 2 (the `lost_pin`/recovery reason conflation) is
  answered for the recovery reason, the dangerous one.
- A journal-known old-pin seq is now hash-bound in both journal
  roles (new seq and old seq): a fabricated old-pin hash at a
  recorded seq refuses. The unrecorded-seq case is named
  residual (i) in the docstring, with PinStore context binding
  named as its control — the docstring now says what the rule
  does not do, which is what I asked the record to do.
- Residual (ii) (resurfaced superseded pair stalls one sequence
  at AlreadyConsumedError, then self-heals) is enumerated, and
  my trace confirms the analysis: no regression, no replay.

**Concession, recorded against my own first round:** the
coordinator's rebuttal of branch (i) is correct, and my
depth == MAX proxy was flawed. Depth measures the head
movement's *recovery chain*, not whether its adoption pair was
retained — and pair retention is adopter-side state the
verifier cannot observe (my own F1 text conceded this). A
depth-0 head whose pair was discarded (journal corruption,
lost artefacts) is exactly the deadlock, and branch (i) would
re-brick it; a depth-MAX head with a retained pair is
adoptable and branch (i) would supersede it anyway. No
verifier-side depth condition separates the deadlock from the
abandonment case. The real choice was always broad-supersede
or no-supersede, and no-supersede leaves a proven, crash-suite-
traced permanent deadlock in a system whose adopter is now
wired live.

**Why the broad primary rule does not block:** its cost is
liveness/fairness, not safety. It cannot regress the pin
(candidate strictly ahead; PinStore CAS + non-regression —
verified in round 1), cannot replay (fresh single-use
envelope; at-head candidate checks untouched), cannot fork
(old pin AT head seq with a wrong hash still refuses at any
candidate position). What it can do is abandon a retained,
adoptable burn when a second authorised primary lands first —
an operator-authorised action, journal-recorded truthfully as
the movement that actually landed. That is a policy loss the
room is entitled to rule on, and branch (ii) is the honest
form of that ruling. The T8′ relocation of non-regression to
PinStore.adopt remains a real weakening for raw-library
callers of `reanchor_pin` (Preserved Dissent 2), but it is now
a *ruled* weakening, not a smuggled one — provided the ruling
is actually written (Dissent 1).

## F2 — client pin fix provenance: DISCHARGED by the stated disposition

Recording it in BUILD-CYCLE-23 as a coordinator-commissioned
fix on seat 3's reported finding, with the latent-since-
cycle-22 defect stated plainly, is exactly the record my F2
required: finding, disposition, and the honest sentence that
cycle 22's "first production adopter" had never completed a
ceremony through a correctly pinned production client. One
wording guard for the coordinator: the BUILD text must not
retroactively place this fix inside DESIGN-FINAL's file
ownership or scope — it was commissioned *because* composition
failed, which is R2's finding path operating late, not the
design anticipating it. With that guard, F2 closes.

## F3 — `recovery_of=None` sentinel: NOT discharged; accepted as a documented residual, non-blocking

The sentinel remains in `check_head` / `append_consumption` /
`_derive_lineage`, and one correction to the coordinator's
framing: "verifier mode always threads explicitly" is
imprecise. `verifier_main`'s consume mode threads
`issued.get("recovery_of")`, which yields **None — the
sentinel itself — for every v1 issuance entry**. So the
production path does not bypass the sentinel for v1-issued
envelopes; it routes through it. Why this still does not
block: (a) authorise now always writes v2, so no new v1
issuances exist; (b) ceremony authorisations carry a hard TTL
cap, so any genuinely pre-cycle-23 v1 envelope is expired and
refused on expiry before the binding matters; (c) the sentinel
only ever binds to the *current head burn with exact
candidate + old-pin match* — it cannot bind a recovery to a
non-head or different-pair burn. The live scope of the
fail-open is therefore empty in production and confined to
direct ledger callers in tests. Preserved as Dissent 3: a
load-bearing binding with a fail-open default is still the
wrong shape for the next direct caller; fail-closed remains
the correct future fix. It does not block this cycle.

## F6(i) — `authorise_pending` append wrap: DISCHARGED

Verified in the diff: the pending append is wrapped,
`OSError` → `PinAdoptionRefused` (chained `from exc`), so
`pin_cycle_hook`'s `.cycle_entry` attachment and the
"cycle recorded, pin pending, alert" contract now cover the
pending-append failure. F6(ii) (unbounded pending-only line
accumulation) stands as originally noted — a record line, not
a blocker, and unchanged by this round.

## New attacks on the fix round

**N1 — LOW: the `unrecoverable` marker is a self-bricking
landmine, guarded only by call order.** I traced every
`check_head` path for a `burned_unadopted` envelope whose
derived lineage is `unrecoverable`: empty journal raises;
candidate behind/at-head (same hash, fork hash) raises before
the marker can matter; candidate ahead raises in the explicit
supersede-exclusion block; bound-mismatch / cap-reached imply
candidate == head target exactly, which raises
AlreadyConsumedError. So the marker is genuinely unreachable
via `append_consumption` today, as its docstring claims.
**But** nothing at the commit point enforces it:
`append_consumption` writes whatever `_derive_lineage`
returns, and if a marker entry ever landed, `_load`'s kind
check (`primary`/`recovery` only) would reject it and the
*entire consumption journal would refuse to load forever* —
a strictly worse failure than the primary-reclassification
the marker exists to prevent. "Never written" is currently an
invariant of one method's call ordering, not of the write
site. One-line remedy (follow-up, not a ship blocker, because
unreachable by construction today): raise in
`append_consumption` if the derived kind is not
`primary`/`recovery`, and pin it with a test.

**N2 — LOW: cross-entry load validation is coherence, not
provenance — sound within that scope.** The ghost-binding,
wrong-pair and depth-jump cases refuse at load, and the
primary → recovery → recovery chain loads (all in my 130-test
re-run). Three limits the record should not overclaim past:
(a) it validates the lineage *graph*, not head-at-write — a
recovery naming a non-head earlier entry of the same pair at
depth−1 loads fine, though `check_head` could never have
written it; (b) it is asymmetric — the consumption journal
cross-validates, the authorisation journal only
format-validates its `recovery_of` (a ghost issuance binding
loads; it is refused only at consume); (c) `_recorded_depth`
for a v1 predecessor counts v2 entries among its predecessors
— unreachable in practice, since v1-after-v2 is corrupt, so
every v1 entry precedes every v2 entry; verified harmless,
worth a comment only. Also noted: load-time strictness (this
validation plus the v1 pair cap at 3) means any future lineage
rule change must migrate the loader first or existing journals
brick on load — the same accepted trade as positional
monotonicity. None of this blocks.

**N3 — INFORMATIONAL: the supersede hash binding is
set-membership, not unique binding.** `recorded` collects
hashes from *both* roles for the old seq; if a seq appears in
the journal with two different hashes (e.g. as one entry's
target and a later entry's old pin), either hash passes. The
docstring's "the recorded hash for that seq" overstates it
slightly. Practical force is small — a superseding envelope
must now reuse a genuinely journal-recorded hash for that seq
rather than invent one, and journal contents are not secret —
but Addendum 3 should describe it as recorded-set membership
if it describes the mechanism at all.

## Preserved dissent (what this SHIP does NOT withdraw)

1. **The records do not yet exist in the tree.** At re-review
   time `internal/DECISION-CONSUMPTION-HEAD.md` still ends at
   Addendum 2, there is no `internal/BUILD-CYCLE-23.md`, and
   no `CROSS-CHECK-BRIEF-CYCLE-23.md`. This SHIP is a judgment
   on the coordinator's *stated disposition*: Addendum 3 and
   BUILD-CYCLE-23 recording the broad primary supersede rule
   as a designed ruling in plain words (not euphemised as
   "narrowed" — the narrowing is real but partial, and the
   brief must say the broad rule remains), and the external
   brief putting supersede to ChatGPT and Gemini as its **own
   numbered question**, separate from cap-2. If the cycle
   commits without those records in that form, this SHIP is
   void and my FIX verdict reinstates automatically. Final
   (non-provisional) ship additionally waits on both external
   seats answering the supersede question, as it already waits
   on cap-2.
2. **T8′ / raw-library non-regression.** Verifier-side
   non-regression for the old-pin-behind-head shape is gone;
   the property now lives in `PinStore.adopt`'s CAS.
   `reanchor_pin` as a library function still returns a
   would-be-regressed pin to any caller who does not adopt
   through PinStore with the authorising capture. Ruled and
   recorded (per Dissent 1), but not solved.
3. **F3 sentinel.** Fail-open default on a load-bearing
   binding, retained by ruling, with the v1 `.get` → None
   nuance above. Non-blocking for the TTL/scope reasons
   given; still the wrong default for the next direct caller.
4. **F5 wording discipline** stands from round 1: the honest
   claim is every production path exercised end-to-end once,
   in composition, against stand-ins. Nothing in the fix round
   changes that, and no shorter claim should ship.

Verdict: **SHIP, 0.78.** The fix round narrowed supersede
past the shapes that made it a safety issue, the coordinator's
rebuttal of my depth==MAX narrowing is technically correct,
and the remaining broad rule is taken — as my own Required #1
demanded — to a designed ruling and to the external seats as
its own question. What remains is dissent about a ruled
policy loss and an unwritten record, not a blocker in the
code.
