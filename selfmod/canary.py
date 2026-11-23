"""Canary self-modification manager: one change at a time, staged in a
copy, committed only on a verified gate decision, rollback to the last
verified state.

Standard library only. No network access. This module never imports or
executes candidate code: staging copies files, verification is the
caller's job (out-of-process if it runs code at all), and this manager
only checks that the decision and the staged bytes are consistent.

How it works
------------
- stage(proposal, decision): validate the proposal (canonicalised
  repo-relative paths, budgets, protected scope), snapshot the exact
  pre-image of every touched path, copy the whole target tree into a
  canary directory outside the tree, apply the change there only, and
  journal the staged state. The live tree is byte-identical after
  staging, by construction and by test.
- mark_verified(proposal_id): the caller attests the canary passed
  its checks (tests, sealed re-run, golden re-run). This is a trusted
  input: this module records the attestation, it does not perform it.
- commit(proposal_id): only from VERIFIED. Re-validates the gate
  decision stored at stage time against the candidate bytes read
  from the canary copy (recomputed root hash must equal the staged
  root hash — a tampered canary file, or a symlink planted in the
  canary, is refused before any live write), re-runs the protected
  check, and re-checks that the live tree still matches the snapshot
  pre-image in bytes AND mode (drift = refuse, nothing written).
  Each file is re-resolved and re-checked immediately before its
  replace, then applied with temp-write + fsync + os.replace,
  journaling progress before the first live write so a crash
  mid-commit is recoverable. Post-apply, every changed path's live
  hash must equal the staged candidate hash or the change is
  rolled back. (Verification covers the changed paths, not a full
  tree manifest.)
- rollback(proposal_id, reason): from STAGED/VERIFIED it discards the
  canary (live was never touched); from COMMITTING/COMMITTED it
  restores the pre-image byte-exactly (created files are removed,
  modified files restored, mode bits restored and verified) and
  prunes only parent directories that did not exist before staging.
- abort(proposal_id, reason): from STAGED/VERIFIED, discards the
  canary and ends the proposal without touching the live tree.
- Recovery: the constructor refuses to operate on a journal left in
  COMMITTING state (NeedsRecoveryError). The classmethod
  CanaryManager.recover_journal(root, journal_dir) is the recovery
  entry point: it restores the pre-image and marks the proposal
  ROLLED_BACK with reason "crash_recovery". Recovery is explicit,
  never silent. A missing snapshot during recovery raises
  CorruptJournalError — fail-closed, human required.

Gate binding
------------
commit requires the GateDecision presented at stage time to be a real
eval.gate.GateDecision with accepted=True, proposal_id matching the
proposal, empty reasons/regressions/forgetting_failures/
protected_violations, a named verifier, and a verifier_note whose
first segment is "content-hash:<candidate root hash>" — the same
binding pattern the memory store uses. The decision's fields are
stored in the journal at stage time and re-validated at commit
against the recomputed candidate root hash, so a decision issued
for one candidate cannot be redirected to different bytes by
tampering with the canary copy. The decision is single-use: it is
consumed by commit, rollback or abort. The root hash binds only
(path, new bytes) pairs — not the tree identity, the pre-image, the
author or file modes — so a decision is portable to another tree
with the same proposal id and candidate bytes; that portability is
a known limit, not a guarantee.

Protected scope
---------------
Tier A (the gate's, authoritative): check_protected_paths refuses any
path under eval/ and exactly core/loop.py, oversight/__init__.py,
oversight/approval.py, trust/__init__.py and trust/pathpolicy.py
(the last four added in cycle 19: the canonicaliser chain the gate's
verdict trusts, plus the package __init__ files on its import path).
Paths are canonicalised
BEFORE that check (backslashes and duplicate separators collapsed,
"." segments dropped); this local canonicalisation is now redundant
defence-in-depth, since the gate's adoption of path-policy/1 in
cycle 13 means the gate itself also judges canonical spellings
such as core/./loop.py. Any ".." segment is refused
outright, which is stronger than canonicalise-then-match. Tier B
(local policy, labelled as ours, not the gate's): selfmod/, .git/
and state/ are also refused, including a bare file named exactly
"selfmod", ".git", "state" or "eval" — a self-change may not weaken
its own manager, and extending the gate's list is a human-gated
protected change, not something this module smuggles in.

Honest limits (stated, not hidden)
----------------------------------
- Forged decisions (A30 class): GateDecision is an unsigned frozen
  dataclass. This module refuses decision objects that are not real
  GateDecision instances and binds a genuine decision to exact bytes,
  but in-process code that can construct a GateDecision with a
  correct content-hash note can still forge acceptance. The gate
  checks consistency, not provenance; closing this needs signed
  decisions (backlog: signed-gate-decisions) and an out-of-process
  sealed runner. This manager is a guardrail against self-deception,
  pipeline bugs and accidental regressions — not a security boundary
  against code with process/filesystem access.
- The canary is a directory copy, not a sandbox: if the caller
  executes staged code in-process it runs with the caller's rights.
- Rollback restores files only. Side effects a committed change
  already caused outside the tree (network, other stores, learned
  state) are irreversible; proposals with external effects are out
  of scope for this manager entirely.
- Deletion is NOT supported in v1: a FileChange with new_bytes=None
  is refused. Rename is delete+create and inherits the refusal.
- A whole tree+journal rollback together loads cleanly: hashes
  detect tamper only against the journal's own chain, whose head is
  not externally anchored in v1.
- Timestamps are UTC host-clock assertions; their form is not
  validated on journal load, and ordering is by journal sequence
  number, never by timestamp.
- Multi-file commit is not atomic. It is made recoverable instead:
  write-ahead journal, per-file atomic replace, applied-files list
  persisted as each file lands, and mandatory recovery before any
  new work after a mid-commit crash. The per-file re-check narrows
  the drift race but does not eliminate it: a concurrent writer who
  changes a file in the instant between its re-check and its
  replace can still be overwritten. This manager assumes a single
  writer process; it takes no file lock, and two managers on one
  journal can race.
- Retention and growth: snapshots and canary copies are kept after
  commit (rollback needs them) and are never pruned by this module,
  so the journal directory grows by a full tree copy per proposal.
  The journal itself is capped at MAX_JOURNAL_ENTRIES entries and
  every transition appends one, so the manager has a finite
  lifetime of roughly a few dozen proposals before a graceful
  CanaryError refuses new proposals; compaction is future work.
  Staging reserves headroom for the proposal's whole lifecycle and
  lifecycle transitions are exempt from the soft cap (a higher hard
  cap still bounds the file), so the cap can never strand a
  proposal mid-commit or make recovery impossible. Non-regular
  files (FIFOs, sockets, devices) anywhere in the target tree are
  refused at stage time — reading one could block or fail raw.
- File modes cannot be changed by a change: existing files keep
  their pre-image mode, and created files are always mode 0o644.
  A change that needs an executable file cannot express it in v1.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from eval.gate import GateDecision, check_protected_paths

SCHEMA_VERSION = 1
MAX_FILES_PER_CHANGE = 8
MAX_FILE_BYTES = 64 * 1024
MAX_CHANGE_BYTES = 256 * 1024
MAX_TREE_BYTES = 20 * 1024 * 1024
MAX_TREE_FILES = 2000
MAX_JOURNAL_ENTRIES = 200
# Transitions of an already-staged proposal (verify, committing,
# committed, rolled back, recovery) are exempt from the soft cap so a
# lifecycle can never brick itself mid-commit; the hard cap is the
# absolute load limit and leaves slack for those transitions.
HARD_JOURNAL_ENTRIES = MAX_JOURNAL_ENTRIES + 64
MAX_TEXT = 2000

PROPOSAL_STATES = (
    "STAGED", "VERIFIED", "COMMITTING", "COMMITTED",
    "ROLLED_BACK", "ABORTED",
)
TERMINAL_STATES = ("COMMITTED", "ROLLED_BACK", "ABORTED")
LOCAL_PROTECTED_PREFIXES = ("selfmod/", ".git/", "state/")
LOCAL_PROTECTED_FILES = ()
PROTECTED_FIRST_COMPONENTS = ("eval", "selfmod", ".git", "state")

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_BAD_CHARS = set("\u200b\u200c\u200d\ufeff\u202a\u202b\u202c\u202d\u202e\u2060")


class CanaryError(ValueError):
    """Raised when a canary operation is refused."""


class CorruptJournalError(CanaryError):
    """Raised when the persisted journal cannot be trusted."""


class NeedsRecoveryError(CanaryError):
    """Raised when a journal was left mid-commit; call recover()."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CanaryError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryError(f"{field} must be non-empty text")
    if len(value) > MAX_TEXT:
        raise CanaryError(f"{field} exceeds {MAX_TEXT} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) == "Cs"
                or unicodedata.category(ch) == "Cf"
                or (code < 32 and ch not in "\t\n") or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise CanaryError(f"{field} contains control or invisible characters")
    return value


def canonicalise_path(value) -> str:
    """Normalise a repo-relative path or refuse it.

    Collapses backslashes, duplicate separators and "." segments, and
    refuses absolute paths, ".." segments, empty paths and NUL bytes,
    so protected-scope checks cannot be evaded by spelling.
    """
    if not isinstance(value, str) or not value.strip():
        raise CanaryError("path must be non-empty text")
    if "\x00" in value:
        raise CanaryError("path contains a NUL byte")
    path = value.strip().replace("\\", "/")
    if path.startswith("/") or re.match(r"^[a-zA-Z]:/", path):
        raise CanaryError(f"path must be repo-relative: {value!r}")
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise CanaryError(f"path escapes the tree: {value!r}")
        parts.append(part)
    if not parts:
        raise CanaryError(f"path must name a file: {value!r}")
    return "/".join(parts)


def _check_protected(canonical_paths) -> None:
    offenders = check_protected_paths(list(canonical_paths))
    if offenders:
        raise CanaryError(f"protected path (gate scope): {offenders[0]}")
    for path in canonical_paths:
        if path.split("/")[0] in PROTECTED_FIRST_COMPONENTS:
            raise CanaryError(f"protected path (local policy): {path}")
        if path in LOCAL_PROTECTED_FILES or any(
                path.startswith(p) for p in LOCAL_PROTECTED_PREFIXES):
            raise CanaryError(f"protected path (local policy): {path}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _candidate_root_hash(changes) -> str:
    lines = ["selfmod-candidate-v1"]
    for change in sorted(changes, key=lambda c: c.path):
        lines.append(f"{change.path}\0{_sha256(change.new_bytes)}\0{len(change.new_bytes)}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _manifest_hash(manifest: dict) -> str:
    lines = ["selfmod-manifest-v1"]
    for path in sorted(manifest):
        entry = manifest[path]
        if entry is None:
            lines.append(f"{path}\0ABSENT")
        else:
            lines.append(f"{path}\0{entry['sha256']}\0{entry['size']}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FileChange:
    path: str
    new_bytes: bytes | None  # None means deletion: refused in v1


@dataclass(frozen=True)
class ChangeProposal:
    proposal_id: str
    author: str
    changes: tuple


@dataclass(frozen=True)
class ApplyResult:
    proposal_id: str
    applied: tuple
    candidate_root_hash: str


class CanaryManager:
    """One active proposal, journaled, over one target tree."""

    @classmethod
    def recover_journal(cls, root, journal_dir) -> dict:
        """Recovery entry point for a journal left mid-commit.

        The regular constructor refuses such a journal, so recovery
        cannot be an ordinary instance method call; this classmethod
        builds the instance past the guard, runs recover(), and
        returns the resulting journal entry.
        """
        instance = cls.__new__(cls)
        instance.root = Path(root).resolve()
        instance.journal_dir = Path(journal_dir).resolve()
        if not instance.root.is_dir():
            raise CanaryError("root must be an existing directory")
        instance.journal_dir.mkdir(parents=True, exist_ok=True)
        instance.journal_path = instance.journal_dir / "journal.json"
        instance.snapshot_dir = instance.journal_dir / "snapshots"
        instance.canary_dir = instance.journal_dir / "canary"
        instance.journal = instance._load()
        return instance.recover()

    def __init__(self, root, journal_dir):
        self.root = Path(root).resolve()
        self.journal_dir = Path(journal_dir).resolve()
        if not self.root.is_dir():
            raise CanaryError("root must be an existing directory")
        if self.journal_dir == self.root or self.root in self.journal_dir.parents \
                or self.journal_dir in self.root.parents:
            raise CanaryError("journal_dir must be outside the target tree")
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.journal_dir / "journal.json"
        self.snapshot_dir = self.journal_dir / "snapshots"
        self.canary_dir = self.journal_dir / "canary"
        self.journal = self._load()
        active = self._active_entry()
        if active is not None and active["state"] == "COMMITTING":
            raise NeedsRecoveryError(
                "journal left mid-commit; call recover() before new work")

    # -- persistence ---------------------------------------------------

    def _fresh(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "seq": 0,
                "entries": [], "used_proposal_ids": [], "digest": ""}

    def _entry_hash(self, entry: dict, prev_hash: str) -> str:
        payload = {k: entry[k] for k in entry if k != "entry_hash"}
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
        return hashlib.sha256(prev_hash.encode() + b"\n" + blob).hexdigest()

    def _compute_digest(self, journal: dict) -> str:
        payload = {k: journal[k] for k in journal if k != "digest"}
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _load(self) -> dict:
        if not self.journal_path.exists():
            return self._fresh()
        raw = self.journal_path.read_bytes()
        if len(raw) > 5 * 1024 * 1024:
            raise CorruptJournalError("journal exceeds size cap")
        try:
            data = json.loads(raw.decode("utf-8"),
                              parse_constant=self._reject_constant,
                              parse_float=self._parse_float,
                              object_pairs_hook=self._no_dup_keys)
        except CorruptJournalError:
            raise
        except Exception as exc:
            self._quarantine(raw)
            raise CorruptJournalError(f"unreadable journal: {exc}") from exc
        self._validate(data)
        return data

    @staticmethod
    def _reject_constant(value):
        raise CorruptJournalError(f"non-finite number in journal: {value}")

    @staticmethod
    def _parse_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise CorruptJournalError(f"non-finite number in journal: {text}")
        return value

    @staticmethod
    def _no_dup_keys(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise CorruptJournalError(f"duplicate journal key: {key}")
            out[key] = value
        return out

    def _quarantine(self, raw: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            (self.journal_dir / f"journal.corrupt-{stamp}.json").write_bytes(raw)
        except OSError:
            pass

    def _validate(self, data) -> None:
        def bad(msg):
            raise CorruptJournalError(msg)
        if not isinstance(data, dict):
            bad("journal is not an object")
        if set(data) != {"schema_version", "seq", "entries", "used_proposal_ids", "digest"}:
            bad("journal keys mismatch")
        if data["schema_version"] != SCHEMA_VERSION or not _is_int(data["schema_version"]):
            bad("unsupported schema_version")
        if not _is_int(data["seq"]) or data["seq"] < 0:
            bad("bad seq")
        if not isinstance(data["entries"], list) or len(data["entries"]) > HARD_JOURNAL_ENTRIES:
            bad("bad entries")
        if not isinstance(data["used_proposal_ids"], list):
            bad("bad used_proposal_ids")
        prev = ""
        active_count = 0
        for i, entry in enumerate(data["entries"]):
            if not isinstance(entry, dict):
                bad("entry is not an object")
            if entry.get("seq") != i + 1:
                bad("entry seq gap")
            if entry.get("state") not in PROPOSAL_STATES:
                bad("unknown entry state")
            for key in ("proposal_id", "author", "candidate_root_hash",
                        "changed_paths", "candidate_hashes", "preimage",
                        "applied_files", "verifier_id", "decision_note",
                        "decision_evaluated_at", "preexisting_dirs",
                        "reason", "created_at", "updated_at"):
                if key not in entry:
                    bad(f"entry missing field: {key}")
            if not isinstance(entry["changed_paths"], list) or \
                    not isinstance(entry["candidate_hashes"], dict) or \
                    not isinstance(entry["preimage"], dict) or \
                    not isinstance(entry["applied_files"], list) or \
                    not isinstance(entry["preexisting_dirs"], list):
                bad("entry field has wrong type")
            if entry.get("entry_hash") != self._entry_hash(entry, prev):
                bad("entry hash chain break")
            prev = entry["entry_hash"]
        latest = {}
        for entry in data["entries"]:
            latest[entry["proposal_id"]] = entry["state"]
        active_count = sum(1 for s in latest.values() if s not in TERMINAL_STATES)
        if active_count > 1:
            bad("more than one active proposal in journal")
        if data["seq"] != len(data["entries"]):
            bad("seq does not match entries")
        if data["entries"] and data["digest"] != self._compute_digest(data):
            bad("journal digest mismatch")
        seen = [e["proposal_id"] for e in data["entries"]]
        if sorted(data["used_proposal_ids"]) != sorted(set(seen)):
            bad("used_proposal_ids mismatch")

    def _save(self) -> None:
        self.journal["digest"] = self._compute_digest(self.journal)
        self._validate(self.journal)
        payload = json.dumps(self.journal, ensure_ascii=False, indent=2,
                             allow_nan=False).encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=self.journal_dir, prefix=".journal-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.journal_path)
            dir_fd = os.open(self.journal_dir, os.O_DIRECTORY)
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

    def _append(self, entry: dict) -> dict:
        if len(self.journal["entries"]) >= HARD_JOURNAL_ENTRIES:
            raise CanaryError(
                "journal hard entry cap reached; compaction is required")
        if entry.get("state") == "STAGED" and \
                len(self.journal["entries"]) >= MAX_JOURNAL_ENTRIES:
            raise CanaryError(
                "journal entry cap reached; compaction is required "
                "before new proposals (documented lifetime limit)")
        entry = dict(entry)
        entry["seq"] = len(self.journal["entries"]) + 1
        prev = self.journal["entries"][-1]["entry_hash"] if self.journal["entries"] else ""
        entry["entry_hash"] = self._entry_hash(entry, prev)
        self.journal["entries"].append(entry)
        self.journal["seq"] = entry["seq"]
        if entry["proposal_id"] not in self.journal["used_proposal_ids"]:
            self.journal["used_proposal_ids"].append(entry["proposal_id"])
        self._save()
        return entry

    def _transition(self, entry: dict, new_state: str, **extra) -> dict:
        """Record a state transition as a new chained journal entry."""
        new_entry = {k: copy.deepcopy(v) for k, v in entry.items()
                     if k not in ("seq", "entry_hash")}
        new_entry["state"] = new_state
        new_entry["updated_at"] = _now()
        new_entry.update(extra)
        return self._append(new_entry)

    # -- helpers ---------------------------------------------------------

    def _active_entry(self):
        seen = set()
        for entry in reversed(self.journal["entries"]):
            if entry["proposal_id"] in seen:
                continue
            seen.add(entry["proposal_id"])
            if entry["state"] not in TERMINAL_STATES:
                return entry
        return None

    def _latest_entry(self, proposal_id: str):
        for entry in reversed(self.journal["entries"]):
            if entry["proposal_id"] == proposal_id:
                return entry
        return None

    def _resolve_in_tree(self, canonical: str) -> Path:
        target = (self.root / canonical)
        # Refuse symlinks in any existing component of the path.
        cursor = self.root
        for part in canonical.split("/"):
            cursor = cursor / part
            if cursor.is_symlink():
                raise CanaryError(f"symlink in path: {canonical}")
        resolved = target.resolve()
        if resolved != self.root and self.root not in resolved.parents \
                and not str(resolved).startswith(str(self.root) + os.sep):
            raise CanaryError(f"path escapes the tree: {canonical}")
        return target

    def _read_tree_file(self, canonical: str):
        target = self._resolve_in_tree(canonical)
        if not target.exists():
            return None
        if not target.is_file():
            raise CanaryError(f"not a regular file: {canonical}")
        data = target.read_bytes()
        mode = stat.S_IMODE(target.stat().st_mode)
        return {"sha256": _sha256(data), "size": len(data), "mode": mode,
                "data": data}

    def _tree_manifest(self) -> dict:
        manifest = {}
        total = 0
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames.sort()
            for name in sorted(dirnames):
                if (Path(dirpath) / name).is_symlink():
                    raise CanaryError("symlink in target tree")
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.is_symlink():
                    raise CanaryError("symlink in target tree")
                if not stat.S_ISREG(path.lstat().st_mode):
                    # A FIFO would block read_bytes forever; a socket
                    # or device raises raw OSError. Refuse cleanly.
                    raise CanaryError(f"non-regular file in target tree: {path}")
                rel = path.relative_to(self.root).as_posix()
                data = path.read_bytes()
                total += len(data)
                count += 1
                if total > MAX_TREE_BYTES or count > MAX_TREE_FILES:
                    raise CanaryError("target tree exceeds canary cap")
                manifest[rel] = {"sha256": _sha256(data), "size": len(data),
                                 "mode": stat.S_IMODE(path.stat().st_mode)}
        return manifest

    def _write_file_atomic(self, target: Path, data: bytes, mode: int) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".canary-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, target)
            dir_fd = os.open(target.parent, os.O_DIRECTORY)
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

    def _snapshot_preimage(self, proposal_id: str, preimage: dict) -> None:
        snap = self.snapshot_dir / proposal_id
        if snap.exists():
            raise CanaryError("snapshot already exists for proposal")
        snap.mkdir(parents=True)
        for path, entry in preimage.items():
            if entry is None:
                continue
            dest = snap / path
            self._write_file_atomic(dest, entry["data"], entry["mode"])

    def _load_preimage(self, entry: dict) -> dict:
        snap = self.snapshot_dir / entry["proposal_id"]
        preimage = {}
        for path, meta in entry["preimage"].items():
            if meta is None:
                preimage[path] = None
            else:
                snap_file = snap / path
                if not snap_file.is_file():
                    raise CorruptJournalError(f"snapshot missing: {path}")
                data = snap_file.read_bytes()
                if _sha256(data) != meta["sha256"]:
                    raise CorruptJournalError(f"snapshot tamper: {path}")
                preimage[path] = {"sha256": meta["sha256"], "size": meta["size"],
                                  "mode": meta["mode"], "data": data}
        return preimage

    # -- public API ------------------------------------------------------

    def status(self):
        active = self._active_entry()
        return copy.deepcopy(active) if active is not None else None

    def history(self):
        return copy.deepcopy(self.journal["entries"])

    def stage(self, proposal: ChangeProposal, decision) -> dict:
        if self._active_entry() is not None:
            raise CanaryError("another proposal is already active (one at a time)")
        if not isinstance(proposal, ChangeProposal):
            raise CanaryError("proposal must be a ChangeProposal")
        proposal_id = _check_id(proposal.proposal_id, "proposal id")
        _check_id(proposal.author, "author")
        if proposal_id in self.journal["used_proposal_ids"]:
            raise CanaryError("proposal_id already used (single-use)")
        if isinstance(proposal.changes, (str, bytes)) or \
                not isinstance(proposal.changes, (list, tuple)):
            raise CanaryError("changes must be a list of FileChange")
        if not proposal.changes:
            raise CanaryError("empty change set")
        if len(proposal.changes) > MAX_FILES_PER_CHANGE:
            raise CanaryError("change exceeds file budget")

        changes = []
        seen = set()
        total = 0
        for raw in proposal.changes:
            if not isinstance(raw, FileChange):
                raise CanaryError("changes must be FileChange entries")
            path = canonicalise_path(raw.path)
            if path in seen:
                raise CanaryError(f"duplicate path in change: {path}")
            seen.add(path)
            if raw.new_bytes is None:
                raise CanaryError("deletion_not_supported_in_v1")
            if not isinstance(raw.new_bytes, bytes):
                raise CanaryError("new_bytes must be bytes")
            if len(raw.new_bytes) > MAX_FILE_BYTES:
                raise CanaryError(f"file exceeds byte budget: {path}")
            total += len(raw.new_bytes)
            changes.append(FileChange(path, raw.new_bytes))
        if total > MAX_CHANGE_BYTES:
            raise CanaryError("change exceeds total byte budget")
        _check_protected([c.path for c in changes])

        root_hash = _candidate_root_hash(changes)
        self._check_decision(decision, proposal_id, root_hash)
        # Reserve journal headroom for the whole lifecycle (stage +
        # verify + committing + one per file + terminal + rollback),
        # so the cap can never strand a proposal mid-commit.
        reserve = len(changes) + 5
        if len(self.journal["entries"]) + reserve > MAX_JOURNAL_ENTRIES:
            raise CanaryError(
                "journal entry cap: not enough headroom for this "
                "proposal's lifecycle; compaction is required")
        # Enforce the tree caps before copying anything (war-room R2 F8).
        self._tree_manifest()

        # Snapshot the pre-image and check for no-op changes.
        preimage = {}
        preexisting_dirs = set()
        for change in changes:
            current = self._read_tree_file(change.path)
            if current is not None and current["sha256"] == _sha256(change.new_bytes):
                raise CanaryError(f"no-op change for path: {change.path}")
            preimage[change.path] = (
                None if current is None else
                {"sha256": current["sha256"], "size": current["size"],
                 "mode": current["mode"], "data": current["data"]})
            parent = (self.root / change.path).parent
            while parent != self.root and parent.exists():
                preexisting_dirs.add(parent.relative_to(self.root).as_posix())
                parent = parent.parent

        stored_preimage = {
            path: (None if e is None else
                   {"sha256": e["sha256"], "size": e["size"], "mode": e["mode"]})
            for path, e in preimage.items()}
        candidate_hashes = {c.path: _sha256(c.new_bytes) for c in changes}
        canary_root = self.canary_dir / proposal_id
        snap_preexisting = (self.snapshot_dir / proposal_id).exists()
        canary_preexisting = canary_root.exists()
        try:
            self._snapshot_preimage(proposal_id, preimage)
            # Build the canary copy: full tree copy, change applied there only.
            if canary_root.exists():
                raise CanaryError("canary already exists for proposal")
            canary_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.root, canary_root)
            for change in changes:
                dest = canary_root / change.path
                mode = preimage[change.path]["mode"] if preimage[change.path] else 0o644
                self._write_file_atomic(dest, change.new_bytes, mode)
            entry = self._append({
                "proposal_id": proposal_id,
                "author": proposal.author,
                "state": "STAGED",
                "candidate_root_hash": root_hash,
                "candidate_hashes": candidate_hashes,
                "changed_paths": [c.path for c in changes],
            "preimage": stored_preimage,
            "applied_files": [],
                "verifier_id": decision.verifier_id,
                "decision_note": decision.verifier_note or "",
                "decision_evaluated_at": decision.evaluated_at or "",
                "preexisting_dirs": sorted(preexisting_dirs),
                "reason": "",
                "created_at": _now(),
                "updated_at": _now(),
            })
        except BaseException:
            # A failed stage leaves no orphans and does not burn the id:
            # the journal entry is appended last, so removing what THIS
            # attempt created makes the proposal fully retryable.
            # Anything that existed before the attempt is left alone.
            if not snap_preexisting:
                shutil.rmtree(self.snapshot_dir / proposal_id,
                              ignore_errors=True)
            if not canary_preexisting:
                shutil.rmtree(canary_root, ignore_errors=True)
            raise
        return copy.deepcopy(entry)

    def _check_decision(self, decision, proposal_id: str, root_hash: str) -> None:
        if not isinstance(decision, GateDecision):
            raise CanaryError("decision must be a GateDecision from the gate")
        if decision.accepted is not True:
            raise CanaryError("gate decision did not accept this change")
        if decision.proposal_id != proposal_id:
            raise CanaryError("gate decision is for a different proposal")
        if decision.reasons or decision.regressions or \
                decision.forgetting_failures or decision.protected_violations:
            raise CanaryError("gate decision is internally inconsistent")
        if not decision.verifier_id:
            raise CanaryError("gate decision has no verifier")
        note = decision.verifier_note or ""
        first = note.split(";")[0].strip()
        if first != f"content-hash:{root_hash}":
            raise CanaryError(
                "gate decision is not bound to this candidate's content hash")

    def mark_verified(self, proposal_id: str) -> dict:
        entry = self._require_active(proposal_id, ("STAGED",))
        return copy.deepcopy(self._transition(entry, "VERIFIED"))

    def _read_canary_file(self, entry: dict, path: str) -> bytes:
        canary_root = self.canary_dir / entry["proposal_id"]
        if canary_root.is_symlink():
            raise CanaryError(f"canary copy tampered (symlink): {path}")
        cursor = canary_root
        for part in path.split("/"):
            cursor = cursor / part
            if cursor.is_symlink():
                raise CanaryError(f"canary copy tampered (symlink): {path}")
        canary_file = canary_root / path
        if not canary_file.is_file():
            raise CanaryError(f"canary copy missing: {path}")
        return canary_file.read_bytes()

    def _verify_canary_against_staged(self, entry: dict) -> dict:
        """Canary bytes must hash to the staged candidate, per file and
        in aggregate — never to themselves (war-room cycle-5 F1)."""
        data_by_path = {}
        changes = []
        for path in entry["changed_paths"]:
            data = self._read_canary_file(entry, path)
            if _sha256(data) != entry["candidate_hashes"][path]:
                raise CanaryError(f"canary copy tampered: {path}")
            data_by_path[path] = data
            changes.append(FileChange(path, data))
        if _candidate_root_hash(changes) != entry["candidate_root_hash"]:
            raise CanaryError("canary copy does not match the staged root hash")
        return data_by_path

    def _check_drift(self, entry: dict, path: str) -> None:
        meta = entry["preimage"][path]
        current = self._read_tree_file(path)
        if meta is None:
            if current is not None:
                raise CanaryError(f"drift: file appeared since staging: {path}")
        elif current is None or current["sha256"] != meta["sha256"] \
                or current["mode"] != meta["mode"]:
            raise CanaryError(f"drift: file changed since staging: {path}")

    def commit(self, proposal_id: str) -> ApplyResult:
        entry = self._require_active(proposal_id, ("VERIFIED",))
        preimage = self._load_preimage(entry)
        # Defence in depth at commit time (war-room R3): protected
        # scope re-checked, and the decision stored at stage time
        # re-validated against the recomputed candidate root hash.
        canonical = [canonicalise_path(p) for p in entry["changed_paths"]]
        if canonical != entry["changed_paths"]:
            raise CanaryError("staged paths are not canonical")
        _check_protected(canonical)
        data_by_path = self._verify_canary_against_staged(entry)
        stored_decision = GateDecision(
            True, entry["proposal_id"], (), (), (), entry["verifier_id"],
            entry["decision_evaluated_at"], (), entry["decision_note"])
        self._check_decision(stored_decision, proposal_id,
                              entry["candidate_root_hash"])
        # Drift check: live must still equal the pre-image exactly.
        for path in entry["changed_paths"]:
            self._check_drift(entry, path)
        # Write-ahead: journal COMMITTING before the first live write.
        entry = self._transition(entry, "COMMITTING", applied_files=[])
        applied = []
        try:
            for path in entry["changed_paths"]:
                # Re-resolve and re-check immediately before the
                # replace: a swapped symlink parent or a late drift
                # is refused here, not written through (R2 F4/F5).
                target = self._resolve_in_tree(path)
                self._check_drift(entry, path)
                data = data_by_path[path]
                if _sha256(self._read_canary_file(entry, path)) != \
                        entry["candidate_hashes"][path]:
                    raise CanaryError(f"canary copy tampered: {path}")
                mode = entry["preimage"][path]["mode"] \
                    if entry["preimage"][path] else 0o644
                self._write_file_atomic(target, data, mode)
                applied.append(path)
                entry = self._transition(entry, "COMMITTING",
                                         applied_files=list(applied))
            # Post-apply verify against the STAGED hashes.
            for path in entry["changed_paths"]:
                current = self._read_tree_file(path)
                if current is None or \
                        current["sha256"] != entry["candidate_hashes"][path]:
                    raise CanaryError(f"post-commit verify failed: {path}")
        except BaseException as exc:
            try:
                self._restore_preimage(entry, preimage)
                self._transition(self._latest_entry(proposal_id), "ROLLED_BACK",
                                 reason="commit_failed_auto_rollback")
            except BaseException:
                # Restore itself failed: the journal stays COMMITTING
                # and recover_journal is the documented next step.
                raise CanaryError(
                    f"commit failed and auto-rollback failed: {exc}") from exc
            if isinstance(exc, CanaryError):
                raise
            raise CanaryError(f"commit failed, rolled back: {exc}") from exc
        self._transition(entry, "COMMITTED", applied_files=list(applied))
        return ApplyResult(proposal_id, tuple(applied),
                           entry["candidate_root_hash"])

    def rollback(self, proposal_id: str, reason: str) -> dict:
        _check_text(reason, "rollback reason")
        entry = self._latest_entry(proposal_id)
        if entry is None:
            raise CanaryError(f"unknown proposal: {proposal_id}")
        if entry["state"] in TERMINAL_STATES and entry["state"] != "COMMITTED":
            raise CanaryError(f"proposal already terminal: {entry['state']}")
        if entry["state"] in ("STAGED", "VERIFIED"):
            shutil.rmtree(self.canary_dir / proposal_id, ignore_errors=True)
            return copy.deepcopy(self._transition(entry, "ROLLED_BACK",
                                                  reason=reason))
        if entry["state"] in ("COMMITTING", "COMMITTED"):
            preimage = self._load_preimage(entry)
            self._restore_preimage(entry, preimage)
            return copy.deepcopy(self._transition(
                self._latest_entry(proposal_id), "ROLLED_BACK", reason=reason))
        raise CanaryError(f"cannot roll back from state: {entry['state']}")

    def recover(self) -> dict:
        active = self._active_entry()
        if active is None or active["state"] != "COMMITTING":
            raise CanaryError("nothing to recover")
        preimage = self._load_preimage(active)
        self._restore_preimage(active, preimage)
        return copy.deepcopy(self._transition(
            self._latest_entry(active["proposal_id"]), "ROLLED_BACK",
            reason="crash_recovery"))

    def abort(self, proposal_id: str, reason: str) -> dict:
        _check_text(reason, "abort reason")
        entry = self._require_active(proposal_id, ("STAGED", "VERIFIED"))
        shutil.rmtree(self.canary_dir / proposal_id, ignore_errors=True)
        return copy.deepcopy(self._transition(entry, "ABORTED", reason=reason))

    def _require_active(self, proposal_id: str, states) -> dict:
        _check_id(proposal_id, "proposal id")
        entry = self._latest_entry(proposal_id)
        if entry is None:
            raise CanaryError(f"unknown proposal: {proposal_id}")
        if entry["state"] not in states:
            raise CanaryError(
                f"illegal transition from state {entry['state']}")
        return entry

    def _restore_preimage(self, entry: dict, preimage: dict) -> None:
        preexisting = set(entry.get("preexisting_dirs", []))
        for path in entry["changed_paths"]:
            meta = preimage[path]
            # Never write or delete through a symlink (war-room R2 F4):
            # _resolve_in_tree refuses any symlinked component.
            target = self._resolve_in_tree(path)
            if target.is_symlink():
                raise CanaryError(f"symlink in path during restore: {path}")
            if meta is None:
                try:
                    target.unlink()
                    dir_fd = os.open(target.parent, os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except FileNotFoundError:
                    pass
                # Prune only dirs that did not exist before staging
                # and are now empty (war-room R4 F5).
                parent = target.parent
                while parent != self.root and parent.exists():
                    rel = parent.relative_to(self.root).as_posix()
                    if rel in preexisting:
                        break
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            else:
                self._write_file_atomic(target, meta["data"], meta["mode"])
        # Verify restoration: bytes AND mode.
        for path in entry["changed_paths"]:
            meta = preimage[path]
            current = self._read_tree_file(path)
            if meta is None:
                if current is not None:
                    raise CanaryError(f"rollback verify failed: {path}")
            elif current is None or current["sha256"] != meta["sha256"] \
                    or current["mode"] != meta["mode"]:
                raise CanaryError(f"rollback verify failed: {path}")
