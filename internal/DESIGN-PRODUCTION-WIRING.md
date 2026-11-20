# Design note — production-signed-path-wiring (deferred to cycle 11)

Recorded 2026-11-20 in cycle 10's planning step. Three coder seats
(seat-5 correctness, seat-9 tools, seat-3 adversarial) designed
`trust/wiring.py` in full. The cycle-10 build was re-scoped to
`signed-state` because the loop's own pick rule (highest leverage,
ties by insertion) selects `signed-state` (7.0, seq 2) ahead of
`production-signed-path-wiring` (7.0, seq 19), and a cycle can only
be recorded against the picked item. These designs are the agreed
starting point for cycle 11; nothing here is built yet.

## Agreed design (reconciled)

- `production_client(verifier_env, *, expected_signer_id,
  expected_key_id)`: validate a copy of the env before any spawn —
  keys restricted to the 15-name wrapper allowlist (unknown keys,
  including the non-existent `AION_SHIP_ANCHOR_PATH`, refuse);
  the 5 core names plus `AION_DEPLOYMENT_MODE` and both anchor
  paths required non-empty; mode must be exactly `production`
  (absent defaults to research in the verifier — a one-string
  downgrade); `*_INIT` ceremony flags forbidden; anchor paths
  absolute, distinct, resolved outside the verifier home; pins
  mandatory, signer pin must equal the env signer id, key id in
  `key-<16 hex>` form supplied out-of-band (the client never reads
  the key file). Errors name the variable, never its value.
- Wrapper routing: REFUSE. `VerifierClient` has no command hook
  (it hardcodes `sys.executable -m <module>`), and
  `run-verifier.sh` discards caller env by design. A
  `launch="wrapper"` request raises rather than silently falling
  back to a same-user spawn. Extending the client with a command
  hook is its own cycle (backlog: `verifier-wrapper-routing`).
- `open_production_store(memory_dir)`: refuse genesis (missing
  `memory.json` is refusal, not bootstrap); read the persisted
  mode read-only (never construct `MemoryStore` to inspect — its
  constructor mkdirs, ratchets and quarantines); require
  `signed_only`; only then construct, and re-assert the mode.
- Strong commit form only: `require_attestation=True`, a
  presented signed attestation, and `expected_state_digest`
  defaulted from the store; no `now=` parameter anywhere.
- Lint extension: count `VerifierClient(` and `MemoryStore(`
  constructions (bare, attribute and import-alias forms) in
  `tests/test_trust_lint.py`; allowlist exactly one of each in
  `trust/wiring.py`, plus `memory/reuse.py`'s two legacy
  constructions as an explicit counted QUARANTINED exception.

## Preserved adversarial findings (seat-3)

Parameterised factories are a laundering surface under a
same-user threat model: the strict-validation factory above is
enforcement by validation + lint, not a capability boundary.
The deployment-grade form derives config only from the
root-owned wrapper env file, takes no path/env/pin arguments,
and returns results, not handles. Genesis/joint-deletion,
builder-owned keys, self-asserted pins, fake verifier modules,
anchor placement inside the verifier home, joint journal+anchor
rollback, and check/use TOCTOU were all catalogued; several are
declared residuals, not closed claims. Full seat reports are in
the cycle-10 build record's design summary.
