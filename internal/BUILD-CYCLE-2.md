# INTERNAL — Build Cycle 2 Record (do not publish)

Scope: ASI-MAP cross-cutting tracks X2 (sealed evaluation), X3
(self-improvement safety gate), X4 (calibration record), in code.
Built after an external critique was checked and accepted in substance.

## Staffing — restaffed mid-cycle per Dilip's correction
Dilip: ASI is a heavy job, ALL 15 scientists are coders — 5 pods of 3.
Cycle 2 began with 3 lead design seats (A, B, C) before the correction
arrived; the remaining 12 seats were then staffed as full pods, so all
15 seats did coder work this cycle. No seat is recorded that did not work.

- Pod 1 — Sealed registry (eval/registry.py)
  - Seat A (lead): full registry design — EvalRegistry, hash-locked items,
    chained access log, log-before-access, aggregate-only scores,
    compare_gains / compare_reports.
  - Seat A2: hash-locking detail — canonical JSON form, verify on
    register/load/evaluate, mismatch behaviour.
  - Seat A3: access-log detail — entry shape, append-only discipline,
    metadata-only exposure, error redaction.
- Pod 2 — Safety gate (eval/gate.py)
  - Seat B (lead): gate semantics + calibration semantics — epsilon 0,
    per-benchmark regression, anchored forgetting check, single named
    verifier attestation bound to the sealed hash, 18-case test plan.
  - Seat B2: regression/forgetting implementation detail and tests.
  - Seat B3: verifier attestation detail — binding, terminal reject,
    all-reasons-collected decisions.
- Pod 3 — Calibration log (eval/calibration.py)
  - Seat D1 (lead): log design — blind entries, close-discussion
    enforcement, atomic validated persistence mirroring the core loop.
  - Seat D2: outcome scoring — signed/absolute error, Brier, per-reviewer
    stats and weights, dissent-preserving summaries.
  - Seat D3: calibration test plan (8+ named cases).
- Pod 4 — Integration / tests
  - Seat E1 (lead): integration plan — flagged that the core loop picks
    the highest-leverage pending item (phase-handlers, 9), so cycle 2
    must be scanned at leverage 10 to be picked; exports and discovery.
  - Seat E2: registry test plan (8+ named cases).
  - Seat E3: shared-validation and file-layout review (see disagreements).
- Pod 5 — Adversarial
  - Seat C (lead): threat model A9–A27 across X2/X3/X4, with blunt
    stop/detect/neither ratings and 10 adversarial test cases.
  - Seat C2: adversarial tests for registry + gate.
  - Seat C3: adversarial tests for the calibration log.
- Coordinator: froze the reconciled contract, wrote all code and tests,
  ran the suite, records state.

## Discussion / disagreements reconciled
- Epsilon: Seat B argued any drop is a regression (epsilon 0, 1e-9 float
  noise only); salami-slicing makes any positive epsilon gameable (Seat C
  A18 agrees). Adopted: gate raises if a caller passes a non-zero epsilon.
- Aggregate vs per-benchmark sealed scores: Seat A returns aggregate-only
  scores from the registry (per-item results are a gaming oracle, A12);
  Seat B's gate needs per-benchmark maps. Reconciled: the gate is a pure
  function over score maps produced on the verifier side; the registry's
  builder-facing surface stays aggregate-only. The gate never reads
  sealed content.
- Verifier: single named non-builder reviewer with an attestation bound
  to the sealed manifest hash (A19), NOT a majority vote (Seat B over the
  cycle-gate analogy; X4: consensus without independent evidence is none).
- Calibration timing proof: Seat C proposed commit–reveal (A24). Seat B/D1
  design (log-generated timestamps, one entry per reviewer+subject,
  record-after-close rejected, hash-chained entries) adopted for v1;
  commit–reveal deferred to the backlog as an explicit known limit.
- Validation helpers: Seat E3 recommended extracting shared helpers
  instead of duplicating them. Coordinator kept loop-style local copies
  per module (Seats A/B designs, cycle-1 precedent: self-contained files,
  no core->eval coupling). Recorded as a live disagreement; revisit when
  a third consumer appears.
- Calibration entry hash: coordinator found during build that hashing
  outcome fields in the chain hash would break the chain when an
  outcome is attached. As first built, the chain hash covered the
  blind core only and outcome fields were checked arithmetically on
  load. The war room (R4) correctly flagged that as not tamper-evident;
  the shipped code seals outcome fields with a separate outcome hash
  and discussion stamps with a close hash, both checked on load (see
  REVIEW-CYCLE-2.md, fix F4).

## Honest limits (from Pod 5, accepted, not hidden)
- Same-process sealing is API discipline, not a security boundary: code
  running as the same user can read the registry file directly (A9).
- A hash stored beside its content detects careless edits and corruption;
  deliberate tamper-then-rehash is only detectable against an externally
  anchored manifest hash (A10). The manifest hash must be anchored
  outside builder-writable storage to mean more.
- Disjoint ids do not prove independent people/models (A17); independence
  is a process property, evidenced by this record and the review record.
- Access/calibration logs are hash-chained; a whole-directory rewrite is
  detectable only against an anchored chain head (A11/A22).

## Scope built
eval/__init__.py, eval/registry.py, eval/gate.py, eval/calibration.py;
tests/test_registry.py (39), tests/test_gate.py (31),
tests/test_calibration.py (19); cycle-2 modules total 125 tests
including cycle 1's 36. (A tests/test_factory.py module from the
parallel cycle-3 build also sits in the tree; it is not cycle 2.)
Stdlib only, no network, no spending.

## Additions after the build (v3/v4 roadmap items, same cycle)
- Protected Gate Rule (v3, highest value): eval/ and core/loop.py are
  marked protected in eval/gate.py; a self-change whose changed_paths
  touch them is rejected with reason "protected_path", and tests prove
  the gate rejects a change targeting the gate itself. NOTE ON TIMING:
  this landed mid-cycle, while the war room's blind pass was already
  running; reviewers were told, and the verification round re-checked
  it. It is recorded here rather than silently folded into the build.
- Golden set (v4): a never-retired baseline set in the registry
  (add / metadata / evaluate only — no rotation or removal method
  exists), distinct from the rotating sealed set, for drift detection.
- Calibration mechanics (v4): entries carry a role — "dissent" marks
  the one assigned anti-ship seat per review (part of the hashed blind
  core); independent scores are locked by close_discussion before any
  outcome can be recorded; minority_report() tracks the minority
  (reviewers, scores, dates, dissent seats) and, once scored, the
  minority's accuracy against the majority's.
- Verifier rotation/diversity (v4): evaluate_self_change accepts a
  verifier_note that is carried verbatim into the GateDecision record.

## Queued for cycle 3 (not built, logged in state)
- Adversarial Test Factory: sealed tests continuously generated and
  rotated from shifting distributions, old sealed sets retired,
  public-vs-sealed gap widening flagged as gaming.
- Protected-gate full enforcement: the gate marks protected paths in
  this cycle; refusing the write itself (external approval workflow
  for oversight code) is cycle 3.
- Self-mod machinery: one change at a time, canary application,
  rollback to last verified state (the gate is already
  one-proposal/all-or-nothing; the apply/rollback machinery is not
  built).
- Commit–reveal for calibration timing proof (deferred in cycle 2).
