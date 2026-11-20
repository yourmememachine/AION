#!/usr/bin/env python3
"""Reproducible deployment health check for the AION verifier
(Trust Boundary v3.1, item 5).

READ-ONLY against the deployment: this checker never signs,
never records a budget query and never consumes a transcript.
It only reads files and filesystem metadata, verifies the
anchors against the live ledgers, compares the staged code copy
against the repo, and runs ONE verify_envelope probe with a
structurally junk envelope ({"envelope": {}}) through the real
wrapper — a request that returns valid:false, ledgers nothing
and consumes no budget, but whose response document reports the
effective deployment_mode from INSIDE the running verifier
process.

Run as root (health-check.sh enforces that and execs this file
with PYTHONPATH=<repo root>):

    health_check.py [--env-file /etc/aion-verifier/verifier.env]
                    [--base /var/lib/aion-verifier]
                    [--repo <repo this script lives in>]
                    [--expect-mode production]
                    [--user aion-verifier]

Exit 0 iff every check passes. One line per check is printed
(PASS/FAIL + name + detail) plus a summary line.

Honest scope: this is a snapshot check at run time, like the
provisioning evidence it replaces. It detects drift (permission,
owner, env, wrapper and staged-code changes, anchor/ledger
disagreement) at the moment it runs; it cannot prove nothing
changed between runs, and root compromise is verifier
compromise — root can rewrite every file this checker reads.
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path

PACKAGES = ("core", "eval", "memory", "oversight", "signing",
            "selfmod", "trust")
WRAPPER_REL = Path("deploy") / "verifier-identity" / "run-verifier.sh"

# The wrapper's allowlist (deploy/verifier-identity/run-verifier.sh),
# replicated so the env file is judged by the same rules the
# launcher applies: plain KEY=VALUE lines, allowlisted names only.
ALLOWED_KEYS = (
    "AION_VERIFIER_KEY_PATH",
    "AION_VERIFIER_SIGNER_ID",
    "AION_VERIFIER_ACTOR_ID",
    "AION_REGISTRY_DIR",
    "AION_VERIFIER_HOME",
    "AION_VERIFIER_TTL_SECONDS",
    "AION_VERIFIER_PURPOSE",
    "AION_VERIFIER_PROPOSAL_BUDGET",
    "AION_VERIFIER_IDENTITY_BUDGET",
    "AION_ANCHOR_PATH",
    "AION_ANCHOR_INIT",
    "AION_BUDGETS_ANCHOR_PATH",
    "AION_BUDGETS_ANCHOR_INIT",
    "AION_DEPLOYMENT_MODE",
)
REQUIRED_KEYS = (
    "AION_VERIFIER_KEY_PATH",
    "AION_VERIFIER_SIGNER_ID",
    "AION_VERIFIER_ACTOR_ID",
    "AION_REGISTRY_DIR",
    "AION_VERIFIER_HOME",
)
_LINE_RE = re.compile(r"^([A-Z_]+)=(.*)$")

# The canonical passwd home of the verifier user on a normally
# provisioned machine. A parameterised (--base) fixture/staging
# deployment lives elsewhere, so the passwd home is accepted when
# it is either the deployment's own home or this canonical one;
# the deployment's configured home is separately required to be
# <base>/home by the directories/env checks below.
CANONICAL_HOME = "/var/lib/aion-verifier/home"


def group_membership_ok(members, user) -> bool:
    """True iff `members` is exactly [user]: the verifier's group
    must have the verifier as its SOLE member. An extra member is
    another OS identity inside the boundary; an empty list means
    the verifier itself is not accounted for. Pure function —
    tests exercise it without touching the real group database."""
    members = list(members)
    return len(members) == 1 and members[0] == user


def _parse_env_strict(path):
    """Parse the env file under the wrapper's allowlist rules.
    Returns (config, errors): config maps allowlisted keys to
    their raw values; errors lists every rule violation."""
    config = {}
    errors = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [f"env file unreadable: {exc}"]
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            errors.append(f"malformed line: {raw_line!r}")
            continue
        key, value = match.group(1), match.group(2)
        if key not in ALLOWED_KEYS:
            errors.append(f"{key} is not an allowlisted variable")
            continue
        config[key] = value
    return config, errors


def _parse_env_lenient(path):
    """Best-effort KEY=VALUE map for locating deployment paths,
    used even when the strict parse (a separate check) fails, so
    one env drift does not mask the other checks' results."""
    config = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return config
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def _owner_mode(path):
    st = os.stat(path)
    return pwd.getpwuid(st.st_uid).pw_name, st.st_uid, \
        oct(st.st_mode & 0o777)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_files(root):
    """{relative path: absolute path} for every file under root,
    ignoring __pycache__ directories and .pyc files."""
    out = {}
    root = Path(root)
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            out[str(path.relative_to(root))] = path
    return out


