"""Tests for the verifier's ceremony_authorise mode (cycle 19,
evidence resolution + Ed25519 key boundary cycle 20) — real
subprocess, following tests/test_trust_verifier.py fixture
discipline: fake registry + generated keys in a temp verifier
home.

Cycle-20 fixture discipline: a REAL evidence artifact file is
created in a tmp evidence dir and EVIDENCE_HASH is its real
SHA-256; the ceremony seed is provisioned through the real
loader path (generate_ceremony_key_file writes it 0600 outside
the repo; the verifier loads it via load_ceremony_seed), never
a literal seed. The client pins the derived CeremonyPublicKey
and verifies envelope signatures client-side.

Covered: listed operator issued + ledgered in BOTH stores +
evidence retained; unconfigured refusals (operators / seed /
evidence, research per-request; production startup refusals);
malformed env grammar; ref grammar refusals; traversal /
symlink escapes under the single unresolvable code with
caller-identical bytes across sub-cases; hash mismatch exit-2;
oversize; membership-before-evidence; retention idempotence +
collision; replay scan on the computed hash; seed==HMAC-key
and RFC-vector-seed startup refusals; client-side signature
verification; malformed bodies burn nothing; ceremony_id /
evidence reuse; identical re-presentation; the dual-append
burn; the TTL hard cap.
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_from_dict,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    load_ceremony_seed,
    sign_ceremony_authorisation,
    verify_ceremony_authorisation,
)
from trust import protocol
from trust.client import VerifierClient
from trust.errors import VerifierConfigError, VerifierProtocolError
from trust.ledger import (
    CeremonyAuthorisationLedger,
    LedgerError,
    SigningLedger,
)
from trust.verifier_main import (
    _REFUSED_TEST_SEEDS,
    _Refuse,
    _load_config,
    _retain_ceremony_evidence,
)

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
REPO = Path(__file__).resolve().parents[1]
RFC_TEST1_SEED_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60")


class CeremonyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        # Ceremony seed via the real generator/loader, 0600,
        # outside the repo.
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.assertEqual(
            stat.S_IMODE(self.seed_path.stat().st_mode), 0o600)
        self.assertEqual(
            load_ceremony_seed(self.seed_path).key_id,
            self.seed_key.key_id)
        self.pub = ceremony_public_key_for(self.seed_key)
        # Real evidence artifacts in a tmp evidence dir.
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        (self.evidence_dir / "case-file-1").write_bytes(ARTIFACT)
        (self.evidence_dir / "case-file-2").write_bytes(ARTIFACT2)
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

    def raw(self, body, *, env_over=None, mode="ceremony_authorise"):
        env = dict(self.env)
        if env_over:
            env.update(env_over)
        full_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full_env.update(env)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=full_env)
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc, result.stdout

    def error_code(self, doc):
        return doc["error"]["code"] if doc and doc.get("error") \
            else None

    def ceremony_entries(self):
        if not (self.ledger_home
                / "ceremony-authorisations.json").exists():
            return []
        return CeremonyAuthorisationLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()

    def retained(self):
        retained_dir = self.ledger_home / "ceremony-evidence"
        if not retained_dir.is_dir():
            return {}
        return {p.name: p.read_bytes()
                for p in retained_dir.iterdir()}


class CeremonyModeTests(CeremonyFixture):
    def test_listed_operator_issued_ledgered_and_retained(self):
        envelope = self.authorise()
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, public_key=self.pub,
                expected_signer_id=SIGNER), ())
        self.assertEqual(signed.key_id, self.seed_key.key_id)
        self.assertTrue(signed.key_id.startswith("pub-"))
        self.assertEqual(len(signed.signature), 128)
        self.assertEqual(signed.operator_id, OPERATOR)
        self.assertEqual(signed.evidence_hash, EVIDENCE_HASH)
        ceremony = self.ceremony_entries()
        self.assertEqual(len(ceremony), 1)
        self.assertEqual(ceremony[0]["kind"], "authorise")
        self.assertEqual(ceremony[0]["ceremony_id"],
                         "ceremony-2026-11-28-001")
        self.assertEqual(ceremony[0]["evidence_hash"], EVIDENCE_HASH)
        self.assertEqual(ceremony[0]["authorisation_id"],
                         signed.authorisation_id)
        signing = [e for e in self.signing_entries()
                   if e["format"] == "ceremony-authorisation"]
        self.assertEqual(len(signing), 1)
        self.assertEqual(signing[0]["decision_id"],
                         signed.authorisation_id)
        self.assertEqual(signing[0]["proposal_id"],
                         "ceremony-2026-11-28-001")
        # Retention: the exact hashed bytes, named by the
        # authorisation id, mode 0600, re-hashing to the
        # envelope's evidence_hash.
        retained = self.retained()
        self.assertEqual(list(retained), [signed.authorisation_id])
        self.assertEqual(retained[signed.authorisation_id], ARTIFACT)
        retained_file = (self.ledger_home / "ceremony-evidence"
                         / signed.authorisation_id)
        self.assertEqual(
            stat.S_IMODE(retained_file.stat().st_mode), 0o600)
        self.assertEqual(
            hashlib.sha256(
                retained[signed.authorisation_id]).hexdigest(),
            signed.evidence_hash)

    def test_no_pin_authorisation_issued(self):
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            reason="initial_anchor", old_pin=None,
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertIsNone(signed.old_pin)
        self.assertEqual(
            verify_ceremony_authorisation(
                signed, public_key=self.pub,
                expected_signer_id=SIGNER,
                expected_old_pin=None), ())

    def test_unconfigured_operators_research_refusal(self):
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_OPERATORS": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operators_unconfigured")

    def test_unconfigured_seed_research_refusal(self):
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_seed_unconfigured")
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_unconfigured_evidence_research_refusal(self):
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_EVIDENCE_DIR": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_unconfigured")
        self.assertEqual(self.ceremony_entries(), [])

    def test_other_modes_still_work_with_ceremony_unconfigured(self):
        env = dict(self.env)
        env["AION_CEREMONY_OPERATORS"] = ""
        client = VerifierClient(
            verifier_env=env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)
        record = client.sealed_eval(["4", "9", "3.14"])
        self.assertIn("payload_hash", record)

    def test_production_startup_refusals(self):
        for over in ({"AION_CEREMONY_OPERATORS": ""},
                     {"AION_CEREMONY_EVIDENCE_DIR": ""},
                     {"AION_CEREMONY_SIGNING_SEED_PATH": ""}):
            env_over = {"AION_DEPLOYMENT_MODE": "production"}
            env_over.update(over)
            code, doc, _ = self.raw(self.body(), env_over=env_over)
            self.assertEqual(code, 3, msg=str(over))
            self.assertEqual(self.error_code(doc),
                             "verifier_misconfigured", msg=str(over))

    def test_malformed_evidence_dir_refuses_startup_in_research(self):
        for bad in ("relative/evidence", "/tmp/evidence/",
                    "/tmp/../evidence", "/tmp/./evidence"):
            code, doc, _ = self.raw(self.body(), env_over={
                "AION_CEREMONY_EVIDENCE_DIR": bad})
            self.assertEqual(code, 3, msg=bad)
            self.assertEqual(self.error_code(doc),
                             "verifier_misconfigured", msg=bad)

    def test_malformed_seed_path_refuses_startup_in_research(self):
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": "relative.seed"})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_unloadable_seed_refuses_startup(self):
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH":
                str(Path(self.tmp.name) / "missing.seed")})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def _write_seed_file(self, name, seed_bytes):
        path = Path(self.tmp.name) / name
        path.write_text(seed_bytes.hex() + "\n")
        path.chmod(0o600)
        return str(path)

    def test_seed_byte_equal_to_hmac_key_refuses_startup(self):
        seed_path = self._write_seed_file("same.seed", self.key.key)
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": seed_path})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_rfc_vector_seed_refuses_startup(self):
        seed_path = self._write_seed_file(
            "rfc.seed", bytes.fromhex(RFC_TEST1_SEED_HEX))
        code, doc, _ = self.raw(self.body(), env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": seed_path})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "verifier_misconfigured")

    def test_refused_seed_list_drift(self):
        # The verifier's refused seeds ARE signing's exported
        # list (imported unconditionally, no local copy): exact
        # set equality, not mere containment, so a seed added
        # on either side without the other fails here.
        self.assertIn(bytes.fromhex(RFC_TEST1_SEED_HEX),
                      _REFUSED_TEST_SEEDS)
        self.assertIn(bytes(range(32)), _REFUSED_TEST_SEEDS)
        import signing.ceremony_authorisation as ca
        self.assertEqual(set(_REFUSED_TEST_SEEDS),
                         set(ca.REFUSED_TEST_SEEDS))

    def test_load_config_pops_seed_and_key_paths(self):
        # In-process _load_config: both secret PATHS are
        # scrubbed from the environment after load (the seed
        # path like the key path), so a later environ dump or
        # child process cannot learn where the secrets live.
        with patch.dict(os.environ, self.env, clear=True):
            config = _load_config()
            self.assertIsNotNone(config.ceremony_signing_key)
            self.assertNotIn("AION_CEREMONY_SIGNING_SEED_PATH",
                             os.environ)
            self.assertNotIn("AION_VERIFIER_KEY_PATH",
                             os.environ)

    def test_config_grammar_refusals(self):
        bad_values = [
            OPERATOR + "," + OPERATOR,
            OPERATOR + ", operator-backup",
            OPERATOR + ",,operator-backup",
            OPERATOR + ",",
            "Operator-Uma",
            ",".join(f"operator-{i}" for i in range(65)),
        ]
        for value in bad_values:
            code, doc, _ = self.raw(self.body(), env_over={
                "AION_CEREMONY_OPERATORS": value})
            self.assertEqual(code, 3, msg=value)
            self.assertEqual(self.error_code(doc),
                             "verifier_misconfigured", msg=value)
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])

    def test_invented_operator_list_refused_as_malformed(self):
        body = self.body()
        body["authorised_operators"] = ["operator-mallory"]
        code, doc, _ = self.raw(body)
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc), "malformed_request")
        self.assertEqual(self.ceremony_entries(), [])

    def test_invented_operator_refused_unsigned_unledgered(self):
        code, doc, _ = self.raw(self.body(
            operator_id="operator-mallory"))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operator_not_authorised")
        self.assertIsNone(doc["result"])
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])
        with self.assertRaises(VerifierConfigError):
            self.authorise(operator_id="operator-mallory")

    def test_membership_before_evidence_resolution(self):
        # Unlisted operator + NONEXISTENT ref: the refusal is
        # the membership refusal (resolution never runs), and
        # nothing is retained or ledgered.
        code, doc, _ = self.raw(self.body(
            operator_id="operator-mallory",
            evidence_ref="no-such-file",
            evidence_hash="f" * 64))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operator_not_authorised")
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_malformed_bodies_burn_nothing(self):
        bad_bodies = [
            self.body(evidence_hash=CAND_HASH),
            self.body(evidence_hash=OLD_HASH),
            self.body(candidate={"cycle_seq": 42,
                                 "payload_hash": CAND_HASH,
                                 "signer_id": "snapshot-svc",
                                 "key_id": "key-0123456789abcdef"}),
            self.body(reason="lost_pin"),
            self.body(reason="chain_gap_recovery", old_pin=None),
            self.body(ceremony_id="-leading-dash"),
            self.body(evidence_hash="xyz"),
            self.body(evidence_ref=""),
        ]
        for body in bad_bodies:
            code, doc, _ = self.raw(body)
            self.assertEqual(code, 2, msg=str(body))
            self.assertEqual(self.error_code(doc),
                             "malformed_request", msg=str(body))
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_evidence_ref_grammar_refusals(self):
        bad_refs = [
            "/absolute/path",
            "../escape",
            "a/../b",
            "a/./b",
            "a//b",
            "trailing/",
            "back\\slash",
            "Upper-Case",
            "has space",
            ".hidden",
            "a..b",
            "x" * 513,
            "/".join(["seg"] * 9),
            "-leading-dash",
        ]
        for ref in bad_refs:
            code, doc, _ = self.raw(self.body(evidence_ref=ref))
            self.assertEqual(code, 2, msg=ref)
            self.assertEqual(self.error_code(doc),
                             "malformed_request", msg=ref)
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_evidence_subdirectory_ref_succeeds(self):
        sub = self.evidence_dir / "bundle"
        sub.mkdir()
        (sub / "report-2.json").write_bytes(ARTIFACT2)
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-009",
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="bundle/report-2.json")
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(signed.evidence_ref, "bundle/report-2.json")
        self.assertEqual(signed.evidence_hash, EVIDENCE_HASH2)

    def test_unresolvable_subcases_share_caller_visible_bytes(self):
        # Missing file, symlink escape, symlinked directory,
        # directory-as-artifact and empty file are ONE refusal
        # to the caller: identical error bytes across sub-cases
        # (the specific sub-case is logged verifier-side only).
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_bytes(b"outside the evidence root\n")
        os.symlink(outside, self.evidence_dir / "escape-link")
        os.symlink(Path(self.tmp.name), self.evidence_dir / "dir-link")
        (self.evidence_dir / "empty-file").write_bytes(b"")
        (self.evidence_dir / "a-dir").mkdir()
        # A FIFO leaf: without O_NONBLOCK on the leaf open the
        # verifier would block forever opening it, before the
        # S_ISREG check could refuse it (cycle 20 fix round).
        os.mkfifo(self.evidence_dir / "a-fifo")
        cases = ["no-such-file", "escape-link", "dir-link/outside.txt",
                 "empty-file", "a-dir", "a-fifo"]
        seen = []
        for ref in cases:
            code, doc, raw_stdout = self.raw(
                self.body(evidence_ref=ref, evidence_hash="f" * 64))
            self.assertEqual(code, 3, msg=ref)
            self.assertEqual(self.error_code(doc),
                             "ceremony_evidence_unresolvable",
                             msg=ref)
            seen.append(doc["error"])
        for error in seen[1:]:
            self.assertEqual(error, seen[0])
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_hash_mismatch_exit2_burns_nothing_and_retry_succeeds(self):
        code, doc, _ = self.raw(self.body(evidence_hash="f" * 64))
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_hash_mismatch")
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.signing_entries(), [])
        self.assertEqual(self.retained(), {})
        # Corrected retry with the same ceremony_id succeeds:
        # the mismatch burned nothing.
        envelope = self.authorise()
        self.assertIn("authorisation_id", envelope)

    def test_oversize_artifact_refused(self):
        big = self.evidence_dir / "big-bundle"
        big.write_bytes(b"x" * ((1 << 20) + 1))
        code, doc, _ = self.raw(self.body(
            evidence_ref="big-bundle",
            evidence_hash=hashlib.sha256(
                b"x" * ((1 << 20) + 1)).hexdigest()))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_too_large")
        self.assertEqual(self.ceremony_entries(), [])
        self.assertEqual(self.retained(), {})

    def test_ceremony_id_reuse_refused(self):
        self.authorise()
        code, doc, _ = self.raw(self.body(
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2"))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)

    def test_evidence_reuse_across_events_refused(self):
        # Same artifact (same COMPUTED hash) under a new
        # ceremony_id: the anti-replay scan keys on the computed
        # hash and refuses.
        self.authorise()
        code, doc, _ = self.raw(self.body(
            ceremony_id="ceremony-2026-11-28-777",
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"}))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)

    def test_identical_representation_refused(self):
        self.authorise()
        code, doc, _ = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")
        self.assertEqual(len(self.ceremony_entries()), 1)

    def test_refused_replays_retain_nothing_and_burn_nothing(self):
        # Scan-before-sign (cycle 20 fix round): BOTH replay
        # refusals run before signing and retention, so each
        # leaves the retained-evidence store count AND the
        # ceremony journal length exactly as the one committed
        # ceremony left them.
        self.authorise()
        self.assertEqual(len(self.retained()), 1)
        self.assertEqual(len(self.ceremony_entries()), 1)
        code, doc, _ = self.raw(self.body(
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"},
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2"))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")
        self.assertEqual(len(self.retained()), 1)
        self.assertEqual(len(self.ceremony_entries()), 1)
        code, doc, _ = self.raw(self.body(
            ceremony_id="ceremony-2026-11-28-777",
            candidate={"cycle_seq": 49, "payload_hash": "e" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"}))
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_evidence_reused")
        self.assertEqual(len(self.retained()), 1)
        self.assertEqual(len(self.ceremony_entries()), 1)

    def _signed_for_ledger(self, ceremony_id, evidence_hash,
                           evidence_ref):
        body = self.body(ceremony_id=ceremony_id,
                         evidence_hash=evidence_hash,
                         evidence_ref=evidence_ref)
        return sign_ceremony_authorisation(
            signing_key=self.seed_key, signer_id=SIGNER,
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"], ttl_seconds=900)

    def test_append_authorisation_rechecks_after_reload(self):
        # Concurrent duplicate issuance (cycle 20 fix round),
        # deterministic interleave of the reviewers' probe:
        # (a) the mode-path scan runs on one ledger instance
        # and passes (empty journal); (b) a competitor append
        # via a FRESH instance commits the pair; (c) the
        # mode-path append on another fresh instance must now
        # raise LedgerError from append_authorisation's own
        # post-reload re-check — not slip a second entry past
        # the stale scan. Exactly ONE journal entry survives
        # for the pair, in all three duplicate shapes (same
        # envelope, same ceremony_id/new evidence, new
        # ceremony_id/same evidence).
        recorded_at = "2026-11-28T00:00:00+00:00"
        signed = self._signed_for_ledger(
            "ceremony-race-001", EVIDENCE_HASH, "case-file-1")
        scanner = CeremonyAuthorisationLedger(self.ledger_home)
        self.assertEqual(scanner.entries(), [])
        competitor = CeremonyAuthorisationLedger(self.ledger_home)
        competitor.append_authorisation(signed,
                                        recorded_at=recorded_at)
        mode_path = CeremonyAuthorisationLedger(self.ledger_home)
        with self.assertRaises(LedgerError):
            mode_path.append_authorisation(
                signed, recorded_at=recorded_at)
        same_id = self._signed_for_ledger(
            "ceremony-race-001", EVIDENCE_HASH2, "case-file-2")
        with self.assertRaises(LedgerError):
            CeremonyAuthorisationLedger(
                self.ledger_home).append_authorisation(
                    same_id, recorded_at=recorded_at)
        same_evidence = self._signed_for_ledger(
            "ceremony-race-002", EVIDENCE_HASH, "case-file-1")
        with self.assertRaises(LedgerError):
            CeremonyAuthorisationLedger(
                self.ledger_home).append_authorisation(
                    same_evidence, recorded_at=recorded_at)
        entries = self.ceremony_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ceremony_id"],
                         "ceremony-race-001")
        self.assertEqual(entries[0]["evidence_hash"],
                         EVIDENCE_HASH)

    def test_retention_idempotence_and_collision(self):
        config = SimpleNamespace(home=str(self.ledger_home))
        _retain_ceremony_evidence(config, "a" * 64, ARTIFACT)
        # Byte-identical re-retention is already-retained.
        _retain_ceremony_evidence(config, "a" * 64, ARTIFACT)
        with self.assertRaises(_Refuse) as ctx:
            _retain_ceremony_evidence(config, "a" * 64, ARTIFACT2)
        self.assertEqual(ctx.exception.code, "ledger_failed")
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_dual_append_burn_on_post_commit_failure(self):
        self.ledger_home.mkdir(exist_ok=True)
        (self.ledger_home / "signing-ledger.json").write_text(
            "this is not a journal")
        code, doc, _ = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ledger_failed")
        self.assertIsNone(doc["result"])
        self.assertEqual(len(self.ceremony_entries()), 1)
        # Retention landed BEFORE the commit point, as designed.
        self.assertEqual(len(self.retained()), 1)
        code, doc, _ = self.raw(self.body())
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc), "ceremony_id_reused")

    def test_ttl_hard_cap_over_configured_ttl(self):
        client = VerifierClient(
            verifier_env=dict(self.env,
                              AION_VERIFIER_TTL_SECONDS="172800"),
            expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        body = self.body()
        envelope = client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        window = (datetime.fromisoformat(signed.expires_at)
                  - datetime.fromisoformat(signed.signed_at))
        self.assertEqual(window.total_seconds(), 900)

    def test_client_without_ceremony_pin_refuses_locally(self):
        client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id)
        body = self.body()
        with self.assertRaises(VerifierConfigError):
            client.ceremony_authorise(
                operator_id=body["operator_id"],
                ceremony_id=body["ceremony_id"],
                reason=body["reason"], old_pin=body["old_pin"],
                candidate=body["candidate"],
                evidence_hash=body["evidence_hash"],
                evidence_ref=body["evidence_ref"])


FAKE_ECHO_MODULE = '''
import json
import os
import sys

from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_to_dict,
    load_ceremony_seed,
    sign_ceremony_authorisation,
)

doc = json.loads(sys.stdin.read())
body = doc["body"]
key = load_ceremony_seed(os.environ["AION_CEREMONY_SIGNING_SEED_PATH"])
candidate = dict(body["candidate"])
candidate["cycle_seq"] = candidate["cycle_seq"] + 5
signed = sign_ceremony_authorisation(
    signing_key=key,
    signer_id=os.environ["AION_VERIFIER_SIGNER_ID"],
    operator_id=body["operator_id"],
    ceremony_id=body["ceremony_id"], reason=body["reason"],
    old_pin=body["old_pin"], candidate=candidate,
    evidence_hash=body["evidence_hash"],
    evidence_ref=body["evidence_ref"])
resp = {"v": "trust-response/1", "request_id": doc["request_id"],
        "mode": doc["mode"], "status": "ok",
        "result": {"signed_authorisation":
                   ceremony_authorisation_envelope_to_dict(signed)},
        "error": None}
sys.stdout.write(json.dumps(resp))
'''

FAKE_TAMPER_MODULE = '''
import json
import os
import sys

from signing.ceremony_authorisation import (
    ceremony_authorisation_envelope_to_dict,
    load_ceremony_seed,
    sign_ceremony_authorisation,
)

doc = json.loads(sys.stdin.read())
body = doc["body"]
key = load_ceremony_seed(os.environ["AION_CEREMONY_SIGNING_SEED_PATH"])
signed = sign_ceremony_authorisation(
    signing_key=key,
    signer_id=os.environ["AION_VERIFIER_SIGNER_ID"],
    operator_id=body["operator_id"],
    ceremony_id=body["ceremony_id"], reason=body["reason"],
    old_pin=body["old_pin"], candidate=body["candidate"],
    evidence_hash=body["evidence_hash"],
    evidence_ref=body["evidence_ref"])
envelope = ceremony_authorisation_envelope_to_dict(signed)
# Tamper: a well-formed hex128 signature that does not verify.
envelope["signature"] = "0" * 128
resp = {"v": "trust-response/1", "request_id": doc["request_id"],
        "mode": doc["mode"], "status": "ok",
        "result": {"signed_authorisation": envelope},
        "error": None}
sys.stdout.write(json.dumps(resp))
'''


class CeremonyClientEchoTests(CeremonyFixture):
    def _fake_client(self, module_name, source):
        fake_dir = Path(self.tmp.name) / "fake"
        fake_dir.mkdir(exist_ok=True)
        (fake_dir / f"{module_name}.py").write_text(source)
        return VerifierClient(
            module=module_name, verifier_env=self.env,
            expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub,
            pythonpath_extra=(str(fake_dir),))

    def test_client_refuses_envelope_bound_to_another_event(self):
        client = self._fake_client("fake_verifier_echo",
                                   FAKE_ECHO_MODULE)
        body = self.body()
        with self.assertRaises(VerifierProtocolError):
            client.ceremony_authorise(
                operator_id=body["operator_id"],
                ceremony_id=body["ceremony_id"],
                reason=body["reason"], old_pin=body["old_pin"],
                candidate=body["candidate"],
                evidence_hash=body["evidence_hash"],
                evidence_ref=body["evidence_ref"])

    def test_client_refuses_tampered_signature(self):
        # The envelope is structurally perfect and bound to the
        # requested event; only the Ed25519 signature is wrong.
        # Client-side verification (R8) must refuse it.
        client = self._fake_client("fake_verifier_tamper",
                                   FAKE_TAMPER_MODULE)
        body = self.body()
        with self.assertRaises(VerifierProtocolError) as ctx:
            client.ceremony_authorise(
                operator_id=body["operator_id"],
                ceremony_id=body["ceremony_id"],
                reason=body["reason"], old_pin=body["old_pin"],
                candidate=body["candidate"],
                evidence_hash=body["evidence_hash"],
                evidence_ref=body["evidence_ref"])
        self.assertIn("signature", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
