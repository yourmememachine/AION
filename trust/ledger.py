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
MAX_RECOVERY_DEPTH = 2
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_ENTRY_KEYS = {"seq", "kind", "recorded_at", "prev_hash", "entry_hash"}


class LedgerError(Exception):
    """A journal operation was refused (duplicate burn, unknown
    decision, wrong kind)."""


class CorruptLedgerError(LedgerError):
    """The journal file failed validation: bad JSON, broken hash
    chain, oversize, malformed entry."""


class AlreadyConsumedError(LedgerError):
    """A ceremony authorisation (or its exact target) is already
    consumed. Machine-distinguishable from a head regression via
    the ``reason`` attribute (cycle 21): the consume mode maps
    this subclass to ``ceremony_already_consumed`` and
    HeadRegressionError to ``ceremony_head_regression``; any
    other LedgerError maps to ``ledger_failed``. These
    distinctions are state oracles by design (see the consume
    mode's docstring); the no-oracle claim covers verification
    failures only."""

    reason = "already_consumed"


class HeadRegressionError(LedgerError):
    """A ceremony envelope's candidate or old pin does not
    satisfy the monotonic head rules against the consumption
    journal's current head. See AlreadyConsumedError for the
    mode-mapping contract."""

    reason = "head_regression"


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

    def _allowed_entry_key_sets(self):
        """Entry key sets _load accepts (cycle 23, R3 seam).

        Default: the single current set (_ENTRY_KEYS |
        EXTRA_KEYS), so default behaviour is byte-identical
        for every existing journal. Subclasses with a schema
        version (the ceremony ledgers) override this to accept
        their v1 and v2 sets, plus positional monotonicity and
        value validation in their own _load."""
        return (frozenset(_ENTRY_KEYS | set(self.EXTRA_KEYS)),)

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
        allowed = self._allowed_entry_key_sets()
        prev = GENESIS_HASH
        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) \
                    or frozenset(entry) not in allowed:
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

    def append_ceremony_consumption(self, signed, *,
                                    recorded_at) -> dict:
        """Mirror a ceremony consumption (cycle 21) in the
        EXISTING entry shape — EXTRA_KEYS is untouched, so no
        journal format migration. This is an audit mirror, NOT
        a second commit: it is invoked only after
        CeremonyConsumptionLedger.append_consumption has
        committed, and it puts the consumption fact into
        the signing ledger as an anchored audit trace (since
        cycle 22 the consumption journal carries its own
        external anchor, advanced before this mirror write).
        Column reuse follows append_ceremony_authorisation /
        try_consume_eval_records' eval-consumption entries:
        kind "consume", format "ceremony-consumption",
        decision_id = authorisation_id, proposal_id =
        ceremony_id, accepted=False. Any cross-check for
        consumptions MUST scope to kind="consume" AND
        format="ceremony-consumption": the issuance mirror
        already writes decision_id = authorisation_id under
        kind "sign", and an unscoped scan would refuse every
        consume as already-consumed."""
        from signing.ceremony_authorisation import \
            SignedCeremonyAuthorisation
        if not isinstance(signed, SignedCeremonyAuthorisation):
            raise LedgerError(
                "can only ledger a SignedCeremonyAuthorisation")
        self._reload()
        return self._append(
            "consume", recorded_at, decision_id=signed.authorisation_id,
            payload_hash=signed.payload_hash,
            purpose="pin-ceremony-consumption",
            proposal_id=signed.ceremony_id,
            accepted=False,
            signer_id=signed.signer_id,
            format="ceremony-consumption")

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
    _V2_EXTRA_KEYS = EXTRA_KEYS | {"recovery_of"}

    def _allowed_entry_key_sets(self):
        # Schema v2 (cycle 23 / DECISION-CONSUMPTION-HEAD
        # Addendum 3, pending): v1 entries (EXTRA_KEYS) and v2
        # entries (v1 + recovery_of). New appends are always v2.
        return (frozenset(_ENTRY_KEYS | set(self.EXTRA_KEYS)),
                frozenset(_ENTRY_KEYS | set(self._V2_EXTRA_KEYS)))

    def _load(self) -> list:
        entries = HashChainJournal._load(self)
        seen_v2 = False
        for entry in entries:
            is_v2 = "recovery_of" in entry
            if is_v2:
                seen_v2 = True
                if not isinstance(entry["recovery_of"], str):
                    raise CorruptLedgerError(
                        "authorisation v2 recovery_of must be a "
                        "string")
                # Cycle 23 fix round (r1-F4): the binding is
                # an authorisation id or nothing — "" (not a
                # recovery issuance) or a 64-char lowercase hex
                # authorisation id; anything else is corrupt.
                rec_of = entry["recovery_of"]
                if rec_of != "" and not (
                        len(rec_of) == 64 and all(
                            c in "0123456789abcdef"
                            for c in rec_of)):
                    raise CorruptLedgerError(
                        "authorisation v2 recovery_of must be "
                        "empty or a 64-char lowercase hex "
                        "authorisation id")
            elif seen_v2:
                raise CorruptLedgerError(
                    "authorisation journal has a v1 entry after "
                    "a v2 entry (positional monotonicity)")
        return entries

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

    def find_by_authorisation_id(self, authorisation_id):
        self._reload()
        for entry in self._entries:
            if entry["authorisation_id"] == authorisation_id:
                return dict(entry)
        return None

    def append_authorisation(self, signed, *, recorded_at,
                             recovery_of="") -> dict:
        """Append an issuance as a schema-v2 entry (cycle 23).

        recovery_of is the authorisation_id of the consumption
        (burn) this issuance recovers, computed by the verifier
        from its own consumption journal at authorise step (5b)
        for reason burned_unadopted, and "" otherwise. It is
        never read from the request. The consume path reads it
        back from this entry to bind a recovery consumption to
        exactly that burn."""
        from signing.ceremony_authorisation import \
            SignedCeremonyAuthorisation
        if not isinstance(signed, SignedCeremonyAuthorisation):
            raise LedgerError(
                "can only ledger a SignedCeremonyAuthorisation")
        if not isinstance(recovery_of, str):
            raise LedgerError("recovery_of must be a string")
        self._reload()
        # Duplicate re-check against the FRESHLY loaded entries
        # (cycle 20 fix round): the mode's anti-replay scan ran
        # earlier on its own snapshot, so a competitor commit
        # landing between that scan and this append must be
        # caught here, at the commit point — otherwise two
        # envelopes are handed out for one (ceremony_id,
        # evidence_hash) pair. This check composes with
        # HashChainJournal._save's under-flock freshness check:
        # a commit landing before this reload is seen by the
        # check below; a commit landing after it trips the
        # freshness check in _save instead. Either way the
        # loser raises (LedgerError here, CorruptLedgerError —
        # a LedgerError subclass — from _save) and its envelope
        # is withheld by the mode as ledger_failed.
        for entry in self._entries:
            if entry["ceremony_id"] == signed.ceremony_id:
                raise LedgerError(
                    "ceremony_id already authorised: "
                    f"{signed.ceremony_id}")
            if entry["evidence_hash"] == signed.evidence_hash:
                raise LedgerError(
                    "evidence_hash already authorised for another "
                    "ceremony")
        return self._append(
            "authorise", recorded_at,
            authorisation_id=signed.authorisation_id,
            payload_hash=signed.payload_hash,
            ceremony_id=signed.ceremony_id,
            evidence_hash=signed.evidence_hash,
            operator_id=signed.operator_id,
            issued_at=recorded_at,
            recovery_of=recovery_of)


