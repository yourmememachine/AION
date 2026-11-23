# Cycle 24 — Design B (Seat B): Item 3 — Supersede Option A

**Explicit, separately authorised, journaled supersession decisions**

Mandate: `internal/CROSS-CHECK-17.md` — seat-gpt FIX 0.96 on the
cycle-23 supersede rule. Today, `CeremonyConsumptionLedger.check_head`
(`trust/ledger.py`) permits a fresh primary whose candidate is
strictly ahead of the consumed head to carry an old pin behind the
head; the burned head movement is abandoned with **no explicit
authorisation for the abandonment**. Option A (chosen; B and the
prose route are rejected in §10) requires: a separately authorised,
journaled supersession decision that **identifies the burned
movement being abandoned** and **binds the decision to the newer
candidate**. Seat-gemini accepted the broad rule provided pin-store
context binding stays mandatory — this design does not touch
`PinStore.adopt`; that condition stands unchanged.

Design only. No production code is written here. All signatures,
field names, codes and test names below are the contract for the
build seats.

---

## 0. Shape of the solution, in one paragraph

A new verifier mode `ceremony_supersede` is the only way to create
a supersession decision. The requester presents an **operator id**
and the **new envelope** (the fresh primary that wants to pass the
behind-head old pin) — never the identity of the movement to be
abandoned. The verifier derives the abandoned movement from **its
own consumption journal's head entry**, checks the supersede shape
holds exactly (§3), and commits a decision entry to a new
hash-chained journal `ceremony-supersessions.json`
(`CeremonySupersessionLedger`, §4) in the verifier home. The
decision binds: the abandoned head entry's `authorisation_id` and
its full (old → new) pair, the new envelope's `authorisation_id`,
the new envelope's candidate `(cycle_seq, payload_hash)`, the new
envelope's old pin, and the `operator_id`. Later,
`_mode_ceremony_consume` looks the decision up **from its own
journal, keyed by the presented envelope's `authorisation_id`**
(the caller never supplies it — the `recovery_of` threading
precedent) and threads it into `check_head` /
`append_consumption`. Inside the supersede branch, a missing
decision raises a new `SupersedeRequiredError`, which the consume
mode maps to a new distinct post-verification state-refusal code
`ceremony_supersede_required`; a present-but-misbound decision
raises `HeadRegressionError` as today. `PinAdopter._reanchor`
catches exactly that code (via a structured client error
attribute, §6), requests the decision once, and re-runs
`reanchor_pin` once with the **same** envelope — sound because
the first consume refused **pre-commit** (§7).

No new environment variable, no allowlist change, no journal
format migration: the consumption journal's schema v2 is
untouched, the issuance journal is untouched, and the decision
journal is a new sibling file (the `CeremonyAuthorisationLedger`
precedent for why a sibling file, not a widened existing journal).

---

## 1. Who identifies the abandoned movement — the verifier

The requester presents only the new envelope. The abandoned
movement is, by construction of the supersede branch, **the
consumption journal's current head entry**: `check_head`'s branch
fires only against `entries[-1]`, the burn being abandoned is the
head movement, and no other entry can be the one abandoned (any
older entry is already behind a later head; abandoning it is
meaningless). Letting the requester name the abandoned movement
would add a request field the verifier must then cross-check
against its own head anyway — pure attack surface (a requester
could name a *different*, still-adoptable burn and launder its
abandonment under an unrelated candidate) for zero information.
So:

- The supersede request body carries **no** abandoned-movement
  field (§2).
- `_mode_ceremony_supersede` reads the head entry from its own
  `CeremonyConsumptionLedger(config.home).entries()` and copies
  the abandoned binding out of that entry at decision time.
- `check_head` re-derives the same identification at consume
  time: the decision is valid only if its abandoned binding
  equals the **then-current** head entry (§5). A decision minted
  against head *H* is inert once the head moves past *H* — it
  cannot be replayed against a later head.

This mirrors the system's standing rule that bindings are
computed by the verifier from its own journals, never read from
the request: authorise step (5b) computes `recovery_of` from
`match_head_burn`; consume threads it from the issuance entry.
The supersession decision is the same pattern, one journal over.

---

## 2. New verifier mode: `ceremony_supersede`

File: `trust/verifier_main.py`. Registered in `_MODES` as
`"ceremony_supersede": _mode_ceremony_supersede`. New strict key
set beside `_CEREMONY_BODY_KEYS`:

```python
_CEREMONY_SUPERSEDE_BODY_KEYS = {"operator_id", "signed_authorisation"}
```

Body shape (the `ceremony_consume` wire precedent — the envelope
rides under `signed_authorisation`):

```json
{"operator_id": "<id>", "signed_authorisation": { ...envelope dict... }}
```

There is deliberately **no** evidence field, **no** ceremony_id
field outside the envelope, and **no** abandoned-movement field
(§1). The decision is not a signed artefact: like a consumption,
it is a verifier act recorded in a hash-chained journal in the
verifier home; the mode returns an unsigned receipt (§2.1). The
"separately authorised" element is the operator presentation
checked against the verifier's protected allowlist — exactly the
provenance level `ceremony_authorise` itself provides (operator-id
allowlist eligibility via the launch channel, not authentication;
the mode's docstring must carry that wording verbatim in
substance, as every ceremony mode does).

### 2.0 Validation order (numbered; mirror authorise/consume discipline)

1. **Config gates, before body validation** (authorise step 1):
   - `config.ceremony_operators` empty →
     `_config("ceremony_operators_unconfigured", ...)` — the mode
     needs the allowlist because it checks membership.
   - `config.ceremony_signing_key is None` →
     `_config("ceremony_seed_unconfigured", ...)` — the mode
     needs the seed-derived public key to verify the envelope
     (consume step 1 precedent).
   - The evidence configuration is **not** a gate: no evidence is
     resolved, read or retained by this mode.
2. **Strict key set**: `set(body) != _CEREMONY_SUPERSEDE_BODY_KEYS`
   → `_malformed("malformed_request", ...)`. Exit 2, no journal
   touched.
3. **Cheap validation**: `operator_id` via `_check_id` →
   `malformed_request`; envelope parse via
   `ceremony_authorisation_envelope_from_dict` → `SigningError`
   maps to `malformed_request` (consume step 3 precedent). Pure
   value work; no filesystem, no journal read yet — a malformed
   request can never create, or be refused by, journal state.
4. **Operator membership** (authorise step 3 — before any journal
   read, so an unlisted operator cannot make this process open a
   journal file and gets no state oracle):
   `operator_id not in config.ceremony_operators` →
   `_config("ceremony_operator_not_authorised", ...)`. Unsigned,
   unledgered.
5. **Envelope verification — single-code, no-oracle** (consume
   step 4, byte-for-byte discipline):
   `verify_ceremony_authorisation(signed, public_key=
   ceremony_public_key_for(config.ceremony_signing_key),
   expected_signer_id=config.signer_id,
   expected_operator_id=operator_id)`. Passing
   `expected_operator_id` folds an envelope-for-a-different-
   operator into the same reason vocabulary as every other
   verification failure. Any non-empty reasons:
   - `set(reasons) <= {"expired", "signed_in_future"}` →
     `_config("ceremony_authorisation_expired", ...)` (the
     documented temporal carve-out, identical to consume);
   - otherwise `_malformed("ceremony_authorisation_invalid",
     ...)` — one code, no per-reason output anywhere including
     stderr (the consume step-4 comment applies verbatim: the
     client embeds stderr excerpts in exception messages).
