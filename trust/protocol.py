"""Wire protocol between the verifier client and verifier process.

One process per request. Framing is a single JSON document per
direction, EOF-terminated: with exactly one request per process
there is nothing to delimit, and whole-stream framing makes
truncation, concatenation and partial writes structurally
detectable — any trailing non-whitespace after the document is a
protocol error on both sides.

Parsing is strict everywhere, following the signing package's
precedent: duplicate keys rejected, non-finite numbers rejected,
exact key sets at every level, unknown fields are errors.
"""

from __future__ import annotations

import json
import re
import secrets

REQUEST_VERSION = "trust-request/1"
RESPONSE_VERSION = "trust-response/1"

MAX_REQUEST_BYTES = 1 << 20       # 1 MiB
MAX_RESPONSE_BYTES = 1 << 20      # 1 MiB
MAX_STDERR_BYTES = 64 << 10       # 64 KiB, capture-truncate

MODES = ("gate", "sealed_eval", "verify_envelope", "submit_claim",
         "issue_attestation")

_REQUEST_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_REQUEST_KEYS = {"v", "request_id", "mode", "body"}
_RESPONSE_KEYS = {"v", "request_id", "mode", "status", "result", "error"}
_ERROR_KEYS = {"code", "detail"}
MAX_ERROR_DETAIL_CHARS = 200


class ProtocolError(ValueError):
    """A protocol document is malformed. Raised on both sides; the
    client maps it to VerifierProtocolError, the verifier to an
    exit-2 error document (when it can still write one)."""


def new_request_id() -> str:
    return "req-" + secrets.token_hex(8)


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProtocolError(f"duplicate key in JSON: {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise ProtocolError(f"non-finite JSON number: {name}")


def _reject_float(text):
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ProtocolError(f"non-finite JSON number: {text}")
    return value


def strict_loads(raw: bytes, *, cap: int, what: str):
    """Parse exactly one strict JSON document from raw bytes."""
    if len(raw) > cap:
        raise ProtocolError(f"{what} exceeds the {cap}-byte cap")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"{what} is not valid UTF-8") from exc
    stripped = text.strip()
    if not stripped:
        raise ProtocolError(f"{what} is empty")
    decoder = json.JSONDecoder(object_pairs_hook=_no_duplicates,
                               parse_constant=_reject_constant,
                               parse_float=_reject_float)
    try:
        doc, end = decoder.raw_decode(stripped)
    except ProtocolError:
        raise
    except RecursionError as exc:
        raise ProtocolError(f"{what} is nested too deeply") from exc
    except ValueError as exc:
        raise ProtocolError(f"{what} is not valid JSON: {exc}") from exc
    if stripped[end:].strip():
        raise ProtocolError(f"{what} has trailing data after the document")
    return doc


def dumps(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def encode_request(request_id: str, mode: str, body) -> bytes:
    if not _REQUEST_ID_RE.fullmatch(request_id or ""):
        raise ProtocolError("request_id is malformed")
    if mode not in MODES:
        raise ProtocolError(f"unknown mode: {mode!r}")
    if not isinstance(body, dict):
        raise ProtocolError("request body must be an object")
    raw = dumps({"v": REQUEST_VERSION, "request_id": request_id,
                 "mode": mode, "body": body})
    if len(raw) > MAX_REQUEST_BYTES:
        raise ProtocolError("request exceeds the size cap")
    return raw


def decode_request(raw: bytes) -> dict:
    doc = strict_loads(raw, cap=MAX_REQUEST_BYTES, what="request")
    if not isinstance(doc, dict) or set(doc) != _REQUEST_KEYS:
        raise ProtocolError("request has missing or unknown keys")
    if doc["v"] != REQUEST_VERSION:
        raise ProtocolError("request version is not trust-request/1")
    if not isinstance(doc["request_id"], str) \
            or not _REQUEST_ID_RE.fullmatch(doc["request_id"]):
        raise ProtocolError("request_id is malformed")
    if doc["mode"] not in MODES:
        raise ProtocolError(f"unknown mode: {doc['mode']!r}")
    if not isinstance(doc["body"], dict):
        raise ProtocolError("request body must be an object")
    return doc


DEPLOYMENT_MODES = ("production", "research")


def encode_response(request_id, mode, status, *, result=None,
                    error=None, deployment_mode=None) -> bytes:
    doc = {"v": RESPONSE_VERSION, "request_id": request_id,
           "mode": mode, "status": status}
    if deployment_mode is not None:
        # Optional effective-mode reporting (Trust Boundary
        # v3.1): present only on responses emitted after the
        # verifier's config load succeeded, so its absence on a
        # pre-config refusal is itself the signal that no mode
        # was ever established.
        if deployment_mode not in DEPLOYMENT_MODES:
            raise ProtocolError(
                f"unknown deployment_mode: {deployment_mode!r}")
        doc["deployment_mode"] = deployment_mode
    if status == "ok":
        doc["result"] = result
        doc["error"] = None
    else:
        doc["result"] = None
        code, detail = error
        doc["error"] = {"code": code,
                        "detail": str(detail)[:MAX_ERROR_DETAIL_CHARS]}
    return dumps(doc)


def decode_response(raw: bytes, *, expected_request_id: str,
                    expected_mode: str,
                    cap: int = MAX_RESPONSE_BYTES) -> dict:
    doc = strict_loads(raw, cap=cap, what="response")
    if not isinstance(doc, dict) \
            or set(doc) not in (_RESPONSE_KEYS,
                                _RESPONSE_KEYS | {"deployment_mode"}):
        raise ProtocolError("response has missing or unknown keys")
    if "deployment_mode" in doc \
            and doc["deployment_mode"] not in DEPLOYMENT_MODES:
        raise ProtocolError("response deployment_mode is unknown")
    if doc["v"] != RESPONSE_VERSION:
        raise ProtocolError("response version is not trust-response/1")
    if doc["request_id"] != expected_request_id:
        raise ProtocolError("response request_id does not echo the request")
    if doc["mode"] != expected_mode:
        raise ProtocolError("response mode does not echo the request")
    if doc["status"] not in ("ok", "error"):
        raise ProtocolError("response status is unknown")
    if doc["status"] == "error":
        err = doc["error"]
        if not isinstance(err, dict) or set(err) != _ERROR_KEYS \
                or not isinstance(err["code"], str) \
                or not isinstance(err["detail"], str):
            raise ProtocolError("response error object is malformed")
    return doc
