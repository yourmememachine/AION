# Review seat rev-r3 (tests & evidence) — cycle 28, blind

Ran the suite: 18 tests, all OK.

VERDICT: FIX 0.60 (reported as "FIX 6")

1. Genuine records — PASS with minor caveats (real reanchor_pin mints;
   test_14's duplicate uses dataclasses.replace — acceptable for a
   validation test but not a genuine record).
2. Excuse controls — one excuse lacks a control: genesis baseline
   (test_13 asserts only genesis_baseline=True). Pair coverage
   (test_06) has no in-test control (minor).
3. test_17 — expectation and comment are honest; the failing-first
   record's description of it is not (see 5).
4a. BLOCKING — supersession excuse via candidate-pair-equals-candidate
    is untested (test_07 exercises only new_authorisation_id-present);
    the pair-covered branch is also untested (no test decision carries
    superseding_old_* fields).
4b. BLOCKING (with 2) — genesis baseline untested through the adopter
    (wired PinAdopter, old_pin None, non-empty journal).
4c. Follow-up, not blocking — provider-from-home freshness not directly
    tested; duplicate authorisation_id in the JOURNAL uncovered;
    test_06 in-test control.
5. Failing-first honesty — FAIL on the behavioural half:
   failing-first.md §2 says test_17 "proceeds to a successful
   re-anchor" (it actually expects PinSupersessionPendingApproval)
   and "passes both before and after the change" (impossible — the
   file failed at import pre-change). The record must be corrected
   and the missing tests added before ship.
