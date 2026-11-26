# Cycle 32 — design A (correctness seat)

## Problem, stated from the code

`ShipTxJournal.recover()` in `trust/shiptx.py` (post-settlement block,
~lines 981–1055) re-verifies each supplied anchor after the settlement
loop, because the pre-settlement verdicts are a stale snapshot: no lock
is held across verify + settle, and a journal/anchor swapped mid-run
must not pass on the old verdict.

The re-verification collects evidence into `new_park`, a list of
`(label, bare_park_reason_or_None)` pairs:

- returned value `r in ANCHOR_PARK_REASONS` and not seen initially →
  `(f"{source}: {r}", r)` — a *park* entry;
- `verify_anchor` **raising** on the re-check, with a failure string
  not seen initially → `(f"{source}: anchor_error:{exc}", None)` — an
  *error* entry (the `None` bare reason is the error marker).

Dispatch after collection is already correct and complete:

- any park pair → `JournalIntegrityError(message, reasons=[bare park
  reasons], anchor_sources=[park labels], outcomes=outcomes,
  anchor_errors=[labels of the `None` entries])`;
- error entries only → plain `AnchorError(message)` with
  `plain.outcomes = tuple(outcomes)`;
- settlements already journaled stand in both cases; nothing is
  re-parked or rolled back.

The gap is purely in **collection**: a reason **returned** by
`verify_anchor` that is not a park reason is silently discarded. The
loop's condition is `if r in ANCHOR_PARK_REASONS and …`, with no
`else`. `verify_anchor` (`trust/anchoring.py`) returns operator-error
reasons as values, never raises them: `anchor_malformed` (any bad or
unreadable anchor content), `anchor_missing` (no file, empty journal),
`anchor_missing_established_ledger` (no file, non-empty journal) — the
`ANCHOR_ERROR_REASONS` set in `trust/shiptx.py`. A mid-recovery swap
to a malformed anchor, or deletion of the anchor file, therefore
passes unreported even though the settlements stand. The exception
path proves this is an omission, not a policy: the identical failure
arriving as an exception *does* raise. Correctness requires the
surface to depend on the failure, not on which of `verify_anchor`'s
two delivery channels carried it.

## Fix: exact semantics

Change only the two collection loops (ship, then tx). Downstream
dispatch, the message construction, and both raise sites are
untouched.

### 1. Per-anchor novelty ("NEW")

A post-settlement result for an anchor is NEW iff it was not in
**that same anchor's** initial result:

- returned reason `r` from the ship anchor is NEW iff
  `r not in ship_reasons`; from the tx anchor iff
  `r not in tx_reasons`. `ship_reasons` / `tx_reasons` are the raw
  initial tuples captured pre-settlement (bare reasons, or the single
  synthetic `f"anchor_error:{exc}"` if the initial call raised).
- Dedup is **per anchor, never cross-anchor**: a reason already seen
  on the *other* anchor does not suppress it here. The two anchors pin
  two different journals; the same bare string from the tx anchor is
  new evidence about a different object. (This matches the existing
  exception-path dedup, which compares against the same anchor's
  initial tuple only.)
- Dedup is **string-exact against the raw initial tuple**, with no
  normalisation between channels: an initial exception recorded as
  `anchor_error:anchor_malformed` does not suppress a post-settlement
  returned `anchor_malformed`, nor vice versa. They are different
  observations of a still-failing anchor, and in that situation the
  initial failure already produced per-transaction error outcomes
  (no settlements), so the post raise carries those outcomes and
  loses nothing.
- Dedup also applies **within** the post-settlement collection:
  the same label is appended at most once (first occurrence wins).
  `verify_anchor` normally returns unique tuples, but the collector
  must not emit a doubled label in the message / `anchor_errors`
  if a future return value repeats a reason.

### 2. Classification of a NEW returned reason

For each NEW returned `r`, in the order `verify_anchor` returned it:

- `r in ANCHOR_PARK_REASONS` → park entry `(f"{source}: {r}", r)`
  (unchanged behaviour).
