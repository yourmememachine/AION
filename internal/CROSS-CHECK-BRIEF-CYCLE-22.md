# Blind review brief — Cycle 22: honest recovery reason, consumption-journal anchoring, first production pin adopter

For external seats seat-gpt / seat-gemini. No internal
verdicts or scores are included in this brief.

## The two questions

1. Item (3) — consumption integrity. In CROSS-CHECK-15,
   seat-gpt provisionally closed item (3) in a scoped form;
   seat-gemini held it OPEN (FIX 0.88) on three grounds:
   (a) the F4 deferral — burned-but-unmoved recovery forced
   the false `lost_pin` label; (b) closure claimed for an
   "integrated system" with zero production callers;
   (c) a new defect — commit-then-mirror ordering left a
   burn erasable by a verifier-home rollback, resurrecting
   a still-valid envelope. **Is item (3) now closed WITHOUT
   the provisional scoping?**
2. **May cycles 14–16 now proceed to re-review** for ship?
   (They were not re-reviewed or shipped in this cycle.)

## Headline claims — with their qualifiers, in substance

- F4 is built, not deferred: recovery from a burned-but-
  unadopted consumption uses a dedicated reason,
  `burned_unadopted`, validated against the RECORDED BURN
  in the verifier's consumption journal — never against a
  caller assertion. The original consumption stays
  permanently burned; recovery is a new ceremony with a
  new ceremony_id and new evidence; there is no alternate
  consumption or adoption path. Recovery is ONE-SHOT per
  burned movement (see the ruling below — we ask you to
  ratify it, as it supersedes two positions in the cycle-22
  design record).
- The mirror gap is closed by anchoring the consumption
  journal itself, with one disclosed residual: a burn whose
  anchor update COMPLETED survives a verifier-home rollback
  (detected at startup, `anchor_refused`). A full rollback
  executed inside the append→anchor-update window (burn in
  the journal, anchor still at the pre-burn prefix) is NOT
  protected — the same window every anchored append in this
  system carries. Research mode, or the anchor
  unconfigured, carries no rollback claim at all.
- The first production adopter is BUILT AND WIRED AS
  SPECIFIED — production code (`trust/pin_adoption.py`,
  `signing/pin_store.py`) exercising authorise → verifier-
  backed consume → atomic adoption against a real pin
  store, end-to-end in tests against the real verifier
  subprocess. It has NOT been run live against the repo's
  `state/state.json`, and nothing in the loop calls it yet;
  `core/loop.py` is untouched. The claim is "first
  production adopter built and wired as specified" — no
  stronger claim is made, and the long-standing
  `ledger-head-anchoring` item is NOT completed by this
  cycle.

## Workstream 1 — F4: the `burned_unadopted` recovery reason

- `burned_unadopted` is a pin-OPTIONAL reason in the shared
  reason grammar (mirrored in `signing/pin_ceremony.py` and
  `signing/ceremony_authorisation.py`, drift-tested): it
  joins neither the must-carry-a-pin nor the must-not-carry-
  a-pin set; a ternary coherence rule is enforced at the
  payload projection, authorise cheap validation,
  `reanchor_pin`, and `verify_ceremony_record`. Issuance-
  side validation is unchanged in strictness.
- Burn identification is implicit and head-only:
  `CeremonyConsumptionLedger.match_head_burn` returns the
  head journal entry iff the candidate target AND the old
  pin exactly equal the head entry's recorded new/old pair
  (no-pin encoded as seq=None / hash="").
- Authorise (verifier mode): after anti-replay, a
  `burned_unadopted` request must pass the burn predicate
  against the verifier's freshly loaded consumption
  journal; failure is a single new exit-3 code,
  `ceremony_recovery_unproven`; an unreadable consumption
  journal surfaces as `ledger_failed`. Consume: the head
  rules gain a single scoped exception — the candidate-at-
  head and old-pin-behind-head refusals lift ONLY for
  `burned_unadopted` when the predicate matches; the
  generic old-pin rule is REPLACED by exact equality there,
  not waived. `append_consumption` is unchanged.
