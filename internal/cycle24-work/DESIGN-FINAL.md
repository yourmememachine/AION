# Cycle 24 Part 1 — DESIGN-FINAL (coordinator rulings)

Date: 2026-11-23. Inputs: design-a.md (items 1+2),
design-b.md (item 3), design-c.md (item 4), CROSS-CHECK-17.
Three coder seats designed together; the rulings below are
the build contract. Baseline: 1620 tests OK (skipped=28).

## R1 — Item 2: ceremony public key MANDATORY in production_client (design A adopted)

- `production_client(verifier_env, *, expected_signer_id,
  expected_key_id, authorisation_public_key, launch=...)`:
  the key parameter loses its default; omission is a
  TypeError. `None` refuses with VerifierConfigError (its own
  branch, after the signer/key pin checks so refusal
  precedence is unchanged); a non-CeremonyPublicKey (including
  CeremonySigningKey) refuses with VerifierConfigError.
- trust/client.py is NOT changed: VerifierClient's own None
  default stays for direct/research constructions; the local
  ceremony refusals remain as defence in depth, unreachable
  via production_client.
- Wiring docstrings rewritten (the "Optional at THIS factory"
  rationale is deleted; the third pin is documented as
  mandatory); deploy/verifier-identity/README.md's stale
  pin warning corrected. Historical internal/ records are
  not edited.
- Only production caller (build_pin_adopter) already passes
  the key. tests/test_trust_wiring.py gains a module-level
  CEREMONY_PUB fixture (derived via _make_ceremony_signing_key
  over a fixed digest + ceremony_public_key_for, per design A)
  and every production_client call in that file passes it.

## R2 — Item 1: production entry point trust/runner.py (design A adopted)

- New module trust/runner.py; `python3 -m trust.runner`
  with NO argv (any argv is a config refusal, exit 2).
  Configuration from the environment only, validated in full
  before any construction; refusals name the variable, never
  its value.
- Verifier env = the os.environ subset restricted to
  wiring.ALLOWED_ENV_KEYS (imported, not copied). Adopter
  vars via pin_adopter_config_from_env. Runner vars:
  AION_RUNNER_STATE_DIR, AION_RUNNER_PLAN_PATH,
  AION_RUNNER_EXPECTED_SIGNER_ID, AION_RUNNER_EXPECTED_KEY_ID,
  AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX (exactly 64 lowercase
  hex chars → 32 bytes → CeremonyPublicKey with the DERIVED
  key id; a supplied id is never trusted).
- Construction order: runner env → whole-plan validation →
  state-layout existence pre-check (state.json AND
  calibration/calibration.json must exist — this blocks
  CoreLoop's silent fresh-state bootstrap) →
  build_pin_adopter (the only adopter construction) →
  exactly CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter)).
  No VerifierClient / MemoryStore / PinStore constructions
  in the runner. Exactly one run_one_cycle call site; the
  trust lint gains the single allowlist entry
  ("trust/runner.py", "run_one_cycle"): 1.
- Plan: {"steps": [{"adopt": true} | {"cycle": {coders,
  reviewers, verdict, verify_passed, delta}}]}, strict schema
  validated up front; semantic gates are CoreLoop's, not
  duplicated. One sorted-JSON summary line per step on
  stdout; diagnostics on stderr only. Exit codes: 0 ok;
  2 config refusal; 3 adoption refused; 4 adoption burned;
  5 cycle recorded, pin pending (hook failure on a cycle
  step; cycle_id surfaced from exc.cycle_entry); 6 step
  refused (loop/semantic refusal before recording);
  1 unexpected.
- Demonstration: tests/test_trust_runner.py drives the
  module as a subprocess against a byte copy of the real
  state/ + the cycle-23 harness production home:
  invocation 1 [adopt, cycle] = genesis initial_anchor @13
  then hooked cycle advancing the pin to 14 (exactly 1
  consumption); two hookless cycles test-side open the gap;
  invocation 2 [adopt, adopt] = chain_gap_recovery ceremony
  to 16 then already_current. Asserts the real
  state/state.json sha256 is unchanged and exactly 2
  consumptions total. Plus design A's five negative tests.
