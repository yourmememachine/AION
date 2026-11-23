# War-room RE-REVIEW — rev-r4 (ceremony integration), cycle 21 fix round

Scope: only my original findings (review-r4.md) and their fix-round
dispositions per the DESIGN-FINAL reconciliation addendum (C4, C5,
C1). Method: read the new test legs and the production code paths
they exercise; ran `tests/test_signing_pin_ceremony.py` in full —
55 tests OK, including the extended spy test, T8′, and T-Cc.

## Verdict: SHIP — score 0.92

All three of my fixable findings are genuinely fixed. Nothing in
the fix round moved the consumer invocation point or weakened the
exactly-once discipline.

## MEDIUM-1 (spy coverage) — FIXED (C4)

`test_spy_consumer_zero_invocations_on_local_refusals` now carries
legs (v)–(viii); each asserts `spy.calls == []` plus a specific
refusal message, and each construction was traced to the code
path it claims:

- **(v) relation gates.** The chained-successor (`snap(2,
  prev=pin)`) and successor-fork (`snap(2, prev="f"*64)`) legs
  assert `malformed_payload`, and the in-test comment honestly
  says why: a seq = old+1 candidate cannot carry a valid
  chain_gap_recovery envelope at all — the payload projection
  (`ceremony_authorisation_payload`, gap-only rule: candidate
  cycle_seq must be at least old_pin + 2) refuses it at envelope
  verification, before the relation gate. That matches the
  cycle-15 re-scope and my original note that these relations
  are unreachable through a valid envelope; the legs are not
  mislabelled as relation-gate refusals. The third leg,
  `gap_prev_is_pin` (`snap(4, prev=pin_hash)`), DOES reach the
  relation gate: the envelope is a valid gap envelope (seq 4 ≥
  1+2), and the asserted message "candidate claims the pin as
  its immediate predecessor" is the exact text of the
  `gap_prev_is_pin` branch in `reanchor_pin`. Genuine.
- **(vi) strict-shape gate.** `strict_reasons="chain_gap"` (a
  bare string) fails the `isinstance(strict_reasons, (list,
  tuple))` / sole-chain-gap check in `reanchor_pin` before any
  recomputation; the asserted message is that gate's exact text.
  Genuine shape-gate pin, not a recomputation refusal in
  disguise.
- **(vii) evidence independence.** `evidence_hash =
  cand.state_sha256` reaches the step-5 non-equality check
  (which covers payload_hash, snapshot_id, state_sha256 and
  calibration_sha256); the comment correctly identifies this as
  the mintable leg that reaches the check itself, and the
  asserted message is the check's exact text.
- **(viii) no-pin bare attestation.** A `lost_pin` envelope over
  a tampered-signature candidate: no strict recomputation runs
  on the no-pin path, so the bare verifier
  (`verify_signed_snapshot`) is indeed the last local gate, and
  the asserted "candidate fails attestation bindings" is its
  refusal. This closes the most distinct hole I flagged.

The one inherent limit stands and is now honestly documented in
the test itself: successor/successor-fork relation branches
cannot be exercised through a valid envelope, so their
zero-invocation property rests on the single-call-site argument
(as before) rather than a direct spy leg. Acceptable.

## LOW-2 (T8′ substring) — FIXED (C5)

The T8′ fresh-envelope leg now asserts the exact string
`"old pin is behind the consumed head"` (test file line 1166),
pinning the R3 old-pin sub-rule specifically rather than any
head refusal. The test passes in the full-file run.

## LOW-3 (stale docstring parenthetical) — FIXED (C1)

The "(nothing burns when `reanchor_pin` runs…)" parenthetical is
gone (grep: zero occurrences of "nothing burns" in signing/,
trust/, tests/). The rewritten paragraph states that issuance
single-use "is NOT itself consumption enforcement", describes
consumption enforcement as the separate cycle-21 mechanism under
the mandated production wiring (exactly-once invocation after
every local check, verifier-backed burn before any record
exists, no-op callable unprotected), and no longer contradicts
the cycle-21 section later in the same docstring.

## Invocation point / exactly-once — UNCHANGED

`signing/pin_ceremony.py` still contains exactly one consumer
invocation, `consume_authorisation(authorisation)` (line 909),
inside the same try that re-raises `SigningError` and converts
any other exception to `SigningError` with the cause chained. It
sits after bare attestation verification and immediately before
`performed_at` normalisation and payload/record construction —
the same position as reviewed. The fix round touched only tests
and docstring wording in my scope.

## Not re-litigated

LOW-1 (post-consume `performed_at` normalisation) was recorded
in my original review as consistent with the R7 burn-on-ambiguity
contract and explicitly not a fix request; the addendum does not
list it, and that disposition stands.

Verdict: **SHIP**, score **0.92** (up from 0.90: every finding I
raised is discharged with genuine constructions, verified by
reading the code paths and running the suite).
