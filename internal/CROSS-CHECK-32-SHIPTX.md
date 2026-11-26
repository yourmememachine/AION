# CROSS-CHECK — Cycle 32 (ship-tx post-settlement), external seats

Brief: internal/CROSS-CHECK-BRIEF-CYCLE-32.md (blind, no
internal verdicts).

## Round 1
- seat-gpt: SHIP 0.96 (ChatGPT, already signed in; conversation
  titled "Blind Review Verdict"). Endorsed per-anchor dedup,
  plain AnchorError for error-only, label format. Checklist:
  (a) confirm no downstream consumer parses anchor_sources
  labels; (b) run the full suite on the modified tree, not the
  baseline.
  Reconciliation: (a) done — the only split of anchor_sources
  text is JournalIntegrityError's constructor validation, and
  returned-error labels never enter anchor_sources (they go to
  anchor_errors, opaque); no downstream parser exists.
  (b) done — 1848 tests OK (skipped=28) by discovery on
  confirming runs; one earlier unidentified flaky failure
  recorded in BUILD-CYCLE-32.md.
- seat-gemini: SHIP 0.88 (Gemini; answered in a new chat without
  sign-in being required). Endorsed per-anchor dedup and plain
  AnchorError with .outcomes. Asks: cross-anchor coverage and
  mixed-case .outcomes assertion; empty-string/None return
  hardening note; .outcomes must read as already-journaled
  settlements.
  Reconciliation: cross-anchor test already existed
  (test_post_returned_reason_on_other_anchor_is_new); mixed
  test now also asserts .outcomes == [COMMITTED];
  verify_anchor returns only literal canonical strings in code
  (no empty/None path); settlements-standing is already stated
  in the contract and the raise messages.

## Round 2
Sent under the 2026-11-26 two-round rule with the reconciliation
summary above.
- seat-gpt: SHIP 0.99, no mandatory fixes. Agreed the dissent
  items are inherited limitations, not this cycle's regressions;
  same-file re-check accepted as a deferred follow-up, not a
  release condition.
- seat-gemini: SHIP 0.97, no mandatory fixes. Note: its round-1
  chat was created anonymously and could not be resumed after
  sign-in, so round 2 ran in a new signed-in chat with the full
  round-1 verdicts and reconciliations restated in the brief.

Final external verdict: SHIP (both seats, both rounds).
