"""The first production adopter of ``reanchor_pin`` (cycle 22,
workstream 3; design C §3, DESIGN-FINAL R3).

``PinAdopter`` owns the loop/storage layer's snapshot pin: it
captures the pin + complete ceremony history fresh from a
``signing.pin_store.PinStore`` on every attempt, snapshots the
loop's state + calibration bytes as one consistent pair, and
either advances the pin (the dense, normal path) or runs the
pin ceremony (the exceptional path) and adopts the returned
pin + record atomically through the store. It never writes the
pin store except through ``PinStore.adopt``, never touches the
loop's state or calibration files (it reads bytes and attests
them; state mutation stays the loop's), and never retries a
consume, an authorise or an adopt automatically.

Supersession (cycle 25, external review Q1; design:
the cycle-25 design-approval record): when a consume is
refused pre-commit with ``ceremony_supersede_required``, the
adopter STOPS. It does not request a supersession decision and
does not re-run the consume. It persists a
``supersession_pending_approval`` line in its pending journal
(a detection aid, like every phase there), writes a
pending-supersession report (design §7) beside the pin, and
raises :class:`PinSupersessionPendingApproval` carrying the
binding facts. The only independent supersession approval is
a signed approval artefact minted out-of-band by a separate
tool (``trust.supersession_approval_tool``) under a dedicated
approver key — a third Ed25519 key, distinct from the snapshot
signing key and the verifier's ceremony seed. This module
never imports that tool, never sees the approver seed path,
and contains no route to mint an approval. Independence here
is at the authorisation-event level: supersession requires a
separately invoked, cryptographically independent approval
operation — a standalone tool invocation, with its own
inputs, producing its own signed artefact under its own
dedicated key — outside the adopter's automated recovery
path. The mechanism does not establish that the invocation
was performed by a human, nor that no other unattended
automation invoked the tool. It is NOT a claim of a separate
human or a separate OS user: on this same-user deployment the
operator and the approver are the same person running a
second command; the guarantee is that supersession cannot
happen as a side effect of this automated flow.

Resume (design §6): the refused envelope is retained on the
pending journal's authorised line. A later attempt for the
same movement scans the approval inbox (``PinAdopterConfig
.supersession_approval_path``, env
``AION_PIN_SUPERSESSION_APPROVAL_PATH`` — an adopter-side
setting, never a verifier variable) for an approval whose
``replacement.authorisation_id`` equals the retained
envelope's id; with none, it raises pending again WITHOUT a
new ceremony, so the retained envelope stays the approvable
one. With one, it presents the approval once (the file is
moved aside regardless of outcome), obtains the verifier's
journaled supersession decision — the verifier verifies the
approval BEFORE issuing — and re-runs the consume of the SAME
envelope exactly once.

Single-file inbox asymmetry: the move-aside above is a
DIRECTORY-mode property. When the inbox is configured as a
single artefact file (``move_aside=False``), the approval is
NOT moved aside on any outcome — it remains in place and may
be re-presented by a later attempt — and the presented-once
property rests entirely on the verifier's single-use rule
(a second decision against the same approval refuses at the
verifier). Safety holds in both modes; only the local
housekeeping differs.

Decision-may-already-exist (consume-first): a journaled
decision can outlive its response — the verifier commits the
decision before its signing-ledger mirror, so a mirror
failure returns ``ledger_failed`` WITH the decision standing,
and a process can die after the decision lands but before
the consume. Resume therefore treats "a decision may already
exist" as a consume-first state: when the pending entry
already carries a ``supersede_decided`` phase, or a decision
request in this attempt refuses with
``ceremony_supersede_unproven`` (a prior decision exists) or
``ledger_failed`` after an approval was presented, the
adopter falls through to exactly ONE re-anchor/consume
attempt of the retained envelope instead of classifying the
movement burned or re-pending it unattempted. What that
consume's refusal means depends on whether a decision
covers the CURRENT head (cycle 25 fix round 2, F2/F3 —
this corrects the earlier claim that a stale decision
yields a supersede-required refusal): NO covering decision
refuses ``ceremony_supersede_required``; a decision that
WAS journaled for this envelope but was minted against a
head that has since moved is inert, and its consume refuses
``ceremony_head_regression`` instead. Both are PRE-COMMIT
refusals — the envelope is certified unconsumed — so
neither is terminal while an approval path remains: a
consume-first attempt falls through to the approval-lookup
path in the SAME attempt, and a consume attempted after a
decision presentation returns the movement to pending
rather than burned. A ``ceremony_already_consumed``
refusal from a resume consume is the opposite certificate:
the consumption COMMITTED verifier-side (its response was
lost on an earlier attempt), so the adopter appends the
``consumed`` phase to its pending journal before raising
burned — the ceremony is then a genuine unadopted burn and
the standard ``burned_unadopted`` recovery engages on
later attempts.

Reason selection (DESIGN-FINAL R3): the ceremony reason is
COMPUTED, never hard-coded per call site. When the
pending-adoption journal shows an unadopted burn for the SAME
candidate (same seq + hash) and the same old pin, the recovery
ceremony uses ``burned_unadopted`` (with-pin: the strict
``("chain_gap",)`` reasons are passed; no-pin: ``None``);
otherwise the honest primary reason (``chain_gap_recovery`` /
``initial_anchor``). ``lost_pin`` is never selected for an
unmoved pin. Because a recovery candidate must be the burned
candidate itself (same seq + hash — the verifier's
``match_head_burn`` binds exactly that), the pending journal's
``authorised`` line retains the candidate snapshot envelope so
a later attempt can re-present the identical candidate instead
of re-signing a same-sequence snapshot with a different hash
(which the consumption head would refuse as a fork). The
retained envelope is a detection aid only: it is fully
re-verified against the current state/calibration bytes on
every attempt, exactly like a freshly signed candidate.

The ``already_current`` outcome is reachable only within
the retained envelope's TTL: it depends on re-presenting
the retained candidate envelope, and once that envelope
has expired a repeat attempt on unchanged state fails
closed (an integrity refusal) rather than reporting
``already_current``.

No ``now=`` parameter anywhere in this flow: freshness stays
on the host clock (the ``commit_production`` precedent).

History reconciliation (cycle 28): when the adopter is built
with a ``consumption_entries_provider`` (an explicit
composition seam — this module never reads the verifier's
journals itself, and ``build_pin_adopter`` never derives the
providers from its environment), every attempt reconciles the
captured store history against the verifier's consumption
journal before anything is persisted or consumed, relevant to
the candidate (trust/history_reconciliation.py). A store
history silently thinned by a restoration now refuses with
the deterministic code ``pin_store_history_incomplete``
instead of laundering the gap into continuity. The production
composition (trust/runner.py) supplies both providers from
the verifier home it legitimately holds, so detection is on
there; without a provider the adopter behaves exactly as
before this cycle and makes no history-completeness claim.
Two wiring notes: a consumption provider WITHOUT a
supersession provider loses the decision-based excuse and
must rely on the known-unadopted head excuse (fail-closed
direction, but composition should supply both); and
``adopt_returned`` — which adopts a pair whose consumption
already committed in an originating ``snapshot_and_adopt``
attempt — does not re-run reconciliation, on the basis that
the originating attempt (when wired) was reconciled at its
start and the pair it adopts is that ceremony's own record.

Honest scope: production code exercised end-to-end in temp
dirs against the real verifier subprocess, and, since cycle 23,
in a live run against a byte copy of the real state/ directory
(seq 13 → 16, two consumptions) in a sandbox under a
production-mode verifier home. The real state/ directory itself
has never been adopted against and is not advanced by any of
this; there is no production deployment (no separate OS user;
the wrapper launch is refused by design).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from signing.ceremony_authorisation import (
    CeremonyPublicKey,
    ceremony_authorisation_envelope_from_dict,
)
from signing.gate_decision import SigningError, load_signing_key
from signing.pin_ceremony import (
    PinCeremonyRecord,
    advance_pin,
    classify_verification,
    reanchor_pin,
)
from signing.pin_store import PinStore, PinStoreError
from signing.state_snapshot import (
    parse_state_bytes,
    sign_state_snapshot,
    snapshot_envelope_from_dict,
    snapshot_envelope_to_dict,
    verify_signed_snapshot,
    verify_snapshot_for_state,
)
from trust.client import (
    CeremonyAlreadyConsumed,
    CeremonyHeadRegression,
    CeremonySupersedeRequired,
)
from trust.history_reconciliation import (
    HistoryReconciliationRefused,
    reconcile_history,
)
from trust.supersession_approval import (
    supersession_approval_from_json,
    supersession_approval_to_dict,
)
from trust.wiring import production_client

REASON_INITIAL_ANCHOR = "initial_anchor"
REASON_CHAIN_GAP_RECOVERY = "chain_gap_recovery"
REASON_BURNED_UNADOPTED = "burned_unadopted"

PENDING_JOURNAL_FILENAME = "adoption-pending.jsonl"
PENDING_REPORT_FILENAME = "pending-supersession.json"

_PIN_ENV_VARS = (
    "AION_PIN_DIR", "AION_PIN_SIGNING_KEY_PATH", "AION_PIN_SIGNER_ID",
    "AION_PIN_OPERATOR_ID", "AION_PIN_EVIDENCE_DIR",
)
_PIN_PATH_VARS = (
    "AION_PIN_DIR", "AION_PIN_SIGNING_KEY_PATH", "AION_PIN_EVIDENCE_DIR",
)


@dataclass(frozen=True)
class PinAdopterConfig:
    state_path: Path            # <state_dir>/state.json
    calibration_path: Path      # <state_dir>/calibration/calibration.json
    pin_dir: Path               # outside state_dir (enforced by PinStore)
    snapshot_signer_id: str     # signer_id for sign_state_snapshot
    expected_snapshot_signer_id: str  # pin for verify (== snapshot_signer_id
    # in this deployment; kept separate because verify-side pinning is
    # the wrapper's contract)
    operator_id: str            # presented to ceremony_authorise
    expected_verifier_signer_id: str  # envelope signer pin
    evidence_dir: Path          # == verifier's AION_CEREMONY_EVIDENCE_DIR
    # Cycle 25: the approval INBOX (design §6) — a directory
    # of <approval_id>.json artefacts minted out-of-band by
    # the approval tool (a single artefact file is also
    # accepted). An adopter-side setting only: never a
    # verifier variable, and it must never carry the approver
    # seed path. None = no inbox configured: a
    # supersede-required refusal can then only ever surface
    # as pending.
    supersession_approval_path: Path | None = None


@dataclass(frozen=True)
class PinAdopterEnv:
    """The adopter-specific env values (``pin_adopter_config_from_env``)."""
    pin_dir: Path
    signing_key_path: Path
    snapshot_signer_id: str
    operator_id: str
    evidence_dir: Path
    # Cycle 25: optional AION_PIN_SUPERSESSION_APPROVAL_PATH.
    supersession_approval_path: Path | None = None


@dataclass(frozen=True)
class AdoptionResult:
    outcome: str            # "advanced" | "reanchored" | "already_current"
    pin: dict               # the pin now in force
    record: PinCeremonyRecord | None   # set iff outcome == "reanchored"


class PinAdoptionRefused(SigningError):
    """Integrity failure / store refusal: nothing persisted."""


class PinSupersessionPendingApproval(SigningError):
    """Cycle 25: a consume was refused pre-commit with
    ``ceremony_supersede_required`` — supersession pending
    independent approval — and no approval artefact for the
    retained envelope was found in the approval inbox (or the
    configured client cannot present one). The envelope is
    provably UNCONSUMED; nothing was decided, nothing was
    re-run, and no supersession decision was requested. This
    is a STOP, not a failure of the movement: an approver
    approves out-of-band with the approval tool against the
    pending-supersession report, the artefact lands in the
    inbox, and a later adoption attempt presents it, obtains
    the verifier's journaled supersession decision, and
    completes the consume of the same envelope.

    Carries the binding facts an approver needs:

    * ``authorisation_id`` / ``ceremony_id`` / ``operator_id``
      / ``reason`` — the original failed consumption attempt
      (the retained envelope's identity);
    * ``candidate_seq`` / ``candidate_hash`` — the replacement
      candidate that would land;
    * ``old_cycle_seq`` / ``old_payload_hash`` — the old side
      of the exact movement (envelope old pin; ``None``/``""``
      for a genesis-side movement);
    * ``abandoned_movement_candidates`` — the unadopted burns
      the adopter's own pending journal knows, as
      ``{authorisation_id, old_cycle_seq, old_payload_hash,
      candidate_seq, candidate_hash}`` dicts: the abandoned
      head movement is among them when the adopter made the
      burns. The VERIFIER identifies the abandoned movement
      authoritatively from its own consumption head at
      decision time; this tuple is the adopter-side aid, not
      the authority;
    * ``envelope_dict`` — the exact envelope whose consumption
      was refused (retained for the resume attempt);
    * ``report_path`` / ``report_written`` — the
      pending-supersession report file (design §7), the
      approval tool's input;
    * ``approval_path`` — the inbox that was scanned
      (``None`` when no inbox is configured);
    * ``journal_persisted`` — whether the
      ``supersession_pending_approval`` journal line landed.
    """

    def __init__(self, message, *, ceremony_id, authorisation_id,
                 operator_id, reason, candidate_seq, candidate_hash,
                 old_cycle_seq, old_payload_hash,
                 abandoned_movement_candidates=(), envelope_dict=None,
                 approval_path=None, journal_persisted=False,
                 report_path=None, report_written=False):
        super().__init__(message)
        self.ceremony_id = ceremony_id
        self.authorisation_id = authorisation_id
        self.operator_id = operator_id
        self.reason = reason
        self.candidate_seq = candidate_seq
        self.candidate_hash = candidate_hash
        self.old_cycle_seq = old_cycle_seq
        self.old_payload_hash = old_payload_hash
        self.abandoned_movement_candidates = tuple(
            abandoned_movement_candidates)
        self.envelope_dict = envelope_dict
        self.approval_path = approval_path
        self.journal_persisted = journal_persisted
        self.report_path = report_path
        self.report_written = report_written
        self.cycle_entry = None

    @property
    def movement(self) -> dict:
        """The exact (old, new) movement this supersession
        would perform, as plain data for an approver."""
        return {
            "old": {"cycle_seq": self.old_cycle_seq,
                    "payload_hash": self.old_payload_hash},
            "new": {"cycle_seq": self.candidate_seq,
                    "payload_hash": self.candidate_hash}}


# Backwards-compatible alias (the cycle-25 design §9 name is
# the …PendingApproval form; early cycle-25 drafts used the
# shorter name).
PinSupersessionPending = PinSupersessionPendingApproval


def _request_supersession_decision(client, *, operator_id,
                                   envelope_dict, approval):
    """Present an independent supersession approval artefact
    and obtain the verifier's journaled supersession decision.

    The approval dict is passed as the third argument of
    ``ceremony_supersede`` (cycle 25 client contract:
    ``ceremony_supersede(operator_id, envelope_dict,
    supersede_approval)`` — the verifier verifies the artefact
    BEFORE issuing any decision). This helper is called ONLY
    from the resume path, when the adopter already holds an
    inbox approval for the retained envelope — never in
    response to a refusal. A client that does not accept an
    approval argument raises TypeError here; the caller treats
    that as "approval cannot be presented" and stays pending —
    the adopter NEVER falls back to requesting a decision
    without an approval."""
    return client.ceremony_supersede(
        operator_id, envelope_dict, approval)


class PinAdoptionBurned(SigningError):
    """Consume committed (or may have committed), adoption did
    not complete. The pair ``reanchor_pin`` returned — if it
    returned — is attached, so the caller can adopt it via
    ``adopt_returned`` without a new ceremony. On a
    ``PinMovedError`` the pair is still attached, but retrying
    its adoption will keep failing CAS until an operator
    reconciles: the burn is real, and the movement belongs to
    whoever moved the pin first."""

    def __init__(self, message, *, returned_pin=None, returned_record=None):
        super().__init__(message)
        self.returned_pin = returned_pin
        self.returned_record = returned_record
        self.cycle_entry = None


def _env_refusal(variable: str, problem: str):
    raise SigningError(f"{variable}: {problem}")


def pin_adopter_config_from_env(mapping) -> PinAdopterEnv:
    """Read the adopter-specific ``AION_PIN_*`` variables from a
    mapping, in the wiring idiom: validate a copy; refusals name
    the variable and never carry its value. These are ADOPTER
    variables, deliberately NOT part of wiring's verifier
    allowlist — the verifier must never see them."""
    if not hasattr(mapping, "get"):
        raise SigningError("pin adopter env: must be a mapping")
    env = dict(mapping)
    for name in _PIN_ENV_VARS:
        value = env.get(name)
        if not isinstance(value, str) or not value.strip():
            _env_refusal(
                name, "required for the pin adopter and must be "
                "non-empty")
    for name in _PIN_PATH_VARS:
        if not Path(env[name]).is_absolute():
            _env_refusal(name, "must be an absolute path")
    # Cycle 25: the independent supersession approval path is
    # OPTIONAL (its absence means supersessions can only ever
    # surface as pending); when present it must be a non-empty
    # absolute path.
    approval_raw = env.get("AION_PIN_SUPERSESSION_APPROVAL_PATH")
    approval_path = None
    if approval_raw is not None:
        if not isinstance(approval_raw, str) \
                or not approval_raw.strip():
            _env_refusal(
                "AION_PIN_SUPERSESSION_APPROVAL_PATH",
                "when present must be non-empty")
        if not Path(approval_raw).is_absolute():
            _env_refusal(
                "AION_PIN_SUPERSESSION_APPROVAL_PATH",
                "must be an absolute path")
        approval_path = Path(approval_raw)
    return PinAdopterEnv(
        pin_dir=Path(env["AION_PIN_DIR"]),
        signing_key_path=Path(env["AION_PIN_SIGNING_KEY_PATH"]),
        snapshot_signer_id=env["AION_PIN_SIGNER_ID"],
        operator_id=env["AION_PIN_OPERATOR_ID"],
        evidence_dir=Path(env["AION_PIN_EVIDENCE_DIR"]),
        supersession_approval_path=approval_path)


def build_pin_adopter(env, *, expected_signer_id, expected_key_id,
                      authorisation_public_key, signing_key_path,
                      config, consumption_entries_provider=None,
                      supersession_entries_provider=None) -> "PinAdopter":
    """The production factory, in the ``production_client``
    idiom: the verifier client is built ONLY via
    ``trust.wiring.production_client``; the pins are out-of-band
    arguments; the snapshot signing key is loaded outside both
    the state dir and the pin dir.

    Cycle 28: the history-reconciliation providers are optional
    pass-through arguments, supplied by the composition layer
    that legitimately holds the verifier's journals. The
    factory deliberately never derives them from ``env`` (which
    carries AION_VERIFIER_HOME for the client): the adopter
    does not read the verifier's journals itself (the cycle-25
    separation), so an unconfigured factory-built adopter makes
    no history-completeness claim — see
    trust/history_reconciliation.py."""
    if not isinstance(config, PinAdopterConfig):
        raise SigningError("config must be a PinAdopterConfig")
    if config.expected_verifier_signer_id != expected_signer_id:
        raise SigningError(
            "expected_verifier_signer_id: the config's verifier "
            "signer pin does not match the out-of-band "
            "expected_signer_id; refusing rather than pinning to "
            "whatever the config asserts")
    if not isinstance(config.operator_id, str) \
            or not config.operator_id.strip():
        raise SigningError(
            "AION_PIN_OPERATOR_ID: an operator id is required "
            "for the pin adopter and must be non-empty")
    # Evidence-dir mismatch refusal: in the local deployment
    # shape the adopter places evidence where the verifier
    # resolves it; a visible mismatch refuses here rather than
    # failing issuance later with ceremony_evidence_unresolvable.
    verifier_evidence = env.get("AION_CEREMONY_EVIDENCE_DIR") \
        if hasattr(env, "get") else None
    if verifier_evidence:
        if Path(verifier_evidence).resolve() \
                != Path(config.evidence_dir).resolve():
            raise SigningError(
                "AION_PIN_EVIDENCE_DIR: the adopter evidence dir "
                "does not resolve equal to the verifier's "
                "AION_CEREMONY_EVIDENCE_DIR; refusing a mismatch "
                "that would fail issuance later")
    client = production_client(
        env, expected_signer_id=expected_signer_id,
        expected_key_id=expected_key_id,
        authorisation_public_key=authorisation_public_key)
    state_dir = Path(config.state_path).parent
    store = PinStore(config.pin_dir, state_dir=state_dir)
    signing_key = load_signing_key(
        signing_key_path,
        forbidden_roots=(state_dir, Path(config.pin_dir)))
    return PinAdopter(
        client=client, store=store,
        signing_key=signing_key, config=config,
        authorisation_public_key=authorisation_public_key,
        consumption_entries_provider=consumption_entries_provider,
        supersession_entries_provider=supersession_entries_provider)


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    """The loop.save() write discipline, for evidence bundles:
    a half-written artefact must never be the bytes the
    verifier hashes."""
    fd, tmp = tempfile.mkstemp(dir=path.parent,
                               prefix=".pin-evidence-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
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


class PinAdopter:
    """The full production flow. Construct via
    ``build_pin_adopter`` in production; tests may construct it
    around a directly built client (the R12 pattern)."""

    def __init__(self, *, client, store, signing_key, config,
                 authorisation_public_key,
                 consumption_entries_provider=None,
                 supersession_entries_provider=None):
        if not isinstance(config, PinAdopterConfig):
            raise SigningError("config must be a PinAdopterConfig")
        if not isinstance(authorisation_public_key, CeremonyPublicKey):
            raise SigningError(
                "authorisation_public_key must be a "
                "CeremonyPublicKey supplied out-of-band")
        if not isinstance(config.operator_id, str) \
                or not config.operator_id.strip():
            raise SigningError(
                "operator_id: an operator id is required and "
                "must be non-empty")
        # Cycle 28: history-reconciliation providers (see
        # trust/history_reconciliation.py). None (the default,
        # and therefore every pre-cycle-28 construction) means
        # NO reconciliation check: detection is an
        # integrated-system property of the wiring that
        # supplies real providers, exactly as cycle 21 scoped
        # single-use consumption to the verifier-backed
        # consumer. A non-callable provider is a construction
        # refusal, never a silent no-check.
        for provider, name in (
                (consumption_entries_provider,
                 "consumption_entries_provider"),
                (supersession_entries_provider,
                 "supersession_entries_provider")):
            if provider is not None and not callable(provider):
                raise SigningError(
                    f"{name} must be a callable or None")
        self._client = client
        self._store = store
        self._key = signing_key
        self._config = config
        self._pub = authorisation_public_key
        self._consumption_entries_provider = \
            consumption_entries_provider
        self._supersession_entries_provider = \
            supersession_entries_provider

    @property
    def store(self) -> PinStore:
        return self._store

    @property
    def pending_journal_path(self) -> Path:
        return self._store.pin_dir / PENDING_JOURNAL_FILENAME

    # -- pending-adoption journal -----------------------------------------
    # Cheap, non-authoritative, outside the combined pin file:
    # it must survive — and be distinguishable from — an adopt
    # crash, and it is never read as history. It is a detection
    # aid for burned-and-unmoved ceremonies, never evidence a
    # ceremony did NOT happen.

    def _append_journal(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True,
                          allow_nan=False).encode("utf-8") + b"\n"
        with open(self.pending_journal_path, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def _read_journal(self) -> list:
        try:
            raw = self.pending_journal_path.read_bytes()
        except (FileNotFoundError, OSError):
            return []
        entries = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue  # crash-truncated tail: detection aid only
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _journal_ceremonies(self) -> list:
        """Journal lines merged per ceremony_id (later lines
        override, except a field a later line omits — notably
        ``candidate_envelope``, carried only on the
        ``authorised`` line — survives from the earlier line),
        each with its accumulated phase set."""
        by_id = {}
        order = []
        for entry in self._read_journal():
            cid = entry.get("ceremony_id")
            if not isinstance(cid, str):
                continue
            if cid not in by_id:
                by_id[cid] = {"phases": set(), "entry": {}}
                order.append(cid)
            slot = by_id[cid]
            slot["phases"].add(entry.get("phase"))
            for key, value in entry.items():
                if value is not None:
                    slot["entry"][key] = value
        return [by_id[cid] for cid in order]

    def _unadopted_burns(self) -> list:
        """Merged journal ceremonies that reached at least
        ``authorised`` and never reached ``adopted``."""
        return [slot["entry"] for slot in self._journal_ceremonies()
                if "adopted" not in slot["phases"]
                and slot["phases"] & {"authorised", "consumed"}]

    def _genuine_burn_entries(self) -> list:
        """Unadopted burns whose envelope may actually have
        been consumed. Cycle 25: a ceremony that reached
        ``supersession_pending`` and never ``consumed`` is NOT
        a burn — its consume was refused pre-commit and the
        envelope is certified unconsumed, so it must not drive
        ``burned_unadopted`` reason selection or be named as an
        abandoned movement. (Its candidate envelope is still
        retained via ``_unadopted_burns`` for re-presentation:
        retention is a cache, burn classification is a claim.)"""
        return [slot["entry"] for slot in self._journal_ceremonies()
                if "adopted" not in slot["phases"]
                and slot["phases"] & {"authorised", "consumed"}
                and not ("supersession_pending_approval"
                         in slot["phases"]
                         and "consumed" not in slot["phases"])]

    def _retained_current_candidate(self, *, candidate_seq, old_pin):
        """The candidate envelope that IS the current pin (same
        seq + hash), retained on a ceremony's journal lines:
        re-presenting it is what makes a repeat attempt on
        unchanged state classify ``already_current`` instead of
        ``pin_mismatch`` (a fresh signing of the same state has
        a different hash and can never reproduce the pin)."""
        if old_pin is None:
            return None
        for slot in self._journal_ceremonies():
            entry = slot["entry"]
            if entry.get("candidate_seq") != candidate_seq \
                    or entry.get("candidate_hash") \
                    != old_pin["payload_hash"]:
                continue
            envelope = entry.get("candidate_envelope")
            if not isinstance(envelope, dict):
                continue
            try:
                signed = snapshot_envelope_from_dict(envelope)
            except SigningError:
                continue
            if signed.cycle_seq == candidate_seq \
                    and signed.payload_hash == old_pin["payload_hash"]:
                return signed
        return None

    @staticmethod
    def _old_pin_projection(old_pin):
        if old_pin is None:
            return None, ""
        return old_pin["cycle_seq"], old_pin["payload_hash"]

    def _find_unadopted_burn(self, *, candidate_seq, candidate_hash,
                             old_pin):
        old_seq, old_hash = self._old_pin_projection(old_pin)
        for entry in self._genuine_burn_entries():
            if entry.get("candidate_seq") == candidate_seq \
                    and entry.get("candidate_hash") == candidate_hash \
                    and entry.get("old_cycle_seq") == old_seq \
                    and entry.get("old_payload_hash") == old_hash:
                return entry
        return None

    def _retained_candidate(self, *, candidate_seq, old_pin):
        """The identical candidate envelope retained by an
        unadopted burn for this sequence and old pin, if any —
        re-presenting it is the only way a recovery candidate
        can be the burned candidate (same seq + hash)."""
        old_seq, old_hash = self._old_pin_projection(old_pin)
        for entry in self._unadopted_burns():
            if entry.get("candidate_seq") != candidate_seq \
                    or entry.get("old_cycle_seq") != old_seq \
                    or entry.get("old_payload_hash") != old_hash:
                continue
            envelope = entry.get("candidate_envelope")
            if not isinstance(envelope, dict):
                continue
            try:
                signed = snapshot_envelope_from_dict(envelope)
            except SigningError:
                continue
            if signed.cycle_seq == candidate_seq \
                    and signed.payload_hash == entry.get("candidate_hash"):
                return signed
        return None

    # -- supersession pending / approval (cycle 25) -------------------------

    def _known_abandoned_movements(self, *, exclude_authorisation_id):
        """The unadopted burns this adopter's pending journal
        knows (excluding the ceremony currently in flight), as
        plain binding dicts. The abandoned head movement is
        among them when this adopter made the burns; the
        verifier identifies it authoritatively regardless."""
        out = []
        for entry in self._genuine_burn_entries():
            if entry.get("authorisation_id") \
                    == exclude_authorisation_id:
                continue
            out.append({
                "authorisation_id": entry.get("authorisation_id"),
                "old_cycle_seq": entry.get("old_cycle_seq"),
                "old_payload_hash": entry.get("old_payload_hash"),
                "candidate_seq": entry.get("candidate_seq"),
                "candidate_hash": entry.get("candidate_hash")})
        return out

    @property
    def pending_report_path(self) -> Path:
        return self._store.pin_dir / PENDING_REPORT_FILENAME

    def _last_genuine_burn(self, *, exclude_authorisation_id=None):
        burns = [b for b in self._genuine_burn_entries()
                 if b.get("authorisation_id")
                 != exclude_authorisation_id]
        return burns[-1] if burns else None

    def _find_pending_supersession(self, *, candidate_seq,
                                   candidate_hash, old_pin):
        """The retained pending supersession for exactly this
        movement (same candidate seq+hash, same old pin) whose
        envelope a resume attempt must re-present, or None."""
        old_seq, old_hash = self._old_pin_projection(old_pin)
        found = None
        for slot in self._journal_ceremonies():
            if "supersession_pending_approval" not in slot["phases"] \
                    or "adopted" in slot["phases"] \
                    or "consumed" in slot["phases"]:
                continue
            entry = slot["entry"]
            if entry.get("candidate_seq") == candidate_seq \
                    and entry.get("candidate_hash") == candidate_hash \
                    and entry.get("old_cycle_seq") == old_seq \
                    and entry.get("old_payload_hash") == old_hash \
                    and isinstance(entry.get("authorisation_envelope"),
                                   dict):
                found = entry
        return found

    def _find_supersession_approval(self, *,
                                    pending_authorisation_id,
                                    pending_head_entry_hash):
        """Scan the approval inbox (design §6) for the approval
        bound to the retained pending envelope. Returns
        ``(approval_dict, file_path, move_aside)`` or None.

        Candidates are parsed with the verify-side
        ``supersession_approval_from_json``; unparseable files
        are ignored, never fatal. Selection: the approval's
        ``replacement.authorisation_id`` equals the pending
        envelope's id, and — when the pending report's head
        entry hash is a known string — its
        ``failed_attempt.head_entry_hash`` equals it. (The
        adopter's report carries ``entry_hash: null`` when it
        cannot know the verifier journal's hash — see
        ``_stop_at_pending`` — in which case the authorisation
        id binding alone selects, and the VERIFIER's binding
        check remains the authoritative gate.) The adopter
        never creates or edits an artefact; in directory mode
        a presented file is moved aside by the caller. In
        single-file mode (``move_aside=False``) the approval
        is NOT moved aside on any outcome: the presented-once
        property there rests entirely on the verifier's
        single-use rule, not on local housekeeping."""
        path = self._config.supersession_approval_path
        if path is None:
            return None
        path = Path(path)
        try:
            if path.is_dir():
                candidates = sorted(path.glob("*.json"))
                move_aside = True
            elif path.is_file():
                candidates = [path]
                move_aside = False
            else:
                return None
        except OSError:
            return None
        for candidate_path in candidates:
            try:
                signed_approval = supersession_approval_from_json(
                    candidate_path.read_bytes().decode("utf-8"))
            except Exception:
                continue
            if signed_approval.replacement.get("authorisation_id") \
                    != pending_authorisation_id:
                continue
            if isinstance(pending_head_entry_hash, str) \
                    and signed_approval.failed_attempt.get(
                        "head_entry_hash") \
                    != pending_head_entry_hash:
                continue
            return (supersession_approval_to_dict(signed_approval),
                    candidate_path, move_aside)
        return None

    def _stop_at_pending(self, sup, *, journal_base, old_pin, signed,
                         reason):
        """The cycle-25 stop (design §7/§8): persist the
        ``supersession_pending_approval`` detection line, write
        the pending-supersession report, and raise
        :class:`PinSupersessionPendingApproval`. Always raises.

        The report's ``head`` block is the adopter's BELIEF
        about the consumption head, from its own pending
        journal (its last genuine burn). The adopter cannot
        know the verifier journal's ``seq``/``entry_hash`` for
        that entry — it has no access to the verifier's
        journals — so those two fields are written as null:
        the approver completes them from the verifier's
        consumption journal as part of the approver's separate
        approval invocation (the approval tool's signing
        projection refuses nulls, so an uncompleted report
        cannot be approved by
        accident), and the verifier re-derives every bound
        fact from its own journals before issuing, so a wrong
        report yields only a refused approval."""
        old_seq, old_hash = self._old_pin_projection(old_pin)
        known_abandoned = self._known_abandoned_movements(
            exclude_authorisation_id=journal_base["authorisation_id"])
        # The head burn is sought BEFORE this ceremony's
        # pending line is appended, so the in-flight ceremony
        # (authorised, not yet marked pending) must be excluded
        # explicitly — it is the movement seeking supersession,
        # never the abandoned head.
        head_burn = self._last_genuine_burn(
            exclude_authorisation_id=journal_base["authorisation_id"])
        if head_burn is not None:
            head_block = {
                "authorisation_id": head_burn.get("authorisation_id"),
                "ceremony_id": head_burn.get("ceremony_id"),
                "old_cycle_seq": head_burn.get("old_cycle_seq"),
                "old_payload_hash": head_burn.get("old_payload_hash"),
                "new_cycle_seq": head_burn.get("candidate_seq"),
                "new_payload_hash": head_burn.get("candidate_hash"),
                "seq": None, "entry_hash": None}
        else:
            head_block = {
                "authorisation_id": None, "ceremony_id": None,
                "old_cycle_seq": None, "old_payload_hash": None,
                "new_cycle_seq": None, "new_payload_hash": None,
                "seq": None, "entry_hash": None}
        persisted = True
        try:
            self._append_journal({
                **journal_base,
                "phase": "supersession_pending_approval",
                "known_abandoned_authorisation_ids": [
                    b["authorisation_id"] for b in known_abandoned],
                "head_authorisation_id": head_block["authorisation_id"],
                "head_entry_seq": None, "head_entry_hash": None})
        except OSError:
            # The journal is a detection aid, never authority;
            # the pending outcome itself is the report and must
            # not be masked by the aid's failure. The outcome
            # carries journal_persisted=False so the loss is
            # visible, not silent.
            persisted = False
        refusal_code = getattr(
            sup, "verifier_code", None) \
            or "ceremony_supersede_required"
        report = {
            "report": "pending-supersession/1",
            "refusal_code": refusal_code,
            "envelope": sup.envelope_dict,
            "operator_id": self._config.operator_id,
            "head": head_block,
            "reported_at": datetime.now(timezone.utc).isoformat()}
        report_written = True
        try:
            _write_bytes_atomically(
                self.pending_report_path,
                json.dumps(report, ensure_ascii=False, sort_keys=True,
                           allow_nan=False).encode("utf-8"))
        except OSError:
            report_written = False
        approval_path = self._config.supersession_approval_path
        raise PinSupersessionPendingApproval(
            "ceremony consumption is supersession pending "
            "independent approval: the verifier refused "
            f"pre-commit with {refusal_code}; the "
            "adopter stopped without requesting a supersession "
            "decision or re-running the consume, and the "
            "movement completes only when an out-of-band "
            "approval artefact for the retained envelope "
            "appears in the approval inbox",
            ceremony_id=journal_base["ceremony_id"],
            authorisation_id=journal_base["authorisation_id"],
            operator_id=self._config.operator_id, reason=reason,
            candidate_seq=signed.cycle_seq,
            candidate_hash=signed.payload_hash,
            old_cycle_seq=old_seq, old_payload_hash=old_hash,
            abandoned_movement_candidates=known_abandoned,
            envelope_dict=sup.envelope_dict,
            approval_path=str(approval_path)
            if approval_path is not None else None,
            journal_persisted=persisted,
            report_path=str(self.pending_report_path),
            report_written=report_written)

    # -- last-candidate retention (advance path) ---------------------------
    # A ceremony leaves its candidate envelope on the journal's
    # authorised line; an advance leaves no journal trace, so
    # the advance path retains its candidate in a small side
    # file. Either way the retained envelope is re-verified in
    # full on every attempt — retention is a cache of a signed
    # artefact, never an authority.

    @property
    def _last_candidate_path(self) -> Path:
        return self._store.pin_dir / "snapshot-candidate.json"

    def _retain_candidate(self, signed) -> None:
        payload = json.dumps(
            {"candidate_envelope": snapshot_envelope_to_dict(signed)},
            ensure_ascii=False, sort_keys=True,
            allow_nan=False).encode("utf-8")
        _write_bytes_atomically(self._last_candidate_path, payload)

    def _read_retained_candidate(self):
        try:
            doc = json.loads(
                self._last_candidate_path.read_bytes().decode("utf-8"))
            return snapshot_envelope_from_dict(doc["candidate_envelope"])
        except Exception:
            return None

    # -- capture ------------------------------------------------------------

    def _read_consistent_pair(self):
        """Read state bytes, read calibration bytes, re-read
        state bytes, refuse if the two state reads differ — the
        ``sign_state_files`` protocol, inlined because
        ``sign_state_files`` returns the snapshot, not the bytes
        ``reanchor_pin`` needs. (Design C §3.3 flags this ~6-line
        duplication as a drift risk with a named follow-up.)"""
        state_path = Path(self._config.state_path)
        calibration_path = Path(self._config.calibration_path)
        try:
            state_first = state_path.read_bytes()
            calibration = calibration_path.read_bytes()
            state_second = state_path.read_bytes()
        except OSError as exc:
            raise PinAdoptionRefused(
                f"state/calibration bytes are unreadable: {exc}") from exc
        if state_first != state_second:
            raise PinAdoptionRefused(
                "state file changed during snapshot capture; "
                "refusing to attest a pair that may never have "
                "coexisted")
        return state_second, calibration

    # -- history reconciliation (cycle 28) --------------------------------
    # Detection of pin-store history incompleteness against the
    # verifier's consumption journal (the follow-up
    # pin-store-history-reconciliation). The providers are
    # composition seams: this adopter never reads the verifier's
    # journals itself.

    def _known_unadopted_authorisation_ids(self):
        """Authorisation ids this adopter's own pending journal
        proves were consumed but never adopted (genuine burns,
        including supersession-pending movements' underlying
        burns as classified by ``_genuine_burn_entries``). These
        — and only these — may excuse the consumption journal's
        head entry in reconciliation, and only for a candidate
        at that head entry's own sequence (fix round, seat-gpt
        FIX 0.91: the beyond-head reach is removed, because an
        adopted ceremony whose "adopted" line above was lost
        is indistinguishable from a genuine burn here): a
        consumed-but-unadopted head is the recovery /
        supersession flows' input, not missing history."""
        return tuple(
            entry["authorisation_id"]
            for entry in self._genuine_burn_entries()
            if isinstance(entry.get("authorisation_id"), str)
            and entry["authorisation_id"])

    def _reconcile_history(self, history, signed, *, old_pin):
        """Step (3b): reconcile the captured store history
        against the consumption journal, relevant to the
        candidate ``signed``. No provider configured: no check
        (the pre-cycle-28 behaviour, claimed as nothing more).
        A provider that raises or returns malformed entries
        fails CLOSED as PinAdoptionRefused — never a silent
        fall-back to no-check behaviour.
        HistoryReconciliationRefused propagates unwrapped so
        its deterministic code survives."""
        if self._consumption_entries_provider is None:
            return
        try:
            consumption_entries = self._consumption_entries_provider()
            supersession_entries = (
                self._supersession_entries_provider()
                if self._supersession_entries_provider is not None
                else ())
        except HistoryReconciliationRefused:
            raise
        except Exception as exc:
            raise PinAdoptionRefused(
                "history reconciliation inputs are unreadable: "
                f"{exc}") from exc
        try:
            reconcile_history(
                history, consumption_entries, supersession_entries,
                candidate_seq=signed.cycle_seq,
                candidate_hash=signed.payload_hash,
                known_unadopted_authorisation_ids=(
                    self._known_unadopted_authorisation_ids()),
                genesis_baseline=old_pin is None)
        except HistoryReconciliationRefused:
            raise
        except SigningError as exc:
            raise PinAdoptionRefused(
                "history reconciliation inputs are malformed: "
                f"{exc}") from exc

    # -- the flow -------------------------------------------------------------

    def snapshot_and_adopt(self) -> AdoptionResult:
        """One attempt, no internal retries of any verifier
        call. See design C §3.3 for the step-by-step contract."""
        cfg = self._config
        # (1) Capture (FRESH-PIN + COMPLETE-HISTORY): one parse,
        # verified, at the start of THIS attempt.
        try:
            old_pin, history = self._store.read_all(signing_key=self._key)
        except PinStoreError as exc:
            raise PinAdoptionRefused(
                f"pin store refuses the capture: {exc}") from exc
        # (2) Consistent byte pair.
        state_bytes, calibration_bytes = self._read_consistent_pair()
        try:
            facts = parse_state_bytes(state_bytes)
        except SigningError as exc:
            raise PinAdoptionRefused(
                f"state bytes fail strict parsing: {exc}") from exc
        # (3) The candidate: re-present a retained burned
        # candidate identically when one exists for this state
        # sequence and old pin; otherwise sign fresh. For a gap
        # candidate the prev link is "" — the immediate
        # predecessor is unobserved, and writing the pin's hash
        # there would fabricate a chain link the snapshot does
        # not have.
        signed = self._retained_current_candidate(
            candidate_seq=facts.cycle_seq, old_pin=old_pin)
        if signed is None and old_pin is not None \
                and facts.cycle_seq == old_pin["cycle_seq"]:
            retained = self._read_retained_candidate()
            if retained is not None \
                    and retained.cycle_seq == facts.cycle_seq \
                    and retained.payload_hash == old_pin["payload_hash"]:
                signed = retained
        if signed is None:
            signed = self._retained_candidate(
                candidate_seq=facts.cycle_seq, old_pin=old_pin)
        if signed is None:
            prev = ""
            if old_pin is not None \
                    and facts.cycle_seq == old_pin["cycle_seq"] + 1:
                prev = old_pin["payload_hash"]
            try:
                signed = sign_state_snapshot(
                    state_bytes, signing_key=self._key,
                    signer_id=cfg.snapshot_signer_id,
                    calibration_bytes=calibration_bytes,
                    prev_snapshot_hash=prev)
            except SigningError as exc:
                raise PinAdoptionRefused(
                    f"candidate signing refused: {exc}") from exc
        # (3b) History reconciliation (cycle 28): the candidate
        # now exists, and nothing has been persisted, authorised
        # or consumed yet in this attempt, so a refusal here is
        # as clean as the integrity-failure branch below. This
        # is the one point every outcome (advanced /
        # already_current / reanchored / genesis) passes
        # through.
        self._reconcile_history(history, signed, old_pin=old_pin)
        # (4) Classify.
        if old_pin is None:
            reasons = verify_signed_snapshot(
                signed, signing_key=self._key,
                expected_state_bytes=state_bytes,
                expected_calibration_bytes=calibration_bytes,
                require_calibration=True,
                expected_signer_id=cfg.expected_snapshot_signer_id)
            if reasons != ():
                raise PinAdoptionRefused(
                    "genesis candidate fails the bare attestation "
                    f"check: {list(reasons)}")
            return self._reanchor(
                old_pin=None, history=history, signed=signed,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                primary_reason=REASON_INITIAL_ANCHOR,
                strict_reasons=None)
        reasons = verify_snapshot_for_state(
            signed, signing_key=self._key, state_bytes=state_bytes,
            calibration_bytes=calibration_bytes, expected_pin=old_pin,
            expected_signer_id=cfg.expected_snapshot_signer_id)
        cls = classify_verification(reasons)
        # (5) Branch.
        if cls == "ok":
            try:
                new_pin = advance_pin(old_pin, signed, ())
            except SigningError as exc:
                raise PinAdoptionRefused(
                    f"pin advance refused: {exc}") from exc
            already = (new_pin["cycle_seq"] == old_pin["cycle_seq"]
                       and new_pin["payload_hash"]
                       == old_pin["payload_hash"])
            try:
                self._store.adopt(new_pin, record=None,
                                  expected_old_pin=old_pin,
                                  signing_key=self._key)
            except PinStoreError as exc:
                raise PinAdoptionRefused(
                    f"pin adoption refused: {exc}") from exc
            if already:
                return AdoptionResult("already_current", old_pin, None)
            self._retain_candidate(signed)
            return AdoptionResult("advanced", new_pin, None)
        if cls == "reanchor_required":
            return self._reanchor(
                old_pin=old_pin, history=history, signed=signed,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                primary_reason=REASON_CHAIN_GAP_RECOVERY,
                strict_reasons=reasons)
        # Integrity failure: persist NOTHING — no pin write, no
        # history write, no evidence artefact is even created
        # (artefact creation lives inside the ceremony branch).
        raise PinAdoptionRefused(
            "snapshot verification is an integrity failure, not "
            f"a ceremony trigger: {list(reasons)}")

    # -- the ceremony sub-flow ------------------------------------------------

    def _evidence_bundle(self, *, ceremony_id, reason, old_pin, signed,
                         state_bytes, calibration_bytes,
                         strict_reasons) -> bytes:
        cfg = self._config
        if old_pin is None:
            old_line = "genesis"
            gap_line = "initial anchor — no prior pin"
        else:
            old_line = (f"seq={old_pin['cycle_seq']} "
                        f"hash={old_pin['payload_hash']}")
            gap_line = (f"gap_from_seq={old_pin['cycle_seq'] + 1} "
                        f"gap_to_seq={signed.cycle_seq - 1}")
        lines = [
            "aion pin-adoption evidence bundle",
            f"ceremony_id={ceremony_id}",
            f"adopter=aion-pin-adopter snapshot_signer_id="
            f"{cfg.snapshot_signer_id}",
            f"operator_id={cfg.operator_id}",
            f"reason={reason}",
            f"old_pin={old_line}",
            f"candidate_seq={signed.cycle_seq}",
            f"candidate_hash={signed.payload_hash}",
            f"candidate_signer_id={signed.signer_id}",
            f"candidate_key_id={signed.key_id}",
            f"state_sha256={hashlib.sha256(state_bytes).hexdigest()}",
            f"calibration_sha256="
            f"{hashlib.sha256(calibration_bytes).hexdigest()}",
            gap_line,
            f"strict_reasons="
            f"{','.join(strict_reasons) if strict_reasons else ''}",
            f"recorded_at="
            f"{datetime.now(timezone.utc).isoformat()}",
        ]
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _pending_phases(self, ceremony_id):
        """The accumulated phase set of one pending-journal
        ceremony (empty when unknown)."""
        for slot in self._journal_ceremonies():
            if slot["entry"].get("ceremony_id") == ceremony_id:
                return slot["phases"]
        return set()

    def _consume_retained(self, *, journal_base, signed_env,
                          signed, old_pin, history, state_bytes,
                          calibration_bytes, strict_reasons,
                          reason, pre_commit_fallthrough=False):
        """Exactly ONE re-anchor/consume attempt of the
        retained envelope against a supersession decision that
        exists (or may already exist) in the verifier's
        supersession journal — the consume path looks the
        decision up by authorisation_id itself.

        Pre-commit refusals (the envelope is certified
        unconsumed) are never burned (cycle 25 fix round 2,
        F2 — this corrects the earlier claim that a stale
        decision yields a supersede-required refusal):

        * ``ceremony_supersede_required`` — NO decision covers
          the current head (none landed, or the head shape
          changed): pending again, against the new head;
        * ``ceremony_head_regression`` — a decision WAS
          journaled for this envelope, but it was minted
          against a head that has since moved, so the
          verifier's binding check against the CURRENT head
          fails and the decision is inert: also pending
          again, never burned — the hash-binding
          head-regression shapes stay refusals for a FRESH
          ceremony (the ``_reanchor`` path is unchanged);
          only this resume-of-a-decided movement re-pends.

        With ``pre_commit_fallthrough=True`` (the consume-first
        entry in ``_resume_pending``) either pre-commit
        refusal instead returns None, signalling the caller
        to fall through to the approval-lookup path in the
        SAME attempt: a pre-commit refusal must not be
        terminal while an approval path remains, and the
        consume-first short-circuit must not make a fresh
        approval bound to the new head unreachable. (The
        alternative — returning to pending WITHOUT the
        decided short-circuit once the decision is
        known-stale — was rejected: it needs a new persistent
        journal phase to encode known-staleness, and a stale
        marker would outlive the attempt that learned it;
        the same-attempt fall-through keeps the state in the
        attempt, where it was learned.)

        A ``ceremony_already_consumed`` refusal (F3) is the
        opposite certificate: the verifier certifies the
        consumption COMMITTED (an earlier resume consume
        landed but its response was lost). The ``consumed``
        phase is appended to the pending journal BEFORE
        raising PinAdoptionBurned, so the ceremony becomes a
        genuine unadopted burn — ``_genuine_burn_entries``
        no longer excludes it and
        ``_find_pending_supersession`` no longer intercepts
        it — and the standard ``burned_unadopted`` recovery
        engages on later attempts. Any other failure keeps
        PinAdoptionBurned's conservatism."""
        cfg = self._config
        eff_strict = strict_reasons \
            if reason == REASON_CHAIN_GAP_RECOVERY else None
        try:
            new_pin, record = reanchor_pin(
                old_pin, signed, signing_key=self._key,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                expected_signer_id=cfg.expected_snapshot_signer_id,
                operator_id=cfg.operator_id, reason=reason,
                evidence_hash=signed_env.evidence_hash,
                authorisation=signed_env,
                authorisation_public_key=self._pub,
                expected_verifier_signer_id=
                cfg.expected_verifier_signer_id,
                ceremony_history=history,
                consume_authorisation=self._client.ceremony_consumer(),
                strict_reasons=eff_strict)
        except CeremonySupersedeRequired as sup:
            if pre_commit_fallthrough:
                return None
            # No covering decision for the current head:
            # still provably unconsumed, still a stop —
            # pending again, against the new head.
            self._stop_at_pending(
                sup, journal_base=journal_base, old_pin=old_pin,
                signed=signed, reason=reason)
        except CeremonyHeadRegression as sup:
            if pre_commit_fallthrough:
                return None
            # A journaled decision exists but is bound to a
            # superseded head (inert verifier-side): still
            # provably unconsumed, still a stop — pending
            # again, against the new head, so a fresh approval
            # bound to the new head can be presented on a
            # later attempt.
            self._stop_at_pending(
                sup, journal_base=journal_base, old_pin=old_pin,
                signed=signed, reason=reason)
        except CeremonyAlreadyConsumed as exc:
            # F3: the verifier has CERTIFIED the consumption.
            # Record the consumed phase first (best-effort,
            # like every journal append here — the Burned
            # raise must not be masked), so the pending
            # ceremony is reclassified as a genuine unadopted
            # burn and the ordinary recovery route engages.
            try:
                self._append_journal(
                    {**journal_base, "phase": "consumed"})
            except OSError:
                pass
            raise PinAdoptionBurned(
                f"re-anchor of the retained envelope refused "
                f"with ceremony_already_consumed: the verifier "
                f"certifies the consumption already committed "
                f"(an earlier resume consume landed but its "
                f"response was lost); the consumed phase has "
                f"been journaled so the ceremony is a genuine "
                f"unadopted burn: {exc}",
                returned_pin=None, returned_record=None) from exc
        except Exception as exc:
            raise PinAdoptionBurned(
                f"re-anchor after a journaled supersession "
                f"decision did not return; the authorisation is "
                f"treated as burned: {exc}",
                returned_pin=None, returned_record=None) from exc
        self._append_journal({**journal_base, "phase": "consumed"})
        try:
            self._store.adopt(new_pin, record,
                              expected_old_pin=old_pin,
                              signing_key=self._key)
        except Exception as exc:
            raise PinAdoptionBurned(
                f"consumption committed but adoption failed: {exc}",
                returned_pin=new_pin, returned_record=record) from exc
        try:
            self._append_journal({**journal_base, "phase": "adopted"})
        except OSError:
            pass
        return AdoptionResult("reanchored", new_pin, record)

    def _resume_pending(self, pending_entry, *, old_pin, history,
                        signed, state_bytes, calibration_bytes,
                        strict_reasons) -> AdoptionResult:
        """Cycle 25 resume (design §6): complete a retained
        supersession-pending movement — ONLY against an inbox
        approval bound to the retained envelope.

        No approval in the inbox: raise
        PinSupersessionPendingApproval again WITHOUT any new
        ceremony (no authorise, no consume), so the retained
        envelope stays the approvable one. With an approval:
        present it once (its file is moved aside regardless of
        outcome in directory mode; in single-file mode it is
        NOT moved aside — see the module docstring's
        single-file asymmetry note), obtain the verifier's
        journaled supersession decision, re-run the consume of
        the SAME envelope exactly once, and adopt.

        Consume-first (r3 F1): if the pending entry already
        carries a ``supersede_decided`` phase, a decision was
        journaled by an earlier attempt whose consume never
        landed — go straight to the single consume attempt
        with NO approval lookup and NO second decision
        request.

        Consume-first fall-through (fix round 2, F2): if that
        consume refuses PRE-COMMIT — supersede-required (no
        covering decision) or head-regression (the journaled
        decision is bound to a head that has since moved and
        is inert) — the attempt does NOT stop there: it falls
        through to the approval-lookup path below in the SAME
        attempt, so a fresh approval bound to the new head
        already in the inbox is presented, and with none the
        movement re-pends. Without this, the decided
        short-circuit would intercept before the approval
        lookup on every later attempt and a fresh approval
        would never be presented — a permanent Burned/pending
        loop. The same fall-through applies in-attempt when
        a decision request refuses ``ceremony_supersede_unproven``
        (a prior decision already exists for this envelope) or
        ``ledger_failed`` (the verifier's step-10 shape: the
        decision may stand despite the failed response)."""
        cfg = self._config
        envelope_dict = pending_entry["authorisation_envelope"]
        try:
            signed_env = ceremony_authorisation_envelope_from_dict(
                envelope_dict)
        except SigningError as exc:
            raise PinAdoptionRefused(
                f"retained pending envelope is unparseable: {exc}"
            ) from exc
        journal_base = {
            "ceremony_id": pending_entry.get("ceremony_id"),
            "authorisation_id": signed_env.authorisation_id,
            "candidate_seq": signed.cycle_seq,
            "candidate_hash": signed.payload_hash,
            "old_cycle_seq": pending_entry.get("old_cycle_seq"),
            "old_payload_hash": pending_entry.get("old_payload_hash"),
        }
        reason = pending_entry.get("reason") \
            or REASON_CHAIN_GAP_RECOVERY
        if "supersede_decided" in self._pending_phases(
                pending_entry.get("ceremony_id")):
            # Consume-first: an earlier attempt journaled the
            # decision (its supersede_decided line landed) but
            # its consume did not. No approval is needed — or
            # usable: a fresh decision request would refuse as
            # already decided — so land the single consume of
            # the retained envelope directly. F2: a PRE-COMMIT
            # refusal from that consume (returned as None)
            # falls through to the approval lookup below in
            # this same attempt instead of terminating the
            # movement — the journaled decision may be stale
            # (bound to a superseded head), and a fresh
            # approval bound to the new head is the one
            # artefact that can move the movement forward.
            result = self._consume_retained(
                journal_base=journal_base, signed_env=signed_env,
                signed=signed, old_pin=old_pin, history=history,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                strict_reasons=strict_reasons, reason=reason,
                pre_commit_fallthrough=True)
            if result is not None:
                return result
        found = self._find_supersession_approval(
            pending_authorisation_id=signed_env.authorisation_id,
            pending_head_entry_hash=pending_entry.get(
                "head_entry_hash"))
        if found is None:
            old_seq, old_hash = self._old_pin_projection(old_pin)
            raise PinSupersessionPendingApproval(
                "ceremony consumption is supersession pending "
                "independent approval: no approval artefact for "
                "the retained envelope was found in the approval "
                "inbox; no new ceremony was started",
                ceremony_id=journal_base["ceremony_id"],
                authorisation_id=signed_env.authorisation_id,
                operator_id=cfg.operator_id, reason=reason,
                candidate_seq=signed.cycle_seq,
                candidate_hash=signed.payload_hash,
                old_cycle_seq=old_seq, old_payload_hash=old_hash,
                abandoned_movement_candidates=
                self._known_abandoned_movements(
                    exclude_authorisation_id=
                    signed_env.authorisation_id),
                envelope_dict=envelope_dict,
                approval_path=str(cfg.supersession_approval_path)
                if cfg.supersession_approval_path is not None
                else None,
                journal_persisted=True,
                report_path=str(self.pending_report_path),
                report_written=self.pending_report_path.is_file())
        approval_dict, approval_file, move_aside = found

        def _move_aside():
            if move_aside:
                try:
                    os.replace(
                        approval_file,
                        approval_file.with_name(
                            approval_file.name + ".presented"))
                except OSError:
                    pass

        try:
            _request_supersession_decision(
                self._client, operator_id=cfg.operator_id,
                envelope_dict=envelope_dict, approval=approval_dict)
        except TypeError:
            # The configured client cannot present an approval
            # artefact: the approval is unpresentable through
            # this channel, so the movement stays pending (the
            # file is NOT moved aside — nothing was presented)
            # and the adopter never falls back to an unapproved
            # decision request.
            old_seq, old_hash = self._old_pin_projection(old_pin)
            raise PinSupersessionPendingApproval(
                "ceremony consumption is supersession pending "
                "independent approval: an approval artefact "
                "exists but the configured client cannot present "
                "it; the movement stays pending",
                ceremony_id=journal_base["ceremony_id"],
                authorisation_id=signed_env.authorisation_id,
                operator_id=cfg.operator_id, reason=reason,
                candidate_seq=signed.cycle_seq,
                candidate_hash=signed.payload_hash,
                old_cycle_seq=old_seq, old_payload_hash=old_hash,
                abandoned_movement_candidates=
                self._known_abandoned_movements(
                    exclude_authorisation_id=
                    signed_env.authorisation_id),
                envelope_dict=envelope_dict,
                approval_path=str(cfg.supersession_approval_path)
                if cfg.supersession_approval_path is not None
                else None,
                journal_persisted=True,
                report_path=str(self.pending_report_path),
                report_written=self.pending_report_path.is_file())
        except Exception as exc:
            _move_aside()
            if getattr(exc, "verifier_code", None) in (
                    "ceremony_supersede_unproven", "ledger_failed"):
                # Consume-first (r3 F1): the refusal/response
                # shape says a decision may ALREADY exist for
                # this envelope — unproven because a prior
                # decision exists (step 8/8b), or ledger_failed
                # after the step-9 commit (step 10: "the
                # decision stands … consumption may proceed
                # against it"). A re-decide would refuse as
                # already decided, and classifying this burned
                # would strand a movement whose decision is
                # journaled. Fall through to exactly ONE
                # consume attempt of the retained envelope; the
                # consume path looks the decision up itself, and
                # only a PRE-COMMIT refusal from THAT consume
                # (supersede-required: no covering decision;
                # head-regression: the decision is bound to a
                # superseded head) returns the movement to
                # pending — never to burned.
                return self._consume_retained(
                    journal_base=journal_base,
                    signed_env=signed_env, signed=signed,
                    old_pin=old_pin, history=history,
                    state_bytes=state_bytes,
                    calibration_bytes=calibration_bytes,
                    strict_reasons=strict_reasons, reason=reason)
            # Any other failure: a decision may or may not be
            # journaled; the approval is spent either way
            # (moved aside), and PinAdoptionBurned's
            # conservatism is retained: the adopter cannot
            # distinguish the cases.
            raise PinAdoptionBurned(
                f"supersession decision request failed; the "
                f"authorisation is treated as burned: {exc}",
                returned_pin=None, returned_record=None) from exc
        _move_aside()
        # The "supersede_decided" pending-journal line is a
        # detection aid only, like every phase; it is NOT a
        # burn phase — _unadopted_burns is unchanged by it. Its
        # append failing is no longer a burn: the decision IS
        # journaled verifier-side, so the movement proceeds to
        # the consume attempt regardless (a later attempt
        # re-derives the consume-first state from the
        # verifier's decision via the unproven fall-through).
        try:
            self._append_journal({**journal_base,
                                  "phase": "supersede_decided"})
        except OSError:
            pass
        return self._consume_retained(
            journal_base=journal_base, signed_env=signed_env,
            signed=signed, old_pin=old_pin, history=history,
            state_bytes=state_bytes,
            calibration_bytes=calibration_bytes,
            strict_reasons=strict_reasons, reason=reason)

    def _reanchor(self, *, old_pin, history, signed, state_bytes,
                  calibration_bytes, primary_reason,
                  strict_reasons) -> AdoptionResult:
        cfg = self._config
        # Cycle 25 resume: a retained supersession-pending
        # movement for THIS candidate and old pin is completed
        # (or re-surfaced as pending) before any new ceremony
        # is contemplated — a fresh authorisation would orphan
        # the retained envelope an approval may already bind.
        if old_pin is not None:
            pending_entry = self._find_pending_supersession(
                candidate_seq=signed.cycle_seq,
                candidate_hash=signed.payload_hash, old_pin=old_pin)
            if pending_entry is not None:
                return self._resume_pending(
                    pending_entry, old_pin=old_pin, history=history,
                    signed=signed, state_bytes=state_bytes,
                    calibration_bytes=calibration_bytes,
                    strict_reasons=strict_reasons)
        # Computed reason (DESIGN-FINAL R3): an unadopted burn
        # for THIS candidate (same seq+hash) and THIS old pin
        # makes this ceremony a burned_unadopted recovery;
        # otherwise the honest primary reason. Never lost_pin
        # for an unmoved pin.
        burn = self._find_unadopted_burn(
            candidate_seq=signed.cycle_seq,
            candidate_hash=signed.payload_hash, old_pin=old_pin)
        if burn is not None:
            reason = REASON_BURNED_UNADOPTED
            eff_strict = strict_reasons if old_pin is not None else None
        else:
            reason = primary_reason
            eff_strict = strict_reasons \
                if reason == REASON_CHAIN_GAP_RECOVERY else None
        ceremony_id = (f"pin-adopt-{signed.cycle_seq}-"
                       f"{uuid.uuid4().hex[:12]}")
        evidence_ref = f"pin-evidence-{ceremony_id}"
        # (1) Evidence artefact first: authored and placed by
        # the adopter; the hash comes from the adopter's own
        # bytes (EVIDENCE-INTENT), never from the envelope.
        bundle = self._evidence_bundle(
            ceremony_id=ceremony_id, reason=reason, old_pin=old_pin,
            signed=signed, state_bytes=state_bytes,
            calibration_bytes=calibration_bytes,
            strict_reasons=strict_reasons)
        evidence_dir = Path(cfg.evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomically(evidence_dir / evidence_ref, bundle)
        evidence_hash = hashlib.sha256(bundle).hexdigest()
        old_projection = None if old_pin is None else {
            "cycle_seq": old_pin["cycle_seq"],
            "payload_hash": old_pin["payload_hash"]}
        candidate_projection = {
            "cycle_seq": signed.cycle_seq,
            "payload_hash": signed.payload_hash,
            "signer_id": signed.signer_id, "key_id": signed.key_id}
        old_seq, old_hash = self._old_pin_projection(old_pin)
        # (1b) Authorise-pending journal line (cycle 23, R4): a
        # detection/audit aid appended BEFORE the authorise call,
        # so a crash between authorise and the authorised line
        # still leaves a trace naming the ceremony and candidate.
        # It carries NO envelope and does NOT count as a burn in
        # _unadopted_burns (only authorised/consumed phases do):
        # program order — the authorised-line append completes
        # before consume begins — means a pending line with no
        # authorised line proves nothing could have consumed, and
        # the next attempt proceeds with a fresh primary ceremony.
        try:
            self._append_journal({
                "phase": "authorise_pending",
                "ceremony_id": ceremony_id,
                "candidate_seq": signed.cycle_seq,
                "candidate_hash": signed.payload_hash,
                "old_cycle_seq": old_seq, "old_payload_hash": old_hash})
        except OSError as exc:
            # Fix round (r6-F6): the pending append's failure
            # surfaces in this function's refusal typing, not
            # as a raw OSError — pin_cycle_hook's alert
            # contract keys off PinAdoptionRefused /
            # PinAdoptionBurned and attaches the cycle entry
            # only to those.
            raise PinAdoptionRefused(
                f"authorise-pending journal append failed: {exc}"
            ) from exc
        # (2) Authorise.
        try:
            envelope_dict = self._client.ceremony_authorise(
                operator_id=cfg.operator_id, ceremony_id=ceremony_id,
                reason=reason, old_pin=old_projection,
                candidate=candidate_projection,
                evidence_hash=evidence_hash, evidence_ref=evidence_ref)
            signed_env = ceremony_authorisation_envelope_from_dict(
                envelope_dict)
        except PinAdoptionRefused:
            raise
        except Exception as exc:
            raise PinAdoptionRefused(
                f"ceremony authorisation failed: {exc}") from exc
        journal_base = {
            "ceremony_id": ceremony_id,
            "authorisation_id": signed_env.authorisation_id,
            "candidate_seq": signed.cycle_seq,
            "candidate_hash": signed.payload_hash,
            "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
        }
        # (3) Pending-adoption journal: authorised. The candidate
        # envelope is retained here so a post-burn attempt can
        # re-present the identical candidate (see module
        # docstring); the journal remains a detection aid, never
        # authority.
        self._append_journal({
            **journal_base, "phase": "authorised",
            "reason": reason, "evidence_hash": evidence_hash,
            # Cycle 25: the authorisation envelope is retained
            # too — a supersession-pending resume must
            # re-present THIS envelope (an approval binds its
            # authorisation_id), never a fresh one.
            "authorisation_envelope": envelope_dict,
            "candidate_envelope": snapshot_envelope_to_dict(signed)})
        # (4) Re-anchor. Consumption commits at the verifier
        # inside this call; any exception from here is treated
        # as burned — a lost consume response is
        # indistinguishable from a refused one at this layer.
        def _attempt(envelope):
            return reanchor_pin(
                old_pin, signed, signing_key=self._key,
                state_bytes=state_bytes,
                calibration_bytes=calibration_bytes,
                expected_signer_id=cfg.expected_snapshot_signer_id,
                operator_id=cfg.operator_id, reason=reason,
                evidence_hash=evidence_hash,
                authorisation=envelope,
                authorisation_public_key=self._pub,
                expected_verifier_signer_id=cfg.expected_verifier_signer_id,
                ceremony_history=history,
                consume_authorisation=self._client.ceremony_consumer(),
                strict_reasons=eff_strict)

        try:
            new_pin, record = _attempt(signed_env)
        except CeremonySupersedeRequired as sup:
            # Cycle 25 (CROSS-CHECK-18 Q1): the adopter STOPS
            # here. Cycle 24 auto-requested a supersession
            # decision after this refusal and re-ran the
            # consume; seat-gpt held cycles 14-16 because an
            # adopter auto-escalating after a refusal is not an
            # independent authorisation event. The auto-request
            # call is DELETED, not gated: this handler requests
            # nothing and re-runs nothing. It records the
            # pending state, writes the pending-supersession
            # report for the out-of-band approval tool, and
            # raises PinSupersessionPendingApproval. Completion
            # is the resume path's job, on a later attempt, only
            # against an inbox approval bound to THIS envelope.
            #
            # The refusal itself is a KNOWN, negative outcome
            # (never a retry concern): the verifier emits
            # ceremony_supersede_required only pre-commit, after
            # its already-consumed check has certified the
            # envelope unconsumed, so the envelope is provably
            # unburned and the retained envelope may be consumed
            # later once a decision exists.
            self._stop_at_pending(
                sup, journal_base=journal_base, old_pin=old_pin,
                signed=signed, reason=reason)
        except Exception as exc:
            raise PinAdoptionBurned(
                f"re-anchor did not return; the authorisation is "
                f"treated as burned: {exc}",
                returned_pin=None, returned_record=None) from exc
        # (5) Adopt atomically.
        self._append_journal({**journal_base, "phase": "consumed"})
        try:
            self._store.adopt(new_pin, record,
                              expected_old_pin=old_pin,
                              signing_key=self._key)
        except Exception as exc:
            raise PinAdoptionBurned(
                f"consumption committed but adoption failed: {exc}",
                returned_pin=new_pin, returned_record=record) from exc
        # The pin has adopted; a failure to append the
        # phase:"adopted" journal line must not mask that
        # success with a raw OSError. The journal is a
        # detection aid, never authority, so the failure is
        # swallowed here (comment-documented swallow, chosen
        # over recording it on the frozen result): the next
        # attempt self-heals via already_current.
        try:
            self._append_journal({**journal_base, "phase": "adopted"})
        except OSError:
            pass
        return AdoptionResult("reanchored", new_pin, record)

    # -- recovery entry point (design C §6.1) ---------------------------------

    def adopt_returned(self, new_pin, record, *,
                       expected_old_pin) -> AdoptionResult:
        """Adopt a (pin, record) pair an earlier
        ``snapshot_and_adopt`` returned but failed to adopt
        (carried on ``PinAdoptionBurned``). No new ceremony, no
        new consumption: a thin, audited wrapper over
        ``PinStore.adopt`` for exactly that pair."""
        if not isinstance(record, PinCeremonyRecord):
            raise SigningError("record must be a PinCeremonyRecord")
        self._store.adopt(new_pin, record,
                          expected_old_pin=expected_old_pin,
                          signing_key=self._key)
        old_seq, old_hash = self._old_pin_projection(expected_old_pin)
        # Same comment-documented swallow as in _reanchor:
        # the adoption above has succeeded, so a journal
        # append failure must not mask it; the next attempt
        # self-heals via already_current.
        try:
            self._append_journal({
                "ceremony_id": record.ceremony_id,
                "authorisation_id": record.authorisation_id,
                "candidate_seq": record.new_cycle_seq,
                "candidate_hash": record.new_payload_hash,
                "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
                "phase": "adopted"})
        except OSError:
            pass
        return AdoptionResult("reanchored", new_pin, record)


def pin_cycle_hook(adopter):
    """The integrated wiring (cycle 23, R1): a ``cycle_hook``
    for ``CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))``
    that adopts the recorded cycle's snapshot pin.

    The returned callable takes the recorded cycle entry, calls
    ``adopter.snapshot_and_adopt()``, and returns its
    AdoptionResult. On PinAdoptionBurned / PinAdoptionRefused /
    PinSupersessionPendingApproval the
    entry is attached as ``.cycle_entry`` before re-raising —
    the run_one_cycle_and_pin contract, preserved: "cycle
    recorded, pin pending, alert". The hook is the integrated
    path; run_one_cycle_and_pin remains only for unhooked
    composition and refuses a hooked loop."""
    def _hook(entry):
        try:
            return adopter.snapshot_and_adopt()
        except (PinAdoptionBurned, PinAdoptionRefused,
                PinSupersessionPendingApproval) as exc:
            exc.cycle_entry = entry
            raise
    return _hook


def run_one_cycle_and_pin(loop, adopter, *, coders, reviewers,
                          verdict, verify_passed, delta):
    """The loop driver (design C §5): run one loop cycle, then
    adopt its snapshot pin. Ordering is forced: the cycle
    persists in state BEFORE the pin can move (a snapshot
    attests bytes that exist). On an adoption exception the
    cycle entry is attached as ``.cycle_entry`` and the
    exception propagates: the contract is "cycle recorded, pin
    pending, alert". The wrapper never rolls back loop state —
    un-saving a shipped cycle would falsify the loop's history.

    Cycle 23 (R1): the integrated path is the loop hook —
    ``CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))``
    — and this driver remains for unhooked composition only.
    A loop that already carries a cycle_hook is REFUSED
    (ValueError): running the driver on it would wire the
    adoption twice for one cycle (double wiring)."""
    if loop.cycle_hook is not None:
        raise ValueError(
            "run_one_cycle_and_pin refuses a loop with a "
            "cycle_hook already wired (double wiring); the hook "
            "(pin_cycle_hook) is the integrated path — run the "
            "cycle through the loop directly")
    entry = loop.run_one_cycle(coders, reviewers, verdict,
                               verify_passed, delta)
    if entry is None:
        return None, None            # idle: no state change, no snapshot
    try:
        result = adopter.snapshot_and_adopt()
    except (PinAdoptionBurned, PinAdoptionRefused,
            PinSupersessionPendingApproval) as exc:
        exc.cycle_entry = entry
        raise
    return entry, result
