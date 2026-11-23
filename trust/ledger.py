"""Hash-chained journals for the trust boundary.

Two journals, one mechanism:

* The ship ledger (verifier/orchestrator-side): a signed ship
  decision is burned BEFORE the loop records the cycle, and the
  burn is never refunded. Replay protection therefore does not
  depend on the loop's state file — rolling state back cannot
  un-burn a decision. A decision is single-use twice over: its
  decision_id can burn once, and its (proposal_id, manifest_hash)
  pair can burn once, so re-signing the same artifact under a
  fresh envelope does not launder a second ship.
* The signing ledger (verifier-side): every signature the
  verifier issues — gate decisions, attestation envelopes, and
  sealed-eval attestations, accepts AND rejections — is appended
  before the response is returned, and the verifier refuses to
  run without its ledger home. A signature with no ledger entry
  is evidence of a second signer using the key.

Both are finite, unkeyed hash chains (the oversight-journal
pattern): they detect edits, reordering, truncation and rollback
of the journal file itself only when a head hash is pinned
outside the journal. They are not MACed and grant no authority;
they make consumption and issuance auditable. The journals live
in verifier-home, outside the build tree and outside the loop's
state directory.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path

from signing.gate_decision import _canonical, _sha256

GENESIS_HASH = "0" * 64
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_ENTRY_KEYS = {"seq", "kind", "recorded_at", "prev_hash", "entry_hash"}


class LedgerError(Exception):
    """A journal operation was refused (duplicate burn, unknown
    decision, wrong kind)."""


class CorruptLedgerError(LedgerError):
    """The journal file failed validation: bad JSON, broken hash
    chain, oversize, malformed entry."""


# Strict parsing (Trust Boundary v3.1, parser inventory): the
# journal is parsed under the same contract as every other
# security-relevant consumer — duplicate keys and non-finite
# numbers are refused by the PARSER, not left to downstream
# validation, so this loader can never disagree with a strict
# consumer about what a journal document says.

def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CorruptLedgerError(f"duplicate key in journal: {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise CorruptLedgerError(f"non-finite number in journal: {name}")


def _parse_float_strict(text):
    value = float(text)
    if not math.isfinite(value):
        raise CorruptLedgerError(f"non-finite number in journal: {text}")
    return value


class HashChainJournal:
    """Append-only JSON journal with a hash chain, guarded by an
    exclusive flock on the journal directory (same pattern as the
    memory store: the lock is on the directory descriptor, not a
    lockfile inside it). Subclasses define entry fields."""

    FILENAME = "journal.json"
    EXTRA_KEYS: frozenset = frozenset()

    def __init__(self, journal_dir):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.journal_dir / self.FILENAME
        self._entries = self._load()

    # -- persistence ----------------------------------------------------

    def _load(self) -> list:
        if not self.journal_path.exists():
            return []
        try:
            raw = self.journal_path.read_bytes()
        except OSError as exc:
            raise CorruptLedgerError(f"unreadable journal: {exc}") from exc
        if len(raw) > MAX_JOURNAL_BYTES:
            raise CorruptLedgerError("journal exceeds the size cap")
        try:
            data = json.loads(raw.decode("utf-8"),
                              object_pairs_hook=_no_duplicate_keys,
                              parse_constant=_reject_constant,
                              parse_float=_parse_float_strict)
        except CorruptLedgerError:
            raise
        except (ValueError, UnicodeDecodeError) as exc:
            raise CorruptLedgerError(f"journal is not valid JSON: {exc}") \
                from exc
        if not isinstance(data, dict) or set(data) != {"entries"} \
                or not isinstance(data["entries"], list):
            raise CorruptLedgerError("journal shape is wrong")
        entries = data["entries"]
        prev = GENESIS_HASH
        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) \
                    or set(entry) != _ENTRY_KEYS | set(self.EXTRA_KEYS):
                raise CorruptLedgerError("journal entry has wrong keys")
            if entry["seq"] != position:
                raise CorruptLedgerError("journal entry seq is broken")
            if entry["prev_hash"] != prev:
                raise CorruptLedgerError("journal hash chain is broken")
            core = {k: v for k, v in entry.items() if k != "entry_hash"}
            if entry["entry_hash"] != _sha256(_canonical(core)):
                raise CorruptLedgerError("journal entry hash mismatch")
            prev = entry["entry_hash"]
        return entries

    def _save(self, entries) -> None:
        text = json.dumps({"entries": entries}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)
        raw = text.encode("utf-8")
        if len(raw) > MAX_JOURNAL_BYTES:
            raise LedgerError("journal exceeds the size cap")
        fd = os.open(self.journal_dir,
                     os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            # Re-check freshness under the lock: another process may
            # have appended since this instance loaded.
            on_disk = self._load()
            if len(on_disk) != len(self._entries) or (
                    on_disk and self._entries
                    and on_disk[-1]["entry_hash"]
                    != self._entries[-1]["entry_hash"]):
                raise CorruptLedgerError(
                    "journal changed on disk since load; refusing to "
                    "overwrite (reconstruct the journal and retry)")
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
        finally:
            os.close(fd)

    def _append(self, kind: str, recorded_at: str, **fields) -> dict:
        entry = {
            "seq": len(self._entries) + 1,
            "kind": kind,
            "recorded_at": recorded_at,
            "prev_hash": self.head(),
        }
        entry.update(fields)
        entry["entry_hash"] = _sha256(_canonical(
            {k: v for k, v in entry.items() if k != "entry_hash"}))
        self._save(self._entries + [entry])
        return dict(entry)

    def _reload(self) -> None:
        """Re-read and re-validate the journal from disk, so a
        long-lived instance never answers from a stale snapshot
        (another process may have appended since construction)."""
        self._entries = self._load()

    # -- reads ------------------------------------------------------------

    def head(self) -> str:
        return self._entries[-1]["entry_hash"] if self._entries \
            else GENESIS_HASH

    def entries(self) -> list:
        return [dict(e) for e in self._entries]


# Bounded reload-and-retry for the ship ledger's append path
# (Trust Boundary v3 crash laboratory, mandate item 2 / 3c).
# HashChainJournal._save refuses to overwrite a journal that
# changed on disk since this instance loaded — the right
# fail-closed default, but under CONCURRENT legitimate appends
# (two processes burning different decisions into one ledger) it
# made the loser fail spuriously with CorruptLedgerError even
# though nothing was corrupt. ShipLedger.burn / finalise
# therefore retry the whole reload -> validate -> append cycle a
# bounded number of times: every attempt re-reads the journal and
# re-runs the duplicate / claim validations against the fresh
# entries, so a concurrent append of the SAME decision or cycle
# is still refused (as a LedgerError on the retry's validation),
# never silently landed twice, and the hash chain is only ever
# extended from a head this instance has just verified.
_APPEND_RETRY_ATTEMPTS = 8


class ShipLedger(HashChainJournal):
    """Single-use burns for ship decisions."""

    FILENAME = "ship-ledger.json"
    EXTRA_KEYS = frozenset({"decision_id", "proposal_id",
                            "manifest_hash", "payload_hash",
                            "cycle_id"})

    def _find_burn(self, decision_id=None, pair=None):
        for entry in self._entries:
            if entry["kind"] != "burn":
                continue
            if decision_id is not None \
                    and entry["decision_id"] == decision_id:
                return entry
            if pair is not None \
                    and (entry["proposal_id"], entry["manifest_hash"]) \
                    == pair:
                return entry
        return None

    def is_consumed(self, *, decision_id, proposal_id,
                    manifest_hash) -> bool:
        self._reload()
        return self._find_burn(decision_id) is not None \
            or self._find_burn(pair=(proposal_id, manifest_hash)) \
            is not None

    def burn(self, *, decision_id, proposal_id, manifest_hash,
             payload_hash, recorded_at) -> dict:
        """Consume a ship decision BEFORE the ship is recorded.
        Burns are never refunded: a ship that fails after the burn
        has spent the decision, and shipping the same artifact
        needs a fresh decision. That asymmetry is deliberate —
        it makes the failure direction safe."""
        last_error = None
        for _attempt in range(_APPEND_RETRY_ATTEMPTS):
            self._reload()
            for value, name in ((decision_id, "decision_id"),
                                (proposal_id, "proposal_id"),
                                (manifest_hash, "manifest_hash"),
                                (payload_hash, "payload_hash")):
                if not isinstance(value, str) or not value:
                    raise LedgerError(
                        f"{name} must be a non-empty string")
            if self._find_burn(decision_id) is not None:
                raise LedgerError(
                    f"decision already consumed: {decision_id}")
            if self._find_burn(pair=(proposal_id, manifest_hash)) \
                    is not None:
                raise LedgerError(
                    "this (proposal_id, manifest_hash) pair was "
                    "already shipped under another decision")
            try:
                return self._append(
                    "burn", recorded_at, decision_id=decision_id,
                    proposal_id=proposal_id,
                    manifest_hash=manifest_hash,
                    payload_hash=payload_hash, cycle_id="")
            except CorruptLedgerError as exc:
                # A concurrent append landed between our reload
                # and our save; reload, re-validate (above) and
                # retry, a bounded number of times.
                last_error = exc
        raise last_error

    def finalise(self, *, decision_id, cycle_id, recorded_at) -> dict:
        last_error = None
        for _attempt in range(_APPEND_RETRY_ATTEMPTS):
            self._reload()
            burn = self._find_burn(decision_id)
            if burn is None:
                raise LedgerError(
                    f"no burn found for decision: {decision_id}")
            for entry in self._entries:
                if entry["kind"] == "finalise" \
                        and entry["decision_id"] == decision_id:
                    raise LedgerError(
                        f"decision already finalised: {decision_id}")
            # Cycle-claim uniqueness (Trust Boundary v2 fix round 2,
            # N1): one recorded cycle finalises exactly one decision.
            # A cycle_id already finalised under a DIFFERENT decision
            # is refused; the same-decision case above is unchanged
            # (it raises, and callers that tolerate an already-landed
            # finalise re-check for their own decision's entry).
            for entry in self._entries:
                if entry["kind"] == "finalise" \
                        and entry["decision_id"] != decision_id \
                        and str(entry["cycle_id"]) == str(cycle_id):
                    raise LedgerError(
                        f"cycle {cycle_id!r} already finalised under "
                        f"a different decision: {entry['decision_id']}")
            try:
                return self._append(
                    "finalise", recorded_at, decision_id=decision_id,
                    proposal_id=burn["proposal_id"],
                    manifest_hash=burn["manifest_hash"],
                    payload_hash=burn["payload_hash"],
                    cycle_id=cycle_id)
            except CorruptLedgerError as exc:
                last_error = exc
        raise last_error


class SigningLedger(HashChainJournal):
    """Every signature the verifier issues — gate decisions,
    verifier-attestation envelopes, and sealed-eval attestations —
    appended before the response is returned. A signature with no
    ledger entry is evidence of a second signer using the key;
    that inference is sound only because the verifier REQUIRES
    its ledger home (see trust/verifier_main.py) and ledgers all
    three formats."""

    FILENAME = "signing-ledger.json"
    EXTRA_KEYS = frozenset({"decision_id", "payload_hash", "purpose",
                            "proposal_id", "accepted", "signer_id",
                            "format"})

    def append_envelope(self, signed, *, recorded_at) -> dict:
        from signing.gate_decision import SignedGateDecision
        if not isinstance(signed, SignedGateDecision):
            raise LedgerError("can only ledger a SignedGateDecision")
        self._reload()
        return self._append(
            "sign", recorded_at, decision_id=signed.decision_id,
            payload_hash=signed.payload_hash, purpose=signed.purpose,
            proposal_id=signed.decision.proposal_id,
            accepted=signed.decision.accepted,
            signer_id=signed.signer_id, format="gate-decision")

    def append_attestation_envelope(self, signed_att, *,
                                    recorded_at) -> dict:
        from signing.attestation import SignedAttestation
        if not isinstance(signed_att, SignedAttestation):
            raise LedgerError("can only ledger a SignedAttestation")
        self._reload()
        return self._append(
            "sign", recorded_at, decision_id=signed_att.attestation_id,
            payload_hash=signed_att.payload_hash,
            purpose="attestation",
            proposal_id=signed_att.proposal_id,
            accepted=signed_att.attestation.decision == "approve",
            signer_id=signed_att.signer_id,
            format="verifier-attestation")

    def append_eval_attestation(self, record, *, recorded_at) -> dict:
        if not isinstance(record, dict) \
                or "payload" not in record \
                or "payload_hash" not in record:
            raise LedgerError("can only ledger an eval attestation "
                              "record")
        self._reload()
        return self._append(
            "sign", recorded_at, decision_id=record["payload_hash"],
            payload_hash=record["payload_hash"],
            purpose="sealed-eval", proposal_id="", accepted=True,
            signer_id=record["payload"]["signer_id"],
            format="sealed-eval")

    def append_ceremony_authorisation(self, signed, *,
                                      recorded_at) -> dict:
        """Ledger a ceremony authorisation envelope (cycle 19) in
        the EXISTING entry shape — EXTRA_KEYS is untouched, so no
        journal format migration. Column reuse, documented: the
        proposal_id column holds the authorisation's scope id,
        which for a ceremony authorisation is its ceremony_id
        (precedent: append_claim stores the claimant in signer_id;
        append_eval_attestation stores proposal_id="").
        decision_id is the authorisation_id, purpose is the
        envelope's purpose, format "ceremony-authorisation",
        accepted=True (an authorisation is an issuance, never a
        rejection artefact — refusals are unledgered)."""
        from signing.ceremony_authorisation import \
            SignedCeremonyAuthorisation
        if not isinstance(signed, SignedCeremonyAuthorisation):
            raise LedgerError(
                "can only ledger a SignedCeremonyAuthorisation")
        self._reload()
        return self._append(
            "sign", recorded_at, decision_id=signed.authorisation_id,
            payload_hash=signed.payload_hash,
            purpose="pin-ceremony-authorisation",
            proposal_id=signed.ceremony_id,
            accepted=True,
            signer_id=signed.signer_id,
            format="ceremony-authorisation")

    def append_claim(self, claim_document, *, recorded_at,
                     signer_id="") -> dict:
        """Ledger an UNSIGNED claim. A claim is a caller assertion
        the verifier records for audit — it is not a signature, it
        grants nothing, and its entry is therefore kind "claim"
        (never "sign") with accepted=False always. decision_id and
        payload_hash are both the sha256 of the canonical claim
        document, so the returned claim_id / claim_hash name the
        claim and nothing else: no envelope exists under that id.
        signer_id here names the CLAIMANT (the attestation's
        verifier_id), not a signer — no key was used."""
        if not isinstance(claim_document, dict) \
                or not isinstance(claim_document.get("proposal_id"), str) \
                or not claim_document["proposal_id"]:
            raise LedgerError(
                "can only ledger a claim document with a proposal_id")
        self._reload()
        claim_hash = _sha256(_canonical(claim_document))
        return self._append(
            "claim", recorded_at, decision_id=claim_hash,
            payload_hash=claim_hash, purpose="claim",
            proposal_id=claim_document["proposal_id"],
            accepted=False, signer_id=signer_id, format="claim")

    def try_consume_eval_records(self, record_hashes, *,
                                 proposal_id, signer_id,
                                 recorded_at) -> bool:
        """Single-use consumption of sealed-eval records at
        attestation issuance (Trust Boundary v3, item 3).

        Appends ONE journal entry per record hash, with
        kind="consume", format="eval-consumption",
        purpose="attestation-consumption",
        decision_id=payload_hash=the record's payload_hash,
        accepted=False, proposal_id as given, and signer_id=the
        consuming signer. Returns True when both (all) records
        were consumed by this call; returns False when either
        hash already carries a consumption entry — the caller
        must then refuse the issuance
        (eval_evidence_consumed).

        Race safety: consumption is checked and appended against
        a fresh load, and the append goes through
        HashChainJournal._save's optimistic-concurrency check
        (CorruptLedgerError when the on-disk journal changed
        since this instance loaded). On CorruptLedgerError the
        method reloads and retries, bounded at 8 attempts; a
        retry reload that finds either hash already consumed
        returns False, and exhausting the attempts under
        contention also returns False (fail-closed: a refused
        issuance, never a double issuance).

        Atomicity adaptation (documented deviation from a naive
        two-append reading): the two entries are built in memory
        and persisted with ONE _save (one atomic file replace),
        not two separate appends. A crash therefore cannot leave
        exactly one of the pair consumed: before the save nothing
        is consumed and no attestation was signed (the caller
        consumes BEFORE signing); after the save both records are
        consumed and a crash before the caller returns the
        attestation leaves the evidence spent with no attestation
        issued — fail-closed in both directions, with no
        half-consumed pair for a retry to misread as another
        process's consumption."""
        hashes = list(record_hashes) if isinstance(
            record_hashes, (list, tuple)) else None
        if hashes is None or not hashes \
                or not all(isinstance(h, str) and h for h in hashes):
            raise LedgerError(
                "record_hashes must be a non-empty list of hashes")
        if len(set(hashes)) != len(hashes):
            raise LedgerError("record_hashes must be distinct")
        for value, name in ((proposal_id, "proposal_id"),
                            (signer_id, "signer_id"),
                            (recorded_at, "recorded_at")):
            if not isinstance(value, str) or not value:
                raise LedgerError(f"{name} must be a non-empty string")
        for _attempt in range(8):
            self._reload()
            consumed = {
                e["payload_hash"] for e in self._entries
                if e["kind"] == "consume"
                and e["format"] == "eval-consumption"}
            if any(h in consumed for h in hashes):
                return False
            new_entries = []
            prev = self.head()
            seq = len(self._entries)
            for record_hash in hashes:
                seq += 1
                entry = {
                    "seq": seq,
                    "kind": "consume",
                    "recorded_at": recorded_at,
                    "prev_hash": prev,
                    "decision_id": record_hash,
                    "payload_hash": record_hash,
                    "purpose": "attestation-consumption",
                    "proposal_id": proposal_id,
                    "accepted": False,
                    "signer_id": signer_id,
                    "format": "eval-consumption",
                }
                entry["entry_hash"] = _sha256(_canonical(
                    {k: v for k, v in entry.items()
                     if k != "entry_hash"}))
                prev = entry["entry_hash"]
                new_entries.append(entry)
            try:
                self._save(self._entries + new_entries)
            except CorruptLedgerError:
                continue
            return True
        return False

    def has_envelope(self, decision_id) -> bool:
        self._reload()
        return any(e["kind"] == "sign" and e["decision_id"] == decision_id
                   for e in self._entries)


