# Blind review brief — Cycle 17: ship-tx journal anchoring

For external seats seat-gpt / seat-gemini. No internal verdicts
or scores are included in this brief.

## Context

Cycles 14+15+16 remain HELD, provisional: their external FIX
converged on pin-ceremony authority being circular (operator
list and evidence both caller-supplied). That fix needs an
owner decision on extending the Protected Gate's scope, so
cycle 17 does not touch it and does not touch any protected
path (eval/, core/, oversight/ unchanged). Cycle 17 instead
closes a different, explicitly-deferred gap: the ship
transaction journal's own head was unpinned (its module
docstring called pinning "future work"), while the signing
and ship ledgers have had external head anchoring since the
trust-boundary cycles.

## What was built (trust/anchoring.py, trust/shiptx.py,
trust/shipcheck.py)

1. `ANCHOR_KINDS` gains `"ship-tx"`. All anchor operations
   (initialise / update / force_reanchor / verify) are generic
   over HashChainJournal, and ShipTxJournal is one, so no
   other anchoring change was needed. The tx journal shares
   the ship ledger's directory, so its anchor inherits the
   outside-that-directory placement rule and must be a
   distinct path from the ship anchor.
2. `ShipTxJournal.recover()` gains `tx_anchor_path=None`
   (keyword, default off = prior behaviour exactly). When
   supplied, the tx journal's anchor is verified BEFORE any
   transaction is settled, under the same classification as
   the ship ledger's anchor: chain-mismatch reasons
   (anchor_head_not_in_chain, anchor_ahead_of_journal,
   anchor_kind_mismatch) park every non-terminal transaction
   at ANOMALY; all other failures (missing, malformed,
   unreadable, inside-dir path) are non-destructive per-tx
   error outcomes. When both anchors are supplied they
   combine park-over-error, and error messages label each
   reason by its anchor ("ship: …" / "ship-tx: …").
3. Same-path guard: passing the SAME file for both anchor
   paths is provably a caller wiring error in-process, so it
   is reported as an operator error instead of letting the
   inevitable kind mismatch park every transaction. A
   DIFFERENT file with the wrong kind still parks: on disk it
   is indistinguishable from a substituted anchor.
4. Deleted-journal surface: if the tx anchor carries
   chain-mismatch reasons but the journal contains no
   transactions at all (the journal file deleted outright
   loads as empty), recover() raises AnchorError instead of
   returning an empty outcome list that would read as a clean
   recovery. Transactions that exist but are all terminal are
   untouched as usual.
5. `recover_ship_tx` in trust/shipcheck.py forwards the new
   keyword. Recovery never advances either anchor; docstrings
   state the resulting stale-anchor rollback window, the
   unkeyed-anchor limit (rewriting journal + anchor together
   defeats it), the one-trust-location limit for two anchors
   in one external directory, and the cross-wired-anchor
   ANOMALY risk.

## Test evidence

- New tests/test_trust_shiptx_anchoring.py: 41 tests —
  ceremony over a ShipTxJournal (genesis pin, nonempty
  refusal + ceremony flag, double-init, monotonic update,
  stale-prefix verifies, missing/bad-kind), kind mismatch in
  both directions, truncation / deletion / replacement
  rollback, inside-dir placement refusal, recovery parks
  (head-not-in-chain, kind mismatch, ahead-of-journal on a
  truncated journal with a live transaction), the
  deleted-journal raise, operator errors (missing + retry
  succeeds, malformed, inside-dir, same-path), proceeds cases
  (valid, stale, omitted = back-compat, shipcheck wrapper),
  combined anchors (both valid, tx park, park-beats-error, tx
  operator error non-destructive), and the war-room fix round
  (same-file in both directions, symlink alias, all-terminal
  raise, discriminating wrapper cases, recovery never
  advances the anchor, force_reanchor/audit for the new kind,
  both-operator-errors labelling, ship-park source).
- Targeted suites (anchoring, shiptx, shiptx recovery,
  shipcheck, crashlab, wiring, v2 wiring): 231 tests OK.
- Full suite: 1228 tests OK (skipped=26), baseline 1187.

## Questions for the seats

1. Is the same-path operator-error exception sound, or does
   it open a way to dodge a genuine kind-mismatch park?
2. Is raising AnchorError for the deleted-journal case the
   right surface, given recover()'s per-transaction isolation
   contract everywhere else?
3. Does anything over-claim what an unkeyed, same-location
   second anchor proves?
