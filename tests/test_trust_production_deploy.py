"""Live production-deployment tests — Trust Boundary v3, item 5
(external seats seat-gpt F5/F7, seat-gemini co-located rollback).

Two classes with two different guards:

* LiveDeploymentTests — skipUnless the LIVE deployment is
  provisioned: this process is root, /etc/aion-verifier/
  verifier.env carries non-empty signer/actor ids, and
  /var/lib/aion-verifier/keys/gate.key exists. The coordinator
  provisions the deployment AFTER these tests are written and
  then runs them; before provisioning they skip cleanly.
  Everything here runs against the REAL paths and the REAL
  wrapper (deploy/verifier-identity/run-verifier.sh).

* ProductionModeSpecTests — the AION_DEPLOYMENT_MODE spec in
  trust/verifier_main.py (and the wrapper allowlist): (a)
  production mode + missing AION_ANCHOR_PATH -> exit 3; (b)
  production mode + AION_ANCHOR_INIT=1 present -> exit 3; (c)
  the variable absent (or blank/unknown) -> exit 3 with error
  code deployment_mode_refused and nothing signed — there is no
  default mode (Trust Boundary v3.1, item 1); (c2) explicit
  AION_DEPLOYMENT_MODE=research + no anchor -> the verifier
  runs, the old unanchored research behaviour preserved via the
  explicit authorised path only; (d) production mode + a valid
  bootstrapped signing anchor + AION_BUDGETS_ANCHOR_PATH missing
  -> exit 3; (e) production mode + budgets anchor path set +
  AION_BUDGETS_ANCHOR_INIT=1 -> exit 3 and no budgets anchor
  file created. These use temp dirs, not the live paths.
  Until the coordinator's patch lands (detected by the string
  AION_DEPLOYMENT_MODE appearing in trust/verifier_main.py) the
  whole class skips, so the file is green pre-patch and the
  tests execute as soon as the patch is in.

Root is OUTSIDE the threat model (see
deploy/verifier-identity/README.md): several tests use root
deliberately for test SETUP only — reading the provisioned
registry file to learn the expected sealed answers, and reading
the key file to verify an attestation test-side. The adversarial
actions themselves are all performed as user `nobody` or as the
verifier user via the wrapper.

Declared residual (also in the deployment README): the signing
anchor and the signing ledger are BOTH verifier-owned, on the
same machine. A joint rollback of both to a consistent older
pair is undetectable from inside this deployment when it is
performed with root or the verifier uid — the two identities
that can write both. The builder identity can write NEITHER, so
the residual does not weaken the builder/verifier boundary it
was built for; whole-machine snapshot restore by the machine
owner is out of scope.
"""

import json
import os
import pwd
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file, load_signing_key
from trust import protocol
from trust.anchoring import initialise_anchor, load_anchor, verify_anchor
from trust.attestation import verify_eval_attestation
from trust.budgets import BudgetStore, GENESIS_CHAIN_HASH
from trust.ledger import SigningLedger

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "deploy" / "verifier-identity" / "run-verifier.sh"
PACKAGES = ("core", "eval", "memory", "oversight", "signing",
            "selfmod", "trust")

LIVE_ENV_FILE = Path("/etc/aion-verifier/verifier.env")
LIVE_BASE = Path("/var/lib/aion-verifier")
LIVE_KEY = LIVE_BASE / "keys" / "gate.key"
LIVE_HOME = LIVE_BASE / "home"
LIVE_ANCHORS = LIVE_BASE / "anchors"
LIVE_REGISTRY = LIVE_BASE / "registry"


def _parse_env_file(path):
    env = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _aion_verifier():
    try:
        return pwd.getpwnam("aion-verifier")
    except KeyError:
        return None


def _live_provisioned():
    if os.geteuid() != 0 or _aion_verifier() is None:
        return False
    if not shutil.which("runuser"):
        return False
    env = _parse_env_file(LIVE_ENV_FILE)
    return bool(env.get("AION_VERIFIER_SIGNER_ID")
                and env.get("AION_VERIFIER_ACTOR_ID")
                and LIVE_KEY.is_file())


LIVE = _live_provisioned()
LIVE_ENV = _parse_env_file(LIVE_ENV_FILE) if LIVE else {}


def _deployment_mode_supported():
    try:
        return "AION_DEPLOYMENT_MODE" in (
            REPO / "trust" / "verifier_main.py").read_text()
    except OSError:
        return False


def _ledger_head(home):
    ledger_file = Path(home) / "signing-ledger.json"
    if not ledger_file.exists():
        return None
    return SigningLedger(home).head()


def _ledger_entries(home):
    ledger_file = Path(home) / "signing-ledger.json"
    if not ledger_file.exists():
        return []
    return SigningLedger(home).entries()


