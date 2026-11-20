# INTERNAL — Build Cycle 6 Record (do not publish)

Scope: protected-gate-enforcement (leverage 8.0): "Protected gate
enforcement: external approval workflow for oversight code changes."
Roadmap v3 Protected Gate Rule; X1 scalable oversight.

## Why this item
phase-handlers (9.0) stays BLOCKED: it edits core/loop.py, a protected
file, and may only proceed through an approval workflow with the
owner's explicit approval + external review. This cycle built that
workflow, so the blocked item now has a legitimate path. The workflow
itself was built OUTSIDE protected scope (new package oversight/) and
no protected file was edited: eval/ and core/loop.py are unchanged.

## Staffing — all 15 seats, 5 pods of 3 coders (design phase)
Five pod agents designed in parallel; coordinator reconciled, wrote
the code and tests.
- Pod A Foundation (1, 5, 8): approvals/ package, pure decision +
  journaled manager, locking, candidate hash strengthened with
  pre-image + expiry binding, CONSUMING recovery.
- Pod B Memory & World (2, 6, 7): non-portable binding, state-based
  staleness, rejection-learning, external must be truly external
  (signed, out-of-process) — accepted as the documented v1 limit and
  the signed-decisions backlog item, not faked in v1.
- Pod C Agents & Tools (9, 10, 11): pure evaluate vs journaled
  consume split, no-bypass API rules, burn-on-consume with no refund.
- Pod D Safety & Eval (3, 4, 15): oversight/ name, local Tier-B
  protection of the enforcer itself, quorum arithmetic, honest
  forgery limit as a v2 signing requirement.
- Pod E Action (12, 13, 14): human-readable flow, fail-closed
  interlock, consume atomicity, retention/compaction concern (the
  journal cap finding later confirmed it).

## Reconciled design choices
- Single module oversight/approval.py (repo pattern: gate.py,
  canary.py, store.py are single-module) over multi-file packages.
- Protected scope single-sourced from eval.gate.check_protected_paths,
  plus local scope: oversight/ prefix and the bare name "oversight".
- Every path in a request must be protected; mixed changes refused.
  Deletion refused (candidate must be bytes).
- Content hash: domain-separated "protected-candidate-v1" over
  proposal id + expiry + per-path (pre-image hash/absent, candidate
  hash, size). Effective expiry = min(request, owner leg, external
  leg); boundary instant is expired; re-checked at consume.
- Roles: owner is the configured OWNER_ID ("dilip"); owner may not be
  author or builder; external reviewer may not be owner, author or
  any builder; builders >= 3 distinct; reward-hacking check and an
  independence note (carried verbatim, form-checked) required.
- Consumption is journaled before the receipt is returned and is
  never refunded; receipt carries effective expiry + pre-image hash.

## Scope built
- oversight/approval.py: pure evaluate_approvals (advisory only) +
  ApprovalManager — create_request, record_owner_approval,
  record_external_review, evaluate, state, status, consume, revoke,
  history, state_digest. Hash-chained journal with whole-journal
  digest, strict load (duplicate keys, non-finite, seq, chain,
  used-id derivation), replay state-machine validation, quarantine on
  corruption, flock + on-disk head check before every save,
  os.replace as the commit point with disk reconciliation on
  post-replace failure, rollback on pre-commit save failure.
- oversight/__init__.py: 23 exports.
- tests/test_oversight_approval.py: 51 tests. Full suite: 379 tests,
  all passing (was 328; pre-existing tests untouched).

## War room outcome (see REVIEW-CYCLE-6.md)
Blind round: 6/6 FIX. All findings reconciled into one fix list and
implemented; verification round 1: V2 SHIP, V3 SHIP, V1 FIX on two
edge blockers (deny two-append atomicity, post-replace fsync
phantom); both fixed (deny derived from the leg in one append;
commit-point reconciliation) plus replay hardening (consumed
requires both approve legs). Verification round 2: V1b SHIP, high
confidence, 38/38 probes. Final verdict: RECONCILED SHIP.

## New backlog from this cycle
- gate-path-canonicalisation (7.0, BLOCKED pending owner approval):
  the war room found eval/gate.py's own protected check does not
  canonicalise (core/./loop.py evades it) and does not cover
  oversight/. Fixing it edits a protected file — it is exactly the
  first change that should go through this new workflow once signed
  decisions land.
- oversight-journal-compaction (5.5): the journal halts at ~49 full
  request cycles; no compaction routine exists yet (documented in the
  module docstring as a hard limit).

## Self-improvement delta
tests_passing 328 -> 379 (+51), verified by rev-r1 (calibration and
verification records in REVIEW-CYCLE-6.md). Process delta: two new
patterns recorded — (1) a terminal transition must be derivable from
a single journaled record, never written as a second append that a
crash can strand; (2) in any replace-based store, os.replace is the
commit point: after it, reconcile from disk instead of rolling back
memory. The war room also caught that a prefix-matched reason filter
silently dropped unprefixed failure reasons — record-time validation
must enumerate reasons attributable to the artefact, never pattern-
match their names.

## Honest limits
All module-docstring limits stand: approvals are unsigned (forgery
class shared with the canary journal; signed decisions are the next
backlog item at 7.5); journal chain/digest are unkeyed and in-file,
so a recomputing rewrite or outright deletion is undetectable —
state_digest() is exposed for external anchoring; timestamps are
caller/host-asserted; cross-machine shared journal dirs unsupported;
journal lifetime ~49 cycles until compaction exists.

## Scorecard (ASI map, after cycle 6)
1 Autonomous research ~10% (no change this cycle)
2 Autonomous building ~38% (+: a second consecutive full
  design->build->review->fix->verify cycle with 15 coder seats,
  6 blind reviewers and two verification rounds)
3 Self-improvement ~32% (+: the approval workflow that gates
  self-changes to the judges now exists and is itself verified;
  signed decisions remain the open proof gap)
4 Long memory + world model ~30% (unchanged)
5 Action with guardrails ~35% (+: protected-change guardrail live,
  with locking, single-use consumption and replay validation)
Phase status: P1/P2 exits met earlier; this cycle completes the
protected-gate prerequisite for P5. Next unblocked item:
signed-gate-decisions (7.5), then signed-state (7.0);
gate-path-canonicalisation (7.0) is blocked on owner approval;
phase-handlers (9.0) remains blocked on the same gate.
