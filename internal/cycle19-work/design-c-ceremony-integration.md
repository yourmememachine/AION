# Cycle 19 — Design note, seat C: ceremony integration in `signing/pin_ceremony.py`

Scope: how `reanchor_pin` consumes a verifier-issued ceremony
authorisation envelope so operator authority and evidence
provenance come from the Protected Gate's protected store
(`internal/DECISION-PROTECTED-GATE-EXTENSION.md`), closing the
circularity both external seats named in CROSS-CHECK-9/10
("caller-supplied operator list is circular; evidence
non-equality is theatre"). Design only — no production code.
Cycles 14–16 stay HELD; nothing here re-reviews or ships them.
Baseline: 1245 tests OK (skipped=26).

Assumed interfaces from the parallel seats (friction list in §7
pins the exact names I need):

- Seat B: `signing/ceremony_authorisation.py` with a frozen
  dataclass `SignedCeremonyAuthorisation`, a verify function
  `verify_ceremony_authorisation(signed, *, signing_key, now=None)
  -> tuple` mirroring `verify_signed_attestation`'s contract
  (malformed → `SigningError`; authentic-but-failing → reason
  strings; `()` = authentic, unexpired, internally consistent),
  and envelope serialisation
  `ceremony_authorisation_from_dict` / `_to_dict` (the verifier
  returns a dict over the wire; the caller reconstructs the
  object before handing it to `reanchor_pin`).
- Seat B: verifier mode `ceremony_authorise` (added to
  `trust/protocol.py` `MODES` and `trust/verifier_main.py`
  `_MODES`) plus a `VerifierClient.ceremony_authorise(...)`
  method. Issuance is verifier-side ONLY; `signing/` gets no
  `sign_ceremony_authorisation` caller path used by builder code
  (the sign function may exist in B's module for the verifier's
  own use, exactly as `sign_attestation` exists for the
  attester identity).

## 1. Envelope consumption inside `reanchor_pin`

### 1.1 Assumed envelope payload (what B must MAC)

Per the task brief, plus the additions marked ★ that I need:

```json
{
  "v": "ceremony-authorisation/1",
  "alg": "HMAC-SHA256",
  "purpose": "ceremony-authorisation",
  "signer_id": "<verifier identity>",
  "key_id": "<verifier key id>",
  "operator_id": "<id>",
  "ceremony_id": "<id>",
  "reason": "chain_gap_recovery | initial_anchor | lost_pin | corrupted_pin",
  "old_pin": {"cycle_seq": 1, "payload_hash": "<hex64>"} | null,
  "candidate": {"cycle_seq": 4, "payload_hash": "<hex64>",
                "signer_id": "<snapshot signer>", "key_id": "<snapshot key id>"},
  "evidence_hash": "<hex64>",
  "evidence_ref": "<text, ≤2000 chars, attestation precedent>",
  "signed_at": "<iso>", "expires_at": "<iso>"
}
```

Dataclass fields on `SignedCeremonyAuthorisation` mirroring
`SignedAttestation`: the payload fields above plus
`payload_hash`, `authorisation_id`, `signature`.

★ Additions beyond the brief, and why:

- `signer_id` + `key_id` (top level): every other envelope in
  `signing/` carries them; B's verify needs `key_id` for the
  `unknown_key` check and the MAC blob, and the audit trail
  needs to name the issuing verifier identity.
- `purpose`: domain/purpose separation inside the payload, the
  `attestation.py` / `state_snapshot.py` precedent
  (`PURPOSE_CEREMONY_AUTHORISATION = "ceremony-authorisation"`).
  B's module domain string (proposed
  `DOMAIN = "ceremony-authorisation-v1"`) already separates the
  MAC; `purpose` is the in-payload belt to that brace.
- `authorisation_id`: derived exactly as `attestation_id` /
  `snapshot_id` are — `_sha256(_canonical({"v": DOMAIN,
  "payload_hash": ..., "key_id": ...}))`. §4 binds this into
  the ceremony record; without a stable derived id the record
  would have to carry the raw payload hash + key id pair.
- `old_pin` sub-shape is EXACTLY `{"cycle_seq", "payload_hash"}`
  (no optional `key_id`/`signer_id`): the ceremony's strict
  recomputation already binds the pin's key/signer through
  `expected_pin=old_captured` (cycle 16), so duplicating them
  in the envelope adds a second spelling of the same claim.
  If B wants them, they must be optional-and-exactly-checked;
  my default is: not present.
