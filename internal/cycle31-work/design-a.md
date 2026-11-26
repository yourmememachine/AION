# Cycle 31 — Design A: ship-tx recovery contract trace (correctness)

Coder seat A (correctness trace). Source of truth is code, not the
cycle records: `trust/shiptx.py` (`ShipTxJournal.recover`),
`trust/anchoring.py` (`verify_anchor`, `JournalIntegrityError`),
pinned by `tests/test_trust_shiptx_anchoring.py`. Cycle intent:
`internal/BUILD-CYCLE-17.md` (ship-tx anchoring, kind `"ship-tx"`)
and `internal/BUILD-CYCLE-18.md` (distinct journal-integrity type).
Wrapper: `trust/shipcheck.py:507` `recover_ship_tx(ledger, loop, *,
recorded_at="", root=None, anchor_path=None, tx_anchor_path=None)`
forwards both anchor paths to `recover()` unchanged.

## 1. recover() inputs / outputs

Signature: `trust/shiptx.py:713`

```python
def recover(self, ledger, loop, *, recorded_at="", root=None,
            anchor_path=None, tx_anchor_path=None) -> list
```

Inputs:

- `self` — the `ShipTxJournal` (the tx journal, `ship-tx.json` in
  the ship ledger's own directory); `self` is the object the
  `tx_anchor_path` pins.
- `ledger` — the `ShipLedger`; evidence source for burns/finalises
  and the object `anchor_path` pins.
- `loop` — the CoreLoop; evidence source is `loop.state["history"]`
  only (`trust/shiptx.py:1056`ff, `_recover_one`).
- `recorded_at=""` — falsy means `stamp = recorded_at or _now()`
  at the head of `recover()`; that one stamp is used for every
  transition journaled by the run.
- `root=None` — optional build tree for manifest re-verification
  before recovery may journal `POST_RECORD_VERIFIED` / finalise
  (see §6 note; not an anchor concern, but it gates settlement).
- `anchor_path=None` — optional ship-ledger anchor, verified with
  `kind="ship"`. `None` = not verified at all (pre-cycle-17
  behaviour preserved exactly).
- `tx_anchor_path=None` — optional tx-journal anchor (cycle 17),
  verified with `kind="ship-tx"`. `None` = not verified. No
  in-tree caller passes it yet — operator/library plumbing
  (docstring, `trust/shiptx.py:713`ff; BUILD-CYCLE-17 §"What was
  built" item 4).

Outputs:

- Normal return: `list` of one outcome dict per transaction that
  changed state or failed to settle:
  `{tx_id, decision_id, from_state, to_state, cycle_id}`, plus
  `reasons` (+ `anchor_sources`) for ANOMALY parks, plus `error`
  for a transaction whose recovery raised or hit an operator-error
  anchor failure. Terminal transactions are skipped, so a second
  run over settled transactions returns `[]` (idempotent).
- Raises instead of returning in exactly the two journal-level
  cases in §5 and §6. A raise discards the return value, so
  completed settlements ride on the exception as `.outcomes`.
- Side effects: appends transitions to the tx journal (via
  `_recover_one` → `transition`); the ONLY ledger write is the
  finalise completing an already-recorded, already-verified cycle
  (`_recover_one`, `trust/shiptx.py:1056`ff). Recovery never burns
  and never runs a cycle. It never writes either anchor file (§7).

Per-transaction isolation inside the settlement loop
(`trust/shiptx.py:907-978`): each non-terminal snapshot is settled
via `_recover_one` with up to 3 attempts; an exception is collected
into that transaction's `error` outcome (transaction left in its
current state) and does not block the others; if a concurrent run
settled it to a terminal state, no outcome is reported for it.

## 2. Anchor verification order

Both anchors are verified BEFORE any transaction is settled —
explicitly so a lazy tx check cannot let early settlements land on
an unpinned journal (`trust/shiptx.py:788-795` comment; code
`trust/shiptx.py:803-831`):

1. Same-file guard first (§4). If it fires, BOTH verifications are
   suppressed (`if not same_path_error:`, `trust/shiptx.py:813`).
2. Ship anchor, if `anchor_path is not None`:
   `verify_anchor(ledger, anchor_path, kind="ship")`
   (`trust/shiptx.py:813-820`). Any exception is caught and
   converted to the single reason string `f"anchor_error:{exc}"`.
3. Tx anchor, if `tx_anchor_path is not None`:
   `verify_anchor(self, tx_anchor_path, kind="ship-tx")`
   (`trust/shiptx.py:821-831`), same exception conversion.

`verify_anchor` itself (`trust/anchoring.py:703`ff) is pure and
returns a tuple of reasons, `()` = anchor names a prefix of the
chain. Its internal order: kind check → outside-journal-dir check
(`_check_outside_journal`; an inside-dir path raises `AnchorError`,
which `recover()` therefore sees as `anchor_error:…`) → reload
chain prefixes → malformed file → `("anchor_malformed",)`; absent
file → `("anchor_missing",)` if journal empty, else
`("anchor_missing_established_ledger",)`; kind mismatch →
`("anchor_kind_mismatch",)`; `seq > journal_len` →
`("anchor_ahead_of_journal",)`; head not at `seq` →
`("anchor_head_not_in_chain",)`. An anchor naming an OLDER prefix
verifies (`()`): staleness is not tampering.

Classification (after both verifications,
`trust/shiptx.py:833-858`): the park set is exactly

```python
ANCHOR_PARK_REASONS = frozenset({"anchor_head_not_in_chain",
    "anchor_ahead_of_journal", "anchor_kind_mismatch"})
# trust/shiptx.py:341-343 — identical to
# trust/anchoring.py:145-147 JOURNAL_INTEGRITY_REASONS
```

Every other returned/raised reason — `anchor_missing`,
`anchor_missing_established_ledger`, `anchor_malformed`
(`ANCHOR_ERROR_REASONS`, `trust/shiptx.py:344-346`), any
`anchor_error:…` wrapper, the same-file message — is an operator
error. Labelling: reasons are labelled `"ship: <r>"` /
`"ship-tx: <r>"` only when the tx anchor participates
(`labelled = tx_anchor_path is not None`, `_label`,
`trust/shiptx.py:836-839`); a ship-only caller keeps its bare
pre-cycle-17 strings exactly.

Then, in order: (a) the no-park-target check on the TX reasons
(§5) — may raise before any settlement; (b) the settlement loop
(§3); (c) post-settlement re-verification (§6) — may raise after
settlements. No lock is held across verify+settle, which is why
(c) exists.

## 3. Park-over-error combination

Computed once, before the loop (`trust/shiptx.py:841-858`):

- `ship_park_reasons` / `tx_park_reasons` = each anchor's reasons
  ∩ `ANCHOR_PARK_REASONS`.
- `anchor_park_reasons` = deduped union, ship first;
  `anchor_park_sources` = the labelled form of the same union.
- `anchor_error_reasons` = deduped labelled non-park reasons from
  both anchors, plus the same-file message if §4 fired.

Settlement loop decision per non-terminal transaction
(`trust/shiptx.py:911-922`, then `_recover_one` at
`trust/shiptx.py:1073-1075`):

- If `anchor_park_reasons` is non-empty: park wins. The
  error-outcome branch is guarded by
  `if anchor_error_reasons and not anchor_park_reasons`, so any
  operator error from either anchor is silently absorbed and
  every non-terminal transaction is parked at ANOMALY via
  `_recover_one(..., anchor_reasons=anchor_park_reasons,
  anchor_park_sources=anchor_park_sources)`, which short-circuits
  before consulting ledger/loop evidence:
  `park(ANOMALY, reasons=list(anchor_reasons),
  anchor_sources=list(anchor_park_sources))`. Outcome carries
  `reasons` = bare union and `anchor_sources` = labelled union.
- Else if `anchor_error_reasons` is non-empty: non-destructive.
  One outcome per non-terminal transaction with
  `to_state == from_state` and
  `error = "anchor verification failed (operator error;
  transaction left in place for the next run): " +
  ", ".join(anchor_error_reasons)`; no transition is journaled,
  no finalise happens; the next run retries.
- Else (both empty): normal evidence-driven settlement in
  `_recover_one`.

Pinned by tests: `test_combined_park_beats_operator_error`
(ship missing + tx mismatch → ANOMALY),
`test_combined_ship_park_tx_error_parks_with_source` (outcome has
no `error` key, `anchor_sources == ["ship:
anchor_head_not_in_chain"]`),
`test_combined_both_operator_errors_labelled` (both labels appear
in the one `error` string, transaction unmoved).

## 4. Same-file guard

`trust/shiptx.py:803-811`: only when BOTH paths are given.

```python
try:
    same_path_error = os.path.samefile(anchor_path, tx_anchor_path)
except OSError:
    same_path_error = Path(anchor_path).resolve() \
        == Path(tx_anchor_path).resolve()
```

- Identity is by FILE, not path string and not content:
  `os.path.samefile` catches symlink and hardlink aliases; the
  fallback (either file missing, so `samefile` raises `OSError`)
  is resolved-path equality.
- On a positive diagnosis BOTH verifications are suppressed
  (`trust/shiptx.py:813`) — running either against the shared
  file would manufacture a kind mismatch and park every
  transaction over a wiring typo. The sole consequence is one
  operator-error reason appended to `anchor_error_reasons`:
  `"ship-tx: tx_anchor_path is the same file as anchor_path; the
  two anchors must be distinct files"` (`trust/shiptx.py:856-858`),
  hence the §3 error outcome, never a park. It fires whichever
  anchor's file is the shared one (ship file or tx file).
- Negative space, pinned: a DIFFERENT file with the wrong kind —
  e.g. the ship anchor file passed as `tx_anchor_path`, or a
  byte-identical COPY (distinct inode) of it — is NOT the guard's
  case: it verifies as `anchor_kind_mismatch` and parks
  (`test_recovery_parks_on_tx_kind_mismatch`,
  `test_byte_copy_distinct_inode_still_parks`,
  `test_ship_tx_file_passed_as_ship_anchor_parks`).
- The guard also disables post-settlement re-verification
  (`if not same_path_error and …`, `trust/shiptx.py:979`).

Tests: `test_same_path_for_both_anchors_is_error_not_anomaly`,
`test_same_file_tx_anchor_shared_is_error_not_anomaly`,
`test_same_file_symlink_alias_is_error_not_anomaly`,
`test_same_file_hardlink_alias_of_ship_anchor`,
`test_same_file_hardlink_alias_of_tx_anchor` (hardlink pins added
in cycle 18, BUILD-CYCLE-18 §"What was built" item 3).

## 5. No-park-target raise (pre-settlement)

`trust/shiptx.py:859-902`. Condition, exactly:

```python
if tx_park_reasons and not any(
        s["state"] not in TERMINAL_STATES
        for s in self.transactions()):
    raise JournalIntegrityError(...)
```

- Fires ONLY on the TX anchor's park reasons. Rationale in code:
  the tx journal is the pinned object itself — deleting its file
  loads as an empty journal, and rolling it back to a
  terminal-only prefix also presents nothing to park; returning
  `[]` would read as a clean recovery in both cases.
- The SHIP anchor deliberately has NO equivalent raise: it pins a
  different file, so with no non-terminal transaction nothing is
  at risk from it (pinned by
  `test_ship_anchor_only_park_with_nothing_to_park_no_raise`,
  which returns `[]`). Asymmetry is intentional, cycles 17+18.
- BUT if the ship anchor ALSO has park reasons in the same call,
  they ride on the raise instead of vanishing (cycle-18 fix
  round): `reasons` = deduped union (tx first in construction,
  ship appended), `anchor_sources` = ship-labelled entries then
  tx-labelled entries, message = tx message + `"; ship anchor
  also failed with chain-mismatch reasons: …"`. The raise still
  FIRES on the tx reasons alone.
- Type: `JournalIntegrityError` (`trust/anchoring.py:159`), an
  `AnchorError` subclass whose constructor VALIDATES the
  contract (`trust/anchoring.py:195-245`): reasons non-empty,
  all in `JOURNAL_INTEGRITY_REASONS` (an operator reason raises
  `ValueError` — it can never mint this type), anchor_sources
  non-empty, labelled `"ship: …"`/`"ship-tx: …"`, suffixes ==
  reasons exactly; bare strings refused. Attributes: `.reasons`
  (bare, deduped tuple), `.anchor_sources` (labelled tuple),
  `.anchor_source` (single source or `"combined"`), `.outcomes`
  (empty here — nothing settled yet), `.anchor_errors` (empty
  here). Message text is the pre-cycle-18 `AnchorError` message,
  unchanged. Callers must catch `JournalIntegrityError` BEFORE
  `AnchorError` (docstring, `trust/anchoring.py:159`ff).
- State dependence, honest: with a live transaction the same
  mismatch PARKS on run 1 (§3); once parked (terminal), run 2
  RAISES. Both behaviours pinned:
  `test_deleted_tx_journal_raises_instead_of_empty_recovery`,
  `test_all_terminal_journal_with_forged_tx_anchor_raises`,
  `test_second_run_after_park_raises_distinct_type`,
  `test_deleted_journal_raises_distinct_type_with_reasons`
  (`reasons == ("anchor_ahead_of_journal",)`,
  `anchor_source == "ship-tx"`),
  `test_pre_settlement_combined_anchors_carry_both_sources`
  (`anchor_source == "combined"`).
- Remedy named in the docstring: supply the correct anchor, or
  `force_reanchor` with a recorded reason
  (`trust/anchoring.py:667`).

## 6. Post-settlement re-verification

`trust/shiptx.py:979-1054`. Runs after the settlement loop, only
if `not same_path_error` and at least one anchor path was given.

- Each supplied anchor is re-verified with the same kind
  (`verify_anchor(ledger, …, kind="ship")` /
  `verify_anchor(self, …, kind="ship-tx")`).
- A reason counts as NEW evidence only if it was not already in
  that anchor's pre-settlement verdict:
  - park reason `r in ANCHOR_PARK_REASONS and r not in
    <initial>_park_reasons` → `new_park.append((f"<src>: {r}", r))`;
  - exception `exc` with `f"anchor_error:{exc}"` NOT in the
    initial reasons → `new_park.append((f"<src>:
    anchor_error:{exc}", None))`. An identical repeat exception
    is not a change (`test_post_settlement_no_new_reason_does_not_raise`:
    a constant park verdict parks in the loop and does not raise).
- If `new_park` is empty: return `outcomes` normally.
- If any entry has a bare reason (park evidence): raise
  `JournalIntegrityError` with `reasons`/`anchor_sources` from
  ONLY the park pairs, `outcomes=outcomes` (settlements stand as
  journaled evidence and ride on the exception because the raise
  discards the return), and `anchor_errors` = the labelled
  `anchor_error:…` entries (never in `.reasons`). Message:
  `"anchor verification changed during recovery; a journal was
  swapped or rolled back mid-run: " + labels`.
  Pinned: `test_post_settlement_park_reason_raises_distinct_type`
  (state is COMMITTED after the raise; `exc.outcomes` carries it),
  `test_post_settlement_combined_sources`,
  `test_post_settlement_mixed_park_and_anchor_error`
  (`exc.anchor_errors == ("ship: anchor_error:anchor_malformed",)`).
- If `new_park` contains ONLY anchor-load failures (all reasons
  `None`): raise PLAIN `AnchorError` (exact type, not the
  subclass) with `.outcomes = tuple(outcomes)` attached ad hoc
  (cycle-18 fix round, so this branch does not silently discard
  settlements either). Pinned:
  `test_post_settlement_anchor_error_only_stays_plain`
  (`type(ctx.exception) is AnchorError`,
  `not isinstance(…, JournalIntegrityError)`).

## 7. Anchor advancement (or not)

Recovery NEVER advances either anchor — no `update_anchor` /
`initialise_anchor` / `force_reanchor` call exists in `recover()`
(docstring `trust/shiptx.py:765-775`; module docstring
`trust/shiptx.py:217-230`). Consequences, stated in code:

- Transitions recovery appends leave the tx anchor
  stale-but-valid: it names an older prefix, and `verify_anchor`
  accepts older prefixes (`trust/anchoring.py:703`ff), so the
  post-recovery state verifies.
- The CALLER must call `update_anchor(journal, tx_anchor_path,
  kind="ship-tx", recorded_at=…)` after recovery
  (`trust/anchoring.py:628`: refuses on kind mismatch, on a
  non-prefix existing anchor, and unless seq strictly increases).
- Until the caller does, rolling the tx journal back to the
  anchored prefix ERASES recovery's settlements undetectably.
  This is the contract's sharpest stated limit.
- Symmetric limits: restoring journal and anchor from different
  backup points, or the journal without a `force_reanchor`, parks
  live transactions at ANOMALY; restoring an OLDER anchor than
  the journal is not detected (anchor names a valid older prefix).
- The pin is unkeyed: rewriting journal + anchor together to a
  matching earlier pair passes; two anchors in one external
  directory are one trust location, not two boundaries; first
  anchoring of an established tx journal needs
  `allow_nonempty_ceremony=True` (`trust/anchoring.py:587`) and
  cannot detect rollback predating it.

Pinned byte-for-byte: `test_recovery_never_advances_tx_anchor_then_caller_does`
— anchor file is byte-identical after a committing recovery,
still verifies, and a subsequent caller `update_anchor` moves it
to the journal head. Also `test_recovery_proceeds_with_stale_valid_tx_anchor`
(genesis anchor + full walk → COMMITTED).

## Contract summary (one line per rule)

1. Verify both anchors first, ship then tx, exceptions folded to
   `anchor_error:…`; same-file (by inode, resolved-path fallback)
   suppresses both and is an operator error only.
2. Park set = {head_not_in_chain, ahead_of_journal,
   kind_mismatch}; anything else is operator error.
3. Any park reason from either anchor parks ALL non-terminal
   transactions at ANOMALY and absorbs all operator errors;
   operator-error-only leaves every transaction unmoved with a
   per-tx `error` outcome.
4. Tx park reasons with no non-terminal transaction to park
   raise `JournalIntegrityError` (ship reasons in the same call
   ride along; ship-only never raises).
5. After settling, re-verify: a NEW park reason raises
   `JournalIntegrityError` carrying `.outcomes` (and
   `.anchor_errors` for accompanying new load failures); a
   new load failure alone raises plain `AnchorError` also
   carrying `.outcomes`.
6. Recovery never advances an anchor; the caller advances it,
   and until then rollback to the anchored prefix is undetectable.
