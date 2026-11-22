# BUILD — Cycle 15: snapshot pin ceremony

Item: backlog `snapshot-pin-ceremony` (seq 35). Chosen over
`pick_next()` leverage order because CROSS-CHECK-8 (cycle 14
external seats) routed it explicitly: both external seats named
the ceremony the most important outstanding trust item, Gemini's
FIX made cycle 14 a split decision, and the route was "next
cycle builds snapshot-pin-ceremony … Cycle 14 + the ceremony
then go back to both seats together."

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15), design round before code:
- Pod A (1, 5, 8): module shape — new `signing/pin_ceremony.py`,
  no changes to the verifier's pin format.
- Pod B (2, 6, 7): caller contract — three-bucket classification
  separating re-anchor-required from integrity failures.
- Pod C (9, 10, 11): implementation — advance_pin as the only
  normal movement; reanchor_pin returning (new_pin, MAC-bound
  audit record) or raising, never a partial result.
- Pod D (3, 4, 15): adversarial map — relabelling, self-derived
  evidence, fork-riding, record forgery, inconsistent reads.
- Pod E (12, 13, 14): consumers — zero production callers today;
  wording fixes in state_snapshot docstrings; records inventory.

War room: 3 live blind reviewer seats run this cycle (rev-r2
adversarial 0.50 FIX, rev-r3 forced dissent 0.35 FIX, rev-r5
test/integration 0.82 FIX-test-only), reconciled below; the
remaining internal seats' scores are recorded in the review
record as not separately seated this run — no fabricated scores.
External seats: blind brief saved at
internal/CROSS-CHECK-BRIEF-CYCLE-15.md; neither seat reachable
from this detached run, both recorded VACANT, verdict
PROVISIONAL. Cycle 14 + 15 go back to both seats together, per
the CROSS-CHECK-8 route.

## What was built

1. `signing/pin_ceremony.py` (new): `advance_pin` (one-step,
   ()-only, chained, binding-checked, capture-once),
   `reanchor_pin` (authorised operator, allowlisted reason,
   independent-evidence non-equality check incl. snapshot_id,
   candidate must pass every attestation binding; never
   backwards/same-seq; with a usable pin present the ONLY reason
   is chain_gap_recovery and it requires a strict result of
   exactly ("chain_gap",); pin+1 unchained = integrity failure,
   refused), `PinCeremonyRecord` with explicit gap bounds,
   `verify_ceremony_record` (MAC + full invariant re-validation),
   `classify_verification` (ok / reanchor_required /
   integrity_failure).
2. Wording fixes in `signing/state_snapshot.py`: observable
   continuity relative to the pin; step-observation gating, not
   a continuity proof; pruned snapshot sequences refused
   regardless of reason; ceremony now referenced as built.
3. Exports added in `signing/__init__.py`.

## Fix rounds (war room)

- rev-r3 dissent: pin+1 fork riding the ceremony → refused;
  gap recovery gated on an actual ("chain_gap",) strict result;
  evidence-independence and pin-marker limits stated honestly
  in the docstring (non-equality only; pin carries no marker —
  pin-format change is future work).
- rev-r2: F1 reason relabelling (lost/corrupted with a present
  pin) → refused, gate is on state not label; F2 snapshot_id
  added to the evidence blocklist; F3 advance_pin now honours
  pin key/signer bindings; F4 verify_ceremony_record
  re-validates reason/evidence/sequence/id invariants; F5
  advance_pin returns capture-once locals, never re-reads.
- rev-r5: missing branch tests added (unknown_key,
  calibration-hash evidence, malformed pin, corrupted_pin,
  classification duplicates/list input).

## Tests

- New suite tests/test_signing_pin_ceremony.py: 15 tests.
- Signing suites combined: 76 tests OK.
- Full suite final tree: **1177 tests, OK (skipped=26)**
  (baseline 1162 → +15; pre-fix-round run was 1175).

## Recording status

Loop state (state/state.json) NOT advanced by this run, as in
cycle 14: recording is left to the signed ship path in the main
chat. Backlog items snapshot-chain-gap-enforcement (34) and
snapshot-pin-ceremony (35) therefore still read `pending` in
loop state while built, reviewed and green in the tree.
No commit, no push from this run.

## Self-improvement delta

tests_passing 1162 → 1177 (coordinator full-suite run on the
final tree; verifier: the war room's non-builder seats).
Process lesson: gate on state, not on labels — any check keyed
to a caller-supplied reason string can be defeated by changing
the string; and a verifier for an audit record must re-validate
the invariants, not only the MAC.