- `ceremony_id` must satisfy `_check_id`
  (`^[a-z0-9_-]{1,64}$`, gate_decision.py:115). The verifier
  generates it (e.g. `"cer-" + token_hex(8)`, the
  `new_request_id` precedent); a caller-proposed id defeats
  its purpose as a verifier-side nonce/handle.

One deliberate non-check: `evidence_ref` CANNOT be
equality-checked inside `reanchor_pin` — the caller has no
independent value to compare it against (that is the whole
point of provenance living verifier-side). It is bound
transitively: record → `authorisation_id` → envelope payload →
`evidence_ref` (§4). Anyone claiming the ceremony "verifies
the evidence_ref" in-process is over-claiming; the docstring
draft in §5 says so.

### 1.2 New `reanchor_pin` signature

```python
def reanchor_pin(old_pin, signed, *, signing_key: SigningKey,
                 state_bytes, calibration_bytes, expected_signer_id,
                 operator_id, reason, evidence_hash,
                 authorised_operators=None,          # legacy path, §2
                 authorisation=None,                  # SignedCeremonyAuthorisation
                 authorisation_key: SigningKey | None = None,
                 strict_reasons=None,
                 now=None, ceremony_history=None) \
        -> tuple[dict, PinCeremonyRecord]:
```

`authorised_operators` gains a default of `None` (today it is
a required keyword). Every existing caller passes it
explicitly, so this is source-compatible with the whole
existing test surface (§6.3). `advance_pin`,
`classify_verification`, `_is_sole_chain_gap` are untouched.

### 1.3 Verification sequence (order matters; each step refuses)

The current function checks the operator list (step ~3) BEFORE
capturing the old pin and the clock. Binding an envelope needs
both captured values, so the protected path reorders minimally:
pin capture and the single clock capture move above the
authority branch. No existing test asserts refusal ORDER
between operator and pin checks (tests assert `SigningError`,
plus message substrings only inside the history checks of
`test_fix_round_cycle16`, which sit downstream and are
unaffected). Sequence:

1. `signing_key` type + `key_id_for` consistency — unchanged.
2. `signed` is a `SignedStateSnapshot` — unchanged.
3. `_check_id(operator_id)`; `reason in REASONS`;
   `_check_hex64(evidence_hash)`; evidence non-equality
   against `(signed.payload_hash, signed.snapshot_id,
   signed.state_sha256, signed.calibration_sha256)` —
   unchanged, and applied on BOTH paths (defence in depth: an
   envelope authorising candidate-derived evidence must still
   not let the ceremony proceed; issuance should never produce
   one, and if it does the ceremony is the last gate).
4. **Contract resolution (§2)** — exactly one authority path:
   - `authorisation is not None and authorised_operators is not None`
     → `SigningError("ceremony authorisation envelope and
     authorised_operators are mutually exclusive; supply exactly
     one authority path")`.
   - `authorisation is None and authorised_operators is None`
     → `SigningError("pin ceremony requires an authority path:
     a ceremony authorisation envelope or the legacy
     authorised_operators list")`.
   - `authorisation is not None and authorisation_key is None`
     → `SigningError("ceremony authorisation supplied without
     authorisation_key; the envelope cannot be verified")` (§3).
   - `authorisation is None and authorisation_key is not None`
     → `SigningError("authorisation_key supplied without a
     ceremony authorisation envelope")` (a dangling key is
     ambiguous intent; refuse rather than ignore).
   - `authorisation` not a `SignedCeremonyAuthorisation`, or
     `authorisation_key` not a `SigningKey` → `SigningError`
     (type refusals, mirroring the existing style).
5. `moment` single clock capture (`_now() if now is None else
   now`) — moved up from its current position; still ONE
   capture for the whole ceremony (cycle-16 rule: freshness
   check, envelope expiry and `performed_at` never straddle a
   boundary by reading the clock twice).
6. Old-pin capture via `_check_pin(old_pin, "old pin")` →
   `(old_seq, old_hash, old_captured)`, each field read ONCE
   (cycle-14 rule) — code unchanged, position moved.
