"""Tests for the separate-OS-user verifier identity
(Trust Boundary v2, mandate item 8; deploy/verifier-identity/).

Two layers:

* Simulation tests (always run): the key-placement rules refuse a
  key file with 0000 permissions, and a verifier client pointed
  at such a key path surfaces the refusal as a verifier CONFIG
  error (exit 3) — the boundary fails closed before anything is
  signed.
* A REAL end-to-end test, guarded by skipUnless(runuser exists
  AND the test process is root AND the `aion-verifier` user
  exists — i.e. deploy/verifier-identity/setup.sh has been run):
  one sealed_eval is executed by the verifier launched as
  `aion-verifier` via the run-verifier.sh wrapper against a temp
  registry/key/home owned by that user, an attestation must come
  back and verify, and reading the key as user `nobody` must fail
  with permission denied.

Why the staged code copy: the verifier executes the repo's Python
packages as `aion-verifier`, so the code must be readable by that
user. This checkout is root:nogroup mode 0660 — not readable by
aion-verifier — so the test stages a world-readable copy of the
same packages in the temp dir and points the wrapper at it via
AION_REPO_ROOT. That mirrors the documented deployment
requirement (README.md in deploy/verifier-identity/).
"""

import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import SigningError, generate_key_file, load_signing_key
from trust import protocol
from trust.attestation import verify_eval_attestation
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import SigningLedger

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "deploy" / "verifier-identity" / "run-verifier.sh"
PACKAGES = ("core", "eval", "memory", "oversight", "signing",
            "selfmod", "trust")
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9")]


def _aion_verifier():
    try:
        return pwd.getpwnam("aion-verifier")
    except KeyError:
        return None


class UnreadableKeySimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.key_path = base / "gate.key"
        self.key = generate_key_file(self.key_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_signing_key_refuses_0000_key(self):
        self.key_path.chmod(0o000)
        with self.assertRaises(SigningError):
            load_signing_key(self.key_path)

    def test_client_surfaces_config_refusal_for_unreadable_key(self):
        self.key_path.chmod(0o000)
        base = Path(self.tmp.name)
        env = {
            "AION_VERIFIER_KEY_PATH": str(self.key_path),
            "AION_VERIFIER_SIGNER_ID": "verifier-svc",
            "AION_VERIFIER_ACTOR_ID": "verifier-actor",
            "AION_REGISTRY_DIR": str(base / "registry"),
            "AION_VERIFIER_HOME": str(base / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
        }
        client = VerifierClient(verifier_env=env)
        with self.assertRaises(VerifierConfigError) as ctx:
            client.sealed_eval(["4", "9"])
        self.assertIn("verifier_misconfigured", str(ctx.exception))


@unittest.skipUnless(
    shutil.which("runuser") and os.geteuid() == 0
    and _aion_verifier() is not None,
    "requires runuser, root, and the aion-verifier user "
    "(run deploy/verifier-identity/setup.sh)")
class RealIdentityEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.pw = _aion_verifier()
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o755)  # traversable by aion-verifier and nobody

        # Stage a world-readable copy of the code (see docstring).
        self.staging = base / "code"
        for package in PACKAGES:
            shutil.copytree(
                REPO / package, self.staging / package,
                ignore=shutil.ignore_patterns("__pycache__"))
        # copytree also copies the source packages' 2770 modes
        # onto the staging root itself, which rglob does not yield.
        self.staging.chmod(0o755)
        for path in self.staging.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)

        # Verifier-owned layout mirroring the deployment.
        vroot = base / "verifier"
        self.home = vroot / "home"          # signing-ledger dir
        self.keys = vroot / "keys"
        self.registry_dir = base / "registry"
        self.keys.mkdir(parents=True)
        self.home.mkdir(parents=True)
        self.keys.chmod(0o700)
        self.key_path = self.keys / "gate.key"
        self.key = generate_key_file(self.key_path)
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt,
                                     expected, "test-actor")
        # Hand the verifier's world over to the verifier.
        for root in (vroot, self.registry_dir):
            for path in [root, *root.rglob("*")]:
                os.chown(path, self.pw.pw_uid, self.pw.pw_gid)
        vroot.chmod(0o755)
        self.home.chmod(0o700)
        self.keys.chmod(0o700)
        self.key_path.chmod(0o600)
        self.registry_dir.chmod(0o700)
        (self.registry_dir / "registry.json").chmod(0o600)

        # Root-owned 0600 env file for the wrapper.
        self.env_file = base / "verifier.env"
        self.env_file.write_text(
            f"AION_VERIFIER_KEY_PATH={self.key_path}\n"
            "AION_VERIFIER_SIGNER_ID=verifier-svc\n"
            "AION_VERIFIER_ACTOR_ID=verifier-actor\n"
            f"AION_REGISTRY_DIR={self.registry_dir}\n"
            f"AION_VERIFIER_HOME={self.home}\n"
            "AION_DEPLOYMENT_MODE=research\n")
        os.chown(self.env_file, 0, 0)
        self.env_file.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_verifier_as_verifier_user(self, mode, body):
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        wrapper_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
            "AION_VERIFIER_ENV_FILE": str(self.env_file),
            "AION_REPO_ROOT": str(self.staging),
        }
        result = subprocess.run(
            [str(WRAPPER)], input=raw, capture_output=True,
            timeout=60, env=wrapper_env)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode=mode)
        self.assertEqual(doc["status"], "ok",
                         msg=str(doc.get("error")))
        return doc["result"]

    def test_sealed_eval_through_verifier_user(self):
        answers = [expected for *_x, expected in ITEMS]
        result = self._run_verifier_as_verifier_user(
            "sealed_eval", {"answers": answers})
        record = result["attestation"]
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(record["payload"]["signer_id"],
                         "verifier-svc")
        # The attestation verifies under the key test-side (root
        # reading the verifier-owned key for verification only).
        key = load_signing_key(self.key_path)
        self.assertEqual(
            verify_eval_attestation(record, signing_key=key), ())
        # And the signature was ledgered in the verifier-owned
        # home before the response was returned.
        ledger = SigningLedger(self.home)
        formats = [e["format"] for e in ledger.entries()
                   if e["kind"] == "sign"]
        self.assertIn("sealed-eval", formats)

    def test_nobody_cannot_read_the_key(self):
        result = subprocess.run(
            ["runuser", "-u", "nobody", "--", "cat",
             str(self.key_path)],
            capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Permission denied", result.stderr)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
