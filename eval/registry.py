"""Benchmark registry with a public set and a sealed held-out set.

Standard library only. Public items are frozen and fully readable. Sealed
expected answers are never returned by any method: callers get metadata
(id, domain, content hash) and aggregate evaluation scores only. Sealed
prompts are shown to one party only — the trusted scorer callable used
for evaluation (see the limits paragraph below). Every sealed item is
hash-locked; a content hash is recomputed and checked on load, before
every save, and before every sealed evaluation, and any mismatch fails
closed. Every access to sealed material is recorded in an append-only,
hash-chained access log, and the log entry is persisted before the access
itself happens. Log entries record attempts: because the entry must be
persisted first, a logged access may still have failed afterwards, and
an entry alone is not proof that an operation succeeded. Reports are
not authenticated: compare_reports binds a report to the identity of
a sealed set (its manifest hash) and checks its internal consistency,
but nothing here signs a report, so it cannot prove an evaluation
actually happened — that requires trusting the verifier-side process
that produced it. Instances are freshness-guarded under an exclusive
inter-instance lock: an instance whose view of the file is stale
refuses to save, rather than rolling newer state back, and the check
and the write it guards are atomic against other instances. A third set,
the golden set, holds never-retired baseline items for drift detection:
it supports addition and evaluation only — no rotation, no removal.

Honest scope: this keeps sealed content out of the public API and makes
edits detectable. It is not encryption and not a filesystem boundary.
Two further limits, stated where they belong: (1) evaluation passes
each item's prompt to the supplied scorer callable, so the scorer must
be a trusted, verifier-side component — a scorer controlled by the
party being evaluated can retain the prompts it is shown, and no log
entry can record that retention; (2) a missing registry file is treated
as a first run and starts empty, so deletion of the file is
indistinguishable from it never having existed. Tamper evidence for
the sealed set and the access log is only as strong as the external
anchoring of the manifest hash and log chain head; hashes stored in
this same file detect careless edits and corruption, and deliberate
tampering only when compared against an externally kept value.
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
import tempfile
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_REGISTRY_BYTES = 5 * 1024 * 1024
MAX_ITEMS_PER_SET = 500
MAX_ACCESS_LOG = 10000
MAX_PROMPT_CHARS = 8000
MAX_EXPECTED_CHARS = 2000
MAX_DOMAIN_CHARS = 200
EPSILON = 1e-9
GENESIS_HASH = "0" * 64
SET_NAMES = ("public", "sealed")
ACCESS_KINDS = ("add", "rotate", "metadata", "manifest", "verify", "evaluate")

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_BAD_CHARS = set("\u200b\u200c\u200d\ufeff\u202a\u202b\u202c\u202d\u202e\u2060")


class CorruptRegistryError(Exception):
    """Raised when persisted registry data cannot be trusted."""


class TamperDetectedError(CorruptRegistryError):
    """Raised when stored content does not match its recorded hash."""


class EvaluationError(Exception):
    """Raised when an evaluation cannot be completed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reject_constant(value: str):
    raise CorruptRegistryError(f"non-finite number in registry: {value}")


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise CorruptRegistryError(f"non-finite number in registry: {text}")
    return value


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(out):
        raise ValueError(f"{field} must be finite")
    return out


