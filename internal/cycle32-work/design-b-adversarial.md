# Cycle 32 — Design B (adversarial / limits seat)

## Subject

The fix for post-settlement re-verification in `ShipTxJournal.recover()`
(`trust/shiptx.py`) discarding **returned** non-park anchor reasons:
`anchor_malformed`, `anchor_missing`, `anchor_missing_established_ledger`
— and, by the same code path, *any* other non-park string
`verify_anchor` returns as a tuple element.

This note is analysis only. No production code was edited.

## 0. The defect, stated exactly

Code read: `trust/shiptx.py` `recover()` (anchor classification at
lines ~341–347, initial verification ~811–860, post-settlement
re-verification ~979–1055), `trust/anchoring.py` (`verify_anchor`,
`JournalIntegrityError`), tests in `tests/test_trust_shiptx_anchoring.py`.

Initial (pre-settlement) verification classifies **every** element of the
returned tuple:

- `ship_reasons` / `tx_reasons` are the full returned tuples, with a raised
  exception synthesised as `(f"anchor_error:{exc}",)` (lines 817–827).
- Park reasons = elements in `ANCHOR_PARK_REASONS`
  (`anchor_head_not_in_chain`, `anchor_ahead_of_journal`,
  `anchor_kind_mismatch`).
- Error reasons = **everything else** (lines 850–860: `r not in
  ANCHOR_PARK_REASONS`). Note, because the fix depends on it:
  `ANCHOR_ERROR_REASONS` (line 344) is *defined but never used as the
  classifier*. The classifier is the complement of the park set — the
  module docstring says so in words: "Any other anchor failure string
  (including a wrapped anchor_error) is treated as operator error:
  parking is reserved for the three named chain-mismatch reasons."

Post-settlement re-verification (lines 996–1021) does **not** classify
every element. Per anchor it appends to `new_park` only when:

1. `r in ANCHOR_PARK_REASONS and r not in <that anchor's park reasons>`, or
2. `verify_anchor` **raises**, and the synthesised `anchor_error:{exc}`
   string was not in that anchor's initial reasons — appended as
   `(label, None)`, the "error-only" marker.

A **returned** non-park reason matches neither branch and is silently
dropped. Headline consequence: an anchor file deleted or corrupted
*between* the initial verification and the re-check — the exact TOCTOU
window the cycle-17 fix round built this block to close — produces no
signal at all if the failure comes back as a return value rather than an
exception. And in `trust/anchoring.py` the return-value channel is the
*normal* one: `verify_anchor` catches its own `AnchorError` from
`_read_anchor` and returns `("anchor_malformed",)`, returns
`("anchor_missing",)` / `("anchor_missing_established_ledger",)` for an
absent file, and raises only for out-of-contract problems (bad `kind`,
anchor path inside the journal directory). So the discarded channel is
not the exotic one; it is the primary one. The exception channel the
current code handles is, for these three reasons, nearly unreachable
through the real `verify_anchor`.

Attack sketch (the one the fix must kill): recovery verifies clean,
settles transactions to `COMMITTED`, an actor (or a torn concurrent
process) deletes/replaces the ship anchor, the re-check returns
`anchor_missing_established_ledger`, `recover()` returns the `COMMITTED`
outcomes as an unqualified success, and the operator — trusting the
clean return — advances the tx anchor with `update_anchor`. The
mid-run anchor loss leaves no trace anywhere.

## 1. What if the initial verification already returned the same reason?

It must **not** raise. This is the dedup constraint, and it is already
the established semantics for both existing post-settlement channels:

- Park channel: `r not in ship_park_reasons` / `r not in tx_park_reasons`.
- Exception channel, with the reason stated in the code comment: "An
  exception identical to the one the initial verification already
  classified is not a change; only a NEW failure is."
- Existing test `test_post_settlement_no_new_reason_does_not_raise`
  pins the park case.

