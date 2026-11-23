# RE-REVIEW — Cycles 14, 15, 16 (cycle 24, part 2)

**Verdicts (each PROVISIONAL on the parent's external round —
internal/CROSS-CHECK-BRIEF-REREVIEW-14-16.md; final ship
confirmation waits for that reconciliation, and this record says
so): cycle 14 SHIP PROVISIONAL; cycle 15 SHIP PROVISIONAL (after a
fix round); cycle 16 SHIP PROVISIONAL (dissent preserved, §4).**
Cycle 14's ship is additionally conditional on cycles 15/16
passing (seat rr14-r5's term — satisfied by the verdicts below)
and, per seat rr14-r6's preserved dissent, on the external seats
ratifying cycle 24's supersede reading: the restoration evidence
for cycle 14 routes through the supersede path, so if the
externals reject that reading, cycle 14's ship reverts to HELD
alongside cycle 24's supersede closure.

Panels: six fresh blind seats per cycle (scores locked in
calibration before discussion; subjects `rereview-cycle-14/15/16`
plus fix-round subjects), one forced-dissent seat each, reviewers
from other pods than the original builders. Cross-cycle regression
evidence built for this re-review: tests/
test_rereview_ceremony_regressions.py (7 tests) and tests/
test_rereview_restoration_regressions.py (6 tests), on top of the
existing suites. Suite totals: 1696 (part-1 close) → 1710 with the
regression files and the cycle-15 claim-pin test.

**What is being shipped, stated once for all three cycles:** not
the November artefacts. The shipped unit is the snapshot-pin line
AS IT STANDS: cycle 14's chain-gap rule (signing/
state_snapshot.py, substantively unchanged since its fix round,
wording amended by cycle 15); cycle 15's ceremony core AS AMENDED
— per-cycle authorship of the current signing/pin_ceremony.py: 15
ceremony core (advance_pin, reanchor_pin, classify_verification,
PinCeremonyRecord); 16 recomputed eligibility, the shared
sole-chain-gap atom, _candidate_relation gates, history checks,
record-context verification; 19 (Part C) ceremony_id/
authorisation_id binding and the removal of the caller-supplied
operator list; 20 the Ed25519 envelope verification and
verifier-bound evidence; 21 the mandatory verifier-owned
consumption and the history's demotion to audit-only; 22 the
burned_unadopted reason and the PinStore composition; 23 the
schema-v2 lineage interplay; 24 supersede-required propagation —
and cycle 16's hardening AS AMENDED by the same list. Any summary
that names these as plain "cycles 14/15/16" without this sentence
misstates the unit (seat rr15-r6's condition, adopted).

## 1. Cycle 14 — snapshot chain-gap enforcement: SHIP PROVISIONAL

Scores: r1 0.93 SHIP, r2 0.92 SHIP, r3 0.91 SHIP, r4 0.90 SHIP,
r5 0.93 SHIP (conditional on 15/16), r6-dissent 0.62 STAY HELD.

The mechanism is intact and unchanged in substance (r1: rule
placement, capture-once pin reads, dedup, sole-enabler grep —
`_enforce_chain_gap` set only by the strict wrapper). Gemini's
three CROSS-CHECK-8 objections are closed: the liveness trap —
the recovery path now exists end-to-end and is production-wired
(strict refusal → classify reanchor_required → verifier-issued
Ed25519 authorisation with verifier-resolved evidence →
verifier-owned consumption → atomic PinStore adoption; cycle-23
live run; restoration leg 4) (r2); dense emission now lives at
the loop/storage layer as an implemented, fail-closed property,
with the assumption stated at the signing layer and disowned at
the ceremony layer (r3); the caller contract separates
reanchor_required from integrity_failure, proven end-to-end
including a reachable mixed case (r3, r4). GPT's condition — the
pin ceremony as the top trust item — is discharged by the
ceremony as it stands (r5), including the caller analysis: the
strict wrapper now sits on the real adoption path
(PinAdopter.snapshot_and_adopt, reanchor_pin's recomputation);
the bare verifier has no downgrade path in any production flow.
Regression composition judged genuine, not shortcut (r4).

Dissent (r6, preserved): derivative trust on a provisional stack;
the bare-verify API shape (a future caller could misuse the
public bare function — documentation and convention are the only
barriers); the post-restore audit hole (answered for cycle 15 in
§2 by rescoping the audit claim to the verifier journal; the
follow-up `pin-store-history-reconciliation` is named below);
operator non-authentication (standing follow-up); the
unattributed regression-file flake (§5). Reconciliation: the
dissent's load-bearing conditions are the external ratification
itself (this verdict is provisional on it, and reverts if the
supersede reading is rejected) and the record-level rescopes,
which this record makes. The mechanism objections were answered
by the majority with evidence; the dissent is claim-scope and is
carried to the external seats in the brief.

Residuals recorded: corrupted pin store is not adopter-recoverable
(operator removes/replaces the file out-of-band, then genesis —
follow-up candidate from r2); the strict wrapper's docstring
still opens one sentence with the shorthand "Chain continuity is
enforced here", immediately defined down to step-observation
gating in the same sentence (r3, non-blocking).

## 2. Cycle 15 — snapshot pin ceremony: SHIP PROVISIONAL

Blind scores: r1 0.91 SHIP, r2 0.93 SHIP, r3 0.89 SHIP,
r4 0.85 STAY HELD, r5 0.90 SHIP, r6-dissent 0.58 STAY HELD.
Fix round (claim rescope, below): r4 → 0.94 SHIP,
r6 → 0.82 SHIP-provisional (blocking dissent withdrawn).

Every original guarantee survives (r1), two in amended literal
form, both strengthenings: the with-pin reason set gained
burned_unadopted (cycle 22) under the IDENTICAL recomputation
gate; the evidence non-equality check was demoted to
defence-in-depth behind verifier-resolved provenance. GPT's
circular-authority P0 is closed in code (r2): the operator list
lives only in the verifier's env config, the caller-supplied list
is deleted with no fallback, evidence is verifier-resolved,
verifier-hashed, retained and event-bound; the key boundary
exceeds the original demand (Ed25519, seed never leaves the
verifier). Issuance-time-only operator membership (restoration
leg 2: a removed operator's outstanding envelope still consumes)
is RULED defensible disclosed scoping (r2, r5): membership is an
issuance fact, the envelope is single-use, event-bound, and
TTL-capped at 900 s; the compromise-revocation caveat is routed
to the `operator-authentication-channel` follow-up and disclosed
to the externals in the brief. Gemini's points: verification
gating closed (no path where a record's existence moves a pin —
r3); anti-fork/stale-head closed at three layers (r3); the
record MAC is RULED a scoped residual (r3): it is the symmetric
snapshot signing key, now SPECIFIED in the docstring (Gemini's
"unspecified" is answered), and the record no longer carries
authority — minting authority is the Ed25519 envelope and the
consumption journal; the claim condition is that the record must
never be claimed to prove authorisation, burn existence, or
attribution, and the code docs honour it. Atomicity P1 discharged
(r4: one document, one fsync'd os.replace, flock CAS; crash
laboratory proves burn-without-adopt, never a torn pair; one
evidence caveat — no kill-during-os.replace injection test).

The audit-history hole (r4's hold, r6's point D): after a
pin-store restoration the store's ceremony history can silently
lack a record the verifier journal has (leg 4 ends [seq 1,
seq 4]). FIX ROUND — r4's option (b), rescope in the code:
signing/pin_store.py's COMPLETE-HISTORY bullet is renamed
VERIFIED-PRESENT-HISTORY and now states the store history is a
non-authoritative, restoration-lossy replica and the verifier's
externally anchored consumption journal (with its signing-ledger
mirror) is the SOLE AUTHORITATIVE ceremony audit history;
signing/pin_ceremony.py's demotion paragraph names the journal as
the audit obligation's authoritative home; a claim-pin test
(test_signing_pin_store.py::test_16) pins the wording. r4
verified the rescope in full and released its hold (0.94). The
detection branch (reconcile store history against the journal)
remains available as follow-up `pin-store-history-reconciliation`.
r6's remaining objections (record MAC, revocation) are recorded
as claim-scope residuals for the external seats, with r6's own
second-look statement that they are "not a claim that the
mechanism is unsafe" — no path was found by which either moves a
pin, mints an authorisation, or bypasses consumption.

## 3. Cycle 16 — pin ceremony hardening: SHIP PROVISIONAL

Scores: r1 0.91, r2 0.90, r3 0.92, r4 0.92, r5 0.91 — SHIP;
r6-dissent 0.41 STAY HELD (reconciliation below).

All hardening guarantees survive verbatim, strengthened, or
explicitly demoted with the compensating mechanism named (r1):
recomputed eligibility (extended to with-pin burned_unadopted),
the shared sole-gap atom, _candidate_relation as sole sequence
arithmetic, single clock capture, record-context verification.
GPT's blocking defect — no independently protected,
rollback-resistant authority/history source; history omission
grants — is closed (r3): omission can still refuse a legitimate
ceremony (fail-closed noise) but can no longer grant one; the
protected ceremony head GPT directed as the priority exists,
verifier-owned and externally anchored. Gemini's opt-in objection
is closed literally (history a required keyword, None refuses —
cycle 20) and then superseded by relocation (r2): protection no
longer rides on anything the caller supplies. Reason exhaustion
is bounded end-to-end (r4): at most 3 consumptions per movement
(1 primary + depth ≤ 2 recoveries, issuance-bound), one genesis
per journal, a strictly monotonic head for everything else, and
supersede decisions that are journaled, single per envelope, and
inert once the head moves. WRITTEN RULING (adopted by this
record, put to the externals in the brief): per-movement caps
plus single-use plus the monotonic head are the whole of the
exhaustion claim; unbounded SEQUENTIAL legitimate ceremonies —
each a fresh envelope, fresh evidence, a strictly-ahead attested
candidate — are operation, not exhaustion; there is no per-pin
or per-operator primary-ceremony bound, and none is claimed.
Layer migration judged sound (r5): the relation branches other
than gap_prev_is_pin are defence-in-depth behind the envelope
projection, the migration is pinned by exact-message tests, and a
hand-built authorisation object gains nothing (verification
re-derives the payload before any signature check; forging a
well-formed one requires the verifier's seed). Two docstring
tightenings from r5 were applied in the fix round ("at the
history layer"; no-pin burned_unadopted added to the
no-recomputation statement).

CLAIM RESCOPE FOR CYCLE 16 (at the claim site, per the dissent's
condition): ceremony_history is audit-only since cycle 21 — it
can refuse, never grant; the relation gates other than
gap_prev_is_pin are defence-in-depth behind envelope projection;
single-use and non-regression are integrated-system properties
under production wiring (the R5 scoping), not properties of
reanchor_pin for an arbitrary caller-supplied callable; the hash
chain Gemini asked for at the record layer was SUBSTITUTED by
the verifier-owned consumption journal's hash chain plus external
anchoring — that substitution is put to both external seats as an
explicit question in the brief, not presented as the demanded
artefact.

Dissent (r6, preserved in substance): the ship is a label
transfer onto cycles 21–24's conditional machinery; the
Addendum-4 conditional (auto-fired supersede) is genuinely
contestable; the palimpsest point. Reconciliation: the verdict
is PROVISIONAL on exactly the external ratification the dissent
demands — the brief puts the supersede reading, the chain
substitution, and the exhaustion ruling to both seats as explicit
questions; the rescope above states the unit as it now is; the
authorship enumeration (§0) names what cycle 16 did and did not
build. The dissent's "sever the supersede closure from 14–16"
alternative was considered: supersede-shaped movements are part
of the current consume path (step 6b reads the supersession
journal on every consume), so severance is not honestly
available; conditional provisionality is the truthful label.

## 4. Loop-state recording — NOT advanced, with the blocker stated

All three cycles pass re-review and part 1 is committed green
(8a8b2c9), but the real loop state (state/state.json, cycle_seq
13) is NOT advanced in this cycle, for a mechanical reason this
record states rather than papers over: `anchored_record_ship`
records the item `CoreLoop.pick_next()` selects, and pick order
is blocked — seq 20 `ledger-head-anchoring` (leverage 6.5,
genuinely complete as a mechanism in cycle 23), seq 21
`separate-os-user-verifier` (6.5, NOT done: no OS-user separation
exists on this VM, and recording it would be a false record),
seq 30 `verifier-wrapper-routing` (6.5), then seq 34
`snapshot-chain-gap-enforcement` (cycle 14, 6.5); seq 35
`snapshot-pin-ceremony` (cycle 15) sits at leverage 4.0 behind
~15 further items, and cycle 16 has NO backlog item of its own
(it was built under the cross-check scope, not a scanned item).
CoreLoop exposes no re-rank API (scan/approve only). The honest
routes are: (a) a recorded operator re-rank of the backlog in the
main chat's ship path, or (b) recording the intervening items in
pick order as they genuinely complete — both are the parent's /
operator's acts, not this re-review's. No ship packages were
pre-built: a package's manifest binds the tree at recording time,
so a package built now could not be honestly consumed later.
This follows the project's own convention (the cycle 14/15/16
build records each state loop state is not advanced by the build
run and recording is left to the signed ship path). state/
state.json sha256 unchanged throughout part 2:
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39.

## 5. Evidence quality note — suite flakes

Two load-shaped failures were observed during part 2, each once,
each in a parallelism/contention test, each passing in isolation
and in repeat runs: HeadBindsChainGapTests under one full-suite
run (rr14-r4 additionally ran it standalone ×3, combined, and 16×
concurrent — all green; the original traceback was not preserved,
so attribution to VM contention is a judgement, not a proof) and
test_trust_sealed_eval_contention under another (passes in
isolation twice). The coordinator's final full-suite run for this
cycle is recorded in the commit message / part-2 close-out. The
dissent seats' point stands in the record: an unattributed flake
is weaker evidence than an attributed one, and the brief does not
claim otherwise.

## 6. Follow-ups named by this re-review

- `ceremony-journal-anchoring` (from cycle 24): anchor the
  issuance journal AND the supersession journal — first item of
  the next trust cycle.
- `pin-store-history-reconciliation` (new): detect store-history
  incompleteness against the consumption journal (the detection
  branch of the cycle-15 audit hole), or anchor the pin-store
  document head.
- `operator-authentication-channel` (standing): per-operator
  credentials; also the home of any consume-side revocation /
  deny-list mechanism (cycle-15 re-review caveat).
- Bare-verifier API confinement (from cycle 14's dissent): a
  trust-lint rule confining bare verify_signed_snapshot calls to
  the known internal sites, or a gap-state-carrying result type.
- Corrupted-pin-store adopter recovery (from cycle 14's r2):
  production-wire the lost_pin/corrupted_pin path so a corrupt
  store does not dead-end at PinAdoptionRefused.
- Kill-during-os.replace torn-store injection test (cycle 15's
  r4 evidence caveat).
