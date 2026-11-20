"""Signed verifier attestations.

Cycle 4's disclosed limit had a quieter twin: gate decisions bound
their attestation by *hash only*. ``attestation_hash_for`` hashes
whatever VerifierAttestation object the caller hands over — any
caller can fabricate an attestation-shaped object ("approve",
reward-hacking checked, any sealed hash) and hash it. Nothing
proved a key holder ever issued it. This module closes that half
of the gap the same way gate_decision.py closes the decision half:
the attestation itself is wrapped in an HMAC envelope under the
verifier-side key, with its own domain separation, and consumers
(``commit_signed(..., signed_attestation=...)``, the ship check)
verify the envelope before trusting the hash it is bound by.

Rules that make the envelope mean something:

* The signer IS the attester. ``sign_attestation`` requires
  signer_id == attestation.verifier_id; a third party countersigning
  someone else's attestation is refused, so a valid envelope names
  exactly one accountable verifier identity.
* The payload binds the attestation to one proposal
  (proposal_id) and, when the attestation concerns a build
  artifact, one build manifest (manifest_hash; empty when the
  attestation is not about an artifact, e.g. a memory write).
* Freshness is the envelope's own signed_at/expires_at window
  (same TTL bounds and clock-skew rule as gate decisions).
  Policy caps (attestations shortest-lived) live in the callers;
  the nested-expiry rule — an attestation must not outlive the
  decision it supports — is enforced at consume time by
  commit_signed / shipcheck.
* ``now=`` parameters exist for tests only; see the warning in
  gate_decision's module docstring.

Honest limits, inherited from gate_decision: HMAC is symmetric —
this is tamper-evidence plus key-placement discipline, not
non-repudiation, and it stops being a boundary at all if builder
code runs as the same OS user with read access to the key file.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import timedelta

from eval.gate import VerifierAttestation
from signing.gate_decision import (
    ALG,
    CLOCK_SKEW_SECONDS,
    TTL_DEFAULT_SECONDS,
    TTL_MAX_SECONDS,
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

import hashlib
import hmac

ATTESTATION_DOMAIN = "signed-verifier-attestation-v1"
PURPOSE_ATTESTATION = "attestation"
ATTESTATION_TTL_DEFAULT_SECONDS = 900

_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def attestation_payload(attestation, *, signer_id, key_id, proposal_id,
                        manifest_hash="", signed_at, expires_at) -> dict:
    """The exact allowlisted projection that gets MACed."""
    if not isinstance(attestation, VerifierAttestation):
        raise SigningError("attestation must be a VerifierAttestation")
    _check_id(signer_id, "signer id")
    _check_id(key_id, "key id")
    _check_id(proposal_id, "proposal id")
    _check_id(attestation.verifier_id, "attestation verifier id")
    if signer_id != attestation.verifier_id:
        raise SigningError(
            "signer_id must equal the attestation's verifier_id: an "
            "attestation envelope is issued by the attester, not "
            "countersigned by a third party")
    if attestation.decision not in ("approve", "reject"):
        raise SigningError("attestation decision must be approve or reject")
    _check_hex64(attestation.sealed_hash, "attestation sealed hash")
    if not isinstance(attestation.reward_hacking_checked, bool):
        raise SigningError("attestation reward_hacking_checked must be a bool")
    _check_text(attestation.evidence_ref, "attestation evidence_ref", 2000)
    if manifest_hash:
        _check_hex64(manifest_hash, "manifest hash")
    signed = _parse_time(signed_at, "signed_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - signed
            <= timedelta(seconds=TTL_MAX_SECONDS)):
        raise SigningError("signing window outside the TTL bounds")
    return {
        "v": "signed-verifier-attestation/1",
        "alg": ALG,
        "purpose": PURPOSE_ATTESTATION,
        "signer_id": signer_id,
        "key_id": key_id,
        "proposal_id": proposal_id,
        "manifest_hash": manifest_hash,
        "attestation": {
            "verifier_id": attestation.verifier_id,
            "decision": attestation.decision,
            "sealed_hash": attestation.sealed_hash,
            "reward_hacking_checked": attestation.reward_hacking_checked,
            "evidence_ref": attestation.evidence_ref,
            "attested_at": _normalise_time(attestation.attested_at,
                                           "attestation attested_at"),
        },
        "signed_at": _normalise_time(signed_at, "signed_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


def _payload_hash(payload: dict) -> str:
    return _sha256(_canonical(payload))


def _attestation_id(payload_hash: str, key_id: str) -> str:
    return _sha256(_canonical(
        {"v": ATTESTATION_DOMAIN, "payload_hash": payload_hash,
         "key_id": key_id}))


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (ATTESTATION_DOMAIN + "\n" + ALG + "\n" + key_id + "\n"
            + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SignedAttestation:
    attestation: VerifierAttestation
    signer_id: str
    key_id: str
    proposal_id: str
    manifest_hash: str
    signed_at: str
    expires_at: str
    payload_hash: str
    attestation_id: str
    signature: str

    def payload(self) -> dict:
        return attestation_payload(
            self.attestation, signer_id=self.signer_id,
            key_id=self.key_id, proposal_id=self.proposal_id,
            manifest_hash=self.manifest_hash, signed_at=self.signed_at,
            expires_at=self.expires_at)


def sign_attestation(attestation, *, signing_key: SigningKey, signer_id,
                     proposal_id, manifest_hash="",
                     ttl_seconds=ATTESTATION_TTL_DEFAULT_SECONDS,
                     now=None) -> SignedAttestation:
    """MAC one verifier attestation under the verifier-side key.

    signer_id must equal attestation.verifier_id (enforced in the
    payload projection): the envelope is the attester's own act.
    """
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        raise SigningError("signing key id does not match its key material")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) \
            or not (TTL_MIN_SECONDS <= ttl_seconds <= TTL_MAX_SECONDS):
        raise SigningError("ttl_seconds outside the TTL bounds")
    signed_at = _now() if now is None else now
    signed = _parse_time(signed_at, "signed_at")
    expires_at = (signed + timedelta(seconds=ttl_seconds)).isoformat()
    payload = attestation_payload(
        attestation, signer_id=signer_id, key_id=signing_key.key_id,
        proposal_id=proposal_id, manifest_hash=manifest_hash,
        signed_at=signed_at, expires_at=expires_at)
    payload_hash = _payload_hash(payload)
    return SignedAttestation(
        attestation=attestation, signer_id=signer_id,
        key_id=signing_key.key_id, proposal_id=proposal_id,
        manifest_hash=manifest_hash, signed_at=signed_at,
        expires_at=expires_at, payload_hash=payload_hash,
        attestation_id=_attestation_id(payload_hash, signing_key.key_id),
        signature=_mac(signing_key.key, payload_hash, signing_key.key_id))


def verify_signed_attestation(signed, *, signing_key: SigningKey,
                              expected_proposal_id=None,
                              expected_sealed_hash=None,
                              expected_verifier_id=None,
                              expected_manifest_hash=None,
                              now=None) -> tuple:
    """Failure reasons for an attestation envelope; () means it is
    authentic, unexpired, internally consistent, and bound as
    expected. Malformed envelopes raise SigningError; authentic-
    but-failing ones return reasons. Mirrors
    verify_signed_decision's contract.

    Note: () proves the named verifier issued this attestation —
    it does NOT prove the attestation approves anything. A signed
    "reject" verifies clean; consumers authorising an action must
    check attestation.decision themselves (commit_signed does).
    """
    if not isinstance(signed, SignedAttestation):
        raise SigningError("signed must be a SignedAttestation")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        return ("key_id_inconsistent",)
    reasons = []
    if signed.key_id != signing_key.key_id:
        reasons.append("unknown_key")
    if signed.signer_id != signed.attestation.verifier_id:
        # Checked before payload re-derivation (which also refuses
        # this, as malformed_payload) so the reason is reachable
        # and names the actual defect.
        reasons.append("signer_not_attester")
    try:
        payload = signed.payload()
    except (SigningError, UnicodeEncodeError):
        reasons.append("malformed_payload")
        return tuple(dict.fromkeys(reasons))
    recomputed_hash = _payload_hash(payload)
    if signed.payload_hash != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    if signed.attestation_id != _attestation_id(recomputed_hash,
                                                signed.key_id):
        reasons.append("attestation_id_mismatch")
    expected_mac = _mac(signing_key.key, recomputed_hash, signed.key_id)
    if not isinstance(signed.signature, str) \
            or not _HEX64_RE.fullmatch(signed.signature) \
            or not hmac.compare_digest(signed.signature.encode("ascii"),
                                       expected_mac.encode("ascii")):
        reasons.append("signature_mismatch")
    if expected_proposal_id is not None \
            and signed.proposal_id != expected_proposal_id:
        reasons.append("proposal_mismatch")
    if expected_verifier_id is not None \
            and signed.attestation.verifier_id != expected_verifier_id:
        reasons.append("verifier_mismatch")
    if expected_sealed_hash is not None \
            and signed.attestation.sealed_hash != expected_sealed_hash:
        reasons.append("sealed_hash_mismatch")
    if expected_manifest_hash is not None \
            and signed.manifest_hash != expected_manifest_hash:
        reasons.append("manifest_mismatch")
    moment = _parse_time(_now() if now is None else now, "now")
    signed_at = _parse_time(signed.signed_at, "signed_at")
    expires_at = _parse_time(signed.expires_at, "expires_at")
    if signed_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))


# -- serialisation ----------------------------------------------------------

_ENVELOPE_KEYS = {"attestation", "signer_id", "key_id", "proposal_id",
                  "manifest_hash", "signed_at", "expires_at",
                  "payload_hash", "attestation_id", "signature"}
_ATTESTATION_KEYS = {"verifier_id", "decision", "sealed_hash",
                     "reward_hacking_checked", "evidence_ref",
                     "attested_at"}


def attestation_envelope_to_dict(signed: SignedAttestation) -> dict:
    if not isinstance(signed, SignedAttestation):
        raise SigningError("signed must be a SignedAttestation")
    a = signed.attestation
    return {
        "attestation": {
            "verifier_id": a.verifier_id, "decision": a.decision,
            "sealed_hash": a.sealed_hash,
            "reward_hacking_checked": a.reward_hacking_checked,
            "evidence_ref": a.evidence_ref, "attested_at": a.attested_at,
        },
        "signer_id": signed.signer_id, "key_id": signed.key_id,
        "proposal_id": signed.proposal_id,
        "manifest_hash": signed.manifest_hash,
        "signed_at": signed.signed_at, "expires_at": signed.expires_at,
        "payload_hash": signed.payload_hash,
        "attestation_id": signed.attestation_id,
        "signature": signed.signature,
    }


def attestation_envelope_from_dict(data) -> SignedAttestation:
    if not isinstance(data, dict) or set(data) != _ENVELOPE_KEYS:
        raise SigningError("attestation envelope has missing or unknown keys")
    inner = data["attestation"]
    if not isinstance(inner, dict) or set(inner) != _ATTESTATION_KEYS:
        raise SigningError("attestation has missing or unknown keys")
    attestation = VerifierAttestation(
        verifier_id=inner["verifier_id"], decision=inner["decision"],
        sealed_hash=inner["sealed_hash"],
        reward_hacking_checked=inner["reward_hacking_checked"],
        evidence_ref=inner["evidence_ref"],
        attested_at=inner["attested_at"])
    if not isinstance(data["manifest_hash"], str):
        raise SigningError("envelope manifest_hash must be a string")
    signed = SignedAttestation(
        attestation=attestation, signer_id=data["signer_id"],
        key_id=data["key_id"], proposal_id=data["proposal_id"],
        manifest_hash=data["manifest_hash"], signed_at=data["signed_at"],
        expires_at=data["expires_at"], payload_hash=data["payload_hash"],
        attestation_id=data["attestation_id"], signature=data["signature"])
    for value, field_name in ((signed.payload_hash, "payload_hash"),
                              (signed.attestation_id, "attestation_id"),
                              (signed.signature, "signature")):
        if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
            raise SigningError(f"envelope {field_name} must be hex64")
    # Validate every field the same way envelope_from_dict does for
    # gate decisions: an envelope that parses is an envelope whose
    # fields a signer could actually have emitted.
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
    # Mirror signing/gate_decision.py's parse_float hook: a float
    # token that overflows to inf (e.g. 1e999) is refused by the
    # PARSER, structurally — not left for downstream type checks
    # to catch only incidentally.
    value = float(text)
    if not math.isfinite(value):
        raise SigningError(f"non-finite JSON number: {text}")
    return value


def attestation_envelope_to_json(signed: SignedAttestation) -> str:
    return json.dumps(attestation_envelope_to_dict(signed),
                      sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def attestation_envelope_from_json(text) -> SignedAttestation:
    if not isinstance(text, str):
        raise SigningError("attestation envelope JSON must be text")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise SigningError(f"attestation envelope is not valid JSON: {exc}") \
            from exc
    return attestation_envelope_from_dict(data)
