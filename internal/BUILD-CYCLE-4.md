# INTERNAL — Build Cycle 4 Record (do not publish)

Scope: P2 — Memory That Works (ROADMAP-NEW.md). Backlog item
memory-store-p2: "Long-term memory store with gated writes and
sealed reuse test". P2 exit: same task scores better 2nd time from
memory alone, on sealed tasks.

Numbering: this is build cycle 4 and CoreLoop state cycle 4. The
factory build took the CYCLE-3 record files and state cycle 2; the
eval build (chat "cycle 2") is state cycle 3 — the overlap is
explained in that cycle's delta evidence and in REVIEW-CYCLE-3.md.
This cycle's numbering is consistent across its record files and
its state entry; no renumbering of earlier cycles.

## Staffing — all 15 seats, 5 pods of 3 coders
- Pod A Foundation (1 Chief, 5 Model Builder, 8 Compute):
  persistence slice — seat-1: file layout, exact-key validation,
  atomic save, fresh/corrupt behaviour, state digest; seat-5:
  two-level hashing (content hash over proposer fields, entry hash
  binding seq/prev/created_at) + tamper matrix; seat-8: registry
  locking copied exactly (directory-fd flock, freshness guard,
  per-instance serialisation) + caps.
- Pod B Memory & World (2 AGI Science, 6 World Models, 7 Spatial):
  memory semantics — seat-2: entry model, provenance semantics,
  strategy-only kinds in v1, single current head per (domain,kind);
  seat-6: supersede rules R1–R10 (current-at-commit, same
  domain+kind, forks rejected, immediate-predecessor chains);
  seat-7: retrieval API (exact-match filters, commit order, deep
  copies, no read logging, both reuse controls).
- Pod C Agents & Tools (9 Coding Agents, 10 Framework, 11 Open
  Models): solver slice — seat-9: anchored fullmatch detection per
  family, naive behaviours, solve() never raises (returns "");
  seat-10: per-family token vocabulary incl. wrong-extra tokens,
  whitelist dispatch, explain() audit surface; seat-11: lesson
  derivation from public items only (classify-don't-trust-domain,
  MIN_ITEMS=4, margin >= 2 items and >= 0.25, tie abstention,
  per-family audit records).
- Pod D Safety & Eval (3 Safety, 4 Scaling/Eval, 15 Future & Risk):
  seat-3: gated-write mapping onto eval/gate.evaluate_self_change
  (sequential per-lesson gating, baselines advance only on accept,
  golden capability maps, changed_paths always supplied) + poison
  cases with expected gate reasons; seat-4: sealed reuse protocol
  (100/100 batches, >= 12/family floor, prompt-overlap rejection,
  min_delta 0.02, instrumented-adapter per-family maps
  cross-checked against registry reports, exact-equality controls,
  pass/fail rule); seat-15: threat model A28–A44 with required
  docstring limit statements.
- Pod E Action (12 Robotics, 13 Voice, 14 Product): seat-12:
  adversarial store test plan (per-field tamper, rollback, forged
  decision, races); seat-13: reuse/solver integration test plan
  (floors not exact counts, controls exact, accepted families set);
  seat-14: package exports + edge cases + full-suite delta check.
- Coordinator: froze the contract, reconciled disagreements (below),
  wrote memory/ + tests, ran the suite and the measurement.

War room: 6 fresh reviewer seats (rev-r1..rev-r6, none of them
builders — the cycle-2 pattern for a 15-coder cycle), blind first,
one assigned dissent seat, scores locked in the calibration log
(subject "cycle-4-build") — see REVIEW-CYCLE-4.md.

## Discussion / disagreements reconciled
- nth-word out-of-range (k == size, naive zero-indexed): seat-10
  proposed modulo wrap; seat-9 proposed "". Adopted "": wrap invents
  behaviour nobody froze; "" is deterministic, never accidentally
  correct, and matches the unknown-prompt rule. Also adopted from
  seat-9 over seat-10: solve() never raises (a scorer exception
  aborts a whole registry evaluation); explain() still reports
  family=None for unclassifiable prompts.
- Entry schema: seat-1's "key"/"source_ref" shape vs the frozen
  contract's domain/author/source/evidence_ref/verifier_id.
  Adopted the contract + seat-2's provenance semantics; seat-1's
  seq, exact-key validation and single-use proposal ids adopted.
