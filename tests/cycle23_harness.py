"""Shared provisioning harness for cycle 23 (DESIGN-FINAL R2) —
NOT a test module: it is imported by the cycle-23 suites and
must not be collected as tests (no TestCase, no test_*
functions).

``provision_production_home`` builds a disposable verifier
home in a temp dir and performs the R2 bootstrap order, which
is forced by production's INIT refusal:

1. ONE research-mode verifier invocation with ALL INIT flags
   set (AION_ANCHOR_INIT, AION_BUDGETS_ANCHOR_INIT,
   AION_CEREMONY_CONSUMPTION_ANCHOR_INIT) and a deliberately
   malformed request — a well-formed protocol envelope whose
   gate body is empty, so config load runs (initialising the
   signing / budgets / ceremony-consumption anchors on empty
   journals) and the mode then refuses the body as malformed
   (exit 2) before anything can be signed. The harness asserts
   the signing ledger gained NO entries.
2. The INIT keys are then REMOVED from the env and
   AION_DEPLOYMENT_MODE flips to "production". The returned
   env is the full production allowlist (wiring-required keys
   + the production-required ceremony keys).

The AION_PIN_* adopter variables are a SEPARATE mapping and
never enter the verifier env (see the production e2e's
negative tests).
"""

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from trust import protocol
from trust.ledger import SigningLedger
from trust.supersession_approval_tool import (
    approver_public_key_for,
    generate_approver_key_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
SNAP_SIGNER = "seat-3"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
CAL = b'{"log":1}'

_INIT_KEYS = ("AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_INIT",
              "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT")


@dataclass
class ProductionHome:
    """A provisioned production-mode verifier home plus the
    out-of-band pins and adopter pieces built against it."""
    base: Path
    verifier_home: Path          # AION_VERIFIER_HOME (ledger dir)
    key_path: Path
    verifier_key_id: str         # HMAC gate key id (key-<16 hex>)
    seed_path: Path
    ceremony_key_id: str         # ceremony pub id (pub-<16 hex>)
    pub: object                  # CeremonyPublicKey
    evidence_dir: Path
    registry_dir: Path
    anchor_paths: dict           # name -> Path
    env: dict                    # production verifier env
    snapshot_key_path: Path      # fresh snapshot signing key file
    snapshot_key: object         # its SigningKey
    bootstrap_returncode: int
    approver_seed_path: object = None  # cycle 25 approver seed file
    approver_key: object = None        # SupersessionApproverKey
    approver_pub: object = None        # SupersessionApproverPublicKey
    _tmp: object = field(default=None, repr=False)

    def cleanup(self):
        if self._tmp is not None:
            self._tmp.cleanup()


def _run_verifier_once(env, raw_request):
    full_env = {"PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(REPO_ROOT),
                "HOME": str(Path.home())}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "trust.verifier_main"],
        input=raw_request, capture_output=True, timeout=60,
        cwd=str(REPO_ROOT), env=full_env)


