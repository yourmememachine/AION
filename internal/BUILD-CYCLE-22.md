# Build record — Cycle 22: honest recovery reason, consumption-journal anchoring, first production pin adopter

Date: 2026-11-23. Mandate: CROSS-CHECK-15 — close the
last external gates on the ceremony line. Item (1)
Ed25519 was closed by both external seats in cycle 21.
Item (3) consumption integrity: seat-gpt provisionally
closed it in scoped form; seat-gemini FIX 0.88 held it
open on (a) the F4 deferral (burned-but-unmoved recovery
forced the false `lost_pin` label), (b) "integrated
system" closure with zero production callers, (c) the
commit-then-mirror resurrection defect. This cycle built
all three convergent workstreams. Cycle 19 Part A +
Item A are shipped and untouched; eval/ is untouched;
cycles 14–16 were NOT re-reviewed or shipped; loop state
was NOT advanced.

## Headline claims — with their qualifiers, in substance

F4 is built: `burned_unadopted` recovery is validated
against the recorded burn in the verifier's consumption
journal (authorise step 5b + consume-side predicate), the
original consumption stays permanently burned, recovery
is a new ceremony (new ceremony_id, new evidence), and
recovery is ONE-SHOT per burned movement (war-room fix-
round ruling, below). The mirror gap is closed by
anchoring the consumption journal: a burn whose anchor
update completed survives a verifier-home rollback
(detected at startup); a full rollback inside the
append→anchor-update window is NOT protected — the same
window every anchored append in this system carries;
research mode / anchor unconfigured carries no rollback
claim. The first production adopter is built and wired
as specified (production code, end-to-end in tests
against the real verifier subprocess); it has NOT run
live against `state/state.json`, nothing in the loop
calls it yet, and `ledger-head-anchoring` is NOT
completed by this cycle. Cycle 22 is PROVISIONAL pending
the external seats on CROSS-CHECK-BRIEF-CYCLE-22.md.

Liveness figures, in numeric form (unchanged): envelope
TTL hard-capped at 900 s; two verifier-availability
windows per ceremony (authorise, consume); a failed or
lost consume burns the issuance pair; no automatic
consume retry.

## Design process

3 coder seats designed together (design-a/b/c in
internal/cycle22-work/) with cross-critiques; coordinator
rulings R1–R4 in internal/cycle22-work/DESIGN-FINAL.md
are the build contract. Build in disjoint file ownership
(3 seats). War room: 6 reviewer seats, blind scores
locked in state/calibration/calibration.json (subject
`cycle-22-review`) before reconciliation, one forced-
dissent seat (rev-r6). First round split (2 SHIP / 4 FIX)
→ fix round (3 seats + 2 coordinator-ruled amendments) →
re-review (subject `cycle-22-rereview`) reconciled
unanimous SHIP. Detail: REVIEW-CYCLE-22.md.

## Workstream 1 — F4: `burned_unadopted` (R1 = design A)

- Reason grammar: `burned_unadopted` is pin-OPTIONAL —
  new mirrored `_EITHER_PIN_REASONS` in
  signing/pin_ceremony.py and
  signing/ceremony_authorisation.py (drift-tested);
  `_NO_PIN_REASONS` unchanged; ternary coherence enforced
  at the payload projection, authorise cheap validation,
  `reanchor_pin`, and `verify_ceremony_record`.
- Burn proof: `CeremonyConsumptionLedger.match_head_burn`
  (trust/ledger.py) — head-only, exact candidate-target +
  old-pin equality. Authorise gains step (5b) after
  anti-replay, before signing, for `burned_unadopted`
  only: predicate failure → new exit-3 code
  `ceremony_recovery_unproven`; unreadable consumption
  journal → `ledger_failed`. Consume: `check_head`'s
  scoped exception lifts the candidate-at-head /
  old-pin-behind-head refusals ONLY when the reason is
  `burned_unadopted` AND the predicate matches (the
  generic old-pin rule is replaced by exact equality
  there); `append_consumption` unchanged.
- With-pin `burned_unadopted` requires the strict
  ("chain_gap",) recomputation in `reanchor_pin`.
- `verify_ceremony_record` states its limit: offline
  record verification proves issuance and shape, not that
  a burn existed.
- Tests: tests/test_signing_ceremony_recovery.py (31,
  incl. the fix-round OneShotRecoveryTests) + 6 verifier
  end-to-end recovery tests in
  tests/test_trust_ceremony_consumption.py.

