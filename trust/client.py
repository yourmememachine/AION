"""Builder-side verifier client. Key-free by construction.

This module never holds key material or any signing capability
— a meta-test in the suite greps it for exactly that. Precision:
the client DOES pass the orchestrator-supplied verifier
environment — which names the key file's location — through to
the subprocess untouched; it never opens that file and cannot
sign. What it CAN check without the key, it must: the response echoes
the request, the envelope is structurally valid and internally
consistent (payload re-derivation, payload hash, decision id),
the signer identity matches the orchestrator's pins, the expiry
window is not already past, and (for sealed_eval) the attestation
is bound to the very transcript the client sent, via the unkeyed
answers hash. The client also supports an optional deployment-
mode pin (expected_deployment_mode): when set, an ok response
must carry a deployment_mode field equal to the pin, and the
observed mode is recorded on the client either way. That field
is verifier-reported: a compromised verifier can lie about its
mode; the pin detects stale/downgraded verifiers and config
drift, it is not cryptographic evidence. What it cannot do is
verify any MAC: client-side
acceptance means "well-formed, consistently bound, from the
pinned signer identity, issued by the process the orchestrator
launched". Cryptographic verification happens at key-holding
consumers (commit_signed, verify_eval_attestation, shipcheck).
Trust on this hop comes from orchestrator launch control, not
from the response bytes.

Fail-closed, always: every transport, protocol or configuration
failure raises. gate() returns signed REJECTIONS as data (the
caller must inspect .accepted) and raises for everything that is
not a signed decision. verify_envelope() raises on transport
failure rather than returning valid=False — "the verifier said
no" and "the verifier never ran" are different audit facts.
Error codes/details surfaced from verifier error documents are
untrusted diagnostic text: the client raises on them, but no
caller should treat their wording as evidence. Transport note:
subprocess output is captured in memory and size-checked after
capture (max_response_bytes); a rogue verifier module can waste
memory up to what the OS allows before the check fires — the
cap bounds acceptance, not capture.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from signing.attestation import attestation_envelope_from_dict
from signing.gate_decision import (
    SigningError,
    _canonical,
    _sha256,
    decision_id_for,
    envelope_from_dict,
    payload_hash_for,
)
from trust import protocol
from trust.attestation import PAYLOAD_KEYS, answers_hash_for, \
    rebuild_eval_payload
from trust.errors import (
    VerifierConfigError,
    VerifierProtocolError,
    VerifierTimeout,
    VerifierUnavailable,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_STDERR_EXCERPT = 500


@dataclass(frozen=True)
class GateOutcome:
    envelope: object          # SignedGateDecision
    gate_inputs_hash: str
    manifest_hash: str
    registry_digest: str

    @property
    def accepted(self) -> bool:
        return self.envelope.decision.accepted is True


@dataclass(frozen=True)
class Verdict:
    valid: bool
    reasons: tuple


def _stderr_excerpt(result) -> str:
    raw = (result.stderr or b"")[:protocol.MAX_STDERR_BYTES]
    return raw.decode("utf-8", errors="replace")[-_STDERR_EXCERPT:]


class VerifierClient:
    """One subprocess per call; no daemon, no session."""

    def __init__(self, *, module="trust.verifier_main",
                 timeout_seconds=30.0,
                 max_response_bytes=protocol.MAX_RESPONSE_BYTES,
                 expected_signer_id=None, expected_key_id=None,
                 expected_deployment_mode=None,
                 verifier_env=None, pythonpath_extra=()):
        if expected_deployment_mode is not None \
                and expected_deployment_mode not in ("production",
                                                     "research"):
            raise VerifierConfigError(
                "expected_deployment_mode must be None, "
                "'production' or 'research'")
        self._module = module
        self._timeout = float(timeout_seconds)
        self._max_response = int(max_response_bytes)
        self._expected_signer_id = expected_signer_id
        self._expected_key_id = expected_key_id
        self._expected_deployment_mode = expected_deployment_mode
        self.observed_deployment_mode = None
        self._verifier_env = dict(verifier_env or {})
        self._pythonpath_extra = tuple(pythonpath_extra)

    # -- transport --------------------------------------------------------

    def _run(self, mode: str, body: dict) -> dict:
        request_id = protocol.new_request_id()
        try:
            raw_request = protocol.encode_request(request_id, mode, body)
        except protocol.ProtocolError as exc:
            raise VerifierProtocolError(str(exc)) from exc
        pythonpath = os.pathsep.join(
            [str(REPO_ROOT)] + [str(p) for p in self._pythonpath_extra])
        env = {"PYTHONPATH": pythonpath}
        if os.environ.get("PATH"):
            env["PATH"] = os.environ["PATH"]
        if os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
        env.update(self._verifier_env)
        try:
            result = subprocess.run(
                [sys.executable, "-m", self._module],
                input=raw_request, capture_output=True,
                timeout=self._timeout, cwd=str(REPO_ROOT), env=env)
        except subprocess.TimeoutExpired:
            # subprocess.run has already killed and reaped the child.
            raise VerifierTimeout(
                f"verifier exceeded the {self._timeout}s timeout and "
                "was killed; no result exists")
        except OSError as exc:
            raise VerifierUnavailable(
                f"verifier could not be spawned: {exc}") from exc
        if result.returncode == 0:
            try:
                doc = protocol.decode_response(
                    result.stdout, expected_request_id=request_id,
                    expected_mode=mode, cap=self._max_response)
            except protocol.ProtocolError as exc:
                raise VerifierProtocolError(
                    f"unusable verifier response: {exc}") from exc
            self.observed_deployment_mode = doc.get("deployment_mode")
            if self._expected_deployment_mode is not None \
                    and doc["status"] == "ok" \
                    and self.observed_deployment_mode \
                    != self._expected_deployment_mode:
                raise VerifierProtocolError(
                    "verifier response deployment_mode "
                    f"{self.observed_deployment_mode!r} does not "
                    "match the pinned mode "
                    f"{self._expected_deployment_mode!r}")
            if doc["status"] != "ok":
                raise VerifierProtocolError(
                    "verifier returned an error document at exit 0")
            if not isinstance(doc["result"], dict):
                raise VerifierProtocolError("verifier result is malformed")
            return doc["result"]
        code, detail = self._error_document(result)
        excerpt = _stderr_excerpt(result)
        message = f"verifier exit {result.returncode}"
        if code:
            message += f" [{code}]"
        if detail:
            message += f": {detail}"
        if excerpt:
            message += f" (stderr: {excerpt!r})"
        if result.returncode == 2:
            raise VerifierProtocolError(message)
        if result.returncode == 3:
            raise VerifierConfigError(message)
        raise VerifierUnavailable(message)

    @staticmethod
    def _error_document(result):
        try:
            doc = protocol.strict_loads(
                result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
                what="response")
            if isinstance(doc, dict) and doc.get("status") == "error" \
                    and isinstance(doc.get("error"), dict):
                return doc["error"].get("code", ""), \
                    doc["error"].get("detail", "")
        except protocol.ProtocolError:
            pass
        return "", ""

    # -- key-free structural checks ----------------------------------------

    def _check_envelope(self, envelope_dict):
        try:
            signed = envelope_from_dict(envelope_dict)
        except SigningError as exc:
            raise VerifierProtocolError(
                f"verifier returned a malformed envelope: {exc}") from exc
        try:
            payload = signed.payload()
        except (SigningError, UnicodeEncodeError) as exc:
            raise VerifierProtocolError(
                f"verifier envelope payload does not re-derive: {exc}"
            ) from exc
        if signed.payload_hash != payload_hash_for(payload):
            raise VerifierProtocolError(
                "verifier envelope payload hash is inconsistent")
        if signed.decision_id != decision_id_for(signed.payload_hash,
                                                 signed.key_id):
            raise VerifierProtocolError(
                "verifier envelope decision id is inconsistent")
        self._check_pins(signed.signer_id, signed.key_id)
        self._check_not_expired(signed.expires_at)
        return signed

    def _check_pins(self, signer_id, key_id):
        if self._expected_signer_id is not None \
                and signer_id != self._expected_signer_id:
            raise VerifierProtocolError(
                "verifier response is from an unexpected signer")
        if self._expected_key_id is not None \
                and key_id != self._expected_key_id:
            raise VerifierProtocolError(
                "verifier response is under an unexpected key")

    @staticmethod
    def _check_not_expired(expires_at):
        try:
            expiry = datetime.fromisoformat(expires_at)
        except (TypeError, ValueError) as exc:
            raise VerifierProtocolError(
                "verifier envelope expiry is unparseable") from exc
        if datetime.now(timezone.utc) >= expiry:
            raise VerifierProtocolError(
                "verifier envelope is already expired on arrival")

    # -- modes --------------------------------------------------------------

    def gate(self, body: dict) -> GateOutcome:
        """Run the gate verifier-side. Returns the signed outcome —
        accept OR reject — as data; raises on every failure that is
        not a signed decision."""
        result = self._run("gate", body)
        if set(result) != {"envelope", "gate_inputs_hash",
                           "manifest_hash", "registry_digest"}:
            raise VerifierProtocolError("gate result is malformed")
        signed = self._check_envelope(result["envelope"])
        if signed.gate_inputs_hash != result["gate_inputs_hash"]:
            raise VerifierProtocolError(
                "gate result's inputs hash disagrees with the envelope")
        for field_name in ("gate_inputs_hash", "manifest_hash",
                           "registry_digest"):
            value = result[field_name]
            if not isinstance(value, str) or len(value) != 64 \
                    or any(c not in "0123456789abcdef" for c in value):
                raise VerifierProtocolError(
                    f"gate result's {field_name} is not a hex digest")
        return GateOutcome(envelope=signed,
                           gate_inputs_hash=result["gate_inputs_hash"],
                           manifest_hash=result["manifest_hash"],
                           registry_digest=result["registry_digest"])

    def sealed_eval(self, answers, *, proposal_id=None) -> dict:
        """Score a positional answer transcript verifier-side.
        Returns the signed attestation record (a dict). The client
        verifies the record's internal consistency and its binding
        to the transcript it sent; the MAC is verified later by
        key-holding consumers."""
        answers = list(answers)
        body = {"answers": answers}
        if proposal_id is not None:
            body["proposal_id"] = proposal_id
        result = self._run("sealed_eval", body)
        if set(result) != {"attestation"}:
            raise VerifierProtocolError("sealed_eval result is malformed")
        record = result["attestation"]
        if not isinstance(record, dict) \
                or set(record) != {"payload", "payload_hash", "signature"} \
                or not isinstance(record["payload"], dict):
            raise VerifierProtocolError(
                "sealed_eval attestation record is malformed")
        payload = record["payload"]
        if set(payload) != set(PAYLOAD_KEYS):
            raise VerifierProtocolError(
                "sealed_eval attestation payload has missing or "
                "extra keys")
        # Validate against the REBUILT canonical payload — the
        # same rebuild verify_eval_attestation performs — not the
        # presented spelling: the verifier signs score as the
        # float correct / n, so a record re-spelled with score as
        # int 1 (same value) hashes identically under the rebuild
        # and must be accepted here exactly as verification
        # accepts it, while a presented score/correct/n whose
        # VALUES disagree with the rebuild is refused.
        try:
            rebuilt = rebuild_eval_payload(record)
        except (SigningError, KeyError, TypeError, UnicodeEncodeError,
                OverflowError, ValueError) as exc:
            raise VerifierProtocolError(
                "sealed_eval attestation payload does not rebuild "
                f"canonically: {exc}") from exc
        if rebuilt["correct"] != payload.get("correct") \
                or rebuilt["n"] != payload.get("n"):
            raise VerifierProtocolError(
                "sealed_eval attestation correct/n do not match "
                "the rebuilt payload")
        if record["payload_hash"] != _sha256(_canonical(rebuilt)):
            raise VerifierProtocolError(
                "sealed_eval attestation payload hash is inconsistent")
        if payload.get("answers_hash") != answers_hash_for(answers):
            raise VerifierProtocolError(
                "sealed_eval attestation is bound to a different "
                "transcript")
        correct, n = payload.get("correct"), payload.get("n")
        if not isinstance(correct, int) or not isinstance(n, int) \
                or n <= 0 or payload.get("score") != correct / n:
            raise VerifierProtocolError(
                "sealed_eval attestation score is inconsistent "
                "with its correct/n")
        for field_name in ("manifest_hash", "registry_digest"):
            value = payload.get(field_name)
            if not isinstance(value, str) or len(value) != 64 \
                    or any(c not in "0123456789abcdef" for c in value):
                raise VerifierProtocolError(
                    f"sealed_eval {field_name} is not a hex digest")
        self._check_pins(payload.get("signer_id"), payload.get("key_id"))
        self._check_not_expired(payload.get("expires_at", ""))
        return record

    def submit_claim(self, attestation: dict, *, proposal_id: str) -> dict:
        """Ledger a caller assertion with the verifier, UNSIGNED.

        The verifier validates the attestation's form, appends it
        to its ledger as a claim (accepted=False) and returns
        {"claim_id", "claim_hash"}. No signature exists anywhere
        for a claim and a claim grants nothing; this is an audit
        record of what was asserted, not an endorsement of it."""
        body = {"attestation": attestation, "proposal_id": proposal_id}
        result = self._run("submit_claim", body)
        if set(result) != {"claim_id", "claim_hash"}:
            raise VerifierProtocolError(
                "submit_claim result is malformed")
        for field_name in ("claim_id", "claim_hash"):
            value = result[field_name]
            if not isinstance(value, str) or len(value) != 64 \
                    or any(c not in "0123456789abcdef" for c in value):
                raise VerifierProtocolError(
                    f"submit_claim {field_name} is not a hex digest")
        if result["claim_id"] != result["claim_hash"]:
            raise VerifierProtocolError(
                "submit_claim claim_id and claim_hash disagree")
        return result

    def issue_attestation(self, *, proposal_id: str, baseline_eval,
                          candidate_eval, public_baseline_score,
                          public_candidate_score) -> dict:
        """Obtain a verifier-DERIVED signed attestation.

        The caller supplies two sealed-eval records (from
        sealed_eval) and the two public aggregate scores; it
        cannot select the decision or the reward-hacking flag —
        the verifier derives both from the verified records.
        Returns the signed attestation dict (the envelope, as
        gate bodies consume it); the MAC is verified later by
        key-holding consumers, as with every client return."""
        body = {"proposal_id": proposal_id,
                "baseline_eval": baseline_eval,
                "candidate_eval": candidate_eval,
                "public_baseline_score": public_baseline_score,
                "public_candidate_score": public_candidate_score}
        result = self._run("issue_attestation", body)
        if set(result) != {"signed_attestation"}:
            raise VerifierProtocolError(
                "issue_attestation result is malformed")
        try:
            signed_att = attestation_envelope_from_dict(
                result["signed_attestation"])
        except SigningError as exc:
            raise VerifierProtocolError(
                f"verifier returned a malformed attestation: {exc}"
            ) from exc
        try:
            payload = signed_att.payload()
        except (SigningError, UnicodeEncodeError) as exc:
            raise VerifierProtocolError(
                "attestation payload does not re-derive") from exc
        if signed_att.payload_hash != _sha256(_canonical(payload)):
            raise VerifierProtocolError(
                "attestation payload hash is inconsistent")
        self._check_pins(signed_att.signer_id, signed_att.key_id)
        self._check_not_expired(signed_att.expires_at)
        return result["signed_attestation"]

    def verify_envelope(self, envelope: dict, expected=None) -> Verdict:
        """Advisory verifier-side check of an envelope. Never a
        substitute for verification at the point of use: consumers
        re-verify with the key where the artefact is consumed."""
        body = {"envelope": envelope}
        if expected is not None:
            body["expected"] = expected
        result = self._run("verify_envelope", body)
        if set(result) != {"valid", "reasons"} \
                or not isinstance(result["valid"], bool) \
                or not isinstance(result["reasons"], list) \
                or not all(isinstance(r, str) for r in result["reasons"]):
            raise VerifierProtocolError(
                "verify_envelope result is malformed")
        return Verdict(valid=result["valid"],
                       reasons=tuple(result["reasons"]))
