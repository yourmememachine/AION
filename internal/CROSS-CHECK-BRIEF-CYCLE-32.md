# Blind review brief — Cycle 32 (external seats)

## What is being built
Close the post-settlement re-verification gap documented in
`docs/RECOVERY-CONTRACT.md` (Cycle 31): in
`ShipTxJournal.recover()` (`trust/shiptx.py`), both supplied
anchors are re-verified after the settlement loop. Today that
re-verification only surfaces (a) NEW returned chain-mismatch
(park) reasons and (b) NEW exception-path anchor failures.
`verify_anchor` RETURNS operator-error reasons as values —
`anchor_malformed`, `anchor_missing`,
`anchor_missing_established_ledger` — and a returned reason of
that kind appearing only post-settlement is silently discarded:
a mid-recovery swap to a malformed or missing anchor passes
unreported, even though settlements already journaled stand.

## Design decisions under review
1. A returned non-park reason is NEW only if it was not in that
   same anchor's initial returned reasons (per-anchor dedup,
   matching the existing exception-path dedup).
2. New returned non-park reasons are treated exactly like
   new exception-path failures: error-only change raises plain
   `AnchorError` carrying the completed outcomes on
   `.outcomes`; mixed with a new park reason they ride on
   `JournalIntegrityError.anchor_errors`, never in `.reasons`.
3. Label format for a returned reason in messages /
   `anchor_errors`: `"<source>: <bare reason>"` (e.g.
   `"ship-tx: anchor_malformed"`), distinct from the
   exception-path label `"<source>: anchor_error:<exc>"`.
4. Any non-park returned string (not only the three named
   operator reasons) is treated as operator error, consistent
   with the pre-settlement classification in the same method.
5. No change to pre-settlement behaviour, park handling, the
   same-file guard, or the no-park-target raise.

## Evidence
- Failing-first tests were written against the current code
  before the fix (see cycle record for the red/green run).
- Pin file: `tests/test_trust_shiptx_anchoring.py` (58 tests
  before this cycle).
- Full suite baseline: 1814 tests OK (skipped=28).

## Questions for reviewers
- Is per-anchor dedup the right novelty test, or should a
  reason already seen on the OTHER anchor suppress it?
- Is plain `AnchorError` (not a per-transaction error outcome)
  the right surface when settlements may already have landed?
- Does the label format risk confusion with park-reason labels
  in `anchor_sources`?
