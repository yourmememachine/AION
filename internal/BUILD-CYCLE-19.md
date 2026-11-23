# BUILD — Cycle 19: Protected Gate scope extension + protected pin-ceremony authority

Mandate: internal/DECISION-PROTECTED-GATE-EXTENSION.md
(2026-11-22) — Dilip delegated the Protected Gate decision
("do whatever is the best decision"); decision taken: EXTEND.
The gate's judgement dependencies enter its protected scope;
the pin ceremony's operator authority and evidence provenance
are sourced from a protected store instead of the same caller.
Design record: internal/cycle19-work/ (design-a/b/c,
critique-a/b/c, DESIGN-FINAL.md — three coder seats designing
together, cross-critiqued, coordinator rulings on the five
disputes). War room: REVIEW-CYCLE-19.md. Verdict: **SHIP
(internal, unanimous after the fix round) — PROVISIONAL** on
the external seats (brief:
internal/CROSS-CHECK-BRIEF-CYCLE-19.md). Item A (cycle 13)
ships WITH this cycle; its closure condition is met with the
qualification stated under F5 below. Cycles 14–16 were NOT
re-reviewed and remain HELD; their re-review is a later step
that may now proceed on the extended gate.

Baseline (coordinator-verified at run start): full suite 1245
tests, OK (skipped=26). Item A verified intact before building
(gate canonicalisation, P-1/P-2 duplicate-key hooks in
eval/registry.py + eval/calibration.py, negative-integration
suite).

## Staffing

3 coder seats building together (design round + cross-critique
round + implementation round, one seat per part, disjoint file
ownership): seat A gate closure, seat B verifier authority,
seat C ceremony integration. War room: 6 reviewer seats that
did not build (rev-r1 scope fidelity, rev-r2 gate closure,
rev-r3 verifier mode, rev-r4 ceremony integration, rev-r5
consistency/wording, rev-r6 forced dissent), blind scores
locked in state/calibration/calibration.json BEFORE
reconciliation (subject `cycle-19-gate-extension`; fix-round
re-reviews under `cycle-19-fixround`). External seats
(seat-gpt, seat-gemini) are NOT part of this record: the
verdict is PROVISIONAL until they review the brief.

## Part A — Gate scope extension (the authorised protected change)

- `eval/gate.py`: the ONLY eval/ change. `PROTECTED_FILES` is
  now `("core/loop.py", "oversight/__init__.py",
  "oversight/approval.py", "trust/__init__.py",
  "trust/pathpolicy.py")`; `PROTECTED_PREFIXES` unchanged. The
  constants comment names why each new file is protected and
  states the closure is the verdict-defining chain, not an
  unqualified dependency closure. No logic change.
- `docs/GATE-CLOSURE.md` (NEW): the layered dependency-closure
  analysis — L0 verdict logic, L1 canonicaliser chain (verified
  to terminate in stdlib + eval.gate), L2 import-path package
  `__init__` files, L3 modules executed via `trust/__init__`
  re-exports including the `sys.modules["trust.pathpolicy"]`
  pre-seeding vector (reproduced live by rev-r2).
- `trust/pathpolicy.py`: mirror `GATE_PROTECTED_FILES` updated
  in the same change (drift tests enforce lockstep); the first
  gate/oversight overlap (`oversight/approval.py` →
  `["gate", "oversight"]`) is reported by classify(), not
  hidden.
