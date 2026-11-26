# Cycle 32 — Test design (Seat C, TESTS angle)

Fix under test: post-settlement re-verification in
`ShipTxJournal.recover()` (`trust/shiptx.py`) discarding RETURNED
non-park anchor reasons. Design only — no production or test code
changed by this document. The normative design decisions are the
ones in `internal/CROSS-CHECK-BRIEF-CYCLE-32.md` §§1–4; this file
turns them into concrete, failing-first test cases for
`tests/test_trust_shiptx_anchoring.py`.

## 1. The bug, in test-relevant terms

`verify_anchor` (`trust/anchoring.py`) reports operator/load
failures as RETURN VALUES, not exceptions:

```python
except AnchorError:            # _read_anchor failure inside verify
    return ("anchor_malformed",)
if anchor is None:             # file absent
    return ("anchor_missing_established_ledger",)  # journal non-empty
    return ("anchor_missing",)                     # journal empty
```

The post-settlement block in `recover()` (after the settlement
loop) only appends to `new_park` when a returned reason
`r in ANCHOR_PARK_REASONS and r not in <pre>_park_reasons`, or when
`verify_anchor` RAISES (converted to
`("<source>: anchor_error:<exc>", None)`). A returned non-park
reason therefore matches neither branch and is silently dropped:
no raise, settlements return as if clean. The existing mixed test
(`test_post_settlement_mixed_park_and_anchor_error`) does NOT
catch this — its fake RAISES `AnchorError("anchor_malformed")`,
i.e. it tests the exception path that already works, with a shape
the real `verify_anchor` never produces for a malformed file.

**Critical authoring rule for every test below: the fake must
RETURN the non-park reason as a tuple, never raise it.** A fake
that raises passes on the buggy code and proves nothing.

## 2. Contract the tests pin (from the brief)

| # | Decision | Test consequence |
|---|----------|------------------|
| D1 | A returned non-park reason is NEW only if absent from THAT SAME anchor's initial returned reasons (per-anchor dedup, mirroring the exception path's `f"anchor_error:{exc}" not in <anchor>_reasons` check). | §4 T6/T7 must NOT raise; §4 T8 (same string, other anchor) MUST raise. |
| D2 | New returned non-park = exactly like a new exception-path failure: error-only ⇒ plain `AnchorError` with completed outcomes on `.outcomes`; mixed with a new park reason ⇒ rides on `JournalIntegrityError.anchor_errors`, NEVER in `.reasons`. | T1–T3, T9–T11. |
| D3 | Label format for a RETURNED reason: `"<source>: <bare reason>"` — e.g. `"ship-tx: anchor_malformed"`. Distinct from the exception-path label `"<source>: anchor_error:<exc>"`. | `anchor_errors == ("ship: anchor_malformed",)`, and explicitly `assertNotIn("anchor_error:", anchor_errors[0])` in T3. This is THE defined format; the production fix must emit exactly it for returned reasons. |
| D4 | ANY non-park returned string is operator error (same classification as pre-settlement: park set is exactly `ANCHOR_PARK_REASONS`, everything else is error). Not a hard-coded list of three. | T5 uses an invented reason string. |
| — | No change to pre-settlement behaviour, park handling, same-file guard, or the no-park-target raise. | Existing 58 tests in the file stay green, unmodified. |

Exception surfaces, for assertions:

- Plain post-settlement error: `type(exc) is AnchorError`,
  `not isinstance(exc, JournalIntegrityError)`,
  `exc.outcomes == tuple(<the outcomes recover() would have
  returned>)`. Plain `AnchorError` has NO `.reasons` /
  `.anchor_errors` contract — tests must NOT assert them on the
  plain type (assert message + `.outcomes` only).
- `JournalIntegrityError`: `type(exc) is JournalIntegrityError`,
  `.reasons` = bare park reasons tuple, `.anchor_sources` =
  labelled park tuple, `.anchor_source` = `"ship"` / `"ship-tx"` /
  `"combined"`, `.anchor_errors` = labelled returned-reason tuple
  (D3 format), `.outcomes` = tuple of completed outcomes.
