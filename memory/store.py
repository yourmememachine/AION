"""Long-term memory store with gated writes.

Standard library only. No network access. The store persists memory
entries as a single JSON document written atomically and validated
deeply on load; a corrupt document fails closed and is never silently
replaced with empty state. Entries are immutable, append-only records
carrying full provenance (author, source, evidence reference, proposal
id, verifier id). An entry is "current" iff no later committed entry
supersedes it; retrieval returns current entries only, in commit
order. A (domain, kind) pair has at most one current entry, so what
retrieval returns is deterministic.

Writes are gated: the only way in is commit_write(entry, decision),
which requires an accepted decision from the existing safety gate
(eval/gate.py, via decide_write below) whose proposal id and verifier
id match the entry, and whose verifier_note carries the entry's
content hash as its first segment — the binding decide_write stamps
in, so a decision issued for one entry cannot be presented for a
different one. Proposal ids are single-use within the store's
history: one accepted decision authorises exactly one entry, and
that entry is the one whose content hash the decision carries.
(After a whole-file rollback to an older state, a proposal id from
the rolled-away suffix is free again — rollback is the documented
limit below, and single-use is a property of the surviving history.)

Immutability and hash-chaining are API discipline, not a security
boundary. Same-process/same-user code can edit, roll back, rewrite
and rehash this store, or construct an accepted GateDecision directly
(it is a plain dataclass with no signature). Tamper is detectable
only when the chain head is anchored outside writable storage: a
fully rehashed rewrite, and a rollback to an older internally valid
file, both load cleanly on a fresh instance. A missing memory file
is treated as a first run and starts empty, so deletion of the file
is indistinguishable from it never having existed.

A committed write proves only that a GateDecision object with
accepted=True, a matching proposal_id, and the entry's content hash
in its verifier_note was presented. It does not prove the gate ran,
a verifier attested, the lesson is true, or the lesson will help
off-distribution. The gate checks consistency of supplied scores,
not provenance or truth. Provenance fields are self-asserted strings
covered by the entry hash: the hash proves they were not altered
after hashing, not that they were true when written. Timestamps
(created_at, and attested_at on gate attestations) are local
host-clock assertions, checked only for form; ordering in this
store is by the seq counter, never by clock.

An instance serves the snapshot it loaded: reads do not notice
newer state written by other instances, and once an instance's
save has been refused for staleness it stays stale — reconstruct
the instance to recover. Content may contain bare newlines ("\n");
carriage returns are rejected like every other control character.

Retrieved lessons are untrusted data, not instructions and not
verified facts. A committed lesson can be wrong, stale in effect, or
misapplied; similarity is not correctness.

Scope for v1: the only writable kind is "strategy" (a compact lesson
token that changes solver behaviour on a repeat task). Facts,
episodes and other kinds need their own truth/conflict semantics and
are rejected at write time, not stored dormant. Content may contain
newlines (memory text needs them); every other text field follows
the registry's stricter rule.

Strict mode (cycle 8): MemoryStore(memory_dir, signed_only=True)
refuses plain commit_write calls; commits then arrive only via
signing.commit_signed, which verifies an HMAC envelope first and
calls _commit_gated. _commit_gated is an internal delegate for
commit_signed, not a public entry point; the lint allowlists
exactly two call sites for it: this delegation and
signing.commit_signed.

Signed-commit permit handshake (Trust Boundary v2 fix round):
verifying the envelope inside commit_signed was not, by itself,
enough — _commit_gated contained no signed_only check, so a
hand-constructed unsigned GateDecision(accepted=True) whose
verifier_note carried the entry's correct content hash committed
successfully on a signed_only store with no key, no envelope and
no verifier (review CRITICAL-1, demonstrated by probe). Now,
when the store's mode is signed_only, _commit_gated additionally
requires a one-shot permit: commit_signed — AFTER it has verified
the envelope MAC and any presented attestation — mints the permit
via MemoryStore._mint_signed_commit_permit and passes it in. The
permit binds the entry's content hash and this store instance's
identity token, is registered in the store's in-memory outstanding
set at mint time, and is consumed (deleted) when presented, so it
cannot be replayed, cannot be moved to another entry or another
store instance, and cannot be forged by constructing a
GateDecision or a permit object — a permit whose nonce is not in
the outstanding set is refused. Direct _commit_gated calls
without a permit on a signed store raise. What this proves,
honestly: within this codebase, a commit on a signed store can
only complete when the verified signing path ran in-process and
minted a permit for that exact entry. What it does NOT prove: it
is not a capability boundary against arbitrary same-process code —
code running in this process can call the mint method itself, but
only commit_signed does so, and only after envelope verification;
a caller with no envelope, or a forged one, fails verification
before any permit exists. The unsigned-store path
(commit_write/decide_write) is unchanged and requires no permit.

Persisted security mode (Trust Boundary v2): the store's mode is
persisted in the memory file itself as a top-level "security_mode"
field ("signed_only" or "unsigned"), and the state digest covers
it, so flipping it by hand in the file is detected like any other
tamper. Opening a store whose persisted mode is "signed_only" with
signed_only=False refuses on every open path; the only way back is
MemoryStore.migrate_security_mode, which appends a hash-chained
audit entry to a separate migration-audit journal in the store
directory BEFORE flipping the persisted mode, and requires a
non-empty actor and reason for a downgrade to "unsigned". Opening
with signed_only=True over an "unsigned" file is a safe ratchet:
allowed, and the persisted mode becomes "signed_only" on the next
save. Legacy files written before this field existed have no
"security_mode" key: they load as "unsigned" (back-compat), are
validated with the legacy state-digest computation (see
_state_digest), and gain the field on first save. Honest limit,
unchanged: a same-user file editor who rewrites the whole file AND
recomputes the digest can still defeat the persisted mode —
detection rests on the digest and on anchoring it externally, as
everywhere else in this store.

Migration journal on open (Trust Boundary v2 fix round, F2): when
a migration-audit.json exists beside the store file, opening the
store verifies the journal's hash chain and requires its final
recorded mode to match the store file's persisted security_mode;
a broken chain or a mismatch refuses the open
(CorruptMemoryError). Previously the journal was written but never
consulted on open.

Accepted residuals, stated plainly (do not read the mechanisms
above as defeating these):
- Whole-file rewrite plus digest recompute defeats the unkeyed
  state digest entirely — including stripping the "security_mode"
  field out of the file and recomputing the LEGACY digest over the
  stripped document, which then loads as a legacy "unsigned" file.
  The digest is tamper-evidence for edits that do not recompute
  it; it is not authentication.
- The migration journal's actor and reason fields are
  unauthenticated, self-asserted strings: the journal proves a
  migration was recorded with those strings, not who performed it
  or that the reason was true.
- Deleting migration-audit.json removes the journal the open-time
  check consults, so that check cannot fire; journal deletion by
  a same-user attacker is an accepted residual, not a detected
  event.
- Deleting memory.json yields a fresh unsigned store on next open
  (see the first-run note above): deletion is indistinguishable
  from the store never having existed.
"""

