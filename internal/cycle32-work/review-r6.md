# Cycle 32 — War-room review R6 (completeness / docs)

Reviewer: R6, completeness/docs seat
Subject: `git diff` — `trust/shiptx.py` `recover()` docstring and
`docs/RECOVERY-CONTRACT.md` "Closed (cycle 32)" update, against the
implemented post-settlement re-verification in `trust/shiptx.py`
and the new tests in `tests/test_trust_shiptx_anchoring.py`.
No code or docs edited by this seat.

Score: 0.82
Verdict: FIX

## What matches exactly (the three axes checked)

1. **Label format — MATCH.** Post-settlement returned reasons are
   appended as `(f"ship: {r}", None)` / `(f"ship-tx: {r}", None)`,
   i.e. `"<source>: <bare reason>"` (e.g. `"ship-tx: anchor_malformed"`),
   unconditionally source-prefixed in the post-settlement block —
   distinct from the exception-path label
   `"<source>: anchor_error:<exc>"`. Both the docstring and the
   contract's Closed paragraph state this format correctly, and the
   mixed test pins it (`anchor_errors == ("ship: anchor_malformed",)`).
2. **Per-anchor dedup — MATCH.** The new `elif` branches test
   `r not in ship_reasons` for the ship anchor and
   `r not in tx_reasons` for the tx anchor separately; there is no
   cross-anchor suppression. Contract ("deduped per anchor against
   that anchor's initial verdict. Only identical repeats are
   suppressed") and docstring ("deduped per anchor against that
   anchor's initial verdict") both state this correctly. Pinned by
   `test_post_returned_same_reason_pre_and_post_no_raise` (same
   anchor, suppressed) and
   `test_post_returned_reason_on_other_anchor_is_new` (other anchor,
   not suppressed).
3. **`anchor_errors` placement — MATCH.** Returned reasons carry the
   `None` bare-reason marker, so on the mixed dispatch they land
   only in `JournalIntegrityError.anchor_errors`
   (`[label for label, r in new_park if r is None]`), never in
   `.reasons` or `.anchor_sources`; error-only they raise plain
   `AnchorError` carrying `.outcomes` (no `anchor_errors` attribute
   added), exactly as the docstring ("riding in `anchor_errors`
   when a park reason accompanies them") and the contract state.
   Pinned by `test_post_returned_mixed_park_and_malformed_is_jie`
   (`reasons == ("anchor_head_not_in_chain",)`,
   `anchor_errors == ("ship: anchor_malformed",)`) and
   `test_post_returned_malformed_only_raises_plain`.

## Findings (FIX)

1. **Stale test count in the same contract file (concrete
   inaccuracy).** "Operating it" still says the pin file runs
   "(58 tests)". This cycle adds 10 tests to that file; verified
   this run: `python3 -m unittest tests.test_trust_shiptx_anchoring`
   runs **68 tests, OK**. A contract whose stated purpose is claims
   "evidenced by … tests" cannot keep the pre-cycle count. One-line
   fix: 58 → 68.
2. **The lead sentences of "The two raises", item 2, were not
   updated and now read as exception-only.** They still say only
   "any accompanying EXCEPTION-path load failures" go in
   `.anchor_errors` and "A new exception-path load failure alone
   raises plain `AnchorError`". That is true but incomplete after
   cycle 32: returned non-park reasons now do both as well. The
   appended Closed paragraph supplies the correction, but a reader
   of the normative sentences alone gets the pre-cycle-32 rule.
   The lead sentences should say exception-path *or returned*
   failures, with the Closed paragraph as the detail.
3. **"When a park reason accompanies" lacks the NEW qualifier
   (both texts).** Placement in `.anchor_errors` is triggered only
   by a *new post-settlement* park entry in the same collection
   (`park_pairs` from `new_park`). A park reason from the *initial*
   verdict does not convert a new returned error into a
   `JournalIntegrityError`: pinned by
   `test_pre_park_plus_post_returned_error_stays_plain` (initial
   park, post `anchor_malformed` → plain `AnchorError` with ANOMALY
   outcomes). Docstring and contract both omit "new", so the
   sentence as written over-promises the JIE/`anchor_errors` route.
4. **Generality and within-run dedup are undocumented (minor).**
   The implementation surfaces *any* returned non-park reason not
   in the initial verdict — not only `anchor_malformed` /
   `anchor_missing*` — pinned by
   `test_post_returned_unknown_reason_is_operator_error`
   (`some_future_reason`). Both texts enumerate only
   malformed/missing, which is the complete set `verify_anchor`
   returns on this call path today, so the claim is not false, but
   it understates the implemented rule. Likewise the new
   within-run dedup `new_park = list(dict.fromkeys(new_park))`
   (by `(label, marker)` pair) is mentioned in neither text;
   "deduped per anchor against that anchor's initial verdict"
   describes only half the dedup actually applied.

## Open-items check

**PASS — no stale entry.** The contract's "Open items carried from
this contract" section (wire a production recovery caller that
passes `tx_anchor_path`; choose a non-`[]` surface for carrier-less
evidence; pin-store head anchoring / pin-directory loss /
operator-authentication-channel / concurrent-actor interleaving)
does **not** list the post-settlement returned-reason gap. The old
"Gap:" paragraph in "The two raises" was correctly replaced by
"Closed (cycle 32):", and no other section re-lists the item as
open. Nothing to remove there.

## What would change the verdict

Fix finding 1 (58 → 68) and finding 2 (make the item-2 lead
sentences cover returned reasons), and add the "new" qualifier in
finding 3. Finding 4 is a one-clause addition ("any returned
non-park reason"; "repeats within the re-check are also deduped").
No behavioural or code change is required — the implementation and
its tests are consistent; the documentation is one revision short
of exact.
