# INTERNAL — Build Cycle 1 Record (do not publish)

## Staffing
- Coder Seat A — Correctness (subagent pass): state model, transition table,
  atomic persistence, duplicate/monotonic cycle ids, resume semantics.
- Coder Seat B — Tests (subagent pass): test plan, persistence, phase-order,
  delta, backlog; P0/P1 split.
- Coder Seat C — Adversarial (subagent pass): threat model A1–A8, traversal,
  corrupt state, review forgery, lesson injection, unevidenced improvement.
- Coordinator: froze the shared contract, integrated all three, wrote code.

## Discussion / disagreements reconciled
- Phase list: Seat A had 7 phases incl. DONE/FAILED, Seat B/C used the
  6-phase LOOP.md list. Reconciled: canonical order is
  SCAN -> BUILD -> REVIEW -> FIX_VERIFY -> SELF_IMPROVE -> SHIP -> DONE.
- State shape: A proposed nested per-cycle dicts; B proposed flat state with
  backlog/history/deltas lists. Reconciled: flat persisted store (B) with
  per-cycle gate records (A) kept on the history entry.
- Corruption: A and C both demanded fail-closed, never silent reset.
  Adopted: raise CorruptStateError, quarantine a copy, keep last-good .bak.
- Lessons injection (C, A4): external-scan items carry source_type and are
  not pickable until approved. Adopted in v1 as a pick gate (full lesson
  context-delimiting is a later cycle).
- Delta gaming (C, A5 / B §5): delta requires metric, baseline, after,
  evidence_ref, and a verifier who was not a builder. Adopted.
- Ordering: cycle_seq (monotonic int) is the ordering authority;
  timestamps are UTC ISO-8601, informational only (C, A7).
- Concurrency: A proposed flock single-writer; C agreed. Adopted as a
  best-effort lock file held during save/load critical sections on POSIX;
  not a distributed lock.
- Deferrals (C v2 list): signed state/votes, hash chain, frozen benchmark
  suite, injection classifier, property fuzzing. Logged to backlog.

## Split of work
- A: transition table, invariants, atomic save — integrated into core/loop.py.
- B: tests/test_loop.py (happy path, persistence, ordering, delta, backlog).
- C: adversarial tests in the same suite (traversal, corruption, forgery,
  duplicate seats, split verdict, verifier==builder, dedup, NaN rejection).

## Scope built
core/loop.py (stdlib only), core/__init__.py, tests/test_loop.py.
No network, no chain calls, no spending, no external assets.
State file: <state_dir>/state.json, schema_version 1, atomic replace,
5 MB load cap, NaN/Infinity rejected.
