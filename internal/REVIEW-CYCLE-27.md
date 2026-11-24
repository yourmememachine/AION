# REVIEW — Cycle 27 war room (ceremony journal anchoring)

Six internal seats, blind, independent scores recorded
before discussion; seat rev-r6 held the forced-dissent
slot. Full seat texts in internal/cycle27-work/
(review-r1..r6.md, rereview-*.md).

## First round — SPLIT

- rev-r1 — SHIP 0.88 (loader correctness; parity with the
  cycle-22 consumption block verified check-for-check;
  distinctness code-complete over all pairs).
- rev-r2 — SHIP 0.92 (commit orders and failure semantics
  correct; no silent anchor skip — exactly one production
  append site per journal, each followed by its anchor
  advance; two minor notes, one taken: the supersede
  docstring step list).
- rev-r3 — FIX 0.80 (no production defect; test gaps:
  INIT discrimination never tested, production gate
  tested for issuance only, no alias test, no positive
  supersession advance).
- rev-r4 — FIX 0.86 (missing DECISION Addendum; deploy
  README INIT list incomplete; verifier header catalogue
  missing the four new variables; no over-claim found in
  any changed surface).
- rev-r5 — FIX 0.82 (README allowlist count wrong —
  "19 → 23" vs the shipped 20 → 24; wiring prose stale;
  health_check only list-deep for the new anchors —
  consumption parity, extension or a recorded decision
  requested; e2e INIT sweep not extended).
- rev-r6 (forced dissent) — FIX 0.45 (blocking: no
  migration path for established journals; wiring break
  contradicting wiring's own rationale; availability
  coupling undisclosed; non-transactional multi-anchor
  bootstrap undisclosed; stale counts).

## Fix round 1 — reconciled fix list applied

- Tests: INIT discrimination (deleted anchor on an
  established journal; anchor ahead after rollback, bytes
  unchanged), supersession production gate (missing path,
  INIT refused), issuance==supersession alias refusal,
  positive supersession advance, issuance migration
  ceremony test; e2e INIT sweep extended to all five flags.
- Docs: DECISION-CONSUMPTION-HEAD Addendum 7 (rulings:
  (a) operator first-pin ceremony per the cycle-17
  precedent; (b) wiring-required break deliberate and
  disclosed; (c) availability coupling is the standing
  cycle-22 position, now explicit; (d) health-check parity
  kept, direct-verification extension is a follow-up);
  deploy README migration section + full INIT list +
  20 → 24; verifier header catalogue for the four new
  variables; wiring prose + recorded anchor-path exception
  rationale; supersede docstring step list.

## Re-review

- Tests seat — SHIP 0.95 (all five test findings verified
  closed against the tree; ran the 18 tests).
- Docs seat — FIX 0.88 → converted to SHIP on the single
  one-line correction it named (a "(20 names)" comment
  above ALLOWED_ENV_KEYS), applied and verified
  (grep count 0).
- rev-r6 re-review — FIX 0.70: F2 and F3 CLOSED; F1, F4,
  F5 NARROWED with three small items: supersession
  migration twin + production-shaped walk + runnable
  ceremony details in the README; honest partial-bootstrap
  wording; the "(20 names)" line (already fixed).

## Fix round 2

- Supersession migration twin test; production-shaped
  migration walk at FULL evidence (both journals
  first-pinned, production invocation with all five anchor
  paths and the ceremony seed configured returns exit 0);
  partial-bootstrap test pinning the disclosed side effect
  (issuance anchor created by the same refused invocation;
  supersession still refuses).
- README migration section now carries the runnable
  ceremony (journal construction, recorded_at, invocation
  context) and the non-transactional bootstrap disclosure
  in plain terms (cross-operation pinning; partial
  bootstrap leaves created anchors on disk — a safe,
  never silent, intermediate state).

## External seats

seat-gpt SHIP 0.93; seat-gemini SHIP 0.88 with a minor
pre-merge check (empty/whitespace seed must not bypass
the gate) — verified in reconciliation: production
requires the seed path outright, an empty value leaves
ceremony modes unconfigured and refusing, and a
whitespace value fails the absolute-path check. Full
record: internal/CROSS-CHECK-21.md.

## Final verdict

SHIP — reconciled unanimous after two fix rounds (the
dissent seat's remaining items were closed in round 2;
its F2/F3 closures and the narrowed-then-closed F1/F4/F5
are recorded above). Final suite: **1785 tests OK
(skipped=28)**, coordinator-run on the final tree. Real
state/state.json not advanced. Verdict form: SHIPPED
(external seats concurred; no provisional qualifier
remains).
