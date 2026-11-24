# CROSS-CHECK-22 — Cycle 28 external seats (pin-store history reconciliation)

Blind brief: internal/CROSS-CHECK-BRIEF-CYCLE-28.md (no internal
verdicts or scores). Both seats sat on Dilip's Google login.

## seat-gpt — first round: FIX 0.91

Architecture sound; Q2 (wiring-dependent detection) accepted
with a production-construction audit condition; Q3
(reconciliation over anchoring) accepted. Blocking Q1 finding:
the known-unadopted head excuse is an assertion, not proof —
a consumed authorisation whose movement was adopted, whose
pending-journal "adopted" line is lost (interrupted cleanup),
combined with a pin-store restore to a pre-adoption
generation, would be excused at the head even though its
record is missing from the store: the exact disappearance
the cycle exists to detect. Asked for lifecycle evidence /
crash-injection tests, or narrowing of the excuse.

## seat-gemini — first round: SHIP 0.84

Excuse set largely sound; independently constructed the
SAME stale-pending head scenario, rated non-blocking
(head-only scope cannot mask gaps behind the head) with a
lifecycle-tightening suggestion. Accepted wiring-dependent
detection (same unwired-caller caution) and reconciliation
over a head anchor.

Convergence: both seats named the same scenario; per the
standing rule an external SHIP does not override a FIX, so
seat-gpt's FIX governed and a fix round ran.

## Fix round (internal/cycle28-work/fix-round-gpt.md)

- Reproduction, failing-first: GPT's compound scenario
  reproduced pre-fix (adopted line stripped + store restored
  to genesis + wired attempt beyond the head: excused, no
  refusal). Controls: store-only restore with intact pending
  journal already refused pre-fix (an adopted ceremony is
  never a genuine burn); pending-journal rollback combined
  with a store restore already refused.
- Fix: the known-unadopted head excuse is narrowed to
  candidates AT the head entry's own sequence
  (E.new_cycle_seq == candidate_seq); the beyond-head reach
  is removed. The compound state is indistinguishable from a
  genuine burn in every source the reconciliation layer has,
  so no corroborating guard inside the layer can separate
  them; the verifier's head rules already force recovery or
  supersession before the head moves.
- Recorded cost: a genuine beyond-head burn (13→15 burn,
  candidate 16) now refuses pin_store_history_incomplete
  instead of reaching the supersession-pending stop —
  operator-reconciliation residual, recorded in
  BUILD-CYCLE-28.md.
- Q2 audit: exactly one production construction site
  (trust/runner.py main) and it wires both providers; the
  factory is pass-through only; no direct production
  PinAdopter construction exists.
- Internal re-review of the narrowing: SHIP 0.90.
- Final suite: 1812 tests OK (skipped=28).

## seat-gpt — delta re-review: SHIP 0.96

"This closes my previous FIX. I ratify the narrowed
known-unadopted exception and accept the recorded
operability cost." The narrowing removes the dangerous
permission instead of pretending to distinguish states the
available evidence cannot distinguish; the three lifecycle
tests and the Q2 audit close its objections; no external
pin-store anchoring and no universal constructor enforcement
required. FIX withdrawn; pin-store-history-reconciliation
considered closed.

## Final verdict

SHIP — reconciled. Internal war room SHIP (REVIEW-CYCLE-28),
seat-gemini SHIP 0.84, seat-gpt FIX 0.91 → fix round →
SHIP 0.96. Final suite 1812 tests OK (skipped=28). Real
state/state.json not advanced (sha256 verified identical).
