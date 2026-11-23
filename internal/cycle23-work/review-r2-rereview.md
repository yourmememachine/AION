# Cycle 23 — war-room RE-REVIEW rev-r2 (fix round)

Lens: verify my own first-round findings (F1–F4) against the
fix round, and re-judge the supersede rule AS NARROWED.
Suites run this round: test_trust_pin_adoption_crash +
test_trust_consumption_schema_v2 + test_signing_pin_ceremony
(98 tests OK); test_trust_pin_adoption_crash +
test_trust_consumption_schema_v2 + test_trust_ceremony_consume
(74 tests OK); ConcurrentRecoveryRaceTests x5 (5/5 OK).
Plus one mutation experiment in a throwaway copy (below).

## Verdict: SHIP — score 0.92

## F1 (was MEDIUM) — CLOSED, isolation proven by mutation

test_t8_composed_supersede_adopt_refusal_ahead_variant
composes the real path end to end: the seq-7 envelope
(old=seq1, candidate=seq7) consumes through the real
ledger-backed fixture consumer against a seq-4 head — i.e.
through check_head's supersede branch, including the new
hash binding (old seq 1 is journal-recorded in that fixture
journal and the claimed hash is the genuine one, so the
binding passes) — reanchor_pin returns (pin7, rec7), and
PinStore.adopt(pin7, rec7, expected_old_pin=pin6) against a
store whose live pin is seq 6 must refuse, leaving the pin
at 6. It does.

Isolation of the refusing layer: I read adopt's order in
signing/pin_store.py — CAS (current != expected ->
PinMovedError), non-regression (7 > 6 passes), record-target
match (rec7's target == pin7, passes), then context binding
via verify_ceremony_record(expected_old_pin=current_pin).
To prove no earlier or later layer is doing the work, I
mutated a throwaway copy of the tree: the binding call was
rewired to expect the record's OWN old pin (binding made
vacuous; CAS, non-regression, target match, replay and
prospective-consistency checks all left intact). Result:
exactly one failure in the 56-test ceremony suite — this
test, with "SigningError not raised": the adoption LANDS
once the binding is neutralised. So in the unmutated code
CAS passes, non-regression passes, and only the context
binding refuses. The fix seat's claim is verified, not just
asserted. This also retroactively mutation-pins the binding
for the ahead shape at the composed level, closing the gap
my first round found in T8-prime's attribution.

## F2 (was MEDIUM) — CLOSED, genuinely concurrent, non-vacuous

ConcurrentRecoveryRaceTests uses the fork multiprocessing
context: two child PROCESSES, each constructing its own
CeremonyConsumptionLedger over the SAME journal dir, released
by a shared ctx.Barrier(2), each appending a DISTINCT
burned_unadopted envelope bound (recovery_of) to the SAME
primary burn. Assertions are exact and outcome-shaped:
sorted outcomes == ["AlreadyConsumedError", "ok"]; the
journal holds exactly 2 entries; exactly one recovery entry,
bound to the burn's authorisation_id, at depth 1. The test
is non-vacuous: if exactly-one broke, both appends landing
(3 entries / 2 recoveries), the loser surfacing any other
exception class, or a wrong depth would each fail it. It
passed 5/5 repeat runs (~0.3 s each), so it is not flaky in
practice. One honest caveat, not a blocker: the barrier
synchronises the start, but no test can guarantee which loser
path fires in a given run — flock-serialised save-freshness
failure followed by append_consumption's reload-retry
re-derivation, or post-winner re-derivation directly. Both
paths converge on the asserted outcome by construction,
which is why the test is deterministic; the DESIGN-FINAL R3
"race-tested" wording is now accurate for the property it
names (two processes, one journal, exactly one lands).

## F3 (was LOW) — CLOSED, wording accurate against the code

check_head's docstring now states the narrowed scope exactly
as coded, and I verified each clause against the narrowed
implementation: (a) burned_unadopted exclusion — a
non-recovery burned_unadopted envelope never rides supersede
and is never reclassified as a primary (ahead ->
HeadRegressionError in the explicit branch; at the head
target -> AlreadyConsumedError and behind -> regression via
the candidate checks above it); (b) journal-known old-pin
seq is hash-bound — the code builds the recorded-hash set
from every entry's (new_cycle_seq, new_payload_hash) and
(old_cycle_seq, old_payload_hash) and refuses when the set
is non-empty and the claimed hash is not in it; (c) residual
(i) is named verbatim: an old-pin seq NOT recorded in the
journal cannot be hash-checked by the verifier, and
adoption-side context binding is named as the control —
which F1's mutation result now shows is load-bearing in
fact. One sub-wording nuance, not a defect: the scope text
says "the recorded hash" (singular) while the code admits
ANY recorded hash for the seq (set membership). For any
journal the current rules can produce, a seq carries at
most one recorded hash per position, so the singular is
accurate in practice; set membership is also the safe
direction (it only ever refuses hashes recorded nowhere).

## F4 (was LOW) — CLOSED, wording accurate

Residual (ii) in the docstring matches my first-round trace
point for point: the superseded movement's retained pair
remains adoptable against a pin still equal to its old pin;
adoption moves the pin to a genuine ceremonied target behind
the head; the head's own movement then cannot re-consume
(candidate == head target -> AlreadyConsumedError); liveness
resumes at the next sequence via supersede again; no
regression, no replay. "Stall one sequence" is the correct
bound. A future reader will find this named rather than
rediscovering it as a suspected deadlock.

## Supersede AS NARROWED — liveness re-judged

The narrowing only REMOVES shapes (burned_unadopted riding
supersede; fabricated old hash at a journal-known seq); it
adds none, so none of my first-round failed attacks revive.
The liveness case the rule exists for still works, verified
by running the suites: crash scenario 6
(test_scenario6_recovery_chain_cap2_then_terminal) burns a
movement at primary + depth 1 + depth 2 with EVERY pair
discarded, leaving pin seq 7 behind consumed head seq 9 with
no retained pair; the next primary (candidate seq 11) lands
via supersede and the pin jumps past the burned sequence.
Note the hash binding ENGAGES on that very path — old seq 7
is journal-recorded (it was a prior head target) — and passes
with the genuine hash, so the binding costs the honest
adopter nothing. The retained-pair reconciliation segment of
scenario 6 and the schema-v2 supersede tests also pass.
Cap-2 with lineage stands as endorsed in round 1.

## Residual risk accepted

The two named residuals (unrecorded-seq old hash unchecked
at the verifier layer; resurfaced-pair one-sequence stall)
are documented, bounded, and carry no regression or replay.
Score 0.92 rather than higher only for the F2 caveat above
(loser-path nondeterminism is inherent, not eliminable) and
the F3 singular/set nuance.