Applied to returned error reasons, the same rule is load-bearing, not
cosmetic. If the initial verification returned `anchor_missing`, the
settlement loop already produced a per-transaction `error` outcome for
every non-terminal transaction ("operator error; transaction left in
place for the next run") and settled **nothing**. If the re-check
returning the identical `anchor_missing` then raised a plain
`AnchorError`, the run would (a) report the same failure twice, in two
different shapes, (b) discard the per-transaction error outcomes as the
return value (they would survive only if the fix remembers to attach
them as `.outcomes`), and (c) convert a documented non-destructive,
retry-next-run outcome into an exception — a behaviour regression for
every caller that treats a returned error-outcome list as the normal
"fix your anchor path and re-run" path.

Dedup baseline — a trap for the implementer: the comparison must be
against that anchor's **full initial tuple** (`ship_reasons` /
`tx_reasons`), not against the park subset and not against a
re-classified error subset. The full tuple is the only baseline that
also contains the synthesised `anchor_error:{exc}` strings, so it is
the only one that dedups correctly across channels (§6, cross-channel
case).

One apparent spurious-new case checked and cleared: `anchor_missing`
vs `anchor_missing_established_ledger` are different strings, so a
journal growing mid-run could in principle escalate one into the other
with the anchor file missing throughout. In practice it cannot fire
spuriously here: `anchor_missing` (empty journal) at initial time
implies no non-terminal transactions exist for that journal to settle,
so nothing grows it; and any transaction that does settle grows the
*tx* journal, whose missing-anchor reason was already the
`_established_ledger` variant if its journal was non-empty. If the
escalation ever does occur, treating it as new is still defensible —
the classification genuinely changed — but a test should pin whichever
behaviour is chosen rather than leaving it accidental.

The converse asymmetry is intentional and must be preserved: a reason
that *disappears* at re-check (anchor healed mid-run) changes nothing.
The post-settlement block only ever adds failures; it never retracts
the initial verdict or the outcomes already produced from it.

## 2. What if the returned reason is an unknown / unclassified string?

**Treat it as operator error. No exceptions, no allow-list check.**
Three independent grounds:

1. **Consistency with pre-settlement classification.** Pre-settlement,
   the error set is literally "not in `ANCHOR_PARK_REASONS`" (see §0).
   A fix that checks membership in `ANCHOR_ERROR_REASONS` instead
   would recreate the original bug for every string outside that
   three-element set — including strings `verify_anchor` can already
   return under other flags (`reanchor_audit_malformed`,
   `reanchor_audit_chain_broken`, `reanchor_audit_anchor_mismatch`
   from the `check_reanchor_audit` path) and any reason a future
   anchoring cycle adds. The bug being fixed *is* "a closed list
   silently swallowed a failure"; fixing it with another closed list
   is the same defect one level down.
2. **The typed-raise invariant forbids the alternative.**
   `JournalIntegrityError.__init__` validates `reasons ⊆
   JOURNAL_INTEGRITY_REASONS` and raises `ValueError` otherwise —
   deliberately, so an operator reason can never ride in that type.
   A naive fix that appends `(label, r)` with `r` = the unknown
   string (i.e. treats it like a park pair) would therefore not just
   misclassify: it would detonate a `ValueError` inside the raise,
   losing the outcomes, the settlements' report, and the original
   signal, and surfacing as an unrelated-looking crash. Unknown
   strings must enter `new_park` only as `(label, None)` — the
   existing error-only marker — so they land in
   `JournalIntegrityError.anchor_errors` (mixed case) or in the plain
   `AnchorError` (error-only case), never in `.reasons`.
3. **Fail-visible is the safe direction for an unrecognised string.**
   An unknown reason means the verifier said "not verified" in words
   this cycle doesn't understand. Classifying it as a non-destructive
   operator error matches the system's standing rule (parking and
   integrity raises are reserved for the three named chain-mismatch
   reasons, because those are the only ones that are rollback
   evidence). Inventing park/integrity semantics for a string whose
   meaning is unknown would be worse than the error classification.

Edge cases inside this case:

- A returned element that is literally an `anchor_error:...` string
  (a future `verify_anchor` that wraps instead of raising, or a mock):
  pre-settlement treats it as operator error per the docstring; the
  post-settlement fix does too, and if the label is built as
  `f"{source}: {r}"` it coincidentally spells exactly like the
  exception channel's label (`ship: anchor_error:...`) — one more
  reason to build the label from the reason, not to synthesise an
  `anchor_error:` prefix around a returned reason (which would
  double-prefix this case).
