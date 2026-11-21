STATUS: APPROVED by Dilip, 2026-11-20. Implemented in the combined cycle-13 run in the Round-C form (function-local import in eval.gate.check_protected_paths; the option-(a) delegation flip was NOT taken), plus P-1/P-2 duplicate-key rejection and the gate negative-integration test. One war-room finding is NOT closed by this implementation and is escalated to Dilip: the gate now trusts trust/pathpolicy.py and oversight/approval.py, which are outside the gate's own protected list (eval/ + core/loop.py); closing it needs a further owner-approved protected change (backlog: protected-list-reconciliation). See internal/REVIEW-CYCLE-13.md. Item A's ship is withheld pending that decision.

# Protected Gate Rule proposal — gate adoption of path-policy/1

Item: CROSS-CHECK-4 item 4 (Trust Boundary v3). Both external
seats voted FIX on v2; seat-gpt F4 and Gemini (Medium) converge:
the gate's protected-path logic has NOT adopted path-policy/1,
the divergence was unbounded, and v2 wording called the policy
canonical/universal. This proposal is the escalation the
mandate allows: the divergence is now demonstrated and bounded
by a differential harness, and the gate change itself is
presented here for Dilip's decision under the Protected Gate
Rule — `eval/gate.py` is a protected path, so NOTHING in this
document has been applied. Coders: POD D (seat-10 harness,
seat-11 caller audit + wording, seat-12 proposal). Evidence:
`tests/test_trust_pathpolicy_differential.py` (66-spelling
corpus, three verdicts per spelling), on top of the cycle-9
drift corpus in `tests/test_trust_pathpolicy.py`.

## What is demonstrated today (no gate change)

**Equivalence domain — canonical spellings.** For every
spelling that IS its own canonical form (20 corpus rows,
including case variants and the zero-width-space / BOM /
Cyrillic-homoglyph spellings, which are canonical spellings of
*different* paths), the gate's verdict equals the policy's
"gate" tag, and oversight's verdict equals the policy's
combined verdict. On canonical input the three implementations
already agree exactly.

**The verifier defence.** The only production path that signs
gate decisions, `trust/verifier_main._mode_gate`, canonicalises
every `changed_paths` entry via the policy and refuses any
entry whose canonical spelling differs from the spelling
presented (plus any entry whose first component is not
lowercase) as a malformed request — unsigned, exit 2. The
harness drives the real verifier subprocess for all 34
non-canonical spellings of protected paths in the corpus: every
one is refused. No non-canonical spelling of a protected path
can reach the gate through the verifier today.

## The divergence table this proposal would close

Non-canonical spellings, by class (66-row corpus; counts pinned
by the harness — any change fails it loudly):

| Class | Count | Meaning |
|---|---|---|
| gate-miss | 10 | Policy gate-protected; the gate's raw verdict passes the path |
| gate-catches-anyway | 10 | Non-canonical, but the gate's prefix/strip rules still flag it |
| policy-catches-oversight | 6 | Oversight scope; the gate's list does not carry it at all |
| both-refuse | 11 | Uncanonicalisable; policy + oversight refuse outright |
| gate-stricter | 1 | Gate flags a spelling whose canonical form is unprotected |
| agree-unprotected-noncanonical | 8 | Unprotected under every verdict; spelling only |
| canonical (equivalence domain) | 20 | All three verdicts agree with the policy |

The full list within the corpus — gate-miss is the only class
in the corpus where a protected file passes the gate's own
check on the spelling presented. The gate-miss class is an
open family, not these ten spellings alone: any separator/
dot-component perturbation of the exact-file entry
`core/loop.py` (repeated slashes, backslash separators, dot
components in any position, trailing slash/dot) derives
gate-miss. The bound that actually protects production is the
verifier's canonical-only rule, not corpus enumeration:

- `core//loop.py`
- `core/./loop.py`
- `core/loop.py/`
- `core/loop.py/.`
- `core///loop.py`
- `core\\loop.py`
- `core\./loop.py`
- `core/././loop.py`
- `core//.//loop.py`
- `core/loop.py//.`

All ten in the corpus are spellings of `core/loop.py`, the
gate's one exact-file entry. The prefix entry (`eval/`) survives every
spelling trick in the corpus; the exact-file match is the
brittle part, exactly as cycle 9 recorded. The gate-stricter
row is `eval/`: the gate flags it (the normalised spelling
starts with `eval/`), while its canonical form `eval` is
unprotected — a false positive the proposal also closes.

## Caller audit (production code, this cycle)

Every production caller of `eval.gate.evaluate_self_change` /
`check_protected_paths`, grepped repo-wide:

