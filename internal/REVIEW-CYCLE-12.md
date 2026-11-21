# REVIEW — Cycle 12: signed-state war room (re-verification round)

Six blind internal reviewers, scores locked in
state/calibration/calibration.json (subject
cycle-12-signed-state-rereview) BEFORE reconciliation, plus two
external seats on the blind delta brief
(internal/CROSS-CHECK-BRIEF-SIGNED-STATE-DELTA.md; full record in
internal/CROSS-CHECK-SIGNED-STATE-R2.md):

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | evidence & attestation | 0.70 | FIX |
| rev-r2 | forced dissent | 0.80 | FIX |
| rev-r3 | parser strictness | 0.97 | SHIP |
| rev-r4 | envelope & serialisation | 0.78 | FIX |
| rev-r5 | rollback & pin semantics | 0.97 | SHIP |
| rev-r6 | integration & honesty | 0.88 | FIX (minor) |
| seat-gpt | external | 0.91 | FIX |
| seat-gemini | external | 0.78 | FIX |

Reconciled verdict: **FIX** — no ship on a split room. One reconciled
fix list; every item landed and re-verified, or explicitly deferred
with a reason (below). After the fix round the coordinator re-ran the
finding seats' own probe scripts against the fixed code (all
hand-builds now refuse; legitimate shapes still pass) and the full
suite is green at 1081. The cycle is recorded as **SHIP,
PROVISIONAL** — final only when the external seats re-review this
cycle's delta (their round-2 FIX findings are reconciled in the R2
record; per the standing rule an external approval never overrides
an internal FIX, and the internal room's FIX items are all closed).

## Principal findings and their disposition

- **rev-r1 DEFECT 1 / rev-r4 (envelope path) — `history_len >
  last_cycle_id` verified clean** under a self-consistent MAC
  (3/2, 5/2, 200/2, 2/1, 100/3 all returned ()). Signer-impossible
  by pigeonhole. CLOSED: `_validate_facts` refuses
  `history_len > last_cycle_id` (bound is ≤, not equality — pruned
  history with fewer entries stays valid, pinned by a positive
  test); the envelope path closes with it (single chokepoint).
  Pinned in Cycle12FixRoundTests; re-probed clean.
- **rev-r1 DEFECT 2 — empty history carrying `last_completed_at`
  verified clean.** Parser-impossible (empty history yields None).
  CLOSED: emptiness agreement for `last_completed_at` added,
  mirroring `last_cycle_id` / `last_item_id`. Pinned + re-probed.
- **rev-r6 — stale `b""` docstring.** `sign_state_snapshot`'s
  docstring described pre-fix behaviour (binds an empty-log hash)
  opposite to the code (refuses `b""`). CLOSED: docstring corrected.
  Minor note carried: the ABA state-flip case for
  `sign_state_files` is covered by the module docstring's hedges
  but not named; accepted as documented.
- **rev-r2 (forced dissent) — the pin+2 chain gap reaches the
  strict wrapper.** A seq-3 snapshot chained to garbage verifies ()
  against a seq-1 pin even through `verify_snapshot_for_state`;
  a caller advancing its pin to it launders a missing seq-2.
  PARTIALLY CLOSED, dissent preserved: the wrapper's docstring now
  states the scope plainly (continuity only for the immediate
  successor; advance pins one sequence at a time), and code-level
  enforcement is queued as backlog `snapshot-chain-gap-enforcement`
  (6.5). rev-r2's position — refuse or flag seq > pin+1 in code,
  not prose — stands in this record per the calibration-over-
  consensus rule; rev-r5's counter (a single pin can only anchor
  its successor; the API offers expected-prev at any distance)
  also stands. The record does not claim the gap is closed.
  Also from rev-r2: backdating against the envelope's own
  timestamp is refused unconditionally but reported as
  `malformed_payload`, not `signed_before_state` (which fires when
  state bytes are supplied) — noted as a reason-labelling limit.
- **seat-gpt HIGH — future-dated `signed_at`.** REFUTED by code:
  verify reports `signed_in_future` when signed_at is more than
  the 300 s skew ahead of now, and `expired` at the MAC-bound
  expiry (TTL ≤ 48 h enforced in the builder), so validity cannot
  stretch to ~32 days. The seat reviewed the brief, not the source
  (its own qualification). Its requested boundary evidence is now
  pinned: −300 s passes, −301 s refuses, +30 days refuses
  (Cycle12FixRoundTests.test_future_signed_at_skew_boundary).
- **seat-gpt MEDIUM — timestamp consistency invariant.** CLOSED in
  substance: the signer derives `last_completed_at` from the final
  history entry (they cannot disagree in a signed snapshot);
  hand-built disagreement with the real history is caught by
  `state_mismatch` when state bytes are supplied and by the
  builder's internal-consistency checks otherwise — including this
  cycle's empty-history fix; history timestamps are non-decreasing
  in the parser and all comparisons use parsed, normalised
  instants, never raw strings.
- **seat-gemini MEDIUMs — pin+2 (converges with rev-r2; see above)
  and the `sign_state_files` window.** The latter is refuted for
  the attested bytes: the signature covers the exact buffers read
  (state at second read, calibration at its read), so post-read
  file mutation cannot alter what was attested; the residual is
  pair-coexistence, already declared. Its hostile-Python-object
  point is assessed not-adopted: envelopes are reconstructed from
  JSON primitives through the strict parser, and the verify guard
  already converts type hostility in the payload path into
  `malformed_payload`; exotic `__eq__` objects never reach MAC
  comparison from any supported entry point. Its calibration
  `None` point is the documented convention (bare verify is
  envelope-only; the strict wrapper requires the bytes) — stated
  in both docstrings.

## Explicit deferrals

1. **snapshot-chain-gap-enforcement** (backlog, 6.5): refuse or
   flag `cycle_seq > pin + 1` in the strict wrapper. Owner:
   next trust cycle.
2. **snapshot-pin-ceremony** (backlog, 4.0): pin advancement /
   replacement authorisation and lost-pin recovery — deployment
   machinery (seat-gpt LOW, seat-gemini).
3. **Atomic multi-file generation** (seat-gpt MEDIUM): declared
   open limit since the original build; not silently dropped.

## Verification summary

- Finding seats' original probe scripts re-run post-fix: all
  defect shapes now refuse; valid + pruned shapes still pass.
- Module: 44 tests OK (10 consecutive runs not required; the
  live-state tests derive their instant from the live file and
  passed against the cycle-12 state after recording).
- Full suite: 1081 tests, OK (skipped=2, by-design live skips).
- Loop state: cycle 12 recorded via CoreLoop (15 coders, 6
  reviewers, reconciled, verify passed); calibration outcomes
  scored for subjects cycle-10b-signed-state and
  cycle-12-signed-state-rereview.

Verdict: **SHIP (PROVISIONAL on external re-review of this delta).**
