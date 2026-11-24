"""Pin-store history reconciliation against the verifier's
consumption journal (cycle 28, follow-up
``pin-store-history-reconciliation`` from REREVIEW-14-16 §2/§6).

The snapshot pin store's ceremony history is a
NON-AUTHORITATIVE, restoration-lossy replica: restoring an
older generation of the store document silently drops later
records, and the store's own verified load cannot detect the
absence — it verifies records PRESENT and cannot detect a
record that is not there (signing/pin_store.py,
VERIFIED-PRESENT-HISTORY). The sole authoritative ceremony
audit history is the verifier's externally anchored
consumption journal. Cycle 15 rescoped the claim to say so;
this module adds the DETECTION the re-review left open: before
an adoption attempt persists or consumes anything, the store
history captured for that attempt is reconciled against the
consumption journal, and a journal entry that is relevant to
the candidate and unaccounted for refuses the attempt with
the deterministic code ``pin_store_history_incomplete``.

What "accounted for" means — a consumption-journal entry E is
MISSING (reported, and refused by ``reconcile_history``) iff
it is relevant to the candidate and none of the excuses hold:

- RELEVANCE: ``E.new_cycle_seq < candidate_seq``, or
  ``E.new_cycle_seq == candidate_seq`` with a different
  ``new_payload_hash`` (a consumed movement at the candidate's
  own sequence to a different snapshot is a fork the store
  does not hold — not the candidate's own burn, whose exact
  pair is the recovery case below). Entries ahead of the
  candidate are not its ancestors and are never reported:
  journal-ahead-of-candidate is a head problem for the
  consumption head rules, not a store-completeness fact.
- PAIR COVERAGE: a store record attesting E's exact movement
  pair ``(old_cycle_seq, old_payload_hash, new_cycle_seq,
  new_payload_hash)`` accounts for E, whatever authorisation
  id it carries. Pair coverage is the operative coverage rule
  and subsumes the same-id case: a primary burn and its
  ``burned_unadopted`` recovery share one pair while differing
  in authorisation id, ceremony and evidence, and the
  recovery record that was adopted covers both journal
  entries. An id-only match over a DIFFERENT movement
  accounts for nothing.
- SUPERSESSION: a supersession-journal decision whose
  ``abandoned_authorisation_id`` is exactly E's accounts for
  E only when the decision's new side has LANDED: the
  decision's ``new_authorisation_id`` is among the store
  records, or its candidate pair is pair-covered by the store
  history, or its candidate pair is exactly the candidate
  under attempt (the superseding record is the one being
  adopted now). A decision alone, or a decision abandoning a
  different entry, excuses nothing — the check is fully bound,
  never existential.
- KNOWN-UNADOPTED HEAD: E is the consumption journal's HEAD
  entry, its authorisation id is in
  ``known_unadopted_authorisation_ids``, AND the candidate is
  AT E's own sequence (``E.new_cycle_seq == candidate_seq``)
  — movements the caller attests were consumed but never
  adopted (in the production wiring, the list is derived
  solely from the adopter's own pending journal: consumed,
  never adopted; at the pure-function level the list is
  caller-attested and a fabricated list could excuse the head
  entry only — the excuse binds to the head entry itself, and
  duplicate authorisation ids or seqs in the supplied journal
  refuse outright, so the excuse cannot leak onto a non-head
  entry sharing the head's id). Those are the recovery /
  supersession flows' input, not missing history. The excuse
  is HEAD-SCOPED by construction: the head can move past a
  burn only via that burn's recovery (pair coverage) or its
  supersession (bound decision), so a non-head entry claimed
  unadopted is a contradiction and is never excused by this
  rule. AT-SEQUENCE SCOPING (fix round, seat-gpt FIX 0.91):
  the excuse does NOT reach a candidate strictly beyond E.
  An adopted ceremony whose pending-journal "adopted" line
  was lost (crash in the adopt→adopted window, the swallowed
  append OSError, or a pending-journal rollback), combined
  with a store restore to a pre-adoption generation, is
  indistinguishable at this layer from a genuine burn — so a
  beyond-head candidate is refused, never excused: adopting
  past an unaccounted head is the movement detection exists
  to refuse. An at-sequence candidate cannot adopt past the
  head either — the verifier's head rules still force the
  burn's recovery or a bound supersession decision (which
  then excuses via the supersession rule on the resume
  attempt) — so the retained reach cannot complete a silent
  adoption. The excuse list is an explicit, auditable
  argument; a wholesale rollback that also loses the caller's
  proof loses the excuse too, and the refusal fails closed.
- GENESIS BASELINE: with ``genesis_baseline=True`` (the
  attempt has no old pin — a sanctioned initial anchor or a
  genesis after pin loss), prior journal entries are the
  attested loss the genesis responds to, not missing history,
  and nothing is reported. The default is False.

Input discipline: the store history must contain only
``PinCeremonyRecord``s (a dict with the right keys is NOT a
record and counts as no coverage); journal entries must carry
the required keys with correctly typed values (a bool sequence
is refused, never silently re-targeted); duplicate
authorisation ids in the store history refuse. Every
malformed input is a ``SigningError`` — the check fails
closed, never skips an entry it cannot read, and never
reports a fabricated missing entry.

Provider helpers: ``consumption_entries_provider_from_home``
and ``supersession_entries_provider_from_home`` build
zero-argument callables that load the verifier's journals
FRESH on every call (a cached ledger instance would answer
from a stale snapshot forever).

INTERNAL / COMPOSITION SEAM (the cycle-25 precaution): the
ledger classes are the VERIFIER PROCESS's stores. Building a
provider from a verifier home is a composition act for the
layer that legitimately holds that home (the operator /
orchestrator audit path and tests), not a licence for the
adopter to reach into the verifier home itself —
``trust.pin_adoption.build_pin_adopter`` therefore never
derives providers from its environment; they are supplied
explicitly or not at all. Detection is an integrated-system
property of the wiring that supplies real providers, exactly
as cycle 21 scoped single-use consumption to the wiring that
supplies the verifier-backed consumer: an adopter built
without a consumption provider makes no history-completeness
claim and behaves exactly as before this cycle.

Scope limits, stated plainly: the check sees consumptions
only — ``advance_pin`` movements never enter the consumption
journal, so a lost advance leaves no journal trace to
reconcile against (the pin itself is the evidence for
advances, and a restored pin is caught by the consumption
head rules on the next ceremony). A coordinated rollback of
the store AND of the journal entries supplied here is out of
scope: the journals' own external anchors (cycles 22/27),
verified at verifier startup, are the control there.
"""

