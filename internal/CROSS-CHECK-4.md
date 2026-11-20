# External war-room seats — Trust Boundary v2 (state cycle 9)
Date: 2026-11-20 ~04:08-04:11 MST. Brief: CROSS-CHECK-BRIEF-CYCLE-V2.md (blind).

## seat-gpt — FIX, confidence 0.94
F1 Critical: eval-record provenance unestablished — authentic signature ≠ trustworthy evaluation. Need the full chain (trusted registry → trusted eval config → controlled execution → authenticated record → derived decision → attestation), the exact decision predicate, and proof a builder cannot influence evaluator inputs/config or get arbitrary scores signed.
F2 Critical: ship exactly-once not proven — crash BETWEEN a durable side effect and its journal write is the untested gap; one-in-flight must hold across processes; value-based join can misattribute duplicate cycle values. Demands a crash laboratory: injection at every durable operation, concurrent workers, duplicate cycles, repeated recovery.
F3 High: budgets bound queries, not disclosed information — one query may return many positions; identity issuance/Sybil unspecified; publish exact accounting in distinct disclosed positions.
F4 High: gate path divergence — unify or formally test equivalence; until then don't call the policy universal.
F5 High: anchoring config-gated — production must fail closed without it; ceremony must not be silently repeatable after state loss.
F6 High: signed_only integrity rests on filesystem ownership — builder's OS identity must be unable to write store metadata; permit binding/atomicity questions.
F7 Med-High: OS identity machinery exists; provisioning + live adversarial permission tests outstanding.
F8 Medium: parser/serialisation ambiguity tests (duplicate keys, bool/int confusion, unicode, canonical hashing).
Five conditions for reconsideration: provenance chain; crash-lab pass; quantified extraction bound incl. identity issuance; path unification/equivalence; provisioned isolation + mandatory anchoring, adversarially tested.

## seat-gemini — FIX, confidence 0.82
High: co-located rollback — ledger AND anchor rolled back together look consistent; anchor must live outside the same rollback scope (undeclared limit).
High: value-based join misattribution (converges with GPT F2).
High: symmetric HMAC while unprovisioned (converges with GPT F7).
Medium: gate path-policy divergence unbounded (GPT F4).
Medium: sealed-eval records may be REUSABLE across attestations — consumption/single-use not specified; concurrent issuance race.
Low: identity authentication for budgets unspecified (GPT F3 Sybil point).
Extraction bound per Gemini: 500 queries/identity holds; fine-grained extraction blocked; coarse probing within budget still leaks signal; multi-identity multiplication undeclared.

## Reconciliation mandate → Trust Boundary v3 (demonstrations, not features)
1. Evaluator provenance chain, documented + enforced + attacked (config substitution, input manipulation, signer misuse).
2. Ship crash laboratory: fault injection at every durable side-effect boundary, cross-process concurrency, duplicate-value cycles, idempotent repeated recovery.
3. Extraction accounting in disclosed positions + authenticated/verifier-issued identities + single-use consumption of eval records at issuance (atomic).
4. Gate path-policy equivalence: differential test harness vs path-policy/1 (no gate edit — Protected Gate Rule); divergences enumerated and bounded, or escalated to Dilip's proposal.
5. Provision the aion-verifier deployment (operator ceremony) and run live OS-denial tests; anchoring mandatory/fail-closed in production mode; anchor placed outside builder rollback scope (verifier-owned) with the co-located-rollback limit declared precisely.
6. Serialisation ambiguity test battery for attestation bodies.
Verdict stays PROVISIONAL until both seats re-review v3.
