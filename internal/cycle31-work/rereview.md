# Cycle 31 — Re-verification (re-review seat)

Scope: ONLY the seven reconciled points from the cycle-31 FIX
verdict, checked against the current code tree. No other claim in
`docs/RECOVERY-CONTRACT.md` was re-audited.

**Score: 10/10**
**Verdict: SHIP**

## Point-by-point

1. **Pickle claim corrected — PASS.**
   The JournalIntegrityError section now states the earlier draft
   was wrong and that the plain `AnchorError` branch's ad-hoc
   `.outcomes` survives pickle and deepcopy via `__dict__`.
   Re-verified empirically in this review: a plain
   `AnchorError("boom")` with `.outcomes` (and an extra
   `.anchor_errors`) set ad hoc round-tripped through
   `pickle.loads(pickle.dumps(...))` and `copy.deepcopy` with both
   attributes intact. The correction as written is accurate.

2. **Post-settlement gap stated — PASS.**
   `verify_anchor` (`trust/anchoring.py:703`, body at 729–733)
   RETURNS `("anchor_malformed",)`, `("anchor_missing",)`, and
   `("anchor_missing_established_ledger",)` as values; the
   `AnchorError` from `_read_anchor` is caught inside
   `verify_anchor`, not propagated. The post-settlement
   re-verification loops in `ShipTxJournal.recover`
   (`trust/shiptx.py:999` and `:1013`) collect a returned reason
   only `if r in ANCHOR_PARK_REASONS`, so returned
   malformed/missing reasons are discarded; only the `except`
   branch (exception-path failures, as `anchor_error:<exc>`) and
   returned park reasons are acted on. The contract's "Gap"
   paragraph and its Open-items entry describe exactly this, with
   no overstatement.

3. **`force_reanchor` audit never checked in recovery — PASS.**
   `verify_anchor` defaults `check_reanchor_audit=False`
   (`trust/anchoring.py:704`). None of the four `verify_anchor`
   calls on the recovery path (`trust/shiptx.py:817`, `:824`,
   `:999`, `:1013`) passes the flag, and `recover_ship_tx` adds no
   call of its own. (Callers outside recovery — tests and the
   verifier health check — do pass `True`; the contract's claim
   is scoped to recovery and is accurate as scoped.)

4. **Citations — PASS.**
   `trust/shiptx.py:713` is exactly
   `def recover(self, ledger, loop, *, recorded_at="", root=None,`
   and `trust/shipcheck.py:507` is exactly
   `def recover_ship_tx(ledger, loop, *, recorded_at="", root=None,`.
   Both citations in the Entry-points section are correct.

5. **Pinning preamble — PASS.**
   The preamble now reads that claims are "evidenced by the cited
   source locations and, where a pin exists, by tests — a pinning
   test proves the tested input/state, not every branch." It no
   longer claims every claim is test-pinned, and it also scopes
   itself honestly ("other cycles touching recovery were not
   exhaustively cross-checked for this document").

6. **Concurrency/atomicity and Operating sections — PASS, no
   overclaiming found.**
   "Operating it" is present and its statements match code
   (recovery never advances either anchor; caller-side
   `update_anchor(..., kind="ship-tx")` is the stated remedy; the
   cited verification command `python3 -m unittest
   tests.test_trust_shiptx_anchoring` runs 58 tests, OK, as
   stated). "Operational assumptions and concurrency boundaries"
   is present and is written as non-claims: sequential model
   assumed, concurrent actors explicitly NOT supported, no
   durability guarantee beyond the journal's append discipline,
   and "Recovery is not atomic: a raise can occur after some
   settlements are journaled. Those settlements stand, ride on
   the exception's `.outcomes`" — which matches the
   post-settlement raise code at `trust/shiptx.py:991`ff.
   Nothing in either section asserts locking, atomicity, or
   crash-consistency the code does not provide.

7. **`anchored_record_ship` export/caller status and
   post-COMMITTED `ShipRefused` — PASS.**
   `anchored_record_ship` is defined at
   `trust/shipcheck.py:425`. It is not imported in
   `trust/__init__.py` (the `shipcheck` import there is only
   `check_ship, record_ship, recover_ship_tx`) and does not
   appear in `__all__`. A tree-wide search finds no non-test
   caller: the only references are its definition, a docstring
   mention in `record_ship`, and `tests/test_cycle23_ship_anchors.py`.
   Post-COMMITTED refusal matches code: after `record_ship`
   returns (transaction COMMITTED), the wrapper calls
   `update_anchor(..., kind="ship-tx")` and on `AnchorError`
   raises `ShipRefused` with the message that the cycle was
   "recorded and decision … finalised, but the ship-tx anchor
   update failed" (`trust/shipcheck.py:495–503`); its docstring
   likewise states the ship stands recorded and finalised. The
   contract's wording ("raises `ShipRefused` AFTER the ship is
   recorded and finalised", wrapper "not exported … and has no
   non-test caller", tx-anchor advancement "currently orphaned")
   is accurate.

## Remaining inaccuracy

None within the seven scoped points. All seven reconciled items
are now stated as the code behaves.
