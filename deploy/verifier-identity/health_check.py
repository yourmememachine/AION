#!/usr/bin/env python3
"""Reproducible deployment health check for the AION verifier
(Trust Boundary v3.1, item 5).

READ-ONLY against the deployment: this checker never signs,
never records a budget query and never consumes a transcript.
It only reads files and filesystem metadata, verifies the
anchors against the live ledgers, compares the staged code copy
against the repo, validates the sealed registry on a COPY (so
the live registry's access log is untouched), and runs ONE
verify_envelope probe with a structurally junk envelope
({"envelope": {}}) through the real wrapper — a request that
returns valid:false, ledgers nothing and consumes no budget,
but whose response document reports the effective
deployment_mode from INSIDE the running verifier process.

The probe is GATED: it is not executed at all when the env-file
or anchors check has failed. A probe against an INIT-flagged or
anchor-inconsistent env could WRITE anchor files (that is what
the INIT ceremony does), so a checker that ran it would heal
the very drift it exists to report. In that case the
effective-mode check FAILs with a "probe not run" detail.

The ten checks, in run order: user, group-membership,
directories, env-file, key-file, anchors, registry,
state-files, staged-code, effective-mode.

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
One residual belongs here too (see check_key_file): substitution
of the signing key by another well-formed non-test key cannot
be detected by any check this deployment supports, because no
key fingerprint is recorded anywhere in the deployment's
artefacts; downstream MAC verification is where that surfaces.
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import inspect
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGES = ("core", "eval", "memory", "oversight", "signing",
            "selfmod", "trust")
DEPLOY_REL = Path("deploy") / "verifier-identity"
WRAPPER_REL = DEPLOY_REL / "run-verifier.sh"

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
_BLANK_RE = re.compile(r"^\s*$")
_COMMENT_RE = re.compile(r"^\s*#")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_INIT_KEYS = ("AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_INIT")
_PATH_KEYS = (
    "AION_VERIFIER_KEY_PATH",
    "AION_REGISTRY_DIR",
    "AION_VERIFIER_HOME",
    "AION_ANCHOR_PATH",
    "AION_BUDGETS_ANCHOR_PATH",
)

# The canonical passwd home of the verifier user on a normally
# provisioned machine. A parameterised (--base) fixture/staging
# deployment lives elsewhere, so the passwd home is accepted when
# it is either the deployment's own home or this canonical one;
# the deployment's configured home is separately required to be
# <base>/home by the directories/env checks below.
CANONICAL_HOME = "/var/lib/aion-verifier/home"


def _no_duplicate_pairs(pairs):
    """object_pairs_hook: build a dict but refuse duplicate keys
    (plain json.loads resolves them last-wins, which would let a
    crafted budgets anchor hide a bogus first ``head``)."""
    doc = {}
    for key, value in pairs:
        if key in doc:
            raise ValueError(f"duplicate key {key!r}")
        doc[key] = value
    return doc


def group_membership_ok(members, user) -> bool:
    """True iff `members` is exactly [user]: the verifier's group
    must have the verifier as its SOLE member. An extra member is
    another OS identity inside the boundary; an empty list means
    the verifier itself is not accounted for. Pure function —
    tests exercise it without touching the real group database."""
    members = list(members)
    return len(members) == 1 and members[0] == user


def _parse_env_strict(path):
    """Parse the env file EXACTLY as run-verifier.sh does.
    Returns (config, errors): config maps allowlisted keys to
    their raw values; errors lists every rule violation.

    Mirror of the wrapper's parser: strip only a trailing CR;
    skip lines matching ^\\s*$ or ^\\s*#; every other line must
    match ^([A-Z_]+)=(.*)$ or it is an error; a duplicate key is
    an ERROR (the wrapper refuses duplicates too). Keys and
    values are NOT stripped — a padded key is malformed and a
    padded value is the value, exactly as the launcher sees it.
    """
    config = {}
    errors = []
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except OSError as exc:
        return {}, [f"env file unreadable: {exc}"]
    except UnicodeDecodeError as exc:
        return {}, [f"env file is not valid UTF-8: {exc}"]
    for raw_line in text.split("\n"):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if _BLANK_RE.match(line) or _COMMENT_RE.match(line):
            continue
        match = _LINE_RE.match(line)
        if not match:
            errors.append(f"malformed line: {line!r}")
            continue
        key, value = match.group(1), match.group(2)
        if key not in ALLOWED_KEYS:
            errors.append(f"{key} is not an allowlisted variable")
            continue
        if key in config:
            errors.append(f"duplicate key {key} in env file")
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
    """(owner name, uid, mode string) from an LSTAT of `path` —
    symlinks are never followed, and the mode string carries the
    full permission set including special bits (no 0o777 mask),
    so a setuid/setgid/sticky drift changes the string and fails
    the caller's exact comparison. An unknown uid is reported as
    "uid:<n>" instead of raising: callers turn it into a FAIL
    line, never a traceback."""
    st = os.lstat(path)
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, OverflowError):
        owner = f"uid:{st.st_uid}"
    return owner, st.st_uid, oct(stat.S_IMODE(st.st_mode))


def _owner_name(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return f"uid:{uid}"


def _is_under(path, root) -> bool:
    try:
        Path(path).relative_to(Path(root))
    except ValueError:
        return False
    return True


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
        problems = []
        if not group_membership_ok(members, self.user):
            problems.append(
                f"group {group.gr_name} effective members: "
                f"{members if members else '[]'}")
        # Supplementary memberships: the verifier user must appear
        # in NO other group's member list. A supplementary group
        # is another route into group-writable state (and another
        # group's route into the verifier's), outside the primary
        # group's sole-membership guarantee.
        extra_groups = sorted(
            entry.gr_name for entry in grp.getgrall()
            if entry.gr_gid != self.pw.pw_gid
            and self.user in entry.gr_mem)
        if extra_groups:
            problems.append(
                f"{self.user} has supplementary group membership "
                f"in: {', '.join(extra_groups)}")
        if problems:
            return self.record(
                "group-membership", False, "; ".join(problems))
        return self.record(
            "group-membership", True,
            f"group {group.gr_name} effective members: {members}; "
            f"no supplementary group memberships beyond the "
            f"primary group")

    def check_directories(self):
        problems = []

        def check_dir(label, path, expected_owner):
            try:
                st = os.lstat(path)
            except OSError:
                problems.append(f"{label} dir {path} missing")
                return
            if stat.S_ISLNK(st.st_mode):
                problems.append(f"{label} dir {path} is a symlink")
                return
            if not stat.S_ISDIR(st.st_mode):
                problems.append(
                    f"{label} dir {path} is not a directory")
                return
            owner = _owner_name(st.st_uid)
            mode = stat.S_IMODE(st.st_mode)
            if owner != expected_owner or mode != 0o700:
                problems.append(
                    f"{label} dir {path} is {owner} {oct(mode)}, "
                    f"expected {expected_owner} 0o700")

        for label, path in (("base", self.base),
                            ("home", self.base / "home"),
                            ("keys", self.base / "keys"),
                            ("anchors", self.base / "anchors"),
                            ("registry", self.base / "registry")):
            check_dir(label, path, self.user)
        env_dir = self.env_file.parent
        check_dir("env", env_dir, "root")
        # Env file itself: lstat — a symlink or a special-bit mode
        # is drift, not a detail to mask away.
        try:
            st = os.lstat(self.env_file)
        except OSError:
            problems.append(f"env file {self.env_file} missing")
        else:
            if stat.S_ISLNK(st.st_mode):
                problems.append(
                    f"env file {self.env_file} is a symlink")
            elif not stat.S_ISREG(st.st_mode):
                problems.append(
                    f"env file {self.env_file} is not a regular file")
            else:
                owner = _owner_name(st.st_uid)
                mode = stat.S_IMODE(st.st_mode)
                if owner != "root" or mode != 0o600:
                    problems.append(
                        f"env file {self.env_file} is {owner} "
                        f"{oct(mode)}, expected root 0o600")
        if problems:
            return self.record(
                "directories", False, "; ".join(problems))
        return self.record(
            "directories", True,
            "base/home/keys/anchors/registry are "
            f"{self.user}-owned 0700; env dir root 0700, "
            "env file root 0600")

    def _validate_env_values(self, config, problems):
        """Value validation mirroring trust/verifier_main.py's
        config load: the verifier's own rules, attributed to the
        env-file check with the specific key named."""
        sys.path.insert(0, str(self.repo))
        try:
            from signing.gate_decision import TTL_MAX_SECONDS, \
                TTL_MIN_SECONDS
        except Exception:
            TTL_MIN_SECONDS, TTL_MAX_SECONDS = 60, 172800
        ttl = config.get("AION_VERIFIER_TTL_SECONDS")
        if ttl:
            if not ttl.isdigit():
                problems.append(
                    f"AION_VERIFIER_TTL_SECONDS is {ttl!r}, "
                    f"not digits")
            elif not TTL_MIN_SECONDS <= int(ttl) <= TTL_MAX_SECONDS:
                problems.append(
                    f"AION_VERIFIER_TTL_SECONDS is {ttl!r}, "
                    f"outside the signing bounds "
                    f"{TTL_MIN_SECONDS}-{TTL_MAX_SECONDS}")
        for key in ("AION_VERIFIER_PROPOSAL_BUDGET",
                    "AION_VERIFIER_IDENTITY_BUDGET"):
            value = config.get(key)
            if value:
                if not value.isdigit() or int(value) < 1:
                    problems.append(
                        f"{key} is {value!r}, must be digits >= 1")
        if "AION_VERIFIER_PURPOSE" in config:
            purpose = config["AION_VERIFIER_PURPOSE"]
            if purpose not in ("memory-commit", "ship"):
                problems.append(
                    f"AION_VERIFIER_PURPOSE is {purpose!r}, "
                    f"expected 'memory-commit' or 'ship'")
        for key in ("AION_VERIFIER_SIGNER_ID",
                    "AION_VERIFIER_ACTOR_ID"):
            value = config.get(key)
            if value and not _ID_RE.match(value):
                problems.append(
                    f"{key} is {value!r}, must match "
                    f"^[a-z0-9][a-z0-9_-]{{0,63}}$")
        for key in _PATH_KEYS:
            value = config.get(key)
            if value and not Path(value).is_absolute():
                problems.append(
                    f"{key} is {value!r}, must be an absolute path")

    def _validate_env_base_binding(self, config, problems):
        """Every configured path must be bound to THIS deployment
        base: a verifier pointed at another deployment's home,
        registry, keys or anchors is a different deployment, and
        checking it under this base's name would bless drift."""
        home = config.get("AION_VERIFIER_HOME")
        expected_home = str(self.base / "home")
        if home and home != expected_home:
            problems.append(
                f"AION_VERIFIER_HOME is {home!r}, expected "
                f"{expected_home!r} (bound to the deployment base)")
        registry = config.get("AION_REGISTRY_DIR")
        expected_registry = str(self.base / "registry")
        if registry and registry != expected_registry:
            problems.append(
                f"AION_REGISTRY_DIR is {registry!r}, expected "
                f"{expected_registry!r} (bound to the deployment "
                f"base)")
        key_path = config.get("AION_VERIFIER_KEY_PATH")
        keys_dir = self.base / "keys"
        if key_path and not _is_under(key_path, keys_dir):
            problems.append(
                f"AION_VERIFIER_KEY_PATH is {key_path!r}, not "
                f"under {keys_dir} (bound to the deployment base)")
        anchors_dir = self.base / "anchors"
        for key in ("AION_ANCHOR_PATH", "AION_BUDGETS_ANCHOR_PATH"):
            value = config.get(key)
            if value and not _is_under(value, anchors_dir):
                problems.append(
                    f"{key} is {value!r}, not under {anchors_dir} "
                    f"(bound to the deployment base)")

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
        # Steady-state INIT guard: an INIT flag with a non-empty
        # value means the NEXT verifier start would run (or try
        # to run) an anchor bootstrap ceremony. A steady-state
        # deployment carries no INIT flags.
        for key in _INIT_KEYS:
            if config.get(key):
                problems.append(
                    f"{key} is set to {config[key]!r}: a "
                    f"steady-state deployment must carry no INIT "
                    f"flags")
        self._validate_env_values(config, problems)
        self._validate_env_base_binding(config, problems)
        if problems:
            return self.record("env-file", False, "; ".join(problems))
        return self.record(
            "env-file", True,
            "env file parses under the wrapper allowlist, required "
            "keys non-empty, values validate as the verifier "
            "validates them, paths are bound to the deployment "
            f"base, no INIT flags, AION_DEPLOYMENT_MODE="
            f"{self.expect_mode}")

    def _key_path(self):
        configured = self.config.get("AION_VERIFIER_KEY_PATH")
        return Path(configured) if configured \
            else self.base / "keys" / "gate.key"

    def _registry_dir(self):
        configured = self.config.get("AION_REGISTRY_DIR")
        return Path(configured) if configured \
            else self.base / "registry"

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
        """Owner/mode, then the key must LOAD under
        signing.load_signing_key's format/safety rules, and must
        not be one of the known test keys the verifier refuses.

        Residual (recorded deliberately): substitution by another
        well-formed non-test key cannot be detected by any check
        the deployment supports — no key fingerprint is recorded
        anywhere in the deployment's artefacts — so this check
        cannot detect it; downstream MAC verification is where
        that surfaces."""
        key_path = self._key_path()
        if key_path.is_symlink():
            return self.record(
                "key-file", False,
                f"key file {key_path} is a symlink")
        if not key_path.is_file():
            return self.record(
                "key-file", False, f"key file {key_path} missing")
        owner, _uid, mode = _owner_mode(key_path)
        if owner != self.user or mode != "0o600":
            return self.record(
                "key-file", False,
                f"key file {key_path} is {owner} {mode}, expected "
                f"{self.user} 0o600")
        sys.path.insert(0, str(self.repo))
        try:
            from signing import load_signing_key
        except Exception as exc:
            return self.record(
                "key-file", False,
                f"signing.load_signing_key not importable: {exc}")
        try:
            loaded = load_signing_key(key_path)
        except Exception as exc:
            return self.record(
                "key-file", False,
                f"key file {key_path} fails "
                f"signing.load_signing_key: {exc}")
        try:
            from trust.verifier_main import _REFUSED_TEST_KEYS
        except Exception:
            # Replicated from trust/verifier_main.py's
            # _REFUSED_TEST_KEYS for contexts where that module is
            # not importable by the checker.
            _REFUSED_TEST_KEYS = (
                bytes(range(32)), bytes(range(32, 64)),
                b"\x00" * 32, b"\xff" * 32,
            )
        if loaded.key in _REFUSED_TEST_KEYS:
            return self.record(
                "key-file", False,
                f"key file {key_path} holds a known test key "
                f"(refused by the verifier)")
        return self.record(
            "key-file", True,
            f"{key_path} is {owner} 0600, loads under "
            f"signing.load_signing_key and is not a known test key")

    def check_anchors(self):
        sys.path.insert(0, str(self.repo))
        try:
            from trust.anchoring import load_anchor, verify_anchor
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
                ledger = SigningLedger(home)
            except Exception as exc:
                # A corrupt or symlinked-away ledger must be a
                # FAIL line, never a traceback that masks the
                # remaining checks (re-review rev-r4, N1).
                ledger = None
                problems.append(
                    f"signing ledger unreadable/corrupt: {exc}")
            if ledger is not None:
                verify_kwargs = {}
                if "check_reanchor_audit" in inspect.signature(
                        verify_anchor).parameters:
                    verify_kwargs["check_reanchor_audit"] = True
                try:
                    reasons = verify_anchor(
                        ledger, signing_anchor, kind="signing",
                        **verify_kwargs)
                except Exception as exc:
                    reasons = (f"verify_anchor raised: {exc}",)
                if reasons:
                    problems.append(
                        f"signing anchor does not verify against "
                        f"the live signing ledger: "
                        f"{','.join(reasons)}")
                # Exactness beyond verify_anchor: verify_anchor
                # alone accepts an anchor naming any STALE PREFIX
                # of the ledger. A steady-state deployment's
                # anchor must name the ledger's CURRENT head at
                # its CURRENT length.
                try:
                    anchor_doc = load_anchor(signing_anchor)
                except Exception as exc:
                    anchor_doc = None
                    problems.append(
                        f"signing anchor is malformed/unreadable: "
                        f"{exc}")
                if anchor_doc is not None:
                    entries = ledger.entries()
                    if anchor_doc.get("head") != ledger.head():
                        problems.append(
                            f"signing anchor head "
                            f"{str(anchor_doc.get('head'))[:12]}… "
                            f"does not equal the live signing "
                            f"ledger head {ledger.head()[:12]}… "
                            f"(stale-prefix anchors are not "
                            f"accepted)")
                    if anchor_doc.get("seq") != len(entries):
                        problems.append(
                            f"signing anchor seq "
                            f"{anchor_doc.get('seq')} does not "
                            f"equal the live signing ledger entry "
                            f"count {len(entries)}")
        budgets_anchor = self._budgets_anchor_path()
        if not budgets_anchor.is_file():
            problems.append(
                f"budgets anchor {budgets_anchor} missing")
        elif not home.is_dir():
            problems.append(f"budget home {home} missing")
        else:
            try:
                doc = json.loads(
                    budgets_anchor.read_text(encoding="utf-8"),
                    object_pairs_hook=_no_duplicate_pairs)
            except Exception:
                doc = None
            if not isinstance(doc, dict) \
                    or set(doc) != {"v", "head", "anchored_at"} \
                    or doc.get("v") != "budgets-anchor/1" \
                    or not isinstance(doc.get("head"), str) \
                    or len(doc.get("head", "")) != 64 \
                    or any(c not in "0123456789abcdef"
                           for c in doc.get("head", "")) \
                    or not isinstance(doc.get("anchored_at"), str) \
                    or not doc.get("anchored_at"):
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
            "signing anchor verifies (incl. reanchor audit) and "
            "its head/seq exactly equal the live signing ledger; "
            "budgets anchor head matches the budget store head "
            "and the store's integrity verifies")

    def check_registry(self):
        """Validate the sealed registry ON A COPY: the registry
        directory is copied to a temp dir and EvalRegistry is
        opened on the copy, so every access-log entry the
        validation writes lands on the copy — the live registry
        is never opened and its access log is untouched."""
        sys.path.insert(0, str(self.repo))
        try:
            from eval.registry import EvalRegistry
        except Exception as exc:
            return self.record(
                "registry", False,
                f"eval.registry not importable: {exc}")
        registry_dir = self._registry_dir()
        actor = self.config.get("AION_VERIFIER_ACTOR_ID")
        if not actor:
            return self.record(
                "registry", False,
                "AION_VERIFIER_ACTOR_ID is not configured; the "
                "registry cannot be validated")
        if not registry_dir.is_dir():
            return self.record(
                "registry", False,
                f"registry dir {registry_dir} missing")
        tmp = tempfile.TemporaryDirectory()
        try:
            copy_dir = Path(tmp.name) / "registry"
            shutil.copytree(registry_dir, copy_dir)
            try:
                registry = EvalRegistry(copy_dir)
                metadata = registry.list_sealed_metadata(actor)
                manifest = registry.sealed_manifest_hash(actor)
            except Exception as exc:
                return self.record(
                    "registry", False,
                    f"registry failed validation on a copy: "
                    f"{type(exc).__name__}: {exc}")
        finally:
            tmp.cleanup()
        if not metadata:
            return self.record(
                "registry", False,
                "registry copy validated but the sealed set is "
                "empty")
        if not manifest:
            return self.record(
                "registry", False,
                "registry copy validated but "
                "sealed_manifest_hash returned nothing")
        return self.record(
            "registry", True,
            f"registry validated entirely on a copy: "
            f"{len(metadata)} sealed items, manifest "
            f"{str(manifest)[:12]}…; the live registry at "
            f"{registry_dir} was never opened, so its access "
            f"log is untouched")

    def check_state_files(self):
        """Modes/ownership of the verifier's state files.
        Group-writability is tolerated ONLY because the
        group-membership check verifies the verifier is its
        group's sole member — that tolerance is stated in the
        detail whenever group bits are present."""
        if self.pw is None:
            return self.record(
                "state-files", False,
                f"user {self.user} does not exist")
        home = self._home_dir()
        targets = [
            ("signing-ledger.json", home / "signing-ledger.json",
             True),
            ("budgets.json", home / "budgets.json", False),
            ("registry.json",
             self._registry_dir() / "registry.json", True),
        ]
        if self.config.get("AION_ANCHOR_PATH"):
            targets.append(
                ("signing anchor", self._signing_anchor_path(), True))
        if self.config.get("AION_BUDGETS_ANCHOR_PATH"):
            targets.append(
                ("budgets anchor", self._budgets_anchor_path(), True))
        problems = []
        group_bits_on = []
        checked = 0
        for label, path, required in targets:
            try:
                st = os.lstat(path)
            except OSError:
                if required:
                    problems.append(f"{label} {path} missing")
                continue
            checked += 1
            if stat.S_ISLNK(st.st_mode):
                problems.append(f"{label} {path} is a symlink")
                continue
            if not stat.S_ISREG(st.st_mode):
                problems.append(
                    f"{label} {path} is not a regular file")
                continue
            if st.st_uid != self.pw.pw_uid:
                problems.append(
                    f"{label} {path} is owned by "
                    f"{_owner_name(st.st_uid)}, expected "
                    f"{self.user}")
            mode = stat.S_IMODE(st.st_mode)
            if mode & 0o007:
                problems.append(
                    f"{label} {path} has mode {oct(mode)}: world "
                    f"access is present")
            if mode & 0o7000:
                problems.append(
                    f"{label} {path} has mode {oct(mode)}: "
                    f"setuid/setgid/sticky bits are present")
            if mode & 0o070:
                group_bits_on.append(label)
        if problems:
            return self.record(
                "state-files", False, "; ".join(problems))
        detail = (
            f"{checked} state files are {self.user}-owned regular "
            f"files with no world access and no special bits")
        if group_bits_on:
            detail += (
                f"; group bits present on "
                f"{', '.join(group_bits_on)} — group access is "
                f"tolerated ONLY because the group-membership "
                f"check verifies {self.user} is the group's sole "
                f"member")
        return self.record("state-files", True, detail)

    def check_staged_code(self):
        staged = self.base / "code"
        if not staged.is_dir():
            return self.record(
                "staged-code", False,
                f"staged code copy {staged} missing")
        problems = []
        # Bytecode in the staged tree: a __pycache__ directory or
        # .pyc file is code the comparison below deliberately
        # ignores, so its presence is itself a failure — staged
        # bytecode could be what the interpreter actually loads.
        for path in sorted(staged.rglob("*")):
            rel = str(path.relative_to(staged))
            if path.is_dir() and path.name == "__pycache__":
                problems.append(f"__pycache__ directory: {rel}")
            elif path.is_file() and path.suffix == ".pyc":
                problems.append(f".pyc file: {rel}")
        # A .py file at the staged ROOT sits outside every package
        # the comparison covers — and a sitecustomize.py there
        # would be imported by the interpreter itself.
        for child in sorted(staged.iterdir()):
            if child.is_file() and child.suffix == ".py":
                problems.append(
                    f".py file at staged root: {child.name}")
        # Staged files must not be verifier-owned or
        # world-writable (the verifier must not be able to rewrite
        # the code it runs), and neither may the code dir itself.
        verifier_uid = self.pw.pw_uid if self.pw else None
        try:
            code_st = os.lstat(staged)
            if verifier_uid is not None \
                    and code_st.st_uid == verifier_uid:
                problems.append(
                    "staged code dir is owned by the verifier user")
            if stat.S_IMODE(code_st.st_mode) & 0o002:
                problems.append("staged code dir is world-writable")
        except OSError:
            pass
        for path in sorted(staged.rglob("*")):
            if not path.is_file():
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            rel = str(path.relative_to(staged))
            if stat.S_IMODE(st.st_mode) & 0o002:
                problems.append(f"world-writable staged file: {rel}")
            if verifier_uid is not None \
                    and st.st_uid == verifier_uid:
                problems.append(
                    f"staged file owned by the verifier user: {rel}")
        # Content comparison: the seven packages plus the whole
        # deploy/verifier-identity/ directory, repo vs staged.
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
        repo_files = _tree_files(self.repo / DEPLOY_REL)
        staged_files = _tree_files(staged / DEPLOY_REL)
        for rel in sorted(set(repo_files) | set(staged_files)):
            label = f"{DEPLOY_REL}/{rel}"
            if rel not in staged_files:
                differing.append(f"missing: {label}")
            elif rel not in repo_files:
                differing.append(f"extra: {label}")
            elif _sha256_file(repo_files[rel]) \
                    != _sha256_file(staged_files[rel]):
                differing.append(f"differing: {label}")
        problems.extend(differing)
        if problems:
            shown = "; ".join(problems[:10])
            if len(problems) > 10:
                shown += f"; … and {len(problems) - 10} more"
            return self.record("staged-code", False, shown)
        return self.record(
            "staged-code", True,
            f"staged copy at {staged} matches the repo for "
            f"{', '.join(PACKAGES)} and {DEPLOY_REL} (sha256); "
            f"no bytecode, no root-level .py files, no "
            f"verifier-owned or world-writable staged files")

    def check_effective_mode(self, gated_by=None):
        if gated_by is not None:
            return self.record(
                "effective-mode", False,
                f"probe not run: {gated_by} check failed "
                f"(read-only guard — a probe against an "
                f"INIT-flagged or anchor-inconsistent env could "
                f"write anchor files)")
        staged = self.base / "code"
        if not staged.is_dir():
            return self.record(
                "effective-mode", False,
                f"staged code copy {staged} missing; probe not "
                f"run (no silent fallback to the repo copy)")
        sys.path.insert(0, str(self.repo))
        try:
            from trust import protocol
        except Exception as exc:
            return self.record(
                "effective-mode", False,
                f"trust.protocol not importable: {exc}")
        wrapper = self.repo / WRAPPER_REL
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(
            request_id, "verify_envelope", {"envelope": {}})
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:"
                    "/usr/bin:/sbin:/bin",
            "AION_VERIFIER_ENV_FILE": str(self.env_file),
            "AION_REPO_ROOT": str(staged),
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
            doc = protocol.decode_response(
                result.stdout, expected_request_id=request_id,
                expected_mode="verify_envelope")
        except Exception as exc:
            return self.record(
                "effective-mode", False,
                f"probe response failed "
                f"protocol.decode_response validation "
                f"(request_id/mode echo): {exc}")
        if not isinstance(doc, dict) \
                or doc.get("status") != "ok":
            return self.record(
                "effective-mode", False,
                f"probe response is not an ok document: "
                f"{str(doc)[:200]}")
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
            f"verifier started under the wrapper, reported "
            f"effective mode {mode} from inside the process, "
            f"rejected a junk envelope; no signing was performed "
            f"or verified")

    def run(self):
        self.check_user()
        self.check_group()
        self.check_directories()
        env_ok = self.check_env_file()
        self.check_key_file()
        anchors_ok = self.check_anchors()
        self.check_registry()
        self.check_state_files()
        self.check_staged_code()
        gated_by = None
        if not env_ok:
            gated_by = "env-file"
        elif not anchors_ok:
            gated_by = "anchors"
        self.check_effective_mode(gated_by=gated_by)
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
