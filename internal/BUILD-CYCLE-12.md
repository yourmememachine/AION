# BUILD — Cycle 12: signed-state recorded (re-verification + fix round)

Item: `signed-state` (leverage 7.0, seq 2) — "Signed state and
per-seat vote records". The module itself was built by an earlier
hourly run (internal/BUILD-SIGNED-STATE.md: `signing/state_snapshot.py`,
39 tests, internal war room + both external seats FIX, fixes applied,
verdict internal SHIP / PROVISIONAL on external re-review) but was
never recorded in loop state. This cycle re-verified the fixed code
with fresh blind probes, ran a further fix round on what the probes
found, obtained the external seats' delta-round verdicts, reconciled
everything, and recorded the item.

Baseline at cycle start: loop state cycle 11 (trust-boundary-v31-fixes,
1075 tests recorded; cycle 11's external round 4 returned SHIP/SHIP —
internal/CROSS-CHECK-6.md — so the Trust Boundary is final). Working
suite at cycle start: 1077 tests (1075 + the 2 tests from
internal/FIX-SIGNED-STATE-SNAPSHOT.md).

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15), as recorded for the original
build in BUILD-SIGNED-STATE.md — Pod A Foundation (1, 5, 8), Pod B
Memory & World (2, 6, 7), Pod C Agents & Tools (9, 10, 11), Pod D
Safety & Eval (3, 4, 15), Pod E Action (12, 13, 14). This cycle's fix
round was applied by the coordinator from the reconciled war-room
findings (the cycle-11 precedent). War room: 6 internal reviewers from
other pods (rev-r1..rev-r6, rev-r6's round-1 dissent role rotates to
rev-r2 as forced dissent this round), blind scores locked in the
calibration log (subject cycle-12-signed-state-rereview) BEFORE
reconciliation, plus the 2 external seats (seat-gpt, seat-gemini) on a
blind delta brief (internal/CROSS-CHECK-BRIEF-SIGNED-STATE-DELTA.md;
record: internal/CROSS-CHECK-SIGNED-STATE-R2.md).

## What this cycle changed

1. **Two signer-impossible fact combinations closed** (rev-r1/rev-r4
   probes, self-consistent-MAC hand-builds): `_validate_facts` in
   signing/state_snapshot.py now refuses (a) `history_len` greater
   than `last_cycle_id` — strictly increasing positive cycle ids
   ending at cycle_seq admit at most cycle_seq entries; fewer stays
   legitimate (pruned history, pinned by a positive test) — and
   (b) an empty history carrying a `last_completed_at`. Both holes
   also closed the envelope-reconstruction path, which re-derives
   through the same builder. Re-probed with the finding seats'
   original scripts: every hand-build now returns
   `malformed_payload`; the legitimate pruned shape still verifies.
2. **Stale docstring corrected** (rev-r6): `sign_state_snapshot` no
   longer claims `b""` "binds the hash of an empty log" — the code
   refuses `b""`; `None` is the only spelling of unbound.
3. **Strict-wrapper chain scope qualified** (rev-r2 dissent):
   `verify_snapshot_for_state`'s docstring now states chain
   continuity is verified only for the pin's immediate successor
   and pins must advance one sequence at a time. Code-level
   enforcement is queued as backlog `snapshot-chain-gap-enforcement`
   (6.5); the pin persistence/recovery ceremony the external seats
   asked about is queued as `snapshot-pin-ceremony` (4.0).
4. **Future-dating boundary evidence** (seat-gpt's HIGH, refuted in
   substance — verify already reports `signed_in_future` beyond the
   300 s skew and `expired` at the MAC-bound expiry, so a far-future
   snapshot cannot stretch the 48 h window): pinned exactly — at
   signed_at−300 s no `signed_in_future`; at −301 s it fires; a
   30-day-future signature fires it immediately.
5. **Tests**: tests/test_signing_state_snapshot.py gains
   Cycle12FixRoundTests (4 tests). Module 40 → 44 tests.

## External seats (delta round, both FIX — reconciled, see R2 record)

seat-gpt FIX 0.91, seat-gemini FIX 0.78. Their one HIGH (future-dated
signed_at) is refuted by the code and now boundary-pinned (item 4);
the timestamp-consistency MEDIUM is closed by fix 1(b) plus the
parser's derivation of last_completed_at from the final entry; the
remaining items are the declared limits (chain completeness, pin
persistence, capture atomicity) — recorded as limits/backlog, not
closures — or rest on the brief rather than the source (both seats
reviewed the change description; seat-gemini's sign_state_files
window concern does not apply to the attested bytes, which are the
exact buffers read). Verdict stays PROVISIONAL until the external
seats re-review this cycle's delta; an external approval would not
have overridden an internal FIX in any case.

## Test totals

Full suite at close: **1081 tests, OK (skipped=2)** — the 2 skips are
the live budget-consumed pair in their by-design post-run state.
Baseline 1075 recorded → 1081: +2 (snapshot test fix) + 4 (this
cycle). Coordinator re-ran the full suite twice this cycle (1077
pre-fix, 1081 post-fix, both ~86 s).

## Self-improvement delta

A payload builder that validates MOST relations still attests the
ones it misses: the re-verification standard is now a self-consistent
MAC over every pairwise relation among the attested facts, probed by
seats who did not write the fix. The loop state and calibration log
can now be attested as exact bytes — the records every scorecard
claim rests on are no longer silently rewritable. Calibration
outcomes for both the original subject (cycle-10b-signed-state) and
this re-review were scored on recording (outcome 1.0).

Next item: production-signed-path-wiring (7.0) — designs preserved in
internal/DESIGN-PRODUCTION-WIRING.md.
