# Cycle 24 — Design Seat C: Item 4, issuance-journal anchoring

Scope: design only, no production code. Item 4 closes the narrowed
follow-up `ceremony-journal-anchoring`: the ceremony **issuance**
journal (`ceremony-authorisations.json`,
`CeremonyAuthorisationLedger`, `trust/ledger.py`) is the last
unanchored verifier journal. Cycle 22 anchored the consumption
journal (kind `"ceremony-consumption"`, env pair
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` / `_INIT`, allowlist
17→19, startup verification in `_load_config`, anchor update
after the journal append in the consume commit order). This
design mirrors cycle 22 exactly wherever the pattern transfers,
and says so where it does not.

---

## 1. Claim check first: what a rollback of ONLY the issuance journal actually does

The task brief asked me to verify the docstring's defect claim
against the signing-ledger mirror. The claim lives in two
places, worded consistently:

- `trust/verifier_main.py` module docstring (~lines 255–267):
  "The ceremony ISSUANCE journal is NOT externally anchored …
  after a journal rollback, only same-ceremony_id reuse leaves
  a detectable trace in the anchored signing ledger — evidence
  reuse under a NEW ceremony_id is NOT detectable from the
  anchored store alone."
- `trust/ledger.py`, `CeremonyAuthorisationLedger` docstring
  ("Rollback residual, stated plainly"): the anchored signing
  ledger preserves `(authorisation_id, payload_hash,
  ceremony_id as proposal_id)` via
  `SigningLedger.append_ceremony_authorisation`, but stores
  **neither `evidence_hash` nor `operator_id`**.

**Verdict: the docstring is accurate, but incomplete in both
directions. The residual risk is smaller than a plain reading
implies, and the design below is written against the verified
version, not the slogan.**

### 1a. What rollback of ONLY the issuance journal DOES enable

Prerequisites the attacker/accident must still satisfy: the
rollback is of the one file (signing ledger, consumption
journal, both their anchors, the evidence directory, and the
retained-evidence copies all intact), **and** someone actively
re-presents the evidence — a listed `operator_id` (allowlist
eligibility, not authentication, per the module docstring),
the artifact still present under `AION_CEREMONY_EVIDENCE_DIR`
with a matching hash, and the ceremony seed still signing via
the verifier. Rollback alone issues nothing.

Given that re-presentation:

1. The anti-replay scan at authorise step (5) reads only the
   issuance journal, so the rolled-back `(ceremony_id,
   evidence_hash)` pair looks unused and the verifier signs a
   **second authorisation for the same `evidence_hash`** —
   under the same ceremony_id or a new one. Evidence
   single-use-per-event is defeated. This is the real defect.
2. The second envelope is **fully consumable**: consume step
   (6) checks issuance presence via
   `CeremonyAuthorisationLedger.find_by_authorisation_id`
   against the rolled-back-and-regrown journal, where the new
   entry legitimately sits. `ceremony_not_issued` does not
   fire.
3. The concrete harm is therefore narrow and specific: **one
   evidence bundle can justify a second, different pin
   movement** (different candidate/old-pin), each consumed
   once. It is *not* a double-spend of one movement (see 1b.2).

### 1b. What it does NOT enable (the parts the docstring omits)

1. **It does not resurrect the original envelope.** Rolling
   the issuance journal back *alone* bricks every unconsumed
   original envelope: consume step (6) finds no issuance entry
   and refuses `ceremony_not_issued`. The failure direction of
   a passive rollback is fail-closed; resurrection requires
   the active re-issuance in 1a.
2. **It does not permit consuming the same movement twice.**
   Even after re-issuance under a new `authorisation_id`, the
   anchored consumption journal, the signing ledger's scoped
   consume-mirror check (consume step 5), and the head rules
   (consume step 7 / `check_head`, cap-2 lineage) still refuse
   a second consumption of an already-consumed movement. The
   re-issued envelope only pays out against a *new* target.
3. **It does not hide that a second issuance happened.** The
   anchored signing ledger records every issuance
   (`authorisation_id`, `payload_hash`, `ceremony_id` as
   `proposal_id`, `format="ceremony-authorisation"`). Same-
   ceremony_id reuse leaves a visible duplicate trace there
   (two `sign` entries, same `proposal_id`, different
   `decision_id`/`payload_hash` — `payload_hash` always
   differs because it binds `issued_at`). New-ceremony_id
   evidence reuse is the one case not joinable from the
   anchored store alone, because `evidence_hash` is not a
   signing-ledger column.
4. **It is not wholly undetectable even in the new-id case —
   just not from the anchored store alone.** Retained evidence
   copies (`_retain_ceremony_evidence`, named by
   `authorisation_id`, inside verifier home) survive a
   single-file journal rollback; hashing two retained copies
   and finding equal bytes joins the two issuances on
   `evidence_hash` by audit. The docstring's own qualifier
   ("only by audit against retained envelopes") covers this;
   it deserves promotion from qualifier to statement.

### 1c. What this anchoring therefore buys — honestly

- **Prevention-at-startup, not detection-after-the-fact, for
  the re-issuance path:** with the anchor configured, a
  rolled-back issuance journal disagrees with the anchor
  (`anchor_ahead_of_journal` / `anchor_head_not_in_chain`) and
  `_load_config` refuses **every** mode with `anchor_refused`
  before any re-issuance can be signed — the same
  detection-at-startup model as the other three anchors.
- **An anchored record that does carry `evidence_hash` and
  `operator_id`** (they are issuance-journal entry fields, and
  the anchor pins the chain that contains them), closing the
  joinability gap in 1b.3 by construction.
- It does **not** buy: protection inside the append→anchor
  window (§5, characterisation test pins it), protection
  against joint journal+anchor rollback (anchor is only as
  external as its placement — `trust/anchoring.py`'s honest
  scope, unchanged), or any change to consumption safety
  (already anchored in cycle 22).

---

## 2. Anchor kind — `trust/anchoring.py`

- `ANCHOR_KINDS` gains `"ceremony-authorisation"`:
  `("signing", "ship", "ship-tx", "ceremony-consumption",
  "ceremony-authorisation")`. This is the single change point:
  `_check_kind` and `_validate_anchor` both consult the tuple.
- Module docstring: the anchor-format kind enumeration
  (`"signing" | "ship" | "ship-tx" | "ceremony-consumption"`)
  gains `| "ceremony-authorisation"`.
- Explicitly **not** touched: `JOURNAL_INTEGRITY_REASONS` and
  `JournalIntegrityError._ANCHOR_SOURCE_NAMES` (`"ship"`,
  `"ship-tx"` only). That type serves ship-tx recovery; the
  authorisation anchor's `verify_anchor` reasons are consumed
  by `_load_config` as plain strings, exactly like the
  consumption anchor's. Widening it is out of scope.
- No format change: `ledger-anchor/1`, same exact key set.
  Existing anchors of other kinds are unaffected (kind is
  checked per-anchor at verify/update).

## 3. Env pair and the allowlist, 19 → 21 — every copy

New names, mirroring the consumption pair's grammar exactly:

- `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH`
- `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT`

(Note the spelling: `AUTHORISATION`, matching
`CeremonyAuthorisationLedger` and the existing
`AION_CEREMONY_*` family — not the US spelling.)

Every copy of the allowlist / count, found by grepping
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` and the count `19`:

| # | Location | Change |
|---|----------|--------|
| 1 | `trust/wiring.py` `ALLOWED_ENV_KEYS` | +2 names (after the consumption pair); header comment "(19 names)" → 21 |
| 2 | `trust/wiring.py` module docstring | "(ALLOWED_KEYS, 19 names — the shipped wrapper governs)" → 21 |
| 3 | `deploy/verifier-identity/run-verifier.sh` `ALLOWED_KEYS` | +2 names, after the consumption pair |
| 4 | `deploy/verifier-identity/health_check.py` `ALLOWED_KEYS` | +2 names — a literal copy, pinned to the wrapper by `test_health_check_allowlist_matches_wrapper`; missing this copy fails that test |
| 5 | `deploy/verifier-identity/health_check.py` `_INIT_KEYS` | + `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT` |
| 6 | `deploy/verifier-identity/health_check.py` `_PATH_KEYS` | + `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH` (gets the same path-shape treatment as the consumption path) |
| 7 | `deploy/verifier-identity/setup.sh` env template | +2 lines with comment block mirroring the consumption block: `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH=/var/lib/aion-verifier/anchors/ceremony-authorisation.anchor.json`, `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT=` (empty). **Mandatory, not cosmetic:** `test_template_keys_equal_allowlist` asserts template keys == allowlist exactly |
| 8 | `tests/test_trust_wiring.py` | `test_allowlist_is_the_shipped_19_names` → re-pin 21, rename, add `assertIn` for both new names; `test_allowlist_matches_wrapper_script_at_test_time` `len(wrapper_keys)` 19 → 21; module docstring "wrapper allowlist has 19 names (… cycle 22 added …)" gains "cycle 24 added `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH` and `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT`" |
| 9 | `tests/test_verifier_deploy.py` | `test_health_check_allowlist_matches_wrapper`: `len(health_keys)` 19 → 21. (`test_every_verifier_main_env_var_is_allowlisted` needs no edit — it regex-extracts `AION_*` from `verifier_main.py` and is the tripwire that fails if any of copies 1/3/4 is missed.) |
| 10 | `tests/test_trust_production_deploy.py` (~line 539) | the literal `allowlisted` set in `test_31_wrapper_probe_sees_only_allowlisted_environment` gains both names |
| 11 | `deploy/verifier-identity/README.md` | line ~133 production paragraph + line ~276 consumption paragraph: add the authorisation pair; the "(allowlist 17 → 19)" note gains "cycle 24: 19 → 21" |

No other count pins exist: the remaining `19`s in the tree are
cycle numbers, test data, or unrelated (verified by grep).

## 4. Wiring — `trust/wiring.py`

- `ALLOWED_ENV_KEYS`: +2 (§3.1).
- **`REQUIRED_ENV_KEYS`: YES, add
  `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH`.** Argument: the
  consumption anchor path *is* wiring-required, and wiring's
  stated stance (comment above `REQUIRED_ENV_KEYS`) is that
  production makes anchoring mandatory and fail-closed — the
  required set is the client-construction minimum, and *all
  anchor paths* are in it. The known asymmetry — wiring
  requires the consumption path unconditionally while the
  verifier requires it only when production + ceremony seed —
  was a deliberate cycle-22 choice (anchors treated
  differently from the ceremony *feature* variables
  operators/evidence/seed, which are allowlisted-but-not-
  required). Leaving the authorisation path out would recreate
  exactly the asymmetry cycle 22 closed, and would let a
  production client be constructed whose verifier refuses to
  start — the precise misconfiguration the required set exists
  to surface one layer up. The counter-argument (a
  ceremony-free production client is forced to name a fourth
  anchor file) is already true of the consumption anchor today
  and was accepted there; consistency wins. The comment above
  `REQUIRED_ENV_KEYS` changes "all three anchor paths" → "all
  four anchor paths", and the module docstring's "all three
  anchor paths are required non-empty" → four.
- `_INIT_ENV_KEYS`: + `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT`
  — `production_client`'s INIT refusal (any value other than
  absent/`""`/`"0"`) then covers it automatically.
