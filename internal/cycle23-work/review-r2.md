# Cycle 23 — war-room review rev-r2 (BLIND)

Lens: head-rule soundness — attack the SUPERSEDE RULE (fix-round
relaxation of `check_head` in `trust/ledger.py`) and judge the
CAP-2 re-rule. Baseline 59a656a, working tree as built.
Suites run: test_trust_consumption_schema_v2,
test_trust_ceremony_consume, test_signing_pin_store,
test_signing_pin_ceremony — 126 tests OK.

## Verdict: FIX — score 0.78

The supersede rule itself survives every attack I could mount:
no integrated pin regression, no replay/resurrection, no
double-consume, no depth-cap bypass, no head-derivation
corruption (traces below). CAP-2 bounded-chains-with-lineage is
the right resolution of the GPT/Gemini split. The FIX is for
two MEDIUM test-evidence gaps: the T8′ defence is not pinned at
the composed level it claims, and the "race" test is not a
concurrency test. Both are cheap to close; neither requires a
design change.

## Findings

### F1 (MEDIUM) — T8′: the coordinator's defence is sufficient but misattributed for its own shape, and no composed test pins it

Trace of the T8′ third leg (tests/test_signing_pin_ceremony.py):
head = seq4 (consume 1→4), live pin advanced to seq6, fresh
envelope old=seq1/candidate=seq5. Supersede lets the consume
LAND (cand 5 > head 4, old 1 < head 4, non-recovery) and
`reanchor_pin` returns pin5. The docstring says what prevents
regression of the live pin is PinStore.adopt's context binding,
"pinned in tests/test_signing_pin_store.py".

Checked against signing/pin_store.py `adopt`, in order:
(1) CAS — current pin under flock must equal
`expected_old_pin`; an honest adopter passes pin6, a stale
caller passing pin1 gets PinMovedError. (2) Non-regression —
new_seq 5 < current_seq 6 refuses outright. (3) Context
binding — `verify_ceremony_record(..., expected_old_pin=
current_pin, expected_new_pin=new_captured)` refuses a record
whose old side (seq1) is not the store's pin.

So for T8′'s exact shape the defence is OVERdetermined: leg
(2) alone refuses even if context binding were deleted, and
T8′ itself never calls `adopt` at all — deleting the binding
would not fail T8′. The binding is genuinely load-bearing only
for the ahead variant (stale old=1, candidate=7, live pin=6:
CAS can be satisfied by passing expected=pin6, non-regression
passes 7>6, only the binding refuses). That variant IS
mutation-pinned, indirectly, by pin-store test_13
(old-side-mismatched record, target ahead of the store pin):
without the context-bound verify, test_13's adopt would land
(CAS passes, target matches, prospective consistency passes),
so test_13 would fail if the binding regressed.

Gap: no single test composes the actual T8′ sequence —
supersede consume through the real consumer, then an adopt
attempt of the returned pair against a store whose pin is
ahead, asserting refusal and an unchanged store — and no test
covers the ahead variant (cand 7 vs live pin 6) end-to-end.
The docstring's "pinned in test_signing_pin_store.py" is true
only by composition of two separately-pinned pieces. Fix:
add the composed test (both shapes) or reword the docstring
to name CAS + non-regression as the defence for this shape
and the binding as the defence for the ahead shape.

### F2 (MEDIUM) — the CAP-2 "race" test is sequential; exactly-one under CONCURRENCY is argued, not tested

`test_race_same_burn_exactly_one_then_fresh_recovery`
(test_trust_consumption_schema_v2.py) issues two recoveries
bound to the same primary burn, then consumes them
SEQUENTIALLY (each consume is its own verifier invocation):
winner lands at depth 1, loser raises already_consumed
(its bound recovery_of no longer equals the head's
authorisation_id, lineage derives primary, candidate == head
target), fresh recovery bound to the winner lands at depth 2.
That pins the lineage logic well. It does not exercise
concurrency: no threads, no barrier, no two ledger instances
racing `append_consumption`.

The mechanism argument is sound — I traced it: both racers
reload head H and derive "recovery"; `_save`'s under-flock
freshness check serialises them, the loser's save raises
CorruptLedgerError, `append_consumption`'s retry loop reloads,
re-derives lineage against the winner's head, and raises
AlreadyConsumedError. Exactly-one holds by construction.
But DESIGN-FINAL R3 says "preserved and race-tested (GPT's
cycle-22 requirement)". As built, the requirement is met in
its semantic form (two authorisations, same burn, exactly one
consumption) but the concurrency wording overclaims what the
test does. Fix: add a true concurrent-append race (threads or
subprocesses on one journal dir, barrier release, assert
exactly one entry lands and the loser surfaces
AlreadyConsumedError), or reword R3/the test docstring to
"interleaving-tested; concurrency follows from the
reload-retry + flock freshness construction".

### F3 (LOW) — supersede ignores the old pin's HASH when old_seq < head_seq; reachable shapes are benign but unenumerated in the docstring

