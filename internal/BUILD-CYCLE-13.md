# BUILD — Cycle 13 (combined run): Protected Gate adoption (Item A) + production signed-path wiring (Item B)

Mandate: Dilip's approval in chat, 2026-11-20 ~14:56 MST ("do
something", replying to the proposal summary). Item A implements
internal/PROTECTED-GATE-PROPOSAL.md under the Protected Gate Rule —
the ONLY authorised edit of protected files, exactly as the
proposal specifies. Item B implements backlog
`production-signed-path-wiring` per the agreed designs in
internal/DESIGN-PRODUCTION-WIRING.md.

NUMBERING, stated once: this was one combined coordinator run
covering both items. Item B is the cycle recorded in loop state
as cycle 13. Item A was built and war-roomed in the same run but
is NOT recorded: its war room split (see REVIEW-CYCLE-13.md) and
the standing rule — nothing ships on a split decision, and
CoreLoop itself refuses a non-reconciled verdict — withholds its
ship pending Dilip's decision on the escalated finding. The
backlog item `gate-path-canonicalisation` therefore stays
`blocked`.

Baseline (coordinator-verified at run start): full suite 1081
tests, OK (skipped=25 — the live deployment had been wiped by
another VM OS reset; re-provisioned at close, see Live
operations).

## Staffing

15 coders, 5 pods of 3 (seat-1..seat-15). Item A: Pod D
(3, 4, 15) production changes; Pod B (2, 6, 7) tests + wording.
Item B: Pod C (9, 10, 11) module + lint; Pod E (12, 13, 14)
tests. War rooms: 6 reviewers per item from OTHER pods, blind
scores locked in the calibration log BEFORE reconciliation
(subjects `cycle-13-gate-adoption`, `cycle-13-build`; fix-round
re-review scores under `cycle-13-fixround`), one forced-dissent
seat per item (Item A rev-r6/seat-14; Item B rev-r6/seat-15).
External seats (seat-gpt, seat-gemini) are NOT part of this
record: both items' verdicts are PROVISIONAL until they review
the delta brief (internal/CROSS-CHECK-BRIEF-CYCLE-13.md).

## Item A — Protected Gate proposal, implemented exactly