7. **Authority branch:**
   - *Legacy path:* the existing membership check, verbatim:
     `authorised_operators` must be list/tuple/set/frozenset
     and contain `operator_id`, else
     `SigningError("operator is not authorised for a pin ceremony")`.
   - *Protected path:*
     a. `reasons = verify_ceremony_authorisation(authorisation,
        signing_key=authorisation_key, now=moment)`; any
        non-`()` result →
        `SigningError(f"ceremony authorisation does not verify:
        {list(reasons)}")`. This covers MAC (`signature_mismatch`),
        payload re-derivation (`payload_hash_mismatch`,
        `malformed_payload`), key pinning (`unknown_key`,
        `key_id_inconsistent`) and the TTL window (`expired`,
        `signed_in_future`, with the standard 300 s
        `CLOCK_SKEW_SECONDS`) — all inside B's function, none
        re-implemented here.
     b. **Exact binding equality.** Read each envelope field
        ONCE into locals, then compare against the ceremony's
        CAPTURED actuals. Every mismatch is its own
        `SigningError`; there is no "close enough" and no
        partial credit:
        - `env.operator_id != operator_id` →
          "ceremony authorisation is for a different operator"
        - `env.reason != reason` →
          "ceremony authorisation is for a different reason"
        - old pin: `old_pin is None` requires `env.old_pin is
          None`; otherwise `env.old_pin == {"cycle_seq": old_seq,
          "payload_hash": old_hash}` (compared against the
          captured locals, never a re-read of the caller's dict)
          → "ceremony authorisation is bound to a different old pin"
        - candidate: `(env.candidate.cycle_seq,
          env.candidate.payload_hash, env.candidate.signer_id,
          env.candidate.key_id) != (signed.cycle_seq,
          signed.payload_hash, signed.signer_id, signed.key_id)`
          → "ceremony authorisation is bound to a different candidate"
        - `env.evidence_hash != evidence_hash` →
          "ceremony authorisation is bound to different evidence"
        - `env.ceremony_id` re-validated with `_check_id`
          (B's payload builder already does; the ceremony does
          not trust that the object it was handed was built by
          B's parser — same posture as
          `verify_ceremony_record` re-validating invariants).
8. Everything downstream is UNCHANGED: reason/pin coherence,
   `_candidate_relation` refusals, the cycle-16 strict
   recomputation for `chain_gap_recovery`,
   `_check_ceremony_history`, the bare-verifier attestation
   check, record construction (§4 additions only).

No fallback: if the envelope fails verification or binding,
the ceremony refuses. It NEVER falls through to the list —
there is no list on this path (§2a), and a "try envelope,
else list" ladder would reintroduce exactly the silent
downgrade the external seats flagged.

TOCTOU note (GPT, CROSS-CHECK-10): `signed` and the envelope
are frozen dataclasses and the pin is captured once via
`_check_pin`, so the objects bound in step 7b are the objects
used through record construction — the cycle-16 qualification
carries over unchanged.

## 2. The contract question — decisions

**(a) Both supplied → REFUSE as ambiguous.** Not "envelope
wins". Three reasons. (i) Auditability: the record (§4) states
which authority backed the jump; if both inputs are present
and one is silently ignored, the caller's expressed intent and
the effective authority diverge invisibly — the caller who
passed a stale list believes the list governed. (ii)
Fail-closed symmetry with the rest of `signing/`: exact key
sets, no unknown fields, no duplicate spellings of one claim
(the empty-calibration rule in `state_snapshot.py` is the
direct precedent: two spellings of roughly the same claim
invite silent confusion, so one is refused). (iii) Migration
cost is one deleted argument; there is no legitimate caller
who needs both.

**(b) Neither supplied → REFUSE.** With `authorised_operators`
defaulting to `None`, absence must not become a third,
unauthorised path. The envelope becomes an ALTERNATIVE
authority path, never an optional extra on top of a default.
Refusal message in §1.3 step 4.

**(c) Legacy path: keep, name it UNPROTECTED, deprecate in the
docstring.** The list parameter stays so the held cycles'
tests keep running unchanged until cycles 14–16 are
re-reviewed (per the owner decision, that re-review happens
after this extension lands, and adopting the envelope path is
a condition of it). But it is renamed in every doc surface as
the legacy/UNPROTECTED path (§5 draft), and §4 makes its use
visible forever in the audit record (`authorisation_id == ""`).

**Why this is not cycle 16's "opt-in protection" defect.**
Gemini's cycle-16 FIX was about `ceremony_history=None`
SILENTLY disabling anti-replay checks that were part of the
same authorisation claim — the caller believed it had the
protection and did not. The design here differs on every axis
that made that a defect:

- Not silent: exactly one path must be explicitly supplied;
  supplying neither refuses; supplying both refuses. There is
  no default that quietly means "no authority check" — the
  check always runs; only its SOURCE differs.
- Not a toggle on one path: the legacy list is a distinct,
  named alternative with its own check, not a `None` that
  switches the envelope checks off. When an envelope is
  supplied, the list is not consulted, weakened, or fallen
  back to — it is refused if present at all.
- Not invisible after the fact: the record binds
  `authorisation_id` (envelope path) or `""` (legacy path),
  so which authority governed is auditable from the record
  alone (§4). Cycle 16's history omission left no trace;
  this leaves one by construction.
- Named as unprotected where it lives: the docstring calls
  the legacy path UNPROTECTED in the signature's own module,
  not in a separate review file (§5).

Residual honesty: within a single deployment, a caller who
still holds the legacy path available can choose it. That is
a deployment-policy fact (production wiring should simply
never pass the list), not something this function can
enforce without breaking the held cycles' tests — stated
plainly in the docstring draft.

## 3. The verification key — `authorisation_key`

- Parameter: `authorisation_key: SigningKey | None = None`,
  keyword-only, NO default substitution. In particular it must
  never default to `signing_key`: silently verifying the
  verifier's envelope under the snapshot key would defeat key
  separation while looking like it worked.
- Refusals: envelope without key → §1.3 step 4 message. Key
  present but inconsistent (`key_id != key_id_for(key)`) →
  B's verify returns `("key_id_inconsistent",)` per the
  attestation/snapshot precedent, which step 7a converts to a
  `SigningError`. Envelope under a different key than
  `authorisation_key` → `unknown_key` / `signature_mismatch`
  from B's verify → same conversion.
- Key separation (external item 6): the envelope is signed
  under the VERIFIER's key and MACed under B's own domain
  (`ceremony-authorisation-v1`), so even where one key file
  serves a research deployment, the authorisation is
  domain-separated from snapshot MACs and from the ceremony
  record's MAC (`snapshot-pin-ceremony-v1`, still under
  `signing_key` — unchanged this cycle; moving the record MAC
  is out of scope and noted in §5). I do NOT propose refusing
  `authorisation_key.key_id == signing_key.key_id` in-process:
  the trust fixtures legitimately run one key for the whole
  verifier home (test_trust_verifier.py's discipline: the
  test/consumer side holds the key to verify outcomes), and
  distinctness of key FILES is a deployment property. The war
  room may overrule me; if it wants enforcement, the refusal
  is one line in step 4 and the E2E fixture grows a second key
  file — flagged in §7.
