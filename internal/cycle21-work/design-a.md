# DESIGN A — Cycle 21: Ed25519 differential validation + seed hygiene (lead) and the protected monotonic consumption head (position)

Seat A (design round; design only, no code in this round).
Scope: workstream A is mine to lead; workstream B is my position
as a full design, for the war room to rule on against the other
seats' designs.

Sources read in full: `internal/CROSS-CHECK-14.md` (the cycle-21
requirements), `internal/CROSS-CHECK-13.md`, `internal/BUILD-CYCLE-20.md`,
`internal/REVIEW-CYCLE-20.md`,
`internal/DECISION-PROTECTED-GATE-EXTENSION.md` (standing rule at
the end: design/store decisions are made by the war room and
recorded — the owner is NOT asked),
`signing/ed25519.py` (the production `verify`), `signing/ceremony_authorisation.py`
(`load_ceremony_seed`, `REFUSED_TEST_SEEDS`), `signing/pin_ceremony.py`
(`reanchor_pin`, `_check_ceremony_history`), `trust/ledger.py`
(`HashChainJournal`, `CeremonyAuthorisationLedger`, `SigningLedger.try_consume_eval_records`
— the closest in-repo precedent for atomic consumption),
`trust/verifier_main.py` (`_load_config`, `_mode_ceremony_authorise`,
`_update_anchor`, startup anchor verification), `trust/client.py`
(`ceremony_authorise`), `trust/anchoring.py`, `signing/gate_decision.py`
(`_check_key_path`, `load_signing_key`), `tests/test_signing_ed25519.py`,
`tests/test_signing_pin_ceremony.py` (Cycle20ConsumptionTests, T7/T8),
`internal/cycle20-work/design-c.md` and `design-a.md` §1 (route 4).

## 0. What cycle 21 must close, in one paragraph each

**Workstream A.** Gemini's blocking item (1) from CROSS-CHECK-14:
the in-house Ed25519 has only ever been validated against
itself (RFC 8032 vectors, a test-only affine oracle, 7
adversarial decode vectors added in the cycle-20 fix round).
An ECC implementation that agrees with its own oracle can
still share a misreading of the standard with that oracle.
The requirement is independent differential validation —
RFC 8032 / Wycheproof adversarial vectors plus
cross-implementation agreement against openssl — and seed
hygiene at verifier startup (file permissions fail-closed,
derivation-overlap checks against the snapshot HMAC key).

**Workstream B.** GPT's blocking FIX 0.96 (CROSS-CHECK-14
item 3): with a stale caller-supplied `ceremony_history`, a
consumed envelope can be replayed within its 900 s TTL and
REGRESS the pin. This is pinned executably by T7/T8 in
`tests/test_signing_pin_ceremony.py`, which assert the
regressed pin value. Two-of-three legs is not partial credit
on a single replay-resistance guarantee; the monotonic head
is a release gate, and it is also the precondition for the
cycles 14–16 re-review. The owner is not asked to decide
the store location (standing rule, DECISION-PROTECTED-GATE-
EXTENSION.md): the war room decides, and this design takes
a position.

---

# PART I — WORKSTREAM B: THE PROTECTED MONOTONIC CONSUMPTION HEAD

## D1. Store location — POSITION: verifier-owned consumption journal in the verifier home (route 4)

**Decision (my position): the consumption head lives in the
verifier process's own protected store — a new sibling
`HashChainJournal` in `AION_VERIFIER_HOME`, file
`ceremony-consumptions.json`, owned by a new class
`CeremonyConsumptionLedger` in `trust/ledger.py`, consulted
and written by a new verifier mode `ceremony_consume`.**
Caller-supplied history stops being authoritative for
single-use. This is route 4 (verifier-delegated consumption),
the recorded runner-up from cycle 20 (BUILD-CYCLE-20.md,
DESIGN-FINAL R1/R11) and the recommended form in the
CROSS-CHECK-14 reconciliation.

Why this location, positively:

1. It is the only existing protected store. `AION_VERIFIER_HOME`
   is already the home of the ceremony issuance journal, the
   signing ledger, the ship ledger and the retained-evidence
   store, and deployment already runs the verifier as a
   dedicated OS user (deploy/verifier-identity/). No new
   trust domain is created, no new env var is needed (the
   journal lives under the existing home), and no wrapper
   allowlist changes (cycle 20 bumped it 15 → 17 across five
   copies for two new env vars; this design adds zero).
2. It is the only location the ceremony caller cannot write.
   The whole defect is that the consumption record is in the
   caller's hand. Any store the caller process can open,
   truncate, or roll back is the same defect in a new file.
3. It reuses the proven mechanism. `HashChainJournal` already
   gives: hash-chained append-only entries, exact-key-set load
   validation, `_save`'s under-flock freshness check, and the
   bounded reload-and-retry pattern `ShipLedger.burn` /
   `SigningLedger.try_consume_eval_records` use to make
   check-and-append safe under concurrency. Cycle 20's
   issuance race was fixed by exactly this composition
   (post-reload duplicate re-check + `_save` freshness);
   the consumption ledger copies that fix, it does not
   re-invent it.
4. It makes consumption *verifier-side* verifiable: the
   verifier that minted the envelope is the process that
   checks signature, expiry, and issuance presence before
   it burns consumption (D5). No other location gets all
   three checks from the minting authority.

### Alternatives weighed and rejected

| Alternative | Why rejected |
|---|---|
| **A. Caller-side pin store / future loop-storage layer** (the loop keeps the head next to the pin) | Same hand as the defect. A caller that can restage `old_pin` can restage, truncate, or simply not consult its own head; a rolled-back loop state rolls the head back with it. Cycle-20 design-c §2 already rejected a `live_pin()` callback on the same ground ("the restaged argument wearing a function costume"). This design rejects the whole family: any head the consuming process owns is not a head, it is a note to itself. |
| **B. A second kind in `CeremonyAuthorisationLedger`** (consume entries alongside `authorise` entries, same file) | Conflates two commit points with different failure semantics. Issuance burns on *mint*; consumption burns on *use*; a file that holds both makes the issuance anti-replay scan read consumption entries, makes rollback analysis ambiguous (which entries may a restore legitimately drop?), and couples the two journals' size caps and anchor stories. The precedent is the other direction: cycle 19 split the ceremony journal out of `SigningLedger` for exactly this reason (entry shape / format migration). |
| **C. Columns in `SigningLedger`** | Format migration: `EXTRA_KEYS` is exact-key-set at load; widening it breaks every historical entry. And a consumption entry is not a signature — the signing ledger's core inference ("a signature with no ledger entry is evidence of a second signer") is about minting, not use. |
| **D. A standalone file the caller owns, MACed by the snapshot key** | The MAC key is held in-process by the ceremony caller (signing key), so the caller can forge its own consumption entries — the cycle-19 HMAC failure, repeated. An Ed25519 signature by the verifier over the head would make entries unforgeable but still deletable/rollable-back by the caller, and adds a second signer role for no gain over route 4. |
| **E. The retained-evidence store as the head** (presence of a retained file = consumed) | Retention is explicitly not a consumption input (cycle 20, stated in three docstrings) and is written *before* the issuance commit; reusing it as consumption state would invert its lifecycle and couple a pre-commit artefact to a post-consumption fact. Also a file-per-consumption with no chain gives no monotonic head, only a set. |
| **F. An external / off-machine store (new env var, new service)** | Stronger in principle (survives verifier-home compromise), but it is a new deployment dependency, a new env var + wrapper allowlist churn, a new availability failure mode, and — decisively — no such store exists in this system today. The threat model that matters for T7/T8 is the *caller* (buggy, rolled-back, or hostile), not the verifier-home operator; route 4 defeats the caller completely. Off-machine anchoring of the *journal head* is the right follow-up (D7), not a new primary store. |