- With-pin `burned_unadopted` in `reanchor_pin` requires
  the strict `("chain_gap",)` recomputation, like any
  with-pin recovery.
- The primary burned-but-unmoved path needs no new
  ceremony at all: the adopter's `adopt_returned(...)`
  completes adoption from the returned (record, envelope)
  pair with no new consumption. A new ceremony is needed
  only when the returned pair was discarded.
- Claim wording, in substance: the label is proven at
  authorise and re-proven at consume against the
  verifier's own consumption journal, under an intact
  verifier home (and, where configured, the consumption
  anchor). The verifier cannot observe pin adoption; that
  a recovered target was in fact unadopted is guaranteed
  only under the production wiring (the adopter computes
  the reason from its pending-adoption journal). Outside
  that wiring the worst case is a redundant, fully
  journaled re-consumption of the IDENTICAL target — never
  a different, forked, or backwards movement.
  `verify_ceremony_record` (offline) proves issuance and
  shape only; it does not prove a burn existed, and its
  docstring says so.

### Ruling we ask you to ratify — recovery is one-shot

As first built this cycle, the exception was
self-perpetuating: a recovery consumption writes a journal
entry indistinguishable from the original burn (the strict
entry schema carries no reason field), so the head entry a
later recovery matches could itself be a recovery —
target-level single-use for the head target was waived
indefinitely. The internal war room ruled recovery
ONE-SHOT per burned movement: `match_head_burn` returns
None when any earlier journal entry carries the same
(old, new) pair as the head, binding both gates through
the shared predicate. This supersedes design-A §6.2
(iterated recovery chains) and §4.4.5's race outcome: both
race authorisations may be issued against the original
burn, the first consumption lands, the second is refused
`AlreadyConsumedError`. Accepted consequence: a recovery
that itself burns unadopted is terminal for that movement;
liveness resumes at the next snapshot sequence. Pinned by
unit tests and end-to-end through the real verifier
(second recovery authorise refuses with
`ceremony_recovery_unproven`; consumption count unchanged).

## Workstream 2 — closing the mirror gap

Design chosen internally (war room, recorded): anchor the
consumption journal — NOT mirror-first restructuring,
which would have inverted cycle 21's externally reviewed
authority choice and left the head authority's journal
incomplete via mirror-only burns; both options carry the
identical append→anchor crash window.

