# Build — signed-state (hourly-run cycle, built in parallel with cycle 10)

Item: `signed-state` (leverage 7.0) — "Signed state and per-seat
vote records". Built by the hourly `ai-continuous-build` run on
2026-11-20. **Status: built, war-room reviewed, fix rounds
complete; NOT yet recorded in loop state.** While this build was
in progress, the main chat recorded its own cycle 10
(`trust-boundary-v3-demonstrations`, a seq-31 item added after
this run's state read, leverage 8.5) at 12:04 UTC. Following the
project's standing practice for parallel work, this run did not
compete for the cycle-10 slot, did not overwrite
`BUILD-CYCLE-10.md` / `REVIEW-CYCLE-10.md`, and did not touch
loop state. `signed-state` remains `pending`; the next cycle
that picks it (it is now the highest-leverage pending item)
only needs to record this already-reviewed build. Coders: 15
(5 pods of 3, two design rounds — see below). War room: 6
internal seats + 2 external seats; full record in
`internal/REVIEW-SIGNED-STATE.md`.

## Planning note

Three coder seats (seat-5, seat-9, seat-3) first designed
`production-signed-path-wiring`; on checking the loop's pick
rule, `signed-state` outranked it on the insertion tie-break,
so a fresh three-seat round (seat-2 correctness, seat-15
adversarial, seat-10 integration) designed this build. The
wiring designs are preserved in
`internal/DESIGN-PRODUCTION-WIRING.md` for the next cycle.

## What was built

`signing/state_snapshot.py` (new) plus exports in
`signing/__init__.py` and `tests/test_signing_state_snapshot.py`
(39 tests):

- **Signer recomputes, never caller-asserted.**
  `sign_state_snapshot` takes raw bytes and derives every bound
  fact with one strict parser shared by sign and verify: state
  SHA-256, schema version, `cycle_seq`, history length, last
  cycle id/item, last `completed_at`. The parser rejects
  duplicate keys at any depth, non-finite numbers,
  bool/float-as-int, oversize input, non-increasing history,
  `cycle_seq` ≠ last history cycle, and garbage or
  non-monotonic `completed_at` values.
- **Vote record bound whole.** The calibration log is bound by
  the hash of the entire file — scores, outcomes and discussion
  timestamps alike. `None` leaves it explicitly unbound; empty
  bytes are refused as malformed; verification can require it.
- **Envelope discipline** mirroring gate decisions:
  domain-separated HMAC (`signed-state-snapshot-v1`),
  allowlisted payload with every field validated in the payload
  builder itself, strict envelope reconstruction, TTL bounds
  (60 s–48 h) and 300 s skew, `signed_at` never before the
  state's last completed cycle.
- **Rollback and chain checks.** A caller-held pin
  (`cycle_seq`, `payload_hash`, optional key/signer bindings):
  older → `snapshot_rolled_back`; same-sequence different hash
  → `pin_mismatch` (compared against the recomputed hash); the
  pin's immediate successor must chain to it
  (`chain_discontinuity`). `expected_prev_snapshot_hash` checks
  a supplied predecessor directly.
- **Production-shaped wrappers.** `verify_snapshot_for_state`
  requires every binding (state bytes, calibration bytes, pin,
  signer). `sign_state_files` enforces the cross-file capture
  protocol in code: read state, read calibration, re-read
  state, refuse on change.

## Honest limits (carried openly)

- No full loop validation is re-run; a well-formed fabricated
  history passes this module but not the loop's loader.
- Rollback is undetectable without an external pin; joint
  rollback of state + calibration + snapshots + pin is
  undetectable in-deployment. Chain completeness is not
  established: snapshots more than one sequence past a pin are
  not chain-checked (rev-r2's preserved dissent).
- HMAC is symmetric: any key holder forges; a snapshot proves
  key-holder-group membership, not individual authorship; no
  rotation/revocation; replay inside the TTL is allowed unless
  the caller's pin has advanced.
- A snapshot is a freshness-bounded attestation (≤48 h), not an
  archival proof; long-lived provenance needs the payload hash
  anchored externally while the snapshot is live.
- The loop's own loader accepts duplicate JSON keys (last-wins)
  where this parser refuses them — worth a backlog item
  (`loop-duplicate-key-rejection`); `core/loop.py` is protected,
  so that fix goes through the protected-change workflow.
- Same-user key placement remains the cryptographic boundary,
  as throughout the signing package.

## Self-improvement delta

Before this build, the loop state and the calibration log —
the records every scorecard claim rests on — could be rewritten
with recomputed internal hashes and no trace. The war room also
re-confirmed a reusable lesson, now pinned by tests in three
cycles running: a payload builder that does not validate every
field it MACs is not a validator, and payload re-derivation is
the one chokepoint where validation must live.