- Message: both raises build
  `"anchor verification changed during recovery; a journal was
  swapped or rolled back mid-run: " + ", ".join(labels)` — assert
  the relevant label is a substring of `str(exc)`, not full-message
  equality (label order across anchors is ship-then-ship-tx).

## 3. Harness pattern (reuse, do not reinvent)

Base class: `TxAnchorFixture` (already in the file), giving
`self.journal`, `self.ledger`, `self.home`, `self.walk`,
`self.burn`, `self.ledger_kinds()`, `tx_anchor_path()`,
`ship_anchor_path()`, `init_tx_anchor()`, `post_record_tx()`,
`loop3()`. Standard setup for most cases:

```python
tx_id = self.post_record_tx()   # state POST_RECORD_VERIFIED,
                                # ledger_kinds() == ["burn"]
self.init_tx_anchor()           # valid ship-tx anchor pinned
# clean recover() then settles: outcomes [COMMITTED],
# journal.state(tx_id) == COMMITTED,
# ledger_kinds() == ["burn", "finalise"]
```

Fake: patch the same target the existing post-settlement tests
use, `mock.patch("trust.anchoring.verify_anchor",
side_effect=fake_verify)`. This works for BOTH verification sites
because `recover()` does `from trust.anchoring import
verify_anchor` inside the method body, at call time. Key the
call counter PER KIND, not globally — with both anchors supplied
the call order is pre: ship, ship-tx; post: ship, ship-tx, and a
global counter makes the both-anchor tests order-fragile:

```python
def make_fake(per_kind_sequences):
    """per_kind_sequences: {kind: [result_call1, result_call2, ...]}
    A result is either a tuple to RETURN or an Exception to raise.
    The last result repeats if called more times than listed."""
    seen = {}
    def fake_verify(journal, path, *, kind, **kw):
        n = seen.get(kind, 0)
        seen[kind] = n + 1
        seq = per_kind_sequences[kind]
        result = seq[min(n, len(seq) - 1)]
        if isinstance(result, Exception):
            raise result
        return result
    return fake_verify
```

Call-count facts to rely on: one supplied anchor ⇒ exactly 2
calls for that kind per `recover()` (pre + post), unless the
pre-settlement no-park-target raise fires first (then post never
runs) or `same_path_error` suppresses both. Both anchors ⇒ 2 per
kind. New class for all of §4:
`PostSettlementReturnedReasonTests(TxAnchorFixture)`; §5 in
`PostSettlementRealFileTests(TxAnchorFixture)`.

**Failing-first check (mandatory before accepting any test):**
every §4/§5 test except T6/T7 (no-raise pins, green both before
and after by design) must be RED on current code — current code
returns the outcomes list and raises nothing, so the
`assertRaises` fails. If a test is green pre-fix, it is testing
the exception path by accident; fix the fake to return.

## 4. Mock-based test cases

### T1 — returned malformed only ⇒ plain `AnchorError`

- Name: `test_post_settlement_returned_malformed_only_raises_plain`
- Setup: standard setup (§3), tx-anchor only.
  `per_kind = {"ship-tx": [(), ("anchor_malformed",)]}`.
- Call: `journal.recover(ledger, loop3(), recorded_at=NOW,
  tx_anchor_path=tx_anchor_path())` under the patch.
- Expected:
  - Raises; `type(exc) is AnchorError`;
    `assertNotIsInstance(exc, JournalIntegrityError)`.
  - `"ship-tx: anchor_malformed" in str(exc)`; and (D3 negative)
    `"anchor_error:anchor_malformed" not in str(exc)`.
  - `exc.outcomes`: tuple, length 1,
    `[o["to_state"] for o in exc.outcomes] == [COMMITTED]`,
    `exc.outcomes[0]["tx_id"] == tx_id`.
  - Settlements stand: `journal.state(tx_id) == COMMITTED`,
    `ledger_kinds() == ["burn", "finalise"]`.

### T2 — returned missing-established only ⇒ plain `AnchorError`

