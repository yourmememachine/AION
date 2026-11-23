"""Signed ceremony authorisations (cycle 20, v2).

The pin ceremony (signing/pin_ceremony.py) re-anchors a snapshot
pin after a chain gap, a lost pin or a corrupted pin. Before
cycle 19 the ceremony took the CALLER's word for who counted
as an operator: ``reanchor_pin`` accepted an ``authorised_operators``
list from the same code that supplied the evidence — the
authority and the evidence came from one hand, which is no
authority at all. The replacement: a *ceremony authorisation*
is an Ed25519 envelope, issued by the out-of-process verifier
(trust/verifier_main.py, mode ``ceremony_authorise``) under a
ceremony seed that only the verifier holds, attesting that an
operator id named on the verifier's OWN protected configuration
(the ``AION_CEREMONY_OPERATORS`` env list, which no request can
carry) presented a specific evidence hash bound to one exact
recovery event. The ceremony consumes the envelope; it never
sees a list, and it never holds minting material — it holds
only the verifier's 32-byte public key, pinned as a
``CeremonyPublicKey``.

What "v2" means, as a conjunction: an Ed25519 signature under
the verifier's ceremony seed, over an ``evidence_hash`` the
verifier computed itself (below), under the narrowed operator
claim stated verbatim below. Cycle 19's v1 envelopes were
HMAC-signed; v2 has NO HMAC path and no dual-verify window —
the HMAC code is deleted from this module, the domain and
payload version are bumped, and a v1 envelope is refused at
parse time when it still carries its HMAC-era markers (a
``key-…`` id and/or a hex64 signature — see
``ceremony_authorisation_envelope_from_dict``). There is no
version field to check: a fully relabelled v1 envelope is
indistinguishable from a v2 forgery and dies at signature
verification instead.

Structural divergence from signing/attestation.py, stated
plainly: there the signer IS the attester. Here the signer (the
verifier) is NOT the operator — the verifier signs ABOUT the
operator's presentation. The operator holds no key and signs
nothing.

Operator identity is operator-id allowlist eligibility via the verifier's launch channel, not authentication: the verifier checks that the presented operator_id was on its configured allowlist at issuance; it does not and cannot verify that the presenter *is* that operator — no per-operator credential exists in this system, and any caller able to launch the verifier can present any listed id. The envelope proves a presentation under an allowlisted id, ledgered at issuance and bound to this event — workflow provenance, not cryptographic attribution: nothing in the envelope is evidence *by* the operator, only *about* them, and it does not prove which human or process made the presentation.

The reason allowlist below is a LOCAL MIRROR of
``signing.pin_ceremony.REASONS``. This module must NOT import
pin_ceremony (pin_ceremony imports this module to verify
envelopes — the import would be circular), so the mirror is a
copy, and a drift test pins mirror == pin_ceremony.REASONS.

Honest limits:

* Evidence: in v2, ``evidence_hash`` is DEFINED as the SHA-256
  the verifier computed over the artefact bytes it resolved
  itself, under its protected evidence root, at issuance; the
  supplied hash in the request is a cross-check only, and the
  computed hash is the one signed. That definition is
  discharged by the verifier mode, not by this signing module:
  the payload projection here is a pure function of its
  arguments and cannot distinguish a computed hash from an
  asserted one. And verifier-computed is not semantic adequacy:
  the hash proves which bytes the verifier read; it does not
  prove the artefact is genuine, complete, or appropriate
  evidence for the event. ``evidence_ref`` remains an opaque,
  caller-supplied locator string (form-checked only). What the
  envelope proves: an allowlisted operator id presented this
  evidence hash bound to this exact event, the presentation
  was ledgered single-use at issuance (see trust/ledger.py's
  CeremonyAuthorisationLedger), and the binding is signed
  under the verifier's ceremony seed. A random hex64 from a
  LISTED operator id is still issuable — it is attributable to
  that operator id as workflow provenance, bound to one event,
  and burned at issuance.
* The signature is asymmetric (Ed25519, signing/ed25519.py):
  forging an envelope requires the verifier's ceremony seed;
  a forged envelope fails verification in the consuming
  process itself, not merely on a later audit. The ceremony
  process holds only public bytes, so a fully compromised
  ceremony process yields no minting capability. Separation is
  type separation (a ``CeremonyPublicKey`` cannot hold secret
  material; a snapshot ``SigningKey`` passed as the verify key
  is a type refusal) plus role separation (minting material
  absent from the ceremony process). Seed-reuse across roles
  (a ceremony seed byte-equal to an HMAC key) is refused at
  provisioning / verifier config load — the only places both
  secrets exist; no in-process id comparison can detect it,
  and none is claimed to.
* Pure-Python Ed25519 scalar multiplication is not
  constant-time. The secret-dependent multiplications (the
  clamped secret scalar AND the deterministic-nonce scalar)
  happen only inside the verifier process, which deployment
  runs as a dedicated OS user. Verification multiplies public
  values only. See signing/ed25519.py's docstring.
* Issuance accounting is not consumption enforcement, and
  neither is anchored provenance: the (ceremony_id,
  evidence_hash) pair is burned at issuance, but a genuine
  envelope replayed within its TTL against a moved pin is a
  consumption-side problem this module does not solve. The
  protected monotonic consumption head that addresses it
  EXISTS as built in cycle 21: the verifier-owned
  ``CeremonyConsumptionLedger`` (trust/ledger.py), driven
  through the verifier's ``ceremony_consume`` mode, with
  signing/pin_ceremony.py's ``reanchor_pin`` invoking the
  required consumer before a ceremony record is constructed.
  Qualification (R5): single-use consumption is a property
  of the INTEGRATED SYSTEM under its production wiring —
  authorise via the verifier client, re-anchor with the
  verifier-backed consumer, adopt the returned pin
  atomically — not a property of this envelope, or of
  ``reanchor_pin`` for an arbitrary caller-supplied
  callable, in the abstract. See signing/pin_ceremony.py
  and trust/ledger.py for the built mechanism and its
  residuals.
* ``now=`` parameters exist for tests only; see the warning in
  gate_decision's module docstring.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from signing import ed25519
from signing.gate_decision import (
    CLOCK_SKEW_SECONDS,
    TTL_MIN_SECONDS,
    SigningError,
    _canonical,
    _check_hex64,
    _check_id,
    _check_key_path,
    _check_owner_only_mode,
    _check_text,
    _normalise_time,
    _now,
    _parse_time,
    _sha256,
)

CEREMONY_AUTHORISATION_DOMAIN = "signed-ceremony-authorisation-v2"
DOMAIN = CEREMONY_AUTHORISATION_DOMAIN
ALG_CEREMONY = "ed25519"  # payload "alg"; NOT gate_decision.ALG
PURPOSE_CEREMONY_AUTHORISATION = "pin-ceremony-authorisation"
CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS = 900
CEREMONY_AUTHORISATION_TTL_MAX_SECONDS = 900  # hard cap, see below

# Ceremony seeds that must never provision a verifier: the four
# predictable test keys, plus the RFC 8032 section 7.1 TEST 1/2/3
# seeds (public knowledge, and the exact seeds the signing test
# fixtures use). This is the single source for the refused-seed
# list: trust/verifier_main.py imports this set and refuses any
# seed in it at config load, unioned with its own local list.
REFUSED_TEST_SEEDS = frozenset({
    bytes(range(32)), bytes(range(32, 64)),
    b"\x00" * 32, b"\xff" * 32,
    bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc4"
        "4449c5697b326919703bac031cae7f60"),  # RFC 8032 TEST 1
    bytes.fromhex(
        "4ccd089b28ff96da9db6c346ec114e0f"
        "5b8a319f35aba624da8cf6ed4fb8a6fb"),  # RFC 8032 TEST 2
    bytes.fromhex(
        "c5aa8df43f9f837bedb7442f31dcb7b1"
        "66d38535076f094b85ce3a2e0b4458f7"),  # RFC 8032 TEST 3
})

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
_HEX128_RE = re.compile(r"[0-9a-f]{128}")

_OLD_PIN_KEYS = {"cycle_seq", "payload_hash"}
_CANDIDATE_KEYS = {"cycle_seq", "payload_hash", "signer_id", "key_id"}

# Sentinel for expected_old_pin in verify_ceremony_authorisation:
# omitted asserts nothing about the pin; an explicit None asserts
# the authorisation is a no-pin authorisation; a dict asserts
# exact equality. (pin_ceremony's _CONTEXT_UNSPECIFIED pattern,
# re-declared here because importing it would be circular.)
_CONTEXT_UNSPECIFIED = object()


# -- ceremony keys ----------------------------------------------------------


def public_key_id_for(public_key: bytes) -> str:
    """The public key id, derived from public bytes only, so any
    consumer can recompute it from the pinned key: "pub-" +
    sha256(public_key)[:16]. The "pub-" prefix and the hash
    input (public bytes, not secret bytes) put these ids in a
    namespace disjoint from gate_decision's "key-" ids."""
    if not isinstance(public_key, (bytes, bytearray)) \
            or len(public_key) != ed25519.PUBLIC_KEY_BYTES:
        raise SigningError(
            f"public key must be exactly "
            f"{ed25519.PUBLIC_KEY_BYTES} bytes")
    return "pub-" + _sha256(bytes(public_key))[:16]


