# Cross-check brief — cycle 10, signed state snapshots (blind external review)

You are an external reviewer seat for the AION project. Review
the new code and return a verdict (SHIP or FIX) with a confidence
score (0–1) and concrete findings with file references. Do not
take any claim on trust; try to refute them.

## What was built

`signing/state_snapshot.py` (new, stdlib-only Python): a key
holder can attest the exact bytes of the core loop's state file
(`state/state.json` — every recorded cycle and self-improvement
delta) and optionally the calibration log
(`state/calibration/calibration.json` — the per-seat blind vote
record). Claims:

1. The signer recomputes every bound fact from the raw bytes
   with one strict parser shared by sign and verify: state
   SHA-256, schema version, cycle_seq, history length, last
   cycle id/item, last completed_at. Caller-asserted facts are
   impossible — there is no parameter for them.
2. The calibration log is bound by the hash of the whole file,
   so any edit to scores, outcomes or timestamps changes it.
   `calibration_bytes=None` leaves it explicitly unbound;
   verification can require it (`require_calibration`).
3. Domain-separated HMAC-SHA256 (`signed-state-snapshot-v1`)
   over an allowlisted payload; strict envelope reconstruction
   (exact keys, duplicate-key and non-finite JSON rejection,
   payload re-derivation before use); TTL bounds and clock skew
   mirror the existing gate-decision signing.
4. Rollback defence is a caller-held pin
   (`expected_pin={cycle_seq, payload_hash}`): older than the
   pin → `snapshot_rolled_back`; same sequence, different hash
   → `pin_mismatch`. Snapshots chain via `prev_snapshot_hash`.
5. Signing refuses a `signed_at` earlier than the state's last
   completed cycle (minus skew); verification reports
   `signed_before_state` for the same condition.

## Declared limits (judge whether they are honest and complete)

No full loop validation is re-run (structural checks only — a
well-formed fabricated history passes this module but not the
loop's loader); rollback is undetectable without an external
pin; joint rollback of state + calibration + snapshots + pin is
undetectable in-deployment; HMAC is symmetric (any key holder
forges; signer id is a claim); the two files are replaced
individually, so a caller reading them sequentially can capture
a pair that never coexisted (mitigation is a caller re-read
protocol, documented, not enforced here); a valid MAC never by
itself authorises anything.

## Acceptance demonstrations to reproduce or refute

- Edit one byte of the state or the calibration log after
  signing → verification against the presented bytes fails.
- Present the cycle-9 snapshot against a pin taken at cycle 10
  → `snapshot_rolled_back`.
- Feed malformed state (duplicate keys, NaN, bool cycle_seq,
  cycle_seq ≠ last history cycle, non-increasing history) →
  signing refuses.
- Extend `expires_at` on a signed envelope → payload
  re-derivation or MAC failure, never a pass.
- Construct a snapshot envelope through the gate-decision
  envelope format (or vice versa) → domain separation refuses.

Return: verdict (SHIP/FIX), confidence, findings ordered by
severity with file references.
