# BUILD — Cycle 17: ship-tx journal anchoring

Item: backlog `ship-tx-journal-anchoring` (seq 29, leverage
5.0) — "Anchor the ship transaction journal head externally
like the signing and ship ledgers." Chosen because cycles
14+15+16 are held on the pin ceremony's circular authority,
which needs Dilip's decision on extending the Protected
Gate's scope; this item is the highest-leverage closable
integrity work that needs no protected path and no owner
decision. No protected paths touched (eval/, core/,
oversight/ unchanged). Baseline: 1187 tests OK (skipped=26),
verified at run start on the cycle-16 tree (commit 21f609b).

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15). Three design pods
reported before code:
- Pod C (9, 10, 11) implementation: one-line ANCHOR_KINDS
  change; recover() wiring with park-over-error combination;
  shipcheck pass-through; flagged the deleted-journal blind
  spot (park reasons with no transactions to land on).
- Pod D (3, 4, 15) adversarial: placement under the shared
  journal directory; unkeyed-anchor limits; verify-then-
  proceed with caller-side advancement; the cross-wired
  anchor risk as the sharpest new failure mode.
- Pod B (2, 6, 7) caller contract: full test plan; confirmed
  no existing test pins ANCHOR_KINDS, so the kind addition
  is additive.
Pods A (1, 5, 8) and E (12, 13, 14): module shape unchanged;
no production caller exists yet — recorded honestly below.

War room: 5 live blind reviewer seats (rev-r1 0.70 FIX,
rev-r2 0.58 FIX, rev-r3 forced dissent 0.35 FIX, rev-r5 0.72
FIX test-only, rev-r6 0.92 SHIP) + a fix round + a
re-verification seat (0.97 SHIP). See REVIEW-CYCLE-17.md.
External seats seat-gpt / seat-gemini: VACANT this detached
run (brief at internal/CROSS-CHECK-BRIEF-CYCLE-17.md), so
the verdict is PROVISIONAL. Cycles 14+15+16 remain held on
the separate Protected Gate decision; this cycle neither
clears nor touches that gate.

## What was built

1. `trust/anchoring.py`: ANCHOR_KINDS gains "ship-tx"; the
   anchor format docstring names the new kind and its
   shared-directory placement rule. All anchor operations
   are generic over HashChainJournal, so initialise /
   update / force_reanchor / verify work on ShipTxJournal
   unmodified.
2. `trust/shiptx.py`: `ShipTxJournal.recover()` gains
   keyword `tx_anchor_path=None` (default = prior behaviour
   exactly). Both anchors are verified BEFORE any settlement
   and combined park-over-error; error reasons are labelled
   by anchor only when the tx anchor participates (ship-only
   callers keep their bare pre-cycle-17 strings). Park
   outcomes carry `anchor_sources`. Recovery never advances
   either anchor. `recover_ship_tx` forwards the keyword.
3. Fix round (war room, all reproduced before fixing):
   - Same-file diagnosis by file identity (os.path.samefile,
     resolved-path fallback) suppressing BOTH verifications —
     sharing either anchor file, or a symlink/hardlink alias
     of it, is a non-destructive operator error, never a
     park. A different wrong-kind file still parks.
   - The no-park-target raise widened from "no transactions
     at all" to "no non-terminal transaction": a journal
     rolled back to a terminal-only prefix with a mismatched
     tx anchor raises AnchorError instead of returning [].
     The ship anchor deliberately has no equivalent raise
     (its ledger is a different file; no transaction is at
     risk from it) — principle stated in the code comment.
   - Post-settlement re-verification: a park reason that
     appears only after the loop (journal swapped
     mid-recovery) raises AnchorError; settlements already
     journaled stand. Identical repeat exceptions are not
     treated as changes.
4. Honest scope, stated in the docstrings: the pin is
   unkeyed (rewriting journal + anchor together defeats it);
   two anchors in one external directory are one trust
   location; initial anchoring of an established tx journal
   needs the nonempty ceremony and cannot detect earlier
   rollback; NO in-tree caller passes tx_anchor_path yet —
   this is operator/library plumbing. Follow-on item:
   wire the ship flow (record_ship advancing the tx anchor
   after COMMITTED, and an operator recovery path that
   passes tx_anchor_path) as its own cycle.

## Tests

- tests/test_trust_shiptx_anchoring.py: 41 tests (30 initial
  + 11 fix-round).
- Targeted suites: 231 tests OK (skipped=1).
- Full suite, final tree: **1228 tests, OK (skipped=26)**
  (baseline 1187 → +41).

## Recording status

Loop state NOT advanced (signed ship path, as cycles
14–16); the backlog item therefore still reads `pending`
in loop state while built, reviewed and green in the tree.
Committed locally only; no push from this run.

## Self-improvement delta

tests_passing 1187 → 1228 (coordinator full-suite run on
the final tree; verifier: the war room's non-builder seats,
incl. an independent re-verification seat that reproduced
the hardlink-alias and mid-recovery-swap cases itself).
Process lessons: (1) a guard that diagnoses a caller mistake
must suppress the mistake's consequences on EVERY check it
feeds, not just the nearest one — the asymmetric same-path
guard manufactured the exact park it existed to prevent;
(2) path equality is not file identity — use samefile /
resolved paths wherever the codebase already does;
(3) "evidence with nowhere to land" is a surface-design
question for every terminal-only state, not only the empty
one.
