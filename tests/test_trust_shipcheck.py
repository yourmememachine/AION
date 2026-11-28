"""Tests for trust.shipcheck + trust.ledger + trust.release
(cycle 7/8): the signed ship path end to end over a fake repo, a
temp CoreLoop, and a verifier-home ship ledger.

The central pins: a ship decision authorises exactly one
artifact; replay — including after a loop-state rollback, and
including a freshly re-signed envelope for the same artifact —
cannot ship twice; the burn precedes the record and is never
refunded.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.gate import GateDecision, VerifierAttestation
from signing import (
    PURPOSE_SHIP,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
from trust.errors import ShipRefused
from trust.ledger import (
    CorruptLedgerError,
    LedgerError,
    ShipLedger,
    SigningLedger,
)
from trust.manifest import build_manifest
from trust.release import build_release_record, release_from_json
from trust.shipcheck import check_ship, record_ship

KEY = make_signing_key(bytes(range(32, 64)))


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


NOW = _ts(0)          # wall-clock: record_ship takes no now=
ATTESTED = _ts(-10)
SATT_AT = _ts(-5)


def _refresh_clock():
    """Re-stamp the fixture clock (cycle 33): freshness checks
    use the host wall clock, so import-time stamps expire during
    a long test run; setUp re-stamps instead."""
    global NOW, ATTESTED, SATT_AT
    NOW = _ts(0)
    ATTESTED = _ts(-10)
    SATT_AT = _ts(-5)
SEALED = "b" * 64
PROPOSAL = "prop-ship"
ITEM = "store-enforced-signed-commits"
CODERS = ["seat-1", "seat-2", "seat-3"]
REVIEWERS = ["rev-r1", "rev-r2", "rev-r3", "rev-r4", "rev-r5", "rev-r6"]
DELTA = {"metric": "tests_passing", "before": 1, "after": 2,
         "evidence_ref": "fixture run", "verifier": "rev-r1"}


def make_tree(root: Path):
    (root / "core").mkdir(parents=True)
    (root / "core" / "a.py").write_text("A = 1\n")
    (root / "eval").mkdir()
    (root / "eval" / "gate.py").write_text("GATE = True\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (root / "internal").mkdir()
    (root / "internal" / "REVIEW.md").write_text("# review\n")
    return root


class ShipFixture(unittest.TestCase):
    def setUp(self):
        _refresh_clock()
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = make_tree(base / "repo")
        self.home = base / "verifier-home"
        self.ledger = ShipLedger(self.home)
        self.loop = CoreLoop(base / "loop-state")
        self.loop.scan([{"id": ITEM, "title": "fixture ship item",
                         "leverage": 5.0}])
        self.manifest = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        self.att = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="review-cycle-8",
            attested_at=ATTESTED)
        self.satt = sign_attestation(
            self.att, signing_key=KEY, signer_id="seat-3",
            proposal_id=PROPOSAL,
            manifest_hash=self.manifest.manifest_hash,
            now=SATT_AT)
        self.envelope = self._envelope()

    def tearDown(self):
        self.tmp.cleanup()

    def _envelope(self, **over):
        decision = GateDecision(
            accepted=True, proposal_id=PROPOSAL, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=NOW,
            protected_violations=(),
            verifier_note=f"content-hash:{self.manifest.manifest_hash}")
        kw = dict(signing_key=KEY, signer_id="verifier-svc",
                  attestation=self.att, signed_attestation=self.satt,
                  gate_inputs_hash=self.manifest.manifest_hash,
                  purpose=PURPOSE_SHIP, now=NOW)
        kw.update(over)
        return sign_gate_decision(decision, **kw)

    def check(self, **over):
        kw = dict(signing_key=KEY, ledger=self.ledger,
                  expected_attestation=self.satt, now=NOW)
        kw.update(over)
        return check_ship(self.root, self.manifest, self.envelope, **kw)

    def record(self, **over):
        kw = dict(root=self.root, manifest=self.manifest,
                  signed=self.envelope, signing_key=KEY,
                  ledger=self.ledger, coders=CODERS,
                  reviewers=REVIEWERS, delta=DELTA,
                  expected_attestation=self.satt,
                  expected_ledger_head=self.ledger.head())
        kw.update(over)
        loop = kw.pop("loop", self.loop)
        if "release" not in kw:
            import hashlib
            if not loop.state_path.exists():
                loop.scan([])  # materialise the initial state file
            kw["release"] = build_release_record(
                self.manifest, self.envelope,
                expected_cycle_id=loop.state["cycle_seq"] + 1,
                pre_ship_cycle_seq=loop.state["cycle_seq"],
                pre_ship_state_sha256=hashlib.sha256(
                    loop.state_path.read_bytes()).hexdigest())
        return record_ship(loop, **kw)


class CheckShipTests(ShipFixture):
    def test_happy_path_is_clean(self):
        self.assertEqual(self.check(), ())

    def test_tampered_tree_after_decision_refused(self):
        (self.root / "core" / "a.py").write_text("A = 2\n")
        reasons = self.check()
        self.assertIn("changed:core/a.py", reasons)

    def test_self_consistent_tampered_manifest_refused(self):
        (self.root / "core" / "a.py").write_text("A = 2\n")
        rebuilt = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        reasons = check_ship(self.root, rebuilt, self.envelope,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("gate_inputs_mismatch", reasons)
        self.assertIn("note_binding_mismatch", reasons)

    def test_wrong_purpose_refused(self):
        env = self._envelope(purpose="memory-commit",
                             signed_attestation=None)
        reasons = check_ship(self.root, self.manifest, env,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("purpose_mismatch", reasons)

    def test_rejected_decision_refused(self):
        decision = GateDecision(
            accepted=False, proposal_id=PROPOSAL,
            reasons=("regression",), regressions=(),
            forgetting_failures=(), verifier_id="seat-3",
            evaluated_at=NOW, protected_violations=(),
            verifier_note=f"content-hash:{self.manifest.manifest_hash}")
        env = sign_gate_decision(
            decision, signing_key=KEY, signer_id="verifier-svc",
            attestation=self.att, signed_attestation=self.satt,
            gate_inputs_hash=self.manifest.manifest_hash,
            purpose=PURPOSE_SHIP, now=NOW)
        reasons = check_ship(self.root, self.manifest, env,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("decision_not_accepted", reasons)

    def test_note_binding_mismatch_refused(self):
        decision = GateDecision(
            accepted=True, proposal_id=PROPOSAL, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=NOW,
            protected_violations=(),
            verifier_note="content-hash:" + "0" * 64)
        env = sign_gate_decision(
            decision, signing_key=KEY, signer_id="verifier-svc",
            attestation=self.att, signed_attestation=self.satt,
            gate_inputs_hash=self.manifest.manifest_hash,
            purpose=PURPOSE_SHIP, now=NOW)
        reasons = check_ship(self.root, self.manifest, env,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("note_binding_mismatch", reasons)

    def test_expired_envelope_refused(self):
        reasons = self.check(now=_ts(16))
        self.assertIn("expired", reasons)

    def test_other_proposal_refused(self):
        other = build_manifest(
            self.root, proposal_id="prop-other", item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        reasons = check_ship(self.root, other, self.envelope,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("proposal_mismatch", reasons)

    def test_review_record_edit_refused(self):
        (self.root / "internal" / "REVIEW.md").write_text("# edited\n")
        self.assertIn("review_record_mismatch", self.check())

    def test_provisional_stage_refused(self):
        prov = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md",
            stage="provisional", created_at=NOW)
        env = sign_gate_decision(
            GateDecision(
                accepted=True, proposal_id=PROPOSAL, reasons=(),
                regressions=(), forgetting_failures=(),
                verifier_id="seat-3", evaluated_at=NOW,
                protected_violations=(),
                verifier_note=f"content-hash:{prov.manifest_hash}"),
            signing_key=KEY, signer_id="verifier-svc",
            attestation=self.att, gate_inputs_hash=prov.manifest_hash,
            purpose=PURPOSE_SHIP, now=NOW)
        reasons = check_ship(self.root, prov, env, signing_key=KEY,
                             now=NOW)
        self.assertIn("stage_not_final", reasons)

    def test_unattested_envelope_refused(self):
        decision = GateDecision(
            accepted=True, proposal_id=PROPOSAL, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=NOW,
            protected_violations=(),
            verifier_note=f"content-hash:{self.manifest.manifest_hash}")
        env = sign_gate_decision(
            decision, signing_key=KEY, signer_id="verifier-svc",
            gate_inputs_hash=self.manifest.manifest_hash,
            purpose=PURPOSE_SHIP, now=NOW)
        reasons = check_ship(self.root, self.manifest, env,
                             signing_key=KEY, now=NOW)
        self.assertIn("attestation_missing", reasons)

    def test_bound_but_unpresented_attestation_refused(self):
        reasons = check_ship(self.root, self.manifest, self.envelope,
                             signing_key=KEY, ledger=self.ledger,
                             now=NOW)
        self.assertIn("attestation_unverifiable", reasons)


class RecordShipTests(ShipFixture):
    def test_record_ship_end_to_end(self):
        entry = self.record()
        self.assertEqual(entry["item_id"], ITEM)
        self.assertEqual(entry["cycle_id"], 1)
        kinds = [e["kind"] for e in self.ledger.entries()]
        self.assertEqual(kinds, ["burn", "finalise"])

    def test_replay_same_envelope_refused(self):
        self.record()
        with self.assertRaises(ShipRefused) as ctx:
            self.record()
        self.assertIn("decision_already_consumed", ctx.exception.reasons)

    def test_replay_after_state_rollback_refused(self):
        self.record()
        rolled_back = CoreLoop(Path(self.tmp.name) / "loop-state-2")
        rolled_back.scan([{"id": ITEM, "title": "fixture ship item",
                           "leverage": 5.0}])
        with self.assertRaises(ShipRefused):
            self.record(loop=rolled_back)

    def test_resigned_same_artifact_refused(self):
        self.record()
        fresh = self._envelope(now=_ts(1))
        self.assertNotEqual(fresh.decision_id,
                            self.envelope.decision_id)
        with self.assertRaises(ShipRefused):
            self.record(signed=fresh)

    def test_burn_is_spent_when_loop_refuses(self):
        bad_delta = dict(DELTA, verifier="seat-1")  # a builder
        with self.assertRaises(ShipRefused) as ctx:
            self.record(delta=bad_delta)
        self.assertIn("spent", str(ctx.exception))
        # The decision cannot be reused even with a fixed delta.
        with self.assertRaises(ShipRefused):
            self.record()

    def test_tampered_tree_records_nothing(self):
        (self.root / "core" / "a.py").write_text("A = 2\n")
        with self.assertRaises(ShipRefused):
            self.record()
        self.assertEqual(self.loop.state["history"], [])
        self.assertEqual(self.ledger.entries(), [])


class LedgerTests(ShipFixture):
    def test_burn_finalise_rules(self):
        ledger = ShipLedger(Path(self.tmp.name) / "home-2")
        ledger.burn(decision_id="d-1", proposal_id="p",
                    manifest_hash="a" * 64, payload_hash="b" * 64,
                    recorded_at=NOW)
        with self.assertRaises(LedgerError):
            ledger.burn(decision_id="d-1", proposal_id="p",
                        manifest_hash="a" * 64, payload_hash="b" * 64,
                        recorded_at=NOW)
        with self.assertRaises(LedgerError):
            ledger.burn(decision_id="d-2", proposal_id="p",
                        manifest_hash="a" * 64, payload_hash="c" * 64,
                        recorded_at=NOW)
        with self.assertRaises(LedgerError):
            ledger.finalise(decision_id="d-9", cycle_id="cycle-1",
                            recorded_at=NOW)
        ledger.finalise(decision_id="d-1", cycle_id="cycle-1",
                        recorded_at=NOW)
        with self.assertRaises(LedgerError):
            ledger.finalise(decision_id="d-1", cycle_id="cycle-1",
                            recorded_at=NOW)

    def test_ledger_tamper_detected_on_load(self):
        self.ledger.burn(decision_id="d-1", proposal_id="p",
                         manifest_hash="a" * 64,
                         payload_hash="b" * 64, recorded_at=NOW)
        path = self.home / "ship-ledger.json"
        data = json.loads(path.read_text())
        data["entries"][0]["proposal_id"] = "forged"
        path.write_text(json.dumps(data))
        with self.assertRaises(CorruptLedgerError):
            ShipLedger(self.home)

    def test_signing_ledger_records_envelopes(self):
        home = Path(self.tmp.name) / "home-3"
        ledger = SigningLedger(home)
        ledger.append_envelope(self.envelope, recorded_at=NOW)
        self.assertTrue(ledger.has_envelope(self.envelope.decision_id))
        self.assertFalse(ledger.has_envelope("d-nope"))
        reloaded = SigningLedger(home)
        self.assertTrue(reloaded.has_envelope(
            self.envelope.decision_id))


class RecordWithReleaseTests(ShipFixture):
    def _release(self, **over):
        import hashlib
        kw = dict(expected_cycle_id=1, pre_ship_cycle_seq=0,
                  pre_ship_state_sha256=hashlib.sha256(
                      self.loop.state_path.read_bytes()).hexdigest())
        kw.update(over)
        return build_release_record(self.manifest, self.envelope, **kw)

    def test_record_with_release_end_to_end(self):
        release = self._release()
        entry = self.record(release=release)
        self.assertEqual(entry["cycle_id"], 1)
        done = release.completed(cycle_id=1, completed_at=NOW)
        self.assertEqual(done.status, "recorded")
        self.assertEqual(done.cycle_id, 1)
        self.assertEqual(release_from_json(done.to_json()), done)

    def test_release_state_drift_refuses_before_burn(self):
        release = self._release(pre_ship_cycle_seq=999)
        with self.assertRaises(ShipRefused) as ctx:
            self.record(release=release)
        self.assertIn("nothing was burned", str(ctx.exception))
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.loop.state["history"], [])

    def test_wrong_item_refuses_before_burn(self):
        self.loop.scan([{"id": "other-item", "title": "other",
                         "leverage": 99.0}])
        with self.assertRaises(ShipRefused) as ctx:
            self.record()
        self.assertIn("nothing was burned", str(ctx.exception))
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(self.loop.state["history"], [])

    def test_record_without_release_refused(self):
        with self.assertRaises(ShipRefused):
            record_ship(self.loop, root=self.root,
                        manifest=self.manifest, signed=self.envelope,
                        signing_key=KEY, ledger=self.ledger,
                        coders=CODERS, reviewers=REVIEWERS,
                        delta=DELTA, expected_attestation=self.satt,
                        expected_ledger_head=self.ledger.head())
        self.assertEqual(self.ledger.entries(), [])

    def test_idle_loop_refuses_before_burn(self):
        idle = CoreLoop(Path(self.tmp.name) / "idle-state")
        with self.assertRaises(ShipRefused):
            self.record(loop=idle)
        self.assertEqual(self.ledger.entries(), [])

    def test_forged_release_fields_refused(self):
        import dataclasses
        release = self._release()
        forged = dataclasses.replace(
            release, proposal_id="prop-other", payload_hash="0" * 64)
        reasons = check_ship(self.root, self.manifest, self.envelope,
                             signing_key=KEY, release=forged,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("release_proposal_mismatch", reasons)
        self.assertIn("release_payload_mismatch", reasons)
        recorded = release.completed(cycle_id=1, completed_at=NOW)
        reasons = check_ship(self.root, self.manifest, self.envelope,
                             signing_key=KEY, release=recorded,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("release_not_prepared", reasons)

    def test_ledger_head_pin(self):
        head = self.ledger.head()
        reasons = self.check(expected_ledger_head="f" * 64)
        self.assertIn("ledger_head_mismatch", reasons)
        self.assertEqual(self.check(expected_ledger_head=head), ())

    def test_malformed_attestation_reasons_not_raise(self):
        import dataclasses
        broken = dataclasses.replace(self.satt,
                                     expires_at="not-a-time")
        reasons = check_ship(self.root, self.manifest, self.envelope,
                             signing_key=KEY, ledger=self.ledger,
                             expected_attestation=broken, now=NOW)
        self.assertIn("attestation_malformed_payload", reasons)


class ReleaseRecordTests(ShipFixture):
    def test_release_roundtrip_and_binding(self):
        release = build_release_record(
            self.manifest, self.envelope, expected_cycle_id=1,
            pre_ship_cycle_seq=0,
            pre_ship_state_sha256="f" * 64)
        clone = release_from_json(release.to_json())
        self.assertEqual(clone, release)
        self.assertEqual(
            check_ship(self.root, self.manifest, self.envelope,
                       signing_key=KEY, release=release,
                       expected_attestation=self.satt, now=NOW),
            ())

    def test_release_for_other_manifest_refused(self):
        other = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at="2026-11-20T00:01:00+00:00")
        # Same tree -> same manifest hash; use a tampered tree for a
        # genuinely different manifest instead.
        (self.root / "core" / "a.py").write_text("A = 2\n")
        different = build_manifest(
            self.root, proposal_id=PROPOSAL, item_id=ITEM,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=NOW)
        self.assertNotEqual(different.manifest_hash,
                            self.manifest.manifest_hash)
        release = build_release_record(
            different, None, expected_cycle_id=1,
            pre_ship_cycle_seq=0, pre_ship_state_sha256="f" * 64)
        reasons = check_ship(self.root, self.manifest, self.envelope,
                             signing_key=KEY, release=release,
                             expected_attestation=self.satt, now=NOW)
        self.assertIn("release_manifest_mismatch", reasons)
        self.assertIsNotNone(other)


if __name__ == "__main__":
    unittest.main()
