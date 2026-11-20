# INTERNAL — Build Cycle 5 Record (do not publish)

Scope: selfmod-canary-rollback (leverage 8.5): "Self-modification
machinery: one change at a time, canary apply, rollback to last
verified state." Roadmap v3 mechanism, X3 self-mod safety.

## Why not phase-handlers (leverage 9.0, top of backlog)
phase-handlers would edit core/loop.py, which eval/gate.py lists in
PROTECTED_FILES. The Protected Gate Rule (ROADMAP v3) forbids the
system modifying its own judge without Dilip's explicit approval +
external review. The item is marked BLOCKED in state (not done, not
dropped) pending that approval, and this cycle took the next highest
non-protected item. This is the gate working as designed.

## Staffing — all 15 seats, 5 pods of 3 coders (design phase)
Five pod agents designed in parallel, each pod's 3 seats with
distinct angles; coordinator reconciled, wrote the code and tests.
- Pod A Foundation (1, 5, 8): content-addressed snapshot, hash-chained
  journal, pointer-level atomicity, crash-recovery rollback.
- Pod B Memory & World (2, 6, 7): canary as counterfactual run,
  golden fail-fast, persisted manager state, deterministic recovery
  (mid-promotion auto-rollback).
- Pod C Agents & Tools (9, 10, 11): API surface, one-at-a-time in 3
  layers, budgets (reconciled 8 files / 64 KiB file / 256 KiB total),
  no queue, selfmod/ protected in v1.
- Pod D Safety & Eval (3, 4, 15): commit bound to a GateDecision,
  Tier A (gate) + Tier B (local) protected paths, canonicalise before
  the gate check, unsigned-decision forgery limit stated.
- Pod E Action (12, 13, 14): single module selfmod/canary.py,
  creation supported, DELETION REFUSED in v1, constructor fails
  closed with NeedsRecoveryError, explicit recover().

## Reconciled design choices
- Single module (Pod E) over multi-file layout (Pod B); journal_dir
  must be outside the target tree.
- Content binding via verifier_note first segment
  "content-hash:<candidate root hash>" (cycle-4 pattern, Pod D).
- No deletion in v1 (Pod E over Pod C's delete op): FileChange with
  new_bytes=None raises deletion_not_supported_in_v1.
- Modes: existing files keep pre-image mode; creates are 0o644;
  a change cannot express a mode change in v1 (documented limit).
- Recovery entry point added in the war-room fix round:
  CanaryManager.recover_journal() classmethod.

## Scope built
- selfmod/canary.py: CanaryManager — stage (validate, canonicalise,
  protected check Tier A+B incl. bare names, budgets, tree caps,
  snapshot pre-image atomically, full-tree canary copy outside the
  tree, journal append last with cleanup-on-failure), mark_verified,
  commit (decision re-validation against recomputed root hash,
  canary per-file hash + symlink walk, protected re-check, drift
  check bytes+mode, per-file re-resolve + re-check before replace,
  write-ahead COMMITTING journal, post-verify against staged
  hashes, auto-rollback wrapped in CanaryError), rollback (bytes+
  mode exact, prunes only non-pre-existing dirs), abort,
  recover_journal. Hash-chained journal with digest, duplicate-key
  and non-finite rejection, quarantine on parse failure, soft cap
  200 with lifecycle reserve + exemption, hard cap 264.
- selfmod/__init__.py: 13 exports.
- tests/test_selfmod_canary.py: 58 tests. Full suite: 328 tests,
  all passing (was 270; pre-existing tests untouched). No protected
  file was edited: eval/ and core/loop.py are unchanged.

## Self-improvement delta
tests_passing 270 -> 328 (+58), verified by rev-r1 in the war-room
verification round (mutation + probe evidence in REVIEW-CYCLE-5.md).
Process delta: the war room caught a tautological self-comparison
in the first commit implementation (canary verified against
itself) — the pattern "expected values must come from the journal
record made at decision time, never re-derived from the artefact
being checked" is now recorded here and in the module docstring for
future cycles.

## Honest limits
All module-docstring limits stand: forged GateDecision (A30 class)
not cryptographically stopped; canary is a copy, not a sandbox;
rollback restores files only; decision portable across trees with
same proposal id + bytes; single-writer assumed, no file lock;
journal/snapshot retention unpruned (compaction queued as
selfmod-journal-compaction, 5.5).

## Scorecard (ASI map, after cycle 5)
1 Autonomous research ~10% (no change this cycle)
2 Autonomous building ~35% (+: a full design->build->review->fix
  cycle ran with 15 coder seats + 6 reviewers, all findings fixed)
3 Self-improvement ~30% (+: the machinery that makes self-change
  safe now exists and is itself war-room verified; gains still
  require signed decisions to be fully proven — queued)
4 Long memory + world model ~30% (P2 done cycle 4, unchanged)
5 Action with guardrails ~30% (+: canary/rollback guardrail live)
Phase status: P1 exit met cycle 3-4, P2 exit met cycle 4; this
cycle builds P5 prerequisites (X3 machinery). Next unblocked item:
protected-gate-enforcement (8.0) — the workflow that would let
phase-handlers proceed with Dilip's approval; then
signed-gate-decisions (7.5), signed-state (7.0).