**Residual of the chosen location, stated plainly:** the
head is only as protected as the verifier home. A writer
who can rewrite `AION_VERIFIER_HOME` can roll the
consumption journal back together with the issuance journal
and resurrect an envelope — the same residual the ceremony
issuance journal already carries (unanchored, see D7).
This is accepted *as the same residual*, not as a new one:
the attacker who can do this already owns the verifier
process, its seed, and its minting capability, so the
consumption head is not the weakest link in that scenario.
What route 4 closes is the *caller-side* replay, which is
the demonstrated defect.

## D2. How `reanchor_pin` invokes consumption — POSITION: REQUIRED consume-callable, invoked once at a single pinned point; caller orchestration alone is rejected

### The signature change

```python
def reanchor_pin(old_pin, signed, *, signing_key, state_bytes,
                 calibration_bytes, expected_signer_id, operator_id,
                 reason, evidence_hash, authorisation,
                 authorisation_public_key, expected_verifier_signer_id,
                 ceremony_history, consume_authorisation,
                 strict_reasons=None, now=None):
```

`consume_authorisation` is a **required keyword-only
parameter with no default** (like `ceremony_history` in
cycle 20: omission is a `TypeError` at the call site).
It is a callable with this protocol:

```python
consume_authorisation(authorisation, new_pin) -> None
#   authorisation: SignedCeremonyAuthorisation (the typed envelope)
#   new_pin:       dict, exactly the pin this call is about to return
#                  ({"cycle_seq", "payload_hash", "key_id", "signer_id"})
# Raises SigningError on any refusal (already consumed, not
# monotonic, not issued, unavailable). Returns None on success.
# Invoked at most once per reanchor_pin call; never retried.
```

A callable is architecturally *required*, not merely
convenient: `signing/` must not import `trust/` (the import
direction is `trust` → `signing`, and `pin_ceremony` already
cannot import its own consumers). The only way
`reanchor_pin` can touch verifier-owned state without
breaking that direction is dependency injection. A
caller-supplied callback is therefore not a concession to
the caller — it is the typed seam across a module boundary,
and its trust comes from *which* callable the production
caller installs (the verifier-backed adapter, §D2.2), not
from the parameter's existence. Unit tests install an
in-memory fake; that is the same pattern as the existing
`now=` test seams.

### D2.1 Why caller orchestration alone is rejected

The alternative — "the caller calls `consume()` before or
after `reanchor_pin` itself" — fails on every leg that
matters:

* **Before:** a consume-then-crash / consume-then-refuse
  sequence burns an envelope whose ceremony then refuses
  (e.g. bare-verifier failure), wasting a single-use
  authorisation and, worse, teaching callers to "retry the
  ceremony with the same envelope", which is exactly the
  replay the head exists to stop.
* **After:** the window between `reanchor_pin` returning
  and the caller consuming is a TOCTOU gap in which a
  second, concurrent or replayed call can return the same
  pin — the defect, preserved.
* **Forgettable:** orchestration is a convention in prose;
  a callable parameter is a type-level requirement that a
  missing `consume_authorisation` fails loudly at the call
  site. Cycle 20 already learned this lesson with
  `ceremony_history`: the opt-in guard was the defect.

### D2.2 The production callable (trust/client.py)

`VerifierClient` gains:

```python
def ceremony_consume(self, signed) -> dict:
    """Consume one ceremony authorisation verifier-side.
    Sends {"signed_authorisation": envelope_dict} to the new
    verifier mode ceremony_consume; verifies the response echo
    (authorisation_id, consumption_seq, consumed head) against
    the envelope it sent; raises VerifierProtocolError on an
    exit-2 refusal (already consumed / not monotonic / not
    issued) and VerifierConfigError / VerifierUnavailable on
    an exit-3 / transport failure. No auto-retry: a timeout
    leaves consumption ambiguous (see §D2.4) and a retry that
    lands as already-consumed is indistinguishable from a
    replay — the caller must treat it as burned."""
```

and a small adapter:

```python
def ceremony_consume_callable(client) -> callable:
    """Return a reanchor_pin consume_authorisation callable
    backed by client.ceremony_consume. Translates the client's
    exceptions to SigningError (preserving the verifier's
    error code in the message); the adapter is the only
    production implementation of the protocol."""
```

The adapter, not `reanchor_pin`, knows about the verifier.
`reanchor_pin` knows only the protocol.

### D2.3 Invocation point — exactly one, pinned

Order inside `reanchor_pin` (new step (9), after the
existing steps):

1. type gates (incl. `CeremonyPublicKey` consistency);
2. **history presence + consume-callable presence** — an
   explicit `ceremony_history is None` refuses, and an
   explicit `consume_authorisation is None` (or a
   non-callable) refuses, both *before* envelope
   verification, for every reason, so a missing continuity
   input is never masked by an expired or foreign envelope;
3. envelope verification (Ed25519, pinned key, single
   captured clock);
4. exact binding (operator / reason / old pin / candidate /
   evidence);
5. evidence non-equality;
6. candidate relation (`backwards` / `same` / `successor` /
   fork spellings refused);
7. `chain_gap_recovery` recomputation of the strict result
   against the captured pin;
8. history content checks (`_check_ceremony_history` —
   still run, see D4) and the bare-verifier attestation
   bindings;
9. **`consume_authorisation(authorisation, new_pin)`** —
   the consumption commit. `new_pin` is the exact dict
   `_pin_of(signed)` that will be returned;
10. only infallible work remains: build the payload,
    compute its hash, MAC the record, return
    `(new_pin, record)`.

Step 9 is the *only* point at which consumption may happen,
and it is the *last fallible* step. Nothing after it can
refuse: the record MAC cannot fail on well-formed inputs
that have already passed steps 1–8. That ordering is what
makes the crash-consistency contract below true *by
construction* rather than by hope.

### D2.4 The crash-consistency contract (exact words — to be copied verbatim into the `reanchor_pin` docstring and the verifier mode docstring)

> **Consumption crash-consistency contract.** The verifier
> records a consumption durably — journal entry written,
> fsynced, atomically replaced, and directory fsynced —
> before it returns success, and `reanchor_pin` returns a
> pin only after the consumption call has returned success.
> Therefore: (a) **no successful pin movement exists
> without a durably committed consumption record** — a
> crash at any point before the verifier's commit leaves
> the envelope unconsumed and the pin unmoved, and the
> ceremony is retryable with the same envelope; (b) **a
> crash after the verifier's commit but before the caller
> adopts the returned pin leaves the envelope burned and
> the pin unmoved** — the ceremony is NOT retryable with
> that envelope, and recovery is a new ceremony_id with a
> new evidence bundle, exactly as for an issuance burn
> after a withheld envelope (cycle 20); there is no
> un-consume, no refund, and no "consume was ambiguous so
> try again" path — an ambiguous timeout is treated as
> burned, never as unconsumed; (c) **a crash during the
> journal write leaves either the old journal or the new
> journal, never a half entry**, because the write is a
> single temp-file fsync plus atomic `os.replace` under
> the directory flock (the `HashChainJournal._save`
> discipline); a retry after such a crash re-reads the
> journal and finds either "not consumed" (retry the
> ceremony) or "already consumed" (refuse, new ceremony);
> (d) **consumption is never recorded for a refused
> ceremony** — the consume call sits after every other
> refusal point, so a ceremony that fails any check burns
> nothing.

