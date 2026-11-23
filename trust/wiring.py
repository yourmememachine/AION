"""Production signed-path wiring: the sanctioned construction
site for the production verifier client and the production
memory store.

This module exists so that production code has exactly one
place that builds a verifier client and one place that opens
the memory store for production use, each behind strict
validation. The trust lint (tests/test_trust_lint.py) counts
the constructions in this file: exactly one of each is
allowlisted here, and any other production construction in
the detected forms (bare / attribute / import-alias
constructions) fails the build; the lint's known blind spots
(getattr-style indirection, bare method references,
functools.partial wrapping, subclassing a watched class, and
name-reassignment) are not detected — see
tests/test_trust_lint.py.

HONESTY — what this module is and is not (seat-3's preserved
finding from the production-wiring design note): these are
parameterised factories, and a parameterised factory is a
laundering surface under a same-user threat model. What is
provided here is enforcement by validation plus lint, NOT a
capability boundary: any code running as the same OS user can
ignore this module, construct the underlying classes directly
(the lint, not the runtime, is what fails the build for that),
read the key file, or edit the store file. The deployment-grade
form is different in kind, not in degree: it derives its
configuration only from the root-owned wrapper env file
(deploy/verifier-identity), takes no path, env or pin arguments
at all, and returns results rather than handles. This module is
the in-repo, same-user step toward that form; do not describe
it as the boundary itself.

Declared residuals — catalogued in the design note and NOT
closed by this module:

- Genesis / joint deletion: open_production_store refuses a
  missing memory.json rather than bootstrapping, but a
  same-user actor who deletes the store (or the store together
  with its migration journal) can still start over through
  other construction paths; only the lint stands in the way.
- Builder-owned keys: nothing here establishes who owns the
  key file the env names; key custody is a deployment fact.
- Self-asserted pins: the signer and key pins are checked for
  consistency against the env and the key-id form, but their
  provenance is the caller's out-of-band channel, which this
  module cannot verify. A caller who pins whatever the env
  already says has pinned nothing.
- Fake verifier modules: the client spawns its verifier module
  by name from the repository on the Python path; same-user
  code that can shadow that module defeats the spawn.
- Anchor placement: the two anchor paths are validated as
  absolute and resolved outside the verifier home at
  construction time in this process, but the verifier re-reads
  them at spawn time in its own process — see TOCTOU below.
- Joint journal+anchor rollback: rolling the store file, its
  migration journal and its external anchors back together,
  consistently, is not detected by anything in this module.
- Check/use TOCTOU: validation happens here, use happens
  later (at spawn, at commit). Files, env-derived paths and
  store state can move between the two; the strong commit form
  narrows the commit-side window by binding the store's state
  digest under the store's own lock, but no check in this
  module eliminates the class. Inside open_production_store
  itself there is an open-side window between the read-only
  inspection of memory.json and the MemoryStore construction:
  a file swapped in that window could otherwise be opened on
  the strength of the earlier inspection. That window is now
  narrowed by byte-binding and state-binding — the inspected
  bytes are captured during inspection and, after
  construction, the file is re-read and the store is refused
  (not handed out) if the bytes differ from the inspected
  bytes, and the constructed store's state digest is also
  compared to the inspected document's state_digest field
  and the store is refused if that differs. The remaining
  ABA residual is a swap restored BEFORE the load:
  indistinguishable from no swap and harmless, because the
  loaded state is the inspected state. A straddle — a swap
  restored after the load but before the re-read, so the
  re-read bytes match again — is now detected via the state
  binding, because the loaded state's digest differs from
  the inspected document's state_digest.

Production client rules (production_client): the env mapping
is copied and the copy is validated BEFORE any client exists
and before anything can be spawned. Keys are restricted to the
wrapper's allowlist as shipped in
deploy/verifier-identity/run-verifier.sh (ALLOWED_KEYS, 20
names — the shipped wrapper governs). An unknown key
refuses, including AION_SHIP_ANCHOR_PATH, which does not exist
anywhere in the verifier's configuration. The five core names,
the deployment mode and all three anchor paths are required
non-empty; the mode must be exactly "production" (the verifier
refuses an absent mode too, and a wiring layer that let
"research" through would be a one-string downgrade of every
guarantee the anchors provide). The INIT ceremony flags are
refused for any value other than the verifier's explicit-off
spellings (absent, empty, or "0"): ceremonies are operator acts
performed outside production steady state. Both anchor paths
must be absolute, distinct from each other, and resolved
outside the verifier home. The pins are mandatory: the signer
pin must equal the env's signer id, and the key pin must be in
the key-<16 lowercase hex> form and is supplied out-of-band —
this function never reads the key file, so the key id cannot
be derived here and a caller who does not already know it
cannot use this factory. The ceremony public-key pin is
mandatory too: it must be a CeremonyPublicKey supplied
out-of-band, and None refuses — a production client that
cannot accept ceremonies must be impossible to build, not
merely unusable at first ceremony use. Every error names the
variable and never carries its value.

Wrapper routing is REFUSED, not emulated: the verifier client
has no command hook (it spawns its module directly), and the
wrapper discards the caller's environment by design, so there
is no honest way to route this client's spawn through
run-verifier.sh. Asking for it raises. Extending the client
with a command hook is its own backlog item
(verifier-wrapper-routing).

Production store rules (open_production_store): genesis is a
refusal — a missing memory.json is never a bootstrap. The
persisted security mode is read by parsing the file directly,
WITHOUT constructing the store first, because the store's
constructor has side effects (it creates the directory, can
ratchet the persisted mode on save, and quarantines a corrupt
file); inspection must not mutate. Only a file persisted as
signed_only is then opened, through the store's signed_only
constructor: the inspected bytes are captured during
inspection, and after construction the file is re-read and
compared to those inspected bytes and the constructed
store's state digest is compared to the inspected
document's state_digest field — if either differs, the
store is refused and not handed out, so a file whose loaded
state differs from the inspected document is not handed out
as a production store. The constructed instance's mode is
also re-asserted before the store is handed out.

Production commit rules (commit_production): the strong form
is the only form. A signed attestation must be presented, the
underlying commit is always invoked with attestation required,
and the expected state digest defaults to the store's current
digest when the caller does not supply one. There is
deliberately no parameter in this module for supplying the
current time: freshness verdicts stay on the host clock inside
the verification path, never on a caller-supplied clock.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

from memory.store import (
    MAX_MEMORY_BYTES,
    CorruptMemoryError,
    MemoryError,
    MemoryStore,
)
from signing.ceremony_authorisation import CeremonyPublicKey
from signing.gate_decision import SigningError, commit_signed
from trust.client import VerifierClient
from trust.errors import VerifierConfigError

__all__ = [
    "ALLOWED_ENV_KEYS",
    "REQUIRED_ENV_KEYS",
    "commit_production",
    "open_production_store",
    "production_client",
]

# The wrapper's allowlist, copied from ALLOWED_KEYS in
# deploy/verifier-identity/run-verifier.sh as shipped (20
# names). A key outside this set is not verifier configuration
# and refuses; the verifier itself would ignore or reject it,
# and a wiring layer that passed it through would be smuggling
# configuration past the wrapper's contract.
ALLOWED_ENV_KEYS = frozenset({
    "AION_VERIFIER_KEY_PATH",
    "AION_VERIFIER_SIGNER_ID",
    "AION_VERIFIER_ACTOR_ID",
    "AION_REGISTRY_DIR",
    "AION_VERIFIER_HOME",
    "AION_VERIFIER_TTL_SECONDS",
    "AION_VERIFIER_PURPOSE",
    "AION_VERIFIER_PROPOSAL_BUDGET",
    "AION_VERIFIER_IDENTITY_BUDGET",
    "AION_ANCHOR_PATH",
    "AION_ANCHOR_INIT",
    "AION_BUDGETS_ANCHOR_PATH",
    "AION_BUDGETS_ANCHOR_INIT",
    "AION_DEPLOYMENT_MODE",
    "AION_CEREMONY_OPERATORS",
    "AION_CEREMONY_EVIDENCE_DIR",
    "AION_CEREMONY_SIGNING_SEED_PATH",
    "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH",
    "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT",
    "AION_SUPERSESSION_APPROVER_PUBLIC_KEY",
})

# Required non-empty for a production client: the five core
# names the verifier itself requires, the deployment mode, and
# all three anchor paths (production makes anchoring mandatory and
# fail-closed, so an unanchored production client is a
# misconfiguration, not a weaker-but-valid one).
# AION_CEREMONY_OPERATORS, AION_CEREMONY_EVIDENCE_DIR and
# AION_CEREMONY_SIGNING_SEED_PATH (cycle 20) are allowlisted
# but deliberately NOT wiring-required, mirroring the operators
# treatment: production *startup* refusal for a missing
# ceremony variable is the verifier's own rule, and wiring's
# required set is the client-construction minimum. A production
# client can therefore be constructed with an env lacking them;
# the verifier it spawns will refuse to start in production —
# fail-closed, one layer down.
REQUIRED_ENV_KEYS = (
    "AION_VERIFIER_KEY_PATH",
    "AION_VERIFIER_SIGNER_ID",
    "AION_VERIFIER_ACTOR_ID",
    "AION_REGISTRY_DIR",
    "AION_VERIFIER_HOME",
    "AION_DEPLOYMENT_MODE",
    "AION_ANCHOR_PATH",
    "AION_BUDGETS_ANCHOR_PATH",
    "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH",
)

_INIT_ENV_KEYS = ("AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_INIT",
                  "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT")
_ANCHOR_ENV_KEYS = ("AION_ANCHOR_PATH", "AION_BUDGETS_ANCHOR_PATH",
                    "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH")
_KEY_ID_RE = re.compile(r"key-[0-9a-f]{16}")

# The only launch mode this factory performs: the client's
# normal same-user spawn of its verifier module.
_LAUNCH_SAME_USER = "same-user"


def _config_refusal(variable: str, problem: str):
    """Raise a configuration refusal that names the variable
    and never carries its value."""
    raise VerifierConfigError(f"{variable}: {problem}")


def production_client(verifier_env, *, expected_signer_id,
                      expected_key_id, authorisation_public_key,
                      launch=_LAUNCH_SAME_USER):
    """Build the production verifier client from a validated
    copy of the given env mapping.

    Validation happens entirely before construction, so a
    refusal means no client existed and nothing was spawned.
    See the module docstring for the full rule set and for what
    this validation does not prove. Returns a client whose
    deployment-mode expectation is pinned to "production": a
    verifier that reports any other mode is refused by the
    client at response time. All three pins (signer, key,
    ceremony public key) are mandatory keyword arguments;
    omitting any is a TypeError, and passing None for the
    ceremony pin is a VerifierConfigError.

    This factory is validation, not a boundary: a same-user
    caller can ignore it and construct the underlying object
    directly (see the module docstring).
    """
    # Wrapper routing first, because it is categorical: there is
    # no fallback from a refused routing to the same-user spawn.
    if launch == "wrapper":
        raise VerifierConfigError(
            "launch='wrapper' is refused: the verifier client "
            "has no command hook to route its spawn through "
            "run-verifier.sh, and the wrapper discards caller "
            "environment by design; silently falling back to a "
            "same-user spawn would misrepresent the deployment")
    if launch != _LAUNCH_SAME_USER:
        raise VerifierConfigError(
            "launch: unknown launch mode; the only supported "
            "launch is the client's normal same-user spawn")

    if not isinstance(verifier_env, Mapping):
        raise VerifierConfigError(
            "verifier_env: must be a mapping of verifier "
            "environment variables")
    # Validate a copy; the caller's mapping is never mutated and
    # never handed to the client unvalidated.
    env = dict(verifier_env)

    for key in env:
        if not isinstance(key, str) or key not in ALLOWED_ENV_KEYS:
            _config_refusal(
                str(key),
                "not an allowlisted verifier variable; unknown "
                "keys are refused, not passed through")
    for key, value in env.items():
        if not isinstance(value, str):
            _config_refusal(
                key, "verifier environment values must be text")

    for name in REQUIRED_ENV_KEYS:
        if name not in env or env[name].strip() == "":
            _config_refusal(
                name,
                "required for a production client and must be "
                "non-empty")

    # Absolute-path requirement for the home, key and registry
    # paths: wiring's "resolved outside home" guarantee must
    # not be cwd-dependent, so a relative spelling refuses
    # rather than resolving against whatever cwd this process
    # happens to have.
    for name in ("AION_VERIFIER_HOME", "AION_VERIFIER_KEY_PATH",
                 "AION_REGISTRY_DIR"):
        if not Path(env[name]).is_absolute():
            _config_refusal(
                name, "must be an absolute path")

    if env["AION_DEPLOYMENT_MODE"] != "production":
        _config_refusal(
            "AION_DEPLOYMENT_MODE",
            "must be exactly 'production' for a production "
            "client; an absent or weaker mode is a downgrade, "
            "not a default")

    for name in _INIT_ENV_KEYS:
        if name in env and env[name] not in ("", "0"):
            _config_refusal(
                name,
                "INIT ceremony flags are forbidden in production "
                "steady state; anchor ceremonies are operator "
                "acts performed outside production")

    home_resolved = Path(env["AION_VERIFIER_HOME"]).resolve()
    key_resolved = Path(env["AION_VERIFIER_KEY_PATH"]).resolve()
    registry_resolved = Path(env["AION_REGISTRY_DIR"]).resolve()
    resolved_anchors = {}
    for name in _ANCHOR_ENV_KEYS:
        anchor = Path(env[name])
        if not anchor.is_absolute():
            _config_refusal(name, "anchor path must be absolute")
        resolved = anchor.resolve()
        if resolved == home_resolved \
                or home_resolved in resolved.parents:
            _config_refusal(
                name,
                "anchor path must resolve outside "
                "AION_VERIFIER_HOME; an anchor inside the "
                "verifier home is rolled back with it")
        if resolved == key_resolved:
            _config_refusal(
                name,
                "anchor path must not equal "
                "AION_VERIFIER_KEY_PATH; an anchor that is the "
                "key file is overwritten or rolled back with it")
        if resolved == registry_resolved \
                or registry_resolved in resolved.parents:
            _config_refusal(
                name,
                "anchor path must not equal or sit inside "
                "AION_REGISTRY_DIR; an anchor inside the "
                "registry directory is rolled back with it")
        if resolved.is_dir():
            _config_refusal(
                name,
                "anchor path must not be an existing "
                "directory; an anchor must name a file")
        resolved_anchors[name] = resolved
    anchor_names = list(resolved_anchors)
    for index, first in enumerate(anchor_names):
        for second in anchor_names[index + 1:]:
            if resolved_anchors[first] == resolved_anchors[second]:
                _config_refusal(
                    f"{first} / {second}",
                    "the anchor paths must be distinct; one file "
                    "cannot anchor two ledgers")

    # Pins are mandatory and are checked without ever reading
    # the key file: the key id's provenance is the caller's
    # out-of-band knowledge, and a factory that derived it from
    # the key file would be pinning the deployment to itself.
    if not isinstance(expected_signer_id, str) \
            or not expected_signer_id:
        _config_refusal(
            "AION_VERIFIER_SIGNER_ID",
            "a signer pin (expected_signer_id) is mandatory "
            "for a production client")
    if expected_signer_id != env["AION_VERIFIER_SIGNER_ID"]:
        _config_refusal(
            "AION_VERIFIER_SIGNER_ID",
            "the signer pin does not match the env's signer "
            "id; refusing rather than pinning to whatever the "
            "env asserts")
    if not isinstance(expected_key_id, str) \
            or not _KEY_ID_RE.fullmatch(expected_key_id):
        raise VerifierConfigError(
            "expected_key_id: a key pin is mandatory and must "
            "be supplied out-of-band in the form "
            "key-<16 lowercase hex>")

    # Ceremony public-key pin: the third mandatory pin, beside
    # the signer and key pins. It is supplied out-of-band the
    # same way, as a CeremonyPublicKey object (its key_id is
    # derived from its bytes), and passed through to the
    # client, whose ceremony_authorise verifies envelope
    # signatures against it. Cycle 20 made this pin optional
    # at this factory on the reasoning that ceremony use was
    # optional for a production client; cycle 24 reverses that
    # (CROSS-CHECK-17, both external seats): a pinless
    # production client constructs fine and wedges only at
    # first ceremony use — exactly the moment the pin adopter
    # needs the ceremony to work — so construction-time
    # refusal is the only honest place for the refusal. A
    # production client that cannot accept ceremonies must be
    # impossible to build.
    if authorisation_public_key is None:
        raise VerifierConfigError(
            "authorisation_public_key: a ceremony public-key "
            "pin is mandatory for a production client; "
            "refusing None rather than constructing a client "
            "that would refuse every ceremony at first use")
    if not isinstance(authorisation_public_key,
                      CeremonyPublicKey):
        raise VerifierConfigError(
            "authorisation_public_key: must be a "
            "CeremonyPublicKey supplied out-of-band")

    return VerifierClient(
        verifier_env=env,
        expected_signer_id=expected_signer_id,
        expected_key_id=expected_key_id,
        authorisation_public_key=authorisation_public_key,
        expected_deployment_mode="production")


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key in memory file: {key}")
        out[key] = value
    return out


def _reject_constant(value: str):
    # Mirror memory/store.py's _load strictness: non-finite
    # constants are corruption, refused at inspection.
    raise CorruptMemoryError(f"non-finite number in memory: {value}")


def _parse_float(text: str) -> float:
    # Mirror memory/store.py's _load strictness: non-finite
    # floats are corruption, refused at inspection.
    value = float(text)
    if not math.isfinite(value):
        raise CorruptMemoryError(f"non-finite number in memory: {text}")
    return value


def _persisted_security_mode(memory_file: Path):
    """Read the persisted security mode from memory.json
    WITHOUT constructing the store: plain parsing only, no
    directory creation, no ratchet, no quarantine. A malformed
    file is corruption and refuses; a file with no persisted
    mode is a legacy unsigned file and reports "unsigned".

    Returns (mode, sha256_hexdigest_of_inspected_bytes,
    state_digest): the byte digest binds the inspection to
    the exact bytes inspected, so the caller can re-read the
    file after construction and refuse if the bytes changed
    underfoot, and the document's own state_digest field
    binds the inspection to the inspected state, so the
    caller can compare it against the constructed store's
    state_digest() and refuse if the loaded state differs
    (see open_production_store). A document with no usable
    state_digest field (missing, not text, or empty) is
    corruption and refuses here at inspection, explicitly:
    the store's own validation would refuse such a file
    anyway, and wiring does not rely on that accidentally.
    Parsing uses strict hooks
    mirroring memory/store.py's _load (parse_constant and
    parse_float refusals plus the duplicate-key hook), so a
    NaN/Infinity file is refused here at inspection, without
    reaching construction (which would quarantine it)."""
    try:
        raw = memory_file.read_bytes()
    except OSError as exc:
        raise CorruptMemoryError(
            f"unreadable memory file: {exc}") from exc
    if len(raw) > MAX_MEMORY_BYTES:
        raise CorruptMemoryError("memory file exceeds size cap")
    try:
        doc = json.loads(raw.decode("utf-8"),
                         parse_constant=_reject_constant,
                         parse_float=_parse_float,
                         object_pairs_hook=_no_duplicate_keys)
    except CorruptMemoryError:
        raise
    except Exception as exc:
        raise CorruptMemoryError(
            f"unreadable memory file: {exc}") from exc
    if not isinstance(doc, dict):
        raise CorruptMemoryError(
            "memory file is not a JSON object; refusing to open")
    inspected_state_digest = doc.get("state_digest")
    if not isinstance(inspected_state_digest, str) \
            or not inspected_state_digest:
        raise CorruptMemoryError(
            "memory file has no usable state_digest field; "
            "refusing to open")
    return doc.get("security_mode", "unsigned"), \
        hashlib.sha256(raw).hexdigest(), inspected_state_digest


def open_production_store(memory_dir):
    """Open an existing production memory store.

    Genesis is refused: a missing memory.json means there is no
    production store here, and silently bootstrapping an empty
    unsigned store in its place is exactly the downgrade this
    factory exists to prevent. The persisted mode is inspected
    read-only first; only a signed_only file is constructed,
    and the constructed instance must still report signed_only
    before it is handed out.

    Refusals are of two types. MemoryError: genesis (no
    memory.json), a persisted mode other than signed_only, or
    a file that changed underfoot — the bytes re-read after
    construction differ from the inspected bytes captured
    during inspection, or the constructed store's state
    digest differs from the inspected document's
    state_digest field, so the store that was constructed is
    not the store that was inspected and its handle is not
    returned. CorruptMemoryError: corrupt content refused by
    inspection (malformed JSON, duplicate keys, non-finite
    numbers, oversize or unreadable file, non-object
    document, or no usable state_digest field) or by
    construction (the store's own load-time validation).

    A refused open after a corrupt swap may leave the store's
    own quarantine copy (memory.corrupt-<stamp>.json) in the
    directory — tamper evidence written by the store during
    construction, not by wiring's inspection, which never
    writes.

    This factory is validation, not a boundary: a same-user
    caller can ignore it and construct the underlying object
    directly (see the module docstring).
    """
    directory = Path(memory_dir)
    memory_file = directory / "memory.json"
    if not memory_file.is_file():
        raise MemoryError(
            "open_production_store refuses genesis: no "
            "memory.json exists in the store directory, and a "
            "missing production store is a refusal, not a "
            "bootstrap")
    persisted_mode, inspected_digest, inspected_state_digest = \
        _persisted_security_mode(memory_file)
    if persisted_mode != "signed_only":
        raise MemoryError(
            "open_production_store requires a store persisted "
            "in signed_only mode; the persisted security_mode "
            "is not signed_only, and opening it here would "
            "ratchet or downgrade it silently")
    store = MemoryStore(directory, signed_only=True)
    # Byte-binding: re-read the file after construction and
    # refuse if it is not exactly the bytes that were
    # inspected. Without this, a file swapped between
    # inspection and construction (e.g. an unsigned file
    # swapped in) would be opened on the strength of the
    # earlier signed_only inspection, because
    # MemoryStore(signed_only=True) ratchets in memory.
    try:
        current_raw = memory_file.read_bytes()
    except OSError as exc:
        raise MemoryError(
            "open_production_store refuses: memory.json "
            "changed underfoot — it could not be re-read "
            "after construction to verify it against the "
            "inspected bytes") from exc
    if hashlib.sha256(current_raw).hexdigest() != inspected_digest:
        raise MemoryError(
            "open_production_store refuses: memory.json "
            "changed underfoot — the bytes after construction "
            "differ from the inspected bytes, so the "
            "constructed store is not handed out")
    # State-binding: bind the CONSTRUCTED OBJECT to the
    # inspected document. The byte re-read above binds only
    # the bytes on disk at re-read time; a straddle swap
    # (unsigned file loaded by construction, then the signed
    # bytes restored before the re-read) passes that check
    # while the handle's loaded state is the swapped-in
    # file's state. Comparing the constructed store's state
    # digest to the inspected document's state_digest field
    # detects that straddle.
    if store.state_digest() != inspected_state_digest:
        raise MemoryError(
            "open_production_store refuses: memory.json "
            "changed underfoot — the constructed store's "
            "state digest differs from the inspected "
            "document's state_digest, so the constructed "
            "store is not handed out")
    if store.signed_only is not True \
            or store.security_mode != "signed_only":
        raise MemoryError(
            "the constructed store does not report signed_only "
            "mode; refusing to hand it out as a production "
            "store")
    return store


def commit_production(store, entry_fields, signed, *,
                      signing_key, signed_attestation,
                      expected_signer_id,
                      expected_state_digest=None):
    """Commit one entry to a production store, strong form only.

    A signed attestation must be presented (there is no form of
    this helper without one), the underlying signed commit is
    always invoked with attestation required, and the expected
    state digest defaults to the store's current digest when
    the caller does not supply one, so the commit is bound to
    the store state the caller actually observed. The store
    must be a signed_only store, as open_production_store
    returns. Freshness is judged inside the verification path
    on the host clock; this helper accepts no time override.
    Returns the committed entry, as the store returns it.

    The expected_signer_id pin is mandatory: callers must pin
    it explicitly. The pin names the GATE DECISION's signer
    id. The presented signed attestation's verifier_id is NOT
    bound to the decision's verifier_id at this surface —
    attester eligibility is judged by the gate flow
    (decide_write) that produced the decision — and this
    non-binding is a declared limit of the strong form,
    recorded in the cycle-13 review.

    This factory is validation, not a boundary: a same-user
    caller can ignore it and construct the underlying object
    directly (see the module docstring).
    """
    if getattr(store, "signed_only", False) is not True:
        raise SigningError(
            "commit_production requires a signed_only store "
            "(see open_production_store); refusing to commit "
            "through the unsigned path")
    if signed_attestation is None:
        raise SigningError(
            "commit_production requires a presented signed "
            "attestation; the strong form is the only form")
    if expected_state_digest is None:
        expected_state_digest = store.state_digest()
    return commit_signed(
        store, entry_fields, signed,
        signing_key=signing_key,
        require_attestation=True,
        expected_signer_id=expected_signer_id,
        signed_attestation=signed_attestation,
        expected_state_digest=expected_state_digest)
