# Cycle 27 — War-Room Review, Seat rev-r6 (FORCED DISSENT)

Reviewer role: argue the strongest possible case against shipping
cycle 27 as-is. Evidence: uncommitted `git diff` in `~/workspace/ai`
plus `internal/cycle27-work/design-final.md`. Where an assigned
attack failed on the evidence, that is stated plainly — the dissent
below rests only on findings that survived checking.

**Score: 0.45 / 1.00**
**Verdict: FIX** (do not ship as-is; Finding 1 alone is blocking)

---

## Finding 1 (BLOCKING) — No migration path exists for an established journal; every real production deployment is wedged on upgrade

The issuance journal has existed since the ceremony work of
cycles 19–20 and the supersession journal since cycle 24. Any
production deployment that has ever authorised or superseded has
**non-empty** journals and **no** ceremony-issuance /
ceremony-supersession anchors. Cycle 27 gives that deployment no
coded or documented way to create the anchors:

- `trust/anchoring.py:730-733` (`verify_anchor`): a missing anchor
  on a non-empty journal returns
  `("anchor_missing_established_ledger",)`, not
  `("anchor_missing",)`.
- The new helper, `trust/verifier_main.py:601` in the diff
  (`_load_ceremony_journal_anchor`), bootstraps only on the exact
  tuple: `if reasons == ("anchor_missing",) and anchor_init:`.
  An established journal therefore raises `anchor_refused` even
  with INIT set.
- `trust/anchoring.py:616-623` (`initialise_anchor`): pinning a
  non-empty journal additionally requires
  `allow_nonempty_ceremony=True`. **No production call site in
  this diff passes that flag** (`grep` over the tree: the flag
  appears only in `trust/anchoring.py` itself and in tests for
  other journals).
- Production mode refuses INIT outright (helper, diff
  `verifier_main.py` production branch; design-final.md
  "Production requirements"), so the operator cannot bootstrap
  in production either.

