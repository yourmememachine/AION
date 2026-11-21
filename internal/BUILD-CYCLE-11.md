# BUILD — Cycle 11: Trust Boundary v3.1 (targeted fixes)

Mandate: internal/CROSS-CHECK-5.md — the external seats' verdicts on
Trust Boundary v3 (Gemini FIX 0.78, ChatGPT FIX 0.89), converging on
one ship-blocker plus qualifications. Targeted fixes and
demonstrations only; no new features; protected paths untouched
(eval/gate.py not edited).

Baseline (parent-verified, re-confirmed at cycle start): full suite
1002 tests, exactly ONE failure —
test_concurrent_issuance_exactly_one_succeeds, the disclosed
refusal-code race (loser sometimes refused registry_untrusted
instead of eval_evidence_consumed; exactly-one-issuance intact).
Root cause: an EvalRegistry instance snapshots at construction; a
concurrent verifier process's access-log saves made a later save on
the stale instance raise CorruptRegistryError (staleness), which the
verifier mapped to registry_untrusted before the race loser could
reach the consumption check.

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15). War room: 6 reviewers
from other pods (rev-r1..rev-r6, rev-r6 forced dissent), blind
scores locked in the calibration log (subject cycle-11-build)
before reconciliation. External seats (seat-gpt, seat-gemini) are
NOT part of this record: the cycle verdict is PROVISIONAL until
they re-review the delta brief (CROSS-CHECK-BRIEF-CYCLE-V3_1.md).

## What was built, by mandate item

1. **Fail-closed deployment mode (the ship-blocker).** The mode is
   now REQUIRED configuration: trust/verifier_main.py refuses
   startup with deployment_mode_refused (exit 3, before key load or
   any ledger/anchor/budget side effect) when
   AION_DEPLOYMENT_MODE is missing, empty, whitespace-only,
   unknown, or non-canonical. Research mode is reachable only by
   naming it exactly; production requirements (signing anchor,
   budgets anchor, no INIT flags) are enforced as properties of
   the mode. The launcher (deploy/verifier-identity/run-verifier.sh)
   refuses BEFORE runuser (exit 1, its own message) when the env
   file's mode is absent/empty/invalid/duplicated, so a wrapper
   launch never reaches the verifier in those states. The mode is
   reported on every post-config response (optional
   deployment_mode protocol field), and trust/client.py can PIN an
   expected mode (expected_deployment_mode): a pinned client
   refuses ok-responses that omit the field or report a different
   mode; the field is verifier-reported, not cryptographic
   evidence (documented in the client). Live proof on the real
   deployment: test_13 (mode blanked in a copy of the live env →
   wrapper refusal, ledger unmoved), test_14 (effective mode
   "production" reported from inside the running verifier),
   test_g (non-live wrapper refusal incl. duplicate keys), test_f
   (successful production run reporting the mode).
   tests/test_trust_mode_contract.py: 14 tests.

2. **Deterministic refusal precedence.** _registry_snapshot():
   registry reads that must save access-log entries retry with a
   FRESH EvalRegistry per attempt, so a race loser survives the
   winner's saves and reaches the consumption check, which refuses
   deterministically with eval_evidence_consumed. Acceptance:
   test_concurrent_issuance_exactly_one_succeeds passed **20/20
   consecutive runs** at cycle close; the full suite is green.
   Fix rounds extended the same discipline to the whole
   sealed_eval path (see Fix rounds): snapshot, evaluate save and
   eval-attestation ledger append all retry on fresh instances;
   the budget is recorded exactly once, before the evaluate loop.

3. **Multi-process race test.** tests/test_trust_multiprocess_race.py
   + tests/fixtures/issuance_racer.py: 4 independent OS processes
   race one eval pair through the real client/launcher — exactly
   1 success, 3 refusals all eval_evidence_consumed, 2 consumption
   entries; a two-disjoint-pairs variant gives 1 success per pair.
   Plus tests/test_trust_sealed_eval_contention.py: 10
   barrier-synchronised processes evaluating distinct transcripts
   — all ok, budget identity count exactly N, exactly N ledger
   eval-attestations.

4. **Strict-parser consumer inventory.** docs/PARSER-INVENTORY.md:
   34 rows enumerating every JSON consumer of security-relevant
   artefacts across the production packages AND deploy/, each with
   a disposition. Four permissive loaders in non-protected modules
   were brought under the strict contract (duplicate-key and
   non-finite refusal, module error types): trust/ledger.py,
   trust/budgets.py, trust/anchoring.py, core/loop.py — plus, in
   the fix rounds, trust/verifier_main.py's budgets-anchor reader
   (protocol.strict_loads, exact key set, hex head) and the health
   checker's budgets-anchor read. Two consumers sit in PROTECTED
   modules and were NOT edited (Protected Gate Rule):
   eval/registry.py and eval/calibration.py accept duplicate keys
   last-wins. Both are carried as protected findings P-1/P-2 with
   an explicit disposition in the inventory and in the delta
   brief; the residual is a parser differential, not an integrity
   break (digests/chains recompute over the last-wins parse).
   tests/test_trust_parser_inventory.py: 23 tests.