class CeremonyAuthorisationLedger(HashChainJournal):
    """Single-use store of record for ceremony authorisations
    (cycle 19): one entry per ISSUED authorisation, in its own
    file in the verifier home.

    The signing ledger's entry shape carries neither ceremony_id
    nor evidence_hash, and widening its EXTRA_KEYS would be a
    journal format migration (every historical entry would fail
    the exact-key-set load check) — so anti-replay lives here, in
    a sibling journal, and the signing ledger records the same
    issuance in its own shape via
    SigningLedger.append_ceremony_authorisation.

    The verifier's ceremony_authorise mode appends here FIRST:
    this append is the commit point for single-use. After it
    lands, the (ceremony_id, evidence_hash) pair is spent whether
    or not anything else succeeds; a later failure withholds the
    envelope and the pair stays burned (recovery is a NEW
    ceremony_id with a NEW evidence bundle).

    Entries are kind "authorise" — never "sign": the signature
    inference ("a signature with no ledger entry is evidence of
    a second signer") lives in the signing ledger; this journal
    is the reuse memory.

    Rollback residual, stated plainly: no external anchor covers
    this journal yet (follow-up: ceremony-journal-anchoring).
    Rolling this file back erases the reuse memory — a listed
    operator could then obtain a second authorisation for the
    same evidence under a new ceremony_id. The anchored signing
    ledger preserves the issuance record (authorisation_id,
    payload_hash, ceremony_id as proposal_id), so a duplicate
    issuance under the SAME ceremony_id leaves a visible
    duplicate trace there; but it stores neither evidence_hash
    nor operator_id, so evidence reuse under a NEW ceremony_id
    is NOT detectable from the anchored store without the
    retained envelopes. The evidence-reuse guarantee is:
    prevented against an intact journal; after a rollback,
    detectable only for same-ceremony_id reuse, and otherwise
    only by audit against retained envelopes."""

    FILENAME = "ceremony-authorisations.json"
    EXTRA_KEYS = frozenset({"authorisation_id", "payload_hash",
                            "ceremony_id", "evidence_hash",
                            "operator_id", "issued_at"})

    def find_by_ceremony(self, ceremony_id):
        self._reload()
        for entry in self._entries:
            if entry["ceremony_id"] == ceremony_id:
                return dict(entry)
        return None

    def find_by_evidence(self, evidence_hash):
        self._reload()
        for entry in self._entries:
            if entry["evidence_hash"] == evidence_hash:
                return dict(entry)
        return None

    def append_authorisation(self, signed, *, recorded_at) -> dict:
        from signing.ceremony_authorisation import \
            SignedCeremonyAuthorisation
        if not isinstance(signed, SignedCeremonyAuthorisation):
            raise LedgerError(
                "can only ledger a SignedCeremonyAuthorisation")
        self._reload()
        return self._append(
            "authorise", recorded_at,
            authorisation_id=signed.authorisation_id,
            payload_hash=signed.payload_hash,
            ceremony_id=signed.ceremony_id,
            evidence_hash=signed.evidence_hash,
            operator_id=signed.operator_id,
            issued_at=recorded_at)