- Name: `test_post_settlement_returned_missing_established_only_raises_plain`
- Setup: identical to T1 except
  `{"ship-tx": [(), ("anchor_missing_established_ledger",)]}`.
  (This is the real return for "anchor file deleted mid-recovery,
  journal non-empty" — the most operationally likely swap.)
- Expected: as T1, with label
  `"ship-tx: anchor_missing_established_ledger" in str(exc)`;
  state `COMMITTED`; ledger `["burn", "finalise"]`.

### T2b — returned plain missing (ship-anchor variant, source labelling)

- Name: `test_post_settlement_returned_missing_on_ship_anchor_only_raises_plain`
- Setup: `post_record_tx()`; valid SHIP anchor only:
  `initialise_anchor(self.ledger, self.ship_anchor_path(),
  kind="ship", recorded_at=NOW, allow_nonempty_ceremony=True)`.
  Recover with `anchor_path=ship_anchor_path()` only.
  `per_kind = {"ship": [(), ("anchor_missing",)]}`.
- Expected: plain `AnchorError` (exact type, not JIE);
  `"ship: anchor_missing" in str(exc)`;
  `exc.outcomes` = the single COMMITTED outcome;
  state `COMMITTED`. Pins that the fix is in BOTH per-anchor
  post-settlement loops, not only the ship-tx one, and that the
  source label follows the anchor, not the reason.

### T3 — mixed returned park + returned malformed ⇒ `JournalIntegrityError`

- Name: `test_post_settlement_returned_park_and_returned_malformed_mixed`
- Setup: BOTH anchors valid: ship anchor as in T2b plus
  `init_tx_anchor()`; `post_record_tx()` first, then both anchors
  (order per existing `_both_valid()` helper pattern).
  Recover with both paths. Per-kind sequences:
  - `"ship"`:   `[(), ("anchor_malformed",)]` — returned error, post only.
  - `"ship-tx"`: `[(), ("anchor_head_not_in_chain",)]` — returned park, post only.
- Expected:
  - Raises; `type(exc) is JournalIntegrityError`.
  - `exc.reasons == ("anchor_head_not_in_chain",)` — the
    malformed reason is NEVER in `.reasons` (D2); explicitly
    `assertNotIn("anchor_malformed", exc.reasons)`.
  - `exc.anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`;
    `exc.anchor_source == "ship-tx"`.
  - **`exc.anchor_errors == ("ship: anchor_malformed",)`** — the
    D3 defined format for a returned reason: source label, colon,
    bare reason. Explicitly
    `assertNotIn("anchor_error:", exc.anchor_errors[0])` to keep
    it distinct from the existing exception-path test's
    `("ship: anchor_error:anchor_malformed",)`.
  - `str(exc)` contains both `"ship-tx: anchor_head_not_in_chain"`
    and `"ship: anchor_malformed"`.
  - `exc.outcomes`: single COMMITTED outcome;
    `journal.state(tx_id) == COMMITTED`;
    `ledger_kinds() == ["burn", "finalise"]`.

### T3b — mixed within ONE anchor's returned tuple (iteration pin)

- Name: `test_post_settlement_one_anchor_returns_park_and_malformed`
- Setup: tx-anchor only, standard setup.
  `{"ship-tx": [(), ("anchor_head_not_in_chain", "anchor_malformed")]}`.
  Real `verify_anchor` never returns two reasons today, but the
  post-settlement loop iterates the returned tuple, and a fix
  that only inspects element `[0]` or classifies the tuple
  wholesale would fail this. (Defensive pin — mark it as such in
  a comment; if the war room rejects multi-reason returns as out
  of contract, this is the one §4 test that may be dropped.)
- Expected: `JournalIntegrityError`;
  `exc.reasons == ("anchor_head_not_in_chain",)`;
  `exc.anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`;
  `exc.anchor_errors == ("ship-tx: anchor_malformed",)`;
  outcomes/state as T3.

### T4 — two returned errors, no park ⇒ one plain `AnchorError`, both labels

- Name: `test_post_settlement_returned_errors_on_both_anchors_raise_plain`
- Setup: both anchors (as T3). Sequences:
  `"ship": [(), ("anchor_malformed",)]`,
  `"ship-tx": [(), ("anchor_missing_established_ledger",)]`.
- Expected: plain `AnchorError` (exact type);
  `str(exc)` contains BOTH `"ship: anchor_malformed"` and
  `"ship-tx: anchor_missing_established_ledger"`;
  `exc.outcomes` = single COMMITTED outcome; state `COMMITTED`.
  Do NOT assert `.anchor_errors`/`.reasons` on the plain type (§2).

### T5 — unknown non-park returned string ⇒ plain `AnchorError` (D4)

- Name: `test_post_settlement_returned_unknown_nonpark_reason_raises_plain`
- Setup: tx-anchor only. `{"ship-tx": [(), ("anchor_some_future_reason",)]}`.
- Expected: plain `AnchorError`;
  `"ship-tx: anchor_some_future_reason" in str(exc)`;
  outcomes/state as T1. Fails any fix that hard-codes
  `ANCHOR_ERROR_REASONS` membership instead of
  "not in `ANCHOR_PARK_REASONS` ⇒ error", and matches the
  pre-settlement classification in the same method.

### T6 — identical returned PARK reason pre and post ⇒ no raise (regression adjacency)

- Name: `test_post_settlement_returned_park_identical_pre_post_no_raise`
- Note: substantively the existing
  `test_post_settlement_no_new_reason_does_not_raise`; keep that
  test untouched and add T7 as the new one. T6 is listed only so
  the suite reads symmetrically — do not duplicate it.

### T7 — identical returned NON-PARK reason pre and post ⇒ no raise (the dedup pin)

- Name: `test_post_settlement_returned_malformed_identical_pre_post_no_raise`
- Setup: tx-anchor only, `post_record_tx()`, `init_tx_anchor()`
  (file validity is irrelevant — verify is mocked).
  `{"ship-tx": [("anchor_malformed",), ("anchor_malformed",)]}`.
- Behaviour on the way: pre-settlement, malformed is an operator
  error with no park reason, so each non-terminal transaction
  gets the non-destructive error outcome and is left in place.
- Expected: **no exception**; `recover()` returns a list of
  length 1 with `"error" in outcomes[0]`,
  `"ship-tx: anchor_malformed" in outcomes[0]["error"]`,
  `outcomes[0]["from_state"] == outcomes[0]["to_state"] ==
  POST_RECORD_VERIFIED`; `journal.state(tx_id) ==
  POST_RECORD_VERIFIED`; `ledger_kinds() == ["burn"]` (no
  finalise). This is the test a naive fix (append every returned
  non-park reason post-settlement, no per-anchor dedup) fails:
  it would raise plain `AnchorError` for a condition the run
  already reported per-transaction. Green pre- and post-fix by
  design — it pins D1, not the bug.

### T8 — same reason string, OTHER anchor post ⇒ still new (per-anchor dedup)

- Name: `test_post_settlement_returned_reason_seen_on_other_anchor_is_new`
- Setup: both anchors valid (as T3). Sequences:
  - `"ship"`: `[("anchor_malformed",), ()]` — malformed pre
    (⇒ per-transaction error outcome, nothing settles), clean post.
  - `"ship-tx"`: `[(), ("anchor_malformed",)]` — clean pre,
    malformed post: the same STRING as ship's pre reason, but
    new FOR THE TX ANCHOR (D1).
- Expected: plain `AnchorError` raised;
  `"ship-tx: anchor_malformed" in str(exc)`;
  `exc.outcomes` has length 1 and its sole entry is the
  pre-settlement ERROR outcome (`"error" in exc.outcomes[0]`,
  `to_state == POST_RECORD_VERIFIED`);
  `journal.state(tx_id) == POST_RECORD_VERIFIED`;
  `ledger_kinds() == ["burn"]`. A global (cross-anchor) dedup
  implementation fails this test. If the war room overturns D1
  in favour of global dedup, this test's expectation flips to
  "no raise" — flag that dependency in the test docstring.

### T9 — pre-settlement park, NEW returned malformed post ⇒ plain, not JIE

- Name: `test_post_settlement_new_returned_error_after_pre_park_raises_plain`
- Setup: tx-anchor only.
  `{"ship-tx": [("anchor_head_not_in_chain",), ("anchor_malformed",)]}`.
- Behaviour on the way: pre park ⇒ settlement loop parks the tx
  at `ANOMALY`. Post: the park reason is gone, a malformed reason
  appears — error-only NEW evidence (the park is not new; it was
  already acted on).
- Expected: plain `AnchorError` (exact type, NOT
  `JournalIntegrityError` — no NEW park reason exists to mint
  one); `exc.outcomes` = single outcome with
  `to_state == ANOMALY`; `journal.state(tx_id) == ANOMALY`;
  `"ship-tx: anchor_malformed" in str(exc)`. Pins that the
  park/error split is computed on NEW reasons only, on both
  sides.

### T10 — returned malformed post with ZERO settlements ⇒ plain, empty outcomes

- Name: `test_post_settlement_returned_malformed_no_settlements_raises_plain`
- Setup: standard setup, then a FIRST, unmocked, valid recover
  commits the tx (`journal.state(tx_id) == COMMITTED`). Second
  recover under the patch:
  `{"ship-tx": [(), ("anchor_malformed",)]}`,
  `tx_anchor_path=tx_anchor_path()`.
- Expected: plain `AnchorError`; `exc.outcomes == ()`;
  state stays `COMMITTED`. Pins that the post-settlement check
  runs even when the settlement loop settled nothing (an
  implementation gated on `if outcomes:` would silently pass a
  swap that happens during a no-op recovery run).

### T11 — returned error on one anchor + exception on the other ⇒ JIE only if a park exists; here plain

- Name: `test_post_settlement_returned_error_and_exception_error_raise_plain`
- Setup: both anchors (as T3). Sequences:
  `"ship": [(), AnchorError("anchor_malformed")]` (raise, post),
  `"ship-tx": [(), ("anchor_missing",)]` (return, post).
- Expected: plain `AnchorError` (no park anywhere);
  `str(exc)` contains BOTH `"ship: anchor_error:anchor_malformed"`
  (exception label format, unchanged) and
  `"ship-tx: anchor_missing"` (returned label format, D3);
  `exc.outcomes` = single COMMITTED outcome. Guards against a
  fix that restructures `new_park` and loses the pre-existing
  exception entries when returned entries are added (and vice
  versa). Companion to the existing raised-only mixed test,
  which must keep passing unchanged:
  `exc.anchor_errors == ("ship: anchor_error:anchor_malformed",)`
  there, vs D3 format here — the contrast is intentional and
  both tests together pin it.

## 5. Real-file (non-mock) tests — feasible, via a finalise hook

Verdict: **mock-only is NOT fully acceptable for this fix, and a
real-file test IS feasible — deterministically, without threads
or timing.** The bug exists precisely because the previous suite
modelled `verify_anchor` as raising a failure the real function
returns; at least the two tests below must exercise the real
`verify_anchor` return path, or the same modelling error can
recur. The remaining §4 cases (per-kind sequencing, dedup,
unknown strings, multi-reason tuples) are mock-only by nature —
the real function cannot be made to return an invented reason or
the same reason twice on demand — and that is acceptable there
because the fake's shape (returns a tuple of strings, keyed by
`kind`) is now pinned against the real contract by §5.

