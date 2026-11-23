# Decision — Consumption head store location: VERIFIER-OWNED
Date: 2026-11-23. Decided by the AION war room (3 coder seats
designing together + cross-critique, coordinator rulings in
internal/cycle21-work/DESIGN-FINAL.md R1), under the standing
rule recorded in DECISION-PROTECTED-GATE-EXTENSION.md
(2026-11-23): design and store-location decisions are made
by the war room and recorded; Dilip is informed of outcomes
in the normal updates, not asked mid-build.

## The decision

The protected monotonic consumption head for the pin
ceremony lives in the VERIFIER's store: a new hash-chained
journal `ceremony-consumptions.json` (class
`CeremonyConsumptionLedger`) under the existing
`AION_VERIFIER_HOME`, written only by a new verifier mode
`ceremony_consume`. Consumption is checked and recorded by
the verifier process at the moment of the ceremony;
caller-supplied `ceremony_history` stops being authoritative
(it remains a required audit/consistency input that can only
refuse, never grant). No new environment variable is
introduced; the deploy wrapper allowlist is unchanged.

## Why this location

- It is the only protected store that already exists. The
  verifier process is the system's established trust
  boundary (separate OS user in production deployment,
  env-only config, its own ledgers); the ceremony process is
  precisely the caller whose supplied state the external
  seats refused to trust (CROSS-CHECK-9/10/14).
- It reuses proven machinery unchanged in kind: the
  HashChainJournal discipline (flock, fsync, atomic replace,
  freshness-under-lock), the issuance journal's
  commit-point pattern, and the signing ledger's anchored
  mirror — so the consumption fact gains an anchored trace
  in production without a journal-format migration.
- It closes the blocking defect as an integrated-system
  property, under production wiring and against an intact
  verifier home: single-use and pin non-regression no longer
  depend on any history the caller supplies, which is the
  exact form of seat-gpt's FIX 0.96 (CROSS-CHECK-14 item
  (3)) and seat-gemini's binding condition on cycles 14–16.
  (Qualifier, made part of this sentence's claim at
  rev-r6's re-review condition and not left to the
  "Accepted residuals" section alone: the consumption
  journal is not externally anchored, so a verifier-home
  rollback can lower the enforced head for never-consumed
  envelopes until ceremony-journal-anchoring lands.)

## Alternatives weighed and rejected (on record in the designs)

- Caller-side consumption store (any form, incl. a MACed
  caller file): it is the defect itself — state the caller
  can roll back cannot refuse the caller.
- A second entry kind in the issuance (ceremony
  authorisation) journal: conflates two commit points and
  forces an exact-key-set format migration on a live
  journal.
- The signing ledger as the primary store: its fixed entry
  shape cannot carry the candidate head; it serves as the
  anchored MIRROR instead.
- A new env-configured directory: pure cost (a fifteenth/
  eighteenth allowlist name in five copies) for no
  additional protection over the verifier home.
- A separate OS user / separate service for consumption:
  a deployment change disproportionate to this cycle;
  deferred to the anchoring follow-up's judgement.
- Anchoring the consumption journal as its own anchor kind
  this cycle: needs a new anchor kind + env var + migration;
  deferred, jointly with the issuance journal, to the
  follow-up `ceremony-journal-anchoring` (extended by this
  decision to cover both journals).

## Accepted residuals (stated, not buried)

- The consumption journal is not externally anchored this
  cycle. A rollback of the verifier home cannot resurrect a
  consumed envelope whose consumption reached the anchored
  signing-ledger mirror (production), but can lower the
  enforced head for never-consumed envelopes.
- The head is a ceremony head, not a pin head: advance_pin
  movements never pass through the verifier. The old-pin
  not-behind rule narrows the fresh-envelope regression
  class; full closure belongs to a future loop/storage
  pin-store compare-and-swap.