## Workstream 2 — consumption-journal anchoring (R2)

War-room design choice: anchor the consumption journal
(option (a)). The mirror-first restructuring (option (c))
was NOT taken — it inverts cycle 21's externally reviewed
authority choice and leaves the head authority's journal
incomplete via mirror-only burns; both options carry the
identical append→anchor crash window. Recorded in
DESIGN-FINAL R2 and the dated addendum to
internal/DECISION-CONSUMPTION-HEAD.md.

- trust/anchoring.py: ANCHOR_KINDS gains
  "ceremony-consumption" (no format change). New env
  AION_CEREMONY_CONSUMPTION_ANCHOR_PATH / _INIT — absolute,
  outside the verifier home, distinct from the signing and
  budgets anchors; wrapper allowlist 17 → 19 in ALL copies
  (run-verifier.sh, health_check.py, wiring.py, setup.sh,
  verifier_main header, wiring/deploy tests).
- Startup (per-request, in _load_config): the consumption
  journal anchor is verified before any mode runs;
  production + ceremony seed configured ⇒ path required,
  INIT refused; ("anchor_missing",) + INIT ⇒
  initialise_anchor (empty journal only); other mismatches
  ⇒ anchor_refused.
- Consume commit order: (1) consumption-journal append →
  (2) NEW consumption-anchor update → (3) signing-ledger
  mirror → (4) signing-anchor update. Anchor BEFORE mirror
  is load-bearing: mirror failure + home rollback leaves
  the anchor ahead of the rolled-back journal ⇒ refused at
  startup. Cycle-21 mirror-failure semantics otherwise
  unchanged.
- Mandatory adversarial test (tests/
  test_trust_ceremony_journal_anchor.py, 10 tests): commit
  consumption → fail the mirror → roll back the verifier
  home → replay REFUSED. MUTATION CHECK PERFORMED: with
  the commit order temporarily reverted (anchor update
  after the mirror), the mandatory test FAILED as required
  (the rolled-back replay succeeded); order restored and
  re-verified by reading the code, and independently
  re-run by war-room seat rev-r2 in a scratch copy with
  the same result.
- Oracle: the claim was NARROWED, not the codes collapsed
  (design B §7.2): the no-forger-oracle claim covers
  verification-failure classes only; temporal/state/
  infrastructure distinctions are state oracles by design,
  documented at the consume mode and at
  AlreadyConsumedError (trust/ledger.py).
- Issuance journal NOT anchored; follow-up
  `ceremony-journal-anchoring` narrowed to it.

## Workstream 3 — first production adopter (R3 = design C)

