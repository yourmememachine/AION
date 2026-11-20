"""The out-of-process verifier (prototype boundary).

Run as ``python -m trust.verifier_main``; one process per request,
single JSON document in on stdin, single JSON document out on
stdout. The process holds the signing key; the builder-side
client (trust/client.py) never does.

PROTOTYPE HONESTY STATEMENT — this is process isolation on one
machine under one OS user. It raises the bar from in-process
discipline to a separate-process boundary: the gate arithmetic
and the sealed-manifest-hash derivation run verifier-side, the
sealed scorer is never builder-side, and builder code cannot
construct a *valid* envelope without the key. On the signed gate
path the sealed score maps are no longer caller-asserted: an
accepted gate decision requires eval_evidence — two sealed-eval
attestation records the verifier re-verifies (MAC, ledger
presence, manifest equality with the live registry, signer
match to the attesting identity, distinctness — baseline and
candidate must be different records, not one record paired
with itself — and ledger order, baseline ledgered before
candidate) — and the caller's
baseline_sealed / candidate_sealed maps are REPLACED with maps
derived from those records ({"sealed": record.score}); caller
maps that disagree are simply overridden, derived wins. The
issue_attestation mode likewise derives its attestation from
verified, ledgered eval records: the sealed scores, the
reward-hacking (gap) check and the approve/reject decision are
all computed verifier-side, and callers may not select them.
That "derived" claim is scoped to the SEALED side only. What
remains caller-asserted, stated plainly: the PUBLIC aggregate
scores handed to issue_attestation are claims — the gap
check's sealed side is verifier-derived, its public side is
not independently verified — and, on the gate path, the
public score maps (baseline_public / candidate_public) and
the capability maps (capability_baseline /
capability_candidate) likewise remain caller-asserted trusted
inputs: no verifier-side source for them exists in this
design (eval/gate.py declares the capability snapshot a
trusted input), and they are NOT verifier-computed evidence.
Lying public or capability maps cannot by themselves create
an accept — a sealed gain, a derived attestation and a MAC
are still required — but they are trusted, not verified, and
no wording here should be read as claiming otherwise. A
caller can always submit an unsigned claim via submit_claim,
which the verifier ledgers without signing; a claim grants
nothing. It is NOT a
separate-machine or separate-user trust domain: any code
running as the same OS user can read the 0600 key file and the
registry file directly. A real boundary requires a separate OS
user (or machine) for the verifier, as
signing/gate_decision.py's docstring already states. Threat
model, matching that docstring: evolved or convenience code
paths that hand-build an accepted GateDecision or present
unsigned/fake results — not a fully malicious same-user process,
which this prototype cannot and does not claim to stop.

Configuration comes ONLY from the environment, set by the
orchestrator at launch — never from the request. A request that
tries to supply signer identity, key path, registry location,
purpose or TTL is a protocol error (strict key sets), not a
silently ignored field:

  AION_VERIFIER_KEY_PATH    absolute path to the 0600 key file
  AION_VERIFIER_SIGNER_ID   signer_id stamped into every signature
  AION_VERIFIER_ACTOR_ID    registry actor for logged sealed access
  AION_REGISTRY_DIR         registry directory the verifier opens
  AION_VERIFIER_TTL_SECONDS optional, default 900, signing bounds
  AION_VERIFIER_PURPOSE     optional: memory-commit (default) | ship
  AION_DEPLOYMENT_MODE      REQUIRED: production | research.
                            The mode must be set explicitly:
                            a missing, blank, unknown or
                            malformed value (including whitespace-
                            padded or wrongly-cased spellings)
                            refuses startup fail-closed
                            (deployment_mode_refused) — there is
                            no default mode. Research mode is
                            entered only when it is explicitly
                            configured. Production makes anchoring
                            MANDATORY and fail-closed: both anchor
                            paths below must be configured, and
                            the INIT ceremony flags are refused —
                            a production verifier never bootstraps
                            an anchor; ceremonies are operator acts
                            performed outside production steady
                            state. Research mode with anchoring
                            unconfigured is NOT rollback-protected:
                            its ledgers can be deleted or rolled
                            back undetectably, and it must never
                            be described as rollback-protected.
  AION_VERIFIER_PROPOSAL_BUDGET optional, per-proposal sealed_eval
                            query cap (default 25)
  AION_VERIFIER_IDENTITY_BUDGET optional, per-identity sealed_eval
                            query cap (default 500)
  AION_ANCHOR_PATH          optional: external anchor file for the
                            signing ledger (see trust/anchoring.py);
                            when set, startup verifies the anchor
                            and every signature updates it
  AION_ANCHOR_INIT          optional: "1" allows ONE bootstrap
                            invocation to create the anchor for an
                            empty, unanchored ledger
  AION_BUDGETS_ANCHOR_PATH  optional: external anchor file for the
                            query-budget store's hash-chain head;
                            must live OUTSIDE AION_VERIFIER_HOME.
                            When set, startup refuses if the anchor
                            is missing without the INIT flag below,
                            or if an established budget store
                            is missing, rolled back or deleted, and
                            every recorded query advances the anchor
  AION_BUDGETS_ANCHOR_INIT  optional: "1" allows ONE bootstrap
                            invocation to create the budgets anchor
                            at the store's GENESIS head only (empty
                            store); pinning a non-genesis head under
                            INIT is refused (anchor_refused), so a
                            deleted anchor cannot launder a rolled-
                            back budget store into a fresh pin —
                            recovery of a non-genesis store goes
                            through an audited path only
  AION_VERIFIER_HOME        REQUIRED: signing-ledger directory;
                            the service refuses to run without it

Exit codes: 0 = protocol success (INCLUDING a signed gate
rejection and a verify_envelope verdict of valid:false); 2 =
malformed request (unsigned error document); 3 = verifier-side
failure — misconfiguration, unsafe/missing key, untrusted
registry, signer conflict (unsigned error document). Nothing
unsigned is ever representable as a decision.

The verifier never touches the network, never spawns processes,
and writes only where the registry itself writes (its access log
and file, plus the quarantine file a corrupt registry document
is moved to) plus its own signing ledger. AION_VERIFIER_HOME is
REQUIRED: the service refuses to run without its ledger, so "a
signature with no ledger entry" stays meaningful. That "only"
is a property of this code under review, not a runtime sandbox
— nothing stops a *modified* verifier, and the docs must not
imply otherwise.
"""

from __future__ import annotations

import json
import math
import re
import os
import sys
import traceback
from pathlib import Path

from eval.factory import FactoryError, assess_gap
from eval.gate import GateInputError, VerifierAttestation, \
    evaluate_self_change
from eval.registry import CorruptRegistryError, EvalRegistry, \
    EvaluationError
from signing.attestation import attestation_envelope_from_dict, \
    attestation_envelope_to_dict, sign_attestation
from signing.gate_decision import (
    PURPOSE_MEMORY_COMMIT,
    PURPOSE_SHIP,
    TTL_MAX_SECONDS,
    TTL_MIN_SECONDS,
    SigningError,
    _canonical,
    _check_hex64,
    _check_id,
    _now,
    _parse_time,
    _sha256,
    envelope_to_dict,
    load_signing_key,
    sign_gate_decision,
    verify_signed_decision,
)
from trust import protocol
from trust.attestation import answers_hash_for, registry_digest_for, \
    sign_eval_attestation, verify_eval_attestation
