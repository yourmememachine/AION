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
    if reasons == ("chain_gap",):
        return "reanchor_required"
    return "integrity_failure"


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


def reanchor_pin(old_pin, signed, *, signing_key: SigningKey,
                 state_bytes, calibration_bytes, expected_signer_id,
                 operator_id, authorised_operators, reason,
                 evidence_hash, strict_reasons=None,
                 now=None) -> tuple[dict, PinCeremonyRecord]:
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
    old_seq = old_hash = None
    if old_pin is not None:
        old_seq, old_hash, _old_captured = _check_pin(old_pin, "old pin")
        if reason != REASON_CHAIN_GAP_RECOVERY:
            # Gate on state, not label (war-room cycle 15, rev-r2):
            # with a usable pin present, chain_gap_recovery is the
            # only coherent ceremony reason — lost/corrupted/initial
            # claims with a present, well-formed pin are refused,
            # so no jump can be laundered by relabelling the reason.
            raise SigningError(
                "with an existing pin the only ceremony reason is "
                "chain_gap_recovery")
        if signed.cycle_seq <= old_seq:
            raise SigningError(
                "re-anchor never moves a pin backwards or replaces "
                "a pin at the same sequence")
        if signed.cycle_seq == old_seq + 1 \
                and signed.prev_snapshot_hash == old_hash \
                and reason == REASON_CHAIN_GAP_RECOVERY:
            raise SigningError(
                "candidate is the pin's chained successor; use "
                "advance_pin, not the ceremony")
        if signed.cycle_seq == old_seq + 1 \
                and signed.prev_snapshot_hash != old_hash:
            # A one-step candidate that does not chain to the pin
            # is a fork/replacement (chain_discontinuity), an
            # integrity failure — never a ceremony trigger
            # (war-room cycle 15, forced-dissent seat).
            raise SigningError(
                "candidate at pin+1 does not chain to the pin; "
                "that is an integrity failure, not a re-anchor case")
    if reason == REASON_CHAIN_GAP_RECOVERY:
        # The ceremony must be gated on an actual strict
        # verification classified reanchor_required, not invoked
        # freely (war-room cycle 15, forced-dissent seat).
        if strict_reasons is None \
                or classify_verification(strict_reasons) \
                != "reanchor_required":
            raise SigningError(
                "chain_gap_recovery requires a strict verification "
                "result of exactly ('chain_gap',)")
        if old_pin is None:
            raise SigningError(
                "chain_gap_recovery requires an existing pin")
    elif old_pin is None and reason not in _NO_PIN_REASONS:
        raise SigningError(f"reason {reason} requires an existing pin")
    # The candidate must pass EVERY attestation binding under the
    # bare verifier (which does not enforce the chain gap). Any
    # failure — integrity or freshness — refuses the ceremony.
    reasons = verify_signed_snapshot(
        signed, signing_key=signing_key,
        expected_state_bytes=state_bytes,
        expected_calibration_bytes=calibration_bytes,
        require_calibration=True, expected_signer_id=expected_signer_id,
        now=now)
    if reasons != ():
        raise SigningError(
            f"candidate fails attestation bindings: {list(reasons)}")
    performed_at = _normalise_time(_now() if now is None else now,
                                    "performed_at")
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


def verify_ceremony_record(record, *, signing_key: SigningKey) -> tuple:
    """Failure reasons for a ceremony audit record; () means the
    record is exactly the one the key holder issued."""
    if not isinstance(record, PinCeremonyRecord):
        raise SigningError("record must be a PinCeremonyRecord")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    reasons = []
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
