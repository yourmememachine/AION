# REVIEW — Cycle 19: Protected Gate scope extension

Six blind reviewers, none of whom built the cycle; scores
locked in state/calibration/calibration.json BEFORE
reconciliation (subject `cycle-19-gate-extension`; fix-round
re-reviews under `cycle-19-fixround`, same reviewer ids).
External seats (seat-gpt, seat-gemini) review the delta brief
(internal/CROSS-CHECK-BRIEF-CYCLE-19.md); the verdict below is
PROVISIONAL on that round. An external approval never
overrides an internal FIX.

Builders: 3 coder seats (A gate closure, B verifier
authority, C ceremony integration) — design and cross-critique
in internal/cycle19-work/.

## Blind round

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | scope fidelity vs decision + design | 0.93 | SHIP |
| rev-r2 | gate closure soundness | 0.93 | SHIP |
| rev-r3 | verifier authority mode | 0.92 | SHIP |
| rev-r4 | ceremony integration | 0.78 | FIX |
| rev-r5 | consistency + wording | 0.82 | FIX |
| rev-r6 | whole cycle (forced dissent) | 0.87 | FIX |

Principal verifications by the SHIP seats: the eval/ diff is
exactly the authorised constants change and Item A is intact
(r1, incl. 160 targeted tests); the closure resists spelling
probes and the negative tests are mutation-verified against
the pre-extension list, with the L3 residual reproduced live
and found honestly stated (r2); the mode's validation order,
unsigned/unledgered membership refusal, anti-replay before
signing, dual-append burn and fail-closed config all verified
against the real subprocess (r3).

## Findings and dispositions

- **rev-r4 F1 MEDIUM (test integrity) → CLOSED by re-scope.**
  The converted helper's fallback mint masked six refusal
  cases: they refused at envelope binding, not at the checks
  they named, leaving reanchor_pin's relation/coherence
  checks regression-unpinned. Fix-round probing showed the
  named checks are STRUCTURALLY UNREACHABLE behind any
  envelope — verify re-derives the payload through the
  projection, which enforces the same gap-only / coherence /
  evidence rules and refuses `malformed_payload` first. The
  tests were renamed and re-scoped to the verification
  refusals they actually exercise (specific messages
  asserted, unreachability commented), and one leg was
  strengthened: evidence == candidate state_sha256 is
  mintable, reaches step 5, and now asserts the real
  independence message. Re-review: SHIP 0.95 — unreachability
  independently confirmed; the duplicated checks are
  desirable defence-in-depth (the prev-hash legs the envelope
  cannot see, e.g. gap_prev_is_pin, remain live). A
  documentation follow-up (note the envelope-shadowing in
  pin_ceremony's honest limits) is recorded, not blocking.
- **rev-r5 F1 MEDIUM (wording) + rev-r6 F2 HIGH
  (detectability overclaim) → CLOSED.** One claim —
  "audit-detectable after a rollback" / "the ledgers make a
  forged envelope detectable" — appeared in four docstrings
  and overstated the anchored store, which stores neither
  evidence_hash nor operator_id. All four passages now state
  the scoped truth (see BUILD-CYCLE-19.md). rev-r5 also
  judged the three builder deviations acceptable (ledger
  purpose literal, TTL clamp, shared refusal code).
- **rev-r5 F2 LOW → CLOSED.** setup.sh's template was pinned
  only in the subset direction; test_template_keys_equal_allowlist
  now pins set equality (mutation-checked by rev-r5).
- **rev-r6 F1 HIGH (consumption-side replay) → OPEN,
  dissent preserved.** The envelope is burned at issuance,
  not consumption; a second consumption within the 900s TTL
  succeeds when ceremony_history is omitted. The dissent's
  flip condition (a caller-unomittable consumption record,
  or mandatory history) is not met. The room accepted the
  coordinator's narrowing (a replay can only re-derive the
  identical bound movement; the residual is re-anchoring
  against a since-moved pin state; a protected monotonic
  head is an owner-level store decision, recorded as a
  follow-up) as scope-honesty, not closure. **rev-r6's
  dissent stands on this point and is preserved here: F1
  remains open, and any future cycle claiming consumption
  single-use without the protected head re-triggers its
  FIX.** Re-review verdict: SHIP 0.91 on that basis.
- **rev-r6 F4 (decision interpretation) → OPEN, owner
  item.** "The gate holds its own list" was implemented as
  the verifier boundary holding the list in protected env
  config. Purpose satisfied, letter substituted; flagged in
  BUILD-CYCLE-19.md and the external brief for Dilip's
  ratification. Not resolvable by any reviewer seat.
- **rev-r6 F3/F5 → CLOSED as statements.** The in-process
  key-holding limit is now stated exactly (a forged envelope
  is indistinguishable at consumption; discovery is
  audit-only). The cycle's claim is scoped in rev-r6's own
  words: "authority relocated to the verifier; gate verdict
  chain L1+L2 closed, L3 open."
- **rev-r3 minors (recorded, not blocking):** operator_id
  grammar asymmetry between mode and config (classification
  only); no reload-retry on ceremony appends (fail-closed
  availability); anchor-failure path after both appends is
  code-verified but untested.
- **rev-r1 housekeeping (done at close):** the cycle-18
  record internal/CROSS-CHECK-12.md is committed separately,
  not swept into the cycle-19 commit.

## Reconciled verdict

**SHIP — unanimous after the fix round** (re-reviews:
rev-r4 0.95 SHIP, rev-r5 0.96 SHIP, rev-r6 0.91 SHIP
provisional-on-conditions). rev-r6's conditions: the verdict
stays PROVISIONAL on the external seats; F4 is flagged to
the owner; BUILD-CYCLE-19.md carries the F4 flag, the F5
scoping and the migration note exactly as reconciled (it
does); F1's dissent is preserved (above). **Item A ships
with this cycle**, with the F5 qualification. Cycles 14–16
remain HELD pending their re-review on the extended gate,
which is a separate later step.
