# Re-review seat rr-r6 (forced dissent, re-check) — cycle 28 fix round

Regression sweep: test_trust_pin_adoption* 20 OK, test_trust_runner*
13 OK, test_cycle28* 23 OK.

Counterexample re-run (finding 2): the exact duplicate-id scenario
now raises SigningError (duplicate authorisation_id); duplicate-seq
also raises; controls with distinct ids behave correctly (excuse
binds to the head entry by identity).

Finding-by-finding: 1 CLOSED (runner wires both providers in
main()); 2 CLOSED (verified by adversarial re-run; test_21 pins it);
3 CLOSED as a stated trust assumption honestly recorded (ledger load
recomputes the hash chain; tail-truncation resistance rests on the
external anchors verified at verifier startup; module docstring
states the scope); 4a CLOSED (excuse can only cover the single head
entry); 4b OPEN — recorded residual, non-blocking (no repair
procedure shipped; accepted as the same class as the cycle-14
corrupted-pin-store operator-recovery residual; the refusal IS the
detection failing closed); 5 CLOSED (genesis bound verified in the
ceremony layer: initial_anchor refused against a non-empty journal
by check_head, so baselining proceeds only via attested-loss
reasons; test_19 pins reconciliation is not the refuser);
6 CLOSED (withdrawn on re-examination — pair coverage is over the
full 4-tuple; relevance ignoring the old side only widens
detection); 7 OPEN — judgement dissent stands (anchoring), not a
defect and not blocking; 8 CLOSED (failing-first corrected; new
tests 19/20/21 pin the demanded cases).

Caveat: the genesis bound and 4b residual rulings must actually be
written into the cycle's review/BUILD record before the cycle is
filed as closed. [Coordinator note: done — see
internal/REVIEW-CYCLE-28.md §Fix round and
internal/BUILD-CYCLE-28.md residuals.]

"My original FIX drivers (findings 1, 2, 5) are genuinely closed."

VERDICT: SHIP 0.85
