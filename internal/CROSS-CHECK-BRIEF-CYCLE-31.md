# Blind review brief — Cycle 31

## What was built
A document, docs/RECOVERY-CONTRACT.md, stating the contract of
ship-transaction recovery as the code implements it today. It
consolidates two earlier build cycles (17: an external anchor pinning
the ship-transaction journal's head; 18: a distinct typed error for
journal-level integrity failures) and corrects their statements to
the current tree, where a later cycle (23) wired the write half of
the flow. No production code changed this cycle; test total is
unchanged at 1814 (skipped=28).

## Design decisions
- The document describes CURRENT state, not the state at cycles
  17/18, and explicitly marks where an older claim became stale
  (the cycle-17 docstring claim that no in-tree caller passes the
  tx anchor path: now false for the write path via an anchored
  record wrapper, still true for the recovery path).
- Contract sections: entry points and return shape; anchor
  verification order (same-file guard, then ship anchor, then tx
  anchor) before any settlement; park-over-error combination of the
  two anchors' failures; the two cases where recovery raises instead
  of returning a list; the typed error's constructor validation and
  handler-order rule; anchor advancement as a caller duty (recovery
  never advances); limits and non-claims (unkeyed anchor, one trust
  location for co-located anchors, ceremony limits, no TOCTOU
  claim, silent empty-list holes as an open design item).
- Known gaps are stated in the document itself rather than hidden:
  unvalidated error attributes, an ad-hoc attribute that does not
  survive pickle, and no test round-tripping one error field.

## Evidence
- Three independent coder traces of the code (correctness, error
  surface, adversarial limits) were reconciled into the document;
  every claim cites a source line or a pinning test in
  tests/test_trust_shiptx_anchoring.py (58 tests).
- State file untouched (hash identical before/after).

## Questions for the reviewer
1. Does any statement overclaim what the code guarantees?
2. Is the stale-claim correction (write path wired, recovery path
   not) the right framing, or does it still mislead?
3. Are the stated limits sufficient for an operator relying on this
   recovery path, or is a material limit missing?
4. Verdict: SHIP or FIX, with a score 0-1.