from trust.anchoring import AnchorError, initialise_anchor, \
    update_anchor, verify_anchor
from trust.budgets import BudgetError, BudgetStore, \
    DEFAULT_PER_IDENTITY_CAP, DEFAULT_PER_PROPOSAL_CAP, \
    GENESIS_CHAIN_HASH
from trust.ledger import SigningLedger
from trust.pathpolicy import canonicalise as _policy_canonicalise

GENESIS_HASH = "0" * 64
MAX_ANSWER_CHARS = 8000
MAX_ANSWERS = 500
_REFUSED_TEST_KEYS = (
    bytes(range(32)), bytes(range(32, 64)),
    b"\x00" * 32, b"\xff" * 32,
)

_GATE_BODY_KEYS = {"proposal_id", "builder_ids", "reviewer_ids",
                   "baseline_public", "candidate_public",
                   "baseline_sealed", "candidate_sealed",
                   "capability_baseline", "capability_candidate",
                   "attestation", "changed_paths", "verifier_note",
                   "manifest_hash", "signed_attestation",
                   "eval_evidence"}
_ATTESTATION_KEYS = {"verifier_id", "decision", "sealed_hash",
                     "reward_hacking_checked", "evidence_ref",
                     "attested_at"}
_EXPECTED_KEYS = {"proposal_id", "purpose", "attestation_hash",
                  "gate_inputs_hash", "entry_content_hash",
                  "signer_id"}


class _Refuse(Exception):
    """Verifier-side refusal carrying an exit code and error code."""

    def __init__(self, exit_code, code, detail=""):
        super().__init__(code)
        self.exit_code = exit_code
        self.code = code
        self.detail = detail


def _malformed(code, detail=""):
    return _Refuse(2, code, detail)


def _config(code, detail=""):
    return _Refuse(3, code, detail)