- The guarantee is a property of the integrated system
  under its production wiring (authorise via the client,
  re-anchor with the verifier-backed consumer, adopt the
  returned pin atomically) — not of the reanchor_pin library
  function for an arbitrary caller-supplied callable.
- Recovery from a burned-but-unmoved consumption is a new
  ceremony ahead of the head; a consumed target is never
  re-anchorable.

## Consequences

- Cycle 21 implements this decision (BUILD-CYCLE-21.md).
- Cycles 14–16 remain HELD; their re-review is the next
  step after cycle 21 reconciles with the external seats,
  and this head is the precondition those cycles were held
  on.

## Addendum — 2026-11-23 (cycle 22): consumption journal anchored

The consumption journal is now externally anchored in its
own right: `trust/anchoring.py` gains the anchor kind
`"ceremony-consumption"`, configured by
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` /
`AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` (allowlist 17 → 19).
The anchor lives outside the verifier home and is distinct
from the signing and budgets anchors. `_load_config`
verifies it on every invocation (the verifier is one
process per request), before any mode runs; production mode
with the ceremony seed configured requires the path and
refuses the INIT flag.

The consume commit order is now: (1) consumption-journal
append (the commit point, unchanged — the journal remains
the head authority); (2) consumption-anchor update;
(3) signing-ledger mirror; (4) signing-anchor update.
Advancing the consumption anchor BEFORE the mirror write is
the load-bearing ordering: a burn whose mirror write failed
(`ledger_failed`, envelope burned) followed by a
verifier-home rollback leaves the external consumption
anchor ahead of the rolled-back journal, so the replay is
refused at startup (`anchor_refused`) instead of consuming
a second time. This supersedes the cycle-21 "Accepted
residuals" bullet above for consumptions whose anchor
update completed, and the R10 residual wording in
`CeremonyConsumptionLedger`'s docstring is rewritten to
match: with the consumption anchor configured, a burn whose
anchor update completed survives a verifier-home rollback
(detected at startup); the append→anchor-update window
(burn in journal, anchor at pre-burn prefix) is protected
against an intact home but NOT against a full rollback
inside that window — the same window every anchored append
in this system carries; research mode / anchor
unconfigured: no rollback claim.

The follow-up `ceremony-journal-anchoring` is NARROWED to
the issuance journal (`ceremony-authorisations.json`) only:
the defect closed here was consumption-specific, and a
resurrected issuance pair yields an envelope that must
still pass consumption, where single-use and the head live.
The earlier decision text above is unchanged history; the
"no new environment variable" and "deferred anchoring"
statements there record cycle 21's position, superseded by
this addendum for the consumption journal only.

## Addendum 2 — 2026-11-23, cycle-22 war-room fix round: recovery is one-shot

The cycle-22 war room (forced-dissent seat rev-r6, finding
F1) established that the recovery exception as first built
was self-perpetuating: a recovery consumption writes a
journal entry indistinguishable from the original burn
(same old→new pair; the strict entry schema carries no
reason field), so the head entry a later recovery matches
could itself be a recovery, waiving target-level single-use
for the head target indefinitely. Ruling: recovery is
ONE-SHOT per burned movement. `match_head_burn` now returns
None when any earlier journal entry carries the same
(old, new) pair as the head; the rule binds at both gates
(authorise step 5b and consume-side `check_head`) through
the shared predicate. This SUPERSEDES two cycle-22 design
positions recorded earlier: design-A §6.2 (iterated recovery
as a chain, one head at a time) and §4.4.5's race outcome
(both pre-authorised recoveries consume and land) — under
one-shot, both race authorisations may be issued against
the original burn, the first consumption lands, and the
second is refused AlreadyConsumedError. Consequence,
accepted by the room: a recovery that itself burns
unadopted is terminal for that movement; liveness resumes
at the next snapshot sequence. The primary burned-but-
unmoved path is unaffected: an adopter holding the returned
pair completes adoption via `adopt_returned` with no new
consumption at all.

## Addendum 3 — 2026-11-23, cycle 23: schema v2 lineage, bounded recovery (cap 2), and the supersede rule

This addendum SUPERSEDES Addendum 2's one-shot ruling.
Recovery is no longer one-shot; it is a bounded chain,
ruled by the cycle-23 war room (DESIGN-FINAL R3) on top of
a versioned journal schema that records lineage explicitly
— the resolution both external seats' cycle-22 texts
pointed at (seat-gpt listed a lineage schema as the
improvement path; seat-gemini demanded the schema be fixed
properly). External ratification of THIS re-rule is still
pending: seat-gpt ratified one-shot in cycle 22, so the
change of bound is put to both seats explicitly in
CROSS-CHECK-BRIEF-CYCLE-23.md, and the cycle-23 verdict is
provisional until they answer.

Schema v2 (trust/ledger.py): consumption-journal entries
carry consumption_kind ("primary"/"recovery"), recovery_of
(the authorisation_id of the burn recovered), and
recovery_depth. Versioning is per-entry: the loader accepts
the v1 and v2 key sets with positional monotonicity (no v1
entry after a v2 entry); v1 entries are never rewritten
(their hashes are anchor-covered). The issuance
(CeremonyAuthorisationLedger) journal carries the binding:
authorise step (5b) records recovery_of from the verifier's
own match_head_burn result — never from the request — and
consume threads it into the lineage derivation, which runs
inside append_consumption's retry loop on freshly reloaded
entries. Load-time coherence (fix round + re-review): a
recovery grounds only on its IMMEDIATE PREDECESSOR (the
burn is the head at consume time in every append-reachable
history), a v2 primary may not re-root an already-consumed
pair, duplicate authorisation_ids are corrupt, and a v1
pair may occur at most twice.

Bound: MAX_RECOVERY_DEPTH = 2 — a movement is consumable
at most 3 times (primary + 2 recoveries). Depth 1 covers a
single adopt fault, depth 2 one full incident's double
fault; a third interruption indicates a broken adopter.
Authorise refuses at the cap (ceremony_recovery_unproven);
consume refuses as AlreadyConsumedError. Exactly-one
success under concurrency is preserved and now pinned by a
true multiprocess race test (two authorisations bound to
the same burn: exactly one consumption lands; a fresh
recovery bound to the WINNER's burn may land at depth + 1).

The supersede rule (designed ruling, recorded here in
plain words): the rule arrived in cycle 23's build phase
(seat 3's scenario-6 deadlock) and was narrowed in the war
room's fix round; it is a BROAD rule for primary movements,
not a terminal-case exception. In check_head, a fresh
non-recovery consumption whose candidate is STRICTLY AHEAD
of the consumed head may carry an old pin BEHIND the head:
the burned head movement is superseded — abandoned, never
adopted; its burn remains a permanent journal fact. The
rule never applies to burned_unadopted envelopes, and when
the old pin's sequence is recorded anywhere in the journal
(as a target or as an old side) its hash must match the
recorded hash. Narrowing the rule to depth == MAX was
considered and rejected in the war room: depth measures
the recovery chain, not artefact retention (which the
verifier cannot observe) — a depth-0 head whose adoption
pair and journal lines were lost is exactly the proven
deadlock, so no depth condition separates deadlock from
abandonment. The rule's cost is liveness/fairness, not
safety: an authorised primary can abandon a retained,
adoptable burn; the pin itself can never regress through
it (strictly-ahead candidate; PinStore CAS + non-
regression + context-bound record verification). Two
residuals are named: (i) an old-pin sequence NOT recorded
in the journal cannot be hash-checked by the verifier
(the verifier cannot observe the pin; adoption-side
context binding is the control); (ii) a resurfaced
superseded pair adopted later can stall one sequence at
AlreadyConsumedError before self-healing via the next
supersede. The rule is put to the external seats as its
own numbered question in the cycle-23 brief.
