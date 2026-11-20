# Build cycle 9 — Trust Boundary v2 (fix cycle)

Item: `signer-recompute-from-raw-inputs` (leverage 7.5), the
top pending backlog item, folded together with the v2 mandate
from cross-check #3 (`internal/CROSS-CHECK-3.md`): both external
seats (ChatGPT 0.68, Gemini 0.58) voted FIX on cycle 8, converging
with the preserved internal dissent. No new capability work —
this cycle closes the eight mandate items, in mandate order.
Coders: 15 (5 pods of 3). War room: 6 internal seats, blind
scores locked in the calibration log (subject `cycle-9-build`)
before discussion; verdict reconciled SHIP after three fix
rounds and per-seat verification re-probes (see
`REVIEW-CYCLE-9.md`). Full suite: **602 → 820 tests, all
passing.** Overall verdict remains **PROVISIONAL** until the
external seats re-review (brief:
`internal/CROSS-CHECK-BRIEF-CYCLE-V2.md`).

## What was built, by mandate item

1. **Evidence-derived attestation.** The verifier's `attest`
   mode is gone. `submit_claim` ledgers a claim UNSIGNED
   (`kind="claim"`, never accepted, no key use) and returns only
   a claim id/hash. `issue_attestation` takes a strict body with
   no caller decision fields (smuggled `approve` /
   `reward_hacking_checked` / `decision` keys are a protocol
   error) and DERIVES the attestation verifier-side from two
   ledgered sealed-eval records: sealed scores from the records,
   the factory gap check run by the verifier itself, decision
   computed, `evidence_ref` bound to both record hashes.
2. **Verifier-produced evidence at the gate.** Gate accepts on
   the signed path require `eval_evidence`; caller sealed maps
   are replaced by the records' scores, both record payload
   hashes are bound into `gate_inputs_hash`, and an accept
   without evidence is refused (`evidence_required`).
   Fix round: evidence records must be DISTINCT and
   ledger-ordered (baseline seq < candidate seq) at both
   issuance and gate, and are bound to the proposal's budget
   scope (MAC-bound `scope` in the eval payload); the gate also
   checks scope roots directly.
3. **Persistent signed_only + legacy quarantine.** The store
   persists `security_mode` in its own metadata; a plain open of
   a signed-persisted store refuses on every open path;
   downgrade only via `migrate_security_mode` (audited,
   hash-chained journal written before the flip; the journal is
   verified on open when present and its final mode must match
   the file). `run_reuse_measurement` requires an explicit
   `legacy_test_mode=True` flag, defaults to refusal, and has
   zero production callers; the call-graph lint now watches it
   and `migrate_security_mode`. Fix round: `_commit_gated` on a
   signed store requires a one-shot permit minted by
   `commit_signed` only after envelope MAC + attestation
   verification (binds content hash + store instance, single
   use) — the war room's hand-built-decision probe now refuses.
4. **Ship transaction state machine.** `trust/shiptx.py`:
   durable hash-chained journal (`ship-tx.json` beside the ship
   ledger), states PREPARED → AUTHORISATION_VERIFIED →
   BURN_PENDING → CYCLE_RECORDED → POST_RECORD_VERIFIED →
   COMMITTED plus terminals ABORTED_SPENT / REFUSED_PRE_BURN /
   ANOMALY; `tx_id = sha256(canonical {decision_id,
   manifest_hash})`; `begin` idempotent and one-in-flight per
   item. `recover_ship_tx` settles from ledger + loop evidence,
   never burns, never runs a cycle. Fix rounds: recovery never
   journals AUTHORISATION_VERIFIED and journals
   POST_RECORD_VERIFIED only after re-verifying the manifest
   from a supplied root (or at the genuine POST_RECORD_VERIFIED
   crash window); ambiguous/contradictory evidence parks at
   ANOMALY; cycle-claim uniqueness enforced at transition,
   recovery attribution, and `ShipLedger.finalise`; the
   one-in-flight gate fires at whichever transition first binds
   an item; itemless CYCLE_RECORDED is refused.
