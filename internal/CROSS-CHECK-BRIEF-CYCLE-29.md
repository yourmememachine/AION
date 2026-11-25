# Cross-check brief — cycle 29 (blind; no internal verdicts)

What was built: one new production-composition test in
tests/test_trust_runner.py,
test_adopt_step_at_head_burn_sequence_recovers_is_exit_0,
plus a claim correction in the comment of the sibling
beyond-head test. No production code changed.

Background: cycle 28 narrowed the known-unadopted head
excuse in history reconciliation to a candidate at the head
entry's own sequence, and its records claimed such a
candidate "can still enter the supersession-pending flow".
A cycle-28 re-review seat noted no wired test pinned that.

Design decisions: three coder seats analysed the shape
blind. The faithful wired shape is: genesis adopt at seq 13,
two test-side cycles to 15, one held-lock adopt that burns
the 13->15 ceremony (exit 4), then a plain wired adopt with
the candidate at seq 15 (the head burn's own sequence).

Evidence: a failing-first probe asserted exit 7
(supersession_pending) for that final attempt and failed
with exit 0. The final test pins the observed behaviour:
the candidate is the burn's exact pair, step (3)
re-presents the retained burned candidate, it classifies
burned_unadopted at recovery depth 0, the recovery consume
lands (consumption 2 -> 3), exit 0 reanchored, pin at 15,
supersession ledger empty, no pending report written.

Questions: (1) Is pinning observed behaviour + correcting
the earlier claim the right closure, or does the
at-sequence pending reach need to exist? (2) Does the new
test actually distinguish recovery-lands from pending and
from reconciliation refusal? (3) Any claim in the new
test's comment that overstates what is pinned?
