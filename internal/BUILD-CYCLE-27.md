# BUILD CYCLE 27 — ceremony journal anchoring (issuance + supersession)

**Summary (claim scope):** Cycle 27 closes the follow-up
`ceremony-journal-anchoring` at its full extended scope:
the ceremony ISSUANCE journal (cycle 22's narrowing) and
the ceremony SUPERSESSION journal (cycle 24's extension)
are now externally anchored in their own right, mirroring
cycle 22's consumption anchoring. Design record:
internal/cycle27-work/design-final.md. Decision record:
DECISION-CONSUMPTION-HEAD Addendum 7. War room: six
internal seats, two fix rounds, three re-review seats
(internal/REVIEW-CYCLE-27.md); external seats seat-gpt
SHIP 0.93 and seat-gemini SHIP 0.88, reconciled in
internal/CROSS-CHECK-21.md.

Baseline: cycle-26 tree at 1764 tests OK (skipped=28).
Final: **1785 tests OK (skipped=28)** — +21 new tests in
tests/test_cycle27_journal_anchors.py, plus fixture and
sweep updates in existing suites. Real `state/state.json`
not advanced (sha256 verified identical before/after).
`eval/` untouched.

## What was built

- `trust/anchoring.py`: anchor kinds `ceremony-issuance`
  and `ceremony-supersession` join ANCHOR_KINDS.
- `trust/verifier_main.py`: one shared loader,
  `_load_ceremony_journal_anchor`, a faithful generalisation
  of the cycle-22 consumption inline block (same refusal
  codes and semantics), verifies both journals at startup
  on every invocation. Production mode with the ceremony
  seed configured requires both paths
  (AION_CEREMONY_ISSUANCE_ANCHOR_PATH,
  AION_CEREMONY_SUPERSESSION_ANCHOR_PATH) and refuses both
  INIT flags. Each anchor: absolute, outside the verifier
  home, distinct from every other anchor path. INIT
  bootstraps only on the exact `anchor_missing` reason —
  an established journal with a missing anchor is
  `anchor_refused`, never silently blessed.
- Commit orders: authorise = issuance append (commit
  point) → issuance-anchor update → signing mirror →
  signing anchor; supersede = decision append (commit
  point) → supersession-anchor update → signing mirror →
  signing anchor. Anchor-update failure is `ledger_failed`:
  the envelope/receipt is withheld and the journal entry
  stands (pair burned / decision stands).
- `trust/wiring.py`: allowlist 20 → 24 names; both new
  PATH keys join REQUIRED_ENV_KEYS on the cycle-22
  consumption terms, with the anchor-path exception to the
  not-wiring-required rationale recorded in the file.
- Deploy: run-verifier.sh, setup.sh, health_check.py and
  the deploy README updated in step, including a cycle-27
  migration section (below).
- Docstrings: both journals' rollback positions rewritten
  in trust/ledger.py; verifier header catalogue documents
  all four new variables; signing/pin_ceremony.py's
  issuance residual updated.

## Honest residuals (unchanged in kind)

- The append→anchor-update window is not protected
  against a full rollback inside that window — the same
  window every anchored append in this system carries.
- Research mode / anchor unconfigured: no rollback claim.
- Coordinated rollback of a journal AND its anchor is not
  detectable (seat-gpt's qualification; stated in the
  journals' docstrings).
- Availability coupling: all five anchors are verified at
  startup on every invocation, so a fault in any one
  refuses every mode — fail-closed, disclosed in the
  migration note.
- First-pinning an established journal is an operator
  ceremony outside the verifier
  (`initialise_anchor(..., allow_nonempty_ceremony=True)`,
  the cycle-17 ship-tx precedent), documented with a
  runnable procedure in the deploy README; the first pin
  blesses current history and cannot detect a pre-pin
  rollback. Proven by migration tests for both journals
  and a production-shaped walk (both journals first-pinned,
  production invocation exit 0).

## Staffing

15 coders, 5 pods of 3: Pod A (1, 5, 8) anchoring +
wiring; Pod C (9, 10, 11) verifier_main config + commit
orders; Pod D (3, 4, 15) adversarial tests (21); Pod B
(2, 6, 7) ledger docstring/residual rewrites; Pod E
(12, 13, 14) deploy README + records. War room: 6 internal
reviewer seats from other pods (rev-r6 forced dissent)
plus seat-gpt and seat-gemini.

## Self-improvement delta

The last two journals whose rollback position rested on
audit-only detection now carry startup-enforced external
anchors: evidence reuse and decision-vanishing after a
rollback are startup refusals, not audit findings. The
integrity spine's journal coverage is now complete — all
five journals (signing, budgets, ship-tx lineage aside,
consumption, issuance, supersession) sit under the same
anchoring discipline, one loader pattern, one failure
vocabulary. Remaining follow-ups (not holds):
operator-authentication-channel,
pin-store-history-reconciliation, the cycles 17+18
CROSS-CHECK-12 recovery-contract document, and the
health-check direct-verification extension recorded in
Addendum 7 ruling (d).
