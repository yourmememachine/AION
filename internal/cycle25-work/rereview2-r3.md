# Cycle 25 — RE-REVIEW 2, seat rev-r3 (adopter side): are F2 and F3 fixed?

Scope: the F2/F3 fix round against `rereview-r3.md` §4–§5 —
the structured `CeremonyHeadRegression` / `CeremonyAlreadyConsumed`
translations in `trust/client.py` (`ceremony_consumer`), the
`_consume_retained` reclassification, the consume-first
fall-through (Option A) and `_stop_at_pending`'s derived
`refusal_code` in `trust/pin_adoption.py`, and the three new
tests in `tests/test_trust_supersede_adopter.py`. No code
modified. Five additional probe scenarios were run against
the real-verifier fixture (probe script kept out of tree, in
/tmp); outcomes are reported as A, B1, B2, C, D below.

Tests run by this seat (unittest): `test_trust_supersede_adopter`
+ `test_trust_runner` + `test_trust_client` — **46 tests, OK**;
`test_trust_pin_adoption` + `test_trust_pin_adoption_crash` +
`test_trust_supersession_approval` +
`test_trust_ceremony_supersede` + `test_trust_ceremony_consume`
— **OK**; full discovery run — **OK (skipped=28)**, no
regressions anywhere.

---

## 1. The translation plumbing is exactly as claimed — and spoof-resistant (probe D)

