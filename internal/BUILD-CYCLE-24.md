# BUILD CYCLE 24 — part 1: cycle 23's convergent external conditions

**Summary (claim scope, verbatim per the cycle-24 war room):**
item (1) is a production-mode entry point; no non-test invocation
path exists yet; production mode under same-user spawn is not
deployment evidence. Item (3)'s supersede closure is conditional on
(a) the external seats ratifying the "separately authorised" reading
in Addendum 4 of internal/DECISION-CONSUMPTION-HEAD.md, with the
PinAdopter auto-fire flow disclosed as the external brief's
headline, and (b) the unanchored-journal residual (the follow-up
`ceremony-journal-anchoring` covers both the authorisation journal
and the new supersession journal; the supersession journal is also
an availability dependency of ordinary consumes — see Addendum 4).
All ship decisions this cycle are PROVISIONAL on the parent's
external round.

Baseline: cycle-23 tree at f8edee2, 1620 tests OK (skipped=28),
coordinator-verified before building. Requirements:
internal/CROSS-CHECK-17.md (Gemini SHIP 0.88 with two named gaps;
GPT FIX 0.96 with the supersede Option A requirement). Designs:
internal/cycle24-work/design-a.md (items 1+2), design-b.md
(item 3), design-c.md (item 4 assessment); coordinator rulings
R1–R4 in internal/cycle24-work/DESIGN-FINAL.md (plus the receipt-key
adjudication note added during the war room). Four builder seats,
disjoint files; war room and fix round in
internal/REVIEW-CYCLE-24.md.

## Item 1 — production entry point (R2)