`check_head` validates old_hash only at old_seq == head_seq.
A supersede envelope may carry any hash at a behind-head seq.
At the raw ledger level that writes an unverifiable old-pin
claim into the journal. Integrated, it cannot move a pin:
reanchor_pin's strict recomputation runs against the claimed
pin, and PinStore.adopt's context binding compares the
record's old (seq, hash) against the store's actual pin, so a
fabricated hash refuses at adoption. Audit-noise only — but
the supersede paragraph in check_head's docstring should say
the behind-head old hash is unchecked at this layer and why
that is safe, since the old rule refused the whole shape.

Related enumeration check (no defect): a burned_unadopted
envelope issued while its burn was head, then overtaken by a
supersede landing, cannot ride supersede afterwards — its
candidate equals the OLD head target, now behind the new
head, so it refuses as candidate-behind-head. The
primary-lineage derivation for a stale burned_unadopted
envelope is therefore unreachable for issued envelopes; only
direct ledger callers with the recovery_of=None sentinel can
produce it, and they are the documented legacy path.

### F4 (LOW) — resurfaced-pair adoption after a supersede creates a one-sequence AlreadyConsumed stall (self-healing, not unsafe)

Trace: movement H (41→47) consumed to cap, pair discarded;
supersede S (41→52) lands, its pair also discarded (pin still
41). H's pair resurfaces and is adopted via adopt_returned:
CAS (expected 41 == current 41), context binding (record old
41 == store pin 41) and non-regression (47 > 41) all pass —
the pin legitimately moves to 47, a genuine ceremonied target,
even though the head is already 52. At state seq 52 the
adopter then cannot re-consume S's target (S's pending-journal
line names old 41, not the current pin 47, so no
burned_unadopted match; a primary at candidate == head target
refuses AlreadyConsumed). Liveness resumes at seq 53 via
supersede again (old 47 < head 52 < cand 53). No regression,
no replay — but this interleaving (supersede does not retire
the superseded movement's adoptable pair) is not enumerated
in DESIGN-FINAL or the check_head docstring. Record it as a
named residual so a future reader does not rediscover it as a
suspected deadlock.

## Attacks that FAILED (supersede holds)

1. Integrated regression (Q1): PinAdopter.snapshot_and_adopt
   reads the pin fresh from the store on every attempt, so it
   never stages a stale old pin itself; a direct caller who
   does is stopped at adopt by CAS + non-regression + context
   binding (F1). No path found where supersede moves a live
   pin backwards or sideways. Same-seq fork at the head still
   refuses at any candidate position (pinned by
   SupersedeRuleTests.test_supersede_does_not_rescue_fork_at_head
   and the consume-mode supersede test).
2. Replay / resurrection / double-consume (Q2): same
   authorisation_id is refused inside append_consumption's
   retry loop before check_head; a fresh envelope for the head
   target refuses (candidate == head, non-recovery); the
   superseded movement can never be recovered afterwards
   because authorise step (5b) and match_head_burn bind
   recovery to the CURRENT head only — supersede retires the
   old movement permanently, as designed. Distinct-movement
   consumptions via repeated supersede each need a fresh
   authorisation + evidence + operator presentation; that is
   the ordinary primary path's cost model, not a cap bypass.
3. Recovery-exception / depth-cap interaction (Q4):
   supersede is gated on `not recovery` and a recovery by
   construction has candidate == head target, so the two
   exceptions are disjoint. Supersede's own entry is a primary
   at depth 0 for a NEW movement, which correctly gets its own
   bounded recovery budget. Authorise (5b) refuses recovery
   issuance at derived depth >= MAX_RECOVERY_DEPTH, and
   consume re-derives lineage inside the retry loop from
   fresh entries, so no stale-snapshot derivation survives a
   race.
4. Head-derivation corruption (Q5): after a supersede the
   head is a v2 primary (depth read directly, no pair-scan);
   match_head_burn and head_target follow the new head;
   the verifier-mode supersede test pins head_target moving
   47 → 50 and a subsequent behind-head candidate refusing.
   v1-head pair-scan derivation is untouched by supersede
   entries (distinct old→new pairs, and new appends are
   always v2).

## CAP-2 re-rule judgement

Bounded-chains-with-lineage is the right resolution.
Gemini's bricking objection to one-shot was correct and is
answered three ways: depth 2 absorbs a double fault in one
incident; authorise (5b) never issues an envelope that cannot
consume (ceremony_recovery_unproven at the cap); and
exhaustion is not a deadlock — the next sequence takes a
primary chain_gap_recovery, and for a pin stranded BEHIND the
head (the case the exhaustion test, which uses old == head
target, does not cover) the supersede rule is exactly the
missing leg, pinned at ledger level
(SupersedeRuleTests) and through the real verifier modes
(test_trust_ceremony_consume
.test_old_pin_behind_head_superseded_when_candidate_ahead,
old 41 → candidate 50 over head 47). GPT's ratified
exactly-one-success is preserved semantically (F2 is about
the concurrency evidence, not the property). Explicit lineage
in schema v2 replaces pair-scan inference for v2 heads, which
was Gemini's root demand; the pair-scan survives only as the
v1 derivation, correctly scoped.

## Required to flip to SHIP

1. F1: composed supersede→adopt-refusal test (T8′ shape and
   the ahead variant), or the docstring rewording described.
2. F2: a true concurrent race test for append_consumption, or
   rewording of the "race-tested" claim in DESIGN-FINAL R3
   and the schema-v2 test module docstring.
F3/F4 are record-as-residual items, not blockers.
