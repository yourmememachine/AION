"""Signed sealed-evaluation attestations.

The verifier process runs a sealed evaluation verifier-side (the
sealed prompts never leave it; the builder supplies a positional
transcript of answers) and returns the result as this signed
record — the attestation IS the report; there is no unsigned
duplicate. Reusing the gate-decision envelope for this was
rejected: its payload is GateDecision-shaped with memory-commit
semantics, and shoehorning a score into it would corrupt both
meanings. This record mirrors the signing package's patterns
(canonical JSON, domain separation, payload-hash-then-MAC, TTL
bounds, reasons-tuple verification) with its own domain; the small
duplication is accepted and noted for a future convergence cycle.

Anti-transplant binding is four-way:

* score <-> manifest_hash — which sealed set was scored;
* score <-> registry_digest — which registry state, including
  access-log head and sealed version, so the same items with a
  different history produce a different digest;
* score <-> answers_hash — which transcript produced the score;
* score <-> scope — which budget scope the evaluation was run
  under (the sealed_eval proposal_id, default "unscoped";
  evidence pairs use "<proposal>:baseline" /
  "<proposal>:candidate"). issue_attestation requires both
  records' scope roots to equal the proposal it is issuing for,
  so a record scored under one proposal's budget cannot be
  re-issued under another proposal id.

Moving the attestation across registries, across registry states,
or onto different answers breaks the payload a key-holding checker
recomputes. The builder-side client can recompute answers_hash
(unkeyed) but cannot verify the MAC; cryptographic verification
happens at key-holding consumers via verify_eval_attestation.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from datetime import timedelta

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
    _normalise_time,
    _now,
    _parse_time,
    _sha256,
    key_id_for,
)

EVAL_DOMAIN = "sealed-eval-attestation-v1"
_HEX64_RE = re.compile(r"[0-9a-f]{64}")

_RECORD_KEYS = {"payload", "payload_hash", "signature"}
_PAYLOAD_KEYS = {"v", "alg", "signer_id", "key_id", "actor", "set",
                 "n", "correct", "score", "version", "manifest_hash",
                 "registry_digest", "answers_hash", "scope",
                 "evaluated_at", "signed_at", "expires_at"}


def answers_hash_for(answers) -> str:
    """Unkeyed hash of a positional answer transcript. The client
    recomputes this from its own transcript as a real check it can
    perform without the key."""
    if not isinstance(answers, (list, tuple)) \
            or not all(isinstance(a, str) for a in answers):
        raise SigningError("answers must be a list of strings")
    return _sha256(_canonical({"v": "sealed-answers/1",
                               "answers": list(answers)}))


def scope_root_for(scope) -> str:
    """Root proposal of a budget scope string: strip ONE trailing
    ":baseline" / ":candidate" suffix, if present. A scope with no
    such suffix is its own root (e.g. "unscoped")."""
    if not isinstance(scope, str):
        raise SigningError("scope must be text")
    for suffix in (":baseline", ":candidate"):
        if scope.endswith(suffix):
            return scope[: -len(suffix)]
    return scope


def registry_digest_for(*, manifest_hash: str, sealed_version: int,
                        log_head: str, log_seq: int) -> str:
    """Digest of the registry state an evaluation ran against,
    synthesised from the registry's public surfaces (it exposes no
    state-digest accessor, and eval/ is protected)."""
    _check_hex64(manifest_hash, "manifest hash")
    _check_hex64(log_head, "log head")
    if not isinstance(sealed_version, int) \
            or isinstance(sealed_version, bool) or sealed_version < 0:
        raise SigningError("sealed_version must be a non-negative int")
    if not isinstance(log_seq, int) or isinstance(log_seq, bool) \
            or log_seq < 0:
        raise SigningError("log_seq must be a non-negative int")
    return _sha256(_canonical({
        "v": "registry-digest/1", "manifest_hash": manifest_hash,
        "sealed_version": sealed_version, "log_head": log_head,
        "log_seq": log_seq}))


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (EVAL_DOMAIN + "\n" + ALG + "\n" + key_id + "\n"
            + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


def _payload(*, signer_id, key_id, actor, report, registry_digest,
             answers_hash, signed_at, expires_at, scope="unscoped") -> dict:
    _check_id(signer_id, "signer id")
    _check_id(key_id, "key id")
    _check_id(actor, "actor")
    if not isinstance(report, dict) or report.get("set") != "sealed":
        raise SigningError("report must be a sealed evaluation report")
    n, correct = report["n"], report["correct"]
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise SigningError("report n must be a positive int")
    if not isinstance(correct, int) or isinstance(correct, bool) \
            or not 0 <= correct <= n:
        raise SigningError("report correct must be an int in [0, n]")
    score = report["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise SigningError("report score must be a number")
    try:
        score_value = float(score)
    except OverflowError as exc:
        raise SigningError("report score must be finite") from exc
    if not math.isfinite(score_value):
        raise SigningError("report score must be finite")
    if score_value != correct / n:
        # Exact, not tolerant: the payload stores correct/n, so a
        # presented score that differs at all — including NaN,
        # which fails every comparison — was not the signed score.
        raise SigningError("report score is not exactly correct / n")
    version = report["version"]
    if not isinstance(version, int) or isinstance(version, bool) \
            or version < 0:
        raise SigningError("report version must be a non-negative int")
    _check_hex64(report["manifest_hash"], "report manifest hash")
    _check_hex64(registry_digest, "registry digest")
    _check_hex64(answers_hash, "answers hash")
    if not isinstance(scope, str) or not scope or len(scope) > 128:
        raise SigningError("scope must be non-empty text")
    signed = _parse_time(signed_at, "signed_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - signed
            <= timedelta(seconds=TTL_MAX_SECONDS)):
        raise SigningError("signing window outside the TTL bounds")
    return {
        "v": "sealed-eval-attestation/1",
        "alg": ALG,
        "signer_id": signer_id,
        "key_id": key_id,
        "actor": actor,
        "set": "sealed",
        "n": n,
        "correct": correct,
        "score": correct / n,
        "version": version,
        "manifest_hash": report["manifest_hash"],
        "registry_digest": registry_digest,
        "answers_hash": answers_hash,
        "scope": scope,
        "evaluated_at": _normalise_time(report["evaluated_at"],
                                        "evaluated_at"),
        "signed_at": _normalise_time(signed_at, "signed_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


def sign_eval_attestation(report, *, signing_key: SigningKey, signer_id,
                          actor, registry_digest, answers_hash,
                          ttl_seconds=TTL_DEFAULT_SECONDS,
                          now=None, scope="unscoped") -> dict:
    """MAC one sealed evaluation report. Returns the record dict
    {payload, payload_hash, signature} — the whole artefact."""
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
    payload = _payload(
        signer_id=signer_id, key_id=signing_key.key_id, actor=actor,
        report=report, registry_digest=registry_digest,
        answers_hash=answers_hash, signed_at=signed_at,
        expires_at=expires_at, scope=scope)
    payload_hash = _sha256(_canonical(payload))
    return {"payload": payload, "payload_hash": payload_hash,
            "signature": _mac(signing_key.key, payload_hash,
                              signing_key.key_id)}


def rebuild_eval_payload(record) -> dict:
    """Rebuild the canonical payload for a presented eval record.

    This is the single rebuild used by both key-holding
    verification (verify_eval_attestation below) and the key-free
    client (trust/client.py): the payload is re-derived from the
    presented fields with score stored as correct / n (a float),
    so a presented score spelled as int 1 for a 1.0 record rebuilds
    to the identical canonical payload the signature was computed
    over — the numeric SPELLING of the score is not part of the
    signed artefact, only its value is. A presented score whose
    value is not exactly correct / n, or any other field a signer
    could not have emitted, raises SigningError (via _payload)."""
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise SigningError("eval attestation record has missing or "
                           "unknown keys")
    payload = record["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise SigningError("eval attestation payload has missing or "
                           "unknown keys")
    report = {"set": payload["set"], "n": payload["n"],
              "correct": payload["correct"],
              "score": payload["score"], "version": payload["version"],
              "manifest_hash": payload["manifest_hash"],
              "evaluated_at": payload["evaluated_at"]}
    return _payload(
        signer_id=payload["signer_id"], key_id=payload["key_id"],
        actor=payload["actor"], report=report,
        registry_digest=payload["registry_digest"],
        answers_hash=payload["answers_hash"],
        signed_at=payload["signed_at"],
        expires_at=payload["expires_at"],
        scope=payload["scope"])


def verify_eval_attestation(record, *, signing_key: SigningKey,
                            expected_manifest_hash=None,
                            expected_registry_digest=None,
                            expected_answers_hash=None,
                            expected_signer_id=None,
                            expected_scope=None,
                            now=None) -> tuple:
    """Failure reasons for a sealed-eval attestation record; ()
    means authentic, unexpired, internally consistent (score is
    exactly correct / n), and bound as expected. Structurally
    malformed records raise SigningError; authentic-but-failing
    ones return reasons. Key-holding consumers only — the client
    cannot call this."""
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        return ("key_id_inconsistent",)
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise SigningError("eval attestation record has missing or "
                           "unknown keys")
    payload = record["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise SigningError("eval attestation payload has missing or "
                           "unknown keys")
    reasons = []
    if payload["key_id"] != signing_key.key_id:
        reasons.append("unknown_key")
    try:
        rebuilt = rebuild_eval_payload(record)
    except (SigningError, KeyError, TypeError, UnicodeEncodeError,
            OverflowError, ValueError):
        return ("malformed_payload",)
    recomputed_hash = _sha256(_canonical(rebuilt))
    if record["payload_hash"] != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    expected_mac = _mac(signing_key.key, recomputed_hash, payload["key_id"])
    signature = record["signature"]
    if not isinstance(signature, str) \
            or not _HEX64_RE.fullmatch(signature) \
            or not hmac.compare_digest(signature.encode("ascii"),
                                       expected_mac.encode("ascii")):
        reasons.append("signature_mismatch")
    if expected_manifest_hash is not None \
            and payload["manifest_hash"] != expected_manifest_hash:
        reasons.append("manifest_mismatch")
    if expected_registry_digest is not None \
            and payload["registry_digest"] != expected_registry_digest:
        reasons.append("registry_digest_mismatch")
    if expected_answers_hash is not None \
            and payload["answers_hash"] != expected_answers_hash:
        reasons.append("answers_mismatch")
    if expected_signer_id is not None \
            and payload["signer_id"] != expected_signer_id:
        reasons.append("signer_mismatch")
    if expected_scope is not None \
            and payload["scope"] != expected_scope:
        reasons.append("scope_mismatch")
    moment = _parse_time(_now() if now is None else now, "now")
    signed_at = _parse_time(payload["signed_at"], "signed_at")
    expires_at = _parse_time(payload["expires_at"], "expires_at")
    if signed_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))

# Public aliases: the key-free client validates record structure
# against exactly these sets.
RECORD_KEYS = _RECORD_KEYS
PAYLOAD_KEYS = _PAYLOAD_KEYS
