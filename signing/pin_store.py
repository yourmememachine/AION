"""The snapshot pin store: one combined pin + ceremony-history file.

Cycle 22, workstream 3 (design C §2, DESIGN-FINAL R3): the first
production adopter of ``reanchor_pin`` needs a pin store that
discharges the ceremony's caller preconditions mechanically:

- FRESH-PIN: every read goes to disk, every call; nothing is
  cached. ``read_all`` parses the file ONCE and returns pin +
  history from that single parse, so a caller can never verify
  against pin generation *n* and pass history from generation
  *n+1*.
- VERIFIED-PRESENT-HISTORY: the ceremony history lives in the
  same document as the pin, and every load verifies every
  record PRESENT in it (``verify_ceremony_record``) plus
  store-level consistency (no duplicate evidence, no forked
  targets, pin matching the history head). The history is
  therefore complete only RELATIVE TO THE STORE DOCUMENT:
  it is a NON-AUTHORITATIVE REPLICA that is
  restoration-lossy — restoring an older generation of the
  document silently drops later records, and no load can
  detect the absence, because the load's checks verify
  records present and cannot detect a record that is not
  there. The SOLE AUTHORITATIVE ceremony audit history is
  the verifier's externally anchored consumption journal
  (with its signing-ledger mirror), against which the store
  history can be reconciled; a gap in the store history
  proves nothing, and the store's safety never depends on
  history completeness (the verifier's consumption head is
  authoritative on any discrepancy). An unverifiable
  history establishes nothing: the load refuses, it does not
  return a partial history.
- ATOMIC-ADOPTION: pin and record persist as ONE JSON document
  replaced by ONE ``os.replace``, written with ``core/loop.py``
  ``save()``'s discipline (mkstemp in the target dir -> write ->
  flush -> fsync -> replace -> dir fsync; temp unlinked on
  failure). ``adopt`` is the only writer, and it is a
  compare-and-swap under an exclusive non-blocking ``flock``:
  the caller names the pin it captured at attempt start
  (``expected_old_pin``) and a mismatch refuses with
  ``PinMovedError`` before anything is written.

Genesis is a ceremony, never a bare write: adopting onto a
missing file requires a no-pin ceremony record (its old side
absent — ``initial_anchor`` / ``lost_pin`` / ``corrupted_pin``
/ a no-pin ``burned_unadopted`` recovery). A corrupt or unverifiable file is
refused on every read and every adopt and is NEVER quarantined,
renamed aside, overwritten or bootstrapped over — the bytes
stay for operator recovery. Caps are declared, not hidden:
the file is at most 1 MiB and the history at most 1000 records;
both refuse, never truncate.

Declared residual (design C §2.1): joint rollback of the one
file (pin + history together, to an older consistent
generation) is undetectable in-deployment — exactly the
residual ``state_snapshot.py`` already states for pin + state.
The verifier's consumption head still bounds the damage.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import tempfile
from dataclasses import fields as _dataclass_fields
from pathlib import Path

from signing.gate_decision import (
    SigningError,
    SigningKey,
    _check_hex64,
    _check_id,
    _normalise_time,
    key_id_for,
)
from signing.pin_ceremony import (
    PinCeremonyRecord,
    _check_pin,
    _payload_hash,
    verify_ceremony_record,
)

STORE_VERSION = "snapshot-pin-store/1"
PIN_STORE_FILENAME = "snapshot-pin.json"
MAX_PIN_STORE_BYTES = 1 * 1024 * 1024
MAX_HISTORY_RECORDS = 1000

_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_RECORD_FIELDS = tuple(f.name for f in _dataclass_fields(PinCeremonyRecord))
_RECORD_FIELD_SET = frozenset(_RECORD_FIELDS)
_HEX64_RECORD_FIELDS = (
    "new_payload_hash", "evidence_hash", "payload_hash",
    "signature", "authorisation_id",
)
_ID_RECORD_FIELDS = (
    "operator_id", "candidate_signer_id", "candidate_key_id", "key_id",
)


class PinStoreError(SigningError):
    """Store-level refusal: corrupt/unverifiable file, cap
    exceeded, non-regression or binding violation."""


class PinMovedError(PinStoreError):
    """CAS mismatch on adopt: the pin under the lock is not the
    pin the caller captured at attempt start. Nothing written."""


class PinStoreBusy(PinStoreError):
    """The adopt lock is held by another writer. ``flock`` is
    released by the OS on process death, so no stale-lock
    recovery protocol exists or is needed."""


# -- record serialisation ---------------------------------------------------


def ceremony_record_to_dict(rec: PinCeremonyRecord) -> dict:
    """Serialise a ceremony record to its exact field dict."""
    if not isinstance(rec, PinCeremonyRecord):
        raise SigningError("rec must be a PinCeremonyRecord")
    return {name: getattr(rec, name) for name in _RECORD_FIELDS}


def ceremony_record_from_dict(data) -> PinCeremonyRecord:
    """Strict reconstruction of a ceremony record: exact key
    set, types checked, and the reconstructed record's
    ``payload()`` must re-derive its ``payload_hash`` (the
    ``snapshot_envelope_from_dict`` precedent). MAC verification
    is NOT done here — it is done by the store load, which holds
    the signing key."""
    if not isinstance(data, dict) or set(data) != _RECORD_FIELD_SET:
        raise SigningError(
            "ceremony record has missing or unknown keys")
    old_seq = data["old_cycle_seq"]
    if old_seq is not None and (
            not isinstance(old_seq, int) or isinstance(old_seq, bool)
            or old_seq < 0):
        raise SigningError(
            "record old_cycle_seq must be an integer or null")
    new_seq = data["new_cycle_seq"]
    if not isinstance(new_seq, int) or isinstance(new_seq, bool) \
            or new_seq < 0:
        raise SigningError("record new_cycle_seq must be an integer >= 0")
    # old_payload_hash is "" for the no-pin shape, hex64 otherwise.
    if data["old_payload_hash"] != "":
        _check_hex64(data["old_payload_hash"], "record old payload hash")
    for name in _HEX64_RECORD_FIELDS:
        _check_hex64(data[name], f"record {name}")
    for name in _ID_RECORD_FIELDS:
        _check_id(data[name], f"record {name}")
    for name in ("reason", "performed_at", "ceremony_id"):
        if not isinstance(data[name], str) or not data[name]:
            raise SigningError(f"record {name} must be non-empty text")
    _check_id(data["ceremony_id"], "record ceremony id")
    _normalise_time(data["performed_at"], "record performed_at")
    try:
        rec = PinCeremonyRecord(
            **{name: data[name] for name in _RECORD_FIELDS})
    except SigningError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise SigningError(f"ceremony record is malformed: {exc}") from exc
    if _payload_hash(rec.payload()) != rec.payload_hash:
        raise SigningError(
            "ceremony record payload does not re-derive its "
            "payload_hash")
    return rec


# -- strict JSON parsing ------------------------------------------------------


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise PinStoreError(f"duplicate key in pin store: {key}")
        out[key] = value
    return out


def _reject_constant(value):
    raise PinStoreError(f"non-finite number in pin store: {value}")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise PinStoreError(f"non-finite number in pin store: {text}")
    return value


class PinStore:
    """Owns ``<pin_dir>/snapshot-pin.json``: pin + ceremony
    history in one document. The pin dir must live outside the
    state dir (the snapshot module's rule: the pin must live
    outside the rollback domain); equality counts as inside."""

    def __init__(self, pin_dir, *, state_dir):
        pin_resolved = Path(pin_dir).resolve()
        state_resolved = Path(state_dir).resolve()
        if pin_resolved == state_resolved \
                or state_resolved in pin_resolved.parents:
            raise PinStoreError(
                "pin_dir must resolve outside state_dir: the pin "
                "must live outside the state's rollback domain")
        self._pin_dir = Path(pin_dir)
        self._state_dir = Path(state_dir)
        self._pin_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._pin_dir / PIN_STORE_FILENAME

    @property
    def pin_dir(self) -> Path:
        return self._pin_dir

    @property
    def lock_path(self) -> Path:
        return self._pin_dir / ".snapshot-pin.lock"

    # -- reads ------------------------------------------------------------

    def read_all(self, *, signing_key) -> tuple:
        """One parse, verified: returns (pin | None, history).

        Missing file -> (None, ()). Any parse, size, version,
        verification or consistency failure -> PinStoreError;
        the file is left exactly as found."""
        return self._read_verified(signing_key)

    def read_pin(self, *, signing_key):
        pin, _history = self._read_verified(signing_key)
        return pin

    def load_history(self, *, signing_key) -> tuple:
        _pin, history = self._read_verified(signing_key)
        return history

    def _read_verified(self, signing_key):
        self._check_key(signing_key)
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None, ()
        except OSError as exc:
            raise PinStoreError(f"pin store is unreadable: {exc}") from exc
        if len(raw) > MAX_PIN_STORE_BYTES:
            raise PinStoreError("pin store exceeds the 1 MiB cap")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PinStoreError("pin store is not valid UTF-8") from exc
        try:
            doc = json.loads(text, object_pairs_hook=_no_duplicate_keys,
                             parse_constant=_reject_constant,
                             parse_float=_parse_float)
        except PinStoreError:
            raise
        except Exception as exc:
            raise PinStoreError(
                f"pin store is not valid JSON: {exc}") from exc
        return self._validate_doc(doc, signing_key)

    @staticmethod
    def _check_key(signing_key):
        if not isinstance(signing_key, SigningKey) \
                or signing_key.key_id != key_id_for(signing_key.key):
            raise PinStoreError("signing key is inconsistent")

    def _validate_doc(self, doc, signing_key):
        if not isinstance(doc, dict) \
                or set(doc) != {"v", "pin", "history"}:
            raise PinStoreError(
                "pin store document has missing or unknown keys")
        if doc["v"] != STORE_VERSION:
            raise PinStoreError(
                f"pin store version must be {STORE_VERSION!r}")
        pin = None
        if doc["pin"] is not None:
            try:
                _seq, _hash, pin = _check_pin(doc["pin"], "pin")
            except SigningError as exc:
                raise PinStoreError(str(exc)) from exc
        if not isinstance(doc["history"], list):
            raise PinStoreError("pin store history must be a list")
        if len(doc["history"]) > MAX_HISTORY_RECORDS:
            raise PinStoreError(
                "pin store history exceeds the 1000-record cap")
        history = []
        for item in doc["history"]:
            try:
                rec = ceremony_record_from_dict(item)
            except SigningError as exc:
                raise PinStoreError(
                    f"pin store history record is malformed: {exc}"
                ) from exc
            reasons = verify_ceremony_record(rec, signing_key=signing_key)
            if reasons != ():
                raise PinStoreError(
                    "pin store history record does not verify: "
                    f"{list(reasons)}")
            history.append(rec)
        history = tuple(history)
        self._check_consistency(pin, history)
        return pin, history

    @staticmethod
    def _check_consistency(pin, history):
        seen_evidence = set()
        targets = {}
        for rec in history:
            if rec.evidence_hash in seen_evidence:
                raise PinStoreError(
                    "pin store history reuses an evidence hash")
            seen_evidence.add(rec.evidence_hash)
            prior = targets.setdefault(rec.new_cycle_seq,
                                       rec.new_payload_hash)
            if prior != rec.new_payload_hash:
                raise PinStoreError(
                    "pin store history is forked: two records "
                    "attest different snapshots at the same "
                    "sequence")
        if pin is not None and history:
            head = max(history, key=lambda r: r.new_cycle_seq)
            if pin["cycle_seq"] < head.new_cycle_seq or (
                    pin["cycle_seq"] == head.new_cycle_seq
                    and pin["payload_hash"] != head.new_payload_hash):
                raise PinStoreError(
                    "pin does not match the history head; the "
                    "combined document is internally inconsistent")

    # -- the only writer ----------------------------------------------------

    def adopt(self, new_pin, record=None, *, expected_old_pin,
              signing_key) -> None:
        """Atomically adopt ``new_pin`` (and append ``record``
        when given) as one document, compare-and-swapped against
        ``expected_old_pin`` under the flock. See the module
        docstring for the full contract."""
        self._check_key(signing_key)
        try:
            _nseq, _nhash, new_captured = _check_pin(new_pin, "new pin")
        except SigningError as exc:
            raise PinStoreError(str(exc)) from exc
        if expected_old_pin is not None:
            try:
                _eseq, _ehash, expected_captured = _check_pin(
                    expected_old_pin, "expected old pin")
            except SigningError as exc:
                raise PinStoreError(str(exc)) from exc
        else:
            expected_captured = None
        if record is not None and not isinstance(record, PinCeremonyRecord):
            raise PinStoreError("record must be a PinCeremonyRecord")

        lock_fd = os.open(self.lock_path,
                          os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PinStoreBusy(
                    "pin store adopt lock is held by another writer")
            # Re-read and re-verify under the lock: the CAS and
            # every guard judge the CURRENT document, never a
            # caller's stale capture.
            current_pin, history = self._read_verified(signing_key)
            if current_pin != expected_captured:
                raise PinMovedError(
                    "pin moved since capture: the pin under the "
                    "lock is not expected_old_pin; nothing written")
            if current_pin is None:
                # Genesis: only via a ceremony record. With no
                # pin there is nothing for advance_pin to chain
                # from, so a bare first write is refused.
                if record is None:
                    raise PinStoreError(
                        "genesis adoption requires a ceremony "
                        "record; a bare first pin write is refused")
                if record.old_cycle_seq is not None \
                        or record.old_payload_hash != "":
                    # Only a no-pin ceremony may create the
                    # store, whatever its no-pin-capable reason
                    # (initial_anchor, lost_pin, corrupted_pin,
                    # or a no-pin burned_unadopted recovery — the
                    # verifier already proved the burn at
                    # authorise and consumed it, so allowing it
                    # here weakens nothing, and refusing it would
                    # dead-end recovery when a genesis ceremony
                    # was consumed but adoption failed before the
                    # store file existed). The genesis defect is
                    # SHAPE, not reason: a record minted against
                    # an existing pin elsewhere (e.g. a
                    # chain_gap_recovery carrying an old
                    # sequence) must not splice its foreign
                    # history in as genesis. The context-bound
                    # verification below enforces the same shape
                    # mechanically.
                    raise PinStoreError(
                        "genesis adoption requires a no-pin "
                        "ceremony record (old pin absent); a "
                        "record minted against an existing pin "
                        "cannot create the store")
            else:
                if new_captured["cycle_seq"] < current_pin["cycle_seq"]:
                    raise PinStoreError(
                        "pin may never move backwards")
                if new_captured["cycle_seq"] == current_pin["cycle_seq"]:
                    if new_captured["payload_hash"] \
                            != current_pin["payload_hash"]:
                        raise PinStoreError(
                            "pin may not be replaced at the same "
                            "sequence with a different snapshot")
                    if record is None:
                        return  # idempotent same-pin no-op
            if record is not None:
                if (record.new_cycle_seq, record.new_payload_hash) != (
                        new_captured["cycle_seq"],
                        new_captured["payload_hash"]):
                    raise PinStoreError(
                        "ceremony record target does not match "
                        "the pin being adopted")
                # Bind the record to THIS store's actual state:
                # its old side must be exactly the pin under the
                # lock (absent at genesis) and its new side the
                # pin being adopted. Context-free verification
                # proves issuance only; without this binding a
                # genuine record minted against a different pin
                # splices a ceremony that never happened against
                # this store into its permanent history.
                reasons = verify_ceremony_record(
                    record, signing_key=signing_key,
                    expected_old_pin=current_pin,
                    expected_new_pin=new_captured)
                if reasons != ():
                    raise PinStoreError(
                        "ceremony record does not verify against "
                        "the store's current pin; the store never "
                        "persists a record it has not itself "
                        f"verified: {list(reasons)}")
                if any(
                        (prior.new_cycle_seq, prior.new_payload_hash)
                        == (record.new_cycle_seq,
                            record.new_payload_hash)
                        for prior in history):
                    raise PinStoreError(
                        "ceremony record target is already a "
                        "ceremonied target in the store history; "
                        "a replayed ceremony is refused")
                prospective = history + (record,)
                if len(prospective) > MAX_HISTORY_RECORDS:
                    raise PinStoreError(
                        "pin store history exceeds the "
                        "1000-record cap")
                # Never write a document the verified load
                # would refuse: run the load-side consistency
                # check over the prospective history (with the
                # pin being adopted) before serialising.
                self._check_consistency(new_captured, prospective)
                history = prospective
            doc = {
                "v": STORE_VERSION,
                "pin": new_captured,
                "history": [ceremony_record_to_dict(r) for r in history],
            }
            payload = json.dumps(doc, ensure_ascii=False, indent=2,
                                 allow_nan=False).encode("utf-8")
            if len(payload) > MAX_PIN_STORE_BYTES:
                raise PinStoreError("pin store exceeds the 1 MiB cap")
            self._write_atomically(payload)
        finally:
            os.close(lock_fd)

    def _write_atomically(self, payload: bytes) -> None:
        """loop.save()'s exact discipline: mkstemp in the pin
        dir -> write -> flush -> fsync -> os.replace -> dir
        fsync. The rename is the single commit point; a failure
        before it leaves the pre-existing file untouched, and a
        dir-fsync failure after it is reported but cannot roll
        the committed document back."""
        fd, tmp = tempfile.mkstemp(dir=self._pin_dir,
                                   prefix=".snapshot-pin-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self._pin_dir, os.O_DIRECTORY)
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
