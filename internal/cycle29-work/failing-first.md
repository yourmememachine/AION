# Cycle 29 failing-first

Probe test (seat-A shape, expecting the cycle-28 claim):
genesis adopt @13 -> hookless cycles to 15 -> one held-lock
burn 13->15 (exit 4, consumption 2, pin 13) -> wired adopt
attempt with candidate at seq 15, asserted exit 7
(supersession_pending).

Result on the pre-change tree: FAILED as designed —
AssertionError: 0 != 7. The at-sequence attempt exits 0
(recovery lands). The probe was then replaced by the final
test pinning the actual behaviour
(test_adopt_step_at_head_burn_sequence_recovers_is_exit_0).
