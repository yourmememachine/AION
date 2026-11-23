# Cycle 25 — Review, seat rev-r4
## Scope: DEPLOYMENT/ALLOWLIST wiring + regression/restoration evidence
Files in scope: `deploy/verifier-identity/*`, `trust/wiring.py`,
`tests/cycle23_harness.py`,
`tests/test_rereview_restoration_regressions.py`,
`tests/test_trust_ceremony_supersede.py`.
Blind verdict filed first in `blind-r4.md` (0.82 / SHIP) before
reading any other seat's cycle-25 output (none existed in
`internal/cycle25-work/` at that time). This review confirms it
by execution. Reviewed against seat-gpt's five criteria in
`internal/CROSS-CHECK-18.md`.

## Tests run by this seat (all green)
- `test_verifier_deploy`, `test_trust_wiring`,
  `test_trust_production_deploy`,
  `test_trust_supersession_approval` — 106 tests, OK (skipped=12).
- `test_trust_ceremony_supersede`, `test_trust_supersede_adopter`,
  `test_rereview_restoration_regressions` — 78 tests, OK.
- `test_trust_pin_adoption_crash`, `test_trust_health_check`,
  `test_cycle23_live_run`, `test_trust_ceremony_consume` —
  63 tests, OK (skipped=12).
- `test_trust_ceremony_journal_anchor`,
  `test_trust_production_e2e` — 15 tests, OK.
Total in-scope/adjacent: 262 tests run, 0 failures.

## Probe 1 — Allowlist 19→20, every §4.3 site (PASS)
Design `design-approval.md` §4.3 enumerates 7 sites; each was
verified in the tree, not taken on trust:
1. `deploy/verifier-identity/run-verifier.sh` — `ALLOWED_KEYS`
   gains `AION_SUPERSESSION_APPROVER_PUBLIC_KEY` as the 20th
   entry (counted manually: 20).
2. `deploy/verifier-identity/health_check.py` — literal copy
   gains the same entry (counted: 20); pinned equal to the
   wrapper by `test_verifier_deploy` (len updated 19→20).
3. `trust/wiring.py` — `ALLOWED_ENV_KEYS` gains the name; BOTH
   docstring "19 names" mentions updated to 20. `trust/runner.py`
   imports the set (no literal copy) — correct per design note.
4. `trust/verifier_main.py` — module docstring env list, new
   `_Config.supersession_approver_key` field, and `_load_config`
   per §4.2: present-but-not-hex64 → `verifier_misconfigured`
   in both modes; production + ceremony seed + absent →
   `verifier_misconfigured`; research + absent → `None`
   (per-request `ceremony_supersede_approval_unconfigured`);
   approver pubkey == ceremony pubkey → startup refusal.