def _stage_code(base):
    """World-readable copy of the repo packages under `base`, as
    in test_trust_identity.py: the verifier (and the nobody
    direct-invocation probe) execute the code as another user,
    and this checkout is not readable by them."""
    staging = base / "code"
    for package in PACKAGES:
        shutil.copytree(REPO / package, staging / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    staging.chmod(0o755)
    for path in staging.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return staging


def _runuser(user, argv, **kw):
    # Absolute path: callers pass restricted env dicts whose PATH
    # (e.g. /usr/bin:/bin) does not contain runuser (/usr/sbin).
    runuser = shutil.which("runuser") or "runuser"
    return subprocess.run([runuser, "-u", user, "--", *argv],
                          capture_output=True, timeout=60, **kw)


# ---------------------------------------------------------------------
# Live deployment (provisioned by the coordinator)
# ---------------------------------------------------------------------

@unittest.skipUnless(
    LIVE,
    "live deployment not provisioned (root + non-empty signer/"
    "actor ids in /etc/aion-verifier/verifier.env + "
    "/var/lib/aion-verifier/keys/gate.key required)")
class LiveDeploymentTests(unittest.TestCase):

    def setUp(self):
        self.pw = _aion_verifier()
        self.env = dict(LIVE_ENV)
        self.home = Path(self.env.get("AION_VERIFIER_HOME",
                                      str(LIVE_HOME)))
        self.key_path = Path(self.env.get("AION_VERIFIER_KEY_PATH",
                                          str(LIVE_KEY)))
        self.registry_dir = Path(self.env.get("AION_REGISTRY_DIR",
                                              str(LIVE_REGISTRY)))
        self.anchor_path = self.env.get("AION_ANCHOR_PATH", "")

    # -- helpers ------------------------------------------------------

    def run_wrapper(self, mode, body, extra_env=None):
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        wrapper_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
        }
        # The provisioned deployment runs from the staged,
        # root-owned code copy: the verifier uid cannot read this
        # checkout (deploy/verifier-identity/README.md).
        staged_code = LIVE_BASE / "code"
        if staged_code.is_dir():
            wrapper_env["AION_REPO_ROOT"] = str(staged_code)
        if extra_env:
            wrapper_env.update(extra_env)
        result = subprocess.run(
            [str(WRAPPER)], input=raw, capture_output=True,
            timeout=60, env=wrapper_env)
        return result, request_id

    def _skip_if_budget_consumed(self, result):
        """Replay/probe accounting is stateful by design: a live
        test's fixed transcript can be evaluated once per operator
        budget reset. A query_budget_exceeded refusal from the
        live deployment therefore means 'already demonstrated',
        not 'broken' — skip honestly instead of failing, and
        never silently pass."""
        if result.returncode != 3:
            return
        try:
            doc = protocol.strict_loads(
                result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
                what="response")
        except Exception:
            return
        if (doc.get("error") or {}).get("code") == \
                "query_budget_exceeded":
            self.skipTest(
                "live budget state already consumed this "
                "transcript; an operator budget reset is "
                "required before this live test can run again "
                "(see the provisioning ceremony record)")

    def registry_answers(self):
        """Expected sealed answers, in registry order. ROOT reads
        the registry file for test setup only — root is outside
        the threat model; no builder identity is used or needed."""
        data = json.loads(
            (self.registry_dir / "registry.json").read_text())
        return [item["expected"] for item in data["sealed_items"]]

    # -- live end-to-end (runs first: later tests rely on a
    #    ledger and anchor existing) ---------------------------------

    def test_10_live_sealed_eval_correct_answers_via_wrapper(self):
        answers = self.registry_answers()
        self.assertTrue(answers, "provisioned registry is empty")
        head_before = _ledger_head(self.home)
        entries_before = len(_ledger_entries(self.home))
        result, request_id = self.run_wrapper(
            "sealed_eval",
            {"answers": answers,
             "proposal_id": f"prodtest-{secrets.token_hex(4)}"})
        self._skip_if_budget_consumed(result)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(doc["status"], "ok", msg=str(doc.get("error")))
        record = doc["result"]["attestation"]
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertEqual(record["payload"]["signer_id"],
                         self.env["AION_VERIFIER_SIGNER_ID"])
        # Verifies under the provisioned key (root reads the key
        # for verification only, as a key-holding consumer would).
        key = load_signing_key(self.key_path)
        self.assertEqual(
            verify_eval_attestation(record, signing_key=key), ())
        # The signature was ledgered in the verifier-owned home.
        self.assertGreater(len(_ledger_entries(self.home)),
                           entries_before)
        self.assertNotEqual(_ledger_head(self.home), head_before)
        formats = [e["format"] for e in _ledger_entries(self.home)
                   if e["kind"] == "sign"]
        self.assertIn("sealed-eval", formats)

    def test_11_live_sealed_eval_wrong_answers_score_below_one(self):
        answers = self.registry_answers()
        wrong = [f"wrong-{i}" for i in range(len(answers))]
        result, request_id = self.run_wrapper(
            "sealed_eval",
            {"answers": wrong,
             "proposal_id": f"prodtest-{secrets.token_hex(4)}"})
        self._skip_if_budget_consumed(result)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(doc["status"], "ok", msg=str(doc.get("error")))
        record = doc["result"]["attestation"]
        self.assertLess(record["payload"]["score"], 1.0)
        key = load_signing_key(self.key_path)
        self.assertEqual(
            verify_eval_attestation(record, signing_key=key), ())

    def test_12_live_anchor_advanced_and_verifies(self):
        if not self.anchor_path:
            self.skipTest("deployment configures no signing anchor")
        anchor_file = Path(self.anchor_path)
        if not anchor_file.exists():
            self.skipTest("signing anchor not yet initialised")
        anchor = load_anchor(anchor_file)
        entries = _ledger_entries(self.home)
        self.assertTrue(entries, "signing ledger is empty")
        # After the evals above, the anchor pins the CURRENT head:
        # it advanced with every signature and verifies clean.
        self.assertEqual(anchor["seq"], len(entries))
        self.assertEqual(anchor["head"], entries[-1]["entry_hash"])
        self.assertEqual(
            verify_anchor(SigningLedger(self.home), anchor_file,
                          kind="signing"), ())

    def test_13_wrapper_refuses_blanked_deployment_mode(self):
        # Launcher-level contract (v3.1 item 1): a copy of the
        # live env file with the AION_DEPLOYMENT_MODE line blanked
        # must make the REAL wrapper refuse before launch —
        # nonzero exit, stderr naming the mode — and the live
        # ledger must not move. This is the drift case the
        # fail-open mode made dangerous: an env edit that used to
        # silently downgrade production to research.
        head_before = _ledger_head(self.home)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        base.chmod(0o755)
        lines = LIVE_ENV_FILE.read_text(
            encoding="utf-8").splitlines()
        blanked = [
            "AION_DEPLOYMENT_MODE="
            if line.startswith("AION_DEPLOYMENT_MODE=") else line
            for line in lines]
        if not any(line.startswith("AION_DEPLOYMENT_MODE=")
                   for line in blanked):
            blanked.append("AION_DEPLOYMENT_MODE=")
        env_file = base / "verifier.env"
        env_file.write_text("\n".join(blanked) + "\n",
                            encoding="utf-8")
        os.chown(env_file, 0, 0)
        env_file.chmod(0o600)
        wrapper_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
            "AION_VERIFIER_ENV_FILE": str(env_file),
        }
        staged_code = LIVE_BASE / "code"
        if staged_code.is_dir():
            wrapper_env["AION_REPO_ROOT"] = str(staged_code)
        result = subprocess.run(
            [str(WRAPPER)], input=b"{}", capture_output=True,
            timeout=60, env=wrapper_env)
        self.assertNotEqual(
            result.returncode, 0,
            msg=result.stdout.decode("utf-8", errors="replace"))
        self.assertIn(b"AION_DEPLOYMENT_MODE", result.stderr)
        self.assertEqual(_ledger_head(self.home), head_before)

    def test_14_wrapper_reports_effective_mode_production(self):
        # The effective mode is verified from INSIDE the running
        # verifier (v3.1 item 1): a junk verify_envelope probe
        # through the real wrapper with the real env file returns
        # exit 0 / valid:false, and the response document's
        # top-level deployment_mode — read via strict_loads on
        # the raw response, since decode_response's key set does
        # not surface it — is the mode the process actually
        # loaded, not a value read back from the env file here.
        result, request_id = self.run_wrapper(
            "verify_envelope", {"envelope": {}})
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["request_id"], request_id)
        self.assertEqual(doc["status"], "ok", msg=str(doc))
        self.assertEqual(doc["result"]["valid"], False)
        self.assertEqual(doc.get("deployment_mode"), "production")

    # -- OS denial battery as `nobody` --------------------------------

    def test_20_nobody_os_denial_battery(self):
        # Cannot read the key file.
        result = _runuser("nobody", ["cat", str(self.key_path)])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        # Cannot list the verifier-owned directories.
        for directory in (LIVE_BASE / "keys", self.home,
                          LIVE_ANCHORS, self.registry_dir):
            with self.subTest(directory=str(directory)):
                result = _runuser("nobody", ["ls", str(directory)])
                self.assertNotEqual(result.returncode, 0)
        # Cannot write into the verifier home; no probe survives.
        probe = self.home / "nobody-probe"
        result = _runuser("nobody", ["touch", str(probe)])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(probe.exists())
        # Cannot replace the registry file; its bytes are unmoved.
        registry_file = self.registry_dir / "registry.json"
        if registry_file.exists():
            before = registry_file.read_bytes()
            result = _runuser(
                "nobody",
                ["cp", "/etc/hostname", str(registry_file)])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(registry_file.read_bytes(), before)
        # Cannot read the signing ledger.
        ledger_file = self.home / "signing-ledger.json"
        if ledger_file.exists():
            result = _runuser("nobody", ["cat", str(ledger_file)])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")

    def test_21_direct_invocation_as_nobody_is_config_refusal(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        base.chmod(0o755)
        staging = _stage_code(base)
        head_before = _ledger_head(self.home)
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(staging),
            "HOME": str(base),
            # Real paths: nobody can neither read the key nor
            # write the ledger home, so config load must refuse.
            "AION_VERIFIER_KEY_PATH": str(self.key_path),
            "AION_VERIFIER_SIGNER_ID":
                self.env["AION_VERIFIER_SIGNER_ID"],
            "AION_VERIFIER_ACTOR_ID": self.env["AION_VERIFIER_ACTOR_ID"],
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home),
            # The live deployment's declared mode (production):
            # without it the v3.1 mode contract would refuse
            # first, and the refusal under test here must stay
            # the key/ledger access refusal, not the mode one.
            "AION_DEPLOYMENT_MODE":
                self.env.get("AION_DEPLOYMENT_MODE", "production"),
        }
        if self.anchor_path:
            env["AION_ANCHOR_PATH"] = self.anchor_path
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval", {"answers": ["x"]})
        result = _runuser(
            "nobody",
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, env=env)
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertTrue(doc["error"]["code"])
        # Nothing was signed: the ledger head is unmoved.
        self.assertEqual(_ledger_head(self.home), head_before)

    # -- wrapper discipline -------------------------------------------

    def test_30_wrapper_refuses_non_root_invocation(self):
        head_before = _ledger_head(self.home)
        # nobody cannot traverse this checkout's parents, so the
        # wrapper script itself is unreachable there; invoke a
        # world-executable copy — the root check under test fires
        # before any path-dependent work in the script.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        base.chmod(0o755)
        wrapper_copy = base / "run-verifier.sh"
        shutil.copyfile(WRAPPER, wrapper_copy)
        wrapper_copy.chmod(0o755)
        result = _runuser("nobody", [str(wrapper_copy)],
                          input=b"{}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"root", result.stderr)
        self.assertEqual(_ledger_head(self.home), head_before)

    def test_31_wrapper_probe_sees_only_allowlisted_environment(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        base.chmod(0o755)
        staging = _stage_code(base)
        # Replace the STAGED verifier_main with a probe: it reports
        # the uid and environment the REAL wrapper actually launches
        # it with. The repo's own copy is never touched.
        probe = staging / "trust" / "verifier_main.py"
        probe.write_text(
            "import json, os, sys\n"
            "sys.stdout.write(json.dumps({\n"
            "    'uid': os.getuid(),\n"
            "    'env': dict(os.environ)}))\n")
        probe.chmod(0o644)
        # Root-owned 0600 test env file naming allowlisted keys only.
        env_file = base / "verifier.env"
        env_file.write_text(
            f"AION_VERIFIER_KEY_PATH={self.key_path}\n"
            f"AION_VERIFIER_SIGNER_ID="
            f"{self.env['AION_VERIFIER_SIGNER_ID']}\n"
            f"AION_VERIFIER_ACTOR_ID="
            f"{self.env['AION_VERIFIER_ACTOR_ID']}\n"
            f"AION_REGISTRY_DIR={self.registry_dir}\n"
            f"AION_VERIFIER_HOME={self.home}\n"
            # The wrapper's launcher-level mode contract (v3.1)
            # refuses any env file without an explicit valid
            # mode before the probe module is ever launched.
            f"AION_DEPLOYMENT_MODE="
            f"{self.env.get('AION_DEPLOYMENT_MODE', 'production')}\n")
        os.chown(env_file, 0, 0)
        env_file.chmod(0o600)
        wrapper_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
            "AION_VERIFIER_ENV_FILE": str(env_file),
            "AION_REPO_ROOT": str(staging),
            # Sentinel: an orchestrator variable that must NOT leak
            # through the wrapper's clean environment.
            "AION_TEST_SENTINEL_LEAK": "must-not-appear",
        }
        result = subprocess.run(
            [str(WRAPPER)], input=b"{}", capture_output=True,
            timeout=60, env=wrapper_env)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        seen = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(seen["uid"], self.pw.pw_uid)
        seen_env = seen["env"]
        self.assertNotIn("AION_TEST_SENTINEL_LEAK", seen_env)
        allowlisted = {
            "AION_VERIFIER_KEY_PATH", "AION_VERIFIER_SIGNER_ID",
            "AION_VERIFIER_ACTOR_ID", "AION_REGISTRY_DIR",
            "AION_VERIFIER_HOME", "AION_VERIFIER_TTL_SECONDS",
            "AION_VERIFIER_PURPOSE", "AION_VERIFIER_PROPOSAL_BUDGET",
            "AION_VERIFIER_IDENTITY_BUDGET", "AION_ANCHOR_PATH",
            "AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_PATH",
            "AION_BUDGETS_ANCHOR_INIT", "AION_DEPLOYMENT_MODE",
        }
        # LC_CTYPE is injected by runuser/PAM itself, after the
        # wrapper's env -i scrub: it is not caller-controlled and
        # cannot be smuggled through the env file (not allowlisted
        # there), so it belongs with the fixed set.
        fixed = {"PATH", "HOME", "PYTHONPATH",
                 "PYTHONDONTWRITEBYTECODE", "LC_CTYPE"}
        self.assertLessEqual(set(seen_env), allowlisted | fixed)
        self.assertEqual(
            seen_env["PATH"],
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:"
            "/sbin:/bin")
        self.assertEqual(seen_env["HOME"],
                         self.pw.pw_dir)
        self.assertEqual(seen_env["PYTHONPATH"], str(staging))
        self.assertEqual(seen_env["PYTHONDONTWRITEBYTECODE"], "1")

    # -- rollback evidence on a COPY -----------------------------------

    def _copy_live_state(self, base):
        """Copy the live verifier home + anchors into `base`;
        returns (home_copy, anchor_copy)."""
        home_copy = base / "home"
        shutil.copytree(self.home, home_copy)
        anchors_copy = base / "anchors"
        if LIVE_ANCHORS.exists():
            shutil.copytree(LIVE_ANCHORS, anchors_copy)
        else:
            anchors_copy.mkdir()
        anchor_copy = None
        if self.anchor_path:
            candidate = anchors_copy / Path(self.anchor_path).name
            anchor_copy = candidate if candidate.exists() else None
        return home_copy, anchor_copy

    def _run_copied_verifier(self, home_copy, anchor_copy, staging,
                             registry_copy, *, with_anchor=True):
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(staging),
            "AION_VERIFIER_KEY_PATH": str(self.key_path),
            "AION_VERIFIER_SIGNER_ID":
                self.env["AION_VERIFIER_SIGNER_ID"],
            "AION_VERIFIER_ACTOR_ID": self.env["AION_VERIFIER_ACTOR_ID"],
            "AION_REGISTRY_DIR": str(registry_copy),
            "AION_VERIFIER_HOME": str(home_copy),
            # The copies exercise the PRODUCTION gate (v3.1 item
            # 1: no default mode — an absent variable would now
            # refuse as deployment_mode_refused and mask the
            # anchor behaviour under test). Cases (i)-(iii) must
            # still refuse at the SIGNING-anchor step, which
            # precedes budgets verification in _load_config.
            "AION_DEPLOYMENT_MODE":
                self.env.get("AION_DEPLOYMENT_MODE", "production"),
        }
        if with_anchor and anchor_copy is not None:
            env["AION_ANCHOR_PATH"] = str(anchor_copy)
        budgets_anchor_copy = (Path(home_copy).parent / "anchors"
                               / "budgets.anchor.json")
        if budgets_anchor_copy.exists():
            env["AION_BUDGETS_ANCHOR_PATH"] = \
                str(budgets_anchor_copy)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval", {"answers": ["x"]})
        return subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=60,
            cwd=str(staging), env=env)

    def test_40_rollback_on_a_copy_is_detected(self):
        entries = _ledger_entries(self.home)
        if not entries or not self.anchor_path \
                or not Path(self.anchor_path).exists():
            self.skipTest("needs a live ledger and signing anchor")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        staging = REPO  # root runs the repo code directly here
        registry_copy = base / "registry"
        shutil.copytree(self.registry_dir, registry_copy)

        # (i) Ledger truncated by one entry, anchor left current:
        # startup refuses (anchor ahead of the journal), exit 3.
        home_copy, anchor_copy = self._copy_live_state(base / "a")
        ledger_file = home_copy / "signing-ledger.json"
        data = json.loads(ledger_file.read_text())
        data["entries"] = data["entries"][:-1]
        ledger_file.write_text(json.dumps(data))
        result = self._run_copied_verifier(
            home_copy, anchor_copy, staging, registry_copy)
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertIn("anchor", doc["error"]["code"])
        self.assertEqual(
            len(json.loads(ledger_file.read_text())["entries"]),
            len(entries) - 1, "the refused run signed nothing new")

        # (ii) Ledger non-empty, anchor deleted: refusal —
        # anchor_missing_established_ledger at startup, exit 3.
        home_copy, anchor_copy = self._copy_live_state(base / "b")
        self.assertIsNotNone(anchor_copy)
        anchor_copy.unlink()
        result = self._run_copied_verifier(
            home_copy, anchor_copy, staging, registry_copy)
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["error"]["code"], "anchor_refused")

        # (iii) BOTH ledger and anchor deleted, anchor still
        # configured: the copy does NOT silently pass as genesis
        # in this configuration — a missing anchor with a
        # configured anchor path refuses (anchor_missing), exit 3.
        home_copy, anchor_copy = self._copy_live_state(base / "c")
        (home_copy / "signing-ledger.json").unlink()
        anchor_copy.unlink()
        result = self._run_copied_verifier(
            home_copy, anchor_copy, staging, registry_copy)
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))

        # (iv) DECLARED RESIDUAL: both deleted AND no anchor
        # configured (the unanchored / research configuration) —
        # the copy is indistinguishable from genesis and the
        # verifier runs. This is the co-located-rollback residual
        # stated in the module docstring: undetectable when the
        # attacker can write both files, which on the provisioned
        # deployment requires root or the verifier uid; the
        # builder identity can write neither.
        home_copy, anchor_copy = self._copy_live_state(base / "d")
        (home_copy / "signing-ledger.json").unlink()
        # The budgets store is part of the rolled-back state too:
        # a PARTIAL rollback that leaves budgets.json behind is
        # still caught — the verbatim ceremony transcript is
        # refused as a replay (observed live during provisioning).
        # Only the full-state rollback below is indistinguishable
        # from genesis in the unanchored configuration.
        budgets_copy = home_copy / "budgets.json"
        if budgets_copy.exists():
            budgets_copy.unlink()
        if anchor_copy is not None:
            anchor_copy.unlink()
        answers = [item["expected"] for item in json.loads(
            (registry_copy / "registry.json").read_text())
            ["sealed_items"]]
        env = {
            "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO),
            "AION_VERIFIER_KEY_PATH": str(self.key_path),
            "AION_VERIFIER_SIGNER_ID":
                self.env["AION_VERIFIER_SIGNER_ID"],
            "AION_VERIFIER_ACTOR_ID": self.env["AION_VERIFIER_ACTOR_ID"],
            "AION_REGISTRY_DIR": str(registry_copy),
            "AION_VERIFIER_HOME": str(home_copy),
            # Case (iv) is precisely the authorised RESEARCH
            # configuration (v3.1 item 1): no anchor configured,
            # so under the new contract the mode must be declared
            # explicitly — an absent variable would refuse as
            # deployment_mode_refused instead of demonstrating
            # the residual below.
            "AION_DEPLOYMENT_MODE": "research",
        }
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval",
            {"answers": answers,
             "proposal_id": f"rollback-residual-{secrets.token_hex(4)}"})
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=60,
            cwd=str(REPO), env=env)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(
            doc["result"]["attestation"]["payload"]["score"], 1.0)


