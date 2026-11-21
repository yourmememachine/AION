# Blind delta brief — combined cycle 13: Protected Gate adoption + production signed-path wiring

For the external war-room seats. This brief describes what
changed, the evidence, and the open questions. It deliberately
contains no internal verdicts or scores. Two work items were
built in one run. Baseline: 1081 tests, all passing. Close:
1145 tests, all passing (2 by-design skips, explained below).

## Item A — the Protected Gate proposal, implemented

Context you have seen before: the gate (`eval/gate.py`) judged
protected paths by literal spelling while the verifier, the
build manifest and the oversight workflow shared
path-policy/1; the divergence was demonstrated by a 66-spelling
differential corpus (10 "gate-miss" spellings of `core/loop.py`
passed the gate's own check). The sealed-registry and
calibration-log loaders accepted duplicate JSON keys last-wins
(findings P-1/P-2). You both recommended the remediation; it
required the owner's approval under the project's Protected
Gate Rule, which has now been given and executed.

What changed, exactly:

1. `eval/gate.py::check_protected_paths` judges the CANONICAL
   spelling: each presented path is canonicalised via
   path-policy/1 (`trust.pathpolicy.canonicalise`, which
   delegates to `oversight.approval.canonicalise_path` — one
   source of spelling rules), checked against the gate's
   unchanged lists (`eval/` prefix, `core/loop.py` file), and
   offenders are returned as the canonical spelling.
   Non-string/blank entries and spellings that cannot be
   canonicalised raise the gate's existing malformed-input
   error (`GateInputError`) — a refusal, never a pass. The
   import is FUNCTION-LOCAL (inside the function): a
   module-level import cycles two ways
   (`gate → trust/__init__ → shipcheck → signing.gate_decision
   → gate`, and `gate → trust.pathpolicy → oversight → gate`);
   the proposal's own correction round named the function-local
   import as an acceptable resolution. The proposal's
   alternative (flipping the delegation so the policy owns the
   algorithm and oversight delegates to it) was NOT taken. The
   gate's old private normaliser was deleted. The module
   header's "standard library only" claim was amended to name
   the lazy policy import as a stated exception. No other gate
   logic changed.
2. `eval/registry.py`: an `object_pairs_hook` now rejects
   duplicate keys at parse (`CorruptRegistryError`), in
   `EvalRegistry._load` and in the freshness check
   `_disk_changed` (same strict parse: duplicate + non-finite
   hooks; the freshness contract is unchanged — any parse
   failure reads as "changed").
3. `eval/calibration.py`: the mirror hook in
   `CalibrationLog._load` (`CorruptCalibrationError`).
4. The differential harness's recorded table was updated to
   the post-adoption shape: the gate-miss and gate-stricter
   classes are now empty (pinned empty by test), the
   uncanonicalisable rows are gate errors, `eval/` agrees
   unprotected. Equivalence now extends to every
   canonicalisable spelling in the corpus.
5. NEW negative-integration test
   (`tests/test_protected_gate_adoption.py`, 9 tests): through
   `evaluate_self_change`, an otherwise-acceptable change
   carrying `core//loop.py` is refused with reason
   `protected_path` and violations `("core/loop.py",)`; the
   canonical spelling refuses identically; a control path
   accepts (the refusal is attributable to the path alone); an
   uncanonicalisable spelling raises and no decision is
   issued. A registry file carrying a bogus-first duplicate
   key (digest valid over the last-wins parse) is refused by
   the REAL verifier subprocess with `registry_untrusted` and
   zero entries in the signing ledger. Both loaders refuse
   their duplicate-key artefacts directly. Two subprocess
   tests pin that the lazy import resolves with either
   `eval.gate` or `trust` imported first (mutation-checked:
   restoring a module-level import makes both fail).

Evidence: import battery 10/10 fresh-interpreter orders;
duplicate keys refused at every nesting depth in both
loaders, including `\u`-escaped duplicate keys; all 10 former
gate-miss spellings now flag; 145 tests across the seven
touched suites, all passing.

### The open question we are putting to you (and to the owner)

Adoption means the gate's verdict now DEPENDS on code outside
the gate's protected list. `trust/pathpolicy.py` is in no
protected list at all (the gate protects `eval/` +
`core/loop.py`; the oversight workflow's own list adds
`oversight/`; nothing lists `trust/`), and
`oversight/approval.py` is covered only by the oversight
workflow, not by the gate. Measured facts:
`check_protected_paths(["trust/pathpolicy.py"]) == ()` and
`oversight.is_protected_path("trust/pathpolicy.py") == False`.
So, inside the gate's stated threat model ("a change that
edits its own judge can fake any gain"), a change editing
only the canonicaliser passes every list today, and a later
protected change would be judged by the edited canonicaliser.
Before adoption the gate's spelling logic lived inside the
protected file itself. Counter-considerations: the verifier
signing path has depended on this same canonicaliser since
Trust Boundary v2 (three of your review rounds shipped in
that shape); adoption removes the gate's independent second
spelling implementation, so the genuinely new element is the
loss of diversity, not the dependency itself; and the human
oversight workflow does review `oversight/` changes. The
internal room did not reach unanimity on whether this blocks
the adoption's ship, and closing it (extending the gate's
protected scope to the code it now trusts, or relocating the
canonicaliser inside protected scope, plus a negative test)
is a further owner-approved protected change that has NOT
been authorised. Item A's ship is therefore withheld pending
the owner's decision, with your views explicitly sought: is
the adoption, as scoped by the approved proposal, shippable
with this declared as a residual — or is the coverage gap a
reason to hold it until the fence is extended?