- Content hash fields: seat-1 included created_at; seat-5 excluded
  store-assigned fields so the hash is computable pre-commit.
  Adopted seat-5 (two-level: content hash over proposer fields with
  a version tag; entry hash binds seq, prev_hash, content_hash,
  created_at, id).
- Proposal replay (seat-15 A34, seat-1): proposal ids are unique
  per entry and ids are unique. As first built, the decision bound
  only proposal id + verifier id — the war room (R2/R3/R6, finding
  F1 in REVIEW-CYCLE-4.md) proved a genuine decision could be
  redirected to a different entry and falsified this paragraph's
  original claim. Fixed in the review round: decide_write stamps
  the entry's content hash into the decision's verifier_note and
  commit_write refuses any decision not carrying the presented
  entry's hash, so one accepted decision commits exactly the one
  entry it was issued for. The residual — a hand-constructed
  GateDecision (A30) — is NOT stopped (the hash is computable by
  anyone holding the entry) and is documented + pinned by
  test_commit_fake_gate_decision_not_stopped.
- Kinds: seat-1's open enum (fact/procedure/episode) vs seat-2's
  strategy-only v1. Adopted seat-2: kinds beyond "strategy" are
  rejected at write and on load; adding a kind is a schema
  decision for a later cycle, not a new string.
- Derivation best-score floor: seat-11 leaned toward adding
  best_score >= 0.75 (a "correct" token right only half the time
  signals a parser bug). Adopted (MIN_BEST_SCORE = 0.75).
- Content cap: seat-8 proposed 4000; the frozen contract and
  seat-2 said 2000 (loop MAX_TEXT precedent). Adopted 2000, with
  seat-12's newline carve-out: content may contain "\n"; all other
  text fields keep the registry's strict rule.
- Domain cap: seat-8 proposed 64; adopted the registry's 200
  (domains may carry provenance-like labels later).
- Seat-8's dir-fd-relative os.replace hardening: NOT adopted this
  cycle — the registry's reviewed pattern (inode re-check before
  path-based replace) is copied exactly; the hardening is queued
  in the backlog instead of smuggled in unreviewed.
- Multiple current lessons per family (seat-10 last-write-wins):
  the store's single-head rule makes it unreachable through
  commit_write; the solver still resolves deterministically (last
  valid token in retrieval order wins; invalid tokens filtered
  before ranking) for override lists.
- Seat-4 vs seat-3 capability maps: seat-4 sketched capability =
  sealed maps at last accepted commit; adopted seat-3's golden-set
  capability maps (the gate's forgetting semantics: a frozen
  capability snapshot, advanced only on accept).

## Scope built
- memory/store.py: MemoryStore — one JSON doc (memory.json),
  atomic save under directory-fd flock with freshness guard,
  deep validation on load (exact keys, contiguous seq, content/
  entry hash recompute, supersede graph, single-head rule, state
  digest), gated commit_write (accepted GateDecision bound by
  proposal id + verifier id + the entry's content hash stamped
  into the decision's verifier_note, decision internally
  consistent, verifier != author, single-use proposals),
  decide_write() wrapping evaluate_self_change with
  changed_paths always supplied, retrieval/get/history reads,
  state_digest()/chain_head() anchoring accessors.
- memory/solver.py: StrategySolver — anchored detection for the 7
  factory families, naive strategies, per-family token vocabulary
  (naive/correct/wrong-extra), whitelist lesson dispatch,
  explain() audit, solve_with_strategy(), derive_lessons() with
  per-family audit records.
- memory/reuse.py: run_reuse_measurement() — the P2 exit protocol
  (see its docstring), ReuseError on dishonest setup.
- memory/__init__.py: exports in eval/__init__ style.
- tests/test_memory_store.py (64), tests/test_memory_solver.py
  (28), tests/test_memory_reuse.py (18). Full suite: 270 tests,
  all passing (was 160; the 160 pre-existing tests are untouched).
  The war-room fix rounds added 20 tests pinning its findings
  (17 in the main fix round, 3 in the verification round).

## The sealed reuse measurement (coordinator run; seeds:
## public "p2-public-7f3a91c2e4", sealed "p2-sealed-bb2002",
## golden "p2-golden-09c4d6e2f1" — chosen on floor/overlap
## criteria before any scores were seen; an earlier sealed
## candidate was rejected for sharing 2 prompts with the public
## batch, and that colliding pair is now a refusal test)
- public_before 20/100 -> public_after 100/100
- sealed_before 20/100 -> sealed_after 100/100 (delta +0.80)
- verdict: compare_reports accepted, reason both_improved
  (min_delta 0.02)