Consequences the build must honour: the client must not
auto-retry `ceremony_consume` (an ambiguous timeout is
burned); the verifier mode must not return success before
the journal commit (see D5 ordering); `reanchor_pin` must
not retry the callable (one invocation, exactly once);
and the caller-side ATOMIC-ADOPTION obligation (persist
pin + record as one step) survives unchanged — but its
failure mode is now safe: failing to adopt can no longer
enable a replay, because the envelope is already burned
verifier-side.

## D3. The precise monotonic refusal rules

The consumption journal holds, per entry, at minimum:
`authorisation_id`, `payload_hash`, `ceremony_id`,
`candidate_cycle_seq`, `candidate_payload_hash`,
`old_cycle_seq` (int or null), `evidence_hash`,
`operator_id`, `consumed_at`. The journal's **consumed
head** is defined as the entry with the maximum
`candidate_cycle_seq` (ties are impossible — see below;
the journal seq is the tiebreak order if ever needed).
Let `H_seq` be that maximum, `H_hash` its
`candidate_payload_hash`; an empty journal has no head.

Rules, in check order inside `CeremonyConsumptionLedger.try_consume`
(and mirrored as the verifier mode's refusal vocabulary):

* **R1 — already consumed (authorisation_id).**
  `authorisation_id` already in the journal ⇒ refuse
  `ceremony_already_consumed`, regardless of
  `ceremony_history` (stale, empty, or omitted — omission
  already refused earlier), regardless of whether the
  candidate equals the previously consumed candidate, and
  regardless of the current pin. A ceremony is not
  idempotent: unlike `advance_pin`'s same-pin no-op, a
  second consumption of the same envelope is a replay,
  never a no-op. This is the rule that flips T7.
* **R2 — candidate not ahead of the consumed head.**
  `candidate_cycle_seq < H_seq` ⇒ refuse
  `ceremony_candidate_not_monotonic`. `candidate_cycle_seq
  == H_seq` and `candidate_payload_hash != H_hash` ⇒ refuse
  (fork at the head: a different snapshot at a sequence a
  ceremony already attested). `candidate_cycle_seq ==
  H_seq` and `candidate_payload_hash == H_hash` ⇒ refuse
  as a replayed target even under a *different*
  authorisation_id — this closes the laundering route of
  minting a fresh envelope for the same target after the
  first consumption (the issuance journal would allow it:
  a new ceremony_id + the same candidate is a new pair).
  A candidate is consumable only when `candidate_cycle_seq
  > H_seq`. This is the rule that flips T8: the replayed
  envelope's candidate (seq 4) is not ahead of the head
  (seq 4, from the first consumption), so it refuses
  before any pin is returned.
* **R3 — stale old pin.**
  When the envelope carries an `old_pin`: `old_pin.cycle_seq
  < H_seq` ⇒ refuse `ceremony_old_pin_stale` (the old pin
  was superseded by a ceremony); `old_pin.cycle_seq ==
  H_seq` and `old_pin.payload_hash != H_hash` ⇒ refuse
  (the old pin is a fork of the head). When the envelope
  carries no old pin (`initial_anchor` / `lost_pin` /
  `corrupted_pin`): no R3 check — a missing pin cannot be
  stale — but R2 still applies, and `initial_anchor`
  additionally refuses whenever the consumption journal is
  non-empty (a non-empty head contradicts "no ceremony
  precedes this one" more authoritatively than the
  caller-supplied empty history does; see D4).
* **Invariant the rules enforce:** consumptions land in
  strictly increasing `candidate_cycle_seq` order, so
  journal order == sequence order == head order, and the
  head can never move backwards. The first consumption
  (empty journal) is unconstrained by R2/R3.

### How the rules cope with `advance_pin` movements (honest limit)

`advance_pin` movements never pass through the verifier
and leave no trace in any journal — this is unchanged by
cycle 21 and is the design's known boundary (see §6,
weakest point). Consequences, stated exactly:

* The consumed head is a **ceremony head, not a pin head**.
  It cannot see that the live pin advanced from seq 4 to
  seq 6 by ordinary advances. R1/R2 still stop the *exact*
  T7/T8 replays, because those replays re-present the
  *same* envelope (R1) or the *same* candidate (R2) — the
  regression in T8 is produced by adopting the returned
  seq-4 pin, and with R1/R2 there is no return to adopt.
* What the head does **not** stop: a *different*, fresh
  envelope whose candidate sits behind the live pin but
  ahead of the ceremony head (e.g. live pin at seq 6 via
  advances; a fresh envelope for candidate seq 5, bound
  to a restaged old pin at seq 1, with `candidate_seq 5 >
  H_seq 4`). R2 passes, the envelope verifies, and
  `reanchor_pin` would return the seq-5 pin. The existing
  in-process checks (envelope old-pin binding, strict
  recomputation) are envelope-vs-argument checks and
  cannot see the live pin either.
* Therefore the design claims: **replay of a consumed
  envelope, and regression through a consumed candidate,
  are closed; regression through a fresh envelope against
  a silently advanced pin is NOT closed by this cycle.**
  Closing it requires the future loop/storage layer to
  report `advance_pin` movements into the head (or to
  perform pin adoption as a compare-and-swap against the
  head) — recorded as a named follow-up, not smuggled
  into this cycle's claims. The war room should not let
  any docstring in this cycle imply the general
  "regression is impossible" claim.

## D4. `ceremony_history`'s role after the head exists — REQUIRED, audit-only, never authoritative

**Position: `ceremony_history` stays a required keyword,
`None` still refuses before envelope verification for
every reason, and `_check_ceremony_history` still runs —
but its authority is demoted to audit/consistency-only.
It can refuse; it can never grant. The consumption head
is the sole authority for single-use.**

Why keep it at all, if it is no longer authoritative?

1. The head knows nothing the caller knows: evidence
   reuse *within the caller's own records*, forked
   histories (two records at the same sequence), and the
   candidate-predates-latest-ceremony time check are
   consistency properties of the caller's record chain,
   and the head (one entry per consumption, keyed by
   authorisation) does not duplicate all of them.
   `_check_ceremony_history` remains defence in depth.
2. Removing it would be an API break that buys nothing:
   every existing caller passes a history, and the
   fail-closed-on-omission behaviour is a real guard
   against a caller that "forgets" continuity entirely.
3. `initial_anchor`'s empty-history requirement stays —
   but it is now *backed* by the head: an empty history
   plus a non-empty consumption journal refuses via R3's
   `initial_anchor` clause, so the empty-history assertion
   is no longer unverifiable in the case that matters
   (a prior ceremony exists).

What changes is the *wording and the claim*, everywhere
(`pin_ceremony.py` docstring, `_check_ceremony_history`
docstring, `reanchor_pin` docstring):

* Old (cycle 20): history is the replay defence, with a
  named stale-history residual.