- **Prototype honesty (must appear in the docstring, §5):**
  in-process verification requires the verifier's key
  in-process, and HMAC is symmetric — any process holding
  `authorisation_key` can FORGE an envelope, exactly as
  everywhere else in `signing/`. The in-process path is
  therefore the key-holding-consumer / research shape (the
  test_trust_verifier fixture discipline). The production
  shape is routing: the caller obtains the envelope from the
  verifier subprocess (`ceremony_authorise`) and the ceremony
  runs where the verifier key legitimately lives, OR a future
  verifier mode checks the envelope verifier-side. Layering
  constraint, non-negotiable: `signing/` must not import
  `trust.*` (the dependency runs the other way), so
  `pin_ceremony.py` itself can never spawn the subprocess —
  production wiring belongs to seat A's layer, and which
  process holds `authorisation_key` in that wiring is an
  explicit open question for A (§7), not something this
  module can settle.

## 4. `PinCeremonyRecord` — bind `ceremony_id` + `authorisation_id`: INCLUDE

Recommendation: **include both fields now**, as
`ceremony_id: str` and `authorisation_id: str`, both `""` on
the legacy path, both part of `payload()` and therefore of
the MAC.

Breakage assessment (verified by grep this round):

- Direct construction: `PinCeremonyRecord(` appears exactly
  ONCE in the codebase — inside `reanchor_pin` itself
  (pin_ceremony.py:524). No test constructs one directly;
  tests obtain records from `reanchor_pin` and mutate them
  with `dataclasses.replace(...)`, which carries new fields
  over untouched.