- controls: empty-memory rerun 20/100, retrieval-disabled rerun
  20/100 — both exactly the baseline
- lessons: largest->scan-max, nth-word->one-indexed,
  reverse->full-reverse, sequence->plus-step — all proposed by
  derivation and accepted by the gate individually;
  subtract-multiply: derivation decision naive_best (no lesson);
  parity/arithmetic: never proposed (no public evidence)
- per-family sealed: largest 0.227->1.0, nth-word 0.0->1.0,
  reverse 0.0->1.0, sequence 0.0->1.0, parity 1.0->1.0 (untouched
  control family, flat)
- sealed evaluations used: 8 (baseline + 4 candidate + after +
  2 controls), all through the registry's logged path. The
  per-family map join additionally regenerates the sealed batch
  from its seed in-process; that access is not an evaluation and
  is not in the count (disclosed in reuse.py's docstring).
- passed: True, invalidated: False
- independently reproduced by war-room reviewer R4: 8 fresh seed
  triples all reached 100 with controls exact, and the shipped
  store scored 24->100 and 29->100 on two sealed batches it was
  never gated on (untouched holdouts).

## Honest limits (stated in code docs, not hidden)
- Forged GateDecision (A30): commit_write checks consistency of
  the decision object, not provenance; in-process code can build
  an accepted one — including the content-hash binding, which is
  computable by anyone holding the entry. Same for fabricated
  attestations fed to the gate (gate.py's trusted-inputs limit,
  inherited).
- Self-attested measurement (war-room R6 F2): in the shipped
  reuse run, the gate attestation is constructed by the harness
  itself inside run_reuse_measurement; reward_hacking_checked is
  asserted, not performed by any check code, and no independent
  verifier process exists in the run. The verifier separation is
  a protocol role played in-process. Disclosed in reuse.py's
  docstring.
- Golden forgetting blind spot: the golden set is a generation-0
  batch (arithmetic, subtract-multiply, reverse, largest,
  sequence); the gate's forgetting check never sees nth-word or
  parity. Disclosed in reuse.py's docstring.
- Timestamps (created_at, attested_at) are local host-clock
  assertions, checked for form only; ordering is by seq.
- The same post-replace fsync window R1 found in store.py (M1,
  fixed here) exists in eval/registry.py's save path: if the
  directory fsync fails after os.replace, the registry instance's
  in-memory digest bookkeeping has the same shape. Flagged, not
  fixed — eval/ is protected-path and out of this cycle's scope;
  queued for a reviewed fix.
- Rollback / full rehash (A29/A32): an older valid file, or a
  fully rehashed rewrite, loads cleanly on a fresh instance;
  detection requires anchoring state_digest()/chain_head()
  externally. Both behaviours are pinned by tests that document
  them as limits, not as protections.
- Poison that helps the measured sets (A33/A35): a lesson that
  improves public+sealed now but encodes a wrong off-distribution
  rule passes the gate by design; the defence is process (factory
  rotation, golden set, later wild tasks), not this gate.
- Derivation is selection over a hand-built hypothesis space
  (seat-11's honesty boundary, in solver.py's docstring): the
  gain proves transfer to unseen items of the same seven factory
  families under the factory's scale shift — not to unseen task
  types.
- Retrieval returns lessons as untrusted data; a committed,
  current, wrong lesson steers the solver (A41) — the write gate
  and supersede path are the mitigations that exist in v1.

## Queued next (scanned into state this cycle)
- memory-consolidation (6.0): consolidation, pruning and
  re-derivation policy for stale lessons; retrieval caps per
  source (A42).
- signed-gate-decisions (7.5): signed gate decisions so a memory
  commit can prove the gate ran (closes A30 properly). The
  signature must cover the decision INCLUDING its content-hash
  binding segment — signing the current decision fields without
  the binding would still permit genuine-decision redirection
  (war-room R2 F1).
- dirfd-replace-hardening (5.0): seat-8's directory-fd-relative
  os.replace for registry + memory stores.
Top of the pre-existing backlog remains phase-handlers (9.0).
