"""Signed ceremony authorisations (cycle 19).

The pin ceremony (signing/pin_ceremony.py) re-anchors a snapshot
pin after a chain gap, a lost pin or a corrupted pin. Before this
cycle the ceremony took its operator authority from the CALLER:
``reanchor_pin`` accepted an ``authorised_operators`` list from
the same code that supplied the evidence — the authority and the
evidence came from one hand, which is no authority at all. This
module is the verifier-side replacement: a *ceremony
authorisation* is an HMAC envelope, issued by the out-of-process
verifier (trust/verifier_main.py, mode ``ceremony_authorise``)
under the verifier's key, attesting that an operator named on the
verifier's OWN protected configuration (the
``AION_CEREMONY_OPERATORS`` env list, which no request can carry)
presented a specific evidence hash bound to one exact recovery
event. The ceremony consumes the envelope; it never sees a list.

Structural divergence from signing/attestation.py, stated
plainly: there the signer IS the attester. Here the signer (the
verifier) is NOT the operator — the verifier signs ABOUT the
operator's presentation. The operator holds no key and signs
nothing; operator authority is list membership decided at
issuance time inside the verifier, against configuration the
request cannot influence.

The reason allowlist below is a LOCAL MIRROR of
``signing.pin_ceremony.REASONS``. This module must NOT import
pin_ceremony (pin_ceremony imports this module to verify
envelopes — the import would be circular), so the mirror is a
copy, and a drift test pins mirror == pin_ceremony.REASONS.

Honest limits (the cycle-19 formulation, carried verbatim in
substance):

* The verifier never opens, fetches or inspects the artefact
  ``evidence_hash`` names. It does not know the artefact exists,
  what it contains, or that the hash was computed over it.
  ``evidence_ref`` is an opaque, caller-supplied locator string
  (form-checked only). What the envelope proves: a listed
  operator presented this evidence hash bound to this exact
  event, the presentation was ledgered single-use at issuance
  (see trust/ledger.py's CeremonyAuthorisationLedger), and the
  binding is signed by the verifier's key. A random hex64 from a
  LISTED operator is still issuable — it is now attributable to
  that operator, bound to one event, and burned on use.
* Operator identity is list membership via the launch channel,
  not authentication of a human.
* HMAC is symmetric: anyone holding the verifier key (including
  a verify-only consumer) can forge an envelope; a forged
  envelope is indistinguishable at consumption (no
  consumption-side ledger check exists — limit M5) and is
  discoverable only on an audit comparing presented envelopes
  against the issuance ledgers. Same-OS-user prototype
  honesty from gate_decision's docstring applies unchanged.
* ``now=`` parameters exist for tests only; see the warning in
  gate_decision's module docstring.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass
from datetime import timedelta

from signing.gate_decision import (
    ALG,
    CLOCK_SKEW_SECONDS,
    TTL_MIN_SECONDS,
    SigningError,
    SigningKey,
    _canonical,
    _check_hex64,
    _check_id,
    _check_text,
    _normalise_time,
    _now,
    _parse_time,
    _sha256,
    key_id_for,
)

CEREMONY_AUTHORISATION_DOMAIN = "signed-ceremony-authorisation-v1"
DOMAIN = CEREMONY_AUTHORISATION_DOMAIN
PURPOSE_CEREMONY_AUTHORISATION = "pin-ceremony-authorisation"
CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS = 900
CEREMONY_AUTHORISATION_TTL_MAX_SECONDS = 900  # hard cap, see below

# LOCAL MIRROR of signing.pin_ceremony's reason vocabulary. This
# module must not import pin_ceremony (import cycle); the drift
# test in tests/test_signing_ceremony_authorisation.py pins
# REASONS == signing.pin_ceremony.REASONS and
# _NO_PIN_REASONS == signing.pin_ceremony._NO_PIN_REASONS.
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

_OLD_PIN_KEYS = {"cycle_seq", "payload_hash"}
_CANDIDATE_KEYS = {"cycle_seq", "payload_hash", "signer_id", "key_id"}

# Sentinel for expected_old_pin in verify_ceremony_authorisation:
# omitted asserts nothing about the pin; an explicit None asserts
# the authorisation is a no-pin authorisation; a dict asserts
# exact equality. (pin_ceremony's _CONTEXT_UNSPECIFIED pattern,
# re-declared here because importing it would be circular.)
_CONTEXT_UNSPECIFIED = object()


def _is_seq(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) \
        and value >= 0


def _project_old_pin(old_pin):
    """Validate and project the old-pin shape: None, or a dict
    with EXACTLY {cycle_seq, payload_hash}. Returns a fresh dict
    (never the caller's object) or None."""
    if old_pin is None:
        return None
    if not isinstance(old_pin, dict) or set(old_pin) != _OLD_PIN_KEYS:
        raise SigningError(
            "old_pin must be null or an object with exactly "
            "cycle_seq and payload_hash")
    if not _is_seq(old_pin["cycle_seq"]):
        raise SigningError("old_pin cycle_seq must be an int >= 0")
    _check_hex64(old_pin["payload_hash"], "old_pin payload hash")
    return {"cycle_seq": old_pin["cycle_seq"],
            "payload_hash": old_pin["payload_hash"]}


def _project_candidate(candidate):
    """Validate and project the candidate shape: a dict with
    EXACTLY {cycle_seq, payload_hash, signer_id, key_id}."""
    if not isinstance(candidate, dict) \
            or set(candidate) != _CANDIDATE_KEYS:
        raise SigningError(
            "candidate must be an object with exactly cycle_seq, "
            "payload_hash, signer_id and key_id")
    if not _is_seq(candidate["cycle_seq"]):
        raise SigningError("candidate cycle_seq must be an int >= 0")
    _check_hex64(candidate["payload_hash"], "candidate payload hash")
    _check_id(candidate["signer_id"], "candidate signer id")
    _check_id(candidate["key_id"], "candidate key id")
    return {"cycle_seq": candidate["cycle_seq"],
            "payload_hash": candidate["payload_hash"],
            "signer_id": candidate["signer_id"],
            "key_id": candidate["key_id"]}


def ceremony_authorisation_payload(
        *, signer_id, key_id, operator_id, ceremony_id, reason,
        old_pin, candidate, evidence_hash, evidence_ref,
        signed_at, expires_at) -> dict:
    """The exact allowlisted projection that gets MACed.

    Validation here is the defence-in-depth copy of the verifier
    mode's pre-checks (the attestation_payload split): an
    authorisation for a non-ceremony movement must be
    un-issuable, not merely unusable."""
    _check_id(signer_id, "signer id")
    _check_id(key_id, "key id")
    _check_id(operator_id, "operator id")
    _check_id(ceremony_id, "ceremony id")
    if not isinstance(reason, str) or reason not in REASONS:
        raise SigningError(
            f"ceremony reason must be one of {sorted(REASONS)}")
    old_pin = _project_old_pin(old_pin)
    candidate = _project_candidate(candidate)
    # Reason/pin coherence, mirroring reanchor_pin's gate-on-state
    # rule: a no-pin reason requires no pin; a pin requires the
    # chain-gap reason.
    if old_pin is None and reason not in _NO_PIN_REASONS:
        raise SigningError(
            f"reason {reason!r} requires an old pin")
    if old_pin is not None and reason != REASON_CHAIN_GAP_RECOVERY:
        raise SigningError(
            "an authorisation carrying an old pin must use reason "
            "chain_gap_recovery")
    if old_pin is not None \
            and candidate["cycle_seq"] < old_pin["cycle_seq"] + 2:
        # Gap-only: +1 is a chained successor (advance_pin's
        # movement, and an integrity failure unchained); equal or
        # backwards is a fork/regression. The FULL relation —
        # including the prev-hash link — is the ceremony's check;
        # the verifier cannot see prev, so only the sequence half
        # is enforced here.
        raise SigningError(
            "candidate cycle_seq must be at least old_pin "
            "cycle_seq + 2 (gap-only re-anchor)")
    _check_hex64(evidence_hash, "evidence hash")
    if evidence_hash == candidate["payload_hash"]:
        raise SigningError(
            "evidence hash must differ from the candidate "
            "payload hash")
    if old_pin is not None \
            and evidence_hash == old_pin["payload_hash"]:
        raise SigningError(
            "evidence hash must differ from the old pin "
            "payload hash")
    _check_text(evidence_ref, "evidence_ref", 2000)
    signed = _parse_time(signed_at, "signed_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - signed
            <= timedelta(
                seconds=CEREMONY_AUTHORISATION_TTL_MAX_SECONDS)):
        raise SigningError(
            "signing window outside the ceremony authorisation "
            "TTL bounds")
    return {
        "v": "signed-ceremony-authorisation/1",
        "alg": ALG,
        "purpose": PURPOSE_CEREMONY_AUTHORISATION,
        "signer_id": signer_id,
        "key_id": key_id,
        "operator_id": operator_id,
        "ceremony_id": ceremony_id,
        "reason": reason,
        "old_pin": old_pin,
        "candidate": candidate,
        "evidence_hash": evidence_hash,
        "evidence_ref": evidence_ref,
        "signed_at": _normalise_time(signed_at, "signed_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


def _payload_hash(payload: dict) -> str:
    return _sha256(_canonical(payload))


def authorisation_id_for(payload_hash: str, key_id: str) -> str:
    """Derive an authorisation id from a payload hash and key id
    (the _attestation_id pattern, public because consumers —
    the client, the ceremony — re-derive it key-free)."""
    _check_hex64(payload_hash, "payload hash")
    _check_id(key_id, "key id")
    return _sha256(_canonical(
        {"v": CEREMONY_AUTHORISATION_DOMAIN,
         "payload_hash": payload_hash, "key_id": key_id}))


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (CEREMONY_AUTHORISATION_DOMAIN + "\n" + ALG + "\n"
            + key_id + "\n" + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SignedCeremonyAuthorisation:
    operator_id: str
    ceremony_id: str
    reason: str
    old_pin: dict | None
    candidate: dict
    evidence_hash: str
    evidence_ref: str
    signer_id: str
    key_id: str
    signed_at: str
    expires_at: str
    payload_hash: str
    authorisation_id: str
    signature: str

    def payload(self) -> dict:
        return ceremony_authorisation_payload(
            signer_id=self.signer_id, key_id=self.key_id,
            operator_id=self.operator_id,
            ceremony_id=self.ceremony_id, reason=self.reason,
            old_pin=self.old_pin, candidate=self.candidate,
            evidence_hash=self.evidence_hash,
            evidence_ref=self.evidence_ref,
            signed_at=self.signed_at, expires_at=self.expires_at)


def sign_ceremony_authorisation(
        *, signing_key: SigningKey, signer_id, operator_id,
        ceremony_id, reason, old_pin, candidate, evidence_hash,
        evidence_ref,
        ttl_seconds=CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS,
        now=None) -> SignedCeremonyAuthorisation:
    """MAC one ceremony authorisation under the verifier-side key.

    The signer is the VERIFIER, signing about the operator's
    presentation; signer_id is the verifier's id and need NOT
    equal operator_id (the one structural divergence from
    attestation.py — see the module docstring).

    TTL: default 900s with a HARD CAP — the effective ttl is
    min(ttl_seconds, 900), so a caller configured with a longer
    verifier TTL does not silently mint longer-lived ceremony
    authorisations. An authorisation is a live operator act;
    nothing in the flow has approval-workflow latency."""
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        raise SigningError("signing key id does not match its key material")
    if not isinstance(ttl_seconds, int) \
            or isinstance(ttl_seconds, bool) \
            or ttl_seconds < TTL_MIN_SECONDS:
        raise SigningError("ttl_seconds outside the TTL bounds")
    effective_ttl = min(ttl_seconds,
                          CEREMONY_AUTHORISATION_TTL_MAX_SECONDS)
    signed_at = _now() if now is None else now
    signed = _parse_time(signed_at, "signed_at")
    expires_at = (signed + timedelta(seconds=effective_ttl)).isoformat()
    payload = ceremony_authorisation_payload(
        signer_id=signer_id, key_id=signing_key.key_id,
        operator_id=operator_id, ceremony_id=ceremony_id,
        reason=reason, old_pin=old_pin, candidate=candidate,
        evidence_hash=evidence_hash, evidence_ref=evidence_ref,
        signed_at=signed_at, expires_at=expires_at)
    payload_hash = _payload_hash(payload)
    return SignedCeremonyAuthorisation(
        operator_id=operator_id, ceremony_id=ceremony_id,
        reason=reason, old_pin=payload["old_pin"],
        candidate=payload["candidate"], evidence_hash=evidence_hash,
        evidence_ref=evidence_ref, signer_id=signer_id,
        key_id=signing_key.key_id, signed_at=signed_at,
        expires_at=expires_at, payload_hash=payload_hash,
        authorisation_id=authorisation_id_for(payload_hash,
                                              signing_key.key_id),
        signature=_mac(signing_key.key, payload_hash,
                       signing_key.key_id))


def verify_ceremony_authorisation(
        signed, *, signing_key: SigningKey,
        expected_signer_id=None,
        expected_purpose=PURPOSE_CEREMONY_AUTHORISATION,
        expected_operator_id=None, expected_ceremony_id=None,
        expected_reason=None,
        expected_old_pin=_CONTEXT_UNSPECIFIED,
        expected_candidate=None,
        expected_evidence_hash=None, expected_evidence_ref=None,
        now=None) -> tuple:
    """Failure reasons for a ceremony authorisation envelope;
    () means it is authentic, unexpired, internally consistent,
    and bound as expected. Malformed envelopes raise
    SigningError; authentic-but-failing ones return reasons from
    exactly this vocabulary: key_id_inconsistent, unknown_key,
    malformed_payload, payload_hash_mismatch,
    authorisation_id_mismatch, signature_mismatch,
    signer_mismatch, operator_mismatch, ceremony_mismatch,
    reason_mismatch, old_pin_mismatch, candidate_mismatch,
    evidence_mismatch, evidence_ref_mismatch, signed_in_future,
    expired.

    ``expected_old_pin`` uses the sentinel pattern: omitted
    asserts nothing; explicit None asserts a no-pin
    authorisation; a dict asserts exact (seq, hash) equality
    against the projected pin shape. ``expected_candidate``
    asserts exact equality of the 4-field candidate projection.

    A () result proves issuance + binding; it does NOT prove the
    operator should have been authorised (that was decided at
    issuance against the verifier's protected list) nor that the
    evidence artefact is genuine (see the module docstring)."""
    if not isinstance(signed, SignedCeremonyAuthorisation):
        raise SigningError("signed must be a SignedCeremonyAuthorisation")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        return ("key_id_inconsistent",)
    reasons = []
    if signed.key_id != signing_key.key_id:
        reasons.append("unknown_key")
    try:
        payload = signed.payload()
    except (SigningError, UnicodeEncodeError):
        reasons.append("malformed_payload")
        return tuple(dict.fromkeys(reasons))
    if payload["purpose"] != expected_purpose:
        # The payload projection always emits the one purpose, so
        # a mismatch here means the caller pinned a different
        # purpose than this envelope type carries.
        reasons.append("malformed_payload")
        return tuple(dict.fromkeys(reasons))
    recomputed_hash = _payload_hash(payload)
    if signed.payload_hash != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    if signed.authorisation_id != authorisation_id_for(
            recomputed_hash, signed.key_id):
        reasons.append("authorisation_id_mismatch")
    expected_mac = _mac(signing_key.key, recomputed_hash, signed.key_id)
    if not isinstance(signed.signature, str) \
            or not _HEX64_RE.fullmatch(signed.signature) \
            or not hmac.compare_digest(signed.signature.encode("ascii"),
                                       expected_mac.encode("ascii")):
        reasons.append("signature_mismatch")
    if expected_signer_id is not None \
            and signed.signer_id != expected_signer_id:
        reasons.append("signer_mismatch")
    if expected_operator_id is not None \
            and signed.operator_id != expected_operator_id:
        reasons.append("operator_mismatch")
    if expected_ceremony_id is not None \
            and signed.ceremony_id != expected_ceremony_id:
        reasons.append("ceremony_mismatch")
    if expected_reason is not None \
            and signed.reason != expected_reason:
        reasons.append("reason_mismatch")
    if expected_old_pin is not _CONTEXT_UNSPECIFIED:
        try:
            expected_pin = _project_old_pin(expected_old_pin)
        except SigningError:
            expected_pin = _CONTEXT_UNSPECIFIED
        if expected_pin is _CONTEXT_UNSPECIFIED \
                or signed.old_pin != expected_pin:
            reasons.append("old_pin_mismatch")
    if expected_candidate is not None:
        try:
            expected_cand = _project_candidate(expected_candidate)
        except SigningError:
            expected_cand = None
        if signed.candidate != expected_cand:
            reasons.append("candidate_mismatch")
    if expected_evidence_hash is not None \
            and signed.evidence_hash != expected_evidence_hash:
        reasons.append("evidence_mismatch")
    if expected_evidence_ref is not None \
            and signed.evidence_ref != expected_evidence_ref:
        reasons.append("evidence_ref_mismatch")
    moment = _parse_time(_now() if now is None else now, "now")
    signed_at = _parse_time(signed.signed_at, "signed_at")
    expires_at = _parse_time(signed.expires_at, "expires_at")
    if signed_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))


# -- serialisation ----------------------------------------------------------

_ENVELOPE_KEYS = {"operator_id", "ceremony_id", "reason", "old_pin",
                  "candidate", "evidence_hash", "evidence_ref",
                  "signer_id", "key_id", "signed_at", "expires_at",
                  "payload_hash", "authorisation_id", "signature"}


def ceremony_authorisation_envelope_to_dict(
        signed: SignedCeremonyAuthorisation) -> dict:
    if not isinstance(signed, SignedCeremonyAuthorisation):
        raise SigningError(
            "signed must be a SignedCeremonyAuthorisation")
    return {
        "operator_id": signed.operator_id,
        "ceremony_id": signed.ceremony_id,
        "reason": signed.reason,
        "old_pin": None if signed.old_pin is None else {
            "cycle_seq": signed.old_pin["cycle_seq"],
            "payload_hash": signed.old_pin["payload_hash"]},
        "candidate": {
            "cycle_seq": signed.candidate["cycle_seq"],
            "payload_hash": signed.candidate["payload_hash"],
            "signer_id": signed.candidate["signer_id"],
            "key_id": signed.candidate["key_id"]},
        "evidence_hash": signed.evidence_hash,
        "evidence_ref": signed.evidence_ref,
        "signer_id": signed.signer_id, "key_id": signed.key_id,
        "signed_at": signed.signed_at,
        "expires_at": signed.expires_at,
        "payload_hash": signed.payload_hash,
        "authorisation_id": signed.authorisation_id,
        "signature": signed.signature,
    }


def ceremony_authorisation_envelope_from_dict(
        data) -> SignedCeremonyAuthorisation:
    if not isinstance(data, dict) or set(data) != _ENVELOPE_KEYS:
        raise SigningError(
            "ceremony authorisation envelope has missing or "
            "unknown keys")
    old_pin = data["old_pin"]
    if old_pin is not None:
        if not isinstance(old_pin, dict) \
                or set(old_pin) != _OLD_PIN_KEYS:
            raise SigningError(
                "envelope old_pin must be null or carry exactly "
                "cycle_seq and payload_hash")
        old_pin = {"cycle_seq": old_pin["cycle_seq"],
                   "payload_hash": old_pin["payload_hash"]}
    candidate = data["candidate"]
    if not isinstance(candidate, dict) \
            or set(candidate) != _CANDIDATE_KEYS:
        raise SigningError(
            "envelope candidate must carry exactly cycle_seq, "
            "payload_hash, signer_id and key_id")
    candidate = {"cycle_seq": candidate["cycle_seq"],
                 "payload_hash": candidate["payload_hash"],
                 "signer_id": candidate["signer_id"],
                 "key_id": candidate["key_id"]}
    signed = SignedCeremonyAuthorisation(
        operator_id=data["operator_id"],
        ceremony_id=data["ceremony_id"], reason=data["reason"],
        old_pin=old_pin, candidate=candidate,
        evidence_hash=data["evidence_hash"],
        evidence_ref=data["evidence_ref"],
        signer_id=data["signer_id"], key_id=data["key_id"],
        signed_at=data["signed_at"], expires_at=data["expires_at"],
        payload_hash=data["payload_hash"],
        authorisation_id=data["authorisation_id"],
        signature=data["signature"])
    for value, field_name in ((signed.payload_hash, "payload_hash"),
                              (signed.authorisation_id,
                               "authorisation_id"),
                              (signed.signature, "signature")):
        if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
            raise SigningError(f"envelope {field_name} must be hex64")
    # Validate every field the same way attestation's from_dict
    # does: an envelope that parses is an envelope whose fields a
    # signer could actually have emitted.
    signed.payload()
    return signed


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SigningError(f"duplicate key in JSON: {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise SigningError(f"non-finite JSON number: {name}")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise SigningError(f"non-finite JSON number: {text}")
    return value


def ceremony_authorisation_envelope_to_json(
        signed: SignedCeremonyAuthorisation) -> str:
    return json.dumps(ceremony_authorisation_envelope_to_dict(signed),
                      sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def ceremony_authorisation_envelope_from_json(
        text) -> SignedCeremonyAuthorisation:
    if not isinstance(text, str):
        raise SigningError(
            "ceremony authorisation envelope JSON must be text")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise SigningError(
            f"ceremony authorisation envelope is not valid JSON: "
            f"{exc}") from exc
    return ceremony_authorisation_envelope_from_dict(data)
