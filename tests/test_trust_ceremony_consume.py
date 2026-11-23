"""Tests for the verifier's ceremony_consume mode (cycle 21,
DESIGN-FINAL R2/R3/R4/R7/R9) — real subprocess, following
tests/test_trust_ceremony_mode.py fixture discipline: fake
registry + generated keys in a temp verifier home, envelopes
issued through the real ceremony_authorise mode.

Covered: happy path (consumption journal entry, signing-ledger
mirror scoped kind="consume" + format="ceremony-consumption",
the issuance mirror's kind="sign" entry NOT tripping the
cross-check); replay; fresh envelope for a consumed target;
candidate behind / forked at the head; old pin behind the
head; old pin ahead of the head (advance_pin case); initial
anchor after consumptions; never-issued; expired; tampered;
seed-unconfigured gate (seed ONLY — operators/evidence blanked
too); corrupt consumption journal; crash kill points (before
append; after append before response — the retry refuses
already-consumed, proving commit-before-response); mirror
failure after commit (ledger_failed, envelope burned);
two-process barrier concurrent double-consume with exactly
one winner; R9 derivation-overlap startup refusals.

Crash/race kill-point mapping (design-b.md section D4 /
DESIGN-FINAL R7) — every crash test below is labelled with
its K-scenario id so coverage is traceable to the ruling:

  K1  kill before the consumption append (burns nothing)
      -> CeremonyConsumeCrashTests.test_k1_...
  K2  kill after the append, before the response (the
      commit lands, the envelope is burned)
      -> CeremonyConsumeCrashTests.test_k2_...
  K3  response lost: consume succeeds, the receipt is
      discarded, a retry refuses already-consumed
      -> CeremonyConsumeCrashTests.test_k3_...
  K4  torn/corrupt consumption journal fails closed
      (ledger_failed); and the deleted-journal half: the
      signing-ledger mirror cross-check still refuses a
      replay of a mirrored envelope
      -> test_k4_corrupt_consumption_journal_ledger_failed,
         CeremonyConsumeCrashTests.test_k4_...
  K5  concurrent double-consume race, the interleave FORCED
      inside append_consumption's reload->save window (both
      processes rendezvous after the reload re-check, before
      either save) so the loser is refused by the in-loop
      re-check specifically, as ceremony_already_consumed
      -> CeremonyConsumeCrashTests.test_k5_...
  K6  crash between the commit and the mirror (mirror append
      fails after the consumption commit: ledger_failed, the
      envelope stays burned, no mirror entry)
      -> CeremonyConsumeCrashTests.test_k6_...
  K6b the post-mirror boundary of design-b section D4 G3,
      adjacent to K6: kill after the mirror append, before
      _update_anchor (consumed AND mirrored; the retry
      refuses already-consumed and both journals agree)
      -> CeremonyConsumeCrashTests.test_k6b_...
"""

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    CeremonySigningKey,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_to_dict,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    public_key_id_for,
    sign_ceremony_authorisation,
)
from signing.ed25519 import public_key_from_seed
from trust import protocol
from trust.client import VerifierClient
from trust.ledger import (
    GENESIS_HASH,
    CeremonyAuthorisationLedger,
    CeremonyConsumptionLedger,
    ShipLedger,
    SigningLedger,
)
from trust.verifier_main import _Refuse, _load_config
import trust.verifier_main as verifier_main

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-uma"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
ARTIFACT = b"ceremony evidence bundle: case file 1\n"
EVIDENCE_HASH = hashlib.sha256(ARTIFACT).hexdigest()
ARTIFACT2 = b"ceremony evidence bundle: case file 2\n"
EVIDENCE_HASH2 = hashlib.sha256(ARTIFACT2).hexdigest()
ARTIFACT3 = b"ceremony evidence bundle: case file 3\n"
EVIDENCE_HASH3 = hashlib.sha256(ARTIFACT3).hexdigest()
REPO = Path(__file__).resolve().parents[1]
RFC_TEST1_SEED_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60")


