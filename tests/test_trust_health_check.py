"""Deployment health-check tests — Trust Boundary v3.1, item 5.

A SYNTHETIC deployment is built in a temp dir (fake env file,
fake base with home/keys/anchors/registry, a generated key, a
small registry, a signing ledger with one claim entry pinned by
a signing anchor, a genesis budgets anchor, and a staged code
copy of the repo packages + wrapper). The checker
(deploy/verifier-identity/health_check.py) is run against it as
a subprocess and must exit 0; each drift case must make it exit
nonzero with the failed check NAMED in its output.

The checker's effective-mode probe goes through the REAL wrapper
(deploy/verifier-identity/run-verifier.sh) with
AION_VERIFIER_ENV_FILE / AION_REPO_ROOT overrides pointing at
the synthetic deployment — exactly the mechanism the live
deployment tests use — so the probe runs as the real
aion-verifier user via runuser. That is why the whole module
skips unless this process is root and the aion-verifier user
exists. The pure-function tests for group_membership_ok need
neither and live in their own unguarded class.

The fixture declares AION_DEPLOYMENT_MODE=production (with both
anchors configured), mirroring the live deployment; the checker
is invoked with --expect-mode production.
"""

import importlib.util
import json
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
from signing import generate_key_file
from trust.anchoring import initialise_anchor
from trust.ledger import SigningLedger

REPO = Path(__file__).resolve().parents[1]
HEALTH_CHECK = (REPO / "deploy" / "verifier-identity"
                / "health_check.py")
PACKAGES = ("core", "eval", "memory", "oversight", "signing",
            "selfmod", "trust")
GENESIS = "0" * 64
RECORDED_AT = "2026-11-20T12:00:00+00:00"


