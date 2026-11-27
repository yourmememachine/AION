# Blind review brief — cycle 32-PROOF, external ROUND 2

You are an external reviewer seat in a war room. Review blind: no
internal verdicts are shown. Round 1 (you and the other external
seat both returned FIX) demanded the fixes below. This round asks:
are they actually landed, and does the cycle now SHIP or FIX?

## What the system is
`trust/proofcarry.py` — a "check-carrying" gate for
self-modification: a change may pass the composed ship path
(`record_ship_with_proof`) only when it carries a machine-checkable
artefact whose declared invariants an independent checker
re-executes from scratch against the exact bound tree contents,
with discrimination proven (each new check must be observed to
fail on the pre-change tree and on a mutated tree). The artefact
carries the required hash-bound field
`"mechanism": "check-carrying/1"` — this is check re-execution
with hashing, explicitly NOT formal proof-carrying code.

## Round-1 demands and what the fix round claims to have landed
- F1/G-claim: CLAIM tightened — it now states tree-content binding
  is not hermetic execution; the execution environment, ambient
  filesystem state and inherited environment are NOT bound by the
  artefact. Claim text is pinned verbatim by
  tests/test_cycle32_claim_pin.py with 9 banned over-claim phrases
  scanned over module + design.
- F2 verify-to-ship atomicity: snapshot composition — the checker
  verifies a snapshot of the post tree and the ship path ships
  that snapshot; record_ship_with_proof re-hashes after
  verification and refuses on mismatch before any ledger burn.
- F3 containment: threat model narrowed in the claim/design
  (no sandbox claimed) + symlink escapes refused by the tree
  hasher and scratch runner.
- F4 ship-path coverage: new tests/test_cycle32_ship_coverage.py
  asserts no self-modification route reaches the signed
  record_ship bypassing the proof wrapper.
- G1 unscoped-edit hole: the checker re-derives the whole
  base..post diff; any changed file outside scope_paths refuses
  with `unscoped_changes`. PARTIAL on the binding half —
  disclosed, not hidden: the artefact hash is NOT in the signed
  record or manifest. The durable carrier is an fsync'd
  append-only sidecar (proof-bindings.jsonl, seven keys incl.
  artefact_hash + manifest_hash) appended AFTER the burn, and
  a pinned test records that if that append fails the ship
  STANDS unbound. Internal review (round 2) scored this the
  cycle's top open item; treat "G1 fully landed" as NOT claimed.
- G2 scratch isolation: one scratch runner for checker and
  builder; fresh copy per check/probe; the scratch tree is
  re-hashed after each pass run and a mutation by the check
  itself refuses with `check_side_effect:<id>`.
- G3 mutation rules: mutations targeting harness files or their
  local-import closure refuse `mutation_invalid`; step-8 crash
  signatures distinguish a harness crash (ImportError /
  ModuleNotFoundError / syntax) from a semantic check failure —
  a crash does NOT count as discrimination.
- G4 tree hasher: symlink refusal, scope_paths normalization and
  dedup, mode decision recorded in design §12.5.

## Evidence offered
- Full suite on the fix-round tree: 1,887 tests, OK (28 skipped).
  Fix-round targeted suites: test_trust_proofcarry (expanded),
  test_cycle32_proof_ship, test_cycle32_ship_coverage (new),
  test_cycle32_claim_pin.
- Demo (internal/cycle32-work/demo-fixround.txt): a fix-round
  artefact for the fix round's own change to trust/proofcarry.py
  verifies ACCEPTED on the untouched post tree and REFUSED
  (post_tree_mismatch) on a tampered copy. Disclosed honestly:
  the ROUND-1 artefact now REFUSES under the new checker
  (mutation_invalid) because its mutation deleted a suite module
  its harness loads dynamically — the new crash-signature rule
  working as designed against a pre-fix artefact; the round-1
  artefact was not regenerated.
- No protected file touched: eval/, core/loop.py,
  trust/shipcheck.py unchanged. Real state/state.json not
  advanced.

## Fix round 2 (internal war room on the fix round, this cycle)
Internal seats on the fix round: R1 FIX 0.82, R2 FIX 0.78,
R3 SHIP 0.95, R4 FIX 0.82, R5 SHIP 0.82, R6 dissent FIX 0.35.
Four probe-confirmed holes were found and fixed with
failing-first tests (tests/test_cycle32_proof_fix2.py, 9 tests;
6 failed before the fix, all pass after; targeted suites
72 tests OK):
1. Harness closure missed `from package import submodule` —
   the submodule file now enters the closure.
2. The unscoped check ran only on the live trees — it is now
   re-run against the snapshot (W4b) before delegation.
3. The whole-tree walk skipped any *.pyc anywhere — only
   __pycache__ members are now skipped; empty-directory and
   mode-only invisibility are stated limits in the docstring.
4. Crash signatures missed NameError/AttributeError — added
   under the same documented conservative tradeoff.
Still open and NOT claimed closed: the binding anchoring
above (R4/R6: fail-closed binding + a non-author anchor are
the dissent seat's stated flip conditions), write-and-restore
side-effect evasion inside a check's own run, and author-chosen
checks/mutations (carried as disclosed limits under the
narrowed claim). Also disclosed: the round-1 flagship artefact
no longer verifies under the current checker and must not be
cited as valid evidence.

## Questions for your seat
1. Does the snapshot composition actually close the
   verify-to-ship race, or is a window left? 
2. Is the narrowed threat model (F3) honest and sufficient for a
   prototype, or is containment still owed?
3. Does the whole-tree diff + `unscoped_changes` refusal fully
   close the unscoped-edit hole, including files the artefact
   scope never mentions?
4. Is the crash-vs-semantic distinction in G3 sound, or can a
   mutation still "discriminate" by crashing the harness in a
   way the signatures miss?
5. Verdict: SHIP or FIX, with a score 0–1 and any mandatory
   conditions. A FIX must name the smallest concrete failure.
