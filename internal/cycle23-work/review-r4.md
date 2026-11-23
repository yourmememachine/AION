# Cycle 23 — War-room review rev-r4 (BLIND)

Lens: WS2 production-mode honesty + the client pin fix.
Baseline 59a656a, working tree reviewed via `git diff`.
`tests/test_trust_production_e2e.py` run by this reviewer:
5 tests, OK.

## Verdict: SHIP — score 0.92

## (1) `_check_ceremony_pins` weakens nothing

- The diff touches exactly one call site: `ceremony_authorise`
  (`trust/client.py:554`). Every other pin path is byte-unchanged
  and still uses `_check_pins`: gate envelopes via
  `_check_envelope` (:254), `sealed_eval` (:404),
  `issue_attestation` (:468). Gate/attestation enforcement is
  identical before/after.
- On the ceremony path the old check was not a weaker-but-valid
  control, it was a namespace collision: production wiring
  mandates `expected_key_id` in `key-<16 hex>` form
  (`trust/wiring.py`, `_KEY_ID_RE`), while ceremony envelopes
  carry `pub-<16 hex>`. The old check therefore refused *every*
  correctly issued production ceremony envelope. The new check
  compares `key_id` against the pinned `CeremonyPublicKey`
  object's derived `key_id` — the same object the Ed25519
  signature is then verified against in
  `verify_ceremony_authorisation` (full event binding incl.
  `expected_signer_id`). The signer pin is retained verbatim.
  Net effect: the ceremony path goes from unusable-under-pins
  to a check that is bound to the actual verification key
  material; for a client with no gate key pin it is strictly
  *stricter* than before (previously no key-id check at all on
  this path when `expected_key_id was None`).
- Fail-closed shape is right, and it cannot surprise a
  legitimate non-ceremony production client:
  `_check_ceremony_pins` is reachable only from
  `ceremony_authorise`, which already refused locally
  (`VerifierConfigError`, before any spawn) when no ceremony
  public key is pinned. The `None` branch inside
  `_check_ceremony_pins` is therefore unreachable via the
  public API — defence-in-depth with the same error type, not
  a new refusal surface. Gate/attestation-only production
  clients (wiring makes the ceremony key optional) never touch
  this code. `trust/wiring.py` is verified unmodified
  (`git diff` empty).

## (2) Bootstrap: sound; one wording imprecision in the design, not the harness

- Order in `verifier_main.main()`: request decode →
  `_load_config()` → mode dispatch. Anchor initialisation is a
  `_load_config` side effect: production refuses all three
  INIT flags outright (signing :682ff, budgets :737ff,
  consumption :824ff — the last gated on the ceremony seed
  being configured, which the harness env does configure), so
  the research-mode INIT invocation is the only route, exactly
  as R2 states. Mode reporting is honest: `deployment_mode`
  stays `None` until config load succeeds and is attached to
  every later response; the e2e asserts the adopter's client
  observes `"production"` after the flip, and `production_client`
  pins that expectation.
- Does the malformed request run no mode body? Strictly, no —
  and the harness docstring says the true thing while
  DESIGN-FINAL R2's shorthand ("so no mode body runs") does
  not. `_mode_gate` *is* entered; it refuses on its first
  check (body key set, `_mode_gate` head) before any signing,
  budget spend, or ledger append. The harness's own wording —
  "the mode then refuses the body as malformed (exit 2) before
  anything can be signed" — is accurate.
- Does the signing-ledger assertion prove it? Alone it proves
  the load-bearing fact — nothing was signed/ledgered. In
  conjunction it proves more: exit 2 (a pre-config decode
  failure also returns 2, but then no anchors would exist) +
  all three anchor files present + signing ledger empty
  together establish that config load ran to completion,
  initialised the anchors, and the gate body refused before
  signing. Minor gap, non-blocking: the harness does not also
  assert the budgets/consumption journals are empty; this is
  covered structurally (gate's first-line refusal precedes any
  budget/ledger mutation, and gate never touches the
  consumption journal), but asserting all three journals empty
  would make the proof self-contained.
- Leftover-state risk: what the bootstrap pins is genesis
  only. `initialise_anchor` refuses a non-empty journal
  without the explicit nonempty ceremony flag, and the budgets
  INIT guard in `_load_config` likewise pins only the genesis
  head — so the research invocation cannot launder an
  established or rolled-back journal into a production-accepted
  anchor. The resulting home (empty journals + genesis anchors
  outside the verifier home) is precisely the fresh-deployment
  genesis state production is designed to accept; INIT keys
  are stripped from the returned env, so no production-refused
  state is carried forward, and no production-acceptable state
  is created that an operator INIT ceremony could not also
  create.