Why a direct swap is hard, and the hook that solves it:
`recover()` is one synchronous call; there is no callback
between the pre-verification, the settlement loop, and the
post-verification. But settlement of a `POST_RECORD_VERIFIED`
transaction calls `ledger.finalise(...)` (via `_finalise`)
DURING the loop — a subclass hook there runs exactly in the
window, with the real anchor files on disk:

```python
class AnchorSwappingLedger(ShipLedger):
    """finalise() lands, then `swap(path)` rewrites an anchor
    file — simulating a mid-recovery anchor swap with the REAL
    verify_anchor on both sides of it."""
    swap = None  # set per-test: callable(Path) -> None
    def finalise(self, **kw):
        result = super().finalise(**kw)
        if self.swap is not None:
            self.swap()
        return result
```

Fixture note: `TxAnchorFixture` builds `self.ledger =
ShipLedger(self.home)` in `setUp` (inherited); the real-file
class must rebuild BOTH objects over the same home before
`post_record_tx()`:
`self.ledger = AnchorSwappingLedger(self.home)` — and
`post_record_tx()`'s `self.burn(...)`/`recover()` must use that
instance (they do — they go through `self.ledger`).
`ShipLedger` is already imported in the test file.
Caveat to state in the test: the hook fires on finalise, so it
only covers transactions that finalise during recovery (the
`POST_RECORD_VERIFIED` fixture tx does); a tx that parks or
errors never finalises and cannot drive this hook — that is
fine, §5's point is the return-value seam, not coverage of
every settlement path.

