"""Authorised pin re-anchoring (the snapshot pin ceremony).

Cycle 15 (backlog item ``snapshot-pin-ceremony``). Cycle 14 made
the strict snapshot wrapper refuse any candidate more than one
sequence past the caller's pin (``chain_gap``). That refusal is
fail-closed by design, but without a recovery path it is also a
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
  of: an operator on a caller-supplied authorised list; an
  allowlisted reason; independent evidence (a hex64 hash that is
  NOT derived from the candidate itself — a pin must never be
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
  stated price of fail-closed step-observation, not a defect
  this module hides.
- Authorisation is a caller-supplied list checked in-process;
  this module cannot prove the operator is a distinct human,
  and the MAC is symmetric (any key holder can forge a record),
  exactly as elsewhere in ``signing/``. The boundary remains key
  placement and an operator list held outside the rollback domain.
- Evidence independence is enforced only as non-equality with
  the candidate's own hashes (war-room cycle 15, forced-dissent
  seat): a re-hash of the candidate, or an invented hex64, passes
  the check. That the evidence genuinely comes from an
  independent source is a caller/operator duty this code cannot
  prove; the record binds whatever hash was supplied so the
  claim is at least auditable after the fact.
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
integrity failure. An optional ``ceremony_history`` (verified
records only) refuses evidence reuse, replayed targets,
candidates behind the history's attested head, and candidates
predating the latest ceremony — ONLY under a complete,
caller-supplied history: the parameter is opt-in, a truncated
or omitted history silently disables every one of those
checks, and the records are attested under the same symmetric
key, so this is a consistency check over caller-supplied
input, not rollback or replay protection. The no-pin reasons
(``initial_anchor`` / ``lost_pin`` / ``corrupted_pin``) receive
no recomputation and no history requirement. Without pin
context, ``verify_ceremony_record`` proves a record was
issued, not that it applies to the caller's pin state.
``verify_ceremony_record`` refuses one-step records (which this
ceremony can never issue) and, when the caller supplies the
expected pin context, records replayed against a different pin
state. What cycle 16 does NOT fix, stated plainly: operator
authority is still a caller-supplied list (independent authority
needs a protected source — an owner decision, not a local
check); evidence is still a bare digest whose provenance this
module cannot prove (history reuse checks apply only when a
history is supplied); nothing here persists the pin and the
record atomically; and the ceremony MAC uses the snapshot
signing key — key separation is stated as required future work,
not enforced here.
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
                 operator_id, authorised_operators, reason,
                 evidence_hash, strict_reasons=None,
                 now=None, ceremony_history=None) \
        -> tuple[dict, PinCeremonyRecord]:
    """Ceremonied re-anchor: returns (new_pin, audit_record).

    See the module docstring for the full rule set. Every refusal
    is a SigningError with the specific failed condition; nothing
    is returned on refusal, so a failed ceremony cannot be
    mistaken for a moved pin."""
    if not isinstance(signing_key, SigningKey) \
            or signing_key.key_id != key_id_for(signing_key.key):
        raise SigningError("signing key is inconsistent")
    if not isinstance(signed, SignedStateSnapshot):
        raise SigningError("signed must be a SignedStateSnapshot")
    _check_id(operator_id, "operator id")
    if not isinstance(authorised_operators, (list, tuple, set, frozenset)) \
            or operator_id not in authorised_operators:
        raise SigningError("operator is not authorised for a pin ceremony")
    if reason not in REASONS:
        raise SigningError(f"ceremony reason must be one of {sorted(REASONS)}")
    _check_hex64(evidence_hash, "evidence hash")
    if evidence_hash in (signed.payload_hash, signed.snapshot_id,
                         signed.state_sha256, signed.calibration_sha256):
        raise SigningError(
            "ceremony evidence must be independent of the candidate; "
            "a pin must never be reconstructed from the snapshot "
            "being verified")
    # One clock capture for the whole ceremony (cycle 16): the
    # verifier's freshness check and the record's performed_at
    # must never straddle an expiry boundary by reading the
    # clock twice.
    moment = _now() if now is None else now
    old_seq = old_hash = None
    old_captured = None
    if old_pin is not None:
        old_seq, old_hash, old_captured = _check_pin(old_pin, "old pin")
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
    if ceremony_history is not None:
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
    }
    payload_hash = _payload_hash(payload)
    record = PinCeremonyRecord(
        old_cycle_seq=old_seq, old_payload_hash=old_hash or "",
        new_cycle_seq=signed.cycle_seq, new_payload_hash=signed.payload_hash,
        operator_id=operator_id, reason=reason, evidence_hash=evidence_hash,
        candidate_signer_id=signed.signer_id, candidate_key_id=signed.key_id,
        key_id=signing_key.key_id, performed_at=performed_at,
        payload_hash=payload_hash,
        signature=_mac(signing_key.key, payload_hash, signing_key.key_id))
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
