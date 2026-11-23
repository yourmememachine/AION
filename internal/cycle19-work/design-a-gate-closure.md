# Cycle 19 — Design A (gate scope extension + dependency closure)

Seat: coder A. Angle: the `eval/gate.py` protected-list extension and the
dependency-closure analysis behind it. DESIGN ONLY — no production code
in this note's round. Authorised production change when built (per task
brief, restated so B/C build to the same boundary): **the only `eval/`
change is the protected-list extension in `eval/gate.py` plus its header
comment. Nothing else in `eval/`.** Baseline: 1245 tests OK (skipped=26).

Sources read for this note: `internal/DECISION-PROTECTED-GATE-EXTENSION.md`,
`internal/REVIEW-CYCLE-13.md` (rev-r6 F1/F2), `internal/CROSS-CHECK-7.md`
(seat-gpt + seat-gemini, Item A), `internal/PROTECTED-GATE-PROPOSAL.md`
(incl. the Round-C import-cycle correction), `eval/gate.py`,
`trust/pathpolicy.py`, `oversight/approval.py`, `trust/__init__.py`,
`oversight/__init__.py`, `selfmod/canary.py`, and a repo-wide grep for
every pin of the old list (§4).

---

## 1. The exact new protected list for `eval/gate.py`

Current (gate.py lines 55–56):

```python
PROTECTED_PREFIXES = ("eval/",)
PROTECTED_FILES = ("core/loop.py",)
```

Proposed — prefixes **unchanged**, four exact files added:

```python
PROTECTED_PREFIXES = ("eval/",)
PROTECTED_FILES = (
    "core/loop.py",
    "oversight/__init__.py",
    "oversight/approval.py",
    "trust/__init__.py",
    "trust/pathpolicy.py",
)
```

(Order above is alphabetical for review diffing; the existing code does
`path in PROTECTED_FILES`, so order is semantically irrelevant. If B/C
prefer append-order for a smaller diff, that is cosmetic — flag it in
reconciliation, do not let it split the room.)

No new prefix. In particular **not** `trust/` and **not** `oversight/`
as gate prefixes — see the per-candidate arguments and §2.3.

### 1.1 Per-candidate verdicts