| Caller | What it feeds the gate | Verdict |
|---|---|---|
| `trust/verifier_main.py` `_mode_gate` → `evaluate_self_change` | Canonicalise-or-refuse per entry via path-policy/1, plus lowercase-first-component rule | Safe — the defence above |
| `oversight/approval.py` `is_protected_path` → `check_protected_paths([canonical])` | Contractually canonical input; its internal producers pass `canonicalise_path` output (`_manifest`) | Safe by contract |
| `selfmod/canary.py` `_check_protected` (call sites lines 682, 832) | Paths already run through its own `canonicalise_path` (same algorithm as oversight's) | Safe — canonicalised first |
| `memory/store.py` `decide_write` → `evaluate_self_change` | `changed_paths=[f"memory/entries/{proposal_id}"]`, constructed in-code from a regex-validated id; never caller-supplied, never a protected prefix | Safe by construction |

No production caller passes raw, uncanonicalised caller input
to the gate. No caller in `trust/` or `signing/` needed a fix
this cycle (`signing/` has no gate callers at all), so the
divergence is NOT eliminable from the caller side: the ten
gate-miss spellings in the corpus are reachable only by
calling the gate directly with raw spellings, which is
precisely what gate adoption would close. Test-only callers
(`tests/test_gate.py`, `tests/test_selfmod_canary.py`) pass literal spellings by
design and are not production surface.

## The proposed change (for Dilip's approval — NOT applied)

Make `check_protected_paths` judge the canonical spelling:
canonicalise each presented path via the shared policy
(`trust/pathpolicy.py`, path-policy/1), and treat any spelling
that cannot be canonicalised as a violation in its own right
(raise `GateInputError`, the gate's existing malformed-input
channel — a refusal, never a silent pass). Precise diff sketch
against `eval/gate.py` as of this cycle:

```diff
 from __future__ import annotations
 
 import math
 import re
 from dataclasses import dataclass
 from datetime import datetime
+
+from trust.pathpolicy import canonicalise as _policy_canonicalise
 
 FLOAT_TOL = 1e-9
 ...
 def check_protected_paths(changed_paths) -> tuple:
     """The subset of changed paths that fall inside protected scope."""
     if isinstance(changed_paths, (str, bytes)) or not isinstance(
             changed_paths, (list, tuple)):
         raise GateInputError("changed_paths must be a list of paths")
     offenders = []
     for raw in changed_paths:
-        path = _normalise_path(raw)
+        # path-policy/1 adoption (Protected Gate Rule proposal,
+        # internal/PROTECTED-GATE-PROPOSAL.md): judge the
+        # canonical spelling, and refuse spellings that have
+        # none — an uncanonicalisable path is malformed input,
+        # never an unprotected one.
+        if not isinstance(raw, str) or not raw.strip():
+            raise GateInputError(
+                "changed path must be non-empty text")
+        try:
+            path = _policy_canonicalise(raw)
+        except ValueError as exc:
+            raise GateInputError(
+                f"changed path is not canonicalisable: {raw!r}"
+            ) from exc
         if path in PROTECTED_FILES or any(
                 path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
             offenders.append(path)
     return tuple(offenders)
```

Notes on the sketch:

- `_normalise_path` becomes unused by this function; whether
  to delete it is part of the same protected change.
- The import direction needs Dilip's eye: `eval/gate.py` would
  import from `trust/`, which imports from `oversight/`, which
  itself imports `check_protected_paths` from the gate — a
  cycle (`oversight → gate → trust.pathpolicy → oversight`).
  Python resolves it only if the import order cooperates, and
  it may not. Two clean alternatives if the direct import
  cycles: (a) move the spelling rules' home — have
  `trust/pathpolicy.py` stop delegating to
  `oversight.approval.canonicalise_path` and own the algorithm,
  with oversight delegating to the policy instead (touches
  `oversight/`, also protected — same dual-leg workflow); or
  (b) the gate keeps a local copy of the canonicalisation
  algorithm and the drift-detector tests are extended to pin
  gate/policy agreement behaviourally over this corpus (weaker:
  two implementations, watched by tests — the status quo's
  failure mode, one level down). POD D recommends (a) as the
  honest unification, sequenced as one protected change
  covering `eval/` + `oversight/` + `trust/pathpolicy.py`.
  Correction (Round C, rev-r4): option (a) does NOT by itself
  break the cycle. Importing `trust.pathpolicy` from the gate
  also executes `trust/__init__.py`, which imports
  `.shipcheck`, which imports `signing.gate_decision`, which
  imports `eval.gate` — a second cycle back into the gate
  itself (`gate → trust/__init__ → trust.shipcheck →
  signing.gate_decision → gate`), independent of the
  oversight delegation direction. Whichever option is chosen,
  a lazy/submodule import or `__init__` avoidance is also
  required (for example a function-local import in the gate,
  or restructuring so the gate reaches the policy module
  without executing the `trust` package `__init__`).
- Offenders would be appended as the CANONICAL spelling: the
  sketch's `offenders.append(path)` appends the canonicalised
  path, so the signed `protected_violations` content changes
  versus today's presented-normalised spelling (the gate's
  `_normalise_path` output — stripped, backslashes translated,
  leading `./` removed, but otherwise as presented; e.g.
  `eval//gate.py` is recorded as `eval//gate.py` today and
  would be recorded as `eval/gate.py` after adoption). Anyone
  comparing or consuming signed decisions across the change
  must expect the canonical form.
