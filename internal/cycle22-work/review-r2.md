# War-room review — seat rev-r2 (WS2 focus) — cycle 22

Blind review of the uncommitted working tree on top of aeb6ef6,
against DESIGN-FINAL R1–R4 and CROSS-CHECK-15 (seat-gemini's
commit-then-mirror resurrection defect). Focus: WS2 — anchoring
the consumption journal. Production code and tests were NOT
edited; the mutation check ran in a scratch copy under /tmp.

## Verdict: FIX — score 0.89

The WS2 mechanism is correct and independently mutation-verified.
The one blocking defect is documentary, but it sits exactly on
the claim surface cycle 22 exists to repair: the authoritative
class docstring for the consumption journal still states the
cycle-21 residual (journal NOT anchored, follow-up covering both
journals), contradicting R2, the consume-mode docstring, and the
DECISION-CONSUMPTION-HEAD addendum — which asserts that very
paragraph "is rewritten". R4's docstring sweep did not land
there. External seats re-checking item (3) will read that
paragraph as the claim.

## Findings

### F1 — MAJOR (docs/claim): stale R10 residual in the consumption journal's own docstring
- `trust/ledger.py:715-725` (`CeremonyConsumptionLedger`):
  "Anchoring residual (cycle 21, R10, stated precisely): this
  journal is NOT externally anchored this cycle… The follow-up
  ceremony-journal-anchoring covers both journals (issuance +
  consumption) jointly." Both clauses are now false: the journal
  IS anchored (kind `ceremony-consumption`,
  `trust/anchoring.py` ANCHOR_KINDS), and R2 narrows the
  follow-up to the issuance journal only.
- `signing/pin_ceremony.py:287-300` repeats the same superseded
  R10 consumption residual ("can lower the enforced head for
  never-consumed envelopes" as the stated residual, no mention
  of the consumption anchor).
- Aggravating: `internal/DECISION-CONSUMPTION-HEAD.md` cycle-22
  addendum states the R10 wording in
  `CeremonyConsumptionLedger`'s docstring "is rewritten to
  match" — it was not (`git diff trust/ledger.py` touches only
  `AlreadyConsumedError` and the WS1 head rules).
- Fix: rewrite both passages with R2's residual wording
  (anchor-configured burns whose update completed survive a
  home rollback, detected at startup; append→anchor window and
  research/unconfigured carry no rollback claim), exactly as
  already done correctly in the consume-mode docstring
  (`trust/verifier_main.py:2613-2622`).

### F2 — MINOR (docs): ambiguous "ceremony journal" in the verifier header
- `trust/verifier_main.py:255-256`: "The ceremony journal is
  NOT externally anchored (follow-up: ceremony-journal-anchoring)".
  In context this is the ISSUANCE journal and is substantively
  correct under R2's narrowing, but the unqualified name now
  collides with the anchored consumption journal two sections
  earlier in the same header (lines 175-195). Name it the
  issuance journal.