class _Config:
    def __init__(self, signing_key, signer_id, actor, registry_dir,
                 ttl_seconds, purpose, home,
                 proposal_budget=DEFAULT_PER_PROPOSAL_CAP,
                 identity_budget=DEFAULT_PER_IDENTITY_CAP,
                 anchor_path=None, anchor_init=False,
                 budgets_anchor_path=None, budgets_anchor_init=False,
                 deployment_mode="research"):
        self.signing_key = signing_key
        self.signer_id = signer_id
        self.actor = actor
        self.registry_dir = registry_dir
        self.ttl_seconds = ttl_seconds
        self.purpose = purpose
        self.home = home
        self.proposal_budget = proposal_budget
        self.identity_budget = identity_budget
        self.anchor_path = anchor_path
        self.anchor_init = anchor_init
        self.budgets_anchor_path = budgets_anchor_path
        self.budgets_anchor_init = budgets_anchor_init
        self.deployment_mode = deployment_mode


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _load_config() -> _Config:
    env = os.environ
    key_path = env.get("AION_VERIFIER_KEY_PATH", "")
    signer_id = env.get("AION_VERIFIER_SIGNER_ID", "")
    actor = env.get("AION_VERIFIER_ACTOR_ID", "")
    registry_dir = env.get("AION_REGISTRY_DIR", "")
    home = env.get("AION_VERIFIER_HOME", "")
    purpose = env.get("AION_VERIFIER_PURPOSE", PURPOSE_MEMORY_COMMIT)
    if not key_path or not signer_id or not actor or not registry_dir \
            or not home:
        # AION_VERIFIER_HOME is REQUIRED: a verifier that signs
        # without ledgering breaks the ledger's core inference.
        raise _config("verifier_misconfigured",
                      "required verifier configuration is missing")
    if not Path(key_path).is_absolute():
        raise _config("verifier_misconfigured",
                      "the key path must be absolute")
    if not _ID_RE.fullmatch(signer_id) or not _ID_RE.fullmatch(actor):
        raise _config("verifier_misconfigured",
                      "signer/actor ids must be well-formed ids")
    if purpose not in (PURPOSE_MEMORY_COMMIT, PURPOSE_SHIP):
        raise _config("verifier_misconfigured", "unknown purpose")
    deployment_mode = env.get("AION_DEPLOYMENT_MODE", "")
    if deployment_mode not in ("research", "production"):
        # Fail-closed deployment mode (Trust Boundary v3.1,
        # item 1): the mode is REQUIRED and must be spelled
        # exactly "production" or "research" — no default, no
        # stripping, no case-folding. A missing, blank, unknown
        # or malformed mode refuses startup rather than silently
        # selecting the weaker (research) mode; research is
        # entered only via this explicit authorised value.
        raise _config("deployment_mode_refused",
                      "AION_DEPLOYMENT_MODE must be set explicitly "
                      "to 'production' or 'research'; a missing, "
                      "blank, unknown or malformed mode is refused "
                      "fail-closed")
    ttl_raw = env.get("AION_VERIFIER_TTL_SECONDS", "")
    if ttl_raw:
        if not ttl_raw.isdigit():
            raise _config("verifier_misconfigured", "bad TTL")
        ttl = int(ttl_raw)
        if not (TTL_MIN_SECONDS <= ttl <= TTL_MAX_SECONDS):
            raise _config("verifier_misconfigured", "TTL out of bounds")
    else:
        ttl = 900
    try:
        signing_key = load_signing_key(
            key_path, forbidden_roots=(Path(registry_dir),))
    except SigningError:
        raise _config("verifier_misconfigured",
                      "signing key is missing or unsafe")
    if signing_key.key in _REFUSED_TEST_KEYS:
        raise _config("verifier_misconfigured",
                      "refusing a known test key")
    # Scrub the key path from the environment once loaded; the key
    # bytes live only in the SigningKey object from here.
    env.pop("AION_VERIFIER_KEY_PATH", None)
    proposal_budget = DEFAULT_PER_PROPOSAL_CAP
    identity_budget = DEFAULT_PER_IDENTITY_CAP
    for env_name, attr in (("AION_VERIFIER_PROPOSAL_BUDGET",
                            "proposal_budget"),
                           ("AION_VERIFIER_IDENTITY_BUDGET",
                            "identity_budget")):
        raw_budget = env.get(env_name, "")
        if raw_budget:
            if not raw_budget.isdigit() or int(raw_budget) < 1:
                raise _config("verifier_misconfigured",
                              "bad query budget")
            if attr == "proposal_budget":
                proposal_budget = int(raw_budget)
            else:
                identity_budget = int(raw_budget)
    anchor_path = env.get("AION_ANCHOR_PATH", "")
    anchor_init_raw = env.get("AION_ANCHOR_INIT", "")
    if anchor_init_raw not in ("", "0", "1"):
        raise _config("verifier_misconfigured", "bad AION_ANCHOR_INIT")
    anchor_init = anchor_init_raw == "1"
    if deployment_mode == "production":
        # Production is fail-closed about rollback evidence: both
        # anchors must be configured, and the INIT ceremony flags
        # are refused outright — a production verifier never
        # bootstraps. Explicitly configured research mode imposes
        # neither requirement and is NOT rollback-protected when
        # anchoring is unconfigured.
        if not anchor_path:
            raise _config("verifier_misconfigured",
                          "production mode requires AION_ANCHOR_PATH")
        if anchor_init:
            raise _config("verifier_misconfigured",
                          "production mode refuses AION_ANCHOR_INIT; "
                          "anchor ceremonies run outside production")
    if anchor_path and not Path(anchor_path).is_absolute():
        raise _config("verifier_misconfigured",
                      "the anchor path must be absolute")
    if anchor_init and not anchor_path:
        raise _config("verifier_misconfigured",
                      "AION_ANCHOR_INIT requires AION_ANCHOR_PATH")
    if anchor_path:
        # Startup anchor verification: an established signing
        # ledger whose external anchor is missing, rolled back or
        # mismatched refuses to sign anything at all.
        try:
            anchor_ledger = SigningLedger(home)
        except Exception:
            raise _config(
                "ledger_failed",
                "the signing ledger could not be opened for anchor "
                "verification")
        try:
            anchor_reasons = verify_anchor(
                anchor_ledger, anchor_path, kind="signing")
        except AnchorError:
            raise _config("anchor_refused",
                          "the anchor path is invalid for this "
                          "ledger")
        if anchor_reasons == ("anchor_missing",) and anchor_init:
            try:
                initialise_anchor(anchor_ledger, anchor_path,
                                  kind="signing", recorded_at=_now())
            except AnchorError:
                raise _config("anchor_refused",
                              "anchor bootstrap failed")
            anchor_reasons = ()
        if anchor_reasons:
            raise _config("anchor_refused",
                          ",".join(anchor_reasons))
    budgets_anchor_path = env.get("AION_BUDGETS_ANCHOR_PATH", "")
    budgets_init_raw = env.get("AION_BUDGETS_ANCHOR_INIT", "")
    if budgets_init_raw not in ("", "0", "1"):
        raise _config("verifier_misconfigured",
                      "bad AION_BUDGETS_ANCHOR_INIT")
    budgets_anchor_init = budgets_init_raw == "1"
    if deployment_mode == "production":
        if not budgets_anchor_path:
            raise _config("verifier_misconfigured",
                          "production mode requires "
                          "AION_BUDGETS_ANCHOR_PATH")
        if budgets_anchor_init:
            raise _config("verifier_misconfigured",
                          "production mode refuses "
                          "AION_BUDGETS_ANCHOR_INIT; anchor ceremonies "
                          "run outside production")
    if budgets_anchor_path and not Path(budgets_anchor_path).is_absolute():
        raise _config("verifier_misconfigured",
                      "the budgets anchor path must be absolute")
    if budgets_anchor_init and not budgets_anchor_path:
        raise _config("verifier_misconfigured",
                      "AION_BUDGETS_ANCHOR_INIT requires "
                      "AION_BUDGETS_ANCHOR_PATH")
    if budgets_anchor_path:
        # Startup budgets-anchor verification, mirroring the
        # signing-ledger anchor: the budget store's hash-chain head
        # is pinned OUTSIDE the verifier home, so deleting or
        # rolling back budgets.json (which would silently reset
        # every query budget) refuses startup instead.
        home_resolved = Path(home).resolve()
        budgets_anchor_resolved = Path(budgets_anchor_path).resolve()
        if budgets_anchor_resolved == home_resolved \
                or home_resolved in budgets_anchor_resolved.parents:
            raise _config("verifier_misconfigured",
                          "the budgets anchor must live outside "
                          "the verifier home")
        try:
            budget_store = BudgetStore(
                Path(home) / "budgets.json",
                per_proposal_cap=proposal_budget,
                per_identity_cap=identity_budget)
            budgets_head = budget_store.head_hash()
            budgets_integrity = budget_store.verify_integrity()
        except BudgetError as exc:
            raise _config("anchor_refused",
                          f"budget store refused: {exc.reason}")
        if budgets_integrity:
            raise _config("anchor_refused",
                          ",".join(budgets_integrity))
        anchored_head = _read_budgets_anchor(budgets_anchor_path)
        if anchored_head is not None:
            if budgets_head != anchored_head:
                raise _config(
                    "anchor_refused",
                    "budgets anchor head mismatch: the budget "
                    "store is missing, rolled back or reset")
        elif budgets_anchor_init:
            # INIT guard (Trust Boundary v3, item 3): bootstrap may
            # pin ONLY the genesis head (empty store), mirroring
            # trust/anchoring.py initialise_anchor's established-
            # ledger guard. Pinning a non-genesis head here would
            # let an operator (or an attacker with env control)
            # delete the anchor and re-pin a rolled-back budget
            # store, laundering a budget reset; a non-genesis store
            # with a missing anchor is a refusal, and its recovery
            # goes through an audited path only.
            if budgets_head != GENESIS_CHAIN_HASH:
                raise _config(
                    "anchor_refused",
                    "anchor_missing_established_budgets: "
                    "AION_BUDGETS_ANCHOR_INIT may pin only the "
                    "genesis head of an empty budget store")
            _write_budgets_anchor(budgets_anchor_path, budgets_head)
        else:
            # A configured anchor that does not exist is a refusal
            # even for a genesis store — mirroring the signing
            # ledger — so deleting budgets.json TOGETHER with its
            # anchor cannot silently reset every budget; only the
            # INIT ceremony may create an anchor.
            raise _config(
                "anchor_refused",
                "anchor_missing_established_budgets"
                if budgets_head != GENESIS_CHAIN_HASH
                else "anchor_missing")
    return _Config(signing_key, signer_id, actor, registry_dir, ttl,
                   purpose, home,
                   proposal_budget=proposal_budget,
                   identity_budget=identity_budget,
                   anchor_path=anchor_path or None,
                   anchor_init=anchor_init,
                   budgets_anchor_path=budgets_anchor_path or None,
                   budgets_anchor_init=budgets_anchor_init,
                   deployment_mode=deployment_mode)


def _update_anchor(config: _Config) -> None:
    """Advance the signing ledger's external anchor after an
    append. A failed update withholds the signature: the ledger
    honestly records that a signature was made and not returned
    (the same philosophy as the oversize-response path)."""
    if not config.anchor_path:
        return
    try:
        update_anchor(SigningLedger(config.home), config.anchor_path,
                      kind="signing", recorded_at=_now())
    except AnchorError:
        raise _config(
            "ledger_failed",
            "the signature was ledgered but its anchor update "
            "failed; refusing to return it")


def _read_budgets_anchor(path):
    """Return the pinned budget-store head, or None when no anchor
    file exists yet. A malformed anchor refuses: an operator must
    repair it deliberately, never have it silently ignored."""
    anchor_file = Path(path)
    if not anchor_file.exists():
        return None
    try:
        doc = json.loads(anchor_file.read_text(encoding="utf-8"))
    except Exception:
        raise _config("anchor_refused", "budgets anchor malformed")
    if not isinstance(doc, dict) or doc.get("v") != "budgets-anchor/1" \
            or not isinstance(doc.get("head"), str) \
            or len(doc["head"]) != 64:
        raise _config("anchor_refused", "budgets anchor malformed")
    return doc["head"]


def _write_budgets_anchor(path, head) -> None:
    anchor_file = Path(path)
    tmp = anchor_file.with_name(anchor_file.name + ".tmp")
    tmp.write_text(_canonical({"v": "budgets-anchor/1", "head": head,
                               "anchored_at": _now()}).decode("utf-8"),
                   encoding="utf-8")
    os.replace(tmp, anchor_file)


