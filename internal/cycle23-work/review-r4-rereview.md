# Cycle 23 — War-room RE-REVIEW rev-r4 (fix round)

Lens: WS2 production-mode honesty + the client pin fix (same as round 1).
Round-1 verdict: SHIP 0.92 (`review-r4.md`). This re-review checks the
fix round (working tree, uncommitted: `trust/ledger.py`,
`trust/pin_adoption.py`, tests, `trust/README.md`,
`deploy/verifier-identity/README.md`) against those conclusions.

## Verdict: SHIP — score 0.92 (unchanged)

## (1) Round-1 conclusions stand — the fix round did not touch their substrate

- `trust/client.py` and `trust/wiring.py`: `git diff` contains no
  wiring change at all, and the client diff is exactly the round-1
  build diff and nothing more — one hunk adding
  `_check_ceremony_pins` (client.py:268) and the single call-site
  swap in `ceremony_authorise` (:554, `_check_pins` →
  `_check_ceremony_pins`); every other pin path still routes through
  `_check_pins`. File mtimes corroborate the task statement:
  client.py 11:29 and wiring.py 10:32 predate the round-1 reviews
  (11:42–11:45); the fix-round files are stamped 11:48–11:49.
  Therefore the round-1 analysis holds byte-for-byte: the fix closes
  the `key-<16 hex>` vs `pub-<16 hex>` namespace collision, binds the
  ceremony key-id check to the pinned `CeremonyPublicKey` object the
  signature is verified against, retains the signer pin verbatim,
  and weakens no gate/attestation path.
- Bootstrap soundness (round-1 §2): unchanged and re-exercised. The
  harness (`tests/cycle23_harness.py`) still bootstraps via one
  research-mode INIT invocation, strips the INIT keys, and flips
  `AION_DEPLOYMENT_MODE` to `production` (:185–187); the e2e still
  asserts the adopter's client observes production mode. The
  round-1 wording nit (DESIGN-FINAL R2's "no mode body runs"
  shorthand vs the harness's accurate docstring) is unaffected and
  remains non-blocking.
- E2e seam correction (round-1 §4): still present and still
  legitimate on the final tree — `tests/test_trust_production_e2e.py:145-165`
  patches `self.adopter._store.adopt` (the adopter's own store
  instance), with the in-test comment disclosing that the old
  `self.store.adopt` seam never fired and was masked by the genesis
  pin-namespace failure. No assertion was weakened; the test remains
  self-checking against seam inertness (an inert seam would make
  `assertRaises(PinAdoptionBurned)` fail).

## (2) Production evidence re-run on the final tree — holds

Reviewer ran, on the final uncommitted tree (unittest; pytest is not
installed on this VM):

```
python3 -m unittest tests.test_trust_production_e2e tests.test_cycle23_live_run -v
Ran 6 tests in 4.274s — OK
```

- `test_trust_production_e2e`: 5/5 OK — the two
  `CeremonyPinNamespaceTests` (different-pub-key envelope refused;
  gate `key-` pin + ceremony `pub-` pin accepts), both negative
  `production_client` tests (adopter env key refused; all three INIT
  flags refused in production env), and
  `test_genesis_dense_advance_and_burned_recovery` — the full
  genesis ceremony + dense advance + `burned_unadopted` recovery in
  production mode, now running through the fix round's ledger
  (schema-v2 bounded recovery) and pin_adoption (authorise-pending
  journal line, r6-F6 refusal typing) code. The fix round therefore
  did not break the production-mode path it touched around.
- `test_cycle23_live_run`: 1/1 OK — the live-run sequence against a
  byte copy of the real `state/` under the production home still
  completes, so the "live run" evidence cited by the READMEs is
  current, not stale round-1 evidence.

## (3) Fix-round items 11–12 — README edits: no overclaim found

- `trust/README.md` (new Pin adoption bullet): "production adopter"
  and "`anchored_record_ship` is the production recording path" are
  the DESIGN-FINAL R5's own terms for these paths, and the bullet
  closes with the scope sentence kept exact and in the same breath:
  "this proves production MODE under same-user spawn on one machine
  (live run against a byte copy of the real state dir); it is not a
  production deployment." No separate-OS-user, wrapper-launch, or
  deployment claim is made or implied; the byte-copy parenthetical
  matches the live-run test re-run above and the identically scoped
  docstring the fix round added to `trust/pin_adoption.py` ("The real
  state/ directory itself has never been adopted against…; there is
  no production deployment"). The hooked-loop refusal claims in the
  bullet match R1 and the code.
- `deploy/verifier-identity/README.md` (bounded-recovery paragraph):
  a mechanism description, not a production-mode/deployment claim,
  and every assertion checks against the final code —
  `MAX_RECOVERY_DEPTH = 2` (`trust/ledger.py:40`), a movement
  consumable at most three times (primary + two recoveries,
  ledger.py:775–776), schema-v2 lineage fields `recovery_of` /
  `recovery_depth`, authorise refusing an unproven recovery
  (`ceremony_recovery_unproven`, `trust/verifier_main.py:2555`),
  consume refusing the capped target as already consumed
  (`AlreadyConsumedError`), and liveness resuming via a fresh
  primary `chain_gap_recovery` through the supersede head rule
  (ledger.py:1096–1254; pinned by the supersede tests in
  `tests/test_trust_consumption_schema_v2.py`). It does not revive
  the stale one-shot wording R3 ordered swept.

## Basis

Nothing in the fix round reopened any round-1 question: the pin fix
and wiring are byte-identical to what was reviewed, the bootstrap
and seam analyses stand, both mandated suites pass on the final
tree (6 tests, OK) with the production-mode evidence intact through
the new ledger/pin_adoption code, and the two README edits scope
their production language exactly at production MODE — same-user
spawn, byte copy, explicitly not a deployment. SHIP, 0.92.
