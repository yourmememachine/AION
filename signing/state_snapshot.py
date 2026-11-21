"""Signed snapshots of the core loop state and the calibration log.

Cycle 10 (backlog item ``signed-state``: "Signed state and per-seat
vote records"). The loop's state file (``state/state.json``) carries
every cycle's history and every self-improvement delta the project
claims; the calibration log (``state/calibration/calibration.json``)
carries the per-seat blind scores those claims rest on. Both are
plain files: a same-user editor who rewrites either one and
recomputes its internal hashes leaves no trace. This module lets a
key holder attest the exact bytes of both files at a moment in
time, so a later reader can prove the state and the vote record
they are looking at are the ones that were attested — or detect
that they are not.

Design, mirroring ``signing/gate_decision.py``:

- The signer RECOMPUTES everything from the raw bytes it is
  handed: the state hash, the extracted state facts (schema
  version, cycle sequence, history length, last cycle) and the
  calibration hash are derived here by one strict parser shared
  by signing and verification — never asserted by the caller.
  Signing a digest handed to the signer would prove only that
  the signer signed it.
- Domain-separated HMAC-SHA256 over an allowlisted payload
  (``signed-state-snapshot-v1``), with the same key rules, TTL
  bounds and clock-skew handling as gate decisions. Snapshots
  carry the previous snapshot's payload hash in the payload;
  verification checks that link where a caller supplies it
  (``expected_prev_snapshot_hash``) and for the immediate
  successor of a pin — elsewhere the link is attested data, not
  a verified chain.
- Verification returns reason strings, ``()`` meaning authentic,
  unexpired, internally consistent (every attested fact passes
  the payload builder's validation) and bound as expected. A
  caller may pin the newest snapshot it trusts
  (``expected_pin={"cycle_seq": ..., "payload_hash": ...}``,
  kept outside the state directory): an older snapshot presented
  against that pin reports ``snapshot_rolled_back``, and a
  same-sequence snapshot with a different hash reports
  ``pin_mismatch``.

Honest limits, stated not hidden:

- A valid MAC proves a key holder attested these exact bytes —
  not that the state is valid. This module structurally checks
  the extracted facts (schema version, non-bool integer fields,
  strictly increasing history cycle ids, ``cycle_seq`` equal to
  the last history cycle) but deliberately does NOT re-run the
  loop's full validation (title hashes, backlog/history
  agreement, delta arithmetic): that logic lives in the loop and
  duplicating it here would drift. A fabricated but well-formed
  history passes this module; it does not pass the loop's own
  loader, and consumers must run both.
- Rollback is undetectable without an external pin: an old state
  paired with its own old snapshot is internally perfect. The
  pin is the defence, exactly as ledger anchoring is elsewhere
  in this project; joint rollback of state, calibration,
  snapshots and pin together is undetectable in-deployment.
- The calibration binding is the hash of the whole log file, so
  any edit — blind scores, outcomes, discussion timestamps —
  changes it. It proves the votes are the recorded ones; it does
  not prove the seats are distinct people or that scores were
  truly blind (the calibration log's own stated limits).
- HMAC is symmetric: any key holder can forge a snapshot, the
  signer id is a claim, and there is no non-repudiation. The
  boundary is key placement (0600, outside the repo, ideally a
  separate OS user), as with gate decisions.
- ``state.json`` and ``calibration.json`` are replaced
  individually, never jointly: two reads can capture a pair that
  never coexisted. ``sign_state_files`` enforces the mitigation
  in code (read state, read calibration, re-read state, refuse
  on change); the byte-level functions cannot, and a calibration
  write racing the second state read in the other order remains
  possible. Integrity is not consistency: the MAC proves the
  bytes were attested, not that they are one coherent generation
  of the application.
- A snapshot is a freshness-bounded attestation, not an archival
  proof: after its TTL (48 hours at most) it no longer verifies,
  however authentic the bytes are. Long-lived provenance comes
  from anchoring the payload hash externally while the snapshot
  is live, not from stretching the TTL.
- The pin is part of the security boundary: it must live outside
  the rollback domain, be protected against modification, be
  advanced only after a verification returns ``()``, and never
  be reconstructed from the snapshot being verified. The chain
  link proves continuity only where it is checked (the immediate
  successor of a pin, or an explicitly supplied expected previous
  hash); a chain alone does not establish completeness — omitted
  intermediate snapshots are invisible without a trusted
  checkpoint. Timestamps rest on the host clock: the 300-second
  skew is a policy choice, not proof of trustworthy time, and
  the effective validity window is at most TTL + skew.
- A valid snapshot establishes membership in the key-holder
  group, not individually attributable authorship. There is no
  key rotation or revocation here: a snapshot under a retired
  key reports ``unknown_key`` against the new key, and replay of
  a snapshot inside its TTL is allowed unless the caller's pin
  has advanced past it.
- Bare ``verify_signed_snapshot`` is an envelope-only check: its
  optional expectations compare nothing when omitted.
  ``verify_snapshot_for_state`` is the strict entry point that
  requires every binding.
- The ``now`` parameters are test seams only. A caller passing a
  past ``now`` resurrects expired snapshots in-process;
  production wrappers must never accept one.
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

DOMAIN = "signed-state-snapshot-v1"
STATE_SNAPSHOT_DOMAIN = DOMAIN
PURPOSE_STATE_SNAPSHOT = "state-snapshot"
MAX_STATE_BYTES = 5 * 1024 * 1024
MAX_CALIBRATION_BYTES = 5 * 1024 * 1024
MAX_HISTORY = 200  # mirrors core/loop.py's history cap

_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (DOMAIN + "\n" + ALG + "\n" + key_id + "\n"
            + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


def _payload_hash(payload: dict) -> str:
    return _sha256(_canonical(payload))


def snapshot_id_for(payload_hash: str, key_id: str) -> str:
    return _sha256(_canonical(
        {"v": DOMAIN, "payload_hash": payload_hash, "key_id": key_id}))


# -- state parsing ----------------------------------------------------------


@dataclass(frozen=True)
class StateFacts:
    """The facts a snapshot extracts from the raw state bytes."""

    state_sha256: str
    schema_version: int
    cycle_seq: int
    history_len: int
    last_cycle_id: int | None
    last_item_id: str | None
    last_completed_at: str | None


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SigningError(f"duplicate key in state: {key}")
        out[key] = value
    return out


def _reject_constant(value):
    raise SigningError(f"non-finite number in state: {value}")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise SigningError(f"non-finite number in state: {text}")
    return value


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_state_bytes(state_bytes) -> StateFacts:
    """Strictly extract the snapshot facts from raw state bytes.

    The one parser used by both signing and verification, so the
    two can never disagree about what the bytes say. Raises
    SigningError on anything malformed. Only the extracted fields
    are interpreted; the byte hash binds everything else.
    """
    if not isinstance(state_bytes, (bytes, bytearray)):
        raise SigningError("state must be bytes")
    raw = bytes(state_bytes)
    if len(raw) > MAX_STATE_BYTES:
        raise SigningError("state exceeds the size cap")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SigningError("state is not valid UTF-8") from exc
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(f"state is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SigningError("state must be a JSON object")
    schema = data.get("schema_version")
    if not _is_int(schema) or schema != 1:
        raise SigningError("state schema_version must be the integer 1")
    cycle_seq = data.get("cycle_seq")
    if not _is_int(cycle_seq) or cycle_seq < 0:
        raise SigningError("state cycle_seq must be a non-negative integer")
    history = data.get("history")
    if not isinstance(history, list):
        raise SigningError("state history must be a list")
    if len(history) > MAX_HISTORY:
        raise SigningError("state history exceeds the loop's history cap")
    last_cycle_id = None
    last_item_id = None
    last_completed_at = None
    previous = 0
    previous_stamp = None
    for entry in history:
        if not isinstance(entry, dict):
            raise SigningError("state history entries must be objects")
        cycle_id = entry.get("cycle_id")
        if not _is_int(cycle_id) or cycle_id < 1:
            raise SigningError("history cycle_id must be a positive integer")
        if cycle_id <= previous:
            raise SigningError("history cycle ids must strictly increase")
        previous = cycle_id
        _check_id(entry.get("item_id"), "history item_id")
        completed = entry.get("completed_at")
        if completed is not None:
            # Every entry's timestamp is validated, not only the
            # last one's (war-room cycle 10, rev-r2/r3), and the
            # sequence must be non-decreasing: history is written
            # in time order, so a later cycle stamped earlier than
            # its predecessor — or an early cycle stamped after
            # the last one — is malformed, even though only the
            # last timestamp is extracted.
            stamp = _parse_time(
                _normalise_time(completed, "history completed_at"),
                "history completed_at")
            if previous_stamp is not None and stamp < previous_stamp:
                raise SigningError(
                    "history completed_at values must be "
                    "non-decreasing")
            previous_stamp = stamp
    if history:
        last = history[-1]
        last_cycle_id = last["cycle_id"]
        last_item_id = last["item_id"]
        if cycle_seq != last_cycle_id:
            raise SigningError(
                "state cycle_seq does not equal the last history cycle")
        completed = last.get("completed_at")
        if completed is not None:
            last_completed_at = _normalise_time(completed, "completed_at")
    elif cycle_seq != 0:
        raise SigningError("state with empty history must have cycle_seq 0")
    return StateFacts(
        state_sha256=_sha256(raw), schema_version=schema,
        cycle_seq=cycle_seq, history_len=len(history),
        last_cycle_id=last_cycle_id, last_item_id=last_item_id,
        last_completed_at=last_completed_at)


def state_hash_for(state_bytes) -> str:
    """SHA-256 of the exact state bytes (no parsing)."""
    if not isinstance(state_bytes, (bytes, bytearray)):
        raise SigningError("state must be bytes")
    raw = bytes(state_bytes)
    if len(raw) > MAX_STATE_BYTES:
        raise SigningError("state exceeds the size cap")
    return _sha256(raw)


def calibration_hash_for(calibration_bytes) -> str:
    """SHA-256 of the exact calibration log bytes (never parsed:
    the whole file is the vote record, so the whole file is bound)."""
    if not isinstance(calibration_bytes, (bytes, bytearray)):
        raise SigningError("calibration log must be bytes")
    raw = bytes(calibration_bytes)
    if len(raw) > MAX_CALIBRATION_BYTES:
        raise SigningError("calibration log exceeds the size cap")
    return _sha256(raw)


# -- payload ------------------------------------------------------------------


def _check_hash_or_empty(value, field: str) -> str:
    if not isinstance(value, str):
        raise SigningError(f"{field} must be a string")
    if value:
        _check_hex64(value, field)
    return value


def _validate_facts(facts: StateFacts) -> str | None:
    """Validate the attested facts themselves — ranges, types and
    the consistency relations checkable without the state bytes —
    and return the normalised last_completed_at (or None).

    This runs inside the payload builder, the one re-derivation
    point shared by signing, verification and envelope
    reconstruction, so a snapshot carrying facts no signer would
    emit fails as malformed_payload everywhere, not only when a
    caller happens to supply the state bytes (war-room cycle 10,
    rev-r1/r2/r4)."""
    if not _is_int(facts.schema_version) or facts.schema_version != 1:
        raise SigningError("state schema_version must be the integer 1")
    if not _is_int(facts.cycle_seq) or facts.cycle_seq < 0:
        raise SigningError("cycle_seq must be a non-negative integer")
    if not _is_int(facts.history_len) or facts.history_len < 0:
        raise SigningError("history_len must be a non-negative integer")
    if facts.history_len > MAX_HISTORY:
        raise SigningError("history_len exceeds the loop's history cap")
    if facts.last_cycle_id is not None and (
            not _is_int(facts.last_cycle_id) or facts.last_cycle_id < 1):
        raise SigningError("last_cycle_id must be a positive integer or None")
    if (facts.history_len == 0) != (facts.last_cycle_id is None):
        raise SigningError(
            "history_len and last_cycle_id disagree about emptiness")
    if facts.history_len == 0 and facts.cycle_seq != 0:
        raise SigningError("empty history requires cycle_seq 0")
    if facts.history_len > 0 and facts.cycle_seq != facts.last_cycle_id:
        raise SigningError("cycle_seq must equal the last history cycle")
    if facts.history_len > 0 and facts.history_len > facts.last_cycle_id:
        # History cycle ids are strictly increasing positive
        # integers ending at cycle_seq, so at most cycle_seq
        # entries can exist; more is signer-impossible even though
        # fewer is legitimate (pruned history). War-room cycle 12,
        # rev-r1/rev-r4.
        raise SigningError(
            "history_len exceeds the last history cycle")
    if facts.last_item_id is not None:
        _check_id(facts.last_item_id, "last item id")
    if (facts.history_len == 0) != (facts.last_item_id is None):
        raise SigningError(
            "history_len and last_item_id disagree about emptiness")
    if (facts.history_len == 0) != (facts.last_completed_at is None):
        raise SigningError(
            "history_len and last_completed_at disagree about emptiness")
    if facts.last_completed_at is None:
        return None
    return _normalise_time(facts.last_completed_at, "last_completed_at")


def state_snapshot_payload(facts: StateFacts, *, signer_id, key_id,
                           signed_at, expires_at,
                           purpose=PURPOSE_STATE_SNAPSHOT,
                           calibration_sha256="",
                           prev_snapshot_hash="") -> dict:
    """The exact allowlisted projection that gets MACed. Every
    field is validated here (see _validate_facts), so payload
    re-derivation is a complete validator, as in gate_decision."""
    if not isinstance(facts, StateFacts):
        raise SigningError("facts must be a StateFacts")
    _check_id(signer_id, "signer id")
    _check_id(key_id, "key id")
    _check_id(purpose, "purpose")
    _check_hex64(facts.state_sha256, "state hash")
    _check_hash_or_empty(calibration_sha256, "calibration hash")
    _check_hash_or_empty(prev_snapshot_hash, "previous snapshot hash")
    last_completed_at = _validate_facts(facts)
    signed = _parse_time(signed_at, "signed_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - signed
            <= timedelta(seconds=TTL_MAX_SECONDS)):
        raise SigningError("signing window outside the TTL bounds")
    if last_completed_at is not None:
        completed = _parse_time(last_completed_at, "last_completed_at")
        if signed < completed - timedelta(seconds=CLOCK_SKEW_SECONDS):
            raise SigningError(
                "signed_at precedes the state's last completed cycle")
    return {
        "v": "signed-state-snapshot/1",
        "alg": ALG,
        "purpose": purpose,
        "signer_id": signer_id,
        "key_id": key_id,
        "state_sha256": facts.state_sha256,
        "state_schema_version": facts.schema_version,
        "cycle_seq": facts.cycle_seq,
        "history_len": facts.history_len,
        "last_cycle_id": facts.last_cycle_id,
        "last_item_id": facts.last_item_id,
        "last_completed_at": last_completed_at,
        "calibration_sha256": calibration_sha256,
        "prev_snapshot_hash": prev_snapshot_hash,
        "signed_at": _normalise_time(signed_at, "signed_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


@dataclass(frozen=True)
class SignedStateSnapshot:
    state_sha256: str
    state_schema_version: int
    cycle_seq: int
    history_len: int
    last_cycle_id: int | None
    last_item_id: str | None
    last_completed_at: str | None
    calibration_sha256: str
    prev_snapshot_hash: str
    signer_id: str
    key_id: str
    purpose: str
    signed_at: str
    expires_at: str
    payload_hash: str
    snapshot_id: str
    signature: str

    def payload(self) -> dict:
        facts = StateFacts(
            state_sha256=self.state_sha256,
            schema_version=self.state_schema_version,
            cycle_seq=self.cycle_seq, history_len=self.history_len,
            last_cycle_id=self.last_cycle_id,
            last_item_id=self.last_item_id,
            last_completed_at=self.last_completed_at)
        return state_snapshot_payload(
            facts, signer_id=self.signer_id, key_id=self.key_id,
            signed_at=self.signed_at, expires_at=self.expires_at,
            purpose=self.purpose,
            calibration_sha256=self.calibration_sha256,
            prev_snapshot_hash=self.prev_snapshot_hash)


# -- signing ------------------------------------------------------------------


def sign_state_snapshot(state_bytes, *, signing_key: SigningKey, signer_id,
                        calibration_bytes=None, prev_snapshot_hash="",
                        purpose=PURPOSE_STATE_SNAPSHOT,
                        ttl_seconds=TTL_DEFAULT_SECONDS,
                        now=None) -> SignedStateSnapshot:
    """Attest the exact state (and optionally calibration) bytes.

    Every bound fact is recomputed here from the raw bytes; the
    caller asserts nothing but the signer identity and the chain
    link. ``calibration_bytes=None`` leaves the vote record
    unbound (``calibration_sha256 == ""``); passing ``b""`` is
    refused as malformed — an empty log is not a vote record —
    so ``None`` is the only spelling of unbound.
    """
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        raise SigningError("signing key id does not match its key material")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) \
            or not (TTL_MIN_SECONDS <= ttl_seconds <= TTL_MAX_SECONDS):
        raise SigningError("ttl_seconds outside the TTL bounds")
    facts = parse_state_bytes(state_bytes)
    if calibration_bytes is not None and len(calibration_bytes) == 0:
        # An empty calibration log is malformed, not "unbound":
        # None already means unbound, and two spellings of roughly
        # the same claim invite silent confusion (external seat,
        # cycle 10).
        raise SigningError(
            "calibration_bytes is empty; pass None to leave the "
            "vote record unbound")
    calibration_sha256 = ("" if calibration_bytes is None
                          else calibration_hash_for(calibration_bytes))
    signed_at = _now() if now is None else now
    signed = _parse_time(signed_at, "signed_at")
    if facts.last_completed_at is not None:
        completed = _parse_time(facts.last_completed_at, "completed_at")
        if signed < completed - timedelta(seconds=CLOCK_SKEW_SECONDS):
            raise SigningError(
                "signed_at precedes the state's last completed cycle; "
                "refusing to attest a state from before it existed")
    expires_at = (signed + timedelta(seconds=ttl_seconds)).isoformat()
    payload = state_snapshot_payload(
        facts, signer_id=signer_id, key_id=signing_key.key_id,
        signed_at=signed_at, expires_at=expires_at, purpose=purpose,
        calibration_sha256=calibration_sha256,
        prev_snapshot_hash=prev_snapshot_hash)
    payload_hash = _payload_hash(payload)
    return SignedStateSnapshot(
        state_sha256=facts.state_sha256,
        state_schema_version=facts.schema_version,
        cycle_seq=facts.cycle_seq, history_len=facts.history_len,
        last_cycle_id=facts.last_cycle_id, last_item_id=facts.last_item_id,
        last_completed_at=facts.last_completed_at,
        calibration_sha256=calibration_sha256,
        prev_snapshot_hash=prev_snapshot_hash,
        signer_id=signer_id, key_id=signing_key.key_id, purpose=purpose,
        signed_at=payload["signed_at"], expires_at=payload["expires_at"],
        payload_hash=payload_hash,
        snapshot_id=snapshot_id_for(payload_hash, signing_key.key_id),
        signature=_mac(signing_key.key, payload_hash, signing_key.key_id))


# -- verification ---------------------------------------------------------------


def verify_signed_snapshot(signed, *, signing_key: SigningKey,
                           expected_state_bytes=None,
                           expected_calibration_bytes=None,
                           require_calibration=False,
                           expected_signer_id=None,
                           expected_purpose=PURPOSE_STATE_SNAPSHOT,
                           expected_pin=None,
                           expected_prev_snapshot_hash=None,
                           now=None) -> tuple:
    """Failure reasons for a snapshot envelope; () means authentic,
    unexpired, internally consistent, and bound as expected.

    Malformed envelopes raise SigningError; authentic-but-failing
    ones return reasons. When ``expected_state_bytes`` is supplied
    it is re-parsed and every extracted fact is compared, not just
    the hash. ``expected_pin`` is a dict ``{"cycle_seq": int,
    "payload_hash": hex64}`` naming the newest snapshot the caller
    already trusts, held outside the state directory: a snapshot
    older than the pin reports ``snapshot_rolled_back`` and one at
    the pinned sequence with a different hash reports
    ``pin_mismatch``. Without a pin, rollback is undetectable and
    this function does not claim otherwise.
    """
    if not isinstance(signed, SignedStateSnapshot):
        raise SigningError("signed must be a SignedStateSnapshot")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        return ("key_id_inconsistent",)
    reasons = []
    if signed.key_id != signing_key.key_id:
        reasons.append("unknown_key")
    try:
        payload = signed.payload()
        recomputed_hash = _payload_hash(payload)
    except (SigningError, UnicodeEncodeError, ValueError, TypeError):
        # A tampered or hand-built envelope can carry fields no
        # signer would emit (inconsistent facts, non-finite floats,
        # unserialisable types): that is a verification failure,
        # never a crash and never a pass.
        return ("malformed_payload",)
    if signed.payload_hash != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    if signed.snapshot_id != snapshot_id_for(recomputed_hash, signed.key_id):
        reasons.append("snapshot_id_mismatch")
    expected_mac = _mac(signing_key.key, recomputed_hash, signed.key_id)
    if not isinstance(signed.signature, str) \
            or not _HEX64_RE.fullmatch(signed.signature) \
            or not hmac.compare_digest(signed.signature.encode("ascii"),
                                       expected_mac.encode("ascii")):
        reasons.append("signature_mismatch")
    if expected_purpose is not None and signed.purpose != expected_purpose:
        reasons.append("purpose_mismatch")
    if expected_signer_id is not None and signed.signer_id != expected_signer_id:
        reasons.append("signer_mismatch")
    if require_calibration and not signed.calibration_sha256:
        reasons.append("calibration_unbound")
    if expected_calibration_bytes is not None:
        try:
            expected_cal_hash = calibration_hash_for(
                expected_calibration_bytes)
        except SigningError:
            reasons.append("malformed_calibration")
        else:
            if signed.calibration_sha256 != expected_cal_hash:
                reasons.append("calibration_mismatch")
    facts = None
    if expected_state_bytes is not None:
        try:
            facts = parse_state_bytes(expected_state_bytes)
        except SigningError:
            reasons.append("malformed_state")
        else:
            if (facts.state_sha256 != signed.state_sha256
                    or facts.schema_version != signed.state_schema_version
                    or facts.cycle_seq != signed.cycle_seq
                    or facts.history_len != signed.history_len
                    or facts.last_cycle_id != signed.last_cycle_id
                    or facts.last_item_id != signed.last_item_id
                    or facts.last_completed_at != signed.last_completed_at):
                reasons.append("state_mismatch")
    if facts is not None and facts.last_completed_at is not None:
        signed_at_dt = _parse_time(signed.signed_at, "signed_at")
        completed = _parse_time(facts.last_completed_at, "completed_at")
        if signed_at_dt < completed - timedelta(seconds=CLOCK_SKEW_SECONDS):
            reasons.append("signed_before_state")
    if expected_prev_snapshot_hash is not None:
        _check_hash_or_empty(expected_prev_snapshot_hash,
                             "expected previous snapshot hash")
        if signed.prev_snapshot_hash != expected_prev_snapshot_hash:
            reasons.append("prev_snapshot_mismatch")
    if expected_pin is not None:
        if not isinstance(expected_pin, dict) \
                or not set(expected_pin) <= {
                    "cycle_seq", "payload_hash", "key_id", "signer_id"} \
                or not _is_int(expected_pin.get("cycle_seq")) \
                or expected_pin["cycle_seq"] < 0 \
                or not isinstance(expected_pin.get("payload_hash"), str) \
                or not _HEX64_RE.fullmatch(expected_pin["payload_hash"]):
            raise SigningError(
                "expected_pin must be {'cycle_seq': int >= 0, "
                "'payload_hash': hex64} with optional 'key_id' / "
                "'signer_id' bindings and no other keys")
        if "key_id" in expected_pin \
                and expected_pin["key_id"] != signed.key_id:
            reasons.append("pin_mismatch")
        if "signer_id" in expected_pin \
                and expected_pin["signer_id"] != signed.signer_id:
            reasons.append("pin_mismatch")
        if signed.cycle_seq < expected_pin["cycle_seq"]:
            reasons.append("snapshot_rolled_back")
        elif signed.cycle_seq == expected_pin["cycle_seq"] \
                and recomputed_hash != expected_pin["payload_hash"]:
            reasons.append("pin_mismatch")
        elif signed.cycle_seq == expected_pin["cycle_seq"] + 1 \
                and signed.prev_snapshot_hash \
                != expected_pin["payload_hash"]:
            # The immediate successor of the pinned snapshot must
            # chain to it: this is the one continuity check a
            # single pin supports (war-room cycle 10, rev-r5 +
            # external seat). Older gaps are not chain-verified;
            # see the module docstring.
            reasons.append("chain_discontinuity")
    moment = _parse_time(_now() if now is None else now, "now")
    signed_at = _parse_time(signed.signed_at, "signed_at")
    expires_at = _parse_time(signed.expires_at, "expires_at")
    if signed_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))


# -- production-shaped wrappers -------------------------------------------------


def verify_snapshot_for_state(signed, *, signing_key: SigningKey,
                              state_bytes, calibration_bytes,
                              expected_pin, expected_signer_id,
                              now=None) -> tuple:
    """The strict verification entry point for production-shaped
    use: every binding is required — the exact state bytes, the
    exact calibration bytes, a caller-held pin and a signer pin.
    Bare ``verify_signed_snapshot`` is an envelope-only check whose
    optional expectations compare nothing when omitted (the same
    convention as ``verify_signed_decision``); consumers attesting
    a live state must use this wrapper, which is to snapshots what
    ``commit_signed``'s strong form is to gate decisions
    (war-room cycle 10, rev-r2). Chain continuity is still
    verified only for the pin's immediate successor: callers must
    advance the pin one sequence at a time, because a snapshot
    more than one sequence past the pin verifies its bindings
    here but not its chain (war-room cycle 12, rev-r2 — dissent
    preserved in internal/REVIEW-CYCLE-12.md; code-level
    enforcement is backlog item snapshot-chain-gap-enforcement)."""
    if state_bytes is None or calibration_bytes is None \
            or expected_pin is None or not expected_signer_id:
        raise SigningError(
            "verify_snapshot_for_state requires state bytes, "
            "calibration bytes, a pin and a signer pin")
    return verify_signed_snapshot(
        signed, signing_key=signing_key,
        expected_state_bytes=state_bytes,
        expected_calibration_bytes=calibration_bytes,
        require_calibration=True, expected_signer_id=expected_signer_id,
        expected_pin=expected_pin, now=now)


def sign_state_files(state_path, calibration_path=None, *,
                     signing_key: SigningKey, signer_id,
                     prev_snapshot_hash="",
                     purpose=PURPOSE_STATE_SNAPSHOT,
                     ttl_seconds=TTL_DEFAULT_SECONDS, now=None,
                     _reader=None) -> SignedStateSnapshot:
    """Sign the state (and calibration) files at two paths, with
    the cross-file consistency protocol enforced in code rather
    than left to caller discipline: read state, read calibration,
    re-read state, and refuse if the state bytes changed between
    reads. The pair attested is then one that coexisted at the
    second read, up to the calibration read racing a state write
    in the other order — the residual race is stated in the
    module docstring. ``_reader`` is a test seam only."""
    read = _reader or (lambda p: p.read_bytes())
    from pathlib import Path
    state_path = Path(state_path)
    state_first = read(state_path)
    calibration = None
    if calibration_path is not None:
        calibration = read(Path(calibration_path))
    state_second = read(state_path)
    if state_first != state_second:
        raise SigningError(
            "state file changed during snapshot capture; refusing "
            "to attest a pair that may never have coexisted")
    return sign_state_snapshot(
        state_second, signing_key=signing_key, signer_id=signer_id,
        calibration_bytes=calibration,
        prev_snapshot_hash=prev_snapshot_hash, purpose=purpose,
        ttl_seconds=ttl_seconds, now=now)


# -- envelopes ------------------------------------------------------------------

_ENVELOPE_KEYS = {
    "state_sha256", "state_schema_version", "cycle_seq", "history_len",
    "last_cycle_id", "last_item_id", "last_completed_at",
    "calibration_sha256", "prev_snapshot_hash", "signer_id", "key_id",
    "purpose", "signed_at", "expires_at", "payload_hash", "snapshot_id",
    "signature",
}


def snapshot_envelope_to_dict(signed: SignedStateSnapshot) -> dict:
    if not isinstance(signed, SignedStateSnapshot):
        raise SigningError("signed must be a SignedStateSnapshot")
    return {
        "state_sha256": signed.state_sha256,
        "state_schema_version": signed.state_schema_version,
        "cycle_seq": signed.cycle_seq,
        "history_len": signed.history_len,
        "last_cycle_id": signed.last_cycle_id,
        "last_item_id": signed.last_item_id,
        "last_completed_at": signed.last_completed_at,
        "calibration_sha256": signed.calibration_sha256,
        "prev_snapshot_hash": signed.prev_snapshot_hash,
        "signer_id": signed.signer_id, "key_id": signed.key_id,
        "purpose": signed.purpose,
        "signed_at": signed.signed_at, "expires_at": signed.expires_at,
        "payload_hash": signed.payload_hash,
        "snapshot_id": signed.snapshot_id, "signature": signed.signature,
    }


def snapshot_envelope_from_dict(data) -> SignedStateSnapshot:
    """Strict reconstruction: exact key set, no unknown fields, and
    the payload must re-derive before the envelope is usable."""
    if not isinstance(data, dict) or set(data) != _ENVELOPE_KEYS:
        raise SigningError("snapshot envelope has missing or unknown keys")
    for field in ("state_sha256", "payload_hash", "snapshot_id", "signature"):
        _check_hex64(data[field], f"envelope {field}")
    for field in ("calibration_sha256", "prev_snapshot_hash"):
        if data[field]:
            _check_hex64(data[field], f"envelope {field}")
    for field in ("state_schema_version", "cycle_seq", "history_len"):
        if not _is_int(data[field]):
            raise SigningError(f"envelope {field} must be an integer")
    if data["last_cycle_id"] is not None and not _is_int(data["last_cycle_id"]):
        raise SigningError("envelope last_cycle_id must be an integer or null")
    try:
        signed = SignedStateSnapshot(
            state_sha256=data["state_sha256"],
            state_schema_version=data["state_schema_version"],
            cycle_seq=data["cycle_seq"], history_len=data["history_len"],
            last_cycle_id=data["last_cycle_id"],
            last_item_id=data["last_item_id"],
            last_completed_at=data["last_completed_at"],
            calibration_sha256=data["calibration_sha256"],
            prev_snapshot_hash=data["prev_snapshot_hash"],
            signer_id=data["signer_id"], key_id=data["key_id"],
            purpose=data["purpose"], signed_at=data["signed_at"],
            expires_at=data["expires_at"], payload_hash=data["payload_hash"],
            snapshot_id=data["snapshot_id"], signature=data["signature"])
    except SigningError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise SigningError(f"snapshot envelope is malformed: {exc}") from exc
    signed.payload()  # validate every field before the envelope is usable
    return signed


def snapshot_envelope_to_json(signed: SignedStateSnapshot) -> str:
    return json.dumps(snapshot_envelope_to_dict(signed),
                      ensure_ascii=False, indent=2, allow_nan=False)


def snapshot_envelope_from_json(text) -> SignedStateSnapshot:
    if not isinstance(text, str):
        raise SigningError("snapshot envelope JSON must be text")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(
            f"snapshot envelope is not valid JSON: {exc}") from exc
    return snapshot_envelope_from_dict(data)


def self_test(signing_key: SigningKey, *, signer_id="self-test") -> bool:
    """Sign and verify a throwaway empty state in memory."""
    probe = json.dumps({
        "schema_version": 1, "cycle_seq": 0, "phase": "SCAN",
        "backlog": [], "history": [], "deltas": [],
        "history_pruned": 0, "deltas_pruned": 0, "current_item_id": None,
    }, sort_keys=True).encode("utf-8")
    try:
        signed = sign_state_snapshot(probe, signing_key=signing_key,
                                     signer_id=signer_id)
    except (SigningError, TypeError):
        return False
    return verify_signed_snapshot(
        signed, signing_key=signing_key, expected_state_bytes=probe,
        expected_purpose=None) == ()
