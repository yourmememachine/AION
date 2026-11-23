"""The first production adopter of ``reanchor_pin`` (cycle 22,
workstream 3; design C §3, DESIGN-FINAL R3).

``PinAdopter`` owns the loop/storage layer's snapshot pin: it
captures the pin + complete ceremony history fresh from a
``signing.pin_store.PinStore`` on every attempt, snapshots the
loop's state + calibration bytes as one consistent pair, and
either advances the pin (the dense, normal path) or runs the
pin ceremony (the exceptional path) and adopts the returned
pin + record atomically through the store. It never writes the
pin store except through ``PinStore.adopt``, never touches the
loop's state or calibration files (it reads bytes and attests
them; state mutation stays the loop's), and never retries a
consume, an authorise or an adopt automatically.

Reason selection (DESIGN-FINAL R3): the ceremony reason is
COMPUTED, never hard-coded per call site. When the
pending-adoption journal shows an unadopted burn for the SAME
candidate (same seq + hash) and the same old pin, the recovery
ceremony uses ``burned_unadopted`` (with-pin: the strict
``("chain_gap",)`` reasons are passed; no-pin: ``None``);
otherwise the honest primary reason (``chain_gap_recovery`` /
``initial_anchor``). ``lost_pin`` is never selected for an
unmoved pin. Because a recovery candidate must be the burned
candidate itself (same seq + hash — the verifier's
``match_head_burn`` binds exactly that), the pending journal's
``authorised`` line retains the candidate snapshot envelope so
a later attempt can re-present the identical candidate instead
of re-signing a same-sequence snapshot with a different hash
(which the consumption head would refuse as a fork). The
retained envelope is a detection aid only: it is fully
re-verified against the current state/calibration bytes on
every attempt, exactly like a freshly signed candidate.

The ``already_current`` outcome is reachable only within
the retained envelope's TTL: it depends on re-presenting
the retained candidate envelope, and once that envelope
has expired a repeat attempt on unchanged state fails
closed (an integrity refusal) rather than reporting
``already_current``.

No ``now=`` parameter anywhere in this flow: freshness stays
on the host clock (the ``commit_production`` precedent).

Honest scope: production code exercised end-to-end in temp
dirs against the real verifier subprocess, and, since cycle 23,
in a live run against a byte copy of the real state/ directory
(seq 13 → 16, two consumptions) in a sandbox under a
production-mode verifier home. The real state/ directory itself
has never been adopted against and is not advanced by any of
this; there is no production deployment (no separate OS user;
the wrapper launch is refused by design).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from signing.ceremony_authorisation import (
    CeremonyPublicKey,
    ceremony_authorisation_envelope_from_dict,
)
from signing.gate_decision import SigningError, load_signing_key
from signing.pin_ceremony import (
    PinCeremonyRecord,
    advance_pin,
    classify_verification,
    reanchor_pin,
)
from signing.pin_store import PinStore, PinStoreError
from signing.state_snapshot import (
    parse_state_bytes,
    sign_state_snapshot,
    snapshot_envelope_from_dict,
    snapshot_envelope_to_dict,
    verify_signed_snapshot,
    verify_snapshot_for_state,
)
from trust.wiring import production_client

REASON_INITIAL_ANCHOR = "initial_anchor"
REASON_CHAIN_GAP_RECOVERY = "chain_gap_recovery"
REASON_BURNED_UNADOPTED = "burned_unadopted"

PENDING_JOURNAL_FILENAME = "adoption-pending.jsonl"

_PIN_ENV_VARS = (
    "AION_PIN_DIR", "AION_PIN_SIGNING_KEY_PATH", "AION_PIN_SIGNER_ID",
    "AION_PIN_OPERATOR_ID", "AION_PIN_EVIDENCE_DIR",
)
_PIN_PATH_VARS = (
    "AION_PIN_DIR", "AION_PIN_SIGNING_KEY_PATH", "AION_PIN_EVIDENCE_DIR",
)


@dataclass(frozen=True)
class PinAdopterConfig:
    state_path: Path            # <state_dir>/state.json
    calibration_path: Path      # <state_dir>/calibration/calibration.json
    pin_dir: Path               # outside state_dir (enforced by PinStore)
    snapshot_signer_id: str     # signer_id for sign_state_snapshot
    expected_snapshot_signer_id: str  # pin for verify (== snapshot_signer_id
    # in this deployment; kept separate because verify-side pinning is
    # the wrapper's contract)
    operator_id: str            # presented to ceremony_authorise
    expected_verifier_signer_id: str  # envelope signer pin
    evidence_dir: Path          # == verifier's AION_CEREMONY_EVIDENCE_DIR


@dataclass(frozen=True)
class PinAdopterEnv:
    """The adopter-specific env values (``pin_adopter_config_from_env``)."""
    pin_dir: Path
    signing_key_path: Path
    snapshot_signer_id: str
    operator_id: str
    evidence_dir: Path


@dataclass(frozen=True)
class AdoptionResult:
    outcome: str            # "advanced" | "reanchored" | "already_current"
    pin: dict               # the pin now in force
    record: PinCeremonyRecord | None   # set iff outcome == "reanchored"


class PinAdoptionRefused(SigningError):
    """Integrity failure / store refusal: nothing persisted."""


class PinAdoptionBurned(SigningError):
    """Consume committed (or may have committed), adoption did
    not complete. The pair ``reanchor_pin`` returned — if it
    returned — is attached, so the caller can adopt it via
    ``adopt_returned`` without a new ceremony. On a
    ``PinMovedError`` the pair is still attached, but retrying
    its adoption will keep failing CAS until an operator
    reconciles: the burn is real, and the movement belongs to
    whoever moved the pin first."""

    def __init__(self, message, *, returned_pin=None, returned_record=None):
        super().__init__(message)
        self.returned_pin = returned_pin
        self.returned_record = returned_record
        self.cycle_entry = None


def _env_refusal(variable: str, problem: str):
    raise SigningError(f"{variable}: {problem}")


def pin_adopter_config_from_env(mapping) -> PinAdopterEnv:
    """Read the adopter-specific ``AION_PIN_*`` variables from a
    mapping, in the wiring idiom: validate a copy; refusals name
    the variable and never carry its value. These are ADOPTER
    variables, deliberately NOT part of wiring's verifier
    allowlist — the verifier must never see them."""
    if not hasattr(mapping, "get"):
        raise SigningError("pin adopter env: must be a mapping")
    env = dict(mapping)
    for name in _PIN_ENV_VARS:
        value = env.get(name)
        if not isinstance(value, str) or not value.strip():
            _env_refusal(
                name, "required for the pin adopter and must be "
                "non-empty")
    for name in _PIN_PATH_VARS:
        if not Path(env[name]).is_absolute():
            _env_refusal(name, "must be an absolute path")
    return PinAdopterEnv(
        pin_dir=Path(env["AION_PIN_DIR"]),
        signing_key_path=Path(env["AION_PIN_SIGNING_KEY_PATH"]),
        snapshot_signer_id=env["AION_PIN_SIGNER_ID"],
        operator_id=env["AION_PIN_OPERATOR_ID"],
        evidence_dir=Path(env["AION_PIN_EVIDENCE_DIR"]))


def build_pin_adopter(env, *, expected_signer_id, expected_key_id,
                      authorisation_public_key, signing_key_path,
                      config) -> "PinAdopter":
    """The production factory, in the ``production_client``
    idiom: the verifier client is built ONLY via
    ``trust.wiring.production_client``; the pins are out-of-band
    arguments; the snapshot signing key is loaded outside both
    the state dir and the pin dir."""
    if not isinstance(config, PinAdopterConfig):
        raise SigningError("config must be a PinAdopterConfig")
    if config.expected_verifier_signer_id != expected_signer_id:
        raise SigningError(
            "expected_verifier_signer_id: the config's verifier "
            "signer pin does not match the out-of-band "
            "expected_signer_id; refusing rather than pinning to "
            "whatever the config asserts")
    if not isinstance(config.operator_id, str) \
            or not config.operator_id.strip():
        raise SigningError(
            "AION_PIN_OPERATOR_ID: an operator id is required "
            "for the pin adopter and must be non-empty")
    # Evidence-dir mismatch refusal: in the local deployment
    # shape the adopter places evidence where the verifier
    # resolves it; a visible mismatch refuses here rather than
    # failing issuance later with ceremony_evidence_unresolvable.
    verifier_evidence = env.get("AION_CEREMONY_EVIDENCE_DIR") \
        if hasattr(env, "get") else None
    if verifier_evidence:
        if Path(verifier_evidence).resolve() \
                != Path(config.evidence_dir).resolve():
            raise SigningError(
                "AION_PIN_EVIDENCE_DIR: the adopter evidence dir "
                "does not resolve equal to the verifier's "
                "AION_CEREMONY_EVIDENCE_DIR; refusing a mismatch "
                "that would fail issuance later")
    client = production_client(
        env, expected_signer_id=expected_signer_id,
        expected_key_id=expected_key_id,
        authorisation_public_key=authorisation_public_key)
    state_dir = Path(config.state_path).parent
    store = PinStore(config.pin_dir, state_dir=state_dir)
    signing_key = load_signing_key(
        signing_key_path,
        forbidden_roots=(state_dir, Path(config.pin_dir)))
    return PinAdopter(client=client, store=store,
                      signing_key=signing_key, config=config,
                      authorisation_public_key=authorisation_public_key)


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    """The loop.save() write discipline, for evidence bundles:
    a half-written artefact must never be the bytes the
    verifier hashes."""
    fd, tmp = tempfile.mkstemp(dir=path.parent,
                               prefix=".pin-evidence-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PinAdopter:
    """The full production flow. Construct via
    ``build_pin_adopter`` in production; tests may construct it
    around a directly built client (the R12 pattern)."""

    def __init__(self, *, client, store, signing_key, config,
                 authorisation_public_key):
        if not isinstance(config, PinAdopterConfig):
            raise SigningError("config must be a PinAdopterConfig")
        if not isinstance(authorisation_public_key, CeremonyPublicKey):
            raise SigningError(
                "authorisation_public_key must be a "
                "CeremonyPublicKey supplied out-of-band")
        if not isinstance(config.operator_id, str) \
                or not config.operator_id.strip():
            raise SigningError(
                "operator_id: an operator id is required and "
                "must be non-empty")
        self._client = client
        self._store = store
        self._key = signing_key
        self._config = config
        self._pub = authorisation_public_key

    @property
    def store(self) -> PinStore:
        return self._store

    @property
    def pending_journal_path(self) -> Path:
        return self._store.pin_dir / PENDING_JOURNAL_FILENAME

    # -- pending-adoption journal -----------------------------------------
    # Cheap, non-authoritative, outside the combined pin file:
    # it must survive — and be distinguishable from — an adopt
    # crash, and it is never read as history. It is a detection
    # aid for burned-and-unmoved ceremonies, never evidence a
    # ceremony did NOT happen.

    def _append_journal(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True,
                          allow_nan=False).encode("utf-8") + b"\n"
        with open(self.pending_journal_path, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def _read_journal(self) -> list:
        try:
            raw = self.pending_journal_path.read_bytes()
        except (FileNotFoundError, OSError):
            return []
        entries = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue  # crash-truncated tail: detection aid only
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _journal_ceremonies(self) -> list:
        """Journal lines merged per ceremony_id (later lines
        override, except a field a later line omits — notably
        ``candidate_envelope``, carried only on the
        ``authorised`` line — survives from the earlier line),
        each with its accumulated phase set."""
        by_id = {}
        order = []
        for entry in self._read_journal():
            cid = entry.get("ceremony_id")
            if not isinstance(cid, str):
                continue
            if cid not in by_id:
                by_id[cid] = {"phases": set(), "entry": {}}
                order.append(cid)
            slot = by_id[cid]
            slot["phases"].add(entry.get("phase"))
            for key, value in entry.items():
                if value is not None:
                    slot["entry"][key] = value
        return [by_id[cid] for cid in order]

    def _unadopted_burns(self) -> list:
        """Merged journal ceremonies that reached at least
        ``authorised`` and never reached ``adopted``."""
        return [slot["entry"] for slot in self._journal_ceremonies()
                if "adopted" not in slot["phases"]
                and slot["phases"] & {"authorised", "consumed"}]

    def _retained_current_candidate(self, *, candidate_seq, old_pin):
        """The candidate envelope that IS the current pin (same
        seq + hash), retained on a ceremony's journal lines:
        re-presenting it is what makes a repeat attempt on
        unchanged state classify ``already_current`` instead of
        ``pin_mismatch`` (a fresh signing of the same state has
        a different hash and can never reproduce the pin)."""
        if old_pin is None:
            return None
        for slot in self._journal_ceremonies():
            entry = slot["entry"]
            if entry.get("candidate_seq") != candidate_seq \
                    or entry.get("candidate_hash") \
                    != old_pin["payload_hash"]:
                continue
            envelope = entry.get("candidate_envelope")
            if not isinstance(envelope, dict):
                continue
            try:
                signed = snapshot_envelope_from_dict(envelope)
            except SigningError:
                continue
            if signed.cycle_seq == candidate_seq \
                    and signed.payload_hash == old_pin["payload_hash"]:
                return signed
        return None

    @staticmethod
    def _old_pin_projection(old_pin):
        if old_pin is None:
            return None, ""
        return old_pin["cycle_seq"], old_pin["payload_hash"]

    def _find_unadopted_burn(self, *, candidate_seq, candidate_hash,
                             old_pin):
        old_seq, old_hash = self._old_pin_projection(old_pin)
        for entry in self._unadopted_burns():
            if entry.get("candidate_seq") == candidate_seq \
                    and entry.get("candidate_hash") == candidate_hash \
                    and entry.get("old_cycle_seq") == old_seq \
                    and entry.get("old_payload_hash") == old_hash:
                return entry
        return None

    def _retained_candidate(self, *, candidate_seq, old_pin):
        """The identical candidate envelope retained by an
        unadopted burn for this sequence and old pin, if any —
        re-presenting it is the only way a recovery candidate
        can be the burned candidate (same seq + hash)."""
        old_seq, old_hash = self._old_pin_projection(old_pin)
        for entry in self._unadopted_burns():
            if entry.get("candidate_seq") != candidate_seq \
                    or entry.get("old_cycle_seq") != old_seq \
                    or entry.get("old_payload_hash") != old_hash:
                continue
            envelope = entry.get("candidate_envelope")
            if not isinstance(envelope, dict):
                continue
            try:
                signed = snapshot_envelope_from_dict(envelope)
            except SigningError:
                continue
            if signed.cycle_seq == candidate_seq \
                    and signed.payload_hash == entry.get("candidate_hash"):
                return signed
        return None

    # -- last-candidate retention (advance path) ---------------------------
    # A ceremony leaves its candidate envelope on the journal's
    # authorised line; an advance leaves no journal trace, so
    # the advance path retains its candidate in a small side
    # file. Either way the retained envelope is re-verified in
    # full on every attempt — retention is a cache of a signed
    # artefact, never an authority.

    @property
    def _last_candidate_path(self) -> Path:
        return self._store.pin_dir / "snapshot-candidate.json"

    def _retain_candidate(self, signed) -> None:
        payload = json.dumps(
            {"candidate_envelope": snapshot_envelope_to_dict(signed)},
            ensure_ascii=False, sort_keys=True,
            allow_nan=False).encode("utf-8")
        _write_bytes_atomically(self._last_candidate_path, payload)

    def _read_retained_candidate(self):
        try:
            doc = json.loads(
                self._last_candidate_path.read_bytes().decode("utf-8"))
            return snapshot_envelope_from_dict(doc["candidate_envelope"])
        except Exception:
            return None

    # -- capture ------------------------------------------------------------

    def _read_consistent_pair(self):
        """Read state bytes, read calibration bytes, re-read
        state bytes, refuse if the two state reads differ — the
        ``sign_state_files`` protocol, inlined because
        ``sign_state_files`` returns the snapshot, not the bytes
        ``reanchor_pin`` needs. (Design C §3.3 flags this ~6-line
        duplication as a drift risk with a named follow-up.)"""
        state_path = Path(self._config.state_path)
        calibration_path = Path(self._config.calibration_path)
        try:
            state_first = state_path.read_bytes()
            calibration = calibration_path.read_bytes()
            state_second = state_path.read_bytes()
        except OSError as exc:
            raise PinAdoptionRefused(
                f"state/calibration bytes are unreadable: {exc}") from exc
        if state_first != state_second:
            raise PinAdoptionRefused(
                "state file changed during snapshot capture; "
                "refusing to attest a pair that may never have "
                "coexisted")
        return state_second, calibration

    # -- the flow -------------------------------------------------------------

    def snapshot_and_adopt(self) -> AdoptionResult:
        """One attempt, no internal retries of any verifier
        call. See design C §3.3 for the step-by-step contract."""
        cfg = self._config
        # (1) Capture (FRESH-PIN + COMPLETE-HISTORY): one parse,
        # verified, at the start of THIS attempt.
        try:
            old_pin, history = self._store.read_all(signing_key=self._key)
        except PinStoreError as exc:
            raise PinAdoptionRefused(
                f"pin store refuses the capture: {exc}") from exc
        # (2) Consistent byte pair.
        state_bytes, calibration_bytes = self._read_consistent_pair()
        try:
            facts = parse_state_bytes(state_bytes)
        except SigningError as exc:
            raise PinAdoptionRefused(
                f"state bytes fail strict parsing: {exc}") from exc
        # (3) The candidate: re-present a retained burned
        # candidate identically when one exists for this state
        # sequence and old pin; otherwise sign fresh. For a gap
        # candidate the prev link is "" — the immediate
        # predecessor is unobserved, and writing the pin's hash
        # there would fabricate a chain link the snapshot does
        # not have.
        signed = self._retained_current_candidate(
            candidate_seq=facts.cycle_seq, old_pin=old_pin)
        if signed is None and old_pin is not None \
                and facts.cycle_seq == old_pin["cycle_seq"]:
            retained = self._read_retained_candidate()
            if retained is not None \
                    and retained.cycle_seq == facts.cycle_seq \
                    and retained.payload_hash == old_pin["payload_hash"]:
                signed = retained
        if signed is None:
            signed = self._retained_candidate(
                candidate_seq=facts.cycle_seq, old_pin=old_pin)
        if signed is None:
            prev = ""
            if old_pin is not None \
                    and facts.cycle_seq == old_pin["cycle_seq"] + 1:
                prev = old_pin["payload_hash"]
            try:
                signed = sign_state_snapshot(
                    state_bytes, signing_key=self._key,
                    signer_id=cfg.snapshot_signer_id,
                    calibration_bytes=calibration_bytes,
                    prev_snapshot_hash=prev)
            except SigningError as exc:
                raise PinAdoptionRefused(
                    f"candidate signing refused: {exc}") from exc
        # (4) Classify.
        if old_pin is None:
            reasons = verify_signed_snapshot(
                signed, signing_key=self._key,
                expected_state_bytes=state_bytes,
                expected_calibration_bytes=calibration_bytes,
                require_calibration=True,
                expected_signer_id=cfg.expected_snapshot_signer_id)
            if reasons != ():
                raise PinAdoptionRefused(
                    "genesis candidate fails the bare attestation "
                    f"check: {list(reasons)}")
            return self._reanchor(
                old_pin=None, history=history, signed=signed,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                primary_reason=REASON_INITIAL_ANCHOR,
                strict_reasons=None)
        reasons = verify_snapshot_for_state(
            signed, signing_key=self._key, state_bytes=state_bytes,
            calibration_bytes=calibration_bytes, expected_pin=old_pin,
            expected_signer_id=cfg.expected_snapshot_signer_id)
        cls = classify_verification(reasons)
        # (5) Branch.
        if cls == "ok":
            try:
                new_pin = advance_pin(old_pin, signed, ())
            except SigningError as exc:
                raise PinAdoptionRefused(
                    f"pin advance refused: {exc}") from exc
            already = (new_pin["cycle_seq"] == old_pin["cycle_seq"]
                       and new_pin["payload_hash"]
                       == old_pin["payload_hash"])
            try:
                self._store.adopt(new_pin, record=None,
                                  expected_old_pin=old_pin,
                                  signing_key=self._key)
            except PinStoreError as exc:
                raise PinAdoptionRefused(
                    f"pin adoption refused: {exc}") from exc
            if already:
                return AdoptionResult("already_current", old_pin, None)
            self._retain_candidate(signed)
            return AdoptionResult("advanced", new_pin, None)
        if cls == "reanchor_required":
            return self._reanchor(
                old_pin=old_pin, history=history, signed=signed,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                primary_reason=REASON_CHAIN_GAP_RECOVERY,
                strict_reasons=reasons)
        # Integrity failure: persist NOTHING — no pin write, no
        # history write, no evidence artefact is even created
        # (artefact creation lives inside the ceremony branch).
        raise PinAdoptionRefused(
            "snapshot verification is an integrity failure, not "
            f"a ceremony trigger: {list(reasons)}")

    # -- the ceremony sub-flow ------------------------------------------------

    def _evidence_bundle(self, *, ceremony_id, reason, old_pin, signed,
                         state_bytes, calibration_bytes,
                         strict_reasons) -> bytes:
        cfg = self._config
        if old_pin is None:
            old_line = "genesis"
            gap_line = "initial anchor — no prior pin"
        else:
            old_line = (f"seq={old_pin['cycle_seq']} "
                        f"hash={old_pin['payload_hash']}")
            gap_line = (f"gap_from_seq={old_pin['cycle_seq'] + 1} "
                        f"gap_to_seq={signed.cycle_seq - 1}")
        lines = [
            "aion pin-adoption evidence bundle",
            f"ceremony_id={ceremony_id}",
            f"adopter=aion-pin-adopter snapshot_signer_id="
            f"{cfg.snapshot_signer_id}",
            f"operator_id={cfg.operator_id}",
            f"reason={reason}",
            f"old_pin={old_line}",
            f"candidate_seq={signed.cycle_seq}",
            f"candidate_hash={signed.payload_hash}",
            f"candidate_signer_id={signed.signer_id}",
            f"candidate_key_id={signed.key_id}",
            f"state_sha256={hashlib.sha256(state_bytes).hexdigest()}",
            f"calibration_sha256="
            f"{hashlib.sha256(calibration_bytes).hexdigest()}",
            gap_line,
            f"strict_reasons="
            f"{','.join(strict_reasons) if strict_reasons else ''}",
            f"recorded_at="
            f"{datetime.now(timezone.utc).isoformat()}",
        ]
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _reanchor(self, *, old_pin, history, signed, state_bytes,
                  calibration_bytes, primary_reason,
                  strict_reasons) -> AdoptionResult:
        cfg = self._config
        # Computed reason (DESIGN-FINAL R3): an unadopted burn
        # for THIS candidate (same seq+hash) and THIS old pin
        # makes this ceremony a burned_unadopted recovery;
        # otherwise the honest primary reason. Never lost_pin
        # for an unmoved pin.
        burn = self._find_unadopted_burn(
            candidate_seq=signed.cycle_seq,
            candidate_hash=signed.payload_hash, old_pin=old_pin)
        if burn is not None:
            reason = REASON_BURNED_UNADOPTED
            eff_strict = strict_reasons if old_pin is not None else None
        else:
            reason = primary_reason
            eff_strict = strict_reasons \
                if reason == REASON_CHAIN_GAP_RECOVERY else None
        ceremony_id = (f"pin-adopt-{signed.cycle_seq}-"
                       f"{uuid.uuid4().hex[:12]}")
        evidence_ref = f"pin-evidence-{ceremony_id}"
        # (1) Evidence artefact first: authored and placed by
        # the adopter; the hash comes from the adopter's own
        # bytes (EVIDENCE-INTENT), never from the envelope.
        bundle = self._evidence_bundle(
            ceremony_id=ceremony_id, reason=reason, old_pin=old_pin,
            signed=signed, state_bytes=state_bytes,
            calibration_bytes=calibration_bytes,
            strict_reasons=strict_reasons)
        evidence_dir = Path(cfg.evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomically(evidence_dir / evidence_ref, bundle)
        evidence_hash = hashlib.sha256(bundle).hexdigest()
        old_projection = None if old_pin is None else {
            "cycle_seq": old_pin["cycle_seq"],
            "payload_hash": old_pin["payload_hash"]}
        candidate_projection = {
            "cycle_seq": signed.cycle_seq,
            "payload_hash": signed.payload_hash,
            "signer_id": signed.signer_id, "key_id": signed.key_id}
        old_seq, old_hash = self._old_pin_projection(old_pin)
        # (1b) Authorise-pending journal line (cycle 23, R4): a
        # detection/audit aid appended BEFORE the authorise call,
        # so a crash between authorise and the authorised line
        # still leaves a trace naming the ceremony and candidate.
        # It carries NO envelope and does NOT count as a burn in
        # _unadopted_burns (only authorised/consumed phases do):
        # program order — the authorised-line append completes
        # before consume begins — means a pending line with no
        # authorised line proves nothing could have consumed, and
        # the next attempt proceeds with a fresh primary ceremony.
        try:
            self._append_journal({
                "phase": "authorise_pending",
                "ceremony_id": ceremony_id,
                "candidate_seq": signed.cycle_seq,
                "candidate_hash": signed.payload_hash,
                "old_cycle_seq": old_seq, "old_payload_hash": old_hash})
        except OSError as exc:
            # Fix round (r6-F6): the pending append's failure
            # surfaces in this function's refusal typing, not
            # as a raw OSError — pin_cycle_hook's alert
            # contract keys off PinAdoptionRefused /
            # PinAdoptionBurned and attaches the cycle entry
            # only to those.
            raise PinAdoptionRefused(
                f"authorise-pending journal append failed: {exc}"
            ) from exc
        # (2) Authorise.
        try:
            envelope_dict = self._client.ceremony_authorise(
                operator_id=cfg.operator_id, ceremony_id=ceremony_id,
                reason=reason, old_pin=old_projection,
                candidate=candidate_projection,
                evidence_hash=evidence_hash, evidence_ref=evidence_ref)
            signed_env = ceremony_authorisation_envelope_from_dict(
                envelope_dict)
        except PinAdoptionRefused:
            raise
        except Exception as exc:
            raise PinAdoptionRefused(
                f"ceremony authorisation failed: {exc}") from exc
        journal_base = {
            "ceremony_id": ceremony_id,
            "authorisation_id": signed_env.authorisation_id,
            "candidate_seq": signed.cycle_seq,
            "candidate_hash": signed.payload_hash,
            "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
        }
        # (3) Pending-adoption journal: authorised. The candidate
        # envelope is retained here so a post-burn attempt can
        # re-present the identical candidate (see module
        # docstring); the journal remains a detection aid, never
        # authority.
        self._append_journal({
            **journal_base, "phase": "authorised",
            "candidate_envelope": snapshot_envelope_to_dict(signed)})
        # (4) Re-anchor. Consumption commits at the verifier
        # inside this call; any exception from here is treated
        # as burned — a lost consume response is
        # indistinguishable from a refused one at this layer.
        try:
            new_pin, record = reanchor_pin(
                old_pin, signed, signing_key=self._key,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                expected_signer_id=cfg.expected_snapshot_signer_id,
                operator_id=cfg.operator_id, reason=reason,
                evidence_hash=evidence_hash,
                authorisation=signed_env,
                authorisation_public_key=self._pub,
                expected_verifier_signer_id=cfg.expected_verifier_signer_id,
                ceremony_history=history,
                consume_authorisation=self._client.ceremony_consumer(),
                strict_reasons=eff_strict)
        except Exception as exc:
            raise PinAdoptionBurned(
                f"re-anchor did not return; the authorisation is "
                f"treated as burned: {exc}",
                returned_pin=None, returned_record=None) from exc
        # (5) Adopt atomically.
        self._append_journal({**journal_base, "phase": "consumed"})
        try:
            self._store.adopt(new_pin, record,
                              expected_old_pin=old_pin,
                              signing_key=self._key)
        except Exception as exc:
            raise PinAdoptionBurned(
                f"consumption committed but adoption failed: {exc}",
                returned_pin=new_pin, returned_record=record) from exc
        # The pin has adopted; a failure to append the
        # phase:"adopted" journal line must not mask that
        # success with a raw OSError. The journal is a
        # detection aid, never authority, so the failure is
        # swallowed here (comment-documented swallow, chosen
        # over recording it on the frozen result): the next
        # attempt self-heals via already_current.
        try:
            self._append_journal({**journal_base, "phase": "adopted"})
        except OSError:
            pass
        return AdoptionResult("reanchored", new_pin, record)

    # -- recovery entry point (design C §6.1) ---------------------------------

    def adopt_returned(self, new_pin, record, *,
                       expected_old_pin) -> AdoptionResult:
        """Adopt a (pin, record) pair an earlier
        ``snapshot_and_adopt`` returned but failed to adopt
        (carried on ``PinAdoptionBurned``). No new ceremony, no
        new consumption: a thin, audited wrapper over
        ``PinStore.adopt`` for exactly that pair."""
        if not isinstance(record, PinCeremonyRecord):
            raise SigningError("record must be a PinCeremonyRecord")
        self._store.adopt(new_pin, record,
                          expected_old_pin=expected_old_pin,
                          signing_key=self._key)
        old_seq, old_hash = self._old_pin_projection(expected_old_pin)
        # Same comment-documented swallow as in _reanchor:
        # the adoption above has succeeded, so a journal
        # append failure must not mask it; the next attempt
        # self-heals via already_current.
        try:
            self._append_journal({
                "ceremony_id": record.ceremony_id,
                "authorisation_id": record.authorisation_id,
                "candidate_seq": record.new_cycle_seq,
                "candidate_hash": record.new_payload_hash,
                "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
                "phase": "adopted"})
        except OSError:
            pass
        return AdoptionResult("reanchored", new_pin, record)


def pin_cycle_hook(adopter):
    """The integrated wiring (cycle 23, R1): a ``cycle_hook``
    for ``CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))``
    that adopts the recorded cycle's snapshot pin.

    The returned callable takes the recorded cycle entry, calls
    ``adopter.snapshot_and_adopt()``, and returns its
    AdoptionResult. On PinAdoptionBurned / PinAdoptionRefused the
    entry is attached as ``.cycle_entry`` before re-raising —
    the run_one_cycle_and_pin contract, preserved: "cycle
    recorded, pin pending, alert". The hook is the integrated
    path; run_one_cycle_and_pin remains only for unhooked
    composition and refuses a hooked loop."""
    def _hook(entry):
        try:
            return adopter.snapshot_and_adopt()
        except (PinAdoptionBurned, PinAdoptionRefused) as exc:
            exc.cycle_entry = entry
            raise
    return _hook


def run_one_cycle_and_pin(loop, adopter, *, coders, reviewers,
                          verdict, verify_passed, delta):
    """The loop driver (design C §5): run one loop cycle, then
    adopt its snapshot pin. Ordering is forced: the cycle
    persists in state BEFORE the pin can move (a snapshot
    attests bytes that exist). On an adoption exception the
    cycle entry is attached as ``.cycle_entry`` and the
    exception propagates: the contract is "cycle recorded, pin
    pending, alert". The wrapper never rolls back loop state —
    un-saving a shipped cycle would falsify the loop's history.

    Cycle 23 (R1): the integrated path is the loop hook —
    ``CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))``
    — and this driver remains for unhooked composition only.
    A loop that already carries a cycle_hook is REFUSED
    (ValueError): running the driver on it would wire the
    adoption twice for one cycle (double wiring)."""
    if loop.cycle_hook is not None:
        raise ValueError(
            "run_one_cycle_and_pin refuses a loop with a "
            "cycle_hook already wired (double wiring); the hook "
            "(pin_cycle_hook) is the integrated path — run the "
            "cycle through the loop directly")
    entry = loop.run_one_cycle(coders, reviewers, verdict,
                               verify_passed, delta)
    if entry is None:
        return None, None            # idle: no state change, no snapshot
    try:
        result = adopter.snapshot_and_adopt()
    except (PinAdoptionBurned, PinAdoptionRefused) as exc:
        exc.cycle_entry = entry
        raise
    return entry, result
