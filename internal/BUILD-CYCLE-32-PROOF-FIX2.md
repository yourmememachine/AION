# BUILD CYCLE 32-PROOF — FIX ROUND 2

**What this cycle did:** war-roomed the external round-1 fix
round (commit 8765d51) with six blind internal seats, then
landed the reconciled cheap-and-probe-confirmed fix list
(R1/R2 items 1–4) failing-first. Full record:
internal/REVIEW-CYCLE-32-PROOF-FIX2.md.

## Fixes landed (trust/proofcarry.py)
1. Harness closure: `from package import submodule` now adds
   the submodule file (package/submodule.py) to the closure
   candidates; plain attribute names seed nothing.
2. Snapshot unscoped re-check (W4b): record_ship_with_proof
   re-runs _unscoped_changes against the snapshot inside the
   context, before delegating — closing the W2→copy race for
   paths the manifest does not bind (docs/, deploy/, top
   level).
3. Whole-tree walk: a .pyc outside __pycache__ is tree
   content and is listed; only __pycache__ members are
   skipped. Empty-directory and mode-only invisibility now
   stated in the _expand_whole_tree docstring.
4. Crash signatures: NameError and AttributeError added to
   _HARNESS_CRASH_MARKERS under the same documented
   conservative tradeoff (a semantic failure naming one is
   refused as mutation_invalid).

## Tests
- New: tests/test_cycle32_proof_fix2.py — 9 tests. Before the
  fix: 6 FAILED (from-import closure, root .pyc ×2, crash
  markers ×2, snapshot re-check); 3 companion pins passed
  both ways (plain-name not invented, __pycache__ still
  ignored, plain AssertionError not a crash).
- After the fix: targeted suites 72 tests OK
  (test_cycle32_proof_fix2 9, test_trust_proofcarry 45,
  test_cycle32_proof_ship 11, test_cycle32_ship_coverage 2,
  test_cycle32_claim_pin 5).
- Full suite on the final tree: **1,896 tests, OK
  (skipped=28)** — the 1,887 of commit 8765d51 plus the 9 new
  tests.

## Staffing
15 coders in 5 pods of 3 (scan/design, closure fix, snapshot
fix, walk+markers fix, tests/verification) — run as
coordinator seats plus delegated agents; war room 6 internal
reviewer seats from outside the building slices (3 delegated
reviewer agents, 2 seats each, blind); external seats:
ChatGPT, Gemini, Claude round 2 requested on the corrected
brief internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF-R2.md.

## Self-improvement delta
The internal war room caught four real holes in a fix round
that all 1,887 tests had passed — two of them in the exact
mechanisms the fix round claimed to close (G1 diff derivation,
G3 harness closure). Lesson recorded: a closure claim is only
as good as its least-common spelling — import-form coverage
must enumerate spellings (import a.b, from a import b,
from a.b import c, relative forms), and every "re-check"
claim must name WHICH tree (live vs snapshot) it runs on.
Scorecard: self-improvement leg unchanged in % (verdict still
PROVISIONAL); integrity spine strengthened — G1/G3 closures
now honest at the spelling level.

## Open follow-ups
- BLOCKING: binding anchoring (R4 item / R6 flip condition) —
  artefact_hash into the signed record/manifest, or
  fail-closed binding + non-author anchor. Next cycle.
- Write-and-restore side-effect evasion inside a check run
  (disclosed limit).
- Round-1 artefact is void under the current checker; never
  cite it as evidence.
- External round 2 (3 seats) to reconcile before any ship.