5. **Deployment health check.** deploy/verifier-identity/
   health_check.py + health-check.sh: 10 checks (user,
   group-membership incl. supplementary groups, directories,
   env-file, key-file, anchors, registry-on-a-copy, state-files,
   staged-code, effective-mode probe through the real wrapper).
   Read-only against production: the probe is gated off when the
   env-file or anchors check fails (an INIT-flagged probe could
   otherwise CREATE the anchors it reports missing — found in
   review, fixed, test-pinned); the registry is validated on a
   copy so the live access log is untouched. Detects drift on
   copies: permission change, wrapper change, env change
   (incl. blanked mode, INIT flags, path redirection), group
   membership change, staged-code change (incl. planted
   sitecustomize.py / __pycache__), anchor staleness, registry
   corruption, key substitution by known test keys. Recorded
   residual: substitution by another well-formed non-test key is
   undetectable by any check the deployment supports (no key
   fingerprint is recorded in the deployment's artefacts);
   downstream MAC verification is where it surfaces.
   tests/test_trust_health_check.py: 16 tests. Live result at
   cycle close: **10/10 PASS** against the real deployment.

6. **Claim-wording qualifications.** docs/PROVENANCE.md,
   docs/EXTRACTION-ACCOUNTING.md, trust/README.md,
   deploy/verifier-identity/README.md now state: crash-safety is
   scoped to process crashes, with power-loss durability
   conditional on filesystem/storage fsync semantics; extraction
   results are an accounting mechanism plus empirical
   measurements on a stated fixture (n=8, 4-token alphabet given
   to the attacker; coordinate descent 2/8; group testing pools
   alone 0/8, pools + tolerated refinement probes 4/8) — never a
   general confidentiality guarantee; the path-divergence claim is
   scoped to the tested corpus dimensions, with symlink
   traversal, case-insensitive folding, unicode normalisation
   equivalence, hard links, alternate roots/mounts and TOCTOU
   explicitly out of scope; and the threat model states plainly
   that root compromise = verifier compromise (env, code,
   startup, execution context).

7. **Provenance dependency-mutation demo.**
   tests/test_trust_provenance_mutation.py: from a genuinely valid
   record + config (control issues successfully), mutate exactly
   one dependency at a time — registry grows after minting,
   cross-registry pointer swap (same ids, one differing answer),
   different key file, different signer id, empty ledger home,
   swapped pair order. Each refuses issuance with the pinned code
   AND the discriminating detail substring, zero consumption,
   zero new signatures. Header declares the fixture scope:
   research mode, unanchored (the bindings are mode-independent).

## Fix rounds (war-room driven; see REVIEW-CYCLE-11.md)

Round 1 closed: sealed_eval routed through the snapshot retry;
strict budgets-anchor readers (verifier + health checker); _Config
mode made a required argument; client mode pin; health-checker
hardening (INIT gating, env-path binding to base, anchor
exactness vs ledger head/count, registry-on-copy validation, key
load/test-key refusal, staged-code bytecode/root-file/ownership
rules, state-file modes incl. special bits and symlinks, wrapper-
exact env parsing incl. duplicate refusal in BOTH checker and
wrapper, supplementary-group check); lint roots extended to
deploy/; inventory claim corrected (row 34); extraction label
corrected; deploy README two-layer description; mutation details
pinned.

Round 2 closed CRITICAL C1 (re-review rev-r1, 0.50): sealed_eval
still nondeterministic under tight contention — the evaluate save
was un-retried and the snapshot bound exhaustible. Fix: evaluate
retry on fresh instances (budget recorded once, before the loop),
bounds raised to 40 and honestly framed as engineering margins
(not proofs), docstring accounting corrected (worst case 41
access-log entries per snapshot call). A third fix closed the
same hole at the eval-attestation ledger append (bounded
fresh-instance retry; no-write-on-CorruptLedgerError verified in
trust/ledger.py before implementing). Final contention evidence:
144/144 barrier-synchronised evals clean across two 12-process ×
3-wave × 2-run probes (zero registry_untrusted, zero
ledger_failed, exact budget and ledger counts); re-review rev-r1
third look: 0.94 SHIP with an independent 36/36 probe.

Coordinator fix (rev-r4 N1): the health checker's anchors check
no longer crashes on a corrupt ledger — it reports FAIL anchors
and still runs all 10 checks. Also closed during re-staging: the
staged code copy must be verifier-READABLE (root-owned a+rX);
the effective-mode probe caught the omission.

## Live operations performed

- Re-staged /var/lib/aion-verifier/code from the fixed repo
  (content mirror + a+rX modes); staged wrapper refreshed.
- Operator budget reset (documented ceremony): budgets store
  deleted, budgets anchor deleted, ONE bootstrap run outside
  production (research-mode ceremony env with
  AION_BUDGETS_ANCHOR_INIT=1 — production refuses INIT flags by
  design) re-pinned the anchor at the fresh store's genesis head.
  Real env file never carried an INIT flag.
- Live battery after reset: health check 10/10; production
  deployment suite 18 tests OK with test_10/test_11 RUNNING and
  PASSING (they skip again only after their one post-reset run,
  by design).

## Test totals

Full suite at close: **1075 tests, OK (skipped=2)** — the 2 skips
are live test_10/test_11 in their post-run consumed state; both
were run and passed explicitly after the reset in this cycle.
Baseline 1002 (1 failure) → 1075 (0 failures): +73 net new tests.
Item-2 acceptance: 20/20 consecutive runs of the previously
failing test.