def _update_budgets_anchor(config: _Config, store) -> None:
    """Advance the budgets anchor after a recorded query. A failed
    update refuses the request: the query was recorded, and the
    verifier says so rather than returning an evaluation whose
    budget accounting is unpinned."""
    if not config.budgets_anchor_path:
        return
    try:
        _write_budgets_anchor(config.budgets_anchor_path,
                              store.head_hash())
    except Exception:
        raise _config(
            "ledger_failed",
            "the query was recorded but its budgets anchor update "
            "failed; refusing to return the evaluation")


def _open_registry(config: _Config) -> EvalRegistry:
    try:
        return EvalRegistry(config.registry_dir)
    except (CorruptRegistryError, ValueError, OSError):
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")


def _registry_snapshot(config: _Config):
    """Return (registry, metadata, manifest_hash) from a FRESH
    registry instance, retrying transient staleness.

    Staleness under concurrency is a retryable race, not
    corruption: an EvalRegistry instance snapshots state at
    construction, and a concurrent verifier process appending
    access-log entries makes this instance's save raise
    CorruptRegistryError ("registry changed on disk since this
    instance loaded it"). Treating that as registry_untrusted
    made refusal codes nondeterministic under concurrent
    issuance (the loser of a race was refused for the wrong
    reason). The access log records attempts by design, so
    retries are semantically safe: each attempt reloads fresh
    and re-records its access. Genuine corruption persists
    across fresh loads, so after all attempts fail the refusal
    is registry_untrusted — deterministically."""
    for _attempt in range(12):
        registry = _open_registry(config)
        try:
            metadata = registry.list_sealed_metadata(config.actor)
            manifest_hash = registry.sealed_manifest_hash(config.actor)
        except (CorruptRegistryError, ValueError):
            continue
        return registry, metadata, manifest_hash
    raise _config("registry_untrusted",
                  "the sealed registry failed validation")


def _registry_digest(registry: EvalRegistry, actor, manifest_hash) -> str:
    log = registry.access_log()
    head = log[-1]["entry_hash"] if log else GENESIS_HASH
    version = log[-1]["sealed_version"] if log else 0
    return registry_digest_for(manifest_hash=manifest_hash,
                               sealed_version=version, log_head=head,
                               log_seq=len(log))


def _attestation_from(body_value):
    if body_value is None:
        return None
    if not isinstance(body_value, dict) \
            or set(body_value) != _ATTESTATION_KEYS:
        raise _malformed("malformed_request",
                         "attestation has missing or unknown keys")
    attestation = VerifierAttestation(
        verifier_id=body_value["verifier_id"],
        decision=body_value["decision"],
        sealed_hash=body_value["sealed_hash"],
        reward_hacking_checked=body_value["reward_hacking_checked"],
        evidence_ref=body_value["evidence_ref"],
        attested_at=body_value["attested_at"])
    # Field FORMS are protocol, field VALUES are gate decisions:
    # an ill-typed attestation is a malformed request (exit 2),
    # while a well-typed attestation the gate dislikes earns a
    # signed rejection. Without this split, ill-typed fields only
    # fail later, inside the signer, mislabelled as its error.
    try:
        _check_hex64(attestation.sealed_hash, "sealed hash")
        _parse_time(attestation.attested_at, "attested_at")
    except SigningError:
        raise _malformed("malformed_request",
                         "attestation fields are ill-typed")
    if not isinstance(attestation.verifier_id, str) \
            or not _ID_RE.fullmatch(attestation.verifier_id) \
            or attestation.decision not in ("approve", "reject") \
            or not isinstance(attestation.reward_hacking_checked, bool) \
            or not isinstance(attestation.evidence_ref, str) \
            or not attestation.evidence_ref:
        raise _malformed("malformed_request",
                         "attestation fields are ill-typed")
    return attestation


def _ledger_entries(config: _Config) -> list:
    try:
        return SigningLedger(config.home).entries()
    except Exception:
        raise _config("ledger_failed",
                      "the signing ledger could not be read; "
                      "refusing to trust eval evidence")


def _ledger_seq_for(entries, payload_hash):
    """Seq of the signing-ledger "sealed-eval" sign entry for a
    payload hash, or None when the record was not ledgered by
    this service. The first matching entry defines issuance
    order for the pair checks below."""
    for entry in entries:
        if entry.get("kind") == "sign" \
                and entry.get("format") == "sealed-eval" \
                and entry.get("payload_hash") == payload_hash:
            seq = entry.get("seq")
            return seq if isinstance(seq, int) \
                and not isinstance(seq, bool) else None
    return None


def _check_eval_pair_distinct_and_ordered(baseline_record,
                                          candidate_record,
                                          baseline_seq,
                                          candidate_seq) -> None:
    """HIGH-5a binding: a baseline/candidate pair must be two
    DISTINCT records, baseline ledgered BEFORE candidate. One
    record paired with itself (assess_gap(x, x, ...) style
    self-pairing) derives nothing about a change, and a
    candidate ledgered before its baseline cannot be evidence
    that the baseline came first. Either case is an unsigned
    config-class refusal — no attestation, no gate signature."""
    baseline_hash = baseline_record.get("payload_hash") \
        if isinstance(baseline_record, dict) else None
    candidate_hash = candidate_record.get("payload_hash") \
        if isinstance(candidate_record, dict) else None
    if baseline_hash is not None and baseline_hash == candidate_hash:
        raise _config(
            "eval_evidence_self_paired",
            "baseline and candidate eval records must be "
            "distinct; the same record cannot serve as both")
    if baseline_seq is None or candidate_seq is None \
            or not baseline_seq < candidate_seq:
        raise _config(
            "eval_evidence_out_of_order",
            "the baseline eval record must precede the candidate "
            "eval record in the signing ledger")


def _scope_root(scope) -> str:
    """Root proposal of a budget scope string: strip ONE trailing
    ":baseline" / ":candidate" suffix, if present."""
    if not isinstance(scope, str):
        return ""
    for suffix in (":baseline", ":candidate"):
        if scope.endswith(suffix):
            return scope[: -len(suffix)]
    return scope


def _check_sealed_eval_scope(scope) -> None:
    """Validate a sealed_eval proposal_id as a signable scope.

    The value becomes the signed eval record's ``scope`` verbatim,
    and issuance later requires the scope ROOT to be the proposal
    id handed to sign_attestation, whose payload projection
    enforces signing's id grammar via _check_id
    (signing/gate_decision.py: ^[a-z0-9_-]{1,64}$, applied in
    signing/attestation.py attestation_payload). A scope is that
    proposal-id grammar plus ONE optional ":baseline" /
    ":candidate" role suffix — the pair scopes the evidence flow
    legitimately uses — so the root (scope stripped of that one
    suffix) must satisfy _check_id exactly. Anything else
    (newlines, homoglyphs, stray colons, uppercase, an over-long
    root) would mint a record issuance can never consume, so it
    is refused here, before any budget is recorded or anything
    is signed. The absent-proposal default "unscoped" satisfies
    the grammar, so the unscoped path stays signable."""
    if not isinstance(scope, str) or not scope:
        raise _malformed("malformed_request",
                         "proposal_id must be non-empty text")
    try:
        _check_id(_scope_root(scope), "proposal id")
    except SigningError:
        raise _malformed(
            "malformed_request",
            "proposal_id must match ^[a-z0-9_-]{1,64}$ with an "
            "optional :baseline or :candidate suffix")


