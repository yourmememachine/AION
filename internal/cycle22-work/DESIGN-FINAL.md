# Cycle 22 — DESIGN-FINAL (coordinator rulings)

Date: 2026-11-23. Inputs: design-a.md (WS1), design-b.md (WS2),
design-c.md (WS3), CROSS-CHECK-15.md, CROSS-CHECK-14.md,
BUILD-CYCLE-21.md. The rulings below are the build contract;
where a design seat disagreed, the losing position is recorded.

## R1 — WS1 (F4): design A adopted in full

- `burned_unadopted` joins `REASONS` in BOTH mirrored modules
  (`signing/pin_ceremony.py`, `signing/ceremony_authorisation.py`);
  `_NO_PIN_REASONS` unchanged; new mirrored `_EITHER_PIN_REASONS
  = {burned_unadopted}` (drift-tested). Coherence rule becomes
  ternary (A §1.3) in the payload projection, the authorise
  mode's cheap validation, `reanchor_pin`, and
  `verify_ceremony_record`.
- Burn identification is implicit: new
  `CeremonyConsumptionLedger.match_head_burn(entries, *,
  candidate, old_pin)` (A §2.2), head-only, target + old-pin
  exact equality (None encoded seq=None/hash=""). No wire
  change, no journal format change, no `reason` in EXTRA_KEYS.
- Authorise: new step (5b) after anti-replay, before signing,
  ONLY for `reason == burned_unadopted` (A §12.3: ordinary
  issuance gains no new failure dependency). Predicate failure
  → ONE new exit-3 code `ceremony_recovery_unproven`;
  unreadable consumption journal → `ledger_failed`.
- Consume: `check_head` gains the single scoped exception
  (A §4.2) — candidate==head and the old-pin-behind-head
  refusal lift iff reason is `burned_unadopted` AND
  `match_head_burn` matches; the old-pin generic rule is
  REPLACED by exact equality for that case, not waived.
  `append_consumption` unchanged. No new consume codes.
- `reanchor_pin`: with-pin `burned_unadopted` requires the
  strict `("chain_gap",)` recomputation exactly as
  chain_gap_recovery (A §6.1.3); no-pin case none. History
  checks unchanged (half-adoption stays refused in-band).
- Iterated recovery is a chain, one head at a time (A §6.2);
  the two-recoveries race outcome (A §4.4.5) is specified and
  test-pinned, not discovered.
- Claim wording: A §8 verbatim in substance, INCLUDING the
  intact-verifier-home qualifier, which R2 narrows but does
  not remove (research mode / anchor-unconfigured).
- Seat B's §8.1 union-read objection (validation must read
  mirror ∪ journal) LAPSES under R2: the consumption journal
  remains the complete burn record; no mirror-only burn state
  exists. Validation reads the journal only — after
  `_load_config`'s per-request anchor verification (R2),
  which is what makes the read trustworthy when configured.

## R2 — WS2 (mirror gap): option (a), anchoring the consumption journal

Seat B recommended (c) (mirror-first restructure); seat A
recommended (a). Ruling: **(a), consumption journal only**,
adopting B's load-bearing ordering insight and B's oracle
work wholesale. Reasons:

1. (c) inverts cycle 21's deliberate, externally reviewed
   authority choice (consumption journal = commit point and
   head authority; mirror = audit copy, "must never be
   appended first") one cycle after it was made, and creates
   a new legal state (mirror-only burn) in which the journal
   — the head authority — is incomplete: `check_head` cannot
   see a mirror-only target, so a fork at a mirror-only-burned
   sequence passes the head rules. B's defence (the pin never
   adopted that target) is honest but the head's completeness
   is a load-bearing invariant for WS1 and for cycle 21's
   re-mint-laundering closure; (a) preserves it.
2. Both options carry the identical append→anchor crash
   window (B §0/§4.3 concedes this for (a) and (c) alike);
   (c)'s advantage is cost, not closure strength. The
   mandatory adversarial test passes under (a) at the same
   layer (startup `anchor_refused` before mode dispatch)
   because the verifier is one process per request and
   `_load_config` verifies anchors on every invocation.
3. (a)'s costs are mechanical and bounded: allowlist 17→19,
   one startup block cloned from the signing block, one
   genesis pattern that already exists twice in-tree.

Design, exactly:

- `trust/anchoring.py`: `ANCHOR_KINDS` gains
  `"ceremony-consumption"`. No format change.