def _load_health_check_module():
    spec = importlib.util.spec_from_file_location(
        "aion_health_check", HEALTH_CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aion_verifier():
    try:
        return pwd.getpwnam("aion-verifier")
    except KeyError:
        return None


ROOTED = os.geteuid() == 0 and _aion_verifier() is not None \
    and shutil.which("runuser") is not None


class GroupMembershipTests(unittest.TestCase):
    """Pure-function contract: exactly one member, the verifier
    itself. No root, no group database."""

    @classmethod
    def setUpClass(cls):
        cls.hc = _load_health_check_module()

    def test_single_member_ok(self):
        self.assertTrue(self.hc.group_membership_ok(
            ["aion-verifier"], "aion-verifier"))

    def test_extra_member_not_ok(self):
        self.assertFalse(self.hc.group_membership_ok(
            ["aion-verifier", "builder"], "aion-verifier"))

    def test_empty_not_ok(self):
        self.assertFalse(self.hc.group_membership_ok(
            [], "aion-verifier"))

    def test_wrong_single_member_not_ok(self):
        self.assertFalse(self.hc.group_membership_ok(
            ["builder"], "aion-verifier"))


@unittest.skipUnless(
    ROOTED,
    "health-check deployment tests need root + the aion-verifier "
    "user + runuser (the probe goes through the real wrapper)")
class SyntheticDeploymentTests(unittest.TestCase):

    def setUp(self):
        self.pw = _aion_verifier()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        root.chmod(0o755)  # the verifier uid must traverse to base
        self.base = root / "base"
        self.etc = root / "etc"
        self.build_deployment()

    # -- fixture ------------------------------------------------------

    def build_deployment(self):
        base, etc = self.base, self.etc
        for sub in ("home", "keys", "anchors", "registry"):
            (base / sub).mkdir(parents=True)
        etc.mkdir(parents=True)
        etc.chmod(0o700)
        # Verifier-owned 0700 deployment directories.
        for path in (base, base / "home", base / "keys",
                     base / "anchors", base / "registry"):
            os.chown(path, self.pw.pw_uid, self.pw.pw_gid)
            path.chmod(0o700)
        # Signing key (generated as root, then handed to the
        # verifier user at 0600, as the ceremony would).
        generate_key_file(base / "keys" / "gate.key")
        os.chown(base / "keys" / "gate.key",
                 self.pw.pw_uid, self.pw.pw_gid)
        # Small sealed registry.
        registry = EvalRegistry(base / "registry")
        registry.add_sealed_item("sealed-1", "algebra", "2+2?", "4",
                                 "verifier-actor")
        registry.add_sealed_item("sealed-2", "algebra", "3*3?", "9",
                                 "verifier-actor")
        os.chown(base / "registry" / "registry.json",
                 self.pw.pw_uid, self.pw.pw_gid)
        # Signing ledger with ONE entry (a claim — no signature,
        # no budget), pinned by its anchor. The anchor ceremony
        # over a non-empty ledger is the documented
        # allow_nonempty_ceremony path.
        ledger = SigningLedger(base / "home")
        ledger.append_claim({"proposal_id": "health-fixture"},
                            recorded_at=RECORDED_AT,
                            signer_id="verifier-main")
        initialise_anchor(ledger, base / "anchors"
                          / "signing.anchor.json", kind="signing",
                          recorded_at=RECORDED_AT,
                          allow_nonempty_ceremony=True)
        # Budgets anchor pinning the GENESIS head of the (empty)
        # budget store, in the verifier's budgets-anchor format.
        (base / "anchors" / "budgets.anchor.json").write_text(
            json.dumps({"v": "budgets-anchor/1", "head": GENESIS,
                        "anchored_at": RECORDED_AT}, sort_keys=True),
            encoding="utf-8")
        for path in (base / "home" / "signing-ledger.json",
                     base / "anchors" / "signing.anchor.json",
                     base / "anchors" / "budgets.anchor.json"):
            os.chown(path, self.pw.pw_uid, self.pw.pw_gid)
        # Staged code copy: repo packages + the wrapper, root-owned
        # and world-readable, as in the live deployment.
        staged = base / "code"
        for package in PACKAGES:
            shutil.copytree(
                REPO / package, staged / package,
                ignore=shutil.ignore_patterns("__pycache__"))
        wrapper_dest = (staged / "deploy" / "verifier-identity"
                        / "run-verifier.sh")
        wrapper_dest.parent.mkdir(parents=True)
        shutil.copyfile(
            REPO / "deploy" / "verifier-identity" / "run-verifier.sh",
            wrapper_dest)
        staged.chmod(0o755)
        for path in staged.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        # Env file: root-owned 0600 in a root-owned 0700 dir,
        # production mode with both anchors configured.
        self.env_file = etc / "verifier.env"
        self.env_file.write_text(
            f"AION_VERIFIER_KEY_PATH={base}/keys/gate.key\n"
            "AION_VERIFIER_SIGNER_ID=verifier-main\n"
            "AION_VERIFIER_ACTOR_ID=verifier-actor\n"
            f"AION_REGISTRY_DIR={base}/registry\n"
            f"AION_VERIFIER_HOME={base}/home\n"
            "AION_VERIFIER_TTL_SECONDS=900\n"
            "AION_VERIFIER_PURPOSE=memory-commit\n"
            "AION_VERIFIER_PROPOSAL_BUDGET=25\n"
            "AION_VERIFIER_IDENTITY_BUDGET=500\n"
            f"AION_ANCHOR_PATH={base}/anchors/signing.anchor.json\n"
            "AION_ANCHOR_INIT=\n"
            f"AION_BUDGETS_ANCHOR_PATH="
            f"{base}/anchors/budgets.anchor.json\n"
            "AION_BUDGETS_ANCHOR_INIT=\n"
            "AION_DEPLOYMENT_MODE=production\n",
            encoding="utf-8")
        os.chown(self.env_file, 0, 0)
        self.env_file.chmod(0o600)

    # -- helpers ------------------------------------------------------

    def run_checker(self):
        return subprocess.run(
            [sys.executable, str(HEALTH_CHECK),
             "--env-file", str(self.env_file),
             "--base", str(self.base),
             "--repo", str(REPO),
             "--expect-mode", "production",
             "--user", "aion-verifier"],
            capture_output=True, timeout=120)

    def assert_drift_detected(self, result, check_name):
        out = result.stdout.decode("utf-8", errors="replace")
        self.assertNotEqual(
            result.returncode, 0,
            msg=out + result.stderr.decode("utf-8",
                                           errors="replace"))
        self.assertIn(f"FAIL {check_name}", out)

    # -- healthy + drift ----------------------------------------------

    def test_healthy_synthetic_deployment_passes(self):
        ledger_file = self.base / "home" / "signing-ledger.json"
        ledger_before = ledger_file.read_bytes()
        result = self.run_checker()
        out = result.stdout.decode("utf-8", errors="replace")
        self.assertEqual(
            result.returncode, 0,
            msg=out + result.stderr.decode("utf-8",
                                           errors="replace"))
        self.assertIn("health-check: 8/8 checks passed", out)
        # Read-only by design: the probe ledgered nothing and no
        # budget store was created by the checker's visit.
        self.assertEqual(ledger_file.read_bytes(), ledger_before)
        self.assertFalse((self.base / "home" / "budgets.json")
                         .exists())

    def test_drift_keys_dir_mode_0755(self):
        (self.base / "keys").chmod(0o755)
        self.assert_drift_detected(self.run_checker(), "directories")

    def test_drift_env_mode_blanked(self):
        text = self.env_file.read_text(encoding="utf-8")
        self.env_file.write_text(
            text.replace("AION_DEPLOYMENT_MODE=production",
                         "AION_DEPLOYMENT_MODE="), encoding="utf-8")
        self.env_file.chmod(0o600)
        self.assert_drift_detected(self.run_checker(), "env-file")

    def test_drift_signing_ledger_truncated(self):
        ledger_file = self.base / "home" / "signing-ledger.json"
        data = json.loads(ledger_file.read_text(encoding="utf-8"))
        data["entries"] = data["entries"][:-1]
        ledger_file.write_text(json.dumps(data), encoding="utf-8")
        self.assert_drift_detected(self.run_checker(), "anchors")

    def test_drift_staged_package_file_modified(self):
        target = self.base / "code" / "trust" / "protocol.py"
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n# drift\n")
        self.assert_drift_detected(self.run_checker(),
                                   "staged-code")

    def test_drift_staged_wrapper_modified(self):
        target = (self.base / "code" / "deploy" / "verifier-identity"
                  / "run-verifier.sh")
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n# drift\n")
        self.assert_drift_detected(self.run_checker(),
                                   "staged-code")

    def test_drift_key_file_mode_0644(self):
        (self.base / "keys" / "gate.key").chmod(0o644)
        self.assert_drift_detected(self.run_checker(), "key-file")


if __name__ == "__main__":
    unittest.main()
