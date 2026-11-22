# Blind review brief — Cycle 15: snapshot pin ceremony

For external war-room seats (seat-gpt, seat-gemini). No internal
verdicts or scores are included in this brief.

## What was built

Cycle 14 made the strict snapshot wrapper refuse candidates more
than one sequence past the caller's pin (`chain_gap`). External
review of cycle 14 split: both seats endorsed the mechanics, one
required a recovery path before production use. Cycle 15 builds
that recovery path as a new module, `signing/pin_ceremony.py`:

1. `advance_pin` — the only normal pin movement: one sequence
   forward, only on verification `()`, only to a candidate chained
   to the pin. Same-sequence/same-hash is an idempotent no-op.
2. `reanchor_pin` — the exceptional movement. Requires all of: an
   operator on a caller-supplied authorised list; an allowlisted
   reason (`initial_anchor`, `chain_gap_recovery`, `lost_pin`,
   `corrupted_pin`); independent evidence (hex64 hash that must
   NOT equal the candidate's payload/state/calibration hashes);
   and a candidate passing every attestation binding under the
   bare verifier. Never backwards, never same-sequence replace,
   and refused when the normal one-step advance would have worked.
3. A MAC-bound audit record for every re-anchor, naming old pin,
   new pin, operator, reason and evidence hash, with explicit
   gap bounds (`gap_from_seq`/`gap_to_seq`) so unobserved
   intermediates stay visible instead of being laundered into
   continuity. `verify_ceremony_record` re-derives it.
4. `classify_verification` — caller contract: `()` → `ok`; sole
   `("chain_gap",)` → `reanchor_required`; anything else →
   `integrity_failure` (never a ceremony trigger).
5. Wording fixes in `signing/state_snapshot.py` per cycle-14
   external review: observable continuity relative to the pin,
   step-observation gating (not a continuity proof), pruned
   snapshot sequences refused regardless of reason, and the
   dense-emission assumption stated as belonging to the
   loop/storage layer, unproven by these modules.

## Questions for the seats

1. Does the ceremony close the cycle-14 liveness trap without
   reopening the laundering gap cycle 14 closed?
2. Is the independent-evidence rule (evidence must not be derived
   from the candidate) strong enough in practice, or theatre?
3. Together with cycle 14, is the pair now reconciled — SHIP or
   FIX for the combined snapshot pin work?

## Test evidence

New module suite `tests/test_signing_pin_ceremony.py`: 13 tests
(classification contract, advance happy/idempotent/refusals,
re-anchor happy paths for gap recovery / initial / lost pin,
seven refusal shapes, no-backwards, ceremony-not-for-normal-
advance, reason/pin coherence, tampered candidate, tampered
audit record). Full-suite total is recorded in
internal/BUILD-CYCLE-15.md.
