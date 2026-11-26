# Cycle 31 — War-room review R1 (correctness)

Reviewer seat: R1, correctness (blind review).
Scope read: `docs/RECOVERY-CONTRACT.md` against `trust/shiptx.py`,
`trust/anchoring.py`, `trust/shipcheck.py`, and
`tests/test_trust_shiptx_anchoring.py` only. I did not read
`internal/cycle31-work/`.
Test check: `python3 -m unittest tests.test_trust_shiptx_anchoring`
— 58 tests, OK.

**Independent score: 0.80**

**Verdict: FIX**

Most of the contract is accurate: the entry-point signatures, the
park-reason set (`JOURNAL_INTEGRITY_REASONS`,
`trust/anchoring.py:145`, matching `ANCHOR_PARK_REASONS` at
`trust/shiptx.py:341-343`), the park-over-error combination and
labelling rule (`trust/shiptx.py:836-858`, `911-922`), the
pre-settlement no-park-target raise and its ship-only asymmetry
(`trust/shiptx.py:859-902`; test at
`tests/test_trust_shiptx_anchoring.py:723`), the
`JournalIntegrityError` constructor validation and `__reduce__`
(`trust/anchoring.py:159`, `195-258`), the `anchored_record_ship`
currency check and tx-anchor advance (`trust/shipcheck.py:425`,
`462-498`), and most of the Limits section all check out. The
items below are the claims that are wrong or materially
inaccurate.

## Wrong / inaccurate claims

1. **Opening evidence claim is false: "Every claim is pinned by a
   test in `tests/test_trust_shiptx_anchoring.py` unless stated as
   a limit."** The write-half claims about `anchored_record_ship`
   have no pin in that file at all (no occurrence of
   `anchored_record_ship` in
   `tests/test_trust_shiptx_anchoring.py`); they are pinned in
   `tests/test_cycle23_ship_anchors.py:155` and `:168`. The
   JournalIntegrityError "known gaps" (mutable attributes, no
   content validation of `outcomes`/`anchor_errors`, pickle
   behaviour) are likewise unpinned in that file — the only
   pickle round-trip there,
   `tests/test_trust_shiptx_anchoring.py:845-859`, constructs the
   error without `anchor_errors`, which the contract itself
   concedes ("no test round-trips a non-empty `anchor_errors`").

2. **"The plain-`AnchorError` branch's ad-hoc `.outcomes` does
   not survive pickle" is false on this tree/runtime.** The
   branch is `trust/shiptx.py:1051-1053`
   (`plain = AnchorError(message); plain.outcomes =
   tuple(outcomes); raise plain`), and `AnchorError` is a plain
   `Exception` subclass with no custom `__reduce__`
   (`trust/anchoring.py:134`). Verified directly on Python 3.12:
   an `AnchorError` built exactly that way round-trips through
   `pickle.loads(pickle.dumps(...))` (and `copy.deepcopy`) with
   `.outcomes` intact, because exception pickling preserves
   `__dict__`. The stated gap does not exist as written.

3. **Post-settlement claim overgeneralises and hides a real
   detection gap: "A new load failure alone raises plain
   `AnchorError`."** That is true only for failures raised as
   exceptions. `verify_anchor` *returns* load failures as tuple
   reasons — `anchor_malformed` at `trust/anchoring.py:728-729`,
   `anchor_missing` / `anchor_missing_established_ledger` at
   `trust/anchoring.py:730-733` — and the post-settlement loop
   only collects returned reasons that are park reasons
   (`trust/shiptx.py:997-1003`, `1011-1017`); `anchor_error:`
   entries are created only in the `except` branches
   (`trust/shiptx.py:1004-1010`, `1018-1021`). A mid-recovery
   swap to a malformed or missing anchor file therefore raises
   nothing post-settlement and the run returns its settlements
   normally. The only test of the plain-`AnchorError` branch
   mocks `verify_anchor` to *raise*
   (`tests/test_trust_shiptx_anchoring.py:970`), which is not how
   the real function reports malformed/missing anchors. The same
   flaw makes the Limits claim "Post-settlement re-verification
   DETECTS a mid-recovery swap" unqualifiedly overstated: it
   detects park-reason swaps and exception-raised failures, not
   returned load-failure swaps. Related minor point in the same
   paragraph: "both anchors are re-verified" — each anchor is
   re-verified only if it was supplied (`trust/shiptx.py:979`,
   `997`, `1011`).

