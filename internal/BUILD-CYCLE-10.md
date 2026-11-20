# BUILD — Cycle 10: Trust Boundary v3 (Demonstrations)

State cycle: 10 · Backlog item: `trust-boundary-v3-demonstrations`
Baseline: 820 tests (cycle 9) → **964 tests, all passing**
(coordinator full-suite run: `Ran 964 tests, OK (skipped=2)`; the 2
skips are the live production tests test_10/test_11 converting to an
honest skip because their fixed transcripts were already consumed by
the recorded provisioning run — see Mandate 5).

Mandate source: `internal/CROSS-CHECK-4.md` — both external seats
(ChatGPT 0.94, Gemini 0.82) voted FIX on Trust Boundary v2 and set
six demonstration demands. This cycle is demonstrations and fault
injection, not new features. Staffing: 15 coders, 5 pods of 3,
disjoint file ownership.

## Mandate 1 — Evaluator provenance chain (Pod A: seat-1/2/3)

- `docs/PROVENANCE.md`: the full chain (trusted registry → trusted
  evaluation configuration → controlled execution → authenticated
  score record → independently derived decision → signed
  attestation) with the exact decision predicate: approve iff
  `sealed_after >= sealed_before` (plain float `>=`, no epsilon)
  AND NOT `gaming_suspected` AND NOT `sealed_regression`, where the
  gap assessment uses `EPSILON=1e-9`, widen threshold 0.05, reason
  precedence sealed_regression → public_only_gain → gap_widened →
  no_flag.
- `tests/test_trust_provenance.py` (15 tests at pod delivery; 20
  after the fix round): eight attack classes driven through the
  REAL verifier subprocess — config substitution, cross-registry
  (refused on manifest mismatch alone), cross-key, expired record,
  signer misuse (submit_claim can never sign), config injection
  (8 fields × 2 modes → exit 2, registry access log unchanged),
  forged record, predicate probes. No enforcement gaps found.

## Mandate 2 — Ship crash laboratory (Pod B: seat-4/5/6)

- `tests/fixtures/ship_crash_runner.py` +
  `tests/test_trust_crashlab.py`: real `os._exit(99)` kills at every
  durable side-effect boundary of `record_ship` (10 crash points at
  pod delivery): recovery run twice from fresh objects is
  idempotent; the decision is consumed exactly once iff the burn
  landed; ≤1 history entry per item; recovery journals NO
  AUTHORISATION_VERIFIED; re-ship of a consumed decision refused.
  ANOMALY occurred nowhere on the sanctioned path.
- Concurrency: two shippers/one item (exactly 1 burn), two
  recoveries racing, and concurrent ShipLedger burns.
- **Hole found and fixed:** concurrent burns of different decisions
  into one ShipLedger failed spuriously
  (`CorruptLedgerError: journal changed on disk since load`).
  `trust/ledger.py`: `ShipLedger.burn`/`finalise` now do bounded
  reload-and-retry (8 attempts), re-running all duplicate/cycle
  validations against fresh entries on every attempt.
  `SigningLedger` untouched.
- Duplicate-value attacks: another ship's cycle is never attributed
  (tx2 parks ANOMALY, tx1 stays COMMITTED); byte-identical payloads
  on two items commit independently with their own cycle ids.

## Mandate 3 — Extraction accounting, identity, consumption (Pod C: seat-7/8/9)

- **Single-use consumption:** `SigningLedger.try_consume_eval_records`
  appends both consumption entries in ONE atomic save (no
  half-consumed-pair window; fail-closed in both crash directions);
  `_mode_issue_attestation` consumes after pair/scope checks,
  before signing, including on derived rejects. Race evidence: two
  concurrent issuances on one pair → exactly 1 success, exactly 2
  consumption entries.
- **Budgets-anchor INIT guard:** INIT may pin only the genesis head;
  a non-genesis store with a missing anchor refuses
  (`anchor_missing_established_budgets`).