- `_ANCHOR_ENV_KEYS`: + `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH`
  — the existing loop then gives it, with no new code:
  absolute-path refusal, resolved-outside-`AION_VERIFIER_HOME`
  refusal, not-equal-to-key-path, not-equal-to-or-inside-
  registry-dir, not-an-existing-directory, and the pairwise
  distinctness loop extends from 3 pairs to 6 automatically.

## 5. `_load_config` and `_Config` — `trust/verifier_main.py`

### `_Config`

Two new keyword parameters, placed after the consumption pair
to keep the anchor families grouped:

```python
ceremony_authorisation_anchor_path=None,
ceremony_authorisation_anchor_init=False,
```

with the matching `self.` assignments. No other constructor
call site exists outside `_load_config`'s return (tests
construct `_Config` only via the process env), so the defaults
keep every other caller byte-identical in behaviour.

### `_load_config` — new block, placed AFTER the consumption block, BEFORE `return _Config(...)`

Placement is forced, not stylistic: distinctness must be
checked against all three existing paths (`anchor_path`,
`budgets_anchor_path`, `ceremony_consumption_anchor_path`),
and the consumption block is the last of those to be resolved.
Consequence to state in the code comment: in a configuration
where *both* ceremony anchors are broken, the consumption
refusal fires first — acceptable, startup refuses either way.