@dataclass(frozen=True)
class CeremonySigningKey:
    """Verifier-side ONLY: the ceremony seed plus its derived
    public identity. Never logged whole: repr shows only the
    key id and a fingerprint of the public key."""

    seed: bytes
    public_key: bytes
    key_id: str

    def __repr__(self) -> str:  # never leak seed bytes into a log
        return (f"CeremonySigningKey(key_id={self.key_id!r}, "
                f"public_fingerprint={_sha256(self.public_key)!r})")


@dataclass(frozen=True)
class CeremonyPublicKey:
    """Ceremony/client-side pin: public bytes only. This type
    cannot hold secret material — that is the type separation
    the v2 key boundary rests on."""

    public_key: bytes
    key_id: str

    def __repr__(self) -> str:
        return f"CeremonyPublicKey(key_id={self.key_id!r})"


def _make_ceremony_signing_key(seed: bytes) -> CeremonySigningKey:
    if not isinstance(seed, (bytes, bytearray)) \
            or len(seed) != ed25519.SEED_BYTES:
        raise SigningError(
            f"ceremony seed must be exactly {ed25519.SEED_BYTES} "
            f"bytes")
    seed = bytes(seed)
    public_key = ed25519.public_key_from_seed(seed)
    return CeremonySigningKey(
        seed=seed, public_key=public_key,
        key_id=public_key_id_for(public_key))