* New: "The caller-supplied history is a consistency
  check over caller-supplied input. It is not rollback or
  replay protection. Single-use is enforced by the
  verifier-owned consumption journal (see
  `CeremonyConsumptionLedger`); a stale, truncated, or
  honestly-empty history cannot cause a consumed envelope
  to be accepted, because the consume call consults the
  head, not the history. A discrepancy between the history
  and the head resolves in favour of the head."

A test pins this demotion: a ceremony with a *stale*
history (empty) after a first consumption refuses via
the head (R1), and a ceremony with a *complete* history
that contradicts the head (e.g. history omits a
consumption the journal holds — constructed by calling
the consume path directly) also refuses via the head.

## D5. What the verifier's consume path cross-checks

New verifier mode `ceremony_consume` (`trust/verifier_main.py`,
added to `_MODES`), request body exactly
`{"signed_authorisation": <envelope dict>}`. Order:

1. **Config gates.** The mode refuses exit-3
   `ceremony_seed_unconfigured` when no ceremony seed is
   configured (the verifier cannot verify the envelope
   without deriving its own public key from the seed),
   and exit-3 `ceremony_consumption_unavailable` when the
   consumption journal cannot be opened/validated.
   Production + absent seed already refuses at startup;
   research + absent refuses per-request, mirroring
   `ceremony_authorise`.
2. **Strict body.** Exact key set, else exit-2
   `malformed_request`. No ledger touched.
3. **Envelope parse.** `ceremony_authorisation_envelope_from_dict`
   (v1 markers refused as superseded, same as issuance).
   Malformed ⇒ exit-2.
4. **Signature + expiry, verifier-side.** The verifier
   derives its `CeremonyPublicKey` from its own seed and
   runs `verify_ceremony_authorisation` with
   `expected_signer_id=config.signer_id` and `now` = the
   verifier's clock. Any reason ⇒ exit-2
   `ceremony_consumption_signature_mismatch` /
   `ceremony_consumption_expired` (sub-case logged
   verifier-side only; caller-visible bytes identical
   across sub-cases, the cycle-20 evidence-sub-case
   precedent). This is a *second* verification of the
   same envelope `reanchor_pin` already verified — not a
   second path, the same call — and it is what makes the
   consume endpoint unusable for forgeries and for
   envelopes that expired between the in-process check
   and the consume call (the 900 s TTL makes that window
   real; expiry at the consume step fails closed, and the
   caller needs a fresh envelope).
5. **Issuance presence.** `authorisation_id` must exist
   in `CeremonyAuthorisationLedger`
   (new `find_by_authorisation_id` lookup), and the
   entry's `payload_hash`, `ceremony_id`, and
   `evidence_hash` must match the envelope's. Absent or
   mismatched ⇒ exit-2 `ceremony_not_issued`. This binds
   consumption to issuance accounting: an envelope the
   verifier never minted — a test envelope, a locally
   minted forgery under a different seed, an envelope
   from a rotated seed — cannot be consumed, even if its
   signature somehow verified under a stale pin. It also
   means consumption cannot precede issuance in any
   ordering.
6. **Monotonic check + append = the commit point.**
   `CeremonyConsumptionLedger.try_consume` reloads,
   re-checks R1/R2/R3 against the fresh entries, and
   appends in one `_save` (bounded retry on
   `CorruptLedgerError`, 8 attempts, re-validating each
   time — the `ShipLedger.burn` pattern). Refusals:
   exit-2 `ceremony_already_consumed` (R1),
   `ceremony_candidate_not_monotonic` (R2),
   `ceremony_old_pin_stale` (R3).
7. **Response.** `{"authorisation_id", "consumption_seq",
   "consumed_head": {"cycle_seq", "payload_hash"},
   "journal_head": <hex64>}`. No signing, no retention
   write, no signing-ledger append (no signature is
   issued, so the signing ledger's inference is
   untouched), and no signing-anchor update. The client
   verifies the echo (authorisation_id matches the
   envelope; consumption_seq is a positive int;
   consumed_head equals the envelope's candidate).

**Explicitly NOT cross-checked at consume time:**

* Operator allowlist membership — issuance already
  decided it; re-checking it would make consumption
  depend on the *current* allowlist, so a legitimate
  operator removed from the list between issuance and
  consumption would strand a valid envelope. The envelope
  is the issuance fact; the consume path trusts the
  signature, not the live list.
* Evidence resolution / retained bytes — retention is
  not a consumption input (cycle 20, unchanged). The
  evidence hash is checked only for equality against the
  issuance entry (step 5), never re-resolved.
* The candidate's attestation bindings — those are
  `reanchor_pin`'s job (steps 7–8, before the consume
  call). The verifier cannot see the snapshot bytes and
  must not pretend to.

**Fail-closed when authoritative state is unavailable:**
any `CorruptLedgerError` / `OSError` opening either
journal ⇒ exit-3 `ceremony_consumption_unavailable`,
and the client adapter converts it to `SigningError`
so `reanchor_pin` refuses. There is no degraded mode,
no local cache, no "consume later" queue. A verifier
that cannot read its consumption journal cannot
authorise a ceremony.

## D6 (B). File-level change list — workstream B

| File | Change |
|---|---|
| `trust/ledger.py` | New `CeremonyConsumptionLedger(HashChainJournal)`: `FILENAME = "ceremony-consumptions.json"`, `EXTRA_KEYS = {authorisation_id, payload_hash, ceremony_id, candidate_cycle_seq, candidate_payload_hash, old_cycle_seq, evidence_hash, operator_id, consumed_at}`; `find_by_authorisation_id`, `consumed_head()`, `is_consumed(authorisation_id)`, `try_consume(signed, *, recorded_at)` with post-reload R1/R2/R3 re-check + bounded retry (8). |
| `trust/verifier_main.py` | New mode `ceremony_consume` (§D5 ordering, steps 1–7); register in `_MODES`; `_Config` gains nothing new (home already held); module docstring: consumption-head section + crash contract + the unanchored residual; `_load_config` gains a startup open of the consumption journal (fail-closed `ledger_failed` if corrupt — mirrors the signing-ledger anchor open). |
| `trust/client.py` | `VerifierClient.ceremony_consume(signed)` + `ceremony_consume_callable(client)` adapter (§D2.2); docstring on the no-retry rule and the ambiguous-timeout-as-burned rule. |
| `signing/pin_ceremony.py` | `reanchor_pin`: new required kw `consume_authorisation` (§D2); presence check at step (2); single invocation at step (9) after all other checks; module + function docstrings rewritten per D4 (history audit-only) and the crash contract (§D2.4) verbatim; F1-narrowed residual paragraph replaced by the D3 honest-limit paragraph. |
| `signing/ceremony_authorisation.py` | No change (envelope format untouched). |
| `trust/anchoring.py` | No change this cycle (see D7). |
| `deploy/verifier-identity/` + deploy README | Document the new journal file in the verifier-home inventory (permissions 0600 dir, owned by the verifier user), the no-new-env-var fact, and the recovery procedure (burned envelope ⇒ new ceremony_id + new evidence). |
| `tests/test_signing_pin_ceremony.py` | T7/T8 flipped to refusals (§D6-B tests below); every existing `reanchor()` helper call gains a fake consume callable (in-memory set implementing the protocol); new `FakeConsumption` helper shared by the file. |
| `tests/test_trust_ceremony_consumption.py` (new) | Verifier-mode tests: consume happy path, R1/R2/R3 refusals, not-issued refusal, expired/forged envelope refusal, corrupt-journal fail-closed, concurrent double-consume (two-process barrier probe, exactly one success — the cycle-20 issuance race test as precedent), crash-boundary tests (§D6-B). |
| `tests/test_trust_consumption.py` | Untouched (sealed-eval consumption is a different mechanism). |