6. **Already-consumed check for the new envelope** (consume
   step 5, both scans): authorisation_id present in the
   consumption journal, or a signing-ledger entry scoped to
   `kind == "consume" and format == "ceremony-consumption"` with
   `decision_id == signed.authorisation_id` →
   `_config("ceremony_already_consumed", ...)`. A consumed
   envelope needs no decision and must never acquire one
   retroactively (a post-hoc decision would falsify the audit
   order: decision first, consumption second). Journal read
   failure → `_config("ledger_failed", ...)` (fail closed, never
   scan partial state).
7. **Issuance presence** (consume step 6):
   `CeremonyAuthorisationLedger(config.home).
   find_by_authorisation_id(signed.authorisation_id)`; `None`,
   or `payload_hash` / `ceremony_id` / `evidence_hash` mismatch
   against the envelope → `_config("ceremony_not_issued", ...)`.
   An envelope the verifier never issued cannot ground a
   decision. Read failure → `ledger_failed`.
8. **Supersede shape — the "only when actually needed" gate**
   (§3). Every predicate failure raises the **single** code
   `_config("ceremony_supersede_unproven", ...)` — the
   authorise-(5b) `ceremony_recovery_unproven` precedent: one
   post-verification state code, no sub-case detail in the
   message, because distinguishing "candidate not ahead", "old
   pin not behind", "hash binding failed" and "decision already
   exists" would hand a presenter a journal-state oracle. This
   step includes the **no-prior-decision** check:
   `CeremonySupersessionLedger(config.home).
   find_by_new_authorisation(signed.authorisation_id)` is not
   `None` → `ceremony_supersede_unproven`. (Re-deciding an
   envelope that already has a decision is gratuitous; the
   existing decision is already usable by consume. A caller that
   lost the receipt does not need a second decision — consume
   looks the decision up itself, §5.)
9. **Commit**: `CeremonySupersessionLedger(config.home).
   append_decision(abandoned_entry=head_entry, signed=signed,
   recorded_at=_now())` (§4). `LedgerError` from the append's
   reload-recheck (a competitor decision for the same envelope
   landed between step 8 and here) → `ceremony_supersede_unproven`
   is **wrong** for that race (the shape was proven); map append
   `LedgerError` → `_config("ledger_failed", ...)` with the
   detail stating a decision may now exist for this envelope and
   consumption may proceed against it — consume is the retry
   surface, not a second supersede call. Any other exception →
   `ledger_failed`.
10. **Signing-ledger mirror + signing anchor** (§4.3):
    `SigningLedger(config.home).append_ceremony_supersession(
    decision_entry, signed=signed, recorded_at=recorded_at)`,
    then `_update_anchor(config)`. Mirror failure after the
    commit → `ledger_failed` with the consumption-mode mirror
    wording adapted: "the supersession decision was committed
    in the supersession journal but could not be mirrored in
    the signing ledger; the decision stands and no receipt is
    returned — consumption may proceed against the journaled
    decision". The decision is **not** rolled back and the mode
    never re-appends it.

Return value (receipt; echoed and validated client-side, §6):

```python
{"abandoned_authorisation_id": head_entry["authorisation_id"],
 "new_authorisation_id": signed.authorisation_id,
 "candidate_cycle_seq": signed.candidate["cycle_seq"],
 "candidate_payload_hash": signed.candidate["payload_hash"],
 "supersession_seq": decision_entry["seq"]}
```

### 2.1 What the mode does NOT do

- It does not consume anything, sign anything, or return the
  decision entry itself. The receipt names the decision; the
  decision lives only in the verifier's journal.