# ---------------------------------------------------------------------
# Production mode (coordinator's AION_DEPLOYMENT_MODE patch)
# ---------------------------------------------------------------------

@unittest.skipUnless(
    _deployment_mode_supported(),
    "AION_DEPLOYMENT_MODE support not yet landed in "
    "trust/verifier_main.py (coordinator patch); tests are "
    "written against the spec and run after it")
class ProductionModeSpecTests(unittest.TestCase):
    """Temp-dir fixture, direct verifier invocation (the wrapper
    allowlist half of the patch is exercised by the live class
    once the provisioned env file carries the variable)."""

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
        for item_id, domain, prompt, expected in [
                ("sealed-1", "algebra", "2+2?", "4"),
                ("sealed-2", "algebra", "3*3?", "9")]:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(REPO),
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": "verifier-svc",
            "AION_VERIFIER_ACTOR_ID": "verifier-actor",
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_verifier(self, env_override):
        env = dict(self.env)
        env.update(env_override)
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "sealed_eval", {"answers": ["4", "9"]})
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=env)
        return result, request_id

    def sign_count(self):
        return len([e for e in _ledger_entries(self.home / "ledger")
                    if e["kind"] == "sign"])

    def test_a_production_mode_without_anchor_path_refuses(self):
        result, _rid = self.run_verifier(
            {"AION_DEPLOYMENT_MODE": "production"})
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertEqual(self.sign_count(), 0)

    def test_b_production_mode_with_anchor_init_present_refuses(self):
        # The INIT ceremony must not be silently repeatable in
        # production: its mere presence is a config refusal.
        anchor = Path(self.tmp.name) / "anchors" / "signing.anchor.json"
        result, _rid = self.run_verifier({
            "AION_DEPLOYMENT_MODE": "production",
            "AION_ANCHOR_PATH": str(anchor),
            "AION_ANCHOR_INIT": "1",
        })
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertEqual(self.sign_count(), 0)

    def bootstrap_signing_anchor(self):
        """A valid signing anchor for the (empty) signing ledger,
        bootstrapped in a temp dir outside the ledger directory —
        so in tests (d)/(e) the production SIGNING-anchor check
        passes and cannot mask the BUDGETS half of the gate: the
        only production requirement left unsatisfied there is the
        budgets one under test."""
        anchors = Path(self.tmp.name) / "anchors"
        anchors.mkdir(exist_ok=True)
        anchor = anchors / "signing.anchor.json"
        initialise_anchor(
            SigningLedger(self.home / "ledger"), anchor,
            kind="signing", recorded_at="2026-11-20T12:00:00+00:00")
        return anchor

    def test_d_production_mode_without_budgets_anchor_path_refuses(self):
        # Production + a valid, bootstrapped signing anchor +
        # AION_BUDGETS_ANCHOR_PATH missing: the budgets half of
        # the production gate refuses on its own (exit 3, error
        # document, nothing signed).
        anchor = self.bootstrap_signing_anchor()
        result, _rid = self.run_verifier({
            "AION_DEPLOYMENT_MODE": "production",
            "AION_ANCHOR_PATH": str(anchor),
        })
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertEqual(self.sign_count(), 0)

    def test_e_production_mode_with_budgets_anchor_init_refuses(self):
        # Production + budgets anchor path set +
        # AION_BUDGETS_ANCHOR_INIT=1: the INIT ceremony flag is
        # refused in production (exit 3), exactly as the signing
        # AION_ANCHOR_INIT is in test (b) — and the refusal must
        # not create the budgets anchor file it was asked to
        # bootstrap, nor sign anything.
        anchor = self.bootstrap_signing_anchor()
        budgets_anchor = (Path(self.tmp.name) / "anchors"
                          / "budgets.anchor.json")
        result, _rid = self.run_verifier({
            "AION_DEPLOYMENT_MODE": "production",
            "AION_ANCHOR_PATH": str(anchor),
            "AION_BUDGETS_ANCHOR_PATH": str(budgets_anchor),
            "AION_BUDGETS_ANCHOR_INIT": "1",
        })
        self.assertEqual(result.returncode, 3,
                         msg=result.stdout.decode("utf-8",
                                                  errors="replace"))
        doc = protocol.strict_loads(
            result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
            what="response")
        self.assertEqual(doc["status"], "error")
        self.assertEqual(self.sign_count(), 0)
        self.assertFalse(budgets_anchor.exists())

    def test_c_absent_mode_refuses_deployment_mode_refused(self):
        # NEW contract (Trust Boundary v3.1, item 1): there is NO
        # default mode. Variable absent — and equally blank or
        # unknown — refuses startup fail-closed with error code
        # deployment_mode_refused (exit 3) and nothing signed:
        # blanking the mode line can no longer silently downgrade
        # a production deployment to research mode.
        for override in ({}, {"AION_DEPLOYMENT_MODE": ""},
                         {"AION_DEPLOYMENT_MODE": "bogus"}):
            with self.subTest(override=override):
                result, _rid = self.run_verifier(override)
                self.assertEqual(
                    result.returncode, 3,
                    msg=result.stdout.decode("utf-8",
                                             errors="replace"))
                doc = protocol.strict_loads(
                    result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
                    what="response")
                self.assertEqual(doc["status"], "error")
                self.assertEqual(doc["error"]["code"],
                                 "deployment_mode_refused")
                self.assertEqual(self.sign_count(), 0)

    def bootstrap_budgets_anchor(self):
        """A valid budgets anchor pinning the budget store's
        GENESIS head (the store has recorded no queries yet), in
        the verifier's budgets-anchor format — exactly the three
        keys {"v", "head", "anchored_at"} that
        trust/verifier_main.py's _write_budgets_anchor writes and
        its (strict) _read_budgets_anchor reads."""
        anchors = Path(self.tmp.name) / "anchors"
        anchors.mkdir(exist_ok=True)
        budgets_anchor = anchors / "budgets.anchor.json"
        genesis_head = BudgetStore(
            self.home / "ledger" / "budgets.json").head_hash()
        self.assertEqual(genesis_head, GENESIS_CHAIN_HASH)
        budgets_anchor.write_text(
            json.dumps({"v": "budgets-anchor/1",
                        "head": genesis_head,
                        "anchored_at": "2026-11-20T12:00:00+00:00"},
                       sort_keys=True),
            encoding="utf-8")
        return budgets_anchor

    def test_f_production_mode_successful_run_reports_production(self):
        # The full production gate satisfied: a valid bootstrapped
        # signing anchor AND a budgets anchor at the genesis head.
        # The verifier runs, signs the sealed eval, and its
        # response reports deployment_mode == "production" — the
        # mode is proven from inside the process, not assumed.
        anchor = self.bootstrap_signing_anchor()
        budgets_anchor = self.bootstrap_budgets_anchor()
        result, request_id = self.run_verifier({
            "AION_DEPLOYMENT_MODE": "production",
            "AION_ANCHOR_PATH": str(anchor),
            "AION_BUDGETS_ANCHOR_PATH": str(budgets_anchor),
        })
        self.assertEqual(
            result.returncode, 0,
            msg=result.stdout.decode("utf-8", errors="replace")
            + result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(doc["status"], "ok", msg=str(doc.get("error")))
        self.assertEqual(doc.get("deployment_mode"), "production")
        self.assertEqual(
            doc["result"]["attestation"]["payload"]["score"], 1.0)
        self.assertEqual(self.sign_count(), 1)

    @unittest.skipUnless(
        os.geteuid() == 0 and _aion_verifier() is not None,
        "wrapper-refusal tests need root + the aion-verifier user "
        "(the real wrapper refuses non-root / missing-user first)")
    def test_g_wrapper_refuses_absent_mode_and_duplicate_key(self):
        # These go through the REAL run-verifier.sh with an
        # AION_VERIFIER_ENV_FILE override — no live deployment
        # involved. (i) Mode line absent: exit 1, stderr names
        # AION_DEPLOYMENT_MODE. (ii) A duplicated key line: exit 1,
        # stderr names the duplicate.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        base.chmod(0o755)
        common = (
            "AION_VERIFIER_KEY_PATH=/var/lib/aion-verifier/keys/"
            "gate.key\n"
            "AION_VERIFIER_SIGNER_ID=verifier-main\n"
            "AION_VERIFIER_ACTOR_ID=verifier-actor\n"
            "AION_REGISTRY_DIR=/var/lib/aion-verifier/registry\n"
            "AION_VERIFIER_HOME=/var/lib/aion-verifier/home\n")
        wrapper_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
        }
        # (i) No AION_DEPLOYMENT_MODE line at all.
        env_file = base / "verifier.env"
        env_file.write_text(common, encoding="utf-8")
        os.chown(env_file, 0, 0)
        env_file.chmod(0o600)
        result = subprocess.run(
            [str(WRAPPER)], input=b"{}", capture_output=True,
            timeout=60,
            env={**wrapper_env,
                 "AION_VERIFIER_ENV_FILE": str(env_file)})
        self.assertEqual(
            result.returncode, 1,
            msg=result.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"AION_DEPLOYMENT_MODE", result.stderr)
        # (ii) A duplicated allowlisted key line.
        env_file.write_text(
            common
            + "AION_VERIFIER_SIGNER_ID=verifier-main\n"
            + "AION_DEPLOYMENT_MODE=production\n",
            encoding="utf-8")
        os.chown(env_file, 0, 0)
        env_file.chmod(0o600)
        result = subprocess.run(
            [str(WRAPPER)], input=b"{}", capture_output=True,
            timeout=60,
            env={**wrapper_env,
                 "AION_VERIFIER_ENV_FILE": str(env_file)})
        self.assertEqual(
            result.returncode, 1,
            msg=result.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"duplicate", result.stderr.lower())
        self.assertIn(b"AION_VERIFIER_SIGNER_ID", result.stderr)

    def test_c2_explicit_research_mode_without_anchor_still_runs(self):
        # Explicit AION_DEPLOYMENT_MODE=research is the ONLY
        # research path: unanchored operation is the preserved
        # behaviour (explicitly NOT rollback-protected — see the
        # deployment README), entered via the authorised explicit
        # value, never via absence.
        result, request_id = self.run_verifier(
            {"AION_DEPLOYMENT_MODE": "research"})
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", errors="replace"))
        doc = protocol.decode_response(
            result.stdout, expected_request_id=request_id,
            expected_mode="sealed_eval")
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(
            doc["result"]["attestation"]["payload"]["score"], 1.0)
        self.assertEqual(self.sign_count(), 1)


if __name__ == "__main__":
    unittest.main()