- Near-miss spellings (`Anchor_Missing`, trailing whitespace, a
  future renamed reason): exact-match classification makes them
  unknown → operator error. That is consistent with the rest of the
  module and is the safe side (error, not silence; not park).
- Residual limit, stated so it is not discovered later: the park set
  is a closed canonical set on purpose. A *future* anchoring reason
  that is genuinely rollback evidence will be misclassified as
  operator error by **both** the pre- and post-settlement paths until
  someone adds it to `ANCHOR_PARK_REASONS`,
  `anchoring.JOURNAL_INTEGRITY_REASONS`, and the
  `JournalIntegrityError` validation together. That is a pre-existing
  property of the design, not something this fix should try to solve
  — but the fix must not make it worse by adding a *second* closed
  list (`ANCHOR_ERROR_REASONS`) that future reasons must also join
  before they are even reported.

## 3. What if one anchor returns an error and the other returns a park?

This is the mixed case, and the exception channel already defines the
required shape — pinned by
`test_post_settlement_mixed_park_and_anchor_error`: the park reason
drives a `JournalIntegrityError`; the error rides in `.anchor_errors`;
`.reasons` and `.anchor_sources` contain **only** the park entries;
the settlements stand and ride on `.outcomes`. The returned-reason fix
must produce the *identical* shape when the error arrives as a return
value instead of an exception:

- ship returns `("anchor_malformed",)` (new), tx returns
  `("anchor_head_not_in_chain",)` (new) → `JournalIntegrityError`,
  `reasons == ("anchor_head_not_in_chain",)`,
  `anchor_sources == ("ship-tx: anchor_head_not_in_chain",)`,
  `anchor_errors == (<ship's labelled error>,)`.
- Mirror image (ship parks, tx errors) symmetrically.
- Same anchor returning **both** in one tuple, e.g.
  `("anchor_malformed", "anchor_head_not_in_chain")`: `verify_anchor`
  today returns at most one reason, but its contract is a tuple and
  the post-settlement loop already iterates elements. The fix must
  classify **element-wise**, splitting one anchor's tuple across the
  park and error channels — never classify the tuple as a whole, and
  never let the error element suppress or contaminate the park
  element (or vice versa).
- If the error element was already present in that anchor's initial
  reasons while the park element is new: dedup removes the error,
  `anchor_errors` is empty, the raise is a pure integrity raise.
  Dedup is per-element, per-anchor (§5), applied before the
  park/error split of what remains.

**Open spelling decision the coders must pin in a test, not leave to
taste:** the exception channel labels its `anchor_errors` entries
`f"{source}: anchor_error:{exc}"` (e.g.
`"ship: anchor_error:anchor_malformed"`). For a *returned* reason
there are two candidate spellings:

- `"ship: anchor_malformed"` — the reason as-is, matching the
  pre-settlement labelled error format (`_label(source, reason)`),
  and matching what the same failure looks like everywhere else in
  the run's output.
- `"ship: anchor_error:anchor_malformed"` — matching the exception
  channel's `anchor_errors` spelling, at the cost of claiming an
  exception wrapper that never happened and double-naming the
  failure.

Recommendation: `"ship: anchor_malformed"` (build the label as
`f"{source}: {r}"`). Rationale: `anchor_error:` is defined in this
codebase as "verify_anchor raised and we synthesised the string";
a returned reason was not synthesised, and consumers diffing
pre-settlement error strings against `anchor_errors` should find the
same text. But whichever spelling is chosen, it is a wire-visible
format: pin it in the mixed-case test. An unpinned choice here is
how the two channels drift apart again.

Ordering/dedup detail: `new_park` is built ship-then-tx, and the
`anchor_errors` extraction preserves that order. Duplicate elements
in a returned tuple (pathological, mock-only today) should be
deduped before joining into the message — `JournalIntegrityError`
dedups its own `reasons`/`anchor_sources`, but the plain
`AnchorError` message is a raw `", ".join(...)` over labels and
would happily print the same failure twice.

