# Blind review brief — Cycle 30

What was built: one new test in tests/test_trust_supersede_adopter.py
(test_wired_resume_repends_after_head_moves_ahead) plus an optional
wired=False kwarg on that suite's make_adopter that forwards the
cycle-28 history-reconciliation providers. No production code changed.

Background: in the wired (production) composition, reconciliation
runs before adoption. Prior cycles pinned: a fresh wired attempt
beyond the consumption head refuses (exit 6); at the head's exact
pair it lands as a recovery (exit 0). Open question: is
supersession-pending reachable at all in the wired composition?

Design decisions:
1. Three independent traces concluded no fresh wired shape reaches
   pending; the only seam implies a pre-existing pending entry.
2. The test seeds a pending state with a single (non-cap) burn,
   journals a real supersession decision bound to the retained
   envelope, moves the head strictly ahead of the candidate
   (sequence 7 vs candidate 5), then makes ONE wired attempt with
   no approval available.
3. Asserted outcome: PinSupersessionPendingApproval re-raised for
   the same envelope; authorise_calls 0, supersede_calls 0,
   consume_calls 1 (pre-commit refusal); consumption count (3) and
   supersession count (1) unchanged; pin unmoved at sequence 1;
   pending report still written.

Test evidence: the new test passes standalone. Full suite result
will be recorded after review.

Questions for reviewers: Is the claim "pending is resume-only in
the wired composition" now justified, with this scope? Is the
seeded state a legitimate retained-pending state or an artificial
construction? Any assertion that is vacuous or could pass for the
wrong reason? Should the concurrent-actor residual block closing
the follow-up?