class CeremonyConsumptionLedger(HashChainJournal):
    """Verifier-owned consumption record for ceremony
    authorisations (cycle 21): one entry per CONSUMED
    authorisation, in its own file in the verifier home. This
    journal is the authoritative monotonic consumption head:
    its latest entry's (new_cycle_seq, new_payload_hash) is
    the head target every later consumption is checked
    against (DESIGN-FINAL R3). That head is a CEREMONY head —
    it sees consumptions only; advance_pin movements never
    pass through the verifier, so a pin advanced outside
    ceremonies is invisible to this journal. The residual
    class that leaves is named in
    DECISION-CONSUMPTION-HEAD.md.

    Schema v2 (cycle 23, R3): entries carry lineage —
    consumption_kind ("primary"/"recovery"), recovery_of
    (the authorisation_id of the burn a recovery consumes,
    "" for primary) and recovery_depth (0 for primary,
    1..MAX_RECOVERY_DEPTH for recovery). A movement is
    consumable at most 1 + MAX_RECOVERY_DEPTH times: a
    primary consumption plus bounded recoveries of its
    successive burns. v1 entries (cycles 21-22, no lineage
    fields) load unchanged and are never rewritten; a v1
    entry after a v2 entry is corrupt (positional
    monotonicity).

    The append here is THE commit point for consumption.
    append_consumption re-checks single-use AND the head
    rules against freshly reloaded entries inside its
    bounded reload-retry loop (the issuance-race lesson), so
    the concurrent loser surfaces as already-consumed
    (AlreadyConsumedError), not corruption. The signing
    ledger's ceremony-consumption entry is an audit mirror
    written only after this commit; it is never the
    authority and must never be appended first.

    Anchoring (cycle 22, R2, replacing cycle 21's R10
    residual): this journal IS externally anchored in its
    own right (anchor kind "ceremony-consumption", verified
    by the verifier at startup on every invocation when
    configured; required in production when the ceremony
    seed is configured). With the consumption anchor
    configured, a burn whose anchor update completed
    survives a verifier-home rollback (detected at startup,
    anchor_refused); the append→anchor-update window (burn
    in journal, anchor at pre-burn prefix) is protected
    against an intact home but NOT against a full rollback
    inside that window — the same window every anchored
    append in this system carries; research mode / anchor
    unconfigured: no rollback claim, and this journal can
    be deleted or rolled back undetectably. The follow-up
    ceremony-journal-anchoring is narrowed to the issuance
    journal only.

    Note on head(): this class does NOT override the base
    class's head() — head() returns the hash-chain head hash
    (GENESIS_HASH when empty) per the base contract, like
    every HashChainJournal subclass. The consumed HEAD
    TARGET is exposed separately as head_target(). The base
    _append is overridden so the chain bookkeeping uses the
    hash head explicitly via chain_head()."""

    FILENAME = "ceremony-consumptions.json"
    EXTRA_KEYS = frozenset({
        "authorisation_id", "ceremony_id", "operator_id",
        "old_cycle_seq", "old_payload_hash",
        "new_cycle_seq", "new_payload_hash",
        "evidence_hash", "consumed_at"})
    _V2_EXTRA_KEYS = EXTRA_KEYS | {
        "consumption_kind", "recovery_of", "recovery_depth"}

    def _allowed_entry_key_sets(self):
        # Schema v2 (cycle 23 / DECISION-CONSUMPTION-HEAD
        # Addendum 3, pending): v1 entries (EXTRA_KEYS) and v2
        # entries (v1 + consumption_kind/recovery_of/
        # recovery_depth). v1 entries are never rewritten or
        # normalised (their hashes are anchor-covered); new
        # appends are always v2.
        return (frozenset(_ENTRY_KEYS | set(self.EXTRA_KEYS)),
                frozenset(_ENTRY_KEYS | set(self._V2_EXTRA_KEYS)))

    @staticmethod
    def _pair_of(entry):
        return (entry["old_cycle_seq"], entry["old_payload_hash"],
                entry["new_cycle_seq"], entry["new_payload_hash"])

    @staticmethod
    def _recorded_depth(entries, index) -> int:
        """Depth of entries[index] within a loaded journal:
        v2 entries carry it; a v1 entry's depth is pair-derived
        (the number of EARLIER entries with its exact pair —
        the derived_head_depth rule, applied per entry)."""
        entry = entries[index]
        if "consumption_kind" in entry:
            return entry["recovery_depth"]
        pair = CeremonyConsumptionLedger._pair_of(entry)
        return sum(
            1 for e in entries[:index]
            if CeremonyConsumptionLedger._pair_of(e) == pair)

    def _load(self) -> list:
        entries = HashChainJournal._load(self)
        seen_v2 = False
        # Single-use at load (cycle 23 re-review, r1): an
        # authorisation_id may occur at most once in the
        # journal; append_consumption refuses duplicates at
        # the commit point, and the loader refuses a journal
        # that somehow contains one.
        seen_authorisations = set()
        for entry in entries:
            if entry["authorisation_id"] in seen_authorisations:
                raise CorruptLedgerError(
                    "consumption journal contains a duplicate "
                    "authorisation_id")
            seen_authorisations.add(entry["authorisation_id"])
        # v1 pair cap (cycle 23 fix round, r1-F3): the v1
        # pair-scan derivation is exact only while a v1 pair
        # occurs at most twice; a third occurrence is corrupt.
        v1_pair_counts = {}
        for entry in entries:
            if "consumption_kind" not in entry:
                pair = self._pair_of(entry)
                v1_pair_counts[pair] = v1_pair_counts.get(pair, 0) + 1
                if v1_pair_counts[pair] >= 3:
                    raise CorruptLedgerError(
                        "v1 consumption pair occurs 3 or more "
                        "times (pair-scan derivation is exact "
                        "only up to two occurrences)")
        for index, entry in enumerate(entries):
            is_v2 = "consumption_kind" in entry
            if is_v2:
                seen_v2 = True
                kind = entry["consumption_kind"]
                depth = entry["recovery_depth"]
                rec_of = entry["recovery_of"]
                if kind not in ("primary", "recovery") \
                        or not isinstance(depth, int) \
                        or isinstance(depth, bool) \
                        or not isinstance(rec_of, str):
                    raise CorruptLedgerError(
                        "consumption v2 entry has incoherent "
                        "lineage fields")
                if kind == "primary":
                    if depth != 0 or rec_of != "":
                        raise CorruptLedgerError(
                            "primary consumption must have "
                            "recovery_depth 0 and empty recovery_of")
                    # A movement's pair is consumed as a
                    # primary at most once (cycle 23 re-review,
                    # r1): check_head refuses a second primary
                    # of an already-consumed pair in every
                    # position (at head: already-consumed;
                    # behind head: regression; the supersede
                    # branch requires a strictly ahead
                    # candidate, which the same pair is not).
                    # A v2 primary whose pair occurred in ANY
                    # earlier entry is therefore a second root
                    # the append path can never write — corrupt.
                    pair = self._pair_of(entry)
                    if any(self._pair_of(earlier) == pair
                           for earlier in entries[:index]):
                        raise CorruptLedgerError(
                            "primary consumption re-roots an "
                            "already-consumed pair (cross-entry "
                            "lineage)")
                else:
                    if not (1 <= depth <= MAX_RECOVERY_DEPTH) \
                            or not rec_of:
                        raise CorruptLedgerError(
                            "recovery consumption must have "
                            "recovery_depth in 1..MAX_RECOVERY_DEPTH "
                            "and a non-empty recovery_of")
                    # Cross-entry lineage (cycle 23 fix round,
                    # r1-F1, strengthened at re-review): a
                    # recovery must name, via recovery_of, its
                    # IMMEDIATE PREDECESSOR entry (v1 or v2)
                    # with the SAME old->new pair whose depth
                    # is exactly this entry's depth - 1. The
                    # burn a recovery consumes is the head at
                    # consume time, so in every append-reachable
                    # history the burn is the entry directly
                    # before the recovery; grounding on any
                    # earlier entry would admit branched
                    # lineages ([primary, recovery d1, recovery
                    # d1, recovery d2]) the append path can
                    # never write. Ghost bindings, wrong-pair
                    # recoveries and depth jumps are corrupt,
                    # not merely unusual.
                    pair = self._pair_of(entry)
                    grounded = index > 0 and (
                        entries[index - 1]["authorisation_id"]
                        == rec_of
                        and self._pair_of(entries[index - 1]) == pair
                        and self._recorded_depth(entries, index - 1)
                        == depth - 1)
                    if not grounded:
                        raise CorruptLedgerError(
                            "recovery consumption is not grounded "
                            "on its immediate predecessor at "
                            "depth - 1 named by recovery_of "
                            "(cross-entry lineage)")
            elif seen_v2:
                raise CorruptLedgerError(
                    "consumption journal has a v1 entry after a "
                    "v2 entry (positional monotonicity)")
        return entries

    @staticmethod
    def _is_v2(entry) -> bool:
        return "consumption_kind" in entry

    @staticmethod
    def derived_head_depth(entries) -> int:
        """Recovery depth of the head entry in ``entries``.

        v2 head: its recorded recovery_depth. v1 head: derived
        by the pair-scan, retained ONLY as this v1 derivation
        (cycle 23, R3) — exact under cycles 21-22 history,
        where a v1 old->new pair occurs at most twice: first
        occurrence is depth 0, second is depth 1 (so the depth
        is the number of earlier entries with the head's exact
        old->new pair). Empty journal: 0."""
        if not entries:
            return 0
        head = entries[-1]
        if CeremonyConsumptionLedger._is_v2(head):
            return head["recovery_depth"]
        head_pair = (head["old_cycle_seq"], head["old_payload_hash"],
                     head["new_cycle_seq"], head["new_payload_hash"])
        return sum(
            1 for e in entries[:-1]
            if (e["old_cycle_seq"], e["old_payload_hash"],
                e["new_cycle_seq"], e["new_payload_hash"]) == head_pair)

    @staticmethod
    def _derive_lineage(entries, signed, recovery_of):
        """Derive (consumption_kind, recovery_of, recovery_depth)
        for consuming ``signed`` against ``entries``.

        Rules (cycle 23, R3):
        * reason != burned_unadopted -> ("primary", "", 0).
        * reason == burned_unadopted -> ("recovery", bound_id,
          head_depth + 1) IFF the bound recovery_of equals the
          CURRENT head entry's authorisation_id AND candidate +
          old pin exactly equal the head's target/old
          (match_head_burn semantics) AND head depth <
          MAX_RECOVERY_DEPTH. ``recovery_of=None`` is the
          legacy/direct-caller sentinel: the bound id is taken
          as the head entry's own authorisation_id (no issuance
          entry exists to thread in that path); an explicit
          string — including "" — is enforced exactly.
        * Otherwise (bound burn not head, bound mismatch, or
          cap reached) a burned_unadopted envelope is NEVER
          reclassified as a primary (cycle 23 fix round,
          r1-F2): the lineage is the non-primary marker
          ("unrecoverable", "", 0), and check_head refuses
          every such envelope (AlreadyConsumedError when the
          candidate equals the head target; HeadRegressionError
          at every other candidate position, and against an
          empty journal). The marker is therefore never what
          append_consumption writes — check_head runs first
          in its retry loop and raises."""
        if signed.reason != "burned_unadopted":
            return ("primary", "", 0)
        if not entries:
            return ("unrecoverable", "", 0)
        burn = CeremonyConsumptionLedger.match_head_burn(
            entries, candidate=signed.candidate,
            old_pin=signed.old_pin)
        if burn is None:
            return ("unrecoverable", "", 0)
        if recovery_of is None:
            # Legacy sentinel: no issuance binding was threaded
            # in, so the head entry itself is the bound burn
            # (synthetic head dicts in unit tests may not even
            # carry an authorisation_id).
            bound = burn.get("authorisation_id", "")
        else:
            bound = recovery_of
            if bound != burn.get("authorisation_id"):
                return ("unrecoverable", "", 0)
        head_depth = CeremonyConsumptionLedger.derived_head_depth(
            entries)
        if head_depth >= MAX_RECOVERY_DEPTH:
            return ("unrecoverable", "", 0)
        return ("recovery", bound, head_depth + 1)

    # -- hash-chain plumbing (head() keeps the base contract)

    def chain_head(self) -> str:
        return HashChainJournal.head(self)

    def _append(self, kind: str, recorded_at: str, **fields) -> dict:
        entry = {
            "seq": len(self._entries) + 1,
            "kind": kind,
            "recorded_at": recorded_at,
            "prev_hash": self.chain_head(),
        }
        entry.update(fields)
        entry["entry_hash"] = _sha256(_canonical(
            {k: v for k, v in entry.items() if k != "entry_hash"}))
        self._save(self._entries + [entry])
        return dict(entry)

    # -- reads ------------------------------------------------------

    def head_target(self):
        """The consumed head target: (new_cycle_seq,
        new_payload_hash) of the latest entry, or None when
        the journal is empty. This is NOT head(): the base
        class's head() is inherited unchanged and returns the
        hash-chain head hash, per the base contract."""
        self._reload()
        if not self._entries:
            return None
        last = self._entries[-1]
        return (last["new_cycle_seq"], last["new_payload_hash"])

    def find_by_authorisation(self, authorisation_id):
        self._reload()
        for entry in self._entries:
            if entry["authorisation_id"] == authorisation_id:
                return dict(entry)
        return None

    # -- head rules (DESIGN-FINAL R3, merged final form) ------------

    @staticmethod
    def match_head_burn(entries, *, candidate, old_pin):
        """Return the head entry iff it is exactly the burn a
        burned_unadopted recovery re-anchors to, else None.
        candidate / old_pin are the projected shapes
        (old_pin None or {cycle_seq, payload_hash}).

        Cycle 23 (R3, superseding the cycle-22 one-shot rule /
        DECISION-CONSUMPTION-HEAD Addendum 3, pending): this is
        burn IDENTIFICATION only — candidate + old pin must
        exactly equal the head entry's recorded target and old
        pin. Whether that burn may ground a recovery is decided
        by the depth rules (derived_head_depth / _derive_lineage
        and authorise step 5b's cap refusal), not here: a
        recovery consumption (schema v2) records its lineage,
        so a recovery head CAN ground a further recovery up to
        MAX_RECOVERY_DEPTH. The old pair-scan clause is removed
        as the ruling mechanism and survives only inside
        derived_head_depth for v1 heads."""
        if not entries:
            return None
        head = entries[-1]
        if (candidate["cycle_seq"], candidate["payload_hash"]) \
                != (head["new_cycle_seq"], head["new_payload_hash"]):
            return None
        if old_pin is None:
            if head["old_cycle_seq"] is not None \
                    or head["old_payload_hash"] != "":
                return None
        elif (old_pin["cycle_seq"], old_pin["payload_hash"]) \
                != (head["old_cycle_seq"], head["old_payload_hash"]):
            return None
        return head

    @staticmethod
    def check_head(entries, signed, recovery_of=None) -> None:
        """Raise AlreadyConsumedError / HeadRegressionError if
        consuming ``signed`` against ``entries`` (a consumption
        journal snapshot, in append order) would violate the
        head rules; return None if it may proceed. Single-use
        by authorisation_id is checked by the caller /
        append_consumption, not here — this is the target and
        old-pin rules only:

        * candidate behind the head seq -> head regression;
          candidate AT the head seq with the head's hash ->
          already consumed (the movement is consumed, even
          under a fresh authorisation_id); at the head seq
          with a different hash -> head regression (fork);
          ahead -> passes.
        * old pin (when present): behind the head seq ->
          head regression, EXCEPT the supersede case below;
          at the head seq requires the head's hash, else
          head regression; ahead of the head -> passes
          (advance_pin movements the verifier never saw are
          legitimate). No old pin -> no old-pin check.
        * supersede (cycle 23 fix seat; narrowed in the fix
          round, r1-F2 / r2-F3): the exception's EXACT scope
          is — the candidate is STRICTLY AHEAD of the head
          (cand_seq > head_seq), the old pin is BEHIND the
          head (old_seq < head_seq), the recovery exception
          above does NOT fire for this envelope, the
          envelope's reason is NOT burned_unadopted (a
          burned_unadopted envelope that does not validly
          match the head burn NEVER rides supersede and is
          never reclassified as a primary: candidate ahead
          -> HeadRegressionError, candidate at the head
          target -> AlreadyConsumedError, behind -> head
          regression), and, when the old pin's seq is
          recorded in the journal (as some entry's
          new_cycle_seq, bound to that entry's
          new_payload_hash, or as an entry's old_cycle_seq,
          bound to its old_payload_hash), the old pin's hash
          must equal the recorded hash for that seq, else
          HeadRegressionError. Within that scope a fresh
          primary may pass the behind-head old pin: the
          burned head movement is superseded — abandoned,
          never adopted; its burn remains a permanent journal
          fact. This closes the adopter-level deadlock where
          a movement consumed to its recovery cap with its
          adoption pair discarded left the pin behind the
          consumed head forever (every later primary refused
          here, and advance_pin cannot cross the gap).
          Justification: the envelope is fresh and
          single-use, and the pin can only move FORWARD to
          the ahead candidate (PinStore CAS + non-regression),
          so no regression or replay is enabled; the head
          becoming behind the pin is already a tolerated
          state (advance_pin movements do it). Candidate
          at/behind the head with a behind-head old pin still
          refuses, and an old pin AT the head seq with a
          different hash still refuses (fork of the head
          target) at any candidate position.
          Two named residuals of this rule: (i) an old-pin
          seq NOT recorded in the journal cannot be
          hash-checked by the verifier — the verifier cannot
          observe the pin, so a behind-head old pin at an
          unrecorded seq is unchecked at this layer;
          adoption-side context binding (PinStore.adopt binds
          the ceremony record to the store's actual pin) is
          the control for that case. (ii) A resurfaced
          superseded pair adopted later can stall one
          sequence at AlreadyConsumedError before
          self-healing via the next supersede (r2-F4): the
          superseded movement's retained pair remains
          adoptable against a pin that still equals its old
          pin, moving the pin to a genuine ceremonied target
          behind the head; the head's own movement then
          cannot re-consume (its candidate equals the head
          target), and liveness resumes at the next sequence
          via supersede again. No regression and no replay
          in either residual.
        * initial_anchor against a non-empty journal ->
          head regression (a first-ever anchor claim after
          recorded consumptions is a contradiction).
        * burned_unadopted recovery is BOUNDED, not one-shot
          (cycle 23, R3 / Addendum 3, pending): the scoped
          exception below applies only when the lineage derived
          by _derive_lineage is a recovery — the issuance-bound
          recovery_of (threaded in by the caller; None = the
          legacy direct-caller sentinel) equals the CURRENT
          head entry's authorisation_id, candidate + old pin
          exactly equal the head's target/old, and the head's
          derived depth is < MAX_RECOVERY_DEPTH. A bound burn
          that is no longer head (the race loser) and a bound
          burn at head whose depth has reached the cap both
          raise AlreadyConsumedError here (candidate == head
          target, not a recovery). recovery_of is the issuance
          entry's recovery_of, read by the consume mode from
          the CeremonyAuthorisationLedger — never from the
          request."""
        if not entries:
            if signed.reason == "burned_unadopted":
                # No head burn exists to recover (fix round,
                # r1-F2): a recovery envelope against an empty
                # journal is never reclassified as a primary.
                raise HeadRegressionError(
                    "burned_unadopted against an empty "
                    "consumption journal (no head burn)")
            return
        last = entries[-1]
        head_seq = last["new_cycle_seq"]
        head_hash = last["new_payload_hash"]
        recovery = CeremonyConsumptionLedger._derive_lineage(
            entries, signed, recovery_of)[0] == "recovery"
        if signed.reason == "initial_anchor":
            raise HeadRegressionError(
                "initial_anchor against a non-empty consumption "
                "journal")
        cand_seq = signed.candidate["cycle_seq"]
        cand_hash = signed.candidate["payload_hash"]
        if cand_seq < head_seq:
            raise HeadRegressionError(
                "candidate is behind the consumed head")
        if cand_seq == head_seq:
            if cand_hash == head_hash:
                if not recovery:
                    raise AlreadyConsumedError(
                        "candidate target already consumed: "
                        f"{cand_seq}")
            else:
                raise HeadRegressionError(
                    "candidate forks the consumed head at its "
                    "sequence")
        if signed.reason == "burned_unadopted" and not recovery:
            # Fix round (r1-F2): supersede NEVER applies to a
            # burned_unadopted envelope. Candidate at/behind
            # the head has already refused above (already
            # consumed / fork / regression); the ahead position
            # refuses here rather than landing as a primary.
            if cand_seq > head_seq:
                raise HeadRegressionError(
                    "burned_unadopted envelope does not match "
                    "the head burn and its candidate is ahead "
                    "of the consumed head (supersede does not "
                    "apply to recovery envelopes)")
        if not recovery and signed.old_pin is not None:
            old_seq = signed.old_pin["cycle_seq"]
            old_hash = signed.old_pin["payload_hash"]
            if old_seq < head_seq:
                # Supersede: a fresh primary whose candidate
                # is strictly ahead of the head may pass a
                # behind-head old pin — the burned head
                # movement is abandoned, never adopted (see
                # the docstring). Any other candidate position
                # (at/behind the head) still refuses.
                if cand_seq <= head_seq:
                    raise HeadRegressionError(
                        "old pin is behind the consumed head")
                # Hash binding (fix round, r1-F2): when the
                # old pin's seq is recorded in the journal —
                # as an entry's new_cycle_seq (bound to its
                # new_payload_hash) or as an entry's
                # old_cycle_seq (bound to its
                # old_payload_hash) — the claimed old hash
                # must equal a recorded hash for that seq; a
                # fabricated old-pin hash at a journal-known
                # seq refuses. A seq recorded nowhere cannot
                # be checked here (named residual (i)).
                recorded = set()
                for entry in entries:
                    if entry["new_cycle_seq"] == old_seq:
                        recorded.add(entry["new_payload_hash"])
                    if entry["old_cycle_seq"] == old_seq:
                        recorded.add(entry["old_payload_hash"])
                if recorded and old_hash not in recorded:
                    raise HeadRegressionError(
                        "old pin hash does not match the "
                        "journal-recorded hash for its sequence "
                        "(supersede hash binding)")
            if old_seq == head_seq and old_hash != head_hash:
                raise HeadRegressionError(
                    "old pin forks the consumed head at its "
                    "sequence")

    # -- the commit point --------------------------------------------

    def append_consumption(self, envelope, *, recorded_at,
                           recovery_of=None) -> dict:
        """Consume one ceremony authorisation. THE commit
        point for consumption: before this append lands
        nothing is consumed; after it lands the
        authorisation_id is spent whether or not anything
        else succeeds. New appends are always schema v2.

        Re-checks, against freshly reloaded entries on every
        attempt of the bounded reload-retry loop (the
        composition the issuance ledger uses): single-use by
        authorisation_id (AlreadyConsumedError) and the R3
        head rules (HeadRegressionError, or
        AlreadyConsumedError for the same-target case). The
        v2 lineage (consumption_kind / recovery_of /
        recovery_depth) is derived INSIDE that loop, from the
        freshly reloaded entries on the same attempt, via
        _derive_lineage — never from a stale snapshot — so a
        race loser's bound burn is no longer head when its
        lineage is derived and it refuses as
        AlreadyConsumedError, while exactly one racer lands.
        recovery_of is the issuance entry's recovery_of
        threaded in by the consume mode (None = legacy
        direct-caller sentinel, see _derive_lineage). A
        CorruptLedgerError from _save's freshness check means
        a competitor landed between reload and save: reload,
        re-check, retry — so the concurrent loser surfaces as
        already-consumed, not corruption.

        Scope note: the duplicate check here is
        consumption-journal-only by design — this journal is
        the authority. The signing-ledger mirror cross-check
        (a rolled-back journal whose consumption survives in
        the anchored mirror) is a mode-level responsibility,
        performed by trust/verifier_main's ceremony_consume
        mode before it calls this method; direct callers of
        this method do not get that cross-check."""
        from signing.ceremony_authorisation import \
            SignedCeremonyAuthorisation
        if not isinstance(envelope, SignedCeremonyAuthorisation):
            raise LedgerError(
                "can only consume a SignedCeremonyAuthorisation")
        last_error = None
        for _attempt in range(_APPEND_RETRY_ATTEMPTS):
            self._reload()
            if any(e["authorisation_id"] == envelope.authorisation_id
                   for e in self._entries):
                raise AlreadyConsumedError(
                    "authorisation already consumed: "
                    f"{envelope.authorisation_id}")
            self.check_head(self._entries, envelope,
                            recovery_of=recovery_of)
            kind, rec_of, depth = \
                CeremonyConsumptionLedger._derive_lineage(
                    self._entries, envelope, recovery_of)
            if kind not in ("primary", "recovery"):
                # Defensive (cycle 23 re-review, r6-N1):
                # _derive_lineage's "unrecoverable" marker for a
                # non-matching burned_unadopted envelope must
                # never be written — check_head has already
                # raised for it, and a journal containing the
                # marker would fail its own load forever. This
                # guard keeps the commit point safe even if a
                # future check_head change lets it through.
                raise LedgerError(
                    "derived consumption kind is not writable: "
                    f"{kind}")
            old_pin = envelope.old_pin
            try:
                return self._append(
                    "consume", recorded_at,
                    authorisation_id=envelope.authorisation_id,
                    ceremony_id=envelope.ceremony_id,
                    operator_id=envelope.operator_id,
                    old_cycle_seq=(None if old_pin is None
                                   else old_pin["cycle_seq"]),
                    old_payload_hash=("" if old_pin is None
                                      else old_pin["payload_hash"]),
                    new_cycle_seq=envelope.candidate["cycle_seq"],
                    new_payload_hash=envelope.candidate["payload_hash"],
                    evidence_hash=envelope.evidence_hash,
                    consumed_at=recorded_at,
                    consumption_kind=kind,
                    recovery_of=rec_of,
                    recovery_depth=depth)
            except CorruptLedgerError as exc:
                last_error = exc
        raise last_error
