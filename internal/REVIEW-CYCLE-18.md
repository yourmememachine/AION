# REVIEW — Cycle 18: journal-integrity error type war room

Blind internal reviewers (scores before reconciliation).
External seats seat-gpt / seat-gemini: VACANT this detached
run (brief at internal/CROSS-CHECK-BRIEF-CYCLE-18.md), so
the verdict is PROVISIONAL. Cycles 14+15+16 remain held on
the Protected Gate decision; cycle 17's external split is
the subject of this cycle and goes back to both external
seats with this delta.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | integration / correctness | 0.88 | SHIP |
| rev-r2 | adversarial / safety | 0.74 | FIX |
| rev-r3 (seat 15) | forced dissent | 0.58 | FIX |
| rev-r4 | API / consumer contract | 0.82 | FIX |
| rev-r5 | test quality | 0.84 | FIX |
| rev-r6 | scope / honesty | 0.92 | SHIP |
| re-verification seat | fix round | 0.93 | SHIP |

Reconciled verdict: **SHIP, PROVISIONAL** — every code
finding below was fixed and re-verified in the fix round
(targeted suites 176 OK; full suite 1245 OK, skipped=26).
rev-r3's structural dissent is preserved, not overridden:
the outcome model is still non-uniform (list vs raise),
the state-dependence and ship/tx asymmetry are labelled,
not cured, and no in-tree caller yet discriminates the new
type — the external seats judge whether that reconciles
their cycle-17 split.

## Findings and dispositions

- rev-r2 F1 / rev-r4 F1 / rev-r1 F2 → CLOSED. Constructor
  now validates: reasons must be canonical chain-mismatch
  reasons only (operator reasons refused), anchor_sources
  non-empty, deduped, labelled ship:/ship-tx: with suffixes
  matching the reasons exactly, bare-string containers
  refused for all fields. Re-verification seat re-probed
  every hole (operator reason, unknown source, mismatched
  suffix, empty sources) — all ValueError.
- rev-r4 F2 / rev-r1 F5 → CLOSED. `__reduce__` via a module
  restore helper: pickle and deepcopy round-trip type,
  reasons, sources, outcomes, anchor_errors and message.
- rev-r2 F3 / rev-r1 F3 → CLOSED. Pre-settlement raise now
  carries ship-anchor park reasons from the same call
  (labelled sources, "combined", message clause), while
  still firing on tx reasons alone; integrated combined
  test added (rev-r5 F4).
- rev-r2 F4 / rev-r3 #5 → CLOSED. The error-only
  post-settlement branch's plain AnchorError now carries
  `.outcomes`; settlements are recoverable from the
  exception on both branches.
- rev-r2 F5 / rev-r5 F3 → CLOSED. Mixed post-settlement
  case tested: park reasons in `.reasons`/`.anchor_sources`,
  the new anchor-load failure in `.anchor_errors` and the
  message, never in `.reasons`.
- rev-r5 F5 → CLOSED. No-new-reason negative test: a
  re-verification returning an already-seen reason parks
  without raising.
- rev-r5 F1/F6, rev-r4 F3/F4 → CLOSED. Exact-type
  assertions added; `JournalIntegrityError` added to
  `trust/__all__`; handler-order rule (subclass before
  AnchorError) stated in the class docstring.
- rev-r3 #1–#4, #8 (structural) → PRESERVED as dissent.
  Non-uniform outcome model, run-history dependence and
  the ship/tx asymmetry survive by design this cycle; the
  combined-source case is now produced through recover()
  (fix-round tests), answering #8's integration half.
- Pod D design-stage silent-[] holes (operator-error /
  same-file evidence with no transaction) → RECORDED as a
  follow-on in BUILD-CYCLE-18.md, not silently dropped.

## Verification

- New/extended suite: 58 tests OK. Targeted suites: 176 OK.
  Full suite, final tree: **1245 tests, OK (skipped=26)**
  (baseline 1228 → +17), confirmed independently by the
  re-verification seat.
- No protected paths touched; no push from this run; loop
  state recording deferred to the signed ship path
  (cycles 14–17 precedent).

Verdict: **SHIP, PROVISIONAL** (external seats vacant;
rev-r3 dissent preserved; follow-ons named).