- It does not check evidence, the operator's evidence, or the
  pin store. Adoption-side context binding remains the control
  for the pin itself (seat-gemini's condition, unchanged).
- It is not idempotent and has no "already decided → success"
  path: step 8 refuses a second decision for the same envelope.

---

## 3. The supersede shape (single source of truth)

Add one static predicate to `CeremonyConsumptionLedger` in
`trust/ledger.py`, used by the supersede mode (step 8),
documented as the definition `check_head`'s branch implements:

```python
@staticmethod
def supersede_head(entries, signed):
    """Return the head entry iff consuming ``signed`` against
    ``entries`` would enter the supersede branch, else None."""
```

It returns `entries[-1]` iff **all** of:

- `entries` is non-empty;
- `signed.reason != "burned_unadopted"` (a recovery envelope
  never supersedes — cycle-23 r1-F2, unchanged);
- the lineage `_derive_lineage(entries, signed, recovery_of)`
  would not be `"recovery"` — in the mode, `recovery_of` is the
  issuance entry's value threaded exactly as consume threads it
  (`issued.get("recovery_of")`, with the §8 conversion applied);
  in practice a `burned_unadopted`-only derivation makes this
  implied by the previous clause, but the predicate states it so
  the mode and `check_head` cannot drift;
- `signed.old_pin is not None`;
- `signed.candidate["cycle_seq"] > head["new_cycle_seq"]`
  (candidate **strictly ahead** of the head);
- `signed.old_pin["cycle_seq"] < head["new_cycle_seq"]`
  (old pin **behind** the head);
- the journal-known old-pin hash binding holds (the r1-F2 rule
  already in `check_head`): collect every hash recorded for
  `old_pin["cycle_seq"]` — each entry's `new_payload_hash` where
  `new_cycle_seq == old_seq`, each entry's `old_payload_hash`
  where `old_cycle_seq == old_seq` (skipping the empty-string
  no-pin spelling) — and if that set is non-empty,
  `signed.old_pin["payload_hash"]` must be in it.

`check_head`'s supersede branch is refactored to use the same
two sub-checks in its existing order (candidate position first,
then hash binding, then — new — the decision binding, §5); the
build seats must keep the branch's *other* refusal outcomes
byte-identical: candidate at/behind head with a behind-head old
pin still raises `HeadRegressionError("old pin is behind the
consumed head")` **before** any decision question arises, so a
non-supersede shape can never elicit `ceremony_supersede_required`.

**No gratuitous decisions** is therefore structural, not
advisory: outside this exact shape the mode refuses at step 8,
and inside consume the branch is unreachable. In particular a
decision can never be minted for: an empty journal, a candidate
at/behind the head, an old pin at/ahead of the head, a
`burned_unadopted` envelope, an envelope whose old-pin hash is
fabricated at a journal-known sequence, an unissued envelope, a
consumed envelope, or an envelope that already has a decision.

---

## 4. New journal: `CeremonySupersessionLedger`

File: `trust/ledger.py` (new class beside
`CeremonyAuthorisationLedger` / `CeremonyConsumptionLedger`);
file name in the verifier home: **`ceremony-supersessions.json`**.

```python
class CeremonySupersessionLedger(HashChainJournal):
    FILENAME = "ceremony-supersessions.json"
    EXTRA_KEYS = frozenset({
        "abandoned_authorisation_id", "abandoned_ceremony_id",
        "abandoned_old_cycle_seq", "abandoned_old_payload_hash",
        "abandoned_new_cycle_seq", "abandoned_new_payload_hash",
        "new_authorisation_id", "new_ceremony_id",
        "operator_id",
        "superseding_old_cycle_seq", "superseding_old_payload_hash",
        "candidate_cycle_seq", "candidate_payload_hash",
        "decided_at"})
```

Entry semantics (kind is `"supersede"` for every entry):

| field | source |
|---|---|
| `abandoned_authorisation_id` | head entry's `authorisation_id` — the burned movement being abandoned |
| `abandoned_ceremony_id` | head entry's `ceremony_id` (audit readability) |
| `abandoned_old_cycle_seq` / `abandoned_old_payload_hash` | head entry's `old_cycle_seq` / `old_payload_hash` (the abandoned pair's old side; seq may be `None`, hash `""` for a no-pin head) |
| `abandoned_new_cycle_seq` / `abandoned_new_payload_hash` | head entry's `new_cycle_seq` / `new_payload_hash` (the abandoned pair's new side == the head target) |
| `new_authorisation_id` | `signed.authorisation_id` — the envelope the decision authorises to pass |
| `new_ceremony_id` | `signed.ceremony_id` |
| `operator_id` | `signed.operator_id` (== the mode's body `operator_id`, enforced by step-5 `expected_operator_id`) — the operator who presented the abandonment for authorisation |
| `superseding_old_cycle_seq` / `superseding_old_payload_hash` | `signed.old_pin` projected — the pin the new movement claims to move from |
| `candidate_cycle_seq` / `candidate_payload_hash` | `signed.candidate` projected — the newer candidate the decision binds to |
| `decided_at` | `recorded_at` (the `consumed_at` / `issued_at` precedent: the domain timestamp duplicates the base `recorded_at`) |

### 4.1 Methods

```python
def find_by_new_authorisation(self, authorisation_id):
    """Reload, return the decision entry dict for this
    new_authorisation_id, or None."""

def append_decision(self, *, abandoned_entry, signed,
                    recorded_at) -> dict:
    """Append one decision as kind "supersede"."""
```

`append_decision` follows `append_authorisation`'s
reload-recheck pattern exactly: bounded retry over
`_APPEND_RETRY_ATTEMPTS`; on every attempt `_reload()`, then
re-check **single-decision-per-envelope** against the freshly
loaded entries — any entry with
`new_authorisation_id == signed.authorisation_id` raises
`LedgerError("supersession already decided for authorisation:
...")` — then `_append(...)` with all fields copied from
`abandoned_entry` / `signed` (never from a request-side dict);
`CorruptLedgerError` from `_save`'s freshness check retries, so
two concurrent supersede calls for the same envelope yield
exactly one decision and one `LedgerError`. Type gate:
`isinstance(signed, SignedCeremonyAuthorisation)` else
`LedgerError` (the other ceremony ledgers' precedent);
`abandoned_entry` must be a consumption entry dict carrying the
keys copied above, else `LedgerError`.

Deliberately **not** enforced at append: one decision per
*abandoned* movement. Two different fresh envelopes may each
legitimately receive a decision abandoning the same head (the
first envelope may expire unconsumed inside its 900 s TTL; the
second is then the live one). Stale decisions are made inert by
the consume-side binding to the *current* head (§5), not by an
append-side uniqueness rule that would deadlock the expiry case.

### 4.2 Load-time validation

Override `_load` (the consumption/authorisation v2 precedent —
base chain validation first, then coherence), raising
`CorruptLedgerError` when:

- a `new_authorisation_id` occurs twice (single-decision at
  load, mirroring the consumption journal's duplicate-
  authorisation rule);
- any id field (`abandoned_authorisation_id`,
  `new_authorisation_id`) is not a 64-char lowercase hex string;
  any hash field that is not `""` is not 64-char lowercase hex;
- `candidate_cycle_seq` is not an `int` (bool excluded) or
  `candidate_cycle_seq <= abandoned_new_cycle_seq` (a decision
  whose candidate is not strictly ahead of the abandoned target
  is incoherent — the append path can never write one);
- `superseding_old_cycle_seq` is not an `int` (bool excluded) or
  `superseding_old_cycle_seq >= abandoned_new_cycle_seq`
  (the superseding old pin must be behind the abandoned head);
- `abandoned_new_cycle_seq` is not an `int` (bool excluded)
  or `< 0`; `abandoned_old_cycle_seq` is neither `None` nor an
  `int >= 0`; `operator_id` / ceremony ids are not non-empty
  strings.

No schema versioning: this journal is born at its final shape
in cycle 24; there are no v1 entries to grandfather.

### 4.3 Signing-ledger mirror — YES; dedicated anchor — NO

**Mirror: yes.** Add to `SigningLedger` (existing entry shape,
`EXTRA_KEYS` untouched — no format migration):

```python
def append_ceremony_supersession(self, decision_entry, *,
                                 signed, recorded_at) -> dict:
```

Column reuse, documented in its docstring exactly as
`append_ceremony_consumption` documents its own: kind
`"supersede"`, format `"ceremony-supersession"`,
`decision_id = signed.authorisation_id`,
`payload_hash = signed.payload_hash`,
`purpose = "pin-ceremony-supersession"`,
`proposal_id = signed.ceremony_id`, `accepted = False`,
`signer_id = signed.signer_id`. Rationale: the signing ledger is
externally anchored, so the mirror gives every decision an
anchored audit trace ("a decision was recorded for this
envelope") at zero format cost — the same reason consumptions
are mirrored. Cross-checks must scope to
`kind == "supersede" and format == "ceremony-supersession"`;
the docstring must warn, as the consumption mirror's does, that
the issuance mirror already writes the same `decision_id` under
kind `"sign"`. The mirror is an audit trace only: **no consume
path reads it**, and its absence never grants or refuses a
consumption (authority is §4's journal + §5's binding).

**Dedicated external anchor: no, this cycle.** No new anchor
kind, no new env var (the deployment allowlist stays at 19).
The follow-up `ceremony-journal-anchoring` — already narrowed
to the issuance journal — is extended by the cycle-24 decision
record to cover `ceremony-supersessions.json` as a second file
in the same follow-up.

### 4.4 Rollback position (stated honestly)

- The supersession journal itself is **not** externally
  anchored this cycle. Its rollback position is the issuance
  journal's, not the consumption journal's.
- Rolling back the **whole verifier home** also rolls back the
  consumption journal, whose anchor (when configured, required
  in production with the ceremony seed) refuses startup
  (`anchor_refused`) for any consumption whose anchor update
  completed — so a whole-home rollback cannot silently restore
  a pre-decision world *and* keep consuming.
- Rolling back **only** `ceremony-supersessions.json`:
  - to an earlier prefix: decisions vanish → consume refuses
    `ceremony_supersede_required` → **fails closed**; the
    operator simply presents the envelope to
    `ceremony_supersede` again (the per-envelope uniqueness
    check lives in the same rolled-back file, so re-deciding
    is possible and correct).
  - to a state containing a decision for a *different* envelope:
    inert — §5 binds the decision to the current head and to
    the presented envelope's id; it cannot be spent by another
    envelope or against a moved head.
- **Forgery, named plainly:** a party with write access to the
  verifier home can rewrite `ceremony-supersessions.json` from
  genesis with a fabricated decision whose hash chain
  self-validates; nothing anchored detects the fabrication
  itself (the signing-ledger mirror detects that *a* decision
  for the envelope was or was not mirrored at a point in the
  anchored history only if the mirror append also happened —
  a forged journal entry with no mirror is indistinguishable
  from a decision whose mirror write failed, §2 step 10).
  This is the same exposure class as the unanchored issuance
  journal, and the same threat-model boundary applies: the
  verifier home is the protected store; a fully malicious
  same-user process is outside the prototype's claim (see
  `trust/verifier_main.py`'s honesty statement). The design
  does **not** claim rollback- or forgery-resistance for the
  decision journal; it claims fail-closed loss and binding
  inertness, above.

---

## 5. Consume-side enforcement

### 5.1 New exception (`trust/ledger.py`)

```python
class SupersedeRequiredError(LedgerError):
    """The supersede shape holds but no journaled supersession
    decision authorises the abandonment. Machine-distinguishable
    ... (see AlreadyConsumedError's mapping contract)."""
    reason = "supersede_required"
```

It subclasses `LedgerError` **directly — not**
`HeadRegressionError`: the consume mode maps the two to
different codes and the adopter acts differently on them (§7),
so they must be distinguishable by type, not by message text.

### 5.2 `check_head` signature and branch

```python
@staticmethod
def check_head(entries, signed, recovery_of=None, *,
               supersede_decision=None) -> None:
```

(`supersede_decision` keyword-only, default `None`: every
existing positional/keyword caller — mode, tests — is
source-compatible, and a direct caller who omits it gets the
new fail-closed behaviour, which is the point.)

Inside the existing supersede branch (after the
candidate-position refusal and after the journal-known hash
binding check — order matters, §3), insert the decision gate.
`supersede_decision` is `None` or a decision entry dict as
returned by `CeremonySupersessionLedger.entries()` /
`find_by_new_authorisation`:

```python
# Supersession decision (cycle 24, Option A): ...
if supersede_decision is None:
    raise SupersedeRequiredError(
        "supersede shape holds but no journaled supersession "
        "decision authorises abandoning the consumed head")
decision = supersede_decision
if decision["abandoned_authorisation_id"] \
        != last["authorisation_id"] \
        or decision["abandoned_old_cycle_seq"] \
        != last["old_cycle_seq"] \
        or decision["abandoned_old_payload_hash"] \
        != last["old_payload_hash"] \
        or decision["abandoned_new_cycle_seq"] \
        != last["new_cycle_seq"] \
        or decision["abandoned_new_payload_hash"] \
        != last["new_payload_hash"] \
        or decision["new_authorisation_id"] \
        != signed.authorisation_id \
        or decision["candidate_cycle_seq"] != cand_seq \
        or decision["candidate_payload_hash"] != cand_hash \
        or decision["superseding_old_cycle_seq"] != old_seq \
        or decision["superseding_old_payload_hash"] != old_hash \
        or decision["operator_id"] != signed.operator_id:
    raise HeadRegressionError(
        "journaled supersession decision does not bind this "
        "envelope to the consumed head it abandons")
```

Binding summary (the task's required five, plus two):
abandoned `authorisation_id` **and** abandoned (old, new) pair
== the current head entry; decision's `new_authorisation_id` ==
`signed.authorisation_id`; decision's candidate `(seq, hash)` ==
`signed.candidate`; decision's superseding old pin ==
`signed.old_pin` (prevents a decision minted for envelope X
being spent by an envelope that reuses X's id with a different
old pin — defence in depth behind the id binding); decision's
`operator_id` == `signed.operator_id`.

A **misbound** decision raises `HeadRegressionError`, never
`SupersedeRequiredError`: a decision exists but does not cover
this consumption — most commonly because the head moved between
decision and consume (a competing consumption landed). Mapping
that to supersede-required would invite the adopter to request
a *second* decision against a head state the first decision's
flow never saw, inside a flow specified as exactly one decision
request (§7). Head-regression is the honest terminal code:
recovery is a fresh ceremony attempt, which re-derives
everything.

### 5.3 `append_consumption` threading

```python
def append_consumption(self, envelope, *, recorded_at,
                       recovery_of=None,
                       supersede_decision=None) -> dict:
```

The retry loop passes `supersede_decision=supersede_decision`
to `check_head` on **every** attempt, against the freshly
reloaded entries — so a head movement between the mode's
pre-check and the commit re-validates the decision against the
new head and refuses (`HeadRegressionError`) rather than landing
on a stale binding. The decision object itself is not re-read
inside the loop: it is a journal entry dict captured by the
mode; if the supersession journal were rolled back mid-flight
the consumption would land on a decision no longer journaled —
accepted and named here: the window requires an active
verifier-home rollback during a single request, the consumption
that lands is itself anchored, and the decision's signing-ledger
mirror (§4.3) preserves the trace. (Re-reading the decision
inside the loop was considered and rejected: it would couple
the consumption commit point to a second journal's freshness
semantics for a window already covered by the mirror.)

### 5.4 Consume mode changes (`_mode_ceremony_consume`)

- New step **(6b)**, immediately after issuance presence (step
  6) and before the head-rules pre-check (step 7): open
  `CeremonySupersessionLedger(config.home)` and
  `decision = ledger.find_by_new_authorisation(
  signed.authorisation_id)`; any exception →
  `_config("ledger_failed", "the supersession journal could
  not be read; refusing to consume from partial state")`.
  The caller never supplies the decision; the body key set is
  unchanged (`{"signed_authorisation"}`).
- Step 7 pre-check: `check_head(consumption_entries, signed,
  recovery_of=bound_recovery_of, supersede_decision=decision)`;
  add, **before** the `HeadRegressionError` handler:
  `except SupersedeRequiredError: raise _config(
  "ceremony_supersede_required", "this consumption would
  supersede the consumed head movement, and no journaled
  supersession decision authorises the abandonment; obtain a
  decision via ceremony_supersede and consume again")`.
- Step 8 commit: `append_consumption(signed, recorded_at=...,
  recovery_of=bound_recovery_of, supersede_decision=decision)`;
  add the same `SupersedeRequiredError` → 
  `ceremony_supersede_required` mapping before the generic
  `except Exception` → `ledger_failed` handler (without it, an
  in-loop supersede refusal would be misreported as
  infrastructure failure). This in-loop raise is still
  **pre-commit**: `check_head` runs before `_append` on every
  attempt, so the code is never emitted after a consumption has
  landed for this envelope.
- The mode docstring's validation-order paragraph gains
  `ceremony_supersede_required` in its enumerated list of
  post-verification state refusals, and step (6b)/(7)/(8)
  wording. The R7 crash-consistency wording gains one sentence:
  a `ceremony_supersede_required` refusal is issued only before
  the commit point and certifies that no consumption of this
  authorisation exists (step 5 has already run).

### 5.5 Why `ceremony_supersede_required` is its own code — the no-oracle taxonomy

The consume mode's documented taxonomy (mode docstring; the
`AlreadyConsumedError` docstring in `trust/ledger.py`): the
no-oracle claim covers **verification failures only** (one code,
`ceremony_authorisation_invalid`). Post-verification **state
refusals** are state oracles *by design* and already distinct:
`ceremony_already_consumed`, `ceremony_not_issued`,
`ceremony_head_regression`, `ceremony_authorisation_expired`.
`ceremony_supersede_required` sits squarely in that class:

- It is reachable **only** by an envelope that passed
  verification, is issued, and is unconsumed — the presenter
  learns nothing about any envelope they could not already
  have consumed up to the head check.
- What it reveals beyond `ceremony_head_regression` is one
  bit — "your envelope's shape is a supersede shape" — which
  the presenter already knows from their own envelope (they
  chose the candidate and old pin) plus the head position that
  `ceremony_head_regression` already reveals. No new oracle
  class is created.
- It **must** be distinct operationally: `head_regression`
  means "new ceremony"; `supersede_required` means "same
  envelope, obtain a decision, consume again" (§7). Collapsing
  them would either deadlock the adopter flow again or force
  the adopter to string-match `HeadRegressionError` messages —
  strictly worse than a documented code.

Exit class: `_config` (exit 3), like every post-verification
state refusal in this mode.

---

## 6. Client: `VerifierClient.ceremony_supersede` + structured refusal codes

File: `trust/client.py`.

### 6.1 Structured code plumbing (the least fragile detection)

Today `_run` embeds the verifier's code only in the exception
**message** (`verifier exit 3 [code]: detail (stderr: ...)`).
String-matching that message is rejected (§10): the format is
incidental, and the embedded stderr excerpt could contain the
bracketed string spuriously. Instead, one small backward-
compatible change to `_run`'s error branch: after constructing
the exception object (`VerifierProtocolError` for exit 2,
`VerifierConfigError` for exit 3, `VerifierUnavailable`
otherwise), set **`err.verifier_code = code`** (the string from
`_error_document`, `""` when no error document parsed) before
raising. No exception class changes; `trust/errors.py` is
untouched; existing callers see identical messages and types.
New test pins the attribute for both exits (§9).

### 6.2 `ceremony_consumer` translation

`ceremony_consumer`'s `_consume` gains one branch before the
generic translation:

```python
try:
    self.ceremony_consume(envelope)
except VerifierError as exc:
    if getattr(exc, "verifier_code", "") \
            == "ceremony_supersede_required":
        raise CeremonySupersedeRequired(
            "ceremony consumption requires a journaled "
            "supersession decision",
            envelope_dict=envelope) from exc
    raise SigningError(
        f"ceremony consumption refused: {exc}") from exc
```

New exception, defined in `trust/client.py` (it is a
client-flow fact, not a signing fact):

```python
class CeremonySupersedeRequired(SigningError):
    """The verifier refused a consumption pre-commit with
    ceremony_supersede_required: the envelope is unconsumed,
    and a ceremony_supersede decision authorises a second
    consume attempt with the same envelope. Carries the exact
    envelope dict the consumer presented."""
    def __init__(self, message, *, envelope_dict):
        super().__init__(message)
        self.envelope_dict = envelope_dict
```

Load-bearing detail, to be stated in its docstring and in
`reanchor_pin`'s cycle-24 note: `reanchor_pin` propagates
`SigningError` from `consume_authorisation` unchanged
(`except SigningError: raise`), so this subclass reaches
`PinAdopter` with its type and `envelope_dict` intact.
`PinAdopter` imports it from `trust.client`.

### 6.3 The client method

```python
def ceremony_supersede(self, operator_id, envelope_dict) -> dict:
```

(Mirrors `ceremony_consume`'s positional-envelope style;
`operator_id` positional-first because it is a scalar like
`submit_claim`'s `proposal_id`.) Behaviour:

- Pre-extract from `envelope_dict`, exactly as
  `ceremony_consume` does: `authorisation_id`, `candidate`
  (`cycle_seq`, `payload_hash`); missing keys →
  `VerifierProtocolError`. (No `ceremony_id` echo is returned
  by this mode, so none is extracted.)
- `result = self._run("ceremony_supersede",
  {"operator_id": operator_id,
   "signed_authorisation": envelope_dict})`.
- Exact result key set: `{"abandoned_authorisation_id",
  "new_authorisation_id", "candidate_cycle_seq",
  "candidate_payload_hash", "supersession_seq"}` — else
  `VerifierProtocolError("ceremony_supersede result is
  malformed")`.
- Echo validation: `new_authorisation_id` == sent id;
  `candidate_cycle_seq` / `candidate_payload_hash` == sent
  candidate; `abandoned_authorisation_id` is a 64-char
  lowercase hex string; `supersession_seq` is an `int >= 1`
  (bool excluded). Any mismatch → `VerifierProtocolError` —
  and the docstring must state the consequence honestly: a
  malformed receipt after a possible commit leaves a decision
  journaled that this client cannot name; the envelope is
  still unconsumed, and a later consume will find the decision
  by authorisation_id itself (§5.4), so the failure is
  recoverable by consuming, not by re-deciding (a re-decide
  would refuse at mode step 8).
- **No public-key pin is required** (contrast
  `ceremony_authorise`): the mode returns no signed artefact,
  so there is nothing for the pinned `CeremonyPublicKey` to
  verify; refusing without a pin would break key-free receipt
  checking for no gain. Docstring states this explicitly.
- Docstring also carries: exit-3 refusals
  (`ceremony_operators_unconfigured`,
  `ceremony_seed_unconfigured`, `ceremony_operator_not_authorised`,
  `ceremony_already_consumed`, `ceremony_not_issued`,
  `ceremony_supersede_unproven`, `ledger_failed`) surface as
  `VerifierConfigError` via `_run`; exit-2
  (`malformed_request`, `ceremony_authorisation_invalid`) as
  `VerifierProtocolError`. Operator identity wording: same
  allowlist-eligibility-not-authentication paragraph as
  `ceremony_authorise`.

---

## 7. Adopter flow (`trust/pin_adoption.py`, `PinAdopter._reanchor`)

Current step (4) calls `reanchor_pin(...)` once inside a
try whose every exception becomes `PinAdoptionBurned`. New
structure — factor the existing call into a zero-argument local
closure `_attempt()` (same arguments, captured locals), then:

```python
try:
    new_pin, record = _attempt()
except CeremonySupersedeRequired as sup:
    # Exactly ONE decision request, then exactly ONE re-run.
    try:
        self._client.ceremony_supersede(
            cfg.operator_id, sup.envelope_dict)
    except Exception as exc:
        raise PinAdoptionBurned(
            f"supersession decision request failed; the "
            f"authorisation is treated as burned: {exc}",
            returned_pin=None, returned_record=None) from exc
    self._append_journal({**journal_base,
                          "phase": "supersede_decided"})
    try:
        new_pin, record = _attempt()
    except Exception as exc:
        raise PinAdoptionBurned(
            f"re-anchor after a journaled supersession "
            f"decision did not return; the authorisation is "
            f"treated as burned: {exc}",
            returned_pin=None, returned_record=None) from exc
except Exception as exc:
    raise PinAdoptionBurned( ...existing wording... ) from exc
```

Rules, all to be stated in code comments at the flow:

- **Exactly one** decision request and **exactly one** re-run.
  No loop. If the re-run itself raises
  `CeremonySupersedeRequired` again (head moved concurrently;
  decision misbound), it falls into the re-run's generic
  handler → `PinAdoptionBurned`. The adopter never asks twice.
- Any failure of the decision request → `PinAdoptionBurned`
  (per the task's rule: any failure in either step is
  `PinAdoptionBurned`/`Refused` as today). Honest note for the
  comment: in this specific failure the envelope is in fact
  **unconsumed** and a decision may or may not be journaled;
  `PinAdoptionBurned`'s "treated as burned" conservatism is
  retained because the adopter cannot distinguish the cases,
  and the next `snapshot_and_adopt` attempt uses a fresh
  ceremony regardless — no state depends on the distinction.
- The pending-adoption journal gains the phase line
  `"supersede_decided"` (after the decision call returns,
  before the re-run) — detection aid only, like every phase;
  `_unadopted_burns` phase logic is unchanged (the line neither
  adds nor removes burn status; it rides on the existing
  `authorised` phase of the same ceremony).
- Nothing else in `_reanchor` changes: reason computation,
  evidence bundle, authorise, journal lines, adopt, and the
  `PinAdoptionBurned` pair-attachment at step (5) are untouched.

### 7.1 Why the re-run is NOT a retry of an ambiguous consume

This distinction is load-bearing and must be documented in
three places: `trust/client.py` (`ceremony_consumer` docstring,
as an explicit exception paragraph beside "Never auto-retry"),
`trust/pin_adoption.py` (comment at the flow above), and the
cycle-24 decision addendum (§11).

> The never-retry rule (cycle 21, R7) exists because a consume
> whose outcome is **unknown** — crash, lost response, timeout
> — may have committed, and re-presenting the envelope risks
> acting on a burn the caller cannot see. A
> `ceremony_supersede_required` refusal is the opposite case:
> the outcome is **known and negative**. The code is emitted
> only from the consume mode's pre-commit head check (step 7)
> or from `append_consumption`'s in-loop re-check, both of
> which run **before** the consumption-journal append that is
> the commit point, and step 5 has already certified the
> envelope unconsumed. The verifier therefore certifies, as
> part of the refusal's documented semantics, that **no
> consumption of this authorisation exists**. The second
> `reanchor_pin` is not a retry: it is the second phase of a
> two-phase authorised flow, re-running every local check
> (envelope verification, binding, history, strict
> recomputation) against the same envelope, and consuming
> only against a decision the verifier journaled in between.
> A lost or ambiguous **supersede-mode** response is not
> covered by this paragraph: it is treated as burned (§7),
> never re-decided blindly within the flow.

---

## 8. Secondary condition: the `recovery_of=None` sentinel

Seat-gpt's cap-2 condition: with `recovery_of=None`,
`_derive_lineage` takes the bound burn as the head entry's own
authorisation_id — a direct in-process caller can bind a
recovery to the head burn with **no issuance record**, so cap-2
is a verifier-mode policy, not a ledger-API guarantee.

**Finding from the code:** in the verifier path the sentinel is
reachable from exactly one place — `_mode_ceremony_consume`
step 6 threads `bound_recovery_of = issued.get("recovery_of")`,
and `.get` yields `None` only for a **v1 issuance entry**
(cycles 19–22 journals, which carry no `recovery_of` key). Every
v2 issuance entry yields a string (`""` or a hex64 id). And
every envelope issued against a v1 entry is necessarily
**expired**: issuance appends have been v2 since cycle 23, and
the envelope TTL is hard-capped at 900 s. So no live envelope
can legitimately arrive at consume with `bound_recovery_of is
None`. The sentinel's verifier-path reachability is already
dead in practice; this design kills it in code, for free.

**Narrowing (consume mode, one change):** after step 6,

```python
bound_recovery_of = issued.get("recovery_of")
if bound_recovery_of is None:
    # Cycle 24: a v1 issuance entry carries no recovery
    # binding. Convert the legacy sentinel to the explicit
    # empty binding BEFORE threading: for a primary envelope
    # the value is never consulted; for a burned_unadopted
    # envelope "" enforces exact binding and cannot equal a
    # head authorisation_id, so the recovery is refused by
    # the lineage rules instead of binding to whatever head
    # is current. The verifier path never passes None.
    bound_recovery_of = ""
```

Effect: a (necessarily expired, but suppose unexpired) v1-issued
`burned_unadopted` envelope is refused —
`AlreadyConsumedError` → `ceremony_already_consumed` when its
candidate equals the head target, `HeadRegressionError` →
`ceremony_head_regression` otherwise — instead of consuming as
a recovery bound to the current head. Primary envelopes are
unaffected (the primary branch of `_derive_lineage` never reads
the binding).

**What stays, and the decision-record wording.** The ledger API
keeps `recovery_of=None` for direct in-process callers (unit
tests and synthetic-head callers, some of whose head dicts carry
no `authorisation_id` at all — see `_derive_lineage`'s sentinel
comment). Removing it from the API would break that caller
class to protect a path the verifier no longer exposes. The
cycle-24 decision record (Addendum 4, §11) must carry this
wording, verbatim in substance:

> The `recovery_of=None` sentinel remains in the
> `CeremonyConsumptionLedger` API as a legacy convenience for
> direct in-process callers, whose head binding is their own
> assertion. It is **not reachable through the verifier**:
> since cycle 24 the consume mode converts a v1 issuance
> entry's absent binding to the explicit empty binding before
> threading, so every recovery consumed through the verifier
> is bound to the exact burn its issuance entry recorded.
> The cap-2 bound is therefore a property of the integrated
> verifier path — the only path that can consume in
> production wiring — and the sentinel is documented at the
> API as conferring no guarantee. A future cycle may remove
> the sentinel from the API outright; nothing in production
> wiring depends on it.

`_derive_lineage`'s docstring gains one sentence pointing at
the mode-side conversion, so the API surface no longer reads
as if the verifier path uses the sentinel.

---

## 9. Test plan

Names are the contract. "Re-pin" = existing test whose
expectation changes; each re-pin carries a comment naming
cycle 24 / Option A, in the established re-pin style.

### 9.1 Ledger class + `check_head` binding — `tests/test_trust_consumption_schema_v2.py`, new class `SupersedeDecisionTests`, plus `tests/test_trust_supersession_ledger.py` (new file) for the journal class

Journal class (`test_trust_supersession_ledger.py`,
`CeremonySupersessionLedgerTests`):

- `test_append_and_find_by_new_authorisation_roundtrip` —
  fields copied from head entry + envelope; `find_by_new_authorisation`
  returns the entry; unknown id returns `None`.
- `test_second_decision_same_envelope_refused_at_append` —
  `LedgerError`; journal length stays 1.
- `test_two_decisions_same_abandoned_different_envelopes_allowed`
  — §4.1's deliberate non-enforcement.
- `test_load_rejects_duplicate_new_authorisation_id` —
  hand-built journal file → `CorruptLedgerError`.
- `test_load_rejects_candidate_not_strictly_ahead_of_abandoned` —
  `candidate_cycle_seq <= abandoned_new_cycle_seq` → corrupt.
- `test_load_rejects_superseding_old_not_behind_abandoned` —
  `superseding_old_cycle_seq >= abandoned_new_cycle_seq` → corrupt.
- `test_load_rejects_non_hex_ids` — corrupt.
- `test_hash_chain_intact_after_append` — reload validates;
  tampered field in the file → `CorruptLedgerError` on load.

`check_head` binding (`SupersedeDecisionTests`; head fixture as
in `SupersedeRuleTests`: primary consumption 41/`"a"*64` →
47/`"b"*64`; helper `_decision_for(env, head_entry)` journals a
decision via `CeremonySupersessionLedger` in a sibling tmp dir
and returns the entry dict):

- `test_supersede_shape_without_decision_raises_supersede_required`
  — `check_head` and `append_consumption` both raise
  `SupersedeRequiredError` (and it is **not** a
  `HeadRegressionError` instance).
- `test_supersede_with_bound_decision_lands_primary` — entry
  written is v2 primary, depth 0; head target advances.
- `test_supersede_decision_bound_to_other_candidate_refuses` —
  **mutation**: decision's `candidate_payload_hash` flipped →
  `HeadRegressionError`; journal length unchanged.
- `test_supersede_decision_bound_to_other_head_refuses` —
  **mutation**: decision's `abandoned_authorisation_id` (and,
  in a second sub-case, `abandoned_new_payload_hash`) flipped
  → `HeadRegressionError`.
- `test_supersede_decision_bound_to_other_envelope_refuses` —
  **mutation**: `new_authorisation_id` flipped →
  `HeadRegressionError`.
- `test_supersede_decision_wrong_operator_refuses` —
  **mutation**: `operator_id` flipped → `HeadRegressionError`.
- `test_supersede_decision_stale_after_head_moves_refuses` —
  decision minted against head 47; a different primary consumes
  to 50; the supersede envelope now faces head 50 →
  `HeadRegressionError` (not supersede-required).
- `test_supersede_hash_binding_failure_precedes_decision_check`
  — fabricated old hash at a journal-known seq, **no** decision
  → still `HeadRegressionError`, never `SupersedeRequiredError`
  (§3 order).
- `test_non_supersede_shapes_never_raise_supersede_required` —
  candidate at head / behind head with behind-head old pin →
  the cycle-23 outcomes (`AlreadyConsumedError` /
  `HeadRegressionError`), decision or no decision.

### 9.2 Mode tests — `tests/test_trust_ceremony_supersede.py` (new file; harness cloned from `test_trust_ceremony_consume.py`)

`CeremonySupersedeModeTests` (each asserts exit code, error
code, and that the supersession + consumption journals are
unchanged on refusal):

- `test_supersede_happy_path_journals_bound_decision` — setup:
  consume primary to 47; authorise fresh primary (old 41,
  candidate 50); supersede → exit 0, receipt echoes;
  supersession journal has exactly 1 entry whose abandoned
  fields equal the consumption head entry and whose candidate
  / new-id fields equal the envelope; signing ledger has the
  scoped mirror entry.
- `test_supersede_then_consume_lands` — after the decision, the
  same envelope consumes (exit 0); head target is the new
  candidate.
- `test_consume_without_decision_refuses_supersede_required` —
  consume of the supersede-shaped envelope → exit 3,
  `ceremony_supersede_required`; consumption journal unchanged
  (the pre-commit certification, §7.1).
- `test_supersede_unconfigured_operators_refuses` /
  `test_supersede_unconfigured_seed_refuses` — the two config
  gates, codes as §2 step 1.
- `test_supersede_extra_body_key_malformed` /
  `test_supersede_missing_operator_malformed` — strict keys.
- `test_supersede_unlisted_operator_refuses` —
  `ceremony_operator_not_authorised`, and (oracle pin) the
  supersession journal file is not even created.
- `test_supersede_forged_envelope_single_code` — bad signature
  → exit 2 `ceremony_authorisation_invalid`; envelope naming a
  different operator than the body → same code (folded
  `operator_mismatch`).
- `test_supersede_expired_envelope_refuses_expired` —
  `ceremony_authorisation_expired`.
- `test_supersede_unissued_envelope_refuses_not_issued`.
- `test_supersede_consumed_envelope_refuses_already_consumed`.
- `test_supersede_not_needed_candidate_not_ahead_unproven` /
  `test_supersede_not_needed_old_pin_not_behind_unproven` /
  `test_supersede_burned_unadopted_envelope_unproven` /
  `test_supersede_fabricated_old_hash_unproven` — the four
  gratuitous-decision refusals, all the single code
  `ceremony_supersede_unproven`, no journal entry written.
- `test_supersede_second_decision_same_envelope_unproven` —
  mode step 8; journal stays at 1 entry.
- `test_supersede_empty_journal_unproven`.

Client tests (same file, `CeremonySupersedeClientTests`, real
subprocess via the harness's client construction):

- `test_client_supersede_echo_validated` — happy path returns
  the receipt dict.
- `test_client_run_attaches_verifier_code` — a state refusal
  raised through `_run` carries `.verifier_code` equal to the
  verifier's code (pin §6.1 for both an exit-3 supersede
  refusal and an exit-2 malformed request).
- `test_consumer_translates_supersede_required_with_envelope`
  — `ceremony_consumer()` over a supersede-shaped envelope
  raises `CeremonySupersedeRequired` whose `.envelope_dict`
  equals the presented envelope dict; a head-regression refusal
  still translates to plain `SigningError` (type pin).

Sentinel narrowing (§8), in `test_trust_ceremony_consume.py`:

- `test_v1_issuance_recovery_envelope_does_not_bind_current_head`
  — hand-write a v1 issuance entry (no `recovery_of` key) for a
  `burned_unadopted` envelope whose candidate equals the head
  target → consume refuses `ceremony_already_consumed` and no
  recovery entry is written. (Direct-ledger sentinel behaviour
  itself stays pinned by the existing schema-v2 lineage tests,
  which call `_derive_lineage` / `append_consumption` with
  `recovery_of=None` explicitly — unchanged.)

### 9.3 Adopter end-to-end — `tests/test_trust_pin_adoption_crash.py`

- **Re-pin / extend the existing discarded-pair scenario**
  (the test whose tail currently lands seq 11 "via supersede",
  ~line 556): outcome assertions unchanged (pin jumps 7 → 11,
  final consumption is a v2 primary with `old_cycle_seq == 7`,
  `new_cycle_seq == 11`), plus new assertions: the supersession
  journal in the verifier home contains **exactly one**
  decision; its `abandoned_new_cycle_seq == 9` (the discarded
  movement's target), `candidate_cycle_seq == 11`, and its
  `new_authorisation_id` equals the final consumption entry's
  `authorisation_id`; the adopter's pending journal carries a
  `"supersede_decided"` phase line for that ceremony.
- New `test_supersede_decision_flow_consumes_exactly_twice_attempted`
  (name to be aligned with the file's style): instrument by
  counting — the scenario performs exactly one
  `ceremony_supersede` request and exactly two consume attempts
  for the seq-11 envelope (first refused
  `ceremony_supersede_required`, second lands); no third
  attempt. (Count via the supersession journal length + a
  wrapping client in the harness, as the file's existing
  counting helpers do.)
- New `test_supersede_decision_failure_is_burned_not_retried`:
  force the supersede call to fail (client stub raising) →
  `PinAdoptionBurned`, exactly one supersede attempt, pin
  unmoved, consumption journal unchanged.

### 9.4 Re-pin inventory (cycle-23 supersede tests that bypass the decision)

Grep basis: `supersede` in `tests/`, plus every direct
`check_head` / `append_consumption` call in a supersede shape.

| file / test | today | cycle-24 re-pin |
|---|---|---|
| `test_trust_consumption_schema_v2.py::SupersedeRuleTests.test_supersede_lands_primary_candidate_ahead_old_behind` | direct `append_consumption` lands | journal a decision first (helper §9.1) and pass `supersede_decision=`; without it the same call now raises `SupersedeRequiredError` — assert both legs |
| `test_trust_consumption_schema_v2.py::SupersedeRuleTests.test_supersede_does_not_rescue_fork_at_head` | `HeadRegressionError` | **unchanged** (old pin AT head seq is not the supersede shape; decision check never reached) — add comment pinning why no decision is involved |
| `test_trust_consumption_schema_v2.py::SupersedeRuleTests.test_supersede_fabricated_old_hash_journal_known_seq_refuses` + `..._known_as_new_seq_refuses` | `HeadRegressionError` | **unchanged outcome**; add a no-decision variant asserting the error is `HeadRegressionError`, not `SupersedeRequiredError` (order pin, §3) |
| `test_trust_consumption_schema_v2.py::SupersedeRuleTests.test_burned_unadopted_candidate_ahead_refuses_no_primary` | `HeadRegressionError` | **unchanged** (recovery envelopes never enter the branch) |
| `test_trust_consumption_schema_v2.py::SupersedeRuleTests.test_candidate_at_or_behind_head_old_behind_still_refuses` | already/head outcomes | **unchanged** |
| `test_signing_ceremony_recovery.py` check_head block (~line 382, `stale_old` assertIsNone) | supersede passes bare | re-pin: bare call raises `SupersedeRequiredError`; call with a bound decision dict returns `None` |
| `test_trust_ceremony_consume.py::test_old_pin_behind_head_superseded_when_candidate_ahead` | consume lands directly | re-pin to the three-step flow: consume → `ceremony_supersede_required`; `ceremony_supersede` → 0; consume → lands, head 50. The trailing behind-head leg unchanged |
| `test_signing_pin_ceremony.py::test_t8_regression_scenario_stale_history_returns_regressed_pin` (fresh-envelope leg, ~line 1175) | fixture consumer's direct `append_consumption` lands via supersede | the **fixture consumer** (test code) gains the production pattern: catch `SupersedeRequiredError`, journal a decision into a `CeremonySupersessionLedger` over the fixture's tmp home bound to its own head, retry the append **once**. Test assertions unchanged; docstring gains a cycle-24 note that the raw-library level now also requires the journaled decision, and the adoption-side context-binding point is unchanged |
| `test_signing_pin_ceremony.py::test_t8_composed_supersede_adopt_refusal_ahead_variant` | same fixture path | same fixture change; assertions unchanged (adopt still refused on context binding — seat-gemini's condition visibly intact) |
| `test_trust_pin_adoption_crash.py` discarded-pair scenario | lands via bare supersede | §9.3: outcome unchanged, decision-journal assertions added — this is the end-to-end deadlock scenario the mandate names |

No other test calls `check_head`/`append_consumption` in a
supersede shape (verified by grep over `tests/` for
`check_head|append_consumption`: the remaining hits are
recovery-lineage, race and mirror tests whose shapes never
enter the branch).

### 9.5 Mutation sweep (acceptance-level)

Beyond §9.1's four binding mutations, the war room should run:
decision entry with `candidate_cycle_seq` ±1; decision journal
file truncated to empty after a decision (consume →
`ceremony_supersede_required`, fail-closed, §4.4); supersede
mode called with the decision for envelope A in flight while
consuming envelope B (B's consume finds no decision keyed to B
→ `ceremony_supersede_required`); and the §9.3 crash scenario
with the supersession journal deleted between decision and
re-run (re-run refuses supersede-required → `PinAdoptionBurned`,
pin unmoved, nothing consumed).

---

## 10. Rejected alternatives

- **Option B — explicit terminal recovery state.** Requires a
  new state on the consumption journal (schema v3 on an
  *anchored* journal, or a second journal marking heads
  terminal) and a rule for who may mark a head terminal and
  when. It fails on the facts Addendum 3 already recorded:
  the deadlock arises for a depth-0 head whose pair was
  discarded, and the verifier cannot observe discard — there
  is no event at which "terminal" becomes true that the
  verifier can check. A caller-asserted terminal flag would
  reintroduce caller-supplied state as authority (the cycle-21
  defect class). Option A needs no consumption-schema change
  and keys the authorisation to an operator presentation the
  verifier can actually gate.
- **The stronger threat-model argument (no build).** Seat-gpt
  considered the cycle-23 justification (fresh single-use
  envelope; pin can only move forward; CAS + context binding)
  and returned FIX 0.96 anyway: the objection is not that
  supersede is unsafe, it is that abandoning a *burned*
  movement is an auditable act currently performed by no one.
  Re-arguing the same premises invites a second FIX and leaves
  the audit gap real: today no artefact names who let the
  seq-9 movement go. Option A closes the artefact gap, not
  just the argument.
- **Caller supplies the decision (or its id) in the consume
  body.** Breaks consume's strict key set, and a caller-named
  decision is a caller assertion until the verifier looks it
  up — at which point keying the lookup by the envelope's own
  authorisation_id (this design) is strictly simpler and
  removes the field entirely.
- **Decision as a new signed envelope type returned to the
  caller.** New signed format, TTL, replay and retention
  surface, plus a presentation step at consume — all to carry
  a fact that never needs to leave the verifier. Consumptions
  themselves are unsigned journal entries; decisions are the
  same class of act.
- **Record the decision inside the consumption entry (schema
  v3).** The decision must exist *before* the consumption it
  authorises and must be creatable while the envelope is still
  unconsumed; folding it into the consumption entry makes it
  simultaneous with the act it authorises and forces a
  migration on the anchored journal. A sibling journal avoids
  both.
- **Pre-authorise supersede at `ceremony_authorise` time**
  (a flag on issuance). The head at issuance is not the head
  at consume; the decision would bind a movement that may not
  be head when spent, and issuance would mint abandonment
  authorisations for movements that later adopt normally —
  gratuitous decisions by construction (§3 forbids them).
- **String-matching the refusal code** in the consumer
  (`"[ceremony_supersede_required]" in str(exc)`). The `_run`
  message format is incidental, and the message embeds a
  stderr excerpt that could contain the bracketed string
  spuriously (false positive → a decision request and re-run
  after a genuinely ambiguous failure — exactly what R7
  forbids). The structured `.verifier_code` attribute (§6.1)
  costs six lines and cannot false-positive on stderr content.
- **Distinct sub-codes in the supersede mode for each shape
  failure.** A journal-state oracle (§2 step 8); the
  `ceremony_recovery_unproven` single-code precedent governs.

---

## 11. Documentation / decision-record updates the build must land

1. `internal/DECISION-CONSUMPTION-HEAD.md` — **Addendum 4**:
   the supersede rule as amended by Option A (bare supersede
   is superseded; the branch now requires a journaled
   decision), the §8 sentinel wording (verbatim in substance),
   and the §4.3 anchoring note (supersession journal added to
   the `ceremony-journal-anchoring` follow-up's scope).
2. `trust/ledger.py` — `check_head` docstring: the supersede
   bullet gains the decision requirement and the
   `SupersedeRequiredError` mapping; `CeremonyConsumptionLedger`
   class docstring unchanged otherwise. `_derive_lineage`
   docstring: the §8 pointer sentence.
3. `trust/verifier_main.py` — module docstring: a
   `ceremony_supersede` paragraph beside the
   `ceremony_authorise` one (what the decision proves:
   an allowlisted operator presented a verified, issued,
   unconsumed envelope in the exact supersede shape, and the
   verifier journaled the abandonment of its own head movement
   bound to that envelope — nothing about the pin, which the
   verifier cannot observe); consume-mode docstring per §5.4.
   No env-var documentation changes (none added).
4. `signing/pin_ceremony.py` — the cycle-21 crash-consistency
   section gains the §7.1 paragraph (pre-commit refusal →
   two-phase flow), since `reanchor_pin`'s consumer contract
   is documented there.
5. `trust/client.py` — `ceremony_consumer` docstring exception
   paragraph (§7.1); `ceremony_consume` docstring notes the
   new refusal code and that `.verifier_code` now rides every
   `_run` error.

---

## 12. Risks and open points for the war room

- **TTL pressure.** The flow authorise → consume(refused) →
  supersede → consume must fit the envelope's ≤900 s life.
  Each step is one local subprocess; the adopter flow adds two
  round-trips inside a single `_reanchor` call. No design
  change needed, but the §9.3 counting test should also assert
  the flow completes on one envelope (it does by construction).
- **Decision without consumption is a permanent journal fact.**
  An envelope that gets a decision and then expires leaves a
  decision entry that can never be spent (binding includes the
  envelope id). This is intentional (audit), and §4.1 allows a
  later envelope its own decision against the same head. The
  journal grows by one entry per abandoned movement — bounded
  by ceremony frequency, far under `MAX_JOURNAL_BYTES`.
- **`ceremony_supersede_unproven` also covers "already
  decided".** An operator debugging a lost receipt sees the
  same code as a shape failure. Accepted (oracle discipline);
  the remedy is identical either way: consume the envelope.
- **The mirror-failure wording** (§2 step 10) tells the caller
  a decision "stands" while returning `ledger_failed`; the
  adopter maps that to `PinAdoptionBurned`. Slightly
  conservative, consistent with every other post-commit
  mirror failure in the system.
- **Fixture consumers in tests** (§9.4) replicate the decision
  step in test code. That is honest — they are direct-ledger
  consumers, the class §8's wording addresses — but the war
  room should confirm no *production* direct consumer exists
  besides `PinAdopter` (grep `append_consumption` outside
  `trust/ledger.py`, `trust/verifier_main.py`, `tests/`:
  none at design time).
- **Interaction with cycle-24 items 1–2** (production entry
  point; mandatory ceremony key in `production_client`): none
  in this design — `ceremony_supersede` needs no client pin
  (§6.3) and no wiring change; the entry point inherits the
  flow through `PinAdopter` unchanged.
