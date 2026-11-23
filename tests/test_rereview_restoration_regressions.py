"""Regression tests for the cycles 14-16 re-review: RESTORATION
and AUTHORITY-TRANSITION behaviours of the snapshot pin
ceremony line (GPT's cycle-22 regression list).

Cycles 14-16 were HELD partly on external findings that the
ceremony lacked rollback-resistant authority/history. Cycles
19-24 answered with verifier-owned anchored journals. These
tests pin, against a PRODUCTION-mode verifier home (the
tests/cycle23_harness.py provisioning: research INIT bootstrap,
INIT stripped, AION_DEPLOYMENT_MODE=production), what the
re-review war rooms must judge:

  1. Verifier-home rollback of the consumption journal alone
     (external anchor left at its advanced value) is refused
     at verifier startup (anchor_refused) and the consumed
     envelope does not become consumable again.
  2. Authority transition - operator removal.
  3. Authority transition - ceremony signing-key rotation.
  4. Pin-store restoration to a pre-advance generation while
     the verifier consumption head stays advanced.

Already covered elsewhere (NOT duplicated here; named as the
evidence for those legs):

  * Leg 1, research-mode anchored home:
    tests/test_trust_ceremony_journal_anchor.py
    MandatoryRollbackTests.test_clean_consume_rollback_refused
    (whole-home rollback) and
    MandatoryRollbackTests.test_consumption_journal_only_rollback_refused
    (journal-only rollback). What was missing, and is written
    here, is the same refusal under a production-mode home.
  * Leg 2, never-listed operator refused at authorise:
    tests/test_trust_ceremony_mode.py
    CeremonyModeTests.test_invented_operator_refused_unsigned_unledgered.
    Partial evidence that consume does not re-check the
    allowlist: tests/test_trust_ceremony_consume.py
    CeremonyConsumeTests.test_seed_unconfigured_is_the_only_gate
    (operators blanked; the seed gate fires first). What was
    missing, and is written here, is the REMOVAL transition:
    an operator listed at issuance and removed afterwards.
  * Leg 3: no existing test rotates the ceremony seed against
    outstanding envelopes; both legs are written here.
  * Leg 4, store-level guards (CAS, context binding,
    prospective consistency) in isolation:
    tests/test_signing_pin_store.py PinStoreTests, and the
    adopter supersede flow against a pin left behind the head
    by a discarded pair:
    tests/test_trust_supersede_adopter.py SupersedeAdopterTests.
    What was missing, and is written here, is the RESTORED
    pin-store file (an older, internally consistent generation
    spliced back under an advanced consumption head) driven
    through the production adopter.

OBSERVED DIVERGENCE (leg 2, pinned deliberately - this is
re-review evidence, not a bug worked around): removing an
operator from AION_CEREMONY_OPERATORS does NOT invalidate
that operator's outstanding, unexpired envelopes at consume.
The verifier's ceremony_consume mode states this in its own
docstring ("Explicitly NOT re-checked here: operator
allowlist membership and evidence resolution (issuance
facts...)"), and the observed behaviour matches the
docstring: the removed operator's envelope CONSUMES AND
LANDS. Removal DOES refuse NEW authorisations for the
removed operator (ceremony_operator_not_authorised at
authorise). The expectation in the re-review brief - that
the authority transition invalidates outstanding envelopes
at consume - is therefore NOT the system's behaviour today;
the war room must judge whether issuance-time-only membership
is acceptable.

CYCLE 25 DISCLOSURE (CROSS-CHECK-18 Q2, settled): the leg-2
behaviour above is now stated explicitly as the contract in
signing/ceremony_authorisation.py: removing an operator
prevents future issuance; it does NOT revoke authorisations
already issued - they remain valid until TTL expiry. Where
an immediate cutover is required, pair removal with a
ceremony signing-key rotation (leg 3), which does invalidate
outstanding envelopes at consume.

CYCLE 25 (leg 4): the restored pin store's recovery no
longer rides an adopter-auto-requested supersession decision
(cycle 24's flow, held by seat-gpt in CROSS-CHECK-18 Q1).
The adopter now STOPS at PinSupersessionPendingApproval -
no decision requested, nothing consumed - and completes only
when a separately invoked attempt presents an out-of-band
independent supersession approval artefact (genuinely signed
by the real approval tool's signing function under a
dedicated approver key; the verifier, configured with the
approver public key only, verifies it before issuing). Leg 4
below is re-pointed through that independently authorised
route. NOTE: leg 4 builds its client directly (VerifierClient
with the approver public key added to the verifier env) —
that is now a CHOICE, not a necessity: seat B's
wiring-allowlist/harness updates for
AION_SUPERSESSION_APPROVER_PUBLIC_KEY (design section 4.3)
HAVE landed (the allowlist is 20 at every §4.3 site and the
harness provisions a real approver key), so the direct
construction is retained only as the leg's existing shape
and does not exercise the wiring validation layer; legs 1-3/5
above use the harness production_client unchanged.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cycle23_harness import (
    CAL, OPERATOR, SIGNER, SNAP_SIGNER, provision_production_home,
)
from core.loop import CoreLoop
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from signing.pin_store import PinStore
from trust.anchoring import load_anchor
from trust.errors import VerifierConfigError, VerifierProtocolError
from trust.ledger import (
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
    SigningLedger,
)
from trust.client import VerifierClient
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
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
from trust.wiring import production_client

OPERATOR_B = "operator-2"   # second entry of the harness OPERATORS
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


class ProductionCeremonyFixture(unittest.TestCase):
    """A production-mode verifier home plus a production_client
    and direct ceremony authorise/consume helpers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = provision_production_home(base / "prod-home")
        self.client = self._client(self.home.env, self.home.pub)
        self._evidence_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self, env, pub):
        return production_client(
            env, expected_signer_id=SIGNER,
            expected_key_id=self.home.verifier_key_id,
            authorisation_public_key=pub)

    def _env_with(self, **over):
        env = dict(self.home.env)
        env.update(over)
        return env

    def evidence(self, ref):
        artifact = f"rereview evidence bundle: {ref}\n".encode()
        (self.home.evidence_dir / ref).write_bytes(artifact)
        return hashlib.sha256(artifact).hexdigest()

    def authorise(self, client, *, operator_id=OPERATOR,
                  ceremony_id="ceremony-rereview-001",
                  evidence_ref="case-rereview-1"):
        return client.ceremony_authorise(
            operator_id=operator_id, ceremony_id=ceremony_id,
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate={"cycle_seq": 47, "payload_hash": CAND_HASH,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=self.evidence(evidence_ref),
            evidence_ref=evidence_ref)

    def consumption_entries(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return ledger.entries()

    def consumption_head(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return ledger.head_target()

    def signing_consume_mirrors(self):
        ledger = SigningLedger(self.home.verifier_home)
        return [e for e in ledger.entries()
                if e["kind"] == "consume"
                and e["format"] == "ceremony-consumption"]


class VerifierHomeRollbackTests(ProductionCeremonyFixture):
    """Leg 1: production-mode consumption-journal rollback."""

    def test_01_journal_only_rollback_refused_at_startup(self):
        envelope = self.authorise(self.client)
        journal_path = (self.home.verifier_home
                        / "ceremony-consumptions.json")
        # Pre-consumption bytes of the consumption journal
        # alone (the file does not exist yet: no consumption
        # has ever landed in this home).
        pre_bytes = journal_path.read_bytes() \
            if journal_path.exists() else None
        self.assertIsNone(pre_bytes)
        result = self.client.ceremony_consume(envelope)
        self.assertEqual(result["consumption_seq"], 1)
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(self.consumption_head(), (47, CAND_HASH))
        # The external consumption anchor advanced with the
        # burn and is LEFT at its current value by the rollback.
        anchor = load_anchor(self.home.anchor_paths["consumption"])
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(len(self.signing_consume_mirrors()), 1)
        # Roll ONLY the consumption journal back to its
        # pre-consumption bytes (a restored old backup).
        journal_path.unlink()
        self.assertEqual(self.consumption_entries(), [])
        # The next verifier ceremony operation refuses at
        # startup: the anchor (seq 1) is ahead of the
        # rolled-back journal (empty).
        fresh = self._client(self.home.env, self.home.pub)
        with self.assertRaises(VerifierConfigError) as cm:
            fresh.ceremony_consume(envelope)
        self.assertEqual(cm.exception.verifier_code,
                         "anchor_refused")
        # The consumed envelope did NOT become consumable
        # again: no new consumption landed, and the signing
        # ledger gained no second mirror.
        self.assertEqual(self.consumption_entries(), [])
        self.assertEqual(len(self.signing_consume_mirrors()), 1)
        anchor = load_anchor(self.home.anchor_paths["consumption"])
        self.assertEqual(anchor["seq"], 1)


class OperatorRemovalTests(ProductionCeremonyFixture):
    """Leg 2: authority transition - operator removal.

    OBSERVED BEHAVIOUR (see module docstring): removal
    refuses NEW authorisations for the removed operator, but
    the removed operator's outstanding envelope still
    CONSUMES. This diverges from the re-review brief's
    expectation that the transition invalidates outstanding
    envelopes at consume; it matches the consume mode's own
    documented contract (allowlist membership is an issuance
    fact, not a consumption gate). Pinned as observed."""

    def test_02_removed_operator_new_authorise_refused(self):
        env = self._env_with(AION_CEREMONY_OPERATORS=OPERATOR)
        restarted = self._client(env, self.home.pub)
        with self.assertRaises(VerifierConfigError) as cm:
            self.authorise(
                restarted, operator_id=OPERATOR_B,
                ceremony_id="ceremony-rereview-removed-001",
                evidence_ref="case-rereview-removed-1")
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_operator_not_authorised")
        self.assertEqual(self.consumption_entries(), [])

    def test_03_removed_operator_outstanding_envelope_still_consumes(self):
        # Issued while operator-2 was on the production list.
        envelope = self.authorise(
            self.client, operator_id=OPERATOR_B,
            ceremony_id="ceremony-rereview-b-001",
            evidence_ref="case-rereview-b-1")
        # Restart the verifier config with operator-2 REMOVED.
        env = self._env_with(AION_CEREMONY_OPERATORS=OPERATOR)
        restarted = self._client(env, self.home.pub)
        # OBSERVED: the outstanding (unexpired) envelope is
        # NOT refused at consume - it lands, exactly one
        # consumption, naming the removed operator.
        result = restarted.ceremony_consume(envelope)
        self.assertEqual(result["consumption_seq"], 1)
        self.assertEqual(result["new_cycle_seq"], 47)
        self.assertEqual(result["new_payload_hash"], CAND_HASH)
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["operator_id"], OPERATOR_B)
        self.assertEqual(self.consumption_head(), (47, CAND_HASH))


class CeremonyKeyRotationTests(ProductionCeremonyFixture):
    """Leg 3: authority transition - ceremony key rotation."""

    def _rotated(self):
        seed2_path = self.base / "ceremony-k2.seed"
        key2 = generate_ceremony_key_file(seed2_path)
        pub2 = ceremony_public_key_for(key2)
        env = self._env_with(
            AION_CEREMONY_SIGNING_SEED_PATH=str(seed2_path))
        return self._client(env, pub2), pub2

    def test_04_old_key_envelope_refused_after_rotation(self):
        envelope_k1 = self.authorise(
            self.client, ceremony_id="ceremony-rereview-k1-001",
            evidence_ref="case-rereview-k1-1")
        rotated, _pub2 = self._rotated()
        # The verifier now derives K2's public key from its
        # configured seed; the K1 envelope's signature no
        # longer verifies - one code, no per-reason oracle.
        with self.assertRaises(VerifierProtocolError) as cm:
            rotated.ceremony_consume(envelope_k1)
        self.assertEqual(cm.exception.verifier_code,
                         "ceremony_authorisation_invalid")
        self.assertEqual(self.consumption_entries(), [])

    def test_05_fresh_envelope_under_rotated_key_lands(self):
        envelope_k1 = self.authorise(
            self.client, ceremony_id="ceremony-rereview-k1-001",
            evidence_ref="case-rereview-k1-1")
        rotated, _pub2 = self._rotated()
        with self.assertRaises(VerifierProtocolError):
            rotated.ceremony_consume(envelope_k1)
        # A fresh envelope issued under K2 (client pinned to
        # K2's public key, as a legitimate rotation updates
        # the pin) authorises and consumes normally.
        envelope_k2 = self.authorise(
            rotated, ceremony_id="ceremony-rereview-k2-001",
            evidence_ref="case-rereview-k2-1")
        self.assertNotEqual(envelope_k2["authorisation_id"],
                            envelope_k1["authorisation_id"])
        self.assertNotEqual(envelope_k2["key_id"],
                            envelope_k1["key_id"])
        result = rotated.ceremony_consume(envelope_k2)
        self.assertEqual(result["consumption_seq"], 1)
        self.assertEqual(result["new_cycle_seq"], 47)
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["authorisation_id"],
                         envelope_k2["authorisation_id"])
        self.assertEqual(self.consumption_head(), (47, CAND_HASH))


class PinStoreRestorationTests(ProductionCeremonyFixture):
    """Leg 4: pin-store restoration under an advanced head.

    OBSERVED BEHAVIOUR: restoring the pin store file to its
    pre-gap-ceremony generation (pin seq 1, genesis history
    only) while the consumption head stays at seq 3 does not
    silently re-consume the seq-3 movement and does not
    regress anything. The next adopter attempt on a NEW state
    (seq 4) recovers only through the legitimate cycle-25
    independently authorised route: a fresh chain_gap_recovery
    ceremony whose first consume is refused pre-commit as
    supersede-required; the adopter STOPS
    (PinSupersessionPendingApproval - no decision requested,
    nothing consumed); an out-of-band approval artefact,
    genuinely signed by the approval tool under a dedicated
    approver key against the pending report completed from
    the verifier's own consumption journal, is placed in the
    adopter's inbox; only then does a later attempt present
    it, obtain the journaled supersession decision, and land
    exactly one new consumption, for the new seq-4 candidate."""

    def setUp(self):
        super().setUp()
        self.state_dir = self.base / "state"
        self.loop = CoreLoop(self.state_dir)
        cal_dir = self.state_dir / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_path = cal_dir / "calibration.json"
        self.calibration_path.write_bytes(CAL)
        self.pin_dir = self.base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        # Cycle 25: the dedicated approver key (tool side
        # only) and a verifier client whose env carries the
        # approver PUBLIC key (production mode requires it
        # beside the ceremony seed). Built directly, not via
        # production_client - see the module docstring note.
        self.approver_key = generate_approver_key_file(
            self.base / "approver.seed")
        approver_pub = approver_public_key_for(self.approver_key)
        env = dict(self.home.env)
        env["AION_SUPERSESSION_APPROVER_PUBLIC_KEY"] = \
            approver_pub.public_key.hex()
        client = VerifierClient(
            verifier_env=env, expected_signer_id=SIGNER,
            expected_key_id=self.home.verifier_key_id,
            authorisation_public_key=self.home.pub)
        self.inbox = self.base / "approval-inbox"
        self.inbox.mkdir()
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.home.evidence_dir,
            supersession_approval_path=self.inbox)
        self.adopter = PinAdopter(
            client=client, store=self.store,
            signing_key=self.home.snapshot_key, config=config,
            authorisation_public_key=self.home.pub)
        self._item_seq = 0

    def scan_items(self, n):
        start = self._item_seq
        items = [{"id": f"item-{start + i}",
                  "title": f"Restoration item {start + i}",
                  "leverage": float(n - i)}
                 for i in range(1, n + 1)]
        self._item_seq = start + n
        self.loop.scan(items)

    def bare_cycle(self):
        return self.loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)

    def read_store(self):
        return self.store.read_all(
            signing_key=self.home.snapshot_key)

    def test_06_restored_pin_store_recovers_only_via_supersede(self):
        # Genesis (seq 1, consumption 1), then a gap ceremony
        # to seq 3 (consumption 2, head at seq 3).
        self.scan_items(1)
        self.bare_cycle()
        genesis = self.adopter.snapshot_and_adopt()
        self.assertEqual(genesis.outcome, "reanchored")
        self.assertEqual(genesis.pin["cycle_seq"], 1)
        pre_advance_bytes = self.store.path.read_bytes()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        gap = self.adopter.snapshot_and_adopt()
        self.assertEqual(gap.outcome, "reanchored")
        self.assertEqual(gap.record.reason, "chain_gap_recovery")
        self.assertEqual(gap.pin["cycle_seq"], 3)
        self.assertEqual(len(self.consumption_entries()), 2)
        head_before = self.consumption_head()
        self.assertEqual(head_before, (3, gap.pin["payload_hash"]))
        # Restore the pin store file to its pre-advance bytes:
        # old pin (seq 1), genesis-only history. The verifier
        # consumption head stays advanced at seq 3.
        self.store.path.write_bytes(pre_advance_bytes)
        pin, history = self.read_store()
        self.assertEqual(pin, genesis.pin)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.consumption_head(), head_before)
        # Next adopter cycle, on new state (seq 4): the first
        # attempt STOPS at supersession pending independent
        # approval - no decision requested, nothing consumed,
        # pin still at the restored seq 1.
        self.scan_items(1)
        self.bare_cycle()
        with self.assertRaises(
                PinSupersessionPendingApproval) as cm:
            self.adopter.snapshot_and_adopt()
        self.assertEqual(cm.exception.candidate_seq, 4)
        self.assertEqual(len(self.consumption_entries()), 2)
        self.assertEqual(
            CeremonySupersessionLedger(
                self.home.verifier_home).entries(), [])
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # The approver's deliberate act: complete the pending
        # report's head seq/entry_hash from the verifier's own
        # consumption journal, sign with the real approval
        # tool under the approver key, drop the artefact in
        # the adopter's inbox.
        report = json.loads(
            self.adopter.pending_report_path.read_text(
                encoding="utf-8"))
        head = self.consumption_entries()[-1]
        # The adopter's report head is all-null here: the
        # seq-3 movement was ADOPTED by this adopter (then the
        # store was rolled back), so its journal holds no
        # unadopted burn to name the head from. The approver
        # completes the whole head block from the verifier's
        # own consumption journal - the deliberate act's
        # verification step.
        self.assertIsNone(report["head"]["authorisation_id"])
        report["head"] = {
            "authorisation_id": head["authorisation_id"],
            "ceremony_id": head["ceremony_id"],
            "old_cycle_seq": head["old_cycle_seq"],
            "old_payload_hash": head["old_payload_hash"],
            "new_cycle_seq": head["new_cycle_seq"],
            "new_payload_hash": head["new_payload_hash"],
            "seq": head["seq"],
            "entry_hash": head["entry_hash"]}
        signed_approval = build_approval_for_report(
            approver_key=self.approver_key,
            approver_id="approver-1", report=report)
        artefact = supersession_approval_to_dict(signed_approval)
        (self.inbox / f"{signed_approval.approval_id}.json"
         ).write_text(
            supersession_approval_to_json(signed_approval),
            encoding="utf-8")
        # The separately invoked attempt completes the route.
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.pin["cycle_seq"], 4)
        # Exactly ONE new consumption landed - the fresh seq-4
        # movement. The consumed seq-3 movement was NOT
        # re-consumed: still exactly one entry targets seq 3,
        # and the head moved forward to seq 4, never back.
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(
            len([e for e in entries if e["new_cycle_seq"] == 3]),
            1)
        self.assertEqual(entries[-1]["new_cycle_seq"], 4)
        self.assertEqual(self.consumption_head(),
                         (4, result.pin["payload_hash"]))
        # The recovery went through the independently approved
        # decision gate, not a silent landing: exactly one
        # supersession decision was journaled by the verifier,
        # abandoning the seq-3 head movement for this envelope,
        # and it records the approval that authorised it.
        decisions = CeremonySupersessionLedger(
            self.home.verifier_home).entries()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["new_authorisation_id"],
                         entries[-1]["authorisation_id"])
        self.assertEqual(decisions[0]["approval_id"],
                         artefact["approval_id"])
        # The adopted store is consistent: pin at seq 4, and
        # its history is the restored genesis record plus the
        # new seq-4 record (the seq-3 record stays lost with
        # the restored generation - the store never fabricates
        # it back).
        pin, history = self.read_store()
        self.assertEqual(pin, result.pin)
        self.assertEqual([r.new_cycle_seq for r in history],
                         [1, 4])


if __name__ == "__main__":
    unittest.main()
