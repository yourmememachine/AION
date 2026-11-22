"""Durable ship transaction state machine (Trust Boundary v2,
mandate item 4; CROSS-CHECK-3 seat-gpt F5).

record_ship's burn-before-record order was already sound, but a
crash between its steps left the outcome implicit: a burn with no
finalise might mean "cycle recorded, finalise lost" or "cycle
never recorded, decision spent" — indistinguishable without
re-deriving it from two other stores. This module makes the
transaction itself durable: every ship attempt is one transaction
with an explicit state, appended to its own hash-chained journal
BEFORE the step it names is taken, so a crash at any point leaves
a state recovery can settle from evidence.

States (the happy path walks them in order):

    PREPARED -> AUTHORISATION_VERIFIED -> BURN_PENDING
             -> CYCLE_RECORDED -> POST_RECORD_VERIFIED
             -> COMMITTED

Terminals:

    COMMITTED           burn + recorded cycle + finalise all
                        agree; the ship happened exactly once.
    ABORTED_SPENT       the burn happened but the authorised
                        cycle was never recorded in the loop.
                        The decision is spent and NEVER
                        replayable: recovery will not re-burn
                        and will not re-run the cycle.
    REFUSED_PRE_BURN    no burn ever landed and the loop's
                        history shows no cycle for the item;
                        nothing was spent. A FRESH decision may
                        retry the ship (the refused decision
                        itself is not reused — this state only
                        certifies that refusing it cost nothing).
    ANOMALY             evidence about the transaction is
                        ambiguous or contradictory, so recovery
                        refuses to guess. ANOMALY is terminal
                        and NEVER auto-resolved: a human
                        operator must reconcile the stores by
                        hand. Recovery parks a transaction here
                        instead of attributing another ship's
                        cycle, fabricating a verification it did
                        not perform, or finalising blind.

One in flight per item: ``begin`` refuses (LedgerError) to open
a transaction for an item while a DIFFERENT transaction for the
same item is still non-terminal, and record_ship surfaces that
refusal as ShipRefused. The gate applies to the EMPTY item_id
too — ``begin``'s default ``""`` is not exempt: all empty-item
transactions share one slot, so concurrent item-less
transactions are gated exactly like named ones. Choice, stated:
the gate was extended to ``""`` rather than refusing an empty
item_id outright, because journal-level callers legitimately
open item-less transactions (the unit tests do, and an
item-less transaction is a coherent journal fact on its own);
the only production caller, record_ship, always passes the
manifest's non-empty item_id, so no sanctioned ship is
item-less either way. The tx <-> loop join is by value (see
below), so two live transactions for one item would make cycle
attribution ambiguous by construction; the gate removes that
ambiguity on the sanctioned path, and recovery independently
re-checks for it (below) in case the gate was bypassed.

Transaction identity and bindings — stated exactly, with the
limit named:

* ``tx_id`` is derived, never chosen: sha256 of the canonical
  ``{"v": "ship-tx/1", "decision_id": ..., "manifest_hash": ...}``
  (see :func:`derive_tx_id`). Anyone holding a ship-ledger burn
  can recompute the tx_id for that burn, because a burn carries
  exactly those two fields. That is the tx <-> ship-ledger
  binding: they join on ``decision_id`` (and the derived tx_id).
  One transaction exists per (decision_id, manifest_hash);
  ``begin`` is idempotent for the SAME transaction (same
  decision, manifest, proposal and item) and returns its
  existing tx_id; a re-begin naming a different item_id for an
  existing tx_id raises LedgerError instead of silently keeping
  the original binding.
* The tx <-> loop binding is by VALUE, not by reference: the
  CYCLE_RECORDED transition records the ``cycle_id`` and
  ``item_id`` of the history entry ``run_one_cycle`` returned.
  The loop's history entry itself cannot carry the tx_id —
  ``core/loop.py`` is a protected path whose entry shape this
  module may not change — so the join is
  ``(cycle_id, item_id)`` compared against the loop's history.
  Honest limit: nothing inside the loop's state file proves a
  history entry belongs to this transaction rather than to
  another ship of the same item. Recovery therefore attributes
  a history entry by item alone ONLY when the attribution is
  unambiguous: an exact (cycle_id, item_id) match is preferred;
  an item-only candidate whose cycle is already claimed by
  another transaction or another decision's finalise, one of
  several history entries for the item, or one contested by
  another live transaction for the same item is NOT attributed
  — the transaction parks at ANOMALY instead.
* Cycle-claim uniqueness: one cycle_id belongs to exactly one
  transaction and one decision. It is enforced at three
  layers: ``transition`` to CYCLE_RECORDED raises if another
  transaction has already journaled that cycle_id;
  ``_recorded_cycle_status`` reports "ambiguous" — on BOTH its
  exact and its item-only path — when another transaction has
  journaled the same cycle or another decision's finalise names
  it; and ``ShipLedger.finalise`` refuses a cycle_id already
  finalised under a different decision_id. A CYCLE_RECORDED
  transition's item_id must also equal the item the transaction
  was begun with (a transaction cannot re-bind itself to
  another item mid-flight); when the transaction was begun
  with an empty item, a supplied item must pass the
  one-in-flight gate for that item at that moment.

First-binding gate (fix round 3, S1/S1b): the gate above is
NOT specific to CYCLE_RECORDED. ``transition`` runs the
one-in-flight gate at WHICHEVER transition first sets the
transaction's item_id — any state, not just CYCLE_RECORDED:
if a transition supplies an item_id while the transaction's
carried item is still empty, the supplied item must pass the
gate (no DIFFERENT non-terminal transaction may hold that
item) at that moment, or the transition raises LedgerError
and appends nothing. Before fix round 3 the gate fired only
at CYCLE_RECORDED, so an item-less transaction could bind a
live item early — at AUTHORISATION_VERIFIED or BURN_PENDING —
and its later CYCLE_RECORDED saw the carried item already set
and skipped the gate branch, walking to COMMITTED while the
item's legitimate holder was still in flight. The round-2
binding rules still apply alongside: a supplied item_id that
disagrees with a NON-empty carried item raises LedgerError
(a transaction cannot re-bind), on every transition.

Item-less CYCLE_RECORDED policy (fix round 3, S2) — chosen:
REFUSED. A CYCLE_RECORDED transition for a transaction whose
item is still empty AND which supplies no item_id raises
LedgerError, unconditionally (even when no other transaction
is live). Rationale: a recorded cycle belongs to an item by
definition in this system — the loop's history entry a cycle
is recorded from carries an item_id, the tx <-> loop join is
``(cycle_id, item_id)``, and the sanctioned caller,
record_ship, always supplies the recorded entry's item_id at
CYCLE_RECORDED (and already began its transaction with that
item). An item-less CYCLE_RECORDED therefore has no honest
meaning, and letting it through left the gate unengaged
altogether: an item-less transaction journaled a cycle claim
with item ``""`` and walked to COMMITTED while another item's
holder was live. The alternative policy — gating an
item-less CYCLE_RECORDED against ALL live transactions —
was not chosen: it would still journal a cycle claim with no
item, which recovery's by-value join cannot attribute, and
no existing legitimate test needs an item-less
CYCLE_RECORDED (every honest CYCLE_RECORDED in the suite is
for a transaction begun with an item, or supplies one at
that transition). Item-less transactions remain legitimate
journal facts at every OTHER state; only the cycle claim
requires an item.

Journal location: the ShipTxJournal lives ALONGSIDE the ship
ledger — ``ship-tx.json`` in the ship ledger's own directory
(``ledger.journal_dir``) — so the two journals share one
verifier-home directory and one fate, while remaining separate
hash chains with separate heads. It subclasses
:class:`trust.ledger.HashChainJournal`: same hash chain, same
atomic replace, same tamper-evidence, same stated limit (a
deleted journal loads as empty; only an externally pinned head
detects that). Cycle 17: the tx journal's head CAN be pinned —
trust.anchoring kind="ship-tx", at a path outside this directory
(the directory shared with the ship ledger) and distinct from
the ship ledger's anchor — and recovery verifies that pin when
the caller supplies ``tx_anchor_path`` (see the Anchor bullet
below). The pin is unkeyed, like the journals: an attacker who
can rewrite both this journal and its anchor can roll both back
to a matching earlier pair and verification passes; it detects
rollback only against an anchor location the journal's writer
cannot rewrite, and only for the prefix up to the last
update_anchor. Two anchors in the same external directory are
one trust location, not two: the tx anchor adds a second head,
not a second boundary. Initial anchoring of an established tx
journal requires the nonempty ceremony
(allow_nonempty_ceremony=True) and therefore cannot detect any
rollback that predates it. One difference: this
journal's appends are serialised by an exclusive flock on the
journal directory held across the read-head + append (the
trust/budgets.py pattern), so concurrent appends through
different ShipTxJournal instances cannot fork or corrupt the
chain; the loser of a race re-reads the head under the lock
instead of failing on a stale snapshot.

Recovery (:meth:`ShipTxJournal.recover`, also exposed as
``trust.shipcheck.recover_ship_tx``) is evidence-driven and
idempotent. For every non-terminal transaction it consults the
ship ledger and the loop's history — never the caller's word —
and applies these rules in order:

* Anchor: when ``anchor_path`` is given, the ship ledger's
  anchor (trust.anchoring, kind="ship") is verified first, and
  the failure KIND decides what happens. Operator-error
  failures — ``anchor_missing``,
  ``anchor_missing_established_ledger`` and
  ``anchor_malformed`` — prove nothing about the ledger itself
  (a mistyped or not-yet-created anchor path is the classic
  case), so they are NON-destructive: each non-terminal
  transaction gets an ``error`` outcome, is left exactly where
  it is, and is retried by the next run once the operator
  supplies a valid anchor. Only chain-mismatch reasons —
  ``anchor_head_not_in_chain``, ``anchor_ahead_of_journal``
  and ``anchor_kind_mismatch`` — are rollback / substitution
  evidence, and only those park every non-terminal transaction
  at ANOMALY. Recovery does not proceed silently on an
  unanchored or rolled-back ledger either way.
* Tx anchor (cycle 17): when ``tx_anchor_path`` is given, THIS
  journal's anchor (kind="ship-tx") is verified at the same
  time, before any settlement, under the same classification,
  and the two anchors combine park-over-error. Passing the
  same file for both paths is reported as an operator error
  (a wiring mistake recovery can prove in-process); passing a
  DIFFERENT wrong-kind file as ``tx_anchor_path`` — e.g. the
  ship anchor — is ``anchor_kind_mismatch`` and parks every
  non-terminal transaction at ANOMALY, terminally: on disk it
  is indistinguishable from a substituted anchor. If the tx
  anchor carries chain-mismatch reasons but no non-terminal
  transaction exists to park — the deleted-journal case —
  recovery raises AnchorError rather than reporting a clean,
  empty recovery. Recovery verifies the tx anchor once and
  never advances it; the caller must call update_anchor(...,
  kind="ship-tx") after recovery, and until it does, rolling
  this journal back to the anchored prefix erases recovery's
  settlements undetectably. Restoring this journal and its
  anchor from different backup points, or restoring the
  journal without a force_reanchor, will park live
  transactions at ANOMALY; restoring an older anchor than the
  journal will not be detected.
* Ambiguous or contradictory evidence -> ANOMALY. That
  includes: an item-only cycle candidate that could belong to
  another transaction; a burn whose manifest_hash disagrees
  with the transaction's; a finalise with no burn; a finalise
  naming a different cycle than the recorded one; a journaled
  cycle (CYCLE_RECORDED / POST_RECORD_VERIFIED) whose burn is
  missing from the ledger or whose cycle is missing from the
  loop's history; a cycle in the history with no burn.
* Provenance: recovery NEVER journals AUTHORISATION_VERIFIED —
  it did not run the ship check, so it cannot claim it did. A
  transaction still at PREPARED with any burn or cycle evidence
  parks at ANOMALY, as does a transaction at BURN_PENDING whose
  journal contains no AUTHORISATION_VERIFIED entry yet which
  has burn/cycle evidence.
* No burn, and the loop's history (consulted BEFORE any
  refusal) shows no cycle for the item -> REFUSED_PRE_BURN.
* A burn, an unambiguous recorded cycle, and journaled
  authorisation -> the transaction may advance: BURN_PENDING
  (if needed), then CYCLE_RECORDED on the unambiguous match.
  The POST_RECORD_VERIFIED step is journaled by recovery ONLY
  when recovery itself re-verifies: when ``root`` is provided
  it rebuilds the manifest from that tree (trying each review
  record under ``internal/`` as the manifest's bound record,
  stage "final") and requires the rebuilt manifest_hash to
  equal the transaction's; when ``root`` is None and the burn
  is still unfinalised, the transaction parks at ANOMALY
  instead of finalising blind — an operator must re-run
  recovery with ``root`` (or reconcile by hand). One stated
  exception, stated exactly: the already-finalised exception
  applies ONLY to a transaction already AT
  POST_RECORD_VERIFIED — the real crash window, where
  record_ship journaled POST_RECORD_VERIFIED, finalised the
  burn, and crashed before journaling COMMITTED. That
  transaction needs no new verification and no new finalise:
  the POST_RECORD_VERIFIED transition was journaled by whoever
  performed the verification, and recovery only completes the
  COMMITTED paperwork. BELOW POST_RECORD_VERIFIED a finalise
  already present in the ledger is NOT evidence the
  verification happened: record_ship finalises only AFTER
  journaling POST_RECORD_VERIFIED, so a finalise coexisting
  with a pre-POST_RECORD_VERIFIED journal state is
  contradictory evidence, not a crash remnant, and the
  transaction parks at ANOMALY — UNLESS ``root`` is provided
  AND manifest re-verification passes, in which case recovery
  journals POST_RECORD_VERIFIED itself (it performed the
  verification) and proceeds to COMMITTED.
  Rebuild limit, stated: the rebuild assumes stage "final" and
  no superseded manifest; a transaction whose manifest does
  not rebuild to an equal hash for ANY reason (tree drift,
  a superseding manifest, a review record outside internal/)
  parks at ANOMALY — the safe direction.
* A burn but no recorded cycle (and no contradiction above)
  -> ABORTED_SPENT. The decision stays spent.

Recovery never burns and never runs a cycle: the only ledger
write it can make is the finalise that completes an
already-recorded, already-verified cycle. Each transaction's
recovery is isolated: an exception while settling one is
collected into that transaction's outcome dict (an ``error``
field, with the transaction left in its current state for a
later run) and does not block the others. Running recovery
twice changes nothing the second time for transactions it
settled: they land in terminal states, and terminal
transactions are skipped (a transaction left non-terminal by
an error outcome is retried by the next run).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
from pathlib import Path

from signing.gate_decision import _canonical, _sha256
from trust.ledger import (
    MAX_JOURNAL_BYTES,
    HashChainJournal,
    LedgerError,
)

TX_VERSION = "ship-tx/1"

PREPARED = "PREPARED"
AUTHORISATION_VERIFIED = "AUTHORISATION_VERIFIED"
BURN_PENDING = "BURN_PENDING"
CYCLE_RECORDED = "CYCLE_RECORDED"
POST_RECORD_VERIFIED = "POST_RECORD_VERIFIED"
COMMITTED = "COMMITTED"
ABORTED_SPENT = "ABORTED_SPENT"
REFUSED_PRE_BURN = "REFUSED_PRE_BURN"
ANOMALY = "ANOMALY"

STATES = (PREPARED, AUTHORISATION_VERIFIED, BURN_PENDING,
          CYCLE_RECORDED, POST_RECORD_VERIFIED, COMMITTED,
          ABORTED_SPENT, REFUSED_PRE_BURN, ANOMALY)
TERMINAL_STATES = frozenset({COMMITTED, ABORTED_SPENT,
                             REFUSED_PRE_BURN, ANOMALY})

# Anchor-failure classification for recovery (fix round 2, N3).
# Chain-mismatch reasons are rollback / substitution evidence
# and park a transaction at ANOMALY; operator-error reasons
# (missing or malformed anchor — e.g. a wrong path) prove
# nothing about the ledger, so recovery reports a
# non-destructive per-transaction error and leaves the
# transaction in place for the next run. Any other anchor
# failure string (including a wrapped anchor_error) is treated
# as operator error: parking is reserved for the three named
# chain-mismatch reasons.
ANCHOR_PARK_REASONS = frozenset({
    "anchor_head_not_in_chain", "anchor_ahead_of_journal",
    "anchor_kind_mismatch"})
ANCHOR_ERROR_REASONS = frozenset({
    "anchor_missing", "anchor_missing_established_ledger",
    "anchor_malformed"})

# The legal transition graph. ABORTED_SPENT is reachable from
# every non-terminal state before POST_RECORD_VERIFIED and from
# CYCLE_RECORDED: whenever a burn exists, "spent" is always a
# safe terminal to land in, whatever step the crash interrupted.
# ANOMALY is reachable from EVERY non-terminal state: ambiguous
# or contradictory evidence can surface at any point, and parking
# must never itself be an illegal transition. REFUSED_PRE_BURN
# is reachable only from states at or before the burn, and
# recovery/record_ship only take it after checking the ship
# ledger shows no burn landed AND the loop history shows no
# recorded cycle.
_TRANSITIONS = {
    PREPARED: frozenset({AUTHORISATION_VERIFIED, REFUSED_PRE_BURN,
                         ABORTED_SPENT, ANOMALY}),
    AUTHORISATION_VERIFIED: frozenset({BURN_PENDING,
                                       REFUSED_PRE_BURN,
                                       ABORTED_SPENT, ANOMALY}),
    BURN_PENDING: frozenset({CYCLE_RECORDED, REFUSED_PRE_BURN,
                             ABORTED_SPENT, ANOMALY}),
    CYCLE_RECORDED: frozenset({POST_RECORD_VERIFIED,
                               ABORTED_SPENT, ANOMALY}),
    POST_RECORD_VERIFIED: frozenset({COMMITTED, ABORTED_SPENT,
                                     ANOMALY}),
    COMMITTED: frozenset(),
    ABORTED_SPENT: frozenset(),
    REFUSED_PRE_BURN: frozenset(),
    ANOMALY: frozenset(),
}


def derive_tx_id(decision_id: str, manifest_hash: str) -> str:
    """The deterministic transaction id for one ship: sha256 of
    the canonical ship-tx/1 binding of decision and manifest.
    Computable identically from the tx journal side, from a
    ship-ledger burn (which carries both fields), and from the
    shipcheck caller — that shared derivability is the binding.
    """
    return _sha256(_canonical({
        "v": TX_VERSION,
        "decision_id": decision_id,
        "manifest_hash": manifest_hash,
    }))


class ShipTxJournal(HashChainJournal):
    """One durable transaction per (decision_id, manifest_hash),
    recorded as a hash-chained journal of state transitions."""

    FILENAME = "ship-tx.json"
    EXTRA_KEYS = frozenset({"tx_id", "decision_id", "proposal_id",
                            "manifest_hash", "item_id", "cycle_id",
                            "from_state", "to_state"})

    def __init__(self, journal_dir):
        super().__init__(journal_dir)
        self._thread_lock = threading.RLock()
        self._flock_depth = 0

    # -- serialised appends (M1) --------------------------------------

    @contextlib.contextmanager
    def _locked(self):
        """Exclusive flock on the journal directory, held across
        a read-head + append (the trust/budgets.py pattern). A
        per-instance RLock serialises threads sharing one
        instance; the flock serialises separate instances and
        processes. Re-entrant for the holding thread via the
        depth counter, so begin/transition can wrap _append."""
        with self._thread_lock:
            if self._flock_depth:
                self._flock_depth += 1
                try:
                    yield
                finally:
                    self._flock_depth -= 1
                return
            fd = os.open(self.journal_dir,
                         os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._flock_depth = 1
                try:
                    yield
                finally:
                    self._flock_depth = 0
            finally:
                os.close(fd)

    def _write_locked(self, entries) -> None:
        """Serialise + atomically replace the journal file. The
        caller must hold the flock (see _locked): unlike
        HashChainJournal._save there is no freshness refusal
        here, because the head was re-read under the same lock
        that serialises every writer of this journal."""
        text = json.dumps({"entries": entries}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)
        raw = text.encode("utf-8")
        if len(raw) > MAX_JOURNAL_BYTES:
            raise LedgerError("journal exceeds the size cap")
        tmp = self.journal_dir / (self.FILENAME + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.journal_path)
        dir_fd = os.open(self.journal_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        self._entries = entries

    def _append(self, kind: str, recorded_at: str, **fields) -> dict:
        """Append one entry with the head re-read under the
        flock, so a concurrent append through another instance
        is folded in rather than forked over or refused."""
        with self._locked():
            self._reload()
            entry = {
                "seq": len(self._entries) + 1,
                "kind": kind,
                "recorded_at": recorded_at,
                "prev_hash": self.head(),
            }
            entry.update(fields)
            entry["entry_hash"] = _sha256(_canonical(
                {k: v for k, v in entry.items()
                 if k != "entry_hash"}))
            self._write_locked(self._entries + [entry])
            return dict(entry)

    # -- internals ---------------------------------------------------

    def _summaries(self) -> dict:
        """{tx_id: summary} in first-seen order, folded from the
        journal: identity fields from the PREPARED entry, item /
        cycle / state from the latest entry that sets them."""
        out = {}
        for entry in self._entries:
            tx_id = entry["tx_id"]
            summary = out.get(tx_id)
            if summary is None:
                summary = {
                    "tx_id": tx_id,
                    "decision_id": entry["decision_id"],
                    "proposal_id": entry["proposal_id"],
                    "manifest_hash": entry["manifest_hash"],
                    "item_id": entry["item_id"],
                    "cycle_id": entry["cycle_id"],
                    "state": entry["to_state"],
                }
                out[tx_id] = summary
            else:
                if entry["item_id"]:
                    summary["item_id"] = entry["item_id"]
                if entry["cycle_id"] != "":
                    summary["cycle_id"] = entry["cycle_id"]
                summary["state"] = entry["to_state"]
        return out

    def _summary(self, tx_id: str):
        return self._summaries().get(tx_id)

    def _authorised(self, tx_id: str) -> bool:
        """True when the journal itself records an
        AUTHORISATION_VERIFIED transition for this transaction —
        the provenance recovery is allowed to rely on."""
        return any(
            entry["tx_id"] == tx_id
            and entry["to_state"] == AUTHORISATION_VERIFIED
            for entry in self._entries)

    # -- writes --------------------------------------------------------

    def begin(self, decision_id, proposal_id, manifest_hash,
              recorded_at, *, item_id="") -> str:
        """Open the transaction for (decision_id, manifest_hash)
        at PREPARED and return its derived tx_id. Idempotent for
        the same transaction: if it already exists with the same
        proposal and item binding, its current state is left
        exactly as it is (no duplicate PREPARED entry) and the
        same tx_id is returned — a retried or replayed ship
        attempt rejoins its original transaction. A re-begin
        naming a DIFFERENT item_id (or proposal) for an existing
        tx_id raises LedgerError: the original binding stands.

        One in flight per item: if a DIFFERENT transaction for
        the same item_id is still non-terminal, begin raises
        LedgerError and opens nothing. The gate applies to the
        empty item_id too (all empty-item transactions share
        one slot) — see the module docstring for the choice and
        its rationale; an idempotent re-begin of an EXISTING
        transaction returns before the gate and is unaffected."""
        with self._locked():
            self._reload()
            for value, name in ((decision_id, "decision_id"),
                                (proposal_id, "proposal_id"),
                                (manifest_hash, "manifest_hash")):
                if not isinstance(value, str) or not value:
                    raise LedgerError(
                        f"{name} must be a non-empty string")
            tx_id = derive_tx_id(decision_id, manifest_hash)
            existing = self._summary(tx_id)
            if existing is not None:
                if existing["proposal_id"] != proposal_id \
                        or existing["decision_id"] != decision_id \
                        or existing["manifest_hash"] != manifest_hash:
                    raise LedgerError(
                        f"tx_id {tx_id} is bound to a different ship "
                        "than the one being begun")
                if item_id and existing["item_id"] \
                        and existing["item_id"] != item_id:
                    raise LedgerError(
                        f"tx_id {tx_id} is bound to item "
                        f"{existing['item_id']!r}, not {item_id!r}")
                return tx_id
            for other in self._summaries().values():
                if other["item_id"] == item_id \
                        and other["state"] not in TERMINAL_STATES:
                    raise LedgerError(
                        f"item {item_id!r} already has a "
                        f"non-terminal ship transaction "
                        f"{other['tx_id']} in flight; refusing "
                        "to open a second one")
            self._append(
                "transition", recorded_at, tx_id=tx_id,
                decision_id=decision_id, proposal_id=proposal_id,
                manifest_hash=manifest_hash, item_id=item_id,
                cycle_id="", from_state="", to_state=PREPARED)
            return tx_id

    def transition(self, tx_id, to_state, recorded_at, cycle_id="",
                   *, item_id="") -> dict:
        """Advance one transaction along the legal graph. Illegal
        jumps — skipping states, leaving a terminal state, moving
        an unknown transaction — raise LedgerError and append
        nothing. ``cycle_id`` / ``item_id`` default to "" meaning
        "unchanged": the values recorded so far carry forward, so
        only the CYCLE_RECORDED transition needs to supply them.
        Validation and append happen under one flock, so a
        concurrent transition is validated against the state it
        actually follows.

        Item binding (fix round 2, H1): a supplied ``item_id``
        that disagrees with the item the transaction already
        carries raises LedgerError — a transaction cannot
        re-bind itself to another item. For CYCLE_RECORDED in
        particular the supplied item must equal the begun item.

        First-binding gate (fix round 3, S1/S1b): WHICHEVER
        transition first sets the transaction's item_id — any
        state, not just CYCLE_RECORDED — runs the one-in-flight
        gate for the supplied item at that moment: if the
        carried item is still empty and a DIFFERENT
        non-terminal transaction holds the supplied item, the
        transition raises LedgerError and appends nothing.
        Item-less CYCLE_RECORDED (fix round 3, S2): a
        CYCLE_RECORDED transition whose carried item is still
        empty and which supplies no item_id is REFUSED
        (LedgerError) — see the module docstring for the
        policy and its rationale. Cycle-claim uniqueness (N1):
        a CYCLE_RECORDED transition naming a cycle_id another
        transaction has already journaled raises LedgerError."""
        with self._locked():
            self._reload()
            if to_state not in STATES:
                raise LedgerError(f"unknown ship-tx state: {to_state!r}")
            summary = self._summary(tx_id)
            if summary is None:
                raise LedgerError(f"unknown ship transaction: {tx_id}")
            current = summary["state"]
            if to_state not in _TRANSITIONS[current]:
                raise LedgerError(
                    f"illegal ship-tx transition {current} -> "
                    f"{to_state} for {tx_id}")
            new_cycle = summary["cycle_id"] if cycle_id == "" \
                else cycle_id
            if to_state == CYCLE_RECORDED and new_cycle == "":
                raise LedgerError(
                    "CYCLE_RECORDED requires the recorded cycle_id")
            if item_id and summary["item_id"] \
                    and item_id != summary["item_id"]:
                raise LedgerError(
                    f"ship transaction {tx_id} is bound to item "
                    f"{summary['item_id']!r}, not {item_id!r}; a "
                    "transition cannot re-bind it to another item")
            if item_id and not summary["item_id"]:
                # First binding (fix round 3, S1/S1b): this
                # transition — WHATEVER state it targets — is
                # where the transaction acquires its item, so
                # this is where the one-in-flight gate fires.
                # (Round 2 fired it only at CYCLE_RECORDED, so
                # binding early, e.g. at AUTHORISATION_VERIFIED
                # or BURN_PENDING, evaded it: the later
                # CYCLE_RECORDED saw the carried item already
                # set and skipped the gate branch.)
                for other in self._summaries().values():
                    if other["tx_id"] == tx_id:
                        continue
                    if other["item_id"] == item_id \
                            and other["state"] \
                            not in TERMINAL_STATES:
                        raise LedgerError(
                            f"item {item_id!r} already has a "
                            f"non-terminal ship transaction "
                            f"{other['tx_id']} in flight; "
                            f"refusing to bind this transaction "
                            f"to it at {to_state}")
            if to_state == CYCLE_RECORDED \
                    and not item_id and not summary["item_id"]:
                # Item-less CYCLE_RECORDED policy (fix round 3,
                # S2): REFUSED — a recorded cycle belongs to an
                # item by definition, and record_ship always
                # supplies one. See the module docstring.
                raise LedgerError(
                    "CYCLE_RECORDED requires an item_id: the "
                    "transaction carries no item and the "
                    "transition supplies none; a recorded cycle "
                    "belongs to an item")
            if to_state == CYCLE_RECORDED:
                all_summaries = self._summaries()
                others = [s for s in all_summaries.values()
                          if s["tx_id"] != tx_id]
                for other in others:
                    if other["cycle_id"] != "" \
                            and str(other["cycle_id"]) \
                            == str(new_cycle):
                        raise LedgerError(
                            f"cycle {new_cycle!r} is already "
                            f"journaled by ship transaction "
                            f"{other['tx_id']}; a cycle belongs to "
                            "exactly one transaction")
            return self._append(
                "transition", recorded_at, tx_id=tx_id,
                decision_id=summary["decision_id"],
                proposal_id=summary["proposal_id"],
                manifest_hash=summary["manifest_hash"],
                item_id=item_id or summary["item_id"],
                cycle_id=new_cycle, from_state=current,
                to_state=to_state)

    # -- reads ---------------------------------------------------------

    def state(self, tx_id):
        """The transaction's current state, or None if no such
        transaction exists."""
        self._reload()
        summary = self._summary(tx_id)
        return summary["state"] if summary is not None else None

    def transaction(self, tx_id):
        """The folded summary for one transaction, or None."""
        self._reload()
        summary = self._summary(tx_id)
        return dict(summary) if summary is not None else None

    def transactions(self) -> list:
        """Folded summaries for every transaction, first-seen
        order."""
        self._reload()
        return [dict(s) for s in self._summaries().values()]

    # -- recovery --------------------------------------------------------

    def recover(self, ledger, loop, *, recorded_at="", root=None,
                anchor_path=None, tx_anchor_path=None) -> list:
        """Drive every non-terminal transaction to the one
        terminal outcome its evidence supports (see the module
        docstring for the full rule set).

        ``ledger`` is the ShipLedger the transactions burned in;
        ``loop`` is the CoreLoop whose history is the record of
        cycles. ``root``, when given, is the build tree recovery
        re-verifies against before journaling
        POST_RECORD_VERIFIED / finalising an unfinalised burn.
        ``anchor_path``, when given, pins the ship ledger's
        anchor to verify before any evidence is trusted. Its
        failure kind decides the outcome (see the module
        docstring): operator-error anchor failures (missing /
        malformed anchor) yield a non-destructive ``error``
        outcome per transaction with the transaction left in
        place; only chain-mismatch reasons park at ANOMALY.
        ``tx_anchor_path`` (cycle 17), when given, pins THIS
        journal's own head (kind="ship-tx") under the identical
        classification, verified before any transaction is
        settled. When both anchors are supplied the outcomes
        combine park-over-error: any chain-mismatch reason from
        either anchor parks; otherwise any operator-error reason
        from either yields the non-destructive error outcome
        (the message labels each reason by its anchor, but only
        when the tx anchor participates — a ship-only caller's
        strings keep their bare pre-cycle-17 form). Passing the
        SAME file for both anchors (by file identity — symlink
        and hardlink aliases included) is a wiring error this
        method can prove in-process, so both verifications are
        suppressed and it is reported as an operator error,
        never a park; a DIFFERENT file whose kind is wrong is
        indistinguishable from a substituted anchor and still
        parks. If the tx anchor carries chain-mismatch reasons
        but this journal holds no non-terminal transaction to
        park — the journal file deleted outright and loading
        empty, or a journal rolled back to a terminal-only
        prefix — the rollback evidence has nowhere to land, so
        recover raises AnchorError instead of returning an
        empty outcome list that would read as "nothing to
        settle"; the remedy is the correct anchor or an audited
        force_reanchor. Park outcomes carry an
        ``anchor_sources`` list naming which anchor produced
        each park reason. Both anchors are also re-verified
        after the settlement loop: a park reason appearing only
        then (a journal swapped mid-recovery) raises
        AnchorError after the run's settlements, which stand as
        journaled evidence. Recovery never advances either
        anchor: transitions it appends leave the tx anchor
        stale-but-valid (it names an older prefix), and the
        caller must call update_anchor(..., kind="ship-tx")
        after recovery — until it does, rolling this journal
        back to the anchored prefix erases recovery's
        settlements undetectably. No in-tree caller passes
        ``tx_anchor_path`` yet: this is operator/library
        plumbing, and wiring it into the ship flow is a
        separate cycle.

        Returns one outcome dict per transaction that changed
        state or failed to settle ({tx_id, decision_id,
        from_state, to_state, cycle_id}, plus ``reasons`` for
        ANOMALY parks and ``error`` for a transaction whose
        recovery raised — such a transaction is left in its
        current state and does not block the others); terminal
        transactions are untouched, so a second run over settled
        transactions returns []. This method never burns and
        never runs a cycle: the only ledger write it can make is
        the finalise that completes an already-recorded cycle.
        """
        from signing.gate_decision import _now
        stamp = recorded_at or _now()
        # Both anchors are verified BEFORE any transaction is
        # settled (cycle 17): verifying the tx anchor lazily,
        # after early transactions have already been settled,
        # would let settlements land on a journal whose head the
        # caller asked to have pinned first.
        # Same-file diagnosis (cycle 17, war-room fix round):
        # the same file passed for both anchors is a wiring
        # error provable in-process, whichever of the two files
        # it is. Identity is by samefile (symlink- and
        # hardlink-proof when both exist), falling back to
        # resolved-path equality. On a same-file diagnosis BOTH
        # verifications are suppressed: running either one
        # against the shared file would manufacture a kind
        # mismatch and park every transaction over a typo.
        same_path_error = False
        if anchor_path is not None and tx_anchor_path is not None:
            try:
                same_path_error = os.path.samefile(
                    anchor_path, tx_anchor_path)
            except OSError:
                same_path_error = Path(anchor_path).resolve() \
                    == Path(tx_anchor_path).resolve()
        ship_reasons = ()
        tx_reasons = ()
        if not same_path_error:
            if anchor_path is not None:
                from trust.anchoring import verify_anchor
                try:
                    ship_reasons = tuple(verify_anchor(
                        ledger, anchor_path, kind="ship"))
                except Exception as exc:
                    ship_reasons = (f"anchor_error:{exc}",)
            if tx_anchor_path is not None:
                from trust.anchoring import verify_anchor
                try:
                    tx_reasons = tuple(verify_anchor(
                        self, tx_anchor_path, kind="ship-tx"))
                except Exception as exc:
                    tx_reasons = (f"anchor_error:{exc}",)
        # N3 classification, applied to each anchor and combined
        # park-over-error: only chain-mismatch reasons are
        # rollback evidence worth parking over; every other
        # anchor failure is an operator error, reported per
        # transaction below without moving any transaction.
        # Reasons are labelled by anchor only when the tx anchor
        # participates; a ship-only caller's error strings keep
        # their pre-cycle-17 bare form exactly.
        labelled = tx_anchor_path is not None

        def _label(source, reason):
            return f"{source}: {reason}" if labelled else reason

        ship_park_reasons = tuple(
            r for r in ship_reasons if r in ANCHOR_PARK_REASONS)
        tx_park_reasons = tuple(
            r for r in tx_reasons if r in ANCHOR_PARK_REASONS)
        anchor_park_reasons = tuple(dict.fromkeys(
            list(ship_park_reasons) + list(tx_park_reasons)))
        anchor_park_sources = tuple(dict.fromkeys(
            [_label("ship", r) for r in ship_park_reasons]
            + [_label("ship-tx", r) for r in tx_park_reasons]))
        anchor_error_reasons = tuple(
            dict.fromkeys(
                [_label("ship", r) for r in ship_reasons
                 if r not in ANCHOR_PARK_REASONS]
                + [_label("ship-tx", r) for r in tx_reasons
                   if r not in ANCHOR_PARK_REASONS]
                + (["ship-tx: tx_anchor_path is the same file as "
                    "anchor_path; the two anchors must be "
                    "distinct files"] if same_path_error else [])))
        if tx_park_reasons and not any(
                s["state"] not in TERMINAL_STATES
                for s in self.transactions()):
            # The tx journal's rollback evidence has no
            # non-terminal transaction to park: the journal file
            # itself is the pinned object, so its deletion loads
            # as an empty journal, and a journal rolled back to
            # a terminal-only prefix presents nothing to park
            # either — returning [] would read as a clean
            # recovery in both cases (cycle 17). Surface it as
            # a refusal instead; the remedy is to supply the
            # correct anchor or force_reanchor with a recorded
            # reason. The ship anchor has no equivalent raise:
            # the ledger it pins is a different file from this
            # journal, an empty/terminal-only journal means no
            # transaction is at risk from it, and the ledger's
            # anchor is verified by the ledger's own consumers.
            from trust.anchoring import AnchorError
            raise AnchorError(
                "ship-tx anchor verification failed with "
                "chain-mismatch reasons and no non-terminal "
                "transaction to park: "
                + ", ".join(tx_park_reasons))
        anchor_reasons = ()
        if anchor_park_reasons:
            anchor_reasons = anchor_park_reasons
        outcomes = []
        for snapshot in self.transactions():
            if snapshot["state"] in TERMINAL_STATES:
                continue
            tx_id = snapshot["tx_id"]
            if anchor_error_reasons and not anchor_park_reasons:
                outcomes.append({
                    "tx_id": tx_id,
                    "decision_id": snapshot["decision_id"],
                    "from_state": snapshot["state"],
                    "to_state": snapshot["state"],
                    "cycle_id": snapshot["cycle_id"],
                    "error": "anchor verification failed "
                             "(operator error; transaction left "
                             "in place for the next run): "
                             + ", ".join(anchor_error_reasons)})
                continue
            outcome = None
            error = None
            for _attempt in range(3):
                try:
                    outcome = self._recover_one(
                        ledger, loop, tx_id, stamp, root=root,
                        anchor_reasons=anchor_reasons,
                        anchor_park_sources=anchor_park_sources)
                    error = None
                    break
                except Exception as exc:  # per-tx isolation
                    error = exc
                    fresh = None
                    try:
                        self._reload()
                        fresh = self._summary(tx_id)
                    except Exception:
                        fresh = None
                    if fresh is not None \
                            and fresh["state"] in TERMINAL_STATES:
                        # A concurrent recovery settled it; that
                        # is not this run's error to report.
                        outcome = None
                        error = None
                        break
                    if fresh is not None \
                            and fresh["state"] != snapshot["state"]:
                        # Another worker made progress between
                        # our snapshot and the failure; retry once
                        # against the fresh state before reporting.
                        snapshot = dict(fresh)
                        continue
                    break
            if error is not None:
                current = snapshot
                try:
                    self._reload()
                    fresh = self._summary(tx_id)
                    if fresh is not None:
                        current = fresh
                except Exception:
                    pass
                if current["state"] in TERMINAL_STATES:
                    # Settled (by a concurrent run) while the
                    # error was being collected: not an error
                    # outcome for this run.
                    continue
                outcomes.append({
                    "tx_id": tx_id,
                    "decision_id": snapshot["decision_id"],
                    "from_state": snapshot["state"],
                    "to_state": current["state"],
                    "cycle_id": current["cycle_id"],
                    "error": str(error)})
            elif outcome is not None:
                outcomes.append(outcome)
        if not same_path_error and (anchor_path is not None
                                    or tx_anchor_path is not None):
            # Post-settlement re-verification (cycle 17 fix
            # round): the anchor verdicts above are a snapshot
            # taken before the loop, and no lock is held across
            # verify+settle. If a journal was swapped or rolled
            # back mid-recovery, the re-check surfaces a park
            # reason the run did not act on; settlements already
            # journaled stand (they are evidence too), and the
            # new mismatch is raised for the operator rather
            # than silently passing on the stale verdict.
            from trust.anchoring import AnchorError, verify_anchor
            new_park = []
            if anchor_path is not None:
                try:
                    for r in verify_anchor(
                            ledger, anchor_path, kind="ship"):
                        if r in ANCHOR_PARK_REASONS \
                                and r not in ship_park_reasons:
                            new_park.append(f"ship: {r}")
                except Exception as exc:
                    # An exception identical to the one the
                    # initial verification already classified is
                    # not a change; only a NEW failure is.
                    if f"anchor_error:{exc}" not in ship_reasons:
                        new_park.append(f"ship: anchor_error:{exc}")
            if tx_anchor_path is not None:
                try:
                    for r in verify_anchor(
                            self, tx_anchor_path, kind="ship-tx"):
                        if r in ANCHOR_PARK_REASONS \
                                and r not in tx_park_reasons:
                            new_park.append(f"ship-tx: {r}")
                except Exception as exc:
                    if f"anchor_error:{exc}" not in tx_reasons:
                        new_park.append(f"ship-tx: anchor_error:{exc}")
            if new_park:
                raise AnchorError(
                    "anchor verification changed during "
                    "recovery; a journal was swapped or rolled "
                    "back mid-run: " + ", ".join(new_park))
        return outcomes

    def _recover_one(self, ledger, loop, tx_id, stamp, *, root,
                     anchor_reasons, anchor_park_sources=()):
        """Settle one transaction from fresh evidence. Returns
        its outcome dict, or None when it is already terminal."""
        self._reload()
        summary = self._summary(tx_id)
        if summary is None or summary["state"] in TERMINAL_STATES:
            return None
        start_state = summary["state"]
        decision_id = summary["decision_id"]

        def park(to_state, cycle_id=None, **extra):
            self.transition(tx_id, to_state, stamp)
            outcome = {
                "tx_id": tx_id, "decision_id": decision_id,
                "from_state": start_state, "to_state": to_state,
                "cycle_id": summary["cycle_id"]
                if cycle_id is None else cycle_id}
            outcome.update(extra)
            return outcome

        if anchor_reasons:
            return park(ANOMALY, reasons=list(anchor_reasons),
                        anchor_sources=list(anchor_park_sources))

        ledger._reload()
        ledger_entries = ledger.entries()
        history = []
        loop_state = getattr(loop, "state", None)
        if isinstance(loop_state, dict):
            history = [e for e in loop_state.get("history", [])
                       if isinstance(e, dict)]
        burn = next(
            (e for e in ledger_entries
             if e["kind"] == "burn"
             and e["decision_id"] == decision_id), None)
        finalise = next(
            (e for e in ledger_entries
             if e["kind"] == "finalise"
             and e["decision_id"] == decision_id), None)
        recorded, cycle_status = self._recorded_cycle_status(
            summary, history, list(self._summaries().values()),
            ledger_entries)

        if cycle_status == "ambiguous":
            return park(ANOMALY,
                        reasons=["ambiguous_cycle_evidence"])
        if burn is not None \
                and burn.get("manifest_hash") \
                != summary["manifest_hash"]:
            return park(ANOMALY,
                        reasons=["burn_manifest_mismatch"])
        if finalise is not None and burn is None:
            return park(ANOMALY,
                        reasons=["finalise_without_burn"])
        if finalise is not None and recorded is not None \
                and str(finalise.get("cycle_id")) \
                != str(recorded.get("cycle_id")):
            return park(ANOMALY,
                        reasons=["finalise_cycle_mismatch"])

        if burn is None:
            if recorded is not None:
                # A cycle with no burn is not a refusal: the
                # history was consulted first (H3) and it
                # contradicts a pre-burn refusal.
                return park(ANOMALY,
                            reasons=["cycle_without_burn"])
            if start_state in (CYCLE_RECORDED,
                               POST_RECORD_VERIFIED):
                # A post-burn state whose burn is missing (ledger
                # rolled back / deleted): REFUSED_PRE_BURN would
                # be an illegal AND false landing (H2).
                return park(ANOMALY,
                            reasons=["burn_missing_post_burn"])
            return park(REFUSED_PRE_BURN)

        # A burn exists from here on.
        if start_state == PREPARED:
            # Burn/cycle evidence for a transaction whose journal
            # never recorded the authorisation check: provenance
            # is missing, and recovery will not fabricate the
            # AUTHORISATION_VERIFIED step post-hoc.
            return park(ANOMALY,
                        reasons=["provenance_missing"])
        if start_state == BURN_PENDING \
                and not self._authorised(tx_id):
            return park(ANOMALY,
                        reasons=["provenance_missing"])

        if recorded is None:
            if start_state in (CYCLE_RECORDED,
                               POST_RECORD_VERIFIED):
                # The journal records a cycle the loop's history
                # no longer shows: contradictory evidence.
                return park(ANOMALY,
                            reasons=["recorded_cycle_missing"])
            if finalise is not None:
                return park(ANOMALY,
                            reasons=["finalise_without_cycle"])
            # Spent, never recorded; never replayable.
            return park(ABORTED_SPENT)

        # An unambiguous recorded cycle, a burn, and journaled
        # authorisation (or a state past it) from here on.
        cycle_id = recorded["cycle_id"]
        if start_state == POST_RECORD_VERIFIED:
            # Verification was journaled by whoever performed it;
            # recovery only completes the paperwork.
            if finalise is None:
                self._finalise(ledger, decision_id, cycle_id,
                               stamp)
            self.transition(tx_id, COMMITTED, stamp)
            return {"tx_id": tx_id, "decision_id": decision_id,
                    "from_state": start_state,
                    "to_state": COMMITTED, "cycle_id": cycle_id}

        # States AUTHORISATION_VERIFIED / BURN_PENDING /
        # CYCLE_RECORDED still owe the POST_RECORD_VERIFIED step,
        # which recovery may journal only after re-verifying
        # itself. The already-finalised exception does NOT apply
        # here (fix round 2, N2): it covers only a transaction
        # already AT POST_RECORD_VERIFIED (handled above).
        # record_ship finalises only after journaling
        # POST_RECORD_VERIFIED, so a finalise present below that
        # state is contradictory evidence, not a crash remnant —
        # with no root to re-verify against it parks at ANOMALY;
        # with a root, recovery re-verifies and, on a pass,
        # journals POST_RECORD_VERIFIED itself below.
        if root is not None:
            if not self._tree_matches(root, summary):
                return park(
                    ANOMALY,
                    reasons=["post_record_reverify_failed"])
        elif finalise is None:
            return park(ANOMALY,
                        reasons=["post_record_unverified"])
        else:
            return park(
                ANOMALY,
                reasons=["finalise_before_post_record_verified"])
        current = self.state(tx_id)
        if current == AUTHORISATION_VERIFIED:
            self.transition(tx_id, BURN_PENDING, stamp)
            current = BURN_PENDING
        if current == BURN_PENDING:
            self.transition(tx_id, CYCLE_RECORDED, stamp,
                            cycle_id=cycle_id,
                            item_id=recorded["item_id"])
            current = CYCLE_RECORDED
        if current == CYCLE_RECORDED:
            self.transition(tx_id, POST_RECORD_VERIFIED, stamp)
            current = POST_RECORD_VERIFIED
        if finalise is None:
            self._finalise(ledger, decision_id, cycle_id, stamp)
        self.transition(tx_id, COMMITTED, stamp)
        return {"tx_id": tx_id, "decision_id": decision_id,
                "from_state": start_state, "to_state": COMMITTED,
                "cycle_id": cycle_id}

    @staticmethod
    def _finalise(ledger, decision_id, cycle_id, stamp):
        """Finalise the burn, tolerating a concurrent recovery
        that finalised it first (re-checked from the ledger)."""
        try:
            ledger.finalise(decision_id=decision_id,
                            cycle_id=cycle_id, recorded_at=stamp)
        except LedgerError:
            ledger._reload()
            if not any(
                    e["kind"] == "finalise"
                    and e["decision_id"] == decision_id
                    for e in ledger.entries()):
                raise

    def _tree_matches(self, root, summary) -> bool:
        """Rebuild the manifest from ``root`` and report whether
        any rebuild equals the transaction's manifest_hash. The
        manifest's bound review record is not stored in the tx
        journal, so each regular file under ``internal/`` is
        tried as that record (stage "final", no superseded
        manifest — the only shape record_ship ships). Any error
        or mismatch is a non-match: the safe direction."""
        from trust.manifest import build_manifest
        root_path = Path(root)
        internal = root_path / "internal"
        if not internal.is_dir():
            return False
        candidates = []
        for dirpath, dirnames, filenames in os.walk(internal):
            dirnames.sort()
            for name in sorted(filenames):
                candidates.append(
                    (Path(dirpath) / name)
                    .relative_to(root_path).as_posix())
        for rel in sorted(candidates):
            try:
                rebuilt = build_manifest(
                    root_path,
                    proposal_id=summary["proposal_id"],
                    item_id=summary["item_id"],
                    review_record_path=rel, stage="final",
                    created_at="1970-01-01T00:00:00+00:00")
            except Exception:
                continue
            if rebuilt.manifest_hash == summary["manifest_hash"]:
                return True
        return False

    @staticmethod
    def _recorded_cycle(summary, history):
        """The loop history entry this transaction's ship
        recorded, or None. An exact (cycle_id, item_id) match is
        preferred; an item-only match is returned only when it
        is the item's sole history entry. Callers that can pass
        the other transactions / ledger entries should use
        _recorded_cycle_status, which also detects candidates
        claimed by another transaction."""
        entry, _status = ShipTxJournal._recorded_cycle_status(
            summary, history)
        return entry

    @staticmethod
    def _recorded_cycle_status(summary, history,
                               all_summaries=None,
                               ledger_entries=None):
        """(entry, "found") | (None, "none") | (None, "ambiguous")
        for the loop history entry this transaction recorded.

        Exact (cycle_id, item_id) matches are preferred, but an
        exact match is still "ambiguous" when another
        transaction has journaled the same cycle_id or another
        decision's finalise names it. When no
        cycle is journaled yet, the item-only candidate is
        "found" only if it is unambiguous: the item's sole
        history entry, not claimed as another transaction's
        journaled cycle, not named by another decision's
        finalise, and not contested by another live transaction
        for the same item. A journaled cycle whose history entry
        disagrees on item, or an item entry naming a different
        cycle than the journaled one, is "ambiguous" — the
        evidence contradicts itself."""
        known_cycle = summary["cycle_id"]
        item_id = summary["item_id"]
        if known_cycle != "":
            # Cycle-claim uniqueness on the exact path too (fix
            # round 2, N1): a cycle another transaction has
            # journaled, or another decision's finalise names, is
            # contested whoever's history entry matches exactly.
            exact_others = [s for s in (all_summaries or [])
                            if s["tx_id"] != summary["tx_id"]]
            if any(s["cycle_id"] != ""
                   and str(s["cycle_id"]) == str(known_cycle)
                   for s in exact_others):
                return None, "ambiguous"
            if any(e.get("kind") == "finalise"
                   and e.get("decision_id") != summary["decision_id"]
                   and str(e.get("cycle_id")) == str(known_cycle)
                   for e in (ledger_entries or [])):
                return None, "ambiguous"
            exact = [
                e for e in history
                if str(e.get("cycle_id")) == str(known_cycle)
                and (not item_id
                     or e.get("item_id") == item_id)]
            if len(exact) == 1:
                return exact[0], "found"
            if len(exact) > 1:
                return None, "ambiguous"
            same_cycle = [
                e for e in history
                if str(e.get("cycle_id")) == str(known_cycle)]
            if same_cycle:
                return None, "ambiguous"
            if item_id and any(
                    e.get("item_id") == item_id for e in history):
                return None, "ambiguous"
            return None, "none"
        if not item_id:
            return None, "none"
        candidates = [e for e in history
                      if e.get("item_id") == item_id]
        if not candidates:
            return None, "none"
        if len(candidates) > 1:
            return None, "ambiguous"
        candidate = candidates[0]
        cand_cycle = str(candidate.get("cycle_id"))
        others = [s for s in (all_summaries or [])
                  if s["tx_id"] != summary["tx_id"]]
        if any(s["cycle_id"] != ""
               and str(s["cycle_id"]) == cand_cycle
               for s in others):
            return None, "ambiguous"
        if any(s["item_id"] == item_id
               and s["state"] not in TERMINAL_STATES
               for s in others):
            return None, "ambiguous"
        if any(e.get("kind") == "finalise"
               and e.get("decision_id") != summary["decision_id"]
               and str(e.get("cycle_id")) == cand_cycle
               for e in (ledger_entries or [])):
            return None, "ambiguous"
        return candidate, "found"
