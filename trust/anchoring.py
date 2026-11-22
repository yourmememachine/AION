"""External monotonic head anchoring for both trust ledgers.

A HashChainJournal (trust/ledger.py) detects edits, reordering and
truncation of its own file ONLY when its head hash is pinned
somewhere the journal's writer cannot also rewrite. This module is
that pin: a small JSON anchor file that lives OUTSIDE the journal's
directory and records the journal's head at a monotonically
increasing sequence number.

Anchor format (exact key set, versioned)::

    {"v": "ledger-anchor/1", "kind": "signing" | "ship" | "ship-tx",
     "head": <hex64>, "seq": <int>, "anchored_at": <iso timestamp>}

The "ship-tx" kind (cycle 17) pins the ship-transaction journal
(trust/shiptx.py) the same way: that journal is a HashChainJournal
in the ship ledger's own directory, so its anchor is subject to
the identical outside-that-directory placement rule and must use
a path distinct from the ship ledger's anchor.

``seq`` is the number of journal entries the head names: the
genesis head (all-zero, an empty journal) is seq 0, the first
entry's hash is seq 1, and so on. An anchor is therefore a claim
about a PREFIX of the chain: it verifies if and only if the
journal still contains an entry (or the genesis state) whose hash
is ``head`` at exactly position ``seq``.

Operations:

* ``initialise_anchor`` — the first-init ceremony. Creates an
  anchor for the journal's CURRENT head. Refuses if any anchor
  already exists at the path: silently re-pinning a head would
  erase exactly the rollback evidence the anchor exists to keep.
  Also refuses on a NON-EMPTY journal unless the caller passes
  ``allow_nonempty_ceremony=True``: pinning the current head of
  an established ledger would bless whatever history the journal
  currently shows — including a rolled-back one — with no record
  that a ceremony ever took place. The flag is the documented
  first-initialisation ceremony for a pre-existing ledger (one
  that legitimately predates anchoring); the default bootstrap
  path (empty ledger, e.g. verifier_main's AION_ANCHOR_INIT)
  needs no flag and is unchanged.
* ``update_anchor`` — the routine advance after appends. Refuses
  if the existing anchor does not name a prefix of the journal's
  current chain (the journal was rolled back or replaced since
  the anchor was written) or if the new seq would not strictly
  increase. The genesis -> first-entry step is seq 0 -> 1 and is
  a normal update; seq 0 itself is only ever written by
  ``initialise_anchor``.
* ``force_reanchor`` — the explicit, audited escape hatch for a
  legitimate re-pin (e.g. a journal restored from backup on
  purpose). Requires a non-empty reason string, appends nothing
  to the journal, and overwrites the anchor. It also PERSISTS an
  audit record itself: a hash-chained entry
  ``{seq, old_anchor, new_anchor, reason, timestamp, prev_hash,
  entry_hash}`` appended to a reanchor-audit file alongside the
  anchor (see ``reanchor_audit_path``), so the reason and both
  anchors survive with the anchor, not only in some caller's
  private log. It still RETURNS the old anchor for callers that
  keep their own records. A malformed existing audit chain
  refuses the re-pin: overwriting it silently is not an audit.
* ``verify_anchor`` — pure check returning a tuple of refusal
  reasons; ``()`` means the anchor names a prefix of the journal.
  With ``check_reanchor_audit=True`` it additionally verifies
  the reanchor audit chain when one exists.
* ``verify_reanchor_audit`` — pure check of the audit chain
  alone: ``()`` means the chain is intact and its latest entry
  names the current anchor file; ``reanchor_audit_missing``
  means no audit file exists (a refusal exactly when a
  force_reanchor is known or expected to have happened — the
  anchor alone cannot prove one did not, which is why callers
  that rely on the hatch must check).

Verification reasons:

* ``anchor_missing`` — no anchor file, and the journal is empty:
  a pre-init state, not yet a refusal for callers that are about
  to run the ceremony (but see the next reason).
* ``anchor_missing_established_ledger`` — no anchor file, but the
  journal is NON-empty: signatures/burns exist that no anchor ever
  pinned. Callers must treat this as a startup refusal — the
  ledger may have been rolled back and re-grown, and there is no
  way to tell.
* ``anchor_head_not_in_chain`` — the anchor's (head, seq) pair
  names no prefix of the journal: the journal was rolled back to
  a DIFFERENT history, replaced, or (journal empty, anchor head
  not genesis) deleted outright.
* ``anchor_ahead_of_journal`` — the anchor's seq exceeds the
  journal's length: the journal was truncated (or deleted and
  recreated empty/short) below the anchored head.
* ``anchor_kind_mismatch`` — the anchor is for the other ledger.
* ``anchor_malformed`` — the file is not a well-formed anchor.

Honest scope: the anchor is only as external as its location.
Callers must place it outside the journal's directory (this
module refuses a path inside it) and, for a real boundary, on
storage the journal writer cannot rewrite — a verifier-owned
directory under a separate OS user (see
deploy/verifier-identity/), or off-machine. An anchor in a
directory the same attacker can write is a second copy of the
journal's own claim, not a pin. The anchor is unkeyed, like the
journals themselves: it detects rollback by disagreement, it
grants no authority.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from signing.gate_decision import SigningError, _canonical, \
    _parse_time, _sha256
from trust.ledger import GENESIS_HASH

ANCHOR_VERSION = "ledger-anchor/1"
ANCHOR_KINDS = ("signing", "ship", "ship-tx")
_ANCHOR_KEYS = {"v", "kind", "head", "seq", "anchored_at"}
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
MAX_ANCHOR_BYTES = 4096

AUDIT_VERSION = "reanchor-audit/1"
_AUDIT_FILE_KEYS = {"v", "entries"}
_AUDIT_ENTRY_KEYS = {"seq", "old_anchor", "new_anchor", "reason",
                     "timestamp", "prev_hash", "entry_hash"}
MAX_AUDIT_BYTES = 1 << 20


class AnchorError(Exception):
    """An anchor operation was refused (existing anchor, rollback
    signal, non-monotonic update, bad placement, malformed file)."""


# Strict parsing (Trust Boundary v3.1, parser inventory): anchor
# and reanchor-audit documents are parsed under the same contract
# as every other security-relevant consumer — duplicate keys and
# non-finite numbers are refused by the PARSER. The hooks raise
# ValueError so each loader's existing handler maps the failure
# to its own malformed reason (anchor_malformed /
# reanchor_audit_malformed).

def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key in JSON: {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise ValueError(f"non-finite number in JSON: {name}")


def _parse_float_strict(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number in JSON: {text}")
    return value


# -- validation -----------------------------------------------------------


def _check_kind(kind) -> str:
    if kind not in ANCHOR_KINDS:
        raise AnchorError(f"anchor kind must be one of {ANCHOR_KINDS}")
    return kind


def _check_recorded_at(recorded_at) -> str:
    if not isinstance(recorded_at, str) or not recorded_at:
        raise AnchorError("recorded_at must be an ISO timestamp string")
    try:
        _parse_time(recorded_at, "recorded_at")
    except SigningError as exc:
        raise AnchorError(str(exc)) from exc
    return recorded_at


def _check_outside_journal(journal, anchor_path: Path) -> Path:
    """The anchor must not live inside the journal's directory:
    whoever can rewrite the journal directory could rewrite both,
    and the pin would prove nothing."""
    anchor_path = Path(anchor_path)
    if not anchor_path.is_absolute():
        anchor_path = Path(os.path.abspath(anchor_path))
    journal_dir = Path(os.path.abspath(journal.journal_dir))
    resolved_anchor = anchor_path.resolve()
    resolved_journal = journal_dir.resolve()
    if resolved_anchor == resolved_journal \
            or resolved_journal in resolved_anchor.parents:
        raise AnchorError(
            "anchor path must live OUTSIDE the journal's directory")
    return anchor_path


def _validate_anchor(data) -> dict:
    """Return the anchor dict or raise AnchorError(malformed)."""
    if not isinstance(data, dict) or set(data) != _ANCHOR_KEYS:
        raise AnchorError("anchor_malformed")
    if data["v"] != ANCHOR_VERSION:
        raise AnchorError("anchor_malformed")
    if data["kind"] not in ANCHOR_KINDS:
        raise AnchorError("anchor_malformed")
    if not isinstance(data["head"], str) \
            or not _HEX64_RE.fullmatch(data["head"]):
        raise AnchorError("anchor_malformed")
    if not isinstance(data["seq"], int) \
            or isinstance(data["seq"], bool) or data["seq"] < 0:
        raise AnchorError("anchor_malformed")
    if not isinstance(data["anchored_at"], str) \
            or not data["anchored_at"]:
        raise AnchorError("anchor_malformed")
    try:
        _parse_time(data["anchored_at"], "anchored_at")
    except SigningError as exc:
        raise AnchorError("anchor_malformed") from exc
    return data


def _read_anchor(anchor_path: Path):
    """The parsed anchor dict, or None when the file is absent.
    Raises AnchorError('anchor_malformed') on any bad content."""
    try:
        raw = anchor_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AnchorError(f"anchor is unreadable: {exc}") from exc
    if len(raw) > MAX_ANCHOR_BYTES:
        raise AnchorError("anchor_malformed")
    try:
        data = json.loads(raw.decode("utf-8"),
                          object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float_strict)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AnchorError("anchor_malformed") from exc
    return _validate_anchor(data)


def load_anchor(anchor_path):
    """Public read: the anchor dict, or None when absent.
    Raises AnchorError on a malformed or unreadable anchor."""
    return _read_anchor(Path(anchor_path))


# -- chain view -------------------------------------------------------------


def _chain_prefixes(journal) -> dict:
    """{seq: head} for every prefix of the journal's chain,
    including the genesis prefix {0: GENESIS_HASH}. Reloads the
    journal from disk first, so a long-lived instance never
    answers from a stale in-memory snapshot (another process —
    or a rollback — may have changed the file since load)."""
    journal._reload()
    prefixes = {0: GENESIS_HASH}
    for entry in journal.entries():
        prefixes[entry["seq"]] = entry["entry_hash"]
    return prefixes


def _current_anchor(journal, *, kind, recorded_at) -> dict:
    prefixes = _chain_prefixes(journal)
    seq = max(prefixes)
    return {"v": ANCHOR_VERSION, "kind": kind, "head": prefixes[seq],
            "seq": seq, "anchored_at": recorded_at}


# -- atomic write -----------------------------------------------------------


def _write_json_atomic(path: Path, data) -> None:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / ("." + path.name + f".tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_anchor(anchor_path: Path, anchor: dict) -> None:
    _write_json_atomic(anchor_path, anchor)


# -- reanchor audit chain ---------------------------------------------------


def reanchor_audit_path(anchor_path) -> Path:
    """The audit file for an anchor: alongside it, named from the
    anchor's stem so a signing and a ship anchor sharing one
    directory keep separate chains — e.g. ``signing.anchor.json``
    -> ``signing.reanchor-audit.json``."""
    anchor_path = Path(anchor_path)
    return anchor_path.parent / (anchor_path.stem + ".reanchor-audit.json")


def _audit_entry_hash(core: dict) -> str:
    return _sha256(_canonical(core))


def _validate_audit_entry(entry) -> dict:
    if not isinstance(entry, dict) or set(entry) != _AUDIT_ENTRY_KEYS:
        raise AnchorError("reanchor_audit_malformed")
    if not isinstance(entry["seq"], int) \
            or isinstance(entry["seq"], bool) or entry["seq"] < 1:
        raise AnchorError("reanchor_audit_malformed")
    for field in ("old_anchor", "new_anchor"):
        value = entry[field]
        if value is not None:
            try:
                _validate_anchor(value)
            except AnchorError as exc:
                raise AnchorError("reanchor_audit_malformed") from exc
    if not isinstance(entry["reason"], str) \
            or not entry["reason"].strip():
        raise AnchorError("reanchor_audit_malformed")
    if not isinstance(entry["timestamp"], str) \
            or not entry["timestamp"]:
        raise AnchorError("reanchor_audit_malformed")
    try:
        _parse_time(entry["timestamp"], "timestamp")
    except SigningError as exc:
        raise AnchorError("reanchor_audit_malformed") from exc
    for field in ("prev_hash", "entry_hash"):
        if not isinstance(entry[field], str) \
                or not _HEX64_RE.fullmatch(entry[field]):
            raise AnchorError("reanchor_audit_malformed")
    core = {k: entry[k] for k in entry if k != "entry_hash"}
    if _audit_entry_hash(core) != entry["entry_hash"]:
        raise AnchorError("reanchor_audit_chain_broken")
    return entry


def _read_audit(audit_path: Path):
    """The validated entry list, or None when the file is absent.
    Raises AnchorError('reanchor_audit_malformed' /
    'reanchor_audit_chain_broken') on any bad content: wrong
    shape, a seq gap, a prev_hash that does not link to the
    previous entry (or to genesis for the first), or a bad
    entry hash."""
    try:
        raw = audit_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AnchorError(f"reanchor audit is unreadable: {exc}") from exc
    if len(raw) > MAX_AUDIT_BYTES:
        raise AnchorError("reanchor_audit_malformed")
    try:
        data = json.loads(raw.decode("utf-8"),
                          object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float_strict)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AnchorError("reanchor_audit_malformed") from exc
    if not isinstance(data, dict) or set(data) != _AUDIT_FILE_KEYS \
            or data["v"] != AUDIT_VERSION \
            or not isinstance(data["entries"], list):
        raise AnchorError("reanchor_audit_malformed")
    prev = GENESIS_HASH
    for position, entry in enumerate(data["entries"], start=1):
        _validate_audit_entry(entry)
        if entry["seq"] != position or entry["prev_hash"] != prev:
            raise AnchorError("reanchor_audit_chain_broken")
        prev = entry["entry_hash"]
    return data["entries"]


def load_reanchor_audit(anchor_path):
    """Public read: the audit entry list for an anchor, or None
    when no reanchor has ever been recorded for it. Raises
    AnchorError on a malformed or broken chain."""
    return _read_audit(reanchor_audit_path(anchor_path))


def _append_audit(anchor_path: Path, *, old_anchor, new_anchor,
                  reason, timestamp) -> dict:
    """Append one hash-chained entry to the anchor's audit file
    and return it. A malformed/broken existing chain refuses
    (AnchorError propagates): a re-pin never papers over the
    record of previous re-pins."""
    audit_path = reanchor_audit_path(anchor_path)
    entries = _read_audit(audit_path) or []
    core = {"seq": len(entries) + 1,
            "old_anchor": old_anchor,
            "new_anchor": new_anchor,
            "reason": reason,
            "timestamp": timestamp,
            "prev_hash": entries[-1]["entry_hash"] if entries
            else GENESIS_HASH}
    entry = dict(core, entry_hash=_audit_entry_hash(core))
    _write_json_atomic(audit_path, {"v": AUDIT_VERSION,
                                    "entries": entries + [entry]})
    return entry


def verify_reanchor_audit(anchor_path) -> tuple:
    """Refusal reasons for an anchor's reanchor audit chain; ()
    means the chain is intact AND the current anchor file is
    consistent with its latest entry: equal to that entry's
    new_anchor, or ADVANCED past it (higher seq — the normal
    update_anchor path after a re-pin; update_anchor itself
    refuses to advance over a non-prefix anchor). An anchor at a
    LOWER seq than the last recorded re-pin, or at the same seq
    with a different head, was rewritten outside both paths and
    is ``reanchor_audit_anchor_mismatch``.

    ``reanchor_audit_missing`` when no audit file exists: that is
    the normal state before any force_reanchor, and a refusal
    exactly when the caller knows a re-pin should have been
    recorded. ``reanchor_audit_malformed`` /
    ``reanchor_audit_chain_broken`` for a present-but-bad chain."""
    anchor_path = Path(anchor_path)
    try:
        entries = _read_audit(reanchor_audit_path(anchor_path))
    except AnchorError as exc:
        return (str(exc),)
    if entries is None:
        return ("reanchor_audit_missing",)
    if not entries:
        return ()
    try:
        anchor = _read_anchor(anchor_path)
    except AnchorError:
        return ("anchor_malformed",)
    if anchor is None:
        return ("anchor_missing",)
    pinned = entries[-1]["new_anchor"]
    if pinned is None or anchor["seq"] < pinned["seq"] \
            or (anchor["seq"] == pinned["seq"]
                and anchor["head"] != pinned["head"]):
        return ("reanchor_audit_anchor_mismatch",)
    return ()


# -- operations -------------------------------------------------------------


def initialise_anchor(journal, anchor_path, *, kind, recorded_at,
                      allow_nonempty_ceremony=False) -> dict:
    """First-init ceremony: pin the journal's CURRENT head.

    Refuses when an anchor already exists at the path (any head,
    any kind, even a malformed file — a file is there, and the
    ceremony does not overwrite evidence).

    Established-ledger guard: also refuses when the journal is
    NON-EMPTY, unless ``allow_nonempty_ceremony=True``. Pinning
    the current head of a journal that already has entries would
    bless exactly the history now on disk — and if that journal
    was rolled back first, the ceremony would launder the
    rollback into a valid anchor with no trace. The flag is the
    explicit, documented ceremony for a ledger that legitimately
    predates anchoring; an operator passing it asserts the
    current history is the true one. The empty-ledger bootstrap
    (the default call sites) is unaffected. Returns the anchor
    written."""
    kind = _check_kind(kind)
    recorded_at = _check_recorded_at(recorded_at)
    anchor_path = _check_outside_journal(journal, Path(anchor_path))
    if anchor_path.exists() or anchor_path.is_symlink():
        raise AnchorError(
            "an anchor already exists at this path; refusing to "
            "re-anchor (use force_reanchor with a recorded reason "
            "for an explicit, audited re-pin)")
    anchor = _current_anchor(journal, kind=kind,
                             recorded_at=recorded_at)
    if anchor["seq"] > 0 and not allow_nonempty_ceremony:
        raise AnchorError(
            "initialise_anchor on a non-empty journal requires "
            "allow_nonempty_ceremony=True: pinning an established "
            "ledger's current head blesses its history as-is, "
            "including a rolled-back one; pass the flag only as "
            "the documented first-initialisation ceremony for a "
            "pre-existing ledger")
    _write_anchor(anchor_path, anchor)
    return dict(anchor)


def update_anchor(journal, anchor_path, *, kind, recorded_at) -> dict:
    """Advance the anchor to the journal's current head after
    appends. Refuses when: no anchor exists (run the ceremony);
    the anchor is malformed or for the other ledger; the existing
    anchor's (head, seq) names no prefix of the journal's chain
    (rollback / replacement signal); or the new seq would not
    strictly increase (no appends since the last anchor — the
    genesis -> first-entry step is seq 0 -> 1 here; seq 0 itself
    is written only by initialise_anchor). Returns the anchor
    written."""
    kind = _check_kind(kind)
    recorded_at = _check_recorded_at(recorded_at)
    anchor_path = _check_outside_journal(journal, Path(anchor_path))
    existing = _read_anchor(anchor_path)
    if existing is None:
        raise AnchorError(
            "no anchor exists at this path; run initialise_anchor "
            "as the explicit first-init ceremony")
    if existing["kind"] != kind:
        raise AnchorError("anchor_kind_mismatch")
    prefixes = _chain_prefixes(journal)
    if prefixes.get(existing["seq"]) != existing["head"]:
        raise AnchorError(
            "anchor_head_not_in_chain: the existing anchor names "
            "no prefix of this journal — the journal was rolled "
            "back or replaced; refusing to advance the anchor "
            "over the evidence")
    new_seq = max(prefixes)
    if new_seq <= existing["seq"]:
        raise AnchorError(
            "anchor update would not strictly increase seq "
            f"({existing['seq']} -> {new_seq}); nothing to anchor")
    anchor = {"v": ANCHOR_VERSION, "kind": kind,
              "head": prefixes[new_seq], "seq": new_seq,
              "anchored_at": recorded_at}
    _write_anchor(anchor_path, anchor)
    return dict(anchor)


def force_reanchor(journal, anchor_path, *, kind, reason,
                   recorded_at) -> dict | None:
    """Explicit, audited re-pin: overwrite the anchor with the
    journal's current head, appending NOTHING to the journal.

    ``reason`` must be a non-empty string. It is not stored in the
    anchor (the anchor format has no field for it) — instead this
    function itself appends a hash-chained audit entry
    ``{seq, old_anchor, new_anchor, reason, timestamp,
    prev_hash, entry_hash}`` to the reanchor-audit file alongside
    the anchor (see ``reanchor_audit_path`` /
    ``verify_reanchor_audit``), BEFORE writing the new anchor, so
    a crash mid-re-pin leaves the record pointing at the old
    anchor rather than a re-pin with no record. A malformed or
    broken existing audit chain refuses the re-pin. Returns the
    old anchor dict, or None when no anchor existed (a
    force_reanchor over nothing is equivalent to the ceremony,
    but the caller asked for the explicit form, so it is
    honoured — and audited the same way)."""
    kind = _check_kind(kind)
    recorded_at = _check_recorded_at(recorded_at)
    if not isinstance(reason, str) or not reason.strip():
        raise AnchorError(
            "force_reanchor requires a non-empty reason string; "
            "it is persisted in the reanchor audit chain")
    anchor_path = _check_outside_journal(journal, Path(anchor_path))
    old = _read_anchor(anchor_path)  # malformed old anchor refuses:
    # overwriting unreadable evidence silently is not an audit.
    anchor = _current_anchor(journal, kind=kind,
                             recorded_at=recorded_at)
    _append_audit(anchor_path, old_anchor=old, new_anchor=anchor,
                  reason=reason, timestamp=recorded_at)
    _write_anchor(anchor_path, anchor)
    return old


def verify_anchor(journal, anchor_path, *, kind,
                  check_reanchor_audit=False) -> tuple:
    """Refusal reasons for this journal against its anchor; ()
    means the anchor names a prefix of the journal's chain.

    An anchor naming an OLDER prefix (the journal has grown since
    the last update) verifies: staleness is not tampering, and
    update_anchor is the remedy. Journal-empty with an anchor at
    genesis is the valid pre-init state; journal-empty with a
    non-genesis anchor is a deleted ledger and refuses.

    With ``check_reanchor_audit=True``, a reanchor audit chain
    that EXISTS for this anchor is additionally verified (see
    ``verify_reanchor_audit``) and any audit refusal reasons are
    appended. A MISSING audit file adds no reason here: no
    re-pin may ever have happened, and the anchor alone cannot
    prove one did — callers that know a re-pin occurred must use
    ``verify_reanchor_audit`` directly, where missing is a
    refusal."""
    kind = _check_kind(kind)
    anchor_path = _check_outside_journal(journal, Path(anchor_path))
    prefixes = _chain_prefixes(journal)
    journal_len = max(prefixes)
    try:
        anchor = _read_anchor(anchor_path)
    except AnchorError:
        return ("anchor_malformed",)
    if anchor is None:
        if journal_len > 0:
            return ("anchor_missing_established_ledger",)
        return ("anchor_missing",)
    if anchor["kind"] != kind:
        return ("anchor_kind_mismatch",)
    if anchor["seq"] > journal_len:
        return ("anchor_ahead_of_journal",)
    if prefixes.get(anchor["seq"]) != anchor["head"]:
        return ("anchor_head_not_in_chain",)
    if check_reanchor_audit:
        audit_reasons = verify_reanchor_audit(anchor_path)
        if audit_reasons != ("reanchor_audit_missing",):
            return audit_reasons
    return ()
