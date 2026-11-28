"""Signed supersession approvals (cycle 25) — VERIFY SIDE ONLY.

A supersession approval is the independent authorisation event
that cycle 25 adds in front of the verifier's cycle-24
supersession decision (trust/ledger.py's
CeremonySupersessionLedger, mode ``ceremony_supersede``).
Cycle 24's decision was separately signed and journaled, but
the pin adopter requested it automatically after a refusal;
seat-gpt's CROSS-CHECK-18 ruling was that a separately signed
decision is not a separately authorised one. This artefact is
what makes the authorisation separate:

* it is signed under a dedicated APPROVER key — a third
  Ed25519 key, distinct from the snapshot signing key and from
  the verifier's ceremony seed;
* it is minted ONLY by a separate tool invocation
  (trust/supersession_approval_tool.py), never by any running
  service — this module contains the payload projection, the
  serialisation and the verification, and NO signing function,
  NO seed type and NO seed loader, so importing it (as the
  verifier, the client and the adopter all legitimately do)
  confers no minting capability;
* it binds (a) the abandoned head movement (the consumption
  head entry's authorisation id, ceremony id and full
  (old -> new) pair), (b) the replacement candidate, (c) the
  exact movement on both sides (the abandoned pair and the
  replacement envelope's old pin -> candidate), and (d) the
  original failed consumption attempt (the attempted envelope's
  authorisation id, the refusal code that ended it, and the
  head entry's authorisation id, journal seq and entry hash
  it was refused against).

Trust claim, stated precisely (design:
the cycle-25 design-approval record, section 1, as
narrowed in cycle 26 — see
the consumption-head decision record, Addendum 6):
supersession requires a separately invoked,
cryptographically independent approval operation — a
standalone tool invocation, with its own inputs, producing
its own signed artefact under its own dedicated key —
outside the adopter's automated recovery path. The
mechanism does not establish that the invocation was
performed by a human, nor that no other unattended
automation invoked the tool. The approval tool's approve
command requires an interactive typed confirmation; no
non-interactive override exists. It is NOT a claim of a
separate human or a
separate OS user. On the same-user deployment the operator
and the approver are the same person running a second
command. The guarantee is that supersession cannot happen
as a side effect of an automated recovery flow; a fully
malicious same-user process remains outside the claim,
exactly as in trust/verifier_main.py's honesty statement.

Construction mirrors signing/ceremony_authorisation.py: an
allowlisted payload projection, canonical JSON, a payload
hash, an id derived from (domain, payload hash, key id), and
an Ed25519 signature over the newline-joined blob
``domain \\n alg \\n key_id \\n payload_hash`` under the strict
profile of signing/ed25519.py. The approver public key id
reuses ceremony_authorisation.public_key_id_for's derivation
("pub-" + sha256(public bytes)[:16]) so key ids across the two
artefact families are computed identically; the keys
themselves are independent draws, and the verifier refuses
startup if the two public keys are ever equal.

``now=`` parameters exist for tests only; see the warning in
signing/gate_decision.py's module docstring.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import timedelta

from signing import ed25519
from signing.ceremony_authorisation import (
    REASON_BURNED_UNADOPTED,
    SignedCeremonyAuthorisation,
    public_key_id_for,
)
from signing.gate_decision import (
    CLOCK_SKEW_SECONDS,
    TTL_MIN_SECONDS,
    SigningError,
    _canonical,
    _check_hex64,
    _check_id,
    _normalise_time,
    _now,
    _parse_time,
    _sha256,
)

SUPERSESSION_APPROVAL_DOMAIN = "signed-supersession-approval-v1"
DOMAIN = SUPERSESSION_APPROVAL_DOMAIN
ALG_APPROVAL = "ed25519"
PURPOSE_SUPERSESSION_APPROVAL = "pin-ceremony-supersession-approval"

# The only refusal an approval can be about: the pre-commit
# state refusal the consume mode emits when the supersede shape
# holds but no decision authorises the abandonment. The
# projection accepts no other value, so an approval can never
# be minted (or verified) as being "about" any other event.
REFUSAL_CODE_SUPERSESSION_REQUIRED = "ceremony_supersede_required"

APPROVAL_TTL_DEFAULT_SECONDS = 900
# Documented deviation from the ceremony envelope's 900 s hard
# cap (design section 6): an approval is a separately
# invoked operation — report, separate tool
# invocation, adopter re-run — and the
# exposure from the longer window is bounded by single-use,
# full binding, and head staleness (any head movement after the
# refusal invalidates the approval's failed-attempt binding).
APPROVAL_TTL_MAX_SECONDS = 3600

_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_HEX128_RE = re.compile(r"[0-9a-f]{128}")

_ABANDONED_KEYS = {"authorisation_id", "ceremony_id",
                   "old_cycle_seq", "old_payload_hash",
                   "new_cycle_seq", "new_payload_hash"}
_REPLACEMENT_KEYS = {"authorisation_id", "ceremony_id", "reason",
                     "operator_id",
                     "superseding_old_cycle_seq",
                     "superseding_old_payload_hash",
                     "candidate_cycle_seq", "candidate_payload_hash"}
_FAILED_ATTEMPT_KEYS = {"attempted_authorisation_id",
                        "refusal_code", "head_authorisation_id",
                        "head_entry_seq", "head_entry_hash"}


# -- approver public key ----------------------------------------------------


@dataclass(frozen=True)
class SupersessionApproverPublicKey:
    """Verifier/client-side pin for the approver key: public
    bytes only. This type cannot hold secret material — the
    same type separation the ceremony key boundary rests on.
    Deliberately NOT a CeremonyPublicKey: an approver pin passed
    where a ceremony pin is expected (or vice versa) is a type
    refusal, never a silent cross-use."""

    public_key: bytes
    key_id: str

    def __repr__(self) -> str:
        return (f"SupersessionApproverPublicKey("
                f"key_id={self.key_id!r})")


def approver_public_key_from_hex(text) -> SupersessionApproverPublicKey:
    """Build the approver public-key pin from its hex64 encoding
    (the form the AION_SUPERSESSION_APPROVER_PUBLIC_KEY verifier
    env var carries). Raises SigningError on any malformed
    input; the key id is derived from the public bytes, never
    taken from the caller."""
    if not isinstance(text, str) or not _HEX64_RE.fullmatch(text):
        raise SigningError(
            "approver public key must be 64 lowercase hex chars")
    public_key = bytes.fromhex(text)
    return SupersessionApproverPublicKey(
        public_key=public_key,
        key_id=public_key_id_for(public_key))


# -- projections --------------------------------------------------------------


def _is_seq(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) \
        and value >= 0


def _project_abandoned(abandoned):
    """Validate and project the abandoned-head binding: a dict
    with EXACTLY the _ABANDONED_KEYS fields. Returns a fresh
    dict (never the caller's object)."""
    if not isinstance(abandoned, dict) \
            or set(abandoned) != _ABANDONED_KEYS:
        raise SigningError(
            "abandoned must be an object with exactly "
            "authorisation_id, ceremony_id, old_cycle_seq, "
            "old_payload_hash, new_cycle_seq and new_payload_hash")
    _check_hex64(abandoned["authorisation_id"],
                 "abandoned authorisation id")
    _check_id(abandoned["ceremony_id"], "abandoned ceremony id")
    old_seq = abandoned["old_cycle_seq"]
    if old_seq is not None and not _is_seq(old_seq):
        raise SigningError(
            "abandoned old_cycle_seq must be null or an int >= 0")
    old_hash = abandoned["old_payload_hash"]
    if not isinstance(old_hash, str) \
            or (old_hash != "" and not _HEX64_RE.fullmatch(old_hash)):
        raise SigningError(
            "abandoned old_payload_hash must be \"\" or hex64")
    if (old_seq is None) != (old_hash == ""):
        raise SigningError(
            "abandoned old pin must be (null, \"\") or (seq, hash)")
    if not _is_seq(abandoned["new_cycle_seq"]):
        raise SigningError(
            "abandoned new_cycle_seq must be an int >= 0")
    _check_hex64(abandoned["new_payload_hash"],
                 "abandoned new payload hash")
    return {"authorisation_id": abandoned["authorisation_id"],
            "ceremony_id": abandoned["ceremony_id"],
            "old_cycle_seq": old_seq,
            "old_payload_hash": old_hash,
            "new_cycle_seq": abandoned["new_cycle_seq"],
            "new_payload_hash": abandoned["new_payload_hash"]}


def _project_replacement(replacement):
    """Validate and project the replacement binding: a dict with
    EXACTLY the _REPLACEMENT_KEYS fields. The reason must not be
    burned_unadopted: an ordinary recovery is not a supersession
    and can never be the replacement side of an approval
    (criterion (iv) at the projection surface — such an approval
    is un-mintable and un-verifiable, not merely unusable)."""
    if not isinstance(replacement, dict) \
            or set(replacement) != _REPLACEMENT_KEYS:
        raise SigningError(
            "replacement must be an object with exactly "
            "authorisation_id, ceremony_id, reason, operator_id, "
            "superseding_old_cycle_seq, "
            "superseding_old_payload_hash, candidate_cycle_seq "
            "and candidate_payload_hash")
    _check_hex64(replacement["authorisation_id"],
                 "replacement authorisation id")
    _check_id(replacement["ceremony_id"], "replacement ceremony id")
    if not isinstance(replacement["reason"], str) \
            or not replacement["reason"]:
        raise SigningError("replacement reason must be text")
    if replacement["reason"] == REASON_BURNED_UNADOPTED:
        raise SigningError(
            "a supersession approval cannot bind a "
            "burned_unadopted (recovery) envelope as its "
            "replacement")
    _check_id(replacement["operator_id"], "replacement operator id")
    if not _is_seq(replacement["superseding_old_cycle_seq"]):
        raise SigningError(
            "superseding_old_cycle_seq must be an int >= 0")
    _check_hex64(replacement["superseding_old_payload_hash"],
                 "superseding old payload hash")
    if not _is_seq(replacement["candidate_cycle_seq"]):
        raise SigningError("candidate_cycle_seq must be an int >= 0")
    _check_hex64(replacement["candidate_payload_hash"],
                 "candidate payload hash")
    if replacement["candidate_cycle_seq"] \
            <= replacement["superseding_old_cycle_seq"]:
        raise SigningError(
            "candidate must be strictly ahead of the superseding "
            "old pin")
    return {"authorisation_id": replacement["authorisation_id"],
            "ceremony_id": replacement["ceremony_id"],
            "reason": replacement["reason"],
            "operator_id": replacement["operator_id"],
            "superseding_old_cycle_seq":
                replacement["superseding_old_cycle_seq"],
            "superseding_old_payload_hash":
                replacement["superseding_old_payload_hash"],
            "candidate_cycle_seq": replacement["candidate_cycle_seq"],
            "candidate_payload_hash":
                replacement["candidate_payload_hash"]}


def _project_failed_attempt(failed_attempt):
    """Validate and project the failed-attempt binding: a dict
    with EXACTLY the _FAILED_ATTEMPT_KEYS fields, and the
    refusal code pinned to the one supersede refusal."""
    if not isinstance(failed_attempt, dict) \
            or set(failed_attempt) != _FAILED_ATTEMPT_KEYS:
        raise SigningError(
            "failed_attempt must be an object with exactly "
            "attempted_authorisation_id, refusal_code, "
            "head_authorisation_id, head_entry_seq and "
            "head_entry_hash")
    _check_hex64(failed_attempt["attempted_authorisation_id"],
                 "attempted authorisation id")
    if failed_attempt["refusal_code"] \
            != REFUSAL_CODE_SUPERSESSION_REQUIRED:
        raise SigningError(
            "failed_attempt refusal_code must be "
            f"{REFUSAL_CODE_SUPERSESSION_REQUIRED!r}")
    _check_hex64(failed_attempt["head_authorisation_id"],
                 "head authorisation id")
    if not _is_seq(failed_attempt["head_entry_seq"]) \
            or failed_attempt["head_entry_seq"] < 1:
        raise SigningError("head_entry_seq must be an int >= 1")
    _check_hex64(failed_attempt["head_entry_hash"],
                 "head entry hash")
    return {"attempted_authorisation_id":
                failed_attempt["attempted_authorisation_id"],
            "refusal_code": failed_attempt["refusal_code"],
            "head_authorisation_id":
                failed_attempt["head_authorisation_id"],
            "head_entry_seq": failed_attempt["head_entry_seq"],
            "head_entry_hash": failed_attempt["head_entry_hash"]}


def supersession_approval_payload(
        *, approver_id, key_id, abandoned, replacement,
        failed_attempt, approved_at, expires_at,
        alg=ALG_APPROVAL) -> dict:
    """The exact allowlisted projection that gets signed.

    ``alg`` is pinned: the projection emits "ed25519" only, and
    any other alg value is refused here (the ceremony v2
    discipline — an artefact claiming another alg cannot
    re-derive its payload and dies as malformed_payload at
    verification)."""
    if alg != ALG_APPROVAL:
        raise SigningError(
            f"supersession approval alg must be {ALG_APPROVAL!r}")
    _check_id(approver_id, "approver id")
    _check_id(key_id, "key id")
    abandoned = _project_abandoned(abandoned)
    replacement = _project_replacement(replacement)
    failed_attempt = _project_failed_attempt(failed_attempt)
    if failed_attempt["attempted_authorisation_id"] \
            != replacement["authorisation_id"]:
        raise SigningError(
            "the failed attempt must be an attempt to consume "
            "the replacement envelope itself")
    if failed_attempt["head_authorisation_id"] \
            != abandoned["authorisation_id"]:
        raise SigningError(
            "the failed attempt must have been refused against "
            "the abandoned head movement")
    approved = _parse_time(approved_at, "approved_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - approved
            <= timedelta(seconds=APPROVAL_TTL_MAX_SECONDS)):
        raise SigningError(
            "approval window outside the supersession approval "
            "TTL bounds")
    return {
        "v": "supersession-approval/1",
        "alg": alg,
        "purpose": PURPOSE_SUPERSESSION_APPROVAL,
        "approver_id": approver_id,
        "key_id": key_id,
        "abandoned": abandoned,
        "replacement": replacement,
        "failed_attempt": failed_attempt,
        "approved_at": _normalise_time(approved_at, "approved_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


def _payload_hash(payload: dict) -> str:
    return _sha256(_canonical(payload))


def approval_id_for(payload_hash: str, key_id: str) -> str:
    """Derive an approval id from a payload hash and the
    approver's PUBLIC key id (no secret participates in the
    id), under this artefact's own domain — disjoint from the
    ceremony authorisation id derivation."""
    _check_hex64(payload_hash, "payload hash")
    _check_id(key_id, "key id")
    return _sha256(_canonical(
        {"v": SUPERSESSION_APPROVAL_DOMAIN,
         "payload_hash": payload_hash, "key_id": key_id}))


def _signed_blob(payload_hash: str, key_id: str) -> bytes:
    """The exact bytes signed by Ed25519: domain, alg, key_id
    and payload_hash, newline-joined, utf-8 (the ceremony
    construction, under this artefact's domain)."""
    return (SUPERSESSION_APPROVAL_DOMAIN + "\n" + ALG_APPROVAL
            + "\n" + key_id + "\n" + payload_hash).encode("utf-8")


@dataclass(frozen=True)
class SignedSupersessionApproval:
    approver_id: str
    key_id: str
    abandoned: dict
    replacement: dict
    failed_attempt: dict
    approved_at: str
    expires_at: str
    payload_hash: str
    approval_id: str
    signature: str
    # Not a wire field (the artefact dict has no alg key; the
    # payload projection carries it). It exists so a
    # hand-constructed typed approval claiming a different alg
    # is refused at payload re-derivation (malformed_payload).
    alg: str = ALG_APPROVAL

    def payload(self) -> dict:
        return supersession_approval_payload(
            approver_id=self.approver_id, key_id=self.key_id,
            abandoned=self.abandoned, replacement=self.replacement,
            failed_attempt=self.failed_attempt,
            approved_at=self.approved_at,
            expires_at=self.expires_at, alg=self.alg)


# -- verification -------------------------------------------------------------


def verify_supersession_approval(
        signed, *, public_key: SupersessionApproverPublicKey,
        expected_approver_id=None, now=None) -> tuple:
    """Failure reasons for a supersession approval; () means it
    is authentic, unexpired, internally consistent, and signed
    under the pinned approver key. Malformed approvals raise
    SigningError; authentic-but-failing ones return reasons
    from exactly this vocabulary: key_id_inconsistent,
    unknown_key, malformed_payload, payload_hash_mismatch,
    approval_id_mismatch, signature_mismatch, approver_mismatch,
    signed_in_future, expired.

    A () result proves the approval was minted under the
    approver key over exactly these bound facts; it does NOT
    prove the bound facts are the verifier's current facts —
    that is approval_binding_mismatches against the verifier's
    own journals, which the supersede mode runs after this
    check (design section 8, steps 5b then 8b)."""
    if not isinstance(signed, SignedSupersessionApproval):
        raise SigningError(
            "signed must be a SignedSupersessionApproval")
    if not isinstance(public_key, SupersessionApproverPublicKey):
        raise SigningError(
            "public_key must be a SupersessionApproverPublicKey")
    try:
        derived_id = public_key_id_for(public_key.public_key)
    except SigningError:
        return ("key_id_inconsistent",)
    if public_key.key_id != derived_id:
        return ("key_id_inconsistent",)
    reasons = []
    if signed.key_id != public_key.key_id:
        reasons.append("unknown_key")
    try:
        payload = signed.payload()
    except (SigningError, UnicodeEncodeError):
        reasons.append("malformed_payload")
        return tuple(dict.fromkeys(reasons))
    if payload["purpose"] != PURPOSE_SUPERSESSION_APPROVAL:
        reasons.append("malformed_payload")
        return tuple(dict.fromkeys(reasons))
    recomputed_hash = _payload_hash(payload)
    if signed.payload_hash != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    if signed.approval_id != approval_id_for(
            recomputed_hash, signed.key_id):
        reasons.append("approval_id_mismatch")
    signature_ok = False
    if isinstance(signed.signature, str) \
            and _HEX128_RE.fullmatch(signed.signature):
        signature_ok = ed25519.verify(
            public_key.public_key,
            _signed_blob(recomputed_hash, signed.key_id),
            bytes.fromhex(signed.signature))
    if not signature_ok:
        reasons.append("signature_mismatch")
    if expected_approver_id is not None \
            and signed.approver_id != expected_approver_id:
        reasons.append("approver_mismatch")
    moment = _parse_time(_now() if now is None else now, "now")
    approved_at = _parse_time(signed.approved_at, "approved_at")
    expires_at = _parse_time(signed.expires_at, "expires_at")
    if approved_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))


def approval_binding_mismatches(
        approval, *, abandoned_entry, head_entry_seq,
        head_entry_hash, signed) -> tuple:
    """Compare a verified approval's binding against the facts
    the VERIFIER derived from its own state; () means fully
    bound. Pure function, no I/O: the caller passes the
    consumption journal's current head entry dict
    (``abandoned_entry``), that entry's journal ``seq`` and
    ``entry_hash``, and the presented envelope (a
    SignedCeremonyAuthorisation).

    Mismatch names, in check order: abandoned_mismatch (the
    abandoned id / ceremony / full (old -> new) pair vs the
    head entry), replacement_mismatch (the replacement ids,
    ceremony, reason and operator vs the envelope),
    movement_mismatch (the replacement movement — the
    envelope's old pin and candidate — vs the approval),
    failed_attempt_mismatch (the attempted id vs the envelope,
    the refusal code vs the constant, and the head id / seq /
    hash vs the head entry). The supersede mode folds ANY
    non-empty result into its single shape code
    ceremony_supersede_unproven (design section 8 step 8b), so
    these names are for tests and logs, never for the wire."""
    if not isinstance(approval, SignedSupersessionApproval):
        raise SigningError(
            "approval must be a SignedSupersessionApproval")
    if not isinstance(signed, SignedCeremonyAuthorisation):
        raise SigningError(
            "signed must be a SignedCeremonyAuthorisation")
    mismatches = []
    abandoned = approval.abandoned
    if abandoned["authorisation_id"] \
            != abandoned_entry["authorisation_id"] \
            or abandoned["ceremony_id"] \
            != abandoned_entry["ceremony_id"] \
            or abandoned["old_cycle_seq"] \
            != abandoned_entry["old_cycle_seq"] \
            or abandoned["old_payload_hash"] \
            != abandoned_entry["old_payload_hash"] \
            or abandoned["new_cycle_seq"] \
            != abandoned_entry["new_cycle_seq"] \
            or abandoned["new_payload_hash"] \
            != abandoned_entry["new_payload_hash"]:
        mismatches.append("abandoned_mismatch")
    replacement = approval.replacement
    if replacement["authorisation_id"] != signed.authorisation_id \
            or replacement["ceremony_id"] != signed.ceremony_id \
            or replacement["reason"] != signed.reason \
            or replacement["operator_id"] != signed.operator_id:
        mismatches.append("replacement_mismatch")
    old_pin = signed.old_pin
    if old_pin is None \
            or replacement["superseding_old_cycle_seq"] \
            != old_pin["cycle_seq"] \
            or replacement["superseding_old_payload_hash"] \
            != old_pin["payload_hash"] \
            or replacement["candidate_cycle_seq"] \
            != signed.candidate["cycle_seq"] \
            or replacement["candidate_payload_hash"] \
            != signed.candidate["payload_hash"]:
        mismatches.append("movement_mismatch")
    attempt = approval.failed_attempt
    if attempt["attempted_authorisation_id"] \
            != signed.authorisation_id \
            or attempt["refusal_code"] \
            != REFUSAL_CODE_SUPERSESSION_REQUIRED \
            or attempt["head_authorisation_id"] \
            != abandoned_entry["authorisation_id"] \
            or attempt["head_entry_seq"] != head_entry_seq \
            or attempt["head_entry_hash"] != head_entry_hash:
        mismatches.append("failed_attempt_mismatch")
    return tuple(mismatches)


# -- serialisation ------------------------------------------------------------

_APPROVAL_KEYS = {"approver_id", "key_id", "abandoned",
                  "replacement", "failed_attempt", "approved_at",
                  "expires_at", "payload_hash", "approval_id",
                  "signature"}


def supersession_approval_to_dict(
        signed: SignedSupersessionApproval) -> dict:
    if not isinstance(signed, SignedSupersessionApproval):
        raise SigningError(
            "signed must be a SignedSupersessionApproval")
    return {
        "approver_id": signed.approver_id,
        "key_id": signed.key_id,
        "abandoned": dict(signed.abandoned),
        "replacement": dict(signed.replacement),
        "failed_attempt": dict(signed.failed_attempt),
        "approved_at": signed.approved_at,
        "expires_at": signed.expires_at,
        "payload_hash": signed.payload_hash,
        "approval_id": signed.approval_id,
        "signature": signed.signature,
    }


def supersession_approval_from_dict(data) -> SignedSupersessionApproval:
    if not isinstance(data, dict) or set(data) != _APPROVAL_KEYS:
        raise SigningError(
            "supersession approval has missing or unknown keys")
    signed = SignedSupersessionApproval(
        approver_id=data["approver_id"], key_id=data["key_id"],
        abandoned=data["abandoned"], replacement=data["replacement"],
        failed_attempt=data["failed_attempt"],
        approved_at=data["approved_at"],
        expires_at=data["expires_at"],
        payload_hash=data["payload_hash"],
        approval_id=data["approval_id"],
        signature=data["signature"])
    for value, field_name in ((signed.payload_hash, "payload_hash"),
                              (signed.approval_id, "approval_id")):
        if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
            raise SigningError(f"approval {field_name} must be hex64")
    if not isinstance(signed.signature, str) \
            or not _HEX128_RE.fullmatch(signed.signature):
        raise SigningError("approval signature must be hex128")
    # Validate every field the same way the ceremony envelope's
    # from_dict does: an approval that parses is an approval
    # whose fields a signer could actually have emitted.
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


def supersession_approval_to_json(
        signed: SignedSupersessionApproval) -> str:
    return json.dumps(supersession_approval_to_dict(signed),
                      sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def supersession_approval_from_json(text) -> SignedSupersessionApproval:
    if not isinstance(text, str):
        raise SigningError("supersession approval JSON must be text")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise SigningError(
            f"supersession approval is not valid JSON: {exc}"
        ) from exc
    return supersession_approval_from_dict(data)