- Negative tests (the external seats' cycle-13 requirement),
  `GateClosureNegativeTests` in
  tests/test_protected_gate_adoption.py: N1 — each of the four
  new files is flagged by the gate itself and refused
  end-to-end through evaluate_self_change, including
  non-canonical spellings reported in canonical form; N2 —
  two-step: a canonicaliser-only change is refused at step 1,
  and former gate-miss spellings still refuse at step 2
  against the unmodified canonicaliser. Mutation-verified by
  rev-r2: on the pre-extension list these tests fail (6 tests,
  13 subtests).
- In-step updates: pathpolicy + differential suites (corpus
  66 → 71 rows; gate-miss and gate-stricter remain pinned
  EMPTY), test_gate additive cases + the negative control
  (`trust/manifest.py` stays UNPROTECTED — no prefix creep),
  canary docstring (it delegates; it does not mirror),
  docs/PROVENANCE.md's quoted list, and the oversight flip
  pinned (`is_protected_path("trust/pathpolicy.py")` is now
  True).

## Part B — Protected operator authority + evidence provenance

- `signing/ceremony_authorisation.py` (NEW): a verifier-issued
  authorisation envelope (domain
  `signed-ceremony-authorisation-v1`, purpose
  `pin-ceremony-authorisation`) binding operator_id,
  ceremony_id, reason, old pin {cycle_seq, payload_hash}|null,
  candidate {cycle_seq, payload_hash, signer_id, key_id},
  evidence_hash and evidence_ref under the verifier's key.
  Payload projection enforces the reason allowlist (a local
  mirror of pin_ceremony.REASONS — importing pin_ceremony
  would cycle; a drift test pins the mirror), reason/pin
  coherence, the gap-only sequence relation, and evidence
  non-equality vs both pin hashes. TTL: 900s default AND hard
  cap. Signer != operator, stated: the verifier signs ABOUT
  the operator's presentation.
- Verifier config: `AION_CEREMONY_OPERATORS` (comma-separated
  operator ids) is parsed ONLY from the environment in
  _load_config. Malformed values refuse startup in both modes;
  production mode + absent/empty refuses startup
  (fail-closed, mirroring the anchor rule); research mode +
  absent loads an empty list and the mode refuses per-request.
  The allowlist step (14 → 15 names) landed in all four live
  copies (run-verifier.sh, trust/wiring.py,
  health_check.py, setup.sh template) with count/set pins —
  including, after the fix round, the setup.sh template in
  the completeness direction. NOT a wiring-required key.
- New verifier mode `ceremony_authorise` (also added to
  trust/protocol.py MODES): strict 7-key body; order is config
  gate → cheap validation (exit 2, no ledger touched) →
  operator membership (UNSIGNED, unledgered exit-3 refusal
  `ceremony_operator_not_authorised` — no signed-reject
  artefact exists for this mode) → anti-replay scan → sign →
  ledger-before-return. Single-use is enforced at issuance by
  a NEW sibling store, `CeremonyAuthorisationLedger`
  (HashChainJournal; own file in the verifier home — the
  SigningLedger's fixed entry shape cannot carry
  ceremony_id/evidence_hash), dual-appended with
  `SigningLedger.append_ceremony_authorisation` (existing
  entry shape unchanged). The ceremony-journal append is the
  commit point; a failure after it returns `ledger_failed`
  and the (ceremony_id, evidence_hash) pair stays burned —
  recovery is a new ceremony_id with a new evidence bundle
  (documented in the mode and module docstrings).
- Client: `VerifierClient.ceremony_authorise(...)` returns
  the envelope dict only, re-derives the payload hash and
  authorisation_id, checks signer/key pins and expiry, and
  verifies the full echo binding against the request.

## Part C — Ceremony integration (signing/pin_ceremony.py)

- `reanchor_pin`: the caller-supplied `authorised_operators`
  parameter is REMOVED — there is no fallback path. New
  required parameters: `authorisation` (a
  SignedCeremonyAuthorisation object; a raw dict is refused),
  `authorisation_key`, `expected_verifier_signer_id`.
  Verification order: type checks → key-separation refusal
  (authorisation key id == snapshot signing key id ⇒ refusal,
  BEFORE envelope verification) → envelope verification on
  the ceremony's single captured clock → EXACT binding
  equality against captured actuals (operator, reason, old
  pin, candidate 4-field projection, evidence hash), each
  mismatch its own refusal → the pre-existing evidence
  non-equality check still runs.
- `PinCeremonyRecord` gains REQUIRED `ceremony_id` +
  `authorisation_id` fields (no defaults — a record with no
  authorisation is unrepresentable), carried in `payload()`;
  `verify_ceremony_record` checks them under the shared
  reason `invalid_authorisation`.
- tests/test_signing_pin_ceremony.py converted through its
  single helper to mint in-process envelopes under a distinct
  verifier key; the E2E suite
  (tests/test_trust_ceremony_authorisation.py) drives the
  real verifier subprocess end-to-end.

## Claim scoping and open items (war-room required wording)

- **F5 scoping (rev-r6's wording, adopted):** authority
  relocated to the verifier; gate verdict chain L1+L2
  closed, L3 open. Item A ships with exactly that
  qualification. The L3 follow-up is `gate-import-isolation`
  (named, not built).
- **F4 — DECISION INTERPRETATION, FLAGGED FOR OWNER
  RATIFICATION (the cycle's one open item).** The decision
  record says the gate "will hold its own protected
  operator-authority list" sourced "from the extended gate's
  protected store". As built, the list lives in the
  VERIFIER's protected env config (AION_CEREMONY_OPERATORS),
  not inside eval/gate.py. The design record's reasoning:
  the gate must stay env-free (its header contract), and a
  list constant inside eval/gate.py would be presentable by
  any caller and unverifiable by the gate itself; the
  out-of-process verifier is the system's existing protected
  boundary (own key, own ledgers, config only from the
  launch channel), and the mandate's own brief directed
  wiring through the verifier infrastructure. Purpose
  satisfied (authority and evidence no longer come from the
  ceremony's caller); letter substituted (where the store
  lives). This needs the owner's explicit ratification; it
  is carried into the external brief, not buried.
- **F1 — consumption-side replay remains OPEN (dissent
  preserved).** The ledger burns at issuance, not
  consumption: the same envelope presented to reanchor_pin
  twice within its 900s TTL succeeds when ceremony_history
  is omitted (pinned by a test named for the limit). The
  narrowing the room accepted: the envelope binds exactly
  one event, so a second consumption can only re-derive the
  identical pin movement — it cannot authorise a different
  jump, candidate or operator; the true residual is
  re-anchoring against a since-moved pin state. Closing it
  needs a protected monotonic consumption head — an
  owner-level store-location decision — recorded as a
  follow-up alongside `ceremony-journal-anchoring`. Making
  ceremony_history merely non-optional would not close it
  (a supplied history proves authenticity of records, not
  completeness). rev-r6's standing condition: any future
  cycle claiming consumption single-use without that head
  re-triggers its FIX.
- **Deployment migration note (F6).** Production deployments
  must now set AION_CEREMONY_OPERATORS or the verifier
  refuses to start (fail-closed by design, ruling D4).
  setup.sh templates the variable (empty, with a comment);
  the pre-existing production fixture in
  tests/test_trust_production_deploy.py gained the variable
  for the same reason.
- **Detectability claims corrected (fix round).** The
  pre-fix wording ("audit-detectable after a rollback")
  overstated the anchored store: it stores neither
  evidence_hash nor operator_id. All four passages
  (signing/ceremony_authorisation.py, trust/ledger.py,
  trust/verifier_main.py, signing/pin_ceremony.py) now state
  the scoped truth — same-ceremony_id reuse leaves a trace;
  evidence reuse under a new ceremony_id is not detectable
  from the anchored store without the retained envelopes; a
  forged envelope is indistinguishable at consumption and
  discoverable only on audit against the issuance ledgers.
  (Precision note: "audit-detectable" now has zero hits in
  shipped code/docs; two hits remain in internal working
  papers — critique-b.md and DESIGN-FINAL.md — quoting the
  pre-fix claim.)
- **Deviations recorded, not hidden:** the signing-ledger
  entry's purpose literal is the envelope's own
  ("pin-ceremony-authorisation"), not design-b's
  "pin-ceremony" (rev-r5: acceptable, strictly more
  consistent); TTL above 900 clamps via min() instead of
  refusing (the DESIGN-FINAL contract; rev-r3 accepted);
  identical and differing re-presentations share the
  `ceremony_id_reused` refusal code (rev-r5: acceptable,
  diagnostic granularity only); rev-r3 minors recorded —
  operator_id grammar asymmetry between the mode and the
  config list (classification only; such an id can never be
  listed) and no reload-retry on the ceremony appends
  (fail-closed availability nit; follow-up class).

## Follow-ups named (recorded, NOT built)

`gate-import-isolation` (R-A: load the canonicaliser without
executing trust/__init__), `ceremony-journal-anchoring` (D5:
extend an external anchor to the ceremony journal), the
protected consumption head (F1), the consumption-side
ledger-presence check (M5). Backlog items closed by this
cycle for the parent's recording step:
`protected-list-reconciliation` and
`gate-path-canonicalisation` (Item A). Loop state was NOT
advanced and state.json was NOT edited (signed ship path
precedent); the only state/ change is the calibration log.

## Test totals

Full suite (coordinator runs): baseline **1245 OK
(skipped=26)** → after implementation **1318 OK
(skipped=26)** → after the fix round **1322 OK
(skipped=26)**. Net +77: gate/pathpolicy/differential
updates, adoption +6 (15 total), ceremony-authorisation unit
32, ceremony mode 15, pin ceremony 25 → 37, E2E 7, wiring /
deploy / production-deploy updates.

## Self-improvement delta

tests_passing 1245 → 1322 (evidence: coordinator full-suite
runs; verifiers rev-r1..rev-r6, non-builder reviewers).
Process lessons: (1) the dissent seat caught a detectability
overclaim repeated in FOUR docstrings — claim wording must be
checked against what the cited store actually stores, field
by field; (2) rev-r4's probe standard (read the actual
refusal messages, not the test names) exposed converted
tests passing for the wrong reason — and the fix round then
showed the masked checks are structurally unreachable behind
the envelope projection, which is now recorded in the tests
themselves; (3) two of the cycle's three cross-seat disputes
were settled by counting (one helper funnels 43 calls; one
constructor site) — grep evidence ended arguments that
position statements could not.