## (3) Claim scope matches what is exercised

- The e2e module docstring and the harness docstring both cap
  the claim at exactly R2/B1: production MODE under same-user
  spawn on this VM; NOT production DEPLOYMENT (no separate OS
  user; `production_client(launch="wrapper")` refused by
  design — verified in the unmodified wiring). The home is a
  `TemporaryDirectory` disposable home; the adopter's client
  genuinely comes from `production_client` via
  `build_pin_adopter`. No name or docstring I read overclaims:
  `provision_production_home` / `ProductionE2E` are qualified
  by their docstrings at the point of definition. The 28
  deployment-gated skips are untouched by these suites.

## (4) The seam correction is legitimate and strengthens the test

- Legitimate: `build_pin_adopter` constructs its own
  `PinStore` over `pin_dir`; the fixture's `self.store` is a
  second instance over the same directory. Patching
  `self.store.adopt` could never fire on the adopter's path —
  the correction changes only the patch target
  (`self.adopter._store.adopt`), no assertion is changed, and
  the in-test comment discloses this plainly, including that
  the inert seam was masked by the genesis pin-namespace
  failure. This is a fix to make the test prove what it always
  claimed, not a weakening.
- Call-order trace (`PinAdopter._reanchor`): evidence →
  authorise-pending journal → authorise → authorised journal →
  `reanchor_pin(...)` (inside which the verifier's
  `ceremony_consume` commits the consumption) → consumed
  journal → `_store.adopt(new_pin, record, ...)` (step 5).
  The flaky wrapper fires only when `record is not None` and
  armed — i.e. only on the ceremony adopt, not the dense
  `record=None` advance — and raises *after* consumption has
  committed, producing `PinAdoptionBurned`. That is a genuine
  post-consumption adopt failure, not a simulated burn.
- The recovery assertion still proves the production-mode
  `burned_unadopted` path: the second `snapshot_and_adopt()`
  must find the unadopted burn, issue a fresh ceremony under
  reason `burned_unadopted`, and consume it as a v2 recovery —
  asserted concretely: outcome `reanchored`, reason
  `burned_unadopted`, pin seq 5, exactly 3 consumptions, last
  entry `consumption_kind == "recovery"`,
  `recovery_depth == 1`, history length 2, no `lost_pin`, and
  the consumption anchor verifying current afterwards. If the
  seam were still inert, the first call would return
  `chain_gap_recovery` normally and `assertRaises
  (PinAdoptionBurned)` would fail — the test is self-checking
  against seam inertness. (This is fault injection in the WS2
  e2e, not cited as WS4 crash coverage, so the R4 *SeamTests
  naming rule is not engaged.)

## (5) Negative tests pin `production_client` itself

- Both negative tests import and call
  `trust.wiring.production_client` directly — no lookalike,
  no stub: `test_adopter_env_key_in_verifier_env_refused`
  adds `AION_PIN_DIR` (outside the 19-key allowlist) and
  asserts `VerifierConfigError` naming the variable, and
  additionally routes the same env through `_build_adopter`
  (i.e. `build_pin_adopter` → `production_client`);
  `test_init_flag_in_production_env_refused` iterates all
  three INIT flags at value `"1"` against `production_client`
  and asserts the refusal names each flag. These are
  construction-time refusals — they fire before any client
  exists or anything is spawned, matching wiring's contract.
- The appended `CeremonyPinNamespaceTests` are honestly
  scoped: transport stubbed at `_run`, docstring states they
  pin the client's pin logic in isolation and that the e2e
  proves the same path against the real verifier. Positive
  (gate `key-` pin + ceremony `pub-` pin accepts) and negative
  (envelope under a different pub key refused,
  "unexpected key") are both present. Minor gap, non-blocking:
  no stub-level test for a wrong-*signer* ceremony envelope;
  that check is the shared first clause of both pin methods
  plus `verify_ceremony_authorisation`'s signer expectation.

## Findings summary

- No weakening found in any gate, attestation, or ceremony
  check; the pin fix closes a real namespace collision that
  made production ceremonies unusable, and binds the key-id
  check to the very key object used for signature
  verification.
- No production-mode overclaim in the harness or e2e; claim
  language matches the same-user, disposable-home reality.
- Non-blocking nits: (a) DESIGN-FINAL R2's "no mode body runs"
  shorthand is imprecise — the gate body is entered and
  refuses at its first check; the harness docstring is the
  accurate record. (b) The bootstrap could assert budgets and
  consumption journals empty as well as the signing ledger.
  (c) `_check_ceremony_pins`' no-pub branch is unreachable via
  the public API (harmless defence-in-depth).