class ConsumeFixture(unittest.TestCase):
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
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.ledger_home),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATOR + ",operator-backup",
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, **over):
        body = {
            "operator_id": OPERATOR,
            "ceremony_id": "ceremony-2026-11-28-001",
            "reason": "chain_gap_recovery",
            "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
            "candidate": {"cycle_seq": 47, "payload_hash": CAND_HASH,
                          "signer_id": "snapshot-svc",
                          "key_id": "key-0123456789abcdef"},
            "evidence_hash": EVIDENCE_HASH,
            "evidence_ref": "case-file-1",
        }
        body.update(over)
        return body

    def authorise(self, **over):
        body = self.body(**over)
        return self.client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])

    def full_env(self, env_over=None):
        env = dict(self.env)
        if env_over:
            env.update(env_over)
        full_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full_env.update(env)
        return full_env

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
        return result.returncode, doc, result.stdout

    def raw_full(self, body, *, request_id, mode="ceremony_consume",
                 env_over=None):
        """Like raw(), but with a caller-fixed request id and
        the raw stdout/stderr bytes returned — for tests that
        compare two responses byte for byte."""
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=self.full_env(env_over))
        return result.returncode, result.stdout, result.stderr

    def consume(self, envelope, **kw):
        return self.raw({"signed_authorisation": envelope}, **kw)

    def error_code(self, doc):
        return doc["error"]["code"] if doc and doc.get("error") \
            else None

    def consumption_entries(self):
        if not (self.ledger_home
                / "ceremony-consumptions.json").exists():
            return []
        return CeremonyConsumptionLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()

    def candidate(self, seq, payload_hash):
        return {"cycle_seq": seq, "payload_hash": payload_hash,
                "signer_id": "snapshot-svc",
                "key_id": "key-0123456789abcdef"}

    def sign_directly(self, *, ceremony_id, candidate, old_pin=None,
                      evidence_hash=EVIDENCE_HASH,
                      evidence_ref="case-file-1", now=None):
        signed = sign_ceremony_authorisation(
            signing_key=self.seed_key, signer_id=SIGNER,
            operator_id=OPERATOR, ceremony_id=ceremony_id,
            reason=("chain_gap_recovery" if old_pin is not None
                    else "lost_pin"),
            old_pin=old_pin, candidate=candidate,
            evidence_hash=evidence_hash, evidence_ref=evidence_ref,
            now=now)
        return ceremony_authorisation_envelope_to_dict(signed)


