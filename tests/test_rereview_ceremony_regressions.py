"""Cross-cycle regression tests for the cycles 14-16 re-review.

Cycles 14-16 built three public surfaces: the chain-gap rule in
the strict snapshot wrapper (``verify_snapshot_for_state``,
cycle 14), the pin ceremony (``advance_pin`` / ``reanchor_pin``
/ ``classify_verification`` / ``verify_ceremony_record``,
cycle 15) and its hardening (cycle 16). They were HELD on
external FIX verdicts. Cycles 19-24 then changed everything
around them: verifier-env operator authority with Ed25519
authorisation envelopes (v2, HMAC deleted), verifier-resolved
evidence provenance, a REQUIRED verifier-owned consumption
head, ``PinStore`` + ``PinAdopter`` as the production path,
schema-v2 lineage and journaled supersession. This file pins
the OLD surfaces under the NEW semantics; it writes no
production code and duplicates no existing test.

Legs already covered elsewhere (named here as the evidence
for that leg, per the re-review brief — NOT re-tested here):

- Leg 2(a), ``consume_authorisation`` omission / None /
  non-callable refusals on ``reanchor_pin``:
  tests/test_signing_pin_ceremony.py,
  Cycle21ConsumptionTests
  .test_t1b_consume_authorisation_keyword_is_required and
  .test_t1b_none_and_noncallable_refuse_before_envelope_verification.
- Leg 3, the pure-function partition of
  ``classify_verification`` over hand-built reason tuples:
  tests/test_signing_pin_ceremony.py,
  ClassifyTests.test_classification_contract. What was
  missing — and is added below — is the same partition
  exercised end-to-end against snapshots produced by the
  current signing path.
- Leg 4, the authorisation-ENVELOPE layer of the v1 flag-day:
  tests/test_signing_pin_ceremony.py, Cycle20ConsumptionTests
  .test_v1_golden_envelope_refused_with_version_wording (a
  literal v1/HMAC-era envelope dict is refused by
  ``ceremony_authorisation_envelope_from_dict`` with wording
  naming the superseded version, and a raw dict presented to
  ``reanchor_pin`` refuses as a non-typed authorisation).
  What was missing — and is added below — is the
  ceremony-RECORD layer of the same flag-day.
- Leg 1, the chain-gap rule against hand-built pins:
  tests/test_signing_state_snapshot.py, Cycle14ChainGapTests;
  and adopter advance/gap movement in production mode:
  tests/test_trust_production_e2e.py. What was missing — and
  is added below — is the composition: a pin that ARRIVED via
  the current production adoption path (verifier-owned
  consumption included) fed back into cycle 14's strict
  wrapper as the trust anchor.

Integration fixture: the production-mode harness of
tests/test_trust_production_e2e.py — a disposable
production verifier home from tests/cycle23_harness.py
(``provision_production_home``) and an adopter built ONLY via
``build_pin_adopter`` (its client comes from
``trust.wiring.production_client``). Fixtures are re-declared
here, not imported from the e2e test module, so this file
runs standalone; the shared provisioning harness itself is
imported, exactly as the production e2e suite imports it.
"""

import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cycle23_harness import (
    CAL, OPERATOR, SIGNER, SNAP_SIGNER, provision_production_home,
)
from core.loop import CoreLoop
from signing import SigningError, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict,
)
from signing.pin_ceremony import (
    PinCeremonyRecord,
    classify_verification,
    reanchor_pin,
    verify_ceremony_record,
)
from signing.pin_ceremony import (
    _mac as _ceremony_mac,
    _payload_hash as _ceremony_payload_hash,
)
from signing.pin_store import (
    PinStore,
    ceremony_record_from_dict,
    ceremony_record_to_dict,
)
from signing.state_snapshot import (
    sign_state_snapshot,
    verify_snapshot_for_state,
)
from trust.ledger import CeremonyConsumptionLedger
from trust.pin_adoption import PinAdopterConfig, build_pin_adopter

CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}


