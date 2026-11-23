"""Signed gate decisions: MAC-authenticated gate outcomes.

No third-party dependencies (standard library plus this repo's own
eval.gate / memory.store). This package provides the strict path
that memory/store.py and oversight/approval.py point to in their
docstrings: until now a gate decision was a plain dataclass, so any
in-process code could hand-build an accepted decision and a memory
commit proved only that such an object was presented, not that the
gate ran. It does NOT by itself close that limit: the plain
commit_write path still exists and still accepts unsigned decisions,
so the limit is closed only for callers who use commit_signed()
exclusively, and fully only when a future gated change makes a store
require the envelope. Until then the signed path is a temporary,
un-enforced bypass boundary — in a self-improving system caller
discipline is the weakest link, because evolved code or a convenience
path can call commit_write directly; treat the guarantee as advisory,
not enforced. The signer_id inside the MAC is likewise a claim by the
key-holder, not an identity tied to key policy.

A signer holding the gate key wraps a GateDecision (accept OR
reject — both are signed, so a signed rejection exists as an
auditable record; note this module keeps no ledger of rejections,
so suppression of a rejection is prevented only if a caller persists
and compares signed outcomes) in a SignedGateDecision envelope. The
MAC covers every field of the decision, the FULL verifier_note
verbatim (including its first segment, the content-hash binding that
ties the decision to one exact memory entry), an optional hash of
the verifier attestation, an optional hash of the gate inputs, the
signer id, the key id, and the signing window (signed_at /
expires_at, normalised to UTC). Neither hash is required by default:
an envelope with attestation_hash="" is bound to no attestation at
all, and commit_signed(require_attestation=True) exists for callers
who must refuse that. commit_signed() verifies the envelope against
the exact entry being committed and only then calls the store's
gated commit (MemoryStore._commit_gated), which re-runs every one
of its existing checks unchanged.

Honest limits, stated plainly. This envelope is MAC-authenticated
with HMAC-SHA256. A valid tag proves only that the payload was issued
by a process holding the gate key and has not changed since. It does
not prove the scores are true, that a sealed evaluation actually ran,
that the verifier was independent, or which key-holder issued it —
HMAC is symmetric, provides no non-repudiation, and anyone holding
the key (including a process that only verifies) can forge an
envelope. The boundary is key placement, not cryptography, and key
placement is a deployment requirement this code only partly
enforces: generate/load refuse a key inside this repo by default
(caller-supplied forbidden_roots extend that), refuse symlinks in
the path, and require an owner-only, owner-readable key file
(0400 or 0600; generate creates 0600) — but make_signing_key accepts raw
bytes with no placement check at all, and a 0600 file is readable by
any code running as the same OS user, so a separate OS user (or
equivalent isolation) for the signer is REQUIRED for a boundary,
not merely ideal. If builder and signer share a user or the key is
readable by builder code, this package is tamper-evidence only.
Signing a decision object handed to the signer proves only that the
signer signed it; hashing gate inputs into gate_inputs_hash binds
those inputs but does not prove the decision corresponds to them —
a deployment that wants "the gate ran" must have the signer
recompute the decision from the raw inputs itself. Timestamps are
host-clock assertions; expiry is a staleness bound, not a trust
root. On the commit_signed path, single-use comes from the store
(proposal ids are single-use in its surviving history), not from
the envelope: verify-only callers get no single-use at all, the
same envelope commits to any number of different stores, and after
a whole-file store rollback a rolled-away proposal id is free again
and the same valid envelope replays — operationally, rollback plus
replay can resurrect previously rejected or poisoned memory states —
closing those needs the store chain head anchored outside writable
storage, as the store's own docstring states. There is NO key rotation or revocation in this
version: one key per deployment, verification takes exactly one
key, and rotating the key instantly invalidates every in-flight
envelope (TTL up to 48 hours). The key id is a 64-bit truncated
fingerprint — a label for humans, not a security identity.

One parameter warning, because it is a loaded foot-gun: every
``now=`` argument in this module exists for tests. A caller that
supplies ``now`` controls the freshness verdict — a past ``now``
resurrects expired envelopes in-process; a future one expires
everything early. The production authorising wrappers (the
verifier process, trust.shipcheck.record_ship) do not accept a
caller-supplied ``now`` at all; they read the host clock
themselves. Library and pure-check functions (verify_*,
commit_signed, trust.shipcheck.check_ship) accept ``now=`` for
tests only. Treat any production call site passing ``now=`` as a
bug.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eval.gate import GateDecision, Regression, VerifierAttestation

DOMAIN = "signed-gate-decision-v1"
ALG = "hmac-sha256"
PURPOSE_MEMORY_COMMIT = "memory-commit"
PURPOSE_SHIP = "ship"
TTL_DEFAULT_SECONDS = 900  # 15 min: proportional to gate-to-commit latency
TTL_MIN_SECONDS = 60
TTL_MAX_SECONDS = 172800  # 48 hours, the approval workflow's bound
CLOCK_SKEW_SECONDS = 300
KEY_BYTES = 32
MAX_NOTE_CHARS = 2000

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_BAD_CHARS = set("\u200b\u200c\u200d\ufeff\u202a\u202b\u202c\u202d\u202e\u2060")


class SigningError(ValueError):
    """Raised when a signing operation is refused or input is malformed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise SigningError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_hex64(value, field: str) -> str:
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise SigningError(f"{field} must be a lowercase hex64 string")
    return value


