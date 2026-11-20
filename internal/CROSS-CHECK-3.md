# External war-room seats — Trust Boundary cycle (state cycle 8)
Date: 2026-11-20 ~03:14-03:16 MST. Brief: CROSS-CHECK-BRIEF-CYCLE-5.md (blind).

## seat-gemini — FIX, 0.58
Critical: same-user key + caller-asserted gate scores make the verifier a "laundry oracle" — signatures authenticate assertions from the same privilege domain; tamper-evident log, not a security boundary.
High: signed_only not persisted (silent downgrade by reopening plain); legacy unsigned memory-reuse bypass still live; production flows not yet on signed paths.
Medium: path canonicalisation drift between verifier and gate; sealed_eval exact-score oracle + no verifier timeout + registry TOCTOU.
Accepted as sound: manifest excluding state/ (with atomic-snapshot caveat); burn-before-record ordering (with recovery caveat).
Refuses to ship: trust-boundary claim while legacy bypass lives; caller-asserted scores as sufficient evidence; silent downgrade via unpersisted flag.
Next: enforce verifier-produced evidence end-to-end; persist signed_only with audited override; route one real cycle fully through the signed path; remove/quarantine legacy path.

## seat-gpt — FIX, 0.68
F1 Critical: attestation authenticates assertions, not truth. Split submit_claim (unsigned) from issue_attestation (authority derives decision from verified evaluation receipts; no caller-selected approval fields). Blocking.
F2 Critical: same-user subprocess is not a separate security principal. Dedicated OS user for verifier, keys/ledger owned by it, authenticated IPC. Blocking for any adversarial-isolation claim.
F3 High: persist signed_only in store metadata; refuse downgrade on every open; commit capability held by authorised component only. Blocking for production memory integrity.
F4 High: manifest/state split defensible, but add an execution-context attestation binding security-relevant state/config/deps/runtime.
F5 High: burn-then-record needs an explicit ship transaction state machine (PREPARED→…→COMMITTED), durable idempotent transitions, shared transaction id, recovery that never replays a consumed decision.
F6 High: sealed-eval oracle leakage — query budgets, per-proposal budgets, adaptive-query detection INSIDE the verifier.
F7 Med-High: anchor BOTH ledgers externally; startup refusal when an established ledger is missing; explicit first-init ceremony.
F8 Medium: one shared versioned canonical path policy for gate/manifest/verifier/shipcheck.
F9 Medium: lint is a regression detector, not a security mechanism — move to capability-oriented design.
Acceptance criteria for next cycle = adversarial demonstrations (builder reads key → OS denies; fabricated approval → no signature; plain store opens signed dir → refuses; adaptive queries → budget stops extraction; ledger deleted → startup refuses; crash at every ship transition → one consistent outcome; red-team with architecture but not test cases).
Final line: "Stop trying to make the authorisation harder to forge until you have established that the authority issuing it cannot be manipulated into authorising the wrong thing."

## Reconciliation mandate (both seats + internal dissent agree)
Trust Boundary v2 cycle, no new capability work until: (1) evidence-derived attestation, (2) persistent non-downgradable signed_only + legacy bypass closed/quarantined, (3) verifier-produced evidence consumed by the gate, (4) ship transaction state machine with safe recovery, (5) in-verifier query budgets, (6) unified path policy, (7) dual-ledger external anchoring + missing-ledger refusal. Separate-OS-user verifier: implement if the VM permits, otherwise build the code paths and document it as the deployment requirement — do not fake it.