4. **The not-type-idempotent consequence is stated without its
   necessary qualifier: "The same evidence parks on run 1 …
   and raises on run 2 (all transactions terminal)."** The raise
   on run 2 fires only on *tx* park reasons
   (`trust/shiptx.py:859`: `if tx_park_reasons and not any(...)`).
   For ship-only park evidence, run 1 parks, run 2 skips the
   now-terminal transactions (`trust/shiptx.py:907-909`), the
   identical post-settlement park reason is suppressed
   (`trust/shiptx.py:1001-1002`), and the call returns `[]` —
   no raise. The contract's own deliberate ship-only asymmetry
   (raise section, item 1) contradicts the unqualified
   consequence sentence.

5. **"Recovery NEVER advances either anchor (pinned
   byte-identical in tests)" overstates the test evidence.** The
   code claim is true (no `update_anchor` call exists in
   `recover()`), but the byte-identical pin in the named test
   file covers only the *tx* anchor:
   `tests/test_trust_shiptx_anchoring.py:524-534`
   (`test_recovery_never_advances_tx_anchor_then_caller_does`).
   No test in that file asserts the ship anchor file is
   byte-identical after a recovery.

6. **Same-file claim is unqualified in a way its own later
   section contradicts: "the call yields one operator-error
   string."** The string is one entry of `anchor_error_reasons`
   (`trust/shiptx.py:850-858`), but it surfaces only inside
   per-transaction `error` outcomes
   (`trust/shiptx.py:911-922`), repeated once per non-terminal
   transaction; with zero non-terminal transactions the loop
   body never runs (`trust/shiptx.py:907-909`) and the call
   yields `[]` and no string at all — the silent-`[]` hole the
   contract itself lists later.

7. **Docstring-staleness framing conflates two functions.** The
   quoted claim "no in-tree caller passes `tx_anchor_path` yet"
   sits in `recover()`'s own docstring
   (`trust/shiptx.py:771-774`), i.e. it is a claim about
   `recover()`'s parameter, and it remains true for that
   parameter (no production caller passes `tx_anchor_path` to
   `recover()` / `recover_ship_tx()`). `anchored_record_ship`
   does not pass `tx_anchor_path` to `recover()` either; it
   consumes its own parameter for verify/update
   (`trust/shipcheck.py:462-498`). Calling the docstring claim
   "stale for the write path" is therefore misleading: as
   scoped, it is not stale at all.

8. **Pin imprecision (minor).** `ShipTxJournal.recover` is
   defined at `trust/shiptx.py:713` (the cited `:714` is the
   signature's continuation line), and `recover_ship_tx` at
   `trust/shipcheck.py:507` (cited `:508` is likewise the
   continuation). The cited anchor-verification order range
   `trust/shiptx.py:803-831` also runs past the verification
   steps (which end at `:827`) into the classification comment
   at `:828-831`. The other pins check out exactly:
   `trust/anchoring.py:145`, `trust/anchoring.py:159`,
   `trust/shipcheck.py:425`.

## Required fixes

Correct items 2 and 3 in the contract text (the pickle gap does
not exist; the post-settlement load-failure surface covers only
exception-raised failures, and returned `anchor_missing` /
`anchor_malformed` reasons arriving post-settlement are silently
ignored — either document that as a limit or treat it as an open
item), qualify items 4–6, fix the evidence claim in item 1 and
the framing in item 7, and tidy the pins in item 8. No code
change is demanded by this review; the findings are against the
contract's factual accuracy.
