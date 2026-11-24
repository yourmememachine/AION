# Cycle 27 — War-Room Review, Seat rev-r1

Reviewer slice: `trust/verifier_main.py` — the generic ceremony-journal
anchor loader (`_load_ceremony_journal_anchor`), its two call sites in
`_load_config`, and the `_Config` plumbing. Reviewed blind and
independently (I did not build this slice): uncommitted `git diff`,
`internal/cycle27-work/design-final.md`, `trust/anchoring.py`, and the
cycle-22 consumption-anchor inline block as the parity reference.

**Score: 0.88**
**Verdict: SHIP** (provisional, as every cycle-27 verdict is, until the
external seats are reconciled in; findings 1–3 below are non-blocking)

Targeted verification run by this seat: the 11 tests in
`tests/test_cycle27_journal_anchors.py` — all pass (unittest, 11/11 OK).
The full suite was not run, per instructions.

## What checks out

### Production gating on `ceremony_seed_raw` — correct, exact parity

The loader raises `verifier_misconfigured` when
`deployment_mode == "production" and ceremony_seed_raw` and either the
anchor path is missing or its INIT flag is `"1"`. This is the identical
predicate and refusal shape as the cycle-22 consumption block in the
same function, keyed to the same `ceremony_seed_raw` value (the raw
`AION_CEREMONY_SIGNING_SEED_PATH` env string read earlier in
`_load_config`). Both new anchors are gated independently, so a
production deployment with the seed configured cannot start with only
one of the two journals anchored. Bad INIT spellings (anything other
than `""`/`"0"`/`"1"`), INIT-without-path, and a non-absolute path are
all `verifier_misconfigured`, again matching the consumption block
check for check.

### INIT bootstrap semantics — established journals are refused, twice over

This was the sharpest question in my slice, and the code is right:

1. `verify_anchor` never returns plain `("anchor_missing",)` for a
   non-empty journal. In `trust/anchoring.py` it returns
   `("anchor_missing_established_ledger",)` when the journal has
   entries and no anchor file exists. The loader only bootstraps on
   the exact tuple `("anchor_missing",)`, so for an established
   journal it falls through to `anchor_refused` with
   `anchor_missing_established_ledger` joined into the reason —
   `initialise_anchor` is never called.
2. Even if it were called, the loader does **not** pass
   `allow_nonempty_ceremony`, so `initialise_anchor`'s own guard
   would refuse to pin a non-empty journal's current head
   (seq > 0). The rollback-laundering path — delete the anchor,
   re-pin the rolled-back head under INIT — is closed at both layers.

This is byte-for-byte the cycle-22 consumption inline block's
behaviour: same exact-tuple test, same no-flag `initialise_anchor`
call, same `anchor_refused` mapping for a failed bootstrap. Parity
confirmed, including the empty-journal case: INIT on an empty journal
with no anchor bootstraps a seq-0 anchor and startup proceeds (covered
by `test_issuance_anchor_init_bootstrap_on_empty_journal_succeeds`).

Error mapping throughout the loader also matches the consumption
block: journal-open failure → `ledger_failed`; `AnchorError` out of
`verify_anchor` (e.g. anchor placed inside the journal directory) →
`anchor_refused`; any residual reasons → `anchor_refused` with the
reasons joined.

### Ordering of the loader calls — correct and load-bearing

In `_load_config` the order is: signing anchor → budgets anchor →
consumption inline block → issuance loader → supersession loader →
`_Config` construction. Two consequences, both good:

- The supersession call's `other_anchors` can (and does) include the
  already-resolved issuance path; any other order would leave the
  issuance↔supersession pair unchecked at this layer.
- Consumption verification still runs first and is unchanged, so
  cycle-22 startup behaviour is not perturbed; a failure in any
  earlier anchor refuses startup before the new loaders run, which is
  the conservative direction.

All five anchor verifications complete inside `_load_config`, i.e. at
startup on every invocation, before any mode runs — as the design
record claims.