def _verify_eval_record(config: _Config, record, *, manifest_hash,
                        entries, expected_signer_id):
    """Verify one sealed-eval attestation record verifier-side:
    MAC under this service's key (verify_eval_attestation), signer
    match to expected_signer_id, manifest equality with the live
    registry, and presence in this service's own signing ledger as
    a format "sealed-eval" sign entry. Any failure is a
    config-class refusal (exit 3, unsigned): evidence that cannot
    be verified must never be laundered into a signed artefact,
    not even a signed rejection built on it. Returns
    (payload, ledger_seq) on success."""
    if not isinstance(record, dict):
        raise _config("eval_evidence_unverifiable",
                      "an eval record is not an object")
    try:
        reasons = verify_eval_attestation(
            record, signing_key=config.signing_key,
            expected_signer_id=expected_signer_id)
    except SigningError:
        raise _config("eval_evidence_unverifiable",
                      "an eval record is malformed")
    if reasons:
        raise _config(
            "eval_evidence_unverifiable",
            "an eval record failed verification: "
            + ",".join(reasons))
    payload = record.get("payload")
    if not isinstance(payload, dict) \
            or payload.get("signer_id") != expected_signer_id:
        raise _config("eval_evidence_unverifiable",
                      "an eval record's signer does not match")
    if payload.get("manifest_hash") != manifest_hash:
        raise _config(
            "eval_evidence_unverifiable",
            "an eval record is bound to a different sealed "
            "manifest than the live registry")
    ledger_seq = _ledger_seq_for(entries, record.get("payload_hash"))
    if ledger_seq is None:
        raise _config(
            "eval_record_not_ledgered",
            "an eval record has no sealed-eval entry in the "
            "signing ledger; it was not issued by this service")
    return payload, ledger_seq


def _verified_eval_pair(config: _Config, baseline_record,
                        candidate_record, *, expected_signer_id):
    """Open the live registry and verify a baseline/candidate pair
    of eval records against it. Returns (baseline_payload,
    candidate_payload, manifest_hash)."""
    _registry, metadata, manifest_hash = _registry_snapshot(config)
    if not metadata:
        raise _config("registry_empty", "the sealed set is empty")
    entries = _ledger_entries(config)
    baseline, baseline_seq = _verify_eval_record(
        config, baseline_record, manifest_hash=manifest_hash,
        entries=entries, expected_signer_id=expected_signer_id)
    candidate, candidate_seq = _verify_eval_record(
        config, candidate_record, manifest_hash=manifest_hash,
        entries=entries, expected_signer_id=expected_signer_id)
    _check_eval_pair_distinct_and_ordered(
        baseline_record, candidate_record, baseline_seq, candidate_seq)
    if baseline["manifest_hash"] != candidate["manifest_hash"]:
        raise _config(
            "eval_evidence_unverifiable",
            "the eval records are bound to different sealed "
            "manifests")
    return baseline, candidate, manifest_hash


def _public_score(body: dict, field: str):
    value = body[field]
    if isinstance(value, bool) \
            or not isinstance(value, (int, float)):
        raise _malformed("malformed_request",
                         f"{field} must be a number in [0, 1]")
    try:
        score = float(value)
    except OverflowError:
        raise _malformed("malformed_request",
                         f"{field} must be a number in [0, 1]")
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise _malformed("malformed_request",
                         f"{field} must be a number in [0, 1]")
    return score


