"""E2E tests for cycle 19 Part C: ceremony authorisation consumed
by signing/pin_ceremony.reanchor_pin, issued by the REAL verifier
subprocess (trust.verifier_main, mode ceremony_authorise) with
AION_CEREMONY_OPERATORS set.

Fixture discipline follows test_trust_verifier.py: temp
verifier-home (0700), generated verifier key, fake registry. The
fixture holds the verifier key test-side only to verify outcomes
and to consume envelopes as a key-holding consumer would. The
SNAPSHOT key is a distinct test key — key separation between the
authorisation key and the snapshot key is enforced in-process.

Clock discipline (critique-c catch): the verifier signs with its
real clock, so the happy paths omit now= end-to-end (live clock
on both sides); fixed-time snapshots would read as
signed_in_future / expired against a live-issued envelope.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict)
from signing.pin_ceremony import reanchor_pin, verify_ceremony_record
from signing.state_snapshot import sign_state_snapshot
from trust.client import VerifierClient
from trust.errors import VerifierConfigError

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
EVIDENCE = "e" * 64
EVIDENCE_REF = "evidence-bundle-e2e"
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
    # No now=: live clock, matching the verifier's (see docstring).
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


class CeremonyAuthorisationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
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
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)
        self._cid = 0

    def tearDown(self):
        self.tmp.cleanup()

    def authorise(self, old_pin, cand, **over):
        """Ask the real verifier for an envelope, return the
        reconstructed typed object."""
        self._cid += 1
        args = dict(
            operator_id=OPERATOR,
            ceremony_id=f"ceremony-e2e-{self._cid}",
            reason="chain_gap_recovery" if old_pin is not None
                   else "initial_anchor",
            old_pin=project_old_pin(old_pin),
            candidate=project_candidate(cand),
            evidence_hash=EVIDENCE, evidence_ref=EVIDENCE_REF)
        args.update(over)
        envelope = self.client.ceremony_authorise(**args)
        return ceremony_authorisation_envelope_from_dict(envelope)

    def reanchor(self, old_pin, cand, authorisation, **over):
        """Consume an envelope in reanchor_pin with NO caller
        list anywhere (the parameter no longer exists). Live
        clock: no now= unless a test overrides it."""
        args = dict(
            signing_key=SNAP_KEY,
            state_bytes=state_bytes(cand.cycle_seq),
            calibration_bytes=CAL, expected_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR, reason="chain_gap_recovery",
            evidence_hash=EVIDENCE, authorisation=authorisation,
            authorisation_key=self.key,
            expected_verifier_signer_id=SIGNER,
            strict_reasons=("chain_gap",))
        args.update(over)
        return reanchor_pin(old_pin, cand, **args)


class CeremonyAuthorisationE2ETests(CeremonyAuthorisationFixture):
    def test_listed_operator_envelope_reanchor_succeeds_without_caller_list(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        new_pin, rec = self.reanchor(pin_of(a), cand, auth)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.ceremony_id, auth.ceremony_id)
        self.assertEqual(rec.authorisation_id, auth.authorisation_id)
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())

    def test_no_pin_initial_anchor_envelope_path(self):
        cand = snap(2)
        auth = self.authorise(None, cand)
        self.assertIsNone(auth.old_pin)
        new_pin, rec = self.reanchor(
            None, cand, auth, reason="initial_anchor",
            strict_reasons=None)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.ceremony_id, auth.ceremony_id)
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=SNAP_KEY), ())

    def test_invented_operator_refused_verifier_side_no_envelope(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(VerifierConfigError):
            self.authorise(pin_of(a), cand,
                           operator_id="operator-invented")
        # No envelope exists to present: the refusal above is the
        # whole story — there is nothing to hand reanchor_pin.

    def test_envelope_replayed_against_different_candidate_refused(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        other = snap(5, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            self.reanchor(pin_of(a), other, auth)
        self.assertIn("different candidate", str(cm.exception))

    def test_envelope_replayed_against_different_pin_refused(self):
        a, b = snap(1), snap(2)
        cand = snap(5, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            self.reanchor(pin_of(b), cand, auth)
        self.assertIn("different old pin", str(cm.exception))

    def test_evidence_hash_swapped_refused(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            self.reanchor(pin_of(a), cand, auth,
                          evidence_hash="d" * 64)
        self.assertIn("different evidence", str(cm.exception))

    def test_consumption_side_replay_within_ttl_without_history_succeeds_documented_limit(self):
        # Pins the C3 documented limit, NOT a feature: the ledger
        # burns the (ceremony_id, evidence_hash) pair at ISSUANCE,
        # not at consumption, and ceremony_history is optional —
        # so the SAME envelope consumed twice for the identical
        # ceremony succeeds twice within its TTL. If a future
        # cycle closes this (mandatory history / consumption-side
        # ledger check), this test must be rewritten with it.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = self.authorise(pin_of(a), cand)
        pin1, rec1 = self.reanchor(pin_of(a), cand, auth)
        pin2, rec2 = self.reanchor(pin_of(a), cand, auth)
        self.assertEqual(pin1, pin2)
        self.assertEqual(rec1.authorisation_id,
                         rec2.authorisation_id)


if __name__ == "__main__":
    unittest.main()