- `ceremony_consumer` translates ONLY via the wrapped cause's
  structured `.verifier_code`, and ONLY when the cause is a
  `VerifierConfigError` (the exit-3 class `_run` builds from
  the verifier's structured error document). No string
  matching anywhere in the new code paths.
- The verifier side emits both codes only from the consume
  mode's authoritative checks (`verifier_main.py`): step (5)
  already-consumed by authorisation_id / signing-mirror, and
  `check_head`'s `HeadRegressionError` / target-based
  `AlreadyConsumedError` at step (7) and in the commit append.
  `_run` parses the code solely from the stdout error
  document; stderr text rides only inside the message, which
  nothing inspects.
- Probe D (stubbed `ceremony_consume` under the real consumer):
  (1) a `VerifierProtocolError` (exit-2 class) CARRYING
  `verifier_code="ceremony_already_consumed"` is NOT
  translated — plain `SigningError`, exact type; (2) a plain
  `SigningError` whose MESSAGE contains both code strings
  propagates untranslated; (3) a `VerifierConfigError` with
  `verifier_code=None` wraps plain; (4) only the sanctioned
  channel — `VerifierConfigError` with the code set, which in
  production `_run` produces only from a verifier exit-3 error
  document — yields the subclass, cause-chained. Local errors
  (timeout/unavailable/protocol) all carry `verifier_code=None`
  or the wrong class, so no local failure can masquerade as a
  verifier certificate.

## 2. F2 — FIXED, including under repetition (probe A) and with a stale approval (probe C)

- The named regression test
  `test_head_move_after_decision_resume_not_burned_fresh_approval_presented`
  passes as specified: resume attempt 1 re-pends after exactly
  one head-regressed consume (supersede 0, authorise 0); attempt
  2 PRESENTS the fresh approval (supersede 1, presented ==
  artefact), the second-decision refusal (`unproven`) falls
  through in-attempt to a consume that head-regresses again,
  and the movement re-pends — never Burned; the movement later
  completes at the next sequence under a new decision.
- Code-level classification sweep of `_consume_retained`:
  `CeremonySupersedeRequired` and `CeremonyHeadRegression`
  both return None under `pre_commit_fallthrough=True`, and
  both route to `_stop_at_pending` otherwise;
  `_stop_at_pending` derives the report's `refusal_code` from
  `getattr(sup, "verifier_code", None)` — verified live in
  probes A/C, where the rewritten report carries
  `"ceremony_head_regression"`. The post-decision consume
  (after a successful decision request, and after an
  `unproven`/`ledger_failed` fall-through) is called WITHOUT
  the fall-through flag, so its head-regression re-pends in
  the same attempt. No path in `_consume_retained` classifies
  a pre-commit refusal as Burned for a decided movement; the
  only Burned exits there are the F3 certified-consumed branch
  and the generic conservatism for genuinely ambiguous
  failures.
- Probe A (head moves TWICE after the decision, @3→@5→@7):
  attempt 1 (no approval) — Pending, consume 1, supersede 0;
  attempt 2 (fresh approval bound to the newest head) —
  presented, unproven, post-decision consume head-regresses,
  Pending again with the report's `refusal_code` now
  `ceremony_head_regression`. Consumption count frozen at 6,
  decisions still 1, pin unmoved. Repetition does not degrade
  the classification.
- Probe C (STALE approval, bound to the pre-move head, dropped
  into the inbox after the move): it IS selected and presented
  — the pending entry carries no head-entry hash to filter by
  (the adopter's report writes it null by design), so selection
  rests on the authorisation-id binding and the VERIFIER's
  binding check is the authoritative gate, exactly as the
  module documents. The verifier refuses `unproven`, the
  fall-through consume head-regresses, the movement re-pends
  with a refreshed report; the stale file is moved aside. A
  fresh approval on the next attempt is still presented —
  nothing is stranded. Cost of a stale artefact is one
  presentation, never a burn or a strand.
- Fresh-ceremony head-regression shapes are unchanged, as
  claimed: `_reanchor`'s fresh consume still treats any
  failure (the new subclass included) under the pre-existing
  any-exception-is-Burned conservatism; the reclassification
  is scoped to the resume-of-a-decided movement in
  `_consume_retained` only.

## 3. F3 — FIXED, and the consumed-phase append cannot misclassify an unconsumed ceremony

- The named regression test
  `test_resume_consume_commit_lost_response_recovers_as_genuine_burn`
  passes as specified (probe P1's exact shape): first attempt
  Burned with the consumption committed verifier-side and no
  `consumed` phase yet; second attempt's consume-first consume
  refuses `ceremony_already_consumed`, the adopter appends the
  `consumed` phase BEFORE raising Burned, `_find_pending_supersession`
  no longer intercepts, the ceremony appears in
  `_genuine_burn_entries`, and a third attempt lands via the
  ordinary `burned_unadopted` recovery (pin @5, exactly one
  new consumption).
- Probe B1 (already-consumed arising on a NON-consume-first
  resume: decision journaled + `supersede_decided` line
  present, consumption committed out-of-band before any resume
  attempt): the FIRST resume attempt already takes the F3
  branch — Burned, `consumed` phase journaled, intercept
  released, genuine-burn entry present — and the next attempt
  recovers and lands. The fix is not specific to the
  lost-response seam.
- Misclassification analysis: the append fires only on
  `CeremonyAlreadyConsumed`, which per §1 can only originate
  from the verifier's exit-3 certificate. That certificate has
  exactly two sources, and both mean this MOVEMENT's
  consumption exists verifier-side: (i) step (5) — this
  authorisation_id (or its signing-mirror entry) is in the
  consumption journal; (ii) `check_head`'s target rule — the
  candidate (seq, hash) IS the current head target, i.e. the
  movement was consumed under another authorisation, in which
  case `burned_unadopted` recovery is still the correct route
  (a recovery envelope binds the recorded burn). There is no
  verifier path that emits the code for a movement with no
  consumption. The append itself is best-effort (OSError
  swallowed, Burned still raised); if it is lost, the next
  attempt re-derives the same certificate from a fresh consume
  and retries the append — self-healing, not a strand.
- Probe B2 (already-consumed on a FRESH, non-resume consume —
  target already consumed by another envelope before the
  adopter's first ceremony): outcome Burned under the
  pre-existing fresh-path conservatism, the fresh envelope
  itself never enters the consumption journal (count
  unchanged), and NO `consumed` phase is appended — the F3
  append is scoped to `_consume_retained` and does not leak
  into the fresh path. (The fresh ceremony still counts as an
  unadopted burn via its `authorised` phase — the cycle-23
  rule, unchanged by this round and not an F3 claim.)

## 4. Non-blocking observations

- **Report freshness in the no-approval fall-through branch:**
  when a consume-first fall-through finds NO approval,
  `_resume_pending` re-pends WITHOUT calling
  `_stop_at_pending`, so the on-disk pending report keeps the
  pre-move `refusal_code`/head block (verified in probe A,
  attempt 1). An approver who mints purely from that stale
  report produces a stale approval — which probe C shows is
  safely refused (`unproven`), costs one presentation, and
  the report is refreshed as soon as any presented approval
  reaches a post-decision consume. The intended approver flow
  completes head facts from the verifier's journal, which
  detects the staleness. Worth a future report refresh on
  that branch; not a strand and not a blocker.
- A presented stale approval is moved aside locally although
  the verifier never journaled it as spent (its refusal is
  `unproven`, pre-commit) — the approver must re-mint rather
  than re-drop the same file. Consistent with the
  presented-once local rule everywhere else in this flow.

## Summary

Both blockers are fixed as claimed and hold under adversarial
variation: head moves repeated twice, already-consumed on a
first (non-lost-response) resume, already-consumed on a fresh
consume, a stale approval in the fall-through, and spoofed /
local error shapes at the translation seam. No path classifies
a pre-commit refusal as Burned for a decided movement; the F3
`consumed` append is verifier-certified, correctly scoped, and
self-healing if the append itself is lost. Full suite green.

Verdict: SHIP (0.89)