Net effect: upgrade a live deployment and the verifier refuses
every start (`anchor_refused` / `verifier_misconfigured`), with
no in-repo ceremony, tool, or README procedure to first-pin an
established issuance or supersession journal. Contrast the
cycle-20 precedent in `deploy/verifier-identity/README.md`
("Cycle-20 migration and flag-day cutover": "Existing production
deployments must set … or the verifier refuses to start after
upgrade. Fail-closed by design, **announced here**"). The cycle-27
README paragraph (diff, README.md ~line 343) states the new
requirements but contains **no migration note at all** — no
flag-day announcement, no established-journal first-pin
procedure, no mention of `allow_nonempty_ceremony` or
`force_reanchor` as the audited escape. Design-final.md is
likewise silent: its "Production requirements" section never
addresses a deployment whose journals predate the anchors.

The cycle-27 tests do not cover this case: the only
established-journal test,
`tests/test_cycle27_journal_anchors.py:447`
(`test_issuance_anchor_missing_on_established_journal_refused`),
asserts the refusal and stops there; no test demonstrates a
legitimate operator recovering from it. A fail-closed upgrade
with no exit is not a migration plan; it is an outage scheduled
for the first real deployment.

Fix required: ship a documented, audited first-pin ceremony for
established ceremony journals (e.g. an operator tool invoking
`initialise_anchor(..., allow_nonempty_ceremony=True)` with the
same out-of-production discipline as other anchor ceremonies),
plus a README migration note in the cycle-20 style, plus a test
that walks an established journal from unanchored to anchored.

## Finding 2 — Wiring `REQUIRED_ENV_KEYS` is an unconditional breaking change that contradicts wiring's own stated rationale, and is stricter than the verifier's gate

- `trust/wiring.py:231-235` (diff): both new PATH keys join
  `REQUIRED_ENV_KEYS` **unconditionally**.
  `production_client` refuses any env missing them
  (`trust/wiring.py:313-318`).
- The verifier's own gate is conditional: `_load_config`
  requires the new anchors only in production **with the
  ceremony seed configured** (helper production branch;
  design-final.md keys the requirement to the seed deliberately).
  A production client that never configures the ceremony seed —
  plain production signing/eval — could construct before this
  cycle and cannot construct after it, for two journals it will
  never open.
- This also contradicts the rationale recorded **in the same
  file and left unchanged** (`trust/wiring.py:215-222`):
  ceremony variables (`AION_CEREMONY_OPERATORS`,
  `AION_CEREMONY_EVIDENCE_DIR`,
  `AION_CEREMONY_SIGNING_SEED_PATH`) are "deliberately NOT
  wiring-required … production *startup* refusal for a missing
  ceremony variable is the verifier's own rule". Cycle 27 makes
  two ceremony variables wiring-required without amending or
  even mentioning that rationale. Either the rationale is wrong
  or the placement is; the diff does not say which.
- Precedent note, honestly stated: the consumption anchor path
  was already wiring-required unconditionally, so cycle 27
  extends an existing pattern rather than inventing one. That
  mitigates surprise for the pattern, but it does not disclose
  this instance: any caller whose env was valid at cycle 26
  (consumption anchor present, new anchors absent) breaks at
  client construction on upgrade, and neither design-final.md
  nor the README cycle-27 paragraph flags the wiring-level
  break separately from the verifier-level, seed-keyed one.

Fix required: either key the wiring requirement to the ceremony
configuration (matching the verifier), or keep it unconditional
and (a) amend the `trust/wiring.py:215-222` rationale to say why
anchor paths are the exception, and (b) disclose the break as a
migration item in the README alongside Finding 1's note.

## Finding 3 — Supersession anchoring silently expands its failure domain from "supersede/consume only" to "every verifier mode, every invocation"

Design-final.md states, as a feature, that "Both journals are
verified at startup on every verifier invocation, in
`_load_config`." `_load_config` runs for **every** mode in this
one-process-per-request verifier (the consumption block's own
comment, `trust/verifier_main.py:1139-1142`, makes the same
point). Consequences the design never weighs:

- A missing, malformed, ahead-of-journal, or simply
  unreachable supersession anchor — or a supersession journal
  that fails to open (`ledger_failed` in the helper's
  `journal_factory` catch) — now refuses **sealed_eval,
  ordinary signing, authorise, consume and recovery alike**,
  not just supersession.
- This reverses the isolation the pre-27 design deliberately
  recorded for this journal: `trust/ledger.py`'s supersession
  docstring (pre-diff text) states that rolling back only this
  file "fails closed" **at consume**
  (`ceremony_supersede_required`) — other modes were
  unaffected. The cycle-25 README note makes the same
  isolation promise for the approver seed ("supersession — and
  only supersession — is wedged"). Cycle 27 couples the
  supersession journal's health to total verifier availability
  and discloses this nowhere: not in design-final.md's
  "Honest residuals", not in the README paragraph.
- The consumption anchor set the every-invocation precedent,
  but consumption is on the path of the ceremony's core
  operation; supersession is a rare, exceptional act. Anchoring
  a rarely-used journal at startup-everywhere buys rollback
  detection for supersession at the price of a new single point
  of total outage (one more anchor file whose loss is a full
  verifier outage — now five anchor files, any one of which
  wedges everything).

This may be the right trade — but it is currently an
**unargued** trade. Fix required: design-final.md and the
README must state the expanded blast radius explicitly
("a supersession-anchor fault refuses all modes"), so the
ship decision is made with the coupling on the record; or
scope supersession verification to the modes that consult the
journal (supersede/consume) and argue why startup-everywhere
is not needed for it.

## Finding 4 — One research invocation now bootstraps five anchors as a side effect, including anchors for operations the request never performs; a refused or failed request still mutates anchor state

The cycle-27 fixture itself codifies the pattern:
`tests/test_cycle27_journal_anchors.py`, `bootstrap_anchors()`
sets all five INIT flags on a single `ceremony_authorise`
request. In `_load_config` order — signing, budgets,
consumption, then the two new helper calls — each INIT pins its
journal's genesis head **before the request is authorised,
validated as a ceremony, or executed at all**. Therefore:

- An authorise request bootstraps the **supersession** anchor
  (pinning the empty supersession journal) although the request
  has nothing to do with supersession; symmetrically, whichever
  request happens to carry INIT first pins journals it does not
  touch. The "ceremony" for journal X is performed by an
  unrelated operation on journal Y.
- `_load_config` is not transactional across the two new
  anchors: if the issuance INIT succeeds and the supersession
  INIT then fails (`AnchorError` → `anchor_refused`), the
  invocation is refused **but the issuance anchor file remains
  on disk**. The same holds if the request later fails after
  config load. A refused invocation leaving half of a two-anchor
  bootstrap behind is new in degree (two anchors, one call, in
  sequence inside one helper-driven block) even though the
  single-anchor version of the pattern is inherited.
- Recovery is possible (re-run with INIT), so this is not a
  wedge like Finding 1 — but no test pins the partial-bootstrap
  state, and neither design-final.md nor the helper docstring
  acknowledges that a failed startup can create anchor files.

Fix required: at minimum, document the non-transactional,
side-effecting bootstrap and add a test for the
issuance-created/supersession-failed intermediate state; or
bootstrap each journal's anchor only in an invocation for that
journal's own ceremony.

## Finding 5 — Documentation ground truth is stale/wrong in the very files this cycle edits

- `deploy/verifier-identity/README.md` cycle-27 paragraph
  (diff): "(allowlist 19 → 23)". Ground truth: the shipped
  wrapper and `ALLOWED_ENV_KEYS` both contain **24** names
  (`tests/test_trust_wiring.py` diff asserts 20 → 24; direct
  count of `run-verifier.sh` ALLOWED_KEYS = 24). The README is
  wrong on both numbers.
- `trust/wiring.py` prose was not updated for a change made in
  that same file: line 92 still says "all three anchor paths
  are required", line 99 "Both anchor paths", line 212's
  comment "all three anchor paths", and the production-client
  prose still describes the allowlist as "20 names". After this
  cycle there are five anchor paths and 24 allowlisted names.
  These are the paragraphs an operator reads to construct a
  production env; leaving them at the pre-27 counts in the same
  diff that changes the counts is exactly how Finding 2's break
  stays undiscovered until deployment.

Fix required: sweep `trust/wiring.py` and the README to the
5-anchor / 24-name ground truth.

---

## Assigned attacks that FAILED on the evidence (no finding)

1. **Generic-helper divergence from the consumption block.**
   Checked line by line (`_load_ceremony_journal_anchor`,
   diff `verifier_main.py:531-619`, against the inline
   consumption block at `verifier_main.py:1069-1167`):
   - Error codes match at every branch:
     `verifier_misconfigured` for bad INIT / missing production
     path / INIT in production / relative path / INIT without
     path / anchor inside home / non-distinct path;
     `ledger_failed` for journal-open failure; `anchor_refused`
     for `verify_anchor` `AnchorError`, bootstrap `AnchorError`,
     and any residual reasons (`",".join(reasons)` in both).
   - `anchor_missing` tuple handling is identical: exact
     equality `reasons == ("anchor_missing",)`, so INIT cannot
     bootstrap an established journal in either implementation
     (that parity is what produces Finding 1 — it is a design
     gap, not a helper bug).
   - Distinctness coverage is complete in aggregate: the
     issuance call checks signing/budgets/consumption; the
     supersession call checks those three plus issuance; every
     pair involving a new anchor is checked by the later of the
     two calls, so an alias still refuses at startup (only the
     wording of which variable is named differs).
   - Non-`AnchorError` exceptions from `verify_anchor` (e.g. a
     corrupt journal raising during chain-prefix computation)
     propagate uncaught — but identically in the consumption
     block, so this is inherited parity, not a cycle-27
     divergence.
   The helper is a faithful generalisation. No finding.

2. **"INIT in the same invocation" as a correctness hazard for
   anchor contents.** Both new anchors pin only the genesis
   head of an empty journal at config load, and the subsequent
   append + `update_anchor` advances the acting journal's
   anchor through the normal path; the cycle-27 rollback and
   commit-order tests exercise exactly this sequence. The
   residual objection is the side-effect/ordering one recorded
   as Finding 4, not incorrect anchor contents.

---

## Summary for reconciliation

Ship is blocked by Finding 1 (no established-journal migration
path — an upgrade outage with no documented exit), compounded
by Finding 2 (an undisclosed, rationale-contradicting wiring
break) and Finding 5 (the operator-facing docs miscount the
very configuration the cycle adds). Finding 3's availability
coupling may be acceptable, but it must be stated and chosen,
not inherited silently. The core anchoring mechanics — helper
parity, commit orders, anchor-update failure semantics — are
sound on the evidence; this dissent is against shipping the
cycle **as-is**, without its migration and disclosure half.

— rev-r6 (forced dissent)
