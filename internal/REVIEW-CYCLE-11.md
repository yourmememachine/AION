# REVIEW — Cycle 11: Trust Boundary v3.1 war room

Six blind reviewers from other pods (rev-r6 forced dissent),
scores locked in state/calibration/calibration.json (subject
cycle-11-build) BEFORE reconciliation:

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | item 1 (mode contract) | 0.74 | FIX |
| rev-r2 | items 2+3 (determinism, races) | 0.88 | SHIP |
| rev-r3 | item 4 (parser inventory) | 0.84 | SHIP |
| rev-r4 | item 5 (health check) | 0.55 | FIX |
| rev-r5 | items 6+7 (wording, mutation demo) | 0.80 | FIX |
| rev-r6 | whole cycle (forced dissent) | 0.55 | FIX |

Reconciled verdict: **FIX** — no ship on a split room. One
reconciled fix list (below); every item was either landed and
re-verified, or explicitly deferred with a reason. After the fix
rounds, the re-review seats returned SHIP (subject
cycle-11-fixround): rev-r4 0.88, rev-r1 0.94 (third look). The
cycle verdict is **SHIP, PROVISIONAL** — it becomes final only
when seat-gpt and seat-gemini re-review the delta brief
(internal/CROSS-CHECK-BRIEF-CYCLE-V3_1.md), per the standing
external-seat rule. An external approval never overrides an
internal FIX; both internal re-reviews are SHIP.

## Principal findings and their disposition

- **rev-r6 F1 CRITICAL / rev-r1 F1 HIGH — the live staged verifier
  was still fail-open v3 code** (test_14 failing). Not a repo
  defect: a stale staged copy. CLOSED by coordinator re-stage +
  readability modes; test_13/test_14 pass live; health check
  10/10 live.
- **rev-r6 F2 HIGH — determinism did not cover sealed_eval.**
  CONFIRMED and worse than reported: re-review rev-r1's probes
  (CRITICAL C1, 0.50 FIX) showed 9/36 registry_untrusted at
  12-process width from TWO holes (un-retried evaluate save;
  snapshot bound exhaustion), and the fix probe then exposed the
  same hole at the eval-attestation ledger append (1–2/36
  ledger_failed). CLOSED in fix rounds 2–3: fresh-instance
  retries at all three saves, budget recorded exactly once,
  bounds 40 framed as margins not proofs, docstring accounting
  corrected to the verified worst case (41 entries). Final
  evidence: 144/144 probe evals clean; rev-r1 third look 0.94
  SHIP with an independent 36/36 probe, exact budget/ledger
  counts, and a deterministic tamper refusal.
- **rev-r4 H1 HIGH — the health checker's probe could MUTATE the
  deployment** (INIT flags + missing anchors → the probe's config
  load created the anchor it reported missing). CLOSED: env check
  FAILs on any non-empty INIT key; the probe is gated off when
  env-file or anchors fail; test asserts the anchor is still
  absent after such a run.
- **rev-r4 H2 HIGH — env paths not bound to --base.** CLOSED:
  HOME/REGISTRY_DIR must equal the base paths, key/anchors under
  the base; AION_REGISTRY_DIR is now stat'ed and validated on a
  copy.
- **rev-r4 M1–M6 / rev-r6 F6 — health-check depth.** CLOSED:
  signing-anchor exactness vs live ledger head+count and
  reanchor-audit check; registry content validation (on a copy);
  key load-validation + known-test-key refusal (with the recorded
  residual: a well-formed non-test key substitution is
  undetectable — no fingerprint exists in the deployment's
  artefacts); staged-code bytecode/root-file/ownership rules and
  full deploy-dir comparison; state-file permission checks incl.
  special bits and symlinks; wrapper-exact env parsing with
  duplicate-key refusal in checker AND wrapper; supplementary
  group memberships. Re-review rev-r4 (0.88 SHIP) re-probed all
  of H1/H2/M1–M6 closed; its one new finding (N1, checker crash
  on corrupt ledger) was fixed by the coordinator and verified:
  FAIL line, all 10 checks still report, no traceback.
