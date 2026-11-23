# Decision — Consumption head store location: VERIFIER-OWNED
Date: 2026-11-23. Decided by the AION war room (3 coder seats
designing together + cross-critique, coordinator rulings in
internal/cycle21-work/DESIGN-FINAL.md R1), under the standing
rule recorded in DECISION-PROTECTED-GATE-EXTENSION.md
(2026-11-23): design and store-location decisions are made
by the war room and recorded; Dilip is informed of outcomes
in the normal updates, not asked mid-build.

## The decision

The protected monotonic consumption head for the pin
ceremony lives in the VERIFIER's store: a new hash-chained
journal `ceremony-consumptions.json` (class
`CeremonyConsumptionLedger`) under the existing
`AION_VERIFIER_HOME`, written only by a new verifier mode
`ceremony_consume`. Consumption is checked and recorded by
the verifier process at the moment of the ceremony;
caller-supplied `ceremony_history` stops being authoritative
(it remains a required audit/consistency input that can only
refuse, never grant). No new environment variable is
introduced; the deploy wrapper allowlist is unchanged.

## Why this location

- It is the only protected store that already exists. The
  verifier process is the system's established trust
  boundary (separate OS user in production deployment,
  env-only config, its own ledgers); the ceremony process is
  precisely the caller whose supplied state the external
  seats refused to trust (CROSS-CHECK-9/10/14).
- It reuses proven machinery unchanged in kind: the
  HashChainJournal discipline (flock, fsync, atomic replace,
  freshness-under-lock), the issuance journal's
  commit-point pattern, and the signing ledger's anchored
  mirror — so the consumption fact gains an anchored trace
  in production without a journal-format migration.
- It closes the blocking defect as an integrated-system
  property, under production wiring and against an intact
  verifier home: single-use and pin non-regression no longer
  depend on any history the caller supplies, which is the
  exact form of seat-gpt's FIX 0.96 (CROSS-CHECK-14 item
  (3)) and seat-gemini's binding condition on cycles 14–16.
  (Qualifier, made part of this sentence's claim at
  rev-r6's re-review condition and not left to the
  "Accepted residuals" section alone: the consumption
  journal is not externally anchored, so a verifier-home
  rollback can lower the enforced head for never-consumed
  envelopes until ceremony-journal-anchoring lands.)

## Alternatives weighed and rejected (on record in the designs)

- Caller-side consumption store (any form, incl. a MACed
  caller file): it is the defect itself — state the caller
  can roll back cannot refuse the caller.
- A second entry kind in the issuance (ceremony
  authorisation) journal: conflates two commit points and
  forces an exact-key-set format migration on a live
  journal.
- The signing ledger as the primary store: its fixed entry
  shape cannot carry the candidate head; it serves as the
  anchored MIRROR instead.
- A new env-configured directory: pure cost (a fifteenth/
  eighteenth allowlist name in five copies) for no
  additional protection over the verifier home.
- A separate OS user / separate service for consumption:
  a deployment change disproportionate to this cycle;
  deferred to the anchoring follow-up's judgement.
- Anchoring the consumption journal as its own anchor kind
  this cycle: needs a new anchor kind + env var + migration;
  deferred, jointly with the issuance journal, to the
  follow-up `ceremony-journal-anchoring` (extended by this
  decision to cover both journals).

## Accepted residuals (stated, not buried)

- The consumption journal is not externally anchored this
  cycle. A rollback of the verifier home cannot resurrect a
  consumed envelope whose consumption reached the anchored
  signing-ledger mirror (production), but can lower the
  enforced head for never-consumed envelopes.
- The head is a ceremony head, not a pin head: advance_pin
  movements never pass through the verifier. The old-pin
  not-behind rule narrows the fresh-envelope regression
  class; full closure belongs to a future loop/storage
  pin-store compare-and-swap.
- The guarantee is a property of the integrated system
  under its production wiring (authorise via the client,
  re-anchor with the verifier-backed consumer, adopt the
  returned pin atomically) — not of the reanchor_pin library
  function for an arbitrary caller-supplied callable.
- Recovery from a burned-but-unmoved consumption is a new
  ceremony ahead of the head; a consumed target is never
  re-anchorable.

## Consequences

- Cycle 21 implements this decision (BUILD-CYCLE-21.md).
- Cycles 14–16 remain HELD; their re-review is the next
  step after cycle 21 reconciles with the external seats,
  and this head is the precondition those cycles were held
  on.