## 4. What if no settlements occurred (outcomes empty) — should it still raise?

**Recommendation: yes — raise, exactly as the exception channel
already does.** The deciding argument is channel consistency, not
the empty-outcomes case in isolation:

- Today, a *new exception* at re-check raises the plain `AnchorError`
  unconditionally once `new_park` is non-empty; the code attaches
  `.outcomes = tuple(outcomes)` whether or not that tuple is empty.
  If a *returned* reason with identical meaning ("anchor unreadable /
  missing / malformed, newly appeared") silently returned `[]`
  whenever `outcomes` happened to be empty, the same physical event
  would raise or not raise depending on which of two channels
  `verify_anchor` happened to report it through. That is precisely
  the channel asymmetry this fix exists to remove.
- `[]` reads as a clean recovery. The codebase has already decided,
  in the adjacent pre-settlement case, that a clean-looking empty
  return is the failure mode to avoid: a tx-anchor park with no
  non-terminal transaction to park raises `JournalIntegrityError`
  rather than returning `[]` (cycle 17, with the reasoning recorded
  in the code). A newly-vanished anchor discovered at re-check is
  the same shape of fact — evidence with nowhere else to land. If
  this run doesn't raise, and the anchor is still missing next run
  but still no transaction is non-terminal, the pre-settlement path
  also returns `[]` (ship anchor) — the mid-run loss could pass
  through *every* run unreported.
- The cost of raising is low and bounded: it is a plain
  `AnchorError`, not an integrity raise, it parks nothing, it rolls
  back nothing, and the settlements (if any) ride on `.outcomes`.

The honest counter-argument, recorded so the war room weighs it
rather than discovers it: the plain-`AnchorError` branch was
justified in its fix round as "outcomes are attached so settlements
are not silently discarded" — with zero outcomes there is nothing
to discard, and an operator-error anchor problem will be reported
again, per-transaction, by the next run that has anything to settle.
On that view a no-settlement raise is noise. It loses, in this
seat's judgement, because "nothing settled this run" is not the
same as "nothing happened": the anchor state *changed during the
run*, which is the specific event the re-verification exists to
catch, and a caller that treats a normal return as "recovery is
clean, proceed to advance anchors" is misled by silence in a way
it is not misled by an exception. (`update_anchor` would in fact
refuse over a missing anchor on its own — so silence is not
directly exploitable into a bad pin — but the run's report would
still be wrong.)

Sub-case worth pinning either way: `outcomes` empty because every
snapshot was already terminal is the true no-op run; `outcomes`
can also end up empty when a concurrent run settled the
transactions mid-loop (the error-collection path drops outcomes
for transactions found terminal on re-read). In the second case
settlements *did* occur during the window — another reason not to
key the raise off `len(outcomes)`.

## 5. Per-anchor dedup vs global dedup — the cross-anchor trap

Dedup must be **per anchor, against that anchor's own initial
tuple**. A global dedup ("reason already seen anywhere in this
call") is actively wrong, because the canonical reasons are
kind-agnostic strings that both anchors produce independently:

- Pre-settlement: ship returns `("anchor_missing",)`, tx returns
  `()`. Post-settlement: ship returns `()` (restored), tx returns
  `("anchor_missing",)` (its file was deleted mid-run). Global
  dedup sees `anchor_missing` "already reported" and discards the
  tx event — the fix would ship with a hole in exactly the shape
  of the original bug. Per-anchor dedup correctly raises: for the
  tx anchor this reason is new.
- Reverse: pre ship `anchor_missing`, post ship `anchor_missing`
  again → per-anchor dedup hits, no raise (§1). Global dedup also
  gets this one right, which is why the trap is easy to miss in
  testing: the naive implementation passes the obvious test and
  fails the cross-anchor one. The cross-anchor test is therefore
  mandatory, in both directions.
- Both anchors newly returning the same reason post-settlement
  (both files deleted mid-run): two labelled entries
  (`ship: ...`, `ship-tx: ...`), one plain `AnchorError` if both
  are error-class, or both labels in `anchor_errors` / sources as
  appropriate. Pre-settlement already preserves this distinction
  by deduping *labelled* strings in `anchor_error_reasons`; the
  post-settlement fix must likewise dedup after labelling, never
  on bare reasons across anchors.
- The existing park channel already implements per-anchor dedup
  correctly (`ship_park_reasons` for ship, `tx_park_reasons` for
  tx). The fix should mirror that structure for errors — ideally
  by checking the full per-anchor tuple (`ship_reasons` /
  `tx_reasons`), which subsumes the park subsets and the
  synthesised exception strings in one comparison.

Related guards the fix must not disturb:

- `same_path_error`: when both paths name the same file, both
  initial verifications are suppressed and the whole
  post-settlement block is skipped (guard at line 979). The fix
  inherits this; it must not re-verify in the same-file case
  (doing so manufactures a kind mismatch over a wiring typo).
- An anchor that was not supplied (`None`) is never verified, in
  either pass. Its dedup baseline is vacuous; the fix must not
  call `verify_anchor` for it or invent a baseline for it.
- Labelling in the post-settlement block is unconditional
  (`f"ship: {r}"` even for a ship-only caller), unlike the
  pre-settlement `labelled` flag. Error entries produced by the
  fix should follow the post-settlement convention already in
  force in that block, for consistency within the raise.

## 6. Cross-channel and miscellaneous edge cases

- **Same failure, different channel across the two passes.**
  Initial pass: `verify_anchor` raises (say the anchor path is
  inside the journal dir — a placement `AnchorError`), so
  `ship_reasons == ("anchor_error:anchor path must live OUTSIDE
  ...",)`. Post pass: the same raise recurs. The existing
  exception-channel dedup already handles this. The fix must not
  break it by, e.g., comparing post reasons against a baseline
  that excluded synthesised strings.
- **Failure changes channel between passes.** Initial: returned
  `("anchor_malformed",)`. Post: the file is now also misplaced /
  unreadable in a way that raises, synthesising a *different*
  string. Not deduped — correctly: it is new evidence, reported
  as a new error. Acceptable and preferable to suppression.
- **Anchor torn-write at re-check.** Anchor writes in this
  codebase are atomic (`_write_json_atomic`, tmp + replace +
  fsync), so a malformed anchor at re-check is genuine corruption,
  substitution, or a non-atomic *external* writer — never a
  half-finished legitimate `update_anchor`. Classifying it as
  operator error (not park) remains right: malformed proves
  nothing about the journal's chain. But "operator error" must
  not mean "invisible", which is the current behaviour.
- **Settlements stand.** Neither raise discards journaled
  settlements; both carry them on `.outcomes`. The fix must
  attach outcomes on the plain-`AnchorError` branch for
  returned-reason raises exactly as the exception branch does
  (line ~1051 precedent) — a returned-reason raise that forgets
  `.outcomes` silently throws away the run's settlement report,
  recreating a different silent-loss bug.
- **Idempotency / next run.** A post-settlement error raise
  changes no state. Next run re-verifies from scratch: if the
  anchor is still bad, the failure now arrives through the
  pre-settlement path (per-transaction error outcomes, or the
  tx-park no-transaction raise if it escalated to a park reason);
  if it was transient, the next run is clean. No double-park, no
  stuck transaction results from the raise itself.
- **Flapping anchor.** An anchor missing only at the re-check
  instant and restored before the operator looks will still have
  raised. That is the intended signal-preservation trade-off of
  the whole re-verification design (same as the park channel);
  the alternative — re-re-verifying until it agrees with itself —
  would let a fast swap-and-restore pass undetected.
- **Message construction.** The raise message joins the labels of
  *all* new entries (park and error). With returned errors now
  included, the existing message text ("a journal was swapped or
  rolled back mid-run") will sometimes describe a run where the
  only change is a deleted anchor file. That wording is already
  loose for the exception-error case; the fix does not need to
  solve it, but the war room may want the message to stay honest
  — at minimum, tests should assert on the structured attributes
  (`.reasons`, `.anchor_sources`, `.anchor_errors`, `.outcomes`,
  exception type), not on message substrings, for the new cases.

## 7. Invariants the fix must preserve (checklist for review)

1. Returned non-park reason, new for its anchor ⇒ `(label, None)`
   entry; never `(label, r)`.
2. Classification of returned strings is complement-of-park;
   `ANCHOR_ERROR_REASONS` membership is never consulted.
3. Dedup is per-anchor, per-element, against the anchor's full
   initial tuple (park reasons, error reasons, and synthesised
   `anchor_error:` strings alike).
4. Park + returned-error (either anchor, or both from one anchor's
   tuple) ⇒ `JournalIntegrityError` with the error only in
   `.anchor_errors`; error-only ⇒ plain `AnchorError` with
   `.outcomes` attached; both raise even when `outcomes` is empty.
5. No new behaviour when nothing changed: identical initial and
   post reasons (any channel, any class) ⇒ normal return.
6. `same_path_error` still suppresses the entire post-settlement
   pass; unsupplied anchors are never verified.
7. Nothing is parked, rolled back, or re-settled because of a
   returned error reason; settlements already journaled stand.

## 8. Test matrix the fix should be required to pass

Mirroring the existing `test_post_settlement_*` naming and mocking
style (`mock.patch("trust.anchoring.verify_anchor")`, first call
clean / second call changed):

| # | Setup | Post-settlement return | Expected |
|---|-------|------------------------|----------|
| 1 | tx anchor only, clean initial | `("anchor_missing",)` | plain `AnchorError` (exact type, not `JournalIntegrityError`); tx state `COMMITTED`; `.outcomes` carries the settlement |
| 2 | ship anchor only, clean initial | `("anchor_malformed",)` | plain `AnchorError`, as #1 |
| 3 | either anchor, clean initial | `("anchor_missing_established_ledger",)` | plain `AnchorError`, as #1 |
| 4 | initial already `("anchor_missing",)` for same anchor | same | **no raise**; per-transaction error outcomes returned normally |
| 5 | initial ship `("anchor_missing",)`, tx clean | tx returns `("anchor_missing",)` | plain `AnchorError` (per-anchor dedup; the cross-anchor trap, §5) — and the mirror direction |
| 6 | clean initial | `("anchor_brand_new_reason",)` | plain `AnchorError`; no `ValueError`; string appears only as an error label |
| 7 | clean initial, both anchors | ship `("anchor_malformed",)`, tx `("anchor_head_not_in_chain",)` | `JournalIntegrityError`; `reasons` park-only; `anchor_errors` holds the ship error with the pinned spelling (§3) |
| 8 | clean initial, one anchor | single tuple `("anchor_malformed", "anchor_head_not_in_chain")` | element-wise split: `JournalIntegrityError`, error in `.anchor_errors`, park in `.reasons` |
| 9 | no non-terminal transactions, clean initial | `("anchor_missing",)` | raises plain `AnchorError` with `.outcomes == ()` (pins the §4 decision) |
| 10 | clean initial, both anchors | both return `("anchor_missing",)` | one plain `AnchorError` naming both labelled sources |
| 11 | initial exception for ship (synthesised `anchor_error:...` in baseline) | ship returns that same `anchor_error:...` string as a tuple element | no raise (cross-channel dedup against the full initial tuple, §6) |
| 12 | initial `("anchor_missing",)` for ship + park for tx (tx parks pre-settlement) | ship returns `("anchor_missing",)` again | no *additional* error entry; outcome is the pre-settlement park behaviour, unchanged |
| 13 | duplicate elements in post tuple | `("anchor_missing", "anchor_missing")` | single labelled entry in the message / `.anchor_errors` |

Tests 4, 5, and 11 are the ones a plausible-but-wrong fix fails;
they should be treated as the gate, not as nice-to-haves.

## 9. Bottom line

The fix is small but the classification discipline is the whole
game: **every** returned element gets classified, complement-of-park
means operator error, dedup is per-anchor against the full initial
tuple, errors never enter `JournalIntegrityError.reasons`, and a
genuinely new failure raises even if the run settled nothing. The
two decisions the war room must explicitly ratify (both
recommended above, both needing a pinning test): raise-on-empty-
outcomes (§4) and the `anchor_errors` spelling for returned
reasons (§3).