from __future__ import annotations

import copy
import fcntl
import functools
import hashlib
import json
import math
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from eval.gate import GateDecision, evaluate_self_change

SCHEMA_VERSION = 1
MAX_MEMORY_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_CONTENT_CHARS = 2000
MAX_DOMAIN_CHARS = 200
MAX_REF_CHARS = 500
GENESIS_HASH = "0" * 64
KINDS = ("strategy",)

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_BAD_CHARS = set("\u200b\u200c\u200d\ufeff\u202a\u202b\u202c\u202d\u202e\u2060")

_ENTRY_FIELDS = ("id", "domain", "kind", "content", "author", "source",
                 "evidence_ref", "proposal_id", "verifier_id", "supersedes")
_STORED_KEYS = set(_ENTRY_FIELDS) | {"seq", "created_at", "content_hash",
                                     "prev_hash", "entry_hash"}


class _SignedCommitPermit:
    """One-shot permit for a single signed commit (see the module
    docstring's handshake paragraph).

    A permit is just a carrier for three values: a random nonce,
    the content hash it is bound to, and the minting store
    instance's identity token. Constructing one of these objects
    does NOT forge a permit: _commit_gated accepts a permit only
    if its nonce is present in the minting store's in-memory
    outstanding set with the same content hash and store token,
    and it deletes the nonce on use (single-use). The nonce is
    256 bits of secrets randomness, known only to the store that
    minted it and the caller it handed the permit to.
    """

    __slots__ = ("_nonce", "_content_hash", "_store_token")

    def __init__(self, nonce, content_hash, store_token):
        self._nonce = nonce
        self._content_hash = content_hash
        self._store_token = store_token


class MemoryError(ValueError):
    """Raised when a memory operation is not allowed."""


# Alias: refusal errors from the store (including the persisted
# security-mode refusal on open) are MemoryErrors; the longer name
# is provided for callers that prefer it.
MemoryStoreError = MemoryError


class CorruptMemoryError(Exception):
    """Raised when persisted memory data cannot be trusted."""


class TamperDetectedError(CorruptMemoryError):
    """Raised when stored content does not match its recorded hash."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key in memory file: {key}")
        out[key] = value
    return out


def _reject_constant(value: str):
    raise CorruptMemoryError(f"non-finite number in memory: {value}")


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise CorruptMemoryError(f"non-finite number in memory: {text}")
    return value


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise MemoryError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_text(value, field: str, cap: int, *, allow_newline: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryError(f"{field} must be non-empty text")
    if len(value) > cap:
        raise MemoryError(f"{field} exceeds {cap} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) in ("Cf", "Cs")
                or (code < 32 and ch not in "\t" and not (allow_newline and ch == "\n"))
                or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise MemoryError(f"{field} contains control or invisible characters")
    return value


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _content_hash(fields: dict) -> str:
    """Hash of the proposer's claim: everything that defines what is
    claimed and on whose authority. Store-assigned fields (seq,
    created_at, prev_hash) are excluded, so the hash is computable
    before commit — and gate decisions do bind to it: decide_write
    stamps it into the decision's verifier_note and commit_write
    refuses a decision carrying any other entry's hash."""
    core = {"v": "memory-content/1"}
    for key in _ENTRY_FIELDS:
        core[key] = fields.get(key)
    return hashlib.sha256(_canonical(core)).hexdigest()


def content_hash_for(fields: dict) -> str:
    """The content hash an entry with these fields will carry."""
    return _content_hash(fields)


def _entry_hash(entry: dict) -> str:
    core = {"v": "memory-entry/1", "seq": entry["seq"],
            "prev_hash": entry["prev_hash"],
            "content_hash": entry["content_hash"],
            "created_at": entry["created_at"], "id": entry["id"]}
    return hashlib.sha256(_canonical(core)).hexdigest()


SECURITY_MODES = ("signed_only", "unsigned")
MIGRATION_AUDIT_FILENAME = "migration-audit.json"
_AUDIT_ENTRY_KEYS = {"seq", "recorded_at", "actor", "reason",
                     "from_mode", "to_mode", "prev_hash", "entry_hash"}
_BASE_KEYS = {"schema_version", "entry_seq", "entries", "state_digest"}


def _legacy_state_digest(data) -> str:
    """The pre-security-mode state digest (cycle <=8 format): the
    core has no "security_mode" component. Used ONLY to validate
    legacy files that carry no "security_mode" field at all; a file
    that carries the field is always validated with _state_digest,
    so a hand-flip of the field cannot fall back to this path."""
    entries = data.get("entries", [])
    core = {
        "schema_version": data.get("schema_version"),
        "entry_seq": data.get("entry_seq"),
        "head": entries[-1]["entry_hash"] if entries else GENESIS_HASH,
        "entries": sorted((e["id"], e["entry_hash"]) for e in entries),
    }
    return hashlib.sha256(_canonical(core)).hexdigest()


