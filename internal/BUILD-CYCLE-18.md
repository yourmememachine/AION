# BUILD — Cycle 18: journal-integrity error type

Item: the reconciliation route recorded in CROSS-CHECK-11
(cycle 17's external split) — "a dedicated journal-level
outcome surface … or a DISTINCT typed error that cannot be
conflated with anchor-load errors and names the anchor +
reasons", plus hard-link coverage for the same-file guard.
Chosen as the highest-leverage closable integrity work that
needs no protected path and no owner decision; cycles
14+15+16 remain held on the pin ceremony's circular
authority (Dilip's Protected Gate decision), untouched here.
No protected paths touched (eval/, core/, oversight/
unchanged). Baseline: 1228 tests OK (skipped=26) at commit
c599305.

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15). Three design pods
reported before code:
- Pod C (9, 10, 11) implementation: the subclass API, bare
  reasons + labelled sources, post-settlement split.
- Pod D (3, 4, 15) adversarial: exact-type pinning, source
  correspondence, the silent-[] holes, hardlink as the
  discriminating same-file case.
- Pod B (2, 6, 7) caller contract: the only production caller
  is recover_ship_tx (propagates unwrapped); the two message
  substrings existing tests check must survive verbatim.
Pods A (1, 5, 8) and E (12, 13, 14): module shape unchanged;
no production caller behaviour changes (subclassing).

War room: 6 live blind reviewer seats (rev-r1 0.88 SHIP,
rev-r2 0.74 FIX, rev-r3 forced dissent 0.58 FIX, rev-r4 0.82
FIX, rev-r5 0.84 FIX, rev-r6 0.92 SHIP) + a fix round + a
re-verification seat (0.93 SHIP). See REVIEW-CYCLE-18.md.
External seats seat-gpt / seat-gemini: VACANT this detached
run (brief at internal/CROSS-CHECK-BRIEF-CYCLE-18.md), so
the verdict is PROVISIONAL and cycles 17+18 both go back to
the external seats together.

## What was built

1. `trust/anchoring.py`: `JournalIntegrityError(AnchorError)`
   — raised only for journal-level integrity failures.
   Constructor-validated structured attributes: `reasons`
   (canonical chain-mismatch set only — an operator reason
   such as anchor_malformed is refused with ValueError),
   `anchor_sources` (labelled, deduped, suffixes must match
   the reasons exactly), derived `anchor_source` ("combined"
   when more than one), `anchor_errors`, `outcomes`.
   Handler-order rule stated in the docstring (catch the
   subclass before AnchorError). `__reduce__` makes pickle /
   deepcopy round-trip. Exported from `trust/__init__.py`
   including `__all__`.
2. `trust/shiptx.py` recover(): the pre-settlement
   no-park-target raise and the post-settlement
   re-verification raise now use the distinct type. Fix
   round: ship-anchor park reasons present in the same call
   ride on the pre-settlement raise (labelled) instead of
   vanishing; the post-settlement split carries new
   anchor-load failures in `.anchor_errors` (never in
   `.reasons`), and the error-only branch's plain AnchorError
   now also carries `.outcomes`, so settlements are not
   discarded on either branch.
3. Tests: hardlink aliases of the same-file guard in both
   directions (the cycle-17 guard used samefile but had no
   hardlink pin), and a byte-identical copy (distinct inode)
   still parks — file identity, not content, is the guard.
   No path-replacement/TOCTOU claim is made this cycle.

## Honest scope

recover() still returns a list and still raises for the
journal-level case; the state-dependence (park on run 1,
raise on run 2) and the ship/tx asymmetry are preserved,
now typed and labelled. rev-r3's dissent — that this is
labelling, not reconciliation — is preserved in the review
record; the external seats judge it on re-review. Follow-on
items named, not built: (a) Pod D's silent-[] holes —
operator-error / same-file evidence with no transaction to
carry it returns [] (a chosen non-[] surface is a design
decision for its own cycle); (b) cycle 17's ship-flow
wiring (record_ship advancing the tx anchor).

## Tests

- tests/test_trust_shiptx_anchoring.py: 58 tests (41 + 17).
- Targeted suites: 176 tests OK.
- Full suite, final tree: **1245 tests, OK (skipped=26)**
  (baseline 1228 → +17), run by the coordinator (1240
  pre-fix-round) and independently by the re-verification
  seat on the final tree (1245).

## Recording status

Loop state NOT advanced (signed ship path, as cycles
14–17); the reconciliation therefore lives in the tree and
these records, not in loop state. Committed locally only;
no push from this run.

## Self-improvement delta

tests_passing 1228 → 1245 (final-tree full-suite runs;
verifier: the war room's non-builder seats, incl. a
re-verification seat that re-probed the constructor holes
itself). Process lessons: (1) a distinct type whose
constructor accepts anything is a label, not a contract —
validate the invariant at construction; (2) when a raise
discards a return value, every branch of that raise must
carry the completed work, not only the branch being
retyped; (3) evidence supplied to a call must not vanish
from that call's failure surface just because a different
piece of evidence triggered the failure.
