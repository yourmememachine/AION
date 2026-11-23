# DESIGN C — Cycle 20: Consumption integrity for `reanchor_pin`

Seat C (consumption side). Design only; no code in this round.
Scope: `signing/pin_ceremony.py` — `reanchor_pin`,
`_check_ceremony_history`, and the claims in that module's
docstring. Sources read in full: `signing/pin_ceremony.py`,
`signing/ceremony_authorisation.py`,
`internal/CROSS-CHECK-13.md`, `internal/BUILD-CYCLE-19.md`
(F1/F5, claim-scoping), `internal/REVIEW-CYCLE-19.md`
(rev-r6's preserved F1 dissent).

External verdict this design answers: Gemini FIX (3)
"consumption replay can REGRESS the pin (envelope old_pin not
checked against the live pin state atomically)" and its
fail-closed demand ("consumption must fail-closed if
state/history continuity cannot be verified"); GPT FIX:
consumption replay "MANDATORY before cycles 14–16 ship
(monotonic protected head, atomic consumption, duplicate
consumption fails with no/stale history, rollback tests)",
plus the corrected scope claims. rev-r6's standing condition
is the acceptance bar for every sentence below: **any claim
of consumption single-use without the protected monotonic
head re-triggers its FIX.** This design therefore claims
less than closure, on purpose, and names the remainder.

---

## 1. The three defects, stated precisely

(i) **Consumption-side replay.** The ceremony journal /
`CeremonyAuthorisationLedger` burns `(ceremony_id,
evidence_hash)` at *issuance* (verifier mode, dual-append,
ledger-before-return). Nothing burns at consumption.
`reanchor_pin` is a pure in-process function with no ledger
access (limit M5, unchanged). The same envelope presented
twice within its 900 s TTL succeeds twice — pinned as a
limit by `test_consumption_side_replay_within_ttl_without_history_succeeds_documented_limit`
in `tests/test_trust_ceremony_authorisation.py`.

(ii) **Pin regression via a restaged argument.** Cycle 19
step (4) binds the envelope's `old_pin` *exactly* to the
captured `old_pin` argument. That check is sound and stays.
But it compares envelope ↔ argument, not envelope ↔ world.
The attack restages the argument: the real pin has moved
from H1 to H3 (by a first consumption and/or `advance_pin`
steps); the caller — buggy, rolled-back, or hostile —
passes the stale H1 as `old_pin` again. Envelope and
argument agree perfectly; every check passes; the function
returns the H2 pin, and a caller that adopts the return
value has regressed. Gemini's "not checked against the live
pin state" is accurate, with the refinement in §2.

(iii) **Opt-in history.** `ceremony_history=None` (the
default) silently skips `_check_ceremony_history` entirely:
no replayed-target refusal, no evidence-reuse refusal, no
behind-head refusal, no predates-latest-ceremony refusal.
Omission is indistinguishable at the call site from a
deliberate "no history exists" — that ambiguity, not the
checks themselves, is the defect cycle 20 removes.

## 2. What "live pin state" can honestly mean in-process

`reanchor_pin` receives every input from its caller. There
is no other channel. Before designing a mechanism, the
ownership facts (grep, this round):

- **No production caller exists.** `reanchor_pin` /
  `advance_pin` appear in production code only as re-exports
  in `signing/__init__.py`. The only call sites in the repo
  are tests (`tests/test_signing_pin_ceremony.py`,
  `tests/test_trust_ceremony_authorisation.py`) and prose
  references (`signing/ceremony_authorisation.py`,
  `trust/verifier_main.py` comments). No loop, storage, or
  wiring code calls the ceremony yet.
- **No in-repo pin store exists.** Nothing in `core/`,
  `trust/`, or `signing/` persists a snapshot pin for this
  module to read. The module docstring already assigns the
  dense-emission assumption — and by the same logic pin
  persistence — to "the loop/storage layer, not this
  module". That layer is not built.

Consequences, honestly:

1. **A "live pin" callback or store-read parameter does not
   fix (ii), and this design rejects it as the mechanism.**
   A caller-supplied `live_pin()` callback is the restaged
   argument wearing a function costume: the same hand that
   passes a stale `old_pin` can return a stale H1 from the
   callback, and nothing in-process can tell the difference.
   It also adds a false atomicity flavour — a read inside
   `reanchor_pin` is not atomic with the caller's later
   adoption of the returned pin (the TOCTOU gap is the
   caller's store transaction, which does not exist yet),
   plus re-entrancy and a new typed surface for zero
   verifiable gain. When the loop/storage layer lands, the
   correct shape is a store-owned compare-and-swap consumed
   *by that layer* around this function — recorded as an
   obligation on that future layer, not built here.
2. **What an in-process function CAN do** is (a) refuse to
   run when the continuity input is absent — fail-closed on
   omission, so disabling the checks takes an explicit,
   visible false assertion (an empty history) rather than a
   silent default; (b) run every consistency check the
   supplied history supports; (c) make the caller's
   obligations explicit, typed, and named in the signature
   and docstring, so a future war room can audit a caller
   against them. That is the whole of this design. It does
   not pretend the function reads live state.

## 3. The consumption contract

### 3.1 `ceremony_history` becomes REQUIRED (no default)

`ceremony_history=None` — omitted or passed explicitly —
is a `SigningError` for **every** reason. The parameter
loses its default in the signature (§4), so omission at a
call site is loud (a missing required keyword argument),
and an explicit `None` refuses with a dedicated message
naming the fail-closed rule. A supplied history is a list
or tuple of `PinCeremonyRecord` exactly as today;
`_check_ceremony_history` itself is **unchanged** — cycle 20
changes when it runs (always) and one per-reason
admissibility rule (§3.2), not what it checks.

What a supplied, verified history actually refuses
(existing `_check_ceremony_history`, now un-omittable):

- every record must verify under the ceremony key — an
  unverifiable history establishes nothing and refuses;
- evidence reuse: within the history, and this ceremony's
  `evidence_hash` against every history record;
- replayed target: candidate `(cycle_seq, payload_hash)`
  already a ceremonied target in the history;
- forked history: two records attesting different snapshots
  at the same sequence;
- candidate behind the history's attested head (lower seq,
  or equal seq with a different hash);
- candidate predating the latest ceremony (candidate
  `signed_at` ≤ the latest record's `performed_at`).

**Does requiring it kill the documented no-history replay?
Yes — that exact case dies.** The cycle-19 pinned limit was
"same envelope twice succeeds *when ceremony_history is
omitted*". Under this contract the second presentation
either omits history (refused, §3.1) or supplies it (§3.3).
The pinned-limit test is replaced, not edited (§6).

### 3.2 Per-reason requirements

| reason | `old_pin` | `ceremony_history` requirement | extra admissibility |
|---|---|---|---|
| `chain_gap_recovery` | required (existing) | required, non-`None`; may be empty `()`/`[]` | none |
| `initial_anchor` | must be `None` (existing) | required, non-`None`; **must be empty** | non-empty history refuses (see below) |
| `lost_pin` | must be `None` (existing) | required, non-`None`; may be empty or populated | populated history runs all §3.1 checks |
| `corrupted_pin` | must be `None` (existing) | required, non-`None`; may be empty or populated | as `lost_pin` |

Justifications, per reason:

- **`chain_gap_recovery`, empty allowed.** The first gap
  ceremony in a deployment's life has, by construction, no
  prior ceremony records — the pin was built entirely by
  `advance_pin`. Requiring a *non-empty* history would
  deadlock the ceremony's primary use case. Empty is
  therefore admissible, but it is now an explicit caller
  assertion — "no prior ceremony has occurred" — made in
  the open, where a reviewer (and a future protected head)
  can hold the caller to it. An empty history that is
  *false* is exactly the stale-history residual of §5.
- **`initial_anchor`, empty ONLY.** "Initial" is a claim
  that no anchor and no ceremony precedes this one. A
  non-empty verified history contradicts the claim on its
  face: ceremonies happened, so a pin existed, so a missing
  pin is `lost_pin`, not `initial_anchor`. Without this
  rule the generic checks do **not** refuse a second
  "initial" anchor whose candidate sits beyond the history
  head with fresh evidence — a clean re-bootstrap laundering
  path. Refusal message names the contradiction and points
  at `lost_pin`. This extends cycle 16's bootstrap
  semantics (explicit `()` vs `None`): `None` = "I decline
  to say" (refused); `()` = "I assert none exist" (checked
  where checkable, an assertion where not).
- **`lost_pin` / `corrupted_pin`, empty or populated.**
  A pin can be lost before any ceremony ever occurred
  (empty is honest) or after several (populated is honest,
  and the checks then have real work: a lost-pin recovery
  must not reuse evidence, must not re-target an old
  ceremonied candidate, and must not land behind the
  ceremony head). Nothing in-process distinguishes lost
  from corrupted — both arrive as `old_pin is None` with
  the reason bound in the envelope — and this design
  invents no distinction. Note the history does **not**
  resurrect or substitute for the pin: with no pin there is
  still no recomputation and no relation check (existing
  cycle-16 scoping, unchanged).

**Is fail-closed-on-omission the right default? Yes**, and
it is the only reading of Gemini's demand available
in-process: where continuity cannot be verified *because
the caller supplied nothing to verify it against*,
consumption refuses. The demand's stronger reading —
refuse when continuity cannot be verified *at all* — is
not implementable in-process (§2) and is precisely the
protected-head follow-up (§5). The docstring must say
which reading was implemented (§7), or this cycle commits
the overclaim rev-r6 exists to catch.

### 3.3 Duplicate consumption, walked through

Same envelope, presented twice, TTL still running:

1. **History omitted on the second presentation** →
   refused (§3.1). The cycle-19 hole is closed.
2. **History updated** — the caller appended the first
   consumption's returned record, as the contract (§4.2)
   requires → refused by `_check_ceremony_history`: the
   candidate is already a ceremonied target. (Evidence
   reuse would also refuse; the target check fires in the
   existing order and the test asserts its message.)
3. **History stale** — the caller supplies the same
   pre-consumption history again (e.g. `()` both times) →
   **succeeds.** Every check passes because, relative to
   the supplied inputs, nothing is wrong. This is the
   residual, named in §5, pinned by an honest test (§6,
   T7/T8), and never described as protection.

One more blind spot the history cannot cover, stated so
nobody over-reads §3.1: `ceremony_history` contains
*ceremony records only*. Normal `advance_pin` movements
leave no trace in it. The history "head" is the **ceremony
head, not the pin head** — a pin advanced past the
candidate by ordinary steps is invisible to every check in
`_check_ceremony_history`. History therefore bounds
regression *across ceremonies*, never regression across
advances. (The regression walk in §6 T8 makes this
concrete.)

## 4. API changes to `reanchor_pin`

### 4.1 Signature

```python
def reanchor_pin(old_pin, signed, *, signing_key: SigningKey,
                 state_bytes, calibration_bytes, expected_signer_id,
                 operator_id, reason,
                 evidence_hash, authorisation,
                 authorisation_verify_key,          # was: authorisation_key — §4.3
                 expected_authorisation_key_id,     # new — §4.3
                 expected_verifier_signer_id,
                 ceremony_history,                  # was: ceremony_history=None
                 strict_reasons=None,
                 now=None) \
        -> tuple[dict, PinCeremonyRecord]:
```

- `ceremony_history`: keyword-only, **no default**.
  Callers must write it. (Repo impact is tests + the
  `reanchor()` test helper only — §2's grep; there is no
  production caller to break. The E2E helper likewise.)
- Verification order gains one early step and keeps the
  rest: after (1) type checks and (2) key separation (§4.3),
  **(2.5) history presence** — `ceremony_history is None`
  refuses here, before envelope verification, so the
  fail-closed refusal is never masked by an expired or
  foreign envelope and its message is unambiguous. Content
  validation stays at the existing call site (after strict
  recomputation, before the bare attestation verify), where
  `_check_ceremony_history` runs **unconditionally** — the
  `if ceremony_history is not None:` guard is deleted. The
  `initial_anchor` empty-only rule (§3.2) is enforced at
  that same site, immediately before the generic check,
  with its own message.
- No other parameter, return shape, or refusal changes.
  `advance_pin` and `verify_ceremony_record` are untouched
  (their context-sentinel pattern — explicit `None` asserts
  absence, omission asserts nothing — is the existing
  precedent §3.2's `()`/`None` split follows).

### 4.2 The caller contract (docstring, named preconditions)

The signature change is backed by three named
preconditions in the module docstring's caller contract,
stated as obligations of the (future) loop/storage layer,
not as properties this function enforces:

- **FRESH-PIN:** `old_pin` must be read from the caller's
  pin store at the start of this ceremony attempt, not
  cached, reconstructed, or replayed from an earlier
  attempt.
- **COMPLETE-HISTORY:** `ceremony_history` must contain
  every ceremony record the caller has ever accepted, in
  particular including the record of any prior consumption
  of this same envelope.
- **ATOMIC-ADOPTION:** on success the caller must persist
  the returned pin and append the returned record to its
  history as one step, before any further ceremony or
  advance; on refusal it must persist neither.

FRESH-PIN and COMPLETE-HISTORY are **unverifiable
in-process** and the docstring says so in those words.
ATOMIC-ADOPTION restates the existing "nothing here
persists the pin and the record atomically" limit as a
caller duty. Naming them does not enforce them; it makes
the future storage layer's review checklist exist, and it
stops any reader mistaking §3 for enforcement.

### 4.3 Interaction with seat A (asymmetric authorisation)

Assumes seat A replaces the envelope's HMAC with an
asymmetric signature: verifier holds the private key,
consumption verifies with a pinned public key. Changes on
this side of the seam (final type/field names are seat
A's; names below are placeholders to be reconciled):

- **Parameter:** `authorisation_key: SigningKey` is
  deleted. In its place: `authorisation_verify_key` — a
  public-key-only object of seat A's verify-key type (it
  must expose **no** secret material and no signing
  operation; the type check in step (1) asserts that type,
  and passing a `SigningKey` refuses) — and
  `expected_authorisation_key_id: str`, the key id the
  caller pins out-of-band for the verifier's public key.
  `expected_verifier_signer_id` is **unchanged and not
  merged** with the key id: signer identity (who the
  verifier claims to be) and key identity (which key
  actually signed) are separate pins, exactly as the
  envelope's top-level `signer_id`/`key_id` are separate
  fields today.
- **Step (3)** calls seat A's verifier in its new shape,
  in substance
  `verify_ceremony_authorisation(authorisation, verify_key=authorisation_verify_key, expected_key_id=expected_authorisation_key_id, expected_signer_id=expected_verifier_signer_id, now=moment)`.
  An envelope whose `key_id` ≠ the pinned expected id
  refuses there (`unknown_key` in the current vocabulary),
  so a caller cannot be silently re-pointed at a different
  verifier key by whoever hands it the key object. Step
  (4) exact binding is unchanged — it never read the key.
- **Key separation, re-thought.** Today's step (2) —
  `authorisation_key.key_id == signing_key.key_id` ⇒
  refusal — exists because both sides are the same kind of
  secret: one HMAC key on both sides collapses the
  boundary. Under asymmetry the rationale transforms:
  - The **real** separation is now cryptographic and
    type-level: the consumption side holds only a public
    key, so possession of everything `reanchor_pin`
    receives no longer confers minting ability (Gemini
    defect (2) — the strongest cycle-19 defect — is what
    actually closes here, in seat A's part).
  - The id-equality check is **retained as
    defence-in-depth, with its claim downgraded**: refuse
    if the pinned authorisation key id equals the snapshot
    `signing_key.key_id`. But the two ids now live in
    different derivation namespaces (seat A's public-key
    derivation vs `key_id_for` over HMAC secret bytes), so
    equality is a tripwire for gross misconfiguration
    (the same key *file* wired to both slots), **not** a
    proof of distinct key material — the same underlying
    seed used for both an HMAC secret and an asymmetric
    private key would produce different ids and pass.
    The docstring must say exactly that (§7) and must not
    repeat cycle 19's phrasing that separation is
    "enforced in-process" without qualification.
  - Ordering is unchanged: the check stays **before**
    envelope verification, so its refusal is unambiguous.
- **What does NOT change:** the ceremony *record's* MAC
  still uses the snapshot `SigningKey` (cycle-19 scoping,
  unchanged); `_check_ceremony_history`'s record
  verification is untouched; `authorisation_id` derivation
  is seat A's concern — if A changes its inputs, only the
  record's carried value changes here, opaquely.

**Fallback if seat A does not land asymmetry:** §3/§4.1/§4.2
stand alone with `authorisation_key: SigningKey` retained
and step (2) in its cycle-19 form. Consumption integrity
must not be held hostage to the key-boundary fix, nor
vice versa — but the docstring's symmetric-MAC sentence
then stays, and CROSS-CHECK-13's FIX on Parts B/C remains
open on A's item alone.

## 5. Residual statement (the paragraph the docstring carries)

> Consumption single-use is **not** achieved by this
> cycle. Requiring `ceremony_history` makes omission
> refuse and makes a second consumption refuse *against a
> history the caller has updated with the first
> consumption's record*; against a stale history — the
> same pre-consumption history supplied twice, or an
> empty history asserted twice — the same envelope
> consumes twice within its TTL and returns the same pin
> again, and if the caller's real pin has since moved
> (by ceremony or by `advance_pin`, which leaves no trace
> in the history at all) adopting that return regresses
> the pin. No in-process check can distinguish a stale
> history from a complete one, because the history is
> caller-supplied input and this module has no pin store,
> no ledger access, and no monotonic counter of its own.
> The real fix is unchanged from cycle 19's F1: a
> **protected monotonic consumption head** — a store
> outside the ceremony caller's control that records
> each consumed `authorisation_id` (or each ceremony's
> resulting pin) monotonically and is consulted, or
> written, atomically at consumption. Its location
> remains an owner-level store decision. Until it lands,
> cycles 14–16's re-review condition on consumption
> (GPT: "duplicate consumption fails with no/stale
> history") is **not** met for the stale-history leg, and
> no wording in this module may imply otherwise.

## 6. Test plan

Delete/replace the pinned limit; add the refusals; pin the
residual honestly. (Unit file:
`tests/test_signing_pin_ceremony.py`; E2E file:
`tests/test_trust_ceremony_authorisation.py`. The
`reanchor()` helpers in both files gain an explicit
`ceremony_history=()` default **in the helper only**, so
existing cases stay readable; the function itself has no
default — T1 pins that.)

**Replaced:**

- T0. `test_consumption_side_replay_within_ttl_without_history_succeeds_documented_limit`
  (E2E) is **deleted**. Its premise (history optional) is
  the defect. Replaced by T5–T8 below.
- T0b. `test_history_empty_and_absent_unchanged` (unit)
  splits: empty half survives as
  `test_history_explicit_empty_accepted`; absent half is
  inverted by T2.

**New — omission / presence:**

- T1. Signature pin: calling `reanchor_pin` without the
  `ceremony_history` keyword raises `TypeError` (the
  parameter has no default). Guards against a future
  "convenience" default creeping back.
- T2. `ceremony_history=None` explicitly, `chain_gap_recovery`
  → `SigningError` asserting the fail-closed message;
  and the refusal fires even with an *expired* envelope
  (pins the §4.1 ordering: presence before envelope
  verification).
- T3. `ceremony_history=None` for each no-pin reason
  (`initial_anchor`, `lost_pin`, `corrupted_pin`) →
  refused, same message. Omission is not a bootstrap path.

**New — per-reason admissibility:**

- T4. `initial_anchor` with a non-empty verified history →
  refused, message names the contradiction / points at
  `lost_pin`. `initial_anchor` with explicit `()` →
  succeeds (bootstrap preserved). `lost_pin` with `()` →
  succeeds; `lost_pin` with a populated history whose
  evidence it reuses → refused (evidence reuse);
  `corrupted_pin` with a populated history and a candidate
  behind its head → refused (behind-head). One test per
  leg, messages asserted (rev-r4's probe standard: read
  the messages, not the test names).

**New — duplicate consumption (the core matrix):**

- T5. Same envelope twice, second call omits history →
  refused (T2's case driven end-to-end in the E2E file,
  real verifier-issued envelope).
- T6. Same envelope twice, second call supplies the
  **updated** history `[rec1]` → refused, message asserts
  "already a ceremonied target". (Unit-level precedent
  exists — `test_history_replayed_target_and_behind_head_refused`
  re-presents with a *different* evidence hash; T6 pins
  the *same envelope, same everything* case, E2E and unit.)
- T7. **Honest residual pin:** same envelope twice, second
  call supplies the **stale** history (the same `()` as
  the first call) → **succeeds**; assert `pin2 == pin1`
  and `rec2.authorisation_id == rec1.authorisation_id`.
  Name: `test_consumption_replay_with_stale_history_succeeds_named_residual_protected_head`.
  The docstring in the test states it pins the §5
  residual / F1 follow-up, not a feature — mirroring the
  cycle-19 test's own honesty formula, one level up.
- T8. **Regression scenario (Gemini's attack, concrete).**
  Pin at seq 1 (H1). Envelope consumes → pin at seq 4
  (H2) with history `()`, record `rec1`. `advance_pin`
  twice on chained snapshots → pin at seq 6 (H3); no
  ceremony records exist for these moves. Replay the
  original envelope with `old_pin` restaged to the seq-1
  pin:
  - with history `[rec1]` (updated) → **refused**
    (replayed target);
  - with history `()` (stale) → **succeeds and returns
    the seq-4 pin** — assert the returned pin's seq is
    *behind* the caller's seq-6 pin, i.e. the regression
    value itself, so the test cannot be misread as a
    benign idempotent re-derivation. Named as a residual
    pin alongside T7. Expected outcome stated plainly:
    under this design the stale leg is **not** stopped;
    stopping it is the protected head's job (§5).

**Confirmed existing (no change, re-run as regression):**

- T9. Envelope `old_pin` ≠ supplied `old_pin` refuses —
  already pinned unit-side (`test_envelope_binding_refusals_per_field`,
  old_pin leg) and E2E
  (`test_envelope_replayed_against_different_pin_refused`,
  "different old pin"). Confirmed sufficient: §1(ii) is
  the *restaged-argument* case (T8), not an
  envelope/argument divergence, and the task brief's
  premise — step (4) already refuses divergence — checks
  out against the code.
- T10. All existing `_check_ceremony_history` legs
  (tampered record, duplicate evidence inside history,
  forked history, behind-head, predates-latest,
  malformed history types incl. `"not-a-history"` and
  non-record entries) pass unchanged — they now run on
  every call instead of opt-in calls.

**Conditional on seat A landing asymmetry:**

- T11. `test_same_key_as_snapshot_refused` re-scoped:
  passing a `SigningKey` as `authorisation_verify_key`
  refuses on type; pinning
  `expected_authorisation_key_id == signing_key.key_id`'s
  counterpart (the verify key whose id equals the
  snapshot key id) refuses with the separation message,
  before envelope verification. A wrong
  `expected_authorisation_key_id` with a genuine envelope
  refuses at step (3) (`unknown_key`). Final shapes wait
  on seat A's type — flagged in §8.

**Migration note for the build round:** every existing
`reanchor()` helper call that relied on the `None` default
(the no-pin happy paths especially) must pass a history
explicitly; a converted test that passes "for the wrong
reason" is the rev-r4 failure mode — each converted case
asserts its specific message at least once per refusal
class.

## 7. Claims sweep — `signing/pin_ceremony.py` docstring

GPT's three distinctions, applied: **issuance accounting
≠ consumption enforcement ≠ anchored provenance**;
**workflow provenance ≠ cryptographic attribution**;
dependency **coverage ≠ complete closure**. Sentence by
sentence (quoted current text → replacement):

1. **Cycle-16 paragraph — history.** Current: *"An
   optional ``ceremony_history`` (verified records only)
   refuses evidence reuse, replayed targets, candidates
   behind the history's attested head, and candidates
   predating the latest ceremony — ONLY under a complete,
   caller-supplied history: the parameter is opt-in, a
   truncated or omitted history silently disables every
   one of those checks…"*
   → Replace with: *"A required ``ceremony_history``
   (verified records only; ``None`` refuses for every
   reason — cycle 20) refuses evidence reuse, replayed
   targets, candidates behind the history's attested
   ceremony head, and candidates predating the latest
   ceremony — ONLY under a complete, caller-supplied
   history: a truncated or stale history silently passes
   every one of those checks, the history records
   ceremonies only (``advance_pin`` movements leave no
   trace in it, so its head is the ceremony head, not the
   pin head), and the records are attested under the same
   symmetric key, so this is a consistency check over
   caller-supplied input, not rollback or replay
   protection. ``initial_anchor`` additionally requires
   the history to be empty; an explicit empty history is
   a caller assertion that no prior ceremony exists, not
   a fact this module can check."*
   (Two wording fixes ride along: "attested head" →
   "attested ceremony head", for the reason above; and
   the following sentence *"The no-pin reasons …
   receive no recomputation and no history requirement"*
   → *"…receive no recomputation; cycle 20 makes the
   history requirement apply to them as to
   ``chain_gap_recovery``, with ``initial_anchor``
   requiring an empty history (§ per-reason table in
   design-c)."*)

2. **Remaining-limits paragraph — consumption replay.**
   Current: *"consumption-side replay — the verifier's
   ledger burns the (ceremony_id, evidence_hash) pair at
   ISSUANCE, not at consumption, so the same envelope
   presented to ``reanchor_pin`` twice within its TTL
   succeeds if ``ceremony_history`` is omitted (history
   stays optional this cycle; making it mandatory
   belongs to the held cycles' re-review)…"*
   → Replace with the §5 residual paragraph (abridged to
   docstring length, keeping the sentences "Consumption
   single-use is not achieved by this cycle", the
   stale-history mechanism, and "the real fix … is a
   protected monotonic consumption head … an owner-level
   store decision"). Also delete nothing else in that
   paragraph: the M5 ledger-presence limit, the
   ceremony-journal rollback limit, the
   pin-and-record atomicity limit, and the record-MAC
   key sentence are all still true and stay verbatim.

3. **Authorisation paragraph — attribution vs provenance,
   and (conditional on A) symmetry.** Current sentences:
   *"…binds the operator, the ceremony id, the reason,
   the old pin, the candidate and the evidence hash"* and
   *"Operator identity is list membership via the
   verifier's launch channel, not authentication of a
   human, and the MAC is symmetric (any holder of the
   verifier key can forge an envelope), exactly as
   elsewhere in ``signing/``."*
   → The first stays only if "binds" is read as envelope
   binding; add after it: *"That binding is workflow
   provenance — it proves a listed operator's presentation
   was ledgered at issuance for this event — not
   cryptographic attribution: the operator holds no key
   and signs nothing, so nothing in the envelope is
   evidence *by* the operator, only *about* them."*
   → The second sentence, **if seat A lands**: replace
   its tail with *"…not authentication of a human. The
   authorisation signature is asymmetric (cycle 20): the
   verifier's private key never leaves the verifier, and
   this module holds only the pinned public key, so
   possession of everything ``reanchor_pin`` receives no
   longer confers the ability to mint an envelope — the
   cycle-19 symmetric limit is retired for the
   authorisation (it still applies to the ceremony
   record's MAC and elsewhere in ``signing/``). Key
   separation is now cryptographic (distinct key pairs,
   private half verifier-side) plus a retained in-process
   id-inequality tripwire that refuses gross
   misconfiguration; the tripwire compares ids from
   different derivations and does not by itself prove
   distinct key material."*
   If A does **not** land, the current sentence stays
   verbatim and the workflow-provenance addition still
   applies.

4. **Evidence-provenance paragraph — issuance ≠
   consumption.** Current: *"…that the presentation was
   ledgered single-use at issuance…"* — accurate, but the
   paragraph's heading claim ("attribution + event
   binding + issuance-side single-use + a signed
   binding") invites a consumption reading. → Append one
   sentence: *"Issuance-side single-use is accounting at
   the verifier: it proves the pair was burned when the
   envelope was minted. It is not consumption
   enforcement (nothing burns when ``reanchor_pin``
   runs — § residual) and not anchored provenance (the
   anchored store carries neither the evidence hash nor
   the operator id — cycle-19 fix-round wording)."*

5. **Dependency coverage vs complete closure — checked,
   no change in this file.** `pin_ceremony.py`'s
   docstring makes no gate-closure claim (grep: no
   occurrence of closure/coverage/dependency language
   about the gate). GPT's corrected wording therefore
   does **not** touch this module; it belongs to seat A's
   files (§7.1). Recorded here so the sweep is seen to
   have looked, not assumed.

6. **Caller-contract paragraph — add §4.2.** After the
   `classify_verification` paragraph, add the three named
   preconditions (FRESH-PIN / COMPLETE-HISTORY /
   ATOMIC-ADOPTION) with the sentence: *"None of the
   three is verifiable in-process; they are the
   loop/storage layer's obligations, stated here so a
   caller can be audited against them."*

### 7.1 What seats A and B must change in theirs

- **Seat A (gate + authorisation module):**
  (a) `docs/GATE-CLOSURE.md` / `eval/gate.py` comments:
  claim dependency **coverage** of the verdict-defining
  chain (L1+L2), never "complete closure" — L3
  (`gate-import-isolation`) stays named-open. (The
  current GATE-CLOSURE.md line "not an unqualified
  dependency closure" is already correct; the sweep is
  over any *new* cycle-20 wording and the BUILD record.)
  (b) `signing/ceremony_authorisation.py` honest limits:
  the HMAC bullet ("anyone holding the verifier key
  (including a verify-only consumer) can forge") is
  retired/rewritten for asymmetric signing; the phrase
  *"bound to one event, and burned on use"* is **wrong
  today** — the pair is burned at **issuance** — and must
  read "burned at issuance; consumption burns nothing"
  regardless of the signature change.
  (c) The key-separation wording wherever A states it:
  match §7 item 3's downgraded tripwire claim.
- **Seat B (verifier / ledgers / client):**
  (a) `trust/ledger.py`, `trust/verifier_main.py`
  (mode docstring), and the `VerifierClient.ceremony_authorise`
  docstring: every "single-use" mention must carry its
  scope — **issuance accounting** (the dual-append burn),
  never consumption enforcement; if B adds verifier-side
  evidence resolution, its claims must distinguish
  verifier-resolved evidence from the cycle-19
  caller-asserted `evidence_hash`/`evidence_ref`, per
  Gemini defect (1) — that distinction is B's to word,
  C's docstring (§7 item 4) already stays inside it.
  (b) If B proposes verifier-delegated consumption (a
  consumption mode / ledger-presence check, M5) as an
  alternative to §3, that is a coordinator-level either/or
  **before** the build round — §3 and a consumption mode
  compose fine, but neither seat should build on the
  assumption the other is the closure.

## 8. Risks / open questions

**For seat A:**
1. Verify-key type name, key-id derivation, and whether
   `verify_ceremony_authorisation` keeps returning the
   same reason vocabulary (`unknown_key` for a pinned-id
   mismatch is assumed in §4.3/T11). C's step (1)/(2)/(3)
   cannot be finalised until these land.
2. Does A's envelope keep the field name `signature` and
   the `authorisation_id` derivation inputs? Any change
   is opaque to C except through the carried record
   fields — confirm no step-(4) impact.
3. If A's public-key id derivation could *ever* collide
   with `key_id_for`'s namespace, the §4.3 tripwire's
   meaning changes again — state the derivation's domain
   separation explicitly in A's docstring.

**For seat B:**
4. Evidence resolution at issuance (Gemini (1)) changes
   what `evidence_hash` *means* at consumption: if the
   verifier resolves the artefact, does the envelope gain
   a field C must binding-check in step (4), or is
   resolution purely issuance-internal? C currently
   equality-checks the hash only; a new bound field is a
   signature change for C — surface it in B's design.
5. Operator authentication binding (Gemini (4) / GPT):
   if B binds operator identity to anything
   envelope-visible, step (4) gains a leg; if it stays
   issuance-internal, C's §7 workflow-provenance wording
   stands as written. Either answer is workable; silence
   is not.
6. TTL interplay, noted not solved: the stale-history
   residual (T7/T8) is bounded by the envelope's 900 s
   TTL — after expiry the replay dies with the envelope.
   That is a mitigant B owns (TTL policy), **not** a fix,
   and must not be worded as one in B's or the BUILD
   record's text.

**For the coordinator / owner:**
7. §3 satisfies Gemini's fail-closed demand in its
   in-process reading and rev-r6's flip condition
   partially ("mandatory history" was one of its two
   named alternatives — the other, a caller-unomittable
   consumption record, is the protected head). rev-r6's
   dissent should be re-polled on exactly that basis;
   this design does **not** claim F1 closed, and the
   BUILD record must carry F1 as *narrowed, still open*,
   with §5 as the wording.
8. GPT's cycles 14–16 condition ("duplicate consumption
   fails with no/stale history") is met for *no* history
   and unmet for *stale* history (§5). The re-review of
   cycles 14–16 must not be scheduled on the claim that
   cycle 20 met it in full.
9. Risk — assertion theatre: making `()` an explicit
   assertion could tempt a future reader to treat
   supplied-`()` as *verified* emptiness. §7 item 1's
   wording ("a caller assertion … not a fact this module
   can check") is the guard; reviewers should grep the
   built docstring for it.
10. Risk — history length: mandatory history means every
    ceremony re-verifies every prior record's MAC
    (existing O(n) behaviour, now on all paths). No cap
    is proposed this cycle; flag for the storage layer,
    whose head design (§5) subsumes it.