def _mode_gate(config: _Config, body: dict) -> dict:
    required = _GATE_BODY_KEYS - {"manifest_hash", "signed_attestation",
                                  "eval_evidence"}
    if not required <= set(body) <= _GATE_BODY_KEYS:
        raise _malformed("malformed_request",
                         "gate body has missing or unknown keys")
    if config.purpose == PURPOSE_SHIP:
        if "manifest_hash" not in body:
            raise _malformed("malformed_request",
                             "ship gate requests must bind a manifest_hash")
        try:
            from signing.gate_decision import _check_hex64
            _check_hex64(body["manifest_hash"], "manifest hash")
        except SigningError:
            raise _malformed("malformed_request",
                             "manifest_hash must be a hex64 string")
    if config.purpose != PURPOSE_SHIP and "manifest_hash" in body:
        raise _malformed("malformed_request",
                         "manifest_hash is only for ship gate requests")
    builder_ids = body["builder_ids"]
    if isinstance(builder_ids, (list, tuple)) \
            and config.signer_id in builder_ids:
        raise _config("signer_conflict",
                      "the configured signer is listed as a builder")
    reviewer_ids = body["reviewer_ids"]
    if isinstance(reviewer_ids, (list, tuple)) \
            and config.signer_id in reviewer_ids:
        raise _config("signer_conflict",
                      "the configured signer is listed as a reviewer")
    attestation = _attestation_from(body["attestation"])
    if attestation is not None \
            and attestation.verifier_id == config.signer_id:
        raise _config("signer_conflict",
                      "the signer cannot attest to its own gate run")
    changed_paths = body["changed_paths"]
    if isinstance(changed_paths, (list, tuple)):
        for path in changed_paths:
            # The protected-path check inside the gate matches
            # literal spellings; non-canonical spellings of a
            # protected path ("../eval/gate.py", "EVAL/gate.py")
            # would slip it. The gate module is protected and
            # cannot be fixed this cycle, so the verifier accepts
            # only canonical spellings — anything else is a
            # malformed request, never a signed accept.
            if not isinstance(path, str):
                raise _malformed("malformed_request",
                                 "changed_paths must be strings")
            try:
                canonical = _policy_canonicalise(path)
            except ValueError:
                raise _malformed(
                    "malformed_request",
                    "changed_paths must use canonical spellings")
            if canonical != path \
                    or path.split("/", 1)[0] != path.split("/", 1)[0].lower():
                raise _malformed(
                    "malformed_request",
                    "changed_paths must use canonical spellings")
    signed_attestation = None
    if "signed_attestation" in body:
        try:
            signed_attestation = attestation_envelope_from_dict(
                body["signed_attestation"])
        except SigningError:
            raise _malformed("bad_signed_attestation",
                             "signed attestation envelope is malformed")
        if attestation is None \
                or signed_attestation.attestation != attestation:
            raise _malformed(
                "bad_signed_attestation",
                "signed attestation does not wrap the presented "
                "attestation")
        if config.purpose == PURPOSE_SHIP \
                and signed_attestation.manifest_hash \
                != body["manifest_hash"]:
            raise _malformed(
                "bad_signed_attestation",
                "signed attestation is bound to a different "
                "artifact than this ship request")
    registry, metadata, manifest_hash = _registry_snapshot(config)
    if not metadata:
        # An empty (or freshly created, e.g. by a config typo in
        # the registry path) sealed set must never yield a signed
        # accept bound to the empty-set hash.
        raise _config("registry_empty", "the sealed set is empty")
    # -- verifier-produced evidence (eval_evidence) -------------------
    # When present, the two eval records are verified exactly as
    # issue_attestation verifies them (MAC, ledger presence,
    # manifest equality with the live registry), with the signer
    # match taken against the ATTESTING identity — the presented
    # attestation's verifier, whose signed envelope is checked
    # above and who must differ from this gate signer (see the
    # signer-conflict checks). The caller's sealed score maps are
    # then REPLACED by maps derived from the records: derived
    # wins, silently, by design — a caller map that lies about
    # the sealed scores has no effect on the signed path.
    # The gate does NOT consume these records (contrast
    # _mode_issue_attestation, which consumes at issuance): the
    # attestation's evidence_ref flow legitimately re-presents
    # the records here, and that reuse is safe because the
    # records are bound to the single attestation being gated —
    # evidence_ref must name exactly these two payload hashes,
    # their scope roots are checked against this proposal below,
    # and their signer must match the attesting identity.
    # Consumption at the gate would break that flow without
    # binding the records to anything new.
    baseline_sealed = body["baseline_sealed"]
    candidate_sealed = body["candidate_sealed"]
    eval_payload_hashes = None
    if "eval_evidence" in body:
        evidence = body["eval_evidence"]
        if not isinstance(evidence, dict) \
                or set(evidence) != {"baseline", "candidate"}:
            raise _malformed(
                "malformed_request",
                "eval_evidence must carry exactly baseline and "
                "candidate records")
        if attestation is None:
            raise _malformed(
                "malformed_request",
                "eval_evidence requires a presented attestation "
                "whose signer the records are matched against")
        entries = _ledger_entries(config)
        baseline_payload, baseline_seq = _verify_eval_record(
            config, evidence["baseline"], manifest_hash=manifest_hash,
            entries=entries, expected_signer_id=attestation.verifier_id)
        candidate_payload, candidate_seq = _verify_eval_record(
            config, evidence["candidate"],
            manifest_hash=manifest_hash, entries=entries,
            expected_signer_id=attestation.verifier_id)
        _check_eval_pair_distinct_and_ordered(
            evidence["baseline"], evidence["candidate"],
            baseline_seq, candidate_seq)
        # Defence in depth (rev-r2 verification minor): the gate
        # checks the records' proposal scope roots directly, as
        # issue_attestation does, instead of relying only on the
        # presented attestation's proposal binding — evidence
        # scored under another proposal's budget scope is not
        # evidence for this one.
        if _scope_root(baseline_payload.get("scope")) \
                != body["proposal_id"] \
                or _scope_root(candidate_payload.get("scope")) \
                != body["proposal_id"]:
            raise _config(
                "eval_evidence_scope_mismatch",
                "the eval records were not scored under this "
                "proposal's scope")
        if baseline_payload["manifest_hash"] \
                != candidate_payload["manifest_hash"]:
            raise _config(
                "eval_evidence_unverifiable",
                "the eval records are bound to different sealed "
                "manifests")
        expected_ref = (f"eval:{evidence['baseline']['payload_hash']}"
                        f":{evidence['candidate']['payload_hash']}")
        if attestation.evidence_ref != expected_ref:
            raise _malformed(
                "malformed_request",
                "the attestation's evidence_ref does not name the "
                "presented eval_evidence records")
        baseline_sealed = {"sealed": baseline_payload["score"]}
        candidate_sealed = {"sealed": candidate_payload["score"]}
        eval_payload_hashes = (evidence["baseline"]["payload_hash"],
                               evidence["candidate"]["payload_hash"])
    try:
        decision = evaluate_self_change(
            proposal_id=body["proposal_id"],
            builder_ids=body["builder_ids"],
            reviewer_ids=body["reviewer_ids"],
            baseline_public=body["baseline_public"],
            candidate_public=body["candidate_public"],
            baseline_sealed=baseline_sealed,
            candidate_sealed=candidate_sealed,
            capability_baseline=body["capability_baseline"],
            capability_candidate=body["capability_candidate"],
            attestation=attestation,
            expected_sealed_hash=manifest_hash,
            evaluated_at=_now(),
            changed_paths=body["changed_paths"],
            verifier_note=body["verifier_note"])
    except GateInputError as exc:
        raise _malformed("gate_input_error", str(exc))
    if decision.accepted and eval_payload_hashes is None:
        raise _config(
            "evidence_required",
            "an accepted decision requires eval_evidence: two "
            "verifier-produced sealed-eval records the sealed "
            "scores are derived from; unsigned-evidence accepts "
            "are not issued")
    if decision.accepted and signed_attestation is None:
        raise _config(
            "attestation_required",
            "an accepted decision requires a signed attestation "
            "envelope (obtain one via the issue_attestation mode); "
            "unsigned accepts are not issued")
    try:
        digest = _registry_digest(registry, config.actor, manifest_hash)
    except ValueError:
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    if config.purpose == PURPOSE_SHIP:
        gate_inputs_hash = body["manifest_hash"]
    else:
        normalised = {
            "proposal_id": body["proposal_id"],
            "builder_ids": body["builder_ids"],
            "reviewer_ids": body["reviewer_ids"],
            "baseline_public": body["baseline_public"],
            "candidate_public": body["candidate_public"],
            "baseline_sealed": baseline_sealed,
            "candidate_sealed": candidate_sealed,
            "capability_baseline": body["capability_baseline"],
            "capability_candidate": body["capability_candidate"],
            "attestation": body["attestation"],
            "changed_paths": body["changed_paths"],
            "verifier_note": body["verifier_note"],
        }
        if eval_payload_hashes is not None:
            # Bind both eval-record payload hashes into the gate
            # inputs hash, so the signed decision names the exact
            # evidence its sealed scores were derived from. (The
            # ship purpose keeps gate_inputs_hash == manifest_hash
            # by design — shipcheck verifies against exactly that —
            # and binds the evidence through the attestation's
            # evidence_ref instead.)
            normalised["eval_evidence"] = {
                "baseline_payload_hash": eval_payload_hashes[0],
                "candidate_payload_hash": eval_payload_hashes[1]}
        gate_inputs_hash = _sha256(_canonical({
            "v": "trust-gate-inputs/1", "request": normalised,
            "manifest_hash": manifest_hash,
            "registry_digest": digest}))
    try:
        signed = sign_gate_decision(
            decision, signing_key=config.signing_key,
            signer_id=config.signer_id, attestation=attestation,
            gate_inputs_hash=gate_inputs_hash, purpose=config.purpose,
            ttl_seconds=config.ttl_seconds,
            signed_attestation=signed_attestation)
    except SigningError as exc:
        raise _malformed("signing_input_error", str(exc))
    try:
        SigningLedger(config.home).append_envelope(
            signed, recorded_at=_now())
    except Exception:
        raise _config("ledger_failed",
                      "the signed envelope could not be ledgered; "
                      "refusing to return it")
    _update_anchor(config)
    return {"envelope": envelope_to_dict(signed),
            "gate_inputs_hash": gate_inputs_hash,
            "manifest_hash": manifest_hash,
            "registry_digest": digest}


