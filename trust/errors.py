"""Error types for the trust boundary.

The split matters for audit: "the verifier said no" (a signed
rejection, returned as data, never an exception), "the verifier
never ran" (VerifierUnavailable), "the request was malformed"
(VerifierProtocolError) and "the verifier is misconfigured"
(VerifierConfigError) are four different facts. No exception in
this module ever carries key material, a key path, or sealed
content.
"""


class TrustError(Exception):
    """Base for trust-boundary failures."""


class VerifierError(TrustError):
    """Base for verifier-client failures. Every client failure
    raises; there is no default-accept path."""


class VerifierUnavailable(VerifierError):
    """The verifier process could not be spawned, crashed, was
    killed, or exited with an unhandled code. No verdict exists."""


class VerifierTimeout(VerifierUnavailable):
    """The verifier exceeded its timeout and was killed and reaped.
    No partial result is ever returned from a timed-out run."""


class VerifierProtocolError(VerifierError):
    """Exit 2 from the verifier (malformed request), or a response
    that is not exactly one well-formed protocol document (garbage,
    oversize, wrong echo, trailing data)."""


class VerifierConfigError(VerifierError):
    """Exit 3 from the verifier: misconfiguration, missing or
    unsafe key, untrusted registry, signer conflict. The verifier
    refused to operate; nothing was signed."""


class ShipRefused(TrustError):
    """record_ship refused (or a burn was rejected). Carries the
    reason tuple from the ship check when the refusal came from
    verification rather than the ledger."""

    def __init__(self, message, reasons=()):
        super().__init__(message)
        self.reasons = tuple(reasons)
