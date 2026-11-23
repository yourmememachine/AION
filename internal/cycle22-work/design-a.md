# Cycle 22 — design A (coder seat A)

Primary slice: WS1 / F4 — an honest recovery reason for
*consumed-but-not-adopted* ceremonies. Plus critique sections
for WS2 (mirror gap) and WS3 (first production adopter).

Status: DESIGN ONLY. No production code changed.
Sources read: `internal/CROSS-CHECK-15.md`,
`internal/BUILD-CYCLE-21.md`, `signing/pin_ceremony.py`,
`signing/ceremony_authorisation.py`, `trust/ledger.py`
(`CeremonyConsumptionLedger`, `CeremonyAuthorisationLedger`,
`SigningLedger.append_ceremony_consumption`),
`trust/verifier_main.py` (`_mode_ceremony_authorise` ~2076,
`_mode_ceremony_consume` ~2394, `_update_anchor` ~793),
`trust/client.py` (`ceremony_consume` / `ceremony_consumer`),
`trust/anchoring.py` (`ANCHOR_KINDS`), `core/loop.py` (`save`).

---

## 0. The defect, restated precisely

Cycle 21's crash contract: consumption commits at the verifier
(a fsync'd `ceremony-consumptions.json` append) *before*
`reanchor_pin` returns anything. A crash / lost response /
adoption failure after that commit leaves:

- the authorisation permanently burned (single-use, no
  un-consume, client never retries), and
- the caller's pin exactly where it was before the ceremony.

The only recovery today is a new ceremony, but the only
reasons that fit its shape are false: the pin is not
`lost_pin` (it exists, unmoved, and the caller can read it),
not `corrupted_pin`, not `initial_anchor`. Gemini (CROSS-
CHECK-15): requiring the false label is "institutionalised
audit falsification". GPT accepted the deferral only as a
mandatory follow-up. This design builds that follow-up.

Non-goals, stated up front:

- No un-consume, no refund, no resurrection of the burned
  envelope. The burned `authorisation_id` stays burned
  forever.
- No new envelope field, no payload-version bump, no wire
  change (see §2.3 for why the burn is identified implicitly).
- No claim that the verifier can *see* non-adoption. It
  cannot; §5 argues exactly what honesty rests on instead.

---

## 1. Decision: `burned_unadopted` is a pin-optional reason

### 1.1 The tension

The current vocabulary is binary:

| shape | allowed reasons today |
|---|---|
| `old_pin is None` | `_NO_PIN_REASONS` = {`initial_anchor`, `lost_pin`, `corrupted_pin`} |
| `old_pin is not None` | `chain_gap_recovery` only |

That binary is enforced in four places that must move
together: `ceremony_authorisation_payload`
(`ceremony_authorisation.py`), `_mode_ceremony_authorise`'s
cheap-validation block, `reanchor_pin`'s gate-on-state block,
and `verify_ceremony_record`'s invariant re-check.

But the burn scenario occurs in **both** shapes:

- **Had-a-pin burn.** The burned ceremony was
  `chain_gap_recovery`: envelope bound `old_pin = P`
  (seq `s`, hash `h`) and candidate `T` (seq ≥ s+2). The pin
  is still `P`. A truthful recovery envelope naturally binds
  `old_pin = P` again and candidate `T` again.
- **No-pin burn.** The burned ceremony was
  `initial_anchor` / `lost_pin` / `corrupted_pin`: envelope
  bound `old_pin = None`, candidate `T`. There is still no
  pin. A truthful recovery envelope binds `old_pin = None`,
  candidate `T`.

### 1.2 Why neither existing bucket fits

- Putting `burned_unadopted` in `_NO_PIN_REASONS` forces the
  had-a-pin recovery to claim `old_pin = None` — a second
  false label replacing the first, and a harmful one: it
  drops the binding to `P`, so `reanchor_pin` would skip the
  relation checks and the strict `chain_gap` recomputation
  that are the local eligibility proof for that case.
- Treating it as `chain_gap_recovery`-only (pin required)
  makes the no-pin burn unrecoverable under an honest label
  — the falsification survives for exactly the
  `initial_anchor` case, where a burned first anchor is a
  plausible early-deployment accident.

### 1.3 Resolution

`burned_unadopted` is **orthogonal to pin presence**: it
asserts something about the *previous ceremony* (it was
consumed; its target was not adopted), not about the pin's
existence. Vocabulary change, identical in both mirrored
modules (`signing/pin_ceremony.py`,
`signing/ceremony_authorisation.py`):

```python
REASON_BURNED_UNADOPTED = "burned_unadopted"
REASONS = frozenset({..., REASON_BURNED_UNADOPTED})   # grows by one
_NO_PIN_REASONS = frozenset({initial_anchor, lost_pin,
                             corrupted_pin})          # UNCHANGED
# NEW mirrored set:
_EITHER_PIN_REASONS = frozenset({REASON_BURNED_UNADOPTED})
```

Coherence rule, replacing the binary everywhere:

```
reason in _NO_PIN_REASONS        -> old_pin must be None
reason == chain_gap_recovery     -> old_pin must be present
reason in _EITHER_PIN_REASONS    -> old_pin may be None or present;
                                    whichever it is, it must EXACTLY
                                    equal the burned entry's old pin
                                    (verifier-checked, §3)
```

`_NO_PIN_REASONS` deliberately does **not** grow, so every
existing assertion of the form "no-pin ⇒ reason ∈
_NO_PIN_REASONS" keeps its meaning, and the drift test gains
one new pinned equality (`_EITHER_PIN_REASONS` mirror ==
mirror) instead of a silent redefinition. `trust/
verifier_main.py` imports `REASONS` / `_NO_PIN_REASONS` from
`ceremony_authorisation` (lines 272–273); it picks the new
reason up automatically and needs one added import for
`_EITHER_PIN_REASONS`.

What the recovery envelope binds, per case:

| | burned envelope | recovery envelope |
|---|---|---|
| had-a-pin | reason `chain_gap_recovery`, old `P`, cand `T` | reason `burned_unadopted`, old `P` (same), cand `T` (same seq+hash; signer/key are the candidate snapshot's own, re-bound at consumption by attestation verification in `reanchor_pin`) |
| no-pin | reason ∈ `_NO_PIN_REASONS`, old `None`, cand `T` | reason `burned_unadopted`, old `None`, cand `T` (same) |

Everything else about the recovery is ordinary: **new**
`ceremony_id`, **new** evidence artefact (issuance
single-use already forbids reusing the burned evidence hash
for *any* ceremony), new envelope, fresh 900 s TTL, full
authorise → `reanchor_pin` → consume flow. `burned_unadopted`
grants no shortcut at any step; it only (a) tells the truth
in the audit record and (b) unlocks the two verifier checks
in §3–§4, which are *additional* refusals, not relaxations,
except for the single scoped head exception in §4.

---

## 2. Identifying the burn — one shared predicate

### 2.1 The consumption entry is the proof

`CeremonyConsumptionLedger` entries carry (EXTRA_KEYS):
`authorisation_id`, `ceremony_id`, `operator_id`,
`old_cycle_seq` (None for no-pin), `old_payload_hash`
(`""` for no-pin), `new_cycle_seq`, `new_payload_hash`,
`evidence_hash`, `consumed_at`. That is everything the
predicate needs. Note what it does **not** carry: `reason`.
Adding `reason` to EXTRA_KEYS is a journal format migration
(every historical entry fails the exact-key-set load check)
and is **rejected for this cycle** — §2.2 shows it is not
needed.

### 2.2 The predicate (single definition, two call sites)

New static method on `CeremonyConsumptionLedger` in
`trust/ledger.py`, used by both verifier modes so authorise-
time and consume-time can never diverge on what counts as
the burn being recovered:

```python
@staticmethod
def match_head_burn(entries, *, candidate, old_pin):
    """Return the head entry iff it is exactly the burn a
    burned_unadopted recovery re-anchors to, else None.
    candidate / old_pin are the projected shapes
    (old_pin None or {cycle_seq, payload_hash})."""
    if not entries:
        return None
    head = entries[-1]
    if (candidate["cycle_seq"], candidate["payload_hash"]) \
            != (head["new_cycle_seq"], head["new_payload_hash"]):
        return None
    if old_pin is None:
        if head["old_cycle_seq"] is not None \
                or head["old_payload_hash"] != "":
            return None
    elif (old_pin["cycle_seq"], old_pin["payload_hash"]) \
            != (head["old_cycle_seq"], head["old_payload_hash"]):
        return None
    return head
```

And the recovery predicate proper:

```
is_recovery(entries, envelope_or_body) :=
    envelope.reason == "burned_unadopted"
    AND match_head_burn(entries,
                        candidate=envelope.candidate,
                        old_pin=envelope.old_pin) is not None
```

Three scoping choices inside this predicate, each argued:

1. **Head-only.** The burn being recovered must be the
   *latest* consumption entry. The honest crash flow has
   nothing between the burn and the recovery attempt; if
   other consumptions have landed since, the target is
   superseded and resurrecting it would fight the monotonic
   head (§4). A non-head burn is simply not recoverable
   under this reason — the operator's path is an ordinary
   ceremony to a *current* target. This also makes the
   predicate O(1) and auditable.
2. **Old-pin equality, not just target equality.** Two
   different pins could in principle aim at the same
   candidate hash only if the snapshot is identical — but
   the old pin is part of what the burn *meant* (the gap it
   claimed to jump). Requiring the recovery to re-bind the
   burned entry's exact old pin prevents a recovery minted
   from a different pin state from riding the exception.
3. **Target uniqueness makes implicit identification
   sound.** At most one consumption entry can ever carry a
   given `(new_cycle_seq, new_payload_hash)` *without* the
   §4 exception (the head rules refuse `candidate == head`
   and `candidate < head` forever after), and every
   exception-created duplicate is itself a head recovery of
   the previous one (§6.2). So `(target, old_pin)` at the
   head identifies the burn unambiguously; no explicit
   `recovers_authorisation_id` field is needed.

### 2.3 Rejected alternative: explicit `recovers_*` field

Adding `recovers_authorisation_id` to the envelope would
mean: payload projection change, `_ENVELOPE_KEYS` change,
dataclass field, client echo checks, `reanchor_pin` binding
checks, and a payload-version question — a wide blast radius
to record a fact the journal already determines. It would
also create a new forgery surface (a field the verifier
must cross-check anyway against the same journal scan).
Implicit matching keeps the wire format at
`signed-ceremony-authorisation/2`, `SignedCeremonyAuthorisation`
unchanged, and `VerifierClient` unchanged.

### 2.4 Operator equality — deliberately NOT required

`match_head_burn` does not require the recovery's
`operator_id` to equal the burned entry's `operator_id`.
Rationale: operator ids are workflow provenance, not
authentication (any caller able to launch the verifier can
present any listed id — the standing narrowed claim), so
equality adds no security; it adds a liveness trap (the
burning operator id decommissioned before recovery). The
recovery envelope records its own operator; both operator
ids are in the journals for audit.

---

## 3. (b) Verifier `ceremony_authorise` — burn proof at issuance

Recovery must be proven **at authorise time**, not only at
consume time: otherwise the verifier would mint envelopes
labelled `burned_unadopted` for events that never burned,
and the false-label problem returns one level up (an
unconsumed recovery envelope is still a signed audit
artefact asserting a burn).

Changes in `_mode_ceremony_authorise`:

1. **Cheap validation (step 2 area).** Replace the binary
   coherence refusals with §1.3's rule:
   - `old_pin is None and reason not in
     _CEREMONY_NO_PIN_REASONS | _EITHER_PIN_REASONS` →
     `malformed_request` (as today).
   - `old_pin is not None and reason not in
     {"chain_gap_recovery"} | _EITHER_PIN_REASONS` →
     `malformed_request` (as today).
   - The gap-only sequence check (`candidate.cycle_seq >=
     old_pin.cycle_seq + 2`) applies unchanged when
     `old_pin is not None`, including for
     `burned_unadopted` — a with-pin recovery candidate is
     still a gap jump over the unmoved pin.
   - Evidence non-equality checks unchanged.
2. **New step (5b), after the anti-replay scan (5), before
   signing (6)** — both scan inputs (candidate, old pin) are
   fixed by then, and a refusal here mints no signature and
   retains no evidence, exactly like the (5) refusals:

```python
if reason == REASON_BURNED_UNADOPTED:   # imported constant
    try:
        consumption_entries = CeremonyConsumptionLedger(
            config.home).entries()
    except Exception:
        raise _config("ledger_failed", "...refusing to "
                      "authorise a recovery without the "
                      "consumption journal")
    burn = CeremonyConsumptionLedger.match_head_burn(
        consumption_entries, candidate=candidate,
        old_pin=old_pin)
    if burn is None or burn["ceremony_id"] == ceremony_id:
        raise _config("ceremony_recovery_unproven", ...)
```

   - `burn["ceremony_id"] == ceremony_id` is in practice
     unreachable (step (5) already refuses a reused
     `ceremony_id` globally); it is stated so the predicate
     "recovery ceremony ≠ burned ceremony" is explicit in
     code, not emergent.
   - **One refusal code for every predicate failure** —
     `ceremony_recovery_unproven`, exit-3 via `_config`
     (it is a state refusal, like `ceremony_id_reused`). No
     sub-case detail in the message and none on stderr that
     reaches the caller: distinguishing "no burn", "burn for
     a different target" and "old-pin mismatch" would hand a
     presenter a journal-state oracle. (This follows the
     consume mode's cycle-21 no-oracle discipline, which is
     stricter than authorise's evidence handling; apply the
     stricter one here.)
   - Unreadable consumption journal → `ledger_failed`,
     fail-closed, mirroring step (5)'s treatment of the
     issuance journal.
3. **Client impact:** none structurally.
   `VerifierClient.ceremony_authorise` passes `reason`
   through and verifies the returned envelope against the
   requested reason/old_pin/candidate; `burned_unadopted`
   flows through. The new exit-3 code surfaces as
   `VerifierConfigError` via `_run`, consistent with the
   other state refusals (docstring list of exit-3 codes
   gains `ceremony_recovery_unproven`).

Authorise-time proof is **necessary but not sufficient**:
the head can move between authorise and consume (another
ceremony consumes a higher target). Consume re-checks
authoritatively (§4). If the head has moved past the
recovery target by consume time, the recovery envelope
refuses there and its issuance pair stays burned — the
operator's remedy is an ordinary ceremony to a current
target, not a second recovery of a superseded burn. That
is existing monotonic semantics, not a new trap.

---

## 4. (c) Verifier `ceremony_consume` / `check_head` — the scoped head exception

This is the only place the design *relaxes* anything, so it
is kept to one predicate in one function.

### 4.1 The problem

`CeremonyConsumptionLedger.check_head(entries, signed)`
today, against head `H = (H_seq, H_hash)` = the burned
entry's target `T`:

- candidate `== H` (seq and hash) → `AlreadyConsumedError`
  ("candidate target already consumed") — the recovery
  candidate **is** `T`, so it dies here;
- with-pin case: recovery `old_pin = P` has `P_seq < H_seq`
  → `HeadRegressionError` ("old pin is behind the consumed
  head") — it dies here too.

Both refusals are correct for every non-recovery envelope.
The exception must lift exactly these two, for exactly the
§2.2 predicate, and nothing else.

### 4.2 Exact change to `check_head`

```python
# after head is computed, before the candidate checks:
recovery = signed.reason == "burned_unadopted" and \
    CeremonyConsumptionLedger.match_head_burn(
        entries, candidate=signed.candidate,
        old_pin=signed.old_pin) is not None
```

- Candidate block: `cand_seq == head_seq and cand_hash ==
  head_hash` raises `AlreadyConsumedError` **unless
  `recovery`** (then it falls through — the movement is a
  re-consumption of the head target under a *new*
  authorisation, which is the point). `cand_seq == head_seq`
  with a *different* hash still raises
  `HeadRegressionError` unconditionally (fork at the head;
  `match_head_burn` already failed on hash, so `recovery`
  is False — belt and braces agree).
- Old-pin block: skipped **iff `recovery`** — replaced, not
  waived: `match_head_burn` has already required the old
  pin to be *exactly* the head entry's recorded old pin,
  which is strictly stronger than the generic rule (generic:
  `old_seq == H_seq` needs hash equality, `old_seq > H_seq`
  passes sight-unseen). For a non-recovery envelope the
  generic block runs byte-identically to today.
- `initial_anchor`-against-non-empty check: untouched;
  `burned_unadopted != initial_anchor`, so a no-pin recovery
  against a non-empty journal is not caught by it. Correct:
  the journal is non-empty *because* it holds the burn.
- `cand_seq < head_seq` / `cand_seq > head_seq`: untouched.
  A `burned_unadopted` envelope whose candidate is ahead of
  the head gets no exception anywhere (and would already
  have failed authorise-time proof unless the head moved —
  §3's race, resolved fail-closed by the old-pin rule:
  its old pin is the burned entry's old pin, now behind
  the head).

`append_consumption` needs **no change**: its bounded
reload-retry loop already re-runs `check_head` against
fresh entries, so the authoritative re-check inherits the
exception, and its `authorisation_id` single-use check
already refuses a second consume of the recovery envelope
itself.

### 4.3 Mode-level changes in `_mode_ceremony_consume`

Almost none, by design:

- Step (5) already-consumed (journal + signing-ledger
  mirror scoped to `kind="consume"` /
  `format="ceremony-consumption"`): keyed on the *new*
  `authorisation_id` — passes for a genuine recovery,
  refuses a replay of the recovery envelope. Unchanged.
- Step (6) issuance presence: the recovery envelope was
  issued normally. Unchanged.
- Step (7): `check_head` as above. Refusal mapping
  unchanged and **no new consume codes**: predicate-false
  recovery attempts surface as the existing
  `ceremony_already_consumed` (candidate == head) or
  `ceremony_head_regression` — both truthful descriptions
  of why that envelope may not consume.
- Step (8) commit order unchanged: consumption append →
  signing-ledger mirror → `_update_anchor`. A mirror
  failure after the recovery's commit burns the recovery
  envelope too; recovery-of-recovery is §6.2.

### 4.4 Abuse analysis of the exception

The exception's full precondition, assembled: envelope
signed by the verifier (Ed25519, step 4) + issued through
the full authorise path including §3's burn proof +
operator on the protected allowlist at issuance + new
evidence artefact resolved and hashed by the verifier +
candidate `(seq, hash)` **exactly** the current head
target + old pin **exactly** the head entry's old pin +
this envelope's own `authorisation_id` never consumed.

1. **Re-consume a target that WAS adopted.** The verifier
   cannot see the pin — this is the honest weak point, and
   the design does not pretend otherwise. What bounds it:
   - *Honest-caller path:* after adoption the caller's pin
     **is** `T`. A recovery attempt must bind
     `old_pin = P` (or `None`) to pass §3/§4, but
     `reanchor_pin` binds the envelope against the caller's
     *fresh* pin (FRESH-PIN obligation): envelope old pin
     `P` ≠ current pin `T` → exact-binding refusal before
     consumption. Minting the envelope with `old_pin = T`
     instead fails twice: payload gap check (`T_seq <
     T_seq + 2`) and `match_head_burn` (old ≠ head entry's
     old).
   - *History path:* adoption appends the ceremony record
     (ATOMIC-ADOPTION obligation); `_check_ceremony_history`
     refuses any candidate that is already a ceremonied
     target in the supplied history. A recovery to an
     adopted target collides with its own record.
   - *Dishonest-caller residue:* a caller that supplies a
     stale pin **and** a truncated history **and** an
     allowlisted operator presentation can get a second
     consumption of `T` and a second record for `T`. The
     resulting pin value is *identical* — same seq, same
     hash, same snapshot. The exception can never change
     the target, fork the head (hash equality is in the
     predicate), move backwards (candidate == head, never
     below), or substitute a different snapshot at the
     sequence. Worst case is a redundant, fully journaled
     ceremony for a movement that already happened — an
     audit-visible operator act, not a silent bypass. This
     is the same trust class as cycle 21's existing
     caller-obligation residuals (FRESH-PIN /
     COMPLETE-HISTORY were never in-process verifiable), and
     the claim wording in §8 scopes it exactly that way.
2. **Re-consume under a different old pin** (e.g. attacker
   pin state): `match_head_burn` old-pin equality refuses
   at authorise; if the journal moved in between, §4's
   generic old-pin rule refuses at consume.
3. **Consume a never-burned target with the new label:**
   authorise refuses (`ceremony_recovery_unproven`) — no
   envelope exists to present at consume. A hand-built
   envelope fails Ed25519 at consume step (4).
4. **Skip evidence/operator via the label:** no step is
   skipped; §3 is *added* to the full issuance path.
5. **Race two recoveries for one burn:** both authorise
   against head `E_burn` (authorise does not consume);
   both consume-attempt: the first lands (head becomes its
   own entry, same target); the second now faces head =
   first recovery's entry — predicate still matches
   (same target, same old pin) so it *can* also land.
   Is that a hole? It produces two consumptions of the
   same target under two distinct, fully issued
   authorisations — equivalent to §6.2's iterated
   recovery, bounded by (1)'s residue argument: pin value
   cannot change. But note the second `reanchor_pin` call
   in an honest caller now races its own adoption of the
   first: if the first was adopted, (1)'s binding/history
   guards refuse the second locally. Flagged as a known,
   bounded behaviour — not silently unspecified.

---

## 5. (a) Payload projection — `ceremony_authorisation_payload`

In `signing/ceremony_authorisation.py`, replace:

```python
if old_pin is None and reason not in _NO_PIN_REASONS: refuse
if old_pin is not None and reason != REASON_CHAIN_GAP_RECOVERY: refuse
```

with §1.3's rule:

```python
if old_pin is None and reason not in (
        _NO_PIN_REASONS | _EITHER_PIN_REASONS):
    raise SigningError(f"reason {reason!r} requires an old pin")
if old_pin is not None and reason not in (
        {REASON_CHAIN_GAP_RECOVERY} | _EITHER_PIN_REASONS):
    raise SigningError("an authorisation carrying an old pin "
                       "must use reason chain_gap_recovery or "
                       "burned_unadopted")
```

Everything else in the projection is unchanged and applies
to `burned_unadopted` as written: the gap-only check for
with-pin envelopes, evidence ≠ candidate hash, evidence ≠
old-pin hash, TTL bounds. The projection remains a pure
function — it validates *coherence*, not the burn; the burn
proof is the verifier modes' job (§3, §4), exactly as
evidence *resolution* is the verifier's job today while the
projection only form-checks the hash.

`sign_ceremony_authorisation` and
`verify_ceremony_authorisation` need no changes (they go
through the projection). No dataclass field changes.

---

## 6. (d) `reanchor_pin` and (e) `verify_ceremony_record`

### 6.1 `reanchor_pin` (signing/pin_ceremony.py)

Local role only — `reanchor_pin` cannot read the verifier's
journals (standing limit M5), so it proves *shape and
eligibility*, never the burn. The burn proof lives at the
verifier (§3, §4); the envelope binding (step 4 of
`reanchor_pin`) ties this ceremony to the envelope the
verifier issued *as* a recovery.

Changes, in the function's existing order:

1. Gate-on-state block (`old_pin is not None`): allow
   `reason in {REASON_CHAIN_GAP_RECOVERY,
   REASON_BURNED_UNADOPTED}`; refusal message updated
   ("with an existing pin the ceremony reason must be
   chain_gap_recovery or burned_unadopted"). All other
   present-pin reasons still refuse — `lost_pin` with a
   readable pin stays a lie and stays refused.
2. Relation checks (`_candidate_relation`): unchanged, and
   they bind the with-pin recovery correctly — candidate
   vs the *unmoved* pin must be `gap`; `same` /
   `same_seq_fork` / `backwards` / `successor` /
   `successor_fork` / `gap_prev_is_pin` all refuse, so a
   recovery envelope cannot ceremony a successor or a fork
   even if one were minted.
3. Strict recomputation: extend the
   `reason == REASON_CHAIN_GAP_RECOVERY` block to also run
   for `burned_unadopted` **when `old_pin is not None`**:
   supplied `strict_reasons` must be exactly `("chain_gap",)`
   and `verify_snapshot_for_state(...)` against the captured
   pin must recompute exactly that. Justification: in the
   had-a-pin case the recovery candidate stands in exactly
   the burned ceremony's relation to the unmoved pin — sole
   `chain_gap` with all bindings passing — so the same
   recomputed eligibility is available and must be required;
   accepting the caller's tuple alone would reopen the
   cycle-16 forgery the recomputation closed. For
   `old_pin is None`, no recomputation (as for the other
   no-pin reasons — there is no pin to recompute against).
   Implementation shape: condition becomes
   `if reason == CHAIN_GAP or (reason == BURNED_UNADOPTED
   and old_pin is not None)`, with the inner
   `old_pin is None` refusal kept for the chain-gap leg.
   The trailing `elif old_pin is None and reason not in
   _NO_PIN_REASONS` becomes `... not in (_NO_PIN_REASONS |
   _EITHER_PIN_REASONS)`.
4. History: `_check_ceremony_history` unchanged — and in
   the honest burn flow it passes, because the burned
   ceremony returned no record (the crash was before
   adoption; a record exists only if `reanchor_pin`
   returned and the caller persisted it). **Named residual:**
   a caller that persisted the record but not the pin
   (ATOMIC-ADOPTION violated, half-adoption) will be
   refused here ("candidate is already a ceremonied
   target") and has no in-band recovery — that state is a
   caller-contract breach, and WS3's single-file atomic
   store (§10) is what makes it unreachable in the
   production wiring. Do not weaken the history check to
   accommodate it.
5. `initial_anchor` empty-history special case: unchanged,
   not applicable to `burned_unadopted`.
6. Consumption invocation: unchanged — exactly once, after
   all local checks; the consumer is the same
   verifier-backed callable. The recovery's own envelope
   burns at *its* consume, per §6.2.
7. Docstring: the cycle-21 crash paragraph gains the honest
   sentence — recovery from a burn is a new ceremony under
   reason `burned_unadopted`, validated by the verifier
   against its consumption journal; `lost_pin` is no longer
   named as the recovery path anywhere. (Several docstrings
   — pin_ceremony module, `CeremonyConsumptionLedger`,
   consume mode — currently say "recovery is a new
   ceremony"; they stay true. The ones naming `lost_pin`
   as the burned-recovery route must be swept.)

### 6.2 Can a burn be recovered twice? — decision

Distinguish the two senses, decide both:

- **Same authorisation twice: never.** The burned
  `authorisation_id` is consumed; the recovery is a new
  authorisation; *it* is consumed once (mode step 5 +
  `append_consumption` single-use). No path re-consumes
  any single envelope. Unchanged from cycle 21.
- **Same target twice: only as a chain, never in
  parallel against a superseded burn.** If the recovery
  itself burns unadopted (crash after its consume commit),
  the head entry is now the *recovery's* consumption —
  same target, same old pin — and a second recovery
  (`burned_unadopted`, new ceremony/evidence/envelope)
  recovers *that* entry. Iterated recovery is therefore
  allowed, one head at a time, each iteration costing a
  full operator-gated issuance with fresh evidence. It
  cannot loop silently (every iteration is journaled in
  both ledgers) and cannot drift (target and old pin are
  pinned by the predicate every time). Recovering the
  *original* burn after an intervening different-target
  consumption is refused (non-head, §2.2.1). I judge
  unbounded-but-fully-audited iteration preferable to an
  arbitrary "one recovery per target" counter: a counter
  would need state the journal doesn't have (a
  recovered-marker — the format-migration problem of
  §2.1), and a legitimate double-crash (burn, recover,
  burn again) is precisely the case a counter would
  brick.

### 6.3 `verify_ceremony_record` (pin_ceremony.py)

Replace the two invariant lines with §1.3's rule:

```python
if record.old_cycle_seq is None \
        and record.reason not in (_NO_PIN_REASONS
                                  | _EITHER_PIN_REASONS):
    reasons.append("invalid_reason")
if record.old_cycle_seq is not None \
        and record.reason not in {REASON_CHAIN_GAP_RECOVERY,
                                  REASON_BURNED_UNADOPTED}:
    reasons.append("invalid_reason")
```

(record stores `old_payload_hash == ""` for the no-pin
shape; presence is keyed on `old_cycle_seq is None`, as
today.) Consequences, checked:

- One-step refusal (`new == old + 1` →
  `not_a_gap_reanchor`): still applies to with-pin
  `burned_unadopted` records — correct, such a record is
  un-issuable (projection gap check) and must not verify.
- Backwards refusal: unchanged.
- **Stated limit:** `verify_ceremony_record` is offline
  and MAC-only. For a `burned_unadopted` record it proves
  the key holder issued a record with a coherent
  reason/pin shape — it does **not** prove a burn existed.
  Burn linkage at audit time is: record →
  `authorisation_id` (the recovery's own, bound in the
  record) → issuance + consumption journals → the
  preceding head entry is the burn the verifier matched.
  The docstring must say this, so nobody upgrades record
  verification into burn verification by implication.

---

## 7. Refusal summary

| site | condition | refusal |
|---|---|---|
| projection / authorise cheap checks | `burned_unadopted` coherence violated (there is no such case — it admits both shapes; other reasons' rules unchanged) | `SigningError` / `malformed_request` |
| authorise (5b) | no head burn matching (target, old pin); journal unreadable | `ceremony_recovery_unproven` (new, exit-3); `ledger_failed` |
| consume step (5)/(append) | recovery envelope's own `authorisation_id` already consumed | `ceremony_already_consumed` (existing) |
| consume step (7) | `burned_unadopted` but predicate false at consume time (head moved / target ≠ head) | `ceremony_already_consumed` or `ceremony_head_regression` (existing mapping) |
| `reanchor_pin` | present pin + reason ∉ {chain_gap, burned_unadopted}; with-pin recovery failing relation or strict recomputation; envelope binding mismatch | `SigningError` (existing style) |
| `verify_ceremony_record` | reason/pin-shape incoherence incl. new reason in wrong shape (none — both shapes legal; e.g. `lost_pin` with pin present still invalid) | `invalid_reason` (existing) |

New public names, complete list: `REASON_BURNED_UNADOPTED`
(both signing modules), `_EITHER_PIN_REASONS` (both,
drift-tested), `CeremonyConsumptionLedger.match_head_burn`,
refusal code `ceremony_recovery_unproven`. Nothing else.

---

## 8. Claim wording (mandatory form)

> Recovery from a consumed-but-unadopted ceremony is a new
> ceremony under reason `burned_unadopted`, proven by the
> verifier — at authorise and again at consume — against
> its consumption journal's head entry: the recovery's
> candidate and old pin must exactly equal the head
> entry's recorded target and old pin. The original
> consumption stays burned; the recovery consumes its own
> envelope under the ordinary single-use and head rules
> with one scoped exception (re-consumption of the exact
> head target under the exact head old pin). The verifier
> cannot observe pin adoption; under the production
> wiring (fresh pin, complete history, atomic adoption)
> an adopted target cannot be recovered, because the
> recovery envelope cannot bind to the adopted pin and
> the adopted target is already a ceremonied target in
> history. Outside that wiring the worst case is a
> redundant, fully journaled re-consumption of the
> identical target — never a different, forked or
> backwards movement. All of it inherits cycle 21's
> intact-verifier-home scoping until WS2 lands (§9).

`lost_pin` keeps its true meaning (pin actually lost) and
remains available for it; nothing in this design relabels
any other scenario.

---

## 9. Tests (specification)

Unit:

- **Vocabulary/drift:** `REASONS` mirrors equal and contain
  `burned_unadopted`; `_NO_PIN_REASONS` mirrors equal and do
  **not**; `_EITHER_PIN_REASONS` mirrors equal.
- **Projection:** `burned_unadopted` with old pin (gap
  candidate) projects; with `None` projects; with-pin
  one-step candidate refuses (gap check); evidence ==
  candidate/old hash refuses; every pre-existing reason's
  coherence outcomes unchanged (regression pin).
- **`match_head_burn`:** empty journal → None; target match
  + old match (both shapes, incl. `""`/None encoding) →
  head entry; target-only match with wrong old → None;
  matching entry at non-head position → None.
- **`check_head`:** recovery envelope vs its burn head →
  passes; same envelope with reason relabelled
  `chain_gap_recovery` → `AlreadyConsumedError` (the label
  alone, backed by the predicate, is what unlocks);
  `burned_unadopted` with candidate == head seq but
  different hash → `HeadRegressionError`;
  `burned_unadopted` for a non-head burn →
  `HeadRegressionError`; ordinary envelope behaviour
  byte-identical across the existing table (regression).
- **`reanchor_pin`:** with-pin recovery happy path
  (recomputed `("chain_gap",)` required — a supplied tuple
  that doesn't match recomputation refuses); no-pin
  recovery happy path; recovery with a history containing
  the target (half-adoption simulation) refuses; consumer
  invoked exactly once, zero times on local refusals
  (existing spy discipline).
- **`verify_ceremony_record`:** genuine records of both
  recovery shapes verify `()`; one-step with-pin recovery
  record → `not_a_gap_reanchor`; hand-MACed record with
  `lost_pin` + old pin present still → `invalid_reason`.

Subprocess e2e (real verifier, `test_trust_ceremony_*`
pattern):

1. **Happy path after a real burn, had-a-pin:** authorise
   chain-gap envelope → `reanchor_pin` with a consumer
   whose consume commits at the verifier but whose caller
   then "crashes" (no adoption — the T-Cc commit-then-raise
   harness shape) → pin unchanged → authorise recovery
   (new ceremony_id, new evidence) → consume succeeds →
   pin adopts `T`; journals show burn, recovery issuance,
   recovery consumption in order.
2. **Happy path, no-pin:** same with a `lost_pin` burn and
   `old_pin=None` recovery.
3. **Forgery: no burn recorded** — authorise
   `burned_unadopted` against an empty consumption journal
   → `ceremony_recovery_unproven`; no envelope returned.
4. **Forgery: burn for a different target** — burn target
   `T1`; recovery aimed at `T2` → `ceremony_recovery_unproven`.
   Recovery aimed at `T1` with a different old pin → same
   code (assert the code is identical — no oracle).
5. **Burn already recovered (chain):** burn → recovery
   burns unadopted again → second recovery succeeds;
   burn → recovery **adopted** → honest second recovery
   attempt refuses locally (binding/history) before any
   consume; burn → different-target consumption lands →
   recovery of the original burn refuses at authorise
   (`ceremony_recovery_unproven`) and, if an envelope was
   minted before the intervening consume, at consume
   (`ceremony_head_regression`).
6. **Recovery envelope consumed twice:** second consume →
   `ceremony_already_consumed`; also replay across fresh
   clients (existing replay discipline).
7. **Race:** two recoveries authorised for one burn, both
   consume — assert the §4.4.5 outcome is the *specified*
   one (both journaled, same target; pin value unchanged)
   so the behaviour is pinned by test, not discovered.

---

## 10. WS2 critique — the mirror gap (design-together)

**The gap:** consume commits to `ceremony-consumptions.json`
(unanchored), then mirrors into the signing ledger
(anchored, via `_update_anchor`). Mirror failure ⇒ a burn
that exists only in the unanchored journal; a verifier-home
rollback then erases it and resurrects a still-valid
(within-TTL) envelope. Gemini is right that cycle 21's
exception only covered consumptions that *reached* the
mirror.

**Obvious approach A — make the signing-ledger mirror the
commit point (restructure).** I argue this fails on its own
terms:

- The signing ledger's entry shape cannot carry the
  consumption record: EXTRA_KEYS has no
  old/new target or evidence fields, and widening it is
  the format migration `CeremonyAuthorisationLedger`'s
  docstring already rejected once. `check_head` needs
  those fields; a mirror-first commit would create
  consumptions the head cannot be computed from.
- Two files have no atomic commit; reordering doesn't
  remove the window, it flips its direction: mirror-first
  leaves a signing-ledger "consume" entry with no journal
  entry — and consume step (5)'s mirror cross-check would
  then refuse the envelope as already-consumed while the
  head journal denies it: a burn with no head, which
  corrupts every later head decision, not just this one.
- Authority inversion: cycle 21 deliberately made the
  consumption journal the authority and the mirror an
  audit copy. Restructuring re-litigates
  DECISION-CONSUMPTION-HEAD for a strictly worse failure
  shape.

**Obvious approach B — anchor the consumption journal
itself.** This is my recommendation, and it is the smaller
idea: add `"ceremony-consumption"` (and, jointly,
`"ceremony-authorisation"` for the issuance journal — the
already-named `ceremony-journal-anchoring` follow-up) to
`trust/anchoring.py`'s `ANCHOR_KINDS`, with anchor files
**outside** the verifier home (the existing placement rule
in anchoring.py: an anchor beside the journal is a second
copy, not a pin), updated at the consume commit
(`_update_anchor`-analogue called where the mode currently
calls `_update_anchor(config)` for the signing ledger) and
**verified before the journal is trusted** — at minimum at
consume/authorise read time: a `verify_anchor` mismatch
(chain-mismatch reasons) ⇒ `ledger_failed`, fail-closed,
never scan a rolled-back journal and proceed.

Costs/risks of B, honestly: a second anchor path in
verifier config (today `_Config` carries one
`anchor_path`); anchor-update failure after the journal
append reproduces the commit-then-fail shape one level up
(burned, `ledger_failed`, no success response — the
existing philosophy, and strictly better than silent
resurrection because the journal entry *survives* and the
anchor disagreement is detectable, not erasable);
research mode (no anchor configured) keeps the residual
and must keep saying so.

**Interaction with WS1 — the reason B must land with or
before WS1's claim is upgraded:** §3's burn proof reads
the consumption journal. Under rollback today:

- a rolled-back journal can *erase* a burn → recovery
  refuses (`ceremony_recovery_unproven`) — fail-closed,
  liveness loss only;
- worse, a rollback to *before* a recovery's consumption
  resurrects the recovery envelope (same class as WS2's
  original defect) and rewinds the head under WS1's
  predicate, so `match_head_burn` would match a stale
  head. WS1 does not widen this hole (the predicate only
  reads the head the journal presents), but WS1's claim
  must carry the intact-home scoping (§8) until B lands.
  With B, the burn proof inherits rollback *detection*:
  authorise (5b) and consume (5)/(7) must run the journal
  anchor verification as part of "journal could be read",
  or WS1 builds a proof on an unverified journal.

Sequencing view: B (journal anchoring) first or together;
WS1's predicate is unchanged either way — anchoring
changes how much the entries can be trusted, not what
they must say.

---

## 11. WS3 critique — first production adopter (design-together)

**Obvious approach A — wire `reanchor_pin` inside
`core/loop.py`'s cycle path.** Wrong home: `CoreLoop` owns
`state/state.json` and knows nothing of snapshots, pins or
verifiers; embedding ceremony wiring there couples the
generic loop to one consumer and makes the pin logic
untestable outside a full loop run.

**Obvious approach B — a pin store in `signing/`** —
my recommendation: new module **`signing/pin_store.py`**,
beside the ceremony it serves (the pin, the history and
`advance_pin`/`reanchor_pin` are all `signing/` concepts;
`core/` and any loop/storage caller consume it). Shape:

```python
class SnapshotPinStore:
    """Owns ONE file: {pin, ceremony_history: [record, ...]}
    in the caller's state dir (NOT inside state.json — the
    pin must never live inside the snapshot it pins)."""
    def read_pin(self) -> dict | None          # fresh, per attempt (FRESH-PIN)
    def history(self) -> tuple[PinCeremonyRecord, ...]
    def adopt(self, new_pin, record) -> None   # ATOMIC-ADOPTION, below
    def advance(self, new_pin) -> None         # advance_pin path, same file
```

plus one orchestration function (in the same module or a
thin loop-side caller) that runs the production wiring
end-to-end: snapshot `state/state.json` via
`signing/state_snapshot.py` (`sign_state_files`) →
`classify_verification` → `ok`: `advance_pin` + `advance`;
`reanchor_required`: `VerifierClient.ceremony_authorise`
→ `reanchor_pin(..., consume_authorisation=
client.ceremony_consumer(), ceremony_history=
store.history())` → `store.adopt(new_pin, record)`;
`integrity_failure`: stop.

**What "atomic adoption" must mean** (today ATOMIC-ADOPTION
is a caller duty `reanchor_pin` cannot verify — the
adopter is where it becomes a mechanism, and the design
must not let it stay a slogan):

- Pin and record persist in **one file, one rename**: write
  temp in the same directory → fsync file → `os.replace` →
  fsync directory. The pattern already exists twice in-tree
  (`HashChainJournal._save`; `CoreLoop.save`,
  core/loop.py ~304) — reuse its shape, don't invent a third.
- Two files (pin file + history file) is **not** atomic
  adoption: the crash window between the renames is exactly
  the half-adoption state §6.1.4 shows is unrecoverable
  in-band. One document or it doesn't count.
- Adoption happens **before** any further `advance_pin` or
  ceremony reads the store, and a failed adoption write
  leaves the on-disk (pin, history) pair at its previous
  value — the pin is then unmoved with the envelope
  burned, i.e. precisely the WS1 scenario, recoverable
  under `burned_unadopted`. The adopter and WS1 are each
  other's justification: WS3 will still crash someday;
  WS1 is what makes that crash honestly recoverable.
- The store must refuse (not repair) a malformed pin file
  on read: a torn/corrupt store is the `corrupted_pin`
  ceremony's input, not a silent reset to `None` (which
  would launder corruption into an `initial_anchor`).

Risks: the store file becomes a new rollback target (a
caller-side rollback of (pin, history) together reopens
the §4.4.1 residue — already the documented class;
anchoring the pin store is future work, do not gold-plate
this cycle); record serialisation needs a
`PinCeremonyRecord` ↔ dict round-trip that does not exist
yet (envelope serialisation in `ceremony_authorisation.py`
is the pattern; records must round-trip through
`verify_ceremony_record` on load or the store refuses).

---

## 12. Open risks / honest flags

1. §4.4.1 is the design's centre of gravity: non-adoption
   is not verifier-provable. The exception is safe against
   *movement* abuse by construction (target + old pin +
   hash all pinned to the head entry) and against honest
   callers by binding + history; the residue is a redundant
   identical-target ceremony by a caller already violating
   two documented obligations with an allowlisted operator
   id. If the war room wants more, the only real upgrade is
   a pin-store CAS / adoption receipt — named future work
   since cycle 21, not smuggled in here.
2. WS1 without WS2 keeps the intact-home scoping. Shipping
   WS1's wording without §8's qualifier would repeat the
   cycle-21 over-claim pattern.
3. Authorise-time proof makes `ceremony_authorise` read a
   second journal; deployments with a corrupt consumption
   journal now refuse recoveries (fail-closed, intended)
   but also — check during build — must not refuse
   *ordinary* authorisations: step (5b) runs only for
   `reason == burned_unadopted`. Ordinary issuance must not
   gain a new failure dependency.
4. TTL pressure is unchanged but worth restating for
   recovery UX: burn → new evidence artefact → authorise →
   consume must fit operator workflow, though each envelope
   gets its own fresh 900 s; the *burned* envelope's expiry
   is irrelevant to the predicate (the journal entry, not
   the envelope, is the proof — an expired-and-consumed
   envelope's burn is still recoverable days later; that
   is deliberate: the crash may be discovered late).