from __future__ import annotations

from pathlib import Path

from signing.gate_decision import SigningError
from signing.pin_ceremony import PinCeremonyRecord

RECONCILIATION_CODE = "pin_store_history_incomplete"

# The minimal key set a caller-built entry dict must carry.
# Real CeremonyConsumptionLedger entries carry more (kind,
# recorded_at, prev_hash, entry_hash, ceremony_id,
# evidence_hash and, in v2, lineage fields); the check reads
# only the fields it names, and consults ceremony_id /
# evidence_hash only when present.
_CONSUMPTION_MINIMAL_KEYS = frozenset({
    "seq", "authorisation_id",
    "old_cycle_seq", "old_payload_hash",
    "new_cycle_seq", "new_payload_hash"})


class HistoryReconciliationRefused(SigningError):
    """The store history is incomplete against the verifier's
    consumption journal: one or more journal entries relevant
    to the candidate are unaccounted for. Deterministic: same
    inputs, same refusal, same missing list (journal order).
    ``code`` is the machine-readable refusal code, mirroring
    the ``verifier_code`` pattern in trust/client.py."""

    code = RECONCILIATION_CODE

    def __init__(self, message, *, missing_entries):
        super().__init__(message)
        self.missing_entries = tuple(missing_entries)
        self.missing_authorisation_ids = tuple(
            e["authorisation_id"] for e in self.missing_entries)
        self.missing_ceremony_ids = tuple(
            e.get("ceremony_id") for e in self.missing_entries)


