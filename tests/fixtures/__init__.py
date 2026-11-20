"""Fixture verifier processes for trust client tests.

These are launched by trust.client.VerifierClient via its module
parameter — a legitimate deployment knob (alternative verifier
builds), not a test backdoor in production code. Production code
contains no sleeper, no fault injection, no env-flag behaviours.
"""