def _state_digest(data) -> str:
    """Digest over schema, count, membership, the chain head and
    the persisted security mode.

    Per-entry hashes alone cannot detect a deleted entry or a
    truncated tail. This digest binds all of them together; it is
    recomputed on every save and checked on load. Like every hash
    here, it detects edits that do not also recompute it — its
    strength comes from anchoring it externally (see state_digest()).

    DIGEST FORMAT CHANGE (Trust Boundary v2): the core now includes
    "security_mode". Files that carry the field validate only
    against this computation; legacy files without the field
    validate against _legacy_state_digest on load and are upgraded
    to this computation (with the field added) on first save.
    """
    entries = data.get("entries", [])
    core = {
        "schema_version": data.get("schema_version"),
        "entry_seq": data.get("entry_seq"),
        "security_mode": data.get("security_mode"),
        "head": entries[-1]["entry_hash"] if entries else GENESIS_HASH,
        "entries": sorted((e["id"], e["entry_hash"]) for e in entries),
    }
    return hashlib.sha256(_canonical(core)).hexdigest()


def _digest_for(data) -> str:
    """The digest computation that applies to a parsed document:
    the current one when the document carries a security_mode
    field, the legacy one when it does not."""
    if "security_mode" in data:
        return _state_digest(data)
    return _legacy_state_digest(data)


def _audit_entry_hash(entry: dict) -> str:
    core = {"v": "memory-migration-audit/1"}
    for key, value in entry.items():
        if key != "entry_hash":
            core[key] = value
    return hashlib.sha256(_canonical(core)).hexdigest()


def _load_migration_audit(memory_dir) -> list:
    """Load and fully verify the migration-audit journal in a store
    directory. Missing journal is an empty list; a malformed or
    chain-broken journal is corruption and fails closed."""
    path = Path(memory_dir) / MIGRATION_AUDIT_FILENAME
    if not path.exists():
        return []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CorruptMemoryError(f"unreadable migration audit: {exc}") from exc
    if len(raw) > MAX_MEMORY_BYTES:
        raise CorruptMemoryError("migration audit exceeds size cap")
    try:
        data = json.loads(raw.decode("utf-8"),
                          parse_constant=_reject_constant,
                          parse_float=_parse_float,
                          object_pairs_hook=_no_duplicate_keys)
    except Exception as exc:
        raise CorruptMemoryError(f"unreadable migration audit: {exc}") from exc
    if not isinstance(data, dict) or set(data.keys()) != {"entries"} \
            or not isinstance(data["entries"], list):
        raise CorruptMemoryError("migration audit has wrong shape")
    entries = data["entries"]
    prev = GENESIS_HASH
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry.keys()) != _AUDIT_ENTRY_KEYS:
            raise CorruptMemoryError("migration audit entry has wrong keys")
        if entry["seq"] != position or entry["prev_hash"] != prev:
            raise CorruptMemoryError("migration audit chain is broken")
        if entry["from_mode"] not in SECURITY_MODES \
                or entry["to_mode"] not in SECURITY_MODES:
            raise CorruptMemoryError("migration audit entry has bad mode")
        if entry["entry_hash"] != _audit_entry_hash(entry):
            raise CorruptMemoryError("migration audit entry hash mismatch")
        prev = entry["entry_hash"]
    return entries


def verify_migration_audit(memory_dir) -> list:
    """The verified migration-audit entries for a store directory
    (empty list when no migration has ever been recorded). Raises
    CorruptMemoryError if the journal does not verify."""
    return _load_migration_audit(memory_dir)


def _validate_fields(entry_fields) -> dict:
    """Check and normalise the proposer's entry fields.

    Shared by decide_write and commit_write, so a decision is only
    ever issued for fields that could actually be committed.
    """
    if not isinstance(entry_fields, dict):
        raise MemoryError("entry_fields must be an object")
    if set(entry_fields.keys()) != set(_ENTRY_FIELDS):
        raise MemoryError(
            "entry_fields must carry exactly the proposer fields")
    fields = {}
    fields["id"] = _check_id(entry_fields.get("id"), "entry id")
    fields["domain"] = _check_text(entry_fields.get("domain"), "domain",
                                   MAX_DOMAIN_CHARS)
    kind = entry_fields.get("kind")
    if kind not in KINDS:
        raise MemoryError(f"kind must be one of {KINDS} in this version")
    fields["kind"] = kind
    fields["content"] = _check_text(entry_fields.get("content"),
                                    "content", MAX_CONTENT_CHARS,
                                    allow_newline=True)
    fields["author"] = _check_id(entry_fields.get("author"), "author")
    fields["source"] = _check_text(entry_fields.get("source"), "source",
                                   MAX_REF_CHARS)
    fields["evidence_ref"] = _check_text(
        entry_fields.get("evidence_ref"), "evidence_ref", MAX_REF_CHARS)
    fields["proposal_id"] = _check_id(entry_fields.get("proposal_id"),
                                      "proposal id")
    fields["verifier_id"] = _check_id(entry_fields.get("verifier_id"),
                                      "verifier id")
    supersedes = entry_fields.get("supersedes")
    if supersedes is not None:
        supersedes = _check_id(supersedes, "supersedes")
    fields["supersedes"] = supersedes
    return fields


def _binding_for(fields: dict) -> str:
    return f"content-hash:{_content_hash(fields)}"


