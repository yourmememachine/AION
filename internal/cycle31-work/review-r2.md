# Cycle 31 — War-room review R2 (error surface)

Scope: `docs/RECOVERY-CONTRACT.md`, sections "The two raises" and
"JournalIntegrityError", verified blind against
`trust/anchoring.py` and `trust/shiptx.py` only.

Score: 0.74
Verdict: FIX

## What checked out (no action)

- Pre-settlement raise: `trust/shiptx.py:859-902` fires
  `JournalIntegrityError` only when `tx_park_reasons` is non-empty
  and no transaction is non-terminal; ship park reasons ride along
  in `reasons`/`anchor_sources` (`trust/shiptx.py:884-888`), and a
  ship-only park in that situation falls through and returns `[]`.
  The contract states this correctly.
- `JournalIntegrityError(AnchorError)` at `trust/anchoring.py:159`
  is correct. Constructor validation is as described: non-empty,
  deduped reasons refused with `ValueError` unless a subset of
  `JOURNAL_INTEGRITY_REASONS` (`trust/anchoring.py:145-147`,
  validation in `__init__`); non-empty, deduped `anchor_sources`
  whose `ship`/`ship-tx` labels' suffix set must equal the reasons
  set; `anchor_source` derived as the single source or
  `"combined"`; `__reduce__` at `trust/anchoring.py:255-260`
  round-trips through `_restore_journal_integrity_error`
  (`trust/anchoring.py:151-155`), which re-runs the constructor.
- Handler-order rule, mutable attributes, and no content
  validation of `outcomes`/`anchor_errors` elements are all
  accurate: `__init__` only rejects a bare `str`/`bytes` container
  for those fields and stores plain attributes (verified
  empirically: arbitrary objects are accepted as elements and
  `reasons` can be reassigned after construction).

## Inaccuracies

1. **Post-settlement "new load failure raises plain
   `AnchorError`" is false for returned load failures — the common
   path.** The contract ("The two raises", item 2) says a new load
   failure alone raises plain `AnchorError` carrying `.outcomes`,
   and that accompanying load failures land in `.anchor_errors`.
   In code, the post-settlement loops at
   `trust/shiptx.py:999-1021` only append to `new_park` when a
   *returned* reason is in `ANCHOR_PARK_REASONS` and new, or when
   `verify_anchor` *raises* an exception (converted to
   `anchor_error:<exc>`, reason `None`). But `verify_anchor`
   reports load failures as return values, not exceptions:
   `trust/anchoring.py:728-733` returns `("anchor_malformed",)`,
   `("anchor_missing_established_ledger",)`, or
   `("anchor_missing",)`. A mid-recovery swap to a malformed or
   missing anchor therefore returns one of those strings, is
   silently discarded by the loops at `trust/shiptx.py:1000-1003`
   and `trust/shiptx.py:1013-1017`, and raises nothing. Only
   exception-path failures (e.g. placement/kind checks raising
   before the return path) can reach the plain-`AnchorError`
   branch at `trust/shiptx.py:1051-1053` or `.anchor_errors` at
   `trust/shiptx.py:1039-1046`. The contract must scope its claim
   to exception-raised failures, or the code must classify
   returned non-park reasons post-settlement.

2. **Known-gap claim "the plain-`AnchorError` branch's ad-hoc
   `.outcomes` does not survive pickle" is false.** The branch is
   `trust/shiptx.py:1051-1052` (`plain = AnchorError(message)`;
   `plain.outcomes = tuple(outcomes)`). `AnchorError`
   (`trust/anchoring.py:134`) defines no `__reduce__`, so default
   `BaseException` pickling preserves `__dict__`. Verified
   empirically in this review: an `AnchorError` with
   `.outcomes = ({'a': 1},)` round-tripped through
   `pickle.dumps`/`pickle.loads` with `.outcomes` intact. Remove
   or re-state this gap (e.g. as "not part of the type's
   constructor contract", which is true, rather than a pickle
   claim, which is not).

3. **"After settlement both anchors are re-verified" overstates
   the guard.** `trust/shiptx.py:979-980` runs re-verification
   only when `not same_path_error and (anchor_path is not None or
   tx_anchor_path is not None)`, and inside it each anchor is
   re-verified only if its own path was supplied
   (`trust/shiptx.py:998` and `trust/shiptx.py:1011`). With one
   anchor supplied, only that one is re-verified; with neither,
   nothing is. The sentence should read "each supplied anchor is
   re-verified (skipped entirely in the same-file case and when
   no anchor path was given)".

4. **The type-idempotence consequence is stated without its
   tx-anchor qualifier.** "The same evidence parks on run 1 and
   raises on run 2" holds only when the park evidence comes from
   the tx anchor: the run-2 raise requires `tx_park_reasons`
   (`trust/shiptx.py:859`). The identical ship-only evidence
   parks on run 1 and returns `[]` on run 2, by the contract's
   own preceding paragraph. As written, the unqualified
   consequence contradicts that paragraph; qualify it to
   tx-anchor evidence.

5. **Unverifiable-from-cited-code claim in the JournalIntegrityError
   section.** "No test round-trips a non-empty `anchor_errors`"
   is a claim about the test suite; nothing in
   `trust/anchoring.py` or `trust/shiptx.py` establishes it, and
   the section presents it alongside code-pinned gaps with no
   test-file citation. Either cite the test file/grep that
   establishes the absence or drop it from this section. (The
   neighbouring gaps — unvalidated elements, mutable attributes —
   are code-verifiable and do check out, per above.)

## Bottom line

The pre-settlement raise and the `JournalIntegrityError`
validation model are described accurately. The post-settlement
error surface is not: returned load failures are ignored, not
raised, and the pickle gap does not exist. Both misstate what a
caller catching `AnchorError` after `recover()` will actually
observe, so this is a FIX, not a wording nit.
