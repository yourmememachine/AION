# REVIEW CYCLE 24 — part 1 war room

**Summary (claim scope, verbatim per the war room):** item (1) is a
production-mode entry point; no non-test invocation path exists
yet; production mode under same-user spawn is not deployment
evidence. Item (3)'s supersede closure is conditional on (a) the
external seats ratifying the "separately authorised" reading in
Addendum 4 of internal/DECISION-CONSUMPTION-HEAD.md, with the
PinAdopter auto-fire flow disclosed as the external brief's
headline, and (b) the unanchored-journal residual — including the
re-review finding that the unanchored supersession journal is also
an availability dependency of ordinary consumes (consume step 6b
reads it on every consume; a corrupt journal refuses ordinary
consumes fail-closed with `ledger_failed`, nothing consumed).
Verdict: **SHIP PROVISIONAL** — reconciled unanimous after the fix
round; provisional on the parent's external round (ChatGPT +
Gemini), per the standing rule.

## Blind round (subject `cycle-24-part1-review`, scores locked before discussion)

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | item 2 mandatory key | 0.94 | SHIP |
| rev-r2 | item 1 runner | 0.80 | FIX |
| rev-r3 | item 3 ledger | 0.82 | FIX |
| rev-r4 | item 3 verifier modes | 0.88 | SHIP |
| rev-r5 | item 3 client/adopter | 0.89 | SHIP |
| rev-r6 | forced dissent, whole part | 0.35 | FIX |

rev-r1: no blocking findings; mutation-verified (restoring the
default or the old conditional fails the new tests); noted the
pre-existing factory behaviour that a hand-forged CeremonyPublicKey
with a wrong key_id constructs (fail-closed downstream; follow-up
noted, not part of this cycle).
rev-r2: F1 MEDIUM — huge-int plan delta (10**400) crashed
_validate_delta with uncaught OverflowError → traceback + exit 1
instead of the exit-2 refusal (float 1e999 was already refused).
F2 LOW — late factory failure leaves an empty pin dir (record
correction; see BUILD-CYCLE-24 item 1 corrections). F3 LOW — exit
paths 3/4/5/idle untested; the 5-vs-6 except-ordering unpinned.
F4 LOW — idle cycles skip CoreLoop gate checks (record note). F5
INFO — no-echo guarantee needed scoping to structured lines.
rev-r3: F1 MEDIUM — check_head never called supersede_head despite
DESIGN-FINAL R3; the copies had already diverged on the "" no-pin
hash spelling (probe B). F2 LOW — append_decision could write an
entry its own _load rejects (self-bricking journal). F3 LOW —
supersession _load gaps (decided_at/recorded_at, candidate hash
"", kind unchecked). Also confirmed sound: the §5.2 binding,
ordering (hash gate before decision gate), SupersedeRequiredError
typing, the append race discipline, the rollback docstring.
rev-r4: five LOWs — F1 validation-order deviation from design-b §2
(envelope parse after membership; matches the mode docstring,
leaks nothing; deliberate reordering, recorded here as the
disposition); F2 the same drift defect as rev-r3 F1; F3
gratuitous-decision shape for initial_anchor (fail-closed,
unreachable); F4 the mode does not thread issuance recovery_of
into supersede_head (inert — burned_unadopted returns earlier,
other reasons ignore the binding; recorded here as the
disposition); F5 post-mirror anchor failure carried the generic
signing wording in the supersede mode.
rev-r5: three LOWs — F1 `.verifier_code` ABSENT on three exit-0
raise paths and the local pre-_run raises (AttributeError on
direct access); F2 the consumer translation trusted the code
string alone (gate on VerifierConfigError as well); F3 the
supersede_decided journal append unwrapped (raw OSError would
escape the hook's typing). The not-a-retry argument was attacked
including the append race and HELD (append_consumption re-runs
check_head on fresh entries before appending, so a
SupersedeRequiredError from the commit call is still provably
pre-commit).

## Forced dissent (rev-r6, 0.35) — preserved

The dissent was about claim scope, not code care: (1) item (1)'s
gap "moved up one level" — nothing runs the runner (no deploy
wrapper/cron; shipcheck remains the sanctioned run_one_cycle
caller without the hooked loop) and the demo is still against a
byte copy with the real state hash asserted unchanged; (2) item
(2) conceded genuinely closed; (3) the supersede decision is NOT
separate in an external sense — PinAdopter auto-fires exactly one
ceremony_supersede with the SAME operator id, same channel, no
human step, no per-operator credential; Option A as built adds
auditability + binding, not an independent check, and design-b
redefined "separately authorised" without flagging the narrowing;
(4) claim honesty — the qualifier lived in docstrings while titles
said "production entry point"; 1678-green partly re-measures
re-pinned expectations; (5) the supersession journal is
authoritative yet unanchored; (6) blast radius on the shared spine
and the new step-(6b) failure surface for ordinary consumes;
(7) DESIGN-FINAL R3 never named the receipt key set. Flip
conditions: a real invocation path OR an explicit claim downgrade
in the summary lines; disclose the auto-fire flow to the externals
as the supersede headline and get seat-gpt's ratification (or make
the decision genuinely out-of-band); state supersede closure as
conditional on the unanchored-journal residual; a differential
note + the corrupt-journal consume test; name the receipt key set
in the record.