### Test list — workstream B

* **T7′ (flipped):** same envelope twice, second call
  with the *stale* history `()` and the verifier-backed
  (or fake-backed, per test layer) consume callable ⇒
  `SigningError` containing `already consumed`; no pin
  returned; the first pin is unchanged.
* **T8′ (flipped):** T8's exact scenario (consume
  seq1→seq4, advance to seq6, replay with restaged
  seq-1 pin, stale history) ⇒ `SigningError`
  `already consumed`; the test asserts the refusal, and
  asserts the caller's seq-6 pin is *not* regressed
  (the function returns nothing to adopt).
* **T9 — different envelope, same target:** fresh
  envelope for the already-consumed candidate under a
  new ceremony_id ⇒ `ceremony_candidate_not_monotonic`
  (R2 laundering route).
* **T10 — candidate behind head, fresh envelope:**
  envelope for candidate seq 3 after head seq 4 ⇒
  `ceremony_candidate_not_monotonic`.
* **T11 — stale old pin:** envelope bound to old pin
  seq 1 after head seq 4 ⇒ `ceremony_old_pin_stale`.
* **T12 — forward consumption still works:** a second,
  distinct ceremony with candidate seq 7 after head
  seq 4 succeeds and the head advances to 7.
* **T13 — `initial_anchor` after a ceremony:** with a
  non-empty consumption journal, an `initial_anchor`
  envelope refuses even with an empty history.
* **T14 — consume callable omitted / None:** `TypeError`
  (omitted) and `SigningError` fail-closed-on-omission
  (explicit `None`), before envelope verification.
* **T15 — history demotion:** a ceremony whose history
  is empty but whose consumption journal is non-empty
  refuses via the head (not via history); a ceremony
  whose history *contradicts* the head (constructed by
  consuming directly) refuses via the head.
* **T16 — consume-after-refusal burns nothing:** a
  ceremony that fails the bare-verifier check never
  invokes the callable (fake records zero calls), and
  the envelope remains consumable by a corrected attempt.
* **T17 — verifier mode, not issued:** an envelope
  signed under a *different* ceremony seed (valid
  signature, never ledgered at issuance) ⇒
  `ceremony_not_issued`.
* **T18 — verifier mode, expired/forged:** expired
  envelope ⇒ refusal at consume time even though the
  in-process check ran inside TTL; tampered signature ⇒
  refusal.
* **T19 — concurrent double-consume:** two processes /
  threads racing the same envelope through the verifier
  mode, barrier-synchronised ⇒ exactly one success, one
  `ceremony_already_consumed` (the cycle-20 issuance
  race probe, adapted).
* **T20 — crash boundaries** (fault injection following
  the `test_trust_crashlab.py` pattern): crash before
  the journal write ⇒ envelope unconsumed, retry
  succeeds; crash after journal replace but before the
  response ⇒ envelope consumed, retry refuses
  `already consumed`, pin unmoved; crash after
  `reanchor_pin` returns but before caller adoption ⇒
  envelope burned, pin unmoved, new ceremony required.
  Each boundary is a named test, not a comment.
* **T21 — unavailable state fails closed:** consumption
  journal corrupted (bad JSON / broken chain) ⇒
  `ceremony_consume` exit-3, client raises, `reanchor_pin`
  refuses; no pin movement.

---

# PART II — WORKSTREAM A: ED25519 DIFFERENTIAL VALIDATION + SEED HYGIENE (LEAD)

## D6 (A). Suite composition — `tests/test_signing_ed25519_differential.py` (new file)

A new file, not an extension of `tests/test_signing_ed25519.py`:
the existing file is the cycle-20 record (RFC vectors, the
affine oracle, the 7 adversarial vectors) and stays
untouched as the baseline; the differential suite is a
separate, independently readable artefact whose whole point
is that it does not trust the code under test. It shares
only literal constants (RFC vectors, small-order list) with
the old file, by re-declaring them — a shared import of
test fixtures would let a fixture error hide in both.

### A1. RFC 8032 known-answer vectors (expanded)

* TEST 1/2/3 (already in the old file, re-declared here):
  `public_key_from_seed`, deterministic `sign` byte-equality,
  `verify` acceptance.
* **The 1024-byte-message vector** (RFC 8032 §7.1, the
  `af82…` 1024-octet message): the old file never exercises
  a long message; a length-dependent bug in the sign/verify
  hashing would hide in short messages. Literal seed /
  public / signature from the RFC, byte-compared.
* **Empty-message vs non-empty boundary:** the empty
  message is a real edge (hash of nothing) and is kept as
  its own case, not folded into the loop.

### A2. Wycheproof-style adversarial table

Every case asserts `verify(...) is False`, and — this is
the differential discipline — every case carries a
`reason` naming *which strict-profile step* rejects it,
so a future profile change that accidentally admits a
case fails the test by reason, not by silence. The table:

| Group | Cases (all REJECT) | Rejecting step |
|---|---|---|
| Non-canonical R | `R` with y = q, y = q+1, y = 2^255−1 (sign bit 0 and 1), y = q with the x=−0 spelling; same constructions applied to A | (2) canonical decode |
| S boundary | S = L−1 (equation-satisfying construction where possible, else the raw forged value), S = L, S = L+1, S = 2^255−1, S+L malleation of a valid signature | (4) S < L |
| Small-order A | all 8 small-order encodings as A, with the valid TEST 1 signature | (3) blocklist |
| Small-order R | all 8 as R, S = 0 and S = 1 | (3) blocklist |
| Mixed torsion A | A′ = A + T for T in {order-2, order-4, order-8} torsion points, with the equation-satisfying S′ construction (cycle-20 F3 pattern, generalised to order-4/8 generators) | (5) cofactorless equation |
| Mixed torsion R | R′ = R + T for the same T set, with S′ = r + k′·a | (5) cofactorless equation |
| Mixed torsion A+R | A′ = A + T₁, R′ = R + T₂ (independent torsions) | (5) |
| Identity/zero | (A=I, R=I, S=0), (A=order-2, R=I, S=0), (A=I, R=B, S=k·a) | (3)/(5) |
| Bit-flips | **exhaustive single-bit flips**: every bit of the 64-byte signature (512 cases) and every bit of the 32-byte public key (256 cases) of TEST 1, each flipped singly, must verify False; plus two-bit flips at the R/S boundary (byte 31/32) as a spot check | (2)/(4)/(5) as applicable |
| Length/type | truncated/overlong signature and key, `None`, `bytearray` vs `bytes` acceptance parity (both must behave identically), non-bytes message | (1) lengths / never-raises |

Construction rule (the cycle-20 F3 discipline, kept):
constructions use `hashlib` only, or the module's point
arithmetic **for construction only** — never for the
expectation. Where a construction claims a lax verifier
would accept, the comment states the exact lax equation
that holds, so the test's reasoning is checkable without
trusting the code. The exhaustive bit-flip loop is the
one place construction is trivial (a byte flip) and the
expectation is uniform (False).

**Cost note (build must measure and record):** 768
bit-flip verifies at the measured ~6–30 ms each is
roughly 5–25 s on this VM. That is acceptable for this
suite and is the price of exhaustiveness; if the build
measures over 60 s, the fallback is byte-mask flips
(0x01 / 0x80 / 0xFF per byte, 288 cases) — but the
fallback must be recorded as a deliberate reduction in
BUILD-CYCLE-21, not silently taken.