- `docs/EXTRACTION-ACCOUNTING.md`: the bound stated in distinct
  disclosed positions — one response discloses one aggregate
  (correct/n, ≤ log2(n+1) bits); caps 25/proposal and 500/identity
  enforced in-verifier before the registry opens; replay and
  near-duplicate probe rules (similarity ≥0.8 OR ≤2 differing
  positions vs ANY prior transcript of the identity; first 2 probes
  tolerated, 3rd latches the family, latch persisted). Measured
  extraction against the real verifier (n=8): coordinate descent
  recovered 2/8 before the latch; group testing 4/8 in 19 evaluated
  queries; full extraction fails. Identity is the
  operator-configured `AION_VERIFIER_ACTOR_ID`; the protocol has no
  identity field (injection attempts → exit 2, budget untouched).

## Mandate 4 — Gate path-policy equivalence (Pod D: seat-10/11/12)

- `tests/test_trust_pathpolicy_differential.py`: differential
  harness over a spelling corpus (48 at pod delivery, 66 after the
  fix round) comparing gate raw verdict / `pathpolicy.classify` /
  oversight-canonicalised verdict. Equivalence PROVEN on canonical
  spellings. Divergences pinned per class (final counts:
  canonical 20, gate-miss 10, gate-catches-anyway 10,
  policy-catches-oversight 6, both-refuse 11, gate-stricter 1,
  agree-unprotected-noncanonical 8). The `eval/` prefix survives
  every trick in the corpus; all 34 non-canonical spellings of
  protected paths are refused as malformed by the real verifier.
- Caller audit: no production caller passes raw input to the gate.
- `internal/PROTECTED-GATE-PROPOSAL.md`: the precise diff sketch
  for `eval/gate.py`, divergence table, caller audit, risk
  analysis, and the import-cycle resolution — for Dilip's decision
  under the Protected Gate Rule. The gate itself was NOT edited.
- Wording corrected: `trust/pathpolicy.py` and `trust/README.md`
  no longer call path-policy/1 universal; the gate has not adopted
  it.

## Mandate 5 — Production isolation, provisioned (Pod E + coordinator)

- Production mode (coordinator patch): `AION_DEPLOYMENT_MODE`
  (production|research, default research) in
  `trust/verifier_main.py`; production requires both anchor paths
  and refuses both INIT flags; added to the wrapper allowlist and
  the setup template.
- Provisioning ceremony EXECUTED on this VM (2026-11-20; full
  record in `deploy/verifier-identity/README.md`): note the VM's
  OS-level state reset mid-cycle (user/dirs vanished; only
  `~/workspace` persisted) and was rebuilt via `setup.sh` —
  `aion-verifier` is uid 999 (was 997 in cycle 9). Key generated
  verifier-owned 0600; registry provisioned AS the verifier (3
  public / 6 sealed / 1 golden operator items); staged root-owned
  code copy at `/var/lib/aion-verifier/code` (the verifier uid
  cannot read the live checkout); anchor ceremony in research mode
  with INIT flags, then env flipped to production; final operator
  budget reset so the delivered deployment starts with fresh
  budgets (the ceremony's own sealed_eval had consumed the
  all-correct transcript — its re-presentation was refused as a
  replay, demonstrating the control).
- Live verification: production sealed_eval through the real
  wrapper scores and signs; INIT-in-production refuses exit 3;
  `tests/test_trust_production_deploy.py` passed 11/11 at
  provisioning time (8 live + 3 spec tests): nobody OS denial
  battery, direct-invocation refusal, wrapper root-only +
  allowlisted-environment probe, rollback-on-a-copy detection
  (ledger-only and anchor-only rollbacks detected; joint rollback
  is the declared residual). The staged copy was refreshed after
  the fix round and the live config load re-verified.

## Mandate 6 — Serialisation ambiguity battery (Pod E: seat-13/14/15)

