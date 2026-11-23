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

## Addendum 4 — cycle 24: supersede Option A as built; sentinel scoping

*(Cycle 24 part 1, implementing CROSS-CHECK-17's convergent scope.
War-room record: internal/REVIEW-CYCLE-24.md.)*

**Option A as built.** The broad supersede rule's missing leg — an
explicit, separately authorised, journaled supersession decision —
is implemented as designed in `internal/cycle24-work/design-b.md`
(adopted as DESIGN-FINAL R3):

- A new verifier mode `ceremony_supersede` mints the decision. The
  VERIFIER identifies the abandoned movement from its own consumption
  head; the request names no abandoned-movement field. All shape
  failures collapse to one refusal code,
  `ceremony_supersede_unproven`.
- The decision is journaled in a dedicated hash-chained journal
  (`CeremonySupersessionLedger`, `ceremony-supersessions.json`) and
  mirrored into the anchored signing ledger (kind `"supersede"`).
  The receipt's key set is canonical (adjudicated during the build;
  named in DESIGN-FINAL's adjudication note):
  `{"abandoned_authorisation_id", "new_authorisation_id",
  "candidate_cycle_seq", "candidate_payload_hash",
  "supersession_seq"}`.
- Consume-side, `check_head`/`append_consumption` accept a
  behind-head old pin ONLY when the shape predicate
  `CeremonyConsumptionLedger.supersede_head` — now the single
  implementation used by both the mode and `check_head` (cycle-24
  fix round) — offers the shape AND a journaled decision binds the
  abandoned movement to this envelope (abandoned authorisation id and
  (old, new) pair, new authorisation id, candidate (seq, hash),
  superseding old pin, operator). The journal-known-hash check runs
  BEFORE the decision gate; a missing decision raises the dedicated
  `SupersedeRequiredError`, surfaced by the consume mode as the
  documented post-verification state-oracle code
  `ceremony_supersede_required`, emitted only pre-commit. Context
  binding (the pin-store's current pin) remains mandatory on every
  adoption, per Gemini's condition. Recovery envelopes are never
  reclassified: `burned_unadopted` (and `initial_anchor`) are excluded
  from the supersede shape by construction.

**What "separately authorised" means here — disclosed reading.** The
decision is a separate authorisation act from the consumption
authorisation: distinct signed envelope, distinct verifier mode,
distinct journal, distinct receipt. It is NOT a separate human act:
`PinAdopter` requests the decision automatically — exactly one
decision request and exactly one re-run of the consume attempt with
the same envelope — when a consume surfaces
`ceremony_supersede_required`, using the same configured operator id
and the same launch channel (operator identity remains allowlist
eligibility, not authentication; see the cycle-20 canonical
sentence). This reading of seat-gpt's Option A wording was adopted
by the cycle-24 war room (DESIGN-FINAL R3) and ratified internally
at re-review (5 of 5 voting seats), with the forced-dissent seat's
objection preserved in REVIEW-CYCLE-24.md. **The supersede item's
closure is CONDITIONAL on seat-gpt ratifying this reading** in the
external round, where the auto-fire flow is disclosed as the brief's
headline; if the external seats reject the reading, the closure
reopens.

**Closure is also conditional on the unanchored-journal residual.**
The supersession journal is authoritative for abandonment yet is not
externally anchored (follow-up `ceremony-journal-anchoring` now
covers BOTH the authorisation journal and the supersession journal;
design in `internal/cycle24-work/design-c.md`). Its rollback
position is stated in the ledger docstring: a file-only rollback to
an earlier prefix fails closed (the decision is simply absent;
re-decidable because uniqueness lives in the same file), and a
rolled-in decision for a different envelope or a moved head is inert
by the §5.2 binding. One widening found at re-review (rev-r6): the
consume mode reads the supersession journal on EVERY consume (step
6b), so the unanchored journal is also an availability dependency of
ordinary consumes — a corrupt journal refuses ordinary consumes
fail-closed with `ledger_failed` and nothing consumed (pinned by
test). Fail-closed is the intended direction; the dependency is
recorded here so the residual is stated in full.

**Sentinel scoping (seat-gpt's cycle-23 condition).** The cap-2
lineage guarantee is a property of the integrated verifier path, not
of the ledger API for arbitrary in-process callers. Precisely: the
consume mode converts a v1 issuance entry's absent `recovery_of`
(the `None` sentinel) to `""` (no lineage) before threading it into
`check_head`, so through the verifier the sentinel is unreachable
and every threaded binding is a string; `check_head`'s own `None`
default remains for direct in-process callers, for whom the
guarantee does not hold. Making lineage mandatory at the ledger API
boundary itself would break the v1 read path and is not attempted;
the scoping sentence above is the precise claim, and it supersedes
any broader reading of Addendum 3's guarantee.

## Addendum 5 — cycle 25: independent supersession authorisation; Addendum 4's reading superseded

*(Cycle 25, resolving the Q1 split in internal/CROSS-CHECK-18.md.
War-room record: internal/REVIEW-CYCLE-25.md. Design:
internal/cycle25-work/design-approval.md.)*

Addendum 4 disclosed that cycle 24's supersession decision,
while a separate signed envelope, mode, journal and receipt,
was requested by PinAdopter AUTOMATICALLY after a refusal, and
recorded that its closure was conditional on seat-gpt ratifying
that reading of "separately authorised". Seat-gpt did not
ratify it (CROSS-CHECK-18): a separately SIGNED decision is not
a separately AUTHORISED one. Addendum 4's reading is therefore
SUPERSEDED as the standing claim. The cycle-24 mechanism
remains as the decision layer; what changed is what may cause
a decision to be issued.

**The rule as of cycle 25.** A supersession decision is
issued only against an independent supersession APPROVAL: a
signed artefact minted out-of-band by the standalone approval
tool (`trust/supersession_approval_tool.py`) under a dedicated
approver key — a third Ed25519 key, distinct from the snapshot
signing key and the verifier's ceremony seed (distinctness
from both is now enforced at verifier startup). The verifier
verifies the approval — signature, expiry, and the full
binding re-derived from its own journals — BEFORE journaling
any decision, and records the approval's id, payload hash and
approver key id in the decision entry. The approval binds the
abandoned head movement, the replacement candidate, the exact
(old, new) movement on both sides, and the original failed
consumption attempt (attempted authorisation id, the refusal
code, and the head entry's authorisation id, journal seq and
entry hash, so any head movement stales the approval).
Approvals are single-use: a spent approval id refuses at load,
at the mode, and inside the ledger's append retry loop.

**The adopter's role.** On `ceremony_supersede_required` the
adopter now STOPS: it journals a pending phase, writes a
pending-supersession report, and raises
`PinSupersessionPendingApproval` (runner exit 7). It makes no
decision request and no re-run. Only a later, separately
invoked attempt that finds an approval artefact in its inbox
presents it — once — and completes the consume. The adopter
is the approval's custodian and presenter, never its author:
its code path contains no import of the approval tool and no
access to the approver seed (the seed's path variable is
absent from the verifier wrapper allowlist and refused by the
client wiring as unknown). The pending report's head `seq` /
`entry_hash` are written null by the adopter — it cannot read
the verifier's journals — and are completed by the approver
from the consumption journal as a disclosed transcription
step inside the act; a wrong transcription is inert, because
the verifier re-derives the binding from its own head entry
and refuses rather than misapproving.

**The precise trust claim.** Independence is at the
AUTHORISATION-EVENT level: supersession cannot happen as a
side effect of an automated recovery flow; it requires a
deliberate separate act, with its own artefact and key,
outside the adopter's control flow. It is NOT a claim of a
separate human or a separate OS user — on this same-user
machine the operator and the approver are the same person
running a second command, and a fully malicious same-user
process remains outside the claim. Approval TTL is 900 s by
default, hard-capped at 3600 s (a documented deviation for a
human-paced act); the effective window is bounded in practice
by the candidate envelope's remaining TTL. Production startup
refuses to run without the approver public key configured
(the fail-fast discipline of cycles 22–23), so the key gates
verifier startup although it is used only by the supersede
mode; approver-key rotation and seed-loss recovery are
documented in deploy/verifier-identity/README.md (rotation
invalidates unspent approvals only; seed loss wedges
supersession alone and is recovered by reprovisioning).

**Stage names (seat-gemini's relabel condition).** The
consumption AUTHORISATION is the cycle-19/20 envelope. The
supersession DECISION is the verifier-journaled record that a
specific abandonment is permitted. The supersession APPROVAL
is the out-of-band artefact that alone authorises a decision.
No stage is an "authorisation" except the first.

**Resume semantics completed in the fix rounds.** A journaled
decision whose outcome was lost to the adopter no longer
strands the movement: resume is consume-first when a decision
may already exist; a pre-commit refusal (supersede-required
or head-regression) on that consume falls through to the
approval path in the same attempt or re-pends, never burns;
and a consume the verifier certifies as already-consumed is
journaled `consumed` adopter-side, releasing the movement to
the ordinary `burned_unadopted` recovery.

## Addendum 6 — cycle 26: claim narrowed to the enforced property

*(Cycle 26, resolving seat-gpt's cycle-25 FIX 0.91 in
internal/CROSS-CHECK-19.md — claim wording only; every
mechanism component was SHIP. Option A: narrow the claim.)*

Addendum 5's "deliberate separate act" phrasing (and the
related "human-paced act" phrasing for the approval TTL) is
SUPERSEDED as claim wording. The cycle-25 mechanism is
unchanged; what changes is only what may be claimed for it.
The word "deliberate" overstated the enforcement: the
mechanism proves a separately invoked, cryptographically
independent approval operation outside the adopter's
automated recovery path, and it cannot prove that no other
unattended automation invokes the approval tool, nor —
even with cycle 26's interactive gate — that the invocation
was an act of human deliberation.

**The canonical claim, verbatim, as of cycle 26:**

Supersession requires a separately invoked, cryptographically independent approval operation — a standalone tool invocation, with its own inputs, producing its own signed artefact under its own dedicated key — outside the adopter's automated recovery path. The mechanism does not establish that the invocation was performed by a human, nor that no other unattended automation invoked the tool.

Every claim site in the tree — exactly the files pinned by
the banned-phrase scan in
`tests/test_cycle26_claim_pin.py`:
`trust/supersession_approval.py`,
`trust/supersession_approval_tool.py`,
`trust/pin_adoption.py`,
`deploy/verifier-identity/README.md`,
`internal/cycle25-work/design-approval.md`,
`signing/pin_ceremony.py` and `trust/runner.py` — is
narrowed to this sentence in substance in cycle 26.

**Interactive gate addition (cycle 26, Option B in
addition).** The approval tool's `approve` command now
requires an interactive typed confirmation; no
non-interactive override exists. This deviates from
CROSS-CHECK-19's reconciliation, which had contemplated a
documented override: the war room voted 6/6 against an
override, none was built, and if one is ever added its
existence will be disclosed in the claim before it ships.
This is a friction and accident-resistance property of the
invocation, not a proof of human deliberation: a TTY can be
scripted via a pty, so the claim above is not upgraded by
the gate, and the gate is not described anywhere as
establishing that a human performed the invocation.

**Claim pin.** The narrowed wording is pinned by
`tests/test_cycle26_claim_pin.py`: it asserts the
over-claim phrases ("deliberate separate act", "deliberate
act", "human-paced act", "deliberate tool invocation",
"deliberate approval act", "deliberate, separate approval
act", "make the *act* deliberate", "deliberate
transcription", "human-paced") do not appear in the
supersession-claim source files,
and that this addendum exists and carries the canonical
narrowing. Earlier addenda in this file are history and
legitimately quote the superseded phrasing; they are not
rewritten.
