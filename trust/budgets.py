"""In-verifier evaluation query budgets (Trust Boundary v2, item 5).

The sealed-eval mode is an exact-score oracle: each query returns
the precise score of one positional answer transcript against the
sealed set, so an adaptive querier can extract the sealed answers
position by position (change one answer, watch the score move).
The fix mandated by the cycle-8 cross-check (F6) is budgets
INSIDE the verifier — the one component the querier does not
control — and this module is that budget store. The verifier
calls check_and_record BEFORE running an evaluation; a refusal
means the evaluation never runs, no attestation is signed, and
no registry access-log entries are spent. A two-phase API
(check_only / record, below) lets the verifier refuse BEFORE
opening the registry without burning budget on a transcript it
then rejects for a non-budget reason (e.g. answer-count
mismatch): check_only records nothing, record re-checks and
records once the transcript is validated.

What is enforced, per registry actor identity:

* Query-count caps: per-proposal cap (default 25) and
  per-identity cap (default 500) on the number of recorded
  evaluations. The identity cap spans proposals. Both defaults
  sit far below the registry's access-log cap
  (eval/registry.py MAX_ACCESS_LOG = 10000 entries, shared
  across every access kind and actor): a single identity can
  never come close to exhausting the log through sealed evals
  alone, and a single proposal's extraction budget is 25
  transcripts — at most 25 exact scores, each of which leaks at
  most log2(n+1) bits about an n-item sealed set.
* Detection is IDENTITY-scoped, not proposal-scoped (war-room
  HIGH-1): replay, near-duplicate similarity and probe counting
  all compare a new transcript against EVERY transcript recorded
  for that identity, across all proposals. The proposal label is
  caller-chosen, so when detection was scoped per label an
  extractor could rotate labels ("prop-a", "prop-b", ...) and
  reset replay/probe detection at will; only the 500
  per-identity cap bound them. The caps stay as query-count
  limits (per-proposal AND per-identity); the DETECTION no
  longer trusts the label.
* transcript replay: a byte-identical resubmission of a previous
  transcript BY THE SAME IDENTITY (under any proposal label) is
  refused ("transcript_replay"). It extracts nothing new, but it
  still burns registry access-log entries and produces a fresh
  signed attestation for an old result, so it is not free. A
  DIFFERENT identity submitting the same transcript is not a
  replay — identities are budgeted independently.
* adaptive-query detection: similarity between two transcripts
  is the fraction of positions whose answers are identical
  (positions beyond the shorter transcript count as different;
  the denominator is the longer length). A new transcript is a
  near-duplicate probe when, against ANY previous transcript of
  the same identity, EITHER its similarity is >= 0.8 OR the
  absolute number of differing positions is <= 2 (war-room
  HIGH-2). The absolute rule exists because the fraction rule is
  blind exactly where extraction is cheapest: at similarity
  0.70/0.79 a probe never counted, and for sealed sets of n <= 4
  a single-position probe has similarity <= 0.75, so the
  fraction-based detector could NEVER fire on the classic
  one-position-at-a-time extraction against a small set. With
  the absolute rule, any transcript within two changed positions
  of a prior one counts, whatever the fraction. (For n <= 2 that
  makes every second query a probe; extraction from such a set
  is trivially cheap anyway, and the detector fails closed.)
  The first two probes (identity-wide) are recorded and allowed
  (a legitimate re-run after fixing a couple of answers looks
  like this); the third latches the probed transcript FAMILY for
  that identity: the prior transcript the tripping probe matched
  is recorded as a blocked family anchor, and every further
  near-duplicate of that family from that identity is refused
  ("adaptive_query_detected"), under any proposal label. Once an
  identity's probe count has reached the limit, ANY further
  near-duplicate query from it (any family) is likewise refused
  and latches its own family. Transcripts that are not
  near-duplicates of a blocked family remain allowed, subject to
  the caps. The latch is persistent: restarting the verifier
  does not clear it. (Two-phase callers: check_only() records
  nothing, so a tripping probe persists only when the caller
  follows it with record(), as the verifier's wiring does —
  record() writes the probe count and the family latch before
  raising the same refusal.)

Persistence follows trust/ledger.py's pattern: one JSON file,
an exclusive flock on the containing directory held across the
whole check-and-record (so there is no check-then-record race
between concurrent verifier processes), write to a temp file in
the same directory, fsync, atomic os.replace, directory fsync.
The file is strictly validated on every load — exact key sets,
types, and the accounting invariants (a proposal's count equals
its stored transcript count; each identity's count equals the
transcripts recorded under its name; no (identity,
answers_hash) pair repeats). A corrupt file is a REFUSAL
("budget_store_corrupt"), never a silent reset: resetting the
budgets on corruption would hand an extractor a fresh budget
for the price of corrupting one file. Schema v1 files (the
pre-identity-scoping format, whose transcripts carry no identity
attribution) are refused the same way rather than migrated
blind: attribution cannot be reconstructed honestly, and an
operator who accepts a budget reset deletes the file
deliberately, as an auditable act — the store never does it
silently.

Integrity (war-room MEDIUM-1): the persisted state is
hash-chained. Each saved state carries "prev_chain_hash" (the
head of the state it replaces; the genesis hash for the first
save) and "chain_hash" = sha256 over the previous head and the
canonical serialisation of the rest of the state. Every load
recomputes and compares the chain, so an edit that does not
recompute it — including an edit that keeps every structural
invariant consistent, e.g. deleting a transcript and fixing the
counts — is detected as corruption. verify_integrity() exposes
that check (plus an optional expected-head comparison) without
raising, and head_hash() exports the current head so an
external anchor can pin it alongside the signing/ship ledger
anchors (trust/anchoring.py). Honest limits, same as the
ledgers: the chain is unkeyed, so a same-user attacker who
rewrites the file AND recomputes the chain produces a
self-consistent store; and rolling the file back to an earlier
SELF-CONSISTENT state passes verify_integrity() on its own —
rollback is detected only against an externally anchored head
(verify_integrity(expected_head=...) or the verifier's startup
anchor check). Wiring that anchor into verifier startup is the
coordinator's patch to trust/verifier_main.py, not this module.

Only per-position answer HASHES are stored (plus the whole-
transcript answers_hash from trust.attestation), never the
answers themselves: similarity needs positional equality only,
and the budget store should not become a second copy of every
transcript ever submitted.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path

from trust.attestation import answers_hash_for

STORE_VERSION = 2
DEFAULT_PER_PROPOSAL_CAP = 25
DEFAULT_PER_IDENTITY_CAP = 500
NEAR_DUPLICATE_SIMILARITY = 0.8
ABSOLUTE_PROBE_MAX_DIFFERING = 2
NEAR_DUPLICATE_LIMIT = 3
MAX_STORE_BYTES = 8 * 1024 * 1024
MAX_ANSWERS = 500  # mirrors trust/verifier_main.py's transcript bound
GENESIS_CHAIN_HASH = "0" * 64

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}$")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_TOP_KEYS = {"schema_version", "identities", "proposals",
             "prev_chain_hash", "chain_hash"}
_IDENTITY_KEYS = {"count", "near_duplicate_probes", "blocked_families"}
_PROPOSAL_KEYS = {"count", "transcripts"}
_TRANSCRIPT_KEYS = {"answers_hash", "identity", "position_hashes"}
_FAMILY_KEYS = {"answers_hash", "position_hashes"}

# Reason codes carried by BudgetError.reason. The first four are
# the query-budget refusals the verifier maps to its
# "query_budget_exceeded" error document; the last two are
# store-integrity refusals (the verifier maps any BudgetError the
# same way — no evaluation runs and nothing is signed either way).
REASON_PROPOSAL_BUDGET = "proposal_budget_exceeded"
REASON_IDENTITY_BUDGET = "identity_budget_exceeded"
REASON_ADAPTIVE = "adaptive_query_detected"
REASON_REPLAY = "transcript_replay"
REASON_CORRUPT = "budget_store_corrupt"
REASON_FULL = "budget_store_full"
# Extra reason string returned (not raised) by verify_integrity.
REASON_MISSING = "budget_store_missing"
REASON_HEAD_MISMATCH = "budget_head_mismatch"


class BudgetError(Exception):
    """A budget check was refused. ``reason`` is one of the
    REASON_* codes above; ``detail`` is diagnostic text."""

    def __init__(self, reason, detail=""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# Strict parsing (Trust Boundary v3.1, parser inventory): the
# store is parsed under the same contract as every other
# security-relevant consumer — duplicate keys and non-finite
# numbers are refused by the PARSER, so this loader can never
# disagree with a strict consumer about what the store says.

def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise BudgetError(REASON_CORRUPT,
                              f"duplicate key in budget store: {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise BudgetError(REASON_CORRUPT,
                      f"non-finite number in budget store: {name}")


def _parse_float_strict(text):
    value = float(text)
    if not math.isfinite(value):
        raise BudgetError(REASON_CORRUPT,
                          f"non-finite number in budget store: {text}")
    return value


def _position_hash(answer: str) -> str:
    return hashlib.sha256(
        ("budget-position/1\n" + answer).encode("utf-8")).hexdigest()


def transcript_similarity(position_hashes_a, position_hashes_b) -> float:
    """Fraction of positions with identical answers. The
    denominator is the longer transcript, so padding a transcript
    with extra positions cannot dilute a near-duplicate below the
    threshold. Two empty transcripts are identical (1.0) — that
    case is reached only via replay, which is checked first."""
    longer = max(len(position_hashes_a), len(position_hashes_b))
    if longer == 0:
        return 1.0
    identical = sum(1 for a, b in zip(position_hashes_a,
                                      position_hashes_b) if a == b)
    return identical / longer


def differing_positions(position_hashes_a, position_hashes_b) -> int:
    """Absolute number of positions whose answers differ;
    positions beyond the shorter transcript count as differing.
    This is the HIGH-2 metric: for small sealed sets the
    similarity FRACTION stays below any sane threshold even for
    a one-position probe, but the absolute difference is 1."""
    longer = max(len(position_hashes_a), len(position_hashes_b))
    identical = sum(1 for a, b in zip(position_hashes_a,
                                      position_hashes_b) if a == b)
    return longer - identical


def _canonical_core(core: dict) -> bytes:
    return json.dumps(core, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _chain_hash(prev_head: str, core: dict) -> str:
    return hashlib.sha256(
        b"budget-chain/1\n" + prev_head.encode("ascii") + b"\n"
        + _canonical_core(core)).hexdigest()


def _core_of(data: dict) -> dict:
    return {"schema_version": data["schema_version"],
            "identities": data["identities"],
            "proposals": data["proposals"]}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class BudgetStore:
    """Persistent sealed-eval query budgets for one budget file.

    ``path`` is the store file itself (the verifier passes
    Path(config.home) / "budgets.json"). Caps are constructor
    parameters so tests and deployments can tighten them; the
    defaults are DEFAULT_PER_PROPOSAL_CAP /
    DEFAULT_PER_IDENTITY_CAP. Instances cache nothing mutable:
    every operation re-reads the file, and record /
    check_and_record do their read-check-write under one
    directory flock, so separate BudgetStore instances (including
    in separate processes) on the same file stay consistent.
    """

    def __init__(self, path, *, per_proposal_cap=DEFAULT_PER_PROPOSAL_CAP,
                 per_identity_cap=DEFAULT_PER_IDENTITY_CAP,
                 near_duplicate_threshold=NEAR_DUPLICATE_SIMILARITY,
                 near_duplicate_limit=NEAR_DUPLICATE_LIMIT):
        for name, value in (("per_proposal_cap", per_proposal_cap),
                            ("per_identity_cap", per_identity_cap),
                            ("near_duplicate_limit", near_duplicate_limit)):
            if not _is_int(value) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        if isinstance(near_duplicate_threshold, bool) \
                or not isinstance(near_duplicate_threshold, (int, float)) \
                or not 0.0 < float(near_duplicate_threshold) <= 1.0:
            raise ValueError("near_duplicate_threshold must be in (0, 1]")
        self.path = Path(path)
        self.per_proposal_cap = per_proposal_cap
        self.per_identity_cap = per_identity_cap
        self.near_duplicate_threshold = float(near_duplicate_threshold)
        self.near_duplicate_limit = near_duplicate_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Load once at construction so a corrupt store refuses as
        # early as possible (verifier startup), not first at query
        # time. A missing file is a fresh store, not corruption.
        self._load()

    # -- persistence ----------------------------------------------------

    @staticmethod
    def _fresh() -> dict:
        return {"schema_version": STORE_VERSION, "identities": {},
                "proposals": {},
                "prev_chain_hash": GENESIS_CHAIN_HASH,
                "chain_hash": GENESIS_CHAIN_HASH}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._fresh()
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise BudgetError(REASON_CORRUPT,
                              f"budget store is unreadable: {exc}") from exc
        if len(raw) > MAX_STORE_BYTES:
            raise BudgetError(REASON_CORRUPT,
                              "budget store exceeds the size cap")
        try:
            data = json.loads(raw.decode("utf-8"),
                              object_pairs_hook=_no_duplicate_keys,
                              parse_constant=_reject_constant,
                              parse_float=_parse_float_strict)
        except BudgetError:
            raise
        except (ValueError, UnicodeDecodeError) as exc:
            raise BudgetError(REASON_CORRUPT,
                              f"budget store is not valid JSON: {exc}") \
                from exc
        self._validate(data)
        self._validate_chain(data)
        return data

    def _validate_chain(self, data) -> None:
        head, prev = data["chain_hash"], data["prev_chain_hash"]
        if head == GENESIS_CHAIN_HASH:
            # The genesis head names the empty state only; a
            # persisted non-empty state under it was rolled back
            # or hand-built.
            if prev != GENESIS_CHAIN_HASH or data["identities"] \
                    or data["proposals"]:
                raise BudgetError(
                    REASON_CORRUPT,
                    "budget store corrupt: genesis chain head on a "
                    "non-empty state")
            return
        if _chain_hash(prev, _core_of(data)) != head:
            raise BudgetError(
                REASON_CORRUPT,
                "budget store corrupt: chain hash mismatch — the "
                "state was edited without recomputing the chain")

    def _validate(self, data) -> None:
        def bad(msg):
            raise BudgetError(REASON_CORRUPT, f"budget store corrupt: {msg}")
        if not isinstance(data, dict) or set(data) != _TOP_KEYS:
            bad("top-level keys differ")
        if data["schema_version"] != STORE_VERSION:
            bad("schema version")
        if not isinstance(data["prev_chain_hash"], str) \
                or not _HEX64_RE.fullmatch(data["prev_chain_hash"]) \
                or not isinstance(data["chain_hash"], str) \
                or not _HEX64_RE.fullmatch(data["chain_hash"]):
            bad("chain hashes")
        identities, proposals = data["identities"], data["proposals"]
        if not isinstance(identities, dict) \
                or not isinstance(proposals, dict):
            bad("identities/proposals must be objects")
        for identity, record in identities.items():
            if not _ID_RE.fullmatch(identity or "") \
                    or not isinstance(record, dict) \
                    or set(record) != _IDENTITY_KEYS:
                bad("identity records")
            if not _is_int(record["count"]) or record["count"] < 0 \
                    or not _is_int(record["near_duplicate_probes"]) \
                    or record["near_duplicate_probes"] < 0:
                bad("identity record fields")
            families = record["blocked_families"]
            if not isinstance(families, list):
                bad("blocked families")
            seen_family_hashes = set()
            for family in families:
                if not isinstance(family, dict) \
                        or set(family) != _FAMILY_KEYS:
                    bad("blocked family keys differ")
                if not isinstance(family["answers_hash"], str) \
                        or not _HEX64_RE.fullmatch(family["answers_hash"]):
                    bad("blocked family answers_hash")
                if family["answers_hash"] in seen_family_hashes:
                    bad("duplicate blocked family for an identity")
                seen_family_hashes.add(family["answers_hash"])
                self._validate_position_hashes(family, bad)
            # A latched family must rest on at least one counted
            # probe; the exact limit in force when it latched is
            # deployment configuration, not stored state, so it is
            # not re-derived here.
            if families and record["near_duplicate_probes"] < 1:
                bad("blocked family with no recorded probes")
        # Collect every recorded transcript, attributed by
        # identity: detection is identity-scoped, so attribution
        # is part of the state's integrity, not decoration.
        per_identity_transcripts = {}
        seen_pairs = set()
        proposal_total = 0
        for proposal_id, record in proposals.items():
            if not isinstance(proposal_id, str) or not proposal_id \
                    or len(proposal_id) > 128:
                bad("proposal id")
            if not isinstance(record, dict) \
                    or set(record) != _PROPOSAL_KEYS:
                bad("proposal record keys differ")
            if not _is_int(record["count"]) or record["count"] < 0:
                bad("proposal record fields")
            transcripts = record["transcripts"]
            if not isinstance(transcripts, list) \
                    or record["count"] != len(transcripts):
                bad("proposal count does not match its transcripts")
            for transcript in transcripts:
                if not isinstance(transcript, dict) \
                        or set(transcript) != _TRANSCRIPT_KEYS:
                    bad("transcript keys differ")
                if not isinstance(transcript["answers_hash"], str) \
                        or not _HEX64_RE.fullmatch(
                            transcript["answers_hash"]):
                    bad("transcript answers_hash")
                owner = transcript["identity"]
                if not isinstance(owner, str) \
                        or not _ID_RE.fullmatch(owner):
                    bad("transcript identity")
                pair = (owner, transcript["answers_hash"])
                if pair in seen_pairs:
                    bad("duplicate transcript recorded for an identity")
                seen_pairs.add(pair)
                self._validate_position_hashes(transcript, bad)
                per_identity_transcripts.setdefault(owner, []).append(
                    transcript)
            proposal_total += record["count"]
        for owner in per_identity_transcripts:
            if owner not in identities:
                bad("transcript recorded for an unknown identity")
        for identity, record in identities.items():
            owned = per_identity_transcripts.get(identity, [])
            if record["count"] != len(owned):
                bad("identity count does not match its transcripts")
            owned_hashes = {t["answers_hash"] for t in owned}
            for family in record["blocked_families"]:
                if family["answers_hash"] not in owned_hashes:
                    bad("blocked family is not a recorded transcript "
                        "of this identity")
        if sum(r["count"] for r in identities.values()) != proposal_total:
            bad("identity totals do not sum to the proposal totals")

    @staticmethod
    def _validate_position_hashes(record, bad) -> None:
        hashes = record["position_hashes"]
        if not isinstance(hashes, list) or len(hashes) > MAX_ANSWERS \
                or not all(isinstance(h, str) and _HEX64_RE.fullmatch(h)
                           for h in hashes):
            bad("position_hashes")

    def _save_locked(self, data) -> None:
        """Serialise and atomically replace the store file. The
        caller must already hold the directory flock. Advances
        the hash chain: the new head is computed over the head of
        the state being replaced and the new state's core."""
        self._validate(data)
        prev_head = data["chain_hash"]
        data["prev_chain_hash"] = prev_head
        data["chain_hash"] = _chain_hash(prev_head, _core_of(data))
        self._validate_chain(data)
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
        if len(raw) > MAX_STORE_BYTES:
            raise BudgetError(REASON_FULL,
                              "budget store exceeds the size cap")
        tmp = self.path.parent / (self.path.name + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
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

    # -- integrity surface (MEDIUM-1) ------------------------------------

    def head_hash(self) -> str:
        """The current hash-chain head: GENESIS_CHAIN_HASH when
        no state has been persisted yet, otherwise the chain_hash
        of the persisted state. This is the value an external
        anchor pins (alongside the ledger heads) so that a
        rollback or deletion of budgets.json is detectable at
        verifier startup. Raises BudgetError on a corrupt store:
        a head that cannot be validated names nothing."""
        if not self.path.exists():
            return GENESIS_CHAIN_HASH
        return self._load()["chain_hash"]

    def verify_integrity(self, expected_head=None) -> tuple:
        """Refusal reasons for the persisted state; () means the
        store is structurally valid and its hash chain recomputes.

        Detects: unreadable/invalid content, broken accounting
        invariants, and any edit that did not recompute the chain
        (including invariant-consistent edits). With
        ``expected_head`` (a head previously exported via
        head_hash() and pinned OUTSIDE this file, e.g. in an
        anchor), also detects rollback, replacement and deletion:
        a missing store under a non-genesis expected head returns
        ("budget_store_missing",), and a head that differs from
        the expected one returns ("budget_head_mismatch",).
        Without an expected head, a rollback to an earlier
        self-consistent state is NOT detectable from this file
        alone — that is exactly what the external anchor is for.
        Never raises for store-content problems."""
        if not self.path.exists():
            if expected_head is not None \
                    and expected_head != GENESIS_CHAIN_HASH:
                return (REASON_MISSING,)
            return ()
        try:
            data = self._load()
        except BudgetError as exc:
            return (exc.reason,)
        if expected_head is not None \
                and data["chain_hash"] != expected_head:
            return (REASON_HEAD_MISMATCH,)
        return ()

    # -- reads ------------------------------------------------------------

    def proposal_count(self, proposal_id) -> int:
        record = self._load()["proposals"].get(proposal_id)
        return record["count"] if record else 0

    def identity_count(self, identity) -> int:
        record = self._load()["identities"].get(identity)
        return record["count"] if record else 0

    def identity_probes(self, identity) -> int:
        """Near-duplicate probes counted against this identity,
        across all proposals (detection is identity-scoped)."""
        record = self._load()["identities"].get(identity)
        return record["near_duplicate_probes"] if record else 0

    def near_duplicate_probes(self, identity) -> int:
        """Alias for identity_probes(). NOTE the scope change
        from schema v1: probes were counted per proposal; they
        are now counted per identity, so this accessor takes an
        identity, not a proposal id."""
        return self.identity_probes(identity)

    def blocked_family_count(self, identity) -> int:
        record = self._load()["identities"].get(identity)
        return len(record["blocked_families"]) if record else 0

    def is_family_blocked(self, identity, answers) -> bool:
        """True when a transcript family has latched for this
        identity AND ``answers`` is a near-duplicate of the
        latched family anchor."""
        answers = list(answers)
        position_hashes = [_position_hash(a) for a in answers]
        record = self._load()["identities"].get(identity)
        if not record:
            return False
        return any(self._is_near_duplicate(
            position_hashes, family["position_hashes"])
            for family in record["blocked_families"])

    def is_blocked(self, identity, answers=None) -> bool:
        """True when this identity has any latched transcript
        family; with ``answers`` given, true only when that
        transcript is a near-duplicate of a latched family.
        (Schema v1 took a proposal id here; the latch is
        identity-scoped now, so the argument is an identity.)"""
        if answers is not None:
            return self.is_family_blocked(identity, answers)
        return self.blocked_family_count(identity) > 0

    # -- the budget gate ----------------------------------------------------

    def _is_near_duplicate(self, position_hashes, prior_hashes) -> bool:
        """A probe under EITHER rule: similarity fraction at/over
        the threshold, or absolute differing positions at/under
        ABSOLUTE_PROBE_MAX_DIFFERING (the small-set rule)."""
        return transcript_similarity(position_hashes, prior_hashes) \
            >= self.near_duplicate_threshold \
            or differing_positions(position_hashes, prior_hashes) \
            <= ABSOLUTE_PROBE_MAX_DIFFERING

    @staticmethod
    def _validate_arguments(identity, proposal_id, answers):
        if not isinstance(identity, str) or not _ID_RE.fullmatch(identity):
            raise ValueError("identity must be a well-formed actor id")
        if not isinstance(proposal_id, str) or not proposal_id \
                or len(proposal_id) > 128:
            raise ValueError("proposal_id must be non-empty text")
        if not isinstance(answers, (list, tuple)) \
                or len(answers) > MAX_ANSWERS \
                or not all(isinstance(a, str) for a in answers):
            raise ValueError("answers must be a bounded list of strings")
        answers = list(answers)
        return answers_hash_for(answers), [_position_hash(a)
                                            for a in answers]

    def _assess(self, data, identity, proposal_id, answers_hash,
                position_hashes):
        """Pure assessment against loaded state. Returns
        ("ok" | "probe" | "trip", anchor) where "probe" is a
        tolerated near-duplicate (anchor is the prior transcript
        it matched) and "trip" is a near-duplicate that reaches
        the probe limit. Raises BudgetError for the latch,
        replay and cap refusals. Check order (first refusal
        wins): blocked-family latch, replay, per-proposal cap,
        per-identity cap, near-duplicate accounting. Replay is
        checked before the caps because a replay is refused for
        what it is, not for budget state; the caps are checked
        before near-duplicate accounting so an over-budget
        transcript is not also counted as a probe. All
        comparisons are against the identity's transcripts across
        ALL proposals — the proposal label scopes only its cap.
        """
        ident = data["identities"].get(identity)
        priors = [t for record in data["proposals"].values()
                  for t in record["transcripts"]
                  if t["identity"] == identity]
        if ident is not None and any(
                self._is_near_duplicate(position_hashes,
                                        family["position_hashes"])
                for family in ident["blocked_families"]):
            raise BudgetError(
                REASON_ADAPTIVE,
                f"identity {identity} is blocked for this transcript "
                "family after repeated near-duplicate queries")
        if any(t["answers_hash"] == answers_hash for t in priors):
            raise BudgetError(
                REASON_REPLAY,
                "this exact transcript was already evaluated by "
                f"identity {identity}")
        record = data["proposals"].get(proposal_id)
        if record is not None \
                and record["count"] >= self.per_proposal_cap:
            raise BudgetError(
                REASON_PROPOSAL_BUDGET,
                f"proposal {proposal_id} has used its "
                f"{self.per_proposal_cap} evaluation budget")
        if ident is not None and ident["count"] >= self.per_identity_cap:
            raise BudgetError(
                REASON_IDENTITY_BUDGET,
                f"identity {identity} has used its "
                f"{self.per_identity_cap} evaluation budget")
        anchor = None
        anchor_key = None
        for prior in priors:
            if self._is_near_duplicate(position_hashes,
                                       prior["position_hashes"]):
                key = (transcript_similarity(
                           position_hashes, prior["position_hashes"]),
                       -differing_positions(
                           position_hashes, prior["position_hashes"]))
                if anchor_key is None or key > anchor_key:
                    anchor, anchor_key = prior, key
        if anchor is None:
            return "ok", None
        probes = ident["near_duplicate_probes"] if ident else 0
        if probes + 1 >= self.near_duplicate_limit:
            return "trip", anchor
        return "probe", anchor

    def check_only(self, identity, proposal_id, answers) -> None:
        """Phase one of the two-phase API (MEDIUM-2): raise
        BudgetError exactly when record() would refuse this
        query — blocked family, replay, either cap, or a probe
        that would trip the limit — and record NOTHING: no
        transcript, no count, no probe increment, no latch, no
        file write. The verifier calls this BEFORE opening the
        registry, validates the transcript itself (answer count),
        and only then calls record(): a garbage-length transcript
        refused by the verifier's own validation therefore burns
        no budget. Because check_only holds no lock, record()
        re-runs the full assessment under the flock; a state
        change between the phases fails closed at record time.
        """
        answers_hash, position_hashes = self._validate_arguments(
            identity, proposal_id, answers)
        data = self._load()
        outcome, _anchor = self._assess(
            data, identity, proposal_id, answers_hash, position_hashes)
        if outcome == "trip":
            raise BudgetError(
                REASON_ADAPTIVE,
                f"identity {identity} would reach "
                f"{self.near_duplicate_limit} near-duplicate queries "
                "with this transcript; further near-duplicate "
                "evaluations are refused")
        return None

    def record(self, identity, proposal_id, answers) -> None:
        """Phase two of the two-phase API, and the whole gate in
        one call: atomically check the budgets for one sealed
        evaluation and record it. Returns None when the
        evaluation may run; raises BudgetError (see the REASON_*
        codes) when it may not — in which case nothing is
        recorded, except that a near-duplicate probe that trips
        the limit still persists its probe count and the blocked
        family latch."""
        answers_hash, position_hashes = self._validate_arguments(
            identity, proposal_id, answers)
        lock_fd = os.open(self.path.parent,
                          os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = self._load()
            outcome, anchor = self._assess(
                data, identity, proposal_id, answers_hash,
                position_hashes)
            ident = data["identities"].get(identity)
            if outcome == "trip":
                # _assess found priors, so the identity record
                # exists. Persist the probe count and latch the
                # probed family; the tripping transcript itself is
                # NOT recorded (it was refused).
                ident["near_duplicate_probes"] += 1
                if all(family["answers_hash"] != anchor["answers_hash"]
                       for family in ident["blocked_families"]):
                    ident["blocked_families"].append(
                        {"answers_hash": anchor["answers_hash"],
                         "position_hashes": list(
                             anchor["position_hashes"])})
                self._save_locked(data)
                raise BudgetError(
                    REASON_ADAPTIVE,
                    f"identity {identity} reached "
                    f"{self.near_duplicate_limit} near-duplicate "
                    "queries; this transcript family is blocked for "
                    "the identity")
            if outcome == "probe":
                # A tolerated probe is still a spent evaluation:
                # count it, then fall through and record it (caps
                # were checked against the pre-probe counts).
                ident["near_duplicate_probes"] += 1
            record = data["proposals"].get(proposal_id)
            if record is None:
                record = {"count": 0, "transcripts": []}
                data["proposals"][proposal_id] = record
            record["transcripts"].append(
                {"answers_hash": answers_hash, "identity": identity,
                 "position_hashes": position_hashes})
            record["count"] += 1
            if ident is None:
                ident = {"count": 0, "near_duplicate_probes": 0,
                         "blocked_families": []}
                data["identities"][identity] = ident
            ident["count"] += 1
            self._save_locked(data)
            return None
        finally:
            os.close(lock_fd)

    def check_and_record(self, identity, proposal_id, answers) -> None:
        """The original single-phase gate; kept for current
        callers (trust/verifier_main.py) and tests. Identical to
        record(): check and record atomically under one flock.
        New verifier wiring should prefer check_only() before
        registry access and record() after transcript validation
        (see MEDIUM-2 in the module history)."""
        return self.record(identity, proposal_id, answers)