- signing/pin_store.py — PinStore over one combined
  snapshot-pin.json (pin + full history, one os.replace,
  loop.save()'s write/fsync/replace/dir-fsync discipline);
  strict record serialisation with payload re-derivation;
  verified load (every record via verify_ceremony_record
  + consistency: no duplicate evidence, no forked targets,
  pin matches history head); CAS adopt under flock with
  non-regression guard; corrupt file refused, never
  repaired/quarantined/bootstrapped over; caps 1 MiB /
  1000 records.
- trust/pin_adoption.py — PinAdopter, build_pin_adopter
  (client ONLY via trust.wiring.production_client;
  AION_PIN_* adopter env separate from the verifier
  allowlist), snapshot_and_adopt() (consistent byte pair;
  classify → advance / ceremony / refuse-and-persist-
  nothing), evidence bundle authored by the adopter (hash
  from its own bytes), pending-adoption journal,
  PinAdoptionRefused / PinAdoptionBurned (returned pair
  attached), adopt_returned(...), and the loop driver
  run_one_cycle_and_pin(...). core/loop.py NOT edited.
  Reason is COMPUTED: an unadopted burn for the same
  candidate + same old pin in the pending journal ⇒
  burned_unadopted; otherwise the primary reason;
  lost_pin is never selected for an unmoved pin.
- Tests: tests/test_signing_pin_store.py (18),
  tests/test_trust_pin_adoption.py (9) — incl. the
  mandatory consume-committed/adopt-failed →
  adopt_returned case (no new consumption) and the
  discarded-pair variant (fresh ceremony under
  burned_unadopted, second consumption, no lost_pin).
- Disclosed deviations from design C (war-room judged
  safe): the pending journal's `authorised` line retains
  the candidate envelope, and advance-path candidates are
  retained in a snapshot-candidate.json side file — both
  non-authoritative caches, fully re-verified on every
  use; they exist because a fresh signing can never
  reproduce a pinned snapshot hash (signed_at is in the
  payload). One test asserts byte-identical journal
  before/after a refused attempt instead of an absent
  journal (the fixture's genesis ceremony legitimately
  created the journal first).

## Fix round (war room → re-review)

- rev-r3 MAJOR ×2 (pin store): adopt() verified records
  with NO pin context (a record minted against a seq-3
  pin adopted cleanly onto a seq-1 pin — a silent history
  splice) and never consistency-checked the document it
  wrote (re-adopting the head record bricked the store).
  Fixed: expected_old_pin / expected_new_pin binding +
  prospective _check_consistency before serialising +
  already-ceremonied-target refusal; regression tests
  12–14, mutation-checked by the fix seat.
- Coordinator ruling (genesis): the fix's first genesis
  guard whitelisted reasons (initial_anchor / lost_pin),
  which dead-ends genesis recovery (a no-pin
  burned_unadopted record IS the recovery for a genesis
  burn whose adoption failed before the file existed).
  Replaced with a SHAPE rule: genesis admits any record
  whose old side is absent; any with-pin record is
  refused. Upheld on re-review by rev-r3 with independent
  probes (test_15 added).
- rev-r6 HIGH (one-shot): the recovery exception was
  self-perpetuating — a recovery consumption is
  indistinguishable from the original burn, so the head
  match could itself be a recovery. Fixed in
  match_head_burn (no match when an earlier entry carries
  the same (old, new) pair), binding authorise and
  consume through the shared predicate. SUPERSESSION,
  stated explicitly: this overrules DESIGN-FINAL R1's
  iterated-chain position (design-A §6.2) and §4.4.5's
  both-recoveries-land race outcome. Under one-shot both
  race authorisations may issue against the original burn;
  the first consumption lands; the second refuses
  AlreadyConsumedError. A recovery that itself burns
  unadopted is terminal for that movement. Recorded in
  DECISION-CONSUMPTION-HEAD.md Addendum 2 and put to the
  external seats in the brief as a ruling to ratify.
  tests/test_trust_ceremony_consumption.py's chain test
  was re-pinned to one-shot semantics (second recovery
  authorise refuses ceremony_recovery_unproven).
- Wording sweep (rev-r2 / rev-r5): the R4 docstring sweep
  had missed live passages — the CeremonyConsumptionLedger
  R10 paragraph ("NOT externally anchored… covers both
  journals"), pin_ceremony's residual summary, the deploy
  README's "no new configuration is needed" and "never
  re-anchorable" claims, ledger.py's "the one journal that
  is externally anchored", verifier_main's unqualified
  "ceremony journal". All rewritten to the cycle-22 state
  with the anchor/window/research qualifiers; design-A §8
  claim wording now carried in full in pin_ceremony.
- Adopter nits (rev-r4): _retained_candidate payload-hash
  check; already_current TTL bound documented; post-adopt
  journal appends guarded (documented swallow; journal is
  a detection aid). test_05b artefact count now exact
  (rev-r6 F5).
- Coordinator mechanical fixes (pre-review): the first
  full-suite run of the cycle failed exactly 2 tests —
  the trust-boundary call-site lint (the adopter's
  run_one_cycle call is now a counted ALLOWLIST exception
  in tests/test_trust_lint.py) and the deploy allowlist
  count (17 → 19 in tests/test_verifier_deploy.py). Both
  are the design-mandated count updates the build seats
  missed; no production behaviour involved.

## Test totals

Baseline at cycle start (aeb6ef6): 1472 OK (skipped=28).
Final full suite: **1547 tests OK (skipped=28)** —
`python3 -m unittest discover -s tests`, zero failures.
Skips are the documented deployment-gated set (deployment
not provisioned on this machine).

## Open after cycle 22

- External seats on CROSS-CHECK-BRIEF-CYCLE-22.md: is
  item (3) closed without the provisional scoping, and
  may cycles 14–16 proceed to re-review? (Not asked of
  the internal room; cycles 14–16 remain HELD.)
- Follow-ups: ceremony-journal-anchoring (issuance journal
  only); ledger-head-anchoring (adopter removes the
  pin-adoption blocker; item itself not completed);
  burned recovery liveness depends on the adopter's
  unanchored local pending journal (rev-r6 carried minor
  F4.2); offline verify_ceremony_record proves shape, not
  burn (F4.1, documented at the function).
- Deployment still not provisioned on this machine.
