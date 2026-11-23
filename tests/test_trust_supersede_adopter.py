"""Cycle 24, supersede Option A — the adopter/client side
(BUILD SEAT 4).

The full deadlock end-to-end against a REAL verifier home
(research mode; the fixture is reused from
tests/test_trust_pin_adoption_crash.py, the R12 pattern): a
movement is consumed to its recovery cap with every returned
pair discarded, so the pin sits behind the consumed head with
no retained pair to reconcile from. The next-sequence primary
ceremony via PinAdopter then runs the two-phase flow:

  1. first consume refuses ``ceremony_supersede_required``
     (pre-commit; the envelope is provably unconsumed);
  2. the adopter requests the decision ONCE via
     ``VerifierClient.ceremony_supersede``;
  3. the verifier journals the decision in its supersession
     journal, binding the abandoned head authorisation to the
     new candidate;
  4. the adopter re-runs the SAME envelope once; it consumes
     and adopts; the pin lands at the new sequence.

Plus: the negative tamper cases (a decision journaled for a
DIFFERENT candidate does not let this consumption land), the
decision-failure-is-burned pin, and the client plumbing pins
(``_run`` sets ``.verifier_code``; the consumer translates
``ceremony_supersede_required`` into
``CeremonySupersedeRequired`` carrying the envelope dict).
"""

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict,
)
from signing.gate_decision import SigningError
from signing.state_snapshot import sign_state_snapshot
from trust.client import CeremonySupersedeRequired
from trust.errors import VerifierConfigError, VerifierProtocolError
from trust.ledger import (
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
    HeadRegressionError,
)
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
    PinAdoptionBurned,
)

# Reuse the crash suite's fixture (real verifier subprocess,
# real store, burn_once seam) rather than re-deriving it.
_spec = importlib.util.spec_from_file_location(
    "crash_fixture",
    Path(__file__).resolve().parent
    / "test_trust_pin_adoption_crash.py")
_crash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_crash)
CrashFixture = _crash.CrashFixture
OPERATOR = _crash.OPERATOR
SNAP_KEY = _crash.SNAP_KEY
SNAP_SIGNER = _crash.SNAP_SIGNER


class CountingClient:
    """Proxy over the real client counting the two calls the
    supersede flow is specified to make exactly once / twice."""

    def __init__(self, real):
        self._real = real
        self.supersede_calls = 0
        self.consume_calls = 0

    def ceremony_authorise(self, **kw):
        return self._real.ceremony_authorise(**kw)

    def ceremony_supersede(self, operator_id, envelope_dict):
        self.supersede_calls += 1
        return self._real.ceremony_supersede(
            operator_id=operator_id, envelope_dict=envelope_dict)

    def ceremony_consumer(self):
        real_consumer = self._real.ceremony_consumer()

        def _consume(authorisation):
            self.consume_calls += 1
            return real_consumer(authorisation)

        return _consume


class FailingSupersedeClient(CountingClient):
    def ceremony_supersede(self, operator_id, envelope_dict):
        self.supersede_calls += 1
        raise RuntimeError("simulated decision-request failure")