- `verify_ceremony_record` re-derives via `record.payload()`
  (the single re-derivation point), so adding the fields to
  `payload()` binds them under the existing MAC with no
  change to the verify algorithm. `test_fix_round_cycle16`
  re-MACs modified records via `_payload_hash(one.payload())`
  + `_mac(...)` — it re-derives from `payload()`, so it stays
  correct automatically.
- No test asserts a literal ceremony `payload_hash` value
  (grep: `payload_hash` in the test file is snapshot/pin
  data, never a hard-coded record hash), so the payload-shape
  change breaks no golden value.
- Giving both fields a default of `""` keeps even hypothetical
  positional construction source-compatible (they append at
  the end of the field order, before `payload_hash` /
  `signature` — NO: appending before existing fields breaks
  positional construction; append them AFTER `signature`?
  Frozen dataclass field order: `payload_hash` and `signature`
  are last and are always passed by keyword in the one
  constructor. Safest: add `ceremony_id` and
  `authorisation_id` as the final two fields WITH defaults
  `""`, after `signature`. `replace()`-based tests are
  unaffected either way.)

New invariants in `verify_ceremony_record` (it already
re-validates ceremony invariants rather than trusting the
MAC — extend that list):

- `authorisation_id` non-empty → must be hex64, else reason
  `"invalid_authorisation"`; empty → legacy record, no reason.
- `ceremony_id` non-empty → must pass `_check_id`, else
  `"invalid_authorisation"` (one shared reason string keeps
  the reason vocabulary small; if the war room wants them
  split, split then).
- No attempt to verify the envelope itself from the record:
  without pin context the record still proves ISSUANCE only —
  now issuance *under a named authorisation*, when one is
  bound. That is the honest claim.

Why not defer: (i) CROSS-CHECK-9's P0 demands evidence
provenance "bound to the recovery event (old pin, candidate,
reason, operator, ceremony id)" — the record is where that
binding becomes auditable after the fact; without it the
envelope is checked at ceremony time and then evaporates,
and a later reader cannot tell a protected ceremony from a
legacy one. (ii) Deferring means a SECOND payload-shape
change later, and every record issued in between permanently
lacks the binding. (iii) The cost now is measured above:
one constructor, one `payload()`, two verify invariants,
zero test breakage. The `evidence_ref` reaches the audit
trail through this chain: record.authorisation_id →
envelope.payload_hash → envelope payload's `evidence_ref`
(§1.1) — which is also why B must expose `authorisation_id`
as a derived field, not leave C to recompute it from parts.

`_check_ceremony_history` is unaffected semantically: it
verifies records via `verify_ceremony_record`, and mixed
legacy/protected histories verify side by side. (Whether a
history containing legacy records should satisfy a protected
deployment is policy for the re-review of cycles 14–16, not
this cycle.)

## 5. Docstring honesty updates — drafted replacement wording

Three places in `pin_ceremony.py`'s module docstring change.
Drafted verbatim:

**(a) The `reanchor_pin` bullet** — replace "an operator on a
caller-supplied authorised list" with:

> - ``reanchor_pin`` is the exceptional movement. It requires
>   ALL of: operator authority from exactly one of two named
>   paths (below); an allowlisted reason; independent evidence
>   (a hex64 hash that is NOT derived from the candidate
>   itself — a pin must never be reconstructed from the
>   snapshot being verified); and a candidate that passes
>   every attestation binding (exact state bytes, exact
>   calibration bytes, signer pin, calibration required) under
>   the bare verifier. …

**(b) The authorisation honest-limit bullet** — replace the
current "Authorisation is a caller-supplied list checked
in-process; …" bullet with:

> - Authorisation has two paths, exactly one of which must be
>   supplied (both or neither is refused). The PROTECTED path
>   (cycle 19) is a ceremony authorisation envelope issued by
>   the verifier (mode ``ceremony_authorise``) from the
>   Protected Gate's own operator list: the envelope binds the
>   operator, the ceremony id, the reason, the old pin, the
>   candidate and the evidence hash, is MACed under the
>   verifier's key in its own domain, expires on a short TTL,
>   and is checked here for MAC, expiry and EXACT binding
>   against this ceremony's captured parameters — an envelope
>   for any other operator, pin, candidate or evidence is
>   refused, and the caller-supplied list is never consulted
>   on this path. The LEGACY path is the pre-cycle-19
>   caller-supplied ``authorised_operators`` list, checked
>   in-process: it is UNPROTECTED (the caller asserts its own
>   authority — the circularity the external seats flagged in
>   cycles 14–16), is retained only so the held cycles'
>   behaviour stays runnable until their re-review adopts the
>   envelope path, and must not be used by production wiring.
>   Which path governed is recorded in the audit record
>   (``authorisation_id`` set, or empty for legacy). Neither
>   path proves the operator is a distinct human; the envelope
>   path's boundary is the verifier's key placement and its
>   protected operator store, and in-process envelope
>   verification needs that key in-process, so a process
>   holding it can forge envelopes — production routing keeps
>   the key verifier-side (see the ceremony authorisation
>   module).

**(c) The evidence honest-limit bullet** — replace the current
"Evidence independence is enforced only as non-equality …"
bullet with:

> - Evidence provenance differs by path. On the protected
>   path, the verifier issues the authorisation only against
>   evidence it has itself sourced/checked in its protected
>   store, and binds the evidence hash and an evidence
>   reference into the envelope; this module verifies that
>   binding exactly, and the audit record names the
>   authorisation, so the provenance claim is auditable after
>   the fact. The evidence reference itself is not (and
>   cannot be) re-checked in-process — the caller has no
>   independent value for it. On the legacy path, evidence
>   independence is still enforced only as non-equality with
>   the candidate's own hashes: a re-hash of the candidate is
>   refused, an invented hex64 passes, and that the evidence
>   genuinely comes from an independent source is a
>   caller/operator duty this code cannot prove. The
>   non-equality check runs on both paths as defence in depth.

**(d) The cycle-16 "does NOT fix" paragraph** — amend the two
relevant clauses: "operator authority is still a
caller-supplied list (…)" and "evidence is still a bare
digest whose provenance this module cannot prove (…)" gain
the suffix "— both addressed for the envelope path in cycle
19 (see above); the statements stand for the legacy path."
And the key-separation clause gains: "the ceremony
AUTHORISATION is MACed under the verifier's key in its own
domain (cycle 19); the ceremony RECORD's MAC still uses the
snapshot signing key."

Also: `reanchor_pin`'s own docstring gains one paragraph
naming the two paths, the mutual-exclusion refusal, and the
no-fallback rule; `PinCeremonyRecord`'s fields are documented
at the dataclass (two-line comment: empty = legacy path).

## 6. Test plan

### 6.1 New end-to-end file: `tests/test_trust_ceremony_authorisation.py`

Following `test_trust_verifier.py`'s `VerifierFixture`
verbatim in shape: temp verifier-home (0700), `generate_key_file`
key, fake registry, env dict (`AION_VERIFIER_KEY_PATH`,
`AION_VERIFIER_SIGNER_ID`, `AION_VERIFIER_ACTOR_ID`,
`AION_REGISTRY_DIR`, `AION_VERIFIER_HOME`,
`AION_DEPLOYMENT_MODE=research`) PLUS seat A's protected-store
env for the operator list / evidence (names are A's to fix —
§7). The fixture holds the verifier key test-side ONLY to
verify outcomes and to build negative fixtures, per that
file's stated discipline. Snapshots/pins built with the
existing test_signing_pin_ceremony helpers' shapes (own copies,
self-contained file).

Helper: `authorise(self, old_pin, cand, **over)` →
`self.client.ceremony_authorise(operator_id=..., reason=...,
old_pin=..., candidate={...}, evidence_hash=...,
evidence_ref=...)`, reconstruct via
`ceremony_authorisation_from_dict`, then call `reanchor_pin`
with `authorisation=` + `authorisation_key=self.key` and NO
`authorised_operators`.

Tests (names final):

1. `test_listed_operator_envelope_reanchor_succeeds_without_caller_list`
   — listed operator → envelope → `reanchor_pin` succeeds;
   new pin equals candidate pin; record verifies `()`;
   `record.ceremony_id == envelope.ceremony_id`,
   `record.authorisation_id == envelope.authorisation_id`.
