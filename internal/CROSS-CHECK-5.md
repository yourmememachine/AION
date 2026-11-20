# External war-room seats — Trust Boundary v3 (state cycle 10)
Date: 2026-11-20 ~05:08-05:11 MST. Brief: CROSS-CHECK-BRIEF-CYCLE-V3.md (blind).

## seat-gpt — FIX, 0.89. seat-gemini — FIX, 0.78. CONVERGENT SHIP-BLOCKER:
**Fail-open deployment mode**: blanking/missing AION_DEPLOYMENT_MODE silently selects research mode (anchoring optional, INIT flags allowed). Required: missing/empty/unknown/malformed mode REFUSES startup; research mode only via an explicit authorised path; live tests must verify the effective mode from INSIDE the running verifier. GPT: "Fix this first... then reconsider SHIP." No architectural redesign demanded.

Claim verdicts (GPT): provenance PASS 0.91 (wants one-at-a-time dependency-mutation demo incl. registry modified after evaluation); exactly-once QUALIFIED 0.90 (process-kill ≠ power-loss — qualify wording; wants multi-PROCESS race test, not threads); extraction QUALIFIED 0.94 (accounting sound; empirical 4/8 is NOT a general guarantee — never promote it; wants adaptive cross-proposal reconstruction attack); gate divergence QUALIFIED 0.92 (66-spelling corpus doesn't bound the whole path space — scope it; wants negative integration test: no alternate route to the protected operation bypassing the verifier); production isolation FAIL 0.98 (solely the fail-open mode); serialisation PASS 0.96 (wants strict-parser consumer inventory incl. offline/migration/recovery utilities).
Additional declared limits demanded: root compromise = verifier compromise (state it fully); provisioning evidence is a snapshot — wants a reproducible deployment health check that consumes no production budget.
Gemini adds: deterministic refusal reasons under concurrency (the registry_untrusted vs eval_evidence_consumed race is a defect, not just a flake); execution-environment attestation gap in provenance (operational trust upstream of the verifier).

## Parent verification note
Parent re-ran the full suite independently: 1002 tests (tree grew past 964 via hourly cycles), 1 failure = test_concurrent_issuance_exactly_one_succeeds — the disclosed refusal-code race, semantics intact (exactly one issuance). It is item 2 of the v3.1 mandate below.

## v3.1 mandate (targeted, no new features)
1. Fail-closed deployment-mode contract + research mode via explicit authorised path only + live inside-verifier effective-mode verification against the real deployment.
2. Deterministic refusal precedence under concurrent issuance (kill the error-code race; the failing test must pass repeatedly, e.g. 20 consecutive runs).
3. Multi-process (not thread) ledger/consumption race test: independent processes, exactly one success.
4. Strict-parser consumer inventory: every security-relevant consumer of signed artefacts (incl. offline inspection, migration, recovery utilities) shares the strict parsing contract, or is listed as a non-security consumer.
5. Deployment health check: reproducible, verifies isolation + mode + anchoring without consuming production budgets; drift cases (permission/user/wrapper/env changes) detected.
6. Wording qualifications in docs/claims: crash claims = process-crash (power-loss explicitly conditional on fs/storage guarantees); extraction = accounting mechanism + empirical results, never a general confidentiality guarantee; path-divergence claim scoped to the tested corpus dimensions; root-compromise limit stated fully.
7. Provenance one-at-a-time dependency mutation demo (incl. registry mutated after evaluation → issuance refused).
Verdict stays PROVISIONAL until both seats re-review the delta brief.