def _check_text(value, field: str, cap: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SigningError(f"{field} must be non-empty text")
    if len(value) > cap:
        raise SigningError(f"{field} exceeds {cap} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) in ("Cf", "Cs")
                or (code < 32 and ch not in "\t\n") or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise SigningError(
                f"{field} contains control or invisible characters")
    return value


def _parse_time(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SigningError(f"{field} must be an ISO timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SigningError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SigningError(f"{field} must be timezone-aware")
    return parsed


def _normalise_time(value, field: str) -> str:
    """One canonical spelling per instant (UTC isoformat), so the
    same decision at the same instant always hashes identically."""
    return _parse_time(value, field).astimezone(timezone.utc).isoformat()


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- keys -----------------------------------------------------------------


@dataclass(frozen=True)
class SigningKey:
    """Key material plus its derived identity. Never logged whole:
    repr shows only the key id and fingerprint."""

    key_id: str
    key: bytes

    def __repr__(self) -> str:  # never leak key bytes into a log line
        return f"SigningKey(key_id={self.key_id!r}, fingerprint={self.fingerprint!r})"

    @property
    def fingerprint(self) -> str:
        return _sha256(self.key)


def key_id_for(key: bytes) -> str:
    """The key id is derived from the key, so a swapped key file is
    detected by id mismatch instead of silently verifying nothing."""
    if not isinstance(key, (bytes, bytearray)) or len(key) < KEY_BYTES:
        raise SigningError(f"signing key must be at least {KEY_BYTES} bytes")
    return "key-" + _sha256(bytes(key))[:16]


def make_signing_key(key: bytes) -> SigningKey:
    # Type-check BEFORE any coercion: bytes(32) is 32 zero bytes and
    # bytes([0]*32) likewise — silently coercing an int or a list
    # would mint a publicly predictable gate key.
    if not isinstance(key, (bytes, bytearray)):
        raise SigningError("signing key must be bytes")
    key = bytes(key)
    return SigningKey(key_id=key_id_for(key), key=key)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MAX_KEY_FILE_BYTES = 1024


def _all_forbidden_roots(extra) -> tuple:
    return (_REPO_ROOT,) + tuple(extra)


def _check_owner_only_mode(mode: int, *, what: str = "key file") -> None:
    """The ONE shared key-file permission predicate (cycle 21, R9),
    used by load_signing_key here and by
    signing.ceremony_authorisation.load_ceremony_seed.

    Accept iff ALL of the following hold: NO special bits at
    all (``mode & 0o7000 == 0`` — no setuid, setgid or sticky
    bit), NO group/world bits at all (``mode & 0o077 == 0``),
    the owner-read bit is set, AND the owner-execute bit is
    clear — the accepted set is therefore literally exactly
    {0400, 0600}. (``stat.S_IMODE`` retains the special bits,
    so they must be refused explicitly: 04600 and 01600 would
    otherwise pass the permission-bit checks below.)
    0600 is what the generators create; 0400 (a read-only key file)
    is a legitimate hardened deployment and is accepted. 0200
    (write-only, no owner read) and every group/world-readable or
    -writable mode refuse. This replaces the retired "exactly
    0600" rule, which refused the more restrictive 0400 for no
    security gain."""
    perm = stat.S_IMODE(mode)
    if perm & 0o7000 or perm & 0o077 or not perm & 0o400 \
            or perm & 0o100:
        raise SigningError(
            f"{what} mode must be owner-only and owner-readable "
            f"(0400 or 0600); got {perm:04o}")


def _check_key_path(target: Path, forbidden_roots) -> Path:
    """Shared placement rules for generate/load: never inside a
    forbidden root (this repo by default), never through a symlink
    in any existing path component."""
    absolute = Path(os.path.abspath(target))
    resolved = absolute.resolve()
    for root in _all_forbidden_roots(forbidden_roots):
        root_resolved = Path(root).resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            raise SigningError(
                "key file must live outside the repo and any "
                "caller-supplied forbidden roots")
    component = absolute
    while True:
        if component.is_symlink():
            raise SigningError("key path passes through a symlink")
        if component.parent == component:
            break
        component = component.parent
    parent = absolute.parent
    if parent.exists() and parent.stat().st_mode & 0o022:
        raise SigningError(
            "key directory is group- or world-writable; the key file "
            "could be replaced regardless of its own mode")
    return absolute


def generate_key_file(path, *, forbidden_roots=()) -> SigningKey:
    """Create a new 0600 key file with O_EXCL; refuse to overwrite.

    The file holds the lowercase hex encoding of exactly 32 random
    bytes and nothing else. Placement rules (see _check_key_path):
    never inside this repo (always) or a caller-named forbidden root,
    never through a symlink, never in a group/world-writable dir.
    """
    target = _check_key_path(Path(path), forbidden_roots)
    if target.exists():
        raise SigningError("key file already exists; refusing to overwrite")
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise SigningError(f"cannot create key directory: {exc}") from exc
    key = secrets.token_bytes(KEY_BYTES)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise SigningError(f"cannot create key file: {exc}") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(key.hex().encode("ascii") + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return make_signing_key(key)


def load_signing_key(path, *, forbidden_roots=()) -> SigningKey:
    """Load a key file, failing closed on every unsafe property:
    a symlinked path component, a mode failing the shared
    owner-only predicate (_check_owner_only_mode: no group/world
    bits, owner-read set — in practice 0400 or 0600; the retired
    "exactly 0600" wording no longer applies), an oversize or
    non-hex file, content that is not exactly 32 bytes, or a
    location inside this repo or a forbidden root.

    Follow-up (cycle 21, R9): this loader still stats-then-reads
    by path. The fd discipline the ceremony seed loader gained
    this cycle (O_NOFOLLOW|O_NONBLOCK open, fstat on the fd,
    bounded fd read) is the named follow-up
    ``signing-key-loader-fd-hardening`` for THIS loader; only the
    permission predicate was widened here, as a separate
    bisectable change."""
    target = _check_key_path(Path(path), forbidden_roots)
    if not target.is_file():
        raise SigningError("key file is missing")
    _check_owner_only_mode(target.stat().st_mode, what="key file")
    try:
        if target.stat().st_size > _MAX_KEY_FILE_BYTES:
            raise SigningError("key file exceeds the size cap")
        raw = target.read_bytes().strip()
    except OSError as exc:
        raise SigningError(f"key file is unreadable: {exc}") from exc
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SigningError("key file does not hold hex key material") from exc
    if not re.fullmatch(r"[0-9a-f]+", text):
        raise SigningError("key file does not hold lowercase hex key material")
    key = bytes.fromhex(text)
    if len(key) != KEY_BYTES:
        raise SigningError(f"key file must hold exactly {KEY_BYTES} bytes")
    return make_signing_key(key)


# -- payload ----------------------------------------------------------------


def attestation_hash_for(attestation) -> str:
    """Hash of the verifier attestation a decision rests on.

    GateDecision does not carry the attestation (in particular not
    its sealed_hash), so without this a valid envelope could be
    paired with a different sealed run at presentation time.
    """
    if not isinstance(attestation, VerifierAttestation):
        raise SigningError("attestation must be a VerifierAttestation")
    _check_id(attestation.verifier_id, "attestation verifier id")
    if attestation.decision not in ("approve", "reject"):
        raise SigningError("attestation decision must be approve or reject")
    _check_hex64(attestation.sealed_hash, "attestation sealed hash")
    if not isinstance(attestation.reward_hacking_checked, bool):
        raise SigningError("attestation reward_hacking_checked must be a bool")
    _check_text(attestation.evidence_ref, "attestation evidence_ref", 2000)
    core = {
        "v": "verifier-attestation/1",
        "verifier_id": attestation.verifier_id,
        "decision": attestation.decision,
        "sealed_hash": attestation.sealed_hash,
        "reward_hacking_checked": attestation.reward_hacking_checked,
        "evidence_ref": attestation.evidence_ref,
        "attested_at": _normalise_time(attestation.attested_at,
                                       "attestation attested_at"),
    }
    return _sha256(_canonical(core))


_SUITES = ("public", "sealed", "capability")
_MAX_EXACT_INT = 2 ** 53


def _score(value, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SigningError(f"{field} must be a number")
    if isinstance(value, int) and abs(value) > _MAX_EXACT_INT:
        raise SigningError(f"{field} is not exactly representable")
    try:
        number = float(value)
    except OverflowError as exc:
        raise SigningError(f"{field} must be finite") from exc
    if not math.isfinite(number):
        raise SigningError(f"{field} must be finite")
    if number == 0.0:
        number = 0.0  # normalise -0.0: equal values, one payload
    if not (low <= number <= high):
        raise SigningError(f"{field} must be in [{low}, {high}]")
    return number


def _regression_dict(reg) -> dict:
    if not isinstance(reg, Regression):
        raise SigningError("regressions must be Regression entries")
    if reg.suite not in _SUITES:
        raise SigningError("regression suite is unknown")
    _check_id(reg.benchmark_id, "regression benchmark id")
    return {
        "suite": reg.suite,
        "benchmark_id": reg.benchmark_id,
        "baseline": _score(reg.baseline, "regression baseline", 0.0, 1.0),
        "candidate": _score(reg.candidate, "regression candidate", 0.0, 1.0),
        "delta": _score(reg.delta, "regression delta", -1.0, 1.0),
    }


def _as_list(values, field: str) -> list:
    if not isinstance(values, (list, tuple)):
        raise SigningError(f"{field} must be a list")
    return list(values)


def _check_id_list(values, field: str) -> list:
    return [_check_id(v, f"{field} entry")
            for v in _as_list(values, field)]


def decision_payload(decision, *, signer_id, key_id, signed_at, expires_at,
                     purpose=PURPOSE_MEMORY_COMMIT, attestation_hash="",
                     gate_inputs_hash="") -> dict:
    """The exact allowlisted projection that gets MACed. Every
    GateDecision field is present; there is no subset signing."""
    if not isinstance(decision, GateDecision):
        raise SigningError("decision must be a GateDecision")
    _check_id(signer_id, "signer id")
    _check_id(key_id, "key id")
    _check_id(purpose, "purpose")
    if decision.accepted is not True and decision.accepted is not False:
        raise SigningError("decision accepted flag must be a bool")
    _check_id(decision.proposal_id, "proposal id")
    if decision.verifier_id is not None:
        _check_id(decision.verifier_id, "verifier id")
    note = decision.verifier_note
    if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS:
        raise SigningError("verifier_note must be text of bounded length")
    if note:
        _check_text(note, "verifier_note", MAX_NOTE_CHARS)
        first = note.split(";", 1)[0]
        if first.strip().startswith("content-hash:") and (
                first != first.strip()
                or not re.fullmatch(r"content-hash:[0-9a-f]{64}", first)):
            raise SigningError(
                "verifier_note binding segment must be exactly "
                "content-hash:<hex64> with no surrounding whitespace")
    if attestation_hash:
        _check_hex64(attestation_hash, "attestation hash")
    if gate_inputs_hash:
        _check_hex64(gate_inputs_hash, "gate inputs hash")
    if not isinstance(decision.regressions, (list, tuple)) or \
            not isinstance(decision.forgetting_failures, (list, tuple)):
        raise SigningError("regressions and forgetting_failures must be lists")
    signed = _parse_time(signed_at, "signed_at")
    expiry = _parse_time(expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= expiry - signed
            <= timedelta(seconds=TTL_MAX_SECONDS)):
        raise SigningError("signing window outside the TTL bounds")
    return {
        "v": "signed-gate-decision/1",
        "alg": ALG,
        "purpose": purpose,
        "signer_id": signer_id,
        "key_id": key_id,
        "accepted": decision.accepted,
        "proposal_id": decision.proposal_id,
        "reasons": _check_id_list(decision.reasons, "reasons"),
        "regressions": [_regression_dict(r) for r in decision.regressions],
        "forgetting_failures": [
            _regression_dict(r) for r in decision.forgetting_failures],
        "protected_violations": [
            _check_text(v, "protected_violations entry", 500)
            for v in _as_list(decision.protected_violations,
                              "protected_violations")],
        "verifier_id": decision.verifier_id,
        "evaluated_at": _normalise_time(decision.evaluated_at,
                                         "evaluated_at"),
        "verifier_note": note,
        "attestation_hash": attestation_hash,
        "gate_inputs_hash": gate_inputs_hash,
        "signed_at": _normalise_time(signed_at, "signed_at"),
        "expires_at": _normalise_time(expires_at, "expires_at"),
    }


def payload_hash_for(payload: dict) -> str:
    return _sha256(_canonical(payload))


def decision_id_for(payload_hash: str, key_id: str) -> str:
    return _sha256(_canonical(
        {"v": DOMAIN, "payload_hash": payload_hash, "key_id": key_id}))


def _mac(key: bytes, payload_hash: str, key_id: str) -> str:
    blob = (DOMAIN + "\n" + ALG + "\n" + key_id + "\n"
            + payload_hash).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SignedGateDecision:
    decision: GateDecision
    signer_id: str
    key_id: str
    purpose: str
    attestation_hash: str
    gate_inputs_hash: str
    signed_at: str
    expires_at: str
    payload_hash: str
    decision_id: str
    signature: str

    def payload(self) -> dict:
        return decision_payload(
            self.decision, signer_id=self.signer_id, key_id=self.key_id,
            signed_at=self.signed_at, expires_at=self.expires_at,
            purpose=self.purpose, attestation_hash=self.attestation_hash,
            gate_inputs_hash=self.gate_inputs_hash)


def sign_gate_decision(decision, *, signing_key: SigningKey, signer_id,
                       attestation=None, gate_inputs_hash="",
                       purpose=PURPOSE_MEMORY_COMMIT,
                       ttl_seconds=TTL_DEFAULT_SECONDS, now=None,
                       signed_attestation=None) -> SignedGateDecision:
    """MAC one gate decision (accept or reject) under the gate key.

    The signer is trusted to pass the decision the gate actually
    produced; see the module docstring on recomputation.

    signed_attestation (signing.attestation.SignedAttestation) is the
    provenance-strong way to bind the verifier's attestation: when
    given, it is itself verified under the same key first, and the
    decision's attestation_hash becomes the attestation envelope's
    payload hash — so the bound hash names an artefact a key holder
    actually issued, not merely a hash of a caller-supplied object.
    If attestation is also given it must be field-equal to the
    attestation the signed attestation wraps (dataclass equality,
    not object identity).
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
    attestation_hash = (attestation_hash_for(attestation)
                        if attestation is not None else "")
    if signed_attestation is not None:
        from signing.attestation import verify_signed_attestation
        if attestation is not None \
                and signed_attestation.attestation != attestation:
            raise SigningError(
                "signed_attestation wraps a different attestation "
                "than the one presented")
        if purpose == PURPOSE_MEMORY_COMMIT \
                and signed_attestation.manifest_hash:
            raise SigningError(
                "a manifest-bound attestation cannot support a "
                "memory-commit decision; artifact bindings belong "
                "to ship decisions")
        reasons = verify_signed_attestation(
            signed_attestation, signing_key=signing_key,
            expected_proposal_id=decision.proposal_id, now=signed_at)
        if reasons:
            raise SigningError(
                "signed attestation failed verification: " + reasons[0])
        if _parse_time(signed_attestation.expires_at, "expires_at") \
                > _parse_time(expires_at, "expires_at"):
            raise SigningError(
                "signed attestation outlives the decision it would "
                "support; refusing to mint a dead pair")
        attestation_hash = signed_attestation.payload_hash
    payload = decision_payload(
        decision, signer_id=signer_id, key_id=signing_key.key_id,
        signed_at=signed_at, expires_at=expires_at, purpose=purpose,
        attestation_hash=attestation_hash, gate_inputs_hash=gate_inputs_hash)
    payload_hash = payload_hash_for(payload)
    return SignedGateDecision(
        decision=decision, signer_id=signer_id, key_id=signing_key.key_id,
        purpose=purpose, attestation_hash=attestation_hash,
        gate_inputs_hash=gate_inputs_hash, signed_at=signed_at,
        expires_at=expires_at, payload_hash=payload_hash,
        decision_id=decision_id_for(payload_hash, signing_key.key_id),
        signature=_mac(signing_key.key, payload_hash, signing_key.key_id))


# -- verification -----------------------------------------------------------


def verify_signed_decision(signed, *, signing_key: SigningKey,
                           expected_proposal_id=None,
                           expected_purpose=PURPOSE_MEMORY_COMMIT,
                           expected_entry_content_hash=None,
                           expected_attestation_hash=None,
                           expected_gate_inputs_hash=None,
                           expected_signer_id=None,
                           now=None) -> tuple:
    """Failure reasons for an envelope; () means it is authentic,
    unexpired, internally consistent, and bound as expected.
    Malformed envelopes raise SigningError; authentic-but-failing
    ones return reasons. A () result proves the envelope is genuine
    and consistent — it does NOT by itself authorise a commit: the
    store's checks (verifier-vs-entry, slot state, single-use) run
    only inside the store's gated commit, reached via commit_signed.

    expected_entry_content_hash is the memory entry's content hash:
    when supplied, the decision's verifier_note must carry it as its
    first segment (the store's binding) AND that segment must be the
    one inside the MACed note — a note swapped after signing fails
    the MAC first, and a genuinely signed decision for another entry
    fails here.
    """
    if not isinstance(signed, SignedGateDecision):
        raise SigningError("signed must be a SignedGateDecision")
    if not isinstance(signing_key, SigningKey):
        raise SigningError("signing_key must be a SigningKey")
    if signing_key.key_id != key_id_for(signing_key.key):
        return ("key_id_inconsistent",)
    reasons = []
    if signed.key_id != signing_key.key_id:
        reasons.append("unknown_key")
    try:
        payload = signed.payload()  # re-derived from the decision fields
    except (SigningError, UnicodeEncodeError):
        # A tampered envelope can carry fields no signer would emit
        # (e.g. an extended expiry outside the TTL bounds): that is a
        # verification failure, not a caller bug, so report it as a
        # reason instead of raising.
        return ("malformed_payload",)
    recomputed_hash = payload_hash_for(payload)
    if signed.payload_hash != recomputed_hash:
        reasons.append("payload_hash_mismatch")
    if signed.decision_id != decision_id_for(recomputed_hash, signed.key_id):
        reasons.append("decision_id_mismatch")
    expected_mac = _mac(signing_key.key, recomputed_hash, signed.key_id)
    if not isinstance(signed.signature, str) \
            or not _HEX64_RE.fullmatch(signed.signature) \
            or not hmac.compare_digest(signed.signature.encode("ascii"),
                                       expected_mac.encode("ascii")):
        reasons.append("signature_mismatch")
    if signed.decision.accepted is True and (
            signed.decision.reasons or signed.decision.regressions
            or signed.decision.forgetting_failures
            or signed.decision.protected_violations):
        reasons.append("inconsistent_decision")
    if expected_purpose is not None and signed.purpose != expected_purpose:
        reasons.append("purpose_mismatch")
    if expected_proposal_id is not None \
            and signed.decision.proposal_id != expected_proposal_id:
        reasons.append("proposal_mismatch")
    if expected_signer_id is not None and signed.signer_id != expected_signer_id:
        reasons.append("signer_mismatch")
    if expected_attestation_hash is not None \
            and signed.attestation_hash != expected_attestation_hash:
        reasons.append("attestation_mismatch")
    if expected_gate_inputs_hash is not None \
            and signed.gate_inputs_hash != expected_gate_inputs_hash:
        reasons.append("gate_inputs_mismatch")
    if expected_entry_content_hash is not None:
        _check_hex64(expected_entry_content_hash, "entry content hash")
        note = signed.decision.verifier_note
        first = note.split(";", 1)[0].strip() if isinstance(note, str) else ""
        if first != f"content-hash:{expected_entry_content_hash}":
            reasons.append("entry_binding_mismatch")
    moment = _parse_time(_now() if now is None else now, "now")
    signed_at = _parse_time(signed.signed_at, "signed_at")
    expires_at = _parse_time(signed.expires_at, "expires_at")
    if signed_at > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
        reasons.append("signed_in_future")
    if moment >= expires_at:
        reasons.append("expired")
    return tuple(dict.fromkeys(reasons))


def require_accepted(signed) -> None:
    """Raise SigningError unless the envelope's decision is a clean
    accept: accepted is True and reasons, regressions, forgetting
    failures and protected violations are all empty.

    verify_signed_decision returning () proves an envelope is
    genuine — it does NOT prove the decision accepted anything (a
    signed rejection verifies clean). Every consumer that treats an
    envelope as an authorisation must call this (or check the same
    fields) itself: commit_signed calls it; trust.shipcheck
    performs the equivalent checks inline and reports them as
    refusal reasons.
    """
    if not isinstance(signed, SignedGateDecision):
        raise SigningError("signed must be a SignedGateDecision")
    decision = signed.decision
    if decision.accepted is not True:
        raise SigningError("signed gate decision did not accept")
    if decision.reasons or decision.regressions \
            or decision.forgetting_failures \
            or decision.protected_violations:
        raise SigningError(
            "signed gate decision is not a clean accept: it carries "
            "reasons, regressions, forgetting failures or protected "
            "violations")


def commit_signed(store, entry_fields, signed, *, signing_key: SigningKey,
                  require_attestation=False, expected_signer_id=None,
                  now=None, signed_attestation=None,
                  expected_state_digest=None) -> dict:
    """Strict memory commit: verify the envelope against this exact
    entry, then delegate to the store's gated commit.

    Raises SigningError (persisting nothing) on any verification
    failure; MemoryError from the store propagates unchanged. With
    require_attestation=True an envelope whose attestation_hash is
    empty is refused. That alone only proves the decision was bound
    to *some* attestation-shaped object at sign time; the strong
    form passes signed_attestation (the SignedAttestation envelope
    itself): it is verified under the same key, its payload hash
    must equal the decision's attestation_hash, its inner
    attestation must say "approve" with the reward-hacking check
    done, and it must not outlive the decision (nested expiry: the
    effective expiry of the pair is the earlier of the two).
    Callers choose the strength: with the defaults
    (signed_attestation=None, require_attestation=False) this
    function enforces neither — the verifier's sanctioned flow
    always presents a signed attestation for its accepts (its
    gate mode refuses to issue one without), and production
    callers of commit_signed should pass signed_attestation and
    require_attestation=True.

    The ``now`` parameter is a test seam only: a caller passing
    it controls the freshness verdict (a past ``now`` resurrects
    expired envelopes in-process). Production callers must not
    pass it; the production wrappers (the verifier process,
    trust.shipcheck.record_ship) never accept one.

    The commit itself goes through the store's _commit_gated, so a
    store constructed with signed_only=True accepts this path while
    refusing plain commit_write calls. On such a store the gated
    commit additionally demands a one-shot permit: this function
    mints it (via the store's _mint_signed_commit_permit, bound to
    this entry's content hash and that store instance) only after
    every verification above has passed, and the store consumes it
    on use — a direct _commit_gated call presenting only a
    hand-built GateDecision is refused on a signed store. There
    is deliberately no fallback to the plain commit path: a store
    without the gated
    commit is refused, and commit_signed bypasses any commit_write
    override by design (validation belongs in the gate path or in
    _commit_gated, not in commit_write subclasses).

    expected_state_digest (cycle 8, from the cycle-7 external
    review): when supplied, it is handed to the store's gated
    commit, which compares it against the store's current state
    digest under the same lock hold as the mutation (a mismatch
    raises the store's MemoryError) — the envelope then proves not
    only the entry payload but the store state the decision was
    made against, closing the decide-to-commit TOCTOU including
    the concurrent-commit race. It is optional because it
    serialises commits: any intervening commit, even a legitimate
    one, moves the digest.
    """
    from memory.store import content_hash_for

    if not isinstance(signed, SignedGateDecision):
        raise SigningError("signed must be a SignedGateDecision")
    if not isinstance(entry_fields, dict):
        raise SigningError("entry_fields must be an object")
    proposal_id = entry_fields.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise SigningError("entry_fields must carry a proposal_id")
    if require_attestation and not signed.attestation_hash:
        raise SigningError(
            "signed gate decision is bound to no attestation")
    if signed_attestation is not None:
        from signing.attestation import verify_signed_attestation
        if signed_attestation.manifest_hash:
            raise SigningError(
                "signed attestation is bound to a build artifact; "
                "it cannot authorise a memory commit")
        reasons = verify_signed_attestation(
            signed_attestation, signing_key=signing_key,
            expected_proposal_id=proposal_id, now=now)
        if reasons:
            raise SigningError(
                "signed attestation failed verification: " + reasons[0])
        if signed_attestation.payload_hash != signed.attestation_hash:
            raise SigningError(
                "signed attestation does not match the decision's "
                "attestation_hash")
        inner = signed_attestation.attestation
        if inner.decision != "approve" \
                or inner.reward_hacking_checked is not True:
            raise SigningError(
                "signed attestation does not approve this write")
        if _parse_time(signed_attestation.expires_at, "expires_at") \
                > _parse_time(signed.expires_at, "expires_at"):
            raise SigningError(
                "signed attestation outlives the decision it supports")
    reasons = verify_signed_decision(
        signed, signing_key=signing_key,
        expected_proposal_id=proposal_id,
        expected_entry_content_hash=content_hash_for(entry_fields),
        expected_signer_id=expected_signer_id,
        now=now)
    if reasons:
        raise SigningError(
            "signed gate decision failed verification: " + reasons[0])
    require_accepted(signed)
    if not hasattr(store, "_commit_gated"):
        raise SigningError(
            "store does not expose the gated commit; commit_signed "
            "requires a MemoryStore (cycle-8 delegation is by the "
            "store's _commit_gated, never the plain commit_write)")
    # Permit handshake (Trust Boundary v2 fix round, CRITICAL-1):
    # on a signed_only store the gated commit refuses anything
    # presented without a one-shot permit, so — only now, AFTER
    # the envelope MAC and any presented attestation have verified
    # and the decision has been required to be a clean accept —
    # mint the permit bound to this exact entry's content hash and
    # hand it to the store with the commit. A forged or absent
    # envelope never reaches this line, so no permit ever exists
    # for it. Unsigned stores take no permit and are unchanged.
    permit = None
    if getattr(store, "signed_only", False):
        if not hasattr(store, "_mint_signed_commit_permit"):
            raise SigningError(
                "signed_only store does not expose the signed-commit "
                "permit mint; refusing to commit without the permit "
                "handshake")
        permit = store._mint_signed_commit_permit(
            content_hash_for(entry_fields))
    # Direct attribute call, deliberately: the trust lint watches
    # _commit_gated call sites, and a getattr indirection would
    # be invisible to it.
    return store._commit_gated(
        entry_fields, signed.decision,
        expected_state_digest=expected_state_digest, permit=permit)


# -- serialisation ------------------------------------------------------------

_ENVELOPE_KEYS = {"decision", "signer_id", "key_id", "purpose",
                  "attestation_hash", "gate_inputs_hash", "signed_at",
                  "expires_at", "payload_hash", "decision_id", "signature"}
_DECISION_KEYS = {"accepted", "proposal_id", "reasons", "regressions",
                  "forgetting_failures", "verifier_id", "evaluated_at",
                  "protected_violations", "verifier_note"}


def _regression_from(data) -> Regression:
    if not isinstance(data, dict) or set(data) != {
            "suite", "benchmark_id", "baseline", "candidate", "delta"}:
        raise SigningError("regression entry has missing or unknown keys")
    for name in ("baseline", "candidate", "delta"):
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SigningError(f"regression {name} must be a number")
    return Regression(suite=data["suite"], benchmark_id=data["benchmark_id"],
                      baseline=data["baseline"], candidate=data["candidate"],
                      delta=data["delta"])


def _str_list(value, field: str) -> list:
    if not isinstance(value, list):
        raise SigningError(f"{field} must be a list")
    return value


def envelope_to_dict(signed: SignedGateDecision) -> dict:
    if not isinstance(signed, SignedGateDecision):
        raise SigningError("signed must be a SignedGateDecision")
    d = signed.decision
    return {
        "decision": {
            "accepted": d.accepted, "proposal_id": d.proposal_id,
            "reasons": list(d.reasons),
            "regressions": [_regression_dict(r) for r in d.regressions],
            "forgetting_failures": [
                _regression_dict(r) for r in d.forgetting_failures],
            "verifier_id": d.verifier_id, "evaluated_at": d.evaluated_at,
            "protected_violations": list(d.protected_violations),
            "verifier_note": d.verifier_note,
        },
        "signer_id": signed.signer_id, "key_id": signed.key_id,
        "purpose": signed.purpose,
        "attestation_hash": signed.attestation_hash,
        "gate_inputs_hash": signed.gate_inputs_hash,
        "signed_at": signed.signed_at, "expires_at": signed.expires_at,
        "payload_hash": signed.payload_hash,
        "decision_id": signed.decision_id, "signature": signed.signature,
    }


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SigningError(f"duplicate key in envelope: {key}")
        out[key] = value
    return out


def _reject_constant(value):
    raise SigningError(f"non-finite number in envelope: {value}")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise SigningError(f"non-finite number in envelope: {text}")
    return value


def envelope_from_dict(data) -> SignedGateDecision:
    """Strict reconstruction: exact key sets, no unknown fields."""
    if not isinstance(data, dict) or set(data) != _ENVELOPE_KEYS:
        raise SigningError("envelope has missing or unknown keys")
    raw = data["decision"]
    if not isinstance(raw, dict) or set(raw) != _DECISION_KEYS:
        raise SigningError("envelope decision has missing or unknown keys")
    for field in ("payload_hash", "decision_id", "signature"):
        _check_hex64(data[field], f"envelope {field}")
    try:
        decision = GateDecision(
            accepted=raw["accepted"], proposal_id=raw["proposal_id"],
            reasons=tuple(_str_list(raw["reasons"], "reasons")),
            regressions=tuple(_regression_from(r) for r in
                              _str_list(raw["regressions"], "regressions")),
            forgetting_failures=tuple(
                _regression_from(r) for r in _str_list(
                    raw["forgetting_failures"], "forgetting_failures")),
            verifier_id=raw["verifier_id"], evaluated_at=raw["evaluated_at"],
            protected_violations=tuple(_str_list(
                raw["protected_violations"], "protected_violations")),
            verifier_note=raw["verifier_note"])
        signed = SignedGateDecision(
            decision=decision, signer_id=data["signer_id"],
            key_id=data["key_id"], purpose=data["purpose"],
            attestation_hash=data["attestation_hash"],
            gate_inputs_hash=data["gate_inputs_hash"],
            signed_at=data["signed_at"], expires_at=data["expires_at"],
            payload_hash=data["payload_hash"], decision_id=data["decision_id"],
            signature=data["signature"])
    except SigningError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise SigningError(f"envelope is malformed: {exc}") from exc
    signed.payload()  # validate every field before the envelope is usable
    return signed


def envelope_to_json(signed: SignedGateDecision) -> str:
    return json.dumps(envelope_to_dict(signed), ensure_ascii=False,
                      indent=2, allow_nan=False)


def envelope_from_json(text) -> SignedGateDecision:
    if not isinstance(text, str):
        raise SigningError("envelope JSON must be text")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(f"envelope is not valid JSON: {exc}") from exc
    return envelope_from_dict(data)


def self_test(signing_key: SigningKey, *, signer_id="self-test") -> bool:
    """Sign and verify a throwaway decision in memory (no store, no
    proposal burned) so an operator can confirm signing works."""
    probe = GateDecision(
        accepted=False, proposal_id="self-test", reasons=("probe",),
        regressions=(), forgetting_failures=(), verifier_id=None,
        evaluated_at=_now(), protected_violations=(), verifier_note="")
    try:
        signed = sign_gate_decision(probe, signing_key=signing_key,
                                    signer_id=signer_id)
    except (SigningError, TypeError):
        return False
    return verify_signed_decision(signed, signing_key=signing_key,
                                  expected_purpose=None) == ()