- **rev-r6 F3 HIGH / rev-r3 MEDIUM — parser mandate incomplete.**
  The inventory's own rows admitted three gaps: protected P-1/P-2
  (by design — see deferrals) and the budgets-anchor readers.
  CLOSED for the readers: verifier_main and health_check now
  strict-parse (duplicates refused, exact keys, hex head). The
  inventory's false repo-wide claim was corrected and the
  health-check reader added as row 34. The lint call-graph roots
  now include deploy/ (was the suite's second failure).
- **rev-r1 F2 / rev-r6 F4 MEDIUM — mode reporting unenforced at
  the client.** CLOSED: VerifierClient(expected_deployment_mode)
  pin refuses ok-responses missing the field or reporting a
  different mode; observed mode is surfaced; the docstring states
  the field is verifier-reported and NOT cryptographic evidence.
- **rev-r5 MEDIUM/LOWs — wording precision.** CLOSED: deploy
  README describes the two refusal layers distinctly (wrapper
  exit 1 pre-runuser; verifier deployment_mode_refused exit 3);
  extraction group-testing relabelled (pools alone 0/8; 4/8 =
  pools + tolerated refinement probes); mutation header corrected
  (case (a) is a strengthened duplicate) and per-case detail
  substrings pinned (manifest binding; unknown_key,
  signature_mismatch; signer_mismatch); mutation fixture scope
  declared (research mode, unanchored).
- **rev-r1 F3 / rev-r6 F7 LOW — _Config mode default.** CLOSED:
  deployment_mode is a required argument; the only construction
  site passes it explicitly.
- **rev-r2 minors.** Retry bound + access-log amplification now
  documented (and corrected in round 2); sealed_eval converted
  (F2); the broad ValueError catch retained deliberately —
  persistent failures exhaust attempts and refuse
  registry_untrusted, which re-review accepted.
- **rev-r1 (round 2) M1 LOW — count-mismatched transcripts spend
  access-log entries without a budget charge** (snapshot precedes
  the count check). Accepted as a declared limit: entries are
  truthful attempt records, the 10,000-entry cap fails closed,
  and the caller population is orchestrator-launched clients.
  Recorded here and in the delta brief.

## Explicit deferrals (rev-r6 F5 — recorded, not silent)

Three asks from the external seats' v3 round are NOT in this
cycle's mandate and are deferred with reasons:
1. **Adaptive cross-proposal extraction/reconstruction attack**
   (seat-gpt qualification on item 3 of CROSS-CHECK-5): the v3.1
   mandate was the convergent ship-blocker plus the listed
   qualifications; a new attack study is new work, queued as a
   candidate for the next trust cycle.
2. **Gate negative-integration test** (seat-gpt): the gate is a
   protected path (Protected Gate Rule); a test that exercises
   the gate's refusal inside the verifier's path policy belongs
   with the owner's pending gate decision
   (internal/PROTECTED-GATE-PROPOSAL.md).
3. **Execution-environment attestation** (seat-gemini): no
   mechanism exists in the current design to attest the
   verifier's execution environment beyond the uid/staged-code
   isolation the health check verifies; recorded as a known gap,
   not silently dropped.

Protected findings P-1/P-2 (duplicate-key acceptance in
eval/registry.py and eval/calibration.py) are likewise deferred
BY DESIGN to the owner's Protected Gate decision; the
recommended changes are described in the delta brief so the
external seats see them too.

## Verification summary

- Item-2 acceptance: previously failing test 20/20 consecutive.
- Full suite: 1075 tests, OK (skipped=2 — live test_10/test_11
  in their by-design post-run state; both run + passed after the
  operator budget reset in this cycle).
- Live deployment: health check 10/10; production suite green
  incl. test_13 (blanked-mode refusal) and test_14 (effective
  mode from inside the process).
- Contention: 144/144 probe evals deterministic (see build
  record).

Verdict: **SHIP (PROVISIONAL on external round 4).**