| Candidate | Verdict | Argument |
|---|---|---|
| `trust/pathpolicy.py` | **IN** (exact file) | The module the gate lazily imports in `check_protected_paths` (`from trust.pathpolicy import canonicalise`). It *defines* the function object whose output the verdict is computed from. This is rev-r6 F1's primary named file and both external seats' starting closure. No argument against exists. |
| `oversight/approval.py` | **IN** (exact file) | Owns `canonicalise_path`, the single source of spelling rules; `trust.pathpolicy.canonicalise` delegates to it and adds nothing. A poisoned `canonicalise_path` is exactly the F1 two-step (edit canonicaliser → passes every list today; later `eval/` change judged by it). Note it is already in *oversight's own* workflow list (`oversight/` prefix + delegation in `is_protected_path`) — that does not help: the F1 attack is a *gate*-judged self-change, and the gate's list is the one that must refuse it at step 1. Gate protection and oversight protection are separate verdicts; this file now legitimately sits in both (first overlap — consequences in §4.3). |
| `trust/__init__.py` | **IN** (exact file) | Executed on every gate verdict call: the lazy `from trust.pathpolicy import …` first executes the `trust` package `__init__`, which imports 12 submodules and re-exports `canonicalise`'s neighbours. It decides *which* `trust.pathpolicy` the import system binds (its import order runs `.attestation`, `.client`, `.errors`, `.ledger`, `.manifest` — and `.manifest` itself imports `trust.pathpolicy` — before the explicit `.pathpolicy` re-export line). An edit to `trust/__init__.py` alone (reorder, add a pre-seeding import, rebind) is a canonicaliser-poisoning edit in every way that matters. rev-r6 named it in the minimum closure ("at minimum `trust/pathpolicy.py`, `trust/__init__.py`, `oversight/approval.py`"). Cheap: one exact file, no prefix blast radius. |
| `oversight/__init__.py` | **IN** (exact file) | Executed on the verdict path: `trust/pathpolicy.py`'s module-level `from oversight.approval import canonicalise_path` first executes `oversight/__init__.py`, which does `from .approval import (… canonicalise_path …)` and builds `__all__`. A poisoned `oversight/__init__.py` can bind a substitute `canonicalise_path` into the `oversight.approval` namespace / pre-register `sys.modules` entries before `.approval` is even loaded. It is the exact analogue of `trust/__init__.py` one hop deeper, and the external seats asked for the canonicaliser's imports analysed "one layer deeper" — this file *is* that layer. Cost is one exact file; it is also already ceremony-authorisable today via oversight's first-component rule, so adding it to the gate list creates no new workflow friction. Leaving it out while including `trust/__init__.py` would be an indefensible asymmetry in review. |
| `oversight/` as a gate **prefix** | **OUT** | Would merge the lists the proposal deliberately kept separate (proposal, "What remains divergent": oversight's list is a superset *by design*, reported as a separate tag). Only `approval.py` + `__init__.py` are on the gate's verdict path; the rest of `oversight/` (nothing else exists today, but the prefix would capture future modules) is not gate-trusted code. Exact files only. |
| `trust/` as a gate **prefix** | **OUT** (this cycle) | See §2.3 — this is the honest-residual decision, and the one place I expect friction with a maximalist B/C design. Short form: it does not close the closure either (the transitive execution set spills into `signing/`, `memory/`, `eval/`), it would put the entire verifier/ship stack behind the dual-leg ceremony, and it exceeds the external seats' stated *starting* closure. The residual it would partially address is named, bounded and backlogged in §2.4 instead of silently absorbed. |
| `core/__init__.py`, `eval/__init__.py` | **No action** | `eval/__init__.py` is already covered by the `eval/` prefix and merely re-exports `PROTECTED_FILES`/`PROTECTED_PREFIXES` from `eval.gate` — it follows the constant automatically, no edit needed. The gate never imports `core/loop.py`; `core/__init__.py` is not on the verdict path. |
| `signing/gate_decision.py` etc. | **OUT** | Executed transitively via L3 (§2.2) but defines nothing the verdict uses; it *consumes* `GateDecision`. Protecting consumers because they are loaded would protect most of the repo. Named as residual, §2.4. |

### 1.2 Header comment (the other authorised `eval/` change)

`eval/gate.py`'s module docstring and the comment above the constants
(lines 52–54) must change in the same commit:

- The protected-scope bullet ("the change does not touch protected
  scope: the evaluation package and the cycle state machine…") gains:
  the gate also protects the code its protected-path verdict itself
  trusts — the path policy and the canonicaliser chain — naming the
  four added files and citing cycle 19 / this extension decision.
- The comment above `PROTECTED_PREFIXES`/`PROTECTED_FILES` must stop
  implying the list is only "the judges" (`eval/` + `core/loop.py`):
  the added files are not judges, they are the judge's *trusted
  inputs*, and the comment should say so, plus state the known
  residual (§2.4) in one sentence so the header does not overclaim
  closure. Per CROSS-CHECK-7 wording discipline: do not write
  "dependency closure" unqualified in the header; write "the files
  that define the canonicalisation the verdict uses, plus the two
  package `__init__` files executed to reach them".

No other line in `eval/gate.py` changes. `check_protected_paths` logic,
the lazy import, and offender reporting (canonical spelling) are
untouched.

---

## 2. Dependency-closure analysis

What does one call to `check_protected_paths` actually trust? Traced
from the code, and verified empirically in a fresh interpreter: a
single `check_protected_paths(['core/loop.py'])` call after
`import eval.gate` leaves the `trust`, `oversight`, `signing`,
`memory` and `eval` package trees loaded (repo-module count is the
rev-r6 F2 observation: "one gate call now loads the whole
trust/signing stack (21 modules)").

### L0 — verdict logic
`eval/gate.py` itself: `check_protected_paths`, the two constants, the
`path in PROTECTED_FILES or startswith(PROTECTED_PREFIXES)` test.
Already protected (`eval/` prefix). ✔ closed before this cycle.

### L1 — verdict inputs: the canonicaliser chain (the F1 hole)
- `trust/pathpolicy.py::canonicalise` — delegates, adds nothing.
- `oversight/approval.py::canonicalise_path` — the actual algorithm
  (strip, backslash translation, `""`/`"."` dropped, `".."` refused,
  absolute/drive refused, empty refused).

One layer deeper, as seat-gpt required: `oversight/approval.py`'s own
imports are **stdlib only** (`copy`, `fcntl`, `hashlib`, `json`,
`math`, `os`, `re`, `tempfile`, `unicodedata`, `dataclasses`,
`datetime`, `pathlib`) **plus `from eval.gate import
check_protected_paths`** — i.e. back into L0, already protected.
`trust/pathpolicy.py`'s own imports are `__future__` plus the one
`oversight.approval` import. **The L1 chain terminates in stdlib +
already-protected code.** That is what makes the §1 closure *exact*
rather than aspirational: after this extension, every repo file that
*defines* the verdict's canonicalisation is in the gate's list.
→ Both files IN (§1). ✔ closed by this extension.

### L2 — package `__init__` files executed on the import path
- `trust/__init__.py` — executed by `from trust.pathpolicy import …`.
- `oversight/__init__.py` — executed by pathpolicy's
  `from oversight.approval import …`.
- (`eval/__init__.py` — executed when the *caller* imports the gate,
  already under the `eval/` prefix.)

These do not define the algorithm, but they control binding: what the
names `trust.pathpolicy` and `oversight.approval` resolve to, and in
what order submodules load. → Both IN (§1). ✔ closed by this extension
at the file-edit level (a self-change editing either `__init__` is now
itself a `protected_path` refusal).

### L3 — modules executed transitively via `trust/__init__` re-exports
`trust/__init__.py` imports, in order: `.attestation`, `.client`,
`.errors`, `.ledger`, `.manifest`, `.release`, `.anchoring`,
`.budgets`, `.pathpolicy`, `.shipcheck`, `.shiptx`, `.wiring`. Those
pull in, transitively: the whole `signing/` package
(`signing/__init__`, `signing/gate_decision`, `signing/attestation`,
`signing/state_snapshot`, `signing/pin_ceremony` — via attestation /
ledger / shipcheck / wiring), `trust/protocol.py` (via client),
`memory/store.py` + `memory/reuse` + `memory/solver` (via wiring),
and `eval/registry` / `eval/calibration` / `eval/factory` (via
`eval/__init__` re-exports when `signing.gate_decision` imports
`eval.gate`).

**The `sys.modules` pre-seeding vector, stated precisely:** the gate's
lazy import binds whatever `sys.modules["trust.pathpolicy"]` holds at
call time. `trust/__init__` executes `.attestation` → `.client` → …
→ `.manifest` *before* its own `.pathpolicy` re-export line, and
`.manifest` imports `trust.pathpolicy` itself — so the real module
normally wins the race. But a self-change editing any earlier-executed
L3 submodule (say `trust/client.py`) to execute
`sys.modules["trust.pathpolicy"] = <fake>` (or to stash a fake
`canonicalise` attribute on the real module) would poison every later
gate verdict in that process, and **that edit is not in the §1 list**.
Same class, one layer deeper than F1. I will not pretend otherwise.

### 2.3 Why the chosen closure is the right scope anyway

1. **It closes the demonstrated attack exactly.** F1 as verified live
   by rev-r6 is: edit *the canonicaliser* (L1) → step 1 passes every
   list → step 2 `eval/` change judged by the poisoned canonicaliser.
   §1 makes step 1 itself a `protected_path` refusal through both the
   gate and (newly) the oversight ceremony (§4.5). The two negative
   tests in §5 pin exactly this.
2. **L3 pre-seeding needs a strictly stronger attacker position than
   F1.** The F1 edit is inert data until judged; an L3 pre-seed edit
   must (a) be smuggled as an ordinary change to a busy, heavily
   tested module, (b) survive that module's own test suites, and
   (c) only pays off in a process that later calls the gate — where
   in-process code of that reach could equally monkeypatch
   `eval.gate` directly, a capability the gate's own header already
   disclaims ("this gate checks CONSISTENCY… independence is a
   property of the process around this gate"). The gate's threat
   model is *proposed file changes judged as paths*, not arbitrary
   code execution in the judging process.
3. **Prefix escalation does not terminate.** `trust/` prefix → for
   consistency `signing/` (executed, defines the decision types the
   gate's output feeds) → `memory/` (executed via wiring) → the
   closure is "most of the repo", every routine change becomes a
   dual-leg ceremony, and the protected list stops meaning "the
   judge and what the judge trusts" and starts meaning "everything
   importable". That is a worse failure mode than a named residual.
4. **The structural fix exists and is the honest long-term answer**
   (§2.5) — it removes L3 from the execution path instead of
   protecting it. Protecting L1+L2 now + structural fix later is
   strictly better than prefix-protecting L3 now.

### 2.4 What this extension does NOT close (for the record / backlog)

- **R-A (L3 pre-seeding, above):** an accepted change to an
  earlier-executed `trust/__init__` submodule that pre-registers or
  mutates `sys.modules["trust.pathpolicy"]`. Mitigations available
  today: none in code. Backlog item to file with this cycle:
  `gate-import-isolation` (§2.5).
- **R-B (import failure surface):** if any L3 module fails to import,
  the gate's lazy import raises the *raw* error, not `GateInputError`
  (rev-r2 LOW from cycle 13, still open; fail-closed everywhere but
  untyped). This extension enlarges the protected list, not the load
  surface — the load surface is unchanged since cycle 13 — so R-B is
  neither worsened nor fixed here. Wrapping the import is an `eval/`
  logic change and is **outside this cycle's authorised eval/ scope**;
  flagging it so nobody "helpfully" lands it in this cycle.
- **R-C (verifier-side strictness unchanged):** the verifier's
  canonical-spelling + lowercase-first-component rules in
  `trust/verifier_main._mode_gate` remain a second, independent line;
  this extension neither relies on nor weakens them.
- **R-D (case sensitivity):** unchanged and by design (proposal
  remainder): `Trust/pathpolicy.py` is a different, unprotected path
  on this Linux target.

### 2.5 Structural mitigation assessment (honest feasibility)

Option: make the gate load the policy *without executing
`trust/__init__.py`* — e.g. `importlib.util.spec_from_file_location`
on `trust/pathpolicy.py` under a private module name, inside the
existing lazy import.

- **Mechanically feasible.** `pathpolicy.py`'s only repo import is
  the absolute `from oversight.approval import canonicalise_path`;
  loaded under a private name it would still resolve that import
  normally (executing `oversight/__init__` + `oversight/approval` —
  both protected under §1 — and *not* `trust/__init__` or any L3
  module). Round-C's analysis is respected: Round C showed option
  (a) (delegation flip) does **not** break the
  `gate → trust/__init__ → shipcheck → signing.gate_decision → gate`
  cycle and that "`__init__` avoidance" is required — direct file
  loading *is* the `__init__`-avoidance branch of that sentence, so
  this is consistent with, not contrary to, the proposal.
- **But NOT in this cycle, for three reasons:** (1) it is an
  `eval/gate.py` *logic* change, outside the authorised scope
  (list + header comment only); (2) it creates a second, divergent
  module instance of `trust.pathpolicy` (dual identity: 
  `sys.modules["trust.pathpolicy"] is not <gate's copy>`; anything
  comparing function identity or relying on module-level state —
  today there is none, the module is pure constants + functions —
  breaks silently); (3) it needs a repo-root path derivation in the
  gate (`Path(__file__).resolve().parent.parent`), introducing a
  filesystem assumption the currently I/O-free-except-import gate
  does not make, which deserves its own war room.
- **Recommendation:** file as backlog `gate-import-isolation`,
  sequenced *after* this extension ships; the extension is the
  prerequisite that makes the interim state defensible.

Alternative structural option, rejected: flipping the delegation so
`oversight` delegates to the policy (proposal option (a)) — Round C
already showed it does not break the `trust/__init__` cycle, and it
touches protected `oversight/` logic for no closure gain over §1.

---

## 3. (Reserved — merged into §4)

## 4. Everything that pins the old list and must change in step

Grep basis: repo-wide search for `PROTECTED_FILES`, `PROTECTED_PREFIXES`,
`GATE_PROTECTED`, `LOCAL_PROTECTED`, `core/loop.py` across `*.py`/`*.md`
(excluding `.git`). Historical records (`internal/BUILD-CYCLE-*`,
`internal/REVIEW-*`, the proposal/status banners) are **history — do
not rewrite them**; they describe the list as it was. Live pins:

### 4.1 `trust/pathpolicy.py` — mirror + docstring (REQUIRED, in step)
- `GATE_PROTECTED_FILES = frozenset({"core/loop.py"})` →
  `frozenset({"core/loop.py", "oversight/__init__.py",
  "oversight/approval.py", "trust/__init__.py", "trust/pathpolicy.py"})`.
  `GATE_PROTECTED_PREFIXES` unchanged (`("eval/",)`).
- Provenance comment block above the constants (lines ~92–102):
  update the quoted source snippet to the new `PROTECTED_FILES`.
- Module docstring: (a) the mirror paragraph stays true but the
  adoption-status bullet for `eval/gate.py` must gain the extension:
  the gate now also *protects* the policy + canonicaliser chain
  (cycle 19), not only consumes it; (b) **classification change**:
  `classify("trust/pathpolicy.py")` → `protected_by == ["gate"]`
  (was `[]`); `classify("oversight/approval.py")` →
  `["gate", "oversight"]` (was `["oversight"]`) — the docstring's
  "separate tags" framing must acknowledge the first overlap.
- Mirror discipline is unchanged and is the safety net: the mirror is
  *copied, not imported*, and §4.2's constant-equality test fails
  loudly if gate and mirror land out of step. Land gate + mirror in
  the **same commit**; a tree with only one of them is a red suite by
  design.

### 4.2 `tests/test_trust_pathpolicy.py` (REQUIRED)
- `MirrorConstantTests.test_gate_mirror_matches_live_gate` — no code
  change (compares live constants); it is the drift detector that
  forces §4.1 to land in step.
- `CORPUS` rows to add/change:
  - `("trust/pathpolicy.py", …, ["gate"], "same")` — currently
    `("trust/manifest.py", …, [])` is the trust representative; add
    rows for `trust/pathpolicy.py` → `["gate"]`,
    `trust/__init__.py` → `["gate"]`,
    `oversight/__init__.py` → `["gate", "oversight"]` (canonicalises
    under oversight's prefix too), and change
    `("oversight/approval.py", …, ["oversight"])` → `["gate", "oversight"]`.
  - Non-canonical variants worth adding: `trust//pathpolicy.py`,
    `trust/./pathpolicy.py`, `./oversight/approval.py` → canonical +
    gate tag, manifest `"refuses"`.
- ⚠️ **Overlap break — `CorpusAgreementTests.
  test_agrees_with_oversight_canonicalised_check`**: its isolation
  derivation asserts `oversight_verdict and not gate_verdict ==
  ("oversight" in protected_by)`, with the comment "they never
  overlap: disjoint prefixes/files". That invariant **dies** with
  this extension: for `oversight/approval.py` and
  `oversight/__init__.py`, oversight verdict True, gate verdict True,
  `"oversight" in protected_by` True → assertion fails. The test must
  be re-derived, not just re-tabled: the correct post-extension
  identity is `oversight_verdict == ("oversight" in protected_by or
  "gate" in protected_by)` (already asserted two lines above) and the
  *isolated-oversight* check needs a different isolation — e.g.
  compare against the policy's own `_oversight_protected(canonical)`
  helper. Flagging as the single non-mechanical test change in my
  section; B/C should expect it and not "fix" it by weakening the
  corpus. (Seat friction: if C's design instead keeps `classify`
  reporting only `["oversight"]` for dual-protected files, I dissent
  — `classify` must report the gate tag truthfully or N1's
  policy-side assertions lie.)

### 4.3 `tests/test_trust_pathpolicy_differential.py` (REQUIRED)
The 66-row `EXPECTED` table + class machinery:
- Canonical rows: `("oversight/approval.py", CANONICAL, …, ["oversight"],
  False)` → `["gate", "oversight"]`, gate verdict **True**.
  `("oversight", …, ["oversight"], False)` unchanged (bare `oversight`
  is not in the gate's list — only the exact file is).
- `POLICY_CATCHES_OVERSIGHT` class: 6 rows. Three canonicalise to
  `oversight` (`oversight/`, `oversight/.`, `oversight//`) — class
  and verdict **unchanged**. Three canonicalise to
  `oversight/approval.py` (`oversight//approval.py`,
  `oversight/approval.py/`, `oversight/approval.py/.`) — the gate now
  catches them: reclassify to `GATE_CATCHES_ANYWAY`, `protected_by`
  `["gate", "oversight"]`, gate verdict True. The class comment
  ("the gate never protects oversight scope at all (its list is
  eval/ + core/loop.py only)") must be rewritten: the gate now
  protects exactly one oversight file, by exact name.
- Add canonical + non-canonical rows for the trust files mirroring
  the `core/loop.py` family: `trust/pathpolicy.py` (CANONICAL,
  `["gate"]`, True), `trust//pathpolicy.py` and
  `trust/./pathpolicy.py` (GATE_CATCHES_ANYWAY, `["gate"]`, True),
  `trust/__init__.py` (CANONICAL, `["gate"]`, True). This grows the
  corpus past 66 — every count pinned in the harness header and in
  `internal/PROTECTED-GATE-PROPOSAL.md`'s table is a *historical*
  record of the pre-extension corpus; update the harness's own
  header counts, leave the proposal alone.
- `DivergenceTableTests` pinned class counts change accordingly
  (POLICY_CATCHES_OVERSIGHT 6 → 3, GATE_CATCHES_ANYWAY +3 plus new
  rows). GATE_MISS and GATE_STRICTER stay pinned **empty** — that
  pin is load-bearing for §5.

### 4.4 `tests/test_gate.py` (REQUIRED, additive)
- `TestProtectedPaths`: add cases asserting each new exact file is a
  violation via `evaluate_self_change` (canonical spelling):
  `trust/pathpolicy.py`, `trust/__init__.py`, `oversight/approval.py`,
  `oversight/__init__.py`; and a **negative control** that the
  extension is exact-file, not prefix: `trust/manifest.py`,
  `trust/client.py`, `oversight/other.py`-style sibling paths remain
  *accepted* (use real existing siblings: `trust/manifest.py` and a
  non-existent-but-plausible `oversight/journal.py` — the gate judges
  strings, existence is irrelevant). This control is what stops a
  future prefix-creep regression from passing silently.
- Existing tests unchanged: `test_dot_slash_and_backslash_paths_are_normalised`
  etc. pin canonicalisation behaviour, which this cycle does not touch.

### 4.5 `oversight/approval.py` — NO constant change, one behaviour consequence (NOTE, verify by test)
`LOCAL_PROTECTED_PREFIXES`/`LOCAL_PROTECTED_FILES` do **not** change.
But `is_protected_path` delegates to `check_protected_paths`, so after
the extension it returns True for `trust/pathpolicy.py` and
`trust/__init__.py` (previously False — rev-r6 verified
`is_protected_path("trust/pathpolicy.py") == False` live). Consequence,
and it is the desired one: `ApprovalManager.create_request` will now
*accept* protected-change requests naming those files (it refuses any
path where `is_protected_path` is False) — i.e. the canonicaliser
chain becomes ceremony-authorisable instead of unchangeable-through-
the-workflow. `tests/test_oversight_approval.py` has no assertion
pinning the old False (grepped) — add one asserting the new True for
both trust files so the consequence is pinned, not accidental.
`oversight/__init__.py` (the package file) is untouched; it re-exports
oversight's own constants only.

### 4.6 `selfmod/canary.py` — docstring only (REQUIRED wording, NO list change)
Checked as tasked: the canary does **not** mirror the gate's list.
`_check_protected` (line ~249) *delegates* Tier A to the imported
`check_protected_paths`, so the extension flows through automatically
at runtime. Its own constants are local policy only:
`LOCAL_PROTECTED_PREFIXES = ("selfmod/", ".git/", "state/")`,
`LOCAL_PROTECTED_FILES = ()`, `PROTECTED_FIRST_COMPONENTS =
("eval", "selfmod", ".git", "state")` — **none of these change**
(Tier B is canary-local; adding `"trust"`/`"oversight"` first
components would refuse *all* trust/oversight paths through the
canary, far beyond the gate's exact files — explicitly not wanted).
The one stale artefact is the docstring (line ~71): "Tier A (the
gate's, authoritative): check_protected_paths refuses any path under
eval/ and core/loop.py exactly" — rewrite to name the extended Tier A
(eval/ prefix + the five exact files). Wording-only edit to a
non-protected file; land it in the same commit so no artefact in the
tree states the old list as current.

### 4.7 Docs (REQUIRED wording)
- `docs/PROVENANCE.md` lines ~403–404 quote the gate's list verbatim
  (`PROTECTED_PREFIXES = ("eval/",)` / `PROTECTED_FILES =
  ("core/loop.py",)`) as the definition of protected scope — update
  the quote and surrounding sentence to the extended list.
- `trust/README.md` / `docs/PARSER-INVENTORY.md`: grepped — no pin of
  the gate's list values (PARSER-INVENTORY #31 describes pathpolicy
  without listing the files) — no change.
- `internal/BUILD-CYCLE-19.md` (the cycle record, written at build
  time) carries the extension + residual R-A wording; historical
  BUILD/REVIEW files are not edited (§4 preamble).

### 4.8 No-change confirmations (grepped, so B/C don't re-hunt)
- `eval/__init__.py` — re-exports the constants from `eval.gate`;
  follows automatically.
- `signing/gate_decision.py` — consumes `protected_violations`
  opaquely (serialises the tuple); new violation strings
  (`trust/pathpolicy.py` etc.) flow through its existing `_str_list`
  validation. No pin, no change. (Worth one existing-suite run to
  confirm no length/charset assumption — the new strings are ordinary
  repo-relative paths like existing ones.)
- `trust/verifier_main.py` — no hardcoded protected list (grepped);
  `_mode_gate` feeds the gate and inherits the extension.
- `trust/manifest.py` buckets — the build manifest classifies files
  by bucket, not by the gate list; no pin found.

---

## 5. The two required negative tests (external seats, CROSS-CHECK-7)

Home: `tests/test_protected_gate_adoption.py` (the cycle-13
negative-integration suite — it already has the otherwise-acceptable
`_evaluate` fixture and the subprocess import-order guards), new class
`GateClosureNegativeTests`. Both tests must be **mutation-checked**
during build: each must FAIL on the pre-extension tree (that is the
proof it tests the extension) and PASS after. Record the mutation
result in BUILD-CYCLE-19.

### N1 — a change editing only the canonicaliser is refused by the gate itself
For each path in the canonicaliser set, via the real entry points:
- `check_protected_paths([path]) == (path,)` for
  `path ∈ {"trust/pathpolicy.py", "oversight/approval.py",
  "trust/__init__.py", "oversight/__init__.py"}`.
- **Non-canonical spelling variant (required):**
  `check_protected_paths(["trust//pathpolicy.py"]) ==
  ("trust/pathpolicy.py",)` and
  `check_protected_paths(["oversight/./approval.py"]) ==
  ("oversight/approval.py",)` — offenders reported in canonical
  spelling, proving the refusal is judged *through* the very
  canonicaliser being protected, on spellings that pre-adoption
  would have needed the verifier's strictness to catch.
- End-to-end leg: `_evaluate(["trust/pathpolicy.py"])` (the suite's
  otherwise-ACCEPTABLE fixture: valid scores + sealed gain + valid
  attestation) returns `accepted == False`, `"protected_path" in
  reasons`, `protected_violations == ("trust/pathpolicy.py",)`;
  same shape for `oversight/approval.py`. The control
  `_evaluate(["src/feature.py"])` already in the suite proves the
  path is the sole cause.
- Policy-side cross-assertion: `pathpolicy.classify(
  "trust/pathpolicy.py")["protected_by"] == ["gate"]` and
  `classify("oversight/approval.py")["protected_by"] ==
  ["gate", "oversight"]`, tying N1 to the §4.1 mirror.

### N2 — a canonicaliser modification cannot authorise a later bypass
The two-step F1 attack, in its testable form. The gate is a pure
function over path *strings* — it never reads the candidate bytes of
the canonicaliser — so "modification" is modelled exactly as the
threat model poses it: as a *proposed change naming the file*.

- **Step 1 (the poison attempt is itself refused):**
  `_evaluate(["trust/pathpolicy.py"])` and
  `_evaluate(["oversight/approval.py"])` are refused with
  `protected_path` (as N1). Because step 1 can never be accepted,
  there is no accepted tree state in which the canonicaliser differs
  — the chain of authorisation is broken at the first link. State
  this reasoning in the test docstring; do not fake a stronger claim.
- **Step 2 (a former gate-miss spelling still refused by the
  unmodified canonicaliser):** in the same test, after the step-1
  refusals, assert the spellings that *would* have been the bypass
  payload are still refused by the canonicaliser as-shipped:
  `check_protected_paths(["core//loop.py"]) == ("core/loop.py",)`,
  `check_protected_paths(["eval//gate.py"]) == ("eval/gate.py",)`,
  and the new-family equivalents
  `check_protected_paths(["trust//pathpolicy.py"]) ==
  ("trust/pathpolicy.py",)`. Plus the end-to-end form:
  `_evaluate(["core//loop.py"])` refused, `protected_path` in
  reasons. 
- **What N2 deliberately does not claim:** it does not simulate a
  poisoned canonicaliser *function* (monkeypatching
  `trust.pathpolicy.canonicalise` in-process and asserting the gate
  still refuses) — that assertion would fail, by design of the
  current architecture, and writing it as a passing test would be
  theatre. The honest pin is: the *only* route to a poisoned
  canonicaliser is an accepted change to a now-protected file, and
  step 1 proves that route is refused. The in-process-monkeypatch
  residual is R-A/§2.4 territory (process trust, already disclaimed
  in the gate header). If B/C propose an in-process variant, my
  position: include it only as an `expectedFailure`-style documented
  residual test or not at all — never as a green assertion.

---

## 6. Shared interface questions — answers from the gate side

**(i) Operator-authority list verifier-side via env config
`AION_CEREMONY_OPERATORS` on the out-of-process verifier — any
gate-side objection?**
**No objection; it is the right side of the boundary.** From the
gate's perspective: `eval/gate.py` is pure, I/O-free (the one lazy
import aside) and must stay env-free — an operator list read from
`os.environ` inside the gate would (a) break the gate's stated
input discipline (everything it judges arrives as explicit
arguments), and (b) be readable/forgeable by the same in-process
caller the decision record exists to distrust. The verifier process
already owns exactly this pattern: `trust/verifier_main.py` takes
its whole authority configuration from `AION_*` env vars
(`AION_VERIFIER_SIGNER_ID`, `AION_ANCHOR_PATH`, budgets, deployment
mode with production-mode refusals), parsed once at startup with
fail-closed config errors. `AION_CEREMONY_OPERATORS` slots into that
precedent cleanly. Two gate-side conditions, both cheap: (1) the
verifier must refuse (config error, unsigned, non-zero exit) when
the variable is absent/empty **in production mode**, mirroring the
`AION_ANCHOR_PATH` production rule — an empty list must never
silently mean "no ceremony possible" *or* "anyone"; (2) whatever
ceremony decision gets signed should carry the operator id that was
authorised (it already does — `pin_ceremony` records `operator_id`),
so the gate-side record stays auditable without the gate ever
seeing the list. Interface friction to flag for B: the *ceremony*
code (`signing/pin_ceremony.py`) currently takes
`authorised_operators` as a caller-supplied parameter (line ~392) —
the env list must be injected at the verifier boundary and the
parameter must stop being reachable from the request payload; that
is B's seam, but the gate side depends on it being done there and
not half-done in both places.

**(ii) Does the gate itself need any new function for ceremony
authority?**
**No.** Nothing in `eval/` beyond the §1 list + header. Reasoning:
ceremony authority is a *provenance* question (who may advance a
pin, what evidence binds to it); the gate's job is *consistency* of
a presented decision. The decision record already states this split
("The gate will hold its own protected operator-authority list and
verify evidence provenance itself, from a protected source") — read
carefully, "the gate" there names the extended *gate system*
(verifier + ceremony + protected list), not the `eval.gate` module;
the concrete mechanism the decision's own consequences name is that
the ceremony's authority/provenance be "sourced from the extended
gate's protected store", i.e. the list lives in verifier-side config
and the ceremony code that consumes it becomes trustworthy *because
the files are now protected*, not because `eval.gate` grows an API.
Adding a ceremony function to `eval/gate.py` would also breach this
cycle's authorised-eval-scope constraint. Verifier-side +
ceremony-side verification is sufficient, provided (i)'s two
conditions hold. Flagged disagreement risk: if C's design reads the
decision as requiring a literal operator-list constant *inside*
`eval/gate.py`, I dissent — a constant in a protected file is
*changeable only by ceremony* but *readable and presentable by any
caller*, and the gate still could not verify the presenter actually
consulted it; the env-on-verifier placement is the one that binds
authority to the out-of-process boundary, which is the whole point
of CROSS-CHECK-9/10's fix.

**(iii) Item A integrity — confirmation from my reading.**
Read and confirmed intact in the current tree:
- **Gate canonicalisation**: `eval/gate.py::check_protected_paths`
  judges the canonical spelling via the function-local
  `from trust.pathpolicy import canonicalise`, returns offenders in
  canonical spelling, raises `GateInputError` for non-string/blank/
  uncanonicalisable input. Untouched by this design except the two
  constants + header (§1) — the extension *depends* on this code:
  N1's non-canonical variants only refuse because canonicalisation
  runs before the list test.
- **P-1**: `eval/registry.py` — `_no_duplicate_keys` (line ~101)
  raising on duplicate keys, wired as `object_pairs_hook` in both
  `_load` (line ~315) and the `_disk_changed` re-read (line ~347).
- **P-2**: `eval/calibration.py` — `_no_duplicate_keys` (line ~74),
  wired into `CalibrationLog._load` (line ~336).
- **Negative-integration test**: `tests/test_protected_gate_adoption.py`
  — `GateAdoptionIntegrationTests` (canonical + non-canonical refusal,
  unprotected control accepted, uncanonicalisable raises with no
  decision), `DuplicateKeyArtefactTests` (loader refusals + real
  verifier subprocess refusing the duplicate-key registry unsigned,
  asserting the exact `registry_untrusted` string and an empty
  signing ledger), `ImportCycleGuardTests` (fresh-interpreter, both
  import orders). §5's N1/N2 extend this file; nothing in it needs
  modification for the extension — its existing assertions use
  `core/loop.py`/`eval/*` paths whose status is unchanged.
- **Interactions with my extension**: (1) Item A's import-cycle
  guards become *more* load-bearing, not less — the lazy import now
  also drags the newly protected `__init__` files, but no import
  *structure* changes, so both orderings must pass unmodified;
  (2) the differential harness (§4.3) is Item A's closure record and
  is the artefact that changes most — its GATE_MISS-pinned-empty
  assertion is the regression tripwire the extension must preserve;
  (3) nothing in P-1/P-2 interacts: different files, and both are
  inside the already-protected `eval/` prefix.

---

## 7. Build sequencing (for the build round)

1. `eval/gate.py` constants + header (§1) and `trust/pathpolicy.py`
   mirror + docstring (§4.1) in the **same commit** — the mirror
   constant test makes any inter-commit tree red by design.
2. Test updates: §4.2 corpus + overlap re-derivation, §4.3 EXPECTED,
   §4.4 gate cases, §4.5 oversight pin, §5 N1/N2 (with pre-extension
   mutation check recorded — run N1/N2 against the constants reverted
   in a scratch copy, not in the tree).
3. Wording: canary docstring (§4.6), `docs/PROVENANCE.md` (§4.7).
4. Full suite: expect 1245 + net new (N1/N2 + corpus rows + gate
   cases ≈ +20–30 depending on subTest counting — report the exact
   number from the run, never estimate it in the record).
5. Backlog filings with this cycle: `gate-import-isolation` (§2.5),
   and the R-B import-error typing (already a recorded follow-up
   from cycle 13 — confirm it is on the backlog, do not duplicate).

## 8. Friction summary for reconciliation

- vs a maximalist design: I hold at exact files, no `trust/` prefix;
  residual R-A is named + backlogged, not prefix-absorbed (§2.3).
- vs a minimalist design (only the two L1 files): `trust/__init__.py`
  and `oversight/__init__.py` are IN — they are executed binding
  control on the verdict path, rev-r6 named the trust one in the
  minimum, and asymmetric inclusion is unreviewable (§1.1).
- `classify()` must report the gate/oversight overlap truthfully
  (§4.2); the differential + pathpolicy corpora change shape, and
  one oversight-isolation test is re-derived, not re-tabled.
- Ceremony authority: verifier-env (`AION_CEREMONY_OPERATORS`),
  zero new gate API (§6). If B/C land the list anywhere in-process,
  that re-opens the CROSS-CHECK-9 circularity this cycle exists to
  close.
