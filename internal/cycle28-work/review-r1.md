# Review seat rev-r1 (core soundness) — cycle 28, blind

Ran the suite: 18 tests, all passing.

Summary judgement: in the production composition (providers built from the
real ledgers, whose loaders enforce unique authorisation_ids, positional
unique seqs, exact key sets and hash chains), no reachable false negative
and no false refusal in recovery, supersede-resume, genesis, or advance
flows. The genuine weaknesses are at the pure-function boundary: the
function claims several bindings ("head-scoped by construction", "fully
bound, never existential", "sorted regardless of input order") that it
does not itself enforce — it inherits them from the ledger loaders.
Defence-in-depth / claim-accuracy gaps, not ship blockers. One dead
constant should be removed or used.

VERDICT: SHIP 0.87

1. Low–Medium (false negative, pure-function only) — head excuse is
   id-based, journal duplicate ids unvalidated: entries [E1(seq 1, id X),
   E2(seq 3, id X)] with known_unadopted=(X,) — E1 is non-head yet excused.
   Unreachable via CeremonyConsumptionLedger.entries() (its _load refuses
   duplicate ids). Fix direction: validate duplicate journal ids, or
   compare entry identity/seq to the head entry.
2. Low–Medium (claim overstated) — _supersede_excused binds only
   abandoned_authorisation_id plus one landed condition; never reads the
   decision's abandoned_old/new fields, never checks the store record
   bearing new_authorisation_id has the decision's candidate pair.
3. Low — relevance at candidate seq compares seq+hash, not the old side;
   equivalence assumed, likely unreachable under head rules.
4. Low (determinism) — sort by seq only, duplicate seqs not rejected;
   stable sort makes order/head depend on input order for that class.
5. Low/info — ID+PAIR coverage is strictly subsumed by PAIR coverage;
   "rule 2 pair-bound" adds no actual constraint; docstring should not
   imply it does.
6. Low — known_unadopted never type-checked (None raises bare TypeError;
   a plain string iterates into a character set); genesis_baseline tested
   for truthiness, not bool. None reachable from PinAdopter.
7. Info (dead code) — _CONSUMPTION_REQUIRED_KEYS defined, referenced
   nowhere; actively misleading. Remove it or enforce it.
8. Verified — minimal key set is safe: real v1 entries carry
   ceremony_id+evidence_hash; the function never reads evidence_hash and
   pair/id coverage is unaffected by their absence.
9. Verified — no false positives in legitimate flows (recovery,
   supersede-resume, genesis, advance/already_current). Wiring caveat:
   consumption provider without supersession provider loses the
   decision-based excuse — worth a docstring note in pin_adoption.py.
10. Verified — validation and determinism basics; no input mutation.
