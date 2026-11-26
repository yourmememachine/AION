# Recovery Contract — Ship Transaction Journal (cycles 17+18, current state)

This document describes the behaviour of ship-transaction recovery
as the code implements it today. "Contract" here means a description
evidenced by code and tests, not a guarantee of stability across
refactors: claims are evidenced by the cited source locations and,
where a pin exists, by tests — a pinning test proves the tested
input/state, not every branch. It consolidates cycles 17 (tx-anchor
anchoring) and 18 (journal-integrity error type), corrected to the
current tree. Cycle 23 later wired the write half of the ship flow;
other cycles touching recovery were not exhaustively cross-checked
for this document.

**An empty result is not proof that no recovery work exists.** See
"Silent-`[]` holes" below before relying on a `[]` return.

## Entry points

- `ShipTxJournal.recover(ledger, loop, *, recorded_at="", root=None,
  anchor_path=None, tx_anchor_path=None) -> list`
  (`trust/shiptx.py:713`), forwarded unwrapped by `recover_ship_tx`
  (`trust/shipcheck.py:507`) — raises propagate to its caller.
  `JournalIntegrityError` is exported from `trust/__init__.py`.
- `root`, when given, is the build tree the manifest is rebuilt
  from; the rebuilt hash must equal the transaction's
  `manifest_hash`. With `root=None` an unfinalised burn past
  CYCLE_RECORDED parks at ANOMALY rather than finalising blind.
- Returns one outcome dict per changed or failed transaction.
  Terminal transactions are skipped, so a re-run over settled
  transactions returns `[]`. ANOMALY is terminal and never
  auto-resolved; it requires human reconciliation. Recovery never
  burns, never re-runs a cycle, and never journals
  AUTHORISATION_VERIFIED; its only ledger write is a completing
  finalise. One transaction's failure is reported in its outcome
  and does not block the others.
- Anchor protection is OPT-IN: both anchor paths default to `None`,
  and on the default path a deleted tx journal loads as empty
  undetectably (`trust/shiptx.py:161`). Nothing in this document's
  anchor sections applies unless a caller passes the paths.

## Anchor verification (before any settlement)

Order (`trust/shiptx.py:803-827`):

1. Same-file guard: if both anchor paths are given and name the same
   file — by `os.path.samefile` (symlink/hardlink-proof), with a
   resolved-path fallback — BOTH verifications are suppressed and
   one operator-error entry is produced. That entry surfaces only
   per non-terminal transaction outcome; with zero non-terminal
   transactions the call returns `[]`. It is never a park. A
   byte-identical copy on a distinct inode is NOT the same file and
   still parks on kind mismatch: file identity, not content.
2. Ship anchor (`kind="ship"`) against the ship ledger.
3. Tx anchor (`kind="ship-tx"`) against this journal.

Classification: park reasons are exactly `JOURNAL_INTEGRITY_REASONS`
(`trust/anchoring.py:145`) — `anchor_head_not_in_chain`,
`anchor_ahead_of_journal`, `anchor_kind_mismatch`. All other anchor
failures (missing, malformed, load errors folded to
`anchor_error:<exc>`) are operator errors.

Combination is park-over-error: any park reason from either anchor
parks ALL non-terminal transactions at ANOMALY and absorbs operator
errors; operator-error-only leaves transactions unmoved with per-tx
`error` outcomes. Reasons are labelled by anchor only when the tx
anchor participates; ship-only callers keep their pre-cycle-17 bare
strings.

## The two raises

Recovery returns a list except in two journal-level cases:

1. **No park target (pre-settlement).** Tx park reasons present and
   zero non-terminal transactions: raises `JournalIntegrityError`.
   Ship park reasons in the same call ride along, labelled. A
   ship-only park with nothing to park deliberately returns `[]` —
   the ship anchor pins a different file, so no transaction of this
   journal is at risk from it. The tx anchor pins THIS journal,
   which is why only it raises.
2. **Post-settlement re-verification.** If at least one anchor path
   was supplied and the same-file case did not fire, each supplied
   anchor is re-verified after settlement. Only NEW evidence counts;
   identical repeats are suppressed. A new park reason raises
   `JournalIntegrityError` carrying the completed settlements in
   `.outcomes` and any accompanying EXCEPTION-path load failures in
   `.anchor_errors` (never in `.reasons`). A new exception-path load
   failure alone raises plain `AnchorError`, also carrying
   `.outcomes`. Settlements already journaled stand in both cases.
   **Gap:** `verify_anchor` RETURNS `anchor_malformed` /
   `anchor_missing*` as values rather than raising, and the
   re-verification loops collect only returned park reasons — so a
   mid-recovery swap to a malformed or missing anchor is silently
   ignored. Only exception-path failures and returned park reasons
   are detected.

Consequence, qualified: `recover()` is not type-idempotent for
tx-anchor evidence — the same tx park evidence parks on run 1 (live
transactions become ANOMALY outcomes) and raises on run 2 (all
transactions terminal). Ship-only park evidence parks on run 1 and
returns `[]` on run 2.

## JournalIntegrityError

`JournalIntegrityError(AnchorError)` (`trust/anchoring.py:159`).
Constructor-validated: `reasons` must be a non-empty deduped subset
of the canonical park set (an operator reason is refused with
`ValueError`); `anchor_sources` must be non-empty, deduped, prefixed
`ship`/`ship-tx`, and its suffix set must equal the reasons set
(set-equality, not positional correspondence). `anchor_source` is
derived: the single prefix, or `"combined"`. `__reduce__` round-trips
through a restoring constructor that re-validates on load (the
round-trip test uses a valid instance; re-validation on load is a
code property, not a pinned behaviour).