- **Any other `r`** → error entry `(f"{source}: {r}", None)` — the
  same `None`-marker shape as an exception-path entry, so the
  existing dispatch consumes it with no new branch.

"Any other" is deliberate, mirroring the pre-settlement
classification in the same method (park = exactly the three
chain-mismatch reasons; everything else is operator error). It covers
the three named `ANCHOR_ERROR_REASONS` today and any future non-park
reason (e.g. a reanchor-audit reason if audit checking is ever
enabled on this path) without a second fix. Enumerating only the
three named reasons would recreate this bug for the next reason
string.

Labels in the post-settlement block are **always** source-prefixed
(`ship: …` / `ship-tx: …`), even for a ship-only caller — that is the
existing post-settlement convention (the pre-settlement `labelled`
flag does not apply here) and returned errors follow it.

The returned-error label is `"<source>: <bare reason>"`
(e.g. `"ship-tx: anchor_malformed"`), **distinct** from the
exception-path label `"<source>: anchor_error:<exc>"`. The
distinction is informative and must be preserved: one says
"`verify_anchor` returned this refusal", the other says "the
verification itself failed to run".

### 3. Error-only change → plain `AnchorError`

If the collection contains error entries and no park entry:

```text
plain = AnchorError(message)
plain.outcomes = tuple(outcomes)
raise plain
```

- Exact type `AnchorError`, **never** `JournalIntegrityError`:
  operator/load failures must not mint the integrity type (its
  constructor would refuse anyway — `reasons` must be a non-empty
  subset of `JOURNAL_INTEGRITY_REASONS`).
- `.outcomes` is a **tuple** of the completed outcome dicts, exactly
  as the existing exception-only branch sets it. No `.reasons`,
  `.anchor_sources`, or `.anchor_errors` attribute is added to the
  plain error — parity with the exception path is the contract;
  callers use `getattr(exc, "anchor_errors", ())`.
- This fires even when `outcomes` is empty (`.outcomes == ()`): the
  raise is about the anchor evidence, not about settlements.

### 4. Mixed NEW park + NEW returned error → `JournalIntegrityError`

If at least one park entry and at least one error entry (returned
and/or exception-path) are collected:

```text
raise JournalIntegrityError(
    message,
    reasons=[bare r for park entries, deduped, encounter order],
    anchor_sources=[park labels, encounter order],
    outcomes=outcomes,
    anchor_errors=[error labels, encounter order])
```

- `anchor_errors` format: the **label strings exactly as collected**
  — `"ship: anchor_malformed"`,
  `"ship-tx: anchor_missing_established_ledger"` for returned
  reasons; `"ship: anchor_error:<exc>"` for exception-path failures.
  Returned and exception entries interleave in collection order
  (ship anchor processed before tx anchor, matching the current
  loop order).
- Error labels go **only** in `anchor_errors` — never in `reasons`
  or `anchor_sources`. Putting one there trips the constructor's
  `ValueError` (suffix set of `anchor_sources` must equal the
  `reasons` set, and reasons must be canonical park reasons), i.e.
  a classification slip becomes a wrong-type crash at the raise
  site instead of the intended exception. `anchor_errors` elements
  receive no content validation in `trust/anchoring.py`, so the
  returned-reason labels are safe there.
- The message is the existing construction — `"anchor verification
  changed during recovery; a journal was swapped or rolled back
  mid-run: "` + all collected labels (park and error) joined in
  encounter order — so a returned error appears in `str(exc)` just
  as the exception-path error does in the pinned mixed test.

### 5. What does not change

- Pre-settlement verification, classification, park-over-error
  combination, per-transaction error outcomes, and the
  no-park-target `JournalIntegrityError` raise: untouched.
- Same-file guard: if both paths name the same file, post-settlement
  re-verification does not run at all; returned errors are moot.
- Only supplied anchors are re-verified; an unsupplied anchor
  produces no entries.
- A post-settlement raise never moves a transaction: settlements
  (including ANOMALY parks from an initial park verdict) stand as
  journaled; the raise only reports.
