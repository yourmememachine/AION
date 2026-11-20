"""Protected-gate enforcement workflow.

Standard library only. This package is the separate channel through
which a change to protected scope (the evaluation package, the cycle
state machine, and this package itself) may be authorised. It does not
modify, override or weaken the safety gate: the gate still refuses
protected paths, and this workflow only issues and consumes
authorisations that a future, separately gated caller may present.

An authorisation is issued only when BOTH legs are present and valid:

- owner approval: the configured owner (OWNER_ID), who may not be the
  author or one of the builders;
- external review: a reviewer who is not the owner, not the author
  and not one of the builders, with the reward-hacking check recorded
  as done and an independence note carried verbatim (its content is
  not judged by this code, as with the gate's verifier note).

Both legs attest the identical binding tuple: proposal id, the
domain-separated content hash and the request expiry. The content
hash binds, per changed path, the pre-image hash (or absence), the
candidate hash and the candidate size, plus the proposal id and the
expiry — so an approval cannot be ported to another proposal, another
base state, or another window. The effective expiry is the earliest
of the request expiry and the two legs' expiries; expiry is re-checked
at consumption time, not only at issue. Consumption is single-use and
final: it is journaled before any receipt is returned, and a consumed
authorisation is never refunded, even if the caller then fails to
apply the change. Proposal ids are burned forever.

Journal lifetime is finite and this is a hard limit, not a detail:
the journal refuses new requests at 200 entries (a request reserves 8
entries of headroom; the hard cap is 264), which is roughly 49 full
request cycles, ever. No compaction or rotation routine exists yet —
when the cap is reached the workflow halts until one is built (it is
a queued backlog item). Concurrent use is guarded, not eliminated:
mutators hold an flock on the journal directory and re-check the
on-disk head before saving, so a stale second manager on the same
machine fails closed instead of overwriting; managers on different
machines sharing one directory are NOT supported.

Honest limits, stated plainly: ids are plain strings and approvals are
unsigned records. This code checks consistency, distinctness, binding
and expiry; it cannot prove the owner really approved, or that the
external reviewer exists, is external, or is a different person or
model. In-process code can construct a correctly bound approval —
the same forgery class the canary journal documents. Closing it
requires signed approvals with keys held outside this process, which
is the recorded next step (signed gate decisions), not a claim made
here. The journal is hash-chained with a whole-journal digest, so
edits, deletions and reordering that do NOT recompute the chain and
digest are detected; the chain and digest are unkeyed and live in the
same file, so any rewrite that recomputes them — including deleting
the journal file outright, which erases every consumption with it —
is not detectable by this code alone, because the head is not
anchored outside the journal directory in this version.
state_digest() is exposed so a caller can anchor the head elsewhere.
Timestamps are caller- or host-asserted (every method accepts a
caller-supplied now); ordering is by journal sequence, never by
timestamp.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eval.gate import check_protected_paths

OWNER_ID = "dilip"
LOCAL_PROTECTED_PREFIXES = ("oversight/",)
LOCAL_PROTECTED_FILES = ("oversight",)
TTL_DEFAULT_SECONDS = 7200
TTL_MIN_SECONDS = 60
TTL_MAX_SECONDS = 172800  # 48 hours
MAX_PATHS = 16
MAX_TEXT = 2000
MAX_JOURNAL_ENTRIES = 200
HARD_JOURNAL_ENTRIES = 264
REQUEST_RESERVE = 8  # journal headroom a new request must leave behind
CLOCK_SKEW_SECONDS = 300

TERMINAL_STATES = ("CONSUMED", "DENIED", "EXPIRED", "REVOKED")

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_BAD_CHARS = set("\xad\u061c\u180e\u200b\u200c\u200d\u2060\ufeff\ufff9\ufffa\ufffb")


class ApprovalError(ValueError):
    """Raised when an approval-workflow operation is refused."""


class CorruptJournalError(ApprovalError):
    """Raised when the persisted journal cannot be trusted."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ApprovalError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError(f"{field} must be non-empty text")
    if len(value) > MAX_TEXT:
        raise ApprovalError(f"{field} exceeds {MAX_TEXT} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) in ("Cs", "Cf")
                or (code < 32 and ch not in "\t\n") or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise ApprovalError(
                f"{field} contains control or invisible characters")
    return value


def _parse_time(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ApprovalError(f"{field} must be timezone-aware")
    return parsed


def canonicalise_path(value) -> str:
    """Normalise a repo-relative path or refuse it (canary spelling)."""
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError("path must be non-empty text")
    if "\x00" in value:
        raise ApprovalError("path contains a NUL byte")
    path = value.strip().replace("\\", "/")
    if path.startswith("/") or re.match(r"^[a-zA-Z]:/", path):
        raise ApprovalError(f"path must be repo-relative: {value!r}")
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ApprovalError(f"path escapes the tree: {value!r}")
        parts.append(part)
    if not parts:
        raise ApprovalError(f"path must name a file: {value!r}")
    return "/".join(parts)


def is_protected_path(canonical: str) -> bool:
    """Protected scope: the gate's list plus this package itself."""
    if canonical in LOCAL_PROTECTED_FILES:
        return True
    if any(canonical.startswith(p) for p in LOCAL_PROTECTED_PREFIXES):
        return True
    if canonical.split("/")[0] == "oversight":
        return True
    return bool(check_protected_paths([canonical]))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(entries: dict) -> tuple:
    """Validate a {path: bytes|None} mapping; return canonical manifest.

    The manifest maps each canonical path to (preimage-marker, data).
    Used for candidate bytes (values are bytes) — pre-images are passed
    through the same helper with the candidate mapping's key set.
    """
    if not isinstance(entries, dict) or not entries:
        raise ApprovalError("change must be a non-empty {path: bytes} mapping")
    if len(entries) > MAX_PATHS:
        raise ApprovalError(f"change exceeds {MAX_PATHS} paths")
    out = {}
    for raw_path, data in entries.items():
        path = canonicalise_path(raw_path)
        if path in out:
            raise ApprovalError(f"duplicate path after canonicalisation: {path}")
        if data is not None and not isinstance(data, (bytes, bytearray)):
            raise ApprovalError(f"content for {path} must be bytes or None")
        out[path] = None if data is None else bytes(data)
    return out


def content_hash_for(*, proposal_id: str, expires_at: str,
                     candidate: dict, preimage: dict) -> str:
    """Domain-separated binding over proposal, expiry and both images."""
    if not isinstance(candidate, dict) or not isinstance(preimage, dict):
        raise ApprovalError("candidate and preimage must be mappings")
    if set(candidate) != set(preimage):
        raise ApprovalError("preimage paths must match candidate paths")
    for path, data in candidate.items():
        if data is None or not isinstance(data, (bytes, bytearray)):
            raise ApprovalError(
                f"candidate for {path} must be bytes (deletion is not "
                "supported in this workflow)")
    lines = []
    for path in sorted(candidate):
        cand = candidate[path]
        pre = preimage[path]
        pre_part = "absent" if pre is None else f"{_sha256(pre)}:{len(pre)}"
        lines.append(f"{path}\x00{pre_part}\x00{_sha256(cand)}:{len(cand)}")
    payload = ("protected-candidate-v1\n" + proposal_id + "\n" + expires_at
               + "\n" + "\n".join(lines))
    return _sha256(payload.encode("utf-8"))


def preimage_hash_for(preimage: dict) -> str:
    lines = []
    for path in sorted(preimage):
        pre = preimage[path]
        part = "absent" if pre is None else f"{_sha256(pre)}:{len(pre)}"
        lines.append(f"{path}\x00{part}")
    return _sha256(("protected-preimage-v1\n" + "\n".join(lines)).encode())


@dataclass(frozen=True)
class ProtectedChangeRequest:
    proposal_id: str
    author_id: str
    builder_ids: tuple
    changed_paths: tuple
    content_hash: str
    preimage_hash: str
    rationale: str
    evidence_ref: str
    requested_at: str
    expires_at: str


@dataclass(frozen=True)
class OwnerApproval:
    owner_id: str
    proposal_id: str
    content_hash: str
    bound_expires_at: str
    decision: str  # "approve" or "deny"
    evidence_ref: str
    attested_at: str
    expires_at: str


@dataclass(frozen=True)
class ExternalReview:
    reviewer_id: str
    proposal_id: str
    content_hash: str
    bound_expires_at: str
    decision: str  # "approve" or "deny"
    reward_hacking_checked: bool
    independence_note: str
    evidence_ref: str
    attested_at: str
    expires_at: str


@dataclass(frozen=True)
class EnforcementDecision:
    authorized: bool
    proposal_id: str
    reasons: tuple
    content_hash: str
    effective_expires_at: str | None
    evaluated_at: str


@dataclass(frozen=True)
class ConsumeReceipt:
    proposal_id: str
    content_hash: str
    decision_id: str
    consumed_at: str
    effective_expires_at: str = ""
    preimage_hash: str = ""


def _leg_reasons(leg, *, kind: str, request: ProtectedChangeRequest,
                 forbidden_ids: set, expected_actor: str | None) -> list:
    reasons = []
    if leg is None:
        return [f"missing_{kind}"]
    actor = leg.owner_id if kind == "owner_approval" else leg.reviewer_id
    if not isinstance(actor, str) or not _ID_RE.fullmatch(actor or ""):
        reasons.append(f"bad_{kind}_id")
        actor = None
    if actor is not None:
        if expected_actor is not None and actor != expected_actor:
            reasons.append("not_owner")
        if actor in forbidden_ids:
            reasons.append(f"{kind}_actor_forbidden")
    if leg.proposal_id != request.proposal_id:
        reasons.append(f"{kind}_proposal_mismatch")
    if leg.content_hash != request.content_hash:
        reasons.append(f"{kind}_hash_mismatch")
    if leg.bound_expires_at != request.expires_at:
        reasons.append(f"{kind}_expiry_binding_mismatch")
    if leg.decision != "approve":
        reasons.append(f"{kind}_did_not_approve")
    if not isinstance(leg.evidence_ref, str) or not leg.evidence_ref.strip():
        reasons.append(f"{kind}_missing_evidence")
    else:
        try:
            _check_text(leg.evidence_ref, f"{kind} evidence_ref")
        except ApprovalError:
            reasons.append(f"{kind}_bad_evidence_text")
    try:
        _parse_time(leg.attested_at, f"{kind} attested_at")
        _parse_time(leg.expires_at, f"{kind} expires_at")
    except ApprovalError:
        reasons.append(f"{kind}_bad_timestamp")
    if kind == "external_review":
        if leg.reward_hacking_checked is not True:
            reasons.append("reward_hacking_not_checked")
        if (not isinstance(leg.independence_note, str)
                or not leg.independence_note.strip()):
            reasons.append("missing_independence_note")
        else:
            try:
                _check_text(leg.independence_note, "independence_note")
            except ApprovalError:
                reasons.append("bad_independence_note_text")
    return reasons


def evaluate_approvals(*, request: ProtectedChangeRequest,
                       owner_approval, external_review, now: str) -> EnforcementDecision:
    """Pure decision: both legs valid, bound, unexpired — or all reasons.

    Malformed request fields raise ApprovalError; a well-formed but
    failing pair returns authorized=False with every reason collected.
    """
    if not isinstance(request, ProtectedChangeRequest):
        raise ApprovalError("request must be a ProtectedChangeRequest")
    _check_id(request.proposal_id, "proposal id")
    _check_id(request.author_id, "author id")
    if (not isinstance(request.content_hash, str)
            or not _HEX64_RE.fullmatch(request.content_hash)):
        raise ApprovalError("request content_hash must be hex64")
    if (not isinstance(request.preimage_hash, str)
            or not _HEX64_RE.fullmatch(request.preimage_hash)):
        raise ApprovalError("request preimage_hash must be hex64")
    if not request.changed_paths:
        raise ApprovalError("request must name at least one changed path")
    _check_text(request.rationale, "rationale")
    _check_text(request.evidence_ref, "evidence_ref")
    _builders = list(request.builder_ids or ())
    if len(set(_builders)) < 3 or any(
            not isinstance(b, str) or not _ID_RE.fullmatch(b)
            for b in _builders):
        raise ApprovalError("request requires at least 3 distinct builder ids")
    builders = set(request.builder_ids or ())
    requested = _parse_time(request.requested_at, "requested_at")
    req_expiry = _parse_time(request.expires_at, "expires_at")
    if not (timedelta(seconds=TTL_MIN_SECONDS)
            <= req_expiry - requested
            <= timedelta(seconds=TTL_MAX_SECONDS)):
        raise ApprovalError("request window outside the TTL bounds")
    moment = _parse_time(now, "now")

    reasons = []
    reasons += _leg_reasons(
        owner_approval, kind="owner_approval", request=request,
        forbidden_ids=builders | {request.author_id}, expected_actor=OWNER_ID)
    reasons += _leg_reasons(
        external_review, kind="external_review", request=request,
        forbidden_ids=builders | {request.author_id, OWNER_ID},
        expected_actor=None)
    if (owner_approval is not None and external_review is not None
            and getattr(owner_approval, "owner_id", None)
            == getattr(external_review, "reviewer_id", None)):
        reasons.append("owner_is_external_reviewer")

    expiries = [req_expiry]
    for leg in (owner_approval, external_review):
        if leg is not None:
            try:
                expiries.append(_parse_time(leg.expires_at, "leg expires_at"))
            except ApprovalError:
                pass
            try:
                attested = _parse_time(leg.attested_at, "leg attested_at")
                if attested < requested - timedelta(seconds=CLOCK_SKEW_SECONDS):
                    reasons.append("attestation_before_request")
                if attested > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
                    reasons.append("attestation_in_future")
                leg_expiry = _parse_time(leg.expires_at, "leg expires_at")
                if attested > leg_expiry or attested > req_expiry:
                    reasons.append("attestation_after_expiry")
            except ApprovalError:
                pass
    effective = min(expiries)
    if moment >= effective:
        reasons.append("expired")
    return EnforcementDecision(
        authorized=not reasons,
        proposal_id=request.proposal_id,
        reasons=tuple(dict.fromkeys(reasons)),
        content_hash=request.content_hash,
        effective_expires_at=effective.isoformat(),
        evaluated_at=now,
    )


class ApprovalManager:
    """Journaled manager: request -> dual approval -> consume once.

    The journal lives in journal_dir (a JSON file with hash-chained
    entries and a whole-journal digest). One request may be active at
    a time. All mutators save atomically before returning.
    """

    JOURNAL_NAME = "journal.json"

    def __init__(self, journal_dir):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.journal_dir / self.JOURNAL_NAME
        self.journal = self._load()
        self._rebuild()

    # -- persistence ----------------------------------------------------

    def _fresh(self) -> dict:
        return {"schema_version": 1, "seq": 0, "entries": [],
                "used_proposal_ids": [], "digest": ""}

    def _entry_hash(self, entry: dict, prev_hash: str) -> str:
        payload = {k: v for k, v in entry.items() if k != "entry_hash"}
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          allow_nan=False).encode("utf-8")
        return _sha256(prev_hash.encode("utf-8") + b"\n" + blob)

    def _compute_digest(self, journal: dict) -> str:
        head = journal["entries"][-1]["entry_hash"] if journal["entries"] else ""
        payload = {"schema_version": journal["schema_version"],
                   "seq": journal["seq"], "head": head,
                   "used": sorted(journal["used_proposal_ids"])}
        return _sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))

    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"non-finite constant {value}")

    @staticmethod
    def _parse_float(text):
        parsed = float(text)
        if not math.isfinite(parsed):
            raise ValueError("non-finite number")
        return parsed

    @staticmethod
    def _no_dup_keys(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate key {key}")
            out[key] = value
        return out

    def _quarantine(self, raw: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.journal_dir / f"journal.corrupt-{stamp}.json"
        try:
            target.write_bytes(raw)
        except OSError:
            pass

    def _load(self) -> dict:
        if not self.journal_path.exists():
            return self._fresh()
        raw = self.journal_path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"),
                              object_pairs_hook=self._no_dup_keys,
                              parse_constant=self._reject_constant,
                              parse_float=self._parse_float)
        except (ValueError, UnicodeDecodeError) as exc:
            self._quarantine(raw)
            raise CorruptJournalError(f"journal is not valid JSON: {exc}") from exc
        try:
            self._validate(data)
        except CorruptJournalError:
            self._quarantine(raw)
            raise
        return data

    def _validate(self, data) -> None:
        def bad(msg):
            raise CorruptJournalError(f"journal corrupt: {msg}")
        if not isinstance(data, dict):
            bad("top level is not an object")
        if set(data) != {"schema_version", "seq", "entries",
                         "used_proposal_ids", "digest"}:
            bad("top-level keys differ")
        if not _is_int(data["schema_version"]) or data["schema_version"] != 1 \
                or not _is_int(data["seq"]):
            bad("schema or seq")
        if not isinstance(data["entries"], list) or \
                len(data["entries"]) > HARD_JOURNAL_ENTRIES:
            bad("entries")
        if not isinstance(data["used_proposal_ids"], list):
            bad("used ids")
        prev = ""
        used = []
        replay: dict = {}
        known_kinds = {"requested", "owner_approval", "external_review",
                       "denied", "revoked", "expired", "consumed"}
        for idx, entry in enumerate(data["entries"]):
            if not isinstance(entry, dict):
                bad("entry is not an object")
            if entry.get("seq") != idx + 1:
                bad("seq gap")
            if entry.get("entry_hash") != self._entry_hash(entry, prev):
                bad("entry hash chain broken")
            prev = entry["entry_hash"]
            pid = entry.get("proposal_id")
            if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
                bad("entry proposal id")
            kind = entry.get("kind")
            if kind not in known_kinds:
                bad("entry kind")
            state = replay.get(pid)
            if state is None:
                if kind != "requested":
                    bad("first entry for a proposal must be requested")
                replay[pid] = {"legs": set(), "terminal": False,
                               "approve_legs": set()}
            else:
                if state["terminal"]:
                    bad("entry after terminal state")
                if kind == "requested":
                    bad("duplicate requested entry")
                if kind in ("owner_approval", "external_review"):
                    if kind in state["legs"]:
                        bad("duplicate leg entry")
                    state["legs"].add(kind)
                    payload = entry.get(
                        "approval" if kind == "owner_approval" else "review")
                    if isinstance(payload, dict) and \
                            payload.get("decision") == "approve":
                        state["approve_legs"].add(kind)
                    elif isinstance(payload, dict) and \
                            payload.get("decision") == "deny":
                        state["terminal"] = True  # a deny leg is terminal
                if kind == "denied" and not state["legs"]:
                    bad("denied without a recorded leg")
                if kind == "consumed" and len(state["approve_legs"]) < 2:
                    bad("consumed without both approve legs")
                if kind in ("denied", "revoked", "expired", "consumed"):
                    state["terminal"] = True
            if pid not in used:
                used.append(pid)
        if data["seq"] != len(data["entries"]):
            bad("seq does not match entries")
        if sorted(used) != sorted(data["used_proposal_ids"]):
            bad("used ids do not match entries")
        if data["digest"] != self._compute_digest(data):
            bad("digest mismatch")

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

    def _disk_head(self):
        """(seq, head hash) of the journal on disk, or (0, '') if absent."""
        if not self.journal_path.exists():
            return 0, ""
        data = self._load()
        head = data["entries"][-1]["entry_hash"] if data["entries"] else ""
        return data["seq"], head

    def _append(self, entry: dict, *, lifecycle: bool = False) -> dict:
        count = len(self.journal["entries"])
        if count >= HARD_JOURNAL_ENTRIES:
            raise ApprovalError("journal hard entry cap reached; "
                                "compaction is required")
        if not lifecycle and count >= MAX_JOURNAL_ENTRIES:
            raise ApprovalError("journal entry cap reached; compaction "
                                "is required before new requests")
        lock_fd = os.open(self.journal_dir, os.O_DIRECTORY)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # Fail closed if another manager moved the journal since we
            # loaded it: a stale instance must never overwrite newer work.
            my_head = (self.journal["entries"][-1]["entry_hash"]
                       if self.journal["entries"] else "")
            if self._disk_head() != (self.journal["seq"], my_head):
                raise ApprovalError(
                    "journal changed on disk since this manager loaded "
                    "it; reload before writing (stale manager refused)")
            entry = dict(entry)
            entry["seq"] = count + 1
            entry["entry_hash"] = self._entry_hash(entry, my_head)
            snapshot = copy.deepcopy(self.journal)
            self.journal["entries"].append(entry)
            self.journal["seq"] = entry["seq"]
            if entry["proposal_id"] not in self.journal["used_proposal_ids"]:
                self.journal["used_proposal_ids"].append(entry["proposal_id"])
            try:
                self._save()
            except BaseException:
                # os.replace is the commit point: if the new entry is
                # already on disk (e.g. only the directory fsync after
                # the replace failed), the append DID commit — reload
                # and keep it rather than rolling memory back into
                # disagreement with disk.
                try:
                    disk = self._load()
                except BaseException:
                    disk = None
                if disk is not None and disk["entries"] and \
                        disk["entries"][-1].get("entry_hash") == \
                        entry["entry_hash"]:
                    self.journal = disk
                    self._rebuild()
                    return entry
                self.journal = snapshot
                self._rebuild()
                raise
            self._rebuild()
            return entry
        finally:
            os.close(lock_fd)

    # -- state rebuild ----------------------------------------------------

    def _rebuild(self) -> None:
        self.requests: dict = {}
        for entry in self.journal["entries"]:
            pid = entry["proposal_id"]
            kind = entry["kind"]
            if kind == "requested":
                self.requests[pid] = {
                    "request": entry["request"], "owner_approval": None,
                    "external_review": None, "terminal": None,
                    "consumed": None}
            elif pid in self.requests:
                rec = self.requests[pid]
                if kind == "owner_approval":
                    rec["owner_approval"] = entry["approval"]
                    if entry["approval"].get("decision") == "deny":
                        rec["terminal"] = "DENIED"
                elif kind == "external_review":
                    rec["external_review"] = entry["review"]
                    if entry["review"].get("decision") == "deny":
                        rec["terminal"] = "DENIED"
                elif kind in ("denied", "revoked", "expired"):
                    rec["terminal"] = kind.upper()
                elif kind == "consumed":
                    rec["terminal"] = "CONSUMED"
                    rec["consumed"] = entry

    def _record(self, proposal_id: str) -> dict:
        _check_id(proposal_id, "proposal id")
        rec = self.requests.get(proposal_id)
        if rec is None:
            raise ApprovalError(f"unknown proposal: {proposal_id}")
        return rec

    @staticmethod
    def _request_obj(rec: dict) -> ProtectedChangeRequest:
        r = rec["request"]
        return ProtectedChangeRequest(
            proposal_id=r["proposal_id"], author_id=r["author_id"],
            builder_ids=tuple(r["builder_ids"]),
            changed_paths=tuple(r["changed_paths"]),
            content_hash=r["content_hash"], preimage_hash=r["preimage_hash"],
            rationale=r["rationale"], evidence_ref=r["evidence_ref"],
            requested_at=r["requested_at"], expires_at=r["expires_at"])

    @staticmethod
    def _owner_obj(data):
        if data is None:
            return None
        return OwnerApproval(**{k: data[k] for k in (
            "owner_id", "proposal_id", "content_hash", "bound_expires_at",
            "decision", "evidence_ref", "attested_at", "expires_at")})

    @staticmethod
    def _external_obj(data):
        if data is None:
            return None
        return ExternalReview(**{k: data[k] for k in (
            "reviewer_id", "proposal_id", "content_hash", "bound_expires_at",
            "decision", "reward_hacking_checked", "independence_note",
            "evidence_ref", "attested_at", "expires_at")})

    def _maybe_expire(self, rec: dict, now: str) -> None:
        if rec["terminal"] is not None:
            return
        decision = evaluate_approvals(
            request=self._request_obj(rec),
            owner_approval=self._owner_obj(rec["owner_approval"]),
            external_review=self._external_obj(rec["external_review"]),
            now=now)
        if "expired" in decision.reasons:
            self._append({"kind": "expired",
                          "proposal_id": rec["request"]["proposal_id"],
                          "at": now}, lifecycle=True)

    def _active(self):
        for pid, rec in self.requests.items():
            if rec["terminal"] is None:
                return pid, rec
        return None, None

    # -- public API -------------------------------------------------------

    def create_request(self, *, proposal_id, author_id, builder_ids,
                       candidate, preimage, rationale, evidence_ref,
                       ttl_seconds=TTL_DEFAULT_SECONDS, now=None) -> dict:
        now = now or _now()
        moment = _parse_time(now, "now")
        _check_id(proposal_id, "proposal id")
        _check_id(author_id, "author id")
        if proposal_id in self.journal["used_proposal_ids"]:
            raise ApprovalError(f"proposal id already used: {proposal_id}")
        if isinstance(builder_ids, (str, bytes)) or not isinstance(
                builder_ids, (list, tuple)):
            raise ApprovalError("builder_ids must be a list of ids")
        builders = [_check_id(b, "builder id") for b in builder_ids]
        if len(set(builders)) < 3:
            raise ApprovalError("builder_ids requires at least 3 distinct ids")
        if author_id == OWNER_ID:
            raise ApprovalError("the owner may not author a protected request")
        if OWNER_ID in builders:
            raise ApprovalError("the owner may not be one of the builders")
        _check_text(rationale, "rationale")
        _check_text(evidence_ref, "evidence_ref")
        if not _is_int(ttl_seconds) or not (
                TTL_MIN_SECONDS <= ttl_seconds <= TTL_MAX_SECONDS):
            raise ApprovalError(
                f"ttl_seconds must be an int in [{TTL_MIN_SECONDS}, "
                f"{TTL_MAX_SECONDS}]")
        cand = _manifest(candidate)
        pre = _manifest(preimage)
        if set(cand) != set(pre):
            raise ApprovalError("preimage paths must match candidate paths")
        for path, data in cand.items():
            if data is None:
                raise ApprovalError(
                    f"candidate for {path} must be bytes (deletion is not "
                    "supported in this workflow)")
            if not is_protected_path(path):
                raise ApprovalError(
                    f"path is not in protected scope: {path} (this "
                    "workflow authorises protected changes only)")
        active_pid, active_rec = self._active()
        if active_rec is not None:
            self._maybe_expire(active_rec, now)
            active_pid, active_rec = self._active()
            if active_rec is not None:
                raise ApprovalError(
                    f"another request is active: {active_pid}")
        if len(self.journal["entries"]) + REQUEST_RESERVE > MAX_JOURNAL_ENTRIES:
            raise ApprovalError("journal entry cap reached; compaction "
                                "is required before new requests")
        expires = moment + timedelta(seconds=ttl_seconds)
        expires_at = expires.isoformat()
        request = {
            "proposal_id": proposal_id, "author_id": author_id,
            "builder_ids": builders, "changed_paths": sorted(cand),
            "content_hash": content_hash_for(
                proposal_id=proposal_id, expires_at=expires_at,
                candidate=cand, preimage=pre),
            "preimage_hash": preimage_hash_for(pre),
            "rationale": rationale, "evidence_ref": evidence_ref,
            "requested_at": now, "expires_at": expires_at,
        }
        self._append({"kind": "requested", "proposal_id": proposal_id,
                      "at": now, "request": request})
        return copy.deepcopy(request)

    def _record_leg(self, proposal_id, leg_obj, kind: str, now: str) -> dict:
        rec = self._record(proposal_id)
        slot = "owner_approval" if kind == "owner_approval" else "external_review"
        leg_dict = dict(leg_obj.__dict__)
        existing = rec[slot]
        if existing is not None and existing == leg_dict:
            return copy.deepcopy(existing)  # idempotent re-record, incl. deny
        if rec["terminal"] is not None:
            raise ApprovalError(
                f"request is terminal ({rec['terminal']}); no further "
                "approvals may be recorded")
        self._maybe_expire(rec, now)
        rec = self._record(proposal_id)
        if rec["terminal"] is not None:
            raise ApprovalError(
                f"request is terminal ({rec['terminal']}); no further "
                "approvals may be recorded")
        if existing is not None:
            raise ApprovalError(f"{kind} already recorded and differs")
        if leg_obj.decision not in ("approve", "deny"):
            raise ApprovalError("decision must be 'approve' or 'deny'")
        # Reject at record time on ANY failure attributable to this leg,
        # so a never-authorisable leg can never occupy the slot. A deny
        # is exempt from the reward-hacking / independence requirements
        # (it authorises nothing) but not from binding or identity.
        request = self._request_obj(rec)
        reasons = _leg_reasons(
            leg_obj, kind=kind, request=request,
            forbidden_ids=set(request.builder_ids) | {request.author_id}
            if kind == "owner_approval" else
            set(request.builder_ids) | {request.author_id, OWNER_ID},
            expected_actor=OWNER_ID if kind == "owner_approval" else None)
        if (kind == "external_review"
                and getattr(leg_obj, "reviewer_id", None) == OWNER_ID):
            reasons.append("external_review_actor_forbidden")
        moment = _parse_time(now, "now")
        try:
            attested = _parse_time(leg_obj.attested_at, "attested_at")
            leg_expiry = _parse_time(leg_obj.expires_at, "expires_at")
            requested = _parse_time(request.requested_at, "requested_at")
            if attested < requested - timedelta(seconds=CLOCK_SKEW_SECONDS):
                reasons.append("attestation_before_request")
            if attested > moment + timedelta(seconds=CLOCK_SKEW_SECONDS):
                reasons.append("attestation_in_future")
            if attested > leg_expiry or attested > _parse_time(
                    request.expires_at, "expires_at"):
                reasons.append("attestation_after_expiry")
            if leg_obj.decision == "approve" and moment >= min(
                    leg_expiry, _parse_time(request.expires_at, "expires_at")):
                reasons.append("expired")
        except ApprovalError:
            reasons.append(f"{kind}_bad_timestamp")
        if leg_obj.decision == "deny":
            reasons = [r for r in reasons if r not in (
                "reward_hacking_not_checked", "missing_independence_note",
                "bad_independence_note_text")]
            reasons = [r for r in reasons
                       if r != f"{kind}_did_not_approve"]
        else:
            reasons = [r for r in reasons
                       if r != f"{kind}_did_not_approve"]
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            raise ApprovalError(
                f"{kind} does not bind to this request: {reasons[0]}")
        self._append({"kind": kind, "proposal_id": proposal_id,
                      "at": now,
                      ("approval" if kind == "owner_approval" else "review"):
                      leg_dict})
        # A recorded deny leg is itself the terminal DENIED transition
        # (derived in _rebuild and in journal replay validation), so the
        # deny is one atomic append, never two.
        return copy.deepcopy(leg_dict)

    def record_owner_approval(self, approval: OwnerApproval, *, now=None) -> dict:
        if not isinstance(approval, OwnerApproval):
            raise ApprovalError("approval must be an OwnerApproval")
        return self._record_leg(approval.proposal_id, approval,
                                "owner_approval", now or _now())

    def record_external_review(self, review: ExternalReview, *, now=None) -> dict:
        if not isinstance(review, ExternalReview):
            raise ApprovalError("review must be an ExternalReview")
        return self._record_leg(review.proposal_id, review,
                                "external_review", now or _now())

    def evaluate(self, proposal_id, *, now=None) -> EnforcementDecision:
        now = now or _now()
        rec = self._record(proposal_id)
        self._maybe_expire(rec, now)
        rec = self._record(proposal_id)
        decision = evaluate_approvals(
            request=self._request_obj(rec),
            owner_approval=self._owner_obj(rec["owner_approval"]),
            external_review=self._external_obj(rec["external_review"]),
            now=now)
        if rec["terminal"] is not None:
            reasons = tuple(dict.fromkeys(
                (f"terminal_{rec['terminal'].lower()}",) + decision.reasons))
            return EnforcementDecision(
                authorized=False, proposal_id=proposal_id, reasons=reasons,
                content_hash=decision.content_hash,
                effective_expires_at=decision.effective_expires_at,
                evaluated_at=now)
        return decision

    def state(self, proposal_id, *, now=None) -> str:
        now = now or _now()
        rec = self._record(proposal_id)
        self._maybe_expire(rec, now)
        rec = self._record(proposal_id)
        if rec["terminal"] is not None:
            return rec["terminal"]
        owner = rec["owner_approval"]
        external = rec["external_review"]
        decision = self.evaluate(proposal_id, now=now)
        if decision.authorized:
            return "ARMED"
        if owner and external:
            return "BOTH_RECORDED"
        if owner:
            return "OWNER_APPROVED"
        if external:
            return "EXTERNALLY_REVIEWED"
        return "REQUESTED"

    def status(self, proposal_id, *, now=None) -> dict:
        now = now or _now()
        rec = self._record(proposal_id)
        decision = self.evaluate(proposal_id, now=now)
        rec = self._record(proposal_id)
        return {"proposal_id": proposal_id, "state": self.state(proposal_id, now=now),
                "request": copy.deepcopy(rec["request"]),
                "owner_approval": copy.deepcopy(rec["owner_approval"]),
                "external_review": copy.deepcopy(rec["external_review"]),
                "authorized": decision.authorized,
                "reasons": list(decision.reasons),
                "effective_expires_at": decision.effective_expires_at}

    def consume(self, *, proposal_id, candidate, preimage, now=None) -> ConsumeReceipt:
        now = now or _now()
        rec = self._record(proposal_id)
        if rec["terminal"] is not None:
            raise ApprovalError(
                f"request is terminal ({rec['terminal']}); consumption "
                "refused")
        decision = self.evaluate(proposal_id, now=now)
        rec = self._record(proposal_id)
        if rec["terminal"] is not None:
            raise ApprovalError(
                f"request is terminal ({rec['terminal']}); consumption "
                "refused")
        if not decision.authorized:
            raise ApprovalError(
                "request is not authorised: " + ", ".join(decision.reasons))
        cand = _manifest(candidate)
        pre = _manifest(preimage)
        if set(cand) != set(pre):
            raise ApprovalError("preimage paths must match candidate paths")
        request = rec["request"]
        if sorted(cand) != list(request["changed_paths"]):
            raise ApprovalError("changed paths differ from the approved request")
        recomputed = content_hash_for(
            proposal_id=proposal_id, expires_at=request["expires_at"],
            candidate=cand, preimage=pre)
        if recomputed != request["content_hash"]:
            raise ApprovalError(
                "content hash mismatch: candidate or pre-image has "
                "drifted since approval")
        if preimage_hash_for(pre) != request["preimage_hash"]:
            raise ApprovalError("pre-image hash mismatch")
        decision_id = _sha256(json.dumps({
            "proposal_id": proposal_id, "content_hash": recomputed,
            "effective_expires_at": decision.effective_expires_at,
            "consumed_at": now}, sort_keys=True).encode("utf-8"))
        self._append({"kind": "consumed", "proposal_id": proposal_id,
                      "at": now, "decision_id": decision_id,
                      "content_hash": recomputed}, lifecycle=True)
        return ConsumeReceipt(
            proposal_id=proposal_id, content_hash=recomputed,
            decision_id=decision_id, consumed_at=now,
            effective_expires_at=decision.effective_expires_at,
            preimage_hash=request["preimage_hash"])

    def revoke(self, *, proposal_id, revoked_by, reason, now=None) -> dict:
        now = now or _now()
        _check_id(revoked_by, "revoked_by")
        _check_text(reason, "reason")
        rec = self._record(proposal_id)
        self._maybe_expire(rec, now)
        rec = self._record(proposal_id)
        if rec["terminal"] is not None:
            raise ApprovalError(
                f"request is terminal ({rec['terminal']}); revocation "
                "refused")
        allowed = {OWNER_ID, rec["request"]["author_id"]}
        if rec["external_review"]:
            allowed.add(rec["external_review"]["reviewer_id"])
        if revoked_by not in allowed:
            raise ApprovalError(
                "only the owner, the author or the external reviewer "
                "may revoke")
        entry = self._append({"kind": "revoked", "proposal_id": proposal_id,
                              "at": now, "by": revoked_by, "reason": reason},
                             lifecycle=True)
        return copy.deepcopy(entry)

    def history(self) -> list:
        return copy.deepcopy(self.journal["entries"])

    def state_digest(self) -> str:
        return self.journal["digest"]