def _check_seq_value(value, field):
    if not isinstance(value, int) or isinstance(value, bool) \
            or value < 0:
        raise SigningError(
            f"history reconciliation: {field} must be an "
            "integer >= 0")
    return value


def _validate_store_history(store_history):
    if isinstance(store_history, (str, bytes, dict)) \
            or not isinstance(store_history, (list, tuple)):
        raise SigningError(
            "history reconciliation: store history must be a "
            "list or tuple of PinCeremonyRecord")
    records = tuple(store_history)
    seen_ids = set()
    for rec in records:
        if not isinstance(rec, PinCeremonyRecord):
            raise SigningError(
                "history reconciliation: store history "
                "contains a non-record entry; only genuine "
                "PinCeremonyRecords count as coverage")
        if rec.authorisation_id in seen_ids:
            raise SigningError(
                "history reconciliation: store history "
                "contains a duplicate authorisation_id")
        seen_ids.add(rec.authorisation_id)
    return records


def _validate_journal_entries(entries, *, label):
    if isinstance(entries, (str, bytes, dict)) \
            or not isinstance(entries, (list, tuple)):
        raise SigningError(
            f"history reconciliation: {label} entries must be "
            "a list or tuple of entry dicts")
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SigningError(
                f"history reconciliation: {label} entry is "
                "not a dict")
        if not _CONSUMPTION_MINIMAL_KEYS <= set(entry):
            raise SigningError(
                f"history reconciliation: {label} entry is "
                "missing required keys")
        _check_seq_value(entry["seq"], f"{label} entry seq")
        if entry["seq"] < 1:
            raise SigningError(
                f"history reconciliation: {label} entry seq "
                "must be >= 1")
        _check_seq_value(entry["new_cycle_seq"],
                         f"{label} entry new_cycle_seq")
        if entry["old_cycle_seq"] is not None:
            _check_seq_value(entry["old_cycle_seq"],
                             f"{label} entry old_cycle_seq")
        for field in ("authorisation_id", "old_payload_hash",
                      "new_payload_hash"):
            if not isinstance(entry[field], str) \
                    or not entry[field]:
                if field == "old_payload_hash" \
                        and entry[field] == "":
                    continue
                raise SigningError(
                    f"history reconciliation: {label} entry "
                    f"{field} must be non-empty text")
        out.append(entry)
    # Journal integrity at this layer (fix round, rev-r6/r1):
    # seqs are positional and authorisation ids are single-use
    # in every real journal (the ledger loaders enforce both);
    # a caller-supplied list that violates either is refused,
    # never reconciled against — among other things, a
    # duplicate authorisation id would let the head excuse
    # (which binds to the head ENTRY, below) leak onto a
    # non-head entry sharing the head's id.
    seqs = [e["seq"] for e in out]
    if len(set(seqs)) != len(seqs):
        raise SigningError(
            f"history reconciliation: {label} entries contain "
            "a duplicate seq")
    ids = [e["authorisation_id"] for e in out]
    if len(set(ids)) != len(ids):
        raise SigningError(
            f"history reconciliation: {label} entries contain "
            "a duplicate authorisation_id")
    return out


def _validate_supersession_entries(entries):
    if isinstance(entries, (str, bytes, dict)) \
            or not isinstance(entries, (list, tuple)):
        raise SigningError(
            "history reconciliation: supersession entries "
            "must be a list or tuple of entry dicts")
    out = []
    for entry in entries:
        if not isinstance(entry, dict) \
                or not isinstance(
                    entry.get("abandoned_authorisation_id"), str) \
                or not entry.get("abandoned_authorisation_id"):
            raise SigningError(
                "history reconciliation: supersession entry "
                "must carry an abandoned_authorisation_id")
        out.append(entry)
    return out


def _pair_of_record(rec):
    return (rec.old_cycle_seq, rec.old_payload_hash,
            rec.new_cycle_seq, rec.new_payload_hash)