- Honesty qualifier (in the module docstring and the build
  record): this is a production entry point for production
  MODE under same-user spawn; it is not deployment evidence
  (no separate OS user on this machine).

## R3 — Item 3: Supersede Option A (design B adopted in full)

- New verifier mode `ceremony_supersede`
  (trust/verifier_main.py), body exactly {"operator_id",
  "signed_authorisation"}. The verifier identifies the
  abandoned movement from its OWN consumption head; the
  request names no abandoned-movement field. Validation
  order mirrors authorise/consume (design B §3): config
  gates (operators + seed; evidence NOT gated) → strict
  keys → cheap validation → operator membership → envelope
  verification (expected_operator_id folded into the single
  ceremony_authorisation_invalid code; temporal carve-out
  preserved) → already-consumed → issuance presence →
  supersede-shape gate → journal commit → signing-ledger
  mirror. Every shape failure (including a prior decision
  for the same envelope) collapses to the single new code
  `ceremony_supersede_unproven` — no shape oracle, no
  gratuitous decisions.
- Shared predicate
  `CeremonyConsumptionLedger.supersede_head(entries, signed)`
  used by BOTH the mode and check_head so they cannot drift.
  Inside check_head the hash-binding check precedes the
  decision check: a fabricated journal-known old-pin hash
  still raises HeadRegressionError, never supersede-required.
- New journal `CeremonySupersessionLedger`
  (trust/ledger.py, file ceremony-supersessions.json in the
  verifier home): entries bind abandoned authorisation_id +
  abandoned (old,new) pair + new authorisation_id +
  candidate (seq, hash) + the superseding envelope's old pin
  + operator_id (design B §4 field list). append_decision
  reload-rechecks single-decision-per-envelope;
  per-abandoned uniqueness is deliberately NOT enforced
  (expiry case, design B). Load-time coherence per design B.
- Signing-ledger mirror: YES — SigningLedger gains
  append_ceremony_supersession (kind "supersede", format
  "ceremony-supersession", existing entry shape), written
  after the journal commit; mirror failure is ledger_failed
  and the decision stands (recovery is a new envelope).
  Dedicated anchor: NO — the journal joins the
  ceremony-journal-anchoring follow-up (see R4); the
  rollback position is stated in the ledger docstring
  exactly as design B §4 argues it.
- Consume side: new `SupersedeRequiredError(LedgerError)`
  (NOT a HeadRegressionError subclass).
  check_head(entries, signed, recovery_of=None, *,
  supersede_decision=None) and append_consumption(...,
  supersede_decision=None): in the supersede branch, a
  missing decision raises SupersedeRequiredError; a present
  decision is binding-checked against the CURRENT head
  inside append_consumption's retry loop (abandoned id ==
  head entry's authorisation_id; new authorisation_id ==
  signed.authorisation_id; candidate seq/hash equal;
  abandoned pair == head pair; superseding old pin equal) —
  any mismatch raises HeadRegressionError. The consume mode
  gains step (6b): it looks the decision up from its own
  supersession journal keyed by the presented envelope's
  authorisation_id (the caller never supplies it — the
  recovery_of threading precedent) and threads it into both
  the step-(7) check_head call and append_consumption;
  SupersedeRequiredError maps to the new exit-3 code
  `ceremony_supersede_required`, documented as a
  post-verification state refusal (the existing oracle
  class), emitted ONLY pre-commit after the already-consumed
  check has certified the envelope unconsumed.
- Client: _run records the verifier's error code on the
  raised exception as `.verifier_code` (structured
  attribute; string matching on messages is forbidden).
  ceremony_consumer translates code ceremony_supersede_required
  into the new `CeremonySupersedeRequired(SigningError)`
  carrying `.envelope_dict`; reanchor_pin does not catch it
  (it propagates as the consumer's SigningError — verify and
  pin this). VerifierClient.ceremony_supersede(operator_id,
  envelope_dict) with full echo validation; no public-key
  pin is needed (nothing signed is returned).
