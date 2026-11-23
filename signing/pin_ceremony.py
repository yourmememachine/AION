"""Authorised pin re-anchoring (the snapshot pin ceremony).

Cycle 15 (backlog item ``snapshot-pin-ceremony``). Cycle 14 made
the strict snapshot wrapper refuse any candidate more than one
sequence past the caller's pin (``chain_gap``). That refusal is
refuse-on-gap by design, but without a recovery path it is also a
liveness trap: a missed or expired intermediate deadlocks strict
catch-up forever. Both external war-room seats (cycle 14) and the
internal forced-dissent seat named the same fix — build the
ceremony BEFORE any production caller depends on the wrapper.
This module is that ceremony, and nothing else:

- ``advance_pin`` is the ONLY normal pin movement: exactly one
  sequence forward, only on a verification result of ``()``, and
  only when the candidate chains to the current pin. Same-sequence
  same-hash is an idempotent no-op; everything else is refused.
- ``reanchor_pin`` is the exceptional movement. It requires ALL
  of: a verifier-issued ceremony authorisation envelope (cycle
  19, made asymmetric in cycle 20 — operator-id allowlist
  eligibility comes from the verifier's own protected operator
  list, never from the caller; there is no caller-supplied list
  and no fallback path); an allowlisted
  reason; independent evidence (a hex64 hash that is NOT derived
  from the candidate itself — a pin must never be
  reconstructed from the snapshot being verified); and a candidate
  that passes every attestation binding (exact state bytes, exact
  calibration bytes, signer pin, calibration required) under the
  bare verifier. Re-anchoring never moves a pin backwards, never
  replaces a pin at the same sequence with a different snapshot,
  and is refused when the normal one-step advance would have
  worked — the ceremony must not become a routine bypass.
- Every successful re-anchor returns a MAC-bound audit record
  (domain ``snapshot-pin-ceremony-v1``) naming the old pin, the
  new pin, the operator, the reason and the evidence hash, so a
  later reader can verify the jump was ceremonied, not silent.
  ``verify_ceremony_record`` re-derives and checks that record.

Caller contract (external seats, cycle 14): verification outcomes
are classified by ``classify_verification`` into exactly three
buckets — ``ok``, ``reanchor_required`` (a sole ``chain_gap``:
every attestation binding passed, only step-observation failed)
and ``integrity_failure`` (anything else). Callers must handle
``reanchor_required`` through this ceremony and must treat
``integrity_failure`` as a stop, never as a ceremony trigger.

Caller preconditions (cycle 20) — obligations of the caller (the
future loop/storage layer) that this function CANNOT verify;
they are documented here so a caller can be audited against
them, not because naming them enforces them:

- FRESH-PIN: ``old_pin`` must be read from the caller's pin
  store at the start of this ceremony attempt, not cached,
  reconstructed, or replayed from an earlier attempt.
- COMPLETE-HISTORY (cycle 21: demoted from a security
  precondition to an audit obligation): ``ceremony_history``
  should contain every ceremony record the caller has ever
  accepted, in particular including the record of any prior
  consumption of this same envelope. Since cycle 21 the
  history is an audit/consistency input that can only refuse,
  never grant; the verifier's consumption head is
  authoritative on any discrepancy (see the cycle-21 section
  below).
- ATOMIC-ADOPTION: on success the caller must persist the
  returned pin and append the returned record to its history
  as one step, before any further ceremony or advance; on
  refusal it must persist neither.
- EVIDENCE-INTENT: ``evidence_hash`` must come from the
  caller's own record of the evidence it reviewed, never
  copied from the presented envelope; copying it converts the
  binding check into an echo.

None of the four is verifiable in-process; they are the
loop/storage layer's obligations, stated here so a caller can
be audited against them.

Honest limits:

- The step-observation check is NOT a cryptographic continuity
  proof. It establishes observable continuity relative to the
  supplied pin only: the verifier observed pin, then pin+1.
  Pruned *snapshot* sequences trigger ``chain_gap`` regardless of
  why they are missing (missed, expired, filtered or pruned);
  pruned *state* history inside a snapshot remains legitimate.
- The dense-emission assumption (one snapshot taken and verified
  per cycle) belongs to the loop/storage layer, not this module,
  and is not proven here. Where emission is not dense, gaps are
  expected and each one costs a ceremony — that cost is the
  stated price of refuse-on-gap step-observation, not a defect
  this module hides.
- Authorisation (cycle 19; asymmetric since cycle 20) comes
  from a verifier-issued, event-bound ceremony authorisation
  envelope: the operator list lives in the verifier's protected
  config, and the envelope — signed under the verifier's
  Ed25519 key, in its own domain — binds the operator, the
  ceremony id, the reason, the old pin, the candidate and the
  evidence hash. This module verifies the envelope's signature
  and expiry on the ceremony's single captured clock and checks
  EXACT binding against the ceremony's captured parameters; an
  envelope for any other operator, pin, candidate or evidence
  is refused, and an envelope failure never falls back to any
  other authority path. The authorisation is asymmetric:
  forgery requires the verifier's seed, which never leaves the
  verifier process; this module holds only the pinned public
  key (a ``CeremonyPublicKey``, a type that cannot hold secret
  material), so possession of everything ``reanchor_pin``
  receives no longer confers the ability to mint an envelope,
  and a forged envelope fails verification IN PROCESS, not
  merely on audit. Key separation is type separation (a
  ``SigningKey`` passed as the authorisation public key is a
  type refusal) plus role separation (minting material is
  absent from the ceremony process). There is no in-process
  id-inequality check: the cycle-19 check compared key ids
  from disjoint derivation namespaces (``pub-…`` for the
  authorisation public key, ``key-…`` for the snapshot key),
  so it could never fire for any key material, and cycle 20
  deleted it rather than keep a guard that guards nothing;
  the real seed-reuse defence is provisioning-side, in the
  verifier's configuration.
  Operator identity is operator-id allowlist eligibility via
  the verifier's launch channel, not authentication: the
  verifier checks that the presented operator_id was on its
  configured allowlist at issuance; it does not and cannot
  verify that the presenter *is* that operator — no
  per-operator credential exists in this system, and any caller
  able to launch the verifier can present any listed id. The
  envelope proves a presentation under an allowlisted id,
  ledgered at issuance and bound to this event — workflow
  provenance, not cryptographic attribution: nothing in the
  envelope is evidence *by* the operator, only *about* them,
  and it does not prove which human or process made the
  presentation.
- Evidence provenance (cycle 19; resolution added cycle 20) is
  workflow attribution + event binding + issuance-side single-use + a
  signed binding. At issuance the verifier resolves the
  evidence artefact itself under its configured evidence root
  and hashes the bytes it read; the hash carried in the
  envelope is the verifier-computed hash, cross-checked
  against the hash the presenter supplied, and the verifier
  retains a copy of the resolved bytes. What the envelope
  proves is that an allowlisted operator id presented this
  evidence bound to this exact event, that the presentation
  was ledgered single-use at issuance, and that the binding is
  signed by the verifier's key. NO consumption path reads
  retained copies: retention is an audit artefact for a future
  audit process, ``reanchor_pin`` neither consults nor can
  consult the retained bytes, and the signed envelope hash is
  the commitment to them. In-process, evidence independence is
  additionally enforced as non-equality with the candidate's
  own hashes (war-room cycle 15, forced-dissent seat): a
  re-hash of the candidate is refused at the ceremony as
  defence in depth. The envelope's ``evidence_ref`` is not
  (and cannot be) equality-checked in-process — the caller has
  no independent value for it; it is bound transitively
  through the audit record's ``authorisation_id``.
  Issuance accounting, consumption enforcement and anchored
  provenance are three separate claims: issuance-side
  single-use is accounting at the verifier (it proves the pair
  was burned when the envelope was minted); it is NOT itself
  consumption enforcement. Consumption enforcement is the
  separate cycle-21 mechanism (see the cycle-21 section
  below): under the mandated production wiring,
  ``reanchor_pin`` invokes the required
  ``consume_authorisation`` callable exactly once, after
  every local check and before the ceremony record is
  constructed, and the verifier-backed consumer burns the
  authorisation in the verifier's consumption journal before
  any record exists. That protection holds only under that
  wiring — a caller-supplied no-op callable gets no
  protection (the R5 integrated-system wording in the
  cycle-21 section below). Issuance single-use is also NOT
  anchored provenance (the anchored store carries neither
  the evidence hash nor the operator id).
- The returned pin is the ordinary pin shape, so downstream
  continuity looks clean unless the caller retains and checks
  the ceremony record; nothing in the pin itself marks the jump.
  Binding the record hash into the pin is future work requiring
  a pin-format change in the verifier.
- A re-anchor asserts the candidate is authentic NOW; it asserts
  nothing about the unobserved intermediates, which stay
  unobserved forever. The audit record preserves that gap
  explicitly (``gap_from_seq`` / ``gap_to_seq``) instead of
  laundering it into continuity.

Cycle 16 hardening (external seats' combined cycles 14+15
review): for ``chain_gap_recovery`` the strict result is
RECOMPUTED inside ``reanchor_pin`` against the captured pin —
a caller-supplied ``("chain_gap",)`` that does not match the
recomputation is refused, so eligibility is bound to this pin
and this candidate (including the pin's key/signer bindings,
when the pin carries them — a pin without those optional
fields has no bindings to bind to). A gap candidate whose
``prev_snapshot_hash`` names the pin itself is refused as an
integrity failure. A required ``ceremony_history`` (verified
records only; ``None`` refuses for every reason — cycle 20,
fail-closed on omission) refuses evidence reuse, replayed
targets, candidates behind the history's attested ceremony
head, and candidates predating the latest ceremony — ONLY
under a complete, caller-supplied history: a truncated or
stale history silently passes every one of those checks, the
history records ceremonies only (``advance_pin`` movements
leave no trace in it, so its head is the ceremony head, not
the pin head), and the records are attested under the same
symmetric key, so this is a consistency check over
caller-supplied input, not rollback or replay protection.
Fail-closed on omission means exactly that: omission refuses,
but an explicit empty history is a caller assertion that no
prior ceremony exists — a claim this module cannot check, not
verified continuity. ``initial_anchor`` additionally requires
the history to be empty; ``initial_anchor`` refusing on any
non-empty history, including unrelated-lineage history, is
deliberate; the recovery is a ``lost_pin`` authorisation, not
a history edit. The no-pin reasons (``initial_anchor`` /
``lost_pin`` / ``corrupted_pin``) receive no recomputation;
cycle 20 makes the history requirement apply to them as to
``chain_gap_recovery``, with ``initial_anchor`` requiring an
empty history. Without pin context,
``verify_ceremony_record`` proves a record was issued, not
that it applies to the caller's pin state.
``verify_ceremony_record`` refuses one-step records (which this
ceremony can never issue) and, when the caller supplies the
expected pin context, records replayed against a different pin
state. What cycle 16 did NOT fix, and cycle 19 now addresses via
the protected path: (1) operator-id allowlist eligibility was
a caller-supplied list — it now comes from a verifier-issued,
event-bound authorisation whose operator list lives in the
verifier's protected config; (2) evidence was a bare digest
whose provenance this module could not prove — it is now
bound, attributed and issuance-side single-use as described
above, and since cycle 20 the verifier resolves and hashes
the artefact itself at issuance.
The REMAINING limits, stated plainly (cycle 21): consumption
single-use is achieved ONLY as an integrated-system property
(see below), not by this function alone. The verifier's
ledger burns the (ceremony_id, evidence_hash) pair at
ISSUANCE, and — since cycle 21 — the verifier's consumption
journal burns the authorisation at CONSUMPTION, consulted
through the required ``consume_authorisation`` callable.

Cycle 21 — consumption head and the integrated-system claim:

- reanchor_pin is no longer an offline function — a
  successful ceremony requires a live verifier round-trip
  inside the envelope's TTL and fails closed when the
  verifier is unreachable; every existing direct caller
  breaks with TypeError until it supplies the keyword, and
  that flag-day breakage is intended.
- Single-use consumption and pin non-regression are
  properties of the INTEGRATED SYSTEM under its production
  wiring — authorise via VerifierClient, re-anchor with
  the verifier-backed consumer, adopt the returned pin
  atomically — not properties of reanchor_pin for an
  arbitrary caller-supplied callable. A no-op callable gets
  no protection, exactly as a caller supplying its own
  signing key or a wrong public-key pin gets none; the
  callable is not materially different from the inputs
  reanchor_pin already trusts.
- Crash-consistency contract: Consumption is committed at
  the verifier — a fsync'd consumption-journal append —
  before reanchor_pin returns anything. There is no
  execution path in the integrated system in which a pin
  movement succeeds without its consumption record durably
  committed first. A crash after the commit but before
  adoption leaves the authorisation burned and the pin
  unmoved; a lost or ambiguous response is treated as
  burned; the client never retries a consume automatically.
  Recovery is a new ceremony (new ceremony_id, new
  evidence), never an un-consume.
- ``ceremony_history`` after the head: the history is an
  audit/consistency input that can only refuse, never
  grant; the verifier's consumption head is authoritative
  on any discrepancy. A stale or empty history no longer
  enables replay when the production consumer is wired,
  because the consumer refuses already-consumed and
  head-regression cases the history cannot see.

Issuance-journal rollback residual (the ceremony
authorisation — ISSUANCE — journal; NOT the consumption
journal): no consumption-side ledger-presence check exists
in-process (the ceremony cannot read the verifier's ledgers
— limit M5); the issuance journal's reuse memory is
rollback-vulnerable until the follow-up
``ceremony-journal-anchoring`` lands (reuse is prevented
against an intact issuance journal; after a rollback it is
detectable only for same-ceremony_id reuse, and otherwise
only by audit against retained envelopes — not prevented).
The consumption journal's own rollback residual is
different (R10, stated precisely in
``CeremonyConsumptionLedger``'s docstring): a rollback of
the verifier home cannot resurrect a consumed envelope
whose consumption is mirrored in the anchored signing
ledger (production), but can lower the enforced head for
never-consumed envelopes. Nothing here persists the pin
and the record atomically
(ATOMIC-ADOPTION above is the caller's duty, not a property
of this function); and the ceremony RECORD's MAC still uses
the snapshot signing key, symmetric as elsewhere in
``signing/`` — the asymmetry of cycle 20 covers the
authorisation envelope only, and the record's own key is
unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from signing.gate_decision import (
    ALG,
    SigningError,
    SigningKey,
    _canonical,
    _check_hex64,
    _check_id,
    _normalise_time,
    _now,
    _parse_time,
    _sha256,
    key_id_for,
)
from signing.ceremony_authorisation import (
    CeremonyPublicKey,
    SignedCeremonyAuthorisation,
    public_key_id_for,
    verify_ceremony_authorisation,
)
from signing.state_snapshot import (
    SignedStateSnapshot,
    verify_signed_snapshot,
    verify_snapshot_for_state,
)

DOMAIN = "snapshot-pin-ceremony-v1"
PIN_CEREMONY_DOMAIN = DOMAIN

REASON_INITIAL_ANCHOR = "initial_anchor"
REASON_CHAIN_GAP_RECOVERY = "chain_gap_recovery"
REASON_LOST_PIN = "lost_pin"
REASON_CORRUPTED_PIN = "corrupted_pin"
REASONS = frozenset({
    REASON_INITIAL_ANCHOR, REASON_CHAIN_GAP_RECOVERY,
    REASON_LOST_PIN, REASON_CORRUPTED_PIN,
})
# Reasons that are coherent only when there is no usable old pin.
_NO_PIN_REASONS = frozenset({
    REASON_INITIAL_ANCHOR, REASON_LOST_PIN, REASON_CORRUPTED_PIN,
})

_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (DOMAIN + "\n" + ALG + "\n" + key_id + "\n"
            + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


def _payload_hash(payload: dict) -> str:
    return _sha256(_canonical(payload))


_REANCHOR_REASONS = ("chain_gap",)


def _is_sole_chain_gap(reasons) -> bool:
    """The one eligibility atom, shared by ``classify_verification``
    and ``reanchor_pin`` (cycle 16): exactly ``("chain_gap",)``,
    by exact tuple equality. Never re-encode this as a set
    membership, an ``in`` check or a length check — each of those
    diverges on duplicates or mixed reasons."""
    if reasons is None:
        return False
    try:
        return tuple(reasons) == _REANCHOR_REASONS
    except TypeError:
        return False


def classify_verification(reasons) -> str:
    """Classify a verification result for callers: ``ok``,
    ``reanchor_required`` or ``integrity_failure``. A sole
    ``chain_gap`` is the only re-anchor trigger; any other
    non-empty result — including ``chain_gap`` mixed with other
    reasons — is an integrity failure, so a tampered candidate
    can never ride the ceremony path."""
    reasons = tuple(reasons)
    if reasons == ():
        return "ok"
    if _is_sole_chain_gap(reasons):
        return "reanchor_required"
    return "integrity_failure"


def _candidate_relation(old_seq, old_hash, signed) -> str:
    """The ceremony's only sequence arithmetic (cycle 16): how the
    candidate stands to the captured pin. ``gap`` is the only
    relation a ceremony may act on."""
    if signed.cycle_seq < old_seq:
        return "backwards"
    if signed.cycle_seq == old_seq:
        return "same" if signed.payload_hash == old_hash \
            else "same_seq_fork"
    if signed.cycle_seq == old_seq + 1:
        return "successor" if signed.prev_snapshot_hash == old_hash \
            else "successor_fork"
    if signed.prev_snapshot_hash == old_hash:
        # A candidate more than one step ahead whose prev names
        # the pin claims the pin as its immediate predecessor,
        # contradicting its own sequence distance — a relabelled
        # successor, not an unobserved gap.
        return "gap_prev_is_pin"
    return "gap"


def _pin_of(signed: SignedStateSnapshot) -> dict:
    return {"cycle_seq": signed.cycle_seq,
            "payload_hash": signed.payload_hash,
            "key_id": signed.key_id, "signer_id": signed.signer_id}


_PIN_ABSENT = object()


def _check_pin(pin, field="pin"):
    """Validate a pin, capturing each field ONCE via .get alone
    (the cycle-14 rule: never validate from one read and compare
    from another). Returns (seq, payload_hash, captured) where
    captured holds exactly the fields present, as read."""
    if not isinstance(pin, dict) or not set(pin) <= {
            "cycle_seq", "payload_hash", "key_id", "signer_id"}:
        raise SigningError(f"{field} has missing or unknown keys")
    seq, payload_hash = pin.get("cycle_seq"), pin.get("payload_hash")
    key_id = pin.get("key_id", _PIN_ABSENT)
    signer_id = pin.get("signer_id", _PIN_ABSENT)
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 \
            or not isinstance(payload_hash, str) \
            or not _HEX64_RE.fullmatch(payload_hash):
        raise SigningError(f"{field} is malformed")
    captured = {"cycle_seq": seq, "payload_hash": payload_hash}
    if key_id is not _PIN_ABSENT:
        captured["key_id"] = key_id
    if signer_id is not _PIN_ABSENT:
        captured["signer_id"] = signer_id
    return seq, payload_hash, captured


def advance_pin(pin, signed, reasons) -> dict:
    """The only normal pin movement. Refuses (SigningError) unless
    the verification result is ``()`` and the candidate is the
    pin's immediate chained successor. Same pin + same candidate
    is an idempotent no-op returning the pin unchanged."""
    pin_seq, pin_hash, captured = _check_pin(pin)
    if not isinstance(signed, SignedStateSnapshot):
        raise SigningError("signed must be a SignedStateSnapshot")
    if tuple(reasons) != ():
        raise SigningError(
            "pin may advance only on a verification result of ()")
    # A pin carrying key/signer bindings may advance only to a
    # candidate under the same bindings — no silent signer switch
    # through the normal path (war-room cycle 15, rev-r2).
    if captured.get("key_id", signed.key_id) != signed.key_id \
            or captured.get("signer_id", signed.signer_id) \
            != signed.signer_id:
        raise SigningError(
            "candidate does not match the pin's key/signer binding")
    if signed.cycle_seq == pin_seq and signed.payload_hash == pin_hash:
        return captured
    if signed.cycle_seq != pin_seq + 1:
        raise SigningError(
            "pin may advance only one sequence at a time; a larger "
            "gap requires the pin ceremony")
    if signed.prev_snapshot_hash != pin_hash:
        raise SigningError(
            "pin may advance only to a candidate chained to the pin")
    return _pin_of(signed)


@dataclass(frozen=True)
class PinCeremonyRecord:
    old_cycle_seq: int | None
    old_payload_hash: str
    new_cycle_seq: int
    new_payload_hash: str
    operator_id: str
    reason: str
    evidence_hash: str
    candidate_signer_id: str
    candidate_key_id: str
    key_id: str
    performed_at: str
    payload_hash: str
    signature: str
    # Cycle 19: the authorisation that governed this ceremony,
    # bound under the record MAC. Both fields are REQUIRED — a
    # record that claims no authorisation is unrepresentable.
    ceremony_id: str
    authorisation_id: str

    def payload(self) -> dict:
        return {
            "v": "snapshot-pin-ceremony/1", "alg": ALG,
            "old_cycle_seq": self.old_cycle_seq,
            "old_payload_hash": self.old_payload_hash,
            "new_cycle_seq": self.new_cycle_seq,
            "new_payload_hash": self.new_payload_hash,
            "operator_id": self.operator_id, "reason": self.reason,
            "evidence_hash": self.evidence_hash,
            "candidate_signer_id": self.candidate_signer_id,
            "candidate_key_id": self.candidate_key_id,
            "key_id": self.key_id, "performed_at": self.performed_at,
            "ceremony_id": self.ceremony_id,
            "authorisation_id": self.authorisation_id,
        }

    @property
    def gap_from_seq(self) -> int | None:
        """First unobserved sequence, or None for an initial anchor."""
        return None if self.old_cycle_seq is None else self.old_cycle_seq + 1

    @property
    def gap_to_seq(self) -> int | None:
        """Last unobserved sequence covered by this re-anchor."""
        if self.old_cycle_seq is None or self.new_cycle_seq <= self.old_cycle_seq + 1:
            return None
        return self.new_cycle_seq - 1


def _check_ceremony_history(ceremony_history, *, signing_key,
                            evidence_hash, signed):
    """Validate a caller-supplied ceremony history (cycle 16).
    History can only refuse, never grant: every record must
    verify under the ceremony key, evidence must not repeat
    within the history or against this ceremony, the candidate
    must not already be a ceremonied target, must not sit behind
    the history's attested head, and must not predate the latest
    ceremony in it. Returns the captured history tuple."""
    if isinstance(ceremony_history, (str, bytes, dict)) \
            or not isinstance(ceremony_history, (list, tuple)):
        raise SigningError(
            "ceremony history must be a list or tuple of records")
    history = tuple(ceremony_history)
    seen_evidence = set()
    for rec in history:
        if not isinstance(rec, PinCeremonyRecord):
            raise SigningError(
                "ceremony history contains a non-record entry")
        if verify_ceremony_record(rec, signing_key=signing_key) != ():
            raise SigningError(
                "ceremony history record does not verify; an "
                "unverifiable history establishes nothing")
        if rec.evidence_hash in seen_evidence:
            raise SigningError(
                "ceremony history itself reuses an evidence hash")
        seen_evidence.add(rec.evidence_hash)
        if (rec.new_cycle_seq, rec.new_payload_hash) \
                == (signed.cycle_seq, signed.payload_hash):
            raise SigningError(
                "candidate is already a ceremonied target; a "
                "replayed ceremony is refused")
    if evidence_hash in seen_evidence:
        raise SigningError(
            "ceremony evidence has already been used in a prior "
            "ceremony")
    targets = {}
    for rec in history:
        prior = targets.setdefault(rec.new_cycle_seq,
                                   rec.new_payload_hash)
        if prior != rec.new_payload_hash:
            raise SigningError(
                "ceremony history is forked: two records attest "
                "different snapshots at the same sequence")
    if history:
        head = max(history, key=lambda r: r.new_cycle_seq)
        if signed.cycle_seq < head.new_cycle_seq or (
                signed.cycle_seq == head.new_cycle_seq
                and signed.payload_hash != head.new_payload_hash):
            raise SigningError(
                "candidate would abandon higher attested work in "
                "the ceremony history")
        latest = max(_parse_time(r.performed_at, "performed_at")
                     for r in history)
        if _parse_time(signed.signed_at, "signed_at") <= latest:
            raise SigningError(
                "candidate predates the latest ceremony in the "
                "history; a stale candidate cannot be the new head")
    return history


def reanchor_pin(old_pin, signed, *, signing_key: SigningKey,
                 state_bytes, calibration_bytes, expected_signer_id,
                 operator_id, reason,
                 evidence_hash, authorisation,
                 authorisation_public_key: CeremonyPublicKey,
                 expected_verifier_signer_id,
                 ceremony_history,
                 consume_authorisation,
                 strict_reasons=None,
                 now=None) \
        -> tuple[dict, PinCeremonyRecord]:
    """Ceremonied re-anchor: returns (new_pin, audit_record).

    See the module docstring for the full rule set. Every refusal
    is a SigningError with the specific failed condition; nothing
    is returned on refusal, so a failed ceremony cannot be
    mistaken for a moved pin.

    Cycle 19: authority is the ``authorisation`` envelope — a
    ``SignedCeremonyAuthorisation`` object (a raw dict is
    refused) issued by the verifier for the verifier identity
    ``expected_verifier_signer_id``. Cycle 20: the envelope is
    verified asymmetrically under ``authorisation_public_key`` —
    a pinned ``CeremonyPublicKey`` holding public bytes only;
    the verifier's seed never leaves the verifier process, and
    there is no caller-supplied operator list and no fallback:
    an envelope that fails verification or exact binding refuses
    the ceremony outright. ``ceremony_history`` is a REQUIRED
    keyword (cycle 20): omitting it is a TypeError at the call
    site, and an explicit ``None`` refuses early, before
    envelope verification, for every reason — fail-closed on
    omission.

    Cycle 21: ``consume_authorisation`` is a REQUIRED keyword
    with the same discipline — omitting it is a TypeError, and
    an explicit ``None`` or a non-callable refuses early,
    before envelope verification. It is a one-argument
    callable taking the SignedCeremonyAuthorisation, returning
    None on success and raising SigningError on any refusal.
    It is invoked exactly once, after ALL local checks and
    immediately before the ceremony record payload is
    constructed; a consumer exception propagates as a refusal
    and nothing is returned.

    reanchor_pin is no longer an offline function — a
    successful ceremony requires a live verifier round-trip
    inside the envelope's TTL and fails closed when the
    verifier is unreachable; every existing direct caller
    breaks with TypeError until it supplies the keyword, and
    that flag-day breakage is intended.

    Crash-consistency contract: Consumption is committed at
    the verifier — a fsync'd consumption-journal append —
    before reanchor_pin returns anything. There is no
    execution path in the integrated system in which a pin
    movement succeeds without its consumption record durably
    committed first. A crash after the commit but before
    adoption leaves the authorisation burned and the pin
    unmoved; a lost or ambiguous response is treated as
    burned; the client never retries a consume automatically.
    Recovery is a new ceremony (new ceremony_id, new
    evidence), never an un-consume.

    Claim wording: single-use consumption and pin
    non-regression are properties of the INTEGRATED SYSTEM
    under its production wiring — authorise via
    VerifierClient, re-anchor with the verifier-backed
    consumer, adopt the returned pin atomically — not
    properties of reanchor_pin for an arbitrary
    caller-supplied callable. A no-op callable gets no
    protection, exactly as a caller supplying its own signing
    key or a wrong public-key pin gets none; the callable is
    not materially different from the inputs reanchor_pin
    already trusts.

    ``ceremony_history`` is an audit/consistency input that
    can only refuse, never grant; the verifier's consumption
    head is authoritative on any discrepancy."""
    if not isinstance(signing_key, SigningKey) \
            or signing_key.key_id != key_id_for(signing_key.key):
        raise SigningError("signing key is inconsistent")
    if not isinstance(signed, SignedStateSnapshot):
        raise SigningError("signed must be a SignedStateSnapshot")
    # (1) Type checks (cycle 19; key gate cycle 20): the
    # authorisation must be the typed envelope object, never a
    # raw dict a caller assembled, and the authorisation verify
    # key must be a CeremonyPublicKey — a type that cannot hold
    # secret material. A SigningKey passed in that slot is a
    # type refusal: this type gate, plus the absence of minting
    # material from this process, IS the key separation now.
    # The cycle-19 in-process id-inequality check is DELETED:
    # ``pub-…`` and ``key-…`` ids are disjoint namespaces over
    # different hash inputs, so the comparison could never fire
    # (DESIGN-FINAL R3). What remains checkable in-process is
    # that the verify object does not lie about its own derived
    # id (``key_id_inconsistent`` in the envelope verifier's
    # vocabulary, refused here before envelope verification).
    if not isinstance(authorisation, SignedCeremonyAuthorisation):
        raise SigningError(
            "authorisation must be a SignedCeremonyAuthorisation")
    if not isinstance(authorisation_public_key, CeremonyPublicKey):
        raise SigningError(
            "authorisation_public_key must be a CeremonyPublicKey")
    if authorisation_public_key.key_id \
            != public_key_id_for(authorisation_public_key.public_key):
        raise SigningError(
            "authorisation public key is inconsistent: its key_id "
            "does not match its public key (key_id_inconsistent)")
    # (1b) CONSUMPTION PRESENCE (cycle 21): the type check sits
    # with the other type gates above. An explicit
    # consume_authorisation=None, or a non-callable, refuses
    # HERE — before envelope verification, mirroring the
    # ceremony_history=None ordering below — for every reason.
    # (Omitting the keyword entirely is a TypeError: the
    # parameter has no default.)
    if consume_authorisation is None or not callable(consume_authorisation):
        raise SigningError(
            "consume_authorisation is required: reanchor_pin is "
            "fail-closed on omission, so consume_authorisation=None "
            "or a non-callable refuses for every reason; supply the "
            "verifier-backed consumer (see "
            "VerifierClient.ceremony_consumer)")
    # (2) HISTORY PRESENCE (cycle 20): an explicit
    # ceremony_history=None refuses HERE — before envelope
    # verification, so the fail-closed-on-omission refusal is
    # never masked by an expired or foreign envelope — for every
    # reason. (Omitting the keyword entirely is a TypeError:
    # the parameter has no default.) A supplied history —
    # including an explicit empty one, which is a caller
    # assertion that no prior ceremony exists — is content-
    # checked later, at the history call site.
    if ceremony_history is None:
        raise SigningError(
            "ceremony_history is required: reanchor_pin is "
            "fail-closed on omission, so ceremony_history=None "
            "refuses for every reason; supply the complete "
            "ceremony history (an explicit empty history asserts "
            "no prior ceremony exists)")
    _check_id(operator_id, "operator id")
    if reason not in REASONS:
        raise SigningError(f"ceremony reason must be one of {sorted(REASONS)}")
    _check_hex64(evidence_hash, "evidence hash")
    # One clock capture for the whole ceremony (cycle 16): the
    # verifier's freshness check, the authorisation envelope's
    # expiry and the record's performed_at must never straddle
    # an expiry boundary by reading the clock twice.
    moment = _now() if now is None else now
    old_seq = old_hash = None
    old_captured = None
    if old_pin is not None:
        # Capture the old pin ONCE, before binding: the envelope
        # is compared against these captured values, never a
        # re-read of the caller's dict.
        old_seq, old_hash, old_captured = _check_pin(old_pin, "old pin")
    # (3) Envelope verification under the verifier's pinned
    # PUBLIC key (cycle 20: Ed25519, asymmetric — this process
    # holds no minting material), pinned to the expected
    # verifier signer, judged on the ceremony's single captured
    # clock.
    auth_reasons = verify_ceremony_authorisation(
        authorisation, public_key=authorisation_public_key,
        expected_signer_id=expected_verifier_signer_id, now=moment)
    if auth_reasons != ():
        raise SigningError(
            "ceremony authorisation does not verify: "
            f"{list(auth_reasons)}")
    # (4) EXACT binding equality against the captured actuals.
    # Each envelope field is read ONCE; every mismatch is its
    # own refusal. The envelope's top-level signer_id/key_id are
    # the VERIFIER's; the candidate's are the SNAPSHOT's — never
    # conflated. evidence_ref is NOT equality-checked here (no
    # ceremony-side counterpart); it is bound transitively via
    # the record's authorisation_id.
    env_operator_id = authorisation.operator_id
    env_reason = authorisation.reason
    env_old_pin = authorisation.old_pin
    env_candidate = authorisation.candidate
    env_evidence_hash = authorisation.evidence_hash
    if env_operator_id != operator_id:
        raise SigningError(
            "ceremony authorisation is for a different operator")
    if env_reason != reason:
        raise SigningError(
            "ceremony authorisation is for a different reason")
    expected_old_pin = None if old_captured is None else {
        "cycle_seq": old_seq, "payload_hash": old_hash}
    if env_old_pin != expected_old_pin:
        raise SigningError(
            "ceremony authorisation is bound to a different old pin")
    expected_candidate = {
        "cycle_seq": signed.cycle_seq,
        "payload_hash": signed.payload_hash,
        "signer_id": signed.signer_id, "key_id": signed.key_id}
    if env_candidate != expected_candidate:
        raise SigningError(
            "ceremony authorisation is bound to a different candidate")
    if env_evidence_hash != evidence_hash:
        raise SigningError(
            "ceremony authorisation is bound to different evidence")
    # (5) The evidence non-equality check still runs — defence
    # in depth behind the envelope binding.
    if evidence_hash in (signed.payload_hash, signed.snapshot_id,
                         signed.state_sha256, signed.calibration_sha256):
        raise SigningError(
            "ceremony evidence must be independent of the candidate; "
            "a pin must never be reconstructed from the snapshot "
            "being verified")
    if old_pin is not None:
        if reason != REASON_CHAIN_GAP_RECOVERY:
            # Gate on state, not label (war-room cycle 15, rev-r2):
            # with a usable pin present, chain_gap_recovery is the
            # only coherent ceremony reason — lost/corrupted/initial
            # claims with a present, well-formed pin are refused,
            # so no jump can be laundered by relabelling the reason.
            raise SigningError(
                "with an existing pin the only ceremony reason is "
                "chain_gap_recovery")
        relation = _candidate_relation(old_seq, old_hash, signed)
        if relation in ("backwards", "same", "same_seq_fork"):
            raise SigningError(
                "re-anchor never moves a pin backwards or replaces "
                "a pin at the same sequence")
        if relation == "successor":
            raise SigningError(
                "candidate is the pin's chained successor; use "
                "advance_pin, not the ceremony")
        if relation == "successor_fork":
            # A one-step candidate that does not chain to the pin
            # is a fork/replacement (chain_discontinuity), an
            # integrity failure — never a ceremony trigger
            # (war-room cycle 15, forced-dissent seat).
            raise SigningError(
                "candidate at pin+1 does not chain to the pin; "
                "that is an integrity failure, not a re-anchor case")
        if relation == "gap_prev_is_pin":
            raise SigningError(
                "candidate claims the pin as its immediate "
                "predecessor while sitting more than one sequence "
                "past it; that is an integrity failure, not a "
                "re-anchor case")
    if reason == REASON_CHAIN_GAP_RECOVERY:
        # The ceremony must be gated on an actual strict
        # verification classified reanchor_required, not invoked
        # freely (war-room cycle 15, forced-dissent seat). Cycle
        # 16: the caller's tuple is no longer trusted on its own —
        # eligibility is RECOMPUTED here, against the captured pin
        # and this candidate, through the strict wrapper, and the
        # supplied tuple must equal the recomputed result exactly.
        # A forged ("chain_gap",) for a candidate whose real strict
        # result is anything else (pin_mismatch, expired, …) is
        # refused, and classify/reanchor can no longer diverge.
        if old_pin is None:
            raise SigningError(
                "chain_gap_recovery requires an existing pin")
        if not isinstance(strict_reasons, (list, tuple)) \
                or not _is_sole_chain_gap(strict_reasons):
            raise SigningError(
                "chain_gap_recovery requires a strict verification "
                "result of exactly ('chain_gap',)")
        supplied = tuple(strict_reasons)
        recomputed = verify_snapshot_for_state(
            signed, signing_key=signing_key, state_bytes=state_bytes,
            calibration_bytes=calibration_bytes,
            expected_pin=old_captured,
            expected_signer_id=expected_signer_id, now=moment)
        if recomputed != _REANCHOR_REASONS \
                or supplied != recomputed:
            raise SigningError(
                "strict verification recomputed against the pin "
                f"gives {list(recomputed)}, not exactly "
                "('chain_gap',); the ceremony is refused")
    elif old_pin is None and reason not in _NO_PIN_REASONS:
        raise SigningError(f"reason {reason} requires an existing pin")
    # History content checks (cycle 20): the history is required
    # (presence was refused early, step (2)), so these checks now
    # run on EVERY ceremony — there is no opt-in guard.
    # initial_anchor additionally requires the history to be
    # EMPTY, checked immediately before the generic check so a
    # verified non-empty history gets this message: "initial" is
    # a claim that no ceremony precedes this one, and a non-empty
    # history contradicts it on its face (a missing pin after
    # prior ceremonies is lost_pin, not initial_anchor). The
    # refusal is deliberate even for unrelated-lineage history —
    # see the module docstring.
    if reason == REASON_INITIAL_ANCHOR \
            and isinstance(ceremony_history, (list, tuple)) \
            and len(ceremony_history) > 0:
        raise SigningError(
            "initial_anchor requires an empty ceremony history: "
            "a non-empty history shows ceremonies already "
            "occurred, so a missing pin is lost_pin, not "
            "initial_anchor; a new authorisation under lost_pin "
            "(with new evidence) is required — the present "
            "envelope cannot be re-reasoned")
    _check_ceremony_history(
        ceremony_history, signing_key=signing_key,
        evidence_hash=evidence_hash, signed=signed)
    # The candidate must pass EVERY attestation binding under the
    # bare verifier (which does not enforce the chain gap). Any
    # failure — integrity or freshness — refuses the ceremony.
    reasons = verify_signed_snapshot(
        signed, signing_key=signing_key,
        expected_state_bytes=state_bytes,
        expected_calibration_bytes=calibration_bytes,
        require_calibration=True, expected_signer_id=expected_signer_id,
        now=moment)
    if reasons != ():
        raise SigningError(
            f"candidate fails attestation bindings: {list(reasons)}")
    # (last fallible step, cycle 21) CONSUMPTION: every local
    # check has passed — type gates, history presence and
    # content, envelope verification, exact binding, relation
    # gates, strict recomputation, bare attestation
    # verification — so the consumer is invoked exactly once,
    # immediately before the ceremony record payload is
    # constructed. Any exception propagates as a refusal
    # (a non-SigningError is converted, cause chained) and
    # nothing is returned: no pin, no record.
    try:
        consume_authorisation(authorisation)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(
            f"ceremony consumption failed: {exc}") from exc
    performed_at = _normalise_time(moment, "performed_at")
    _parse_time(performed_at, "performed_at")
    payload = {
        "v": "snapshot-pin-ceremony/1", "alg": ALG,
        "old_cycle_seq": old_seq, "old_payload_hash": old_hash or "",
        "new_cycle_seq": signed.cycle_seq,
        "new_payload_hash": signed.payload_hash,
        "operator_id": operator_id, "reason": reason,
        "evidence_hash": evidence_hash,
        "candidate_signer_id": signed.signer_id,
        "candidate_key_id": signed.key_id,
        "key_id": signing_key.key_id, "performed_at": performed_at,
        "ceremony_id": authorisation.ceremony_id,
        "authorisation_id": authorisation.authorisation_id,
    }
    payload_hash = _payload_hash(payload)
    record = PinCeremonyRecord(
        old_cycle_seq=old_seq, old_payload_hash=old_hash or "",
        new_cycle_seq=signed.cycle_seq, new_payload_hash=signed.payload_hash,
        operator_id=operator_id, reason=reason, evidence_hash=evidence_hash,
        candidate_signer_id=signed.signer_id, candidate_key_id=signed.key_id,
        key_id=signing_key.key_id, performed_at=performed_at,
        payload_hash=payload_hash,
        signature=_mac(signing_key.key, payload_hash, signing_key.key_id),
        ceremony_id=authorisation.ceremony_id,
        authorisation_id=authorisation.authorisation_id)
    return _pin_of(signed), record


_CONTEXT_UNSPECIFIED = object()


def verify_ceremony_record(record, *, signing_key: SigningKey,
                           expected_old_pin=_CONTEXT_UNSPECIFIED,
                           expected_new_pin=_CONTEXT_UNSPECIFIED) -> tuple:
    """Failure reasons for a ceremony audit record; () means the
    record is exactly the one the key holder issued. Without pin
    context this proves ISSUANCE only, not applicability to any
    pin state. Cycle 16: each context argument is independent —
    omitting it asserts nothing about that side; passing
    ``expected_old_pin=None`` explicitly asserts the record's
    old pin is absent; passing a pin dict asserts an exact
    (sequence, hash) match on that side. A genuine record
    replayed against a different pin state reports
    ``pin_context_mismatch`` instead of verifying clean, and a
    malformed context pin reports that reason rather than
    raising."""
    if not isinstance(record, PinCeremonyRecord):
        raise SigningError("record must be a PinCeremonyRecord")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    reasons = []
    if expected_old_pin is not _CONTEXT_UNSPECIFIED \
            or expected_new_pin is not _CONTEXT_UNSPECIFIED:
        ctx_ok = True
        try:
            if expected_old_pin is None:
                ctx_ok = record.old_cycle_seq is None
            elif expected_old_pin is not _CONTEXT_UNSPECIFIED:
                o_seq, o_hash, _o = _check_pin(expected_old_pin,
                                               "expected old pin")
                ctx_ok = (record.old_cycle_seq,
                          record.old_payload_hash) == (o_seq, o_hash)
            if ctx_ok and expected_new_pin is not _CONTEXT_UNSPECIFIED:
                n_seq, n_hash, _n = _check_pin(expected_new_pin,
                                               "expected new pin")
                ctx_ok = (record.new_cycle_seq,
                          record.new_payload_hash) == (n_seq, n_hash)
        except SigningError:
            ctx_ok = False
        if not ctx_ok:
            reasons.append("pin_context_mismatch")
    if record.key_id != signing_key.key_id:
        reasons.append("unknown_key")
    # Re-validate the ceremony invariants, not only the MAC
    # (war-room cycle 15, rev-r2): a record that violates the
    # rules reanchor_pin enforces must not verify as () merely
    # because a key holder signed it.
    def _is_seq(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    if record.reason not in REASONS:
        reasons.append("invalid_reason")
    if not isinstance(record.evidence_hash, str) \
            or not _HEX64_RE.fullmatch(record.evidence_hash):
        reasons.append("invalid_evidence")
    # Cycle 19: the record must name the authorisation that
    # governed the ceremony — a well-formed ceremony id and a
    # hex64 authorisation id, under one shared reason.
    authorisation_ok = True
    try:
        _check_id(record.ceremony_id, "ceremony id")
    except SigningError:
        authorisation_ok = False
    if not isinstance(record.authorisation_id, str) \
            or not _HEX64_RE.fullmatch(record.authorisation_id):
        authorisation_ok = False
    if not authorisation_ok:
        reasons.append("invalid_authorisation")
    if not _is_seq(record.new_cycle_seq) \
            or (record.old_cycle_seq is not None
                and not _is_seq(record.old_cycle_seq)):
        reasons.append("invalid_sequence")
    elif record.old_cycle_seq is not None \
            and record.new_cycle_seq <= record.old_cycle_seq:
        reasons.append("backwards_reanchor")
    elif record.old_cycle_seq is not None \
            and record.new_cycle_seq == record.old_cycle_seq + 1:
        # reanchor_pin can never issue a one-step record (a chained
        # successor must use advance_pin; an unchained one is an
        # integrity failure), so a MACed one-step "re-anchor" is
        # un-issuable and must not verify clean (cycle 16).
        reasons.append("not_a_gap_reanchor")
    if record.old_cycle_seq is None \
            and record.reason not in _NO_PIN_REASONS:
        reasons.append("invalid_reason")
    if record.old_cycle_seq is not None \
            and record.reason != REASON_CHAIN_GAP_RECOVERY:
        reasons.append("invalid_reason")
    for value in (record.operator_id, record.candidate_signer_id,
                  record.candidate_key_id, record.key_id):
        try:
            _check_id(value, "record id")
        except SigningError:
            reasons.append("invalid_id")
            break
    try:
        recomputed = _payload_hash(record.payload())
    except Exception:
        return ("malformed_payload",)
    if record.payload_hash != recomputed:
        reasons.append("payload_hash_mismatch")
    expected = _mac(signing_key.key, recomputed, record.key_id)
    if not isinstance(record.signature, str) \
            or not _HEX64_RE.fullmatch(record.signature) \
            or not hmac.compare_digest(record.signature.encode("ascii"),
                                       expected.encode("ascii")):
        reasons.append("signature_mismatch")
    return tuple(dict.fromkeys(reasons))
