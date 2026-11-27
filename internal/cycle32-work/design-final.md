# Cycle 32 — Design (final): proof-carrying self-improvement prototype

New standalone module `trust/proofcarry.py`. A change that wants to
ship carries a *proof artefact*: a content-bound record declaring
invariants about the change, the evidence that they held, and enough
structure for an independent checker to re-run every declared check
itself and refuse the ship if the artefact does not reproduce. The
module composes with the existing ship path at exactly one seam
(§2); it modifies nothing protected.

Standing claim (verbatim — this is the whole claim, and §8 lists
what it excludes):

> A proof artefact establishes only this: the invariants it
> declares were executed by the independent checker against the
> exact tree contents bound in the artefact, each declared check
> passed on that tree, and each check was shown to fail on the
> pre-change tree (for invariants declared new) and on a mutated
> tree. It establishes nothing about properties the change did not
> declare, and it is not a proof of general correctness.

## 1. Placement and non-modification

- New file only: `trust/proofcarry.py`, plus its tests. No existing
  file is edited by this cycle.
- Untouched, by name: `eval/gate.py`, `eval/registry.py`,
  `eval/calibration.py`, `core/loop.py` (protected set), and
  `trust/shipcheck.py` itself — `check_ship` and `record_ship`
  keep their exact current signatures and behaviour. The wrapper
  below calls `record_ship`; it does not patch, wrap at import
  time, or reimplement any part of it.
- Reused, not reinvented: canonical serialisation and hashing are
  `signing.gate_decision._canonical` / `_sha256` (the same pair
  `trust/manifest.py` uses, so an artefact hashes under the same
  canonical discipline as a manifest); refusal is
  `trust.errors.ShipRefused` carrying the reason tuple; path
  spelling discipline follows `trust.manifest.canonicalise_path`
  (one canonical repo-relative spelling per path, backslash /
  `..` / non-canonical spellings refused, never normalised).

## 2. Composition seam: `record_ship_with_proof`

```python
def record_ship_with_proof(loop, *, artefact, base_root, post_root,
                           expected_change_id=None,
                           **record_ship_kwargs) -> dict
```

Order is the design:

1. `reasons = verify_proof_artefact(artefact, base_root=base_root,
   post_root=post_root, expected_change_id=expected_change_id)`.
2. If `reasons` is non-empty: raise
   `ShipRefused("proof artefact refused: " + ", ".join(reasons),
   reasons)` — **before** `record_ship` is called, therefore
   before the ship transaction opens, before any ledger burn,
   before any journal write. A refused proof spends nothing, not
   even a `REFUSED_PRE_BURN` transaction record: the attempt never
   reaches the state machine. This is strictly earlier than
   `record_ship`'s own pre-burn refusals, which do open a
   transaction.
3. If `reasons == ()`: delegate —
   `return trust.shipcheck.record_ship(loop,
   **record_ship_kwargs)` — arguments forwarded unchanged, return
   value (the loop history entry) returned unchanged, a
   `ShipRefused` from the delegate propagates unchanged.

Caller contract: `post_root` must be the same tree passed to
`record_ship` as `root`. The wrapper cannot itself prove that
identity in this prototype (see §7, scope-bounded binding, and
follow-up 1); the sanctioned caller passes one variable to both.

## 3. Artefact format `proof-artefact/1` — schema, field by field

The artefact is a JSON dict. Unknown keys at **every** level (top,
`changed_files` entry, invariant, mutation, evidence entry) are
refused as `artefact_malformed`; nothing is silently ignored, so a
future format version cannot smuggle semantics past this checker.

| Field | Type | Rules |
|---|---|---|
| `format` | str | Exactly `"proof-artefact/1"`. Anything else is malformed, not a version negotiation. |
| `change_id` | str | Non-empty. The change this artefact is about; matched against `expected_change_id` when the caller supplies one. |
| `created_at` | str | Timestamp string (builder stamps `_now()` when the caller passes `""`, the house pattern). Recorded for audit; **not** verdict-bearing — the checker makes no freshness judgement on it. |
| `scope_paths` | list[str] | Non-empty, sorted, deduplicated. Each entry a canonical repo-relative path naming a file or a directory the change touches. This list is the binding boundary (§4). |
| `base_tree_hash` | str | Lowercase hex64; tree hash (§4) of the pre-change tree over `scope_paths`. |
| `post_tree_hash` | str | Lowercase hex64; tree hash of the post-change tree over the same `scope_paths`. |
| `changed_files` | list[dict] | Sorted by `path`; the complete derived diff between the two trees inside scope (§4). May be empty only if the tree hashes are equal — in which case there is no change to carry proof for, and the invariants will fail discrimination/vacuity on their own terms. |
| `invariants` | list[dict] | Non-empty (empty → `no_invariants`). Declaration order is the checker's execution and reason order. See invariant table below. |
| `evidence` | list[dict] | Exactly one entry per invariant (§5). See evidence table below. |
| `artefact_hash` | str | Lowercase hex64; sha256 of `_canonical(artefact)` over every field **except** `artefact_hash` itself. Unkeyed integrity, not authenticity (§7). |

`changed_files` entry:

| Field | Type | Rules |
|---|---|---|
| `path` | str | Canonical repo-relative path, inside at least one scope path. |
| `base_sha256` | str \| null | Hex64 content hash in the base tree; `null` = the file is absent in base (added by the change). |
| `post_sha256` | str \| null | Hex64 content hash in the post tree; `null` = absent in post (deleted by the change). Both null is malformed — the entry would assert nothing. |

Invariant:

| Field | Type | Rules |
|---|---|---|
| `id` | str | Non-empty, unique within the artefact (duplicate → `invariant_duplicate:<id>`). |
| `description` | str | Non-empty human statement of the property. Audit surface only; the checker never parses it. |
| `argv` | list[str] | Non-empty list of non-empty strings. Executed with `shell=False`, `cwd` = tree root, 60 s timeout (§6). `argv` is code execution — see §7 before running any artefact. |
| `scope` | str | `"new"` or `"preserved"`. `"new"`: the property is created by this change — the check must **fail** on the base tree. `"preserved"`: the property predates the change — no base-tree requirement (it is expected to pass there too). |
| `mutation` | dict | `{path, content_b64}`; see below. Always explicit in the artefact — the builder resolves defaults before writing (§5), the checker never guesses a mutation. |

Mutation:

| Field | Type | Rules |
|---|---|---|
| `path` | str | Canonical repo-relative path of the file to perturb in a copy of the post tree. Must name a file (not a directory), must not escape the tree copy, no symlink components. |
| `content_b64` | str \| null | Base64 bytes to write at `path`; `null` = delete the file. Applying the mutation must make the invariant's check fail (checker §6 step 8). A mutation that leaves the target byte-identical to its post content is `mutation_invalid:<id>` — it cannot discriminate anything. |

Evidence entry (one per invariant, builder-run on the post tree):

| Field | Type | Rules |
|---|---|---|
| `invariant_id` | str | Must name a declared invariant; an entry naming none is `evidence_unexpected:<id>`, a declared invariant with no entry is `evidence_missing:<id>`. |
| `tree_hash` | str | Must equal the artefact's `post_tree_hash` (else `evidence_tree_mismatch:<id>`): evidence gathered on any other tree is not evidence about this change. |
| `exit_code` | int | The builder-run exit code (a JSON bool is not an int and is malformed). Non-zero → `evidence_failed:<id>`: the builder's own run already failed, so the artefact contradicts itself before the checker runs anything. |
| `stdout_sha256` | str | Hex64 of the builder-run stdout. The verdict-bearing cross-check (§5). |
| `stderr_sha256` | str | Hex64 of the builder-run stderr. Compared on re-run under the same determinism requirement as stdout (§5). |

## 4. Tree hash

`tree_hash(root, scope_paths) -> str`, deterministic:

- Walk each scope path under `root`. A scope path naming a file
  contributes that file; naming a directory contributes every file
  under it, recursively. Entries are deduplicated by path
  (overlapping scope paths do not double-count) and sorted by
  path.
- Excluded from the walk: any path with a `__pycache__` component
  and any `*.pyc` file. (Deliberate divergence from
  `trust/manifest.py`, which treats `__pycache__` as hostile and
  refuses the build: proofcarry *excludes* it, so proofcarry alone
  does not bind bytecode shadows — §7 states the consequence; in
  composition the manifest path still refuses them.)
- Symlinks are refused, anywhere the walk observes one (file or
  directory component): the walk raises, and the checker folds
  that to the side's tree-mismatch reason (§6) rather than hashing
  through a link. Non-regular files are refused the same way.
- A scope path **missing** from the tree contributes exactly one
  null entry `{path: <scope_path>, sha256: null, size: null}`.
  This is what makes a newly added file representable in the base
  tree: the base walk records the scope path as absent instead of
  the artefact being unbuildable for any change that creates a
  file.
- Each present file contributes `{path, sha256, size}` —
  repo-relative canonical path, hex64 content hash, byte size.
- The tree hash is `_sha256(_canonical({"format":
  "proof-tree/1", "entries": [...]}))` over the sorted entry list.
  An existing-but-empty directory contributes no entries (it ships
  nothing — same stance as the manifest).

`changed_files` is *derived*, never hand-authored: the builder
walks both trees over `scope_paths`, and the diff of the two
per-file hash maps (added / deleted / content-changed) **is**
`changed_files`. The checker re-derives it the same way (§6 step
4), so a hand-trimmed `changed_files` that hides a touched file
fails against the re-derived diff.

## 5. Builder

```python
def build_proof_artefact(*, change_id, scope_paths, base_root,
                         post_root, invariants,
                         created_at="") -> dict
```

Builder-side invariant specs carry the artefact invariant fields
plus an optional `target` path used only to resolve a default
mutation; `target` never appears in the artefact. For each
invariant, in order:

1. Resolve the mutation. Explicit `mutation` wins. Otherwise the
   default: revert the invariant's target file to its base
   content — `content_b64` = base64 of the file's base-tree bytes,
   or `null` (deletion) if the target is absent in the base tree.
   Neither `mutation` nor `target` supplied → the builder refuses
   (`ValueError`); an invariant without a discriminating mutation
   is not buildable.
2. Run `argv` on the **post tree** (`shell=False`, `cwd=post_root`,
   60 s timeout) and record the evidence entry:
   `{invariant_id, tree_hash: post_tree_hash, exit_code,
   stdout_sha256, stderr_sha256}`. A non-zero exit or a timeout at
   build time means the builder produces no artefact — shipping a
   self-failed artefact for the checker to refuse is possible but
   pointless, and the builder does not do it.
