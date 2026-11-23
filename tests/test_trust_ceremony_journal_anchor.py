"""Anchored consumption-journal tests (cycle 22, WS2 / R2):
the ceremony consumption journal carries its own external
anchor (kind "ceremony-consumption",
AION_CEREMONY_CONSUMPTION_ANCHOR_PATH), verified at startup
on every verifier invocation, and advanced in the consume
commit order BEFORE the signing-ledger mirror write:

    (1) consumption-journal append (commit point);
    (2) consumption-anchor update;
    (3) signing-ledger mirror;
    (4) signing-anchor update.

The mandatory adversarial test (DESIGN-FINAL R2, adapted
from design B's T-WS2-1): authorise E; snapshot the verifier
home; consume E with the MIRROR patched to fail (journal
append + consumption-anchor update land, mirror raises) =>
ledger_failed; roll the home back (anchors untouched);
replay E via a fresh client => REFUSED with anchor_refused
at startup, and no journal gained an entry.

Characterisation tests pin the claim boundaries honestly:
the append->anchor window (a rollback inside it resurrects
the envelope — replay SUCCEEDS) and research mode with no
anchor configured (no rollback claim — replay succeeds).
A future closure of either window must flip those tests
deliberately.

Fixture follows design B section 6's notes: research mode
with AION_ANCHOR_PATH (signing) AND
AION_CEREMONY_CONSUMPTION_ANCHOR_PATH both OUTSIDE the
verifier home; the anchors are bootstrapped with a one-off
INIT request, then INIT is removed for the steady state.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from trust import protocol
from trust.budgets import GENESIS_CHAIN_HASH
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import (
    CeremonyConsumptionLedger,
    SigningLedger,
)

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-uma"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
ARTIFACT = b"ceremony evidence bundle: anchor case file\n"
EVIDENCE_HASH = hashlib.sha256(ARTIFACT).hexdigest()
REPO = Path(__file__).resolve().parents[1]

MIRROR_FAIL_MODULE = '''
import sys

import trust.verifier_main as vm


def _boom(self, signed, *, recorded_at):
    raise RuntimeError("mirror unavailable")


vm.SigningLedger.append_ceremony_consumption = _boom
sys.exit(vm.main())
'''

ANCHOR_FAIL_MODULE = '''
import sys

import trust.verifier_main as vm

_orig_update = vm.update_anchor


def _boom(journal, anchor_path, *, kind, recorded_at):
    if kind == "ceremony-consumption":
        raise vm.AnchorError("consumption anchor unavailable")
    return _orig_update(journal, anchor_path, kind=kind,
                        recorded_at=recorded_at)


vm.update_anchor = _boom
sys.exit(vm.main())
'''

# Journal append lands; the consumption-anchor update is
# SKIPPED (a no-op standing in for death/failure inside the
# append->anchor window) and the mirror then fails, so the
# consume returns ledger_failed with the anchor still at the
# pre-burn prefix — the exact append->anchor window state.
WINDOW_MODULE = '''
import sys

import trust.verifier_main as vm


def _skip(config):
    return None


def _boom(self, signed, *, recorded_at):
    raise RuntimeError("mirror unavailable")


vm._update_ceremony_consumption_anchor = _skip
vm.SigningLedger.append_ceremony_consumption = _boom
sys.exit(vm.main())
'''


class AnchoredFixture(unittest.TestCase):
    anchored = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        (self.evidence_dir / "case-file-1").write_bytes(ARTIFACT)
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.ledger_home = self.home / "ledger"
        self.anchors_dir = base / "anchors"
        self.anchors_dir.mkdir()
        self.signing_anchor = self.anchors_dir / "signing.anchor.json"
        self.consumption_anchor = (
            self.anchors_dir / "ceremony-consumption.anchor.json")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.ledger_home),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATOR,
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        if self.anchored:
            self.env["AION_ANCHOR_PATH"] = str(self.signing_anchor)
            self.env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = \
                str(self.consumption_anchor)
        self.client = self._fresh_client()

    def tearDown(self):
        self.tmp.cleanup()

    def _fresh_client(self, env=None):
        return VerifierClient(
            verifier_env=env or self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)

    def full_env(self, env_over=None):
        env = dict(self.env)
        if env_over:
            env.update(env_over)
        full = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full.update(env)
        return full

    def raw(self, body, *, env_over=None, mode="ceremony_consume"):
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=self.full_env(env_over))
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc

    def error_code(self, doc):
        return doc["error"]["code"] if doc and doc.get("error") \
            else None

    def bootstrap_anchors(self):
        """One INIT-flagged authorise request creates both
        anchors (empty ledgers), modelling the bootstrap
        ceremony; steady state afterwards carries no INIT."""
        code, doc = self.raw(
            {"operator_id": OPERATOR,
             "ceremony_id": "ceremony-bootstrap",
             "reason": "chain_gap_recovery",
             "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
             "candidate": {"cycle_seq": 47, "payload_hash": CAND_HASH,
                           "signer_id": "snapshot-svc",
                           "key_id": "key-0123456789abcdef"},
             "evidence_hash": EVIDENCE_HASH,
             "evidence_ref": "case-file-1"},
            mode="ceremony_authorise",
            env_over={"AION_ANCHOR_INIT": "1",
                      "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT": "1"})
        self.assertEqual(code, 0, msg=str(doc))
        self.assertTrue(self.signing_anchor.exists())
        self.assertTrue(self.consumption_anchor.exists())
        return doc["result"]["signed_authorisation"]

    def authorise(self, ceremony_id="ceremony-anchor-1"):
        return self.client.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id=ceremony_id,
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate={"cycle_seq": 47, "payload_hash": CAND_HASH,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH, evidence_ref="case-file-1")

    def snapshot_home(self):
        snapshot = self.base / "home-snapshot"
        shutil.copytree(self.ledger_home, snapshot)
        return snapshot

    def restore_home(self, snapshot):
        shutil.rmtree(self.ledger_home)
        shutil.copytree(snapshot, self.ledger_home)

    def consumption_entries(self):
        if not (self.ledger_home
                / "ceremony-consumptions.json").exists():
            return []
        return CeremonyConsumptionLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()

    def run_wrapper(self, name, source, envelope):
        wrapper_dir = self.base / "wrapper"
        wrapper_dir.mkdir(exist_ok=True)
        wrapper = wrapper_dir / f"{name}.py"
        wrapper.write_text(source)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "ceremony_consume",
            {"signed_authorisation": envelope})
        result = subprocess.run(
            [sys.executable, str(wrapper)], input=raw,
            capture_output=True, timeout=30, cwd=str(REPO),
            env=self.full_env())
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc


class MandatoryRollbackTests(AnchoredFixture):

    def test_mandatory_mirror_failure_then_rollback_refused(self):
        # THE mandatory adversarial test (R2): mirror failure
        # after the journal append + consumption-anchor update,
        # then a verifier-home rollback, must NOT resurrect
        # the envelope: the replay is refused at startup with
        # anchor_refused and no journal gains an entry.
        envelope = self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        signing_before = len(self.signing_entries())
        code, doc = self.run_wrapper(
            "mirror_fail", MIRROR_FAIL_MODULE, envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        # The burn stands in the journal and its anchor
        # advanced past it; the mirror never landed.
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(
            [e for e in self.signing_entries()
             if e["kind"] == "consume"], [])
        self.restore_home(snapshot)
        fresh = self._fresh_client()
        with self.assertRaises(VerifierConfigError) as cm:
            fresh.ceremony_consume(envelope)
        self.assertIn("anchor_refused", str(cm.exception))
        # No journal gained an entry from the refused replay.
        self.assertEqual(self.consumption_entries(), [])
        self.assertEqual(len(self.signing_entries()), signing_before)

    def test_clean_consume_rollback_refused(self):
        envelope = self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        result = self.client.ceremony_consume(envelope)
        self.assertEqual(result["consumption_seq"], 1)
        self.restore_home(snapshot)
        fresh = self._fresh_client()
        with self.assertRaises(VerifierConfigError) as cm:
            fresh.ceremony_consume(envelope)
        self.assertIn("anchor_refused", str(cm.exception))
        self.assertEqual(self.consumption_entries(), [])

    def test_consumption_journal_only_rollback_refused(self):
        # Only the consumption journal is restored from the
        # pre-consume snapshot; the signing ledger keeps the
        # mirror entry. The consumption anchor is still ahead
        # of the rolled-back journal, so startup refuses.
        envelope = self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        self.client.ceremony_consume(envelope)
        shutil.copyfile(
            snapshot / "ceremony-consumptions.json",
            self.ledger_home / "ceremony-consumptions.json") \
            if (snapshot / "ceremony-consumptions.json").exists() \
            else (self.ledger_home
                  / "ceremony-consumptions.json").unlink()
        self.assertEqual(self.consumption_entries(), [])
        self.assertEqual(
            len([e for e in self.signing_entries()
                 if e["kind"] == "consume"]), 1)
        fresh = self._fresh_client()
        with self.assertRaises(VerifierConfigError) as cm:
            fresh.ceremony_consume(envelope)
        self.assertIn("anchor_refused", str(cm.exception))

    def test_anchor_update_failure_burns_and_intact_replay_refused(self):
        # Consumption-anchor update patched to raise: the burn
        # stands in the journal, the consume returns
        # ledger_failed, and a replay on the INTACT home
        # refuses ceremony_already_consumed.
        envelope = self.bootstrap_anchors()
        code, doc = self.run_wrapper(
            "anchor_fail", ANCHOR_FAIL_MODULE, envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertEqual(len(self.consumption_entries()), 1)
        fresh = self._fresh_client()
        with self.assertRaises(VerifierConfigError) as cm:
            fresh.ceremony_consume(envelope)
        self.assertIn("ceremony_already_consumed", str(cm.exception))

    def test_append_anchor_window_rollback_replay_succeeds(self):
        # CHARACTERISATION — pins the claim boundary (R2): a
        # burn whose journal append landed but whose anchor
        # update did NOT complete is NOT protected against a
        # full verifier-home rollback inside that window (the
        # same append->anchor window every anchored append in
        # this system carries). After rollback, journal and
        # anchor agree on the pre-burn history and the replay
        # SUCCEEDS. A future closure must flip this test
        # deliberately.
        envelope = self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        code, doc = self.run_wrapper(
            "window", WINDOW_MODULE, envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertEqual(len(self.consumption_entries()), 1)
        self.restore_home(snapshot)
        fresh = self._fresh_client()
        result = fresh.ceremony_consume(envelope)
        self.assertEqual(result["consumption_seq"], 1)
        self.assertEqual(len(self.consumption_entries()), 1)


class ResearchModeNoAnchorTests(AnchoredFixture):
    anchored = False

    def test_research_no_anchor_rollback_replay_succeeds(self):
        # CHARACTERISATION — pins the no-claim boundary: with
        # no anchors configured (research mode), a consume
        # followed by a full home rollback is undetectable
        # and the replay succeeds. No rollback claim is made
        # for this configuration.
        envelope = self.authorise()
        snapshot = self.snapshot_home()
        self.client.ceremony_consume(envelope)
        self.assertEqual(len(self.consumption_entries()), 1)
        self.restore_home(snapshot)
        fresh = self._fresh_client()
        result = fresh.ceremony_consume(envelope)
        self.assertEqual(result["consumption_seq"], 1)


class ConsumptionAnchorStartupTests(AnchoredFixture):

    def _production_env(self):
        """A production env over this fixture: signing anchor
        bootstrapped, budgets anchor at genesis, ceremony
        configured — the full production gate except what each
        test varies."""
        anchors = self.base / "prod-anchors"
        anchors.mkdir(exist_ok=True)
        signing_anchor = anchors / "signing.anchor.json"
        from trust.anchoring import initialise_anchor
        initialise_anchor(
            SigningLedger(self.ledger_home), signing_anchor,
            kind="signing",
            recorded_at="2026-11-20T12:00:00+00:00")
        budgets_anchor = anchors / "budgets.anchor.json"
        budgets_anchor.write_text(json.dumps(
            {"v": "budgets-anchor/1", "head": GENESIS_CHAIN_HASH,
             "anchored_at": "2026-11-20T12:00:00+00:00"},
            sort_keys=True), encoding="utf-8")
        env = dict(self.env)
        env["AION_DEPLOYMENT_MODE"] = "production"
        env["AION_ANCHOR_PATH"] = str(signing_anchor)
        env["AION_BUDGETS_ANCHOR_PATH"] = str(budgets_anchor)
        return env, anchors

    def _sealed_eval(self, env):
        full = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full.update(env)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval", {"answers": ["4", "9"]})
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=full)
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc

    def test_production_ceremony_without_consumption_anchor_refused(self):
        env, _anchors = self._production_env()
        del env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"]
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_production_consumption_anchor_init_refused(self):
        env, anchors = self._production_env()
        env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = str(
            anchors / "ceremony-consumption.anchor.json")
        env["AION_CEREMONY_CONSUMPTION_ANCHOR_INIT"] = "1"
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_consumption_anchor_inside_home_refused(self):
        code, doc = self.raw(
            {"signed_authorisation": {}},
            env_over={
                "AION_ANCHOR_PATH": str(self.signing_anchor),
                "AION_ANCHOR_INIT": "1",
                "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH": str(
                    self.ledger_home / "consumption.anchor.json"),
            })
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_consumption_anchor_duplicate_of_signing_refused(self):
        code, doc = self.raw(
            {"signed_authorisation": {}},
            env_over={
                "AION_ANCHOR_PATH": str(self.signing_anchor),
                "AION_ANCHOR_INIT": "1",
                "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH": str(
                    self.signing_anchor),
            })
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")


if __name__ == "__main__":
    unittest.main()
