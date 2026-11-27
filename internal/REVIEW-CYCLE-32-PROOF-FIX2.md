# REVIEW — Cycle 32-PROOF, fix round 1 war room + fix round 2

Scope: the external round-1 fix round (commit 8765d51) for the
check-carrying prototype (trust/proofcarry.py). Six internal
seats, blind, run as three delegated reviewer agents (two seats
each) plus coordinator reconciliation. Scores locked in the
seat reports before reconciliation.

## Seats
- R1 correctness — FIX 0.82. F2 PARTIAL (snapshot never
  re-checked for unscoped changes), G1 PARTIAL, G3 PARTIAL
  (from-import closure miss, probe-confirmed), G4 MET,
  F3 MET by narrowing.
- R2 adversarial — FIX 0.78. Two executed bypasses:
  from-import mutation escape; root-level .pyc invisible to
  the whole-tree diff. Plus the W2→snapshot race on
  non-manifest paths and write-and-restore side-effect
  evasion (the last carried as a disclosed limit).
- R3 claim — SHIP 0.95. F1 MET: the pinned CLAIM now states
  tree-contents-only binding; environment, interpreter and
  out-of-tree access expressly not bound; six banned phrases
  added to the pin. No affirmative over-claim found.
- R4 integration — FIX 0.82. Protected files untouched
  (eval/, core/loop.py, trust/shipcheck.py); seam refuses
  before burn. Single item: artefact-hash binding is an
  unsigned sidecar (proof-bindings.jsonl) appended after the
  burn; ship stands if the append fails — G1's second half
  PARTIAL (the design's own open follow-up 5).
- R5 tests/evidence — SHIP 0.82. 63 targeted tests pass;
  failing-first empirically demonstrated against a7e522b
  (ship file 7/11 fail, claim pin 2/5 fail). Demo disclosure
  honest — with the consequence recorded: the round-1
  flagship artefact is retroactively VOID under the current
  checker and must not be cited as valid evidence.
- R6 forced dissent — FIX 0.35. Author-chosen checks and
  mutation; unkeyed hashes; binding failure tolerated;
  environment disclosed not bound; crash rule is a word list.
  Flip condition: fail-closed binding AND a non-author
  anchor/countersign for the artefact hash.

## Reconciled verdict
FIX — split decision (3 FIX / 2 SHIP / 1 dissent FIX); nothing
ships on a split. Fix list split in two:
- Fix round 2 (this cycle, landed): R1/R2 items 1–4 — see
  internal/BUILD-CYCLE-32-PROOF-FIX2.md. Targeted suites
  72 tests OK after the fix; 6 of the 9 new tests failed
  before it.
- Blocking follow-up (next cycle): the binding anchoring —
  anchor artefact_hash into the signed ship record/manifest
  or make the binding fail-closed with a non-author anchor
  (R4's single item = R6's flip condition). Until it lands,
  G1 is recorded PARTIAL everywhere, including the external
  round-2 brief.

## External seats
Round 2 brief: internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF-R2.md
(corrected to disclose the binding as PARTIAL before sending).
Verdict stays PROVISIONAL until ChatGPT, Gemini and Claude
round-2 reviews are reconciled.