class Checker:
    def __init__(self, env_file, base, repo, expect_mode, user):
        self.env_file = Path(env_file)
        self.base = Path(base)
        self.repo = Path(repo)
        self.expect_mode = expect_mode
        self.user = user
        self.results = []
        self.config = _parse_env_lenient(self.env_file)
        try:
            self.pw = pwd.getpwnam(user)
        except KeyError:
            self.pw = None

    def record(self, name, ok, detail):
        self.results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}",
              flush=True)
        return ok

    # -- individual checks -------------------------------------------

    def check_user(self):
        if self.pw is None:
            return self.record(
                "user", False, f"user {self.user} does not exist")
        shell = self.pw.pw_shell
        home = self.pw.pw_dir
        problems = []
        if Path(shell).name != "nologin":
            problems.append(f"shell is {shell}, not nologin")
        expected_home = str(self.base / "home")
        if home not in (expected_home, CANONICAL_HOME):
            problems.append(
                f"home is {home}, expected {expected_home}")
        if problems:
            return self.record("user", False, "; ".join(problems))
        return self.record(
            "user", True,
            f"{self.user} exists, shell {shell}, home {home}")

    def check_group(self):
        if self.pw is None:
            return self.record(
                "group-membership", False,
                f"user {self.user} does not exist")
        try:
            group = grp.getgrgid(self.pw.pw_gid)
        except KeyError:
            return self.record(
                "group-membership", False,
                f"primary gid {self.pw.pw_gid} has no group entry")
        # Effective membership: the group's member list PLUS every
        # user whose PRIMARY group this is (primary members are
        # not listed in gr_mem — the verifier itself is one).
        members = set(group.gr_mem)
        for entry in pwd.getpwall():
            if entry.pw_gid == self.pw.pw_gid:
                members.add(entry.pw_name)
        members = sorted(members)
        ok = group_membership_ok(members, self.user)
        return self.record(
            "group-membership", ok,
            f"group {group.gr_name} effective members: "
            f"{members if members else '[]'}")

    def check_directories(self):
        problems = []
        for label, path in (("base", self.base),
                            ("home", self.base / "home"),
                            ("keys", self.base / "keys"),
                            ("anchors", self.base / "anchors"),
                            ("registry", self.base / "registry")):
            if not path.is_dir():
                problems.append(f"{label} dir {path} missing")
                continue
            owner, _uid, mode = _owner_mode(path)
            if owner != self.user or mode != "0o700":
                problems.append(
                    f"{label} dir {path} is {owner} {mode}, "
                    f"expected {self.user} 0o700")
        env_dir = self.env_file.parent
        if not env_dir.is_dir():
            problems.append(f"env dir {env_dir} missing")
        else:
            owner, _uid, mode = _owner_mode(env_dir)
            if owner != "root" or mode != "0o700":
                problems.append(
                    f"env dir {env_dir} is {owner} {mode}, "
                    f"expected root 0o700")
        if not self.env_file.is_file():
            problems.append(f"env file {self.env_file} missing")
        else:
            owner, _uid, mode = _owner_mode(self.env_file)
            if owner != "root" or mode != "0o600":
                problems.append(
                    f"env file {self.env_file} is {owner} {mode}, "
                    f"expected root 0o600")
        if problems:
            return self.record(
                "directories", False, "; ".join(problems))
        return self.record(
            "directories", True,
            "base/home/keys/anchors/registry are "
            f"{self.user}-owned 0700; env dir root 0700, "
            "env file root 0600")

    def check_env_file(self):
        config, errors = _parse_env_strict(self.env_file)
        problems = list(errors)
        for key in REQUIRED_KEYS:
            if not config.get(key):
                problems.append(f"required key {key} missing/empty")
        mode = config.get("AION_DEPLOYMENT_MODE")
        if mode is None:
            problems.append("AION_DEPLOYMENT_MODE is absent")
        elif mode == "":
            problems.append("AION_DEPLOYMENT_MODE is blank")
        elif mode != self.expect_mode:
            problems.append(
                f"AION_DEPLOYMENT_MODE is {mode!r}, expected "
                f"{self.expect_mode!r}")
        if problems:
            return self.record("env-file", False, "; ".join(problems))
        return self.record(
            "env-file", True,
            "env file parses under the wrapper allowlist, required "
            f"keys non-empty, AION_DEPLOYMENT_MODE="
            f"{self.expect_mode}")

    def _key_path(self):
        configured = self.config.get("AION_VERIFIER_KEY_PATH")
        return Path(configured) if configured \
            else self.base / "keys" / "gate.key"

    def _home_dir(self):
        configured = self.config.get("AION_VERIFIER_HOME")
        return Path(configured) if configured else self.base / "home"

    def _signing_anchor_path(self):
        configured = self.config.get("AION_ANCHOR_PATH")
        return Path(configured) if configured \
            else self.base / "anchors" / "signing.anchor.json"

    def _budgets_anchor_path(self):
        configured = self.config.get("AION_BUDGETS_ANCHOR_PATH")
        return Path(configured) if configured \
            else self.base / "anchors" / "budgets.anchor.json"

    def check_key_file(self):
        key_path = self._key_path()
        if not key_path.is_file():
            return self.record(
                "key-file", False, f"key file {key_path} missing")
        owner, _uid, mode = _owner_mode(key_path)
        if owner != self.user or mode != "0o600":
            return self.record(
                "key-file", False,
                f"key file {key_path} is {owner} {mode}, expected "
                f"{self.user} 0o600")
        return self.record(
            "key-file", True, f"{key_path} is {owner} 0600")

    def check_anchors(self):
        sys.path.insert(0, str(self.repo))
        try:
            from trust.anchoring import verify_anchor
            from trust.budgets import BudgetStore
            from trust.ledger import SigningLedger
        except Exception as exc:  # repo not importable: a failure
            return self.record(
                "anchors", False, f"trust modules not importable "
                f"from {self.repo}: {exc}")
        problems = []
        home = self._home_dir()
        signing_anchor = self._signing_anchor_path()
        if not signing_anchor.is_file():
            problems.append(
                f"signing anchor {signing_anchor} missing")
        elif not home.is_dir():
            problems.append(f"ledger home {home} missing")
        else:
            try:
                reasons = verify_anchor(
                    SigningLedger(home), signing_anchor,
                    kind="signing")
            except Exception as exc:
                reasons = (f"verify_anchor raised: {exc}",)
            if reasons:
                problems.append(
                    f"signing anchor does not verify against the "
                    f"live signing ledger: {','.join(reasons)}")
        budgets_anchor = self._budgets_anchor_path()
        if not budgets_anchor.is_file():
            problems.append(
                f"budgets anchor {budgets_anchor} missing")
        elif not home.is_dir():
            problems.append(f"budget home {home} missing")
        else:
            try:
                doc = json.loads(
                    budgets_anchor.read_text(encoding="utf-8"))
            except Exception:
                doc = None
            if not isinstance(doc, dict) \
                    or doc.get("v") != "budgets-anchor/1" \
                    or not isinstance(doc.get("head"), str) \
                    or len(doc.get("head", "")) != 64:
                problems.append(
                    f"budgets anchor {budgets_anchor} is malformed")
            else:
                try:
                    store = BudgetStore(home / "budgets.json")
                    integrity = store.verify_integrity()
                    head = store.head_hash()
                except Exception as exc:
                    integrity, head = (f"raised: {exc}",), None
                if integrity:
                    problems.append(
                        f"budget store integrity: "
                        f"{','.join(integrity)}")
                elif head != doc["head"]:
                    problems.append(
                        f"budgets anchor head {doc['head'][:12]}… "
                        f"does not match budget store head "
                        f"{str(head)[:12]}…")
        if problems:
            return self.record("anchors", False, "; ".join(problems))
        return self.record(
            "anchors", True,
            "signing anchor verifies against the live signing "
            "ledger; budgets anchor head matches the budget store "
            "head and the store's integrity verifies")

    def check_staged_code(self):
        staged = self.base / "code"
        if not staged.is_dir():
            return self.record(
                "staged-code", False,
                f"staged code copy {staged} missing")
        differing = []
        for package in PACKAGES:
            repo_files = _tree_files(self.repo / package)
            staged_files = _tree_files(staged / package)
            for rel in sorted(set(repo_files) | set(staged_files)):
                label = f"{package}/{rel}"
                if rel not in staged_files:
                    differing.append(f"missing: {label}")
                elif rel not in repo_files:
                    differing.append(f"extra: {label}")
                elif _sha256_file(repo_files[rel]) \
                        != _sha256_file(staged_files[rel]):
                    differing.append(f"differing: {label}")
        repo_wrapper = self.repo / WRAPPER_REL
        staged_wrapper = staged / WRAPPER_REL
        if not staged_wrapper.is_file():
            differing.append(f"missing: {WRAPPER_REL}")
        elif not repo_wrapper.is_file():
            differing.append(f"repo wrapper missing: {WRAPPER_REL}")
        elif _sha256_file(repo_wrapper) \
                != _sha256_file(staged_wrapper):
            differing.append(f"differing: {WRAPPER_REL}")
        if differing:
            shown = "; ".join(differing[:10])
            if len(differing) > 10:
                shown += f"; … and {len(differing) - 10} more"
            return self.record("staged-code", False, shown)
        return self.record(
            "staged-code", True,
            f"staged copy at {staged} matches the repo for "
            f"{', '.join(PACKAGES)} and {WRAPPER_REL} (sha256)")

    def check_effective_mode(self):
        sys.path.insert(0, str(self.repo))
        try:
            from trust import protocol
        except Exception as exc:
            return self.record(
                "effective-mode", False,
                f"trust.protocol not importable: {exc}")
        wrapper = self.repo / WRAPPER_REL
        staged = self.base / "code"
        repo_root = staged if staged.is_dir() else self.repo
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "verify_envelope", {"envelope": {}})
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
            "AION_VERIFIER_ENV_FILE": str(self.env_file),
            "AION_REPO_ROOT": str(repo_root),
        }
        try:
            result = subprocess.run(
                [str(wrapper)], input=raw, capture_output=True,
                timeout=60, env=env)
        except Exception as exc:
            return self.record(
                "effective-mode", False, f"probe failed to run: "
                f"{exc}")
        if result.returncode != 0:
            stderr = result.stderr.decode(
                "utf-8", errors="replace").strip()
            return self.record(
                "effective-mode", False,
                f"verifier probe exited {result.returncode}: "
                f"{stderr[:200]}")
        try:
            doc = protocol.strict_loads(
                result.stdout, cap=protocol.MAX_RESPONSE_BYTES,
                what="response")
        except Exception as exc:
            return self.record(
                "effective-mode", False,
                f"probe response is not a strict response "
                f"document: {exc}")
        if not isinstance(doc, dict) \
                or doc.get("status") != "ok":
            return self.record(
                "effective-mode", False,
                f"probe response is not an ok document: "
                f"{str(doc)[:200]}")
        # The deployment_mode field is read via strict_loads on
        # the RAW response: protocol.decode_response's strict key
        # set does not carry it, by design (it tolerates the
        # field, it does not surface it).
        if "deployment_mode" not in doc:
            return self.record(
                "effective-mode", False,
                "staged code stale: the verifier response carries "
                "no deployment_mode field (the staged copy predates "
                "the field); re-stage the code")
        mode = doc["deployment_mode"]
        if mode != self.expect_mode:
            return self.record(
                "effective-mode", False,
                f"running verifier reports deployment_mode="
                f"{mode!r}, expected {self.expect_mode!r}")
        valid = (doc.get("result") or {}).get("valid")
        if valid is not False:
            return self.record(
                "effective-mode", False,
                f"junk-envelope probe unexpectedly returned "
                f"valid={valid!r}")
        return self.record(
            "effective-mode", True,
            f"running verifier reports deployment_mode="
            f"{mode} (junk-envelope probe: valid:false, exit 0, "
            f"nothing ledgered, no budget consumed)")

    def run(self):
        self.check_user()
        self.check_group()
        self.check_directories()
        self.check_env_file()
        self.check_key_file()
        self.check_anchors()
        self.check_staged_code()
        self.check_effective_mode()
        passed = sum(1 for _n, ok, _d in self.results if ok)
        print(f"health-check: {passed}/{len(self.results)} "
              f"checks passed")
        return 0 if passed == len(self.results) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only health check for the AION "
                    "verifier deployment (see module docstring).")
    parser.add_argument("--env-file",
                        default="/etc/aion-verifier/verifier.env")
    parser.add_argument("--base", default="/var/lib/aion-verifier")
    parser.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[2]),
        help="repo the staged copy is compared against "
             "(default: the repo this script lives in)")
    parser.add_argument("--expect-mode", default="production")
    parser.add_argument("--user", default="aion-verifier")
    args = parser.parse_args(argv)
    checker = Checker(args.env_file, args.base, args.repo,
                      args.expect_mode, args.user)
    return checker.run()


if __name__ == "__main__":
    sys.exit(main())