2. `test_invented_operator_refused_verifier_side_no_envelope`
   — `ceremony_authorise` for an operator not in the
   protected store raises (`VerifierConfigError`, the
   unsigned-refusal precedent from `issue_attestation`;
   exact exception is A/B's to confirm, §7) and NO envelope
   exists to present. (GPT's named test: invented operator list.)
3. `test_forged_envelope_under_attacker_key_refused` — an
   envelope-shaped object MACed test-side under a different
   key (B's sign function + `make_signing_key(b"\xff"*32)`)
   → `SigningError` at `reanchor_pin` even for a listed
   operator. (Proves the caller cannot mint authority.)
4. `test_envelope_replayed_against_different_candidate_refused`
   — envelope for candidate A presented with candidate B →
   binding `SigningError`. (GPT: replayed against a different
   pin state — candidate half.)
5. `test_envelope_replayed_against_different_pin_refused` —
   envelope issued for old pin A presented with old pin B
   (both genuine gap ceremonies) → binding `SigningError`.
   (GPT: replayed record against a different pin state —
   pin half.)
6. `test_evidence_hash_swapped_refused` — envelope issued for
   evidence X, ceremony called with evidence Y →
   `SigningError`; also envelope's own evidence swapped
   test-side (payload tamper) → B-verify failure →
   `SigningError`. (GPT: random evidence hash — a random hash
   now fails unless the VERIFIER bound it.)
7. `test_evidence_reuse_across_events_refused` — the same
   envelope presented for a second, different ceremony →
   binding refusal (distinct from cycle 16's history-level
   reuse, which is unchanged). (GPT: evidence reuse across events.)
8. `test_expired_envelope_refused` — authorise, then call
   `reanchor_pin(..., now=<past expires_at>)` via the existing
   `now=` test seam → `SigningError` mentioning the verify
   reasons. (The seam is test-only, as everywhere in signing/.)
9. `test_wrong_authorisation_key_refused` — genuine envelope,
   `authorisation_key` = a different `SigningKey` →
   `SigningError` (`unknown_key`/`signature_mismatch` inside).
10. `test_both_authority_paths_refused_ambiguous` — envelope
    AND `authorised_operators=[operator]` (operator IS
    listed, so only the ambiguity rule can refuse) →
    `SigningError`.
11. `test_neither_authority_path_refused` — no list, no
    envelope → `SigningError`.
12. `test_envelope_without_authorisation_key_refused`;
    `test_authorisation_key_without_envelope_refused`.
13. `test_operator_arg_mismatch_refused` — envelope for
    operator-2, ceremony called as operator-1 →
    `SigningError`. `test_reason_mismatch_refused` — envelope
    for `lost_pin` (old pin None), ceremony called with
    `chain_gap_recovery` + a pin → `SigningError` (binding
    fires before/independent of reason-coherence).
14. `test_no_pin_ceremony_envelope_path` — `initial_anchor`
    with `old_pin=None` end-to-end: envelope's `old_pin` is
    null, reanchor succeeds, record binds the ids.
15. `test_legacy_record_carries_empty_authorisation_id` — a
    legacy-path record has `ceremony_id == authorisation_id
    == ""` and still verifies `()`; a protected record with
    `authorisation_id` swapped via `replace` →
    `payload_hash_mismatch`; with `authorisation_id` replaced
    by a non-hex64 string → `"invalid_authorisation"` in
    `verify_ceremony_record` reasons.
16. `test_envelope_path_with_ceremony_history_still_enforced`
    — protected path + cycle-16 history reuse refusal still
    fires (paths compose; the envelope does not bypass history).

### 6.2 Pure-unit additions (in the same new file or a small
class in it, no subprocess): contract-resolution refusals
(10–12) can also run in-process with a test-side-signed
envelope for speed, but the E2E versions above are the ones
that count; do not duplicate — keep 10–12 E2E-only and let
the legacy suite cover the list path.

### 6.3 Existing tests touched: NONE

`tests/test_signing_pin_ceremony.py` requires no edits:
every call passes `authorised_operators` explicitly (the
`reanchor()` helper sets it via `setdefault`), the new
parameters default to `None`, `PinCeremonyRecord` gains
defaulted trailing fields, and no assertion depends on the
record payload's exact hash (§4). The full suite expectation
after the build: 1245 + 16-ish new, skipped=26, with
`test_signing_pin_ceremony.py` byte-identical. If the build
finds it must touch that file, that is a design smell to
bring back to the war room, not a silent edit.

## 7. Interface friction / asks of seats A and B

**Of B (envelope module + verifier mode) — blocking for C:**

1. Exact payload key names as in §1.1, in particular nested
   `old_pin` / `candidate` with EXACTLY the subkeys shown;
   `old_pin` carries no `key_id`/`signer_id`. If B's payload
   uses flat fields (`old_cycle_seq`, …) instead, C's binding
   code changes shape — either is workable, drifting between
   them is not. Pin it in B's note.
2. Verify function name/signature:
   `verify_ceremony_authorisation(signed, *, signing_key,
   now=None) -> tuple`, reason vocabulary mirroring
   attestation (`unknown_key`, `key_id_inconsistent`,
   `payload_hash_mismatch`, `signature_mismatch`,
   `malformed_payload`, `expired`, `signed_in_future`). C
   converts any non-`()` to `SigningError` and does not parse
   individual reasons — but the E2E tests quote them, so the
   vocabulary must be stable.
3. `authorisation_id` exposed as a dataclass field AND a
   derivation function `authorisation_id_for(payload_hash,
   key_id)` (precedent: `snapshot_id_for`,
   `_attestation_id`). §4 depends on the field existing.
4. `ceremony_id` format: verifier-generated, `_check_id`-safe
   (`^[a-z0-9_-]{1,64}$`). A UUID with hyphens passes; a
   hex token passes; anything with uppercase/spaces does not.
5. TTL policy: propose default 900 s (attestation precedent),
   bounded by `TTL_MIN_SECONDS`/`TTL_MAX_SECONDS`, expiry
   semantics `moment >= expires_at` ⇒ `expired`. C passes its
   single captured `moment` as `now=`; B's verify must accept
   `now=` (test seam only, same warning as elsewhere).
6. Serialisation names: `ceremony_authorisation_to_dict` /
   `ceremony_authorisation_from_dict` with exact key sets
   (attestation precedent), since the client returns a dict
   and C's caller must reconstruct a typed object —
   `reanchor_pin` takes the OBJECT, never a raw dict (a dict
   parameter would invite callers to hand-assemble one).
7. Client method + refusal surface: `VerifierClient.
   ceremony_authorise(...)` return shape (envelope dict only,
   or dict + metadata?) and which exception an unlisted
   operator / unprovenanced evidence raises verifier-side —
   C's test 2 asserts it. Precedent says unsigned refusals are
   `VerifierConfigError` (exit 3); a signed "refusal envelope"
   would be a design change — say which.

**Of A (protected store):**

8. Env/config names for the protected operator list and the
   evidence-provenance source, and the issuance-side checks
   the verifier performs on `evidence_hash`/`evidence_ref`
   before binding them (C cannot specify A's store, but C's
   docstring draft §5c claims "evidence it has itself
   sourced/checked" — A must confirm that claim is true of
   the store design, or §5c gets weakened before the build).
9. Production wiring: which process calls `reanchor_pin` in
   the protected deployment and where `authorisation_key`
   legitimately lives (§3 layering). If the answer is "the
   verifier process itself runs the ceremony", C's signature
   already supports it; if it is "a key-holding consumer",
   the docstring's prototype honesty covers it; if it is
   "neither — verification must move verifier-side", that is
   a new verifier mode (`ceremony_verify`) and a bigger C
   change — surface it NOW, not at the war room.
10. Single-use: nothing in-process stops the SAME envelope
    being presented twice for the IDENTICAL ceremony (same
    pin, candidate, evidence) when no `ceremony_history` is
    supplied — binding equality makes it single-EVENT, not
    single-USE. Recommend the verifier ledgers issued
    `authorisation_id`s (the `SigningLedger` precedent) so
    issuance is auditable; consumption-side single-use needs
    the protected head/history work that remains future
    scope. Flagged as a residual for the docstring, not
    silently dropped.

**Open question for the war room (from §3):** enforce
`authorisation_key.key_id != signing_key.key_id` in-process?
C recommends no (deployment property; fixture reality);
GPT's cycle-16 list has "MAC key separation provisioned and
enforced" — if the room reads "enforced" as in-process, the
refusal is one line in step 4 and the E2E fixture needs a
second key file in the verifier home. Decide before the
build round, because it changes the fixture.