- Env: `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` +
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`, following the
  signing/budgets precedent in `_load_config`: absolute path
  required; must live outside the verifier home (explicit
  check like the budgets block) and be distinct from the
  signing and budgets anchor paths (extend the distinctness
  validation in `_load_config` and `trust/wiring.py`).
  Allowlist 17→19 in ALL copies: run-verifier.sh,
  health_check.py (incl. _INIT_KEYS/_PATH_KEYS), wiring.py
  (ALLOWED_ENV_KEYS, _INIT_ENV_KEYS, _ANCHOR_ENV_KEYS),
  setup.sh, tests/test_trust_wiring.py,
  tests/test_trust_production_deploy.py, verifier_main
  header docstring.
- Production rule: production mode + ceremony seed
  configured ⇒ consumption anchor path REQUIRED at startup
  and INIT refused (mirroring AION_ANCHOR_PATH's production
  discipline). Research: optional; unconfigured ⇒ no
  rollback claim (wording must say so).
- Startup block (per-request, in `_load_config`): construct
  `CeremonyConsumptionLedger(home)`; `verify_anchor(...,
  kind="ceremony-consumption")`; `("anchor_missing",)` +
  INIT ⇒ `initialise_anchor` (its own established-ledger
  guard applies unchanged — a non-empty journal with a
  missing anchor is NOT silently blessed; recovery is the
  audited force_reanchor path, exactly as for signing);
  any other reasons ⇒ `anchor_refused`. The block runs when
  the anchor path is configured, regardless of mode.
- Consume commit order becomes: (1) consumption-journal
  append (commit point, unchanged); (2) NEW
  `_update_ceremony_consumption_anchor(config)` — no-op when
  unconfigured, AnchorError ⇒ `ledger_failed`, burn stands;
  (3) signing-ledger mirror; (4) `_update_anchor` (signing).
  B's ordering point is the crux: the consumption anchor
  advances BEFORE the mirror write, so the Gemini sequence
  (mirror failure + home rollback) leaves the anchor ahead
  of the rolled-back journal ⇒ `anchor_ahead_of_journal` ⇒
  refused at startup. Mirror failure semantics are
  otherwise UNCHANGED from cycle 21 (burn stands,
  `ledger_failed`) — K6 does not flip.
- Authorise mode also appends to the signing ledger only;
  it does not touch the consumption journal or its anchor
  (except WS1's read at (5b), which runs after config-load
  anchor verification).
- Issuance journal (`ceremony-authorisations.json`): NOT
  anchored this cycle. Follow-up `ceremony-journal-anchoring`
  is NARROWED to the issuance journal. Seat A's preference
  for joint anchoring is recorded; scoping reasons are
  B §1.4's (defect is consumption-specific; a resurrected
  issuance pair yields an envelope that must still pass
  consumption, where single-use and the head live).
- Oracle: B §7.2 adopted — narrow the claim, do not collapse
  codes. B's exact replacement wording goes into the consume
  mode docstring (and any "no forger oracle" phrasing in
  trust/ + signing/ is reconciled to it), plus B's one
  sentence in `AlreadyConsumedError`'s docstring.
- Residual wording: cycle-21 R10 paragraph is rewritten to
  state: with the consumption anchor configured, a burn
  whose anchor update completed survives a verifier-home
  rollback (detected at startup); the append→anchor-update
  window (burn in journal, anchor at pre-burn prefix) is
  protected against an intact home but NOT against a full
  rollback inside that window — the same window every
  anchored append in this system carries; research mode /
  anchor unconfigured: no rollback claim.
- Mandatory tests: B's T-WS2-1 adapted to (a) — anchored
  fixture (AION_ANCHOR_PATH for signing + the new
  consumption anchor path outside home, INIT bootstrap then
  removed): authorise E; snapshot home; consume E with the
  MIRROR patched to fail (journal append + consumption
  anchor update land; mirror raises) ⇒ `ledger_failed`;
  roll back home (anchors untouched); replay E via a fresh
  client ⇒ REFUSED with `anchor_refused` at startup; assert
  no journal gained an entry. Plus: clean-consume rollback
  variant (T-WS2-3 adapted); consumption-journal-only
  rollback (journal restored, signing ledger intact ⇒
  startup refuses — anchor ahead); anchor-update-failure
  characterisation (patch the consumption-anchor update to
  raise ⇒ `ledger_failed`, replay on intact home refuses
  `ceremony_already_consumed`); append→anchor window
  characterisation test asserting replay SUCCEEDS after
  rollback inside that window, labelled as pinning the
  claim boundary (T7/T8 precedent — a future closure must
  flip it deliberately); research-mode characterisation
  (no anchors: consume, roll back, replay succeeds — pins
  the no-claim boundary). Mutation discipline: the
  mandatory test must be shown to FAIL against the
  pre-cycle-22 commit order (anchor update after mirror)
  or its absence — run once during build, result recorded.

## R3 — WS3 (first production adopter): design C adopted in full

- `signing/pin_store.py`: `PinStore`, single combined file
  `snapshot-pin.json` (pin + full history, one os.replace,
  loop.save() discipline), record serialisation
  (`ceremony_record_to_dict`/`from_dict` with payload
  re-derivation), verified load (every record via
  `verify_ceremony_record` + store consistency), CAS adopt
  under flock with non-regression guard, genesis only via a
  ceremony record, corrupt file refused never repaired.
- `trust/pin_adoption.py`: `PinAdopter`, `PinAdopterConfig`,
  `build_pin_adopter` (client ONLY via
  `production_client`; pins out-of-band; adopter env
  `AION_PIN_*` separate from the verifier allowlist),
  `snapshot_and_adopt()` flow exactly as C §3.3–3.5
  (consistent byte pair; gap candidates carry
  `prev_snapshot_hash=""`; classify → advance / ceremony /
  refuse-persist-nothing; evidence bundle
  `pin-evidence-<ceremony_id>` authored and placed by the
  adopter, hash from its own bytes), pending-adoption
  journal `adoption-pending.jsonl`, `PinAdoptionRefused` /
  `PinAdoptionBurned` (returned pair attached),
  `adopt_returned(...)` recovery entry point, and the loop
  driver `run_one_cycle_and_pin(...)`. `core/loop.py`
  untouched.
- WS1 integration (lands this cycle, so build the branch):
  `_reanchor`'s reason is computed — when the pending
  journal shows an unadopted burn for the SAME candidate
  (same seq+hash) and the same old pin, the recovery
  ceremony uses `burned_unadopted` (with-pin: pass the
  strict reasons; no-pin: none); otherwise the honest
  primary reason (`chain_gap_recovery` / `initial_anchor`).
  No `lost_pin` is ever selected for an unmoved pin.
- Scope honesty (C §4/§5): deliverable is production code
  exercised end-to-end in temp dirs against the real
  verifier subprocess; NO live run against state/state.json;
  F1 closure wording is "first production adopter built and
  wired as specified". The `ledger-head-anchoring` backlog
  item is NOT completed by this workstream; the record must
  say the pin-adoption blocker in front of recording cycles
  past 13 is removed, and live recording additionally needs
  a runner switch + verifier provisioning (deployment).
- Tests: C §8.1 (11 store tests incl. crash points) and
  §8.2 (8 integration cases) as specified; the integration
  harness may construct the adopter around a direct
  `VerifierClient` in research mode (R12 pattern) with the
  module docstring stating so honestly, per C §8.2's note.

## R4 — Cross-cutting

- Full suite must be green at the end
  (`python3 -m unittest discover -s tests`); baseline is
  1472 OK (skipped=28) at aeb6ef6.
- Docstring sweeps: every place naming `lost_pin` as the
  burned-recovery route is corrected (A §6.1.7); every
  "mirror"/commit-order passage in trust/ledger.py,
  trust/verifier_main.py, signing/pin_ceremony.py,
  trust/client.py reconciled to R2's order; cycle-21 crash
  contract guarantees (committed before return; burned
  stays burned; never retry) survive verbatim in substance.
- DECISION-CONSUMPTION-HEAD.md gains a dated cycle-22
  addendum (do not rewrite history): consumption journal
  anchored; follow-up narrowed to the issuance journal.
- Records: BUILD-CYCLE-22.md, REVIEW-CYCLE-22.md, brief
  CROSS-CHECK-BRIEF-CYCLE-22.md (blind; asks the seats
  whether item (3) is now closed WITHOUT the provisional
  scoping, and whether cycles 14–16 may proceed to
  re-review). Verdict PROVISIONAL until the parent seats
  the externals. Cycles 14–16 are NOT re-reviewed here.
- eval/ and Part A/Item A untouched. No GitHub push.