5. **In-verifier evaluation confidentiality.** `trust/budgets.py`
   enforced inside the verifier before the registry opens:
   per-proposal cap 25, per-identity cap 500, byte-identical
   replay refused. Fix round: replay/similarity/probe detection
   is IDENTITY-scoped across proposal labels; probes also count
   on an absolute rule (≤2 differing positions regardless of
   fraction); two-phase check/record so garbage-length
   transcripts burn no budget; a tripping probe is persisted so
   the family latch materialises on disk.
6. **Unified canonical path policy.** `trust/pathpolicy.py`
   (`path-policy/1`) consumed by the manifest and by the
   verifier's gate-path canonicalisation; shipcheck consumes it
   transitively (manifest rebuild + signed decision).
   `eval/gate.py` is protected and has NOT adopted it — that
   remains for a Protected Gate Rule proposal to Dilip (see
   honest limits).
7. **Dual-ledger anchoring.** `trust/anchoring.py`: external
   monotonic head anchors for BOTH signing and ship ledgers;
   startup refusal when an established ledger's anchor is
   missing/mismatched; first-initialisation only via the INIT
   ceremony; `initialise_anchor` refuses non-empty journals
   without an explicit ceremony flag; `force_reanchor` persists
   a hash-chained audit record. Fix round: the query-budget
   store is anchored the same way (`AION_BUDGETS_ANCHOR_PATH`),
   including refusal on combined store+anchor deletion.
8. **Separate OS identity.** Performed on this VM, not faked:
   user `aion-verifier` (uid 997, nologin shell), verifier-owned
   0700 dirs `/var/lib/aion-verifier/{home,keys,anchors,
   registry}`, root-owned env template, wrapper
   `deploy/verifier-identity/run-verifier.sh` (allowlisted env,
   `runuser` drop). A real end-to-end sealed_eval through the
   wrapper returned a valid attestation ledgered in the
   verifier's own home; `nobody` is denied the key. The live
   verifier is deliberately NOT provisioned (no key, blank ids,
   no registry copy): a launch today refuses as misconfigured,
   fail-closed, and the 6-step operator ceremony is documented
   in `deploy/verifier-identity/README.md`.

## Honest limits (unchanged or consciously accepted)

- Same-user HMAC remains the cryptographic basis; item 8 is the
  deployment boundary, and the client does not yet route through
  the wrapper in production wiring (backlog:
  `production-signed-path-wiring`, still open).
- Public/capability score maps at the gate and the public side
  of the attestation gap check remain caller-asserted trusted
  inputs (no verifier-side source exists in this design;
  `eval/gate.py` declares the capability snapshot a trusted
  input). They cannot by themselves create an accept — sealed
  gain, a derived attestation and a MAC are still required —
  and the docstrings say exactly this.
- The persisted store mode is protected by an unkeyed digest:
  whole-file rewrite + recompute (including stripping
  `security_mode` to the legacy digest), migration-journal
  deletion, and store-file deletion remain possible for the
  file's owner. All four are documented as accepted residuals
  in `memory/store.py`; retiring the legacy digest is backlogged.
- Anchoring is opt-in by configuration on the ship path and
  verifier startup; joint rollback of journal + anchor to
  genesis is undetectable; the ship-tx journal and (pre-fix)
  budget store were unanchored — budgets are now anchored when
  configured, the tx journal remains backlogged.
- The tx↔loop join is by value on (cycle_id, item_id) —
  `core/loop.py` is protected and its history cannot carry the
  tx_id; the docs state this rather than claiming a shared id
  inside loop state.
- `issue_attestation` issues manifest-unbound envelopes, so a
  ship attestation bound to a build manifest cannot yet be
  issued through it (backlogged: ship-variant issuance).
- Reviewer independence is still asserted from roster
  construction, not measured (backlog:
  `reviewer-independence-measurement`).