3. Compute `base_tree_hash`, `post_tree_hash`, the derived
   `changed_files`, then `artefact_hash` last, over the finished
   document.

The builder is the *sanctioned build path* §7 refers to: artefacts
enter the system from here, not from callers' hand-written JSON.

## 6. Checker: `verify_proof_artefact`

```python
def verify_proof_artefact(artefact, *, base_root, post_root,
                          expected_change_id=None) -> tuple
```

Returns a tuple of refusal reasons; `()` accepts. Reasons are
emitted in algorithm step order, per-invariant reasons in artefact
declaration order, deduplicated preserving first occurrence (the
`check_ship` pattern). Steps 1–2 return their single reason alone:
nothing in a structurally broken or hash-mismatched artefact —
above all its `argv` — is trusted enough to act on. Steps 3–5
accumulate, but if any of them produced a reason the checker stops
before step 6: **no check is ever executed against trees the
artefact does not correctly bind.**

1. **Schema.** Exact key sets at every level; types per §3
   (strict: bool is not int, hashes are lowercase hex64, sizes
   non-negative ints, `argv` a non-empty list of non-empty
   strings, paths canonical). Any failure →
   `("artefact_malformed",)`, return.
2. **Self-hash.** Recompute `artefact_hash` over the artefact
   minus that field. Mismatch → `("artefact_hash_mismatch",)`,
   return.