The block mirrors the consumption block (~lines 815–913) step
for step, with `CeremonyAuthorisationLedger`,
`kind="ceremony-authorisation"`, and the new env names:

1. Read `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH` /
   `_INIT`; INIT raw outside `("", "0", "1")` →
   `verifier_misconfigured` ("bad
   AION_CEREMONY_AUTHORISATION_ANCHOR_INIT").
2. **Production gate, gated identically to consumption:**
   `if deployment_mode == "production" and ceremony_seed_raw:`
   — path missing → `verifier_misconfigured` ("production
   mode with the ceremony seed configured requires
   AION_CEREMONY_AUTHORISATION_ANCHOR_PATH"); INIT set →
   `verifier_misconfigured` ("production mode refuses
   AION_CEREMONY_AUTHORISATION_ANCHOR_INIT; anchor ceremonies
   run outside production"). Do **not** gate on production
   alone: mirroring means the seed-conditional form, so a
   production deployment without the ceremony seed keeps
   today's startup behaviour exactly.
3. Path present but not absolute → `verifier_misconfigured`.
4. INIT without path → `verifier_misconfigured` ("…
   AION_CEREMONY_AUTHORISATION_ANCHOR_INIT requires
   AION_CEREMONY_AUTHORISATION_ANCHOR_PATH").
5. Placement/distinctness (only when path set): resolved path
   equal to or inside resolved `AION_VERIFIER_HOME` →
   `verifier_misconfigured`; equality against each of
   `AION_ANCHOR_PATH`, `AION_BUDGETS_ANCHOR_PATH`,
   `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` (the consumption
   block's two-entry loop becomes a three-entry loop) →
   `verifier_misconfigured` naming the other variable.
6. Startup verification (runs before EVERY mode — one process
   per request): open `CeremonyAuthorisationLedger(home)`
   (exception → `ledger_failed`, "could not be opened for
   anchor verification"); `verify_anchor(ledger, path,
   kind="ceremony-authorisation")` (`AnchorError` →
   `anchor_refused`, invalid path); reasons ==
   `("anchor_missing",)` **and** INIT →
   `initialise_anchor(..., kind="ceremony-authorisation")`.
   `initialise_anchor`'s own established-ledger guard makes
   this an **empty-journal-only bootstrap**: a non-empty
   issuance journal with a missing anchor raises `AnchorError`
   → `anchor_refused` — it is NOT silently blessed, and
   recovery of an established journal is the audited
   `force_reanchor` path, exactly as for signing/consumption.
   Any remaining reasons → `anchor_refused` with the joined
   reasons.
7. `return _Config(...)` gains
   `ceremony_authorisation_anchor_path=(… or None)` and
   `ceremony_authorisation_anchor_init=(…)`.

One deliberate non-mirror: there is no budgets-style bespoke
anchor format here — like consumption, this journal uses
`trust/anchoring.py`'s generic anchor, not a hand-rolled file.

## 6. Commit order — `_mode_ceremony_authorise` steps (8)–(11)

New helper, mirroring `_update_ceremony_consumption_anchor`
(~line 949) line for line:

```python
def _update_ceremony_authorisation_anchor(config: _Config) -> None:
    """… no-op when unconfigured (research — no rollback
    claim); AnchorError is ledger_failed: the pair stands
    burned in the issuance journal …"""
    if not config.ceremony_authorisation_anchor_path:
        return
    try:
        update_anchor(
            CeremonyAuthorisationLedger(config.home),
            config.ceremony_authorisation_anchor_path,
            kind="ceremony-authorisation", recorded_at=_now())
    except AnchorError:
        raise _config(
            "ledger_failed",
            "the ceremony authorisation was recorded in the "
            "ceremony journal but its anchor update failed; "
            "the (ceremony_id, evidence_hash) pair stays "
            "burned and the envelope is withheld — retry "
            "under a new ceremony_id with a new evidence "
            "bundle")
```

Commit order changes from (8) journal append → (9) signing
append → (10) signing-anchor update to:

- **(8) `CeremonyAuthorisationLedger.append_authorisation` —
  the commit point (unchanged).**
- **(9) NEW: `_update_ceremony_authorisation_anchor(config)`.**
- (10) `SigningLedger.append_ceremony_authorisation` (was 9).
- (11) `_update_anchor(config)` — signing anchor (was 10).

Ordering rationale, mirroring consume's cycle-22 R2 order:
the journal's own anchor advances **before the mirror write**,
so a mirror failure at (10) followed by a verifier-home
rollback leaves the authorisation anchor *ahead* of the
rolled-back journal, and the re-issuance replay is refused at
startup (`anchor_refused`) instead of resurrecting the pair.
Anchor-after-mirror would leave a window in which mirror
failure + rollback makes journal and anchor agree on the
pre-issuance history while the pair is burned in the intact
journal's timeline only — precisely the cycle-22 defect shape.

Failure semantics at (9): anchor update raises → `ledger_failed`,
envelope withheld, pair burned (the journal append at (8)
stands). State plainly in the mode docstring the one asymmetry
this creates: at the moment of a (9) failure the signing
ledger has **no trace yet** of this issuance — the issuance
journal entry is the only record — whereas a (2)-step
consumption-anchor failure in consume happens with the burn
already journalled and the mirror still to come. On an intact
home the next startup verifies fine (anchor naming an older
prefix is staleness, not tampering) and the step-(5) scan
refuses the pair as reused, so the burn is enforceable; the
anchor catches up at the next successful issuance's (9).

The mode docstring's "Exact order" paragraph is rewritten
(8)–(11) with this rationale, mirroring how
`_mode_ceremony_consume`'s docstring states its R2 order.

## 7. Harness — `tests/cycle23_harness.py`

- `_INIT_KEYS` gains `"AION_CEREMONY_AUTHORISATION_ANCHOR_INIT"`
  (bootstrap step 1 sets all four INIT flags in the one
  research-mode invocation).
- `anchor_paths` dict gains
  `"authorisation": anchors_dir / "authorisation.anchor.json"`.
  The existing bootstrap assertion loop
  (`for name, path in anchor_paths.items(): assert is_file`)
  then asserts **four anchors** with no further edit — say so
  in the harness docstring, whose step-1 text ("initialising
  the signing / budgets / ceremony-consumption anchors")
  gains " / ceremony-authorisation".
- `steady_env` gains
  `"AION_CEREMONY_AUTHORISATION_ANCHOR_PATH":
  str(anchor_paths["authorisation"])`; the production env
  derived from it then satisfies both the verifier's
  production+seed requirement and (via §4) wiring's required
  set.
- Consumers `tests/test_trust_production_e2e.py` and
  `tests/test_cycle23_live_run.py` need no harness-side edits;
  e2e's existing `verify_anchor(... anchor_paths["consumption"]
  ...)` assertion pattern gains an authorisation twin (§9).

## 8. Test / fixture blast radius — full inventory

Verdicts: **BREAKS** = fails without the new keys;
**MASKED** = still passes but for the wrong reason (same
refusal code), fixture must gain the anchor to keep isolating
what it names; **UNAFFECTED** = research mode or anchor
unconfigured, helper is a no-op.

| File / fixture | Verdict | Required change |
|---|---|---|
| `tests/cycle23_harness.py` `provision_production_home` | **BREAKS** — production + seed; every production invocation refuses startup without the path | §7 |
| `tests/test_trust_wiring.py` `production_env()` | **BREAKS** — wiring `REQUIRED_ENV_KEYS` (§4) makes every `production_client` test refuse | add path (`anchors/ceremony-authorisation.anchor.json`); `test_init_flag_one_refused` flag loop gains the 4th INIT; new distinctness test mirroring `test_consumption_anchor_equal_to_signing_refused` |
| `tests/test_trust_pin_adoption.py` `prod_env` literal (~line 386, cases b/c) | **BREAKS** — `build_pin_adopter` → `production_client` refuses with `VerifierConfigError` before the expected `SigningError` | add path distinct from its `s.json`/`b.json`/`c.json` (e.g. `a.json`) |
| `tests/test_trust_production_deploy.py` `test_f_production_mode_successful_run_reports_production` | **BREAKS** — production + real seed via raw env, expects returncode 0 | add authorisation anchor path + `initialise_anchor(CeremonyAuthorisationLedger(home/"ledger"), …, kind="ceremony-authorisation", recorded_at="2026-11-20T12:00:00+00:00")` beside the existing consumption-anchor bootstrap |
| `tests/test_trust_production_deploy.py` `test_31_…` allowlisted literal | completeness | §3.10 |
| `tests/test_verifier_deploy.py` | count pin only | §3.9 |
| `tests/test_trust_ceremony_journal_anchor.py` `ConsumptionAnchorStartupTests._production_env` (`test_production_ceremony_without_consumption_anchor_refused`, `test_production_consumption_anchor_init_refused`) | **MASKED** — production + seed; both still get `verifier_misconfigured`, but from the missing authorisation path instead of the consumption condition under test | `_production_env` gains an initialised authorisation anchor (empty issuance journal) so the consumption condition is again the only failure |
| `tests/test_trust_ceremony_mode.py` `test_production_startup_refusals` | **MASKED (pre-existing pattern)** — already passes on the shared `verifier_misconfigured` code with other production gates unsatisfied; the new gate adds one more coincidental reason | no change required to pass; optionally note in the test comment. Do not "fix" its isolation in this item |
| `tests/test_trust_health_check.py` | check-and-update — fixtures are built around the setup.sh template / health-check copies; the §3.4–3.7 copy updates flow through, but any literal env dict naming the consumption pair must gain the authorisation pair | verify at build time; no production-mode startup is exercised here |
| Research-mode ceremony suites: `test_trust_ceremony_mode.py` (base), `test_trust_ceremony_authorisation.py`, `test_trust_ceremony_consume.py`, `test_trust_ceremony_consumption.py`, `test_trust_consumption.py`, `test_trust_consumption_schema_v2.py`, `test_trust_ceremony_journal_anchor.py` `AnchoredFixture` (research) | **UNAFFECTED** — authorisation anchor unconfigured ⇒ `_load_config` block skipped, update helper no-ops. This is by design and matches cycle 22's research behaviour | none |
| `tests/test_trust_production_e2e.py` (via harness) | fixed by §7; its `test_init_flag_in_production_env_refused` loop ("any of the three anchor families") gains the 4th flag | §9 |

## 9. New tests to write

New file `tests/test_trust_ceremony_authorisation_anchor.py`,
mirroring `tests/test_trust_ceremony_journal_anchor.py`'s
fixture and wrapper-patching technique (research mode, signing
+ authorisation anchors outside home, INIT bootstrap, then
INIT removed):

1. `test_mandatory_mirror_failure_then_rollback_refused` —
   THE mandatory adversarial test: authorise E (journal append
   + authorisation-anchor update land); snapshot home; second
   authorise attempt run with
   `SigningLedger.append_ceremony_authorisation` patched to
   fail — wait, order: the mirror failure must be on the
   *issuance under attack*. Exact form: authorise E1 cleanly;
   snapshot home; roll home back is wrong direction — use the
   consume test's shape transposed: bootstrap anchors;
   snapshot home (empty issuance journal, anchors at genesis);
   authorise E with the signing-mirror patched to fail ⇒
   `ledger_failed`, issuance journal has 1 entry, authorisation
   anchor seq == 1, signing ledger has no `sign` entry for E;
   restore home from snapshot (journal empty again, anchor
   untouched at seq 1); re-authorise the same evidence under a
   NEW ceremony_id via a fresh client ⇒ refused at startup
   with `anchor_refused`; no journal gained an entry.
2. `test_clean_authorise_rollback_refused` — clean authorise,
   snapshot-before/rollback-after ⇒ startup `anchor_refused`.
3. `test_issuance_journal_only_rollback_refused` — only
   `ceremony-authorisations.json` restored; anchor ahead ⇒
   `anchor_refused`.
4. `test_anchor_update_failure_burns_and_intact_replay_refused`
   — `update_anchor` patched to raise for
   `kind="ceremony-authorisation"` only ⇒ `ledger_failed`,
   journal entry stands, envelope withheld; replay on the
   intact home ⇒ `ceremony_evidence_reused` (or
   `ceremony_id_reused` for the same-id replay — assert the
   evidence variant with a new ceremony_id).
5. `test_append_anchor_window_rollback_reauthorise_succeeds` —
   CHARACTERISATION, pins the claim boundary: anchor update
   skipped (no-op patch) + mirror failure ⇒ `ledger_failed`;
   rollback home; re-authorise succeeds. A future window
   closure must flip this test deliberately.
6. `ResearchModeNoAnchorTests.test_research_no_anchor_rollback_reissue_succeeds`
   — CHARACTERISATION: no anchors configured; authorise,
   snapshot, rollback, re-issue same evidence under a new
   ceremony_id succeeds (the §1a defect, pinned as the
   no-claim boundary).
7. `AuthorisationAnchorStartupTests` — production env
   (mirroring `ConsumptionAnchorStartupTests._production_env`
   with all four anchors initialised): production + seed
   without authorisation path ⇒ `verifier_misconfigured`;
   production with authorisation INIT ⇒
   `verifier_misconfigured`; authorisation anchor inside home
   ⇒ `verifier_misconfigured`; authorisation anchor equal to
   each of signing / budgets / consumption ⇒
   `verifier_misconfigured` (three subtests); non-empty
   issuance journal + missing anchor + INIT ⇒ `anchor_refused`
   (empty-only bootstrap, §5.6).
8. Wiring-side additions (§8): allowlist 21 re-pin,
   INIT-flag loop, distinctness test in
   `test_trust_wiring.py`; e2e INIT loop 4th flag; e2e
   post-authorise `verify_anchor(..., anchor_paths[
   "authorisation"], kind="ceremony-authorisation") == ()`
   assertion beside the consumption one.

## 10. Documentation updates

- `trust/verifier_main.py` module docstring:
  (a) two new env entries after
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`, mirroring the
  consumption pair's wording ("optional: external anchor file
  for the ceremony authorisation (issuance) journal (kind
  "ceremony-authorisation", cycle 24); must live OUTSIDE
  AION_VERIFIER_HOME and be distinct from the signing,
  budgets and ceremony consumption anchor paths. When set,
  startup verifies the anchor on every invocation and every
  issuance advances it BEFORE the signing-ledger mirror
  write. Production mode with the ceremony seed configured
  REQUIRES the path and refuses the INIT flag; research mode
  with the path unconfigured makes NO rollback claim for
  issuances." + the INIT entry: "allows ONE bootstrap
  invocation to create the authorisation anchor for an EMPTY
  issuance journal; a non-empty journal with a missing anchor
  is NOT silently blessed (anchor_refused) — recovery is the
  audited force_reanchor path");
  (b) **rewrite the "NOT externally anchored" passage**
  (~lines 255–267): the issuance journal IS externally
  anchored (follow-up `ceremony-journal-anchoring` closed for
  both journals); replace with the consume-docstring claim
  form — with the anchor configured, an issuance whose anchor
  update completed survives a verifier-home rollback
  (detected at startup, `anchor_refused`); the
  append→anchor-update window is not protected against a full
  rollback inside it; research / unconfigured: no rollback
  claim, and the §1 statement (prevented against an intact
  journal; after a rollback, detectable only for
  same-ceremony_id reuse from the signing ledger, otherwise
  only by audit against retained envelopes) stands as the
  unconfigured-mode truth. Keep the §1b.1 point: a passive
  rollback bricks unconsumed envelopes (`ceremony_not_issued`)
  — never describe the unanchored mode as "resurrecting"
  envelopes.
- `trust/verifier_main.py` `_mode_ceremony_authorise`
  docstring: order paragraph (8)–(11) per §6.
- `trust/ledger.py` `CeremonyAuthorisationLedger` docstring:
  replace the "Rollback residual, stated plainly" paragraph
  with an "Anchoring (cycle 24)" paragraph mirroring
  `CeremonyConsumptionLedger`'s cycle-22 paragraph — anchored
  in its own right, verified at startup when configured,
  required in production when the ceremony seed is
  configured; window + unconfigured caveats; the old residual
  text retained as the explicit unconfigured-mode statement.
- `signing/pin_ceremony.py` (~line 301): the "Issuance-journal
  rollback residual" paragraph — update the "until the
  follow-up lands" clause to the configured/unconfigured form
  above (this is the adopter-side copy of the same claim; it
  must not keep saying "rollback-vulnerable until…" once the
  anchor exists).
- `trust/wiring.py` docstring + comments: counts per §3.1/§4.
- `trust/anchoring.py` docstring: kind enumeration per §2.
- `deploy/verifier-identity/README.md`: per §3.11.
- `internal/DECISION-CONSUMPTION-HEAD.md`: new dated addendum
  recording `ceremony-journal-anchoring` CLOSED (both
  journals), mirroring how cycle 22's narrowing was recorded
  — addendum, not a rewrite of history.

## 11. FIT ASSESSMENT — do not land this in cycle 24 with items 1–3

**Recommendation: record item 4 as the explicit remaining
follow-up (first build item of the next cycle), and land it in
cycle 24 only under the sequencing condition at the end of
this section.** The design above is complete and buildable as
written; the objection is coupling, not readiness.

Deciding factors, in weight order:

1. **Item 3's journal shape is not yet settled, and it decides
   this item's surface.** CROSS-CHECK-17 records item 3 as
   supersede Option A — "explicit, separately authorised,
   journaled supersession decision" (GPT's condition, Gemini
   concurring on scope). At the time of writing,
   `internal/cycle24-work/` contains no design-a/design-b yet:
   whether supersession rides the existing issuance journal
   (new entry kind / new mode threading authorise step (5b)
   and the commit order), or introduces its own journal, is
   undecided. If it introduces a journal, that journal is born
   unanchored and this exact exercise repeats next cycle —
   or, worse, item 4 anchors the issuance journal in the same
   cycle that item 3 changes what issuance entries mean. If
   supersession authorisations are themselves issued through
   `ceremony_authorise`, §6's commit order is a shared edit
   surface with item 3's threading.
2. **Shared-surface collisions with items 1–2 are certain,
   not hypothetical.** Item 2 (ceremony public key mandatory
   in `production_client`) edits the same function, the same
   `REQUIRED_ENV_KEYS` neighbourhood, and the same test file
   (`test_trust_wiring.py`) as §4. Item 1 (real production
   entry point) will construct its env against the allowlist —
   if both land in one cycle, the 19→21 count pins (§3.8/§3.9)
   and every production fixture in §8 must be written against
   whichever lands second, serialising the cycle's tail and
   putting the count arithmetic at risk of being pinned twice
   inconsistently (supersede may itself want env keys, which
   would make the true target 23, not 21).
3. **Blast radius is verifier-wide, and cycle 24 is already
   loaded.** The §5 block runs in `_load_config` before
   *every* mode: a defect refuses all traffic, not just
   ceremonies. §8 touches nine files including the shared
   production harness every cycle-23/24 e2e stands on.
   CROSS-CHECK-17's convergent cycle-24 scope is items (1),
   (2), (3), then (4) the cycles 14–16 re-review as its own
   war room — issuance anchoring is not in it. Adding a fifth
   build item with a verifier-wide startup surface, in the
   cycle whose output gates the re-review, spends review
   attention the re-review is owed.
4. **Deferral is cheap — §1 is why.** The verified residual is
   an evidence-reuse re-issuance requiring an active
   re-presentation by a presenter of a listed operator id
   after a single-file rollback; it cannot resurrect an
   envelope passively, cannot double-consume a movement, and
   is partially detectable today (same-ceremony_id trace in
   the anchored signing ledger; retained-copy audit
   otherwise). Nothing about items 1–3 makes it worse. A
   one-cycle deferral costs little; a coupled landing risks
   the cycle.

**Sequencing condition if the war room overrules:** land item
4 strictly *last* in cycle 24, after items 1–3 have merged,
and only if item 3's final design confirms supersession
creates **no new journal and no new env keys** (rides
`CeremonyAuthorisationLedger` / existing modes). In that case
§3's count pins are written once, against the post-item-3
allowlist, and §6's commit order is edited on top of item 3's
final authorise order, not beside it. If item 3 adds a journal
or env keys, item 4 stays follow-up and its design is re-run
with the supersession journal folded into the same anchoring
pass — one allowlist growth, one war room, both journals.

## 12. Open questions for the war room

1. §4's REQUIRED decision: is the war room content that a
   ceremony-free production client must name a fourth anchor
   (the consumption precedent says yes)? If no, the verifier's
   production+seed gate still refuses at startup — wiring
   would be knowingly weaker than for consumption, and that
   asymmetry needs a recorded reason, not silence.
2. Should startup verification of the issuance journal run
   even when the ceremony seed is unconfigured but the path
   is set? This design says yes (mirror consumption: the
   block is keyed on path presence, the production *requirement*
   is the seed-conditional part). Confirm the mirror is exact
   on this point.
3. Does the §9.1 mandatory test's transposed shape (mirror
   patched on the *issuance* under attack) satisfy the seats
   as the analogue of cycle 22's R2 mandatory test, or do they
   want the consume-shaped variant (clean issuance, then a
   *second* issuance as the replay vehicle after rollback of
   the first) as well? Both are specified in §9.1/§9.2 between
   them; naming one as THE mandatory test is a war-room call.