def _check_id(value, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _check_text(value, field: str, cap: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if len(value) > cap:
        raise ValueError(f"{field} exceeds {cap} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) == "Cf"
                or (code < 32 and ch not in "\t") or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise ValueError(f"{field} contains control or invisible characters")
    return value


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _content_hash(item_id: str, domain: str, prompt: str, expected: str) -> str:
    return hashlib.sha256(_canonical({
        "domain": domain, "expected": expected, "id": item_id, "prompt": prompt,
    })).hexdigest()


def _normalise_answer(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _state_digest(data) -> str:
    """Digest over versions, item membership and the log head.

    Per-item hashes alone cannot detect a deleted item, a rolled-back
    version counter, or a truncated log tail. This digest binds all of
    them together; it is recomputed on every save and checked on load.
    Like every hash here, it detects edits that do not also recompute
    it — its strength comes from anchoring it externally.
    """
    log = data.get("access_log") or []
    core = {
        "schema_version": data.get("schema_version"),
        "public_version": data.get("public_version"),
        "sealed_version": data.get("sealed_version"),
        "golden_version": data.get("golden_version"),
        "public": sorted((it["id"], it["content_hash"])
                         for it in data.get("public_items", [])),
        "sealed": sorted((it["id"], it["content_hash"])
                         for it in data.get("sealed_items", [])),
        "golden": sorted((it["id"], it["content_hash"])
                         for it in data.get("golden_items", [])),
        "log_seq": data.get("log_seq"),
        "log_head": log[-1]["entry_hash"] if log else GENESIS_HASH,
    }
    return hashlib.sha256(_canonical(core)).hexdigest()


def compare_gains(public_before, public_after, sealed_before, sealed_after,
                  min_delta=0.0) -> dict:
    """Accept a gain only if it appears on both the public and sealed sets.

    Pure function: no state, no logging. Any regression on either set is
    rejected even if the other set improved.
    """
    scores = {}
    for name, value in (("public_before", public_before),
                        ("public_after", public_after),
                        ("sealed_before", sealed_before),
                        ("sealed_after", sealed_after),
                        ("min_delta", min_delta)):
        scores[name] = _finite(value, name)
        if not 0.0 <= scores[name] <= 1.0:
            raise ValueError(f"{name} must be in [0.0, 1.0]")
    public_delta = scores["public_after"] - scores["public_before"]
    sealed_delta = scores["sealed_after"] - scores["sealed_before"]
    threshold = max(EPSILON, scores["min_delta"])

    def improved(delta: float) -> bool:
        return delta > EPSILON and delta >= threshold

    if public_delta < -EPSILON or sealed_delta < -EPSILON:
        reason, accepted = "regression", False
    elif improved(public_delta) and improved(sealed_delta):
        reason, accepted = "both_improved", True
    elif improved(public_delta):
        reason, accepted = "public_only", False
    elif improved(sealed_delta):
        reason, accepted = "sealed_only", False
    else:
        reason, accepted = "no_gain", False
    return {"accepted": accepted, "public_delta": public_delta,
            "sealed_delta": sealed_delta, "reason": reason}


def _serialised(method):
    """Serialise one instance across threads.

    The freshness guard handles separate instances; this lock makes a
    single shared instance safe too, so two threads using the same
    registry cannot interleave a mutation with its save.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._thread_lock:
            return method(self, *args, **kwargs)
    return wrapper


class EvalRegistry:
    """One registry file, two item sets, one chained access log."""

    def __init__(self, registry_dir):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.registry_dir / "registry.json"
        self._lock_depth = 0
        self._lock_owner = None
        self._lock_fd = None
        self._thread_lock = threading.RLock()
        self._state = self._load()
        # Digest of the state as this instance last saw it on disk.
        # Every save re-checks it: if another instance (or a file
        # editor) changed the registry meanwhile, this instance is
        # stale and must fail closed instead of silently rolling the
        # newer state back with its next write.
        self._disk_digest = self._state["state_digest"]

    @contextmanager
    def _locked(self):
        """Exclusive inter-instance lock for this registry directory.

        The freshness check is only meaningful if no other instance
        can write between the check and the replace, so save() holds
        this lock across both. Evaluations deliberately do NOT hold
        the lock while scoring: they work on a snapshot and detect a
        concurrent change at the end of the run instead, so a second
        instance writing mid-evaluation fails the evaluation closed
        rather than deadlocking against it.

        Two details keep the lock honest. Re-entrancy is owned by a
        thread, not by the instance: a second thread of the same
        process is another writer, not a nested call, and must take
        the lock on its own descriptor. And the lock is taken on the
        registry directory itself, not on a lockfile inside it: a
        lockfile can be unlinked mid-race, splitting the lock across
        two inodes, while the directory an instance was opened on
        cannot be unlinked out from under it. Before the replace,
        save() also re-checks that the directory path still names
        the locked inode.
        """
        ident = threading.get_ident()
        if self._lock_owner == ident:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        fd = os.open(self.registry_dir,
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
        """True if the registry file no longer matches what this
        instance last loaded or saved."""
        if not self.registry_path.exists():
            return self._disk_digest != _state_digest(self._fresh())
        try:
            raw = self.registry_path.read_bytes()
            on_disk = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            return True
        return (not isinstance(on_disk, dict)
                or on_disk.get("state_digest") != self._disk_digest)

    # -- persistence -----------------------------------------------------

    def _fresh(self) -> dict:
        data = {"schema_version": SCHEMA_VERSION, "public_version": 0,
                "sealed_version": 0, "golden_version": 0,
                "public_items": [], "sealed_items": [], "golden_items": [],
                "access_log": [], "log_seq": 0}
        data["state_digest"] = _state_digest(data)
        return data

    def _load(self) -> dict:
        if not self.registry_path.exists():
            return self._fresh()
        try:
            size = self.registry_path.stat().st_size
            raw = self.registry_path.read_bytes()[: MAX_REGISTRY_BYTES + 1]
        except OSError as exc:
            raise CorruptRegistryError(f"unreadable registry: {exc}") from exc
        if size > MAX_REGISTRY_BYTES:
            raise CorruptRegistryError("registry file exceeds size cap")
        if len(raw) > MAX_REGISTRY_BYTES:
            raise CorruptRegistryError("registry file exceeds size cap")
        try:
            data = json.loads(raw.decode("utf-8"),
                              parse_constant=_reject_constant,
                              parse_float=_parse_float)
        except CorruptRegistryError:
            raise
        except Exception as exc:
            self._quarantine(raw)
            raise CorruptRegistryError(f"unreadable registry: {exc}") from exc
        self._validate(data)
        return data

    def _quarantine(self, raw: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            (self.registry_dir / f"registry.corrupt-{stamp}.json").write_bytes(raw)
        except OSError:
            pass

    def _validate(self, data) -> None:
        def bad(msg):
            raise CorruptRegistryError(msg)

        if not isinstance(data, dict):
            bad("registry is not an object")
        if set(data.keys()) != {"schema_version", "public_version",
                                "sealed_version", "golden_version",
                                "public_items", "sealed_items",
                                "golden_items", "access_log", "log_seq",
                                "state_digest"}:
            bad("registry has missing or unknown keys")
        if not _is_int(data.get("schema_version")) or data["schema_version"] != SCHEMA_VERSION:
            bad("unsupported schema_version")
        for key in ("public_version", "sealed_version", "golden_version",
                    "log_seq"):
            if not _is_int(data.get(key)) or data[key] < 0:
                bad(f"bad {key}")
        public_items, sealed_items, log = (data.get("public_items"),
                                           data.get("sealed_items"),
                                           data.get("access_log"))
        golden_items = data.get("golden_items")
        if not all(isinstance(x, list)
                   for x in (public_items, sealed_items, golden_items, log)):
            bad("item sets and access_log must be lists")
        if (len(public_items) > MAX_ITEMS_PER_SET
                or len(sealed_items) > MAX_ITEMS_PER_SET
                or len(golden_items) > MAX_ITEMS_PER_SET):
            bad("item set exceeds cap")
        if len(log) > MAX_ACCESS_LOG:
            bad("access log exceeds cap")

        seen_ids = set()
        for items in (public_items, sealed_items, golden_items):
            for it in items:
                if not isinstance(it, dict):
                    bad("item is not an object")
                if set(it.keys()) != {"id", "domain", "prompt", "expected",
                                      "content_hash"}:
                    bad("item has missing or unknown keys")
                try:
                    _check_id(it.get("id"), "item id")
                    _check_text(it.get("domain"), "item domain", MAX_DOMAIN_CHARS)
                    _check_text(it.get("prompt"), "item prompt", MAX_PROMPT_CHARS)
                    _check_text(it.get("expected"), "item expected", MAX_EXPECTED_CHARS)
                except ValueError as exc:
                    bad(str(exc))
                if it["id"] in seen_ids:
                    bad("duplicate item id across sets")
                seen_ids.add(it["id"])
                expected_hash = _content_hash(it["id"], it["domain"],
                                              it["prompt"], it["expected"])
                if it.get("content_hash") != expected_hash:
                    raise TamperDetectedError(
                        f"content hash mismatch for item {it['id']}")

        prev_hash = GENESIS_HASH
        for position, entry in enumerate(log, start=1):
            if not isinstance(entry, dict):
                bad("access log entry is not an object")
            if set(entry.keys()) != {"seq", "at", "actor", "kind", "item_id",
                                     "sealed_version", "prev_hash",
                                     "entry_hash"}:
                bad("access log entry has missing or unknown keys")
            if entry.get("seq") != position:
                bad("access log seq is not strictly increasing from 1")
            if entry.get("kind") not in ACCESS_KINDS:
                bad("unknown access kind")
            try:
                _check_id(entry.get("actor"), "access actor")
            except ValueError as exc:
                bad(str(exc))
            if entry.get("item_id") is not None:
                try:
                    _check_id(entry["item_id"], "access item_id")
                except ValueError as exc:
                    bad(str(exc))
            if entry.get("sealed_version") is not None and not _is_int(entry["sealed_version"]):
                bad("bad sealed_version in access log")
            if entry.get("prev_hash") != prev_hash:
                bad("access log chain is broken")
            core = {k: entry.get(k) for k in
                    ("seq", "at", "actor", "kind", "item_id", "sealed_version", "prev_hash")}
            if entry.get("entry_hash") != hashlib.sha256(_canonical(core)).hexdigest():
                bad("access log entry hash mismatch")
            prev_hash = entry["entry_hash"]
        if data["log_seq"] != len(log):
            bad("log_seq does not match access log length")
        if data.get("state_digest") != _state_digest(data):
            bad("state digest mismatch")

    @_serialised
    def save(self) -> None:
        with self._locked():
            self._save_locked()

    def _save_locked(self) -> None:
        if self._disk_changed():
            raise CorruptRegistryError(
                "registry changed on disk since this instance loaded it; "
                "refusing to overwrite newer state")
        self._state["state_digest"] = _state_digest(self._state)
        self._validate(self._state)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2,
                             allow_nan=False).encode("utf-8")
        if len(payload) > MAX_REGISTRY_BYTES:
            raise ValueError("registry exceeds size cap")
        fd, tmp = tempfile.mkstemp(dir=self.registry_dir,
                                   prefix=".registry-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            if self._lock_fd is not None and (
                    os.stat(self.registry_dir).st_ino
                    != os.fstat(self._lock_fd).st_ino):
                raise CorruptRegistryError(
                    "registry directory was replaced during save")
            os.replace(tmp, self.registry_path)
            self._disk_digest = self._state["state_digest"]
            dir_fd = os.open(self.registry_dir, os.O_DIRECTORY)
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

    # -- access log --------------------------------------------------------

    def _append_log(self, actor: str, kind: str, item_id, sealed_version) -> None:
        if len(self._state["access_log"]) >= MAX_ACCESS_LOG:
            raise ValueError("access log cap reached")
        prev_hash = (self._state["access_log"][-1]["entry_hash"]
                     if self._state["access_log"] else GENESIS_HASH)
        entry = {"seq": self._state["log_seq"] + 1, "at": _now(),
                 "actor": actor, "kind": kind, "item_id": item_id,
                 "sealed_version": sealed_version, "prev_hash": prev_hash}
        entry["entry_hash"] = hashlib.sha256(_canonical(entry)).hexdigest()
        self._state["access_log"].append(entry)
        self._state["log_seq"] = entry["seq"]

    def _sealed_access(self, actor: str, kind: str, item_id, action):
        """Persist the log entry first; only then perform the access."""
        actor = _check_id(actor, "actor")
        snapshot = copy.deepcopy(self._state)
        try:
            self._append_log(actor, kind, item_id, self._state["sealed_version"])
            self.save()
        except BaseException:
            self._state = snapshot
            raise
        return action()

    @_serialised
    def access_log(self, actor=None, kind=None) -> list:
        """Deep copies of log entries, optionally filtered. Never logged."""
        if actor is not None:
            _check_id(actor, "actor")
        if kind is not None and kind not in ACCESS_KINDS:
            raise ValueError("unknown access kind")
        return copy.deepcopy([
            e for e in self._state["access_log"]
            if (actor is None or e["actor"] == actor)
            and (kind is None or e["kind"] == kind)
        ])

    # -- public set --------------------------------------------------------

    def _all_ids(self) -> set:
        return ({it["id"] for it in self._state["public_items"]}
                | {it["id"] for it in self._state["sealed_items"]}
                | {it["id"] for it in self._state["golden_items"]})

    def _new_item(self, item_id, domain, prompt, expected) -> dict:
        item_id = _check_id(item_id, "item id")
        domain = _check_text(domain, "item domain", MAX_DOMAIN_CHARS)
        prompt = _check_text(prompt, "item prompt", MAX_PROMPT_CHARS)
        expected = _check_text(expected, "item expected", MAX_EXPECTED_CHARS)
        if item_id in self._all_ids():
            raise ValueError(f"duplicate item id: {item_id}")
        return {"id": item_id, "domain": domain, "prompt": prompt,
                "expected": expected,
                "content_hash": _content_hash(item_id, domain, prompt, expected)}

    @_serialised
    def add_public_item(self, item_id, domain, prompt, expected) -> dict:
        item = self._new_item(item_id, domain, prompt, expected)
        snapshot = copy.deepcopy(self._state)
        try:
            self._state["public_items"].append(item)
            self._state["public_version"] += 1
            self.save()
        except BaseException:
            self._state = snapshot
            raise
        return copy.deepcopy(item)

    @_serialised
    def get_public_item(self, item_id) -> dict:
        _check_id(item_id, "item id")
        for it in self._state["public_items"]:
            if it["id"] == item_id:
                return copy.deepcopy(it)
        raise ValueError(f"unknown public item: {item_id}")

    @_serialised
    def list_public_items(self, domain=None) -> list:
        if domain is not None:
            _check_text(domain, "domain", MAX_DOMAIN_CHARS)
        return copy.deepcopy([
            it for it in self._state["public_items"]
            if domain is None or it["domain"] == domain
        ])

    @_serialised
    def run_public_evaluation(self, actor, scorer) -> dict:
        _check_id(actor, "actor")
        for it in self._state["public_items"]:
            if it["content_hash"] != _content_hash(it["id"], it["domain"],
                                                   it["prompt"], it["expected"]):
                raise TamperDetectedError(
                    f"content hash mismatch for item {it['id']}")
        return self._run_evaluation(self._state["public_items"], "public",
                                    self._state["public_version"], scorer)

    # -- sealed set --------------------------------------------------------

    @staticmethod
    def _metadata(item: dict) -> dict:
        return {"id": item["id"], "domain": item["domain"],
                "content_hash": item["content_hash"]}

    @_serialised
    def add_sealed_item(self, item_id, domain, prompt, expected, actor) -> dict:
        item = self._new_item(item_id, domain, prompt, expected)

        def action():
            snapshot = copy.deepcopy(self._state)
            try:
                self._state["sealed_items"].append(item)
                self._state["sealed_version"] += 1
                self.save()
            except BaseException:
                self._state = snapshot
                raise
            return self._metadata(item)

        return self._sealed_access(actor, "add", item["id"], action)

    @_serialised
    def list_sealed_metadata(self, actor) -> list:
        return self._sealed_access(
            actor, "metadata", None,
            lambda: [self._metadata(it) for it in self._state["sealed_items"]])

    def _manifest_hash(self) -> str:
        joined = "".join(sorted(it["content_hash"]
                                for it in self._state["sealed_items"]))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    @_serialised
    def sealed_manifest_hash(self, actor) -> str:
        return self._sealed_access(actor, "manifest", None, self._manifest_hash)

    def _verify_sealed(self) -> bool:
        if not self._state["sealed_items"]:
            raise ValueError("no sealed items to verify")
        for it in self._state["sealed_items"]:
            if it["content_hash"] != _content_hash(it["id"], it["domain"],
                                                   it["prompt"], it["expected"]):
                raise TamperDetectedError(
                    f"content hash mismatch for item {it['id']}")
        return True

    @_serialised
    def verify_sealed_integrity(self, actor) -> bool:
        return self._sealed_access(actor, "verify", None, self._verify_sealed)

    @_serialised
    def run_sealed_evaluation(self, actor, scorer) -> dict:
        """Evaluate the sealed set. The scorer receives each prompt, so it
        must be a trusted verifier-side callable (see module docstring).
        The report carries the sealed manifest hash so downstream checks
        can bind a decision to exactly this sealed set."""
        def action():
            self._verify_sealed()
            report = self._run_evaluation(self._state["sealed_items"],
                                          "sealed",
                                          self._state["sealed_version"], scorer,
                                          sealed=True)
            report["manifest_hash"] = self._manifest_hash()
            return report
        return self._sealed_access(actor, "evaluate", None, action)

    @_serialised
    def rotate_sealed_item(self, item_id, prompt, expected, actor) -> dict:
        item_id = _check_id(item_id, "item id")
        prompt = _check_text(prompt, "item prompt", MAX_PROMPT_CHARS)
        expected = _check_text(expected, "item expected", MAX_EXPECTED_CHARS)

        def action():
            for it in self._state["sealed_items"]:
                if it["id"] == item_id:
                    snapshot = copy.deepcopy(self._state)
                    try:
                        it["prompt"] = prompt
                        it["expected"] = expected
                        it["content_hash"] = _content_hash(
                            item_id, it["domain"], prompt, expected)
                        self._state["sealed_version"] += 1
                        self.save()
                    except BaseException:
                        self._state = snapshot
                        raise
                    return self._metadata(it)
            raise ValueError(f"unknown sealed item: {item_id}")

        return self._sealed_access(actor, "rotate", item_id, action)

    # -- golden set --------------------------------------------------------
    # The golden set is the never-retired baseline used for drift
    # detection: items can be added, but there is deliberately no
    # rotation or removal method, so its version only ever moves by
    # addition and old golden items are always re-scored.

    @_serialised
    def add_golden_item(self, item_id, domain, prompt, expected, actor) -> dict:
        item = self._new_item(item_id, domain, prompt, expected)

        def action():
            snapshot = copy.deepcopy(self._state)
            try:
                self._state["golden_items"].append(item)
                self._state["golden_version"] += 1
                self.save()
            except BaseException:
                self._state = snapshot
                raise
            return self._metadata(item)

        return self._sealed_access(actor, "add", item["id"], action)

    @_serialised
    def list_golden_metadata(self, actor) -> list:
        return self._sealed_access(
            actor, "metadata", None,
            lambda: [self._metadata(it) for it in self._state["golden_items"]])

    @_serialised
    def run_golden_evaluation(self, actor, scorer) -> dict:
        def action():
            if not self._state["golden_items"]:
                raise ValueError("no golden items to evaluate")
            for it in self._state["golden_items"]:
                if it["content_hash"] != _content_hash(
                        it["id"], it["domain"], it["prompt"], it["expected"]):
                    raise TamperDetectedError(
                        f"content hash mismatch for item {it['id']}")
            version = self._state["golden_version"]
            report = self._run_evaluation(self._state["golden_items"],
                                          "golden", version, scorer,
                                          sealed=True, check_version=False)
            if self._state["golden_version"] != version:
                raise EvaluationError("golden set changed during evaluation")
            if self._disk_changed():
                raise EvaluationError(
                    "registry changed on disk during evaluation")
            return report
        return self._sealed_access(actor, "evaluate", None, action)

    # -- evaluation ----------------------------------------------------------

    def _run_evaluation(self, items, set_name, version, scorer,
                        sealed=False, check_version=True) -> dict:
        # Evaluate a snapshot taken at the start of the run: a scorer that
        # mutates the registry mid-run cannot change what is being scored,
        # and for the sealed set any version change during the run fails
        # the evaluation closed instead of stamping a stale version.
        snapshot = copy.deepcopy(items)
        if not snapshot:
            raise ValueError(f"cannot evaluate an empty {set_name} set")
        correct = 0
        for it in snapshot:
            try:
                response = scorer(it["prompt"])
            except EvaluationError:
                if sealed:
                    # A scorer-raised EvaluationError passes through
                    # verbatim and could carry the prompt it was shown;
                    # replace it with the generic message.
                    raise EvaluationError(
                        "scorer raised during evaluation") from None
                raise
            except Exception as exc:
                if sealed:
                    # No chained context: a scorer exception may carry the
                    # prompt it was shown, and that must not leak through.
                    raise EvaluationError(
                        "scorer raised during evaluation") from None
                raise EvaluationError("scorer raised during evaluation") from exc
            if not isinstance(response, str):
                raise EvaluationError("scorer must return text")
            if _normalise_answer(response) == _normalise_answer(it["expected"]):
                correct += 1
        if (sealed and check_version
                and self._state["sealed_version"] != version):
            raise EvaluationError("sealed set changed during evaluation")
        if sealed and check_version and self._disk_changed():
            # Another instance changed the registry on disk mid-run:
            # this instance's view is stale even if its own version
            # counter never moved.
            raise EvaluationError(
                "registry changed on disk during evaluation")
        return {"set": set_name, "n": len(snapshot), "correct": correct,
                "score": correct / len(snapshot), "version": version,
                "evaluated_at": _now()}

    @_serialised
    def compare_reports(self, public_before, public_after,
                        sealed_before, sealed_after, min_delta=0.0) -> dict:
        for report, want in ((public_before, "public"), (public_after, "public"),
                             (sealed_before, "sealed"), (sealed_after, "sealed")):
            if not isinstance(report, dict) or report.get("set") != want:
                raise ValueError(f"expected a {want} evaluation report")
            _finite(report.get("score"), "report score")
            if not _is_int(report.get("version")) or report["version"] < 0:
                raise ValueError("report version must be a non-negative int")
            n, correct = report.get("n"), report.get("correct")
            if not _is_int(n) or n <= 0:
                raise ValueError("report n must be a positive int")
            if not _is_int(correct) or not 0 <= correct <= n:
                raise ValueError("report correct must be an int in [0, n]")
            if abs(report["score"] - correct / n) > 1e-9:
                raise ValueError("report score does not match correct / n")
        for report in (sealed_before, sealed_after):
            manifest = report.get("manifest_hash")
            if (manifest is not None
                    and report["version"] == self._state["sealed_version"]
                    and manifest != self._manifest_hash()):
                raise ValueError(
                    "sealed report was not produced by the current sealed set")
        if public_before["version"] != public_after["version"]:
            raise ValueError("public reports come from different versions")
        if sealed_before["version"] != sealed_after["version"]:
            raise ValueError("sealed reports come from different versions")
        before_hash = sealed_before.get("manifest_hash")
        after_hash = sealed_after.get("manifest_hash")
        if (before_hash is None) != (after_hash is None):
            raise ValueError("sealed reports disagree on manifest binding")
        if before_hash is not None and before_hash != after_hash:
            raise ValueError("sealed reports come from different sealed sets")
        return compare_gains(public_before["score"], public_after["score"],
                             sealed_before["score"], sealed_after["score"],
                             min_delta=min_delta)