1. **Gate adoption of path-policy/1** (`eval/gate.py`):
   `check_protected_paths` now judges the CANONICAL spelling via
   the shared policy and appends offenders as the canonical
   spelling; non-string/blank entries and uncanonicalisable
   spellings raise `GateInputError`. Import mechanics per the
   proposal's Round-C correction: a FUNCTION-LOCAL import of
   `trust.pathpolicy.canonicalise` inside the function (a
   module-level import cycles two ways; the option-(a)
   delegation flip was NOT taken — the policy still delegates to
   `oversight.approval.canonicalise_path`, so the spelling rules
   keep ONE source). `_normalise_path` DELETED (its only
   production user was the old check; a dead second normaliser
   is the proposal's rejected option-(b) failure mode). Module
   header amended honestly: the "Standard library only" claim
   now names the lazy policy import as the one stated exception.
   Nothing else in the gate changed.
2. **P-1** (`eval/registry.py`): `object_pairs_hook`
   duplicate-key rejection raising `CorruptRegistryError`,
   wired into `EvalRegistry._load`, and the SAME strict parse
   (constant/float/duplicate hooks) in `_disk_changed`, whose
   contract is preserved (any parse failure → "changed", never
   an exception; `CorruptRegistryError` is not a `ValueError`,
   so its catch was widened minimally).
3. **P-2** (`eval/calibration.py`): the mirror hook raising
   `CorruptCalibrationError` in `CalibrationLog._load`.
4. **Gate negative-integration test** (the test both external
   seats asked for): NEW `tests/test_protected_gate_adoption.py`
   (9 tests) — an otherwise-acceptable change carrying
   `core//loop.py` is refused `protected_path` with violations
   `("core/loop.py",)` through `evaluate_self_change`; canonical
   spelling likewise; control path accepts; uncanonicalisable
   spelling raises, no decision; a duplicate-key registry
   artefact is refused by the REAL verifier subprocess
   (`registry_untrusted`, zero signatures in the signing
   ledger — assertion tightened to the exact code in the fix
   round); loader-level legs for both protected loaders;
   import-cycle guards in both import orders.
5. **Drift pins flipped**: the differential harness's EXPECTED
   table now records the post-adoption shape (gate-miss and
   gate-stricter classes EMPTY and pinned empty; both-refuse
   rows are gate errors; `eval/` agrees unprotected), and
   `test_trust_pathpolicy.py`'s KnownDivergenceTests became
   AdoptionTests recording the closure as cycle-13 history, not
   a silent edit. `docs/PARSER-INVENTORY.md` P-1/P-2
   dispositions now read FIXED in cycle 13 (finding texts kept
   verbatim). Stale rationale comments in
   `trust/verifier_main.py` and `selfmod/canary.py` corrected
   (comment-only): both defences are now redundant
   defence-in-depth, and say so.

Verification (pods + reviewers, independently repeated): all 10
former gate-miss spellings return `("core/loop.py",)`;
import-order battery 10/10 fresh interpreters; duplicate keys
refused at every nesting depth in both loaders (reviewer
probes, incl. `\u`-escaped duplicates); suites — gate 31,
registry 39, calibration 19, pathpolicy 11, differential 13,
parser-inventory 23, adoption 9: all OK.

**Item A outcome: implementation complete; SHIP WITHHELD.** The
war room split 5 SHIP / 1 FIX on a finding outside the approved
proposal's scope — see REVIEW-CYCLE-13.md (rev-r6 F1) and the
escalation in the delta brief. The code stands in the tree,
fully tested; the loop records nothing for Item A.

## Item B — production signed-path wiring

Delivered, per internal/DESIGN-PRODUCTION-WIRING.md:

- **NEW `trust/wiring.py`** — the sanctioned production
  construction site. `production_client(verifier_env, *,
  expected_signer_id, expected_key_id, launch="same-user")`
  validates a copy of the env before any spawn: keys restricted
  to the wrapper's allowlist (ground truth: **14 names** — the
  design note's "15" is an arithmetic error in the note; the
  shipped `run-verifier.sh` has 14, verified by extraction and
  now pinned by a test that parses the wrapper at test time);
  the 5 core names + mode + both anchor paths required
  non-empty; mode exactly `production`; `*_INIT` flags refused
  except the verifier's own off-spellings (`""`/`"0"`); anchors
  absolute, distinct, resolved outside the verifier home;
  signer pin must equal the env signer id; key pin in
  `key-<16 hex>` form, supplied out-of-band (the factory never
  reads the key file); every error names the variable, never
  its value. `launch="wrapper"` RAISES (no silent fallback —
  the client has no command hook and the wrapper discards
  caller env by design). `open_production_store(memory_dir)`
  refuses genesis, reads the persisted mode WITHOUT
  constructing the store, requires `signed_only`, then
  constructs and binds the result to the inspected document
  (see fix rounds). `commit_production` is the strong form
  only: presented signed attestation mandatory,
  `require_attestation=True` hardcoded, state digest defaulted
  from the live store, signer pin mandatory (fix round), and
  NO `now=` anywhere in the module's public surface.
- **Lint extension** (`tests/test_trust_lint.py`): the counted
  allowlist now also counts `VerifierClient(` and
  `MemoryStore(` constructions (bare / attribute / import-alias
  forms): exactly one of each in `trust/wiring.py`;
  `memory/reuse.py`'s two `MemoryStore(` constructions as an
  explicit counted QUARANTINED exception.
- Exports added to `trust/__init__.py` (established pattern; no
  cycle — verified by the import battery).
- **Tests**: NEW `tests/test_trust_wiring.py` — 49 tests:
  refusal battery per class, no-value-leak probes, env-copy
  semantics, store-open refusals with tree-unchanged proofs,
  commit strong-form pins, the dynamic wrapper-allowlist test,
  and `LiveProductionWiringTests` against the real deployment
  (see Live operations).

### Scope reconciliation (Item B) — read against the item's title

The backlog title promises three things: wire production flows
through the sanctioned signed paths; the factories above; and
"migrate memory/reuse.py off the legacy unsigned exception".
Delivered: the factories + lint, per the cycle-10 reconciled
design note, which is the team's agreed scope for this item.
NOT delivered, stated plainly:

- **No production caller was wired — because none exists to
  wire.** Verified by grep at close (and independently by the
  dissent seat): outside `trust/wiring.py` and its re-export in
  `trust/__init__.py`, there are ZERO production references to
  `production_client` / `open_production_store` /
  `commit_production`. The loop's ship recording goes through
  `trust/shipcheck.record_ship` (itself the sanctioned signed
  path, with an in-process coordinator key — a different trust
  shape the design does not re-route), and the deployment
  health check drives the wrapper directly. The factory is the
  sanctioned site for the first production caller, fenced by
  the lint; it is not yet load-bearing, and this record does
  not pretend otherwise.
- **memory/reuse.py was NOT migrated.** Its two constructions
  remain, now as a counted, named QUARANTINED lint exception —
  the design note's explicit choice for this cycle. Counted is
  not temporary: the migration is split out as a named
  follow-on (below) so it cannot become permanent by default.

Follow-ons split out of this item at recording:
`reuse-legacy-migration` (NEW, added to the backlog in this
cycle's recording step) and the already-pending
`verifier-wrapper-routing` (seq 30 — the deployment-grade,
no-argument form the design describes). Item B is recorded as a
scope split, not as the title's full completion.

### Fix rounds (war-room driven; see REVIEW-CYCLE-13.md)

Round 1 closed: byte-binding of inspection→construction in
`open_production_store` (rev-r2 F1 — a post-inspection swap to
an unsigned file was OPENED via the constructor's in-memory
ratchet and the re-assert was tautological); strict parse hooks
at inspection (F2); refusal-type documentation (F3);
`commit_production`'s signer pin made MANDATORY (rev-r4 HIGH —
it defaulted to None and an attacker-signer envelope committed
unpinned) with the attestation-verifier non-binding declared in
the docstring as a limit of the strong form; lint subclassing +
name-reassignment blind spots pinned and the "any other
construction" claims scoped to the detected forms (rev-r5 F1);
`production_client` hardening — anchors refused when equal to
the key path, inside the registry dir, or a directory;
home/key/registry required absolute; whitespace-only required
values refused (rev-r3 F1 / rev-r6 F6 / rev-r1 Low-1);
laundering-surface sentence in each public docstring (rev-r6
F3); dynamic wrapper-allowlist test (rev-r6 condition 4).
Round 2 closed F1′ (rev-r2, second look): the straddle-ABA —
the constructed OBJECT is now bound to the inspected document
(`store.state_digest()` must equal the inspected document's
`state_digest` field), the two falsified docstring sentences
corrected, and the corrupt-swap quarantine side effect
documented (P5). Regression tests pin both swap shapes and a
pass-through control.

## Live operations performed

- Deployment re-provisioned from the wiped VM state via the
  documented ceremony (internal/REPROVISION-2026-11-20-B.md):
  `aion-verifier` recreated, production env, fresh key
  (`key-edff2c569bfce4b4`), staged code refreshed from the
  cycle-13 tree, registry re-provisioned (3 public / 6 sealed /
  1 golden; sealed manifest `574ff877a81f71c9…`), anchor INIT
  ceremony outside production, production smoke `sealed_eval`
  score 1.0 signed with effective mode "production", final
  operator budget reset.
- **Health check: 10/10 PASS** against the real deployment.
- **LiveProductionWiringTests: RAN and PASSED** (not a skip) —
  `production_client` built from the real root-owned env with
  operator-side pins drove the production verifier and the
  mode pin held at response time. This was the dissent seat's
  hard pre-record gate; satisfied before recording.
- Production deployment suite: 18 tests OK on the fresh budgets
  (test_10/test_11 ran and passed; back to their by-design skip
  state afterwards).

## Test totals

Full suite at close (coordinator run): **1145 tests, OK
(skipped=2)** — the 2 skips are live test_10/test_11 in their
by-design post-run state. Baseline 1081 → 1145: +64 net new
(pathpolicy +1, adoption +9, lint +5, wiring +49).

## Self-improvement delta

tests_passing 1081 → 1145 (evidence: coordinator full-suite run
at close; verifier rev-r1, a non-builder reviewer). Process
lesson recorded in REVIEW-CYCLE-13.md: two of this run's three
production defects (ratchet swap, unpinned-by-default commit)
were cases of a safety argument the code could not support —
the re-verification standard from cycle 12 (probe the invariant
the docstring asserts, with the finding seat's own technique)
caught both, and the dissent seat's scope audit caught the
third (an item title quietly outliving its delivery).
