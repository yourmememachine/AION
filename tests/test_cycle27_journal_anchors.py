"""Anchored ceremony-journal tests (cycle 27): the two
remaining unanchored ceremony journals gain external anchors,
mirroring the consumption anchoring of cycle 22:

* the issuance journal (ceremony-authorisations.json), kind
  "ceremony-issuance",
  AION_CEREMONY_ISSUANCE_ANCHOR_PATH /
  AION_CEREMONY_ISSUANCE_ANCHOR_INIT;
* the supersession journal (ceremony-supersessions.json),
  kind "ceremony-supersession",
  AION_CEREMONY_SUPERSESSION_ANCHOR_PATH /
  AION_CEREMONY_SUPERSESSION_ANCHOR_INIT.

Both anchors are verified at startup on every verifier
invocation. INIT may pin only when the verification reasons
are exactly ("anchor_missing",). In production mode with the
ceremony seed configured, both paths are required and INIT
is refused. Each anchor path must be absolute, must live
outside the verifier home, and must be distinct from every
other anchor path.

Commit orders pinned here:

    ceremony_authorise: (1) issuance-journal append (commit
    point); (2) issuance-anchor update; (3) signing-ledger
    mirror; (4) signing-anchor update. A failed step (2) is
    ledger_failed and the envelope is withheld — the pair
    stays burned.

    ceremony_supersede: (1) supersession-journal
    append_decision (commit point); (2) supersession-anchor
    update; (3) signing-ledger mirror; (4) signing-anchor
    update. A failed step (2) is ledger_failed; the decision
    stands and no receipt is returned.

The supersession rollback test is driven at the
_load_config level (see SupersessionAnchorRollbackTests):
a decision is appended through the supersession ledger's
own API, its anchor is initialised and advanced, the
journal file alone is rolled back to its pre-decision
prefix, and a verifier invocation must then refuse at
startup. The full supersede commit order is covered
separately by SupersessionAnchorCommitTests.

Fixture follows the cycle-22 anchored fixture: research
mode with the signing, consumption, issuance and
supersession anchors all OUTSIDE the verifier home,
bootstrapped with a one-off INIT request, then INIT is
removed for the steady state.
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
    _make_ceremony_signing_key,
    ceremony_authorisation_envelope_from_dict,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    sign_ceremony_authorisation,
)
from trust import protocol
from trust.anchoring import initialise_anchor, load_anchor, update_anchor
from trust.budgets import GENESIS_CHAIN_HASH
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import (
    CeremonyAuthorisationLedger,
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
    SigningLedger,
)
from trust.supersession_approval import supersession_approval_to_dict
from trust.supersession_approval_tool import (
    _make_approver_key,
    approver_public_key_for as _approver_pin_for,
    sign_supersession_approval,
)

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-uma"
APPROVER_ID = "approver-1"
APPROVER_KEY = _make_approver_key(
    hashlib.sha256(b"cycle27 supersede approver seed").digest())
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
NOW = "2026-11-20T12:00:00+00:00"
ARTIFACT = b"ceremony evidence bundle: anchor case file 1\n"
EVIDENCE_HASH = hashlib.sha256(ARTIFACT).hexdigest()
ARTIFACT2 = b"ceremony evidence bundle: anchor case file 2\n"
EVIDENCE_HASH2 = hashlib.sha256(ARTIFACT2).hexdigest()
ARTIFACT3 = b"ceremony evidence bundle: anchor case file 3\n"
EVIDENCE_HASH3 = hashlib.sha256(ARTIFACT3).hexdigest()
REPO = Path(__file__).resolve().parents[1]

ISSUANCE_ANCHOR_FAIL_MODULE = '''
import sys

import trust.verifier_main as vm

_orig_update = vm.update_anchor


def _boom(journal, anchor_path, *, kind, recorded_at):
    if kind == "ceremony-issuance":
        raise vm.AnchorError("issuance anchor unavailable")
    return _orig_update(journal, anchor_path, kind=kind,
                        recorded_at=recorded_at)


vm.update_anchor = _boom
sys.exit(vm.main())
'''

SUPERSESSION_ANCHOR_FAIL_MODULE = '''
import sys

import trust.verifier_main as vm

_orig_update = vm.update_anchor


def _boom(journal, anchor_path, *, kind, recorded_at):
    if kind == "ceremony-supersession":
        raise vm.AnchorError("supersession anchor unavailable")
    return _orig_update(journal, anchor_path, kind=kind,
                        recorded_at=recorded_at)


vm.update_anchor = _boom
sys.exit(vm.main())
'''


# -- direct-minted envelopes (supersession ledger-level test) -------------

_MINT_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle27 supersession mint seed").digest())
_mint_counter = [0]


def _mint(reason="chain_gap_recovery", **over):
    _mint_counter[0] += 1
    kwargs = dict(
        signing_key=_MINT_KEY, signer_id="verifier-svc",
        operator_id="operator-1",
        ceremony_id=f"ceremony-c27-{_mint_counter[0]}",
        reason=reason,
        old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
        candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                   "signer_id": "snapshot-svc",
                   "key_id": "key-0123456789abcdef"},
        evidence_hash="e" * 64, evidence_ref="evidence-bundle-1",
        now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


class Cycle27Fixture(unittest.TestCase):
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
        (self.evidence_dir / "case-file-2").write_bytes(ARTIFACT2)
        (self.evidence_dir / "case-file-3").write_bytes(ARTIFACT3)
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
        self.issuance_anchor = (
            self.anchors_dir / "ceremony-issuance.anchor.json")
        self.supersession_anchor = (
            self.anchors_dir / "ceremony-supersession.anchor.json")
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
            "AION_SUPERSESSION_APPROVER_PUBLIC_KEY":
                _approver_pin_for(APPROVER_KEY).public_key.hex(),
        }
        if self.anchored:
            self.env["AION_ANCHOR_PATH"] = str(self.signing_anchor)
            self.env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = \
                str(self.consumption_anchor)
            self.env["AION_CEREMONY_ISSUANCE_ANCHOR_PATH"] = \
                str(self.issuance_anchor)
            self.env["AION_CEREMONY_SUPERSESSION_ANCHOR_PATH"] = \
                str(self.supersession_anchor)
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

    def authorise_body(self, ceremony_id="ceremony-anchor-1",
                       evidence_hash=EVIDENCE_HASH2,
                       evidence_ref="case-file-2", **over):
        body = {
            "operator_id": OPERATOR,
            "ceremony_id": ceremony_id,
            "reason": "chain_gap_recovery",
            "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
            "candidate": {"cycle_seq": 47, "payload_hash": CAND_HASH,
                          "signer_id": "snapshot-svc",
                          "key_id": "key-0123456789abcdef"},
            "evidence_hash": evidence_hash,
            "evidence_ref": evidence_ref,
        }
        body.update(over)
        return body

    def raw(self, body, *, env_over=None, mode="ceremony_authorise"):
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
        """One INIT-flagged authorise request creates every
        anchor (empty ledgers), modelling the bootstrap
        ceremony; steady state afterwards carries no INIT."""
        code, doc = self.raw(
            self.authorise_body(
                ceremony_id="ceremony-bootstrap",
                evidence_hash=EVIDENCE_HASH,
                evidence_ref="case-file-1"),
            mode="ceremony_authorise",
            env_over={"AION_ANCHOR_INIT": "1",
                      "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT": "1",
                      "AION_CEREMONY_ISSUANCE_ANCHOR_INIT": "1",
                      "AION_CEREMONY_SUPERSESSION_ANCHOR_INIT": "1"})
        self.assertEqual(code, 0, msg=str(doc))
        self.assertTrue(self.signing_anchor.exists())
        self.assertTrue(self.consumption_anchor.exists())
        self.assertTrue(self.issuance_anchor.exists())
        self.assertTrue(self.supersession_anchor.exists())
        return doc["result"]["signed_authorisation"]

    def authorise(self, ceremony_id="ceremony-anchor-1",
                  evidence_hash=EVIDENCE_HASH2,
                  evidence_ref="case-file-2", **over):
        body = self.authorise_body(
            ceremony_id=ceremony_id, evidence_hash=evidence_hash,
            evidence_ref=evidence_ref, **over)
        return self.client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])

    def snapshot_home(self):
        snapshot = self.base / "home-snapshot"
        shutil.copytree(self.ledger_home, snapshot)
        return snapshot

    def restore_home(self, snapshot):
        shutil.rmtree(self.ledger_home)
        shutil.copytree(snapshot, self.ledger_home)

    def issuance_entries(self):
        if not (self.ledger_home
                / "ceremony-authorisations.json").exists():
            return []
        return CeremonyAuthorisationLedger(self.ledger_home).entries()

    def consumption_entries(self):
        if not (self.ledger_home
                / "ceremony-consumptions.json").exists():
            return []
        return CeremonyConsumptionLedger(self.ledger_home).entries()

    def supersession_entries(self):
        if not (self.ledger_home
                / "ceremony-supersessions.json").exists():
            return []
        return CeremonySupersessionLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()

    def run_wrapper(self, name, source, mode, body):
        wrapper_dir = self.base / "wrapper"
        wrapper_dir.mkdir(exist_ok=True)
        wrapper = wrapper_dir / f"{name}.py"
        wrapper.write_text(source)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
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

    def assert_client_refused(self, fn, code):
        with self.assertRaises(VerifierConfigError) as cm:
            fn()
        self.assertEqual(
            getattr(cm.exception, "verifier_code", None), code,
            msg=str(cm.exception))


class IssuanceRollbackReplayTests(Cycle27Fixture):

    def test_issuance_rollback_replay_refused_at_startup(self):
        # Authorise E with the issuance anchor configured;
        # roll the verifier home back to the pre-E snapshot
        # (anchors untouched); re-authorising the same
        # evidence under a NEW ceremony_id via a fresh client
        # is refused at startup with anchor_refused, and the
        # issuance journal gains no entry.
        self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        before = len(self.issuance_entries())
        self.authorise()
        self.assertEqual(len(self.issuance_entries()), before + 1)
        self.restore_home(snapshot)
        fresh = self._fresh_client()
        self.assert_client_refused(
            lambda: fresh.ceremony_authorise(
                operator_id=OPERATOR,
                ceremony_id="ceremony-anchor-replay",
                reason="chain_gap_recovery",
                old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
                candidate={"cycle_seq": 47,
                           "payload_hash": CAND_HASH,
                           "signer_id": "snapshot-svc",
                           "key_id": "key-0123456789abcdef"},
                evidence_hash=EVIDENCE_HASH2,
                evidence_ref="case-file-2"),
            "anchor_refused")
        self.assertEqual(len(self.issuance_entries()), before)


class IssuanceAnchorUpdateFailureTests(Cycle27Fixture):

    def test_issuance_anchor_update_failure_burns_pair(self):
        # The issuance-anchor update is patched to raise: the
        # authorise returns ledger_failed and the envelope is
        # withheld, but the issuance journal HAS the entry
        # (the pair stays burned) and re-authorising the same
        # pair is refused as already spent. The signing-ledger
        # mirror must not have landed (the anchor update
        # precedes it in the commit order).
        self.bootstrap_anchors()
        before = len(self.issuance_entries())
        signing_before = len(self.signing_entries())
        code, doc = self.run_wrapper(
            "issuance_anchor_fail", ISSUANCE_ANCHOR_FAIL_MODULE,
            "ceremony_authorise", self.authorise_body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertNotIn("signed_authorisation",
                         (doc or {}).get("result") or {})
        self.assertEqual(len(self.issuance_entries()), before + 1)
        self.assertEqual(len(self.signing_entries()), signing_before)
        fresh = self._fresh_client()
        self.assert_client_refused(
            lambda: fresh.ceremony_authorise(
                operator_id=OPERATOR,
                ceremony_id="ceremony-anchor-1",
                reason="chain_gap_recovery",
                old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
                candidate={"cycle_seq": 47,
                           "payload_hash": CAND_HASH,
                           "signer_id": "snapshot-svc",
                           "key_id": "key-0123456789abcdef"},
                evidence_hash=EVIDENCE_HASH2,
                evidence_ref="case-file-2"),
            "ceremony_id_reused")


class IssuanceAnchorStartupTests(Cycle27Fixture):

    def test_issuance_anchor_missing_on_established_journal_refused(self):
        self.bootstrap_anchors()
        self.assertGreaterEqual(len(self.issuance_entries()), 1)
        self.issuance_anchor.unlink()
        code, doc = self.raw(self.authorise_body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")

    def test_issuance_anchor_init_bootstrap_on_empty_journal_succeeds(self):
        envelope = self.bootstrap_anchors()
        self.assertTrue(envelope)
        anchor = json.loads(
            self.issuance_anchor.read_text(encoding="utf-8"))
        self.assertEqual(anchor["kind"], "ceremony-issuance")
        self.assertEqual(anchor["seq"], len(self.issuance_entries()))
        self.assertGreaterEqual(anchor["seq"], 1)

    def test_issuance_anchor_inside_home_refused(self):
        # Bootstrap first, so every other anchor verifies and
        # the issuance placement check is the refusal reached.
        self.bootstrap_anchors()
        code, doc = self.raw(
            self.authorise_body(),
            env_over={
                "AION_CEREMONY_ISSUANCE_ANCHOR_PATH": str(
                    self.ledger_home / "issuance.anchor.json"),
            })
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_issuance_anchor_equal_to_consumption_refused(self):
        self.bootstrap_anchors()
        code, doc = self.raw(
            self.authorise_body(),
            env_over={
                "AION_CEREMONY_ISSUANCE_ANCHOR_PATH": str(
                    self.consumption_anchor),
            })
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")


class IssuanceProductionGateTests(Cycle27Fixture):

    def _production_env(self):
        """A production env over this fixture: signing and
        consumption anchors initialised at genesis, budgets
        anchor at genesis, ceremony configured — the full
        production gate except what each test varies."""
        anchors = self.base / "prod-anchors"
        anchors.mkdir(exist_ok=True)
        signing_anchor = anchors / "signing.anchor.json"
        initialise_anchor(
            SigningLedger(self.ledger_home), signing_anchor,
            kind="signing", recorded_at=NOW)
        initialise_anchor(
            CeremonyConsumptionLedger(self.ledger_home),
            anchors / "ceremony-consumption.anchor.json",
            kind="ceremony-consumption", recorded_at=NOW)
        initialise_anchor(
            CeremonyAuthorisationLedger(self.ledger_home),
            anchors / "ceremony-issuance.anchor.json",
            kind="ceremony-issuance", recorded_at=NOW)
        initialise_anchor(
            CeremonySupersessionLedger(self.ledger_home),
            anchors / "ceremony-supersession.anchor.json",
            kind="ceremony-supersession", recorded_at=NOW)
        budgets_anchor = anchors / "budgets.anchor.json"
        budgets_anchor.write_text(json.dumps(
            {"v": "budgets-anchor/1", "head": GENESIS_CHAIN_HASH,
             "anchored_at": NOW}, sort_keys=True), encoding="utf-8")
        env = dict(self.env)
        env["AION_DEPLOYMENT_MODE"] = "production"
        env["AION_ANCHOR_PATH"] = str(signing_anchor)
        env["AION_BUDGETS_ANCHOR_PATH"] = str(budgets_anchor)
        env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = str(
            anchors / "ceremony-consumption.anchor.json")
        env["AION_CEREMONY_ISSUANCE_ANCHOR_PATH"] = str(
            anchors / "ceremony-issuance.anchor.json")
        env["AION_CEREMONY_SUPERSESSION_ANCHOR_PATH"] = str(
            anchors / "ceremony-supersession.anchor.json")
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

    def test_production_without_issuance_anchor_refused(self):
        env, _anchors = self._production_env()
        del env["AION_CEREMONY_ISSUANCE_ANCHOR_PATH"]
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_production_issuance_anchor_init_refused(self):
        env, _anchors = self._production_env()
        env["AION_CEREMONY_ISSUANCE_ANCHOR_INIT"] = "1"
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")


class SupersessionAnchorRollbackTests(Cycle27Fixture):
    """Level used: the _load_config level, as documented in
    the module docstring — the decision is appended through
    CeremonySupersessionLedger.append_decision (the ledger
    API the supersede mode itself uses), the anchor is
    initialised on the empty journal and advanced over the
    decision, and only the journal file is then rolled back.
    """

    def test_supersession_journal_only_rollback_refused_at_startup(self):
        self.ledger_home.mkdir(parents=True, exist_ok=True)
        # Pin every other configured anchor on its empty
        # journal, so the supersession mismatch is the only
        # startup refusal available.
        initialise_anchor(
            SigningLedger(self.ledger_home), self.signing_anchor,
            kind="signing", recorded_at=NOW)
        initialise_anchor(
            CeremonyConsumptionLedger(self.ledger_home),
            self.consumption_anchor, kind="ceremony-consumption",
            recorded_at=NOW)
        initialise_anchor(
            CeremonyAuthorisationLedger(self.ledger_home),
            self.issuance_anchor, kind="ceremony-issuance",
            recorded_at=NOW)
        supersession = CeremonySupersessionLedger(self.ledger_home)
        initialise_anchor(
            supersession, self.supersession_anchor,
            kind="ceremony-supersession", recorded_at=NOW)
        journal_path = (
            self.ledger_home / "ceremony-supersessions.json")
        pre_decision = journal_path.read_bytes() \
            if journal_path.exists() else None
        # Land one decision through the ledger API.
        consumption = CeremonyConsumptionLedger(self.ledger_home)
        head_env = _mint()
        consumption.append_consumption(head_env, recorded_at=NOW)
        head_entry = consumption.entries()[-1]
        replacement = _mint(
            candidate={"cycle_seq": 52, "payload_hash": "c" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        supersession.append_decision(
            abandoned_entry=head_entry, signed=replacement,
            recorded_at=NOW)
        self.assertEqual(len(self.supersession_entries()), 1)
        update_anchor(
            supersession, self.supersession_anchor,
            kind="ceremony-supersession", recorded_at=NOW)
        # Roll back ONLY the supersession journal file to its
        # pre-decision prefix; the rest of the home (and the
        # consumption anchor) stays intact.
        if pre_decision is None:
            journal_path.unlink()
        else:
            journal_path.write_bytes(pre_decision)
        self.assertEqual(self.supersession_entries(), [])
        code, doc = self.raw(
            {"answers": ["4", "9"]}, mode="sealed_eval")
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")


class SupersessionAnchorCommitTests(Cycle27Fixture):

    def _approval_for(self, envelope):
        signed_env = ceremony_authorisation_envelope_from_dict(
            envelope)
        head = self.consumption_entries()[-1]
        abandoned = {
            "authorisation_id": head["authorisation_id"],
            "ceremony_id": head["ceremony_id"],
            "old_cycle_seq": head["old_cycle_seq"],
            "old_payload_hash": head["old_payload_hash"],
            "new_cycle_seq": head["new_cycle_seq"],
            "new_payload_hash": head["new_payload_hash"]}
        replacement = {
            "authorisation_id": signed_env.authorisation_id,
            "ceremony_id": signed_env.ceremony_id,
            "reason": signed_env.reason,
            "operator_id": signed_env.operator_id,
            "superseding_old_cycle_seq":
                signed_env.old_pin["cycle_seq"],
            "superseding_old_payload_hash":
                signed_env.old_pin["payload_hash"],
            "candidate_cycle_seq": signed_env.candidate["cycle_seq"],
            "candidate_payload_hash":
                signed_env.candidate["payload_hash"]}
        failed_attempt = {
            "attempted_authorisation_id": signed_env.authorisation_id,
            "refusal_code": "ceremony_supersede_required",
            "head_authorisation_id": head["authorisation_id"],
            "head_entry_seq": head["seq"],
            "head_entry_hash": head["entry_hash"]}
        approval = sign_supersession_approval(
            approver_key=APPROVER_KEY, approver_id=APPROVER_ID,
            abandoned=abandoned, replacement=replacement,
            failed_attempt=failed_attempt, ttl_seconds=900)
        return supersession_approval_to_dict(approval)

    def test_supersession_anchor_update_failure_decision_stands(self):
        # Full supersede flow: the supersession-anchor update
        # is patched to raise after the journal append (the
        # commit point). The call is ledger_failed with no
        # receipt, the decision stands in the journal, and
        # the signing-ledger mirror must not have landed
        # (the anchor update precedes it in the commit order).
        self.bootstrap_anchors()
        primary = self.authorise()
        self.client.ceremony_consume(primary)
        envelope = self.authorise(
            ceremony_id="ceremony-anchor-supersede",
            candidate={"cycle_seq": 50, "payload_hash": "d" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH3,
            evidence_ref="case-file-3")
        signing_before = len(self.signing_entries())
        body = {"operator_id": OPERATOR,
                "signed_authorisation": envelope,
                "supersession_approval": self._approval_for(envelope)}
        code, doc = self.run_wrapper(
            "supersession_anchor_fail",
            SUPERSESSION_ANCHOR_FAIL_MODULE,
            "ceremony_supersede", body)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertEqual(len(self.supersession_entries()), 1)
        self.assertEqual(len(self.signing_entries()), signing_before)


class ResearchModeNoIssuanceAnchorTests(Cycle27Fixture):
    anchored = False

    def test_research_no_issuance_anchor_rollback_replay_succeeds(self):
        # CHARACTERISATION — pins the no-claim boundary: with
        # no issuance anchor configured (research mode), an
        # authorisation followed by a full home rollback is
        # undetectable and the replay of the same evidence
        # under a new ceremony_id succeeds. No rollback claim
        # is made for this configuration.
        self.authorise(ceremony_id="ceremony-pre",
                       evidence_hash=EVIDENCE_HASH,
                       evidence_ref="case-file-1")
        snapshot = self.snapshot_home()
        self.assertEqual(len(self.issuance_entries()), 1)
        self.authorise()
        self.assertEqual(len(self.issuance_entries()), 2)
        self.restore_home(snapshot)
        self.assertEqual(len(self.issuance_entries()), 1)
        fresh = self._fresh_client()
        envelope = fresh.ceremony_authorise(
            operator_id=OPERATOR, ceremony_id="ceremony-replay",
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate={"cycle_seq": 47, "payload_hash": CAND_HASH,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        self.assertTrue(envelope)
        self.assertEqual(len(self.issuance_entries()), 2)


class IssuanceAnchorInitDiscriminationTests(Cycle27Fixture):

    def test_issuance_init_refused_anchor_deleted_on_established_journal(self):
        # Established issuance journal, anchor file deleted:
        # INIT=1 must refuse anchor_refused (the reason is
        # anchor_missing_established_ledger, not the bare
        # anchor_missing INIT may pin) and must NOT create a
        # replacement anchor file — INIT may not re-pin an
        # established journal.
        self.bootstrap_anchors()
        self.assertGreaterEqual(len(self.issuance_entries()), 1)
        self.issuance_anchor.unlink()
        self.assertFalse(self.issuance_anchor.exists())
        code, doc = self.raw(
            self.authorise_body(
                ceremony_id="ceremony-anchor-init-deleted"),
            env_over={"AION_CEREMONY_ISSUANCE_ANCHOR_INIT": "1"})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")
        self.assertFalse(self.issuance_anchor.exists())

    def test_issuance_init_refused_anchor_ahead_after_journal_rollback(self):
        # Issuance journal rolled back so the existing anchor
        # is AHEAD of / mismatched with the journal: INIT=1
        # must refuse anchor_refused (INIT never re-pins on a
        # non-anchor_missing reason) and the anchor file's
        # bytes must be unchanged afterwards.
        self.bootstrap_anchors()
        snapshot = self.snapshot_home()
        self.authorise()
        self.restore_home(snapshot)
        anchor_bytes = self.issuance_anchor.read_bytes()
        anchor = json.loads(anchor_bytes.decode("utf-8"))
        self.assertGreater(anchor["seq"],
                           len(self.issuance_entries()))
        code, doc = self.raw(
            self.authorise_body(
                ceremony_id="ceremony-anchor-init-ahead"),
            env_over={"AION_CEREMONY_ISSUANCE_ANCHOR_INIT": "1"})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")
        self.assertEqual(self.issuance_anchor.read_bytes(),
                         anchor_bytes)


class SupersessionProductionGateTests(Cycle27Fixture):

    def _production_env(self):
        """Mirror of IssuanceProductionGateTests._production_env:
        a production env over this fixture with every anchor
        initialised at genesis — the full production gate
        except what each test varies."""
        anchors = self.base / "prod-anchors"
        anchors.mkdir(exist_ok=True)
        signing_anchor = anchors / "signing.anchor.json"
        initialise_anchor(
            SigningLedger(self.ledger_home), signing_anchor,
            kind="signing", recorded_at=NOW)
        initialise_anchor(
            CeremonyConsumptionLedger(self.ledger_home),
            anchors / "ceremony-consumption.anchor.json",
            kind="ceremony-consumption", recorded_at=NOW)
        initialise_anchor(
            CeremonyAuthorisationLedger(self.ledger_home),
            anchors / "ceremony-issuance.anchor.json",
            kind="ceremony-issuance", recorded_at=NOW)
        initialise_anchor(
            CeremonySupersessionLedger(self.ledger_home),
            anchors / "ceremony-supersession.anchor.json",
            kind="ceremony-supersession", recorded_at=NOW)
        budgets_anchor = anchors / "budgets.anchor.json"
        budgets_anchor.write_text(json.dumps(
            {"v": "budgets-anchor/1", "head": GENESIS_CHAIN_HASH,
             "anchored_at": NOW}, sort_keys=True), encoding="utf-8")
        env = dict(self.env)
        env["AION_DEPLOYMENT_MODE"] = "production"
        env["AION_ANCHOR_PATH"] = str(signing_anchor)
        env["AION_BUDGETS_ANCHOR_PATH"] = str(budgets_anchor)
        env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = str(
            anchors / "ceremony-consumption.anchor.json")
        env["AION_CEREMONY_ISSUANCE_ANCHOR_PATH"] = str(
            anchors / "ceremony-issuance.anchor.json")
        env["AION_CEREMONY_SUPERSESSION_ANCHOR_PATH"] = str(
            anchors / "ceremony-supersession.anchor.json")
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

    def test_production_without_supersession_anchor_refused(self):
        env, _anchors = self._production_env()
        del env["AION_CEREMONY_SUPERSESSION_ANCHOR_PATH"]
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_production_supersession_anchor_init_refused(self):
        env, _anchors = self._production_env()
        env["AION_CEREMONY_SUPERSESSION_ANCHOR_INIT"] = "1"
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")


class SupersessionAnchorAliasTests(Cycle27Fixture):

    def test_supersession_anchor_equal_to_issuance_refused(self):
        self.bootstrap_anchors()
        code, doc = self.raw(
            self.authorise_body(),
            env_over={
                "AION_CEREMONY_SUPERSESSION_ANCHOR_PATH": str(
                    self.issuance_anchor),
            })
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")


class SupersessionAnchorPositiveAdvanceTests(Cycle27Fixture):

    def test_supersession_anchor_advances_on_successful_supersede(self):
        # Full flow with every anchor configured, including
        # supersession: consume the primary, authorise a
        # supersede-shaped envelope, obtain the approver
        # approval, and supersede successfully. Afterwards the
        # supersession anchor file exists, its kind is
        # "ceremony-supersession", and its head equals the
        # supersession journal's head.
        self.bootstrap_anchors()
        primary = self.authorise()
        self.client.ceremony_consume(primary)
        envelope = self.authorise(
            ceremony_id="ceremony-anchor-supersede-positive",
            candidate={"cycle_seq": 50, "payload_hash": "d" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH3,
            evidence_ref="case-file-3")
        approval = SupersessionAnchorCommitTests._approval_for(
            self, envelope)
        receipt = self.client.ceremony_supersede(
            OPERATOR, envelope, approval)
        self.assertEqual(receipt["supersession_seq"], 1)
        self.assertEqual(len(self.supersession_entries()), 1)
        self.assertTrue(self.supersession_anchor.exists())
        anchor = load_anchor(self.supersession_anchor)
        self.assertEqual(anchor["kind"], "ceremony-supersession")
        journal = CeremonySupersessionLedger(self.ledger_home)
        self.assertEqual(anchor["head"], journal.head())
        self.assertEqual(anchor["seq"],
                         len(self.supersession_entries()))


class IssuanceMigrationCeremonyTests(Cycle27Fixture):
    anchored = False

    def test_issuance_migration_first_pin_ceremony_on_established_journal(self):
        """Migration ceremony for an established issuance journal.

        The journal is built with NO issuance anchor configured
        (it predates anchoring), then an operator runs the
        documented first-pin ceremony outside the verifier —
        initialise_anchor(..., kind="ceremony-issuance",
        allow_nonempty_ceremony=True) — after which a verifier
        invocation with AION_CEREMONY_ISSUANCE_ANCHOR_PATH set
        starts cleanly (no anchor_refused) and a subsequent
        authorisation advances the anchor.

        Note: the first pin blesses the journal's current
        history as-is; it cannot detect a rollback that
        happened before the pin.
        """
        self.authorise(ceremony_id="ceremony-pre-pin",
                       evidence_hash=EVIDENCE_HASH,
                       evidence_ref="case-file-1")
        self.assertGreaterEqual(len(self.issuance_entries()), 1)
        self.assertFalse(self.issuance_anchor.exists())
        journal = CeremonyAuthorisationLedger(self.ledger_home)
        pinned = initialise_anchor(
            journal, self.issuance_anchor,
            kind="ceremony-issuance", recorded_at=NOW,
            allow_nonempty_ceremony=True)
        self.assertEqual(pinned["kind"], "ceremony-issuance")
        self.assertEqual(pinned["seq"], len(self.issuance_entries()))
        self.assertEqual(pinned["head"], journal.head())
        # A verifier invocation with the anchor configured now
        # starts and the authorisation advances the anchor.
        code, doc = self.raw(
            self.authorise_body(
                ceremony_id="ceremony-post-pin"),
            env_over={
                "AION_CEREMONY_ISSUANCE_ANCHOR_PATH": str(
                    self.issuance_anchor),
            })
        self.assertEqual(code, 0, msg=str(doc))
        self.assertIsNone(self.error_code(doc))
        anchor = load_anchor(self.issuance_anchor)
        self.assertEqual(anchor["kind"], "ceremony-issuance")
        self.assertEqual(anchor["seq"], pinned["seq"] + 1)
        self.assertEqual(
            anchor["head"],
            CeremonyAuthorisationLedger(self.ledger_home).head())


def _establish_supersession_journal(home):
    """Append one supersession decision through the ledger
    API (the pattern SupersessionAnchorRollbackTests uses):
    a consumption head is landed first, then a decision
    abandoning it. Returns nothing; the journal on disk is
    the evidence."""
    consumption = CeremonyConsumptionLedger(home)
    head_env = _mint()
    consumption.append_consumption(head_env, recorded_at=NOW)
    head_entry = consumption.entries()[-1]
    replacement = _mint(
        candidate={"cycle_seq": 52, "payload_hash": "c" * 64,
                   "signer_id": "snapshot-svc",
                   "key_id": "key-0123456789abcdef"})
    CeremonySupersessionLedger(home).append_decision(
        abandoned_entry=head_entry, signed=replacement,
        recorded_at=NOW)


class SupersessionMigrationCeremonyTests(Cycle27Fixture):
    anchored = False

    def test_supersession_migration_first_pin_ceremony_on_established_journal(self):
        """Migration ceremony for an established supersession
        journal.

        The journal is built with NO supersession anchor
        configured (it predates anchoring): at least one
        decision is appended via the ledger API, then an
        operator runs the documented first-pin ceremony
        outside the verifier — initialise_anchor(...,
        kind="ceremony-supersession",
        allow_nonempty_ceremony=True) — after which a
        verifier invocation with
        AION_CEREMONY_SUPERSESSION_ANCHOR_PATH set succeeds
        (no anchor_refused).

        Note: the first pin blesses the journal's current
        history as-is; it cannot detect a rollback that
        happened before the pin.
        """
        self.ledger_home.mkdir(parents=True, exist_ok=True)
        _establish_supersession_journal(self.ledger_home)
        self.assertGreaterEqual(len(self.supersession_entries()), 1)
        self.assertFalse(self.supersession_anchor.exists())
        journal = CeremonySupersessionLedger(self.ledger_home)
        pinned = initialise_anchor(
            journal, self.supersession_anchor,
            kind="ceremony-supersession", recorded_at=NOW,
            allow_nonempty_ceremony=True)
        self.assertEqual(pinned["kind"], "ceremony-supersession")
        self.assertEqual(pinned["seq"],
                         len(self.supersession_entries()))
        self.assertEqual(pinned["head"], journal.head())
        code, doc = self.raw(
            {"answers": ["4", "9", "3.14"]}, mode="sealed_eval",
            env_over={
                "AION_CEREMONY_SUPERSESSION_ANCHOR_PATH": str(
                    self.supersession_anchor),
            })
        self.assertEqual(code, 0, msg=str(doc))
        self.assertIsNone(self.error_code(doc))


class ProductionMigrationWalkTests(Cycle27Fixture):
    anchored = False

    def _sealed_eval(self, env):
        full = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full.update(env)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval",
            {"answers": ["4", "9", "3.14"]})
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

    def test_production_migration_walk_both_journals_first_pinned(self):
        """Production-shaped migration walk.

        Evidence level achieved: FULL — a benign sealed_eval
        request in production mode returns exit 0, so the
        production configuration load and the request itself
        both succeeded; this is not merely a post-config-load
        request-level refusal.

        Both ceremony journals are established and
        unanchored first: the issuance journal via its
        ledger API, and the supersession journal via
        append_decision against a fabricated abandoned-head
        binding (so the consumption and signing journals
        stay empty, and their anchors below pin empty
        journals, exactly as the production-gate fixture
        pins them). An operator then first-pins BOTH
        ceremony journals via the migration ceremony
        (allow_nonempty_ceremony=True), pins the signing
        and consumption anchors on their empty journals,
        and writes the budgets anchor at genesis. A
        production-mode invocation with the ceremony seed
        configured and every anchor path set (signing,
        budgets, consumption, issuance, supersession) then
        succeeds with exit 0 on the benign request.
        """
        self.ledger_home.mkdir(parents=True, exist_ok=True)
        # Establish the issuance journal (direct ledger API).
        CeremonyAuthorisationLedger(self.ledger_home) \
            .append_authorisation(_mint(), recorded_at=NOW)
        self.assertGreaterEqual(len(self.issuance_entries()), 1)
        # Establish the supersession journal (direct ledger
        # API, fabricated abandoned-head binding; see the
        # docstring for why consumption stays empty).
        head_env = _mint()
        abandoned = {
            "authorisation_id": head_env.authorisation_id,
            "ceremony_id": head_env.ceremony_id,
            "old_cycle_seq": head_env.old_pin["cycle_seq"],
            "old_payload_hash": head_env.old_pin["payload_hash"],
            "new_cycle_seq": head_env.candidate["cycle_seq"],
            "new_payload_hash": head_env.candidate["payload_hash"]}
        replacement = _mint(
            candidate={"cycle_seq": 52, "payload_hash": "c" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        CeremonySupersessionLedger(self.ledger_home) \
            .append_decision(abandoned_entry=abandoned,
                             signed=replacement, recorded_at=NOW)
        self.assertGreaterEqual(len(self.supersession_entries()), 1)
        self.assertEqual(self.consumption_entries(), [])
        self.assertEqual(self.signing_entries(), [])
        # Operator first-pin ceremony for BOTH journals.
        anchors = self.base / "prod-anchors"
        anchors.mkdir(exist_ok=True)
        issuance_anchor = anchors / "ceremony-issuance.anchor.json"
        supersession_anchor = (
            anchors / "ceremony-supersession.anchor.json")
        pinned_issuance = initialise_anchor(
            CeremonyAuthorisationLedger(self.ledger_home),
            issuance_anchor, kind="ceremony-issuance",
            recorded_at=NOW, allow_nonempty_ceremony=True)
        self.assertEqual(pinned_issuance["seq"],
                         len(self.issuance_entries()))
        pinned_supersession = initialise_anchor(
            CeremonySupersessionLedger(self.ledger_home),
            supersession_anchor, kind="ceremony-supersession",
            recorded_at=NOW, allow_nonempty_ceremony=True)
        self.assertEqual(pinned_supersession["seq"],
                         len(self.supersession_entries()))
        # Remaining anchors pinned on their empty journals.
        signing_anchor = anchors / "signing.anchor.json"
        initialise_anchor(
            SigningLedger(self.ledger_home), signing_anchor,
            kind="signing", recorded_at=NOW)
        consumption_anchor = (
            anchors / "ceremony-consumption.anchor.json")
        initialise_anchor(
            CeremonyConsumptionLedger(self.ledger_home),
            consumption_anchor, kind="ceremony-consumption",
            recorded_at=NOW)
        budgets_anchor = anchors / "budgets.anchor.json"
        budgets_anchor.write_text(json.dumps(
            {"v": "budgets-anchor/1", "head": GENESIS_CHAIN_HASH,
             "anchored_at": NOW}, sort_keys=True), encoding="utf-8")
        env = dict(self.env)
        env["AION_DEPLOYMENT_MODE"] = "production"
        env["AION_ANCHOR_PATH"] = str(signing_anchor)
        env["AION_BUDGETS_ANCHOR_PATH"] = str(budgets_anchor)
        env["AION_CEREMONY_CONSUMPTION_ANCHOR_PATH"] = str(
            consumption_anchor)
        env["AION_CEREMONY_ISSUANCE_ANCHOR_PATH"] = str(
            issuance_anchor)
        env["AION_CEREMONY_SUPERSESSION_ANCHOR_PATH"] = str(
            supersession_anchor)
        # The ceremony seed is already configured in
        # self.env (AION_CEREMONY_SIGNING_SEED_PATH).
        self.assertTrue(env["AION_CEREMONY_SIGNING_SEED_PATH"])
        code, doc = self._sealed_eval(env)
        self.assertEqual(code, 0, msg=str(doc))
        self.assertIsNone(self.error_code(doc))


class PartialBootstrapStateTests(Cycle27Fixture):

    def test_partial_bootstrap_issuance_pin_lands_supersession_refuses(self):
        """Partial-bootstrap state, pinned as disclosed.

        Research mode: the issuance journal is empty, the
        supersession journal is ESTABLISHED (non-empty) and
        its anchor is missing. One invocation carries BOTH
        issuance and supersession INIT=1. The issuance check
        runs first and its INIT legitimately pins the empty
        journal, so the issuance anchor file IS created by
        that same invocation; the supersession INIT cannot
        bless an established journal, so the invocation
        still refuses with exit 3 / anchor_refused. A second
        invocation, with only the supersession problem
        remaining, still refuses and still creates no
        supersession anchor.
        """
        self.ledger_home.mkdir(parents=True, exist_ok=True)
        # Every earlier-checked anchor verifies: signing and
        # consumption pinned on their empty journals.
        initialise_anchor(
            SigningLedger(self.ledger_home), self.signing_anchor,
            kind="signing", recorded_at=NOW)
        initialise_anchor(
            CeremonyConsumptionLedger(self.ledger_home),
            self.consumption_anchor, kind="ceremony-consumption",
            recorded_at=NOW)
        # Supersession journal established, anchor missing;
        # issuance journal empty, anchor missing.
        _establish_supersession_journal(self.ledger_home)
        self.assertGreaterEqual(len(self.supersession_entries()), 1)
        self.assertEqual(self.issuance_entries(), [])
        self.assertFalse(self.issuance_anchor.exists())
        self.assertFalse(self.supersession_anchor.exists())
        code, doc = self.raw(
            {"answers": ["4", "9", "3.14"]}, mode="sealed_eval",
            env_over={
                "AION_CEREMONY_ISSUANCE_ANCHOR_INIT": "1",
                "AION_CEREMONY_SUPERSESSION_ANCHOR_INIT": "1"})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")
        # The honest partial-bootstrap side effect: the
        # issuance anchor WAS created by that invocation.
        self.assertTrue(self.issuance_anchor.exists())
        anchor = load_anchor(self.issuance_anchor)
        self.assertEqual(anchor["kind"], "ceremony-issuance")
        self.assertEqual(anchor["seq"], 0)
        self.assertFalse(self.supersession_anchor.exists())
        # Second invocation: only the supersession problem
        # remains, and it still refuses.
        code, doc = self.raw(
            {"answers": ["4", "9", "3.14"]}, mode="sealed_eval",
            env_over={
                "AION_CEREMONY_SUPERSESSION_ANCHOR_INIT": "1"})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "anchor_refused")
        self.assertFalse(self.supersession_anchor.exists())


if __name__ == "__main__":
    unittest.main()
