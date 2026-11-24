# Cycle 27 — War-Room Review, Seat rev-r5

Slice reviewed: wiring + deploy coherence (`trust/wiring.py`,
`deploy/verifier-identity/{run-verifier.sh, setup.sh,
health_check.py, README.md}`), blind and independent. I did not
build this slice. Method: full `git diff`, full reads of
`wiring.py`, `setup.sh`, `health_check.py`, a repo-wide grep for
every anchor-env enumeration site, programmatic set/count
comparison of the three allowlist copies, and a spot-check of
`verifier_main.py`'s distinctness lists where the wiring
question touches it. Tests re-run by this seat:
`test_trust_wiring`, `test_verifier_deploy`,
`test_trust_health_check`, `test_cycle27_journal_anchors` —
93 tests, OK (13 skipped).

**Score: 0.82**
**Verdict: FIX**

The runtime wiring is sound — I found no bypass. The FIX is
driven by a factually wrong count shipped in the deploy README,
stale normative prose in the very file this cycle edited, and a
health checker that still cannot see any ceremony anchor
directly. None of these is a runtime hole; all of them are
exactly the coherence this slice exists to guarantee.

## What verifies clean

1. **`production_client` is genuinely generic — no
   consumption-specific hardcoding bypasses the new keys.**
   Every anchor rule iterates the module tuples, and both
   tuples were extended correctly:
   `_ANCHOR_ENV_KEYS` (5 names) drives the per-anchor loop —
   absolute path, resolved outside `AION_VERIFIER_HOME`, not
   equal to the key path, not equal to or inside
   `AION_REGISTRY_DIR`, not an existing directory — and the
   pairwise-distinctness double loop runs over all five
   resolved anchors, so issuance-vs-supersession and
   issuance/supersession-vs-consumption aliasing all refuse.
   `_INIT_ENV_KEYS` (5 names) drives the production INIT
   refusal generically (`""`/`"0"` only). Both new PATH keys
   are in `REQUIRED_ENV_KEYS`, which also makes the anchor
   loop's `env[name]` indexing safe (no unrequired key can be
   reached). A caller cannot smuggle the new anchors past any
   rule that the consumption anchor is subject to.
2. **The three allowlist copies agree exactly.** Programmatic
   check by this seat: `wiring.ALLOWED_ENV_KEYS` = 24 names,
   wrapper `ALLOWED_KEYS` = 24, `health_check.ALLOWED_KEYS` =
   24, and the three sets are equal. Tests pin 24 in both
   `test_trust_wiring` and `test_verifier_deploy` and pass.
   The task brief's "20 → 24" is the correct count.
3. **`setup.sh` provisions the anchor directory correctly.**
   The `install -d … "${BASE}/anchors"` line (0700,
   verifier-owned) pre-dates this cycle and covers all five
   anchor files, since the two new template paths live in that
   same directory
   (`/var/lib/aion-verifier/anchors/ceremony-issuance.anchor.json`,
   `…/ceremony-supersession.anchor.json`). The new template
   values are absolute, mutually distinct, distinct from the
   three existing anchor paths, and outside the verifier home
   — a template-filled deployment passes wiring's rules.
   Template-keys == allowlist is test-enforced and passes.
4. **`health_check.py`'s list-level updates are consistent:**
   `ALLOWED_KEYS` +4, `_INIT_KEYS` +2 (so the steady-state
   "no INIT flags" guard now covers both new flags), and
   `_PATH_KEYS` +2 (so both new paths get the absolute-path
   value check). The INIT guard and value validation iterate
   these tuples, so those checks really do cover the new keys.
5. **Verifier-side distinctness (spot-check, adjacent slice):**
   `verifier_main.py`'s issuance block checks distinctness
   against signing/budgets/consumption and the supersession
   block against all four predecessors, so pairwise coverage
   is complete, albeit asymmetric — the older consumption
   block naming only signing/budgets is compensated by the
   later blocks naming it. Not a finding.

## Findings

1. **[Deploy README — factual error introduced by this cycle]
   The cycle-27 paragraph added to
   `deploy/verifier-identity/README.md` states "allowlist
   19 → 23". The shipped allowlist is 20 → 24 (verified by
   count in finding-context 2 above; cycle 25's approver key
   was the 20th name). The README is the operator-facing
   record of the wrapper contract; a wrong count there is the
   kind of drift the wrapper/wiring/health equality tests
   exist to prevent in code, shipped in prose instead. Fix
   the number.