### A3. Cross-implementation agreement against openssl

**Tooling.** `openssl` at `/usr/bin/openssl`, 3.0.13
(verified this round). Tests use `subprocess` with a
hard timeout (30 s per invocation), temp files created
0600 under `tempfile.TemporaryDirectory`, and are
guarded by the repo's existing skip pattern:

```python
OPENSSL = shutil.which("openssl")
@unittest.skipUnless(OPENSSL, "openssl not available")
```

matching `tests/test_trust_identity.py`'s
`skipUnless(shutil.which("runuser") …)` form. A
`setUpClass` probe runs `openssl version` and skips
the class if the binary cannot execute (broken install
is a skip, not a failure — the suite must stay green on
a machine without openssl, and the *absence* of the
differential is visible in the skip count). No network,
no key generation by openssl for the test vectors
(deterministic seeds are the RFC literals).

**DER wrapping (the part that usually breaks).**
OpenSSL's `pkeyutl` does not take raw 32-byte Ed25519
keys; it takes DER. The suite constructs DER in-test
from literal prefixes — no `cryptography` library, no
asn1 parser, stdlib only:

* **PKCS#8 private key (seed):**
  `30 2e 02 01 00 30 05 06 03 2b 65 70 04 22 04 20`
  + 32 seed bytes. (RFC 8410 / OpenSSL's Ed25519
  PKCS#8: `PrivateKeyInfo` with algorithm OID
  1.3.101.112, the seed as an OCTET STRING inside the
  `CurvePrivateKey` OCTET STRING.)
* **SPKI public key:**
  `30 2a 30 05 06 03 2b 65 70 03 21 00`
  + 32 public-key bytes.

Both prefixes are pinned as literals in the test and
asserted structurally (length 48 / 44, OID bytes
`06 03 2b 65 70` at the right offset) before use, so a
prefix typo fails as a test failure, not as a mysterious
openssl error. The suite also cross-checks key
derivation through openssl itself: `openssl pkey -in
<priv.der> -pubout -outform DER` must yield exactly the
constructed SPKI bytes for each RFC seed — that pins
our `public_key_from_seed` against openssl's, through
a path that never touches our verify.

**Agreement matrix.** Two directions, both required:

1. **openssl signs → we verify.** For each RFC vector
   message: `openssl pkeyutl -sign -rawin -inkey
   <priv.der> -in <msg>` must produce a signature that
   is *byte-identical* to our `sign(seed, message)`
   (Ed25519 is deterministic — this is the strongest
   agreement claim available) and that our `verify`
   accepts. Byte-identity is asserted, not just
   acceptance: acceptance alone would pass a
   probabilistic signer, and Ed25519 is not one.
2. **We sign → openssl verifies.** Our `sign` output
   must pass `openssl pkeyutl -verify -pubin -inkey
   <pub.der> -rawin -in <msg> -sigfile <sig>`, exit 0,
   for the RFC messages and for 10 random
   (seed, message) pairs (seeded RNG, seed recorded in
   the test for reproducibility).

**Adversarial differential — the honest part.** The
adversarial cases in A2 must NOT be asserted as
"openssl agrees" across the board, because openssl's
verifier is not our strict profile: it is a different
implementation with its own acceptance choices (e.g.
it may accept some non-canonical or small-order
inputs our profile rejects, and it historically
accepted the cofactored equation in ways the strict
profile does not). The differential therefore
classifies each adversarial case into one of three
buckets, recorded in the test table:

* **AGREE-REJECT** — openssl rejects (non-zero exit /
  "Signature Verification Failure") and we reject.
  Asserted as agreement.
* **AGREE-ACCEPT** — both accept. Only the valid
  signatures and the S = L−1 equation-satisfying
  construction (if openssl accepts it) may sit here;
  any other case landing here is a test failure.
* **DIVERGE-EXPECTED** — we reject, openssl accepts.
  Asserted as *our* rejection plus a recorded openssl
  acceptance. The test asserts the openssl outcome is
  in the *allowed* set for that case (accept or reject),
  never that it equals ours. A case whose openssl
  outcome falls outside its allowed set is a failure
  that must be investigated, not re-bucketed.

The build must report the actual bucket counts; a
DIVERGE-EXPECTED case discovered at build time that
was predicted AGREE-REJECT is a finding, not a
reclassification to be done silently.

**What the differential does not prove (stated in the
test module docstring):** agreement with openssl pins
our implementation against *one* independent
implementation; it does not prove the RFC reading
itself, and openssl's own Ed25519 has had its
acceptance quirks. The RFC vectors are the
specification anchor; openssl is the independence
anchor; the affine oracle is the arithmetic anchor.
Three anchors, none of which is the code under test.

### A4. Seed hygiene — permission semantics and derivation-overlap checks

**D6-A decision 1 — permission semantics: "owner-only,
readable" (0400 or 0600), not "exactly 0600".**
`load_ceremony_seed` currently demands `st_mode & 0o777
== 0o600`. That is stricter than the security property
in one direction (0400 is *more* restrictive and is
refused) and looser than it in another (it says nothing
about ownership). The property that matters is: *no
principal other than the file's owner can read the
seed, and the owner can read it.* The new rule,
applied to the `stat` of the opened file descriptor
(see below):

```
permitted  iff  (mode & 0o077) == 0          # no group/other bits at all
                 and (mode & 0o400) != 0     # owner can read
                 and (mode & 0o100) == 0     # owner-execute is not a key-file mode
# i.e. exactly {0400, 0600}
```

0600 stays the generated mode (`generate_ceremony_key_file`
is unchanged: it creates 0600). 0400 is accepted because
a read-only seed file is a legitimate hardened deployment
and refusing it would push operators toward the more
permissive mode. 0200/0000 refuse (unreadable — but as a
*permission* refusal, not a confusing read error).
0700/0640/0604 refuse. **The same predicate is applied
to `gate_decision.load_signing_key`** in this cycle:
the two loaders share one key-file discipline and
letting them drift is exactly how a hygiene rule rots;
the change is a shared `_check_owner_only_mode`
helper in `gate_decision.py` used by both loaders,
with tests for both. (If the war room rules this out of
scope, the fallback is ceremony-only — but the
divergence must then be recorded as a named follow-up,
not left silent.)

**D6-A decision 2 — the loader must stop trusting
`stat`-then-`read` (TOCTOU / FIFO).** The current
loader does `target.is_file()`, then `target.stat()`,
then `target.read_bytes()` — three separate syscalls
on a path that `_check_key_path` has already validated
for symlinks. A FIFO at the path fails `is_file()` and
is refused, which is correct by accident; a file
swapped between the mode check and the read is not
covered. New loader discipline (mirroring the cycle-20
evidence walk's `O_NOFOLLOW` + `O_NONBLOCK` lesson,
which fixed a FIFO hang in the same codebase):

* `os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)`;
* `os.fstat(fd)`: require `S_ISREG` (regular file —
  this is the explicit regular-file check the task
  requires, and it now happens on the fd, not the path);
  require the owner-only mode from decision 1 **on the
  fstat result**; require `st_uid == os.geteuid()`
  (the seed must be owned by the process's user — the
  verifier runs as a dedicated OS user, and a seed
  owned by another uid is a provisioning error, not a
  file to trust); require size ≤ 1024;