3. **Change binding.** `expected_change_id is not None` and
   `artefact["change_id"] != expected_change_id` →
   `change_id_mismatch`. (With no expected id the artefact is
   checked on its own terms; naming the expected change is the
   caller's replay defence at this seam.)
4. **Tree binding.** Recompute both tree hashes from `base_root`
   / `post_root` over `scope_paths`. Recomputed base ≠ declared →
   `base_tree_mismatch`; recomputed post ≠ declared →
   `post_tree_mismatch`. `post_tree_mismatch` is deliberately the
   one reason covering both *tamper* (the post tree changed after
   the artefact was built) and *stale-artefact replay* (an
   artefact built for change A presented against change B's tree
   — the trees differ, so the hash differs). Then verify
   `changed_files` against the walks: each entry's
   `base_sha256` / `post_sha256` must match the file's actual
   presence and content in the respective tree (a disagreement is
   that side's `base_tree_mismatch` / `post_tree_mismatch`), and
   the re-derived diff must equal `changed_files` as a set (an
   undeclared touched file → `post_tree_mismatch`).
5. **Invariant / evidence cross-validation** (no execution yet).
   No invariants → `no_invariants`. Duplicate invariant id →
   `invariant_duplicate:<id>`. Evidence set vs invariant set:
   missing → `evidence_missing:<id>`, undeclared →
   `evidence_unexpected:<id>`. Per invariant: evidence
   `tree_hash != post_tree_hash` → `evidence_tree_mismatch:<id>`;
   evidence `exit_code != 0` → `evidence_failed:<id>`. Mutation
   structurally invalid (bad path, undecodable base64, names a
   directory, byte-identical no-op) → `mutation_invalid:<id>`.
   If steps 3–5 produced any reason, return them now.
6. **Post-tree re-run.** For each invariant, run `argv` against a
   scratch copy of the post tree (`cwd` = copy root, `shell=False`,
   60 s timeout; scratch copies so a check with side effects
   cannot dirty the trees being verified, and so step 8 starts
   from pristine contents). Non-zero exit or timeout →
   `check_failed:<id>`. Exit 0 but the re-run's stdout hash ≠
   evidence `stdout_sha256` (stderr hash compared likewise) →
   `evidence_output_mismatch:<id>`.
7. **Base-tree discrimination — `"new"` invariants only.** Run
   `argv` against a scratch copy of the base tree. Exit 0 →
   `check_not_discriminating:<id>`: the check passes without the
   change, so it cannot be evidence *for* the change. (Its output
   is not compared to anything; only the exit code speaks.)
   `"preserved"` invariants skip this step by definition.
8. **Mutation vacuity — every invariant.** Validate and apply the
   mutation to a fresh scratch copy of the post tree (write the
   decoded bytes, or delete the file when `content_b64` is null);
   an application failure (target is a directory in the tree,
   parent component a symlink, …) → `mutation_invalid:<id>`. Run
   `argv` in the mutated copy. Exit 0 → `check_vacuous:<id>`: the
   check does not notice its own target being reverted/deleted,
   so its pass on the post tree proves nothing about that target.
   Non-zero or timeout counts as noticing — the check failed, as
   required.

Erratum (fix round, recording a supersession — the sentence
above is retained as history and no longer governs): for the
base-tree probe (step 7) and the mutation probe (step 8), a
timeout or a failure to spawn is NOT treated as noticing.
Those probes require an observed non-zero exit; a run that
produces no verdict (timeout, spawn error) is a refusal
(`check_not_discriminating:<id>` / `check_vacuous:<id>`),
because the standing claim says each check was *shown to
fail* on those trees, and a timeout shows nothing. The
post-tree run (step 6) is unchanged: a timeout there already
reports as `check_failed:<id>`.

Timeout rule, uniform across steps 6–8 and the builder: a timeout
is treated as "did not exit 0" for that run's comparison, partial
output is discarded, and on the post-tree run it therefore reports
as `check_failed:<id>`, never as an output mismatch.

### Evidence is content-bound, not self-reported

The checker **re-runs everything**. Evidence is never trusted as a
record of what happened; it is a *prediction* the artefact makes
about what the checker will observe, and the artefact is refused
when the prediction is wrong. Three bindings make self-reporting
useless to a lazy or dishonest builder: the evidence entry is
bound to the tree (`tree_hash` must equal `post_tree_hash`, and
that hash is recomputed from the real tree in step 4, not read
from the artefact); the predicted outcome is bound to the
checker's own execution (step 6 compares exit code *and* output
hashes against a fresh run); and the artefact as a whole is bound
by `artefact_hash`, so evidence cannot be edited after the fact
without invalidating the document (accidental-edit protection —
see §7 for why this is not authenticity). A builder that fabricates
evidence without running the checks produces an artefact whose
predictions fail in step 6 with `evidence_output_mismatch` (or
`evidence_failed` if it honestly records its own non-zero exit).

## 7. Threat model and honest limits

What this defends against: a ship proceeding on checks that were
never run, were run against different contents than the ones
shipping, no longer pass, or pass vacuously (a check that would
pass on the old tree, or on a tree with the change reverted).
Content binding plus mandatory re-execution plus the two failure
probes (base tree, mutated tree) close those four holes for the
declared invariants.

What it does not defend against, stated plainly:

- **Same-user process limits.** The checker, the trees, and the
  artefact all live under one OS user — the same limit the
  manifest module discloses for its walk. A malicious same-user
  process can rewrite tree and artefact together to a matching
  pair, or race the walk/run window (TOCTOU). Scratch copies
  narrow the run window; nothing here eliminates it, and no lock
  is held. `artefact_hash` is *unkeyed*: it detects edits that
  didn't recompute it, and nothing more. Authenticity of a ship
  still comes from the existing signed-decision path in
  `check_ship`, not from this artefact.
- **`argv` is code execution.** The checker executes whatever
  commands the artefact declares, with the checker's privileges;
  `shell=False` removes shell injection, not program choice —
  `argv[0]` is arbitrary. Therefore the checker must only ever be
  run on artefacts from the sanctioned build path (§5: built by
  `build_proof_artefact` inside the build pipeline for a change
  under review). Running an artefact from an untrusted source is
  running that source's code. This prototype has no argv
  allowlist and no sandbox (follow-up 3).
- **Determinism is a requirement, not a property.** Checks must be
  deterministic in exit code and output: a check that prints a
  timestamp, a pid, an absolute path, or unordered hash-map
  iteration will false-refuse at `evidence_output_mismatch`.
  That is the design working as specified — nondeterministic
  checks cannot carry reproducible evidence — but it is a real
  authoring constraint, and the execution environment
  (interpreter, installed packages, locale) is *not* bound in the
  artefact: builder and checker are assumed to run in the same
  environment (follow-up 4).
- **Scope-bounded binding vs the manifest's whole-tree binding.**
  A proof artefact binds only the contents under its
  `scope_paths`. A change outside scope is invisible to it, and
  the `__pycache__`/`.pyc` exclusion (§4) means bytecode inside
  scope is not bound by proofcarry at all. Neither gap is a hole
  in the *composition*, because `record_ship_with_proof` still
  delegates to `record_ship`, whose manifest binds the whole
  evaluated tree and refuses `__pycache__` outright — proofcarry
  is an additional gate, never the only one. But the converse
  obligation is real: nobody may cite a verified artefact as
  binding anything outside its `scope_paths`. Production
  composition would close the seam properly by having the
  artefact also carry the ship's `manifest_hash` and the wrapper
  refuse unless it equals the `manifest.manifest_hash` being
  shipped (and, symmetrically, a base manifest hash for the
  pre-change tree) — follow-up 1. Until then, the §2 caller
  contract (`post_root` is `record_ship`'s `root`) is
  operator-asserted, exactly as other caller duties in this repo
  are labelled.
- **Declared properties only.** The claim at the top is the
  ceiling. An artefact with one trivial-but-discriminating
  invariant verifies exactly as well as one with twenty meaningful
  ones; choosing invariants worth declaring is a review duty, not
  something the checker can grade.
- **Harness-presence gaming (disclosed in the fix round).**
  When the check harness itself is newly added by the change,
  base-probe discrimination can be satisfied by the harness's
  absence on the base tree: the check cannot run there, and
  under the observed-failure rule that absence counts as a
  refusal-grade non-pass rather than as evidence about the
  checked content. In that case the mutation probe is the
  load-bearing discrimination, which is why a mutation may
  never target the harness itself (a mutation path referenced
  by the invariant's `argv` is `mutation_invalid:<id>`):
  invariant authors should target mutations at the content
  under check, not at the script that checks it.

Terminology (added in the fix round): despite the format
name, this mechanism is check-carrying — author-declared
executable checks re-verified by re-execution — not
proof-carrying in the formal-methods (Necula) sense; no
logical proof object exists in the artefact, and nothing in
this design should be read as claiming one.

## 8. Non-claims

- Not a proof of general correctness (per the standing claim).
- No authenticity, signer, or non-repudiation claim: the artefact
  is unsigned and its hash is unkeyed.
- No claim about undeclared properties, out-of-scope files, or
  `state/` contents.
- No freshness claim: `created_at` is informational; replay of a
  *stale* artefact is refused only insofar as the trees or the
  expected `change_id` differ — replaying an artefact against the
  identical base/post trees it was built for is re-verification,
  and it passes, correctly.
- No concurrency claim: simultaneous checker runs against mutating
  trees are outside the sequential model, as elsewhere in `trust/`.

## 9. Test plan (for the build seat)

Happy path (build → verify `()` → `record_ship_with_proof`
delegates and returns the history entry) plus one failing-first
case per reason string: malformed schema / unknown key, hash
mismatch, base and post tree tamper after build, stale artefact
against a second change's trees, `change_id` mismatch, empty
invariants, duplicate id, evidence missing / unexpected /
wrong-tree / self-failed / output-mismatched (builder evidence
edited, hash recomputed — the step-6 case that proves evidence is
re-run, not trusted), post check failure, `"new"` invariant
passing on base, mutation still passing (vacuous), invalid
mutation (no-op and bad base64), a newly added file (null base
entry) and a deleted file (null post entry), symlink inside scope
refused, and the seam test: a refused artefact raises `ShipRefused`
with the ledger and tx journal byte-identical before and after —
nothing burned, nothing journaled.

## 10. Open follow-ups

1. Bind `manifest_hash` (and a base manifest hash) in the artefact
   and enforce equality in `record_ship_with_proof` — production
   composition, §7.
2. Keyed authenticity for artefacts (sign the artefact hash under
   the existing signing discipline) if artefacts ever cross a
   trust boundary; unnecessary while builder and checker are one
   pipeline.
3. `argv` allowlist or sandboxed execution before any artefact
   from outside the sanctioned build path is ever checked.
4. Bind an environment fingerprint (interpreter + relevant package
   versions) into evidence, or scope the determinism requirement
   explicitly per invariant.
5. Anchor the `artefact_hash` in the ship record (alongside
   `manifest_hash` in the tx journal) so a shipped change's proof
   artefact is itself part of the durable ship evidence.
6. Decide whether `"preserved"` invariants should also carry a
   base-tree *pass* requirement (currently: no requirement —
   a preserved invariant whose check fails on base but passes on
   post is indistinguishable from `"new"` at verify time, and is
   accepted; the distinction today is documentation plus the
   discrimination exemption).

## 11. Fix-round addendum — the mechanism field (dissent condition 5)

Added after re-review: every artefact carries a required
top-level field `"mechanism": "check-carrying/1"`, covered by
`artefact_hash`. `_artefact_malformed` refuses an artefact whose
mechanism field is absent or has any other value. The corrected
mechanism name therefore travels inside the artefact object
itself — the one artefact that can leave this repository — and
cannot be stripped without invalidating the artefact, rather
than living only in the producing code's docstrings. The format
identifier remains `proof-artefact/1`; the CLAIM's wording is
unchanged; no authenticity is claimed for the field beyond the
unkeyed hash (section 8 stands).

## 12. Fix-round addendum — external round 1 reconciliation (cycle 32-PROOF)

Status: this addendum is appended to `design-final.md` as §12 by
the coordinator. It DECIDES every round-1 external finding
(seat-gpt FIX 0.87, items F1–F4; seat-gemini FIX 0.86, items
G1–G4; record: `internal/CROSS-CHECK-32-PROOF.md`). Where this
addendum and §§1–11 disagree, this addendum governs; §12.9
lists the superseded statements by section. Two coder seats
implement from this document alone: every mechanism below names
the functions to add or change in `trust/proofcarry.py`, their
signatures, the step ordering, the exact refusal reason strings,
and the tests that must pin the behaviour. No other file's code
changes except tests and the CLAIM pin (test file) as specified
in §12.6; `trust/shipcheck.py`, `trust/manifest.py`, and
`core/loop.py` are NOT edited.

Coordinator-verified facts this addendum relies on (do not
re-litigate in implementation):

- `core/loop.py run_one_cycle` persists state via `save()`
  BEFORE returning a deepcopy of the history entry; mutating the
  returned entry does NOT persist, and `_check_delta` rebuilds
  the delta dict with only known fields (extra keys dropped).
  Neither the returned entry nor the delta is a durable carrier
  for the artefact hash.
- `trust/manifest.py` has an exact key set; `check_ship`
  rebuilds the manifest from the tree and compares hashes, so a
  caller-added manifest field is infeasible without deep
  surgery. The artefact hash is therefore NOT bound through the
  manifest (§12.1 binds it through the ship record instead).
- `record_ship_with_proof` receives the `ShipLedger` inside
  `**record_ship_kwargs` as `ledger=...`;
  `ledger.journal_dir` is the verifier-home directory that
  already holds the ship-ledger and ship-tx records.
- `record_ship` itself re-verifies the manifest against `root`
  AFTER recording and withholds finalise on drift;
  `anchored_record_ship`'s post-ship anchor-advance failure
  pattern ("the ship stands recorded; the refusal says so") is
  the house pattern for post-ship bookkeeping failure.

Refusal-string conventions for the whole addendum: checker
reasons are bare reason strings in the tuple returned by
`verify_proof_artefact`; the wrapper raises
`ShipRefused("proof_refused:" + ",".join(reasons), reasons)` for
every pre-delegation refusal, exactly as the current wrapper
does for verification reasons. New reason strings introduced
here: `unscoped_changes`, `check_side_effect:<id>`. Reused:
`post_tree_mismatch`, `mutation_invalid:<id>`.

### 12.1 Unscoped-edit refusal and artefact-hash binding (G1)

Problem: the artefact binds only its `scope_paths`
(design §4/§7), so a change that also edits files OUTSIDE scope
ships on a valid artefact while the out-of-scope edits are
invisible to proofcarry. In composition the ship manifest does
bind the whole evaluated tree, but nothing ties the VERIFIED
ARTEFACT to the WHOLE change that shipped. This section closes
both halves: refuse on any out-of-scope difference, and bind
the verified artefact hash durably into the ship's evidence.

#### 12.1.1 Whole-tree diff and the `unscoped_changes` refusal

New helpers in `trust/proofcarry.py`:

```python
def _expand_whole_tree(root) -> list
def _whole_tree_changed_paths(base_root, post_root) -> list
def _unscoped_changes(base_root, post_root, scope_paths) -> tuple
```

- `_expand_whole_tree(root)` walks the ENTIRE tree at `root`
  recursively and returns the sorted entry list
  `[{path, sha256, size}, ...]` with repo-relative POSIX paths,
  under proofcarry's existing walk discipline (the discipline
  of `_expand_scope`, generalised to a root walk): skip any
  directory named `__pycache__` and any `*.pyc` file; refuse
  (raise `ProofError`) on any symlink observed anywhere —
  symlink file, symlinked directory, or a symlink at any
  component the walk descends through — and on any non-regular
  file. Implement it by factoring the per-directory walk out of
  `_expand_scope` if convenient, but `_expand_scope`'s
  observable behaviour must not change.
- `_whole_tree_changed_paths(base_root, post_root)` returns the
  sorted list of paths whose `{sha256, size}` entry differs
  between the two whole-tree expansions, or that exist in only
  one of them. A `ProofError` from either expansion propagates.
- `_unscoped_changes(base_root, post_root, scope_paths)` returns
  the sorted tuple of changed paths `p` for which
  `_path_in_scope(p, scope_paths)` is False. Empty tuple means
  every whole-tree difference is inside the artefact's scope.

Placement (DECIDED): the check lives in
`record_ship_with_proof`, NOT in `verify_proof_artefact`.
`verify_proof_artefact`'s contract is scope-bounded by design
(§4): it answers "does this artefact reproduce against these
trees, over its scope", and the standalone demo artefacts are
built against full-repository trees whose out-of-scope
differences are expected and legitimate at verify time. The
unscoped-edit hole is a property of the SHIP composition —
the moment a scoped artefact is used to authorise a whole-tree
ship — so the refusal belongs at that seam, next to the other
composition duties. A caller that verifies standalone and ships
through any other route is outside the proof-gated composition
entirely (§12.8 states the coverage honestly).

Wrapper step W2 (full wrapper ordering is §12.2.2): after
verification accepts and before the snapshot is taken, compute
`unscoped = _unscoped_changes(base_root, post_root,
artefact["scope_paths"])`. If `unscoped` is non-empty, raise
`ShipRefused("proof_refused:unscoped_changes",
("unscoped_changes",))`. If the whole-tree walk raises
`ProofError` (symlink or non-regular file anywhere in either
tree), fold it to the same refusal —
`ShipRefused("proof_refused:unscoped_changes",
("unscoped_changes",))` — because a tree the walk cannot even
enumerate cannot be shown to be scope-clean; failing closed
with the composition's own reason is preferable to leaking a
builder-side exception type across the ship seam. This refusal
is pre-delegation: `record_ship` is never called, nothing is
burned, no transaction opens, no binding record is written
(the §9 seam property, extended).

Window argument (why W2 on the live trees is sufficient in
composition): the caller's manifest is built from the live
tree BEFORE the wrapper runs. A change outside scope that
exists at W2 time is in the whole-tree diff and refuses. A
change outside scope that lands after W2 but before the
snapshot (§12.2) enters the snapshot, and `check_ship`'s
rebuild of the manifest from the snapshot then differs from
the caller's manifest — refusal inside `record_ship`, pre-burn
(the transaction lands at `REFUSED_PRE_BURN`; nothing is
spent). A change that lands after the snapshot is not in the
snapshot and does not ship. There is no interleaving in which
an out-of-scope edit both escapes W2 and ships.

#### 12.1.2 Binding the verified artefact into the ship record

Two carriers, because only one of them is durable:

(a) Returned-entry fields (convenience, explicitly
non-durable). After `record_ship` returns the history entry,
the wrapper sets two keys on the RETURNED dict before
returning it:

```python
entry["proof_artefact_hash"] = artefact["artefact_hash"]
entry["proof_post_tree_hash"] = artefact["post_tree_hash"]
```

The entry `record_ship` returns is the loop's deepcopy, taken
after `save()`; these keys exist only on the object the caller
receives. They are an audit convenience for the calling
pipeline (which can log or display them immediately) and MUST
NOT be described anywhere as persisted loop state. The module
docstring for `record_ship_with_proof` states this in one
sentence.

(b) Durable binding record (the actual binding). After a
successful ship, append exactly one JSON line to the file
`proof-bindings.jsonl` in `ledger.journal_dir`:

```python
def _append_proof_binding(journal_dir, record) -> None
```

`record` has EXACTLY these keys:

| Key | Value |
|---|---|
| `cycle_id` | `entry["cycle_id"]` from the returned entry |
| `item_id` | `entry["item_id"]` from the returned entry |
| `change_id` | `artefact["change_id"]` |
| `manifest_hash` | `record_ship_kwargs["manifest"].manifest_hash` |
| `artefact_hash` | `artefact["artefact_hash"]` |
| `post_tree_hash` | `artefact["post_tree_hash"]` |
| `recorded_at` | `_now()` at append time (the `signing.gate_decision._now` already imported by this module) |

Serialisation and durability: one line =
`json.dumps(record, sort_keys=True, separators=(",", ":"),
ensure_ascii=False) + "\n"`, written with a single `write()`
to the file opened in append mode (`open(path, "a",
encoding="utf-8")`), then `flush()` and `os.fsync()` on the
file, then `os.fsync()` on a descriptor opened on
`journal_dir` itself (the directory-fsync pattern of
`trust/ledger.py._save`). `_append_proof_binding` raises
`OSError` on any failure; it does not catch.

Preconditions (checked at wrapper step W0, before any
verification or delegation): `record_ship_kwargs` must contain
`ledger` and `manifest`; if either is absent, raise
`ProofError("record_ship_with_proof requires ledger=... and "
"manifest=... so the proof binding can be recorded")`.
(`record_ship` requires both anyway; the wrapper checks first
because the binding is impossible without them, and a
`TypeError` from the delegate after a successful verification
would misreport the failure.)

Ordering and failure semantics (DECIDED, following the
`anchored_record_ship` anchor-advance pattern):

1. The binding append happens AFTER `record_ship` returns —
   it needs `cycle_id`, and a binding for a ship that did not
   happen must never exist.
2. The returned-entry fields (a) are set BEFORE the append, so
   a caller that catches the failure below still holds an
   entry naming the artefact.
3. If `_append_proof_binding` raises `OSError`, the wrapper
   raises `ShipRefused` with reasons `()` and the EXACT message
   shape of the house pattern:

   ```python
   raise ShipRefused(
       f"cycle {entry['cycle_id']} recorded and the decision "
       f"finalised, but the proof binding failed: {exc}")
   ```

   The ship STANDS: the cycle is recorded, the decision is
   burned and finalised, nothing is rolled back and nothing is
   refunded. The refusal exists so the failure is loud, never
   silent. The missing line in `proof-bindings.jsonl` is the
   anomaly signal, exactly as a stale ship-tx anchor is for
   `anchored_record_ship`: reconciliation is an operator act
   (append the record by hand from the artefact and the entry;
   every field is recoverable from those two objects plus the
   manifest).
4. If `record_ship` itself raises `ShipRefused`, it propagates
   unchanged: no entry fields, no binding append.
5. A torn final line (crash mid-write) is possible in
   principle despite the single-write discipline; this cycle
   ships NO reader for `proof-bindings.jsonl`, and the design
   states plainly that any future reader must refuse a
   malformed line rather than skip it.

Honest limit, stated for the record: `proof-bindings.jsonl` is
an append-only evidence file in the verifier home; it is not
hash-chained and not signed in this cycle. Its tamper-evidence
is cross-checking — a binding line is falsifiable against the
artefact, the manifest, and the ship ledger, all of which the
operator retains. Hash-chaining it (or anchoring it like the
ship-tx journal) is follow-up work, recorded in §12.9.

#### 12.1.3 Tests (G1)

In `tests/test_cycle32_proof_ship.py` (end-to-end) unless
noted:

- `test_unscoped_change_refused_before_burn`: post tree differs
  from base in one scoped file (valid artefact) AND one file
  outside `scope_paths`. `record_ship_with_proof` raises
  `ShipRefused` with `reasons == ("unscoped_changes",)`. Ship
  ledger entries, ship-tx journal bytes, and loop state are
  byte-identical before/after; `proof-bindings.jsonl` does not
  exist afterwards.
- `test_unscoped_addition_and_deletion_refused`: two variants —
  a file ADDED outside scope in post, and a file DELETED
  outside scope in post — each refuses with
  `("unscoped_changes",)`.
- `test_unscoped_pycache_difference_ignored`: the only
  out-of-scope difference is a `*.pyc` file inside a
  `__pycache__` directory; the ship proceeds (the ignore
  discipline applies to the whole-tree diff exactly as to the
  scoped walk).
- `test_scoped_ship_writes_proof_binding`: happy path. Assert
  (i) the returned entry's `proof_artefact_hash` and
  `proof_post_tree_hash` equal the artefact's; (ii)
  `proof-bindings.jsonl` in `ledger.journal_dir` contains
  exactly one line; it parses as JSON; its key set is exactly
  the seven keys of §12.1.2; `cycle_id`/`item_id` match the
  entry, `change_id`/`artefact_hash`/`post_tree_hash` match
  the artefact, `manifest_hash` matches the shipped manifest;
  (iii) the PERSISTED loop state (state file re-read from
  disk) history entry for that cycle does NOT contain either
  proof key — pinning that the bindings file, not the entry,
  is the durable carrier.
- `test_proof_binding_failure_ship_stands`: monkeypatch
  `trust.proofcarry._append_proof_binding` to raise
  `OSError("disk full")`. The wrapper raises `ShipRefused`
  whose message contains `"recorded and the decision
  finalised, but the proof binding failed"` and the cycle id;
  the ledger shows the burn AND the finalise for the decision;
  the loop history contains the cycle. (In
  `tests/test_trust_proofcarry.py` a unit variant with a fake
  delegate is acceptable for the message shape, but the
  end-to-end ledger assertion belongs in the ship suite.)

### 12.2 Verify-to-ship atomicity: the snapshot composition (F2)

Problem: verification reads the live post tree; `record_ship`
then ships the live post tree. Between the wrapper's final
re-hash and `record_ship`'s own manifest re-verification, the
tree can change. `record_ship`'s post-record re-verification
catches drift only AFTER the burn (the cycle is recorded, the
burn is left unfinalised as an anomaly) — the proof gate's
promise "what was verified is what ships" deserves a
construction, not a race outcome.

#### 12.2.1 Mechanism (DECIDED): snapshot, verify the snapshot, ship the snapshot

New helper in `trust/proofcarry.py`:

```python
import contextlib

@contextlib.contextmanager
def _snapshot_tree(root):
    """Yield the Path of a private snapshot copy of root."""
```

Behaviour: first run `_expand_whole_tree(root)` and discard
the result — this pre-walk refuses symlinks and non-regular
files BEFORE anything is copied, so the copy below never
dereferences a link the walk would have refused. Then create
a `tempfile.TemporaryDirectory(prefix="proofcarry-snapshot-")`,
`shutil.copytree(root, Path(tmp) / "tree", ignore=_IGNORE)`
(the existing ignore patterns: `__pycache__`, `*.pyc`;
`copytree`'s default `copy2` preserves the executable bit,
which the ship manifest binds — a snapshot that lost the bit
would fail `check_ship` against the caller's manifest), and
yield `Path(tmp) / "tree"`. The directory is removed when the
context exits, on success and on exception alike.

The wrapper then (full ordering in §12.2.2): verifies the
artefact against the SNAPSHOT as the post tree, and delegates
`record_ship(loop, root=<snapshot>, **record_ship_kwargs)`
while the snapshot context is still open. The snapshot lives
until `record_ship` returns or raises; only then is it
removed.

Why this removes the verify-to-ship window BY CONSTRUCTION:
after the snapshot is taken, the object that is verified and
the object that is shipped are the same bytes in a private
temporary directory that no other step in the pipeline writes
to. Mutations of the caller's live post tree after the
snapshot — by a stray build step, a background process, or the
loop's own recording machinery — cannot reach the snapshot.
`record_ship`'s manifest rebuild, its post-record
re-verification, and the cycle recording all read the
snapshot. There is no interval in which "verified" and
"shipped" name different trees, because they name one tree.

Why advisory file locks were REJECTED as the primary
mechanism: a lock (flock or lockfile) binds only cooperating
processes — every writer must take the same lock, and nothing
in the same-user threat model (§7) compels an arbitrary writer
to do so. A lock would therefore narrow the window only
against writers that already cooperate, while adding a
liveness hazard (a held lock across subprocess check runs and
a ledger transaction) and a false sense of closure. The
snapshot needs no cooperation: it removes the shared mutable
object instead of policing access to it. (A lock may still be
added later as defence in depth; it is not load-bearing and
is not added here.)

Residual, stated plainly: the caller's manifest is built from
the live tree BEFORE the wrapper runs, so the snapshot is not
the only comparison in the composition — it is checked against
that manifest inside `record_ship`. A change to the live tree
between manifest build and snapshot makes the snapshot differ
from the manifest, and `check_ship`'s rebuild comparison
refuses (pre-burn; the transaction lands at
`REFUSED_PRE_BURN`, nothing is spent). The composition is
fail-closed in both directions: live-tree drift after the
manifest build refuses the ship; live-tree drift after the
snapshot is simply not what ships. What the snapshot does NOT
do: protect the BASE tree (it is only ever read by the
checker's scratch probes, never shipped), and make
`verify_proof_artefact` standalone atomic (a caller that
verifies standalone and acts later on the live tree still has
the §7 race; the atomicity property belongs to this
composition).

Cost, accepted: the artefact's checks execute against the
snapshot in addition to the live-tree verification (§12.2.2
keeps both). Checks are already required to be deterministic
and reproducible (§7); a second full verification is the price
of making the shipped object the verified object, and it is
paid only on the ship path, not by standalone verification.

#### 12.2.2 `record_ship_with_proof` — full step ordering (DECIDED)

```python
def record_ship_with_proof(loop, *, base_root, post_root, artefact,
                           expected_change_id=None,
                           **record_ship_kwargs):
```

- W0. Guards, before anything else: `root` in
  `record_ship_kwargs` → the existing `ProofError("root is
  supplied by record_ship_with_proof")`. Missing `ledger` or
  `manifest` in `record_ship_kwargs` → the §12.1.2
  `ProofError`. Nothing has run, nothing is spent.
- W1. Live verification:
  `reasons = verify_proof_artefact(artefact,
  base_root=base_root, post_root=post_root,
  expected_change_id=expected_change_id)`. Non-empty →
  `ShipRefused("proof_refused:" + ",".join(reasons), reasons)`.
  (Unchanged from the current wrapper, including its
  post-verification re-hash, which is subsumed by W4 but kept
  so standalone behaviour of this step is byte-identical.)
- W2. Unscoped refusal (§12.1.1): non-empty unscoped tuple or
  a `ProofError` from the whole-tree walk →
  `ShipRefused("proof_refused:unscoped_changes",
  ("unscoped_changes",))`.
- W3. Enter `with _snapshot_tree(post_root) as snapshot:`.
  A `ProofError`/`OSError` while snapshotting propagates as
  `ShipRefused("proof_refused:post_tree_mismatch",
  ("post_tree_mismatch",))` — the post tree could not be
  captured, so it cannot be bound; nothing is delegated,
  nothing is spent.
- W4. Snapshot verification (authoritative):
  `reasons = verify_proof_artefact(artefact,
  base_root=base_root, post_root=snapshot,
  expected_change_id=expected_change_id)`. Step 4 of that
  verification IS the re-hash of the snapshot
  (`tree_hash(snapshot, scope_paths)` must equal
  `artefact["post_tree_hash"]`). Non-empty reasons →
  the same `proof_refused:` `ShipRefused` as W1, raised inside
  the context; the snapshot is discarded; nothing is spent.
- W5. Delegate INSIDE the context:
  `entry = trust.shipcheck.record_ship(loop, root=snapshot,
  **record_ship_kwargs)`. A `ShipRefused` from the delegate
  propagates unchanged (this includes the manifest-vs-snapshot
  drift refusal of §12.2.1's residual, and any post-burn
  refusal `record_ship` itself raises — the snapshot does not
  mask the delegate's own semantics). Exit the context
  (snapshot removed) only after this call returns or raises.
- W6. Set the returned-entry proof fields (§12.1.2a).
- W7. Append the binding record (§12.1.2b), with the
  ship-stands failure semantics of §12.1.2 step 3. Return the
  entry.

Note the deliberate asymmetry with the current code: the
current wrapper delegates `root=post_root`; after this
addendum it NEVER passes the live post tree to `record_ship`.
The §2 caller contract ("`post_root` must be the same tree
passed as `root`") is discharged by the wrapper itself.

#### 12.2.3 Tests (F2)

In `tests/test_cycle32_proof_ship.py`:

- `test_live_tamper_during_recording_is_harmless`: the
  deterministic race test. Define a loop subclass of the real
  `CoreLoop` used by the existing ship suite:

  ```python
  class _TamperPostTreeLoop(CoreLoop):
      def run_one_cycle(self, *args, **kwargs):
          # Tamper with the LIVE post tree at the worst
          # moment: after verification, during recording.
          (self._tamper_target).write_bytes(b"tampered\n")
          return super().run_one_cycle(*args, **kwargs)
  ```

  where `_tamper_target` is a scoped file inside the live
  `post_root`. Ship a valid artefact through
  `record_ship_with_proof`. Assert: the ship FINALISES (entry
  returned; ledger contains the finalise; the ship-tx journal
  reaches `COMMITTED`); the tamper really landed (the live
  file's bytes are the tampered bytes and differ from the
  manifest's recorded hash for that path — the test is not
  vacuous); and the proof binding line exists with
  `post_tree_hash == artefact["post_tree_hash"]`. This test
  must FAIL against the pre-addendum wrapper (which delegates
  the live tree: `record_ship`'s post-record re-verification
  sees the tamper and withholds finalise) — that failing-first
  property is the point of the test, and the coder seat
  records it in the build record.
- `test_pre_call_tamper_refuses_before_burn`: build the
  artefact and the manifest, THEN tamper a scoped file in the
  live post tree, then call the wrapper. `ShipRefused` with
  `post_tree_mismatch` among the reasons; no burn in the
  ledger; no binding line. (Extends the existing
  `test_tampered_post_tree_refused_before_burn`; keep both.)
- `test_snapshot_removed_after_ship_and_after_refusal`:
  monkeypatch `trust.proofcarry._snapshot_tree` with a
  wrapper that records the yielded path; after a successful
  ship and after a delegate refusal, the recorded path no
  longer exists.
- `test_manifest_built_before_live_change_refuses`: build the
  manifest from the live tree, change a scoped live file,
  restore the file's artefact-relevant state so W1/W4 pass is
  NOT the refusal under test — precisely: change a file that
  is inside the manifest's tree but OUTSIDE the artefact's
  scope is already §12.1's case; for this test change a scoped
  file and then change it BACK to the artefact contents but
  with the executable bit flipped (manifest binds the bit,
  proofcarry does not, §12.5). W1 and W4 pass; the snapshot
  carries the flipped bit; `check_ship` refuses inside
  `record_ship`. Assert `ShipRefused` propagates, the ledger
  has NO burn (pre-burn refusal), and no binding line exists.
  This pins the §12.2.1 residual: manifest-vs-snapshot drift
  is fail-closed.

### 12.3 Scratch isolation and side-effect refusal (G2)

Problem: the checker already runs its probes in scratch copies
(design §6), but (i) a check that WRITES to its scratch tree
can manufacture its own pass — write the expected output file,
overwrite the content under check, delete the failing case —
and the current checker never looks at the scratch tree after
the run; and (ii) the BUILDER still runs its evidence runs on
the live post tree (§5), so a builder check with side effects
dirties the very tree the artefact then binds, and its recorded
output may describe a tree state that no longer exists.

#### 12.3.1 One scratch runner for checker and builder (DECIDED)

Replace `_scratch_run` and the bespoke step-8 copy logic with
one helper in `trust/proofcarry.py`:

```python
def _run_in_scratch(argv, root, scope_paths, *, mutation=None):
    """Run argv in a fresh scratch copy of root.

    Returns (result, side_effect, applied):
      result     -- (exit_code, stdout, stderr), or None when
                    the copy or the run could not be made
                    (no verdict exists);
      side_effect -- True when the scratch tree's scope hash
                    after the run differs from before it;
      applied    -- False only when a requested mutation could
                    not be applied (result is then None).
    """
```

Exact behaviour:

1. Create a `tempfile.TemporaryDirectory()`; the copy always
   lives at `<tmpdir>/tree` (the uniform-basename property of
   the current `_scratch_run` is preserved — every probe
   presents the same `cwd` basename, so a check that prints
   its working directory's name stays deterministic).
   `shutil.copytree(root, dest, ignore=_IGNORE)`. Any
   `OSError`/`shutil.Error` during the copy →
   `(None, False, False)` when a mutation was requested, else
   `(None, False, True)`.
2. If `mutation` is not None, apply it to the copy exactly as
   the current step 8 does (write the decoded bytes, creating
   parent directories, or delete the file when `content_b64`
   is None). If the target is a directory in the copy, or the
   application raises `OSError` → `(None, False, False)`.
3. Pre-run hash: `pre = tree_hash(dest, scope_paths)`. For a
   mutation run this hash is taken AFTER the mutation is
   applied (the mutation is the intended difference; only the
   CHECK's writes count as side effects). A `ProofError` here
   → `(None, False, applied)`.
4. `result = _safe_run(argv, dest)` (unchanged semantics: None
   on spawn failure or timeout).
5. Post-run hash: `post = tree_hash(dest, scope_paths)`; a
   `ProofError` here (the check planted a symlink or a
   non-regular file in scope) counts as a side effect.
   `side_effect = (post != pre) or post-hash-failed`.
6. Return `(result, side_effect, True)`.

Every run — checker steps 6, 7, 8 and the builder's evidence
run — goes through this helper, each in a FRESH scratch copy.
No run ever reuses another run's copy (the current step 8's
stage-then-copy double copy is deleted; one copy, mutation
applied in place, is sufficient now that the pre-run hash is
taken after application).

Checker integration (in `verify_proof_artefact`): for each
invariant, each step evaluates its run as follows, in this
precedence order:

- If `side_effect` is True: add `check_side_effect:<id>` and
  DISCARD the run's verdict entirely — the step draws no other
  conclusion from that run (no `check_failed`, no
  `evidence_output_mismatch`, no `check_not_discriminating`,
  no `check_vacuous`, no `mutation_invalid` from that run).
  A pass manufactured by writing to the tree does not count,
  and a failure observed in a tree the check itself dirtied
  proves nothing either.
- Otherwise the step's existing verdict logic applies to
  `result` unchanged (§12.4.3 adds one rule to step 8 only).

Step-specific notes: step 6 (post) — a side-effect-free run is
compared to evidence exactly as today. Step 7 (base) — the
discrimination verdict comes only from a clean run. Step 8
(mutation) — `applied is False` → `mutation_invalid:<id>`
(existing rule, now reported by the helper); a clean,
applied, non-crashing observed failure is noticing (§12.4.3).

Builder integration (in `build_proof_artefact`): SUPERSEDES
§5 step 2's "run `argv` on the post tree". The builder now
runs each check via
`_run_in_scratch(entry["argv"], post_root, scope)` and:

- `result is None` → raise the same class of `ProofError` the
  builder raises today for an unrunnable check
  (`check could not be run` wording may be retained).
- `side_effect is True` → raise
  `ProofError(f"check_side_effect:{entry['id']}: the builder "
  f"check modified its scratch copy of the post tree; "
  f"refusing to build the artefact")`.
- `result[0] != 0` → the existing refusal (no artefact for a
  failing change), unchanged.
- Otherwise record the evidence entry from `result` exactly as
  today (`stdout_sha256`/`stderr_sha256` over the scratch
  run's output).

The builder NEVER runs a declared check against the live post
tree after this addendum. The live trees are only ever read
(hash walks) by builder and checker alike.

Scope of the re-hash, and its residual (stated, not hidden):
the pre/post comparison is `tree_hash` over the artefact's
`scope_paths` — the contents the artefact binds. A check that
writes INSIDE its scratch tree but OUTSIDE scope, or anywhere
outside the scratch tree (the temp directory's parent, the
operator's home, a network service), is not detected by this
comparison. The first half is acceptable because out-of-scope
scratch contents cannot affect the verdict about bound
contents in any later step (every step starts from a fresh
copy of the LIVE tree, never from a previous scratch copy);
the second half is the execution-environment limit the CLAIM
now states (§12.6): scratch isolation protects the EVIDENCE,
it does not sandbox the check.

#### 12.3.2 Tests (G2)

In `tests/test_trust_proofcarry.py`:

- `test_check_side_effect_refused`: a check script (inside the
  tree, run as `[sys.executable, <script>]`) that appends a
  line to a scoped content file in its `cwd` and then exits 0
  printing a fixed string. Builder evidence is produced by
  hand-running the script's logic cleanly (or by a builder run
  of a clean variant — the coder seat constructs the artefact
  so step 6's scratch run is the dirty one). `verify` returns
  exactly `("check_side_effect:<id>",)` for a single-invariant
  artefact whose other probes are clean — in particular NOT
  `evidence_output_mismatch` and NOT an accept.
- `test_base_probe_side_effect_voids_run`: a `new` invariant
  whose check, on the base scratch copy, writes to a scoped
  file and exits non-zero. Reasons contain
  `check_side_effect:<id>` and do NOT contain
  `check_not_discriminating:<id>` (the dirty run's failure is
  void, not discrimination).
- `test_mutation_probe_side_effect_voids_run`: a check that
  passes cleanly on post, fails cleanly on base, and — keyed
  on the mutated file's content — writes to a scoped file
  before exiting non-zero on the mutated copy. Reasons
  contain `check_side_effect:<id>` and neither
  `check_vacuous:<id>` nor `mutation_invalid:<id>` for that
  invariant.
- `test_builder_side_effect_raises`: `build_proof_artefact`
  with a check that writes to a scoped file in its `cwd`
  raises `ProofError` whose message contains
  `check_side_effect:<id>`; no artefact is returned.
- `test_builder_and_checker_leave_live_trees_untouched`: a
  check that writes a NEW file `scratch-marker.txt` at its
  `cwd` root (outside `scope_paths`, so no side-effect
  refusal) and otherwise passes/fails as its invariant
  requires. After `build_proof_artefact` and after
  `verify_proof_artefact`, assert neither the live base nor
  the live post tree contains `scratch-marker.txt`, and both
  trees' whole-tree expansions (`_expand_whole_tree`) are
  identical before and after. This pins "the builder moved
  off the live tree" and "the checker never dirtied a live
  tree" as observable facts, not intentions.

### 12.4 Mutation rules: scope, presence, harness closure, crash signatures (G3)

Problem: `mutation_invalid` today checks the mutation path
against the invariant's `argv` strings and against the post
tree's file set, but a mutation can still (i) target a file
outside the artefact's scope, (ii) target a file the harness
transitively depends on (an imported helper the `argv` strings
never name), so the mutated run "fails" because the harness
broke, not because the check noticed the content change, and
(iii) step 8 counts ANY observed non-zero exit as noticing,
including an import/syntax crash of the harness itself.

#### 12.4.1 Pre-execution rules (checker step 5) (DECIDED)

Change the signature of the existing validator:

```python
def _mutation_invalid_reason(inv, post_files, post_root,
                             scope_paths) -> bool
```

(the one internal caller, in step 5, passes
`artefact["scope_paths"]`). It returns True — the caller adds
`mutation_invalid:<id>`, and no `argv` is executed for the
artefact, per the existing steps 3–5 early return — when ANY
of the following holds. Rules 1–3 are new; rule 4 is the
existing set, retained verbatim:

1. Scope: `not _path_in_scope(mpath, scope_paths)`. A mutation
   must perturb bound content; a target outside scope is
   invalid even if it exists in the post tree. (The default
   mutation always targets a changed file, which is in scope
   by construction, so this rule bites only explicit
   mutations.)
2. Presence: `mpath not in post_files` (existing rule, kept in
   this position: a mutation must name a file present in the
   post tree — including the delete case, where presence in
   post is what makes the deletion a perturbation).
3. Harness dependency: `mpath in
   _harness_dependencies(inv["argv"], post_root)` (new, §12.4.2),
   OR the existing `_mutation_references_argv(mpath,
   inv["argv"])` test. Either test marks the target as part of
   the harness.
4. Existing rules, unchanged: malformed path spelling
   (`_check_scope_path` raises); undecodable `content_b64`;
   target unreadable in the post tree; decoded content
   byte-identical to the post content (the no-op rule).

#### 12.4.2 Harness dependencies: argv files plus their local-import closure

New helper in `trust/proofcarry.py`:

```python
def _harness_dependencies(argv, root) -> set
```

Returns the set of canonical repo-relative paths (POSIX
spelling, as `_check_scope_path` would accept) that the check
harness consists of, computed against the tree at `root` (the
checker passes the POST tree — the harness whose failure step
8 must not mistake for noticing is the post tree's harness):

- Seeds: for each `argv` element `e`, let `cand` be `e` with
  one leading `"./"` stripped if present. If `cand` passes
  `_check_scope_path` and `(root / cand)` is a regular file
  and not a symlink, add `cand`. (Elements that are flags,
  absolute interpreter paths, or expressions simply seed
  nothing. The existing `_mutation_references_argv` string
  test remains as a second, independent net for spellings
  this resolution does not reach — e.g. a bare basename.)
- Closure: process the seed set as a worklist. For each member
  ending in `.py` not yet parsed, read it and `ast.parse` its
  bytes; on `SyntaxError`/`ValueError` the file contributes no
  imports (it stays a dependency itself; an unparseable harness
  file fails step 6 on its own merits). For every
  `ast.Import` and `ast.ImportFrom` node:
  - `ast.Import`: for each alias, the module path is
    `alias.name` split on `"."`.
  - `ast.ImportFrom` with `level == 0`: the module path is
    `node.module` split on `"."` (skip if `node.module` is
    None).
  - `ast.ImportFrom` with `level >= 1`: resolve relative to
    the importing file's directory, ascending `level - 1`
    further directories, then append `node.module`'s parts if
    `node.module` is not None.
  - For a module path `parts` resolved against a base
    directory `base` (for absolute imports: BOTH the tree
    root AND the importing file's directory are tried, in
    that order — checks run with `cwd` = tree root, and
    same-directory imports are the other common layout), the
    candidate files are `base/parts.py` and
    `base/parts/__init__.py`, and additionally, for each
    proper prefix of `parts`, `base/prefix/__init__.py`
    (package files the import machinery loads along the way).
    A candidate that exists under `root` as a regular
    non-symlink file is added to the set (and, if `.py`,
    queued for parsing). Candidates outside `root`, symlinks,
    and missing files are skipped silently — the closure is a
    conservative approximation of what the interpreter will
    load from THIS tree, nothing more.
- Termination: each `.py` file is parsed at most once; the
  worklist empties because the tree is finite.

The direction is deliberately over-inclusive: a file the
harness MIGHT load is treated as harness. Over-inclusion
costs the author a different mutation target; under-inclusion
would let a harness break masquerade as discrimination.

Builder note: the builder does NOT pre-validate mutations
against the closure (it never has validated mutations beyond
resolving defaults). An artefact whose mutation targets a
harness dependency builds fine and is refused by the checker
at step 5. That asymmetry is retained deliberately — the
checker is the authority — and is stated here so no coder
seat "helpfully" adds a builder path that could diverge.

#### 12.4.3 Step 8 crash signatures (DECIDED)

New constant and helper in `trust/proofcarry.py`:

```python
_HARNESS_CRASH_MARKERS = (
    "ModuleNotFoundError", "ImportError",
    "SyntaxError", "IndentationError",
)

def _harness_crash_in_stderr(stderr: bytes) -> bool:
    text = stderr.decode("utf-8", errors="replace")
    return any(marker in text for marker in _HARNESS_CRASH_MARKERS)
```

In step 8, after the side-effect precedence of §12.3.1, a
clean applied run is judged in this order:

1. `result is None` (spawn failure/timeout) →
   `check_vacuous:<id>` (unchanged: no observed failure, per
   the §6 erratum's observed-failure rule).
2. `result[0] == 0` → `check_vacuous:<id>` (unchanged).
3. `result[0] != 0` and `_harness_crash_in_stderr(result[2])`
   → `mutation_invalid:<id>`, and NOT noticing: the run
   crashed in the harness's own machinery, which is exactly
   the failure mode §12.4.1 rule 3 cannot fully exclude in
   advance (dynamic imports, runtime-computed module names).
   A mutation that breaks the harness proves nothing about
   whether the check notices the CONTENT change.
4. Otherwise (observed non-zero exit, no crash marker) → the
   check noticed; no reason.

Conservative direction, stated for authors: this rule cannot
distinguish a harness crash from a check that SEMANTICALLY
reports a missing import — a check whose genuine failure
output contains any of the four marker strings (for example,
a check that verifies error text by printing
`ImportError: ...` to stderr before exiting 1) will be
refused `mutation_invalid:<id>` on its mutated run even
though its failure was semantic. That false refusal is
accepted by design: the checker has no sound way to tell the
two apart from outside the process, and the failure direction
must favour refusing a possibly-vacuous artefact over
accepting a possibly-broken harness. The author's remedy is
to choose a mutation whose failure mode is a clean assertion
or output difference, or to keep the marker strings out of
the check's failure output.

Why step 7 (the base probe) is UNCHANGED: on the base tree a
crash signature is frequently the EXPECTED shape of
discrimination — when the change adds the harness itself, the
base run cannot start, and the observed-failure rule already
treats "cannot run" as `check_not_discriminating` while a
crash exit counts as the failure the claim requires (§7's
harness-presence disclosure). Applying the crash rule at
step 7 would refuse every new-harness invariant. Step 8 is
different in kind: it runs on the POST tree, where step 6 has
already shown the harness runs cleanly, so a crash there can
only have been caused by the mutation — and a
mutation-caused harness crash is the mutation's defect, not
the check's sensitivity.

#### 12.4.4 Tests (G3)

In `tests/test_trust_proofcarry.py`:

- `test_mutation_out_of_scope_invalid`: explicit mutation
  naming a file present in the post tree but outside
  `scope_paths` → `mutation_invalid:<id>` in the step-5
  reasons, and (sentinel-argv pattern, as in the existing
  hash-tamper test) the check's `argv` is never executed.
- `test_mutation_transitive_import_invalid`: post tree has
  `check.py` (the `argv` target) doing `import helpers.util`,
  with `helpers/__init__.py` and `helpers/util.py` present;
  the mutation targets `helpers/util.py` — a path appearing
  in NO `argv` element — and also a variant targeting
  `helpers/__init__.py`. Both → `mutation_invalid:<id>`.
  A second variant uses a package-relative import
  (`from .util import ...` inside a package) with the mutation
  on the relatively-imported file → `mutation_invalid:<id>`.
- `test_mutation_of_imported_data_file_still_valid`: the
  check reads (does not import) a data file and asserts on
  its content; the mutation targets that data file; the
  artefact verifies `()` on the happy path (the closure must
  not swallow plain data reads).
- `test_mutation_dynamic_import_crash_is_invalid_not_noticing`:
  the check loads a module whose NAME it reads from a plain
  config file (so the module is in neither `argv` nor the
  static closure); the mutation rewrites the config file to
  name a nonexistent module, so the mutated run exits
  non-zero with `ModuleNotFoundError` on stderr. Reasons
  contain `mutation_invalid:<id>` and NOT
  `check_vacuous:<id>`, and the artefact is refused (the crash
  does not count as noticing).
- `test_mutation_semantic_crash_word_refused_conservatively`:
  the mutation targets a plain data file; the check's
  semantic failure path prints a line containing
  `ImportError` to stderr and exits 1 on the mutated tree.
  Reasons contain `mutation_invalid:<id>`. The test name and
  docstring record that this false refusal is the DECIDED
  conservative direction of §12.4.3, so a future reader does
  not "fix" it as a bug.
- Regression (no new test): the existing base-probe tests
  (`test_probe_cannot_run_on_base_not_discriminating` and the
  happy-path tests whose harness is new in post) must pass
  unchanged, pinning that step 7 acquired no crash rule.

### 12.5 Tree hasher audit: what is already true, and the mode decision (G4)

No mechanism change to `tree_hash` / `_expand_scope` is
required by round 1 beyond the `_expand_whole_tree`
generalisation of §12.1.1. This section audits what the
current code already does (verified against
`trust/proofcarry.py` as built), decides the two open points,
and pins the rest with tests so the properties cannot erode
silently.

Already true (audited, with the enforcing code):

- Symlink refusal at prefixes: `_refuse_symlink_prefixes`
  checks EVERY component of every scope path with
  `os.path.islink` before the exists/file/dir dispatch, so a
  symlinked intermediate directory named by a scope path is
  refused, not walked through.
- Symlink refusal in the walk: `_expand_scope` refuses any
  symlinked directory it encounters (checked before the
  `__pycache__` pruning, so a symlinked `__pycache__` is
  refused, not skipped) and any file that is a symlink or not
  a regular file; a scope path naming a non-file non-directory
  is refused outright.
- Refusal, never normalisation, of non-canonical spellings:
  `_check_scope_path` refuses empty strings, backslashes,
  leading or trailing `/`, and any empty, `.` or `..`
  component. `_validate_scope_paths` returns the SORTED SET of
  the validated spellings — duplicates collapse, spellings are
  never rewritten into a canonical cousin. `_artefact_malformed`
  additionally requires an artefact's `scope_paths` to be
  exactly sorted and duplicate-free, so a hand-written
  artefact cannot smuggle a second spelling past the checker.
- Dedup of overlapping scope entries: `_expand_scope`
  accumulates entries in a dict keyed by path, so a file
  reached through two overlapping scope paths (a directory
  and a file inside it) contributes exactly one entry, and the
  entry list is emitted sorted by path. `proof-tree/1` hashes
  that deduplicated list.
- Missing scope paths contribute exactly one null entry
  `{path, sha256: None, size: None}` (the added-file
  representation, §4).

DECIDED — file mode: DOCUMENT, do not bind. Tree entries
continue to carry content hash and size ONLY
(`{path, sha256, size}`); `tree_hash` does not observe the
mode. Rationale: proofcarry's binding is a CONTENT binding —
that is what the CLAIM says (§12.6: "the binding covers tree
contents only") — and checks are invoked through an explicit
`argv` (typically an interpreter plus a script path), not by
executing tree files in place, so the executable bit is not
part of what a check's verdict describes. The composition
covers mode where it matters: the ship manifest's file
entries DO bind the executable bit
(`trust/manifest.py`: entries carry `executable`, and
`verify_manifest` reports `executable_flip`), and
`check_ship` rebuilds that manifest from the shipped tree, so
inside `record_ship_with_proof` a mode flip on a shipped file
refuses the ship (pinned by §12.2.3's
`test_manifest_built_before_live_change_refuses`). Standalone
`verify_proof_artefact` does NOT bind mode, and the module
docstring gains one sentence saying exactly that, next to the
existing `__pycache__` disclosure: a mode-only change is
invisible to proofcarry alone. Any future change to bind mode
in `proof-tree/1` is a format change (new format string), not
a silent strengthening, and the pinning test below is written
to fail if the hash starts observing mode.

DECIDED — the root itself: DOCUMENT. `tree_hash` does not
check whether `root` itself is a symlink. `root` is supplied
by the operator (the same operator duty as `record_ship`'s
`root`); a symlinked root resolves every scope under the
operator's chosen anchor, and there is no second party whose
tree identity could be confused by it. The module docstring
states this in one sentence. Roots BELOW the anchor are a
different matter and are refused, per the audit above.

Accepted race, restated for completeness: between the walk's
symlink check and the subsequent file read, a same-user
process could swap a link in (the same accepted race
`trust/manifest.py` discloses). §12.2's snapshot removes this
race from the SHIP composition for the post tree; standalone
verification keeps the §7 disclosure.

Demo reproduction (G4's tail): the demo artefact must be
reproducible from a fresh construction of the same change —
pinned by `test_fresh_construction_reproduces_hashes` below
rather than by a one-off manual rerun.

#### 12.5.1 Tests (G4)

In `tests/test_trust_proofcarry.py`:

- `test_symlink_variants_refused`: four sub-cases, each making
  `tree_hash` raise `ProofError` (and, through the wrapper
  paths that fold walk failures, refusing rather than
  hashing through): (i) a symlinked FILE inside a scoped
  directory; (ii) a symlinked DIRECTORY inside a scoped
  directory; (iii) a scope path whose intermediate component
  is a symlink; (iv) a scope path naming a symlink directly.
- `test_noncanonical_scope_spellings_refused`: the builder
  raises `ProofError` for each of `"a//b"`, `"a/./b"`,
  `"a/../b"`, `"/abs"`, `"a/"`, `"a\\b"`, `""` as a scope
  path; and an artefact carrying any of them (with the
  artefact hash recomputed over the tampered document)
  verifies as `("artefact_malformed",)`.
- `test_overlapping_scopes_deduplicated`: with scope
  `["pkg", "pkg/mod.py", "pkg"]` the builder's entry
  expansion contains `pkg/mod.py` exactly once, and
  `tree_hash(root, ["pkg", "pkg/mod.py"])` equals
  `tree_hash(root, ["pkg"])`.
- `test_mode_not_bound_by_tree_hash`: `chmod` a scoped file
  `+x` between two `tree_hash` calls; the hashes are EQUAL.
  The test docstring cites this section: mode is bound by the
  ship manifest in composition, deliberately not by
  `proof-tree/1`.
- `test_fresh_construction_reproduces_hashes`: build the same
  change twice in two independent temporary directory pairs
  (identical file contents, fixed `created_at` passed to the
  builder); the two artefacts are byte-identical including
  `artefact_hash`, and both verify `()`. This is the
  fresh-clone reproduction property, exercised at unit scale;
  the repository-scale demo artefact continues to be
  regenerated by its in-repo generator.

### 12.6 The CLAIM — final text (F1, F3)

F1 and the environment half of F3 are resolved by NARROWING
the claim to what is actually enforced, not by building a
sandbox (seat-gpt's round-2 condition expressly allows
"boundaries enforced OR threat model narrowed"; §12.3–§12.5
enforce the tree-internal boundaries, and this section
narrows everything outside the tree). The `CLAIM` constant in
`trust/proofcarry.py` is replaced, verbatim and in full, by:

> A proof artefact establishes only this: the invariants it declares were executed by the independent checker against the exact tree contents bound in the artefact, each declared check passed on that tree, and each check was shown to fail on the pre-change tree (for invariants declared new) and on a mutated tree. The binding covers tree contents only: checks run as ordinary subprocesses with the checker's privileges and inherited environment, and the execution environment, the interpreter, and anything outside the tree a check reads or writes are not bound by the artefact. It establishes nothing about properties the change did not declare, and it is not a proof of general correctness.

This is the final text. It keeps the round-1 claim's core
sentence untouched in substance (executed / passed / shown to
fail on base and mutated trees / nothing about undeclared
properties / not a proof of general correctness) and adds
exactly the three round-1 qualifications, in the same
declarative discipline: the binding is over tree CONTENTS;
checks are ordinary subprocesses carrying the checker's
privileges and inherited environment (no env scrubbing, no
privilege drop, no sandbox — stated as fact, not apology);
and the execution environment, the interpreter, and anything
outside the tree that a check reads or writes are outside the
binding. The coder seats update BOTH copies of the pinned
text — the `CLAIM` constant in `trust/proofcarry.py` and the
`CLAIM` literal in `tests/test_cycle32_claim_pin.py` — to this
exact string (whitespace-normalised equality is what the pin
checks; the sentence must match after normalisation).

Claim-pin banned-phrase additions (DECIDED): the following
phrases are ADDED to `BANNED_PHRASES` in
`tests/test_cycle32_claim_pin.py`:

- `hermetic execution`
- `binds the execution environment`
- `environment is bound`
- `runs in a sandbox`
- `guarantees the execution environment`
- `isolated execution`

Collision check (performed at design time, re-verified by the
existing `test_banned_phrases_do_not_collide_with_claim`):
none of the six is a substring of the new CLAIM (the claim
says the environment is NOT bound — none of the affirmative
spellings above appears in it), and none appears in the
current text of `trust/proofcarry.py` or in §§1–11 of this
design (the module says "no sandboxing beyond `shell=False`",
which contains none of the six spellings). One mechanical
consequence the coder seats MUST implement with the addition:
this addendum itself has to be able to NAME the phrases it
bans, so once §12 is appended to `design-final.md`, the pin's
design-file scan (`test_no_overclaim_phrases_in_design_final`)
is changed to scan only the part of the file BEFORE the
`"\n## 12."` heading — the §§1–11 design document — with a
comment in the test saying why (the reconciliation record
quotes banned phrases in order to ban them, exactly as the
test file itself does and is likewise not scanned). The
module scan (`test_no_overclaim_phrases_in_proofcarry`) is
NOT narrowed: `trust/proofcarry.py` must never contain any
banned phrase anywhere, including comments, so the coder
seats must not copy this section's list into the module.

### 12.7 Ship-path coverage (F4)

Every route by which a cycle can be recorded, and its proof
status after this addendum (DECIDED — this enumeration is the
honest coverage statement; nothing in it is aspirational):

| Route | What it is | Proof-gated? |
|---|---|---|
| `CoreLoop.run_one_cycle(...)` called directly | The raw recording entry point in `core/loop.py`. Any in-process, same-user code that can import `core.loop` and construct a loop can call it; NOTHING in-process prevents that, and this prototype does not pretend otherwise — the identical limit is stated in `trust/shipcheck.py`'s own docstring for the signed path. | No. Guarded only by the call-graph lint tradition (see the static guard below): production code outside the pinned call sites fails the suite. |
| `trust.shipcheck.record_ship` | The sanctioned signed ship path (check, burn, record, re-verify, finalise). | Not by itself. Proof is an ADDITIONAL gate that exists only in the composition below; `record_ship` alone requires the signed decision, manifest, release and pinned ledger head, and no proof artefact. |
| `trust.shipcheck.anchored_record_ship` | The production recording path: `record_ship` with the expected ledger head derived from the ship anchor, plus the ship-tx anchor advance. | **No — explicit deferral.** This prototype does not compose the proof wrapper with the anchored path. Any document, docstring, or build record that describes the anchored production path as proof-gated is WRONG until the follow-up below lands. |
| `trust.proofcarry.record_ship_with_proof` | The proof-gated composition over `record_ship` (§§2, 12.1, 12.2): verification, unscoped refusal, snapshot, snapshot verification, delegation, binding record. | Yes — the only proof-gated route. |

The deferred enforcement, stated precisely: the named
follow-up is a function
`anchored_record_ship_with_proof(loop, *, base_root,
post_root, artefact, expected_change_id=None,
**anchored_record_ship_kwargs)` in `trust/proofcarry.py`
that performs W1–W4 of §12.2.2 against a snapshot and
delegates to `trust.shipcheck.anchored_record_ship` with
`root=<snapshot>`, then performs W6–W7 (entry fields and the
§12.1.2 binding record, taking `manifest_hash` and
`journal_dir` from its kwargs exactly as §12.1.2 specifies).
Until that function exists and the production caller uses it,
the production path is signed-only. This deferral — not a
silent gap — is the round-2 answer to F4 for the anchored
route, together with the guard test below for the raw route.

Wording rule (binding on all new prose in code, design, and
build/review records from this addendum on): never write
"the ship path requires proof", "ships require proof",
"all ships require proof", or "every ship requires proof"
without the qualifier. The qualified form is: "the ship path
requires proof **when composed via
`record_ship_with_proof`**". The guard test below pins the
four unqualified spellings as absent from
`trust/proofcarry.py`.

Static guard test (new file
`tests/test_cycle32_ship_path_guard.py`): AST-scan every
`.py` file under the production roots — the same root tuple
as `tests/test_trust_lint.py`'s `PRODUCTION_ROOTS`
(`core`, `eval`, `memory`, `signing`, `selfmod`, `oversight`,
`trust`, `machine`, `products`, `deploy`) — counting CALL
sites (`ast.Call` nodes whose func is an `ast.Attribute` with
the watched attr, or an `ast.Name` with the watched id;
definitions, docstrings, and string literals are not calls).
Pin the observed sanctioned sets EXACTLY — any added or
removed call site fails the test until this pin is updated
deliberately in a reviewed change:

- `run_one_cycle(` — exactly:
  `{"trust/shipcheck.py": 1, "trust/pin_adoption.py": 1,
  "trust/runner.py": 1}` (respectively: the ship route of the
  table above; the pin-adoption path's own signed discipline;
  the runner path — both pre-existing sanctioned non-proof
  routes, recorded here so the enumeration is complete).
- `record_ship(` — exactly:
  `{"trust/shipcheck.py": 1, "trust/proofcarry.py": 1}` (the
  call inside `anchored_record_ship`, and the proof wrapper's
  delegation). Exact-name matching keeps
  `record_ship_with_proof` and `anchored_record_ship` calls
  from being miscounted here.
- `anchored_record_ship(` — exactly `{}` in production code:
  the production path currently has NO production caller (it
  is exercised from tests and operator tooling). The empty
  pin is the point: the first production caller must arrive
  as a deliberate, reviewed pin update — which is also the
  moment the deferred composition above must be revisited.

The guard inherits the trust lint's stated blind spots
(getattr-style indirection, `functools.partial` wrapping,
name reassignment are not detected by a static AST scan) and
says so in its module docstring; it is enforcement by test
against evolved/convenience code paths, which is the threat
model, not a barrier against a determined same-user caller —
the same sentence the shipcheck docstring already carries.
The same test file also asserts the §12.7 wording pin: none
of the four unqualified spellings appears in
`trust/proofcarry.py`.

### 12.8 Round-1 findings — resolution map

| Finding | Resolution (one line) |
|---|---|
| F1 (execution binding vs hermetic execution) | CLAIM replaced verbatim (§12.6): binding is over tree contents only; environment, interpreter, and out-of-tree reads/writes are expressly not bound. |
| F2 (verify-to-ship atomicity) | Snapshot composition (§12.2): the wrapper verifies and ships one private snapshot copy; the live tree is never delegated, and manifest-vs-snapshot drift refuses pre-burn. |
| F3 (filesystem/process containment) | Tree-internal boundaries enforced (§12.4 harness closure + crash rule, §12.5 symlink/spelling audit pinned by tests); everything outside the tree narrowed out of the claim (§12.6) — no sandbox is built or claimed. |
| F4 (ship-path coverage) | All four recording routes enumerated with honest proof status (§12.7); the anchored composition is an explicit named deferral, and a static guard test pins the exact sanctioned call-site sets. |
| G1 (unscoped-edit hole + artefact binding) | Whole-tree base..post diff in the wrapper refuses `unscoped_changes` for any out-of-scope difference (§12.1.1), and the verified artefact hash is bound durably via `proof-bindings.jsonl` plus the returned entry's proof fields (§12.1.2). |
| G2 (scratch isolation + side effects) | Every run — checker steps 6–8 AND the builder — executes in a fresh scratch copy re-hashed over scope afterwards; a difference refuses `check_side_effect:<id>` (checker) or raises `ProofError` (builder) and voids the run (§12.3). |
| G3 (mutation rules) | Mutation targets must be in scope, present in post, and outside the harness's argv-plus-transitive-local-import closure (§12.4.1–12.4.2); a harness-crash signature on the mutated run is `mutation_invalid:<id>`, never noticing (§12.4.3); step 7 is unchanged. |
| G4 (proof-tree/1 hardening) | Audit confirms symlink refusal (prefixes and in-walk), refuse-don't-normalise spellings, and path dedup are already enforced and are now pinned by tests; file mode is DECIDED document-not-bind, covered in composition by the ship manifest's executable bit (§12.5). |

### 12.9 Statements in §§1–11 superseded by this addendum

- Standing claim (unnumbered, top of document): REPLACED by
  the §12.6 claim, verbatim.
- §2, step 3 and the caller-contract paragraph: the wrapper no
  longer delegates with the caller's `root` and no longer
  returns the delegate's entry unchanged — it delegates
  `root=<snapshot>` (§12.2.2 W5), augments the returned entry
  (§12.1.2a), and appends the binding record (§12.1.2b). The
  caller contract "`post_root` must be the same tree passed to
  `record_ship` as `root`" is DISCHARGED by the wrapper and is
  deleted as a caller duty.
- §5, step 2 ("Run `argv` on the post tree", `cwd=post_root`):
  SUPERSEDED by §12.3.1 — the builder runs every check in a
  fresh scratch copy and refuses on side effects.
- §6, step 6: EXTENDED by §12.3.1 (post-run scope re-hash;
  `check_side_effect:<id>`; a dirty run's verdict is void).
- §6, step 8: the double-copy application procedure is
  REPLACED by §12.3.1's single-copy `_run_in_scratch` with the
  pre-run hash taken after application, and its verdict rule
  ("non-zero counts as noticing") is NARROWED by §12.4.3 (a
  harness-crash signature is `mutation_invalid:<id>`, not
  noticing). The §6 erratum's observed-failure rule otherwise
  stands.
- §6, step 5's mutation validation: EXTENDED by §12.4.1
  (scope rule, presence rule restated, harness-closure rule).
- §7, "Same-user process limits" paragraph: the sentence
  "Scratch copies narrow the run window; nothing here
  eliminates it, and no lock is held" is SUPERSEDED for the
  ship composition by §12.2 (the snapshot eliminates the
  verify-to-ship window for the shipped tree by construction;
  no lock is held, and none is needed). It remains accurate
  for standalone `verify_proof_artefact`.
- §7, "Determinism is a requirement" paragraph: its
  environment caveat ("the execution environment … is *not*
  bound in the artefact") is PROMOTED into the CLAIM itself
  (§12.6); the paragraph stands as explanation.
- §7, "Scope-bounded binding" paragraph: the statement that a
  change outside scope "is invisible" to the composition is
  SUPERSEDED for the wrapper by §12.1.1 (out-of-scope
  differences refuse the ship); it remains true of standalone
  verification. Follow-up 1 in that paragraph (carry
  `manifest_hash` in the artefact) is NOT landed by this
  addendum and remains open; §12.1.2 binds `manifest_hash`
  and `artefact_hash` together at ship time in the binding
  record instead, which narrows but does not close it.
- §9 test plan: EXTENDED by the test lists in §§12.1.3,
  12.2.3, 12.3.2, 12.4.4, 12.5.1, and the new guard file of
  §12.7. Where §9 and this addendum describe the same case,
  this addendum's version governs.
- §10, follow-up 5 ("Anchor the `artefact_hash` in the ship
  record"): PARTIALLY LANDED by §12.1.2 — the artefact hash
  is bound into the ship's durable evidence
  (`proof-bindings.jsonl` in the ledger's directory, keyed by
  cycle and manifest) — but NOT into the ship-tx journal or
  the manifest; follow-up 5 remains open for journal
  anchoring and for hash-chaining the bindings file.
- §10: NEW follow-up 7 recorded — the anchored composition
  `anchored_record_ship_with_proof` specified in §12.7.
  Follow-ups 1, 2, 3, 4, and 6 are unchanged.

Nothing else in §§1–11 is altered. In particular §3's schema,
§4's tree-hash format (`proof-tree/1`), §8's non-claims, and
§11's mechanism field stand exactly as written; §12.5's
document-not-bind mode decision is a clarification of §4, not
a format change.