Other declared residuals (Item A): case sensitivity and
invisible-character spellings are unchanged (filesystem
facts, documented in the policy); oversight's list remains a
superset by design; a broken `trust.pathpolicy` would surface
at the gate as a raw import error (fail-closed everywhere —
no decision can be produced — but not converted to the gate's
typed refusal); no generative test exists over the open
spelling family — the corpus pins 66 spellings literally.

## Item B — production signed-path wiring

Per the design note preserved from cycle 10
(internal/DESIGN-PRODUCTION-WIRING.md). NEW module
`trust/wiring.py`, the sanctioned construction site:

- `production_client(env, *, expected_signer_id,
  expected_key_id, launch="same-user")`: validates a copy of
  the verifier env before any spawn — keys restricted to the
  wrapper's allowlist (the design note says 15 names; the
  shipped wrapper has 14, an arithmetic error in the note —
  the code follows the shipped wrapper, and a test now parses
  `run-verifier.sh` at test time and asserts set equality);
  core names + mode + both anchor paths required non-empty
  (whitespace-only refuses); mode exactly `production`;
  `*_INIT` flags refused except the verifier's off-spellings;
  anchors absolute, distinct, resolved outside the verifier
  home, and (after review) refused when equal to the key
  path, inside the registry dir, or a directory;
  home/key/registry paths must be absolute; signer pin must
  equal the env's signer id; key pin must be `key-<16 hex>`,
  supplied out-of-band (the factory never reads the key
  file); errors name the variable, never the value (probed
  with sentinels). `launch="wrapper"` RAISES — the client
  has no command hook and the wrapper discards caller env,
  so routing is refused rather than faked.
- `open_production_store(dir)`: refuses genesis (missing
  `memory.json` is a refusal, not a bootstrap); reads the
  persisted mode WITHOUT constructing the store (no mkdir /
  ratchet / quarantine side effects — tree-hash probed);
  strict parse at inspection (duplicate keys, non-finite);
  requires `signed_only`; then constructs and binds the
  result to the inspected document twice over: the file's
  bytes must be unchanged after construction, AND the
  constructed store's `state_digest()` must equal the
  inspected document's `state_digest` field. The second
  binding exists because review demonstrated a straddle: a
  swap restored after the load but before the byte re-read
  otherwise handed out a store whose loaded state was the
  swapped file's. Declared remaining window: a swap restored
  BEFORE the load is indistinguishable and harmless (the
  loaded state is the inspected state).