New `trust/runner.py`: `python3 -m trust.runner`, no argv; the
non-test entry point that runs the production pin-adoption loop.
Configuration is env-only (`AION_RUNNER_STATE_DIR`,
`AION_RUNNER_PLAN_PATH`, `AION_RUNNER_EXPECTED_SIGNER_ID`,
`AION_RUNNER_EXPECTED_KEY_ID`,
`AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX` — exactly 64 lowercase hex
chars constructing a `CeremonyPublicKey` whose key id is DERIVED,
never accepted from configuration) on top of the full
`production_client` env contract. The whole plan is validated
before anything is constructed; a state-layout pre-check (state.json
AND calibration/calibration.json must exist) runs before
`build_pin_adopter`, so a mispointed state dir refuses instead of
silently bootstrapping a fresh loop. Construction is exactly
`CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))`; the
runner constructs no VerifierClient/MemoryStore/PinStore itself
(one new trust-lint allowlist entry). Plan steps are `{"adopt":
true}` or `{"cycle": {coders, reviewers, verdict, verify_passed,
delta}}` (delta shape mirrors record_ship's manifest delta). Exit
codes: 0 ok/idle, 2 config/plan refusal, 3 adoption refused, 4
adoption burned, 5 cycle recorded pin pending, 6 step refused, 1
unexpected (traceback). Structured outcome lines never echo
configured values; the no-echo guarantee is scoped to those lines
(exits 0/2/3/4/5/6) — exit 1 tracebacks may include exception
messages (docstring, corrected in the fix round). Demonstration:
tests/test_trust_runner.py drives the entry point itself as a
subprocess against a byte copy of the real state — genesis adopt
@13, hooked cycle advancing the pin to @14, test-side hookless
cycles to 15/16, chain_gap_recovery adopt @16 → already_current;
real state/state.json sha256 unchanged; exactly 2 consumptions.
Fix round added subprocess tests for exits 3, 4, 5 and idle (the
exit-5/exit-4 seam is genuine: the test holds the pin store's flock
so the ceremony consumes and PinStore.adopt then fails — a real
post-consumption burn, witnessed by the recorded cycle + exactly 1
consumption + no pin file).

Corrections to design-a recorded by the war room: (§1.4) a LATE
factory failure (e.g. a bad signing-key file, raised by
load_signing_key AFTER PinStore.__init__ has created the pin dir)
does leave an empty pin directory behind — "writes nothing at
construction" holds only for failures before the factory runs; the
exit code is 2 either way. (Idle cycles) a cycle step against an
exhausted/idle backlog returns before CoreLoop's gate checks run —
an inherited loop contract the runner surfaces faithfully; the
build record does not claim plan cycle steps are gate-checked in
all states. (Empty plan) a plan must carry 1–100 steps; idle is a
cycle step with no pickable item, not an empty plan.

## Item 2 — mandatory ceremony key (R1)

`production_client(..., *, ceremony_public_key)` is now a required
keyword: omitting it is a TypeError at the call site; None or a
non-CeremonyPublicKey is a VerifierConfigError, checked after the
existing signer/key-id pins. A production client that cannot accept
ceremonies is impossible to construct. The only production caller
(build_pin_adopter) already passed the key. trust/client.py is
unchanged. deploy/verifier-identity/README.md's stale pin warning
was rewritten as a requirement. New tests pin omission, None,
wrong-type, and precedence (the signer-pin and key-id refusals fire
before the ceremony check).

## Item 3 — supersede Option A (R3)

As designed in design-b.md and recorded in DECISION-CONSUMPTION-HEAD
Addendum 4. New verifier mode `ceremony_supersede` (registered in
trust/protocol.py MODES): the verifier identifies the abandoned
movement from its own consumption head; the request names no
abandoned field; every shape failure collapses to the single code
`ceremony_supersede_unproven`. New hash-chained
`CeremonySupersessionLedger` (ceremony-supersessions.json; mirrored
into the anchored signing ledger, kind "supersede"; dedicated
external anchor deliberately NOT added — see item 4). The shared
predicate `CeremonyConsumptionLedger.supersede_head` decides the
shape; `check_head`/`append_consumption` thread an optional
`supersede_decision`, raise the new `SupersedeRequiredError`
(direct LedgerError subclass) only pre-commit when the shape holds
but no decision is supplied, and check the journal-known old-pin
hash BEFORE the decision gate. The consume mode looks the decision
up from its own journal (step 6b), keyed by the envelope's
authorisation id, and maps the error to the new exit-3 code
`ceremony_supersede_required` (documented post-verification
state-oracle class). The consume mode also narrows the cycle-23
sentinel: a v1 issuance entry's absent recovery_of is converted
from None to "" before threading, so the sentinel is unreachable
through the verifier (Addendum 4 states the precise scoping).
Client: `_run` errors carry a structured `.verifier_code` (set on
every raise; string-matching is not used anywhere);
`ceremony_consumer` translates the code — gated on
VerifierConfigError after the fix round — to
`CeremonySupersedeRequired` carrying the envelope; `reanchor_pin`
propagates it untouched; `VerifierClient.ceremony_supersede`
validates the receipt by exact key set. PinAdopter._reanchor
factors the attempt into `_attempt()`: on
CeremonySupersedeRequired it makes exactly one decision request
and exactly one re-run with the same envelope, journaling a
`supersede_decided` phase (not a burn phase); design-b §7.1 records
why this is not an ambiguous-consume retry (the code is emitted
only pre-commit, after the already-consumed check certifies the
envelope unconsumed; a lost DECISION response is treated as burned,
never re-decided). End-to-end deadlock test: a movement consumed to
the cap with both adoption pairs discarded lands its next-sequence
primary only after the journaled decision (counting pin: exactly 1
supersede call, 2 consume attempts).

Fix round (war-room findings): check_head now derives its supersede
determination from supersede_head itself (the blind round found the
two copies had already diverged on the "" no-pin hash spelling; a
16-case drift-equivalence battery pins agreement, and the ledger
seat's probe-B direction — agree on the predicate's semantics — was
ratified at re-review with reasons recorded in REVIEW-CYCLE-24.md);
supersede_head excludes initial_anchor explicitly;
append_decision validates shape before appending (it could
previously write an entry its own _load rejects); the supersession
_load rejects kind != "supersede", decided_at != recorded_at, and a
non-hex64 candidate hash; the supersede mode's post-mirror anchor
failure carries mode-accurate detail; `.verifier_code = None` is
set on every client raise that has no code; the consumer
translation is gated on the exception type as well as the code; the
supersede_decided journal append is wrapped to PinAdoptionBurned
on OSError; two tests pin ordinary consumes against an absent
(proceeds normally) and a corrupt (refuses ledger_failed, nothing
consumed) supersession journal.

## Item 4 — issuance-journal anchoring: DEFERRED (R4)

Design C's fit assessment, adopted: the design is complete and
buildable as written (kind "ceremony-authorisation", env pair,
authorise commit order journal → authorisation-anchor → signing
mirror → signing anchor), but it does not fit cleanly after items
1–3: the allowlist change (19 → 21) is replicated across wiring,
run-verifier.sh, health_check.py, the setup.sh template and the
deploy tests; `_load_config`'s blast radius is verifier-wide; and
CROSS-CHECK-17's convergent scope excludes it. The harm model does
not force it now: a rolled-back issuance journal bricks the
original envelope (refused `ceremony_not_issued` at consume) rather
than enabling a double-consume — the anchored consumption journal
and the head rules still refuse — and the residual misuse needs
active re-presentation by a listed operator against a different
movement, partially detectable today. It remains the explicit
follow-up `ceremony-journal-anchoring`, now covering BOTH the
authorisation journal and the cycle-24 supersession journal, and
is the first item of the next trust cycle. The verifier module
docstring names both unanchored journals.

## Tests

1620 → 1678 at the build seats' landing (coordinator-side run),
→ 1696 after the fix round (coordinator-verified on the final
tree: Ran 1696 tests, OK, skipped=28 — the skips are the documented
deployment-gated ones; the deployment is not provisioned on this
VM). New files: trust/runner.py, tests/test_trust_runner.py (12),
tests/test_trust_ceremony_supersede.py (49),
tests/test_trust_supersede_adopter.py (6). eval/ untouched. Real
state/state.json not advanced (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
before and after).
