# REVIEW — Cycle 10: Trust Boundary v3

## War room (blind round)

Six reviewers from outside the building pods; blind scores locked
in `state/calibration/calibration.json` (subject `cycle-10-build`)
BEFORE discussion; rev-r6 held the forced-dissent seat.

| Seat | Scope | Blind score | Verdict |
|---|---|---|---|
| rev-r1 | Provenance chain | 0.78 | FIX |
| rev-r2 | Crash laboratory | 0.74 | FIX |
| rev-r3 | Extraction / consumption | 0.87 | SHIP |
| rev-r4 | Path-policy equivalence | 0.80 | FIX |
| rev-r5 | Production isolation | 0.84 | FIX |
| rev-r6 | Serialisation + whole-cycle (DISSENT) | 0.38 | FIX |

No seat found a forgery, a signer misuse that succeeds, an
exactly-once violation, or a production-gate bypass. The FIX
verdicts were about claim accuracy and three real code defects
found by the dissent seat.

## Findings and disposition

**rev-r6 (dissent) — the round's most valuable seat:**
- S1 HIGH — sealed_eval scope grammar weaker at minting than at
  consumption (signable-but-unconsumable scopes). FIXED
  (`_check_sealed_eval_scope`, grammar on the scope root).
- S2 HIGH — client and verifier disagreed on the same int-spelled
  record. FIXED (shared `rebuild_eval_payload`).
- S3 MEDIUM — evidence consumed before proposal_id validation.
  FIXED (validation precedes consumption).
- S4 MEDIUM — battery missing classes (-0.0, huge ints,
  n/correct/version spellings, timestamp spellings, release
  duplicate keys). ADDED to the battery (all safe in code; now
  demonstrated).
- S5 MEDIUM — "932 headline elides that the live tests didn't run
  in this run." PARTLY A MISREAD (the live class HAD run, 11/11 at
  provisioning; r5 verified ledger/anchor state on disk), but the
  underlying point stands: the cycle records must carry the live
  evidence explicitly rather than letting a test count imply it.
  DONE in BUILD-CYCLE-10.md and the deploy README.
- S6 LOW — parse_float hook asymmetry in from_json loaders.
  FIXED (structural strictness in all three loaders).
- S7 LOW — unicode answer normalisation untested. ADDED (NFC/NFD
  score-equal, hash-different, fail-closed).

**rev-r1:** PROVENANCE.md stale on consumption (F1, MEDIUM) —
FIXED (doc brought current + replay attack test). Approve
semantics understated (F2) — FIXED (plain-language subsection).
Predicate boundary probes (F3) and cross-key isolation (F4) —
ADDED. registry_digest tail-entry fragility (F5) — DOCUMENTED in
the doc as a construction note.

**rev-r2:** anchor write had no crash coverage (F1) — FIXED
(anchored variant: after_commit / after_anchor /
during_anchor_save). During-save kills covered 2 of ~7 saves
(F2) — during_finalise_save ADDED; state-equivalence argument
stated in the docstring with named equivalences; claim wording
narrowed to exactly what is covered. StubLoop test framing (F3) —
RELABELLED as a recovery-logic unit test + production companion
test added (CoreLoop refuses the duplicated state first; tx left
BURN_PENDING, fail-closed). Pair-only race (F4) — ADDED.

**rev-r3:** SHIP. Doc qualifications only — "only practical route"
struck (F1), score-channel scope + manifest-as-oracle stated
(F2), free-n disclosure noted (F3). ALL APPLIED.

**rev-r4:** counts, equivalence, and caller audit independently
re-derived and confirmed. "Full gate-miss list" overclaim (F1) —
FIXED (bounded wording; open family stated; verifier
canonical-only rule named as the real bound). Corpus gaps (F2) —
corpus extended to 66; three probed spellings the reviewer
predicted as agree-unprotected in fact derive CANONICAL and were
pinned as such with an explanatory comment. Import-cycle
understatement (F3) — FIXED in the proposal (trust/__init__ chain,
canonical-spelling effect on signed violations, gate header
invariant).

**rev-r5:** deployment and gate verified live, no bypass (extra
probes: unknown/blank/whitespace mode values, isolated budgets
checks). README status false (F1) — FIXED (executed ceremony
recorded; layout includes the staged code copy). Budgets-half
spec tests missing (F2) — ADDED (test_d/test_e). 0660 group
qualification (F3) — APPLIED + wrapper `umask 077`. Blank-mode
downgrade (F4) — DECLARED as a known limit in the README.
Wrapper AION_REPO_ROOT caller override (F5, INFO) — noted; root
is outside the threat model.

## Fix-round verification

Two independent re-reviewers (fresh seats, given findings + fixes,
not the blind scores):
- Code fixes: **0.92** — S1/S2/S3/S6 and the crash-lab fixes
  CLOSED, probed beyond the shipped tests (33 scope spellings with
  budget-integrity snapshots; 12 tamper/re-spell cases in both
  consumer directions; nested/negative/constant parse probes).
  Two LOW residuals: (i) the crash-lab docstring's begin-save
  sentence overreached — CORRECTED by the coordinator (a kill
  during the begin save leaves no journal at all; strictly safer,
  explicitly not claimed as an equivalence); (ii) the
  concurrent-issuance error-code flake (pre-existing; semantics
  hold) — backlogged as `consumption-race-error-code`.
- Docs/claims: **0.97** — every finding CLOSED; stale-claim sweep
  clean. Two wording nits: INIT flags "removed" → corrected to
  "blanked"; the 11/11 figure is historical (suite has since
  grown) and is time-qualified in the README.

## Reconciled verdict

**SHIP (internal, unanimous after fix rounds) — PROVISIONAL.**
The verdict stays provisional until the two external war-room
seats (ChatGPT and Gemini) re-review v3 from the blind brief at
`internal/CROSS-CHECK-BRIEF-CYCLE-V3.md`, per Dilip's standing
rule. Calibration outcome for subject `cycle-10-build` recorded
as 1.0 (internal ship), following the cycle-9 convention; the
dissent seat's 0.38 remains on record and scored.

Full suite at reconciliation: **964 tests, OK (skipped=2)** —
820 (cycle 9) → 932 (pod delivery) → 964 (post-fix). The 2 skips
are the live test_10/test_11 budget-consumed skips, by design.

## What needs Dilip

1. **Protected Gate Rule proposal** (`internal/PROTECTED-GATE-PROPOSAL.md`):
   adopt path-policy/1 inside `eval/gate.py` or leave the gate as
   is (the verifier's canonical-only rule currently carries the
   production bound). Decision is Dilip's + external review.
2. Nothing else: provisioning required no step that needed
   Dilip's hand — the ceremony was completed by the coordinator
   as root. Note the VM's OS state reset mid-cycle and was
   rebuilt; the verifier user is now uid 999.

## Next backlog (top)

- `production-signed-path-wiring` (7.0) — wire production flows
  through the provisioned wrapper/ship path.
- `signed-state` (7.0).
- `consumption-race-error-code` (4.5, new) — deterministic refusal
  code under concurrent issuance.
