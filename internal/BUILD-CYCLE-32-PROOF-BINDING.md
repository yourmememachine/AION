# BUILD CYCLE 32-PROOF — BINDING ROUND

**What this cycle did:** landed the blocking follow-up from
the fix-round-2 reconciliation (internal R4/R6 + the Gemini
seat converged on it): the proof binding is now hash-chained
and fail-closed pre-burn, instead of a plain JSON line
appended after the ship committed. Blind brief for the
external seats: internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF-
BINDING.md. Review record:
internal/REVIEW-CYCLE-32-PROOF-BINDING.md.

## Changes (trust/proofcarry.py only)
1. Hash-chained bindings: every record in
   proof-bindings.jsonl now carries prev_binding_hash
   (genesis = 64 zeroes) and binding_hash (self-hash of the
   canonical record core). _append_proof_binding re-reads
   and re-verifies the chain before extending it.
2. verify_proof_bindings(journal_dir): pure check —
   proof_binding_malformed / proof_binding_chain_broken.
3. Fail-closed pre-burn gate (step W2b in
   record_ship_with_proof): after live verification,
   before the snapshot/delegation (the burn happens inside
   the delegation), a side-effect-free preflight requires
   the existing chain to verify, the bindings path to be a
   regular file when present, and the target writable.
   Failure = ShipRefused with nothing spent.
4. The two tests pinning the exact binding key set
   (test_trust_proofcarry, test_cycle32_proof_ship) were
   updated to the 9-key set. Post-ship append failure keeps
   its anomaly semantics (the ship stands; the preflight is
   what moved the predictable failures pre-burn).

## Tests
- New: tests/test_cycle32_proof_binding.py — 6 tests.
  Failing-first: 3 failures + 2 errors of 6 before the fix;
  6 OK after.
- Targeted suites after the fix: 128 tests OK
  (binding, proofcarry, proof ship, fix2, claim pin).
- Affected ship suites standalone: test_trust_shipcheck +
  test_trust_shiptx + test_trust_shiptx_recovery = 86 OK;
  combined with all cycle-32 suites = 119 OK.
- Full suite (unittest discover): 1,902 tests ran
  (1,896 + 6), 28 skipped, 7 failures + 14 errors —
  identical across two runs, all "expired /
  attestation_expired" in the three ship suites above.
  Attributed to a PRE-EXISTING fixture time-bomb: those
  modules stamp timestamps at import time, freshness uses
  the host clock, and the full runs took ~24 min under
  heavy machine contention, expiring the stamps before
  the late suites ran. Not a regression of this change.
  Follow-up owed: stamp those fixtures in setUp.

## Staffing (current rule: 1 lead + 2 bug hunters)
Lead built and verified. Bug hunter 1 (adversarial review
of the binding design): confirmed the preflight TOCTOU,
the missing append lock (concurrent shippers can fork the
chain), torn-tail bricking, and that the chain does not
stop a writer who recomputes it — all recorded as limits,
none claimed closed. Bug hunter 2 (test/claim surface):
confirmed exactly the two key-set tests needed updating,
the two failure-stands tests keep their meaning, and the
claim-pin suite is unaffected; flagged the "durable
carrier" wording, now scoped in the docstring with the
anchor disclaimer. External seats (ChatGPT, Gemini,
Claude): brief prepared; sessions not run in this
scheduled run — verdict PROVISIONAL, nothing ships, and
the working tree is NOT committed (commit only on a
passed war room).

## Self-improvement delta
Lesson: a binding that lands after the commit it binds is
an anomaly report, not a binding — the check that a record
CAN be written belongs before the irreversible step, and
every integrity claim must name what it cannot detect
(tail truncation, chain recomputation) in the same breath.
Scorecard: no % change claimed (verdict provisional);
self-improvement leg's integrity spine strengthened —
recorded bindings are now tamper-evident and a ship that
cannot be bound is refused before it burns.

## Open follow-ups
- BLOCKING for ship: external-seat reconciliation on the
  brief (plus the current 1.0-from-all-seats bar).
- Non-author anchor for the binding chain head (closes
  tail truncation + chain recomputation).
- flock the binding append (concurrent-shipper fork).
- Fresh flagship artefact under the current checker
  (the round-1 artefact is void; still owed).
- Forged-.pyc regression test + forced -B env
  (Claude round-2 residual).
- Fixture time-bomb: stamp shipcheck/shiptx fixture times
  in setUp instead of at import.