- The import breaks the gate's own header invariant:
  `eval/gate.py` line 3 states "Standard library only, pure
  functions, no I/O" — a module-level import of
  `trust.pathpolicy` makes the gate depend on a repo package
  (and, transitively through `trust/__init__.py`, on the
  signing/trust stack), so the header claim would have to be
  amended as part of the same protected change, not left
  standing over code it no longer describes.
- Behaviour after adoption: the ten gate-miss spellings in
  the corpus flag as violations; `eval/` stops flagging (canonical `eval` is
  unprotected); every both-refuse spelling raises
  `GateInputError` instead of returning a verdict — callers
  that catch gate errors already treat that as a refusal.
- The differential harness's recorded table would flip: the
  gate-miss and gate-stricter classes empty out, both-refuse
  rows become gate errors. Updating `EXPECTED` in the harness
  is part of the same change, and the harness failing until it
  is updated is the drift detector doing its job.

## Risk analysis — what could the change break?

Answered from the caller audit, not in the abstract:

- **No legitimate production caller passes non-canonical
  spellings today.** The verifier already refuses them before
  the gate; the canary and oversight feed canonical spellings;
  the memory store constructs a canonical path. Adoption
  changes no production caller's outcome on the inputs it
  actually sends.
- **Signed-rejection vs unsigned-refusal shift:** today a
  both-refuse spelling sent directly to `evaluate_self_change`
  can yield a signed GateDecision (usually a rejection on other
  grounds, or — for a spelling like `a/../../eval/gate.py` on
  an otherwise-clean change — potentially a signed ACCEPT,
  since the gate misses it). After adoption it raises
  `GateInputError` before any decision exists. Through the
  verifier nothing changes (it already refuses those spellings
  unsigned). Direct in-process callers would see an exception
  where they previously saw a decision object; the audit found
  none that rely on deciding such spellings.
- **The `eval/` false positive disappears:** a change naming
  the bare directory spelling `eval/` would no longer count as
  a protected violation. No caller names directory paths (all
  name files); the policy and oversight already treat `eval`
  as unprotected, so adoption aligns the gate with both.
- **Import-cycle risk** is the one real engineering risk, and
  it is why the sequencing note above exists. It is testable in
  minutes and fails at import time, loudly, never silently.
- **Test fallout is expected and bounded:** `tests/test_gate.py`
  pins current `_normalise_path` behaviour (e.g. the backslash
  case), and both pathpolicy suites pin the divergence; all
  are updated in the same protected change, with the harness's
  new table as the record of the closed divergence.

## What remains divergent even after adoption

- **Oversight's list is a superset by design.** Oversight
  protects `oversight/` and the bare `oversight` path on top of
  the gate's list, because the oversight workflow guards
  itself. Adoption does not merge the lists; the policy keeps
  reporting "gate" and "oversight" as separate tags, and the
  equivalence claim is per-tag, as the harness asserts.
- **Case sensitivity.** The policy and both lists are
  case-sensitive (Linux semantics): `EVAL/gate.py` is a
  different, unprotected path, and stays so after adoption.
  The verifier additionally demands a lowercase first
  component — a verifier-local strictness on top of the
  policy that adoption does not remove; through the verifier,
  `EVAL/gate.py` remains refused even though no list protects
  it. On a case-insensitive filesystem the case question would
  need a separate ruling; this codebase targets Linux.
- **Invisible-character spellings.** Canonicalisation is
  byte-preserving: a zero-width space inside `eval/` still
  flags via the prefix, and a BOM/homoglyph first component
  names a genuinely different file that no list protects.
  Adoption neither creates nor closes that; it is a
  filesystem-level fact, recorded here so it is not mistaken
  for a policy gap.

## Decision requested

Approve or decline: (1) gate adoption of path-policy/1 per the
diff sketch, with the import-cycle resolution sequenced as
option (a) — one dual-leg protected change covering `eval/`,
`oversight/` and `trust/pathpolicy.py`; or (2) decline, in
which case the demonstrated status quo stands — equivalence on
canonical spellings, the verifier as the sole signing path
refusing every non-canonical spelling, and the divergence
table pinned by the harness — and the policy's wording stays
at "consumed by manifest + verifier; gate adoption declined".
Either way, the v2 overclaim does not return: the wording now
states adoption status exactly.
