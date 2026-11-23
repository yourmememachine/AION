"""Core cycle loop: scan -> build -> review -> fix/verify -> improve -> ship.

Standard library only. No network access. Persistent state is a single
JSON document written atomically and validated deeply on load and save;
a corrupt document fails closed and is never silently replaced with
empty state. A cycle is computed in memory and persisted in one save,
so an interruption can never strand the loop mid-cycle.

An optional constructor-injected ``cycle_hook`` is called once per
recorded cycle, after the cycle has been persisted: the contract is
"cycle recorded, pin pending, alert" — a hook failure never
un-records the cycle and never corrupts state; it propagates to the
caller, who owns whatever the hook was pending on.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_STATE_BYTES = 5 * 1024 * 1024
MAX_OPEN_BACKLOG = 100
MAX_HISTORY = 200
MAX_DELTAS = 200
MAX_TEXT = 2000
MAX_SEATS = 15
MAX_LEVERAGE = 1000.0
MIN_CODERS = 3
MIN_REVIEWERS = 6

PHASES = ("SCAN", "BUILD", "REVIEW", "FIX_VERIFY", "SELF_IMPROVE", "SHIP")
ITEM_STATUSES = ("pending", "active", "done", "blocked")
_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_BAD_CHARS = set("\u200b\u200c\u200d\ufeff\u202a\u202b\u202c\u202d\u202e\u2060")


class InvalidTransition(Exception):
    """Raised when a phase move or gate check is not allowed."""


class CorruptStateError(Exception):
    """Raised when persisted state cannot be trusted."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reject_constant(value: str):
    raise CorruptStateError(f"non-finite number in state: {value}")


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise CorruptStateError(f"non-finite number in state: {text}")
    return value


def _no_duplicate_keys(pairs):
    # Strict parsing (Trust Boundary v3.1, parser inventory):
    # duplicate keys are refused by the PARSER, matching the
    # non-finite hooks above, so this loader can never disagree
    # with a strict consumer (e.g. signing.state_snapshot's
    # parse_state_bytes, which reads the same state document)
    # about what the state says.
    out = {}
    for key, value in pairs:
        if key in out:
            raise CorruptStateError(f"duplicate key in state: {key}")
        out[key] = value
    return out


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


def _check_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{field} exceeds {MAX_TEXT} characters")
    for ch in value:
        code = ord(ch)
        if (ch in _BAD_CHARS or unicodedata.category(ch) == "Cf"
                or (code < 32 and ch not in "\t") or 0x7F <= code <= 0x9F
                or code in (0x2028, 0x2029) or 0xFE00 <= code <= 0xFE0F):
            raise ValueError(f"{field} contains control or invisible characters")
    return value


def _title_hash(title: str) -> str:
    normalised = unicodedata.normalize("NFKC", title).casefold()
    return hashlib.sha256(" ".join(normalised.split()).encode("utf-8")).hexdigest()


def _check_participants(values, field: str, minimum: int) -> list:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise InvalidTransition(f"{field} must be a list of ids")
    if len(values) > MAX_SEATS:
        raise InvalidTransition(f"{field} exceeds {MAX_SEATS} seats")
    out = []
    for value in values:
        try:
            out.append(_check_id(value, f"{field} entry"))
        except ValueError as exc:
            raise InvalidTransition(str(exc)) from exc
    if len(set(out)) < minimum:
        raise InvalidTransition(f"{field} requires at least {minimum} distinct ids")
    return out


