# Cycle 22 — Review R1 (WS1 focus: `burned_unadopted` honest recovery)

Reviewer seat: rev-r1 (blind). Tree: uncommitted changes on aeb6ef6.
Scope read: DESIGN-FINAL.md (R1–R4), CROSS-CHECK-15.md,
design-a.md §4.4.5/§6.2 (race/iteration spec referenced by R1),
signing/pin_ceremony.py, signing/ceremony_authorisation.py,
trust/ledger.py, trust/verifier_main.py (authorise 5b, consume),
tests/test_signing_ceremony_recovery.py,
tests/test_trust_ceremony_consumption.py.

## Verdict: SHIP — score 0.88

## Findings

### F1 (Minor — test-coverage gap vs contract wording): the two-recoveries race outcome is specified and behaves as specified, but is NOT test-pinned in-tree

DESIGN-FINAL R1 states the race outcome (design-a §4.4.5) "is
specified and test-pinned, not discovered." I searched all test
files: the pinned recovery cases are the happy paths (with-pin /
no-pin), forgery refusals, the iterated chain
(`test_recovery_chain_second_recovery_succeeds`,
tests/test_trust_ceremony_consumption.py:372 — authorise happens
AFTER the previous burn, so it is the §6.2 chain, not the race),
and same-envelope double-consume
(`test_recovery_envelope_consumed_twice_refused`, ibid:396).
No test authorises TWO recoveries against one head burn and then
consumes both.

I verified the actual behaviour with a scratch script
(/tmp/r1_adversarial.py, ledger level, real signed envelopes):
both race recoveries LAND, exactly as §4.4.5 specifies (the
second faces head = first recovery's entry; target + old-pin
still match, so the predicate passes). The outcome is bounded
as designed — identical pin value, two distinct fully-issued
authorisations, both journaled — so this is not a safety
defect. But because the pin is missing, a future change to
`match_head_burn`/`check_head` could silently flip the race
semantics (e.g. to second-refused) with the whole suite green.
Recommend adding the pin test; does not block ship.

### F2 (Info — verified, no defect): original burn permanence and relabel resistance

Scratch evidence (/tmp/r1_adversarial.py, steps 1–8):
- Original envelope re-consume after its burn: AlreadyConsumed.
- Still AlreadyConsumed AFTER two recovery consumptions land —
  recovery appends new entries; nothing un-burns or rewrites
  the original entry. No removal/un-burn API exists in
  trust/ledger.py; `append_consumption` re-checks
  authorisation_id over the full journal on every retry attempt
  (trust/ledger.py, append_consumption loop).
- Relabel bypasses refused: a fresh `chain_gap_recovery`
  envelope for the consumed target → AlreadyConsumed; a
  `lost_pin` no-pin envelope for the same target →
  AlreadyConsumed. The scoped exception in `check_head` is
  gated on `reason == "burned_unadopted"` AND
  `match_head_burn(...) is not None` (trust/ledger.py,
  check_head) — no other reason can ride it.

### F3 (Info — verified, no defect): burn proof is against the recorded journal, head-only, exact — not caller assertion

- Authorise step (5b) (trust/verifier_main.py:2514–2545) reads
  a freshly constructed `CeremonyConsumptionLedger` (hash-chain
  validated on load), calls `match_head_burn` on its entries,
  and refuses with the single exit-3 code
  `ceremony_recovery_unproven` for every predicate failure —
  including the self-recovery case
  `burn["ceremony_id"] == ceremony_id`. Unreadable journal →
  `ledger_failed`, never a partial scan. It runs ONLY for
  `reason == burned_unadopted`, after anti-replay (5), before
  signing (6): ordinary issuance gains no new failure
  dependency, per R1.
- `match_head_burn` (trust/ledger.py) inspects `entries[-1]`
  only, requires exact (seq, hash) equality on the candidate
  target AND exact old-pin equality, with the no-pin shape
  encoded as seq=None/hash="" — a target-only match with a
  wrong/absent old pin returns None (unit-pinned in
  tests/test_signing_ceremony_recovery.py, MatchHeadBurnTests,
  incl. the non-head-match case).
- New-ceremony discipline (b) is enforced compositionally:
  anti-replay at authorise step (5) refuses reused ceremony_id
  and reused evidence_hash, so a recovery is necessarily a new
  ceremony_id with new evidence; 5b additionally refuses the
  burned ceremony's own id.
- In `check_head`, the old-pin generic rule is REPLACED, not
  waived, for the recovery case: the `if not recovery` guard
  skips the generic rule only when `match_head_burn`'s exact
  equality already held (stricter than the generic rule, which
  permits old pins ahead of the head).
- TOCTOU is fail-closed (scratch steps 9–11): if an ordinary
  ahead ceremony moves the head between a recovery's authorise
  and consume, the stale recovery refuses HeadRegression at
  consume; `match_head_burn` against the moved head is None.

### F4 (Info — verified, no defect): reason-grammar extension does not weaken issuance-side validation

Ternary coherence is present in all four contract sites:
payload projection (signing/ceremony_authorisation.py,
`ceremony_authorisation_payload`: no-pin requires
_NO_PIN|_EITHER, with-pin requires
{chain_gap_recovery}|_EITHER, plus the unchanged gap-only
seq ≥ old+2 and evidence non-equality rules); authorise cheap
validation (trust/verifier_main.py:2428–2437, importing the
mirrored sets from ceremony_authorisation rather than keeping
a third copy); `reanchor_pin` (signing/pin_ceremony.py: with-pin
gate admits only chain_gap_recovery/burned_unadopted, with-pin
burned_unadopted additionally requires the strict
`("chain_gap",)` recomputation exactly as chain_gap_recovery,
no-pin case gets none); `verify_ceremony_record`
(ternary invalid_reason checks in both pin shapes).
`_NO_PIN_REASONS` is unchanged in both mirrored modules and
`_EITHER_PIN_REASONS == {burned_unadopted}` in both; drift is
pinned by VocabularyTests (tests/test_signing_ceremony_recovery.py)
and the authorisation drift tests. Existing-reason coherence
regressions are pinned in ProjectionTests
(`test_existing_reasons_coherence_regression`).

### F5 (Info — scope note, not a defect): ledger-level direct callers bypass 5b, as documented

`CeremonyConsumptionLedger.append_consumption` on an empty
journal would accept a seed-signed recovery envelope for a
never-burned target (check_head returns early on empty
entries). This is unreachable in the integrated system:
issuance requires authorise 5b (refuses with no head burn),
and consume mode requires issuance presence
(`ceremony_not_issued`, trust/verifier_main.py step (6))
before the head check. This matches the module's documented
scope-note pattern (mode-level checks are the mode's
responsibility). No action.

## Tests run

- `tests.test_signing_ceremony_recovery`,
  `tests.test_trust_ceremony_consumption`,
  `tests.test_signing_ceremony_authorisation`: 94 tests, OK
  (54.9s).
- Adversarial scratch /tmp/r1_adversarial.py (not committed):
  12 steps, all outcomes as specified — permanence, relabel
  refusal, race-both-land (§4.4.5), TOCTOU head-move refusal.

## Headlines

- F1 Minor: two-recoveries race behaves per §4.4.5 (both land, bounded) but has no test pin despite R1's "test-pinned" wording.
- All (a)–(d) safety checks pass under adversarial testing: burn is permanent, recovery is a genuinely new ceremony proven against the recorded head burn with exact target+old-pin equality, and the ternary grammar extension weakens nothing.