def ceremony_public_key_for(
        signing_key: CeremonySigningKey) -> CeremonyPublicKey:
    """The public pin corresponding to a signing key."""
    if not isinstance(signing_key, CeremonySigningKey):
        raise SigningError(
            "signing_key must be a CeremonySigningKey")
    return CeremonyPublicKey(public_key=signing_key.public_key,
                             key_id=signing_key.key_id)


_MAX_SEED_FILE_BYTES = 1024


def load_ceremony_seed(path, *, forbidden_roots=()) -> CeremonySigningKey:
    """Load a ceremony seed file under the same discipline as
    gate_decision.load_signing_key (shared _check_key_path and,
    since cycle 21, the shared _check_owner_only_mode predicate):
    failing closed on a symlinked path component, a mode failing
    the owner-only predicate (no group/world bits, owner-read
    set — in practice 0400 or 0600; the retired "exactly 0600"
    wording no longer applies), an oversize or non-hex file,
    content that is not exactly 32 bytes, or a location inside
    this repo or a caller-named forbidden root.

    Cycle-21 fd discipline (this loader only; the gate loader's
    equivalent is the follow-up signing-key-loader-fd-hardening):
    the file is opened ONCE with O_NOFOLLOW|O_NONBLOCK, every
    property (regular file, mode, size) is checked by fstat on
    that fd, and the bytes are read bounded from the same fd —
    there is no stat-then-read gap for a swap to hide in, and a
    FIFO at the path is refused as non-regular instead of
    hanging the read. Owner-uid check (seed loader only, NOT
    applied to the gate loader): when the process euid is
    non-zero, the file must be owned by that euid; as root the
    check is vacuous and skipped."""
    target = _check_key_path(Path(path), forbidden_roots)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise SigningError(
            f"ceremony seed file is missing or unreadable: "
            f"{exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SigningError(
                "ceremony seed file is not a regular file")
        _check_owner_only_mode(info.st_mode,
                               what="ceremony seed file")
        euid = os.geteuid() if hasattr(os, "geteuid") else 0
        if euid != 0 and info.st_uid != euid:
            raise SigningError(
                "ceremony seed file is not owned by the "
                "current user")
        if info.st_size > _MAX_SEED_FILE_BYTES:
            raise SigningError(
                "ceremony seed file exceeds the size cap")
        chunks = []
        remaining = _MAX_SEED_FILE_BYTES + 1
        try:
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 4096))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError as exc:
            raise SigningError(
                f"ceremony seed file is unreadable: {exc}") from exc
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    if len(raw) > _MAX_SEED_FILE_BYTES:
        raise SigningError("ceremony seed file exceeds the size cap")
    raw = raw.strip()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SigningError(
            "ceremony seed file does not hold hex seed material") from exc
    # Exactly 64 lowercase hex chars, checked BEFORE decoding:
    # an odd-length or non-hex file must fail as SigningError,
    # never as a raw ValueError out of bytes.fromhex.
    if not _HEX64_RE.fullmatch(text):
        raise SigningError(
            "ceremony seed file does not hold lowercase hex seed "
            "material")
    seed = bytes.fromhex(text)
    if len(seed) != ed25519.SEED_BYTES:
        raise SigningError(
            f"ceremony seed file must hold exactly "
            f"{ed25519.SEED_BYTES} bytes")
    return _make_ceremony_signing_key(seed)