- One anchor's re-check raising does not skip the other anchor's
  re-check (existing per-anchor `try/except`); returned reasons are
  collected anchor-by-anchor in ship-then-tx order.

## Edge cases

1. **Repeat of an initial reason, same anchor** — initial and post
   both return `anchor_malformed` for the tx anchor: suppressed, no
   raise; `recover()` returns normally (with the per-transaction
   error outcomes the initial verdict already produced). The
   existing park analogue is pinned by
   `test_post_settlement_no_new_reason_does_not_raise`.
2. **Same bare reason, other anchor** — initial ship returns
   `anchor_malformed`, post tx newly returns `anchor_malformed`:
   NEW for tx; error-only → plain `AnchorError` whose message
   contains `ship-tx: anchor_malformed` (and not a second ship
   entry, the ship post result being a suppressed repeat).
3. **Initial park, NEW error only post** — transactions already
   parked at ANOMALY pre-settlement; post adds only a returned
   error: **plain** `AnchorError` carrying the ANOMALY outcomes,
   *not* `JournalIntegrityError`. The integrity type is reserved
   for park evidence discovered post-settlement. This asymmetry is
   existing exception-path semantics; returned errors inherit it
   deliberately.
4. **Initial error, NEW park post** — `JournalIntegrityError`
   (existing behaviour, unchanged); the initial error does not
   ride anywhere — only NEW evidence is reported post-settlement.
5. **Park + error from the same anchor in one return tuple** —
   e.g. tx post returns `("anchor_head_not_in_chain",
   "anchor_malformed")` (order as returned): mixed raise, `reasons
   == ("anchor_head_not_in_chain",)`, `anchor_sources ==
   ("ship-tx: anchor_head_not_in_chain",)`, `anchor_errors ==
   ("ship-tx: anchor_malformed",)`.
6. **Returned error on one anchor + exception on the other** —
   both are error entries; plain raise if no park, both labels in
   the message in ship-then-tx order; with a park anywhere, both
   labels in `anchor_errors` in that order.
7. **Anchor deleted mid-run** — post `verify_anchor` returns
   `anchor_missing` (pinned journal now empty — not reachable after
   settlements grow it) or, in practice after any settlement,
   `anchor_missing_established_ledger`. Both are error entries;
   which of the two appears is `verify_anchor`'s call at re-check
   time and the collector must not care.
