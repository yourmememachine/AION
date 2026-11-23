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
  AION_CEREMONY_OPERATORS   comma-separated operator ids
                            allowlisted to be named as the
                            operator id in ceremony authorisations
                            (mode ceremony_authorise, cycle 19).
                            Loaded ONLY here, from the
                            environment — a request can never
                            carry an operator list. REQUIRED in
                            production: absent or empty refuses
                            startup (verifier_misconfigured),
                            mirroring the anchor rule. In research
                            mode absent/empty loads as an empty
                            list and the MODE refuses every request
                            (ceremony_operators_unconfigured).
                            A malformed list (bad id grammar,
                            whitespace, empty segment, duplicate,
                            more than 64 entries) refuses startup
                            in BOTH modes.
  AION_CEREMONY_EVIDENCE_DIR
                            absolute path to the directory
                            holding ceremony evidence artifacts,
                            provisioned OUTSIDE the verifier and
                            read — never written — by the verifier
                            at issuance (cycle 20). evidence_ref
                            in a ceremony_authorise request is a
                            path RELATIVE to this directory. A
                            malformed spelling refuses startup in
                            BOTH modes; production + absent refuses
                            startup; research + absent loads as
                            None and the mode refuses per-request
                            (ceremony_evidence_unconfigured).
                            Filesystem existence is a per-request
                            check, not a startup one. The root is
                            resolved ONCE at config load and the
                            resolved path is stored on the config.
  AION_CEREMONY_SIGNING_SEED_PATH
                            absolute path to the ceremony signing
                            seed file (32-byte Ed25519 seed, 0600,
                            loaded via load_ceremony_seed — cycle
                            20). The seed does NOT ride
                            AION_VERIFIER_KEY_PATH: it is a second,
                            purpose-only secret, used only by mode
                            ceremony_authorise; every other mode
                            keeps the HMAC key. A malformed value
                            refuses startup in BOTH modes;
                            production + absent refuses startup
                            (verifier_misconfigured); research +
                            absent loads as None and the mode
                            refuses per-request
                            (ceremony_seed_unconfigured);
                            present-but-unloadable refuses startup
                            in BOTH modes. A seed byte-equal to the
                            HMAC verifier key, or on the refused
                            test-seed list, refuses startup. The
                            seed path is scrubbed from the
                            environment after load, like the key
                            path.
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
  AION_CEREMONY_CONSUMPTION_ANCHOR_PATH
                            optional: external anchor file for
                            the ceremony consumption journal
                            (kind "ceremony-consumption", cycle
                            22); must live OUTSIDE
                            AION_VERIFIER_HOME and be distinct
                            from the signing and budgets anchor
                            paths. When set, startup verifies the
                            anchor on every invocation and every
                            consumption advances it BEFORE the
                            signing-ledger mirror write.
                            Production mode with the ceremony
                            seed configured REQUIRES the path and
                            refuses the INIT flag below; research
                            mode with the path unconfigured makes
                            NO rollback claim for consumptions.
  AION_CEREMONY_CONSUMPTION_ANCHOR_INIT
                            optional: "1" allows ONE bootstrap
                            invocation to create the consumption
                            anchor for an EMPTY consumption
                            journal; a non-empty journal with a
                            missing anchor is NOT silently blessed
                            (anchor_refused) — recovery is the
                            audited force_reanchor path, exactly
                            as for signing
  AION_VERIFIER_HOME        REQUIRED: signing-ledger directory;
                            the service refuses to run without it

Exit codes: 0 = protocol success (INCLUDING a signed gate
rejection and a verify_envelope verdict of valid:false); 2 =
malformed request (unsigned error document); 3 = verifier-side
failure — misconfiguration, unsafe/missing key, untrusted
registry, signer conflict (unsigned error document). Nothing
unsigned is ever representable as a decision.

The ceremony_authorise mode (cycle 19, evidence + key boundary
cycle 20) issues signed ceremony authorisations for pin
re-anchors: operator-id allowlist eligibility comes from this
process's protected AION_CEREMONY_OPERATORS list, never from
the request, and each issuance is ledgered single-use at
issuance in BOTH the ceremony journal (the commit point) and
the signing ledger before the envelope is returned. Honest
limits, stated plainly: The verifier resolves the evidence
itself: `evidence_ref` is a relative path under the directory
named only by its own `AION_CEREMONY_EVIDENCE_DIR`
configuration; the verifier opens the artifact (refusing
absolute refs, `..` escapes and any symlink on the path),
reads at most 1 MiB of opaque bytes, computes the SHA-256
itself, refuses if it differs from the hash the caller
supplied, and retains a copy of the bytes it hashed under its
verifier home, named by the authorisation id. What the
envelope proves: at issuance, an artifact with exactly the
bound `evidence_hash` existed at the bound `evidence_ref` in
that protected location and was read by the verifier; the
presentation was ledgered single-use at issuance; and the
binding is signed by the verifier's ceremony seed (Ed25519).
It does NOT prove the artifact's contents are true, relevant
or adequate as evidence for this recovery, who authored it,
or when it was created — a caller presenting an allowlisted
operator id can still obtain an authorisation over a *real
but worthless* artifact. A random hex64 with no artifact
behind it is no longer issuable. Operator identity is
operator-id allowlist eligibility via the verifier's launch
channel, not authentication: the verifier checks that the
presented operator_id was on its configured allowlist at
issuance; it does not and cannot verify that the presenter
*is* that operator — no per-operator credential exists in
this system, and any caller able to launch the verifier can
present any listed id. The envelope proves a presentation
under an allowlisted id, ledgered at issuance and bound to
this event — workflow provenance, not cryptographic
attribution: nothing in the envelope is evidence *by* the
operator, only *about* them, and it does not prove which
human or process made the presentation. Refusals of this mode
(unconfigured list, unlisted operator, replay) are unsigned
and unledgered.
OPERATOR RECOVERY from a post-commit ledger failure: the
(ceremony_id, evidence_hash) pair stays burned even though no
envelope was returned — retry the ceremony under a NEW
ceremony_id with a NEW evidence bundle (a re-issued evidence
artefact, hence a new hash); there is no idempotent re-issue.
The ceremony ISSUANCE journal is NOT externally anchored
(follow-up: ceremony-journal-anchoring, narrowed in cycle
22 to this issuance journal only — the consumption journal
is separately anchored, see above): its evidence-reuse guarantee is
prevented against an intact journal; after a journal rollback,
only same-ceremony_id reuse leaves a detectable trace in the
anchored signing ledger — evidence reuse under a NEW
ceremony_id is NOT detectable from the anchored store alone
(see trust/ledger.py's CeremonyAuthorisationLedger for the
full statement) — never describe it as rollback-resistant.

