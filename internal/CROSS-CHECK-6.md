# External war-room seats — Trust Boundary v3.1 (state cycle 11) — ROUND 4
Date: 2026-11-20 ~06:24-06:26 MST. Brief: CROSS-CHECK-BRIEF-CYCLE-V3_1.md (delta, blind).

## seat-gpt — SHIP, 0.86
Fail-open mode: genuinely resolved (multi-layer; byte-identical ledger demo valued). Concurrency: resolved within demonstrated model (144/144, exact accounting; retries = engineering margins, fail-closed on exhaustion). Parser inventory: acceptable residual, owner approval still required — "do not let the exceptions become permanent." Health check: ship. STRONGEST REMAINING DEFECT: production signing-key identity not independently anchored — a well-formed non-test key substitution escapes health checks; wants an independently protected key fingerprint recorded at provisioning, checked at startup/health, with a negative substitution test. Next priorities: P0 key-identity pinning; P1 gate negative-integration test + protected parser remediation; P2 adaptive extraction study + execution attestation design. "v3.1 has earned a ship decision. It has not earned a claim of complete trust-boundary assurance."

## seat-gemini — SHIP, 0.84
Defence-in-depth on mode, stress evidence (144/144, 20/20, 1075), provenance mutations, candid deferrals. Strongest remaining defect: the duplicate-key last-wins loaders (sealed registry + calibration) — the parser differential, contained by digest recomputation, fix queued in the gate proposal awaiting Dilip. Also flags: key-substitution gap (converges with GPT), retry bounds are margins not proofs, deferrals stand.

## RECONCILIATION: TRUST BOUNDARY SHIPPED (v1→v3.1, four external sittings: FIX, FIX, FIX, SHIP/SHIP).
Next trust backlog from the seats: signing-key fingerprint pinning (P0); Protected Gate proposal — path-policy adoption + P-1/P-2 duplicate-key loaders + gate negative-integration test (needs Dilip's approval under the Protected Gate Rule); adaptive cross-proposal extraction study; execution-environment attestation design.
Parent note: parent's independent suite run at 06:25 MST showed 1075 tests with 1 ERROR in test_signing_state_snapshot (hourly track's signed-state module; live-state timing collision with cycle-11 recording) — unrelated to the trust code, root-cause fix dispatched the same morning; the brief's "1075 all passing" reflected the coordinator's run before that state collision.
