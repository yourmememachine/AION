# Cross-check brief — Trust Boundary v2 (blind external review)

You are an external reviewer seat for the AION project's trust
boundary. Review the code in the repository (stdlib-only Python,
local) and return a verdict (SHIP or FIX) with a confidence
score and concrete findings. You are reviewing a FIX cycle: the
previous external review of the v1 trust boundary voted FIX,
with the core objection that the verifier was a "laundry
oracle" — it signed caller-asserted claims (an `approve`
decision and `reward_hacking_checked` flag chosen by the
caller), the store's `signed_only` mode was a non-persisted
construction-time flag with a live legacy bypass, ship had no
transaction discipline, sealed-eval queries were an unbounded
per-position score oracle, ledger rollback was undetectable
without a caller-supplied pin, and the verifier ran as the same
OS user as the builders. This cycle claims to close those
items. Verify the claims adversarially; do not take them on
trust, and do not soften a FIX into a pass.

## What v2 claims

1. **Claim/issuance split** (`trust/verifier_main.py`,
   `trust/protocol.py`, `trust/ledger.py`): the old `attest`
   mode is removed. `submit_claim` ledgers a claim unsigned and
   issues no signature. `issue_attestation` accepts a strict
   body (caller-supplied decision fields are a protocol error)
   and derives its decision from two ledgered sealed-eval
   records it verifies itself (MAC, signer, live-registry
   manifest, ledger presence, distinctness, ledger order,
   proposal scope).
2. **Evidence-bound gate accepts**: on the signed path, gate
   accepts require `eval_evidence`; caller sealed score maps
   are replaced by the records' scores and both record hashes
   are bound into the signed inputs hash.
3. **Persistent `signed_only`** (`memory/store.py`): the
   security mode is persisted in store metadata; plain opens of
   a signed store refuse; downgrade only via an audited,
   hash-chained migration; signed commits additionally require
   a one-shot permit minted by the verified `commit_signed`
   path. The legacy unsigned reuse measurement is behind an
   explicit test-only flag with no production callers, watched
   by a call-graph lint.
4. **Ship transactions** (`trust/shiptx.py`,
   `trust/shipcheck.py`): a durable journal with states
   PREPARED → AUTHORISATION_VERIFIED → BURN_PENDING →
   CYCLE_RECORDED → POST_RECORD_VERIFIED → COMMITTED (+
   ABORTED_SPENT / REFUSED_PRE_BURN / ANOMALY), a transaction
   id derived from (decision, manifest), one-in-flight per
   item, and recovery that settles to one consistent outcome,
   never replays a consumed decision, and never journals a
   verification step it did not itself perform.
5. **In-verifier query budgets** (`trust/budgets.py`): caps
   per proposal (25) and per identity (500); replay refusal;
   near-duplicate/adaptive-query detection scoped per identity
   (not per caller-chosen label), including an absolute
   differing-position rule for small sets; enforced inside the
   verifier before the registry opens.
6. **One canonical path policy** (`trust/pathpolicy.py`,
   `path-policy/1`): consumed by the manifest and the verifier.
   Note: the gate's own protected-path code lives in a
   protected file and has not adopted it; judge whether the
   remaining divergence is honestly recorded.
7. **Anchoring** (`trust/anchoring.py`): external monotonic
   head anchors for the signing ledger, the ship ledger, and
   the budget store; startup refusal when an established ledger
   or its anchor is missing; first initialisation only through
   an explicit ceremony; re-anchoring is audited.
8. **Separate OS identity** (`deploy/verifier-identity/`): a
   dedicated `aion-verifier` user, verifier-owned key/ledger/
   anchor/registry dirs (0700), and a wrapper that drops
   privileges. The live verifier on the dev VM is deliberately
   unprovisioned (operator ceremony documented); judge the
   machinery and the honesty of that state, not a live service.

## Acceptance demonstrations to reproduce or refute

- A builder submits a fabricated approval claim → no approval
  signature exists anywhere (check the signing ledger).
- A signed store opened with a plain constructor → refusal;
  a hand-built unsigned gate decision presented to the store's
  gated commit → refusal.
- Adaptive sealed-eval probing (label rotation, one-position
  refinements, small sets) → the budget stops extraction;
  state the bound you believe actually holds.
- The signing ledger (or budget store) deleted or rolled back
  → verifier startup refuses.
- A ship crashed at every transaction transition → recovery
  reaches exactly one consistent outcome and a consumed
  decision is never shippable again; try to make recovery
  misattribute another ship's cycle or fabricate a verification.
- Builder-side code (or an unprivileged user) tries to read the
  verifier's key → the OS denies it.

## Declared limits (judge whether they are honest and complete)

Same-user HMAC is still the cryptographic basis where the
separate-OS-user deployment is not provisioned; public and
capability score maps at the gate remain caller-asserted
trusted inputs (claimed unable to create an accept alone);
the store mode's unkeyed digest can be defeated by a whole-file
rewrite by the file's owner; anchoring is configuration-gated;
the ship-transaction ↔ loop-record join is by value because
the loop's history format is protected. If you find a limit
that is NOT declared, or a claim the code does not support,
that is a finding.

Return: verdict (SHIP/FIX), confidence, findings ordered by
severity with file references, and the extraction bound you
measured for item 5.