The verifier never touches the network, never spawns processes,
and writes only where the registry itself writes (its access log
and file, plus the quarantine file a corrupt registry document
is moved to) plus its own signing ledger and ceremony journal. AION_VERIFIER_HOME is
REQUIRED: the service refuses to run without its ledger, so "a
signature with no ledger entry" stays meaningful. That "only"
is a property of this code under review, not a runtime sandbox
— nothing stops a *modified* verifier, and the docs must not
imply otherwise.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import os
import stat
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
from signing import ed25519 as _ed25519
from signing.ceremony_authorisation import (
    CEREMONY_AUTHORISATION_TTL_MAX_SECONDS,
    REASONS as _CEREMONY_REASONS,
    REASON_BURNED_UNADOPTED as _CEREMONY_REASON_BURNED_UNADOPTED,
    _EITHER_PIN_REASONS as _CEREMONY_EITHER_PIN_REASONS,
    _NO_PIN_REASONS as _CEREMONY_NO_PIN_REASONS,
    REFUSED_TEST_SEEDS as _REFUSED_TEST_SEEDS,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_to_dict,
    ceremony_public_key_for,
    load_ceremony_seed,
    sign_ceremony_authorisation,
    verify_ceremony_authorisation,
)
from signing.gate_decision import (
    PURPOSE_MEMORY_COMMIT,
    PURPOSE_SHIP,
    TTL_MAX_SECONDS,
    TTL_MIN_SECONDS,
    SigningError,
    _canonical,
    _check_hex64,
    _check_id,
    _check_text,
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
from trust.ledger import AlreadyConsumedError, \
    CeremonyAuthorisationLedger, CeremonyConsumptionLedger, \
    CorruptLedgerError, HeadRegressionError, SigningLedger
from trust.pathpolicy import canonicalise as _policy_canonicalise

GENESIS_HASH = "0" * 64
MAX_ANSWER_CHARS = 8000
MAX_ANSWERS = 500
_REFUSED_TEST_KEYS = (
    bytes(range(32)), bytes(range(32, 64)),
    b"\x00" * 32, b"\xff" * 32,
)

# Refused ceremony seeds (cycle 20, critique-b §3.5 / A-1d):
# signing.ceremony_authorisation.REFUSED_TEST_SEEDS, imported
# unconditionally above and used directly — the signing module
# owns the list (the predictable test seeds plus the RFC 8032
# §7.1 TEST 1–3 vector seeds, public knowledge pinned in its
# own test vectors, so a production verifier provisioned with
# one is a verifier anyone can mint for). There is deliberately
# NO local copy or fallback here: two lists drift, and a drift
# test (tests/test_trust_ceremony_mode.py) asserts this
# module's refused seeds == signing's REFUSED_TEST_SEEDS.
# _REFUSED_TEST_KEYS above is a separate list: it refuses the
# HMAC verifier key, not ceremony seeds.

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
                 ceremony_consumption_anchor_path=None,
                 ceremony_consumption_anchor_init=False,
                 ceremony_operators=(), ceremony_evidence_dir=None,
                 ceremony_signing_key=None, *, deployment_mode):
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
        self.ceremony_consumption_anchor_path = \
            ceremony_consumption_anchor_path
        self.ceremony_consumption_anchor_init = \
            ceremony_consumption_anchor_init
        self.ceremony_operators = tuple(ceremony_operators)
        # Resolved evidence root (Path) or None; resolved ONCE
        # in _load_config (cycle 20, R5(b)).
        self.ceremony_evidence_dir = ceremony_evidence_dir
        # CeremonySigningKey or None (research + unconfigured).
        self.ceremony_signing_key = ceremony_signing_key
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
    # Ceremony operator allowlist (cycle 19): parsed ONLY here,
    # from the environment — never from a request. Grammar per
    # entry is the verifier id grammar; no stripping (mirroring
    # the deployment-mode no-strip philosophy), so whitespace-
    # padded spellings, empty segments and duplicates are
    # malformed, as are more than 64 entries. Detail strings name
    # the variable and never echo its value. Malformed refuses
    # startup in BOTH modes; production additionally refuses an
    # absent/empty list at startup (mirroring the anchor rule —
    # production is fail-closed at deployment about protective
    # config), while research loads an empty list and lets the
    # mode refuse per-request.
    ceremony_operators = ()
    ceremony_raw = env.get("AION_CEREMONY_OPERATORS", "")
    if ceremony_raw:
        segments = ceremony_raw.split(",")
        if len(segments) > 64 \
                or len(set(segments)) != len(segments) \
                or any(not _ID_RE.fullmatch(segment)
                       for segment in segments):
            raise _config(
                "verifier_misconfigured",
                "AION_CEREMONY_OPERATORS is malformed: it must be "
                "a comma-separated list of at most 64 distinct "
                "well-formed operator ids")
        ceremony_operators = tuple(segments)
    if deployment_mode == "production" and not ceremony_operators:
        raise _config(
            "verifier_misconfigured",
            "production mode requires AION_CEREMONY_OPERATORS")
    # Ceremony evidence dir (cycle 20, design-b §1.2 as ruled in
    # R4/R5): form is a startup fact in BOTH modes — a present
    # value must be a non-empty absolute path with no trailing
    # slash (except the root spelling) and no `.` / `..`
    # segment; no stripping, no normalising. Production +
    # absent refuses startup; research + absent loads None and
    # the mode refuses per-request. Existence/type are NOT
    # startup checks. The root is resolved ONCE here and the
    # resolved path stored (R5(b)): the per-request fd-walk
    # applies below this resolved root, whose ancestors may
    # legitimately be symlinks.
    ceremony_evidence_dir = None
    evidence_raw = env.get("AION_CEREMONY_EVIDENCE_DIR", "")
    if evidence_raw:
        evidence_path = Path(evidence_raw)
        segments = evidence_raw.split("/")
        if not evidence_path.is_absolute() \
                or (evidence_raw.endswith("/")
                    and evidence_raw != "/") \
                or any(segment in (".", "..")
                       for segment in segments):
            raise _config(
                "verifier_misconfigured",
                "AION_CEREMONY_EVIDENCE_DIR is malformed: it "
                "must be a non-empty absolute path with no "
                "trailing slash and no '.' or '..' segment")
        ceremony_evidence_dir = evidence_path.resolve()
    elif deployment_mode == "production":
        raise _config(
            "verifier_misconfigured",
            "production mode requires AION_CEREMONY_EVIDENCE_DIR")
    # Ceremony signing seed path FORM (cycle 20, critique-b
    # §3.5): the load itself happens after the HMAC key load
    # below (deterministic error precedence, and the
    # byte-equality check needs both secrets), but a malformed
    # spelling refuses startup here, in both modes.
    ceremony_seed_raw = env.get("AION_CEREMONY_SIGNING_SEED_PATH",
                                "")
    if ceremony_seed_raw:
        if not Path(ceremony_seed_raw).is_absolute():
            raise _config(
                "verifier_misconfigured",
                "AION_CEREMONY_SIGNING_SEED_PATH is malformed: "
                "it must be a non-empty absolute path")
    elif deployment_mode == "production":
        raise _config(
            "verifier_misconfigured",
            "production mode requires "
            "AION_CEREMONY_SIGNING_SEED_PATH")
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
    # Ceremony signing seed (cycle 20, critique-b §3.5): loaded
    # ONLY here, through the disciplined loader, with the
    # registry dir as a forbidden root. Present-but-unloadable
    # refuses startup in BOTH modes — a configured but broken
    # seed is a misdeployment, not a runtime condition.
    # Research + absent loaded None above (the mode refuses
    # per-request); production + absent already refused.
    ceremony_signing_key = None
    if ceremony_seed_raw:
        try:
            ceremony_signing_key = load_ceremony_seed(
                ceremony_seed_raw,
                forbidden_roots=(Path(registry_dir),))
        except SigningError:
            raise _config("verifier_misconfigured",
                          "ceremony signing seed is missing or "
                          "unsafe")
        # Pair checks, over RAW BYTES in this one place both
        # secrets exist (critique-b A-1c): a key_id comparison
        # cannot catch byte-equality — the ids live in disjoint
        # namespaces ("key-…" over the secret, "pub-…" over the
        # public key) — so the comparison is over the seed
        # bytes themselves. Detail names neither value.
        seed_bytes = getattr(ceremony_signing_key, "seed", None)
        if seed_bytes is not None \
                and seed_bytes == signing_key.key:
            raise _config(
                "verifier_misconfigured",
                "ceremony signing seed must differ from the "
                "verifier signing key")
        if seed_bytes is not None \
                and seed_bytes in _REFUSED_TEST_SEEDS:
            raise _config("verifier_misconfigured",
                          "refusing a known test ceremony seed")
        # Derivation-overlap pair checks (cycle 21, R9): the
        # closed set below, checked here because this is the
        # one place both secrets exist. Each relation refuses
        # startup as verifier_misconfigured with a detail that
        # names neither secret value:
        #   (2) seed == sha256(key)
        #   (3) key == sha256(seed)
        #   (4) key == ceremony public key (public material as
        #       the HMAC secret — the most dangerous relation)
        #   (5) seed == sha256(ceremony public key)
        #   (6) key == sha256(ceremony public key)
        #   (7) seed == sha256(own public key): "own" is read
        #       both ways the designs used it — the ceremony
        #       key's own public key (the same bytes as (5),
        #       kept explicit) and the public key derived by
        #       treating the HMAC key bytes as an Ed25519
        #       seed; both are publicly derivable values a
        #       seed must never equal.
        #   (8) key in REFUSED_TEST_SEEDS (live exactly for
        #       the RFC 8032 vector seeds, which the HMAC
        #       refused list does not cover).
        # ((1) seed == key is the byte-equality check above,
        # and the independent refused-list checks stand.)
        # Residual wording (mandatory, R9): these relations
        # catch accidents and known derivations, not arbitrary
        # KDF overlap; no stronger claim is made. Provisioning
        # discipline — independent random draws — remains the
        # real defence.
        if seed_bytes is not None:
            key_bytes = signing_key.key
            ceremony_public = ceremony_signing_key.public_key
            key_public = _ed25519.public_key_from_seed(key_bytes) \
                if len(key_bytes) == _ed25519.SEED_BYTES else None
            overlap = (
                seed_bytes == hashlib.sha256(key_bytes).digest()
                or key_bytes == hashlib.sha256(seed_bytes).digest()
                or key_bytes == ceremony_public
                or seed_bytes
                == hashlib.sha256(ceremony_public).digest()
                or key_bytes
                == hashlib.sha256(ceremony_public).digest()
                or (key_public is not None
                    and seed_bytes
                    == hashlib.sha256(key_public).digest())
                or key_bytes in _REFUSED_TEST_SEEDS)
            if overlap:
                raise _config(
                    "verifier_misconfigured",
                    "the ceremony signing seed and the verifier "
                    "signing key fail the derivation-overlap "
                    "check; provision them as independent random "
                    "draws")
        # Scrub the seed path from the environment after load,
        # like the key path.
        env.pop("AION_CEREMONY_SIGNING_SEED_PATH", None)
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
    ceremony_consumption_anchor_path = env.get(
        "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH", "")
    consumption_init_raw = env.get(
        "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT", "")
    if consumption_init_raw not in ("", "0", "1"):
        raise _config(
            "verifier_misconfigured",
            "bad AION_CEREMONY_CONSUMPTION_ANCHOR_INIT")
    ceremony_consumption_anchor_init = consumption_init_raw == "1"
    if deployment_mode == "production" and ceremony_seed_raw:
        # Production + ceremony seed configured: the consumption
        # journal's anchor is REQUIRED at startup and its INIT
        # flag is refused (mirroring AION_ANCHOR_PATH's
        # production discipline, cycle 22 R2).
        if not ceremony_consumption_anchor_path:
            raise _config(
                "verifier_misconfigured",
                "production mode with the ceremony seed "
                "configured requires "
                "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH")
        if ceremony_consumption_anchor_init:
            raise _config(
                "verifier_misconfigured",
                "production mode refuses "
                "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT; anchor "
                "ceremonies run outside production")
    if ceremony_consumption_anchor_path and not Path(
            ceremony_consumption_anchor_path).is_absolute():
        raise _config(
            "verifier_misconfigured",
            "the ceremony consumption anchor path must be "
            "absolute")
    if ceremony_consumption_anchor_init \
            and not ceremony_consumption_anchor_path:
        raise _config(
            "verifier_misconfigured",
            "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT requires "
            "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH")
    if ceremony_consumption_anchor_path:
        # Placement + distinctness (budgets-style): the anchor
        # must live outside the verifier home and must not be
        # either of the other two anchor files — one file
        # cannot anchor two journals.
        home_resolved = Path(home).resolve()
        consumption_anchor_resolved = Path(
            ceremony_consumption_anchor_path).resolve()
        if consumption_anchor_resolved == home_resolved \
                or home_resolved in consumption_anchor_resolved.parents:
            raise _config(
                "verifier_misconfigured",
                "the ceremony consumption anchor must live "
                "outside the verifier home")
        for other_name, other_path in (
                ("AION_ANCHOR_PATH", anchor_path),
                ("AION_BUDGETS_ANCHOR_PATH", budgets_anchor_path)):
            if other_path and consumption_anchor_resolved \
                    == Path(other_path).resolve():
                raise _config(
                    "verifier_misconfigured",
                    "the ceremony consumption anchor path must "
                    f"be distinct from {other_name}")
        # Startup anchor verification (per request — this
        # process is one-per-request, so this runs before
        # EVERY mode): a consumption journal whose external
        # anchor is missing on an established journal, ahead
        # of the journal, or names no prefix refuses startup.
        try:
            consumption_ledger = CeremonyConsumptionLedger(home)
        except Exception:
            raise _config(
                "ledger_failed",
                "the ceremony consumption journal could not be "
                "opened for anchor verification")
        try:
            consumption_reasons = verify_anchor(
                consumption_ledger,
                ceremony_consumption_anchor_path,
                kind="ceremony-consumption")
        except AnchorError:
            raise _config(
                "anchor_refused",
                "the ceremony consumption anchor path is invalid "
                "for this journal")
        if consumption_reasons == ("anchor_missing",) \
                and ceremony_consumption_anchor_init:
            try:
                initialise_anchor(
                    consumption_ledger,
                    ceremony_consumption_anchor_path,
                    kind="ceremony-consumption",
                    recorded_at=_now())
            except AnchorError:
                raise _config(
                    "anchor_refused",
                    "ceremony consumption anchor bootstrap failed")
            consumption_reasons = ()
        if consumption_reasons:
            raise _config("anchor_refused",
                          ",".join(consumption_reasons))
    return _Config(signing_key, signer_id, actor, registry_dir, ttl,
                   purpose, home,
                   proposal_budget=proposal_budget,
                   identity_budget=identity_budget,
                   anchor_path=anchor_path or None,
                   anchor_init=anchor_init,
                   budgets_anchor_path=budgets_anchor_path or None,
                   budgets_anchor_init=budgets_anchor_init,
                   ceremony_consumption_anchor_path=(
                       ceremony_consumption_anchor_path or None),
                   ceremony_consumption_anchor_init=(
                       ceremony_consumption_anchor_init),
                   ceremony_operators=ceremony_operators,
                   ceremony_evidence_dir=ceremony_evidence_dir,
                   ceremony_signing_key=ceremony_signing_key,
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


def _update_ceremony_consumption_anchor(config: _Config) -> None:
    """Advance the ceremony consumption journal's external
    anchor after a consumption append (cycle 22, R2). A no-op
    when the anchor is unconfigured (research mode — no
    rollback claim is made there). A failed update is
    ledger_failed: the burn stands in the journal, and the
    verifier says so rather than returning a success whose
    rollback protection was never pinned."""
    if not config.ceremony_consumption_anchor_path:
        return
    try:
        update_anchor(
            CeremonyConsumptionLedger(config.home),
            config.ceremony_consumption_anchor_path,
            kind="ceremony-consumption", recorded_at=_now())
    except AnchorError:
        raise _config(
            "ledger_failed",
            "the consumption was committed in the consumption "
            "journal but its anchor update failed; the "
            "authorisation stays burned and no success is "
            "returned — recovery is a new ceremony")


def _read_budgets_anchor(path):
    """Return the pinned budget-store head, or None when no anchor
    file exists yet. A malformed anchor refuses: an operator must
    repair it deliberately, never have it silently ignored."""
    anchor_file = Path(path)
    if not anchor_file.exists():
        return None
    try:
        doc = protocol.strict_loads(anchor_file.read_bytes(),
                                    cap=64 << 10,
                                    what="budgets anchor")
    except (protocol.ProtocolError, OSError):
        raise _config("anchor_refused", "budgets anchor malformed")
    if not isinstance(doc, dict) \
            or set(doc) != {"v", "head", "anchored_at"} \
            or doc["v"] != "budgets-anchor/1" \
            or not isinstance(doc["head"], str) \
            or len(doc["head"]) != 64 \
            or any(c not in "0123456789abcdef" for c in doc["head"]) \
            or not isinstance(doc["anchored_at"], str) \
            or not doc["anchored_at"]:
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


_SNAPSHOT_ATTEMPTS = 40
_EVAL_ATTEMPTS = 40
_LEDGER_ATTEMPTS = 40


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
    is registry_untrusted — deterministically.

    Bound rationale — an engineering margin, NOT a proof:
    each attempt fails only if a competitor's save lands
    inside its load->save window; attempts are independent
    races, so no attempt count PROVES success under sustained
    contention. The bound of 40 was validated empirically
    under barrier-synchronised multi-process contention
    (10-wide in tests/test_trust_sealed_eval_contention.py,
    12-wide in the fix-round probe), and exhaustion still
    refuses registry_untrusted — fail-closed, never a wrong
    success.

    Cost, accounted exactly: a FAILED attempt persists at
    most 1 access-log entry — the metadata save may land
    before the manifest save detects staleness, while a
    metadata save that itself detects staleness persists 0
    (staleness is checked before any write) — and a
    SUCCESSFUL attempt persists 2 (metadata + manifest). A
    snapshot call therefore adds at most 39*1 + 2 = 41
    entries under adversarial contention vs 2 uncontended;
    the entries are truthful attempt records, and the log
    cap fails closed."""
    for _attempt in range(_SNAPSHOT_ATTEMPTS):
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
            # The verifier canonicalises-or-refuses every entry
            # before the gate as defence-in-depth: it accepts only
            # canonical spellings — anything else is a malformed
            # request, never a signed accept. Since cycle 13 the
            # gate itself also judges canonical spellings
            # (path-policy/1 adoption), so the layers agree.
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
    # Through the snapshot retry, not a direct open: a direct
    # instance goes stale when a competing process appends
    # access-log entries, and its save then misreports
    # registry_untrusted under concurrency. The snapshot's
    # manifest_hash is not used here — the digest below is
    # derived from the evaluation report's own manifest hash.
    registry, metadata, _snapshot_manifest_hash = \
        _registry_snapshot(config)
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
    # The scorer factory is built ONCE, outside the retry loop
    # below (as is all answers parsing/validation above); each
    # attempt calls it for a FRESH answer iterator, because a
    # failed attempt may already have consumed part of the
    # transcript and a retry must score the whole transcript.

    def _fresh_scorer():
        remaining = iter(answers)

        def scorer(prompt):  # prompt seen only in this process
            try:
                return next(remaining)
            except StopIteration:
                raise EvaluationError("answer count mismatch")

        return scorer

    # Evaluate retry on FRESH instances (Trust Boundary v3.1,
    # fix round 2, C1). The budget was recorded exactly ONCE,
    # above, BEFORE this loop — the v2 two-phase discipline
    # (check_only earlier in this mode, record here) — and is
    # NEVER re-recorded on retries, so a retried evaluation
    # still costs exactly one recorded query. The first
    # attempt reuses the snapshot instance; on
    # CorruptRegistryError the instance is discarded and the
    # next attempt runs on a fresh _open_registry instance.
    # Retrying a STALENESS failure is safe: in
    # eval/registry.py the evaluate access-log save checks
    # staleness (_disk_changed) BEFORE any write and the
    # sealed-access wrapper rolls its in-memory state back,
    # so a stale evaluate persists nothing and scores
    # nothing. (A CorruptRegistryError raised for genuine
    # tampering inside the evaluation itself occurs after
    # that log entry landed; retrying it is still safe — it
    # simply refuses again — and exhaustion below refuses
    # registry_untrusted either way.)
    # The bound of _EVAL_ATTEMPTS is an engineering margin,
    # NOT a proof, in the same sense as _registry_snapshot:
    # each attempt fails only if a competitor's save lands
    # inside its load->save window, attempts are independent
    # races, the margin was validated empirically under
    # barrier-synchronised contention (see
    # tests/test_trust_sealed_eval_contention.py), and
    # exhaustion refuses registry_untrusted — fail-closed,
    # never a wrong success.
    report = None
    eval_registry = registry
    for _eval_attempt in range(_EVAL_ATTEMPTS):
        if _eval_attempt:
            eval_registry = _open_registry(config)
        try:
            report = eval_registry.run_sealed_evaluation(
                config.actor, _fresh_scorer())
            break
        except CorruptRegistryError:
            continue
        except EvaluationError:
            raise _config("evaluation_failed",
                          "the sealed evaluation failed closed")
        except ValueError:
            raise _config("registry_untrusted",
                          "the sealed registry failed validation")
    else:
        raise _config("registry_untrusted",
                      "the sealed registry failed validation")
    registry = eval_registry
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
    # Ledger append retry on FRESH instances (Trust Boundary
    # v3.1, fix round 3). The record above is built ONCE from
    # the successful evaluation and is re-appended VERBATIM on
    # every attempt: the evaluation is not re-run, the budget
    # is not re-recorded and the record is not re-signed. The
    # ledger entry append_eval_attestation derives from it
    # (decision_id / payload_hash = record["payload_hash"],
    # signer_id = record["payload"]["signer_id"]) is a
    # deterministic function of the record, and recorded_at is
    # captured once here and reused, mirroring the recorded_at
    # reuse in ShipLedger.burn's reload-and-retry
    # (trust/ledger.py); the only entry fields that differ on
    # a retry are the chain fields (seq / prev_hash /
    # entry_hash), which name the fresh head the entry extends
    # — they are not part of the signed record, of the response
    # below ({"attestation": record}), or of the payload_hash
    # downstream ledger-presence checks look up, so a retry
    # cannot break the response or its verification.
    # Retrying a CorruptLedgerError is safe against
    # double-append ONLY because of a verified property of
    # HashChainJournal._save (trust/ledger.py): its freshness
    # check runs under the directory flock BEFORE the tmp file
    # is written or replaced, and every other
    # CorruptLedgerError on the append path (the _reload /
    # under-lock _load validation) likewise precedes any
    # write — a CorruptLedgerError from the append therefore
    # guarantees that attempt wrote NOTHING, so the successful
    # attempt is the one and only append of this record. Any
    # other exception is not a staleness race and refuses
    # ledger_failed at once, exactly as before.
    # The bound of _LEDGER_ATTEMPTS is an engineering margin,
    # NOT a proof, in the same sense as the evaluate loop
    # above: each attempt fails only if a competitor's append
    # lands inside its load->save window, attempts are
    # independent races, the margin was validated empirically
    # under barrier-synchronised contention (see
    # tests/test_trust_sealed_eval_contention.py), and
    # exhaustion refuses ledger_failed — fail-closed, never a
    # wrong success.
    ledger_recorded_at = _now()
    ledger_entry = None
    for _ledger_attempt in range(_LEDGER_ATTEMPTS):
        try:
            ledger_entry = SigningLedger(
                config.home).append_eval_attestation(
                    record, recorded_at=ledger_recorded_at)
            break
        except CorruptLedgerError:
            # Stale instance: discard it; the next attempt
            # constructs a fresh SigningLedger and re-appends
            # the same record.
            continue
        except Exception:
            raise _config("ledger_failed",
                          "the eval attestation could not be "
                          "ledgered; refusing to return it")
    if ledger_entry is None:
        # Every attempt lost the append race: exhaustion still
        # refuses ledger_failed, fail-closed.
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


_CEREMONY_BODY_KEYS = {"operator_id", "ceremony_id", "reason",
                       "old_pin", "candidate",
                       "evidence_hash", "evidence_ref"}
_CEREMONY_OLD_PIN_KEYS = {"cycle_seq", "payload_hash"}
_CEREMONY_CANDIDATE_KEYS = {"cycle_seq", "payload_hash",
                            "signer_id", "key_id"}


def _ceremony_seq(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) \
        and value >= 0


_CEREMONY_EVIDENCE_MAX_BYTES = 1 << 20
_CEREMONY_EVIDENCE_SEGMENT_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)*$")


def _check_evidence_ref_grammar(evidence_ref) -> None:
    """evidence_ref grammar (cycle 20, design-b §1.3): a
    relative path under the configured evidence directory —
    ≤512 chars, 1–8 canonical lowercase segments, no leading or
    trailing slash, no backslash, no `.` / `..` / empty
    segments. Pure string work; violations are exit-2
    malformed_request and touch no filesystem."""
    detail = ("evidence_ref must be a relative path under the "
              "configured evidence directory")
    if not isinstance(evidence_ref, str) \
            or len(evidence_ref) > 512 \
            or evidence_ref.startswith("/") \
            or evidence_ref.endswith("/") \
            or "\\" in evidence_ref:
        raise _malformed("malformed_request", detail)
    segments = evidence_ref.split("/")
    if not 1 <= len(segments) <= 8:
        raise _malformed("malformed_request", detail)
    for segment in segments:
        if not segment or segment in (".", "..") \
                or not _CEREMONY_EVIDENCE_SEGMENT_RE.fullmatch(
                    segment):
            raise _malformed("malformed_request", detail)


def _evidence_unresolvable(subcase: str):
    """The SINGLE caller-visible refusal for every existence /
    type / symlink sub-case (cycle 20, R5(c)): distinct codes
    would hand a presenter an enumeration oracle over the
    evidence store. The specific sub-case is logged
    verifier-side only, on stderr, and never reaches the
    caller."""
    print(f"ceremony evidence unresolvable: {subcase}",
          file=sys.stderr)
    return _config(
        "ceremony_evidence_unresolvable",
        "the named evidence artifact could not be resolved "
        "under the configured evidence directory")


def _resolve_ceremony_evidence(config: _Config, evidence_ref):
    """Resolve, read and hash one evidence artifact (cycle 20).

    The root was resolved ONCE at config load
    (config.ceremony_evidence_dir); the fd-walk below applies
    BELOW that resolved root, with O_NOFOLLOW on every
    component — any symlink on the path refuses. Residual
    window, named not hidden (R5(b)): the root itself is the
    resolved path from config load; ancestors of the root may
    be symlinks, and a swap OF the root between config load
    and this walk is outside what the walk can see — the walk
    guarantees containment below the directory it opens.
    Returns (content_bytes, sha256_hex). All existence / type
    / symlink failures raise the single
    ceremony_evidence_unresolvable refusal; oversize raises
    ceremony_evidence_too_large."""
    root = config.ceremony_evidence_dir
    segments = evidence_ref.split("/")
    fds = []
    try:
        try:
            root_fd = os.open(
                root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise _evidence_unresolvable("root_missing")
        except NotADirectoryError:
            raise _evidence_unresolvable("root_not_directory")
        except OSError:
            raise _evidence_unresolvable("root_unopenable")
        fds.append(root_fd)
        current = root_fd
        for segment in segments[:-1]:
            try:
                current = os.open(
                    segment,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current)
            except FileNotFoundError:
                raise _evidence_unresolvable(
                    "intermediate_missing")
            except NotADirectoryError:
                raise _evidence_unresolvable(
                    "intermediate_not_directory")
            except OSError:
                raise _evidence_unresolvable(
                    "intermediate_unopenable_or_symlink")
            fds.append(current)
        try:
            # O_NONBLOCK on the leaf open (cycle 20 fix round):
            # without it, opening a FIFO leaf blocks forever,
            # before the S_ISREG fstat check below can refuse
            # it. O_NONBLOCK does not alter read behaviour for
            # regular files (it is meaningful only for FIFOs,
            # devices and sockets), so the blocking reads below
            # keep their semantics for the only file type that
            # passes the fstat check.
            final_fd = os.open(
                segments[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=current)
        except FileNotFoundError:
            raise _evidence_unresolvable("artifact_missing")
        except OSError:
            raise _evidence_unresolvable(
                "artifact_unopenable_or_symlink")
        fds.append(final_fd)
        info = os.fstat(final_fd)
        if not stat.S_ISREG(info.st_mode):
            raise _evidence_unresolvable("artifact_not_regular")
        if info.st_size == 0:
            raise _evidence_unresolvable("artifact_empty")
        if info.st_size > _CEREMONY_EVIDENCE_MAX_BYTES:
            raise _config(
                "ceremony_evidence_too_large",
                "the named evidence artifact exceeds the 1 MiB "
                "evidence size cap")
        digest = hashlib.sha256()
        chunks = []
        total = 0
        while True:
            chunk = os.read(final_fd, 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > _CEREMONY_EVIDENCE_MAX_BYTES:
                raise _config(
                    "ceremony_evidence_too_large",
                    "the named evidence artifact exceeds the "
                    "1 MiB evidence size cap")
            digest.update(chunk)
            chunks.append(chunk)
        if total != info.st_size:
            raise _evidence_unresolvable(
                "artifact_changed_during_read")
        return b"".join(chunks), digest.hexdigest()
    finally:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass


def _retain_ceremony_evidence(config: _Config, authorisation_id,
                              content: bytes) -> None:
    """Retain the exact bytes the verifier hashed, under
    <home>/ceremony-evidence/<authorisation_id> (cycle 20,
    design-b §1.8 as re-ordered by R5(a) and the build note).

    Called AFTER signing (the authorisation_id is derivable
    only once the envelope exists — it is a function of the
    payload hash and the signing key's public id) and BEFORE
    the ceremony-journal append, so the invariant "every
    committed ceremony has its evidence retained" holds: no
    journal commit can land without its retained copy already
    on disk. A failure here is a PRE-commit refusal
    (ledger_failed class): nothing is burned and the request
    is retryable. Idempotent: an existing retained file with
    byte-identical content is already-retained and the flow
    proceeds; different bytes under a derived id are a payload
    collision and refuse pre-commit."""
    retained_dir = Path(config.home) / "ceremony-evidence"
    try:
        retained_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise _config(
            "ledger_failed",
            "the ceremony evidence could not be retained; "
            "refusing before commit — nothing is burned and "
            "the request is retryable")
    target = retained_dir / authorisation_id
    try:
        fd = os.open(target,
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            existing = target.read_bytes()
        except OSError:
            existing = None
        if existing is not None and existing == content:
            return  # already retained, byte-identical
        raise _config(
            "ledger_failed",
            "a different artifact is already retained under "
            "this authorisation id; refusing before commit — "
            "nothing is burned and the request is retryable")
    except OSError:
        raise _config(
            "ledger_failed",
            "the ceremony evidence could not be retained; "
            "refusing before commit — nothing is burned and "
            "the request is retryable")
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except OSError:
        # Partial-write orphan cleanup (cycle 20 fix round):
        # the file exists under this authorisation id but holds
        # incomplete bytes; left in place it would permanently
        # block a same-id retry (the byte-compare above would
        # refuse it as a collision). Best-effort unlink before
        # propagating the refusal — if the unlink itself fails
        # the refusal still stands and the orphan is an
        # operator-repair artefact, named by id.
        try:
            os.unlink(target)
        except OSError:
            pass
        raise _config(
            "ledger_failed",
            "the ceremony evidence could not be retained; "
            "refusing before commit — nothing is burned and "
            "the request is retryable")
    finally:
        os.close(fd)
    try:
        dir_fd = os.open(retained_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _mode_ceremony_authorise(config: _Config, body: dict) -> dict:
    """Issue a signed ceremony authorisation (cycle 19; evidence
    resolution and Ed25519 signing, cycle 20).

    Operator identity is operator-id allowlist eligibility via
    the verifier's launch channel, not authentication: the
    verifier checks that the presented operator_id was on its
    configured allowlist at issuance; it does not and cannot
    verify that the presenter *is* that operator — no
    per-operator credential exists in this system, and any caller
    able to launch the verifier can present any listed id. The
    envelope proves a presentation under an allowlisted id,
    ledgered at issuance and bound to this event — workflow
    provenance, not cryptographic attribution: nothing in the
    envelope is evidence *by* the operator, only *about* them,
    and it does not prove which human or process made the
    presentation.

    The verifier signs ABOUT the operator's presentation: it
    binds the evidence hash IT COMPUTED over bytes IT READ —
    resolved from evidence_ref under its own configured
    evidence directory — to one exact recovery event (old pin,
    candidate, reason, ceremony_id) under its ceremony seed.
    The claim is the module docstring's: existence + content at
    issuance, nothing about truth, relevance or authorship.

    Exact order implemented here, and why: (1) config gates
    (operators, seed, evidence — a disabled mode refuses
    wholesale, whatever the body says); (2) cheap validation,
    including the evidence_ref grammar — pure string work, no
    filesystem touched, so a bad spelling can never burn a
    single-use pair; (3) operator membership — BEFORE evidence
    resolution, so an unlisted operator id cannot make this
    process open a file (no existence oracle, no read
    amplification); (4) evidence resolution: fd-walk below the
    resolved root, verifier-computed SHA-256, the supplied
    evidence_hash cross-checked against it; (5) anti-replay
    scan keyed on ceremony_id and the COMPUTED hash; (5b) for
    reason burned_unadopted ONLY, the burn proof against the
    consumption journal's head entry (cycle 22, WS1 — one
    refusal code, ceremony_recovery_unproven, for every
    predicate failure); (6) sign
    with the CeremonySigningKey (TTL min(config, 900));
    (7) retention write of the hashed bytes under the
    authorisation id; (8) ceremony-journal append — the
    COMMIT POINT; (9) signing-ledger append; (10) anchor
    update.

    The anti-replay scan sits at (5), BEFORE signing and
    retention (cycle 20 fix round): its inputs — ceremony_id
    and the verifier-computed evidence hash — are both fixed
    once resolution at (4) has run, so a refused replay now
    leaves no trace at all: no signature is minted and no
    retained-evidence file is written for a presentation that
    will be refused. Retention sits at (7), not beside
    resolution at (4), for one reason: the retained file is
    named by the authorisation_id, which is derivable only
    after signing (it is a function of the payload hash,
    which binds the computed evidence hash, and the signing
    key's public id). Retention still precedes the journal
    append, so the invariant "every committed ceremony has
    its evidence retained" holds: no journal append can land
    without its retained copy already on disk, and nothing
    burns before the journal append — a retention failure,
    and equally a replay refusal at (5), is a pre-commit
    refusal. Any failure AFTER the journal
    append is ledger_failed and the (ceremony_id,
    evidence_hash) pair stays burned with no envelope
    returned — recovery is a NEW ceremony_id with a NEW
    evidence bundle (documented in the module docstring).
    Retention is NOT a consumption input: no consumption path
    reads retained copies; the signed envelope hash is the
    commitment to the retained bytes. An IDENTICAL
    re-presentation is refused like any replay: the verifier
    cannot distinguish a lost response from a replay, and
    single-use that makes exceptions for plausible stories
    is not single-use.

    Race honesty: one process per request; the anti-replay scan
    and the commit append are not atomic as a pair, but two
    composed mechanisms guarantee at most one handed-out
    authorisation per (ceremony_id, evidence_hash) pair
    (cycle 20 fix round): CeremonyAuthorisationLedger.
    append_authorisation re-checks the pair against the
    entries it reloads immediately before appending — a
    competitor commit landing before that reload is seen by
    the re-check and refused with LedgerError — and
    HashChainJournal._save's under-flock freshness check
    refuses a save whose on-disk journal moved after that
    reload, so a commit landing after the reload trips the
    freshness check instead. The loser of a concurrent race
    gets ledger_failed (the mode maps both failures to it),
    its envelope is never returned, and no orphan
    signing-ledger entry exists for it."""
    # (1) Config gates, before body validation: a deployment
    # that never configured ceremony operators refuses the mode
    # wholesale, whatever the body says. Seed and evidence
    # configuration gate the same way (research + absent only;
    # production refused both at startup).
    if not config.ceremony_operators:
        raise _config(
            "ceremony_operators_unconfigured",
            "AION_CEREMONY_OPERATORS is not configured; the "
            "ceremony_authorise mode is disabled")
    if config.ceremony_signing_key is None:
        raise _config(
            "ceremony_seed_unconfigured",
            "AION_CEREMONY_SIGNING_SEED_PATH is not configured; "
            "the ceremony_authorise mode is disabled")
    if config.ceremony_evidence_dir is None:
        raise _config(
            "ceremony_evidence_unconfigured",
            "AION_CEREMONY_EVIDENCE_DIR is not configured; the "
            "ceremony_authorise mode is disabled")
    # (2) Strict key set + cheap field validation: malformed,
    # exit 2, NO ledger touched.
    if set(body) != _CEREMONY_BODY_KEYS:
        raise _malformed(
            "malformed_request",
            "ceremony_authorise body has missing or unknown keys; "
            "operator eligibility comes from the verifier's "
            "configuration, never from the request")
    operator_id = body["operator_id"]
    ceremony_id = body["ceremony_id"]
    reason = body["reason"]
    old_pin = body["old_pin"]
    candidate = body["candidate"]
    evidence_hash = body["evidence_hash"]
    evidence_ref = body["evidence_ref"]
    try:
        _check_id(operator_id, "operator id")
    except SigningError:
        raise _malformed("malformed_request",
                         "operator_id must be a well-formed id")
    # ceremony_id grammar: signing's _check_id intersected with
    # this service's stricter first-char rule (_ID_RE) — the
    # effective minting grammar.
    if not isinstance(ceremony_id, str) \
            or not _ID_RE.fullmatch(ceremony_id):
        raise _malformed("malformed_request",
                         "ceremony_id must be a well-formed id")
    try:
        _check_id(ceremony_id, "ceremony id")
    except SigningError:
        raise _malformed("malformed_request",
                         "ceremony_id must be a well-formed id")
    if not isinstance(reason, str) or reason not in _CEREMONY_REASONS:
        raise _malformed("malformed_request",
                         "reason must be a ceremony reason")
    try:
        _check_hex64(evidence_hash, "evidence hash")
        _check_text(evidence_ref, "evidence_ref", 2000)
    except SigningError:
        raise _malformed("malformed_request",
                         "evidence fields are ill-formed")
    # evidence_ref grammar (cycle 20): a relative path under the
    # configured evidence directory, canonical lowercase
    # segments only — still pure string work, no filesystem.
    _check_evidence_ref_grammar(evidence_ref)
    if old_pin is not None:
        if not isinstance(old_pin, dict) \
                or set(old_pin) != _CEREMONY_OLD_PIN_KEYS \
                or not _ceremony_seq(old_pin["cycle_seq"]):
            raise _malformed("malformed_request",
                             "old_pin is ill-formed")
        try:
            _check_hex64(old_pin["payload_hash"],
                         "old_pin payload hash")
        except SigningError:
            raise _malformed("malformed_request",
                             "old_pin is ill-formed")
    if not isinstance(candidate, dict) \
            or set(candidate) != _CEREMONY_CANDIDATE_KEYS \
            or not _ceremony_seq(candidate["cycle_seq"]):
        raise _malformed("malformed_request",
                         "candidate is ill-formed")
    try:
        _check_hex64(candidate["payload_hash"],
                     "candidate payload hash")
        _check_id(candidate["signer_id"], "candidate signer id")
        _check_id(candidate["key_id"], "candidate key id")
    except SigningError:
        raise _malformed("malformed_request",
                         "candidate is ill-formed")
    # Reason/pin coherence (the payload projection re-checks this
    # at signing time — defence in depth, as in attestation).
    # Ternary rule (cycle 22, WS1): no-pin reasons require no
    # pin; chain_gap_recovery requires a pin; burned_unadopted
    # (in _CEREMONY_EITHER_PIN_REASONS) is coherent with either
    # shape — whichever pin shape it carries must EXACTLY equal
    # the burned entry's old pin, proven at step (5b) below.
    if old_pin is None and reason not in (
            _CEREMONY_NO_PIN_REASONS | _CEREMONY_EITHER_PIN_REASONS):
        raise _malformed(
            "malformed_request",
            "a no-pin ceremony requires a no-pin reason")
    if old_pin is not None and reason not in (
            {"chain_gap_recovery"} | _CEREMONY_EITHER_PIN_REASONS):
        raise _malformed(
            "malformed_request",
            "a ceremony carrying an old pin requires reason "
            "chain_gap_recovery or burned_unadopted")
    if old_pin is not None \
            and candidate["cycle_seq"] < old_pin["cycle_seq"] + 2:
        raise _malformed(
            "malformed_request",
            "candidate cycle_seq must be at least old_pin "
            "cycle_seq + 2 (gap-only re-anchor)")
    # Evidence non-equality, verifier-side half: the full
    # four-way check stays inside reanchor_pin, which sees the
    # real snapshot; neither layer may drop its half.
    if evidence_hash == candidate["payload_hash"] \
            or (old_pin is not None
                and evidence_hash == old_pin["payload_hash"]):
        raise _malformed(
            "malformed_request",
            "evidence_hash must differ from the pin payload "
            "hashes it is evidence about")
    # (3) Operator membership: a config-class refusal, UNSIGNED
    # and UNLEDGERED by deliberate design — there is no
    # signed-reject artefact for this mode; signing a rejection
    # would mint verifier artefacts at a non-operator's request.
    if operator_id not in config.ceremony_operators:
        raise _config(
            "ceremony_operator_not_authorised",
            "the named operator is not on the verifier's "
            "configured ceremony operator list")
    # (4) Evidence resolution (cycle 20): the FIRST step with
    # side effects (file opens), earned by passing membership.
    # The verifier reads the artifact itself and computes the
    # hash; the supplied hash is a cross-check only, never the
    # signed value.
    evidence_bytes, computed_hash = _resolve_ceremony_evidence(
        config, evidence_ref)
    if computed_hash != evidence_hash:
        raise _malformed(
            "ceremony_evidence_hash_mismatch",
            "the supplied evidence_hash does not match the "
            "hash the verifier computed over the resolved "
            "artifact")
    # Re-run the evidence non-equality check against the
    # COMPUTED hash — the value that will be signed (equal to
    # the supplied hash on this path, by the cross-check above).
    if computed_hash == candidate["payload_hash"] \
            or (old_pin is not None
                and computed_hash == old_pin["payload_hash"]):
        raise _malformed(
            "malformed_request",
            "evidence_hash must differ from the pin payload "
            "hashes it is evidence about")
    # (5) Anti-replay scan of the ceremony journal, BEFORE
    # signing and retention (cycle 20 fix round): both scan
    # inputs — ceremony_id and the COMPUTED hash — are fixed
    # by now, so a refused replay mints no signature and
    # writes no retained-evidence file. A journal that cannot
    # be read refuses ledger_failed — never scan a partial
    # history and proceed.
    try:
        ceremony_entries = CeremonyAuthorisationLedger(
            config.home).entries()
    except Exception:
        raise _config(
            "ledger_failed",
            "the ceremony journal could not be read; refusing "
            "to authorise without its reuse history")
    for entry in ceremony_entries:
        if entry["ceremony_id"] == ceremony_id:
            raise _config(
                "ceremony_id_reused",
                "this ceremony_id was already authorised; "
                "ceremony ids are single-use at issuance")
    for entry in ceremony_entries:
        if entry["evidence_hash"] == computed_hash:
            raise _config(
                "ceremony_evidence_reused",
                "this evidence_hash was already authorised for "
                "another ceremony; evidence is single-use per "
                "event at issuance")
    # (5b) Burn proof for burned_unadopted recoveries ONLY
    # (cycle 22, WS1): the recovery's candidate and old pin
    # must exactly equal the consumption journal's HEAD
    # entry's recorded target and old pin, and the recovery
    # ceremony must not be the burned ceremony itself. This
    # runs only for reason == burned_unadopted — ordinary
    # issuance gains no new failure dependency on the
    # consumption journal. The journal read here runs AFTER
    # _load_config's per-request anchor verification of that
    # journal (when its anchor is configured), which is what
    # makes the read trustworthy. ONE refusal code for every
    # predicate failure, with no sub-case detail: distinguishing
    # "no burn", "burn for a different target" and "old-pin
    # mismatch" would hand a presenter a journal-state oracle.
    if reason == _CEREMONY_REASON_BURNED_UNADOPTED:
        try:
            consumption_entries = CeremonyConsumptionLedger(
                config.home).entries()
        except Exception:
            raise _config(
                "ledger_failed",
                "the consumption journal could not be read; "
                "refusing to authorise a recovery without it")
        burn = CeremonyConsumptionLedger.match_head_burn(
            consumption_entries, candidate=candidate,
            old_pin=old_pin)
        if burn is None or burn["ceremony_id"] == ceremony_id:
            raise _config(
                "ceremony_recovery_unproven",
                "no recorded consumption proves this recovery")
    # (6) Sign with the ceremony seed, with the ceremony TTL
    # hard cap applied over the configured verifier TTL. The
    # COMPUTED hash is signed, never the body value.
    try:
        signed = sign_ceremony_authorisation(
            signing_key=config.ceremony_signing_key,
            signer_id=config.signer_id,
            operator_id=operator_id, ceremony_id=ceremony_id,
            reason=reason, old_pin=old_pin, candidate=candidate,
            evidence_hash=computed_hash, evidence_ref=evidence_ref,
            ttl_seconds=min(
                config.ttl_seconds,
                CEREMONY_AUTHORISATION_TTL_MAX_SECONDS))
    except SigningError as exc:
        raise _malformed("signing_input_error", str(exc))
    # (7) Retention, BEFORE the commit point (see docstring):
    # the retained file is named by the authorisation id, which
    # exists only now that signing has happened.
    _retain_ceremony_evidence(config, signed.authorisation_id,
                              evidence_bytes)
    # (8) Commit: ceremony journal FIRST (the commit point),
    # then the signing ledger, then the anchor. Any failure
    # after the first append is ledger_failed and the pair
    # stays burned — see the docstring.
    recorded_at = _now()
    try:
        CeremonyAuthorisationLedger(
            config.home).append_authorisation(
                signed, recorded_at=recorded_at)
    except Exception:
        raise _config(
            "ledger_failed",
            "the ceremony authorisation could not be ledgered; "
            "refusing to return it")
    try:
        SigningLedger(config.home).append_ceremony_authorisation(
            signed, recorded_at=recorded_at)
    except Exception:
        raise _config(
            "ledger_failed",
            "the ceremony authorisation was recorded in the "
            "ceremony journal but could not be entered in the "
            "signing ledger; the (ceremony_id, evidence_hash) "
            "pair stays burned and the envelope is withheld — "
            "retry under a new ceremony_id with a new evidence "
            "bundle")
    _update_anchor(config)
    return {"signed_authorisation":
            ceremony_authorisation_envelope_to_dict(signed)}


def _mode_ceremony_consume(config: _Config, body: dict) -> dict:
    """Consume a ceremony authorisation (cycle 21): record the
    single-use consumption of an issued envelope in the
    verifier-owned consumption journal and enforce the
    monotonic consumption head (DESIGN-FINAL R2/R3/R4).

    Crash-consistency contract (R7, exact wording): Consumption
    is committed at the verifier — a fsync'd consumption-journal
    append — before reanchor_pin returns anything. There is no
    execution path in the integrated system in which a pin
    movement succeeds without its consumption record durably
    committed first. A crash after the commit but before
    adoption leaves the authorisation burned and the pin
    unmoved; a lost or ambiguous response is treated as burned;
    the client never retries a consume automatically. Recovery
    is a new ceremony (new ceremony_id, new evidence), never an
    un-consume.

    Rollback claim (cycle 22, R2, replacing cycle 21's R10
    residual): with the consumption anchor configured, a burn
    whose anchor update completed survives a verifier-home
    rollback (detected at startup, anchor_refused); the
    append→anchor-update window (burn in journal, anchor at
    pre-burn prefix) is protected against an intact home but
    NOT against a full rollback inside that window — the same
    window every anchored append in this system carries;
    research mode / anchor unconfigured: no rollback claim.

    The head enforced here is a CEREMONY head — it sees
    consumptions only; advance_pin movements never pass through
    the verifier, so a pin advanced outside ceremonies is
    invisible to this journal. The residual class that leaves
    is named in DECISION-CONSUMPTION-HEAD.md.

    Liveness figures, stated numerically: the envelope TTL is
    hard-capped at 900 s, and every ceremony now needs TWO
    verifier-availability windows inside that life — one to
    authorise, one to consume. A failed or lost consume burns
    the issuance pair, and recovery needs a new ceremony_id
    plus a new evidence artefact; the client never retries a
    consume automatically.

    Commit order (cycle 22, R2): (1) consumption-journal
    append — THE commit point; (2) consumption-anchor update
    (_update_ceremony_consumption_anchor — a no-op when the
    anchor is unconfigured; AnchorError is ledger_failed and
    the burn stands); (3) signing-ledger mirror (kind
    "consume", format "ceremony-consumption"); (4) signing
    anchor update. The consumption anchor advances BEFORE the
    mirror write, so a mirror failure followed by a
    verifier-home rollback leaves the consumption anchor
    ahead of the rolled-back journal and the replay is
    refused at startup (anchor_refused). A mirror failure
    after the commit is ledger_failed and the envelope stays
    burned, with no success response. The shared
    directory flock serialises the steps against the
    other verifier-home journals but is NOT cross-ledger
    atomicity: a concurrent ceremony_authorise may interleave
    between the steps, which is benign (the journals are
    independent chains and the mirror entry's content does not
    depend on issuance state).

    Validation order (R2): (1) config gate — the ceremony seed
    only; the operator allowlist and evidence configuration
    are issuance facts and are NOT consumption gates; (2)
    strict body key set, exactly {"signed_authorisation"};
    (3) envelope parse; (4) verifier-side signature
    verification + expiry under the public key derived from
    the configured ceremony seed. One refusal code,
    ceremony_authorisation_invalid, for all verification-
    failure classes — signature, signer, payload structure
    and binding failures returned by
    verify_ceremony_authorisation — with byte-identical
    stdout and stderr across those classes: within
    verification failure there is no per-reason forger
    oracle. The no-oracle claim covers verification failures
    only. By design, and outside that claim: temporal
    failure (reasons ⊆ {expired, signed_in_future}) returns
    ceremony_authorisation_expired — which therefore
    certifies an envelope valid in every non-temporal
    respect; post-verification state refusals return
    ceremony_already_consumed, ceremony_not_issued and
    ceremony_head_regression, reachable only by an envelope
    that passed verification; and infrastructure failure
    returns ledger_failed, the same code on both sides of
    the commit point; (5)
    already-consumed (consumption journal, plus the signing
    ledger scoped to kind="consume" +
    format="ceremony-consumption" — the issuance mirror's
    kind="sign" entry for the same authorisation_id must
    never trip this check); (6) issuance presence in the
    ceremony journal with payload/ceremony/evidence field
    match, else ceremony_not_issued; (7) the R3 head rules,
    else ceremony_head_regression; (8) commit. An
    unreadable/corrupt journal at any step is ledger_failed —
    fail closed, never scan partial state. Explicitly NOT
    re-checked here: operator allowlist membership and
    evidence resolution (issuance facts; retention is not a
    consumption input)."""
    # (1) Config gate: the seed only.
    if config.ceremony_signing_key is None:
        raise _config(
            "ceremony_seed_unconfigured",
            "AION_CEREMONY_SIGNING_SEED_PATH is not configured; "
            "the ceremony_consume mode is disabled")
    # (2) Strict body key set.
    if set(body) != {"signed_authorisation"}:
        raise _malformed(
            "malformed_request",
            "ceremony_consume body must carry exactly "
            "signed_authorisation")
    # (3) Envelope parse.
    try:
        signed = ceremony_authorisation_envelope_from_dict(
            body["signed_authorisation"])
    except SigningError as exc:
        raise _malformed("malformed_request", str(exc))
    # (4) Signature + expiry, verifier-side, under the public
    # key derived from the configured seed.
    reasons = verify_ceremony_authorisation(
        signed,
        public_key=ceremony_public_key_for(
            config.ceremony_signing_key),
        expected_signer_id=config.signer_id)
    if reasons:
        # No per-reason output anywhere — not even stderr: the
        # client embeds stderr excerpts in its exception
        # messages, so a reason tuple printed here would reach
        # the caller and defeat R2's single-code rule
        # (ceremony_authorisation_invalid; within verification
        # failure there is no per-reason forger oracle).
        if set(reasons) <= {"expired", "signed_in_future"}:
            raise _config(
                "ceremony_authorisation_expired",
                "the ceremony authorisation is expired")
        raise _malformed(
            "ceremony_authorisation_invalid",
            "the ceremony authorisation failed verification")
    # (5) Already-consumed: consumption journal first, then
    # the signing-ledger mirror, scoped to consume entries.
    try:
        consumption_ledger = CeremonyConsumptionLedger(config.home)
        consumption_entries = consumption_ledger.entries()
        signing_entries = SigningLedger(config.home).entries()
    except Exception:
        raise _config(
            "ledger_failed",
            "the consumption state could not be read; refusing "
            "to consume from partial state")
    if any(e["authorisation_id"] == signed.authorisation_id
           for e in consumption_entries):
        raise _config(
            "ceremony_already_consumed",
            "this authorisation was already consumed")
    if any(e["kind"] == "consume"
           and e["format"] == "ceremony-consumption"
           and e["decision_id"] == signed.authorisation_id
           for e in signing_entries):
        raise _config(
            "ceremony_already_consumed",
            "this authorisation was already consumed")
    # (6) Issuance presence, with field match.
    try:
        issued = CeremonyAuthorisationLedger(
            config.home).find_by_authorisation_id(
                signed.authorisation_id)
    except Exception:
        raise _config(
            "ledger_failed",
            "the ceremony journal could not be read; refusing "
            "to consume from partial state")
    if issued is None \
            or issued["payload_hash"] != signed.payload_hash \
            or issued["ceremony_id"] != signed.ceremony_id \
            or issued["evidence_hash"] != signed.evidence_hash:
        raise _config(
            "ceremony_not_issued",
            "this authorisation is absent from the ceremony "
            "journal, or its issued fields do not match")
    # (7) Head rules against the consumption snapshot (the
    # commit append re-checks them against fresh entries).
    try:
        CeremonyConsumptionLedger.check_head(
            consumption_entries, signed)
    except AlreadyConsumedError:
        raise _config(
            "ceremony_already_consumed",
            "this authorisation's target was already consumed")
    except HeadRegressionError as exc:
        raise _config("ceremony_head_regression", str(exc))
    # (8) Commit (cycle 22, R2 order): consumption append —
    # the commit point; then the consumption-anchor update;
    # then the signing-ledger mirror; then the signing anchor.
    recorded_at = _now()
    try:
        entry = consumption_ledger.append_consumption(
            signed, recorded_at=recorded_at)
    except AlreadyConsumedError:
        raise _config(
            "ceremony_already_consumed",
            "this authorisation was already consumed")
    except HeadRegressionError as exc:
        raise _config("ceremony_head_regression", str(exc))
    except Exception:
        raise _config(
            "ledger_failed",
            "the consumption could not be committed")
    _update_ceremony_consumption_anchor(config)
    try:
        SigningLedger(config.home).append_ceremony_consumption(
            signed, recorded_at=recorded_at)
    except Exception:
        raise _config(
            "ledger_failed",
            "the consumption was committed in the consumption "
            "journal but could not be mirrored in the signing "
            "ledger; the authorisation stays burned and no "
            "success is returned — recovery is a new ceremony")
    _update_anchor(config)
    return {"authorisation_id": signed.authorisation_id,
            "ceremony_id": signed.ceremony_id,
            "consumption_seq": entry["seq"],
            "new_cycle_seq": signed.candidate["cycle_seq"],
            "new_payload_hash": signed.candidate["payload_hash"]}


_MODES = {"gate": _mode_gate, "sealed_eval": _mode_sealed_eval,
          "verify_envelope": _mode_verify_envelope,
          "submit_claim": _mode_submit_claim,
          "issue_attestation": _mode_issue_attestation,
          "ceremony_authorise": _mode_ceremony_authorise,
          "ceremony_consume": _mode_ceremony_consume}


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
