# External seats — cycle 32-PROOF (proof-carrying prototype), ROUND 1
Per Dilip's 2026-11-26 rule: minimum 2 external rounds.

## seat-gpt — FIX 0.87 (2026-11-26 ~08:32 CST)
Architecture endorsed; seam (Q3) correct. Mandatory fixes:
- F1: clarify execution-binding guarantee in the claim (tree-content binding != hermetic execution; env/filesystem access not controlled).
- F2: verify-to-ship atomicity (tree must not change between final re-hash and ledger burn; lock/snapshot or equivalent).
- F3: filesystem/process containment (symlink escape, executable resolution, env inheritance, process spawning) — enforced boundary or narrowed threat model + tests.
- F4: ship-path coverage (prove no self-modification route reaches signed record_ship bypassing the wrapper).
Round-2 SHIP conditions: race closed; boundaries enforced or threat model narrowed; all ship routes gated; claim tightened to actual execution guarantees. Explicitly does NOT demand formal proofs or a full sandbox for a prototype.

## seat-gemini — PENDING (round 1 blocked on Google 2-step phone approval in the fresh browser environment; Dilip asked to tap Yes + 52)

## seat-gemini — FIX 0.86 (2026-11-26 ~08:32 CST)
Architecture endorsed. Four required items, converging with seat-gpt:
- G1: close the unscoped-edit hole — refuse (unscoped_changes) when the actual base..post diff touches files outside scope_paths; bind the verified artefact hash into the record_ship manifest/metadata so the signed record cannot decouple from the verified artefact.
- G2: isolate scratch execution per check/probe (fresh or reset copies); verify scratch tree hash unchanged after the pass run (check_side_effect refusal).
- G3: tighten mutation_invalid — reject mutations hitting harness dependencies/transitive imports; distinguish import/syntax crashes from semantic check failure.
- G4: proof-tree/1 hardening — symlink refusal (or hash targets without dereferencing), scope_paths normalization/dedup, demo artefact reproduced from a fresh clone.
Also: environment/ambient-state non-binding (claim scope), TOCTOU on out-of-scope files, mutation semantics (one author-chosen mutation != sensitivity proof).

## RECONCILIATION (round 1)
Both seats FIX, convergent. Fix round scope = GPT F1-F4 + Gemini G1-G4 (heavy overlap): unscoped-change refusal + artefact-hash binding into the ship record; verify-to-ship atomicity/locking; per-check scratch isolation + side-effect refusal; mutation-target rules (non-harness, in-scope, crash-vs-assertion distinction); tree-hasher symlink/normalization hardening; claim tightened on execution-environment scope. Then ROUND 2 to both seats (Dilip's 2-round rule).

## ROUND 2 (2026-11-26, after fix rounds 1-2)
Brief: internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF-R2.md
(corrected before sending to disclose the binding as PARTIAL).
All three seats reachable and signed in.

- seat-gpt — SHIP 0.91, as a narrowly scoped prototype with
  the disclosed limits retained as explicit boundaries.
  Conditions: snapshot identity at delegation as an invariant;
  reporting must distinguish proof check / ship / persisted
  binding as three separate facts; no promotion beyond the
  current claim. Binding anchoring required before advancing
  BEYOND the prototype, not a blocker for it.
- seat-gemini — FIX 0.68. Smallest failure: the unclosed half
  of G1 — burn precedes the binding append and an append
  failure leaves the ship standing unbound. Flip conditions:
  (1) fail-closed binding (artefact_hash inside the signed
  record/manifest, or pending binding written+fsync'd BEFORE
  record_ship); (2) replace the stale round-1 flagship
  artefact with a fresh one verified under the current
  checker. Otherwise yes on the race, the narrowed threat
  model, whole-tree completeness within stated bounds, and
  the crash distinction; mode-only hashing noted for next
  iteration.
- seat-claude — FIX 0.72 (reviewed from the brief only;
  findings conditional, probe invited). Conditions:
  (1) __pycache__ absent from snapshot/scratch execution +
  forged-.pyc test; (2) invert crash classification to an
  allow-list; (3) shipped-bytes == verified-snapshot test
  under mid-flight live mutation; (4) full suite green;
  (5) keep the non-claims. Explicitly would NOT block on
  fail-closed binding / non-author anchor for a prototype.

### Coordinator probe on seat-claude (1)
Both the snapshot copy (trust/proofcarry.py:300) and the
scratch runner copy (:631) already use
_IGNORE = ignore_patterns("__pycache__", "*.pyc"): the
execution copies contain no __pycache__ at all, so a forged
matching-header .pyc in the source tree is never copied and
cannot be loaded from the tree. The hole is closed by
construction for proofcarry's own copies. Residual (real,
small): the child process environment is inherited, not
forced to -B / PYTHONDONTWRITEBYTECODE=1, and a check could
write and load its own bytecode inside its scratch run
(side-effect territory). Recorded as a follow-up, with the
forged-.pyc regression test still owed.

## RECONCILIATION (round 2)
Split: 1 SHIP / 2 FIX. Under the no-ship-on-split rule the
cycle verdict stays PROVISIONAL — nothing ships. Convergent
blocking item across internal R4/R6 and seat-gemini:
fail-closed binding anchoring (next cycle, already the
recorded blocking follow-up). Also owed next cycle: fresh
flagship artefact under the current checker (seat-gemini 2);
forged-.pyc regression test + forced -B env (seat-claude 1
residual); crash allow-list inversion assessed against the
documented conservative tradeoff (seat-claude 2 — a design
decision for the war room, not silently adopted);
shipped-bytes == snapshot test (seat-claude 3; partially
covered by existing snapshot tests).