- PinAdopter._reanchor: the reanchor_pin call is factored
  into an _attempt() closure. On CeremonySupersedeRequired:
  exactly ONE ceremony_supersede request (operator from
  config, the carried envelope_dict) and exactly ONE re-run
  of _attempt() with the same envelope; a "supersede_decided"
  line joins the pending-journal phases (it is NOT a burn
  phase). Any failure in the decision request or the re-run
  surfaces as PinAdoptionBurned, as every post-authorise
  failure does today. Design B §7.1's not-a-retry argument
  (the code is emitted only pre-commit, after unconsumed
  certification; the envelope is provably unburned) is
  documented at the flow, in the consumer docstring, and in
  the decision record (Addendum 4).
- Sentinel narrowing (seat-gpt's secondary condition): the
  consume mode converts a v1 issuance entry's absent
  recovery_of (None) to "" before threading, so the
  bind-to-head sentinel is unreachable through the verifier;
  the ledger API keeps None for direct in-process callers.
  The scoping sentence for the decision record is design B
  §8's verbatim wording: the cap-2 lineage guarantee is a
  property of the integrated verifier path, not of the
  ledger API for arbitrary in-process callers.
- Cycle-23 supersede tests are re-pinned per design B §9's
  inventory (decision journaled first, via the ledger or the
  mode as each test's layer requires); outcomes that design B
  marks unchanged stay unchanged.

## R4 — Item 4: issuance-journal anchoring DEFERRED (design C fit assessment adopted)

Item 4 is NOT built this cycle. It is recorded as the
explicit remaining follow-up `ceremony-journal-anchoring`,
whose scope now covers BOTH the issuance journal
(ceremony-authorisations.json) AND the new supersession
journal (ceremony-supersessions.json). Reasoning (design C
§1 + §9, adopted): the claim-check shows a rolled-back
issuance journal bricks the original envelope
(ceremony_not_issued) and cannot double-consume a movement
(the anchored consumption journal and head rules still
refuse); the residual harm needs an active re-presentation
by a listed operator against a different movement, and is
partially detectable today. Against that, the build
collides with items 2-3 on shared surfaces (allowlist count
pins in wiring/deploy/tests, the _load_config verifier-wide
blast radius) in the same cycle that gates the cycles 14-16
re-review, and CROSS-CHECK-17's convergent scope does not
include it. Design C is complete and buildable as written
(anchor kind "ceremony-authorisation", env pair, allowlist
19→21 with its full copy inventory, authorise commit order
(8)→(9)→(10)→(11)) — it is the first item of the next
trust cycle. The verifier_main docstring's follow-up note
is updated to name both journals.

## File ownership (build seats, disjoint)

- Seat 1 (item 2): trust/wiring.py,
  tests/test_trust_wiring.py,
  deploy/verifier-identity/README.md.
- Seat 2 (item 1): trust/runner.py (new),
  tests/test_trust_runner.py (new), tests/test_trust_lint.py.
- Seat 3 (item 3 core): trust/ledger.py,
  trust/verifier_main.py, tests/test_trust_ceremony_supersede.py
  (new), re-pins in tests/test_trust_consumption_schema_v2.py
  and tests/test_trust_ceremony_consume.py.
- Seat 4 (item 3 client/adopter + R4 docstring note is seat
  3's file — seat 3 does it): trust/client.py,
  trust/pin_adoption.py, signing/pin_ceremony.py (only if
  propagation needs a change; otherwise docstring),
  tests/test_trust_supersede_adopter.py (new), re-pins in
  tests/test_signing_pin_ceremony.py,
  tests/test_signing_ceremony_recovery.py,
  tests/test_trust_pin_adoption_crash.py.

Every seat runs its own test files plus the full suite
before reporting. Nothing ships on a split; the war room
follows the build.

---

## Adjudication note (added during the part-1 war room, rev-r6 §7)

R3 as written did not name the supersede RECEIPT key set returned by
the `ceremony_supersede` mode and validated by the client. Both build
seats independently converged on design-b §2's set, and that set is
the canonical one, pinned here by adjudication:

    {"abandoned_authorisation_id", "new_authorisation_id",
     "candidate_cycle_seq", "candidate_payload_hash",
     "supersession_seq"}

An earlier draft spelling (`supersede_seq` / `new_cycle_seq` /
`new_payload_hash`) appeared in coordinator seat briefs only and was
NOT implemented anywhere. The receipt validation on the client is an
exact-set check against the set above.
