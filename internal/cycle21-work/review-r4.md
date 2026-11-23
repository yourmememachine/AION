# War-room review — rev-r4 (ceremony integration), cycle 21 — BLIND

Scope: CROSS-CHECK-14 item (3); DESIGN-FINAL R5, R6, R7, R12;
`signing/pin_ceremony.py` (`reanchor_pin` as built),
`trust/client.py` (`ceremony_consume` + `ceremony_consumer`),
`tests/test_signing_pin_ceremony.py` (helper, Cycle20ConsumptionTests
as rewritten, Cycle21ConsumptionTests),
`tests/test_trust_ceremony_authorisation.py` (E2E helper),
`tests/test_trust_ceremony_consumption.py`. Cycle-20 comparison via
`git diff HEAD` (HEAD = cycle-20 commit bc83d0d; cycle 21 is the
uncommitted working tree). Full suite as handed to me: 1464 tests OK
(skipped=28), baseline 1406 — not re-run; this review is code/test
reading plus diff and grep.

## Verdict: SHIP — score 0.90

No BLOCKER and no HIGH finding in this scope. The integration is
structurally sound: one consumption call site, after every local
check, before record construction; T7′/T8′ are genuine flips of the
cycle-20 residual pins; the test helper's default consumer is a real
ledger-backed consumer; the client adapter is complete, including
echo-mismatch handling. Remaining findings are test-pin breadth and
assertion-strength gaps (MEDIUM/LOW), not code defects — the single
call site makes the uncovered refusal classes incapable of leaking
consumption without a code restructuring that would itself be
review-visible.

## (1) Invocation point — PASS

`signing/pin_ceremony.py`:

- Exactly one textual invocation of the consumer in the whole
  function: `consume_authorisation(authorisation)` at line 890,
  inside a try that re-raises `SigningError` and converts any other
  exception to `SigningError` (cause chained). Grep confirms no
  second call site.
- Code order read directly (not the docstring): signing-key/signed
  type gates → authorisation type + public-key consistency gates →
  consume-presence gate (line 686) → history-presence gate →
  operator/reason/evidence format checks → old-pin capture (once) →
  envelope verification (`verify_ceremony_authorisation`) → exact
  binding (operator, reason, old pin, candidate, evidence) →
  evidence-independence check → relation gates (backwards/same/
  same-seq-fork/successor/successor-fork/gap-prev-is-pin) →
  `chain_gap_recovery` strict recomputation
  (`verify_snapshot_for_state`, line 831) → `initial_anchor`
  empty-history gate → `_check_ceremony_history` (line 865) → bare
  attestation verification (`verify_signed_snapshot`, line 871) →
  **consume (line 890)** → `performed_at` normalisation → payload
  construction (line 898) → record construction → the function's
  only return.
- No path constructs or returns a record without consuming: the
  sole `return` is after the consume block. No path consumes twice:
  one call site, no loop, no retry in `reanchor_pin`.
- Consumer exceptions propagate as refusals and nothing is
  returned, matching R5/R7, including the non-`SigningError`
  conversion.

LOW-1 — Post-consume fallible step. `performed_at =
_normalise_time(moment, …)` and its `_parse_time` re-check run
*after* consumption (lines ~896–897). A failure there would burn
the authorisation and return nothing. That is consistent with the
R7 crash contract (burned, never silently succeeded), and `moment`
has already been consumed by the envelope/snapshot verifiers, so
the practical risk is negligible — noted for completeness, not a
fix request.

## (2) T1b ordering — PASS

- Code: the explicit-`None`/non-callable gate at
  `pin_ceremony.py:686` (`consume_authorisation is None or not
  callable(…)`) sits with the type gates, *before* the
  history-presence gate and long before envelope verification.
  (Only the signing-key/signed/authorisation type gates precede
  it — R5's "before envelope verification" is what is claimed and
  what holds.)