5. `deploy/verifier-identity/setup.sh` — template writes
   `AION_SUPERSESSION_APPROVER_PUBLIC_KEY=` with provisioning
   comments. Note: it writes the empty template slot for the
   operator to fill from the tool's `public-key` output rather
   than generating a key itself — this matches the established
   deploy pattern for the ceremony seed ("never generated
   silently by setup.sh") and §4.3 item 7's template-equality
   test (`test_template_keys_equal_allowlist`) passes, so this
   is consistent, not a miss.
6. `deploy/verifier-identity/README.md` — new "Supersession
   approval (cycle 25)" section documenting the var, the
   19→20 move, and the §1 honesty claim (event-level
   independence only, no separate-human upgrade).
7. Tests/fixtures — `test_trust_wiring.py` (len 19→20 in both
   the wiring pin and the wrapper set-equality pin),
   `test_verifier_deploy.py` (health-copy len 20),
   `test_trust_production_deploy.py` (production fixture gains
   a fixed hex64 approver pin distinct from the ceremony key),
   `tests/cycle23_harness.py` (provisions a real approver key
   via the tool's `generate_approver_key_file`, puts only the
   PUBLIC hex in the production env, exposes
   `approver_key`/`approver_pub` on `ProductionHome`).
No stale "19" allowlist counts remain in `trust/`, `deploy/`
or `tests/` (grep sweep; remaining hits are the historical
"19 → 20" note in the deploy README and unrelated text).
Cross-check by footprint: every non-historical file naming
`AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` (the previous var's
footprint) either also names the new var or is a research-mode
/ direct-subprocess fixture that does not copy the allowlist
(`test_trust_ceremony_journal_anchor.py`,
`test_trust_production_e2e.py` — the latter goes through the
harness, which now carries the var; both suites pass).

## Probe 2 — Approver SEED path is never a verifier variable (PASS)
- `AION_SUPERSESSION_APPROVER_SEED_PATH` is absent from:
  the wrapper `ALLOWED_KEYS`, `health_check.py`'s copy,
  `trust/wiring.py` (source and `ALLOWED_ENV_KEYS`),
  `trust/verifier_main.py`, `trust/pin_adoption.py`,
  `trust/client.py`, and all of `deploy/` (grep, exit 1).
  It exists only in `trust/supersession_approval_tool.py`
  (its own process env var) and in tests asserting its absence.
- Wiring refusal verified live by this seat:
  `production_client({"AION_SUPERSESSION_APPROVER_SEED_PATH": …})`
  raises `VerifierConfigError` — "not an allowlisted verifier
  variable; unknown keys are refused, not passed through".
- Deploy scan passes: `test_every_verifier_main_env_var_is_allowlisted`
  extracts every `AION_*` name in `verifier_main.py` and requires
  it ⊆ wrapper allowlist — it passes precisely because
  `verifier_main.py` never names the seed-path var (its comment
  says so explicitly), and `test_template_keys_equal_allowlist`
  pins setup.sh's template to exactly the 20 names.
- Wrapper semantics are in fact STRONGER than the design's
  "discards it" wording (§4.1): placed in the env FILE, a
  non-allowlisted key hard-fails the launch (exit 1); placed in
  the invoking shell, it is discarded by the `env -i` clean
  environment. Minor wording imprecision in the design doc;
  the code errs on the safe side. Non-blocking.

## Probe 3 — Restoration evidence, criterion (v) (PASS, one stale comment)
`test_06_restored_pin_store_recovers_only_via_supersede`
(genesis seq 1 → gap ceremony seq 3 → pin-store file restored
to pre-advance bytes while the consumption head stays at 3)
genuinely exercises the independently authorised route, with
no shortcut found:
- First seq-4 attempt raises `PinSupersessionPendingApproval`;
  asserted: candidate_seq 4, consumption count still 2,
  supersession decision journal EMPTY, pin still at restored
  seq 1. The adopter requests nothing.
- The approver act is real: the test reads the adopter's
  pending report, asserts its head `authorisation_id` is null
  (the honest case — the seq-3 movement was adopted, then the
  store rolled back, so the adopter cannot name the head),
  completes the WHOLE head block from the verifier's own
  consumption journal (authorisation_id, ceremony_id, old/new
  pair, seq, entry_hash), and signs with
  `build_approval_for_report` — the real approval tool's
  signing function under a dedicated approver key generated
  by the tool's `generate_approver_key_file`. No fabricated
  decision, no stubbed approval check, no direct journal writes.
- Completion is asserted end-to-end: outcome reanchored,
  pin seq 4, exactly ONE new consumption (seq-3 movement NOT
  re-consumed — exactly one entry targets seq 3), exactly one
  journaled supersession decision whose `new_authorisation_id`
  equals the landed consumption's and whose `approval_id`
  equals the presented artefact's `approval_id`. Store history
  is [1, 4] — the lost seq-3 record is not fabricated back.
- Crash-suite scenario 6 (`test_scenario6_recovery_chain_cap2_then_terminal`
  in `test_trust_pin_adoption_crash.py`) is re-pointed the same
  way: first attempt stops at `PinSupersessionPendingApproval`
  with the decision journal asserted empty; report head
  completed from the verifier journal (authorisation_id
  asserted equal, seq/entry_hash filled); tool-signed approval
  dropped in the inbox; completion lands seq 11 and the single
  decision's `approval_id` is asserted equal to the signed
  approval's. It no longer rides the cycle-24 auto-request.
- MINOR (non-blocking): the restoration module docstring still
  says leg 4 builds its client directly "because seat B's
  wiring-allowlist/harness updates … are theirs to land".
  Those updates HAVE landed (Probe 1, sites 3 and 7), so the
  rationale is stale, and leg 4 still constructs a raw
  `VerifierClient` instead of `production_client` — the route
  itself is genuine (real verifier subprocess, real tool
  signature), but leg 4 therefore does not exercise the wiring
  validation layer. Recommend a follow-up comment correction
  (and optionally switching leg 4 to `production_client`);
  not a criterion-(v) failure.

## Probe 4 — Criterion (iv): ordinary recovery cannot self-escalate (PASS)
The regression evidence covers each required refusal, and all
of it ran green under this seat:
- Adopter-only flow reaches pending and NO further:
  `test_trust_supersede_adopter.test_deadlock_stops_at_pending_without_approval`
  uses a counting client — supersede_calls == 0, exactly one
  consume attempt, no decision journaled, pin unmoved; a second
  approval-less attempt does not even re-authorise/consume.
  Restoration test_06 and crash scenario 6 assert the same stop.
- No-approval / auto-request shape refuses:
  `test_no_approval_auto_request_refuses` (null and absent
  approval both `malformed_request`, nothing journaled);
  unconfigured approver key refuses
  `ceremony_supersede_approval_unconfigured`.
- Forged / self-minted artefacts refuse: wrong approver key →
  `ceremony_supersede_approval_invalid`; approval SELF-SIGNED
  WITH THE CEREMONY SEED → invalid; approval signed with the
  SNAPSHOT signing key → invalid (both are genuine Ed25519
  signatures under the wrong key — the approver pin is what
  refuses them). Expired approval → dedicated expired code.
- Wrong binding refuses as `ceremony_supersede_unproven`:
  approval bound to another candidate, to another failed
  attempt (stale head seq/hash), and to another abandoned
  movement (fabricated head) each refuse with nothing journaled;
  adopter-side, a tampered inbox artefact is never even
  presented (`test_wrong_binding_approval_never_presented`,
  supersede_calls == 0).
- Reuse refuses: `test_approval_reuse_refuses` — one approval
  mints exactly one decision; replay for the same envelope and
  for a different envelope both refuse; ledger load also
  rejects duplicate `approval_id`
  (`test_load_rejects_duplicate_approval_id`).
- Ordinary recovery cannot acquire a decision:
  `test_recovery_envelope_cannot_acquire_decision` — a
  `burned_unadopted` envelope presented with a genuinely signed
  approval (bound to a primary) still refuses unproven; the
  shape predicate excludes the recovery before binding is
  consulted, and an approval bound to a recovery envelope is
  un-mintable at the tool/projection surface.

## Criteria summary (seat-gpt, CROSS-CHECK-18)
(i) Independent authorisation event binding abandoned head +
replacement candidate + exact movement + original failed
attempt — evidenced in-scope by test_06 / scenario 6 completing
head facts from the verifier journal and the decision recording
the approval id. (ii) Approval verified BEFORE the decision
issues and recorded in it — asserted via `approval_id` in the
single journaled decision in all three end-to-end tests.
(iii) Verifier refuses adopter auto-requests — Probe 4,
no-approval and counting-client tests. (iv) PASS — Probe 4.
(v) PASS — Probe 3. Gemini's relabelling condition is outside
this seat's file scope except where it touches deploy docs:
the deploy README and setup.sh comments use "approval"
throughout and carry the event-level-only claim without
upgrade ("independent approver" / "four-eyes" wording absent).

## Findings
- F1 (minor, non-blocking): stale rationale comment in
  `tests/test_rereview_restoration_regressions.py` (module
  docstring + leg-4 setUp) claiming seat B's §4.3 updates have
  not landed; they have. Leg 4's direct `VerifierClient`
  construction is now a choice, not a necessity, and bypasses
  wiring validation. Fix the comment in a follow-up.
- F2 (minor, non-blocking): design §4.1 says the wrapper
  "discards" the seed-path var if placed in the verifier env
  file; the wrapper actually refuses the launch for any
  non-allowlisted env-file key (shell-env occurrence is the
  discarded case). Code is stricter than the doc; doc wording
  only.
- No missed or inconsistent §4.3 site found. No shortcut in
  the restoration evidence found.

**Final verdict: SHIP — score 0.88.** Deployment/allowlist
wiring is complete and consistent at 20 across every §4.3
site, the approver seed path is structurally excluded from
the verifier and refused by wiring, and the restoration +
regression evidence genuinely proves criteria (iv) and (v).
The two minor findings are documentation drift, not blockers.