- `commit_production(...)`: strong form only — presented
  signed attestation mandatory, `require_attestation=True`
  hardcoded, `expected_state_digest` defaulted from the live
  store, signer pin MANDATORY (it defaulted to None in the
  first build; review showed an envelope under a different
  signer id committing unpinned — now a TypeError to omit
  it), no `now=` parameter anywhere in the module.
  Declared limit: the pin names the gate decision's signer;
  the attestation's verifier_id is NOT bound to the
  decision's verifier_id at this surface (attester
  eligibility is judged by the gate flow that produced the
  decision).
- The module docstring carries the design's honesty
  verbatim in substance: a parameterised factory is
  enforcement by validation + lint, NOT a capability
  boundary under the project's same-user threat model; the
  deployment-grade form (config only from the root-owned
  wrapper env file, no arguments, returns results not
  handles) is described, not built (separate backlog item).
- Lint: `tests/test_trust_lint.py` now counts
  `VerifierClient(` / `MemoryStore(` constructions in
  production code (bare/attribute/import-alias forms) —
  exactly one of each allowed in `trust/wiring.py`;
  `memory/reuse.py`'s two legacy constructions are a counted
  QUARANTINED exception. The lint's blind spots are now
  enumerated and pinned by tests (getattr indirection, bare
  method references, `functools.partial`, subclassing a
  watched class, name-reassignment) and its claims are scoped
  to the detected forms.

Scope honesty (Item B): the backlog item's title also
promises wiring production flows and migrating
`memory/reuse.py` off its legacy unsigned path. Neither
happened, and the record says so: a repo-wide grep finds
ZERO production callers of the new factories (the loop's
ship recording uses `trust/shipcheck.record_ship` directly;
the health check drives the wrapper), so there is currently
no in-repo production flow to wire — the factory is the
sanctioned site for the first one, fenced by the lint, not
yet load-bearing. The reuse migration is split out as a
named follow-on backlog item rather than left inside a
"done" title.

Live evidence (Item B): the VM had wiped the deployment
again; it was re-provisioned by the documented ceremony
against this tree. Deployment health check 10/10. The
wiring's live test RAN against the real deployment (not a
skip): a client built by `production_client` from the real
root-owned env, pins obtained operator-side, drove the
production verifier; the response reported effective mode
`production` from inside the process and the client's mode
pin held. Production deployment suite: 18/18 on fresh
budgets. The 2 skips in the full-suite count are that
suite's two one-shot live tests in their by-design
post-run state.

Declared residuals (Item B): numeric budget values are
unbounded in both the factory and the verifier (a config
error silently disables the query cap — a verifier-layer
concern); TTL/budget/purpose formats are validated by the
verifier at spawn, not the factory (fail-closed, late);
anchors' contents are not read by the factory (swapped
anchors refuse downstream on kind/format); the attestation
carries no store binding (inherited, documented in the
signing layer); joint journal+anchor rollback, builder-owned
keys, self-asserted pins, fake verifier modules, and
check/use TOCTOU outside the bound windows remain as
catalogued in the module docstring.

## Questions for the seats

1. Item A: ship-with-declared-residual, or hold until the
   gate's fence covers the code it now trusts? If hold:
   is extending the gate's own list the right closure, or
   relocating the canonicaliser?
2. Item A: does the function-local import (vs the proposal's
   delegation flip) change your judgement of the adoption?
3. Item B: is factory+lint, with zero production callers and
   the migration split out, an honest completion of the
   design note's scope — or should the item stay open until
   a caller exists?
4. Item B: the store-open state binding and the mandatory
   signer pin — any remaining way to obtain a
   weaker-than-claimed production handle through this
   module?
5. Anything in either delta that the brief misdescribes.