def _mode_sealed_eval(config: _Config, body: dict) -> dict:
    if not {"answers"} <= set(body) <= {"answers", "proposal_id"}:
        raise _malformed("malformed_request",
                         "sealed_eval body must carry answers and "
                         "optionally proposal_id")
    proposal_id = body.get("proposal_id", "unscoped")
    _check_sealed_eval_scope(proposal_id)
    answers = body["answers"]
    if not isinstance(answers, list) \
            or len(answers) > MAX_ANSWERS \
            or not all(isinstance(a, str) and len(a) <= MAX_ANSWER_CHARS
                       for a in answers):
        raise _malformed("malformed_request",
                         "answers must be a bounded list of strings")
    # Query budgets are enforced HERE, inside the verifier, in two
    # phases. Phase one (check_only) runs before the registry is
    # opened: a refused query spends no registry access-log entries
    # and runs no evaluation. Recording is deferred until AFTER
    # the answer-count check below, so a garbage-length transcript
    # burns no budget at all; record() then re-runs the full
    # assessment under the store lock and fails closed if the
    # state moved between the phases.
    try:
        budget_store = BudgetStore(
            Path(config.home) / "budgets.json",
            per_proposal_cap=config.proposal_budget,
            per_identity_cap=config.identity_budget)
    except BudgetError as exc:
        raise _config("budget_store_corrupt", exc.reason)
    try:
        budget_store.check_only(config.actor, proposal_id, answers)
    except BudgetError as exc:
        if exc.reason == "adaptive_query_detected":
            # Persist the tripping probe through record() — which
            # records the probe count and the family latch before
            # refusing — so the latch materialises on disk exactly
            # as it does for direct BudgetStore callers, instead of
            # existing only as a recomputed refusal. The refusal
            # itself is unchanged.
            try:
                budget_store.record(config.actor, proposal_id,
                                    answers)
            except BudgetError:
                pass
            try:
                _update_budgets_anchor(config, budget_store)
            except Exception:
                pass
        raise _config("query_budget_exceeded", exc.reason)
    registry = _open_registry(config)
    try:
        metadata = registry.list_sealed_metadata(config.actor)
    except (CorruptRegistryError, ValueError):
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    if not metadata:
        raise _config("registry_empty", "the sealed set is empty")
    if len(answers) != len(metadata):
        raise _malformed(
            "answer_count_mismatch",
            f"transcript has {len(answers)} answers for "
            f"{len(metadata)} sealed items")
    try:
        budget_store.record(config.actor, proposal_id, answers)
    except BudgetError as exc:
        raise _config("query_budget_exceeded", exc.reason)
    _update_budgets_anchor(config, budget_store)
    remaining = iter(answers)

    def scorer(prompt):  # prompt is seen only inside this process
        try:
            return next(remaining)
        except StopIteration:
            raise EvaluationError("answer count mismatch")

    try:
        report = registry.run_sealed_evaluation(config.actor, scorer)
    except CorruptRegistryError:
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    except EvaluationError:
        raise _config("evaluation_failed",
                      "the sealed evaluation failed closed")
    except ValueError:
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    try:
        digest = _registry_digest(registry, config.actor,
                                  report["manifest_hash"])
    except ValueError:
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    record = sign_eval_attestation(
        report, signing_key=config.signing_key,
        signer_id=config.signer_id, actor=config.actor,
        registry_digest=digest, answers_hash=answers_hash_for(answers),
        ttl_seconds=config.ttl_seconds, scope=proposal_id)
    try:
        SigningLedger(config.home).append_eval_attestation(
            record, recorded_at=_now())
    except Exception:
        raise _config("ledger_failed",
                      "the eval attestation could not be ledgered; "
                      "refusing to return it")
    _update_anchor(config)
    return {"attestation": record}


def _mode_verify_envelope(config: _Config, body: dict) -> dict:
    if not set(body) <= {"envelope", "expected"} \
            or "envelope" not in body:
        raise _malformed("malformed_request",
                         "verify_envelope body is malformed")
    if "expected" in body and not isinstance(body["expected"], dict):
        raise _malformed("malformed_request",
                         "expected must be an object when present")
    expected = body.get("expected") or {}
    if not set(expected) <= _EXPECTED_KEYS:
        raise _malformed("malformed_request",
                         "expected carries unknown keys")
    if "purpose" in expected \
            and (not isinstance(expected["purpose"], str)
                 or not expected["purpose"]):
        raise _malformed("malformed_request",
                         "an expected purpose must be a string; "
                         "null does not mean 'any'")
    from signing.gate_decision import envelope_from_dict
    try:
        signed = envelope_from_dict(body["envelope"])
    except SigningError:
        return {"valid": False, "reasons": ["malformed_envelope"]}
    try:
        reasons = verify_signed_decision(
            signed, signing_key=config.signing_key,
            expected_proposal_id=expected.get("proposal_id"),
            expected_purpose=expected.get("purpose",
                                          PURPOSE_MEMORY_COMMIT),
            expected_entry_content_hash=expected.get(
                "entry_content_hash"),
            expected_attestation_hash=expected.get("attestation_hash"),
            expected_gate_inputs_hash=expected.get("gate_inputs_hash"),
            expected_signer_id=expected.get("signer_id"))
    except SigningError as exc:
        raise _malformed("malformed_request", str(exc))
    return {"valid": not reasons, "reasons": list(reasons)}


def _mode_submit_claim(config: _Config, body: dict) -> dict:
    """Ledger a caller's attestation-shaped CLAIM, unsigned.

    This replaces the old attest mode, which signed whatever
    approval fields the caller selected — a laundry oracle. A
    claim is validated for FORM only (via _attestation_from),
    appended to the signing ledger as a claim entry (kind
    "claim", accepted=False), and acknowledged with its hash. NO
    signature is issued and nothing about the claim is endorsed:
    the claim's verifier_id need not be this service's, its
    decision may say "approve" — it still grants nothing."""
    if set(body) != {"attestation", "proposal_id"}:
        raise _malformed("malformed_request",
                         "submit_claim body has missing or unknown "
                         "keys")
    attestation = _attestation_from(body["attestation"])
    if attestation is None:
        raise _malformed("malformed_request",
                         "submit_claim requires an attestation")
    if not isinstance(body["proposal_id"], str) \
            or not _ID_RE.fullmatch(body["proposal_id"]):
        raise _malformed("malformed_request",
                         "proposal_id must be a well-formed id")
    claim_document = {
        "v": "trust-claim/1",
        "proposal_id": body["proposal_id"],
        "attestation": body["attestation"],
    }
    try:
        entry = SigningLedger(config.home).append_claim(
            claim_document, recorded_at=_now(),
            signer_id=attestation.verifier_id)
    except Exception:
        raise _config("ledger_failed",
                      "the claim could not be ledgered; "
                      "refusing to acknowledge it")
    return {"claim_id": entry["decision_id"],
            "claim_hash": entry["payload_hash"]}