def decide_write(*, entry_fields, builder_ids, reviewer_ids,
                 baseline_public, candidate_public,
                 baseline_sealed, candidate_sealed,
                 capability_baseline, capability_candidate,
                 attestation, expected_sealed_hash,
                 verifier_note="") -> GateDecision:
    """Run one proposed memory write through the safety gate.

    A memory write is a self-change: it alters what the system does
    on future tasks. The gate (eval/gate.py) receives per-family
    score maps produced by the caller — public and golden maps may
    be computed builder-side; sealed maps are a protocol obligation
    on the caller to produce verifier-side, because the registry's
    builder-facing surface is aggregate-only (the shipped reuse
    harness plays the verifier role in-process; see its docstring
    for what that does and does not separate). changed_paths always
    names the one memory object written, so the protected-path
    check is never skipped.

    The returned decision is bound to this exact entry: its
    verifier_note begins with the entry's content hash, and
    commit_write refuses the decision for any other entry.
    """
    fields = _validate_fields(entry_fields)
    binding = _binding_for(fields)
    note = binding if not verifier_note else f"{binding}; {verifier_note}"
    return evaluate_self_change(
        proposal_id=fields["proposal_id"],
        builder_ids=builder_ids,
        reviewer_ids=reviewer_ids,
        baseline_public=baseline_public,
        candidate_public=candidate_public,
        baseline_sealed=baseline_sealed,
        candidate_sealed=candidate_sealed,
        capability_baseline=capability_baseline,
        capability_candidate=capability_candidate,
        attestation=attestation,
        expected_sealed_hash=expected_sealed_hash,
        evaluated_at=_now(),
        changed_paths=[f"memory/entries/{fields['proposal_id']}"],
        verifier_note=note,
    )


