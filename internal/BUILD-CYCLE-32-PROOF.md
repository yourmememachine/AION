# BUILD CYCLE 32 (proof) — proof-carrying self-improvement, prototype

**Summary:** Dilip picked direction #1 from the world-first
shortlist — proof-carrying self-improvement. This cycle builds
the prototype: a change may pass the composed ship path only
when it carries a machine-checkable artefact whose declared
invariants an independent checker re-verifies from scratch
against the exact bound tree contents. New module
`trust/proofcarry.py`; composition seam
`record_ship_with_proof` verifies first (ShipRefused before
any burn) and delegates to the existing signed `record_ship`.
No protected file touched: `eval/` untouched, `core/loop.py`
untouched, `trust/shipcheck.py` untouched. Real
state/state.json not advanced.

NUMBERING COLLISION (disclosed): a concurrent scheduled-build
cycle also used the number 32 for the ship-tx post-settlement
fix (its record is internal/BUILD-CYCLE-32.md; its brief is
internal/CROSS-CHECK-BRIEF-CYCLE-32.md). This cycle's records
carry the -PROOF suffix to stay disjoint. Renumbering one
cycle is a coordinator follow-up.

## Claim (verbatim, pinned by tests/test_cycle32_claim_pin.py)
"A proof artefact establishes only this: the invariants it
declares were executed by the independent checker against the
exact tree contents bound in the artefact, each declared check
passed on that tree, and each check was shown to fail on the
pre-change tree (for invariants declared new) and on a mutated
tree. It establishes nothing about properties the change did
not declare, and it is not a proof of general correctness."
Terminology, in the module, the design, and inside every
artefact (required hash-bound field
`"mechanism": "check-carrying/1"`): this is check-carrying —
author-declared executable checks re-verified by re-execution
— not proof-carrying in the formal-methods (Necula) sense.

## What was built
- `trust/proofcarry.py` — artefact builder, independent
  checker (`verify_proof_artefact`, staged: schema and
  self-hash return alone; binding steps accumulate and return
  before ANY argv executes; probes run only in scratch copies
  with uniform basename), scope-bounded tree hashing
  (`proof-tree/1`), re-derived changed-files verification,
  pre-validated mutations (no-op / harness-targeting ->
  `mutation_invalid`), discrimination requiring an OBSERVED
  non-zero exit, and the `record_ship_with_proof` seam with a
  post-verification re-hash.
- Tests (26 new): `tests/test_trust_proofcarry.py` (19 —
  happy path, tamper, stale replay, vacuous, non-discriminating,
  missing evidence, malformed-alone, sentinel-argv-never-run,
  changed-files trimming, no-op mutation, probe-cannot-run,
  NUL argv, mechanism field, root guard, refuses-before-
  delegating), `tests/test_cycle32_proof_ship.py` (2 —
  end-to-end signed ship; tamper refuses before burn),
  `tests/test_cycle32_claim_pin.py` (5 — CLAIM verbatim,
  9 banned over-claim phrases over module + design doc).
- Demo: `tests/cycle32_demo.py` (temp-tree accept/refuse/
  vacuous, output in internal/cycle32-work/demo-output.txt)
  and a REAL-change artefact for this cycle's own diff
  (base = git archive of 8e8234f, post = working repo;
  generator `tests/cycle32_real_change_demo.py`; artefact
  internal/cycle32-work/demo-artefact.json). Its second
  invariant executes the actual cycle-32 test suites via the
  output-normalising `tests/cycle32_suite_check.py`.
  Verify: ACCEPTED (); tampered copy REFUSED
  (post_tree_mismatch). See demo-real-change.txt.

## War room
3 coder seats (design / core / integration+demo), 6 reviewer
seats blind (R6 forced dissent), fix round F1–F17, 3 re-review
seats. First round was FIX from five seats (execution-before-
binding, live-tree probes, changed_files unverified,
harness-presence gaming, demo defects, claim overreach on
"shown to fail"); R4 SHIP. Re-review: RR1 SHIP, RR2 SHIP,
RR3 (dissent seat) conditions 1–4 MET and (5) flipped by its
own stated minimal step — the hash-bound mechanism field,
landed by the coordinator with a regression test. Final:
reconciled unanimous SHIP, internal, PROVISIONAL pending the
external seats (brief
internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF.md; 2 external
rounds per the 2026-11-26 rule). Full record:
internal/REVIEW-CYCLE-32-PROOF.md. Design:
internal/cycle32-work/design-final.md.

## Tests
Full suite on the final tree: **1850 tests discovered, OK
(skipped=28)**. Attribution: baseline 1814 + 26 new this cycle
+ 10 from the concurrent ship-tx cycle whose files share the
tree. This cycle's targeted suites: 40 tests OK (proofcarry
19, proof-ship 2, claim-pin 5, trust-lint 14). An earlier
full-suite run during the build showed 10 failures — traced
to the concurrent cycle's failing-first tests mid-flight, not
this cycle; the final run is clean.

## Staffing
15 coders in 5 pods of 3 (design, core module, integration/
demo, fix round, verification) — three seats ran as delegated
agents plus coordinator seats; war room 6 internal reviewer
seats + 3 re-review seats, all from outside the building
slices; external seats pending (parent runs them).

## Self-improvement delta
The war room's adversarial seats reproduced three
design-vs-code divergences the builders believed were
implemented (execution ordering, scratch isolation,
changed-files verification) — the cycle's lesson, again:
a design statement is not evidence; only a failing-first
test is. The dissent seat also forced the mechanism's name
to travel inside the artefact itself. Scorecard:
Self-improvement leg gains its first executable gate
prototype (declared invariants, re-verified, discrimination
proven); no % change claimed until the external rounds land.

## Open follow-ups
- Bind the ship manifest_hash (base + post) into the
  artefact (design follow-up 1) and sign the artefact under
  the existing signing discipline (follow-up 2).
- Builder default-mutation fallback retained vs design §5's
  refusal letter (recorded deviation).
- "preserved"-scope discrimination semantics (follow-up 6).
- Cycle-numbering collision with the concurrent ship-tx
  cycle 32 — renumber one cycle's records.
- External rounds 1–2 on the -PROOF brief.
