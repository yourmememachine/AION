# REVIEW — Cycle 32 (ship-tx post-settlement) war room

NOTE on numbering: a concurrent session is also running a
"cycle 32" (proof-carrying self-improvement; its record is
internal/REVIEW-CYCLE-32.md). This record covers ONLY the
ship-tx post-settlement returned-failure cycle. Files are
disjoint; renumbering is a coordinator follow-up.

Six internal seats, blind, scores before discussion; R3 forced
dissent. External: internal/CROSS-CHECK-32-SHIPTX.md (2 rounds).

First round:
- R1 correctness SHIP 0.92; R2 error surface SHIP 9/10;
  R5 tests SHIP 9/10 (independently re-ran failing-first in a
  scratch copy: 9 red / 1 guard green on old code).
- R4 safety/limits FIX 8/10 and R6 completeness FIX 0.82 —
  docs-only, same two defects: pin count still 58 (now 68),
  "The two raises" item-2 lead exception-path-only. Both fixed;
  R6's further points (explicit "new" qualifier, unknown-string
  and within-run dedup documented) also applied.
- R3 forced dissent FIX 4/10: raise-after-settlement asymmetry,
  spelling-based dedup, flapping invisibility, same-file
  diagnosis not recomputed at re-verification, docs
  overclaiming. Reconciled: the first three are pre-existing
  cycle-17/18 behaviour for the park and exception channels —
  this cycle extends parity to the returned channel and does
  not introduce them; the unknown-string-by-negation classifier
  matches the pre-settlement classifier in the same method.
  Taken from R3: contract wording softened ("on the same terms
  as", not "exactly like") and same-file re-check at
  re-verification added to open follow-ups. Dissent preserved
  here and in internal/cycle32-work/review-r3.md.

External round 1: seat-gpt SHIP 0.96, seat-gemini SHIP 0.88 —
see CROSS-CHECK-32-SHIPTX.md for reconciliation of their asks
(consumer check, full-suite re-run, cross-anchor and mixed
.outcomes coverage, empty-string return path).

External round 2 (2-round rule, 2026-11-26): seat-gpt SHIP
0.99, seat-gemini SHIP 0.97, no mandatory fixes from either.

Final verdict: SHIP — war room reconciled, both external seats
SHIP in both rounds. Code and tests verified: pin file 68 OK;
full discovery suite 1848 OK (skipped=28) on confirming runs,
one earlier unidentified flaky failure recorded. Local commit
only, after the concurrent session's own commit landed and
file disjointness was verified (see BUILD-CYCLE-32.md).
