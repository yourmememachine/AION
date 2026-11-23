# Gate closure — layered analysis (cycle 19)

What does one call to `eval.gate.check_protected_paths` actually
trust? This document is the layered closure analysis behind the
cycle-19 gate scope extension. It states what the extension
closes, and — plainly — what it does not. The protected list is
the verdict-defining chain plus the import-path packages; it is
**not** an unqualified dependency closure.

The gate's list after cycle 19:

```python
PROTECTED_PREFIXES = ("eval/",)
PROTECTED_FILES = ("core/loop.py", "oversight/__init__.py",
                   "oversight/approval.py", "trust/__init__.py",
                   "trust/pathpolicy.py")
```

`trust/pathpolicy.py` mirrors the same five files in
`GATE_PROTECTED_FILES`, copied not imported, under drift-detection
tests.

## L0 — verdict logic

`eval/gate.py` itself: `check_protected_paths`, the two constants,
and the `path in PROTECTED_FILES or startswith(PROTECTED_PREFIXES)`
test. Already protected by the `eval/` prefix before this cycle.
Closed before cycle 19.

## L1 — verdict inputs: the canonicaliser chain

- `trust/pathpolicy.py::canonicalise` — delegates, adds nothing.
- `oversight/approval.py::canonicalise_path` — the actual algorithm
  (strip, backslash translation, `""`/`"."` components dropped,
  `".."` refused, absolute and drive paths refused, empty refused).

One layer deeper: `oversight/approval.py`'s own imports are stdlib
only plus `from eval.gate import check_protected_paths` — back into
L0, already protected. `trust/pathpolicy.py`'s own imports are
`__future__` plus the one `oversight.approval` import. The L1 chain
therefore terminates in stdlib + already-protected code, which is
what makes this layer's closure exact rather than aspirational:
after the extension, every repo file that *defines* the verdict's
canonicalisation is in the gate's list. Both files are protected
(exact files) by cycle 19. Closed by this extension.

This closes the demonstrated two-step attack exactly: previously
a change editing only the canonicaliser passed every list at
step 1, and a later `eval/` change would then be judged by the
poisoned canonicaliser at step 2. Step 1 is now itself a
`protected_path` refusal (pinned by the negative tests N1/N2 in
`tests/test_protected_gate_adoption.py`).

Note the overlap, reported honestly: `oversight/approval.py` was
already in oversight's own protected scope, and is now protected
by **both** lists. `trust.pathpolicy.classify()` reports
`["gate", "oversight"]` for it; the overlap is not hidden.

## L2 — package `__init__` files executed on the import path

- `trust/__init__.py` — executed by the gate's lazy
  `from trust.pathpolicy import canonicalise`.
- `oversight/__init__.py` — executed by pathpolicy's
  `from oversight.approval import canonicalise_path`.
- (`eval/__init__.py` — executed when the caller imports the gate,
  already under the `eval/` prefix.)

These do not define the algorithm, but they control binding: what
the names `trust.pathpolicy` and `oversight.approval` resolve to,
and in what order submodules load. Both are protected (exact
files) by cycle 19. Closed by this extension at the file-edit
level: a self-change editing either `__init__` is now itself a
`protected_path` refusal.

Why each new file is protected, in one place:

| File | Why |
|---|---|
| `trust/pathpolicy.py` | The gate judges canonical spellings through its `canonicalise`. |
| `oversight/approval.py` | That `canonicalise` delegates to its `canonicalise_path`, the single source of spelling rules. |
| `trust/__init__.py` | Executes on the gate's import path to `trust.pathpolicy`; controls which module that name binds. |
| `oversight/__init__.py` | Executes on the import path to `oversight.approval`; controls what `canonicalise_path` binds to. |

## L3 — modules executed via `trust/__init__` re-exports

`trust/__init__.py` imports, in order: `.attestation`, `.client`,
`.errors`, `.ledger`, `.manifest`, `.release`, `.anchoring`,
`.budgets`, `.pathpolicy`, `.shipcheck`, `.shiptx`, `.wiring`.
Those pull in transitively the whole `signing/` package,
`trust/protocol.py`, parts of `memory/`, and `eval/` re-exports.
These modules are executed when the gate verdict runs, but they
define nothing the verdict uses — they *consume* its result.
Protecting consumers because they are loaded would, by the same
logic, protect most of the repo, and prefix escalation does not
terminate (`trust/` → `signing/` → `memory/` → …). They are
therefore **not** in the gate's list. That leaves the residual
below, named rather than silently absorbed.

## Residuals — what this cycle does NOT close

### Residual R-A: L3 `sys.modules` pre-seeding is NOT closed

The gate's lazy import binds whatever
`sys.modules["trust.pathpolicy"]` holds at call time.
`trust/__init__` executes several L3 submodules before its own
`.pathpolicy` re-export line, and `.manifest` itself imports
`trust.pathpolicy`. An accepted change to an earlier-executed L3
submodule (for example `trust/client.py`) that pre-registers or
mutates `sys.modules["trust.pathpolicy"]` — or stashes a fake
`canonicalise` attribute on the real module — would poison later
gate verdicts in that process, and that edit is not in the
protected list. No in-code mitigation exists today.

The structural fix is the follow-up **`gate-import-isolation`**
(named, not built): load the policy without executing
`trust/__init__.py`, e.g. by direct file loading under a private
module name inside the gate's lazy import. It is out of this
cycle's authorised `eval/` scope (list + comment only), it would
create a second module instance of `trust.pathpolicy`, and it
needs its own review. The L1+L2 extension above is the
prerequisite that makes the interim state defensible: the only
route to a poisoned canonicaliser *definition* is now a refused
protected change; R-A requires the strictly stronger position of
smuggling executable pre-seeding code through an ordinary,
heavily tested module — in a process where code of that reach
could equally monkeypatch `eval.gate` directly, a capability the
gate's own header already disclaims (the gate checks consistency;
independence is a property of the process around it).

### Residual R-B: the lazy import's raw failure stays untyped

If any module on the lazy-import path fails to import,
`check_protected_paths` raises the raw error, not
`GateInputError`. It fails closed everywhere, but untyped.
Wrapping the import would be an `eval/` logic change and is
outside this cycle's authorised `eval/` scope, so it stays open
here — neither worsened (this extension enlarges the protected
list, not the load surface) nor fixed.

### Residual M4: the new ceremony-authorisation code is unprotected

The cycle-19 ceremony-authorisation code —
`signing/ceremony_authorisation.py` and the verifier's ceremony
mode — is itself outside every protected list. It is named here,
not extended this cycle: adding it to the gate's list was not
part of the agreed extension, and its protection belongs with
the held cycles' re-review.

## Out of scope by design

- No `trust/` or `oversight/` gate prefix: exact files only, so
  routine trust/oversight work does not become a dual-leg
  ceremony and the gate/oversight lists stay separately reported.
- Case sensitivity is unchanged: `Trust/pathpolicy.py` is a
  different, unprotected path on this (case-sensitive) target.
- The verifier's canonical-spelling + lowercase-first-component
  rules remain a second, independent line; this extension neither
  relies on nor weakens them.