8. **No transactions / no settlements** — post block runs whenever
   an anchor path was supplied and the same-file guard did not
   fire, even with `outcomes == []`; a NEW returned error still
   raises plain `AnchorError` with `.outcomes == ()`. (Contrast
   pre-settlement, where carrier-less ship evidence returns `[]` —
   that hole is a separate open item, not this cycle's.)
9. **Returned string identical in form to an exception wrapper** —
   if a future `verify_anchor` *returned* `"anchor_error:…"` as a
   value, it would be labelled `"ship: anchor_error:…"` and be
   indistinguishable from an exception entry. Accepted: the
   failure surface is identical, and no current return value has
   that form.
10. **Label-format collision risk** — a returned-error label
    (`"ship-tx: anchor_malformed"`) has the same shape as a park
    label in `anchor_sources`. They never share a list: park
    labels live in `anchor_sources`, error labels in
    `anchor_errors` (or only in the plain error's message).
    Consumers must read the attributes, not parse the message;
    the design adds no message parsing anywhere.
11. **Kind mismatch is not an error case** — `anchor_kind_mismatch`
    is a park reason and stays on the park path; a swapped-in
    wrong-kind anchor file post-settlement already raises the
    integrity error today.

## Tests needed

Failing-first: every "NEW returned error" test below is red on
current code (the run returns outcomes silently); suppression tests
are green-before-and-after guards. Mock pattern follows the pinned
file (`tests/test_trust_shiptx_anchoring.py`): patch
`trust.anchoring.verify_anchor` with a per-anchor call counter —
first call = initial verdict, second = post-settlement verdict.

1. **Error-only, tx, malformed (returned)** — initial `()`, post
   `("anchor_malformed",)`: exact type `AnchorError`, not
   `JournalIntegrityError`; transaction reaches COMMITTED;
   `exc.outcomes` is a tuple with the COMMITTED outcome; message
   contains `"ship-tx: anchor_malformed"`.
2. **Error-only, ship-only caller, missing** — post returns
   `("anchor_missing",)`: plain `AnchorError`, label
   `"ship: anchor_missing"` (prefixed even ship-only).
3. **Error-only, `anchor_missing_established_ledger`** — post
   returns it for the tx anchor: plain `AnchorError`, correct
   label.
4. **Mixed, cross-anchor** — ship post returns
   `("anchor_malformed",)`, tx post returns
   `("anchor_head_not_in_chain",)`: `JournalIntegrityError`,
   `reasons == ("anchor_head_not_in_chain",)`,
   `anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`,
   `anchor_errors == ("ship: anchor_malformed",)`, settlements in
   `exc.outcomes`, error label in `str(exc)`.
5. **Mixed, same anchor** — one post return of
   `("anchor_head_not_in_chain", "anchor_malformed")`:
   `anchor_errors == ("ship-tx: anchor_malformed",)` (or the
   ship analogue); reasons/sources contain only the park entry.
6. **Mixed, returned error + exception error + park** — e.g. ship
   post raises, tx post returns park + malformed: `anchor_errors`
   holds both error labels in ship-then-tx order; neither appears
   in `reasons`/`anchor_sources` (constructor would refuse).
7. **Suppression, same anchor** — initial and post both return
   `("anchor_malformed",)` for the same anchor: no raise; the
   returned outcomes are the per-transaction anchor-error
   outcomes from the initial verdict.
8. **No cross-anchor suppression** — initial ship
   `("anchor_malformed",)`, initial tx `()`, post ship repeats it,
   post tx newly returns `("anchor_malformed",)`: plain
   `AnchorError` raised; message contains the `ship-tx:` label.
9. **Unknown non-park string** — post returns
   `("some_future_reason",)`: treated as operator error (plain
   `AnchorError`), pinning decision "any non-park string".
10. **Both anchors, error-only** — post returns a different named
    error per anchor, no park: one plain `AnchorError`, both
    labels in the message in ship-then-tx order, `.outcomes`
    preserved.
11. **Duplicate in post tuple** — post returns
    `("anchor_malformed", "anchor_malformed")`: the label occurs
    exactly once in the message.
12. **Zero outcomes** — all transactions terminal before the run;
    post returns a NEW error: plain `AnchorError` with
    `exc.outcomes == ()`.
13. **Initial park + NEW returned error only** — post adds an
    error, no new park: plain `AnchorError` (not the integrity
    type) carrying the ANOMALY outcomes (edge case 3).
14. **Real-verifier integration (one, non-mock values)** — the
    post call delegates to the real `verify_anchor` after the
    test overwrites the anchor file with malformed bytes /
    deletes it: proves the returned-tuple path end-to-end, not
    only the mock's tuple shape; expect the plain raise with the
    corresponding real reason label.
15. **Regression** — the existing post-settlement tests
    (park-only integrity raise, exception-only plain raise,
    mixed park + exception, no-new-reason) pass unmodified, and
    the full suite stays green (baseline 1814 tests, per the
    cycle-32 brief).

## Implementation note (for the builder, not part of this design's
## authority)

The minimal correct diff is inside each post-settlement loop:

```python
for r in verify_anchor(...):
    if r in ANCHOR_PARK_REASONS:
        if r not in <initial reasons for this anchor>:
            new_park.append((f"{source}: {r}", r))
    elif r not in <initial reasons for this anchor>:
        label = f"{source}: {r}"
        if label not already in new_park:
            new_park.append((label, None))
```

plus the same not-already-present guard on the park and exception
appends if within-run dedup (semantics §1) is implemented at append
time rather than by a seen-set. No other lines change.