- Test: `test_t1b_none_and_noncallable_refuse_before_envelope_verification`
  (`tests/test_signing_pin_ceremony.py:1255ff`) loops `None, 42,
  "consumer"` with an envelope minted at `NOW` (TTL 900 s, so
  expired at the ceremony's `now="2026-11-20T12:16:00+00:00"`) and
  asserts the "fail-closed on omission" message. This genuinely
  pins the ordering: were the gate after envelope verification,
  the refusal would be the envelope's `expired` reason, not the
  omission message. Same construction as T2 for history.
- `test_t1b_consume_authorisation_keyword_is_required` also pins
  no-default via `inspect.signature` (TypeError on omission).

## (3) Spy tests — PASS with a breadth gap

`test_spy_consumer_zero_invocations_on_local_refusals`
(`tests/test_signing_pin_ceremony.py:1279ff`) pins ZERO invocations
for: (i) expired envelope, (ii) binding mismatch (envelope for
operator-9), (iii) history refusal (replayed target with updated
history), (iv) tampered candidate signature.
`test_spy_consumer_exactly_one_invocation_on_success` pins exactly
one invocation on success, delegating to the real fixture consumer.

MEDIUM-1 — Spy coverage does not span every local refusal class
R5 names. Not spied: relation-gate refusals (successor,
successor-fork, gap-prev-is-pin, backwards/same), the
`strict_reasons` shape gate (None / non-sole-chain_gap, which
fires *before* recomputation), evidence-independence refusal,
reason/pin coherence, `initial_anchor` non-empty-history refusal,
and — the most distinct hole — bare attestation verification on a
no-pin reason (`lost_pin`/`initial_anchor`), where no strict
recomputation runs at all and the bare verifier is the last local
gate before consumption. Leg (iv) is also slightly mislabelled:
its comment calls it a strict-recomputation refusal, and that is
in fact what fires (tampered signature → recomputed result ≠
`("chain_gap",)`), so bare-attestation-after-recomputation is not
independently pinned either. No leak is possible in the current
code — all these checks sit textually before the single call site
at line 890 — but R5's wording ("zero invocations on any local
refusal, pinned by spy tests") is only partially discharged.
Recommend adding spy legs for relation-gate, strict-shape, and
no-pin bare-attestation refusals in a later cycle; not a ship
blocker for this one.

## (4) T7′/T8′ genuineness — PASS (the heart of this review)

Diffed against the cycle-20 originals (`git diff HEAD`):

- **T7′** (`test_consumption_replay_with_stale_history_succeeds_named_residual_protected_head`,
  name retained, body flipped). Cycle 20 asserted the second
  presentation with stale `()` history SUCCEEDED (`pin2 == pin1`,
  same authorisation_id). T7′ preserves the exact scenario shape —
  same envelope, same stale `()` history — and now asserts
  `SigningError` containing "already consumed". The refusal is for
  the right reason: every local check passed on the identical
  first call, history is unchanged, and the second call goes
  through a *fresh* `LedgerBackedConsumer` instance over the same
  fixture dir, so the refusal can only come from the persisted
  consumption journal ("authorisation already consumed: …",
  `trust/ledger.py` `append_consumption`), not from in-memory
  state or an incidental earlier gate.
- **T8′** (`test_t8_regression_scenario_stale_history_returns_regressed_pin`,
  name retained, body flipped). Scenario shape preserved exactly:
  consume seq1→seq4, advance the real pin to seq6 by two ordinary
  `advance_pin` steps (no ceremony-history trace), replay the
  original envelope with `old_pin` restaged to the seq-1 pin.
  Updated-history leg still refuses at the history
  ("already a ceremonied target") — and importantly that leg
  refuses *before* consumption, so it does not disturb the stale
  leg that follows. Stale-history leg: cycle 20 asserted it
  SUCCEEDED and returned the regressed seq-4 pin
  (`regressed["cycle_seq"] == 4 < 6`); T8′ now asserts refusal
  with "already consumed" and no returned pin. Yes — the stale leg
  genuinely reaches the consumer: it is byte-for-byte the
  arrangement that succeeded under cycle-20 code, with the
  consumer as the only new gate on that path.
- **T8′ fresh-envelope leg**: new envelope, old=seq1,
  candidate=seq5, evidence `"f"*64`, history `()`. Local checks
  pass by construction (gap relation, strict recomputation yields
  sole chain_gap for a seq-5 candidate with foreign prev against
  the seq-1 pin, bare attestation valid), so the refusal comes
  from the consumer: candidate seq 5 is ahead of the consumed
  head (4), but the old pin seq 1 is behind it → R3 old-pin rule →
  `HeadRegressionError` ("old pin is behind the consumed head").

LOW-2 — The fresh-envelope leg asserts only
`assertIn("head", str(cm.exception))`. "head" appears in no local
refusal message in `reanchor_pin`, so the assertion does
discriminate consumer-vs-local, but it does not discriminate
*which* head rule fired (old-pin-behind vs candidate-fork would
both pass). Tightening to "old pin is behind the consumed head"
would pin the intended R3 sub-rule. Assertion-strength issue
only; the scenario construction leaves the old-pin rule as the
only reachable head refusal.

## (5) Helper discipline (R12) — PASS

- Grep of the whole test suite: no `lambda`-returning-None, no
  `Mock`, no dummy callable is used as a `consume_authorisation`
  anywhere. The only consumers in the tree are: the helper default
  (real ledger-backed), `_fresh_fixture_consumer()` (real, new
  dir), `_CountingConsumer` spies, T-Cc's commit-then-raise
  consumer, and `VerifierClient.ceremony_consumer()` in the two
  trust test files.
- Helper default (`tests/test_signing_pin_ceremony.py:298`):
  `kw.setdefault("consume_authorisation", _default_consumer())`,
  where `LedgerBackedConsumer.__call__` opens a *fresh*
  `CeremonyConsumptionLedger` over the fixture dir on every call
  and translates `LedgerError` → `SigningError`. Never an
  always-succeed fake.
- Fixture scoping / poisoning: every reanchor-consuming class
  (`ReanchorTests`, `CeremonyAuthorisationTests`,
  `Cycle16HardeningTests`, `Cycle20ConsumptionTests`,
  `Cycle21ConsumptionTests`) calls `_reset_fixture_consumer()` in
  `setUp`, i.e. per test *method* — a fresh temp dir per test, so
  one test's consumption cannot poison another test's ceremony,
  while calls *within* a test share one consumer (continuity
  where a test needs it, e.g. T7′/T8′). This is per-test rather
  than the literal per-class wording of R12, but it satisfies
  R12's actual constraint (fixture-scoped, NOT per call) with
  stronger isolation. Within-test cases that need a second
  unrelated ceremony correctly pass `_fresh_fixture_consumer()`
  explicitly (Cycle16 fix-round legs, lines 909/934/949).
- Fakes only where the fake is the subject: `_CountingConsumer`
  (invocation discipline) and T-Cc's commit-then-raise consumer,
  which commits to a *real* ledger before raising and then
  asserts exactly one consumption entry and already-consumed on
  retry — R7's T-Cc as specified. The no-delegate spy in the
  zero-invocation test is never invoked on any asserted path
  (that is the assertion), so its return-None body is not an
  always-succeed default in disguise.
- At least one of T7′/T8′ wires a real ledger-backed consumer:
  both do (T7′ explicitly via a fresh instance; T8′ via the
  helper default, whose `__call__` re-opens the ledger per call).

## (6) Client adapter — PASS

`trust/client.py`:

- `ceremony_consumer()` (line 644ff): the returned callable
  type-checks the argument (`SignedCeremonyAuthorisation`, else
  `SigningError` from the adapter itself), converts via
  `ceremony_authorisation_envelope_to_dict`, makes exactly one
  `ceremony_consume` call, returns `None` on success. No retry
  loop anywhere; `_run` is one subprocess per call.
- Error translation is complete: `except VerifierError` — and
  `trust/errors.py` shows `VerifierUnavailable`,
  `VerifierTimeout` (subclass of Unavailable),
  `VerifierProtocolError`, and `VerifierConfigError` all derive
  from `VerifierError`, so timeout and unavailable are translated
  to `SigningError` (cause chained) exactly like state refusals.
  Transport failures in `_run` are themselves normalised to those
  classes (TimeoutExpired → `VerifierTimeout`, OSError →
  `VerifierUnavailable`, exit 2/3 → Protocol/Config).
- `ceremony_consume` (line 576ff) validates every echo: it
  captures `authorisation_id`, `ceremony_id`, and candidate
  seq/hash from the sent dict *before* the call (missing keys →
  `VerifierProtocolError`), then requires the result's exact key
  set `{authorisation_id, ceremony_id, consumption_seq,
  new_cycle_seq, new_payload_hash}` and equality of
  authorisation_id, ceremony_id, and candidate seq/hash against
  what was sent, plus `consumption_seq` an int ≥ 1 (bool
  excluded). A verifier returning a *different* authorisation_id
  is therefore a `VerifierProtocolError`, which the consumer
  translates to `SigningError` — a protocol refusal, envelope
  treated as burned, never a silent success. That answers the
  review question directly: yes, covered.

## (7) E2E — PASS

`git diff HEAD -- tests/test_trust_ceremony_authorisation.py` is
exactly two hunks: a docstring paragraph and one line in the
fixture's `reanchor()` helper —
`consume_authorisation=self.client.ceremony_consumer()` as the
default, overridable via `**over` (`args.update(over)` after the
default). All eight original tests and their assertions are
byte-identical. The E2E now genuinely exercises mode + client +
ledger: the happy paths authorise via the real subprocess
(issuance journal entry exists), then consume via the real
`ceremony_consume` mode (which checks issuance presence and the
head), so success is impossible without the full chain working.
Per-test fixtures (fresh verifier home in `setUp`) prevent
cross-test consumption poisoning. The subprocess suite
(`tests/test_trust_ceremony_consumption.py`) additionally covers
replay across fresh client instances, never-issued, expired,
verifier-down fail-closed, and the R4 mirror-scoping trap — all
wired through the real client consumer, consistent with what I
read there.

## Minor / out-of-scope observations

LOW-3 — Stale wording in the `pin_ceremony.py` module docstring:
the cycle-19/20 evidence-provenance paragraph still says issuance
single-use "is NOT consumption enforcement (nothing burns when
`reanchor_pin` runs — see the consumption limit below)". The
cycle-21 section later in the same docstring states the correct,
superseding position, but the unqualified parenthetical is now
wrong for the production wiring and could mislead a reader who
stops early. Wording fix for a later docs pass; the function
docstring itself is correct.

## Summary of grades

- BLOCKER: none. HIGH: none.
- MEDIUM-1: spy-test breadth — several local refusal classes
  (relation gates, strict-shape gate, evidence independence,
  no-pin bare attestation) have no zero-invocation pin, though
  the single call site makes leakage structurally impossible
  today.
- LOW-1: post-consume `performed_at` normalisation (consistent
  with the burn-on-ambiguity contract).
- LOW-2: T8′ fresh-envelope leg asserts substring "head" rather
  than the specific old-pin head-regression message.
- LOW-3: stale "nothing burns" parenthetical in the module
  docstring, superseded by the cycle-21 section in the same file.

Verdict: **SHIP**, score **0.90**.
