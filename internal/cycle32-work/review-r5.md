# Cycle 32 — War-room review R5 (tests)

Reviewer: R5, tests seat (reviewing the test slice, not own code)
Scope: the 10 new tests in `tests/test_trust_shiptx_anchoring.py`
(`JournalIntegrityErrorTests`, cycle-32 block) plus the `_fake_seq`
helper; production diff in `trust/shiptx.py` read only as context.
No code or tests edited by this review.

## Verdict: SHIP — score 9/10

## Evidence run

- `python3 -m unittest tests.test_trust_shiptx_anchoring` on the
  working tree: **68 tests, OK** (58 pre-existing + 10 new; pytest is
  not installed on this VM, unittest is the runner).
- Failing-first check, independently re-run by this seat: the 10 new
  tests were run in a scratch copy (`/tmp/ai-old`) with
  `trust/shiptx.py` reverted to HEAD (pre-fix). Result: **9 FAIL,
  1 pass** — see "Passes on old code" below. The suite is genuinely
  red on the old code and green on the fix.

## Findings

### 1. Fakes RETURN tuples for returned-reason cases — PASS

`_fake_seq` dispatches on type: `isinstance(result, Exception)`
raises, anything else is `return`ed. Every returned-reason case
supplies a tuple, never an exception instance:

- malformed only: `[(), ("anchor_malformed",)]`
- missing: `[(), ("anchor_missing_established_ledger",)]`
- mixed: ship returns `("anchor_malformed",)`, ship-tx returns the
  park tuple `("anchor_head_not_in_chain",)`
- unknown: `[(), ("some_future_reason",)]`
- pre-park + post-error, dedup, cross-anchor, zero-settlement: all
  tuple returns on both calls.

This is the critical authoring rule for this cycle — the pre-existing
mixed test faked the failure by *raising* `AnchorError`, a shape the
real `verify_anchor` never produces for a malformed file, and so
proved nothing about this gap. The new fakes do not repeat that
mistake. The one deliberate exception is correctly separated:
`test_post_returned_and_exception_errors_both_surface` makes the
ship fake *raise* `AnchorError("boom")` while ship-tx *returns*
`("anchor_malformed",)`, and asserts both labels surface
(`"ship: anchor_error:boom"` and `"ship-tx: anchor_malformed"`) —
pinning that the two channels coexist and stay distinguishable.

`_fake_seq` itself is sound: per-kind call counting, sequence
clamped to its last element (`seq[min(seen, len(seq)) - 1]`), so an
extra verification call repeats the last verdict instead of erroring
the fake — the tests are not brittle to call-count drift.

### 2. Real-verify test — PASS

`test_post_real_anchor_corrupted_mid_recovery_raises` does not use
`_fake_seq` at all. It wraps the real `verify_anchor`, overwrites
the anchor file with `b"not json at all"` on the second call
(the post-settlement re-verification; only the tx anchor is
supplied, so the call sequence is deterministic), and delegates to
the real implementation. It asserts exact type `AnchorError`,
`anchor_malformed` in the message, and the tx state `COMMITTED`
(settlement stands). This proves the end-to-end returned path —
real file corruption → real returned tuple → new raise — that the
tuple fakes only simulate.

### 3. Dedup / cross-anchor / zero-settlement — all pinned

- **Dedup (same anchor, same reason):**
  `test_post_returned_same_reason_pre_and_post_no_raise` — fake
  returns `("anchor_malformed",)` pre- and post-settlement; recover
  returns 1 outcome, the outcome's `error` contains
  `anchor_malformed`, and state stays `POST_RECORD_VERIFIED`
  (pre-settlement classification, no post-settlement raise).
- **Cross-anchor (per-anchor, not global, dedup):**
  `test_post_returned_reason_on_other_anchor_is_new` — ship returns
  `anchor_malformed` on both calls, ship-tx gains it only
  post-settlement; plain `AnchorError` raises naming
  `"ship-tx: anchor_malformed"`. A global dedup implementation
  would suppress this and fail the test.
- **Zero settlements:**
  `test_post_returned_error_with_no_settlements_raises` — tx is
  transitioned to `COMMITTED` before recover, so the settlement
  loop has nothing to do; asserts plain `AnchorError` and
  `ctx.exception.outcomes == ()`. The raise is not conditioned on
  settlements having landed.

Also pinned, beyond the asked-for three: mixed park + returned
error is a `JournalIntegrityError` with exact separation
(`reasons == ("anchor_head_not_in_chain",)`,
`anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`,
`anchor_errors == ("ship: anchor_malformed",)`);
pre-existing park + post returned error stays plain `AnchorError`
(not upgraded to JIE) with the `ANOMALY` outcome riding on it; and
an invented future reason string is treated as operator error,
pinning the "any non-park string" classification rather than a
hard-coded list of three.

### 4. Passes on old code — only the intended guard

From the scratch-copy run against pre-fix `trust/shiptx.py`:
9 of the 10 new tests FAIL (mostly `AnchorError not raised`; the
mixed test fails on `anchor_errors == ()` vs
`("ship: anchor_malformed",)`, and the both-surface test fails
because the returned label is absent from the message). The single
pass is `test_post_returned_same_reason_pre_and_post_no_raise` —
the intended dedup guard: on old code the post-settlement returned
reason was silently dropped, which coincidentally matches the
no-raise expectation for an already-seen reason. It is a regression
guard for the dedup rule, not a bug detector, and it is the only
such case. No other new test is vacuous against the old code.

### 5. Minor coverage gaps (non-blocking, do not hold the cycle)

- Bare `anchor_missing` (empty-journal variant) is not exercised
  post-settlement; only `anchor_missing_established_ledger` is.
  The production branch treats all non-park strings uniformly and
  the unknown-reason test pins that uniformity, so risk is low.
- No ship-anchor-only returned-error plain-raise test: the ship
  branch is exercised in the mixed and both-surface tests, but
  never solo the way ship-tx is in the malformed-only test. The
  two branches are symmetric in the diff.
- The within-run dedup line (`dict.fromkeys(new_park)`) has no
  direct test — no fake returns a duplicated tuple such as
  `("anchor_malformed", "anchor_malformed")` in one call.

These are follow-up test additions worth queueing, not FIX items:
none of them leaves the cycle's stated contract (returned non-park
reason, per-anchor dedup, plain-vs-JIE surfacing) unpinned.

## Summary

The 10 tests satisfy the cycle's critical rule — returned reasons
are returned, not raised — include a genuine real-verify corruption
test, pin dedup, cross-anchor novelty, and the zero-settlement
raise, and are 9/10 red on the old code with the sole pass being
the intended dedup guard. **SHIP, 9/10.**