### Distinctness — code coverage complete for every pair involving a new anchor

There are five anchor paths and ten pairs. The pairs involving a
cycle-27 anchor are all checked in `verifier_main`:

- issuance vs signing, budgets, consumption — via the issuance call's
  `other_anchors` (3 pairs);
- supersession vs signing, budgets, consumption, issuance — via the
  supersession call's `other_anchors` (4 pairs).

Comparison is on `Path(...).resolve()` on both sides, so symlink and
`..` aliases of the same file are caught, matching the consumption
block's discipline. The one pair not checked inside `verifier_main`
itself, signing↔budgets, is pre-existing (neither of those older
blocks checks the other) and is not a cycle-27 regression; at the
wiring layer the pairwise loop over `_ANCHOR_ENV_KEYS` — now extended
to all five anchor keys — checks all ten pairs for a production
client. An unconfigured (empty) other-anchor is correctly skipped, so
research mode with only one new anchor configured does not false-refuse.

### `_Config` plumbing — complete

Four new keyword fields (`ceremony_issuance_anchor_path/init`,
`ceremony_supersession_anchor_path/init`) with safe defaults
(`None`/`False`), assigned to same-named attributes, and populated at
the single `_Config` construction site in `_load_config` from the
loader return values. The loader already normalises its path return
to `anchor_path or None`, so the attributes are `None` (not `""`) when
unconfigured — which is what the `_update_ceremony_*_anchor` helpers'
truthiness no-op tests rely on. No other `_Config` construction site
exists in `trust/` or `tests/`, so nothing else needed updating.

## Findings (all non-blocking)

1. **Test coverage of distinctness and of the supersession call site
   is thin.** `tests/test_cycle27_journal_anchors.py` exercises
   exactly one of the seven new distinctness pairs
   (issuance == consumption). No test sets supersession equal to any
   other anchor, and the supersession side has no production-gate,
   INIT-bootstrap, established-journal-missing-anchor, or
   inside-home test — the suite is issuance-led (8 of 11 tests) with
   supersession covered only for rollback refusal and
   anchor-update failure. The risk is bounded because both call sites
   share the one generic loader and the wiring pairwise loop is
   separately exercised, but the supersession call site's
   `other_anchors` tuple is precisely the kind of hand-written list
   where a dropped entry would pass silently today. Recommended
   follow-up (not a ship blocker): add supersession == issuance and
   supersession production-gate tests.
2. **Strictness asymmetry between layers, in the safe direction —
   noted, not a defect.** `_load_config` requires the two new anchor
   paths in production only when the ceremony seed is configured,
   while `trust/wiring.py`'s `REQUIRED_ENV_KEYS` now requires both
   PATH keys unconditionally for a production client. A
   production-without-seed verifier could therefore start without
   the new anchors when launched outside the wiring factory. This
   exactly mirrors the pre-existing consumption anchor's split
   (same seed-keyed gate in `verifier_main`, same unconditional
   wiring requirement), and the stricter layer is the one that
   builds real deployments, so I do not ask for a change — but the
   design record's "required in production" phrasing should be read
   as "required in production with the ceremony seed" at the
   verifier layer.
3. **Cosmetic plumbing asymmetry.** At the `_Config` call site the
   consumption path is wrapped in an explicit `or None` while the
   two new paths are passed bare, relying on the loader's own
   normalisation. The resulting values are identical; flagging only
   so a future reader does not "fix" one side into a divergence.

## Bottom line

The loader is a faithful generalisation of the cycle-22 consumption
discipline: same production predicate on `ceremony_seed_raw`, same
INIT semantics with the established-journal refusal preserved at two
layers, complete distinctness for every pair a new anchor
participates in, correct call ordering, and clean `_Config`
plumbing. SHIP at 0.88, the deduction being finding 1's coverage
gap rather than any defect found in the loader itself.
