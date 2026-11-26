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