def _pair_of_entry(entry):
    return (entry["old_cycle_seq"], entry["old_payload_hash"],
            entry["new_cycle_seq"], entry["new_payload_hash"])


def find_missing_history(store_history, consumption_entries,
                         supersession_entries=(), *,
                         candidate_seq, candidate_hash,
                         known_unadopted_authorisation_ids=(),
                         genesis_baseline=False) -> tuple:
    """Return the consumption-journal entries (in journal
    order) that are relevant to the candidate and unaccounted
    for by the store history. See the module docstring for the
    exact missing/excuse rules. Pure and deterministic: the
    result is sorted by journal ``seq`` regardless of input
    order, and repeated calls on the same inputs agree."""
    records = _validate_store_history(store_history)
    entries = _validate_journal_entries(
        consumption_entries, label="consumption journal")
    decisions = _validate_supersession_entries(supersession_entries)
    _check_seq_value(candidate_seq, "candidate_seq")
    if not isinstance(candidate_hash, str) or not candidate_hash:
        raise SigningError(
            "history reconciliation: candidate_hash must be "
            "non-empty text")
    if not isinstance(genesis_baseline, bool):
        raise SigningError(
            "history reconciliation: genesis_baseline must be "
            "a bool")
    if isinstance(known_unadopted_authorisation_ids,
                  (str, bytes)) \
            or known_unadopted_authorisation_ids is None:
        raise SigningError(
            "history reconciliation: "
            "known_unadopted_authorisation_ids must be an "
            "iterable of authorisation id strings")
    try:
        known_unadopted = set(known_unadopted_authorisation_ids)
    except TypeError as exc:
        raise SigningError(
            "history reconciliation: "
            "known_unadopted_authorisation_ids must be an "
            "iterable of authorisation id strings") from exc
    if not all(isinstance(i, str) and i for i in known_unadopted):
        raise SigningError(
            "history reconciliation: "
            "known_unadopted_authorisation_ids must contain "
            "only non-empty strings")
    if genesis_baseline:
        return ()
    entries = sorted(entries, key=lambda e: e["seq"])

    record_ids = {rec.authorisation_id for rec in records}
    record_pairs = {_pair_of_record(rec) for rec in records}
    by_id = {rec.authorisation_id: rec for rec in records}
    head_entry = entries[-1] if entries else None

    def _supersede_excused(entry):
        for decision in decisions:
            if decision["abandoned_authorisation_id"] \
                    != entry["authorisation_id"]:
                continue
            # When the decision carries the abandoned movement's
            # target fields (real supersession entries do), they
            # must agree with THIS entry — a decision about a
            # different movement of the same id excuses nothing.
            ab_new_seq = decision.get("abandoned_new_cycle_seq")
            ab_new_hash = decision.get("abandoned_new_payload_hash")
            if isinstance(ab_new_seq, int) \
                    and not isinstance(ab_new_seq, bool) \
                    and isinstance(ab_new_hash, str) \
                    and (ab_new_seq, ab_new_hash) != (
                        entry["new_cycle_seq"],
                        entry["new_payload_hash"]):
                continue
            cand_seq = decision.get("candidate_cycle_seq")
            cand_hash = decision.get("candidate_payload_hash")
            cand_pair_known = isinstance(cand_seq, int) \
                and not isinstance(cand_seq, bool) \
                and isinstance(cand_hash, str)
            new_id = decision.get("new_authorisation_id")
            if isinstance(new_id, str) and new_id in by_id:
                # The replacement record landed. When the
                # decision also carries its candidate pair, the
                # landed record must BE that candidate movement,
                # not merely some record with the right id.
                if not cand_pair_known:
                    return True
                landed = by_id[new_id]
                if (landed.new_cycle_seq, landed.new_payload_hash) \
                        == (cand_seq, cand_hash):
                    return True
            if cand_pair_known:
                if (cand_seq, cand_hash) == (candidate_seq,
                                             candidate_hash):
                    return True
                # The decision's candidate pair pair-covered:
                # some store record attests that exact target
                # as its new side, with the decision's
                # superseding old side as its old side.
                sup_old_seq = decision.get(
                    "superseding_old_cycle_seq")
                sup_old_hash = decision.get(
                    "superseding_old_payload_hash")
                if (sup_old_seq, sup_old_hash, cand_seq,
                        cand_hash) in record_pairs:
                    return True
        return False

    missing = []
    for entry in entries:
        new_seq = entry["new_cycle_seq"]
        relevant = new_seq < candidate_seq or (
            new_seq == candidate_seq
            and entry["new_payload_hash"] != candidate_hash)
        if not relevant:
            continue
        pair = _pair_of_entry(entry)
        # PAIR coverage (the operative coverage rule; it
        # subsumes the same-id case, because a primary burn and
        # its recovery share the pair while differing in id,
        # ceremony and evidence — coverage is a statement about
        # the MOVEMENT being attested in the store, and the
        # id-bound check adds no constraint beyond it).
        if pair in record_pairs:
            continue
        # SUPERSESSION (fully bound, new side landed).
        if _supersede_excused(entry):
            continue
        # KNOWN-UNADOPTED HEAD: the excuse binds to the head
        # ENTRY itself (identity after the seq sort), never to
        # any entry that merely shares the head's id, and —
        # fix round, seat-gpt FIX 0.91 — only to a candidate
        # AT the head entry's own sequence: a candidate beyond
        # the head would adopt past the burn, and that reach
        # silently excused an adopted record's disappearance
        # when the pending journal's "adopted" line was lost
        # together with a store restore (the compound state is
        # indistinguishable from a genuine burn at this layer,
        # so the beyond reach is removed, not corroborated).
        if entry is head_entry \
                and entry["authorisation_id"] in known_unadopted \
                and entry["new_cycle_seq"] == candidate_seq:
            continue
        missing.append(entry)
    return tuple(missing)


