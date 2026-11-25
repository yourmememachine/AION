# CROSS-CHECK — Cycle 30 external seats

Brief: internal/CROSS-CHECK-BRIEF-CYCLE-30.md (blind, no internal
verdicts). Reviews ran before the internal fix round; the fix
round's counting-provider and consumed-envelope assertions address
Gemini's consume-1 watch-item and ChatGPT's independent-counters
note.

- seat-gpt — SHIP 0.94. Resume-only justified within the sequential
  wired scope; seeded state legitimate as a persisted
  recovery-boundary state; no vacuous assertions seen; concurrency
  residual should not block closure — record it separately. Noted
  it could not independently verify the three traces from the
  brief alone.
- seat-gemini — SHIP 0.78. Same scoped conclusion; seeded state
  "constructed, acceptable if every seeded field satisfies
  production invariants"; watch-item: verify consume 1 is a real
  pre-commit attempt, not a no-op counter (addressed in fix round
  by consumed_authorisation_ids pin); resume-to-resolution not
  tested (re-pend only — accepted scope).

Both external seats SHIP, reconciled with the internal fix round.
