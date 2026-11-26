# Cycle 31 — War-room review R3 (forced dissent)

Reviewer: R3, dissent seat
Subject: `docs/RECOVERY-CONTRACT.md` (untracked, proposed for ship)
Scope checked: the contract itself; `trust/shipcheck.py` (cycle-23
wiring in particular); `trust/shiptx.py:713ff` (`ShipTxJournal.recover`);
`trust/anchoring.py` (`JOURNAL_INTEGRITY_REASONS`,
`JournalIntegrityError`, `force_reanchor` / reanchor audit,
`verify_anchor`); `trust/__init__.py`; call sites across `trust/` and
`core/`; test locations. I did not rely on the other cycle-31 work
products.

## Score

**0.35 / 1.00**

## Verdict

**FIX — do not ship as written.** The contract is a mostly accurate
description of library plumbing presented as the current production
recovery contract. Its own limits section disproves that framing, its
central test-pinning claim is demonstrably false for the cycle-23
material it most advertises, and it omits an entire audited escape
hatch (`force_reanchor`) that changes the trust story it tells.
Shipping it would freeze these overclaims into the document future
operators will trust instead of the code.

## The case against shipping

1. **There is no wired production recovery to contract over.** The
   contract concedes, mid-document, that "no non-test caller passes
   `tx_anchor_path` to `recover()`/`recover_ship_tx()`; the defaults
   silently reproduce pre-cycle-17 behaviour." That is not a footnote
   to a recovery contract — it negates the title and the opening line
   ("the contract of ship-transaction recovery as the code implements
   it today"). The default, actually-callable path gets *no* tx-anchor
   verification at all: no park, no `JournalIntegrityError`, no
   post-settlement re-verification. Every guarantee in the "Anchor
   verification" and "The two raises" sections is conditional on an
   argument no production caller supplies. A reader who stops at the
   headings — the normal use of a contract doc — will believe the
   system recovers this way. It does not.

2. **Cycle 23 is mislabelled "current / production," and the contract
   understates how partial that wiring is.** It calls
   `anchored_record_ship` (`trust/shipcheck.py:425`) the "Write half
   (cycle 23, current)" that "requires both anchors, verifies them AND
   requires currency … then advances the tx anchor after COMMITTED,"
   adding only "It has no non-test caller yet." Checked: outside tests
   the name occurs only at its definition and in `record_ship`'s
   docstring ("The production recording path is
   `anchored_record_ship`"); it is not even exported —
   `trust/__init__.py:69` exports only `check_ship, record_ship,
   recover_ship_tx`. Meanwhile the older `record_ship` remains fully
   callable with `anchor_path=None`, advances only the ship anchor,
   and never touches the tx anchor, so a direct `record_ship` ship
   silently leaves the tx anchor stale and makes the *next*
   `anchored_record_ship` refuse on currency. The "production path" is
   an opt-in wrapper nothing opts into, sitting beside an unwrapped
   path that breaks its invariant. The contract presents a two-layer
   split-brain advancement scheme as a completed wiring.

3. **The post-COMMITTED failure mode of cycle 23 is omitted.**
   `anchored_record_ship` advances the tx anchor *after*
   `record_ship` returns COMMITTED, and on `AnchorError` raises
   `ShipRefused` stating the cycle "recorded and decision …
   finalised, but the ship-tx anchor update failed"
   (`trust/shipcheck.py:497ff`). The caller therefore receives a
   refusal for a ship that committed, and — by the wrapper's own
   currency pre-check — every subsequent anchored ship refuses until
   an operator reconciles the stale tx anchor. The contract's
   advancement bullet mentions neither the committed-but-refused
   return, nor the self-inflicted lockout of the next ship, nor who
   is supposed to reconcile or how. For a recovery contract, omitting
   the new stuck state its newest wiring creates is a material gap,
   not a simplification.

4. **The test-pinning claim is false exactly where it matters.**
   The introduction promises: "Every claim is pinned by a test in
   `tests/test_trust_shiptx_anchoring.py` unless stated as a limit."
   That file contains **zero** references to `anchored_record_ship`.
   The whole cycle-23 paragraph — both-anchor requirement, currency
   (head/seq equality, stale-prefix refusal), advancement after
   COMMITTED — is pinned, if anywhere, by
   `tests/test_cycle23_ship_anchors.py`, a different file the contract
   never names. So the one section the contract flags as "corrected
   to the current tree" carries a provenance claim a single `grep`
   disproves. If the pinning claim fails for the newest material,
   the reader cannot trust it for the older material either, and the
   document's core selling point ("every claim is pinned") collapses
   into an unverified assertion.

5. **The contract omits `force_reanchor` entirely — the audited
   escape hatch that is the stated remedy for its own raises.**
   `trust/shiptx.py`'s recovery docstring names the remedy for a
   no-park-target raise as "the correct anchor or an audited
   force_reanchor." `trust/anchoring.py:667ff` implements
   `force_reanchor` with a hash-chained reanchor-audit file alongside
   the anchor (`reanchor_audit_path`, `verify_reanchor_audit`,
   entries carrying the recorded reason and both anchors). The word
   "reanchor" appears nowhere in the contract. Consequences:
   (a) the contract's limit "No in-anchor record of the ceremony
   exists" is at best half the story — there *is* an audit record
   for reanchors, just not in the anchor and not mentioned;
   (b) worse, recovery never checks it: `verify_anchor` defaults
   `check_reanchor_audit=False` (`trust/anchoring.py:704`), and
   neither `ShipTxJournal.recover` nor `recover_ship_tx` /
   `anchored_record_ship` passes `True` (zero occurrences in
   `trust/shiptx.py` or `trust/shipcheck.py`). A `force_reanchor`
   that blesses a rolled-back journal is therefore invisible to the
   very recovery flow this contract describes. Omitting both the
   hatch and its non-enforcement hides the largest operator-shaped
   hole in the anchor story.

6. **By its own limits, the headline guarantee is prefix-only and
   self-erasing — yet the framing never says so up front.** The
   contract admits: the anchor is unkeyed plain JSON; rewriting
   journal and anchor together passes; "because recovery does not
   advance, rollback to the anchored prefix erases its settlements
   undetectably"; restoring an older anchor is not detected; the two
   anchors in one directory are "one trust location, not two." In
   other words the mechanism detects only a narrow slice of rollback
   (journal moved, anchor left alone, anchor previously advanced by
   somebody else, caller remembered to pass both paths). That is a
   legitimate design trade-off — but a document titled a *contract*
   that leads with verification order, park classification and typed
   raises, and relegates "the settlements you just made can vanish
   undetectably" to a limits bullet, misstates the current security
   posture by emphasis even where each sentence is locally true.

7. **The silent-`[]` problem defeats the contract's own purpose and
   is carried as an "open design item" instead of a blocker.**
   Operator-error evidence, same-file evidence, and ship-only park
   evidence with no carrier all return `[]`, "indistinguishable from
   a clean run." Combined with point 1 (no caller passes the paths
   anyway) and the admitted non-idempotence of `recover()` (run 1
   parks, run 2 raises on identical evidence), an operator cannot
   distinguish "recovered clean," "evidence seen but surfaceless,"
   and "anchors never checked" from the return value. A contract
   that documents three indistinguishable outcomes for success and
   for integrity evidence is not yet a contract an operator can act
   on; shipping it normalises the ambiguity instead of resolving the
   "unbuilt design decision" first.

8. **Smaller inaccuracies confirm the document was not re-verified
   line-by-line against the tree it claims to pin.** `recover` is
   cited at `trust/shiptx.py:714`; the definition is at line 713.
   `recover_ship_tx` is cited at `trust/shipcheck.py:508`; the
   definition is at line 507 (508 is its wrapped signature line).
   Individually trivial — but in a document whose authority rests
   entirely on precise pins to code, off-by-one pins in the opening
   "Entry points" section are evidence the pinning pass was not
   actually run, reinforcing point 4.

## What would change this verdict

Retitle/reframe as a *library* contract for cycles 17+18 as
optionally invoked, with the unwired-recovery and unwired-write-path
facts in the introduction rather than the middle; correct the
test-pinning claim to name `test_cycle23_ship_anchors.py` for the
cycle-23 claims (or drop the single-file claim); add a
`force_reanchor` section stating that recovery does not verify the
reanchor audit (`check_reanchor_audit` never passed); document the
post-COMMITTED `ShipRefused` + next-ship currency lockout from
cycle 23; and fix the two line pins. Until then: **do not ship.**