def generate_ceremony_key_file(path, *, forbidden_roots=()) -> CeremonySigningKey:
    """Create a new 0600 ceremony seed file with O_EXCL; refuse
    to overwrite. The file holds the lowercase hex encoding of
    exactly 32 random bytes and nothing else. Placement rules
    are gate_decision's (see _check_key_path): never inside this
    repo (always) or a caller-named forbidden root, never
    through a symlink, never in a group/world-writable dir."""
    target = _check_key_path(Path(path), forbidden_roots)
    if target.exists():
        raise SigningError(
            "ceremony seed file already exists; refusing to "
            "overwrite")
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise SigningError(
            f"cannot create ceremony seed directory: {exc}") from exc
    seed = secrets.token_bytes(ed25519.SEED_BYTES)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600)
    except OSError as exc:
        raise SigningError(
            f"cannot create ceremony seed file: {exc}") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(seed.hex().encode("ascii") + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return _make_ceremony_signing_key(seed)


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
        signed_at, expires_at, alg=ALG_CEREMONY) -> dict:
    """The exact allowlisted projection that gets signed.

    Validation here is the defence-in-depth copy of the verifier
    mode's pre-checks (the attestation_payload split): an
    authorisation for a non-ceremony movement must be
    un-issuable, not merely unusable.

    ``alg`` is pinned: the projection emits "ed25519" only, and
    any other alg value is refused here — so an envelope object
    claiming "hmac-sha256" cannot re-derive its payload at all
    and dies as malformed_payload at verification, before any
    signature checking. There is no HMAC fallback branch."""
    if alg != ALG_CEREMONY:
        raise SigningError(
            f"ceremony authorisation alg must be {ALG_CEREMONY!r}")
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
        "v": "signed-ceremony-authorisation/2",
        "alg": alg,
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
    the client, the ceremony — re-derive it key-free). Under v2
    the domain input is the v2 domain and the key id is the
    PUBLIC key id, so no secret participates in the id."""
    _check_hex64(payload_hash, "payload hash")
    _check_id(key_id, "key id")
    return _sha256(_canonical(
        {"v": CEREMONY_AUTHORISATION_DOMAIN,
         "payload_hash": payload_hash, "key_id": key_id}))


def _signed_blob(payload_hash: str, key_id: str) -> bytes:
    """The exact bytes signed by Ed25519: the v1 construction
    carried over unchanged in shape — domain, alg, key_id and
    payload_hash, newline-joined, utf-8. Only the primitive
    changed."""
    return (CEREMONY_AUTHORISATION_DOMAIN + "\n" + ALG_CEREMONY
            + "\n" + key_id + "\n" + payload_hash).encode("utf-8")


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
    # Not a wire field (the envelope dict has no alg key; the
    # payload projection carries it). It exists so a
    # hand-constructed typed envelope claiming a different alg
    # is refused at payload re-derivation (malformed_payload)
    # rather than silently re-derived as ed25519.
    alg: str = ALG_CEREMONY

    def payload(self) -> dict:
        return ceremony_authorisation_payload(
            signer_id=self.signer_id, key_id=self.key_id,
            operator_id=self.operator_id,
            ceremony_id=self.ceremony_id, reason=self.reason,
            old_pin=self.old_pin, candidate=self.candidate,
            evidence_hash=self.evidence_hash,
            evidence_ref=self.evidence_ref,
            signed_at=self.signed_at, expires_at=self.expires_at,
            alg=self.alg)


def sign_ceremony_authorisation(
        *, signing_key: CeremonySigningKey, signer_id, operator_id,
        ceremony_id, reason, old_pin, candidate, evidence_hash,
        evidence_ref,
        ttl_seconds=CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS,
        now=None) -> SignedCeremonyAuthorisation:
    """Sign one ceremony authorisation under the verifier-side
    ceremony seed (Ed25519).

    The signer is the VERIFIER, signing about the operator's
    presentation; signer_id is the verifier's id and need NOT
    equal operator_id (the one structural divergence from
    attestation.py — see the module docstring).

    TTL: default 900s with a HARD CAP — the effective ttl is
    min(ttl_seconds, 900), so a caller configured with a longer
    verifier TTL does not silently mint longer-lived ceremony
    authorisations. An authorisation is a live operator act;
    nothing in the flow has approval-workflow latency."""
    if not isinstance(signing_key, CeremonySigningKey):
        raise SigningError(
            "signing_key must be a CeremonySigningKey")
    if signing_key.key_id != public_key_id_for(signing_key.public_key) \
            or signing_key.public_key \
            != ed25519.public_key_from_seed(signing_key.seed):
        raise SigningError(
            "ceremony signing key id or public key does not match "
            "its seed material")
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
    signature = ed25519.sign(
        signing_key.seed,
        _signed_blob(payload_hash, signing_key.key_id)).hex()
    return SignedCeremonyAuthorisation(
        operator_id=operator_id, ceremony_id=ceremony_id,
        reason=reason, old_pin=payload["old_pin"],
        candidate=payload["candidate"], evidence_hash=evidence_hash,
        evidence_ref=evidence_ref, signer_id=signer_id,
        key_id=signing_key.key_id, signed_at=signed_at,
        expires_at=expires_at, payload_hash=payload_hash,
        authorisation_id=authorisation_id_for(payload_hash,
                                              signing_key.key_id),
        signature=signature)


def verify_ceremony_authorisation(
        signed, *, public_key: CeremonyPublicKey,
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

    Reason meanings under v2: ``key_id_inconsistent`` means the
    CeremonyPublicKey object lies about its own derived id
    (public_key_id_for(public_key.public_key) !=
    public_key.key_id); ``unknown_key`` means signed.key_id !=
    public_key.key_id (the envelope was not issued under the
    pinned key); ``signature_mismatch`` means Ed25519
    verification failed (including a signature that is not
    hex128 — a typed envelope can be hand-constructed, bypassing
    from_dict, so the format is re-checked here and folded into
    this reason, never raised).

    ``expected_old_pin`` uses the sentinel pattern: omitted
    asserts nothing; explicit None asserts a no-pin
    authorisation; a dict asserts exact (seq, hash) equality
    against the projected pin shape. ``expected_candidate``
    asserts exact equality of the 4-field candidate projection.

    A () result proves issuance + binding; it does NOT prove the
    operator should have been authorised (that was decided at
    issuance against the verifier's protected list) nor that the
    evidence artefact is semantically adequate (see the module
    docstring)."""
    if not isinstance(signed, SignedCeremonyAuthorisation):
        raise SigningError("signed must be a SignedCeremonyAuthorisation")
    if not isinstance(public_key, CeremonyPublicKey):
        raise SigningError("public_key must be a CeremonyPublicKey")
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
    signature_ok = False
    if isinstance(signed.signature, str) \
            and _HEX128_RE.fullmatch(signed.signature):
        signature_ok = ed25519.verify(
            public_key.public_key,
            _signed_blob(recomputed_hash, signed.key_id),
            bytes.fromhex(signed.signature))
    if not signature_ok:
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