def _serialised(method):
    """Serialise one instance across threads (registry precedent)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._thread_lock:
            return method(self, *args, **kwargs)
    return wrapper


class MemoryStore:
    """One memory file, gated append-only entries, derived currency."""

    def __init__(self, memory_dir, *, signed_only=False,
                 _skip_migration_journal_check=False):
        if not isinstance(signed_only, bool):
            raise MemoryError("signed_only must be a bool")
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.memory_dir / "memory.json"
        self._lock_depth = 0
        self._lock_owner = None
        self._lock_fd = None
        self._thread_lock = threading.RLock()
        self._signed_only = signed_only
        # Signed-commit permit handshake state: a per-instance
        # identity token (permits minted for one instance are
        # refused by every other, including another instance over
        # the same directory) and the outstanding-permit registry
        # (nonce -> content hash). In-memory only, by design: a
        # permit never outlives the instance that minted it, and
        # commit_signed mints and presents within one call.
        self._store_token = secrets.token_hex(16)
        self._outstanding_permits = {}
        existed = self.memory_path.exists()
        self._state = self._load()
        if existed and not _skip_migration_journal_check:
            # F2: consult the migration journal on open. A broken
            # chain raises CorruptMemoryError from the loader; a
            # final recorded mode that disagrees with the store
            # file's persisted mode refuses here. Compared against
            # the mode AS LOADED (before the ratchet below), i.e.
            # the mode actually persisted in the file.
            # _skip_migration_journal_check exists only for
            # migrate_security_mode's internal flip construction,
            # which runs in the window where the journal already
            # records the target mode and the file does not yet.
            # Journal DELETION remains an accepted residual (see
            # the module docstring): with no journal present there
            # is nothing to consult and this check cannot fire.
            audit_entries = _load_migration_audit(self.memory_dir)
            if audit_entries and audit_entries[-1]["to_mode"] \
                    != self._state["security_mode"]:
                raise CorruptMemoryError(
                    "migration audit's final recorded mode "
                    f"({audit_entries[-1]['to_mode']!r}) does not "
                    "match the store's persisted security_mode "
                    f"({self._state['security_mode']!r}); refusing "
                    "to open")
        if existed and self._state["security_mode"] == "signed_only" \
                and not signed_only:
            raise MemoryError(
                "store is persisted as signed_only: opening it with "
                "signed_only=False is refused. Open with "
                "signed_only=True, or downgrade only through the "
                "audited MemoryStore.migrate_security_mode")
        if signed_only and self._state["security_mode"] != "signed_only":
            # Safe ratchet: opening an unsigned store in strict mode
            # is allowed; the persisted mode becomes "signed_only"
            # on the next save (the in-memory state carries it from
            # here, and _save_locked persists it).
            self._state["security_mode"] = "signed_only"
        self._disk_digest = self._state["state_digest"]

    @property
    def signed_only(self) -> bool:
        """Whether this instance refuses unsigned commit_write calls.

        Strict mode (cycle 7, persisted in Trust Boundary v2): a
        signed_only store accepts commits only through
        signing.commit_signed, which verifies an HMAC envelope
        first, mints a one-shot permit bound to the entry and this
        store instance, and then calls _commit_gated — which
        refuses any signed-store commit presented without that
        permit (see the module docstring's handshake paragraph).
        The mode is PERSISTED
        in the memory file as its "security_mode" field and covered
        by the state digest: once a store has been saved as
        signed_only, opening it with signed_only=False refuses on
        every open path, and the only way back to "unsigned" is the
        audited MemoryStore.migrate_security_mode (hash-chained
        audit journal, non-empty actor and reason required).
        Opening with signed_only=True over an "unsigned" file is a
        safe ratchet and persists "signed_only" on the next save.

        Remaining honest limit: a same-user file editor who
        rewrites the whole file AND recomputes the state digest can
        still flip the persisted mode undetectably — detection
        rests on the digest and on anchoring it externally, as
        elsewhere in this store. What the persisted mode removes is
        the silent in-process downgrade: no constructor call alone
        re-enables unsigned commits over a signed_only store.
        """
        return self._signed_only

    @property
    def security_mode(self) -> str:
        """The store's effective security mode: "signed_only" or
        "unsigned". For an existing file this is the persisted mode
        (after the open-time ratchet, if any); for a fresh store it
        is the mode the first save will persist."""
        return self._state["security_mode"]

    @classmethod
    def migrate_security_mode(cls, memory_dir, *, to_mode, actor,
                              reason) -> dict:
        """Audited migration of a store's persisted security mode.

        This is the ONLY way to move a store whose persisted mode
        is "signed_only" back to "unsigned" (upgrades to
        "signed_only" may also be done by simply opening the store
        with signed_only=True and saving). The migration appends a
        hash-chained entry to the migration-audit journal
        (migration-audit.json in the store directory, a small local
        hash chain in the trust/ledger.py pattern — memory does not
        import trust) BEFORE the persisted mode is flipped, so a
        completed flip always has its audit entry. A downgrade to
        "unsigned" requires a non-empty actor and a non-empty
        reason; actor is required for every migration. Migrating to
        the mode the store is already in is refused as a no-op.
        Returns the audit entry that was appended.
        """
        memory_dir = Path(memory_dir)
        memory_path = memory_dir / "memory.json"
        if to_mode not in SECURITY_MODES:
            raise MemoryError(
                f"to_mode must be one of {SECURITY_MODES}")
        actor = _check_text(actor, "actor", MAX_REF_CHARS)
        if reason is not None and not isinstance(reason, str):
            raise MemoryError("reason must be text")
        if to_mode == "unsigned" and not (reason and reason.strip()):
            raise MemoryError(
                "downgrading a store to 'unsigned' requires a "
                "non-empty reason")
        if reason:
            _check_text(reason, "reason", MAX_REF_CHARS)
        if not memory_path.exists():
            raise MemoryError(
                "no memory store exists in that directory; nothing "
                "to migrate")

        probe = cls.__new__(cls)
        probe.memory_dir = memory_dir
        probe.memory_path = memory_path
        probe._signed_only = False
        state = probe._load()
        from_mode = state["security_mode"]
        if from_mode == to_mode:
            raise MemoryError(
                f"store is already in mode {to_mode!r}; migration "
                "refused as a no-op")

        # 1. Audit first, under the directory lock, re-verifying
        # the existing chain before extending it.
        fd = os.open(memory_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            entries = _load_migration_audit(memory_dir)
            audit_entry = {
                "seq": len(entries) + 1,
                "recorded_at": _now(),
                "actor": actor,
                "reason": reason or "",
                "from_mode": from_mode,
                "to_mode": to_mode,
                "prev_hash": (entries[-1]["entry_hash"]
                              if entries else GENESIS_HASH),
            }
            audit_entry["entry_hash"] = _audit_entry_hash(audit_entry)
            payload = json.dumps({"entries": entries + [audit_entry]},
                                 ensure_ascii=False, indent=2,
                                 allow_nan=False).encode("utf-8")
            tmp_fd, tmp = tempfile.mkstemp(dir=memory_dir,
                                           prefix=".migration-audit-",
                                           suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, memory_dir / MIGRATION_AUDIT_FILENAME)
                dir_fd = os.open(memory_dir, os.O_DIRECTORY)
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
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        # 2. Only now flip the persisted mode, through the store's
        # own locked, validated save path. The mode is re-checked
        # on the freshly loaded instance: if it moved since the
        # probe, refuse rather than flip on a stale premise (the
        # audit entry above stands as a record of the attempt).
        # The journal check is skipped for this construction only:
        # the audit entry above already records to_mode while the
        # file still persists from_mode, so the open-time journal
        # check would (correctly, for any other opener) refuse.
        store = cls(memory_dir, signed_only=(from_mode == "signed_only"),
                    _skip_migration_journal_check=True)
        if store.security_mode != from_mode:
            raise CorruptMemoryError(
                "store security mode changed during migration; "
                "refusing to flip")
        store._state["security_mode"] = to_mode
        store._signed_only = (to_mode == "signed_only")
        store.save()
        return dict(audit_entry)

    @contextmanager
    def _locked(self):
        """Exclusive inter-instance lock on the store directory itself.

        Copied from the registry: the lock is taken on the directory
        descriptor, not a lockfile inside it, because a lockfile can
        be unlinked mid-race and split the lock across two inodes.
        Re-entrancy is owned by thread, not by instance.
        """
        ident = threading.get_ident()
        if self._lock_owner == ident:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        fd = os.open(self.memory_dir,
                     os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        fcntl.flock(fd, fcntl.LOCK_EX)
        self._lock_owner = ident
        self._lock_depth = 1
        self._lock_fd = fd
        try:
            yield
        finally:
            self._lock_owner = None
            self._lock_depth = 0
            self._lock_fd = None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _disk_changed(self) -> bool:
        """True if the file on disk is not the state this instance
        last loaded or saved. The digest is RECOMPUTED over the
        parsed file, never trusted from the file's own digest field:
        an edit that leaves the stored field untouched (naive
        tamper) must read as changed here, so a live instance
        refuses to save over it instead of silently clobbering it.
        The read is size-capped like the load path."""
        if not self.memory_path.exists():
            return self._disk_digest != _state_digest(self._fresh())
        try:
            if self.memory_path.stat().st_size > MAX_MEMORY_BYTES:
                return True
            raw = self.memory_path.read_bytes()[: MAX_MEMORY_BYTES + 1]
            if len(raw) > MAX_MEMORY_BYTES:
                return True
            # The same strict parser as the load path: duplicate
            # keys and non-finite constants read as changed here,
            # not as a silently healable file.
            on_disk = json.loads(raw.decode("utf-8"),
                                 parse_constant=_reject_constant,
                                 parse_float=_parse_float,
                                 object_pairs_hook=_no_duplicate_keys)
        except Exception:
            return True
        if not isinstance(on_disk, dict):
            return True
        if set(on_disk.keys()) not in (_BASE_KEYS,
                                       _BASE_KEYS | {"security_mode"}):
            return True
        if "security_mode" in on_disk \
                and on_disk["security_mode"] not in SECURITY_MODES:
            return True
        try:
            entries = on_disk.get("entries")
            if not isinstance(entries, list):
                return True
            for entry in entries:
                if not isinstance(entry, dict):
                    return True
                if set(entry.keys()) != _STORED_KEYS:
                    return True
                # Recompute, never trust, both hash levels: the
                # state digest alone covers only the stored hash
                # fields, so a content edit that leaves them
                # untouched is caught here, not there.
                if _content_hash(entry) != entry.get("content_hash"):
                    return True
                if _entry_hash(entry) != entry.get("entry_hash"):
                    return True
            recomputed = _digest_for(on_disk)
            # The stored digest field must also match its own
            # contents: the digest core excludes that field, so
            # corrupting it alone is otherwise invisible here.
            if on_disk.get("state_digest") != recomputed:
                return True
            return recomputed != self._disk_digest
        except Exception:
            return True

    # -- persistence -----------------------------------------------------

    def _fresh(self) -> dict:
        data = {"schema_version": SCHEMA_VERSION, "entry_seq": 0,
                "entries": [],
                "security_mode": ("signed_only" if self._signed_only
                                  else "unsigned")}
        data["state_digest"] = _state_digest(data)
        return data

    def _load(self) -> dict:
        if not self.memory_path.exists():
            return self._fresh()
        try:
            size = self.memory_path.stat().st_size
            raw = self.memory_path.read_bytes()[: MAX_MEMORY_BYTES + 1]
        except OSError as exc:
            raise CorruptMemoryError(f"unreadable memory: {exc}") from exc
        if size > MAX_MEMORY_BYTES or len(raw) > MAX_MEMORY_BYTES:
            raise CorruptMemoryError("memory file exceeds size cap")
        try:
            data = json.loads(raw.decode("utf-8"),
                              parse_constant=_reject_constant,
                              parse_float=_parse_float,
                              object_pairs_hook=_no_duplicate_keys)
        except Exception as exc:
            # Every parse-stage failure quarantines, including
            # non-finite constants and duplicate keys.
            self._quarantine(raw)
            raise CorruptMemoryError(f"unreadable memory: {exc}") from exc
        try:
            self._validate(data)
        except CorruptMemoryError:
            raise
        except Exception as exc:
            raise CorruptMemoryError(f"invalid memory: {exc}") from exc
        if "security_mode" not in data:
            # Legacy file (pre-dates the persisted mode): it loads
            # as "unsigned" and gains the field on first save, when
            # _save_locked recomputes the digest in the new format.
            data["security_mode"] = "unsigned"
        return data

    def _quarantine(self, raw: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            (self.memory_dir / f"memory.corrupt-{stamp}.json").write_bytes(raw)
        except OSError:
            pass

    def _validate(self, data) -> None:
        def bad(msg):
            raise CorruptMemoryError(msg)

        if not isinstance(data, dict):
            bad("memory is not an object")
        if set(data.keys()) not in (_BASE_KEYS,
                                    _BASE_KEYS | {"security_mode"}):
            bad("memory has missing or unknown keys")
        if "security_mode" in data \
                and data["security_mode"] not in SECURITY_MODES:
            bad("security_mode has an invalid value")
        if not _is_int(data.get("schema_version")) or data["schema_version"] != SCHEMA_VERSION:
            bad("unsupported schema_version")
        entries = data.get("entries")
        if not isinstance(entries, list):
            bad("entries must be a list")
        if len(entries) > MAX_ENTRIES:
            bad("entries exceed cap")
        if not _is_int(data.get("entry_seq")) or data["entry_seq"] != len(entries):
            bad("entry_seq does not match entry count")

        seen_ids, seen_proposals = set(), set()
        by_id = {}
        superseded_by = {}
        prev_hash = GENESIS_HASH
        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                bad("entry is not an object")
            if set(entry.keys()) != _STORED_KEYS:
                bad("entry has missing or unknown keys")
            try:
                _check_id(entry.get("id"), "entry id")
                _check_id(entry.get("author"), "author")
                _check_id(entry.get("verifier_id"), "verifier id")
                _check_id(entry.get("proposal_id"), "proposal id")
                _check_text(entry.get("domain"), "domain", MAX_DOMAIN_CHARS)
                _check_text(entry.get("content"), "content",
                            MAX_CONTENT_CHARS, allow_newline=True)
                _check_text(entry.get("source"), "source", MAX_REF_CHARS)
                _check_text(entry.get("evidence_ref"), "evidence_ref",
                            MAX_REF_CHARS)
            except MemoryError as exc:
                bad(str(exc))
            if entry.get("kind") not in KINDS:
                bad("unknown entry kind")
            if entry["id"] in seen_ids:
                bad("duplicate entry id")
            seen_ids.add(entry["id"])
            if entry["proposal_id"] in seen_proposals:
                bad("duplicate proposal id")
            seen_proposals.add(entry["proposal_id"])
            if entry["verifier_id"] == entry["author"]:
                bad("verifier must differ from author")
            if not _is_int(entry.get("seq")) or entry["seq"] != position:
                bad("entry seq is not contiguous from 1")
            stamp = entry.get("created_at")
            if not isinstance(stamp, str) or not stamp:
                bad("bad created_at")
            else:
                try:
                    parsed = datetime.fromisoformat(
                        stamp.replace("Z", "+00:00"))
                except ValueError:
                    bad("bad created_at")
                else:
                    if parsed.tzinfo is None:
                        bad("created_at must be timezone-aware")
            if entry["content_hash"] != _content_hash(entry):
                raise TamperDetectedError(
                    f"content hash mismatch for entry {entry['id']}")
            if entry["prev_hash"] != prev_hash:
                bad("entry chain is broken")
            if entry["entry_hash"] != _entry_hash(entry):
                bad("entry hash mismatch")
            prev_hash = entry["entry_hash"]
            by_id[entry["id"]] = entry
            target = entry.get("supersedes")
            if target is not None:
                try:
                    _check_id(target, "supersedes")
                except MemoryError as exc:
                    bad(str(exc))
                if target not in by_id or by_id[target]["seq"] >= entry["seq"]:
                    bad("supersedes must name an earlier entry")
                if (by_id[target]["domain"] != entry["domain"]
                        or by_id[target]["kind"] != entry["kind"]):
                    bad("supersedes crosses domain or kind")
                if target in superseded_by:
                    bad("entry superseded by more than one entry")
                superseded_by[target] = entry["id"]
        heads = {}
        for entry in entries:
            if entry["id"] in superseded_by:
                continue
            slot = (entry["domain"], entry["kind"])
            if slot in heads:
                bad("two current entries share a domain and kind")
            heads[slot] = entry["id"]
        # Files carrying the security_mode field validate only
        # against the new digest (which covers the field); legacy
        # files without it validate against the legacy computation
        # and are upgraded on save. See _state_digest.
        if data.get("state_digest") != _digest_for(data):
            bad("state digest mismatch")

    @_serialised
    def save(self) -> None:
        with self._locked():
            self._save_locked()

    def _save_locked(self) -> None:
        if self._disk_changed():
            raise CorruptMemoryError(
                "memory changed on disk since this instance loaded it; "
                "refusing to overwrite newer state")
        self._state["state_digest"] = _state_digest(self._state)
        self._validate(self._state)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2,
                             allow_nan=False).encode("utf-8")
        if len(payload) > MAX_MEMORY_BYTES:
            raise MemoryError("memory exceeds size cap")
        fd, tmp = tempfile.mkstemp(dir=self.memory_dir,
                                   prefix=".memory-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            if self._lock_fd is not None and (
                    os.stat(self.memory_dir).st_ino
                    != os.fstat(self._lock_fd).st_ino):
                raise CorruptMemoryError(
                    "memory directory was replaced during save")
            os.replace(tmp, self.memory_path)
            dir_fd = os.open(self.memory_dir, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            # Only now is the new state durable: if anything above
            # raised after the replace, _disk_digest still names the
            # OLD state, so this instance reads as stale and refuses
            # further saves rather than rolling back over an entry
            # that did reach disk.
            self._disk_digest = self._state["state_digest"]
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- derived views -----------------------------------------------------

    def _superseded_ids(self) -> set:
        return {e["supersedes"] for e in self._state["entries"]
                if e["supersedes"] is not None}

    def _current_entries(self) -> list:
        superseded = self._superseded_ids()
        return [e for e in self._state["entries"]
                if e["id"] not in superseded]

    # -- writes ------------------------------------------------------------

    @_serialised
    def _mint_signed_commit_permit(self, content_hash) -> _SignedCommitPermit:
        """Mint a one-shot signed-commit permit bound to one entry's
        content hash and to this store instance.

        ONLY signing.commit_signed may call this, and only after it
        has verified the envelope MAC (and any presented
        attestation) for that exact entry. The permit is registered
        in this instance's outstanding set and consumed by
        _commit_gated on presentation. This is an in-codebase
        handshake, not a capability boundary against arbitrary
        same-process code: any in-process caller CAN call this
        method, but no code path other than the verified
        commit_signed flow does, and a forged or absent envelope
        fails inside commit_signed before a permit is minted.
        """
        if not isinstance(content_hash, str) \
                or not _HEX64_RE.fullmatch(content_hash):
            raise MemoryError(
                "permit content hash must be a lowercase hex64 string")
        nonce = secrets.token_hex(32)
        self._outstanding_permits[nonce] = content_hash
        return _SignedCommitPermit(nonce, content_hash, self._store_token)

    def _consume_signed_commit_permit(self, permit, content_hash) -> None:
        """Validate and consume (single-use) a signed-commit permit
        for an entry with the given content hash. Raises MemoryError
        on any mismatch; on success the permit can never be used
        again, even if the surrounding commit later fails."""
        if not isinstance(permit, _SignedCommitPermit):
            raise MemoryError(
                "signed_only store: _commit_gated requires a one-shot "
                "signed-commit permit minted by the verified "
                "signing.commit_signed path; a GateDecision alone, "
                "however well-formed, does not authorise a commit "
                "on a signed store")
        if permit._store_token != self._store_token:
            raise MemoryError(
                "signed-commit permit was minted for a different store")
        registered = self._outstanding_permits.get(permit._nonce)
        if registered is None:
            raise MemoryError(
                "signed-commit permit is unknown or already used "
                "(permits are single-use)")
        if registered != content_hash \
                or permit._content_hash != content_hash:
            raise MemoryError(
                "signed-commit permit is bound to a different "
                "entry content hash")
        del self._outstanding_permits[permit._nonce]

    def commit_write(self, entry_fields, decision) -> dict:
        """Plain commit path. On a signed_only store this refuses:
        commits must arrive via signing.commit_signed, which
        verifies the envelope and then calls _commit_gated. On a
        default store it is exactly the gated commit below."""
        if self._signed_only:
            raise MemoryError(
                "signed_only store: unsigned commits are refused; "
                "use signing.commit_signed with a verified envelope")
        return self._commit_gated(entry_fields, decision)

    @_serialised
    def _commit_gated(self, entry_fields, decision, *,
                      expected_state_digest=None, permit=None) -> dict:
        """Commit one entry, authorised by an accepted gate decision.

        Internal delegate: commit_write calls this on plain stores,
        signing.commit_signed calls it after envelope verification.
        When expected_state_digest is given, the store's current
        state digest must equal it — checked here, under the same
        lock hold as the mutation, so the decide-to-commit epoch
        check cannot be raced by another commit on this instance.

        Permit handshake: on a signed_only store this ALSO requires
        a valid one-shot permit (see _mint_signed_commit_permit),
        which is validated and consumed once the decision has been
        shown to be bound to this entry. A direct call presenting
        only a GateDecision — the CRITICAL-1 probe — raises
        MemoryError and commits nothing. On an unsigned store no
        permit is required and the path is exactly as before.

        entry_fields carries exactly the proposer's fields (id,
        domain, kind, content, author, source, evidence_ref,
        proposal_id, verifier_id, supersedes); the store assigns seq,
        created_at and all hashes. The decision must be a real
        GateDecision, accepted and internally consistent (no reasons,
        regressions, forgetting failures or protected violations),
        and bound to this entry by proposal id, verifier id, and the
        content-hash segment decide_write stamps into its
        verifier_note.

        Validation failures raise MemoryError and persist nothing.
        A save refused because this instance is stale raises
        CorruptMemoryError instead (and persists nothing new); the
        instance stays stale and must be reconstructed. Note the
        module docstring: on an UNSIGNED store a hand-built
        GateDecision that satisfies every check also commits —
        consistency is checked here, provenance is a process
        property. On a signed_only store that is no longer true:
        the permit handshake above is additionally required.
        """
        fields = _validate_fields(entry_fields)
        supersedes = fields["supersedes"]

        if not isinstance(decision, GateDecision):
            raise MemoryError("decision must be a GateDecision")
        if decision.accepted is not True:
            raise MemoryError("gate decision did not accept this write")
        if (decision.reasons or decision.regressions
                or decision.forgetting_failures
                or decision.protected_violations):
            raise MemoryError(
                "gate decision is internally inconsistent: an accepted "
                "decision carries no failure records")
        if decision.proposal_id != fields["proposal_id"]:
            raise MemoryError("decision proposal_id does not match the entry")
        if decision.verifier_id != fields["verifier_id"]:
            raise MemoryError("decision verifier_id does not match the entry")
        note = decision.verifier_note
        first_segment = (note.split(";", 1)[0].strip()
                         if isinstance(note, str) else "")
        if first_segment != _binding_for(fields):
            raise MemoryError(
                "decision is not bound to this entry's content hash")
        if self._signed_only:
            # Signed stores: the decision alone is not enough — a
            # one-shot permit from the verified commit_signed path
            # must be presented and is consumed here.
            self._consume_signed_commit_permit(
                permit, _content_hash(fields))
        if fields["verifier_id"] == fields["author"]:
            raise MemoryError("verifier must differ from author")
        if expected_state_digest is not None \
                and self.state_digest() != expected_state_digest:
            raise MemoryError(
                "store state moved since the decision was made "
                "(state digest mismatch)")

        entries = self._state["entries"]
        if len(entries) >= MAX_ENTRIES:
            raise MemoryError("entry cap reached")
        if any(e["id"] == fields["id"] for e in entries):
            raise MemoryError(f"duplicate entry id: {fields['id']}")
        if any(e["proposal_id"] == fields["proposal_id"] for e in entries):
            raise MemoryError(
                f"proposal id already used: {fields['proposal_id']}")
        current = {e["id"]: e for e in self._current_entries()}
        if supersedes is not None:
            if supersedes == fields["id"]:
                raise MemoryError("an entry cannot supersede itself")
            target = current.get(supersedes)
            if target is None:
                raise MemoryError(
                    "supersedes must name an existing current entry")
            if (target["domain"] != fields["domain"]
                    or target["kind"] != fields["kind"]):
                raise MemoryError(
                    "supersedes must stay within the same domain and kind")
        else:
            for e in current.values():
                if (e["domain"] == fields["domain"]
                        and e["kind"] == fields["kind"]):
                    raise MemoryError(
                        "a current entry already covers this domain and "
                        "kind; supersede it instead")

        entry = dict(fields)
        entry["seq"] = len(entries) + 1
        entry["created_at"] = _now()
        entry["prev_hash"] = (entries[-1]["entry_hash"]
                              if entries else GENESIS_HASH)
        entry["content_hash"] = _content_hash(entry)
        entry["entry_hash"] = _entry_hash(entry)
        snapshot = copy.deepcopy(self._state)
        try:
            self._state["entries"].append(entry)
            self._state["entry_seq"] = len(self._state["entries"])
            self.save()
        except BaseException:
            self._state = snapshot
            raise
        return copy.deepcopy(entry)

    # -- reads ---------------------------------------------------------------

    @_serialised
    def retrieve(self, domain=None, kind=None, *, limit=None) -> list:
        """Current entries only, in commit order, as deep copies.

        Filters are exact-match and ANDed; no match is an empty list,
        never an error. Reads are not logged and never mutate state:
        memory content is the agent's own, not sealed material.
        """
        if domain is not None:
            _check_text(domain, "domain", MAX_DOMAIN_CHARS)
        if kind is not None and kind not in KINDS:
            raise MemoryError(f"kind must be one of {KINDS}")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise MemoryError("limit must be a positive int")
        out = [copy.deepcopy(e) for e in self._current_entries()
               if (domain is None or e["domain"] == domain)
               and (kind is None or e["kind"] == kind)]
        if limit is not None:
            out = out[:limit]
        return out

    @_serialised
    def list_current(self) -> list:
        """All current entries — retrieve() with no filters."""
        return self.retrieve()

    @_serialised
    def get(self, entry_id) -> dict:
        """One entry by id, current or not, with a computed flag."""
        _check_id(entry_id, "entry id")
        superseded = self._superseded_ids()
        for e in self._state["entries"]:
            if e["id"] == entry_id:
                out = copy.deepcopy(e)
                out["current"] = e["id"] not in superseded
                return out
        raise MemoryError(f"unknown memory entry: {entry_id}")

    @_serialised
    def history(self, entry_id=None) -> list:
        """Audit view: all entries, or one supersession chain.

        With an id, returns the chain containing it, oldest to
        newest. Audit only — solver code must never read memory
        through here, or superseded lessons re-enter by the back
        door.
        """
        superseded = self._superseded_ids()

        def view(e):
            out = copy.deepcopy(e)
            out["current"] = e["id"] not in superseded
            return out

        if entry_id is None:
            return [view(e) for e in self._state["entries"]]
        _check_id(entry_id, "entry id")
        by_id = {e["id"]: e for e in self._state["entries"]}
        if entry_id not in by_id:
            raise MemoryError(f"unknown memory entry: {entry_id}")
        head = by_id[entry_id]
        while head["supersedes"] is not None:
            head = by_id[head["supersedes"]]
        chain = [head]
        successor = {e["supersedes"]: e for e in self._state["entries"]
                     if e["supersedes"] is not None}
        while chain[-1]["id"] in successor:
            chain.append(successor[chain[-1]["id"]])
        return [view(e) for e in chain]

    @_serialised
    def state_digest(self) -> str:
        """The current state digest, for external anchoring."""
        return self._state["state_digest"]

    @_serialised
    def chain_head(self) -> str:
        """The last entry's hash (GENESIS_HASH when empty)."""
        entries = self._state["entries"]
        return entries[-1]["entry_hash"] if entries else GENESIS_HASH
