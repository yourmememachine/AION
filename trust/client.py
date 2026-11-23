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
verify any MAC: the HMAC envelopes stay unverifiable here.
The one cryptographic exception (cycle 20) is the ceremony
authorisation: it is Ed25519-signed, so a client configured
with the pinned CeremonyPublicKey verifies its signature
itself in ceremony_authorise — public material only, still
no signing capability. Client-side
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
from signing.ceremony_authorisation import (
    CeremonyPublicKey,
    SignedCeremonyAuthorisation,
    authorisation_id_for,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_to_dict,
    verify_ceremony_authorisation,
)
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
    VerifierError,
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
                 authorisation_public_key=None,
                 expected_deployment_mode=None,
                 verifier_env=None, pythonpath_extra=()):
        if expected_deployment_mode is not None \
                and expected_deployment_mode not in ("production",
                                                     "research"):
            raise VerifierConfigError(
                "expected_deployment_mode must be None, "
                "'production' or 'research'")
        if authorisation_public_key is not None \
                and not isinstance(authorisation_public_key,
                                   CeremonyPublicKey):
            raise VerifierConfigError(
                "authorisation_public_key must be a "
                "CeremonyPublicKey (the pinned ceremony "
                "verification key) or None")
        self._module = module
        self._timeout = float(timeout_seconds)
        self._max_response = int(max_response_bytes)
        self._expected_signer_id = expected_signer_id
        self._expected_key_id = expected_key_id
        # The ceremony public-key pin (cycle 20): beside the
        # signer/key pins, but a public-key OBJECT — its key_id
        # is derived from its bytes, so the pin cannot be
        # re-pointed independently of the key material.
        self._authorisation_public_key = authorisation_public_key
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

    def ceremony_authorise(self, *, operator_id, ceremony_id, reason,
                           old_pin, candidate, evidence_hash,
                           evidence_ref) -> dict:
        """Obtain a verifier-issued ceremony authorisation.

        The caller names the operator and the recovery event;
        ELIGIBILITY is the verifier's own protected operator
        allowlist (AION_CEREMONY_OPERATORS in its environment) —
        this client cannot supply, extend or override it, and
        the request body has no field for a list. This client
        asserts the operator id; it does not authenticate it.
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

        Returns the envelope dict only. In addition to the
        structural checks, this client verifies the envelope's
        Ed25519 signature itself with its pinned
        CeremonyPublicKey (the same
        verify_ceremony_authorisation call consumers make — not
        a second verify path), so a mis-pinned key or a forged
        envelope fails here, at the earliest point. A client
        with no ceremony public-key pin configured refuses
        locally (VerifierConfigError) rather than accepting an
        unverified envelope. Exit-3 refusals (unconfigured
        list, ceremony_seed_unconfigured,
        ceremony_evidence_unconfigured, unlisted operator,
        replay, evidence reuse, ceremony_evidence_unresolvable,
        ceremony_evidence_too_large) surface as
        VerifierConfigError; exit-2 malformed requests
        (including ceremony_evidence_hash_mismatch) as
        VerifierProtocolError — via _run, as with every mode."""
        if self._authorisation_public_key is None:
            raise VerifierConfigError(
                "ceremony_authorise requires a pinned ceremony "
                "public key (authorisation_public_key); refusing "
                "to request an envelope this client cannot "
                "verify")
        body = {"operator_id": operator_id,
                "ceremony_id": ceremony_id, "reason": reason,
                "old_pin": old_pin, "candidate": candidate,
                "evidence_hash": evidence_hash,
                "evidence_ref": evidence_ref}
        result = self._run("ceremony_authorise", body)
        if set(result) != {"signed_authorisation"}:
            raise VerifierProtocolError(
                "ceremony_authorise result is malformed")
        envelope = result["signed_authorisation"]
        try:
            signed = ceremony_authorisation_envelope_from_dict(envelope)
        except SigningError as exc:
            raise VerifierProtocolError(
                f"verifier returned a malformed ceremony "
                f"authorisation: {exc}") from exc
        try:
            payload = signed.payload()
        except (SigningError, UnicodeEncodeError) as exc:
            raise VerifierProtocolError(
                "ceremony authorisation payload does not "
                "re-derive") from exc
        if signed.payload_hash != _sha256(_canonical(payload)):
            raise VerifierProtocolError(
                "ceremony authorisation payload hash is "
                "inconsistent")
        if signed.authorisation_id != authorisation_id_for(
                signed.payload_hash, signed.key_id):
            raise VerifierProtocolError(
                "ceremony authorisation id is inconsistent")
        self._check_pins(signed.signer_id, signed.key_id)
        self._check_not_expired(signed.expires_at)
        # Cryptographic verification (cycle 20, R8): verify the
        # Ed25519 signature with the pinned CeremonyPublicKey —
        # the same verify_ceremony_authorisation call consumers
        # make, with the full event binding as expectations.
        # The envelope's evidence_hash is the verifier-computed
        # one; the echo comparison below binds it against the
        # REQUEST's hash, which the verifier cross-checked
        # against its computed value before signing.
        try:
            reasons = verify_ceremony_authorisation(
                signed,
                public_key=self._authorisation_public_key,
                expected_signer_id=self._expected_signer_id,
                expected_operator_id=operator_id,
                expected_ceremony_id=ceremony_id,
                expected_reason=reason,
                expected_old_pin=old_pin,
                expected_candidate=candidate,
                expected_evidence_hash=evidence_hash,
                expected_evidence_ref=evidence_ref)
        except SigningError as exc:
            raise VerifierProtocolError(
                f"ceremony authorisation failed verification: "
                f"{exc}") from exc
        if reasons:
            raise VerifierProtocolError(
                "ceremony authorisation failed signature "
                "verification: " + ",".join(reasons))
        # Echo binding (the sealed_eval answers-hash precedent):
        # the envelope must be bound to the event THIS client
        # sent, not merely well-formed.
        if signed.operator_id != operator_id \
                or signed.ceremony_id != ceremony_id \
                or signed.reason != reason \
                or signed.old_pin != old_pin \
                or signed.candidate != candidate \
                or signed.evidence_hash != evidence_hash \
                or signed.evidence_ref != evidence_ref:
            raise VerifierProtocolError(
                "ceremony authorisation is bound to a different "
                "event than requested")
        return envelope

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

    def ceremony_consume(self, envelope_dict) -> dict:
        """Consume a ceremony authorisation at the verifier.

        The body is exactly ``{"signed_authorisation":
        envelope_dict}`` (the ceremony_authorise wire
        precedent). The verifier re-verifies the envelope
        under its own derived public key, checks single-use
        against its consumption journal, checks issuance
        presence and the head rules, and commits the
        consumption-journal append before responding.

        Head-vs-pin-head narrowing: the head is a ceremony
        head; it sees consumptions only; advance_pin
        movements never pass through the verifier.

        The result's exact key set is validated, and its
        echoes must match the envelope THIS client sent —
        authorisation_id, ceremony_id, and the candidate
        seq/hash (as new_cycle_seq / new_payload_hash);
        consumption_seq must be an int >= 1. Any mismatch is
        a VerifierProtocolError: a receipt that does not bind
        to the sent envelope is a protocol failure, and the
        envelope is treated as burned (see ceremony_consumer).

        Operator claim, narrowed as in ceremony_authorise:
        this client asserts an envelope; it does not
        authenticate the operator the envelope names, and
        consumption checks no operator allowlist — allowlist
        membership is an issuance fact, not a consumption
        gate. Exit-3 state refusals (already-consumed,
        not-issued, head regression, expired) surface as
        VerifierConfigError via _run; for this mode that
        class carries ceremony state refusals, and the
        correct operator response is a new ceremony, not a
        config fix."""
        if not isinstance(envelope_dict, dict):
            raise VerifierProtocolError(
                "ceremony_consume requires the envelope dict")
        try:
            sent_id = envelope_dict["authorisation_id"]
            sent_ceremony = envelope_dict["ceremony_id"]
            sent_candidate = envelope_dict["candidate"]
            sent_seq = sent_candidate["cycle_seq"]
            sent_hash = sent_candidate["payload_hash"]
        except (KeyError, TypeError) as exc:
            raise VerifierProtocolError(
                "ceremony_consume envelope dict is missing its "
                "authorisation_id, ceremony_id or candidate") from exc
        result = self._run(
            "ceremony_consume",
            {"signed_authorisation": envelope_dict})
        if set(result) != {"authorisation_id", "ceremony_id",
                           "consumption_seq", "new_cycle_seq",
                           "new_payload_hash"}:
            raise VerifierProtocolError(
                "ceremony_consume result is malformed")
        if result["authorisation_id"] != sent_id \
                or result["ceremony_id"] != sent_ceremony \
                or result["new_cycle_seq"] != sent_seq \
                or result["new_payload_hash"] != sent_hash:
            raise VerifierProtocolError(
                "ceremony_consume result does not echo the "
                "envelope sent (authorisation_id, ceremony_id "
                "or candidate mismatch)")
        seq = result["consumption_seq"]
        if not isinstance(seq, int) or isinstance(seq, bool) \
                or seq < 1:
            raise VerifierProtocolError(
                "ceremony_consume consumption_seq is not an "
                "int >= 1")
        return result

    def ceremony_consumer(self):
        """Return the production ``consume_authorisation``
        callable for ``signing.pin_ceremony.reanchor_pin``.

        The returned callable takes one argument — the
        SignedCeremonyAuthorisation — converts it via
        ceremony_authorisation_envelope_to_dict, calls
        ceremony_consume, returns None on success, and
        translates any Verifier* exception into SigningError
        (cause chained), which is reanchor_pin's refusal
        vocabulary. A non-envelope argument raises
        SigningError from the conversion itself.

        Never auto-retry (cycle 21, R7): Consumption is
        committed at the verifier — a fsync'd
        consumption-journal append — before reanchor_pin
        returns anything. A crash after the commit but
        before adoption leaves the authorisation burned and
        the pin unmoved; a lost or ambiguous response is
        treated as burned; the client never retries a consume
        automatically. Recovery is a new ceremony (new
        ceremony_id, new evidence), never an un-consume.
        This callable therefore makes exactly one consume
        attempt per invocation.

        Head-vs-pin-head narrowing: the head the consumer
        enforces is a ceremony head; it sees consumptions
        only; advance_pin movements never pass through the
        verifier."""
        def _consume(authorisation):
            if not isinstance(authorisation,
                              SignedCeremonyAuthorisation):
                raise SigningError(
                    "consume_authorisation requires a "
                    "SignedCeremonyAuthorisation")
            envelope = ceremony_authorisation_envelope_to_dict(
                authorisation)
            try:
                self.ceremony_consume(envelope)
            except VerifierError as exc:
                raise SigningError(
                    f"ceremony consumption refused: {exc}") from exc
            return None
        return _consume