* read exactly from the fd (bounded, `os.read` loop),
  never re-opening the path.

The uid check is the one genuinely new restriction:
it can break a deployment where the seed is provisioned
by root and read by the verifier user — that deployment
is *already* broken by the mode rule's spirit (root can
read it regardless), and the fix is to provision as the
verifier user. The build must call this out in the
deploy README if any test fixture trips on it.

**D6-A decision 3 — derivation-overlap relations,
checked in `_load_config` only.** `_load_config` is
the one place both secrets exist (the cycle-20
comment says so, and it is still true). The existing
byte-equality check stays; the following are added,
all over raw bytes, all refusing startup with
`verifier_misconfigured` and a detail that names
neither value, extracted into a unit-testable helper
`_check_seed_key_separation(seed_bytes, key_bytes)`
in `verifier_main.py`:

```
R1  seed == key                          (existing)
R2  sha256(seed).digest() == key         # HMAC key derived from the seed
R3  sha256(key).digest() == seed         # seed derived from the HMAC key
R4  seed in _REFUSED_TEST_KEYS           # ceremony seed is a known HMAC test key
R5  key  in REFUSED_TEST_SEEDS           # HMAC key is a known ceremony test seed
```

Both directions of the sha256 relation are checked
(R2 and R3) because derivation has no canonical
direction — either secret could have been minted from
the other, and a check in one direction only would
bless the mirror image. Hex-encoding variants are
deliberately *not* checked (a 64-char hex string
truncated to 32 bytes is a different, detectable
misprovisioning that the loader's exact-length rule
already refuses in its own way) — the closed set
above is the checkable set, and the docstring must
say so rather than imply "all derivation overlaps
are detected".

**Residual, stated plainly:** no finite list of
relations detects an arbitrary KDF overlap
(`seed = HKDF(key, …)`, `key = seed XOR mask`, a
shared passphrase, …). Provisioning discipline —
independent random draws from `secrets.token_bytes`,
never derived, never copied — is the real defence;
these checks catch the accidents (copy-paste, a
script that hashes one secret to mint the other),
not a determined derivation. That is the honest
scope of a startup check.

**Where the checks run (and do not run):**
`_load_config` at verifier startup, both modes, for
the seed path *and* the HMAC key (the HMAC key load
already happens there). `load_ceremony_seed` itself
does NOT gain the overlap checks — it holds only one
secret and cannot check a relation. The verifier's
per-request path does not re-check (startup is the
gate; re-checking per request would re-read the seed
file per request and re-introduce the TOCTOU the
loader hardening just removed).

### A5. File-level change list — workstream A

| File | Change |
|---|---|
| `tests/test_signing_ed25519_differential.py` (new) | A1 + A2 + A3 (RFC 1024-byte vector, adversarial table with rejecting-step reasons, exhaustive bit-flips, openssl differential with DER prefixes and bucket classification, skipUnless guard). |
| `signing/ed25519.py` | **No change expected.** If the differential finds a defect, the fix is a separate, named change with its own test — the suite's job is to find it, not to smuggle a fix in under "test". |
| `signing/ceremony_authorisation.py` | `load_ceremony_seed`: fd-based open (`O_NOFOLLOW \| O_NONBLOCK`), fstat `S_ISREG` + owner-only mode (0400/0600) + `st_uid == euid`, bounded fd read. Docstring updated with the new semantics. |
| `signing/gate_decision.py` | Shared `_check_owner_only_mode` helper; `load_signing_key` uses it (same 0400/0600 semantics); `generate_key_file` / `generate_ceremony_key_file` unchanged (still create 0600). |
| `trust/verifier_main.py` | `_load_config`: `_check_seed_key_separation` helper (R1–R5); called after both secrets load, before env scrubbing; existing byte-equality check subsumed (kept as R1, not deleted silently). Startup refusal wording names the relation class, never a value. |
| `tests/test_signing_ceremony_authorisation.py` | Seed-loader tests: 0400 accepted, 0600 accepted, 0640/0700/0200/0000 refused, symlink refused, FIFO refused (no hang — assert it returns promptly), non-regular refused, wrong-owner refused (where the test harness can `chown`; skipUnless root/can-chown), oversize refused. |
| `tests/test_signing_gate_decision.py` | Same permission matrix for `load_signing_key` (0400 newly accepted — a behaviour change that must be pinned, not discovered). |
| `tests/test_trust_ceremony_mode.py` (or a new `test_trust_seed_hygiene.py`) | `_check_seed_key_separation` unit tests (R1–R5 each, plus a clean pair that passes); config-level tests: seed == sha256-derived key refuses startup; seed in HMAC refused set refuses startup. |
| `deploy/verifier-identity/` README | Seed provisioning note: 0400 is now accepted, ownership must be the verifier user, independent random draws, rotation procedure updated to mention the overlap check (a rotated seed derived from the old key will refuse startup — by design). |

### A6. Test list — workstream A (summary counts)

