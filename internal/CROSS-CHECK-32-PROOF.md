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