### F3 — MINOR (observation, benign): production consumption-anchor gate is seed-conditioned
- `trust/verifier_main.py` (~line 820): the production
  REQUIRED/INIT-refused rule for the consumption anchor fires
  only `if deployment_mode == "production" and
  ceremony_seed_raw`. No live gap: production without a seed
  already refuses startup earlier ("production mode requires
  AION_CEREMONY_SIGNING_SEED_PATH"), so the condition is
  unreachable in the weaker form. Recorded for accuracy, not
  as a defect requiring change.
- Relatedly, `_load_config` checks consumption-anchor
  distinctness against the signing and budgets paths, but not
  signing-vs-budgets pairwise (pre-existing); `trust/wiring.py`
  checks all pairs. No action needed for WS2.

## Checks that PASSED (with evidence)

### (a) Commit order is load-bearing — verified in code AND by independent mutation
- Actual consume path, `trust/verifier_main.py`: journal append
  at line 2790 (`append_consumption`, the commit point) →
  `_update_ceremony_consumption_anchor(config)` at line 2802 →
  signing-ledger mirror at line 2804
  (`append_ceremony_consumption`) → `_update_anchor(config)`
  (signing) at line 2813. Exactly R2's order. Mirror failure
  still maps to `ledger_failed` with the burn standing (K6
  unchanged); consumption-anchor failure also `ledger_failed`
  via `_update_ceremony_consumption_anchor` (lines 946-968).
- Mandatory test logic re-read
  (`tests/test_trust_ceremony_journal_anchor.py:285-317`): it
  genuinely exercises the sequence — bootstrap with both
  anchors INIT'd then INIT removed, snapshot of the ledger
  home only (anchors live outside it), mirror patched to raise
  in a wrapper subprocess, rollback, replay via a fresh client
  asserted to raise `anchor_refused`, and assertions that no
  journal gained an entry. The patch target
  (`SigningLedger.append_ceremony_consumption`) is the real
  mirror call site.
- Independent mutation (scratch copy /tmp/aion-mut, repo
  untouched): moving the consumption-anchor update to AFTER
  the mirror write made
  `test_mandatory_mirror_failure_then_rollback_refused` FAIL
  ("VerifierConfigError not raised" — the replay resurrected
  and consumed), while the clean-consume rollback variant
  still passed, as expected. This confirms the build seat's
  reported mutation result and that the test pins the ORDER,
  not merely the anchor's existence. Scratch copy deleted.

### (b) Residual append→anchor window — honestly documented in the operative places
- Consume-mode docstring (`trust/verifier_main.py:2613-2622`)
  carries R2's wording verbatim in substance: window protected
  against an intact home, NOT against a full rollback inside
  it; research/unconfigured: no rollback claim.
- Characterisation tests pin both boundaries and are labelled
  as claim-boundary pins a future closure must flip
  deliberately: `test_append_anchor_window_rollback_replay_succeeds`
  (window module skips the anchor update, mirror fails,
  rollback, replay SUCCEEDS) and
  `ResearchModeNoAnchorTests.test_research_no_anchor_rollback_replay_succeeds`.
  (The stale paragraphs in F1 are the exception, not the rule.)

### (c) Allowlist 17→19 — consistent in ALL copies
- `deploy/verifier-identity/run-verifier.sh` ALLOWED_KEYS: 19.
- `deploy/verifier-identity/health_check.py` ALLOWED_KEYS: 19,
  with the new INIT key in `_INIT_KEYS` and the new PATH key in
  `_PATH_KEYS` (lines 96-97, 111, 120).
- `trust/wiring.py` ALLOWED_ENV_KEYS: 19; new path also in
  `_INIT_ENV_KEYS`, `_ANCHOR_ENV_KEYS`, and REQUIRED_ENV_KEYS.
- `deploy/verifier-identity/setup.sh` template writes both new
  keys (lines 113-114) with the outside-home/distinct comment.
- `trust/verifier_main.py` header docstring documents both.
- Cross-copy equality is asserted by
  tests/test_trust_wiring.py and tests/test_trust_production_deploy.py
  (both green in my run).

### (d) Startup refusal semantics — correct
- `_load_config` consumption block (~lines 815-925): runs
  whenever the path is configured, regardless of mode (the
  verifier is one process per request, so this precedes every
  mode dispatch). `verify_anchor(..., kind="ceremony-consumption")`;
  `("anchor_missing",)` + INIT ⇒ `initialise_anchor` — and
  since `verify_anchor` returns `anchor_missing` only for an
  EMPTY journal, a non-empty journal with a missing anchor
  yields `anchor_missing_established_ledger` ⇒ `anchor_refused`,
  never silently blessed; recovery is the audited
  force_reanchor path, as R2 requires. All other reasons ⇒
  `anchor_refused` with the joined reasons. Placement
  (outside verifier home) and distinctness (vs signing and
  budgets anchor paths, resolved) refuse as
  `verifier_misconfigured`; non-absolute path and INIT-without-path
  likewise. Production + seed ⇒ path required, INIT refused.
- Startup tests cover production-missing, production-INIT,
  inside-home, and duplicate-of-signing refusals
  (ConsumptionAnchorStartupTests) — all green.
- Consumption-journal-only rollback (signing ledger intact)
  also refuses at startup: covered by
  `test_consumption_journal_only_rollback_refused`.

### (e) Oracle narrowing — landed as specified
- Consume-mode docstring (`trust/verifier_main.py:2663-2685`):
  the single code `ceremony_authorisation_invalid` covers
  verification-failure classes only, with byte-identical
  output; temporal failure (`ceremony_authorisation_expired`)
  is declared by design to certify an envelope valid in every
  non-temporal respect; post-verification state refusals
  (`ceremony_already_consumed`, `ceremony_not_issued`,
  `ceremony_head_regression`) and `ledger_failed` (same code
  on both sides of the commit point) are declared outside the
  claim.
- `trust/ledger.py:54-65` (`AlreadyConsumedError`): carries
  B's sentence — "These distinctions are state oracles by
  design…; the no-oracle claim covers verification failures
  only." A grep for remaining unqualified "no forger oracle"
  phrasing across trust/ and signing/ found only the two
  reconciled sites.

## Tests run by this seat
`python3 -m unittest tests.test_trust_ceremony_journal_anchor
tests.test_trust_ceremony_consumption tests.test_trust_wiring
tests.test_trust_production_deploy` → **90 tests, OK
(skipped=12)**, ~76s. Plus the /tmp mutation run above
(mandatory test FAILED under reverted order, as required).

## Bottom line
WS2's mechanism closes the Gemini resurrection defect for every
burn whose anchor update completed, the mandatory test truly
pins the ordering, and the residual window is honestly bounded
in the operative docstrings and tests. FIX is solely for F1:
rewrite the two stale R10 passages so the repository does not
simultaneously claim and disclaim the anchoring — a one-pass
docstring change, no code or test changes needed.