2. **[wiring.py — stale normative prose in the edited file]
   The code was updated but the module's own rule statements
   were not: the module docstring still says the wrapper
   allowlist is "(ALLOWED_KEYS, 20 names — the shipped wrapper
   governs)", that "all three anchor paths are required
   non-empty", and that "Both anchor paths must be absolute,
   distinct from each other…"; the comment above
   `ALLOWED_ENV_KEYS` repeats "(20 names)" and the comment
   above `REQUIRED_ENV_KEYS` repeats "all three anchor paths".
   There are now five anchor paths and 24 names. A reader
   trusting the docstring — which this module explicitly
   frames as its rule set — gets the pre-cycle-27 contract.
   Update the prose to five/24 (or drop the counts).
3. **[health_check.py — the new anchors are list-visible but
   check-invisible, as is consumption] The cycle extended the
   three lists but none of the substantive anchor checks:
   (a) `_validate_env_base_binding` binds only
   `AION_ANCHOR_PATH` and `AION_BUDGETS_ANCHOR_PATH` to
   `<base>/anchors` — the new paths (and consumption's) can
   point at any absolute location and pass;
   (b) `check_anchors()` verifies only the signing and budgets
   anchors against their ledgers — a missing, malformed or
   stale issuance/supersession anchor file produces no
   anchors FAIL (it surfaces only indirectly, as an
   effective-mode probe failure when the verifier refuses to
   start, with no anchor attribution);
   (c) `check_state_files()` owner/mode/symlink-checks only
   the signing and budgets anchor files — the new anchor
   files' ownership, world-access and symlink state are
   unchecked;
   (d) `check_env_file()`'s production block requires the
   ceremony evidence dir and seed path but no ceremony anchor
   path at all, so an env file missing both new PATH keys
   passes the env-file check that wiring and the verifier
   would refuse.
   In fairness: the new keys receive *exactly* the treatment
   consumption received in cycle 22 — there is no asymmetry
   between ceremony anchors, and this is a pre-existing gap
   the cycle inherited rather than introduced. But cycle 27's
   claim is that these two journals are now anchored "the
   same way", and the deployment's own drift detector cannot
   detect drift in three of the five anchors. Either extend
   (a)–(d) to all ceremony anchors, or record explicitly in
   the cycle record that health-check anchor verification
   remains signing+budgets-only by decision. Silence is the
   one option that should not ship.
4. **[Missed enumeration — test side]
   `tests/test_trust_production_e2e.py`'s
   `test_init_flag_in_production_env_refused` still sweeps
   only the three pre-cycle-27 INIT flags ("for any of the
   three anchor families") — the two new flags are not
   exercised there even though `production_client` would
   refuse them. `tests/cycle23_harness.py` *was* updated
   correctly, which makes the e2e omission a genuine miss
   rather than a pattern. Also stale, minor:
   `tests/test_trust_wiring.py`'s module docstring still
   describes the ground truth as "19 names" (its assertions
   were correctly re-pinned to 24), and a comment in
   `tests/test_trust_production_deploy.py` still calls the
   approver key "the 20th allowlisted name" in a context the
   new counts make confusing.
5. **[setup.sh / README — no migration path for existing
   deployments] `setup.sh` never overwrites an existing env
   file (by design), and the cycle adds no migration note —
   unlike the cycle-20 combined-migration note this README
   already carries as precedent. An existing production
   deployment upgraded to cycle-27 code will refuse to start
   (fail-closed, and correctly so) until the operator adds
   four lines and runs two INIT ceremonies, but nothing in
   the deploy docs tells the operator that, or that the two
   new anchor files must be bootstrapped before steady state.
   The new `setup.sh` template lines also ship without the
   explanatory comment block the consumption lines carry
   (outside-home, distinctness, production requirement). Add
   the migration note and the comment block.

## Bottom line

Wiring: ship-quality — the generic handling covers the new
keys completely, and I could not construct a wiring-level
bypass. Deploy coherence: not yet — finding 1 is a wrong fact
in the operator contract, finding 2 leaves the edited module
describing the old contract, and finding 3 needs either the
health-check extension or an explicit recorded decision.
Fix 1 and 2, resolve 3 one way or the other, and sweep 4–5;
then this slice has my SHIP.