def provision_production_home(base=None):
    """Provision a disposable production verifier home.

    When ``base`` is None a TemporaryDirectory is created and
    owned by the returned object (call ``cleanup()``). When a
    base is given, the caller owns its lifetime.
    """
    tmp = None
    if base is None:
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    base.chmod(0o700)

    home = base / "verifier-home"
    home.mkdir(exist_ok=True)
    home.chmod(0o700)
    verifier_home = home / "ledger"
    key_path = home / "gate.key"
    verifier_key = generate_key_file(key_path)
    seed_path = base / "ceremony.seed"
    seed_key = generate_ceremony_key_file(seed_path)
    pub = ceremony_public_key_for(seed_key)
    # Cycle 25: a dedicated approver key (approval-tool side);
    # the verifier env carries only its PUBLIC key hex —
    # production with the ceremony seed configured requires it.
    approver_seed_path = base / "approver.seed"
    approver_key = generate_approver_key_file(approver_seed_path)
    approver_pub = approver_public_key_for(approver_key)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    registry_dir = base / "registry"
    registry = EvalRegistry(registry_dir)
    for item_id, domain, prompt, expected in ITEMS:
        registry.add_sealed_item(item_id, domain, prompt, expected,
                                 "test-actor")
    anchors_dir = base / "anchors"
    anchors_dir.mkdir(exist_ok=True)
    anchor_paths = {
        "signing": anchors_dir / "signing.anchor.json",
        "budgets": anchors_dir / "budgets.anchor.json",
        "consumption": anchors_dir / "consumption.anchor.json",
    }
    # A fresh snapshot signing key for the adopter side: outside
    # every state dir and pin dir the suites use under base's
    # per-test subdirs, and never the verifier's key.
    snapshot_key_path = base / "snapshot.key"
    snapshot_key = generate_key_file(snapshot_key_path)

    steady_env = {
        "AION_VERIFIER_KEY_PATH": str(key_path),
        "AION_VERIFIER_SIGNER_ID": SIGNER,
        "AION_VERIFIER_ACTOR_ID": ACTOR,
        "AION_REGISTRY_DIR": str(registry_dir),
        "AION_VERIFIER_HOME": str(verifier_home),
        "AION_ANCHOR_PATH": str(anchor_paths["signing"]),
        "AION_BUDGETS_ANCHOR_PATH": str(anchor_paths["budgets"]),
        "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH":
            str(anchor_paths["consumption"]),
        "AION_CEREMONY_OPERATORS": OPERATORS,
        "AION_CEREMONY_EVIDENCE_DIR": str(evidence_dir),
        "AION_CEREMONY_SIGNING_SEED_PATH": str(seed_path),
        "AION_SUPERSESSION_APPROVER_PUBLIC_KEY":
            approver_pub.public_key.hex(),
    }

    # (1) Research-mode bootstrap: all INIT flags set, one
    # deliberately malformed request (well-formed envelope,
    # empty gate body) so _load_config initialises the anchors
    # on the empty journals and the mode body never runs.
    bootstrap_env = dict(steady_env)
    bootstrap_env["AION_DEPLOYMENT_MODE"] = "research"
    for name in _INIT_KEYS:
        bootstrap_env[name] = "1"
    raw = protocol.encode_request("bootstrap-1", "gate", {})
    result = _run_verifier_once(bootstrap_env, raw)
    if result.returncode != 2:
        raise AssertionError(
            "R2 bootstrap: expected exit 2 (malformed gate body) "
            f"from the research INIT invocation, got "
            f"{result.returncode}: "
            f"{result.stdout!r} {result.stderr!r}")
    ledger = SigningLedger(verifier_home)
    if ledger.entries() != []:
        raise AssertionError(
            "R2 bootstrap: the malformed bootstrap request "
            "resulted in signing-ledger entries; no mode body "
            "may run during anchor initialisation")
    for name, path in anchor_paths.items():
        if not path.is_file():
            raise AssertionError(
                f"R2 bootstrap: the {name} anchor was not "
                f"initialised at {path}")

    # (2) Strip INIT, flip to production.
    production_env = dict(steady_env)
    production_env["AION_DEPLOYMENT_MODE"] = "production"

    return ProductionHome(
        base=base, verifier_home=verifier_home,
        key_path=key_path, verifier_key_id=verifier_key.key_id,
        seed_path=seed_path, ceremony_key_id=seed_key.key_id,
        pub=pub, evidence_dir=evidence_dir,
        registry_dir=registry_dir, anchor_paths=anchor_paths,
        env=production_env, snapshot_key_path=snapshot_key_path,
        snapshot_key=snapshot_key,
        bootstrap_returncode=result.returncode,
        approver_seed_path=approver_seed_path,
        approver_key=approver_key, approver_pub=approver_pub,
        _tmp=tmp)