### R1 — real anchor corrupted to malformed mid-recovery ⇒ plain `AnchorError`

- Name: `test_post_settlement_real_anchor_turned_malformed_raises_plain`
- Setup: swapping ledger as above; `post_record_tx()`;
  `init_tx_anchor()` (real, valid). NO mock anywhere.
  `self.ledger.swap = lambda: tx_anchor_path().write_text("this is not an anchor\n")`
  (same malformed payload as the existing
  `test_malformed_tx_anchor_is_error_not_anomaly`).
- Call: `journal.recover(self.ledger, loop3(), recorded_at=NOW,
  tx_anchor_path=tx_anchor_path())`.
- Expected: raises plain `AnchorError` (exact type, not JIE);
  `"ship-tx: anchor_malformed" in str(exc)`;
  `exc.outcomes` = single COMMITTED outcome;
  `journal.state(tx_id) == COMMITTED`;
  `ledger_kinds() == ["burn", "finalise"]` (finalise landed
  BEFORE the swap — order inside the hook matters and is
  asserted by this). RED on current code (real post-verify
  returns `("anchor_malformed",)`, currently discarded).

### R2 — real anchor deleted mid-recovery ⇒ plain `AnchorError`, missing-established

- Name: `test_post_settlement_real_anchor_deleted_raises_plain`
- Setup: as R1, swap = `lambda: tx_anchor_path().unlink()`.
- Expected: plain `AnchorError`;
  `"ship-tx: anchor_missing_established_ledger" in str(exc)`
  (journal is non-empty at post-verify — it gained the COMMITTED
  entry — so the real function returns the established variant,
  not `anchor_missing`; asserting the exact variant pins that
  understanding); outcomes/state/ledger as R1.