class CoreLoop:
    """One state file, sequential gated cycles, atomic persistence.

    ``cycle_hook`` (keyword-only, default None) is an opaque
    callable invoked by run_one_cycle once per recorded cycle,
    after persistence — see run_one_cycle for the contract. The
    loop neither knows nor cares what the hook does; integrations
    that must react to a recorded cycle (e.g. pinning its
    snapshot) inject one instead of wrapping the loop.
    """

    def __init__(self, state_dir, *, cycle_hook=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "state.json"
        self._cycle_hook = cycle_hook
        self.state = self._load()

    @property
    def cycle_hook(self):
        """The constructor-injected cycle hook, or None (read-only)."""
        return self._cycle_hook

    # -- persistence -----------------------------------------------------

    def _fresh(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "cycle_seq": 0,
            "phase": "SCAN",
            "backlog": [],
            "history": [],
            "deltas": [],
            "history_pruned": 0,
            "deltas_pruned": 0,
            "current_item_id": None,
        }

    def _load(self) -> dict:
        if not self.state_path.exists():
            return self._fresh()
        if self.state_path.stat().st_size > MAX_STATE_BYTES:
            raise CorruptStateError("state file exceeds size cap")
        raw = self.state_path.read_bytes()[: MAX_STATE_BYTES + 1]
        if len(raw) > MAX_STATE_BYTES:
            raise CorruptStateError("state file exceeds size cap")
        try:
            data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                              parse_float=_parse_float,
                              object_pairs_hook=_no_duplicate_keys)
        except CorruptStateError:
            raise
        except Exception as exc:
            self._quarantine(raw)
            raise CorruptStateError(f"unreadable state: {exc}") from exc
        self._validate(data)
        return data

    def _quarantine(self, raw: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            (self.state_dir / f"state.corrupt-{stamp}.json").write_bytes(raw)
        except OSError:
            pass

    def _validate(self, data) -> None:
        def bad(msg):
            raise CorruptStateError(msg)

        if not isinstance(data, dict):
            bad("state is not an object")
        if not _is_int(data.get("schema_version")) or data["schema_version"] != SCHEMA_VERSION:
            bad("unsupported schema_version")
        if data.get("phase") not in PHASES:
            bad("unknown phase in state")
        if not _is_int(data.get("cycle_seq")) or data["cycle_seq"] < 0:
            bad("bad cycle_seq")
        for key in ("history_pruned", "deltas_pruned"):
            if not _is_int(data.get(key)) or data[key] < 0:
                bad(f"bad {key}")
        backlog, history, deltas = data.get("backlog"), data.get("history"), data.get("deltas")
        if not all(isinstance(x, list) for x in (backlog, history, deltas)):
            bad("backlog/history/deltas must be lists")
        if len(history) > MAX_HISTORY or len(deltas) > MAX_DELTAS:
            bad("history/deltas exceed cap")

        seen_ids, seen_hashes = set(), set()
        statuses = {}
        open_count = 0
        for it in backlog:
            if not isinstance(it, dict):
                bad("backlog entry is not an object")
            try:
                _check_id(it.get("id"), "item id")
                _check_text(it.get("title"), "item title")
                leverage = _finite(it.get("leverage"), "leverage")
            except ValueError as exc:
                bad(str(exc))
            if not 0 <= leverage <= MAX_LEVERAGE:
                bad("leverage out of range")
            if it.get("title_hash") != _title_hash(it["title"]):
                bad("title_hash mismatch")
            if it.get("status") not in ITEM_STATUSES:
                bad("unknown item status")
            if it.get("source_type") not in ("internal", "external_scan"):
                bad("unknown source_type")
            if not isinstance(it.get("approved"), bool):
                bad("approved must be a bool")
            approver = it.get("approved_by")
            if approver is not None:
                try:
                    _check_id(approver, "approved_by")
                except ValueError as exc:
                    bad(str(exc))
            if it["approved"] and approver is None:
                bad("approved item without an approver")
            if not _is_int(it.get("seq")) or it["seq"] < 0:
                bad("bad item seq")
            if it["id"] in seen_ids or it["title_hash"] in seen_hashes:
                bad("duplicate backlog id or title")
            seen_ids.add(it["id"])
            seen_hashes.add(it["title_hash"])
            statuses[it["id"]] = it["status"]
            if it["status"] != "done":
                open_count += 1
        if open_count > MAX_OPEN_BACKLOG:
            bad("open backlog exceeds cap")

        last_cycle = 0
        coders_by_cycle = {}
        reviewers_by_cycle = {}
        for entry in history:
            if not isinstance(entry, dict):
                bad("history entry is not an object")
            if not _is_int(entry.get("cycle_id")) or entry["cycle_id"] <= last_cycle:
                bad("history cycle_id is not strictly increasing")
            last_cycle = entry["cycle_id"]
            if entry.get("item_id") not in seen_ids:
                bad("history item_id not in backlog")
            try:
                coders = _check_participants(entry.get("coders"), "coders", MIN_CODERS)
                reviewers = _check_participants(entry.get("reviewers"), "reviewers", MIN_REVIEWERS)
            except InvalidTransition as exc:
                bad(str(exc))
            if set(coders) & set(reviewers):
                bad("coders and reviewers overlap in history")
            if entry.get("verdict") != "reconciled" or entry.get("verify_passed") is not True:
                bad("history entry did not pass its gates")
            coders_by_cycle[entry["cycle_id"]] = set(coders)
            reviewers_by_cycle[entry["cycle_id"]] = set(reviewers)
        if data["cycle_seq"] != last_cycle:
            bad("cycle_seq does not equal the last history cycle_id")
        shipped_items = [e["item_id"] for e in history]
        if len(shipped_items) != len(set(shipped_items)):
            bad("one backlog item is credited with more than one cycle")
        for item_id, status in statuses.items():
            if (status == "done") != (item_id in shipped_items):
                bad("item status and history disagree")

        for delta in deltas:
            if not isinstance(delta, dict):
                bad("delta entry is not an object")
            if delta.get("cycle_id") not in coders_by_cycle:
                bad("delta without a matching history entry")
            try:
                _check_text(delta.get("metric"), "delta metric")
                _check_text(delta.get("evidence_ref"), "delta evidence_ref")
                before = _finite(delta.get("before"), "delta before")
                after = _finite(delta.get("after"), "delta after")
                change = _finite(delta.get("change"), "delta change")
            except ValueError as exc:
                bad(str(exc))
            if after <= before or abs(change - (after - before)) > 1e-9:
                bad("delta is not a recorded improvement")
            if delta.get("verifier") in coders_by_cycle[delta["cycle_id"]]:
                bad("delta verifier was a builder")
            if delta.get("verifier") not in reviewers_by_cycle[delta["cycle_id"]]:
                bad("delta verifier was not a reviewer for that cycle")

        current = data.get("current_item_id")
        if current is not None and current not in seen_ids:
            bad("current_item_id not in backlog")

    def save(self) -> None:
        self._validate(self.state)
        payload = json.dumps(self.state, ensure_ascii=False, indent=2,
                             allow_nan=False).encode("utf-8")
        if len(payload) > MAX_STATE_BYTES:
            raise ValueError("state exceeds size cap")
        fd, tmp = tempfile.mkstemp(dir=self.state_dir, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.state_path)
            dir_fd = os.open(self.state_dir, os.O_DIRECTORY)
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

    # -- backlog (SCAN) ---------------------------------------------------

    def scan(self, items) -> int:
        """Add backlog items atomically. Returns how many were added.

        Items from external scans are never approved by intake; they need
        a separate approve() call before they can be picked.
        """
        existing_ids = {it["id"] for it in self.state["backlog"]}
        existing_hashes = {it["title_hash"] for it in self.state["backlog"]}
        open_count = sum(1 for it in self.state["backlog"] if it["status"] != "done")
        next_seq = max((it["seq"] for it in self.state["backlog"]), default=-1) + 1
        new_items = []
        batch_ids, batch_hashes = set(), set()
        for raw in items:
            if not isinstance(raw, dict):
                raise ValueError("backlog item must be an object")
            item_id = _check_id(raw.get("id"), "item id")
            title = _check_text(raw.get("title"), "item title")
            leverage = _finite(raw.get("leverage", 0), "leverage")
            if not 0 <= leverage <= MAX_LEVERAGE:
                raise ValueError("leverage out of range")
            title_hash = _title_hash(title)
            if item_id in existing_ids or item_id in batch_ids:
                raise ValueError(f"duplicate backlog id: {item_id}")
            if title_hash in existing_hashes or title_hash in batch_hashes:
                continue  # duplicate content: dedup, do not re-add
            source_type = raw.get("source_type", "internal")
            if source_type not in ("internal", "external_scan"):
                raise ValueError("unknown source_type")
            if open_count + len(new_items) >= MAX_OPEN_BACKLOG:
                raise ValueError("open backlog cap reached")
            new_items.append({
                "id": item_id,
                "title": title,
                "title_hash": title_hash,
                "leverage": leverage,
                "status": "pending",
                "source_type": source_type,
                "approved": source_type == "internal",
                "approved_by": "intake" if source_type == "internal" else None,
                "seq": next_seq + len(new_items),
            })
            batch_ids.add(item_id)
            batch_hashes.add(title_hash)
        snapshot = copy.deepcopy(self.state)
        self.state["backlog"].extend(new_items)
        try:
            self.save()
        except BaseException:
            self.state = snapshot
            raise
        return len(new_items)

    def approve(self, item_id, approver) -> None:
        """Approve a pending item (required for externally scanned items)."""
        _check_id(item_id, "item id")
        approver = _check_id(approver, "approver")
        for it in self.state["backlog"]:
            if it["id"] == item_id:
                if it["status"] != "pending":
                    raise ValueError(f"only a pending item can be approved: {item_id}")
                snapshot = copy.deepcopy(self.state)
                it["approved"] = True
                it["approved_by"] = approver
                try:
                    self.save()
                except BaseException:
                    self.state = snapshot
                    raise
                return
        raise ValueError(f"unknown backlog item: {item_id}")

    def pick_next(self):
        """Highest-leverage pending, approved item; ties break by insertion.

        Returns a copy, so callers cannot mutate stored state through it.
        """
        candidates = [
            it for it in self.state["backlog"]
            if it["status"] == "pending" and it["approved"]
        ]
        if not candidates:
            return None
        return copy.deepcopy(min(candidates, key=lambda it: (-it["leverage"], it["seq"])))

    # -- cycles -------------------------------------------------------------

    def run_one_cycle(self, coders, reviewers, verdict, verify_passed, delta):
        """Run one full cycle. Returns the history entry, or None if idle.

        All gates are checked before anything is persisted, and the cycle
        is written in a single save: a failed or interrupted cycle leaves
        the stored state exactly as it was.

        When a cycle_hook was injected, it is called exactly once
        with the recorded entry, AFTER the persistence above has
        completed — the snapshot-restore path does not run for hook
        failures. The contract is "cycle recorded, pin pending,
        alert": a hook exception propagates unwrapped, the cycle
        stays recorded, and stored state is exactly what the save
        wrote. Idle cycles (no pickable item) never fire the hook.
        """
        if self.state["phase"] != "SCAN":
            raise InvalidTransition(f"cycle must start at SCAN, not {self.state['phase']}")
        item = self.pick_next()
        if item is None:
            return None

        coders = _check_participants(coders, "coders", MIN_CODERS)
        reviewers = _check_participants(reviewers, "reviewers", MIN_REVIEWERS)
        if set(coders) & set(reviewers):
            raise InvalidTransition("reviewers must not be builders")
        if verdict != "reconciled":
            raise InvalidTransition("cannot ship on a split or missing verdict")
        if verify_passed is not True:
            raise InvalidTransition("verification must pass before shipping")
        checked_delta = self._check_delta(delta, builders=set(coders),
                                          reviewers=set(reviewers))

        snapshot = copy.deepcopy(self.state)
        try:
            stored = next(it for it in self.state["backlog"] if it["id"] == item["id"])
            stored["status"] = "done"
            self.state["cycle_seq"] += 1
            cycle_id = self.state["cycle_seq"]
            entry = {
                "cycle_id": cycle_id,
                "item_id": item["id"],
                "phases": list(PHASES),
                "coders": coders,
                "reviewers": reviewers,
                "verdict": verdict,
                "verify_passed": True,
                "completed_at": _now(),
            }
            self.state["history"].append(entry)
            if len(self.state["history"]) > MAX_HISTORY:
                dropped = len(self.state["history"]) - MAX_HISTORY
                self.state["history"] = self.state["history"][dropped:]
                self.state["history_pruned"] += dropped
            self.state["deltas"].append(checked_delta | {"cycle_id": cycle_id})
            if len(self.state["deltas"]) > MAX_DELTAS:
                dropped = len(self.state["deltas"]) - MAX_DELTAS
                self.state["deltas"] = self.state["deltas"][dropped:]
                self.state["deltas_pruned"] += dropped
            self.save()
        except BaseException:
            self.state = snapshot
            raise
        if self._cycle_hook is not None:
            self._cycle_hook(copy.deepcopy(entry))
        return copy.deepcopy(entry)

    def _check_delta(self, delta, builders: set, reviewers: set) -> dict:
        if not isinstance(delta, dict):
            raise InvalidTransition("self-improvement requires a delta record")
        try:
            metric = _check_text(delta.get("metric"), "delta metric")
            before = _finite(delta.get("before"), "delta before")
            after = _finite(delta.get("after"), "delta after")
            evidence = _check_text(delta.get("evidence_ref"), "delta evidence_ref")
        except ValueError as exc:
            raise InvalidTransition(str(exc)) from exc
        if after <= before:
            raise InvalidTransition("delta must show an improvement (after > before)")
        change = after - before
        if not math.isfinite(change):
            raise InvalidTransition("delta change must be finite")
        verifier = delta.get("verifier")
        if verifier not in reviewers:
            raise InvalidTransition("delta verifier must be one of the reviewers")
        if verifier in builders:
            raise InvalidTransition("delta verifier must not be a builder")
        return {
            "metric": metric,
            "before": before,
            "after": after,
            "change": change,
            "evidence_ref": evidence,
            "verifier": verifier,
            "recorded_at": _now(),
        }