class SupersedeAdopterTests(CrashFixture):
    def make_adopter(self, client):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=_crash.SIGNER,
            evidence_dir=self.evidence_dir)
        return PinAdopter(client=client, store=self.store,
                          signing_key=SNAP_KEY, config=config,
                          authorisation_public_key=self.pub)

    def supersession_entries(self):
        return CeremonySupersessionLedger(
            self.home / "ledger").entries()

    def burn_movement_to_cap(self, cycles=2):
        """Consume one movement to its recovery cap (primary,
        depth 1, depth 2) discarding every returned pair."""
        self.scan_items(cycles)
        for _ in range(cycles):
            self.bare_cycle()
        self.burn_once()   # primary, pair discarded
        self.burn_once()   # depth-1 recovery, pair discarded
        self.burn_once()   # depth-2 recovery, pair discarded

    def drive_to_next_sequence(self, cycles=2):
        self.scan_items(cycles)
        for _ in range(cycles):
            self.bare_cycle()

    # -- the deadlock end-to-end --------------------------------

    def test_deadlock_end_to_end_via_decision_flow(self):
        self.genesis()                       # pin @1, head @1
        self.burn_movement_to_cap()          # movement to 3, terminal
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 4)    # genesis + 3 burns
        head_at_decision = entries[-1]
        self.assertEqual(head_at_decision["new_cycle_seq"], 3)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # Next sequence: primary ceremony, old pin 1 behind
        # head 3, candidate 5 strictly ahead — supersede shape.
        self.drive_to_next_sequence()
        counting = CountingClient(self.client)
        adopter = self.make_adopter(counting)
        result = adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.pin["cycle_seq"], 5)
        # Exactly one decision request, exactly two consume
        # attempts for this envelope (first refused
        # supersede-required, second lands); no third attempt.
        self.assertEqual(counting.supersede_calls, 1)
        self.assertEqual(counting.consume_calls, 2)
        # The decision is journaled in the verifier's
        # supersession journal and binds the abandoned head
        # authorisation + pair to the new candidate.
        decisions = self.supersession_entries()
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 5)
        final = entries[-1]
        self.assertEqual(final["new_cycle_seq"], 5)
        self.assertEqual(final.get("consumption_kind"), "primary")
        self.assertEqual(
            decision["abandoned_authorisation_id"],
            head_at_decision["authorisation_id"])
        self.assertEqual(decision["abandoned_new_cycle_seq"], 3)
        self.assertEqual(decision["abandoned_new_payload_hash"],
                         head_at_decision["new_payload_hash"])
        self.assertEqual(decision["new_authorisation_id"],
                         final["authorisation_id"])
        self.assertEqual(decision["candidate_cycle_seq"], 5)
        self.assertEqual(decision["candidate_payload_hash"],
                         final["new_payload_hash"])
        # The adopter's pending journal carries the
        # supersede_decided phase line for this ceremony, and
        # that phase is NOT a burn phase: the ceremony adopted,
        # so it is not an unadopted burn at all.
        lines = [json.loads(line) for line in
                 adopter.pending_journal_path.read_text(
                     encoding="utf-8").splitlines() if line.strip()]
        decided = [line for line in lines
                   if line.get("phase") == "supersede_decided"]
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["candidate_seq"], 5)
        self.assertEqual(decided[0]["authorisation_id"],
                         final["authorisation_id"])
        # The seq-5 ceremony itself adopted, so it is not an
        # unadopted burn (the three cap burns to seq 3 remain
        # listed — they were genuinely never adopted).
        self.assertEqual(
            [b for b in adopter._unadopted_burns()
             if b.get("candidate_seq") == 5], [])
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 5)

    def test_decision_failure_is_burned_not_retried(self):
        self.genesis()
        self.burn_movement_to_cap()
        self.drive_to_next_sequence()
        consumed_before = len(self.consumption_entries())
        failing = FailingSupersedeClient(self.client)
        adopter = self.make_adopter(failing)
        with self.assertRaises(PinAdoptionBurned) as cm:
            adopter.snapshot_and_adopt()
        self.assertIsNone(cm.exception.returned_pin)
        self.assertIsNone(cm.exception.returned_record)
        # Exactly one decision attempt, exactly one consume
        # attempt; nothing consumed, no decision journaled,
        # pin unmoved.
        self.assertEqual(failing.supersede_calls, 1)
        self.assertEqual(failing.consume_calls, 1)
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)
        self.assertEqual(self.supersession_entries(), [])
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)

    # -- negative: a decision for a DIFFERENT candidate --------

    def _authorise_primary(self, *, ceremony_id, candidate_seq,
                           candidate_hash, evidence_ref):
        """Authorise a fresh primary envelope against the
        current (unmoved) pin, presenting evidence the
        verifier can resolve."""
        pin, _history = self.read_store()
        bundle = f"supersede-adopter test evidence {ceremony_id}\n"
        (self.evidence_dir / evidence_ref).write_text(
            bundle, encoding="utf-8")
        return self.client.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id=ceremony_id,
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": pin["cycle_seq"],
                     "payload_hash": pin["payload_hash"]},
            candidate={"cycle_seq": candidate_seq,
                       "payload_hash": candidate_hash,
                       "signer_id": SNAP_SIGNER,
                       "key_id": SNAP_KEY.key_id},
            evidence_hash=hashlib.sha256(
                bundle.encode("utf-8")).hexdigest(),
            evidence_ref=evidence_ref)

    def _signed_candidate(self, seq):
        state_bytes, calibration_bytes = \
            self.adopter._read_consistent_pair()
        return sign_state_snapshot(
            state_bytes, signing_key=SNAP_KEY,
            signer_id=SNAP_SIGNER,
            calibration_bytes=calibration_bytes,
            prev_snapshot_hash="")

    def test_decision_for_different_candidate_does_not_land(self):
        self.genesis()
        self.burn_movement_to_cap()          # head @3, pin @1
        self.drive_to_next_sequence()        # state @5
        cand5 = self._signed_candidate(5)
        envelope_a = self._authorise_primary(
            ceremony_id="supersede-tamper-a", candidate_seq=5,
            candidate_hash=cand5.payload_hash,
            evidence_ref="supersede-tamper-a")
        # A decision is journaled for envelope A (candidate 5).
        receipt = self.client.ceremony_supersede(
            OPERATOR, envelope_a)
        self.assertEqual(receipt["new_authorisation_id"],
                         envelope_a["authorisation_id"])
        self.assertEqual(len(self.supersession_entries()), 1)
        # Envelope B: a DIFFERENT envelope (different
        # authorisation, candidate 7). The decision for A must
        # not let B's consumption land: B's consume refuses
        # supersede-required (no decision is keyed to B) and
        # the consumption journal is unchanged.
        envelope_b = self._authorise_primary(
            ceremony_id="supersede-tamper-b", candidate_seq=7,
            candidate_hash="c" * 64,
            evidence_ref="supersede-tamper-b")
        consumed_before = len(self.consumption_entries())
        with self.assertRaises(VerifierConfigError) as cm:
            self.client.ceremony_consume(envelope_b)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_supersede_required")
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)
        # Ledger-level tamper pin: threading A's decision into
        # B's head check is a binding mismatch — head
        # regression, never a landing.
        signed_b = ceremony_authorisation_envelope_from_dict(
            envelope_b)
        entries = CeremonyConsumptionLedger(
            self.home / "ledger").entries()
        decision = self.supersession_entries()[0]
        with self.assertRaises(HeadRegressionError):
            CeremonyConsumptionLedger.check_head(
                entries, signed_b, supersede_decision=decision)
        # And A's own consumption DOES land against its
        # decision — the decision was specific, not a blanket.
        result = self.client.ceremony_consume(envelope_a)
        self.assertEqual(result["new_cycle_seq"], 5)

    # -- client plumbing -----------------------------------------

    def test_consumer_translates_supersede_required(self):
        self.genesis()
        self.burn_movement_to_cap()
        self.drive_to_next_sequence()
        cand5 = self._signed_candidate(5)
        envelope = self._authorise_primary(
            ceremony_id="supersede-consumer", candidate_seq=5,
            candidate_hash=cand5.payload_hash,
            evidence_ref="supersede-consumer")
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        consumer = self.client.ceremony_consumer()
        with self.assertRaises(CeremonySupersedeRequired) as cm:
            consumer(signed)
        self.assertIs(type(cm.exception), CeremonySupersedeRequired)
        self.assertIsInstance(cm.exception, SigningError)
        self.assertEqual(cm.exception.envelope_dict, envelope)
        # After the decision, the same consumer call lands.
        self.client.ceremony_supersede(OPERATOR, envelope)
        self.assertIsNone(consumer(signed))

    def test_run_attaches_verifier_code_exit3_unproven(self):
        # A non-supersede envelope presented to the supersede
        # mode: genesis head @1, old pin @1 is NOT behind the
        # head, so the shape gate refuses with the single code
        # ceremony_supersede_unproven (exit 3), and _run must
        # attach it as .verifier_code.
        self.genesis()
        self.drive_to_next_sequence(cycles=2)   # state @3
        cand3 = self._signed_candidate(3)
        envelope = self._authorise_primary(
            ceremony_id="supersede-unproven", candidate_seq=3,
            candidate_hash=cand3.payload_hash,
            evidence_ref="supersede-unproven")
        with self.assertRaises(VerifierConfigError) as cm:
            self.client.ceremony_supersede(OPERATOR, envelope)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_run_attaches_verifier_code_exit2_malformed(self):
        # Exit-2 path: a malformed supersede body (missing the
        # envelope key) refuses malformed_request, and _run
        # attaches that code too.
        with self.assertRaises(VerifierProtocolError) as cm:
            self.client._run("ceremony_supersede",
                             {"operator_id": OPERATOR})
        self.assertEqual(cm.exception.verifier_code,
                         "malformed_request")


if __name__ == "__main__":
    unittest.main()