- `trust/anchoring.py`: ANCHOR_KINDS gains
  `"ceremony-consumption"` (no format change). New env
  `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` /
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`; wrapper
  allowlist 17 → 19 in every copy. The anchor path must be
  absolute, outside the verifier home, and distinct from
  the signing and budgets anchors. Production mode with
  the ceremony seed configured REQUIRES the path at
  startup and refuses INIT.
- Startup verifies the consumption journal against its
  anchor on every invocation: `anchor_missing` + INIT
  initialises (empty journal only); any other mismatch is
  `anchor_refused`.
- Consume commit order is now: (1) consumption-journal
  append (the commit point; the journal remains the head
  authority) → (2) consumption-anchor update → (3)
  signing-ledger mirror → (4) signing-anchor update. The
  anchor-before-mirror ordering is load-bearing: a mirror
  failure followed by a verifier-home rollback leaves the
  external anchor ahead of the rolled-back journal, and
  the replay is refused at startup.
- Mandatory adversarial test, in tree: commit a
  consumption, fail the mirror, roll back the verifier
  home, attempt replay — refused. The test was mutation-
  checked: reverting the commit order (anchor update after
  the mirror) makes it FAIL (the rolled-back replay
  succeeds); with the shipped order it passes. Character-
  isation tests also pin the disclosed residuals (in-window
  rollback replay succeeds; research-mode replay succeeds)
  as labelled characterisations, not as guarantees.
- Oracle note: the claim was NARROWED, not the codes
  collapsed. The no-forger-oracle claim covers
  verification-failure classes only (byte-identical stdout
  and stderr there); temporal, state, and infrastructure
  distinctions are state oracles BY DESIGN and are now
  documented as such at the consume mode and at
  `AlreadyConsumedError`.
- The ISSUANCE journal remains unanchored; the follow-up
  `ceremony-journal-anchoring` is narrowed to it alone,
  on the recorded reasoning that a resurrected issuance
  pair still yields only an envelope that must pass
  consumption, where single-use and the head live.

## Workstream 3 — first production adopter

- `signing/pin_store.py` — `PinStore`: one combined file
  `snapshot-pin.json` holding the pin AND the full ceremony
  history in a single document, written by one
  `os.replace` with the same write/fsync/replace/dir-fsync
  discipline as the loop's state save. Verified load:
  every record re-verified (`verify_ceremony_record`) plus
  payload re-derivation and store-consistency checks (no
  duplicate evidence, no forked targets, pin matches the
  history head). Adoption is a compare-and-swap under
  flock against the pin re-read under the lock, with a
  non-regression guard. A corrupt file is refused on read
  and on adopt — never repaired, quarantined, or
  bootstrapped over.
- Adoption binds the record to the store's actual state:
  `adopt()` verifies the record with
  expected_old_pin = the store's current pin and
  expected_new_pin = the record's target, and consistency-
  checks the PROSPECTIVE history before writing (a first
  build of this store skipped both; the internal war room
  demonstrated a cross-pin history splice and a self-
  bricking re-adoption against it — both are now refused
  and regression-tested). Genesis follows a SHAPE rule: a
  record may create the store only if its old side is
  absent (any no-pin reason, including a no-pin
  `burned_unadopted` — which can exist only if the verifier
  already proved and consumed the burn); any with-pin
  record at genesis is refused.
- `trust/pin_adoption.py` — `PinAdopter` /
  `build_pin_adopter`: the client is built ONLY via
  `trust.wiring.production_client`; adopter env
  (`AION_PIN_*`) is separate from the verifier allowlist.
  `snapshot_and_adopt()` classifies (advance / ceremony /
  refuse-and-persist-nothing), authors its own evidence
  bundle (hash from its own bytes), and calls
  `reanchor_pin` with the verifier-backed consumer. The
  ceremony reason is COMPUTED by the adopter: an unadopted
  burn for the same candidate and same old pin in its
  pending-adoption journal yields `burned_unadopted`;
  otherwise the primary reason; `lost_pin` is never
  selected for an unmoved pin. Consume-committed /
  adopt-failed surfaces as `PinAdoptionBurned` with the
  returned pair attached, and `adopt_returned(...)`
  completes it with no new consumption (test-pinned,
  including the discarded-pair variant recovering under
  `burned_unadopted` with a second consumption and no
  `lost_pin` anywhere).
- Disclosed implementation notes: the pending journal's
  `authorised` line retains the candidate envelope, and a
  small side file retains advance-path candidates — both
  are non-authoritative caches, fully re-verified on every
  use; they exist because a fresh signing can never
  reproduce a pinned snapshot hash (signed_at is in the
  payload), so the identical candidate must be re-presented
  for the burn predicate to match it. The end-to-end test
  harness builds the adopter around a directly constructed
  research-mode `VerifierClient` (the established in-repo
  pattern) because `production_client` requires production
  mode plus anchors; `build_pin_adopter` itself is
  exercised separately, including its refusals.

## What was NOT done

- Cycles 14–16: not re-reviewed, not shipped; loop state
  not advanced.
- No live run of the adopter against `state/state.json`;
  no caller in `core/loop.py` (a driver,
  `run_one_cycle_and_pin(...)`, is provided in
  `trust/pin_adoption.py`).
- Issuance-journal anchoring (narrowed follow-up);
  `ledger-head-anchoring` (the adopter removes the
  pin-adoption blocker in front of it; the item itself is
  not completed); deployment is not provisioned on this
  machine (deployment-gated tests skip by design).

## Liveness figures (unchanged from cycle 21)

Envelope TTL hard-capped at 900 s; every ceremony needs
two verifier-availability windows inside that life (one to
authorise, one to consume). A failed or lost consume burns
the issuance pair; the client never retries a consume
automatically.