- `tests/test_trust_serialisation.py` (49 tests at pod delivery,
  59 after the fix round): wire layer (duplicate keys at any depth
  incl. post-decode unicode escapes, NaN/±Inf/1e999, concatenated
  documents, BOM, invalid UTF-8, 20k-deep nesting), mode bodies
  (unknown fields in all 5 modes, null-vs-missing, bool/int/string
  confusion), artefact dicts (eval record, gate envelope,
  attestation envelope). Every refusal asserts the signing-ledger
  sign count is unchanged. No gap found at pod delivery — the war
  room's dissent seat then found the artefact-layer defects below.

## War-room fix round (see REVIEW-CYCLE-10.md)

The internal war room (6 blind reviewers) voted FIX ×5 / SHIP ×1.
All findings were fixed and independently re-verified (re-review
scores 0.92 code / 0.97 docs):

- **S1 (HIGH):** sealed_eval's proposal_id (the signed scope) was
  validated more weakly than issuance's id grammar. Fixed:
  `_check_sealed_eval_scope` applies signing's `_check_id` to the
  scope root (one optional `:baseline`/`:candidate` suffix, the
  legitimate pair-scope form) before any budget recording.
- **S2 (HIGH):** `verify_eval_attestation` accepted an int-spelled
  score (payload rebuilt) while `trust/client.py` hashed the
  presented payload and rejected the same record. Fixed: shared
  `rebuild_eval_payload` used by both consumers.
- **S3 (MEDIUM):** issue_attestation consumed the eval pair before
  validating proposal_id. Fixed: id + public-score validation now
  precede consumption; consumption on derived rejects unchanged.
- **S6 (LOW):** `parse_float` non-finite hooks added to the
  attestation/manifest/release JSON loaders (structural, not
  emergent, strictness).
- Crash lab: anchored crash points (after_commit, after_anchor,
  during_anchor_save), during_finalise_save, the state-equivalence
  argument stated, the stub test relabelled as a recovery-logic
  unit test with a production companion test.
- Differential corpus 48 → 66; proposal wording bounded ("full
  list within the corpus"; gate-miss is an open family; the real
  bound is the verifier's canonical-only rule); import-cycle
  analysis completed.
- PROVENANCE.md brought current (consumption is live; what an
  issuance approve certifies stated plainly); predicate boundary
  tests (0.05 exact / 0.05+2e-9 / 1e-10 drop) and a shared-home
  cross-key MAC-isolation test added; EXTRACTION-ACCOUNTING.md
  qualified (score-channel scope; non-adaptive designs bounded
  only by the aggregate cap).
- Deploy README status corrected to the executed ceremony;
  budgets-half production-gate spec tests added; wrapper gained
  `umask 077`.

## Known residuals (declared, not hidden)

- Public/capability gate score maps remain caller-asserted trusted
  inputs (cannot create an accept alone; issuance approve
  certifies non-regression over asserted publics — see
  PROVENANCE.md).
- Recovery does not advance a stale ship anchor after a
  post-COMMITTED crash; the anchor remains a valid prefix
  (stale-not-tampered) until a later `update_anchor`.
- Co-located rollback: ledger+anchor rolled back together is
  undetectable if the attacker can write both (root, the verifier
  uid, or a member of the verifier's group — the group must remain
  single-member). Whole-machine snapshot restore by the machine
  owner is out of scope.
- Blanking `AION_DEPLOYMENT_MODE` in the root-owned env file
  silently selects research mode (operator-error path, declared).
- All callers of one verifier deployment share its single actor
  budget (availability, not confidentiality).
- Known flake: `test_concurrent_issuance_exactly_one_succeeds`
  intermittently reports the losing racer's refusal as
  `registry_untrusted` instead of `eval_evidence_consumed`
  (semantics hold: exactly one issuance, loser refused
  fail-closed). Backlogged as `consumption-race-error-code`.
- Reviewer independence still unmeasured (carried from v2).
