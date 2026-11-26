# CROSS-CHECK — Cycle 31 external seats

Brief: internal/CROSS-CHECK-BRIEF-CYCLE-31.md (blind, no internal
verdicts). Both seats ran in new conversations on the user's
signed-in accounts.

- seat-gpt — FIX 0.89. No inherent overclaim found; stale-claim
  correction "the correct framing". Required before SHIP:
  operational assumptions around concurrent writers, recovery and
  anchor advancement; explicit durability statement; empty list
  must not read as proof no recovery work exists. Noted it
  reviewed the brief, not the tree; said the verdict becomes
  SHIP ~0.94 if those are already covered.
- seat-gemini — FIX 0.72. Flagged: "contract" framing can
  overstate stability; line citations drift; completeness beyond
  cycle 23 not cross-checked; empty-list semantics, partial /
  non-atomic recovery state, and the unwired recovery-side tx
  verification as an operational risk, not just a docstring note.

Reconciliation: all required items were applied in the fix round
(preamble reworded to "evidenced by", completeness caveat added,
concurrency/atomicity section added, empty-list warning promoted
to the document head, advancement-orphan framing made explicit)
and the internal re-verification seat passed the revised
document. Neither external seat's FIX required production code
changes. Verdict reconciled: SHIP.
