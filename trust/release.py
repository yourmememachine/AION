"""Release records: the third document that breaks the circle.

The manifest cannot name the decision that authorises it (the
decision binds the manifest hash — a manifest naming the decision
would be circular), and the decision cannot name the recorded
cycle (the cycle exists only after the ship records it). The
release record ties the three together: manifest hash, decision
id, review-record hash, the exact pre-ship loop state the ship
expects to extend, and — once recorded — the cycle id it became.
It lives with the manifest under state/trust/<proposal_id>/,
outside the manifest's own scope.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from trust.manifest import ManifestError

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")


def _rid(value, field_name):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ManifestError(f"{field_name} must match ^[a-z0-9_-]{{1,64}}$")
    return value

RELEASE_VERSION = "release-record/1"
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_KEYS = {"v", "proposal_id", "item_id", "stage", "manifest_hash",
         "decision_id", "payload_hash", "review_record_hash",
         "expected_cycle_id", "pre_ship_state", "status", "cycle_id",
         "completed_at"}
_PRE_STATE_KEYS = {"cycle_seq", "state_file_sha256"}
_STATUSES = ("prepared", "recorded")


@dataclass(frozen=True)
class ReleaseRecord:
    proposal_id: str
    item_id: str
    stage: str
    manifest_hash: str
    decision_id: str          # "" when no ship envelope exists yet
    payload_hash: str         # "" likewise
    review_record_hash: str
    expected_cycle_id: int    # the loop's next cycle number
    pre_ship_cycle_seq: int
    pre_ship_state_sha256: str
    status: str = "prepared"
    cycle_id: int = 0         # 0 until recorded
    completed_at: str = ""

    def completed(self, *, cycle_id: int, completed_at: str):
        """The recorded form of this release: same bindings, status
        flipped, cycle named. The ship path returns this so the
        third document is actually tied to the recorded cycle."""
        import dataclasses
        if self.status != "prepared":
            raise ManifestError("only a prepared release can complete")
        if cycle_id != self.expected_cycle_id:
            raise ManifestError(
                "completed cycle does not match the expected cycle")
        return dataclasses.replace(
            self, status="recorded", cycle_id=cycle_id,
            completed_at=completed_at)

    def to_dict(self) -> dict:
        return {
            "v": RELEASE_VERSION,
            "proposal_id": self.proposal_id,
            "item_id": self.item_id,
            "stage": self.stage,
            "manifest_hash": self.manifest_hash,
            "decision_id": self.decision_id,
            "payload_hash": self.payload_hash,
            "review_record_hash": self.review_record_hash,
            "expected_cycle_id": self.expected_cycle_id,
            "pre_ship_state": {
                "cycle_seq": self.pre_ship_cycle_seq,
                "state_file_sha256": self.pre_ship_state_sha256,
            },
            "status": self.status,
            "cycle_id": self.cycle_id,
            "completed_at": self.completed_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)


def _hex64_or_empty(value, field_name, *, allow_empty):
    if value == "" and allow_empty:
        return value
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise ManifestError(f"{field_name} must be a lowercase hex64")
    return value


def build_release_record(manifest, signed, *, expected_cycle_id,
                         pre_ship_cycle_seq, pre_ship_state_sha256,
                         status="prepared", cycle_id=0,
                         completed_at="") -> ReleaseRecord:
    """Assemble a release record from a manifest and (optionally)
    the ship envelope that authorises it. signed may be None for a
    prepared record whose envelope does not exist yet."""
    if signed is not None:
        if signed.decision.proposal_id != manifest.proposal_id:
            raise ManifestError(
                "ship envelope is for a different proposal than the "
                "manifest")
        if signed.gate_inputs_hash != manifest.manifest_hash:
            raise ManifestError(
                "ship envelope is not bound to this manifest")
        decision_id, payload_hash = signed.decision_id, signed.payload_hash
    else:
        decision_id, payload_hash = "", ""
    if not isinstance(expected_cycle_id, int) \
            or isinstance(expected_cycle_id, bool) \
            or expected_cycle_id < 1:
        raise ManifestError("expected_cycle_id must be a positive int")
    return ReleaseRecord(
        proposal_id=manifest.proposal_id, item_id=manifest.item_id,
        stage=manifest.stage, manifest_hash=manifest.manifest_hash,
        decision_id=decision_id, payload_hash=payload_hash,
        review_record_hash=manifest.review_record["record_hash"],
        expected_cycle_id=expected_cycle_id,
        pre_ship_cycle_seq=pre_ship_cycle_seq,
        pre_ship_state_sha256=pre_ship_state_sha256,
        status=status, cycle_id=cycle_id, completed_at=completed_at)


def release_from_dict(data) -> ReleaseRecord:
    if not isinstance(data, dict) or set(data) != _KEYS:
        raise ManifestError("release record has missing or unknown keys")
    if data["v"] != RELEASE_VERSION:
        raise ManifestError("release record version is wrong")
    _rid(data["proposal_id"], "proposal id")
    _rid(data["item_id"], "item id")
    if data["stage"] not in ("provisional", "final"):
        raise ManifestError("release record stage is unknown")
    _hex64_or_empty(data["manifest_hash"], "manifest_hash",
                    allow_empty=False)
    _hex64_or_empty(data["decision_id"], "decision_id", allow_empty=True)
    _hex64_or_empty(data["payload_hash"], "payload_hash", allow_empty=True)
    _hex64_or_empty(data["review_record_hash"], "review_record_hash",
                    allow_empty=False)
    if not isinstance(data["expected_cycle_id"], int) \
            or isinstance(data["expected_cycle_id"], bool) \
            or data["expected_cycle_id"] < 1:
        raise ManifestError("expected_cycle_id must be a positive int")
    pre = data["pre_ship_state"]
    if not isinstance(pre, dict) or set(pre) != _PRE_STATE_KEYS:
        raise ManifestError("pre_ship_state has missing or unknown keys")
    if not isinstance(pre["cycle_seq"], int) \
            or isinstance(pre["cycle_seq"], bool) or pre["cycle_seq"] < 0:
        raise ManifestError("pre_ship_state.cycle_seq must be a "
                            "non-negative int")
    _hex64_or_empty(pre["state_file_sha256"], "state_file_sha256",
                    allow_empty=False)
    if data["status"] not in _STATUSES:
        raise ManifestError("release record status is unknown")
    if not isinstance(data["cycle_id"], int) \
            or isinstance(data["cycle_id"], bool) \
            or data["cycle_id"] < 0:
        raise ManifestError("cycle_id must be a non-negative int")
    if data["status"] == "recorded" and not data["cycle_id"]:
        raise ManifestError("a recorded release must name its cycle")
    if data["status"] == "prepared" and data["cycle_id"]:
        raise ManifestError("a prepared release cannot name a cycle")
    return ReleaseRecord(
        proposal_id=data["proposal_id"], item_id=data["item_id"],
        stage=data["stage"], manifest_hash=data["manifest_hash"],
        decision_id=data["decision_id"], payload_hash=data["payload_hash"],
        review_record_hash=data["review_record_hash"],
        expected_cycle_id=data["expected_cycle_id"],
        pre_ship_cycle_seq=pre["cycle_seq"],
        pre_ship_state_sha256=pre["state_file_sha256"],
        status=data["status"], cycle_id=data["cycle_id"],
        completed_at=data["completed_at"])


def release_from_json(text) -> ReleaseRecord:
    if not isinstance(text, str):
        raise ManifestError("release record JSON must be text")

    def _no_duplicates(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ManifestError(f"duplicate key in JSON: {key!r}")
            out[key] = value
        return out

    def _reject_constant(name):
        raise ManifestError(f"non-finite JSON number: {name}")

    def _parse_float(text):
        # Mirror signing/gate_decision.py's parse_float hook: a
        # float token that overflows to inf (e.g. 1e999) is
        # refused by the PARSER, structurally.
        value = float(text)
        if not math.isfinite(value):
            raise ManifestError(f"non-finite JSON number: {text}")
        return value

    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except ManifestError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ManifestError(f"release record is not valid JSON: {exc}") \
            from exc
    return release_from_dict(data)