def _mode_issue_attestation(config: _Config, body: dict) -> dict:
    """Derive and sign an attestation from verified eval evidence.

    The caller supplies two sealed-eval records and two PUBLIC
    aggregate scores (numbers in [0, 1] — caller-asserted claims,
    see the module docstring). The strict key set is the point:
    a body carrying caller-selected decision or
    reward_hacking_checked fields is a malformed request. The
    verifier verifies both records with its own key, requires
    them in its own ledger as sealed-eval sign entries, requires
    them to be DISTINCT records with the baseline ledgered
    before the candidate, requires their manifest hashes to
    equal each other and the live registry's sealed manifest
    hash, requires their budget-scope roots (scope stripped of
    a trailing :baseline/:candidate) to equal the requested
    proposal_id, and requires their signer to be this service.
    It then DERIVES the attestation — sealed side only: sealed
    scores from the records, the gap check run verifier-side,
    reward_hacking_checked=True because it just ran, and
    decision approve iff the sealed score did not regress and
    the gap check flags neither gaming nor a sealed regression.
    Any verification failure is a config-class refusal — never a
    signed reject built on unverifiable evidence.

    Single-use consumption (Trust Boundary v3, item 3): after the
    pair and scope checks pass and BEFORE anything is signed,
    BOTH records are consumed in the signing ledger via
    SigningLedger.try_consume_eval_records (atomic, race-safe
    against concurrent issuance processes); an already-consumed
    record refuses the issuance (eval_evidence_consumed).
    Consumption happens even when the derived decision is
    "reject": the evidence was presented and spent either way,
    and refunding it on a reject would let a caller probe
    decisions repeatedly with the same pair. The GATE path
    deliberately does NOT consume: a gate legitimately
    re-presents the attestation's own records, and that reuse is
    safe because the gate binds the records to the single
    attestation via evidence_ref (the attestation names exactly
    these two payload hashes), re-checks their scope roots
    against the gate's proposal, and matches their signer to the
    attesting identity — the records can corroborate only the
    one attestation they were consumed to issue."""
    if set(body) != {"proposal_id", "baseline_eval", "candidate_eval",
                     "public_baseline_score",
                     "public_candidate_score"}:
        raise _malformed("malformed_request",
                         "issue_attestation body has missing or "
                         "unknown keys; caller-selected approval "
                         "fields are not accepted")
    # Cheap deterministic INPUT validation runs BEFORE the eval
    # pair is verified or consumed: proposal_id is validated with
    # signing's id grammar (the same _check_id sign_attestation
    # applies at signing time) and the public scores are
    # range-checked by _public_score below. Validating only at
    # signing time — after try_consume_eval_records — would burn
    # a genuine single-use eval pair on a mere bad spelling.
    # Consumption still happens on DERIVED rejects (see the
    # docstring): only input-validation failures move earlier.
    try:
        _check_id(body["proposal_id"], "proposal id")
    except SigningError:
        raise _malformed("malformed_request",
                         "proposal_id must be a well-formed id")
    public_before = _public_score(body, "public_baseline_score")
    public_after = _public_score(body, "public_candidate_score")
    baseline, candidate, manifest_hash = _verified_eval_pair(
        config, body["baseline_eval"], body["candidate_eval"],
        expected_signer_id=config.signer_id)
    # LOW-3 binding: records scored under another proposal's
    # budget scope cannot be re-issued under this proposal id.
    for payload in (baseline, candidate):
        if _scope_root(payload.get("scope")) != body["proposal_id"]:
            raise _config(
                "eval_evidence_scope_mismatch",
                "an eval record was scored under a different "
                "proposal's budget scope than the proposal the "
                "attestation is requested for")
    # Single-use consumption (see the docstring): spend BOTH
    # records atomically with the check, before signing, and
    # regardless of the decision derived below.
    try:
        consumed = SigningLedger(config.home).try_consume_eval_records(
            [body["baseline_eval"]["payload_hash"],
             body["candidate_eval"]["payload_hash"]],
            proposal_id=body["proposal_id"],
            signer_id=config.signer_id, recorded_at=_now())
    except Exception:
        raise _config("ledger_failed",
                      "the eval evidence could not be consumed; "
                      "refusing to issue an attestation on it")
    if not consumed:
        raise _config(
            "eval_evidence_consumed",
            "an eval record was already consumed by a previous "
            "attestation issuance; eval evidence is single-use")
    sealed_before = baseline["score"]
    sealed_after = candidate["score"]
    try:
        gap = assess_gap(public_before, public_after,
                         sealed_before, sealed_after)
    except FactoryError as exc:
        raise _malformed("malformed_request", str(exc))
    decision = "approve" if (
        sealed_after >= sealed_before
        and not gap["gaming_suspected"]
        and not gap["sealed_regression"]) else "reject"
    attestation = VerifierAttestation(
        verifier_id=config.signer_id,
        decision=decision,
        sealed_hash=manifest_hash,
        reward_hacking_checked=True,
        evidence_ref=(f"eval:{body['baseline_eval']['payload_hash']}"
                      f":{body['candidate_eval']['payload_hash']}"),
        attested_at=_now())
    try:
        signed_att = sign_attestation(
            attestation, signing_key=config.signing_key,
            signer_id=config.signer_id,
            proposal_id=body["proposal_id"],
            manifest_hash="",
            ttl_seconds=config.ttl_seconds)
    except SigningError as exc:
        raise _malformed("signing_input_error", str(exc))
    try:
        SigningLedger(config.home).append_attestation_envelope(
            signed_att, recorded_at=_now())
    except Exception:
        raise _config("ledger_failed",
                      "the signed attestation could not be "
                      "ledgered; refusing to return it")
    _update_anchor(config)
    return {"signed_attestation":
            attestation_envelope_to_dict(signed_att)}


_MODES = {"gate": _mode_gate, "sealed_eval": _mode_sealed_eval,
          "verify_envelope": _mode_verify_envelope,
          "submit_claim": _mode_submit_claim,
          "issue_attestation": _mode_issue_attestation}


def _emit(request_id, mode, status, *, result=None, error=None,
          deployment_mode=None) -> int:
    """Write the single response document. Returns 3 instead of 0
    when an ok-result had to be replaced: a response larger than
    the protocol cap is never emitted (the signature it carried
    was already ledgered — the ledger records that a signature
    was made and withheld, which is the honest audit trail).

    deployment_mode is the effective mode from the loaded config,
    passed only for responses emitted after config load succeeded;
    pre-config responses omit the field entirely."""
    encoded = protocol.encode_response(
        request_id, mode, status, result=result, error=error,
        deployment_mode=deployment_mode)
    if len(encoded) + 1 > protocol.MAX_RESPONSE_BYTES and status == "ok":
        encoded = protocol.encode_response(
            request_id, mode, "error",
            error=("verifier_failure",
                   "the signed response exceeded the protocol size "
                   "cap and was withheld"),
            deployment_mode=deployment_mode)
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()
        return 3
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()
    return 0


def main() -> int:
    raw = sys.stdin.buffer.read(protocol.MAX_REQUEST_BYTES + 1)
    request_id = None
    mode = None
    try:
        request = protocol.decode_request(raw)
    except protocol.ProtocolError as exc:
        _emit(None, None, "error",
              error=("malformed_request", str(exc)))
        return 2
    request_id, mode = request["request_id"], request["mode"]
    # Effective-mode reporting: deployment_mode stays None until
    # config load SUCCEEDS. Config refusals (including the
    # deployment-mode contract itself) and malformed requests are
    # pre-config responses and carry no deployment_mode field —
    # the absence is itself the signal that no mode was
    # established. Every later response (ok results and
    # mode-level refusals alike) carries the loaded mode.
    deployment_mode = None
    try:
        config = _load_config()
        deployment_mode = config.deployment_mode
        result = _MODES[mode](config, request["body"])
    except _Refuse as refusal:
        _emit(request_id, mode, "error",
              error=(refusal.code, refusal.detail),
              deployment_mode=deployment_mode)
        return refusal.exit_code
    except Exception:  # unhandled: stderr gets the trace, stdout a
        traceback.print_exc()  # generic unsigned error document
        _emit(request_id, mode, "error",
              error=("verifier_failure", "unhandled verifier failure"),
              deployment_mode=deployment_mode)
        return 3
    return _emit(request_id, mode, "ok", result=result,
                 deployment_mode=deployment_mode)


if __name__ == "__main__":
    sys.exit(main())
