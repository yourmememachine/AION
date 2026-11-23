# Blind review brief — Cycle 18: journal-integrity error type

For external seats seat-gpt / seat-gemini. No internal verdicts
or scores are included in this brief. This cycle implements the
reconciliation route recorded after the cycle-17 split, where
one seat held that raising AnchorError for a deleted ship-tx
journal is correct (journal-level integrity failure) and the
other held that raising a generic AnchorError conflates it with
anchor-load errors and makes the contract state-dependent.
Both seats are asked to re-review this delta.

## What was built (trust/anchoring.py, trust/shiptx.py,
trust/shipcheck.py docstring, trust/__init__.py)

1. `JournalIntegrityError(AnchorError)` in trust/anchoring.py.
   Raised ONLY for journal-level integrity failures; anchor-load
   and operator errors stay plain AnchorError / per-transaction
   error outcomes. Because it subclasses AnchorError, every
   existing `except AnchorError` caller still catches it; the
   docstring states callers wanting the distinction must catch
   the subclass BEFORE AnchorError.
2. Structured attributes, validated in the constructor:
   `reasons` (bare canonical chain-mismatch reasons only —
   anchor_head_not_in_chain, anchor_ahead_of_journal,
   anchor_kind_mismatch; any other reason, including operator
   reasons like anchor_malformed, is refused with ValueError),
   `anchor_sources` (labelled "ship: …" / "ship-tx: …" entries
   whose suffixes must match the reasons exactly, deduped),
   derived `anchor_source` (single source or "combined"),
   `anchor_errors` (labelled NEW anchor-load failures that
   accompanied integrity evidence; never in `reasons`), and
   `outcomes`. Empty reasons or empty sources are refused.
   Pickle/deepcopy round-trip via `__reduce__`.
3. Pre-settlement raise in ShipTxJournal.recover(): when the
   tx anchor carries chain-mismatch reasons and no non-terminal
   transaction exists to park, it now raises
   JournalIntegrityError. If the ship anchor also carries park
   reasons in the same call, they ride on the raise (labelled,
   message notes them); the raise still fires on the tx reasons
   alone — the ship anchor keeps its deliberate asymmetry (it
   pins a different file; its park reasons with nothing to park
   do not raise, pinned by test).
4. Post-settlement re-verification raise: restructured into
   (labelled entry, bare reason-or-None) pairs. A new park
   reason raises JournalIntegrityError carrying the completed
   outcomes; a NEW anchor-load failure alone raises plain
   AnchorError, now also carrying the completed outcomes as an
   attribute so settlements are not discarded on either branch.
5. Same-file guard (cycle 17, os.path.samefile): hardlink
   aliases are now pinned by tests in both directions, plus a
   byte-identical COPY (distinct inode) still parks on kind
   mismatch — file identity, not content, is the guard. No
   claim is made about the check/use race (TOCTOU): it is not
   addressed this cycle.

## What was NOT changed

- recover() still returns a list of per-transaction outcomes
  and still raises for the journal-level case: the outcome
  model is not uniform. The state-dependence (park on run 1,
  raise on run 2) and the ship/tx asymmetry are preserved,
  now typed and labelled — one internal dissent seat holds
  this is labelling, not reconciliation, and that dissent is
  preserved in the review record for your judgement.
- No protected paths touched (eval/, core/, oversight/).
- Message strings at the original raise sites are unchanged;
  the pre-settlement message gains a ship clause only when
  ship park reasons are also present.

## Test evidence

- tests/test_trust_shiptx_anchoring.py: 58 tests (41 cycle-17
  + 12 initial cycle-18 + 5 fix-round) — exact-type assertions,
  structured attributes, constructor validation, pickle,
  wrapper propagation, ship-only no-raise asymmetry, hardlink
  both directions, byte-copy parks, post-settlement pure-park /
  pure-error / mixed / combined / no-new-reason cases.
- Full suite results are in the cycle's build record.

## Questions for the seats

1. Does the distinct typed subclass genuinely reconcile the
   cycle-17 split, or is the preserved raise-vs-return
   non-uniformity still a FIX?
2. Is the constructor validation (canonical reasons only,
   sources must match reasons) the right boundary, or does it
   over-constrain a legitimate future journal-integrity use?
3. Does anything over-claim what this cycle proves?