Handler-order rule: catch `JournalIntegrityError` BEFORE
`AnchorError`, or the distinction is silently lost. Known gaps:
`outcomes`/`anchor_errors` elements receive no content validation;
attributes are mutable after construction; no test round-trips a
non-empty `anchor_errors`. (An earlier draft also claimed the plain
`AnchorError` branch's ad-hoc `.outcomes` does not survive pickle —
that was wrong, verified empirically: it survives pickle and
deepcopy via `__dict__`.)

## Anchor advancement — who moves the pin

Recovery NEVER advances either anchor (the code claim; the
byte-identical test pin covers the tx anchor —
`tests/test_trust_shiptx_anchoring.py:524`). Advancement is a
caller duty:

- Write half (cycle 23, current): `anchored_record_ship`
  (`trust/shipcheck.py:425`) requires both anchors, verifies them
  AND requires currency (anchor head/seq equal the journal's
  current head/length — a merely-verifying stale prefix refuses),
  then advances the tx anchor after COMMITTED. If that advance
  fails it raises `ShipRefused` AFTER the ship is recorded and
  finalised, and the stale tx anchor blocks subsequent anchored
  ships until an operator reconciles. The wrapper is not exported
  from `trust/__init__.py` and has no non-test caller; direct
  `record_ship` remains callable, advances only the ship anchor,
  and leaves the tx anchor stale. Tx-anchor advancement in
  production is therefore currently orphaned: the interface exists,
  no production caller invokes it.
- Recovery half (still unwired): `recover()` ACCEPTS an optional
  `tx_anchor_path` that no in-tree caller supplies. The cycle-17
  docstring claim is scoped to `recover()` itself
  (`trust/shiptx.py:771`) and remains true for it. The specific
  missing protection on the recovery path is tx-anchor
  verification; ship-anchor verification is available there when a
  caller passes `anchor_path`.

## Operating it

- Anchor operations (`trust/anchoring.py`): `initialise_anchor`,
  `update_anchor`, `force_reanchor`, `verify_anchor`. Anchors must
  live OUTSIDE the journal directory they pin.
- After a successful recovery that settled transactions, the caller
  — not recovery — should advance the tx anchor with
  `update_anchor(..., kind="ship-tx")`; until then, rollback to the
  anchored prefix erases the settlements undetectably (see Limits).
- Verification command for this contract's main pin file:
  `python3 -m unittest tests.test_trust_shiptx_anchoring` (58
  tests). Cycle-23 write-half behaviour is pinned separately in
  `tests/test_cycle23_ship_anchors.py`.

## Operational assumptions and concurrency boundaries

- The sequential model is assumed: one recovery or write operation
  at a time against a journal and its anchors. Concurrent actors
  are NOT supported by anything in this contract — a second actor
  burning between reconciliation and consume is an explicitly open
  item, and callers must serialise recovery, writes, and anchor
  advancement themselves.
- No durability guarantee across an abrupt process or machine
  failure is established by this document beyond what the journal's
  own append discipline provides; a successful return means the
  outcomes were journaled, not that a crash-consistency proof
  exists.
- Recovery is not atomic: a raise can occur after some settlements
  are journaled. Those settlements stand, ride on the exception's
  `.outcomes`, and re-running recovery is the remedy — settled
  transactions are skipped on re-run.

## Limits and non-claims

- The anchor is unkeyed plain JSON and grants no authority by
  itself. Rewriting journal and anchor together to a matching
  earlier pair passes verification. Protection is prefix-only up
  to the last advancement; because recovery does not advance,
  rollback to the anchored prefix erases its settlements
  undetectably. Restoring an older anchor is not detected.
- `force_reanchor` is the audited escape hatch (hash-chained
  reanchor audit alongside the anchor), but recovery NEVER checks
  that audit: `verify_anchor` defaults
  `check_reanchor_audit=False` (`trust/anchoring.py:703`) and no
  call in recovery passes it. A sanctioned re-pin over a
  rolled-back journal therefore passes recovery undetected.
- Two anchors in one external directory are one trust location, not
  two. Separate-OS-user or off-machine storage is operator-asserted
  and unverifiable in-tree.
- Initial anchoring of an established tx journal requires the
  nonempty ceremony (`allow_nonempty_ceremony=True`), which blesses
  on-disk history as-is and cannot detect any rollback that predates
  it. No in-anchor record of the ceremony exists.
- No path-replacement/TOCTOU claim is made. The same-file guard is
  point-in-time identity; verify-and-settle holds no lock.
  Post-settlement re-verification detects only the changes listed
  in "The two raises" — it does not prevent a swap, and settlements
  stand.
- By-value binding limit: a loop history entry is matched to a
  transaction by value; nothing in loop state proves the entry
  belongs to this transaction — attribution is inferential.
- Manifest-rebuild limit: re-verification assumes the current
  manifest; any rebuild mismatch, including ordinary tree drift,
  parks the transaction at ANOMALY.
- False-park direction: restoring journal and anchor from
  mismatched backup points parks live transactions at ANOMALY.
- Silent-`[]` holes (open design item): operator-error evidence,
  same-file evidence, and (deliberately) ship-only park evidence
  with no non-terminal transaction to carry it return `[]`,
  indistinguishable from a clean run. Recovery does not detect or
  surface these holes. A chosen non-`[]` surface is an unbuilt
  design decision, not a bug fix.

## Open items carried from this contract

- Wire a production recovery caller that passes `tx_anchor_path`.
- Choose a non-`[]` surface for carrier-less evidence, or record a
  decision to keep `[]`.
- Post-settlement re-verification: surface returned (non-exception)
  malformed/missing anchor failures instead of discarding them.
- Pin-store head anchoring; reconciliation repair for wholesale
  pin-directory loss; operator-authentication-channel;
  concurrent-actor interleaving (outside the sequential model).
