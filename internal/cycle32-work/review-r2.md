# Cycle 32 — War-room review R2 (error surface / types)

Reviewer seat: R2, error surface / types (blind; based on `git diff`
of `trust/shiptx.py`, `tests/test_trust_shiptx_anchoring.py`,
`docs/RECOVERY-CONTRACT.md`, plus `trust/anchoring.py` for the
exception definitions). No code edited by this seat.

## Verdict: SHIP

## Score: 9/10

## Evidence run

- `python3 -m unittest tests.test_trust_shiptx_anchoring` — 68 tests,
  OK (58 pre-cycle + 10 new cycle-32 tests, all passing).

## Findings — discipline checks (all pass)

1. **Error-only → plain `AnchorError`, never `JournalIntegrityError`.**
   In the post-settlement block, returned non-park reasons are appended
   as `(label, None)` pairs, exactly like exception-path failures.
   The raise branches on `park_pairs` (pairs with a bare reason):
   with no park pair, the code constructs `AnchorError(message)`
   directly and raises it — `JournalIntegrityError` is not reachable
   on that branch. Tests pin this with `assertIs(type(exc), AnchorError)`
   plus `assertNotIsInstance(..., JournalIntegrityError)` for returned
   `anchor_malformed`, `anchor_missing_established_ledger`, an unknown
   future reason, and the pre-park + post-returned-error case (a park
   reason seen *pre*-settlement correctly does not convert a new
   post-settlement error into a JIE — "mixed" means mixed among the
   NEW post-settlement findings, which matches the brief).

2. **Mixed park + error → `.anchor_errors`, never `.reasons`.**
   With a park pair present, the raise is `JournalIntegrityError`
   with `reasons`/`anchor_sources` built only from park pairs and
   `anchor_errors=[label for label, r in new_park if r is None]`.
   This is also enforced structurally downstream: the JIE constructor
   validates `reasons ⊆ JOURNAL_INTEGRITY_REASONS` and that
   `anchor_sources` suffixes equal the reasons set, so a non-park
   string leaking into `.reasons` would raise `ValueError`, not ship
   silently. Mixed test asserts exactly:
   `reasons == ("anchor_head_not_in_chain",)`,
   `anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`,
   `anchor_errors == ("ship: anchor_malformed",)`.

3. **`.outcomes` attachment on both raise branches.**
   JIE branch passes `outcomes=outcomes` (constructor stores
   `tuple(outcomes)`); error-only branch sets
   `plain.outcomes = tuple(outcomes)` before raising — the same
   attachment pattern the pre-existing exception path used, so no
   settlement is silently discarded with the return value on either
   branch. Pinned by tests: error-only carries `[COMMITTED]`,
   the no-settlements case carries `()` (not a missing attribute),
   and the pre-park/post-error case carries `[ANOMALY]`.

4. **Message / label formats vs the exception path — distinct and
   consistent.** Returned reasons are labelled
   `"<source>: <bare reason>"` (e.g. `"ship-tx: anchor_malformed"`);
   exception-path failures keep `"<source>: anchor_error:<exc>"`
   (e.g. `"ship: anchor_error:boom"`), matching the initial-verdict
   encoding `f"anchor_error:{exc}"` used for dedup comparison, so a
   returned reason can never collide with or be deduped against an
   exception entry. The combined test asserts both spellings surface
   side by side in one message. Returned-error labels share the bare
   spelling of park labels, but that is not a type-safety issue:
   callers are directed to the structured attributes (`.reasons` /
   `.anchor_sources` vs `.anchor_errors`), never to message parsing,
   and the structural separation in finding 2 is exact.

5. **Per-anchor dedup is correct.** Novelty is tested against that
   anchor's own initial verdict (`r not in ship_reasons` /
   `r not in tx_reasons`), not a global set: a reason already seen on
   the *other* anchor does not suppress a new one (pinned), and an
   identical repeat on the same anchor does not raise (pinned, and
   the run returns the per-transaction error outcome instead).
   Within-run `dict.fromkeys(new_park)` dedup by (label, reason)
   tuple closes the duplicate-returned-tuple case the exception
   channel cannot produce.

## Minor observations (non-blocking, no fix required)

- **Coverage gaps, code verified correct by reading:** the mixed
  JIE test does not assert `.outcomes` on that exception (the plain
  branch's `.outcomes` is pinned, and the JIE constructor path is
  shared with pre-existing pinned tests); there is no mixed test
  where the park reason and the returned error come from the *same*
  anchor (the filter is source-independent, so the cross-anchor
  test exercises the same code path); bare `anchor_missing` itself
  is not tested, only its `anchor_missing_established_ledger`
  sibling — both travel the identical non-park branch.
- **Plain `AnchorError` carries `.outcomes` but no `.anchor_errors`
  attribute** in the error-only case. Consistent with the
  pre-existing exception-path plain raise; the labels are in the
  message. A caller that unconditionally reads `.anchor_errors`
  off any `AnchorError` would get `AttributeError`, but no such
  contract is documented — noted for the record only.
- **Future-reason risk is accepted by design:** any non-park string
  is treated as operator error (brief decision 4). If
  `verify_anchor` ever gains a new chain-mismatch reason without
  `ANCHOR_PARK_REASONS` / `JOURNAL_INTEGRITY_REASONS` being updated
  in step (they are currently identical sets), it would surface as
  plain/`anchor_errors` instead of JIE. That is a standing coupling
  between the two sets, not a regression introduced here.

## Summary

The returned-non-park channel is surfaced exactly like the
exception channel at every point the type discipline cares about:
plain `AnchorError` when error-only, `JournalIntegrityError` with
the error quarantined in `.anchor_errors` when mixed with a new
park reason, `.outcomes` attached on both branches, settlements
standing, and label formats that keep the returned and exception
channels distinguishable. SHIP.