def reconcile_history(store_history, consumption_entries,
                      supersession_entries=(), *,
                      candidate_seq, candidate_hash,
                      known_unadopted_authorisation_ids=(),
                      genesis_baseline=False) -> tuple:
    """Reconcile or refuse: returns ``()`` when the store
    history accounts for every consumption-journal entry
    relevant to the candidate; otherwise raises
    :class:`HistoryReconciliationRefused` with the
    deterministic code ``pin_store_history_incomplete``."""
    missing = find_missing_history(
        store_history, consumption_entries, supersession_entries,
        candidate_seq=candidate_seq, candidate_hash=candidate_hash,
        known_unadopted_authorisation_ids=(
            known_unadopted_authorisation_ids),
        genesis_baseline=genesis_baseline)
    if missing:
        ids = [e["authorisation_id"] for e in missing]
        raise HistoryReconciliationRefused(
            "pin store history is incomplete against the "
            "verifier consumption journal: "
            f"{len(missing)} consumed ceremony record(s) "
            "relevant to the candidate are missing from the "
            f"store history (authorisation_ids: {ids}); the "
            "store history is a restoration-lossy replica and "
            "the consumption journal is authoritative — an "
            "operator must reconcile the store against the "
            "journal before this adoption can proceed",
            missing_entries=missing)
    return ()


# -- provider helpers (composition seam; see module docstring) -------------


def consumption_entries_provider_from_home(verifier_home):
    """A zero-argument callable returning the consumption
    journal's entries, loaded fresh on every call."""
    home = Path(verifier_home)

    def _provider():
        from trust.ledger import CeremonyConsumptionLedger
        return CeremonyConsumptionLedger(home).entries()

    return _provider


def supersession_entries_provider_from_home(verifier_home):
    """A zero-argument callable returning the supersession
    journal's entries, loaded fresh on every call."""
    home = Path(verifier_home)

    def _provider():
        from trust.ledger import CeremonySupersessionLedger
        return CeremonySupersessionLedger(home).entries()

    return _provider
