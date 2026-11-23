"""The supersession approval TOOL (cycle 25) — CREATE SIDE ONLY.

This module is the ONLY place in the repo that signs a
supersession approval (trust/supersession_approval.py carries
the verify-side primitives and deliberately no signing path).
It is a standalone CLI, invoked as a separate operation
outside the adopter's automated recovery path:

    python -m trust.supersession_approval_tool generate-key \
        --seed-path /path/to/approver.seed
    python -m trust.supersession_approval_tool public-key \
        --seed-path /path/to/approver.seed
    python -m trust.supersession_approval_tool approve \
        --seed-path /path/to/approver.seed --approver-id <id> \
        --pending-report pending.json --out approval.json

NOTHING in the running system imports this module: not the
verifier (it holds only the approver PUBLIC key, via the
AION_SUPERSESSION_APPROVER_PUBLIC_KEY env var), not the client,
not the pin adopter. That import absence — pinned by tests —
is the auditable form of cycle 25's core property: the
adopter's code path has no route to mint an approval. The
adopter stops on ceremony_supersede_required, writes a
pending-supersession report, and a later, separate invocation
of THIS tool is what turns the report into a signed approval
artefact (design: internal/cycle25-work/design-approval.md).

Key custody: the approver seed is a 32-byte Ed25519 seed in a
hex file, loaded here under the same discipline as the
ceremony seed loader (single-fd O_NOFOLLOW read, owner-only
mode, owner-uid check, size cap, never inside this repo). Its
path arrives via --seed-path or this process's own
AION_SUPERSESSION_APPROVER_SEED_PATH env var — a name that is
deliberately NOT a verifier env var: it is absent from the
verifier wrapper's allowlist (so run-verifier.sh HARD-FAILS
the launch if it is misplaced in the verifier env file; only
an occurrence in the invoking shell is discarded, by the
wrapper's clean environment) and refused as an
unknown key by trust/wiring.py. The seed type minted here,
SupersessionApproverKey, is disjoint from CeremonySigningKey,
so approver material can never be passed where ceremony
material is expected.

The tool performs no network, verifier or journal access and
cannot check that a pending report is truthful. It does not
need to: the verifier re-derives every bound fact from its own
journals before issuing a decision, so an approval over a
fabricated or stale report verifies cryptographically and
still refuses on binding. The tool's refusals are about the
ACT's shape: a report that is not about a
ceremony_supersede_required refusal, a report whose envelope
is a burned_unadopted recovery (an ordinary recovery is not a
supersession and must never acquire an approval), a refused
test seed, or a TTL outside [60, 3600].

Trust claim (verbatim in substance from the design): the
independence this creates is at the authorisation-event
level — a separately invoked, cryptographically independent
approval operation outside the adopter's automated recovery
path, with its own artefact and key — NOT a claim of
enforced human deliberation, a separate human, or a separate
OS user.

Cycle 26: approve requires an interactive typed
confirmation; no non-interactive override exists. Before
anything is signed or written, approve requires that
confirmation: stdin must be a TTY, a binding summary of the
pending report (the abandoned movement, the replacement
candidate, and the failed attempt) is printed, and the
operator must type the first 12 hex characters of the
candidate payload hash exactly. A non-interactive invocation
(piped, redirected, or otherwise not a TTY), a wrong token,
or EOF refuses and mints nothing. There is deliberately no
non-interactive override flag — no non-interactive override
exists — and if one is ever added its existence must be
disclosed in this claim. The interactive gate is a property
of the CLI main() approve path only; this module's
in-process signing functions (build_approval_for_report /
sign_supersession_approval) are deliberately ungated, since
the security boundary is approver-seed custody.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from signing import ed25519
from signing.ceremony_authorisation import (
    REASON_BURNED_UNADOPTED,
    REFUSED_TEST_SEEDS,
    ceremony_authorisation_envelope_from_dict,
    public_key_id_for,
)
from signing.gate_decision import (
    SigningError,
    _check_key_path,
    _check_owner_only_mode,
    _now,
    _parse_time,
    _sha256,
)
from trust.supersession_approval import (
    APPROVAL_TTL_DEFAULT_SECONDS,
    APPROVAL_TTL_MAX_SECONDS,
    REFUSAL_CODE_SUPERSESSION_REQUIRED,
    SignedSupersessionApproval,
    SupersessionApproverPublicKey,
    _payload_hash,
    _signed_blob,
    approval_id_for,
    supersession_approval_payload,
    supersession_approval_to_json,
)

SEED_PATH_ENV_VAR = "AION_SUPERSESSION_APPROVER_SEED_PATH"

_MAX_SEED_FILE_BYTES = 1024

_REPORT_KEYS = {"report", "refusal_code", "envelope",
                "operator_id", "head", "reported_at"}
_REPORT_KIND = "pending-supersession/1"
_HEAD_KEYS = {"authorisation_id", "ceremony_id",
              "old_cycle_seq", "old_payload_hash",
              "new_cycle_seq", "new_payload_hash",
              "seq", "entry_hash"}


# -- approver key -------------------------------------------------------------


@dataclass(frozen=True)
class SupersessionApproverKey:
    """Tool-side ONLY: the approver seed plus its derived public
    identity. Never logged whole: repr shows only the key id
    and a fingerprint of the public key."""

    seed: bytes
    public_key: bytes
    key_id: str

    def __repr__(self) -> str:  # never leak seed bytes into a log
        return (f"SupersessionApproverKey(key_id={self.key_id!r}, "
                f"public_fingerprint={_sha256(self.public_key)!r})")


def _make_approver_key(seed: bytes) -> SupersessionApproverKey:
    if not isinstance(seed, (bytes, bytearray)) \
            or len(seed) != ed25519.SEED_BYTES:
        raise SigningError(
            f"approver seed must be exactly {ed25519.SEED_BYTES} "
            f"bytes")
    seed = bytes(seed)
    if seed in REFUSED_TEST_SEEDS:
        raise SigningError("refusing a known test approver seed")
    public_key = ed25519.public_key_from_seed(seed)
    return SupersessionApproverKey(
        seed=seed, public_key=public_key,
        key_id=public_key_id_for(public_key))


def approver_public_key_for(
        key: SupersessionApproverKey) -> SupersessionApproverPublicKey:
    """The public pin corresponding to an approver key (the
    value provisioned into AION_SUPERSESSION_APPROVER_PUBLIC_KEY
    as hex, via the public-key subcommand)."""
    if not isinstance(key, SupersessionApproverKey):
        raise SigningError(
            "key must be a SupersessionApproverKey")
    return SupersessionApproverPublicKey(
        public_key=key.public_key, key_id=key.key_id)


def load_approver_seed(path, *, forbidden_roots=()) -> SupersessionApproverKey:
    """Load an approver seed file under the ceremony seed
    loader's discipline (mirrored from
    signing.ceremony_authorisation.load_ceremony_seed): the
    file is opened ONCE with O_NOFOLLOW|O_NONBLOCK, every
    property is checked by fstat on that fd, and the bytes are
    read bounded from the same fd; failing closed on a
    symlinked path component, a non-owner-only mode, a
    non-regular or oversize file, content that is not exactly
    32 bytes of lowercase hex, a location inside this repo or a
    caller-named forbidden root, an owner-uid mismatch (when
    the process euid is non-zero), or a known test seed."""
    target = _check_key_path(Path(path), forbidden_roots)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise SigningError(
            f"approver seed file is missing or unreadable: "
            f"{exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SigningError(
                "approver seed file is not a regular file")
        _check_owner_only_mode(info.st_mode,
                               what="approver seed file")
        euid = os.geteuid() if hasattr(os, "geteuid") else 0
        if euid != 0 and info.st_uid != euid:
            raise SigningError(
                "approver seed file is not owned by the "
                "current user")
        if info.st_size > _MAX_SEED_FILE_BYTES:
            raise SigningError(
                "approver seed file exceeds the size cap")
        chunks = []
        remaining = _MAX_SEED_FILE_BYTES + 1
        try:
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 4096))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError as exc:
            raise SigningError(
                f"approver seed file is unreadable: {exc}") from exc
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    if len(raw) > _MAX_SEED_FILE_BYTES:
        raise SigningError("approver seed file exceeds the size cap")
    raw = raw.strip()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SigningError(
            "approver seed file does not hold hex seed material"
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise SigningError(
            "approver seed file does not hold lowercase hex seed "
            "material")
    seed = bytes.fromhex(text)
    if len(seed) != ed25519.SEED_BYTES:
        raise SigningError(
            f"approver seed file must hold exactly "
            f"{ed25519.SEED_BYTES} bytes")
    return _make_approver_key(seed)


def generate_approver_key_file(path, *, forbidden_roots=()) -> SupersessionApproverKey:
    """Create a new 0600 approver seed file with O_EXCL; refuse
    to overwrite. The seed is an independent random draw — never
    derived from the ceremony seed or the snapshot signing key
    (provisioning discipline; equality with the ceremony key is
    additionally detected verifier-side at the public-key
    level)."""
    target = _check_key_path(Path(path), forbidden_roots)
    if target.exists():
        raise SigningError(
            "approver seed file already exists; refusing to "
            "overwrite")
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise SigningError(
            f"cannot create approver seed directory: {exc}") from exc
    seed = secrets.token_bytes(ed25519.SEED_BYTES)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600)
    except OSError as exc:
        raise SigningError(
            f"cannot create approver seed file: {exc}") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(seed.hex().encode("ascii") + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return _make_approver_key(seed)


# -- signing ------------------------------------------------------------------


def sign_supersession_approval(
        *, approver_key: SupersessionApproverKey, approver_id,
        abandoned, replacement, failed_attempt,
        ttl_seconds=APPROVAL_TTL_DEFAULT_SECONDS,
        now=None) -> SignedSupersessionApproval:
    """Sign one supersession approval under the approver seed.
    TOOL-SIDE ONLY — the only function in the repo that produces
    this signature. TTL: default 900 s; a TTL outside
    [60, APPROVAL_TTL_MAX_SECONDS (3600)] REFUSES — it is never
    silently clamped to the window."""
    if not isinstance(approver_key, SupersessionApproverKey):
        raise SigningError(
            "approver_key must be a SupersessionApproverKey")
    if approver_key.key_id \
            != public_key_id_for(approver_key.public_key) \
            or approver_key.public_key \
            != ed25519.public_key_from_seed(approver_key.seed):
        raise SigningError(
            "approver key id or public key does not match its "
            "seed material")
    if not isinstance(ttl_seconds, int) \
            or isinstance(ttl_seconds, bool) \
            or ttl_seconds < 60 \
            or ttl_seconds > APPROVAL_TTL_MAX_SECONDS:
        raise SigningError("ttl_seconds outside the TTL bounds")
    approved_at = _now() if now is None else now
    approved = _parse_time(approved_at, "approved_at")
    expires_at = (approved + timedelta(seconds=ttl_seconds)).isoformat()
    payload = supersession_approval_payload(
        approver_id=approver_id, key_id=approver_key.key_id,
        abandoned=abandoned, replacement=replacement,
        failed_attempt=failed_attempt,
        approved_at=approved_at, expires_at=expires_at)
    payload_hash = _payload_hash(payload)
    signature = ed25519.sign(
        approver_key.seed,
        _signed_blob(payload_hash, approver_key.key_id)).hex()
    return SignedSupersessionApproval(
        approver_id=approver_id, key_id=approver_key.key_id,
        abandoned=payload["abandoned"],
        replacement=payload["replacement"],
        failed_attempt=payload["failed_attempt"],
        approved_at=approved_at, expires_at=expires_at,
        payload_hash=payload_hash,
        approval_id=approval_id_for(payload_hash,
                                    approver_key.key_id),
        signature=signature)


def build_approval_for_report(
        *, approver_key: SupersessionApproverKey, approver_id,
        report, ttl_seconds=APPROVAL_TTL_DEFAULT_SECONDS,
        now=None) -> SignedSupersessionApproval:
    """Build and sign an approval from a pending-supersession
    report (design section 7 — the adopter's stop-and-report
    artefact). The binding projections are built HERE, from the
    report's envelope and head blocks, so the CLI and any test
    driving the tool in-process share one construction.

    Refuses (SigningError): a report that is not a
    pending-supersession/1 report, a refusal_code other than
    ceremony_supersede_required, a head block that is not the
    exact shape, or an envelope whose reason is
    burned_unadopted."""
    if not isinstance(report, dict) or set(report) != _REPORT_KEYS:
        raise SigningError(
            "pending report has missing or unknown keys")
    if report["report"] != _REPORT_KIND:
        raise SigningError(
            f"pending report kind must be {_REPORT_KIND!r}")
    if report["refusal_code"] != REFUSAL_CODE_SUPERSESSION_REQUIRED:
        raise SigningError(
            "pending report is not about a "
            f"{REFUSAL_CODE_SUPERSESSION_REQUIRED} refusal; "
            "refusing to approve any other event")
    envelope = ceremony_authorisation_envelope_from_dict(
        report["envelope"])
    if envelope.reason == REASON_BURNED_UNADOPTED:
        raise SigningError(
            "the pending envelope is a burned_unadopted "
            "recovery; an ordinary recovery is not a "
            "supersession and cannot be approved")
    if report["operator_id"] != envelope.operator_id:
        raise SigningError(
            "pending report operator_id does not match the "
            "envelope's operator_id")
    head = report["head"]
    if not isinstance(head, dict) or set(head) != _HEAD_KEYS:
        raise SigningError(
            "pending report head must carry exactly "
            "authorisation_id, ceremony_id, old_cycle_seq, "
            "old_payload_hash, new_cycle_seq, new_payload_hash, "
            "seq and entry_hash")
    if envelope.old_pin is None:
        raise SigningError(
            "the pending envelope carries no old pin; it cannot "
            "stand in the supersede relation to a head")
    abandoned = {
        "authorisation_id": head["authorisation_id"],
        "ceremony_id": head["ceremony_id"],
        "old_cycle_seq": head["old_cycle_seq"],
        "old_payload_hash": head["old_payload_hash"],
        "new_cycle_seq": head["new_cycle_seq"],
        "new_payload_hash": head["new_payload_hash"]}
    replacement = {
        "authorisation_id": envelope.authorisation_id,
        "ceremony_id": envelope.ceremony_id,
        "reason": envelope.reason,
        "operator_id": envelope.operator_id,
        "superseding_old_cycle_seq": envelope.old_pin["cycle_seq"],
        "superseding_old_payload_hash":
            envelope.old_pin["payload_hash"],
        "candidate_cycle_seq": envelope.candidate["cycle_seq"],
        "candidate_payload_hash": envelope.candidate["payload_hash"]}
    failed_attempt = {
        "attempted_authorisation_id": envelope.authorisation_id,
        "refusal_code": REFUSAL_CODE_SUPERSESSION_REQUIRED,
        "head_authorisation_id": head["authorisation_id"],
        "head_entry_seq": head["seq"],
        "head_entry_hash": head["entry_hash"]}
    return sign_supersession_approval(
        approver_key=approver_key, approver_id=approver_id,
        abandoned=abandoned, replacement=replacement,
        failed_attempt=failed_attempt, ttl_seconds=ttl_seconds,
        now=now)


# -- interactive confirmation gate (cycle 26) ---------------------------------

_CONFIRMATION_TOKEN_CHARS = 12


def _short_id(value) -> str:
    """Short form of a hex authorisation id for the binding
    summary: the first 12 characters."""
    if not isinstance(value, str) or len(value) < 12:
        raise SigningError(
            "pending report is malformed: an authorisation id "
            "needed for the confirmation summary is missing or "
            "not a string")
    return value[:12]


def _confirmation_summary(report) -> tuple[str, str]:
    """Build the binding summary for the interactive gate from
    the pending report dict, and return (summary_text,
    confirmation_token). Defensive extraction only: any
    missing or ill-typed field the summary needs raises
    SigningError, so a malformed report refuses here (or at
    build_approval_for_report) before anything is signed."""
    if not isinstance(report, dict):
        raise SigningError(
            "pending report is malformed: not an object; cannot "
            "build the confirmation summary")
    try:
        head = report["head"]
        envelope = report["envelope"]
        candidate = envelope["candidate"]
        old_cycle_seq = head["old_cycle_seq"]
        new_cycle_seq = head["new_cycle_seq"]
        head_authorisation_id = head["authorisation_id"]
        candidate_cycle_seq = candidate["cycle_seq"]
        candidate_payload_hash = candidate["payload_hash"]
        attempted_authorisation_id = envelope["authorisation_id"]
        refusal_code = report["refusal_code"]
    except (KeyError, TypeError) as exc:
        raise SigningError(
            "pending report is malformed: a field needed for "
            "the confirmation summary is missing") from exc
    if not isinstance(candidate_payload_hash, str) \
            or len(candidate_payload_hash) \
            < _CONFIRMATION_TOKEN_CHARS:
        raise SigningError(
            "pending report is malformed: the candidate payload "
            "hash needed for the confirmation summary is missing "
            "or not a string")
    token = candidate_payload_hash[:_CONFIRMATION_TOKEN_CHARS]
    summary = (
        "Supersession approval — interactive confirmation "
        "required.\n"
        f"Abandoned movement: cycle {old_cycle_seq} -> "
        f"{new_cycle_seq} "
        f"(authorisation {_short_id(head_authorisation_id)}…)\n"
        f"Replacement candidate: cycle {candidate_cycle_seq}, "
        f"payload hash {candidate_payload_hash}\n"
        f"Failed attempt: authorisation "
        f"{_short_id(attempted_authorisation_id)}…, "
        f"refusal code {refusal_code}\n"
        f"Confirmation code (first "
        f"{_CONFIRMATION_TOKEN_CHARS} hex characters of the "
        f"candidate payload hash): {token}")
    return summary, token


def _require_interactive_confirmation(report, *, stream=None) -> None:
    """Cycle 26 gate on `approve`: refuse unless an operator
    at a TTY confirms the binding summary by typing the
    confirmation token exactly.

    `stream` defaults to sys.stdin resolved AT CALL TIME (not
    import time) so tests can substitute a fake TTY. Raises
    SigningError — minting and writing nothing — when stdin
    is not a TTY, when the typed line is empty/EOF, or when it
    does not match the token."""
    if stream is None:
        stream = sys.stdin
    summary, token = _confirmation_summary(report)
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        raise SigningError(
            "approve requires an interactive confirmation: "
            "stdin is not a TTY; refusing to sign "
            "non-interactively")
    print(summary)
    print("Type the confirmation code exactly to approve: ",
          end="", flush=True)
    line = stream.readline()
    if not line or line.strip() != token:
        raise SigningError(
            "interactive confirmation failed: the typed "
            "confirmation code does not match; refusing to sign")
    print("Confirmation accepted.")


# -- CLI ------------------------------------------------------------------------


def _seed_path(args) -> str:
    path = args.seed_path or os.environ.get(SEED_PATH_ENV_VAR, "")
    if not path:
        raise SigningError(
            "no approver seed path: pass --seed-path or set "
            f"{SEED_PATH_ENV_VAR} in the tool's own environment")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="supersession_approval_tool",
        description="Mint supersession approvals (cycle 25) via "
                    "a separately invoked, cryptographically "
                    "independent approval operation outside the "
                    "adopter's automated recovery path; approve "
                    "requires an interactive typed confirmation; "
                    "no non-interactive override exists.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate-key", "public-key", "approve"):
        p = sub.add_parser(name)
        p.add_argument("--seed-path", default=None)
    approve = sub.choices["approve"]
    approve.add_argument("--approver-id", required=True)
    approve.add_argument("--pending-report", required=True)
    approve.add_argument("--out", required=True)
    approve.add_argument("--ttl-seconds", type=int,
                         default=APPROVAL_TTL_DEFAULT_SECONDS)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-key":
            key = generate_approver_key_file(_seed_path(args))
            print(f"approver key created: key_id={key.key_id} "
                  f"public_key={key.public_key.hex()}")
            return 0
        key = load_approver_seed(_seed_path(args))
        if args.command == "public-key":
            print(key.public_key.hex())
            return 0
        # approve
        try:
            report = json.loads(
                Path(args.pending_report).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SigningError(
                f"pending report is unreadable: {exc}") from exc
        # Cycle 26: the interactive confirmation gate runs
        # BEFORE any signing or output file creation, so an
        # interrupt at the prompt mints nothing.
        try:
            _require_interactive_confirmation(report)
        except KeyboardInterrupt:
            print("supersession_approval_tool: interactive "
                  "confirmation interrupted; refusing to sign",
                  file=sys.stderr)
            return 2
        approval = build_approval_for_report(
            approver_key=key, approver_id=args.approver_id,
            report=report, ttl_seconds=args.ttl_seconds)
        out = Path(args.out)
        if out.exists():
            raise SigningError(
                "output file already exists; refusing to "
                "overwrite an approval artefact")
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(supersession_approval_to_json(approval) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        print(f"approval written: approval_id={approval.approval_id}")
        return 0
    except SigningError as exc:
        print(f"supersession_approval_tool: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