## Fix round

All rev-r2/r3/r4/r5 findings fixed in code (see BUILD-CYCLE-24):
the OverflowError refusal + regression test; exit 3/4/5/idle
subprocess tests (exit 5 via a genuine flock-seam burn);
check_head structurally unified on supersede_head + a 16-case
drift-equivalence battery; append_decision shape validation;
supersession _load coherence (kind, decided_at == recorded_at,
hex64 candidate hash); initial_anchor excluded from supersede_head;
mode-accurate anchor-failure detail; `.verifier_code = None` on
every codeless client raise; the translation gated on
VerifierConfigError; the supersede_decided append wrapped to
PinAdoptionBurned; ordinary-consume pins for absent/corrupt
supersession journals. Record-only dispositions: rev-r2 F2 (pin
dir correction, in BUILD-CYCLE-24), rev-r2 F4 (idle gate note, in
BUILD-CYCLE-24), rev-r4 F1 (deliberate parse-order note, above),
rev-r4 F4 (inert sentinel threading, above), DESIGN-FINAL receipt
adjudication note (canonical set named; the draft spelling in
coordinator seat briefs was never implemented).

Probe-B ruling (rev-r3, re-review): unifying on the predicate's
semantics — "agree on offering" — is ACCEPTABLE and the
conservative direction is not required: (a) the corner is
unreachable by construction (append_consumption writes "" only
with old seq None; the signing layer refuses to mint an envelope
whose old-pin hash is ""); (b) "" carries zero hash information and
is decisive only when it is the sole record for that seq, making
the corner semantically identical to the already-accepted
unrecorded-seq residual (i); (c) in production the consumption
journal is externally anchored, so a hand-crafted entry breaks
anchor currency; and even in the offered shape a journaled,
§5.2-bound decision is still required with the candidate strictly
ahead — no regression or replay is enabled.

## Re-review (subject `cycle-24-part1-rereview`)

| seat | score | verdict |
|---|---|---|
| rev-r2 | 0.96 | SHIP |
| rev-r3 | 0.95 | SHIP |
| rev-r4 | 0.95 | SHIP |
| rev-r5 | 0.95 | SHIP |
| rev-r6 (dissent) | 0.78 | SHIP — provisional only |

rev-r1's scope (item 2) was untouched by the fix round; its blind
SHIP 0.94 stands. On the open question — whether disclosure of the
auto-fire flow as the external brief's headline + seat-gpt's
ratification of the §8 reading suffices to ship part 1
provisionally — the vote was 5 of 5 YES (rev-r6's yes is the
conditional one below). rev-r2 additionally mutation-tested the
runner's except-ordering (swapping the handlers fails the exit-3/4
tests) and probed 13 further unrepresentable-delta shapes, all
clean refusals. rev-r5 probed all four local raise paths for
`.verifier_code` directly. rev-r3 re-probed probe F boundaries and
the _load gaps independently.

rev-r6's re-review judgement, preserved: conditions (1), (2), (3)
and the note half of (4) are satisfied-FOR-PROVISIONAL on the
coordinator's record commitments (the summary-line qualification
now stands at the head of BUILD-CYCLE-24.md and this record);
condition (5) and the corrupt-journal test are fully satisfied.
Two new notes: (i) the step-(6b) read makes the unanchored
supersession journal an availability dependency of ordinary
consumes — recorded in Addendum 4 and in this record's summary;
(ii) the provisional label must not be dropped on the strength of
the re-review alone, only on inspection of the written records and
the external round. If the external seats reject the §8 reading,
the supersede closure reopens without a new internal round being
needed to re-hold it.

## Differential note (rev-r6 condition 4)

Pre-existing test files whose EXPECTATIONS changed in part 1
(re-pins, each individually motivated in the build seats' reports):
tests/test_trust_wiring.py (mandatory key at every call site),
tests/test_trust_lint.py (one allowlist entry),
tests/test_trust_consumption_schema_v2.py (v1-issuance sentinel
re-pin), tests/test_trust_ceremony_consume.py (sentinel re-pin +
the two new supersession-journal pins),
tests/test_signing_pin_ceremony.py (T8 fixture consumer),
tests/test_signing_ceremony_recovery.py (adopter fixtures),
tests/test_trust_pin_adoption_crash.py (scenario-6 supersession
tail). Every other pre-existing test passed unmodified. New test
files: tests/test_trust_runner.py (12),
tests/test_trust_ceremony_supersede.py (49),
tests/test_trust_supersede_adopter.py (6). Totals: 1620 → 1696 OK
(skipped=28), coordinator-verified on the final tree.