* RFC: 3 re-declared vectors × (keygen + deterministic sign + verify) + 1024-byte vector + empty-message edge ≈ 10 tests.
* Adversarial table: ~40 named cases (non-canonical R/A ~8, S boundary ~6, small-order A/R 16, mixed torsion ~10, identity/zero ~4, length/type ~8), each with its rejecting-step reason.
* Bit-flips: 768 exhaustive single-bit cases (2 tests: signature flips, public-key flips) + boundary two-bit spot check.
* Openssl differential: derivation agreement (3 seeds), openssl-signs-we-verify (3 RFC messages + byte-identity), we-sign-openssl-verifies (3 + 10 random), adversarial buckets (table-driven, ~20 cases classified), skip-behaviour test (openssl absent ⇒ skipped, not failed — asserted by running the module with a scrubbed PATH in a subprocess, the repo's existing pattern for optional tooling).
* Seed hygiene: loader permission matrix (~12), fd/regular-file/FIFO/wrong-owner (~6), separation helper R1–R5 (~7) + config-level refusals (~4).

---

# PART III — D7. ANCHORING OF THE NEW CONSUMPTION JOURNAL

**Decision: the consumption journal is NOT externally
anchored this cycle. The residual is named, in the same
words as the ceremony journal's, and the follow-up is
extended to cover both journals together.**

`trust/anchoring.py` supports kinds `signing`, `ship`,
`ship-tx`. Adding a fourth kind (`ceremony-consumption`)
would need a new anchor path env var, a new INIT ceremony,
startup verification in `_load_config`, and anchor updates
in the consume mode — a second anchoring surface built in
the same cycle as the journal itself, with no production
caller yet to exercise either. That is scope the cycle
does not need: the journal's job this cycle is to defeat
the *caller*, and an unanchored journal in the verifier
home defeats the caller completely. Anchoring defends
against a *different* attacker (the verifier-home writer
rolling the journal back), and that attacker is already
un-defended for the ceremony issuance journal — the
follow-up `ceremony-journal-anchoring` (BUILD-CYCLE-20.md,
verifier_main.py module docstring) already names it.

What this cycle does instead:

1. **Name the residual verbatim** in the consumption
   ledger's docstring, mirroring the ceremony journal's
   paragraph: "Rollback residual, stated plainly: no
   external anchor covers this journal yet (follow-up:
   ceremony-journal-anchoring, extended to the
   consumption journal). Rolling this file back erases
   consumption memory — a listed operator could then
   re-consume an envelope under the same authorisation.
   The anchored signing ledger preserves the issuance
   record (authorisation_id, payload_hash, ceremony_id),
   so a re-consumption after a rollback leaves a
   *consumption* trace that disagrees with the issuance
   record only by audit, not by prevention."
2. **Extend the existing follow-up** (do not create a
   second one): `ceremony-journal-anchoring` now covers
   both `ceremony-authorisations.json` and
   `ceremony-consumptions.json`, with one anchor kind
   each or a shared anchor discipline decided in that
   follow-up.
3. **Do not half-anchor.** A cheap alternative — writing
   the consumption head hash into the *signing* anchor
   — was considered and rejected: it would couple the
   signing anchor's update cadence to consumption, make
   the signing anchor's meaning ambiguous ("head of
   which journal?"), and give a false sense of coverage
   (the anchor would pin a hash the verifier never
   verifies against the consumption journal on startup).
   No anchor is better than a misleading one.

The honest ordering is therefore: this cycle closes the
demonstrated caller-side replay; the verifier-home
rollback residual (shared with issuance) is named and
queued, not closed.

---

# PART IV — RISKS, OPEN QUESTIONS, AND THE WEAKEST POINT

## Risks

1. **The consume-then-crash window burns envelopes.**
   A verifier commit followed by a crash before the
   caller adopts the pin strands a valid ceremony: the
   operator must re-do the whole ceremony with a new
   ceremony_id and new evidence. This is fail-closed
   (safe) but availability-costly, and with the 900 s
   TTL the re-do must happen fast. Mitigation: the
   contract (§D2.4) makes the window explicit and the
   recovery procedure is documented; the window is the
   same shape as the issuance burn (cycle 20) and is
   accepted on the same reasoning. Residual: an operator
   who crashes repeatedly could burn several envelopes
   before one lands.
2. **The ceremony becomes online.** `reanchor_pin` was
   a pure offline function; with a required consume
   callable it now needs a live verifier at consumption
   time. A verifier outage, a timeout, or a slow
   subprocess now refuses ceremonies that would
   previously have succeeded offline. Mitigation: the
   failure is a refusal, never a silent success; the
   30 s client timeout bounds the wait. Residual: the
   availability story of the ceremony changes, and the
   deploy docs must say so.
3. **Two journals, two rollbacks.** Issuance and
   consumption journals can now disagree in *two*
   directions (issued-but-never-consumed is normal;
   consumed-but-issuance-rolled-back is a rollback
   artefact). Audit tooling that reconciles them must
   handle both, and the D5 step-5 issuance check is
   what prevents the second direction from being
   exploitable at consume time.
4. **The 0400 acceptance is a behaviour change.**
   Any deployment or test that asserted "not exactly
   0600 refuses" (there are such tests) must be updated
   deliberately, with the new semantics pinned. The
   risk is a silent drift where one loader is updated
   and the other is not — hence the shared helper.
5. **Openssl differential flakiness.** Subprocess
   invocation, temp-file handling, and openssl version
   skew (3.0.13 here; other machines differ) can make
   the differential suite brittle. Mitigation: the
   skipUnless guard, the `setUpClass` probe, per-call
   timeouts, and bucket classification (DIVERGE-EXPECTED
   is a recorded outcome, not a failure). Residual: a
   machine with a differently-behaving openssl could
   produce bucket surprises that need triage, not
   auto-reclassification.
6. **Exhaustive bit-flips cost.** ~768 verifies at
   6–30 ms is 5–25 s; on a slower or loaded VM it could
   dominate the suite. Mitigation: the byte-mask
   fallback, recorded if taken.

## Open questions for the war room (not the owner)

* Q1. Should `try_consume` also record the *returned
  pin* hash chain (i.e. store the previous head's hash
  in each entry, beyond the journal's own chain)? The
  journal chain already links entries; a pin-chain
  field would be redundant but would make the
  consumption head auditable without replaying the
  journal. I say no — one chain, not two.
* Q2. Should the consume mode's response include the
  full consumed head history (for the caller to audit),
  or only the head? I say head only; history is the
  journal's job.
* Q3. Is the `st_uid == euid` loader check too strict
  for the research-mode workflow, where a developer
  provisions a seed as themselves and runs the verifier
  as themselves (same uid — fine) vs. a shared test
  account (different uid — refuses)? I say keep it;
  research mode is not a reason to accept a seed owned
  by someone else.

## The weakest point of this design (adversarial self-critique)

**The consumption head is a ceremony head, not a pin
head — and nothing in this design can see `advance_pin`.**

The strongest claim this design can honestly make is:
*no consumed envelope can be consumed again, and no
consumed candidate can be re-attested.* That closes T7
and T8 exactly as specified. But the general regression
class — "the pin moves backwards" — survives in a
narrowed form: a *fresh* envelope for a candidate that
is behind the live pin (advanced silently by
`advance_pin`) but ahead of the ceremony head will
pass R1, R2, and R3, verify, and return a regressed
pin. The head cannot see the live pin, the envelope
cannot see the live pin, and `reanchor_pin` cannot see
the live pin. Every layer in this design checks the
envelope against *arguments*, and the arguments can be
restaged. The only thing that would close the general
class is a pin store that the ceremony consults and
updates atomically with adoption — a store that does
not exist yet, in a layer (the loop/storage layer) that
does not exist yet. This design's honest boundary is
therefore: it makes *replay* impossible and leaves
*restaging against a silently advanced pin* to the
future layer, named in §D3 and in the docstrings. If
the war room wants the general claim, it must scope
the loop/storage layer's pin-store CAS into a future
cycle — it cannot be had by tightening this one.

The second-weakest point, close behind: the consume
call makes the ceremony depend on a live verifier
process at the exact moment of highest stakes (the
900 s TTL is ticking), and the ambiguous-timeout rule
("treat as burned") converts every transient verifier
hiccup into a lost ceremony. That is the correct
fail-closed choice, but it is a real availability cost
that the build must measure (how often does a consume
call time out under load?) and the war room should
watch.

---

# PART V — CONSOLIDATED FILE LIST

**Workstream A (lead):**
`tests/test_signing_ed25519_differential.py` (new);
`signing/ceremony_authorisation.py` (`load_ceremony_seed`);
`signing/gate_decision.py` (shared mode helper);
`trust/verifier_main.py` (`_check_seed_key_separation`);
`tests/test_signing_ceremony_authorisation.py`;
`tests/test_signing_gate_decision.py`;
`tests/test_trust_ceremony_mode.py` (or new
`test_trust_seed_hygiene.py`); deploy README.

**Workstream B (position):**
`trust/ledger.py` (`CeremonyConsumptionLedger`);
`trust/verifier_main.py` (`ceremony_consume` mode);
`trust/client.py` (`ceremony_consume` + adapter);
`signing/pin_ceremony.py` (`consume_authorisation`
parameter + docstrings); `tests/test_signing_pin_ceremony.py`
(T7′/T8′ flipped + fake consume); new
`tests/test_trust_ceremony_consumption.py`; deploy
verifier-home inventory + recovery procedure.

**No change:** `signing/ed25519.py` (unless the
differential finds a defect — then a separate named
fix), `signing/ceremony_authorisation.py` envelope
format, `trust/anchoring.py`, `tests/test_trust_consumption.py`
(sealed-eval), cycles 14–16 (not re-reviewed this cycle),
no GitHub push.
