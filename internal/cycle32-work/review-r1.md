# Cycle 32 — War-room review R1 (correctness, blind)

- **Verdict: SHIP**
- **Score: 0.92**
- Scope reviewed: `git diff` only — `trust/shiptx.py` (post-settlement
  re-verification), `tests/test_trust_shiptx_anchoring.py` (+10 tests),
  `docs/RECOVERY-CONTRACT.md`. No code/tests edited by this reviewer.
- Verification run by this reviewer: `python3 -m unittest
  tests.test_trust_shiptx_anchoring` → **Ran 68 tests, OK** (58 baseline
  + 10 new cycle-32 tests, consistent with the brief's stated baseline).

## Claims verified against the code

1. **Returned non-park reasons now surface post-settlement — CONFIRMED.**
   `trust/shiptx.py:1010-1021` (ship) and `trust/shiptx.py:1036-1038`
   (ship-tx): a returned reason that is not in `ANCHOR_PARK_REASONS`
   (`trust/shiptx.py:341-343`) and was not in that anchor's initial
   reasons is appended as `(f"<source>: {r}", None)`. The `None` marker
   routes it through the existing error channel at
   `trust/shiptx.py:1052-1076`: error-only → plain `AnchorError` with
   `.outcomes` attached; mixed with a new park reason →
   `JournalIntegrityError` with the label in `.anchor_errors`
   (`trust/shiptx.py:1069-1070`), never in `.reasons`. This matches the
   documented contract in `docs/RECOVERY-CONTRACT.md:89-98`.

2. **Per-anchor dedup is genuinely per-anchor — CONFIRMED.**
   The ship branch tests membership in `ship_reasons` only
   (`trust/shiptx.py:1011`) and the tx branch in `tx_reasons` only
   (`trust/shiptx.py:1037`); neither consults the other anchor's set.
   Those are the initial verdict tuples captured at
   `trust/shiptx.py:817-833`. The park-first `if`/`elif` ordering is
   sound: a repeated park reason fails both branches (it is in
   `ANCHOR_PARK_REASONS`, so the `elif` guard excludes it), and a
   repeated non-park reason fails the `elif` membership test.
   `test_post_returned_reason_on_other_anchor_is_new` proves the
   cross-anchor case is NOT suppressed; 
   `test_post_returned_same_reason_pre_and_post_no_raise` proves the
   same-anchor repeat IS suppressed and the original per-tx error
   outcome is preserved.

3. **"Any non-park string = operator error" is consistent, not new
   overreach — CONFIRMED.** Pre-settlement classification already
   treats every non-park reason as an operator error
   (`trust/shiptx.py:856-861`), and the real `verify_anchor` in
   `trust/anchoring.py` returns only `anchor_malformed` /
   `anchor_missing` / `anchor_missing_established_ledger` on this
   channel. `test_post_returned_unknown_reason_is_operator_error`
   therefore pins intended forward-compatible behaviour.

4. **Within-run dedup — CONFIRMED.** `trust/shiptx.py:1043-1045`
   dedups `new_park` by `(label, reason)` pair via `dict.fromkeys`;
   identical labels from different anchors cannot collide because the
   label carries the source prefix.

5. **Settlements stand and outcomes ride the raise — CONFIRMED by
   tests.** The new tests assert `COMMITTED` state after the plain
   raise, `.outcomes` contents on the plain raise (including `()` when
   there were no settlements), and `ANOMALY` outcomes preserved in
   `test_pre_park_plus_post_returned_error_stays_plain` (a pre-existing
   park does not upgrade a post-only error to `JournalIntegrityError`
   — correct, since JIE fires only on a NEW park reason).

6. **Test quality is high.** 10 tests cover: malformed-only,
   missing-established-only, mixed park+returned-error (with exact
   `.reasons` / `.anchor_sources` / `.anchor_errors` separation),
   same-reason suppression, cross-anchor novelty, unknown reason,
   no-settlements, pre-park + post-error, returned+exception both
   surfacing, and — strongest — a real (non-mocked-sequence) anchor
   file corrupted mid-recovery. The gap described in the pre-fix
   contract is genuinely closed, including the real-file path.

## Non-blocking observations (do not hold the ship)

- `docs/RECOVERY-CONTRACT.md:83-88`: the lead paragraph of item 2
  still describes only exception-path failures entering
  `.anchor_errors` / raising plain `AnchorError`; the cycle-32
  paragraph at lines 89-98 corrects/extends it. Read together they are
  accurate, but a future tidy-up should fold the returned-reason case
  into the lead paragraph so the first read is not stale.
- Coverage gaps, low risk because the code path is generic over any
  non-park string: no test for bare `anchor_missing` post-settlement
  (only `anchor_missing_established_ledger`), no test returning a
  duplicated reason inside a single post-settlement tuple (the dedup
  at `trust/shiptx.py:1045` is untested directly), and no error-only
  test where BOTH anchors newly return non-park reasons in the same
  run (aggregation is covered only via the returned+exception mix).
- Pre-existing, not introduced here: if both anchors newly return the
  same park reason post-settlement, `JournalIntegrityError.reasons`
  at `trust/shiptx.py:1065` would list the bare reason twice (labels
  differ, bare reasons do not dedup). Out of this cycle's scope.

## Conclusion

The fix is minimal, symmetric across both anchors, reuses the
established error channel and label conventions, and the dedup
semantics match both the design brief and the pre-settlement
classification. No correctness defect found. **SHIP (0.92).**
