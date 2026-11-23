"""Subprocess integration tests for ceremony CONSUMPTION
(cycle 21, seat C): authorise via the REAL verifier, consume
via VerifierClient.ceremony_consumer() inside
signing/pin_ceremony.reanchor_pin, against the verifier's
CeremonyConsumptionLedger + signing-ledger mirror.

Fixture discipline follows test_trust_ceremony_authorisation.py:
temp verifier-home (0700), generated verifier key, real
evidence artifact, ceremony seed via generate_ceremony_key_file
and the real loader, live clock end-to-end. Fixtures are
re-declared here, not imported, so this file runs standalone.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    load_ceremony_seed,
    sign_ceremony_authorisation,
)
from signing.pin_ceremony import reanchor_pin, verify_ceremony_record
from signing.state_snapshot import sign_state_snapshot
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import CeremonyConsumptionLedger, SigningLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
ARTIFACT = b"ceremony evidence bundle: consumption case file\n"
EVIDENCE = hashlib.sha256(ARTIFACT).hexdigest()
EVIDENCE_REF = "evidence-bundle-consumption"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
CAL = b'{"log":1}'


def state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq, "phase": "SCAN",
           "backlog": [], "history": history, "deltas": [],
           "history_pruned": 0, "deltas_pruned": 0,
           "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


def snap(seq, prev=""):
    return sign_state_snapshot(state_bytes(seq), signing_key=SNAP_KEY,
                               signer_id=SNAP_SIGNER,
                               calibration_bytes=CAL,
                               prev_snapshot_hash=prev)


def pin_of(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "key_id": s.key_id, "signer_id": s.signer_id}


def project_old_pin(pin):
    if pin is None:
        return None
    return {"cycle_seq": pin["cycle_seq"],
            "payload_hash": pin["payload_hash"]}


def project_candidate(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "signer_id": s.signer_id, "key_id": s.key_id}


class CeremonyConsumptionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.assertEqual(
            load_ceremony_seed(self.seed_path).key_id,
            self.seed_key.key_id)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        (self.evidence_dir / EVIDENCE_REF).write_bytes(ARTIFACT)
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATORS,
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = self._fresh_client()
        self._cid = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _fresh_client(self):
        return VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)

    def authorise(self, old_pin, cand, **over):
        self._cid += 1
        args = dict(
            operator_id=OPERATOR,
            ceremony_id=f"ceremony-consume-{self._cid}",
            reason="chain_gap_recovery" if old_pin is not None
                   else "initial_anchor",
            old_pin=project_old_pin(old_pin),
            candidate=project_candidate(cand),
            evidence_hash=EVIDENCE, evidence_ref=EVIDENCE_REF)
        args.update(over)
        envelope = self.client.ceremony_authorise(**args)
        return ceremony_authorisation_envelope_from_dict(envelope)

    def reanchor(self, old_pin, cand, authorisation, **over):
        """Consume via the real client-backed consumer unless a
        test overrides consume_authorisation. Live clock."""
        args = dict(
            signing_key=SNAP_KEY,
            state_bytes=state_bytes(cand.cycle_seq),
            calibration_bytes=CAL, expected_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR, reason="chain_gap_recovery",
            evidence_hash=EVIDENCE, authorisation=authorisation,
            authorisation_public_key=self.pub,
            expected_verifier_signer_id=SIGNER,
            ceremony_history=(),
            consume_authorisation=self.client.ceremony_consumer(),
            strict_reasons=("chain_gap",))
        args.update(over)
        return reanchor_pin(old_pin, cand, **args)

    def mint_directly(self, old_pin, cand, **over):
        """Sign an envelope directly with the seed — NO
        issuance ever happens at the verifier."""
        args = dict(
            signing_key=self.seed_key, signer_id=SIGNER,
            operator_id=OPERATOR,
            ceremony_id="ceremony-never-issued",
            reason="chain_gap_recovery",
            old_pin=project_old_pin(old_pin),
            candidate=project_candidate(cand),
            evidence_hash=EVIDENCE, evidence_ref=EVIDENCE_REF)
        args.update(over)
        return sign_ceremony_authorisation(**args)


class CeremonyConsumptionIntegrationTests(CeremonyConsumptionFixture):

    def test_full_flow_authorise_reanchor_with_client_consumer_succeeds(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        new_pin, rec = self.reanchor(pin_of(a), cand, auth)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.authorisation_id, auth.authorisation_id)
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())

    def test_replay_across_fresh_client_instances_refuses(self):
        # Same envelope, second ceremony run through a FRESH
        # VerifierClient (new subprocess per call anyway) with
        # a STALE () history: refuses already-consumed — the
        # authority is the verifier's journal, not the client
        # instance or the caller's history.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.reanchor(pin_of(a), cand, auth)
        fresh = self._fresh_client()
        with self.assertRaises(SigningError) as cm:
            self.reanchor(
                pin_of(a), cand, auth,
                consume_authorisation=fresh.ceremony_consumer())
        self.assertIn("already_consumed", str(cm.exception))

    def test_never_issued_envelope_refuses_at_consume(self):
        # Signed directly with the seed, never issued: the
        # signature is genuine, but there is no issuance-journal
        # entry, so the CONSUMER refuses (checked at the
        # consumer directly, isolating the consume leg from
        # reanchor_pin's local checks).
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.mint_directly(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            self.client.ceremony_consumer()(auth)
        self.assertIn("not_issued", str(cm.exception))
        with self.assertRaises(SigningError):
            self.reanchor(pin_of(a), cand, auth)

    def test_expired_envelope_refuses_at_consume(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.mint_directly(
            pin_of(a), cand, ceremony_id="ceremony-expired",
            now="2020-01-01T00:00:00+00:00")
        with self.assertRaises(SigningError) as cm:
            self.client.ceremony_consumer()(auth)
        self.assertIn("expired", str(cm.exception))

    def test_verifier_down_consumer_raises_and_reanchor_returns_nothing(self):
        # Fail-closed: a verifier that cannot be spawned makes
        # the consumer raise SigningError, and reanchor_pin
        # returns nothing (it raises; no pin/record exists).
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        down = VerifierClient(
            module="trust.no_such_verifier_module",
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        with self.assertRaises(SigningError):
            down.ceremony_consumer()(auth)
        with self.assertRaises(SigningError):
            self.reanchor(
                pin_of(a), cand, auth,
                consume_authorisation=down.ceremony_consumer())

    def test_mirror_scoping_sign_and_consume_entries_coexist(self):
        # Mirror scoping (DESIGN-FINAL R4 trap): the signing
        # ledger holds BOTH the kind="sign" issuance mirror and
        # the kind="consume" consumption mirror for the same
        # authorisation_id, and a second consume still refuses
        # already-consumed — the consume check is scoped to
        # kind="consume" + format="ceremony-consumption" and is
        # not confused by the sign entry (nor did the sign
        # entry block the first consume, above).
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.reanchor(pin_of(a), cand, auth)
        entries = SigningLedger(self.home / "ledger").entries()
        mine = [e for e in entries
                if e.get("decision_id") == auth.authorisation_id]
        kinds = {(e["kind"], e["format"]) for e in mine}
        self.assertIn(("sign", "ceremony-authorisation"), kinds)
        self.assertIn(("consume", "ceremony-consumption"), kinds)
        with self.assertRaises(SigningError) as cm:
            self.reanchor(pin_of(a), cand, auth)
        self.assertIn("already_consumed", str(cm.exception))


class CeremonyRecoveryIntegrationTests(CeremonyConsumptionFixture):
    """WS1 (cycle 22): honest recovery under reason
    burned_unadopted, end-to-end against the real verifier.
    A burn is produced by a consume that commits at the
    verifier while the caller then "crashes" without adopting
    (the commit-then-raise harness shape); recovery is a NEW
    ceremony (new ceremony_id, NEW evidence artefact) whose
    authorise must be proven against the consumption
    journal's head entry (verifier step 5b)."""

    def add_evidence(self, name, data):
        (self.evidence_dir / name).write_bytes(data)
        return hashlib.sha256(data).hexdigest(), name

    def burn_via_reanchor_crash(self, old_pin, cand, auth,
                                evidence_hash):
        """Consume auth inside reanchor_pin, then raise as if
        the caller crashed after the commit: reanchor_pin
        returns nothing and the pin stays unmoved."""
        real_consumer = self.client.ceremony_consumer()

        def crashing_consumer(signed):
            real_consumer(signed)
            raise SigningError("simulated crash after commit")

        with self.assertRaises(SigningError):
            self.reanchor(
                old_pin, cand, auth, evidence_hash=evidence_hash,
                reason=auth.reason,
                consume_authorisation=crashing_consumer)

    def consumption_entries(self):
        ledger_home = self.home / "ledger"
        if not (ledger_home / "ceremony-consumptions.json").exists():
            return []
        return CeremonyConsumptionLedger(ledger_home).entries()

    def recovery_authorise(self, old_pin, cand, name, data):
        ev_hash, ev_ref = self.add_evidence(name, data)
        envelope = self.authorise(
            old_pin, cand, reason="burned_unadopted",
            evidence_hash=ev_hash, evidence_ref=ev_ref)
        return envelope, ev_hash

    def test_recovery_happy_path_had_a_pin(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.burn_via_reanchor_crash(pin_of(a), cand, auth, EVIDENCE)
        recovery, ev_hash = self.recovery_authorise(
            pin_of(a), cand, "evidence-recovery-1",
            b"recovery evidence bundle one\n")
        new_pin, rec = self.reanchor(
            pin_of(a), cand, recovery, reason="burned_unadopted",
            evidence_hash=ev_hash)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.reason, "burned_unadopted")
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())

    def test_recovery_happy_path_no_pin(self):
        cand = snap(4, prev="f" * 64)
        auth = self.authorise(None, cand)
        # Burn the no-pin envelope directly at the verifier.
        self.client.ceremony_consumer()(auth)
        recovery, ev_hash = self.recovery_authorise(
            None, cand, "evidence-recovery-nopin",
            b"recovery evidence bundle no-pin\n")
        new_pin, rec = self.reanchor(
            None, cand, recovery, reason="burned_unadopted",
            evidence_hash=ev_hash, strict_reasons=())
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.reason, "burned_unadopted")
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())

    def test_recovery_forgery_no_burn_unproven(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(VerifierConfigError) as cm:
            self.recovery_authorise(
                pin_of(a), cand, "evidence-forgery-1",
                b"forgery evidence bundle\n")
        self.assertIn("ceremony_recovery_unproven",
                      str(cm.exception))

    def test_recovery_forgery_different_target_same_code(self):
        # Burn target T1; a recovery aimed at a DIFFERENT
        # target, and one aimed at T1 with a DIFFERENT old
        # pin, both refuse with the SAME code — no oracle
        # distinguishing the sub-cases.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.burn_via_reanchor_crash(pin_of(a), cand, auth, EVIDENCE)
        other = snap(5, prev="e" * 64)
        with self.assertRaises(VerifierConfigError) as cm1:
            self.recovery_authorise(
                pin_of(a), other, "evidence-forgery-2",
                b"forgery evidence bundle two\n")
        b = snap(2)
        with self.assertRaises(VerifierConfigError) as cm2:
            self.recovery_authorise(
                pin_of(b), cand, "evidence-forgery-3",
                b"forgery evidence bundle three\n")
        self.assertIn("ceremony_recovery_unproven",
                      str(cm1.exception))
        self.assertIn("ceremony_recovery_unproven",
                      str(cm2.exception))

    def test_recovery_is_one_shot_second_recovery_refused(self):
        """One-shot recovery (cycle-22 war-room fix round,
        rev-r6 F1): a burned_unadopted recovery is one-shot
        per burned movement — the first recovery authorises,
        consumes, and succeeds, but a SECOND burned_unadopted
        ceremony for the same target/old-pin pair is refused
        at authorise with the single code
        ceremony_recovery_unproven, because a recovery
        consumption cannot ground another recovery. This
        supersedes the iterated-chain semantics (design-A
        §6.2) this test previously pinned, under which a
        second recovery recovering the first recovery's head
        entry succeeded."""
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.burn_via_reanchor_crash(pin_of(a), cand, auth, EVIDENCE)
        recovery1, ev1 = self.recovery_authorise(
            pin_of(a), cand, "evidence-one-shot-1",
            b"one-shot evidence bundle one\n")
        new_pin, rec = self.reanchor(
            pin_of(a), cand, recovery1, reason="burned_unadopted",
            evidence_hash=ev1)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.authorisation_id,
                         recovery1.authorisation_id)
        self.assertEqual(rec.reason, "burned_unadopted")
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())
        consumed_before = len(self.consumption_entries())
        self.assertEqual(consumed_before, 2)
        with self.assertRaises(VerifierConfigError) as cm:
            self.recovery_authorise(
                pin_of(a), cand, "evidence-one-shot-2",
                b"one-shot evidence bundle two\n")
        self.assertIn("ceremony_recovery_unproven",
                      str(cm.exception))
        self.assertEqual(
            str(cm.exception).count("ceremony_recovery_unproven"),
            1)
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)

    def test_recovery_envelope_consumed_twice_refused(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        self.burn_via_reanchor_crash(pin_of(a), cand, auth, EVIDENCE)
        recovery, ev_hash = self.recovery_authorise(
            pin_of(a), cand, "evidence-twice-1",
            b"twice evidence bundle\n")
        self.reanchor(
            pin_of(a), cand, recovery, reason="burned_unadopted",
            evidence_hash=ev_hash)
        with self.assertRaises(SigningError) as cm:
            self.client.ceremony_consumer()(recovery)
        self.assertIn("already_consumed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
