"""Cycle 24 supersede Option A, as AMENDED by cycle 25
(CROSS-CHECK-18 Q1) — the adopter/client side.

The full deadlock end-to-end against a REAL verifier home
(research mode; the fixture is reused from
tests/test_trust_pin_adoption_crash.py, the R12 pattern): a
movement is consumed to its recovery cap with every returned
pair discarded, so the pin sits behind the consumed head with
no retained pair to reconcile from. Cycle 25 flow (design:
internal/cycle25-work/design-approval.md):

  1. first consume refuses ``ceremony_supersede_required``
     (pre-commit; the envelope is provably unconsumed);
  2. the adopter STOPS: it requests NO supersession decision
     and re-runs NOTHING. It persists a
     ``supersession_pending_approval`` pending-journal line,
     writes the pending-supersession report, and raises
     ``PinSupersessionPendingApproval``;
  3. a later attempt with still no inbox approval raises
     pending again WITHOUT a new ceremony (no authorise, no
     consume), so the retained envelope stays approvable;
  4. the approver's separate approval invocation (in these tests: the real
     approval tool's signing function in-process, per design
     criterion (v)) completes the report's head seq/entry_hash
     from the verifier's consumption journal, signs an
     approval artefact under a dedicated approver key, and
     drops it in the adopter's approval inbox;
  5. the next attempt presents the approval once via
     ``VerifierClient.ceremony_supersede`` (the verifier —
     configured with the approver PUBLIC key only — verifies
     it BEFORE issuing), obtains the journaled supersession
     decision, re-runs the SAME envelope's consume exactly
     once, and adopts.

Plus: a wrong-binding artefact is never presented, the
decision-failure-is-burned pin (approval file moved aside),
the negative tamper cases (a decision journaled for a
DIFFERENT candidate does not let this consumption land), and
the client plumbing pins (``_run`` sets ``.verifier_code``;
the consumer translates ``ceremony_supersede_required`` into
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
from trust.client import (
    CeremonyAlreadyConsumed,
    CeremonyHeadRegression,
    CeremonySupersedeRequired,
    VerifierClient,
)
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
    PinSupersessionPendingApproval,
)
from trust.supersession_approval import (
    supersession_approval_to_dict,
    supersession_approval_to_json,
)
from trust.supersession_approval_tool import (
    approver_public_key_for,
    build_approval_for_report,
    generate_approver_key_file,
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

APPROVER_ID = "approver-1"


class CountingClient:
    """Proxy over a real client counting the calls the
    supersede flow makes. A ``ceremony_supersede`` call
    WITHOUT an approval artefact is a test failure — the
    adopter must never request a decision unapproved."""

    def __init__(self, real):
        self._real = real
        self.supersede_calls = 0
        self.consume_calls = 0
        self.authorise_calls = 0
        self.approvals_presented = []

    def ceremony_authorise(self, **kw):
        self.authorise_calls += 1
        return self._real.ceremony_authorise(**kw)

    def ceremony_supersede(self, operator_id, envelope_dict,
                           approval=None):
        self.supersede_calls += 1
        if approval is None:
            raise AssertionError(
                "ceremony_supersede invoked without an approval "
                "artefact — adopter self-escalation")
        self.approvals_presented.append(approval)
        return self._real.ceremony_supersede(
            operator_id, envelope_dict, approval)

    def ceremony_consumer(self):
        real_consumer = self._real.ceremony_consumer()

        def _consume(authorisation):
            self.consume_calls += 1
            return real_consumer(authorisation)

        return _consume


class FailingSupersedeClient(CountingClient):
    def ceremony_supersede(self, operator_id, envelope_dict,
                           approval=None):
        self.supersede_calls += 1
        self.approvals_presented.append(approval)
        raise RuntimeError("simulated decision-request failure")


class AmbiguousSupersedeClient(CountingClient):
    """The verifier COMMITS the decision (the real call
    succeeds verifier-side), then the response is ambiguated
    into the step-(10) ``ledger_failed`` shape — the decision
    stands, no receipt reaches the adopter (r3 F1's seam)."""

    def ceremony_supersede(self, operator_id, envelope_dict,
                           approval=None):
        self.supersede_calls += 1
        if approval is None:
            raise AssertionError(
                "ceremony_supersede invoked without an approval "
                "artefact — adopter self-escalation")
        self.approvals_presented.append(approval)
        self._real.ceremony_supersede(
            operator_id, envelope_dict, approval)
        err = VerifierConfigError(
            "the supersession decision was committed but its "
            "mirror failed (simulated step-10 ledger_failed)")
        err.verifier_code = "ledger_failed"
        raise err


class LostConsumeResponseClient(CountingClient):
    """The resume consume COMMITS verifier-side (the real
    consumer succeeds), then the response is lost — the
    adopter sees only a plain failure (r3 F3's P1 seam)."""

    def ceremony_consumer(self):
        real_consumer = self._real.ceremony_consumer()

        def _consume(authorisation):
            self.consume_calls += 1
            real_consumer(authorisation)
            raise SigningError("simulated lost consume response")

        return _consume


class SupersedeAdopterTests(CrashFixture):
    def setUp(self):
        super().setUp()
        # The dedicated approver key (third key): only the
        # approval tool side of the test ever holds it; the
        # verifier gets its PUBLIC key via env, the adopter
        # never sees either.
        self.approver_key = generate_approver_key_file(
            self.base / "approver.seed")
        approver_pub = approver_public_key_for(self.approver_key)
        env = dict(self.env)
        env["AION_SUPERSESSION_APPROVER_PUBLIC_KEY"] = \
            approver_pub.public_key.hex()
        self.client2 = VerifierClient(
            verifier_env=env, expected_signer_id=_crash.SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        self.inbox = self.base / "approval-inbox"
        self.inbox.mkdir()

    def make_adopter(self, client, approval_path=None):
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=_crash.SIGNER,
            evidence_dir=self.evidence_dir,
            supersession_approval_path=approval_path)
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

    def drive_to_pending(self, counting=None):
        """Genesis + cap burns + next sequence, then one
        adopter attempt with NO approval available. Returns
        (adopter, pending, head_entry)."""
        self.genesis()                       # pin @1, head @1
        self.burn_movement_to_cap()          # movement to 3, terminal
        entries = self.consumption_entries()
        head_at_decision = entries[-1]
        self.assertEqual(head_at_decision["new_cycle_seq"], 3)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        self.drive_to_next_sequence()
        adopter = self.make_adopter(
            counting or CountingClient(self.client),
            approval_path=self.inbox)
        with self.assertRaises(
                PinSupersessionPendingApproval) as cm:
            adopter.snapshot_and_adopt()
        return adopter, cm.exception, head_at_decision

    def mint_approval_into_inbox(self, adopter):
        """The approver's separate approval invocation (design criterion
        (v): the REAL tool signing function in-process):
        complete the pending report's head seq/entry_hash
        from the verifier's own consumption journal, sign the
        approval, and drop the artefact in the inbox as
        <approval_id>.json. Returns the artefact dict."""
        report = json.loads(
            adopter.pending_report_path.read_text(
                encoding="utf-8"))
        head = self.consumption_entries()[-1]
        # The adopter's report names the head movement (its
        # belief, from its own journal); the approver verifies
        # it against the verifier journal and completes the
        # two fields the adopter cannot know.
        self.assertEqual(report["head"]["authorisation_id"],
                         head["authorisation_id"])
        report["head"]["seq"] = head["seq"]
        report["head"]["entry_hash"] = head["entry_hash"]
        signed = build_approval_for_report(
            approver_key=self.approver_key,
            approver_id=APPROVER_ID, report=report)
        artefact = supersession_approval_to_dict(signed)
        (self.inbox / f"{signed.approval_id}.json").write_text(
            supersession_approval_to_json(signed),
            encoding="utf-8")
        return artefact

    # -- the deadlock: pending stop, then approved resume ----

    def test_deadlock_stops_at_pending_without_approval(self):
        counting = CountingClient(self.client)
        adopter, pending, head = self.drive_to_pending(counting)
        # The binding facts an approver needs.
        self.assertEqual(pending.candidate_seq, 5)
        self.assertEqual(pending.old_cycle_seq, 1)
        self.assertEqual(pending.movement["new"]["cycle_seq"], 5)
        self.assertEqual(pending.movement["old"]["cycle_seq"], 1)
        self.assertTrue(pending.authorisation_id)
        self.assertTrue(pending.journal_persisted)
        self.assertTrue(pending.report_written)
        abandoned_ids = [b["authorisation_id"] for b in
                         pending.abandoned_movement_candidates]
        self.assertIn(head["authorisation_id"], abandoned_ids)
        # NO further: the supersede mode was never invoked,
        # exactly one consume attempt happened, no decision
        # was journaled, nothing new was consumed, pin unmoved.
        self.assertEqual(counting.supersede_calls, 0)
        self.assertEqual(counting.consume_calls, 1)
        self.assertEqual(self.supersession_entries(), [])
        self.assertEqual(len(self.consumption_entries()), 4)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # The pending journal carries the
        # supersession_pending_approval detection line, and the
        # report file names the retained envelope + head.
        lines = [json.loads(line) for line in
                 adopter.pending_journal_path.read_text(
                     encoding="utf-8").splitlines() if line.strip()]
        pend = [line for line in lines
                if line.get("phase")
                == "supersession_pending_approval"]
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["candidate_seq"], 5)
        self.assertEqual(pend[0]["authorisation_id"],
                         pending.authorisation_id)
        report = json.loads(
            adopter.pending_report_path.read_text(
                encoding="utf-8"))
        self.assertEqual(report["report"], "pending-supersession/1")
        self.assertEqual(report["refusal_code"],
                         "ceremony_supersede_required")
        self.assertEqual(report["envelope"]["authorisation_id"],
                         pending.authorisation_id)
        self.assertEqual(report["head"]["authorisation_id"],
                         head["authorisation_id"])
        self.assertIsNone(report["head"]["seq"])
        self.assertIsNone(report["head"]["entry_hash"])
        # A second attempt with still no approval stays
        # pending WITHOUT a new ceremony: no authorise, no
        # consume, no supersede — the retained envelope stays
        # the approvable one.
        counting2 = CountingClient(self.client)
        adopter2 = self.make_adopter(counting2,
                                     approval_path=self.inbox)
        with self.assertRaises(PinSupersessionPendingApproval):
            adopter2.snapshot_and_adopt()
        self.assertEqual(counting2.authorise_calls, 0)
        self.assertEqual(counting2.consume_calls, 0)
        self.assertEqual(counting2.supersede_calls, 0)
        self.assertEqual(self.supersession_entries(), [])
        self.assertEqual(len(self.consumption_entries()), 4)

    def test_resume_with_independent_approval_completes(self):
        adopter, _pending, head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        counting = CountingClient(self.client2)
        adopter2 = self.make_adopter(counting,
                                     approval_path=self.inbox)
        result = adopter2.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.pin["cycle_seq"], 5)
        # No new ceremony: zero authorise calls. Exactly one
        # decision request presenting exactly the artefact,
        # exactly one consume (the re-run of the SAME retained
        # envelope, which lands).
        self.assertEqual(counting.authorise_calls, 0)
        self.assertEqual(counting.supersede_calls, 1)
        self.assertEqual(counting.approvals_presented, [artefact])
        self.assertEqual(counting.consume_calls, 1)
        # The approval file was moved aside after presentation.
        self.assertEqual(list(self.inbox.glob("*.json")), [])
        self.assertEqual(
            len(list(self.inbox.glob("*.json.presented"))), 1)
        # The decision is journaled in the verifier's
        # supersession journal, binds the abandoned head
        # authorisation + pair to the new candidate, and
        # records the approval that authorised it.
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
            head["authorisation_id"])
        self.assertEqual(decision["abandoned_new_cycle_seq"], 3)
        self.assertEqual(decision["abandoned_new_payload_hash"],
                         head["new_payload_hash"])
        self.assertEqual(decision["new_authorisation_id"],
                         final["authorisation_id"])
        self.assertEqual(decision["candidate_cycle_seq"], 5)
        self.assertEqual(decision["candidate_payload_hash"],
                         final["new_payload_hash"])
        self.assertEqual(decision["approval_id"],
                         artefact["approval_id"])
        # The pending journal carries the supersede_decided
        # phase line, and the seq-5 ceremony adopted, so it is
        # not an unadopted burn.
        lines = [json.loads(line) for line in
                 adopter2.pending_journal_path.read_text(
                     encoding="utf-8").splitlines() if line.strip()]
        decided = [line for line in lines
                   if line.get("phase") == "supersede_decided"]
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["candidate_seq"], 5)
        self.assertEqual(
            [b for b in adopter2._unadopted_burns()
             if b.get("candidate_seq") == 5], [])
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 5)

    def test_ambiguous_decision_response_lands_consume_no_second_decision(self):
        # r3 F1 regression: the decision request's response is
        # killed/ambiguated AFTER the verifier commits (the
        # step-10 ledger_failed shape). The adopter must fall
        # through to the single consume of the retained
        # envelope against the already-journaled decision —
        # NOT classify the movement burned — landing the pin
        # with the approval spent (moved aside), exactly one
        # decision journaled, and no second decision request.
        adopter, _pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        ambiguous = AmbiguousSupersedeClient(self.client2)
        adopter2 = self.make_adopter(ambiguous,
                                     approval_path=self.inbox)
        result = adopter2.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.pin["cycle_seq"], 5)
        self.assertEqual(ambiguous.supersede_calls, 1)
        self.assertEqual(ambiguous.approvals_presented, [artefact])
        self.assertEqual(ambiguous.consume_calls, 1)
        self.assertEqual(ambiguous.authorise_calls, 0)
        decisions = self.supersession_entries()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["approval_id"],
                         artefact["approval_id"])
        self.assertEqual(len(self.consumption_entries()), 5)
        self.assertEqual(list(self.inbox.glob("*.json")), [])
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 5)

    def test_supersede_decided_entry_resumes_consume_first_no_approval(self):
        # r3 F1, second trigger: an earlier attempt journaled
        # the decision AND its supersede_decided pending line,
        # then died before the consume. The next attempt must
        # land the consume with NO approval in the inbox and
        # NO second decision request.
        adopter, pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        # The earlier attempt: decision obtained for real…
        self.client2.ceremony_supersede(
            OPERATOR, pending.envelope_dict, artefact)
        self.assertEqual(len(self.supersession_entries()), 1)
        # …its supersede_decided line landed, then it died.
        adopter._append_journal({
            "ceremony_id": pending.ceremony_id,
            "authorisation_id": pending.authorisation_id,
            "candidate_seq": pending.candidate_seq,
            "candidate_hash": pending.candidate_hash,
            "old_cycle_seq": pending.old_cycle_seq,
            "old_payload_hash": pending.old_payload_hash,
            "phase": "supersede_decided"})
        # The approval file is gone (presented/spent).
        for path in self.inbox.glob("*.json"):
            path.unlink()
        counting = CountingClient(self.client2)
        adopter2 = self.make_adopter(counting,
                                     approval_path=self.inbox)
        result = adopter2.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.pin["cycle_seq"], 5)
        self.assertEqual(counting.supersede_calls, 0)
        self.assertEqual(counting.authorise_calls, 0)
        self.assertEqual(counting.consume_calls, 1)
        self.assertEqual(len(self.supersession_entries()), 1)
        self.assertEqual(len(self.consumption_entries()), 5)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 5)

    def _write_approval_dict(self, artefact):
        (self.inbox / f"{artefact['approval_id']}.json").write_text(
            json.dumps(artefact), encoding="utf-8")
        return artefact

    def _consume_fresh_envelope_at_head(self):
        """Move the consumption head concurrently: a fresh
        envelope whose old pin IS the head pair (@3) is
        consumed, advancing the head to @5 under a DIFFERENT
        hash than the pending candidate's (r3 F2's P2 mover).
        """
        head = self.consumption_entries()[-1]
        bundle = "head-mover test evidence\n"
        (self.evidence_dir / "head-mover").write_text(
            bundle, encoding="utf-8")
        envelope = self.client.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id="head-mover",
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": head["new_cycle_seq"],
                     "payload_hash": head["new_payload_hash"]},
            candidate={"cycle_seq": 5, "payload_hash": "d" * 64,
                       "signer_id": SNAP_SIGNER,
                       "key_id": SNAP_KEY.key_id},
            evidence_hash=hashlib.sha256(
                bundle.encode("utf-8")).hexdigest(),
            evidence_ref="head-mover")
        result = self.client.ceremony_consume(envelope)
        self.assertEqual(result["new_cycle_seq"], 5)
        self.assertEqual(result["new_payload_hash"], "d" * 64)
        return envelope

    def test_head_move_after_decision_resume_not_burned_fresh_approval_presented(self):
        # r3 F2 regression (probe P2): a decision is journaled
        # for the retained envelope, THEN the head moves
        # concurrently. The journaled decision is bound to the
        # superseded head, so the resume consume refuses
        # ceremony_head_regression PRE-COMMIT. That must NOT
        # classify the movement burned, and the consume-first
        # short-circuit must NOT intercept before the approval
        # lookup on later attempts: a fresh approval bound to
        # the NEW head must be presentable in the same attempt
        # the fall-through reaches it.
        adopter, pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        # The earlier attempt: decision obtained for real
        # (bound to the head @3), supersede_decided journaled,
        # approval spent — then it died before the consume.
        self.client2.ceremony_supersede(
            OPERATOR, pending.envelope_dict, artefact)
        self.assertEqual(len(self.supersession_entries()), 1)
        adopter._append_journal({
            "ceremony_id": pending.ceremony_id,
            "authorisation_id": pending.authorisation_id,
            "candidate_seq": pending.candidate_seq,
            "candidate_hash": pending.candidate_hash,
            "old_cycle_seq": pending.old_cycle_seq,
            "old_payload_hash": pending.old_payload_hash,
            "phase": "supersede_decided"})
        for path in self.inbox.glob("*.json"):
            path.unlink()
        mover = self._consume_fresh_envelope_at_head()
        self.assertEqual(len(self.consumption_entries()), 5)
        # Resume attempt 1 (no approval in the inbox): the
        # consume-first consume refuses head-regression, the
        # attempt falls through to the approval lookup, finds
        # none, and re-pends — NOT burned. Exactly one consume,
        # no decision request, no new ceremony, pin unmoved.
        counting = CountingClient(self.client2)
        adopter2 = self.make_adopter(counting,
                                     approval_path=self.inbox)
        with self.assertRaises(PinSupersessionPendingApproval):
            adopter2.snapshot_and_adopt()
        self.assertEqual(counting.supersede_calls, 0)
        self.assertEqual(counting.consume_calls, 1)
        self.assertEqual(counting.authorise_calls, 0)
        self.assertEqual(len(self.supersession_entries()), 1)
        self.assertEqual(len(self.consumption_entries()), 5)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # The approver mints a FRESH approval bound to the NEW
        # head (the mover entry) for the retained envelope.
        artefact2 = self._write_approval_dict(
            self._approval_for_envelope(pending.envelope_dict))
        # Resume attempt 2: the approval IS presented in this
        # attempt (supersede_calls == 1) — the pre-F2 code
        # burned here without ever presenting it. The verifier
        # refuses a second decision for the same envelope
        # (ceremony_supersede_unproven: a prior decision
        # exists), the in-attempt fall-through consume refuses
        # head-regression again (the stale decision is inert),
        # and the movement re-pends — still NOT burned.
        counting2 = CountingClient(self.client2)
        adopter3 = self.make_adopter(counting2,
                                     approval_path=self.inbox)
        with self.assertRaises(PinSupersessionPendingApproval):
            adopter3.snapshot_and_adopt()
        self.assertEqual(counting2.supersede_calls, 1)
        self.assertEqual(counting2.approvals_presented,
                         [artefact2])
        self.assertEqual(counting2.consume_calls, 2)
        self.assertEqual(counting2.authorise_calls, 0)
        self.assertEqual(len(self.supersession_entries()), 1)
        self.assertEqual(len(self.consumption_entries()), 5)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # The movement then completes at the next sequence: a
        # fresh candidate @7 pends against the new head, a
        # fresh approval bound to the new head obtains a NEW
        # decision against it, and the consume lands.
        self.drive_to_next_sequence()
        counting3 = CountingClient(self.client2)
        adopter4 = self.make_adopter(counting3,
                                     approval_path=self.inbox)
        with self.assertRaises(
                PinSupersessionPendingApproval) as cm:
            adopter4.snapshot_and_adopt()
        self.assertEqual(counting3.authorise_calls, 1)
        self.assertEqual(counting3.consume_calls, 1)
        self.assertEqual(counting3.supersede_calls, 0)
        pending7 = cm.exception
        self.assertEqual(pending7.candidate_seq, 7)
        artefact3 = self._write_approval_dict(
            self._approval_for_envelope(pending7.envelope_dict))
        counting4 = CountingClient(self.client2)
        adopter5 = self.make_adopter(counting4,
                                     approval_path=self.inbox)
        result = adopter5.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.pin["cycle_seq"], 7)
        self.assertEqual(counting4.authorise_calls, 0)
        self.assertEqual(counting4.supersede_calls, 1)
        self.assertEqual(counting4.approvals_presented,
                         [artefact3])
        self.assertEqual(counting4.consume_calls, 1)
        decisions = self.supersession_entries()
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[1]["abandoned_authorisation_id"],
                         mover["authorisation_id"])
        self.assertEqual(decisions[1]["candidate_cycle_seq"], 7)
        self.assertEqual(len(self.consumption_entries()), 6)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 7)

    def test_resume_consume_commit_lost_response_recovers_as_genuine_burn(self):
        # r3 F3 regression (probe P1): a resume consume commits
        # verifier-side but its response is lost. The first
        # attempt is Burned (as designed); the NEXT attempt's
        # consume refuses ceremony_already_consumed — the
        # verifier's certificate that the consumption landed —
        # so the adopter appends the consumed phase to its
        # pending journal before raising Burned, and a later
        # attempt engages the ordinary burned_unadopted
        # recovery and lands.
        adopter, pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        lost = LostConsumeResponseClient(self.client2)
        adopter2 = self.make_adopter(lost,
                                     approval_path=self.inbox)
        with self.assertRaises(PinAdoptionBurned):
            adopter2.snapshot_and_adopt()
        self.assertEqual(lost.supersede_calls, 1)
        self.assertEqual(lost.approvals_presented, [artefact])
        self.assertEqual(lost.consume_calls, 1)
        self.assertEqual(lost.authorise_calls, 0)
        # The consumption DID commit verifier-side; the pin
        # did not move; the adopter journal does not yet carry
        # a consumed phase for the pending ceremony.
        self.assertEqual(len(self.consumption_entries()), 5)
        self.assertEqual(len(self.supersession_entries()), 1)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertNotIn(
            "consumed",
            adopter2._pending_phases(pending.ceremony_id))
        # Later attempt: consume-first (supersede_decided is
        # journaled) — the verifier refuses
        # ceremony_already_consumed, the adopter journals the
        # consumed phase, and raises Burned. No decision
        # request, no new ceremony, nothing new consumed.
        counting = CountingClient(self.client2)
        adopter3 = self.make_adopter(counting,
                                     approval_path=self.inbox)
        with self.assertRaises(PinAdoptionBurned):
            adopter3.snapshot_and_adopt()
        self.assertEqual(counting.supersede_calls, 0)
        self.assertEqual(counting.consume_calls, 1)
        self.assertEqual(counting.authorise_calls, 0)
        self.assertEqual(len(self.consumption_entries()), 5)
        self.assertIn(
            "consumed",
            adopter3._pending_phases(pending.ceremony_id))
        # The ceremony is now a GENUINE unadopted burn: the
        # pending-supersession intercept no longer claims it.
        pin, _history = self.read_store()
        self.assertIsNone(adopter3._find_pending_supersession(
            candidate_seq=pending.candidate_seq,
            candidate_hash=pending.candidate_hash, old_pin=pin))
        self.assertIn(
            pending.authorisation_id,
            [b.get("authorisation_id")
             for b in adopter3._genuine_burn_entries()])
        # A later attempt engages the ordinary burned_unadopted
        # recovery (a fresh ceremony for the SAME candidate)
        # and lands the pin.
        counting2 = CountingClient(self.client2)
        adopter4 = self.make_adopter(counting2,
                                     approval_path=self.inbox)
        result = adopter4.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "burned_unadopted")
        self.assertEqual(result.pin["cycle_seq"], 5)
        self.assertEqual(counting2.authorise_calls, 1)
        self.assertEqual(counting2.consume_calls, 1)
        self.assertEqual(counting2.supersede_calls, 0)
        self.assertEqual(len(self.consumption_entries()), 6)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 5)

    def test_wrong_binding_approval_never_presented(self):
        adopter, _pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        # Tamper the inbox artefact's binding: it now names a
        # different envelope, so the adopter's selection must
        # not pick it (and the verifier would refuse it too).
        path = self.inbox / f"{artefact['approval_id']}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["replacement"]["authorisation_id"] = "e" * 64
        path.write_text(json.dumps(doc), encoding="utf-8")
        counting = CountingClient(self.client2)
        adopter2 = self.make_adopter(counting,
                                     approval_path=self.inbox)
        with self.assertRaises(PinSupersessionPendingApproval):
            adopter2.snapshot_and_adopt()
        self.assertEqual(counting.supersede_calls, 0)
        self.assertEqual(counting.consume_calls, 0)
        self.assertEqual(self.supersession_entries(), [])
        self.assertEqual(len(self.consumption_entries()), 4)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)

    def test_decision_failure_is_burned_not_retried(self):
        adopter, _pending, _head = self.drive_to_pending()
        artefact = self.mint_approval_into_inbox(adopter)
        consumed_before = len(self.consumption_entries())
        failing = FailingSupersedeClient(self.client2)
        adopter2 = self.make_adopter(failing,
                                     approval_path=self.inbox)
        with self.assertRaises(PinAdoptionBurned) as cm:
            adopter2.snapshot_and_adopt()
        self.assertIsNone(cm.exception.returned_pin)
        self.assertIsNone(cm.exception.returned_record)
        # Exactly one decision attempt (with the approval
        # presented), no consume at all; nothing consumed, no
        # decision journaled, pin unmoved — and the approval
        # file was still moved aside (presented once, spent).
        self.assertEqual(failing.supersede_calls, 1)
        self.assertEqual(failing.approvals_presented, [artefact])
        self.assertEqual(failing.consume_calls, 0)
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)
        self.assertEqual(self.supersession_entries(), [])
        self.assertEqual(list(self.inbox.glob("*.json")), [])
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

    def _approval_for_envelope(self, envelope_dict):
        """Mint a genuine approval for a directly-authorised
        envelope (client-level tests): the report is built
        from the envelope + the verifier journal's head."""
        head = self.consumption_entries()[-1]
        report = {
            "report": "pending-supersession/1",
            "refusal_code": "ceremony_supersede_required",
            "envelope": envelope_dict,
            "operator_id": OPERATOR,
            "head": {
                "authorisation_id": head["authorisation_id"],
                "ceremony_id": head["ceremony_id"],
                "old_cycle_seq": head["old_cycle_seq"],
                "old_payload_hash": head["old_payload_hash"],
                "new_cycle_seq": head["new_cycle_seq"],
                "new_payload_hash": head["new_payload_hash"],
                "seq": head["seq"],
                "entry_hash": head["entry_hash"]},
            "reported_at": "2026-11-23T00:00:00+00:00"}
        signed = build_approval_for_report(
            approver_key=self.approver_key,
            approver_id=APPROVER_ID, report=report)
        return supersession_approval_to_dict(signed)

    def test_decision_for_different_candidate_does_not_land(self):
        self.genesis()
        self.burn_movement_to_cap()          # head @3, pin @1
        self.drive_to_next_sequence()        # state @5
        cand5 = self._signed_candidate(5)
        envelope_a = self._authorise_primary(
            ceremony_id="supersede-tamper-a", candidate_seq=5,
            candidate_hash=cand5.payload_hash,
            evidence_ref="supersede-tamper-a")
        # A decision is journaled for envelope A (candidate 5),
        # against a genuine independent approval for A.
        approval_a = self._approval_for_envelope(envelope_a)
        receipt = self.client2.ceremony_supersede(
            OPERATOR, envelope_a, approval_a)
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
        # After the independently approved decision, the same
        # consumer call lands.
        approval = self._approval_for_envelope(envelope)
        self.client2.ceremony_supersede(OPERATOR, envelope, approval)
        self.assertIsNone(consumer(signed))

    def test_consumer_translates_head_regression(self):
        # F2 plumbing: a consume whose candidate sits AT the
        # head seq under a different hash refuses
        # ceremony_head_regression; the consumer surfaces it
        # as the structured CeremonyHeadRegression (never a
        # string match), carrying the presented envelope.
        self.genesis()
        self.burn_movement_to_cap()          # head @3, pin @1
        envelope = self._authorise_primary(
            ceremony_id="consumer-head-regression",
            candidate_seq=3, candidate_hash="c" * 64,
            evidence_ref="consumer-head-regression")
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        consumed_before = len(self.consumption_entries())
        with self.assertRaises(CeremonyHeadRegression) as cm:
            self.client.ceremony_consumer()(signed)
        self.assertIs(type(cm.exception), CeremonyHeadRegression)
        self.assertIsInstance(cm.exception, SigningError)
        self.assertEqual(cm.exception.envelope_dict, envelope)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_head_regression")
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)

    def test_consumer_translates_already_consumed(self):
        # F3 plumbing: a second consume of an envelope whose
        # consumption already committed refuses
        # ceremony_already_consumed; the consumer surfaces it
        # as the structured CeremonyAlreadyConsumed, carrying
        # the presented envelope.
        self.genesis()
        self.drive_to_next_sequence(cycles=2)   # state @3
        cand3 = self._signed_candidate(3)
        envelope = self._authorise_primary(
            ceremony_id="consumer-already-consumed",
            candidate_seq=3, candidate_hash=cand3.payload_hash,
            evidence_ref="consumer-already-consumed")
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        consumer = self.client.ceremony_consumer()
        self.assertIsNone(consumer(signed))
        with self.assertRaises(CeremonyAlreadyConsumed) as cm:
            consumer(signed)
        self.assertIs(type(cm.exception), CeremonyAlreadyConsumed)
        self.assertIsInstance(cm.exception, SigningError)
        self.assertEqual(cm.exception.envelope_dict, envelope)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_already_consumed")

    def test_run_attaches_verifier_code_exit3_unproven(self):
        # A non-supersede envelope presented to the supersede
        # mode WITH a genuine approval: genesis head @1, old
        # pin @1 is NOT behind the head, so the shape gate
        # refuses with the single code
        # ceremony_supersede_unproven (exit 3), and _run must
        # attach it as .verifier_code.
        self.genesis()
        self.drive_to_next_sequence(cycles=2)   # state @3
        cand3 = self._signed_candidate(3)
        envelope = self._authorise_primary(
            ceremony_id="supersede-unproven", candidate_seq=3,
            candidate_hash=cand3.payload_hash,
            evidence_ref="supersede-unproven")
        approval = self._approval_for_envelope(envelope)
        with self.assertRaises(VerifierConfigError) as cm:
            self.client2.ceremony_supersede(
                OPERATOR, envelope, approval)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_run_attaches_verifier_code_exit2_malformed(self):
        # Exit-2 path: a malformed supersede body (missing the
        # envelope key) refuses malformed_request, and _run
        # attaches that code too. Uses the approver-configured
        # client: seat B's cycle-25 config gate (approver key
        # unconfigured) runs before body validation by design.
        with self.assertRaises(VerifierProtocolError) as cm:
            self.client2._run("ceremony_supersede",
                              {"operator_id": OPERATOR})
        self.assertEqual(cm.exception.verifier_code,
                         "malformed_request")


if __name__ == "__main__":
    unittest.main()