class CeremonyConsumeTests(ConsumeFixture):
    def test_happy_path_journal_mirror_and_result(self):
        envelope = self.authorise()
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        result = doc["result"]
        self.assertEqual(
            set(result), {"authorisation_id", "ceremony_id",
                          "consumption_seq", "new_cycle_seq",
                          "new_payload_hash"})
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(result["authorisation_id"],
                         signed.authorisation_id)
        self.assertEqual(result["ceremony_id"], signed.ceremony_id)
        self.assertEqual(result["consumption_seq"], 1)
        self.assertEqual(result["new_cycle_seq"], 47)
        self.assertEqual(result["new_payload_hash"], CAND_HASH)
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["kind"], "consume")
        self.assertEqual(entry["authorisation_id"],
                         signed.authorisation_id)
        self.assertEqual(entry["ceremony_id"], signed.ceremony_id)
        self.assertEqual(entry["operator_id"], OPERATOR)
        self.assertEqual(entry["old_cycle_seq"], 41)
        self.assertEqual(entry["old_payload_hash"], OLD_HASH)
        self.assertEqual(entry["new_cycle_seq"], 47)
        self.assertEqual(entry["new_payload_hash"], CAND_HASH)
        self.assertEqual(entry["evidence_hash"], EVIDENCE_HASH)
        self.assertEqual(entry["consumed_at"], entry["recorded_at"])
        ledger = CeremonyConsumptionLedger(self.ledger_home)
        self.assertEqual(ledger.head_target(), (47, CAND_HASH))
        self.assertEqual(
            ledger.find_by_authorisation(
                signed.authorisation_id)["seq"], 1)
        # Mirror: exactly one consume entry, scoped; and the
        # issuance mirror's kind="sign" entry for the SAME
        # authorisation_id exists and did NOT trip the
        # cross-check (this consume succeeded with it present).
        mirrors = [e for e in self.signing_entries()
                   if e["kind"] == "consume"]
        self.assertEqual(len(mirrors), 1)
        self.assertEqual(mirrors[0]["format"],
                         "ceremony-consumption")
        self.assertEqual(mirrors[0]["decision_id"],
                         signed.authorisation_id)
        self.assertEqual(mirrors[0]["proposal_id"],
                         signed.ceremony_id)
        self.assertFalse(mirrors[0]["accepted"])
        issuance = [e for e in self.signing_entries()
                    if e["kind"] == "sign"
                    and e["format"] == "ceremony-authorisation"]
        self.assertEqual(len(issuance), 1)
        self.assertEqual(issuance[0]["decision_id"],
                         signed.authorisation_id)

    def test_replay_same_envelope_already_consumed(self):
        envelope = self.authorise()
        code, _, _ = self.consume(envelope)
        self.assertEqual(code, 0)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_fresh_envelope_same_target_already_consumed(self):
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_candidate_behind_head_regression(self):
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            candidate=self.candidate(44, "c" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_head_regression")

    def test_fork_at_head_seq_regression(self):
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            candidate=self.candidate(47, "c" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_head_regression")

    def test_old_pin_behind_head_regression(self):
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            candidate=self.candidate(50, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_head_regression")

    def test_old_pin_ahead_of_head_admitted(self):
        # advance_pin case: the live pin moved past the ceremony
        # head with no verifier trace (head target seq 47); a
        # ceremony based on old seq 50 with candidate 55 is
        # legitimate and admitted.
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            old_pin={"cycle_seq": 50, "payload_hash": "e" * 64},
            candidate=self.candidate(55, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 0, msg=str(doc))
        self.assertEqual(doc["result"]["new_cycle_seq"], 55)
        ledger = CeremonyConsumptionLedger(self.ledger_home)
        self.assertEqual(ledger.head_target(), (55, "d" * 64))

    def test_initial_anchor_after_consumption_regression(self):
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            reason="initial_anchor", old_pin=None,
            candidate=self.candidate(60, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_head_regression")

    def test_never_issued_envelope_refused(self):
        envelope = self.sign_directly(
            ceremony_id="ceremony-never-issued-001",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate=self.candidate(47, CAND_HASH))
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_not_issued")
        self.assertEqual(self.consumption_entries(), [])

    def test_expired_envelope_refused(self):
        past = (datetime.now(timezone.utc)
                - timedelta(seconds=2000)).isoformat()
        envelope = self.sign_directly(
            ceremony_id="ceremony-expired-001",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate=self.candidate(47, CAND_HASH), now=past)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_authorisation_expired")

    def test_tampered_envelope_invalid(self):
        envelope = self.authorise()
        envelope = dict(envelope, signature="0" * 128)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc),
                         "ceremony_authorisation_invalid")
        self.assertEqual(self.consumption_entries(), [])

    def test_malformed_body_refused(self):
        code, doc, _ = self.raw({"signed_authorisation": {},
                                 "extra": 1})
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc), "malformed_request")

    def test_seed_unconfigured_is_the_only_gate(self):
        # Operators and evidence blanked as well: consumption
        # gates on the seed ONLY (they are issuance facts), so
        # the refusal is still the seed's.
        envelope = self.authorise()
        code, doc, _ = self.consume(envelope, env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": "",
            "AION_CEREMONY_OPERATORS": "",
            "AION_CEREMONY_EVIDENCE_DIR": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_seed_unconfigured")
        self.assertEqual(self.consumption_entries(), [])

    def test_old_pin_equal_head_equal_hash_admitted(self):
        # The normal next ceremony (rev-r3 LOW-4): the second
        # ceremony's old pin IS the consumption head — same
        # seq, same hash — and its candidate is ahead. The
        # head rules admit it.
        self.consume(self.authorise())
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            old_pin={"cycle_seq": 47, "payload_hash": CAND_HASH},
            candidate=self.candidate(52, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.consume(envelope2)
        self.assertEqual(code, 0, msg=str(doc))
        self.assertEqual(doc["result"]["new_cycle_seq"], 52)
        ledger = CeremonyConsumptionLedger(self.ledger_home)
        self.assertEqual(ledger.head_target(), (52, "d" * 64))

    def test_invalid_envelopes_indistinguishable_to_caller(self):
        # B1 / rev-r3 HIGH-1 regression: two differently-invalid
        # envelopes — a bad signature vs a binding mismatch —
        # must produce BYTE-IDENTICAL caller-visible error
        # documents and identical stderr. (The verifier once
        # printed the per-reason verify tuple to stderr, which
        # the client embeds in its exception messages — a
        # forger oracle defeating R2's single invalid code.)
        request_id = protocol.new_request_id()
        bad_sig = dict(self.authorise(), signature="0" * 128)
        code1, out1, err1 = self.raw_full(
            {"signed_authorisation": bad_sig}, request_id=request_id)
        envelope2 = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        bad_binding = dict(envelope2)
        bad_binding["candidate"] = dict(
            envelope2["candidate"], payload_hash="f" * 64)
        code2, out2, err2 = self.raw_full(
            {"signed_authorisation": bad_binding},
            request_id=request_id)
        self.assertEqual(code1, 2)
        self.assertEqual(code2, 2)
        self.assertEqual(out1, out2)
        self.assertEqual(
            self.error_code(json.loads(out1.decode("utf-8"))),
            "ceremony_authorisation_invalid")
        self.assertEqual(err1, err2)
        for leak in (b"signature_mismatch", b"payload_hash_mismatch",
                     b"authorisation_id_mismatch", b"verify reasons"):
            self.assertNotIn(leak, err1)
            self.assertNotIn(leak, err2)
        self.assertEqual(self.consumption_entries(), [])

    def test_head_contract_polymorphic(self):
        # B2 / rev-r3 MEDIUM-1 + rev-r6 F2: head() is the base
        # contract — the chain hash (GENESIS_HASH when empty) —
        # for EVERY HashChainJournal subclass, including
        # CeremonyConsumptionLedger; the consumption target is
        # head_target()'s job alone.
        def assert_chain_head(ledger):
            head = ledger.head()
            self.assertIsInstance(head, str)
            self.assertEqual(len(head), 64)
            self.assertTrue(
                all(c in "0123456789abcdef" for c in head))
            entries = ledger.entries()
            self.assertEqual(
                head, entries[-1]["entry_hash"] if entries
                else GENESIS_HASH)

        empty_consumption = CeremonyConsumptionLedger(
            self.base / "empty-consumption-home")
        self.assertEqual(empty_consumption.head(), GENESIS_HASH)
        self.assertIsNone(empty_consumption.head_target())
        assert_chain_head(empty_consumption)

        ship = ShipLedger(self.base / "ship-home")
        self.assertEqual(ship.head(), GENESIS_HASH)
        ship.burn(decision_id="decision-1", proposal_id="prop-1",
                  manifest_hash="m" * 64, payload_hash="n" * 64,
                  recorded_at="2026-11-28T00:00:00+00:00")
        assert_chain_head(ship)
        self.assertNotEqual(ship.head(), GENESIS_HASH)

        # After a real consume, the fixture's three verifier
        # journals all honour the same contract, while the
        # consumption ledger's head_target() gives the target.
        self.consume(self.authorise())
        consumption = CeremonyConsumptionLedger(self.ledger_home)
        assert_chain_head(consumption)
        self.assertEqual(consumption.head_target(),
                         (47, CAND_HASH))
        assert_chain_head(SigningLedger(self.ledger_home))
        assert_chain_head(
            CeremonyAuthorisationLedger(self.ledger_home))

    def test_k4_corrupt_consumption_journal_ledger_failed(self):
        envelope = self.authorise()
        self.ledger_home.mkdir(parents=True, exist_ok=True)
        (self.ledger_home
         / "ceremony-consumptions.json").write_text("not a journal")
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")


KILL_BEFORE_MODULE = '''
import os
import sys

import trust.verifier_main as vm


def _kill(self, envelope, *, recorded_at):
    os._exit(70)


vm.CeremonyConsumptionLedger.append_consumption = _kill
sys.exit(vm.main())
'''

KILL_AFTER_MODULE = '''
import os
import sys

import trust.verifier_main as vm

_orig = vm.CeremonyConsumptionLedger.append_consumption


def _kill(self, envelope, *, recorded_at):
    _orig(self, envelope, recorded_at=recorded_at)
    os._exit(70)


vm.CeremonyConsumptionLedger.append_consumption = _kill
sys.exit(vm.main())
'''

MIRROR_FAIL_MODULE = '''
import sys

import trust.verifier_main as vm


def _boom(self, signed, *, recorded_at):
    raise RuntimeError("mirror unavailable")


vm.SigningLedger.append_ceremony_consumption = _boom
sys.exit(vm.main())
'''

KILL_AFTER_MIRROR_MODULE = '''
import os
import sys

import trust.verifier_main as vm

_orig = vm.SigningLedger.append_ceremony_consumption


def _kill(self, signed, *, recorded_at):
    _orig(self, signed, recorded_at=recorded_at)
    os._exit(70)


vm.SigningLedger.append_ceremony_consumption = _kill
sys.exit(vm.main())
'''

APPEND_BARRIER_MODULE = '''
import io
import os
import sys
import time
from pathlib import Path

data = sys.stdin.buffer.read()

import trust.verifier_main as vm
from trust.ledger import HashChainJournal

_barrier_dir = Path(os.environ["CEREMONY_TEST_BARRIER_DIR"])
_count = int(os.environ.get("CEREMONY_TEST_BARRIER_COUNT", "2"))
_orig_save = HashChainJournal._save
_gated = False


def _gated_save(self, entries):
    # Rendezvous INSIDE append_consumption's reload->save
    # window: this first _save call happens only after the
    # reload and the single-use/head re-checks have run, so
    # when both processes are parked here, both have reloaded
    # the (still empty) journal and passed every check, and
    # neither has saved. Releasing them together forces the
    # loser's save to hit the freshness check and surface
    # through append_consumption's in-loop re-check.
    global _gated
    if not _gated:
        _gated = True
        _barrier_dir.mkdir(parents=True, exist_ok=True)
        (_barrier_dir / f"{os.getpid()}.ready").write_text("x")
        deadline = time.time() + 30
        while time.time() < deadline:
            if len(list(_barrier_dir.glob("*.ready"))) >= _count:
                break
            time.sleep(0.002)
        print("APPEND_WINDOW_REACHED", file=sys.stderr,
              flush=True)
    return _orig_save(self, entries)


vm.CeremonyConsumptionLedger._save = _gated_save


class _Stdin:
    buffer = io.BytesIO(data)


sys.stdin = _Stdin()
sys.exit(vm.main())
'''


class CeremonyConsumeCrashTests(ConsumeFixture):
    def _run_wrapper(self, name, source, envelope):
        wrapper_dir = self.base / "wrapper"
        wrapper_dir.mkdir(exist_ok=True)
        wrapper = wrapper_dir / f"{name}.py"
        wrapper.write_text(source)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "ceremony_consume",
            {"signed_authorisation": envelope})
        return subprocess.run(
            [sys.executable, str(wrapper)], input=raw,
            capture_output=True, timeout=30, cwd=str(REPO),
            env=self.full_env())

    def test_k1_kill_before_append_burns_nothing(self):
        envelope = self.authorise()
        result = self._run_wrapper("kill_before", KILL_BEFORE_MODULE,
                                   envelope)
        self.assertEqual(result.returncode, 70)
        self.assertEqual(self.consumption_entries(), [])
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 0, msg=str(doc))

    def test_k2_kill_after_append_before_response_burns(self):
        # Commit-before-response: the first attempt died after
        # the append; the envelope is burned and a second
        # attempt refuses already-consumed.
        envelope = self.authorise()
        result = self._run_wrapper("kill_after", KILL_AFTER_MODULE,
                                   envelope)
        self.assertEqual(result.returncode, 70)
        self.assertEqual(len(self.consumption_entries()), 1)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_k3_response_lost_retry_refused(self):
        # K3 — response lost: the consume committed and
        # returned ok, but the caller never saw the receipt
        # (discarded here). A retry of the same envelope
        # refuses already-consumed; exactly one entry exists.
        envelope = self.authorise()
        code, _doc, _ = self.consume(envelope)
        self.assertEqual(code, 0)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_k4_deleted_journal_mirror_still_refuses_replay(self):
        # K4, second half (design-b section D4): the
        # consumption journal is deleted, leaving the mirror;
        # the mode's signing-ledger cross-check (scoped
        # kind="consume" + format="ceremony-consumption") is
        # what still refuses the replay.
        envelope = self.authorise()
        code, _, _ = self.consume(envelope)
        self.assertEqual(code, 0)
        (self.ledger_home
         / "ceremony-consumptions.json").unlink()
        self.assertEqual(self.consumption_entries(), [])
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")

    def test_k6b_kill_after_mirror_before_anchor(self):
        # K6b — kill after the mirror append, before
        # _update_anchor. The design's state for this boundary
        # (design-b section D4 G3): consumed AND mirrored —
        # the anchor step is the only thing skipped (a no-op
        # in this fixture: no anchor is configured), so the
        # durable state is the two journals in agreement, and
        # a retry refuses already-consumed without adding
        # anything to either journal.
        envelope = self.authorise()
        result = self._run_wrapper(
            "kill_after_mirror", KILL_AFTER_MIRROR_MODULE,
            envelope)
        self.assertEqual(result.returncode, 70)
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(
            len([e for e in self.signing_entries()
                 if e["kind"] == "consume"]), 1)
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(
            len([e for e in self.signing_entries()
                 if e["kind"] == "consume"]), 1)

    def test_k6_mirror_failure_after_commit_burns(self):
        envelope = self.authorise()
        result = self._run_wrapper("mirror_fail", MIRROR_FAIL_MODULE,
                                   envelope)
        self.assertEqual(result.returncode, 3)
        doc = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertIn("burned", doc["error"]["detail"])
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(
            [e for e in self.signing_entries()
             if e["kind"] == "consume"], [])
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")

    def test_k5_concurrent_double_consume_one_winner(self):
        # K5 — concurrent double-consume, interleave FORCED
        # inside append_consumption's reload->save window (not
        # a start-line barrier): the wrapper rendezvous sits in
        # CeremonyConsumptionLedger._save, after the reload and
        # re-checks, so both processes demonstrably pass the
        # mode's snapshot pre-checks and enter the append
        # before either saves. The loser therefore surfaces
        # ceremony_already_consumed via append_consumption's
        # in-loop re-check after its save hits the freshness
        # check — not via the mode pre-check, and not as
        # ledger_failed. Both processes printing
        # APPEND_WINDOW_REACHED is the proof both entered the
        # window.
        envelope = self.authorise()
        wrapper_dir = self.base / "wrapper"
        wrapper_dir.mkdir(exist_ok=True)
        wrapper = wrapper_dir / "append_barrier_consume.py"
        wrapper.write_text(APPEND_BARRIER_MODULE)
        barrier_dir = self.base / "append-barrier"
        env = self.full_env({
            "CEREMONY_TEST_BARRIER_DIR": str(barrier_dir),
            "CEREMONY_TEST_BARRIER_COUNT": "2"})
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "ceremony_consume",
            {"signed_authorisation": envelope})
        procs = [
            subprocess.Popen(
                [sys.executable, str(wrapper)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=str(REPO), env=env)
            for _ in range(2)]
        # Feed and close BOTH stdins before reading either
        # output: the wrapper reads stdin to EOF before it
        # starts, so a sequential communicate() would leave
        # the second process parked on its stdin read while
        # the first waits at the barrier for it.
        for proc in procs:
            proc.stdin.write(raw)
            proc.stdin.close()
        outcomes = []
        for proc in procs:
            out = proc.stdout.read()
            err = proc.stderr.read()
            proc.wait(timeout=60)
            doc = json.loads(out.decode("utf-8"))
            outcomes.append((proc.returncode, doc, err))
        for _code, _doc, err in outcomes:
            self.assertIn(b"APPEND_WINDOW_REACHED", err)
        codes = sorted(code for code, _, _ in outcomes)
        self.assertEqual(codes, [0, 3])
        loser = [doc for code, doc, _ in outcomes if code == 3][0]
        self.assertEqual(self.error_code(loser),
                         "ceremony_already_consumed")
        self.assertEqual(len(self.consumption_entries()), 1)


class DerivationOverlapStartupTests(ConsumeFixture):
    def _write_secret(self, name, data):
        path = self.base / name
        path.write_text(data.hex() + "\n")
        path.chmod(0o600)
        return str(path)

    def _startup(self, key_bytes, seed_bytes):
        key_path = self._write_secret("overlap.key", key_bytes)
        seed_path = self._write_secret("overlap.seed", seed_bytes)
        code, doc, _ = self.raw(
            self.body(), mode="ceremony_authorise", env_over={
                "AION_VERIFIER_KEY_PATH": key_path,
                "AION_CEREMONY_SIGNING_SEED_PATH": seed_path})
        return code, doc

    def _assert_refused(self, key_bytes, seed_bytes):
        code, doc = self._startup(key_bytes, seed_bytes)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_seed_is_sha256_of_key_refused(self):
        key = b"\x11" * 32
        self._assert_refused(key, hashlib.sha256(key).digest())

    def test_key_is_sha256_of_seed_refused(self):
        seed = b"\x22" * 32
        self._assert_refused(hashlib.sha256(seed).digest(), seed)

    def test_key_is_ceremony_public_key_refused(self):
        seed = b"\x33" * 32
        self._assert_refused(public_key_from_seed(seed), seed)

    def test_key_is_sha256_of_ceremony_public_key_refused(self):
        seed = b"\x44" * 32
        self._assert_refused(
            hashlib.sha256(public_key_from_seed(seed)).digest(),
            seed)

    def test_seed_is_sha256_of_signing_keys_public_key_refused(self):
        # "Own public key" read as the public key derived by
        # treating the HMAC key bytes as an Ed25519 seed.
        key = b"\x55" * 32
        seed = hashlib.sha256(public_key_from_seed(key)).digest()
        self._assert_refused(key, seed)

    def test_rfc_vector_seed_as_hmac_key_refused(self):
        self._assert_refused(bytes.fromhex(RFC_TEST1_SEED_HEX),
                             b"\x66" * 32)

    def test_seed_is_sha256_of_ceremony_public_key_refused(self):
        # This relation is self-referential through the real
        # loader (the public key is derived from the seed
        # itself), so it is exercised at config load with the
        # loader stubbed to a key whose public key and seed
        # stand in the relation.
        public = public_key_from_seed(b"\x77" * 32)
        fake = CeremonySigningKey(
            seed=hashlib.sha256(public).digest(),
            public_key=public, key_id=public_key_id_for(public))
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(verifier_main, "load_ceremony_seed",
                             lambda *a, **k: fake):
            with self.assertRaises(_Refuse) as ctx:
                _load_config()
        self.assertEqual(ctx.exception.code,
                         "verifier_misconfigured")

    def test_non_overlapping_pair_starts_fine(self):
        code, doc, _ = self.raw(self.body(),
                                mode="ceremony_authorise")
        self.assertEqual(code, 0, msg=str(doc))
        self.assertIn("signed_authorisation", doc["result"])


if __name__ == "__main__":
    unittest.main()