def _looks_like_v1_envelope(data: dict) -> bool:
    """A cycle-19 (v1) envelope is identifiable by its HMAC-era
    markers: a "key-…" key id (derived from secret bytes) and/or
    a hex64 (32-byte HMAC) signature. A v2 envelope always
    carries a "pub-…" key id and a hex128 signature."""
    key_id = data.get("key_id")
    signature = data.get("signature")
    if isinstance(key_id, str) and key_id.startswith("key-"):
        return True
    if isinstance(signature, str) \
            and _HEX64_RE.fullmatch(signature):
        return True
    return False


def ceremony_authorisation_envelope_from_dict(
        data) -> SignedCeremonyAuthorisation:
    if not isinstance(data, dict) or set(data) != _ENVELOPE_KEYS:
        raise SigningError(
            "ceremony authorisation envelope has missing or "
            "unknown keys")
    # VERSION CHECK FIRST (before the hex128 format check
    # below): a superseded v1 envelope must be refused AS a
    # superseded version — naming it — not as a generic format
    # failure a future maintainer might "fix" by re-adding a v1
    # parse path. There is no v1 fallback in this build.
    if _looks_like_v1_envelope(data):
        raise SigningError(
            "ceremony authorisation version 1 "
            "(signed-ceremony-authorisation/1) is superseded and "
            "is not accepted by this build; cycle 20 requires "
            "signed-ceremony-authorisation/2")
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
                               "authorisation_id")):
        if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
            raise SigningError(f"envelope {field_name} must be hex64")
    if not isinstance(signed.signature, str) \
            or not _HEX128_RE.fullmatch(signed.signature):
        raise SigningError("envelope signature must be hex128")
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