class ProductionPinFixture(unittest.TestCase):
    """The production e2e fixture shape: production-mode
    verifier home, real CoreLoop state, adopter built via
    build_pin_adopter against a PinStore outside the state
    dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = provision_production_home(base / "prod-home")
        self.state_dir = base / "state"
        self.loop = CoreLoop(self.state_dir)
        cal_dir = self.state_dir / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_path = cal_dir / "calibration.json"
        self.calibration_path.write_bytes(CAL)
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.home.evidence_dir)
        self.adopter = build_pin_adopter(
            self.home.env, expected_signer_id=SIGNER,
            expected_key_id=self.home.verifier_key_id,
            authorisation_public_key=self.home.pub,
            signing_key_path=self.home.snapshot_key_path,
            config=config)
        self._item_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def scan_items(self, n):
        start = self._item_seq
        items = [{"id": f"item-{start + i}",
                  "title": f"Re-review item {start + i}",
                  "leverage": float(n - i)}
                 for i in range(1, n + 1)]
        self._item_seq = start + n
        self.loop.scan(items)

    def bare_cycle(self):
        return self.loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)

    def state_bytes(self):
        return self.loop.state_path.read_bytes()

    def read_store(self):
        return self.store.read_all(
            signing_key=self.home.snapshot_key)

    def consumption_count(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return len(ledger.entries())

    def genesis(self):
        """Adopt the seq-1 pin through the CURRENT production
        path: initial_anchor ceremony, verifier-issued v2
        envelope, verifier-owned consumption, atomic PinStore
        adoption."""
        self.scan_items(1)
        self.bare_cycle()
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "initial_anchor")
        self.assertEqual(result.pin["cycle_seq"], 1)
        return result

    def sign_current(self, prev=""):
        return sign_state_snapshot(
            self.state_bytes(),
            signing_key=self.home.snapshot_key,
            signer_id=SNAP_SIGNER, calibration_bytes=CAL,
            prev_snapshot_hash=prev)

    def strict(self, signed, pin):
        return verify_snapshot_for_state(
            signed, signing_key=self.home.snapshot_key,
            state_bytes=self.state_bytes(), calibration_bytes=CAL,
            expected_pin=pin, expected_signer_id=SNAP_SIGNER)


class HeadBindsChainGapTests(ProductionPinFixture):
    """Leg 1: the pin cycle 22-24's production machinery
    adopted is the same trust anchor cycle 14's chain-gap
    invariant judges against."""

    def test_adopted_pin_accepts_next_and_refuses_pin_plus_two(self):
        genesis = self.genesis()
        pin, history = self.read_store()
        # The pin in force IS the pin the production path
        # returned, and it arrived with exactly one verifier
        # consumption behind it — the machinery cycle 14
        # never had.
        self.assertEqual(pin, genesis.pin)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.consumption_count(), 1)

        # pin+1, correctly chained to the adopted pin: the
        # strict wrapper accepts.
        self.scan_items(1)
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 2)
        next_snap = self.sign_current(prev=pin["payload_hash"])
        self.assertEqual(self.strict(next_snap, pin), ())

        # pin+2, CORRECTLY linked to the unseen pin+1
        # snapshot: correctness at that distance is
        # unobservable from the adopted pin, so cycle 14's
        # rule refuses with exactly ("chain_gap",).
        self.scan_items(1)
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 3)
        gap_snap = self.sign_current(prev=next_snap.payload_hash)
        reasons = self.strict(gap_snap, pin)
        self.assertEqual(reasons, ("chain_gap",))
        self.assertEqual(classify_verification(reasons),
                         "reanchor_required")


class FabricatedConsumptionTests(ProductionPinFixture):
    """Leg 2(b): a consume callable that returns a fabricated
    success WITHOUT verifier journaling does not move the
    pin in the PinStore.

    Honest scope, pinned deliberately: ``reanchor_pin``
    itself returns a (pin, record) pair under the stub —
    that is the documented cycle-21 R5 residual (single-use
    is a property of the INTEGRATED SYSTEM under production
    wiring, not of ``reanchor_pin`` for an arbitrary
    caller-supplied callable; a no-op callable gets no
    protection). What this test pins is the part of the
    current semantics that DOES hold at the real surfaces:
    the fabricated consume journals nothing at the verifier,
    and the PinStore — the only place a pin is in force —
    does not move. Pin movement requires the adopter's
    atomic ``PinStore.adopt`` step, which the fabricated
    path never reaches.
    """

    def test_fabricated_consume_journals_nothing_and_store_unmoved(self):
        self.genesis()
        old_pin, history = self.read_store()
        store_bytes_before = self.store.path.read_bytes()
        consumption_before = self.consumption_count()

        # A gap candidate at seq 3 against the seq-1 pin.
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.assertEqual(self.loop.state["cycle_seq"], 3)
        candidate = self.sign_current()
        self.assertEqual(
            self.strict(candidate, old_pin), ("chain_gap",))

        # A GENUINE verifier-issued v2 envelope for this exact
        # event (the authority leg is real; only the consume
        # callable is fabricated). The evidence artefact is
        # placed where the production verifier resolves it,
        # and the hash is computed from the adopter-side
        # bytes, as the production flow does.
        ceremony_id = f"pin-rereview-3-{uuid.uuid4().hex[:12]}"
        evidence_ref = f"pin-evidence-{ceremony_id}"
        bundle = (
            "rereview fabricated-consume evidence\n"
            f"ceremony_id={ceremony_id}\n"
            f"candidate_seq={candidate.cycle_seq}\n"
            f"candidate_hash={candidate.payload_hash}\n"
        ).encode("utf-8")
        (self.home.evidence_dir / evidence_ref).write_bytes(bundle)
        evidence_hash = hashlib.sha256(bundle).hexdigest()
        envelope_dict = self.adopter._client.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id=ceremony_id,
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": old_pin["cycle_seq"],
                     "payload_hash": old_pin["payload_hash"]},
            candidate={"cycle_seq": candidate.cycle_seq,
                       "payload_hash": candidate.payload_hash,
                       "signer_id": candidate.signer_id,
                       "key_id": candidate.key_id},
            evidence_hash=evidence_hash, evidence_ref=evidence_ref)
        envelope = ceremony_authorisation_envelope_from_dict(
            envelope_dict)

        calls = []

        def fabricated_consume(authorisation):
            # A cycle-15-era caller-side success: a receipt
            # shaped like a verifier answer, returned without
            # any round-trip — nothing is journaled anywhere.
            calls.append(authorisation)
            return {"status": "consumed",
                    "receipt": "fabricated-" + "0" * 32}

        returned_pin, record = reanchor_pin(
            old_pin, candidate,
            signing_key=self.home.snapshot_key,
            state_bytes=self.state_bytes(), calibration_bytes=CAL,
            expected_signer_id=SNAP_SIGNER, operator_id=OPERATOR,
            reason="chain_gap_recovery",
            evidence_hash=evidence_hash, authorisation=envelope,
            authorisation_public_key=self.home.pub,
            expected_verifier_signer_id=SIGNER,
            ceremony_history=history,
            consume_authorisation=fabricated_consume,
            strict_reasons=("chain_gap",))

        # The stub WAS the consumption step reanchor_pin ran
        # (exactly once), and — the R5 residual, asserted so
        # the re-review sees it rather than a claim that the
        # function refused — reanchor_pin returned a pair.
        self.assertEqual(len(calls), 1)
        self.assertEqual(returned_pin["cycle_seq"], 3)
        self.assertEqual(record.new_cycle_seq, 3)

        # But nothing landed: no verifier consumption was
        # journaled, and the pin in force in the PinStore is
        # byte-for-byte the pre-ceremony pin, history intact.
        self.assertEqual(self.consumption_count(),
                         consumption_before)
        self.assertEqual(self.store.path.read_bytes(),
                         store_bytes_before)
        pin_after, history_after = self.read_store()
        self.assertEqual(pin_after, old_pin)
        self.assertEqual(history_after, history)


# -- Leg 3: classify_verification against the current signing path ----

_SNAP_KEY = make_signing_key(bytes(range(32, 64)))
_SNAP_SIGNER = "seat-3"
_NOW = "2026-11-20T12:00:00+00:00"
_CAL = b'{"log":1}'


def _state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq,
           "phase": "SCAN", "backlog": [], "history": history,
           "deltas": [], "history_pruned": 0, "deltas_pruned": 0,
           "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


def _snap(seq, prev=""):
    return sign_state_snapshot(
        _state_bytes(seq), signing_key=_SNAP_KEY,
        signer_id=_SNAP_SIGNER, calibration_bytes=_CAL,
        prev_snapshot_hash=prev, now=_NOW)


def _pin_of(signed):
    return {"cycle_seq": signed.cycle_seq,
            "payload_hash": signed.payload_hash,
            "key_id": signed.key_id, "signer_id": signed.signer_id}


class ClassifyCoherenceEndToEndTests(unittest.TestCase):
    """Leg 3: cycle 15's classifier partitions outcomes the
    CURRENT signing path actually produces through the strict
    wrapper. The mixed case IS reachable end-to-end (a gap
    candidate verified against the wrong calibration bytes
    co-reports calibration_mismatch with chain_gap), so no
    leg here rests on hand-built reason tuples alone."""

    def _strict(self, signed, pin, calibration_bytes=_CAL):
        return verify_snapshot_for_state(
            signed, signing_key=_SNAP_KEY,
            state_bytes=_state_bytes(signed.cycle_seq),
            calibration_bytes=calibration_bytes,
            expected_pin=pin, expected_signer_id=_SNAP_SIGNER,
            now=_NOW)

    def test_ok_outcome_classifies_ok(self):
        first = _snap(1)
        second = _snap(2, prev=first.payload_hash)
        reasons = self._strict(second, _pin_of(first))
        self.assertEqual(reasons, ())
        self.assertEqual(classify_verification(reasons), "ok")

    def test_sole_chain_gap_classifies_reanchor_required(self):
        first = _snap(1)
        second = _snap(2, prev=first.payload_hash)
        third = _snap(3, prev=second.payload_hash)
        reasons = self._strict(third, _pin_of(first))
        self.assertEqual(reasons, ("chain_gap",))
        self.assertEqual(classify_verification(reasons),
                         "reanchor_required")

    def test_mixed_chain_gap_classifies_integrity_failure(self):
        first = _snap(1)
        second = _snap(2, prev=first.payload_hash)
        third = _snap(3, prev=second.payload_hash)
        reasons = self._strict(third, _pin_of(first),
                               calibration_bytes=b'{"log":2}')
        self.assertIn("chain_gap", reasons)
        self.assertIn("calibration_mismatch", reasons)
        self.assertGreaterEqual(len(reasons), 2)
        self.assertEqual(classify_verification(reasons),
                         "integrity_failure")


# -- Leg 4: the v1 / HMAC-era flag-day at the record layer -------------


class V1CeremonyRecordFlagDayTests(unittest.TestCase):
    """Leg 4: a ceremony record in the pre-cycle-20 shape
    does NOT verify under current semantics.

    Which layers refuse it, precisely:

    - A cycle-15-era record carried NO authorisation binding:
      ``ceremony_id`` / ``authorisation_id`` were added as
      REQUIRED fields in cycle 19. The v1 shape is therefore
      unrepresentable as a current ``PinCeremonyRecord``
      payload that verifies: serialised in its own shape it
      is refused at reconstruction by the pin store
      (``ceremony_record_from_dict``: missing keys), and
      carried into the current dataclass with the binding
      fields empty it is refused by
      ``verify_ceremony_record`` itself with
      ``invalid_authorisation`` — even when its HMAC record
      MAC is perfectly valid. That last point is the honest
      layering: the ceremony RECORD's MAC is still the
      symmetric HMAC of cycles 15-16 (unchanged by design;
      the cycle-20 asymmetry covers the authorisation
      envelope only), so the flag-day refusal for records
      lives in the authorisation-binding validation, not in
      the MAC check.
    - The authorisation-envelope layer of the same flag-day
      is already pinned by the golden test named in the
      module docstring; a full v1 ENVELOPE cannot be built
      with current code because the v1 HMAC minting path is
      deleted from signing/ceremony_authorisation.py.
    """

    def _v1_shaped_record(self):
        """A record with every cycle-15 field coherent and a
        VALID current-algorithm record MAC, but the v1-era
        empty authorisation binding."""
        record = PinCeremonyRecord(
            old_cycle_seq=1, old_payload_hash="a" * 64,
            new_cycle_seq=4, new_payload_hash="b" * 64,
            operator_id="operator-1", reason="chain_gap_recovery",
            evidence_hash="e" * 64,
            candidate_signer_id=_SNAP_SIGNER,
            candidate_key_id=_SNAP_KEY.key_id,
            key_id=_SNAP_KEY.key_id, performed_at=_NOW,
            payload_hash="", signature="",
            ceremony_id="", authorisation_id="")
        payload_hash = _ceremony_payload_hash(record.payload())
        return replace(
            record, payload_hash=payload_hash,
            signature=_ceremony_mac(
                _SNAP_KEY.key, payload_hash, _SNAP_KEY.key_id))

    def test_v1_shaped_record_fails_verify_ceremony_record(self):
        record = self._v1_shaped_record()
        reasons = verify_ceremony_record(
            record, signing_key=_SNAP_KEY)
        self.assertNotEqual(reasons, ())
        self.assertIn("invalid_authorisation", reasons)
        # The MAC is NOT the refusing layer: neither MAC nor
        # payload-hash reasons appear — the record is refused
        # for lacking the v2-era authorisation binding alone.
        self.assertNotIn("signature_mismatch", reasons)
        self.assertNotIn("payload_hash_mismatch", reasons)

    def test_v1_shaped_record_dict_refused_at_reconstruction(self):
        record = self._v1_shaped_record()
        v1_dict = ceremony_record_to_dict(record)
        # The exact cycle-15 serialised shape: the two
        # authorisation-binding fields do not exist yet.
        del v1_dict["ceremony_id"]
        del v1_dict["authorisation_id"]
        with self.assertRaises(SigningError) as cm:
            ceremony_record_from_dict(v1_dict)
        self.assertIn("missing or unknown keys", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
