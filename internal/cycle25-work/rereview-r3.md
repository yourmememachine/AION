# Cycle 25 — RE-REVIEW, seat rev-r3 (adopter side): is F1 fixed?

Scope: the F1 fix in `trust/pin_adoption.py` (`_consume_retained`,
consume-first resume in `_resume_pending`), the two new tests in
`tests/test_trust_supersede_adopter.py`, and the runner adds in
`trust/runner.py` / `tests/test_trust_runner.py`. No code modified.

Tests run by this seat (unittest):
`tests/test_trust_supersede_adopter.py` +
`tests/test_trust_runner.py` — **23 tests, OK**; plus
`tests/test_trust_pin_adoption_crash.py` +
`tests/test_trust_pin_adoption.py` — **20 tests, OK** (no
regression). Four additional probe scenarios were run against the
real-verifier fixture (probe script kept out of tree, in /tmp);
their outcomes are reported as P1–P4 below.

---

## 1. F1 as filed — FIXED, and the named tests prove the named shapes

- **Case (c), in-attempt `ledger_failed`:**
  `test_ambiguous_decision_response_lands_consume_no_second_decision`
  passes as specified — the `AmbiguousSupersedeClient` performs the
  real `ceremony_supersede` (decision committed verifier-side) and
  then raises `VerifierConfigError` with
  `verifier_code="ledger_failed"`; the SAME attempt falls through
  to `_consume_retained` and lands: pin seq 5,
  `supersede_calls==1`, `consume_calls==1`, `authorise_calls==0`,
  exactly one decision journaled (bound to the presented
  approval's id), approval file moved aside. This is exactly the
  step-(10) shape F1 named.
- **Case (a), `supersede_decided` resume:**
  `test_supersede_decided_entry_resumes_consume_first_no_approval`
  passes — decision journaled by a simulated earlier attempt, its
  `supersede_decided` line present, approval file gone; the next
  attempt lands the consume with `supersede_calls==0`,
  `authorise_calls==0`, `consume_calls==1`, still exactly one
  decision. No approval lookup, no second decision.
- **Case (b), `ceremony_supersede_unproven` after presentation:**
  implemented in the same fall-through (verifier_code check in
  `_resume_pending`) and its safety is probed at P4 below.
- **Failed `supersede_decided` append no longer burns:** the
  append is wrapped in `except OSError: pass` and the attempt
  proceeds to the consume regardless; the code comment correctly
  notes a later attempt re-derives consume-first via the
  unproven fall-through. One composition I verified by reading
  rather than by test: crash after the decision lands but before
  the consume, WITH the decided-append also lost, leaves no
  `supersede_decided` phase and an empty inbox → next attempt
  re-pends with zero verifier calls; recovery then requires the
  approver to mint a fresh approval, whose presentation refuses
  `unproven` (prior decision, verifier step 8) and lands via
  case (b). That route exists and is sound — it costs a second
  approver act for a decision already made, but it is not a
  strand. Acceptable.
- `_consume_retained` is genuinely exactly-one-consume, and a
  supersede-required refusal from it returns the movement to
  pending via `_stop_at_pending` (never burned) — probed at P3.

## 2. Case (b) cannot consume against a different envelope's decision — PASS

Two independent reasons, both checked:

- The verifier's consume mode looks the decision up from its OWN
  supersession journal keyed by the PRESENTED envelope's
  `authorisation_id` (`verifier_main.py` step (6b)); the caller
  never supplies a decision. `check_head` then binds the found
  decision field-by-field to this envelope AND the current head
  (`ledger.py`), raising `HeadRegressionError` on any mismatch.
  The pre-existing
  `test_decision_for_different_candidate_does_not_land` pins this
  at ledger/client level.
- Probe P4 (this seat): decision request refuses
  `ceremony_supersede_unproven` with NO decision in existence
  (the stale-binding shape — `unproven` is a single code covering
  several gates, not only prior-decision). The fall-through
  consume ran exactly once, refused supersede-required
  pre-commit, and the movement returned to
  `PinSupersessionPendingApproval`: pin unmoved, consumption
  count unchanged, zero decisions. So when `unproven` does NOT
  mean "a decision exists for this envelope", case (b) degrades
  to a re-pend with a fresh report — never to a landing, never
  to a burn. The approval presented in case (b) is additionally
  selected by `replacement.authorisation_id ==` the retained
  envelope's id, so the presentation itself is same-envelope.

## 3. Consume-first with head moved and NO decision — PASS (P3)

Probe P3: a `supersede_decided` journal line present but no
verifier decision ever journaled, head unmoved. Resume goes
consume-first (0 supersede, 0 authorise, 1 consume), the consume
refuses supersede-required, and the outcome is
`PinSupersessionPendingApproval` — pin unmoved, nothing
consumed. The claimed fallback holds: the phase line is a
detection aid, and a consume-first attempt against a
non-existent decision re-pends instead of stranding or burning.

## 4. F2 (blocker, availability): concurrent head move AFTER a decision strands in a Burned loop — the claimed behaviour does not hold

The fix's claim (module docstring and `_consume_retained`'s
comment): a decision that does not cover the current head —
"e.g. the head moved concurrently" — yields a supersede-required
refusal from the consume, hence pending again against the new
head. That is true only when NO decision exists for the
envelope (P3/P4). When a decision IS journaled for the envelope
and the head then moves, the verifier does not emit
`ceremony_supersede_required`: `check_head` finds the decision,
its binding check against the CURRENT head fails, and it raises
`HeadRegressionError` ("a decision minted against a head that
has since moved is inert") → verifier code
`ceremony_head_regression`. The client consumer translates ONLY
`ceremony_supersede_required` into `CeremonySupersedeRequired`;
head-regression wraps as a generic `SigningError`, so
`_consume_retained` classifies it `PinAdoptionBurned`.

Probe P2 (real verifier): pending movement driven as in the
suite, real decision journaled, `supersede_decided` line
appended, then the head moved concurrently (a fresh envelope
whose old pin is the head pair @3 consumed, advancing the head
to @5 under a different hash).

- Resume attempt 1 (consume-first): **PinAdoptionBurned** — not
  pending. supersede 0, consume 1, authorise 0.
- The approver then minted a FRESH approval bound to the NEW
  head for the retained envelope and placed it in the inbox.
  Resume attempt 2: **PinAdoptionBurned again, and the fresh
  approval was never presented** (`supersede_calls==0`) —
  because case (a) consume-first intercepts BEFORE the approval
  lookup on every attempt while the `supersede_decided` phase
  persists.

So in precisely the sub-case the original review flagged, the
movement is stranded in a Burned loop and the one artefact that
could obtain a new decision against the new head is unreachable.
No safety property is violated (nothing is decided or consumed
without an approval; the stale decision is correctly inert
verifier-side), but the adopter-side classification and the
intercept order defeat recovery. Narrow fix direction
(adopter-side only): a PRE-COMMIT refusal from a consume-first
attempt (head-regression included) should not be terminal
`Burned` while an approval path remains — e.g. fall through to
the approval-lookup path in the same attempt when the
consume-first consume refuses pre-commit, or return to pending
WITHOUT the `supersede_decided` short-circuit once the journaled
decision is known-stale, so a fresh approval can be presented.
(The hash-binding head-regression shapes must stay refusals for
a FRESH ceremony; the distinction needed is resume-of-a-decided
movement vs first presentation, which the pending entry already
encodes.)

## 5. F3 (blocker, availability): consume-commit loss ON the resume consume re-strands — the genuine-burn exclusion's premise no longer holds

Probe P1: resume with a genuine approval; the client consumer
calls the real consume (the consumption COMMITS verifier-side)
and then raises, simulating the crash/lost-response window at
the consume itself. First attempt: `PinAdoptionBurned`, as
designed — but the consumption journal now has 5 entries and the
pair is lost. Every subsequent attempt: `PinAdoptionBurned`
again, each making exactly one consume call that the verifier
refuses `ceremony_already_consumed`, pin stuck @1.

Why there is no exit: `_find_pending_supersession` keeps
intercepting this candidate/old-pin (the adopter journal never
gains a `consumed` phase — the Burned is raised inside
`_consume_retained` before the append), and
`_genuine_burn_entries` excludes a pending ceremony with no
`consumed` phase, so the ordinary `burned_unadopted` recovery —
which is exactly how a normal ceremony survives this same
window — never engages. The predecessor review accepted that
exclusion on the premise "a pending ceremony's envelope is
provably unconsumed"; the F1 fix invalidates the premise,
because a resume consume can now commit while the journal still
shows no `consumed` phase. Narrow fix direction: on a
`ceremony_already_consumed` refusal from `_consume_retained`,
the verifier has CERTIFIED the consumption — append the
`consumed` phase to the pending journal before raising Burned,
so the ceremony becomes a genuine unadopted burn and the
standard recovery route takes over on later attempts. (The
client consumer currently wraps non-supersede codes into a
plain `SigningError`, so the code must be surfaced or matched
for this — plumbing, not design.)

## 6. The predecessor's non-blocking adds — all landed

- Runner exit-7 test now exists
  (`test_adopt_step_supersession_pending_is_exit_7`) and passes;
  the exit-7 line in `trust/runner.py` now carries
  `report_written`. §5's coverage gap is closed.
- The stale cycle-24 paragraph in `trust/client.py`'s
  `ceremony_consumer` docstring is gone; the text now describes
  the cycle-25 stop.
- The single-file inbox move-aside asymmetry is documented in
  the module docstring and in `_find_supersession_approval`.

---

## Summary

F1 as filed — the decision-side ambiguity window
(`ledger_failed` in-attempt, lost decision response,
`supersede_decided` resume, decided-append failure) — is
genuinely fixed, with regression tests that pin the exact
counts F1 demanded, and case (b) is proven safe against
cross-envelope decisions (P4 + the verifier's authorisation-id
keying). No safety property regressed anywhere probed. But two
adjacent windows in the same resume machinery strand the
movement permanently, both reproduced against the real
verifier: F2 (head moves after the decision → head-regression
misclassified as Burned, and consume-first makes the fresh
approval that would fix it unreachable) and F3 (consume commit
whose response is lost on a resume → already-consumed Burned
loop, with the genuine-burn exclusion blocking the standard
recovery). Both are narrow and adopter-side; neither requires
touching the authorisation core.

Verdict: FIX (0.74)
