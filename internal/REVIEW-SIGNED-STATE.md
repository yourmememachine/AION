# War-room review — signed-state (hourly-run build)

Subject: `cycle-10b-signed-state` — `signing/state_snapshot.py`.
Calibration log: `state/calibration` (subject
`cycle-10b-signed-state`, blind scores recorded, discussion
closed, outcome deferred until the cycle is recorded in loop
state). External brief: `internal/CROSS-CHECK-BRIEF-SIGNED-STATE.md`;
external record: `internal/CROSS-CHECK-SIGNED-STATE.md`.

## Blind round (scores = probability the build is correct)

| Seat | Role | Score | Verdict |
|------|------|-------|---------|
| rev-r1 | evidence & attestation | 0.74 | FIX |
| rev-r2 | assigned forced dissent | 0.40 | FIX |
| rev-r3 | parser strictness | 0.82 | SHIP |
| rev-r4 | envelope & serialisation | 0.50 | FIX |
| rev-r5 | rollback & pin semantics | 0.55 | FIX |
| rev-r6 | integration & honesty | 0.80 | FIX |
| seat-gpt | external (ChatGPT) | 0.86 | FIX |
| seat-gemini | external (Gemini) | 0.84 | FIX |

Convergent findings (internal and external seats independently
landed on the same core defects):

- The payload builder validated almost none of the facts it
  MACed, so a hand-built envelope with signer-impossible facts
  (schema 999, inconsistent cycle fields, garbage timestamps)
  verified `()` standalone — rev-r1, rev-r2, rev-r4, rev-r6.
- Snapshot chaining was carried data, never verified; the pin
  was a sequence floor with no successor continuity — rev-r2,
  rev-r5, rev-r6, seat-gpt F1, seat-gemini #1.
- `signed_before_state` fired only when state bytes were
  supplied, though the envelope itself carries the timestamp —
  rev-r1, rev-r2, rev-r5.
- The parser validated `completed_at` only on the last history
  entry — rev-r2, rev-r3 (F5).
- Verify could crash (raw TypeError/ValueError) on untrusted
  field types instead of returning reasons — rev-r2, rev-r4.
- Cross-file capture consistency was a documented caller duty,
  not code — seat-gpt F2, seat-gemini #2.
- rev-r3's one HIGH was loop-side, not this build: the loop's
  loader accepts duplicate JSON keys (last-wins) where this
  parser refuses them. Filed for a backlog item; `core/loop.py`
  is protected.

## Fix rounds and verification

Round 1 (coordinator): facts validated inside the payload
builder (the shared re-derivation chokepoint) — ranges, types,
consistency, normalised timestamps, anti-backdate; strict
hash-or-empty typing; verify's exception guard broadened and
the payload hash moved inside it; pin hardened (strict keys,
non-negative sequence, optional key/signer bindings, recomputed
hash comparison, immediate-successor chain rule);
`expected_prev_snapshot_hash`; per-entry `completed_at`
validation; `state_hash_for` size cap; strict wrapper
`verify_snapshot_for_state`; `sign_state_files` double-read;
empty calibration bytes refused (seat-gemini); docstring
corrections (chaining scope, pin storage contract, TTL vs
provenance, key-group membership, replay, clock trust);
exports completed; the live-state test de-bombed (rev-r6: it
hard-coded cycle 9 and would have gone red on recording).

Verification re-probes by the finding seats: rev-r4 SHIP 1.0,
rev-r5 SHIP 1.0, rev-r6 SHIP 0.98 — every probe FIXED.
rev-r2 re-verified at 0.80 FIX on two partials: a future
`completed_at` on a non-last entry, and the pin+2 chain gap.

Round 2 (coordinator): history `completed_at` values must be
non-decreasing. rev-r2 spot re-check: FIXED (9/10, PASS on the
item). The pin+2 chain gap is carried as a documented limit
with rev-r2's dissent preserved here, per the calibration-over-
consensus rule: snapshots more than one sequence past a pin
are not chain-checked, and the record does not claim otherwise.

## Reconciled verdict

**SHIP (internal, reconciled after two fix rounds and
verification re-probes) — PROVISIONAL pending external
re-review.** Both external seats voted FIX on the blind brief;
their findings were reconciled in (chain checks, capture
protocol in code, empty-bytes refusal, expanded limits) but
neither has re-reviewed the fixed code. Seat-gpt also noted it
reviewed the design description, not the source. The remaining
external findings not adopted as code: pin persistence/recovery
ceremony and an enforceable multi-file generation protocol
(seat-gpt F2/F3) — both are deployment machinery beyond this
module's scope and are recorded as limits, not closures.