### R3 (optional, if the both-anchor hook is wanted) — real mixed

- Name: `test_post_settlement_real_forged_tx_and_malformed_ship_mixed`
- Setup: both real anchors valid (ship as T2b + tx). Swap hook
  rewrites BOTH files during finalise: ship anchor →
  `"this is not an anchor\n"`; tx anchor → forged JSON
  `{"v": "ledger-anchor/1", "kind": "ship-tx", "head": "f"*64,
  "seq": 1, "anchored_at": NOW}` (payload copied from
  `RecoveryParkTests._forge_tx_anchor` pattern).
- Expected: `JournalIntegrityError`;
  `exc.reasons == ("anchor_head_not_in_chain",)`;
  `exc.anchor_errors == ("ship: anchor_malformed",)` (D3 format,
  from the REAL return path); outcomes COMMITTED.
  This is the real-file twin of T3; include it if the fix's
  author wants one end-to-end mixed proof — T3 + R1 + R2 are
  sufficient if scope must be cut.

## 6. Suite-level requirements

- Count: +12 mock tests (T1, T2, T2b, T3, T3b, T4, T5, T7, T8,
  T9, T10, T11; T3b is the droppable one, §4) + R1, R2
  mandatory real-file (+R3 optional) ⇒ file goes from 58 to
  72–73 tests; full-suite baseline 1814 ⇒ 1828–1829,
  skipped unchanged.
- No existing test is modified. In particular
  `test_post_settlement_mixed_park_and_anchor_error`,
  `test_post_settlement_anchor_error_only_stays_plain`,
  `test_post_settlement_park_reason_raises_distinct_type`, and
  `test_post_settlement_no_new_reason_does_not_raise` are the
  regression fence for the exception/park paths the fix must
  not disturb.
- Everywhere a settlement is asserted, also assert the ledger
  side (`ledger_kinds()`): a raise must never be accompanied by
  a rolled-back or duplicated finalise.
- Where `.outcomes` is asserted, assert it is a `tuple` (both
  raise sites store `tuple(outcomes)`), not merely list-equal.
