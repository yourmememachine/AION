"""Check-carrying self-improvement: proof artefacts for a change.

A proof artefact binds a declared change to the exact trees it
was checked against. It names the scope, the base and post tree
hashes, the files that changed, the invariants the change
declares, and -- for each invariant -- evidence that was
BUILDER-run on the post tree: the builder ran each declared
check while building the artefact and recorded the outcome as
evidence. The checker does not produce that evidence and does
not trust it: verification recomputes both tree hashes from
the live trees, re-runs every check itself on scratch copies
of the trees, compares what it observes against the
builder-run evidence, re-runs every check declared ``new`` on
a scratch copy of the base tree (where it must be observed to
fail, or the check does not discriminate this change from
what came before), and re-runs every check on a mutated
scratch copy of the post tree (where it must also be observed
to fail, or the check is vacuous for the mutation the
artefact declares).

Terminology: despite the format name, this mechanism is
check-carrying -- author-declared executable checks
re-verified by re-execution -- not proof-carrying in the
formal-methods (Necula) sense; no logical proof object
exists in the artefact or anywhere else in this module.

Honest scope, stated plainly: see CLAIM below. An artefact
establishes only what its declared checks actually exercised,
against the exact tree contents it binds. The binding covers
tree contents only: checks run as ordinary subprocesses with
the checker's privileges and inherited environment, and the
execution environment, the interpreter, and anything outside
the tree a check reads or writes are not bound by the
artefact. It establishes nothing about properties the change
did not declare, nothing about trees other than the ones
hashed, and it is not a proof of general correctness. The
mutation is a single declared perturbation -- defaulting to
reverting a changed file to its base contents -- not an
exploration of the mutation space. Checks are subprocesses
run with the caller's privileges and no sandboxing beyond
``shell=False`` and a timeout; a check the artefact declares
is code the verifier operator is choosing to execute, exactly
as with a test suite.

Tree entries bind content hash and size only, not the file
mode: a mode-only change is invisible to this module alone
(the ship manifest binds the executable bit, so in the ship
composition a mode flip refuses the ship). ``tree_hash``
also does not check whether ``root`` itself is a symlink:
``root`` is supplied by the operator, and a symlinked root
resolves every scope under the operator's chosen anchor;
symlinks below that anchor are refused.
"""

from __future__ import annotations

import ast
import base64
import binascii
import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import trust.shipcheck
from signing.gate_decision import _canonical, _now, _sha256
from trust.errors import ShipRefused

FORMAT = "proof-artefact/1"

# The mechanism name that travels inside every artefact, bound by
# artefact_hash: despite the format identifier, this mechanism is
# check-carrying (see the module docstring's terminology note),
# and any artefact without this exact field is malformed.
MECHANISM = "check-carrying/1"

CLAIM = (
    "A proof artefact establishes only this: the invariants it "
    "declares were executed by the independent checker against "
    "the exact tree contents bound in the artefact, each "
    "declared check passed on that tree, and each check was "
    "shown to fail on the pre-change tree (for invariants "
    "declared new) and on a mutated tree. The binding covers "
    "tree contents only: checks run as ordinary subprocesses "
    "with the checker's privileges and inherited environment, "
    "and the execution environment, the interpreter, and "
    "anything outside the tree a check reads or writes are "
    "not bound by the artefact. It establishes nothing about "
    "properties the change did not declare, and it is not a "
    "proof of general correctness."
)

_HEX64_RE = re.compile(r"[0-9a-f]{64}")

_ARTEFACT_KEYS = {
    "format", "mechanism", "change_id", "created_at", "scope_paths",
    "base_tree_hash", "post_tree_hash", "changed_files",
    "invariants", "evidence", "artefact_hash",
}
_INVARIANT_KEYS = {"id", "description", "argv", "scope", "mutation"}
_MUTATION_KEYS = {"path", "content_b64"}
_EVIDENCE_KEYS = {
    "invariant_id", "tree_hash", "exit_code",
    "stdout_sha256", "stderr_sha256",
}
_CHANGED_KEYS = {"path", "base_sha256", "post_sha256"}

_CHECK_TIMEOUT = 60


class ProofError(ValueError):
    """A tree, check, or artefact construction is malformed or
    refused. Raised for structural problems and for a change
    whose own declared checks do not pass on its post tree;
    verification refusals are reported as reason tuples by
    verify_proof_artefact, never raised."""


def _sha256_bytes(data: bytes) -> str:
    return _sha256(data)


def _is_hex64(value) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _check_scope_path(raw) -> str:
    if not isinstance(raw, str) or not raw:
        raise ProofError("scope path must be a non-empty string")
    if "\\" in raw or raw.startswith("/") or raw.endswith("/"):
        raise ProofError(f"scope path must be a clean relative path: {raw!r}")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProofError(
            f"scope path has an empty, '.' or '..' component: {raw!r}")
    return raw


def _validate_scope_paths(scope_paths) -> list:
    if not isinstance(scope_paths, (list, tuple)) or not scope_paths:
        raise ProofError("scope_paths must be a non-empty list of paths")
    return sorted({_check_scope_path(p) for p in scope_paths})


def _hash_file(full: Path) -> dict:
    try:
        data = full.read_bytes()
    except OSError as exc:
        raise ProofError(f"file is unreadable: {full}: {exc}") from exc
    return {"sha256": _sha256_bytes(data), "size": len(data)}


def _refuse_symlink_prefixes(root: Path, scope: str) -> None:
    cur = root
    for part in scope.split("/"):
        cur = cur / part
        if os.path.islink(cur):
            raise ProofError(f"symlink in scope path: {scope}")


def _expand_scope(root, scope_paths) -> list:
    """Expand scope paths to a sorted entry list of
    {path, sha256, size}, deduplicated by path. Missing scope
    paths yield a single null entry; directories recurse.
    Symlinks are refused anywhere the walk observes one --
    including any component/prefix of a scope path;
    __pycache__ directories and *.pyc files are skipped (they
    are interpreter by-products, not tree contents)."""
    root = Path(root)
    by_path = {}
    for scope in _validate_scope_paths(scope_paths):
        _refuse_symlink_prefixes(root, scope)
        full = root / scope
        if not full.exists():
            by_path.setdefault(
                scope, {"path": scope, "sha256": None, "size": None})
            continue
        if full.is_file():
            info = _hash_file(full)
            by_path[scope] = {"path": scope, "sha256": info["sha256"],
                              "size": info["size"]}
            continue
        if not full.is_dir():
            raise ProofError(f"non-regular file in scope: {scope}")
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames.sort()
            for dirname in list(dirnames):
                sub = Path(dirpath) / dirname
                if os.path.islink(sub):
                    raise ProofError(
                        f"symlinked directory inside the tree: "
                        f"{sub.relative_to(root).as_posix()}")
            if "__pycache__" in dirnames:
                dirnames.remove("__pycache__")
            for name in sorted(filenames):
                if name.endswith(".pyc"):
                    continue
                fpath = Path(dirpath) / name
                rel = fpath.relative_to(root).as_posix()
                if "__pycache__" in Path(rel).parts:
                    continue
                if os.path.islink(fpath) or not fpath.is_file():
                    raise ProofError(f"non-regular file inside the tree: {rel}")
                info = _hash_file(fpath)
                by_path[rel] = {"path": rel, "sha256": info["sha256"],
                                "size": info["size"]}
    return [by_path[p] for p in sorted(by_path)]


def _expand_whole_tree(root) -> list:
    """Expand the ENTIRE tree at ``root`` to a sorted entry
    list of {path, sha256, size} with repo-relative POSIX
    paths, under the same walk discipline as _expand_scope:
    skip any directory named __pycache__ (a .pyc file outside
    __pycache__ is tree content like any other file and IS
    listed); refuse (ProofError) on any symlink observed
    anywhere and on any non-regular file. Limits, stated:
    entries are files only, so adding or removing an EMPTY
    directory is invisible to this expansion, and entries
    carry {sha256, size} only, so a mode-only change is
    invisible here (the module docstring's mode note)."""
    root = Path(root)
    by_path = {}
    if not root.exists():
        return []
    if not root.is_dir():
        raise ProofError(f"whole-tree root is not a directory: {root}")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for dirname in list(dirnames):
            sub = Path(dirpath) / dirname
            if os.path.islink(sub):
                raise ProofError(
                    f"symlinked directory inside the tree: "
                    f"{sub.relative_to(root).as_posix()}")
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in sorted(filenames):
            fpath = Path(dirpath) / name
            rel = fpath.relative_to(root).as_posix()
            if "__pycache__" in Path(rel).parts:
                continue
            if os.path.islink(fpath) or not fpath.is_file():
                raise ProofError(f"non-regular file inside the tree: {rel}")
            info = _hash_file(fpath)
            by_path[rel] = {"path": rel, "sha256": info["sha256"],
                            "size": info["size"]}
    return [by_path[p] for p in sorted(by_path)]


def _whole_tree_changed_paths(base_root, post_root) -> list:
    base = {e["path"]: (e["sha256"], e["size"])
            for e in _expand_whole_tree(base_root)}
    post = {e["path"]: (e["sha256"], e["size"])
            for e in _expand_whole_tree(post_root)}
    return sorted(
        p for p in set(base) | set(post) if base.get(p) != post.get(p))


def _unscoped_changes(base_root, post_root, scope_paths) -> tuple:
    return tuple(
        p for p in _whole_tree_changed_paths(base_root, post_root)
        if not _path_in_scope(p, scope_paths))


_BINDING_FILE = "proof-bindings.jsonl"
_BINDING_GENESIS = "0" * 64
_BINDING_KEYS = {
    "cycle_id", "item_id", "change_id", "manifest_hash",
    "artefact_hash", "post_tree_hash", "recorded_at",
    "prev_binding_hash", "binding_hash",
}


def _parse_proof_bindings(journal_dir) -> list:
    """Parse every binding record in ``journal_dir``. A
    missing or empty file parses to []. Raises ProofError on
    a malformed line or record shape, OSError on a read
    failure."""
    path = Path(journal_dir) / _BINDING_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            raise ProofError("blank line in proof bindings")
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ProofError(
                f"proof binding is not valid JSON: {exc}") from exc
        if not isinstance(record, dict) \
                or set(record) != _BINDING_KEYS:
            raise ProofError("proof binding has wrong keys")
        records.append(record)
    return records


def _binding_chain_reasons(records) -> tuple:
    """() iff ``records`` form one hash chain: genesis prev,
    each prev naming the previous record's binding_hash, and
    every binding_hash recomputing over its record core."""
    prev = _BINDING_GENESIS
    for record in records:
        if record["prev_binding_hash"] != prev \
                or not _is_hex64(record["binding_hash"]):
            return ("proof_binding_chain_broken",)
        core = {k: v for k, v in record.items()
                if k != "binding_hash"}
        if _sha256(_canonical(core)) != record["binding_hash"]:
            return ("proof_binding_chain_broken",)
        prev = record["binding_hash"]
    return ()


def verify_proof_bindings(journal_dir) -> tuple:
    """Pure check of the durable proof-binding chain in
    ``journal_dir``: () means every recorded binding is
    intact and chained. Editing, reordering or truncating
    the MIDDLE of the file is detected; deleting the tail
    is not distinguishable from a shorter history by this
    check alone — that needs a non-author anchor, which
    remains a separate follow-up and is not claimed here."""
    try:
        records = _parse_proof_bindings(journal_dir)
    except (ProofError, OSError):
        return ("proof_binding_malformed",)
    return _binding_chain_reasons(records)


def _preflight_proof_binding(journal_dir) -> tuple:
    """Fail-closed pre-burn probe, with no side effects (it
    creates nothing): the existing chain must verify, the
    bindings path must be a regular file when it exists, and
    the journal directory must be writable. Returns refusal
    reasons, () when the post-ship append can be expected to
    land. A race after this probe is still possible; the
    post-ship append failure stays anomaly-signalled."""
    reasons = verify_proof_bindings(journal_dir)
    if reasons:
        return reasons
    journal_dir = Path(journal_dir)
    path = journal_dir / _BINDING_FILE
    if path.exists() and not path.is_file():
        return ("proof_binding_unavailable",)
    target = path if path.exists() else journal_dir
    if not os.access(target, os.W_OK):
        return ("proof_binding_unavailable",)
    return ()


def _append_proof_binding(journal_dir, record) -> None:
    """Append ``record`` to proof-bindings.jsonl in
    ``journal_dir`` as the next hash-chained binding:
    prev_binding_hash names the current tail (genesis for
    the first record) and binding_hash self-hashes the
    record core. fsync'd (file, then directory). Raises
    ProofError if the existing chain does not verify,
    OSError on any IO failure; it does not catch."""
    journal_dir = Path(journal_dir)
    path = journal_dir / _BINDING_FILE
    records = _parse_proof_bindings(journal_dir)
    reasons = _binding_chain_reasons(records)
    if reasons:
        raise ProofError(
            "existing proof binding chain does not verify: "
            + ", ".join(reasons))
    full = dict(record)
    full["prev_binding_hash"] = (
        records[-1]["binding_hash"] if records
        else _BINDING_GENESIS)
    full["binding_hash"] = _sha256(_canonical(full))
    line = json.dumps(full, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    dir_fd = os.open(journal_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


@contextlib.contextmanager
def _snapshot_tree(root):
    """Yield the Path of a private snapshot copy of root."""
    # Pre-walk first: refuse symlinks and non-regular files
    # BEFORE anything is copied, so the copy never
    # dereferences a link the walk would have refused.
    _expand_whole_tree(root)
    with tempfile.TemporaryDirectory(
            prefix="proofcarry-snapshot-") as tmp:
        dest = Path(tmp) / "tree"
        shutil.copytree(root, dest, ignore=_IGNORE)
        yield dest


def tree_hash(root, scope_paths) -> str:
    """Hex64 hash binding the exact contents of the scope in
    the tree at ``root``: the sha256 of the canonical JSON of
    {"format": "proof-tree/1", "entries": [...]} over the
    sorted, deduplicated scope-expanded entry list."""
    entries = _expand_scope(root, scope_paths)
    return _sha256(_canonical({"format": "proof-tree/1",
                               "entries": entries}))


def changed_files(base_root, post_root, scope_paths) -> list:
    """Sorted list of {path, base_sha256, post_sha256} for
    scope-expanded files whose hash differs between the two
    trees or that exist in only one of them."""
    base = {e["path"]: e["sha256"]
            for e in _expand_scope(base_root, scope_paths)}
    post = {e["path"]: e["sha256"]
            for e in _expand_scope(post_root, scope_paths)}
    out = []
    for path in sorted(set(base) | set(post)):
        base_sha = base.get(path)
        post_sha = post.get(path)
        if path not in base or path not in post or base_sha != post_sha:
            out.append({"path": path, "base_sha256": base_sha,
                        "post_sha256": post_sha})
    return out


def _validate_argv(argv) -> list:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ProofError("check argv must be a non-empty list of strings")
    if any(not isinstance(a, str) or not a or "\x00" in a for a in argv):
        raise ProofError("check argv must be a non-empty list of strings")
    return list(argv)


def _run_check(argv, cwd) -> tuple:
    """Run one declared check: (exit_code, stdout, stderr).
    shell=False, timeout 60s. A check that cannot be spawned
    or times out raises ProofError -- no verdict exists for it."""
    argv = _validate_argv(argv)
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), shell=False, timeout=_CHECK_TIMEOUT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired as exc:
        raise ProofError(f"check timed out: {argv!r}") from exc
    except (OSError, ValueError) as exc:
        raise ProofError(f"check could not be run: {argv!r}: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def _default_mutation(base_root, changed, target=None) -> dict:
    if target is not None:
        path = _check_scope_path(target)
        base_file = Path(base_root) / path
        if not base_file.is_file() or os.path.islink(base_file):
            content_b64 = None
        else:
            content_b64 = base64.b64encode(
                base_file.read_bytes()).decode("ascii")
        return {"path": path, "content_b64": content_b64}
    if not changed:
        raise ProofError(
            "cannot default a mutation: the change has no changed files")
    first = changed[0]
    base_file = Path(base_root) / first["path"]
    if first["base_sha256"] is None or not base_file.is_file():
        content_b64 = None
    else:
        content_b64 = base64.b64encode(base_file.read_bytes()).decode("ascii")
    return {"path": first["path"], "content_b64": content_b64}


def _validate_mutation(mutation, *, field="mutation") -> dict:
    if not isinstance(mutation, dict) or set(mutation) != _MUTATION_KEYS:
        raise ProofError(f"{field} must have exactly path and content_b64")
    path = _check_scope_path(mutation["path"])
    content_b64 = mutation["content_b64"]
    if content_b64 is not None:
        if not isinstance(content_b64, str):
            raise ProofError(f"{field} content_b64 must be a string or None")
        try:
            base64.b64decode(content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProofError(f"{field} content_b64 is not valid base64") from exc
    return {"path": path, "content_b64": content_b64}


def _validate_invariant_input(inv):
    """Validate a builder-side invariant spec. Returns
    (artefact_invariant, target): ``target`` is a builder-only
    input selecting the default-mutation file; it is consumed
    at build time and never stored in the artefact."""
    if not isinstance(inv, dict):
        raise ProofError("invariant must be a dict")
    unknown = set(inv) - (_INVARIANT_KEYS | {"target"})
    missing = {"id", "description", "argv", "scope"} - set(inv)
    if unknown or missing:
        raise ProofError(
            f"invariant keys must be id, description, argv, scope and "
            f"optionally mutation/target: {inv!r}")
    if not isinstance(inv["id"], str) or not inv["id"]:
        raise ProofError("invariant id must be a non-empty string")
    if not isinstance(inv["description"], str) or not inv["description"]:
        raise ProofError("invariant description must be a non-empty string")
    argv = _validate_argv(inv["argv"])
    if inv["scope"] not in ("new", "preserved"):
        raise ProofError("invariant scope must be 'new' or 'preserved'")
    out = {"id": inv["id"], "description": inv["description"],
           "argv": argv, "scope": inv["scope"]}
    if "mutation" in inv and inv["mutation"] is not None:
        out["mutation"] = _validate_mutation(inv["mutation"])
    target = None
    if "target" in inv and inv["target"] is not None:
        target = _check_scope_path(inv["target"])
    return out, target


def build_proof_artefact(*, change_id, base_root, post_root, scope_paths,
                         invariants, created_at="") -> dict:
    """Build a proof artefact for a change. Runs every declared
    check in a fresh scratch copy of the post tree (never on
    the live post tree) and records the outcome as builder-run
    evidence; a check that does not pass there, or that
    modifies its scratch copy, raises ProofError -- there is
    no artefact for a failing change. Checks are NOT run on
    the base or mutated trees here: showing they fail there is
    the verifier's job, done independently at verify time."""
    if not isinstance(change_id, str) or not change_id:
        raise ProofError("change_id must be a non-empty string")
    if not isinstance(created_at, str):
        raise ProofError("created_at must be a string")
    if created_at == "":
        created_at = _now()
    scope = _validate_scope_paths(scope_paths)
    if not isinstance(invariants, (list, tuple)) or not invariants:
        raise ProofError("invariants must be a non-empty list")
    base_hash = tree_hash(base_root, scope)
    post_hash = tree_hash(post_root, scope)
    changed = changed_files(base_root, post_root, scope)
    normalised = []
    evidence = []
    seen_ids = set()
    for inv in invariants:
        entry, target = _validate_invariant_input(inv)
        if entry["id"] in seen_ids:
            raise ProofError(f"duplicate invariant id: {entry['id']}")
        seen_ids.add(entry["id"])
        if "mutation" not in entry:
            entry["mutation"] = _default_mutation(
                base_root, changed, target=target)
        result, side_effect, _applied = _run_in_scratch(
            entry["argv"], post_root, scope)
        if result is None:
            raise ProofError(
                f"check could not be run: {entry['argv']!r}")
        if side_effect:
            raise ProofError(
                f"check_side_effect:{entry['id']}: the builder "
                f"check modified its scratch copy of the post "
                f"tree; refusing to build the artefact")
        exit_code, stdout, stderr = result
        if exit_code != 0:
            raise ProofError(
                f"check for invariant {entry['id']!r} failed on the "
                f"post tree (exit {exit_code}); cannot build a proof "
                f"artefact for a failing change")
        normalised.append(entry)
        evidence.append({
            "invariant_id": entry["id"],
            "tree_hash": post_hash,
            "exit_code": exit_code,
            "stdout_sha256": _sha256_bytes(stdout),
            "stderr_sha256": _sha256_bytes(stderr),
        })
    artefact = {
        "format": FORMAT,
        "mechanism": MECHANISM,
        "change_id": change_id,
        "created_at": created_at,
        "scope_paths": scope,
        "base_tree_hash": base_hash,
        "post_tree_hash": post_hash,
        "changed_files": changed,
        "invariants": normalised,
        "evidence": evidence,
    }
    artefact["artefact_hash"] = _sha256(_canonical(artefact))
    return artefact


def _artefact_malformed(artefact) -> bool:
    if not isinstance(artefact, dict) or set(artefact) != _ARTEFACT_KEYS:
        return True
    if artefact["format"] != FORMAT:
        return True
    if artefact["mechanism"] != MECHANISM:
        return True
    if not isinstance(artefact["change_id"], str) or not artefact["change_id"]:
        return True
    if not isinstance(artefact["created_at"], str):
        return True
    scope = artefact["scope_paths"]
    if not isinstance(scope, list) or not scope:
        return True
    try:
        for p in scope:
            _check_scope_path(p)
    except ProofError:
        return True
    if scope != sorted(scope) or len(set(scope)) != len(scope):
        return True
    if not _is_hex64(artefact["base_tree_hash"]):
        return True
    if not _is_hex64(artefact["post_tree_hash"]):
        return True
    if not _is_hex64(artefact["artefact_hash"]):
        return True
    changed = artefact["changed_files"]
    if not isinstance(changed, list):
        return True
    changed_paths = []
    for entry in changed:
        if not isinstance(entry, dict) or set(entry) != _CHANGED_KEYS:
            return True
        try:
            _check_scope_path(entry["path"])
        except (ProofError, TypeError):
            return True
        if not _path_in_scope(entry["path"], scope):
            return True
        if entry["base_sha256"] is None and entry["post_sha256"] is None:
            return True
        for key in ("base_sha256", "post_sha256"):
            if entry[key] is not None and not _is_hex64(entry[key]):
                return True
        changed_paths.append(entry["path"])
    if changed_paths != sorted(changed_paths) \
            or len(set(changed_paths)) != len(changed_paths):
        return True
    invariants = artefact["invariants"]
    if not isinstance(invariants, list):
        return True
    for inv in invariants:
        if not isinstance(inv, dict) or set(inv) != _INVARIANT_KEYS:
            return True
        if not isinstance(inv["id"], str) or not inv["id"]:
            return True
        if not isinstance(inv["description"], str) or not inv["description"]:
            return True
        try:
            _validate_argv(inv["argv"])
        except ProofError:
            return True
        if inv["scope"] not in ("new", "preserved"):
            return True
        mutation = inv["mutation"]
        if not isinstance(mutation, dict) or set(mutation) != _MUTATION_KEYS:
            return True
        if not isinstance(mutation["path"], str) or not mutation["path"]:
            return True
        if mutation["content_b64"] is not None \
                and not isinstance(mutation["content_b64"], str):
            return True
    evidence = artefact["evidence"]
    if not isinstance(evidence, list):
        return True
    for ev in evidence:
        if not isinstance(ev, dict) or set(ev) != _EVIDENCE_KEYS:
            return True
        if not isinstance(ev["invariant_id"], str) or not ev["invariant_id"]:
            return True
        if not _is_hex64(ev["tree_hash"]):
            return True
        if not isinstance(ev["exit_code"], int) \
                or isinstance(ev["exit_code"], bool):
            return True
        if not _is_hex64(ev["stdout_sha256"]):
            return True
        if not _is_hex64(ev["stderr_sha256"]):
            return True
    return False


def _path_in_scope(path, scope_paths) -> bool:
    for scope in scope_paths:
        if path == scope or path.startswith(scope.rstrip("/") + "/"):
            return True
    return False


def _path_escapes(path) -> bool:
    if not isinstance(path, str) or not path or "\\" in path \
            or path.startswith("/"):
        return True
    return any(part in ("", ".", "..") for part in path.split("/"))


def _safe_run(argv, cwd):
    try:
        return _run_check(argv, cwd)
    except (ProofError, ValueError):
        return None


_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def _run_in_scratch(argv, root, scope_paths, *, mutation=None):
    """Run argv in a fresh scratch copy of root.

    Returns (result, side_effect, applied):
      result     -- (exit_code, stdout, stderr), or None when
                    the copy or the run could not be made
                    (no verdict exists);
      side_effect -- True when the scratch tree's scope hash
                    after the run differs from before it;
      applied    -- False only when a requested mutation could
                    not be applied (result is then None).
    The copy always lives at <tmpdir>/tree, so every probe
    presents the same cwd basename."""
    applied = True
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tree"
            try:
                shutil.copytree(root, dest, ignore=_IGNORE)
            except (OSError, shutil.Error, ValueError):
                return (None, False, False) if mutation is not None \
                    else (None, False, True)
            if mutation is not None:
                target = dest / mutation["path"]
                try:
                    if target.is_dir():
                        return (None, False, False)
                    if mutation["content_b64"] is None:
                        target.unlink()
                    else:
                        decoded = base64.b64decode(
                            mutation["content_b64"], validate=True)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(decoded)
                except (OSError, ValueError, binascii.Error):
                    return (None, False, False)
            try:
                pre = tree_hash(dest, scope_paths)
            except ProofError:
                return (None, False, applied)
            result = _safe_run(argv, dest)
            try:
                post = tree_hash(dest, scope_paths)
                side_effect = post != pre
            except ProofError:
                side_effect = True
            return (result, side_effect, True)
    except (OSError, shutil.Error, ValueError):
        return (None, False, False) if mutation is not None \
            else (None, False, True)


_HARNESS_CRASH_MARKERS = (
    "ModuleNotFoundError", "ImportError",
    "SyntaxError", "IndentationError",
    # Fix round 2: a mutation that breaks a harness submodule
    # at attribute/name level surfaces as one of these, and
    # counting it as the check "noticing" would accept a
    # harness break as discrimination. Same documented
    # conservative tradeoff as the original markers: a
    # semantic failure whose stderr merely names one of these
    # is refused as mutation_invalid.
    "NameError", "AttributeError",
)


def _harness_crash_in_stderr(stderr: bytes) -> bool:
    text = stderr.decode("utf-8", errors="replace")
    return any(marker in text for marker in _HARNESS_CRASH_MARKERS)


def _is_plain_file(root, cand) -> bool:
    """True when ``root / cand`` is a regular file and not a
    symlink. Failure-silent by design (design 12.4.2: argv
    elements that are flags, interpreter paths, or expressions
    simply seed nothing): any filesystem error on a candidate
    -- OSError such as ENAMETOOLONG from a long argv element
    treated as a path, or ValueError from an unencodable one
    -- means the candidate is not a harness file, never an
    exception out of the closure computation."""
    try:
        full = root / cand
        return full.is_file() and not os.path.islink(full)
    except (OSError, ValueError):
        return False


def _harness_dependencies(argv, root) -> set:
    """The set of canonical repo-relative paths the check
    harness consists of: argv-referenced files plus the
    transitive local-import closure of any .py file among
    them, computed against the tree at ``root``."""
    root = Path(root)
    deps = set()
    for element in argv:
        if not isinstance(element, str):
            continue
        cand = element[2:] if element.startswith("./") else element
        try:
            _check_scope_path(cand)
        except ProofError:
            continue
        if _is_plain_file(root, cand):
            deps.add(cand)
    parsed = set()
    worklist = [p for p in deps if p.endswith(".py")]
    while worklist:
        current = worklist.pop()
        if current in parsed:
            continue
        parsed.add(current)
        try:
            tree_ast = ast.parse((root / current).read_bytes())
        except (OSError, SyntaxError, ValueError):
            continue
        importer_dir = current.rsplit("/", 1)[0] if "/" in current else ""
        for node in ast.walk(tree_ast):
            module_paths = []  # list of (parts, bases)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_paths.append(
                        (alias.name.split("."), None))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level >= 1:
                    base_parts = importer_dir.split("/") \
                        if importer_dir else []
                    ascend = node.level - 1
                    if ascend:
                        base_parts = base_parts[:-ascend] \
                            if ascend <= len(base_parts) else []
                    parts = list(base_parts)
                    if node.module:
                        parts += node.module.split(".")
                    module_paths.append((parts, "relative"))
                elif node.module:
                    module_paths.append(
                        (node.module.split("."), None))
                # `from package import submodule`: the imported
                # names may themselves be submodule files
                # (package/submodule.py) and belong in the
                # closure; names that are plain attributes of
                # the package simply yield no existing candidate
                # and seed nothing.
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if module_paths:
                        base_parts, base_kind = module_paths[-1]
                        module_paths.append(
                            (list(base_parts) + [alias.name],
                             base_kind))
            for parts, kind in module_paths:
                if kind == "relative":
                    bases = [""]
                    # parts already include the importing dir.
                    candidates = _import_candidates(parts, "")
                    _add_import_candidates(
                        candidates, root, deps, worklist)
                else:
                    for base in ("", importer_dir):
                        candidates = _import_candidates(parts, base)
                        _add_import_candidates(
                            candidates, root, deps, worklist)
    return deps


def _import_candidates(parts, base) -> list:
    """Candidate files for a module path ``parts`` resolved
    against directory ``base`` (repo-relative, '' = root):
    base/parts.py, base/parts/__init__.py, and for each proper
    prefix, base/prefix/__init__.py."""
    if not parts or any(p in ("", ".", "..") for p in parts):
        return []
    prefix = (base + "/") if base else ""
    joined = "/".join(parts)
    candidates = [prefix + joined + ".py",
                  prefix + joined + "/__init__.py"]
    for i in range(1, len(parts)):
        candidates.append(
            prefix + "/".join(parts[:i]) + "/__init__.py")
    return candidates


def _add_import_candidates(candidates, root, deps, worklist) -> None:
    for cand in candidates:
        try:
            _check_scope_path(cand)
        except ProofError:
            continue
        if _is_plain_file(root, cand) and cand not in deps:
            deps.add(cand)
            if cand.endswith(".py"):
                worklist.append(cand)


def _mutation_references_argv(mutation_path, argv) -> bool:
    """True when the mutation would perturb the check harness
    itself: the mutation path (or its basename, as a whole
    path component) appears in an argv element. A mutation
    must perturb the checked content, never the harness."""
    base = mutation_path.rsplit("/", 1)[-1]
    for element in argv:
        if not isinstance(element, str):
            continue
        if element == mutation_path or element == base:
            return True
        if mutation_path in element:
            return True
        if ("/" + base) in element or element.endswith("/" + base):
            return True
    return False


def _mutation_invalid_reason(inv, post_files, post_root, scope_paths):
    """Pre-execution mutation validation (design step 5 plus
    the harness rules). Returns True if invalid."""
    mutation = inv["mutation"]
    mpath = mutation["path"]
    try:
        _check_scope_path(mpath)
    except ProofError:
        return True
    if not _path_in_scope(mpath, scope_paths):
        return True
    if post_files is None or mpath not in post_files:
        return True
    if mpath in _harness_dependencies(inv["argv"], post_root):
        return True
    if _mutation_references_argv(mpath, inv["argv"]):
        return True
    if mutation["content_b64"] is None:
        return False
    try:
        decoded = base64.b64decode(mutation["content_b64"], validate=True)
    except (binascii.Error, ValueError):
        return True
    try:
        current = (Path(post_root) / mpath).read_bytes()
    except OSError:
        return True
    if decoded == current:
        return True
    return False


def verify_proof_artefact(artefact, *, base_root, post_root,
                          expected_change_id=None) -> tuple:
    """All refusal reasons for accepting this artefact against
    the live base and post trees; () means accept. Step 1
    (schema) returns ("artefact_malformed",) alone and step 2
    (self-hash) returns ("artefact_hash_mismatch",) alone:
    nothing in such an artefact -- above all its argv -- is
    executed. Steps 3-5 accumulate; if any of them produced a
    reason, return without executing any argv."""
    if _artefact_malformed(artefact):
        return ("artefact_malformed",)
    core = {k: v for k, v in artefact.items() if k != "artefact_hash"}
    if _sha256(_canonical(core)) != artefact["artefact_hash"]:
        return ("artefact_hash_mismatch",)

    reasons = []

    def add(reason):
        if reason not in reasons:
            reasons.append(reason)

    # Step 3: change binding.
    if expected_change_id is not None \
            and artefact["change_id"] != expected_change_id:
        add("change_id_mismatch")

    # Step 4: tree binding + changed_files re-derivation.
    scope = artefact["scope_paths"]
    post_files = None
    try:
        live_base_hash = tree_hash(base_root, scope)
    except ProofError:
        live_base_hash = None
    if live_base_hash != artefact["base_tree_hash"]:
        add("base_tree_mismatch")
    try:
        live_post_hash = tree_hash(post_root, scope)
    except ProofError:
        live_post_hash = None
    if live_post_hash != artefact["post_tree_hash"]:
        add("post_tree_mismatch")
    if live_base_hash is not None and live_post_hash is not None:
        try:
            post_files = {
                e["path"] for e in _expand_scope(post_root, scope)
                if e["sha256"] is not None}
            derived = changed_files(base_root, post_root, scope)
        except ProofError:
            derived = None
        if derived is not None and derived != artefact["changed_files"]:
            add("post_tree_mismatch")
    else:
        try:
            post_files = {
                e["path"] for e in _expand_scope(post_root, scope)
                if e["sha256"] is not None}
        except ProofError:
            post_files = None

    # Step 5: invariant / evidence cross-validation (no execution).
    invariants = artefact["invariants"]
    if not invariants:
        add("no_invariants")
    ids = []
    for inv in invariants:
        if inv["id"] in ids:
            add(f"invariant_duplicate:{inv['id']}")
        else:
            ids.append(inv["id"])
    by_id = {}
    for inv in invariants:
        by_id.setdefault(inv["id"], inv)

    evidence = artefact["evidence"]
    ev_by_id = {}
    for ev in evidence:
        ev_by_id.setdefault(ev["invariant_id"], []).append(ev)
    for inv_id in ids:
        if inv_id not in ev_by_id:
            add(f"evidence_missing:{inv_id}")
    for ev_id, entries in ev_by_id.items():
        if ev_id not in by_id or len(entries) > 1:
            add(f"evidence_unexpected:{ev_id}")
    single_ev = {k: v[0] for k, v in ev_by_id.items() if len(v) == 1}

    for inv_id in ids:
        ev = single_ev.get(inv_id)
        if ev is None:
            continue
        if ev["tree_hash"] != artefact["post_tree_hash"]:
            add(f"evidence_tree_mismatch:{inv_id}")
        if ev["exit_code"] != 0:
            add(f"evidence_failed:{inv_id}")

    for inv_id in ids:
        if _mutation_invalid_reason(by_id[inv_id], post_files, post_root,
                                    scope):
            add(f"mutation_invalid:{inv_id}")

    if reasons:
        return tuple(reasons)

    # Step 6: post-tree re-run, in a fresh scratch copy. A
    # run with a side effect is void: its verdict is discarded
    # entirely.
    for inv_id in ids:
        inv = by_id[inv_id]
        result, side_effect, _applied = _run_in_scratch(
            inv["argv"], post_root, scope)
        if side_effect:
            add(f"check_side_effect:{inv_id}")
            continue
        if result is None or result[0] != 0:
            add(f"check_failed:{inv_id}")
            continue
        ev = single_ev.get(inv_id)
        if ev is not None:
            if _sha256_bytes(result[1]) != ev["stdout_sha256"] \
                    or _sha256_bytes(result[2]) != ev["stderr_sha256"]:
                add(f"evidence_output_mismatch:{inv_id}")
    # Step 7: base-tree discrimination -- "new" only. A probe
    # that cannot be observed to fail (exit 0, timeout, or
    # spawn error) does not discriminate. A side-effecting
    # run is void, not discrimination.
    for inv_id in ids:
        inv = by_id[inv_id]
        if inv["scope"] != "new":
            continue
        result, side_effect, _applied = _run_in_scratch(
            inv["argv"], base_root, scope)
        if side_effect:
            add(f"check_side_effect:{inv_id}")
            continue
        if result is None or result[0] == 0:
            add(f"check_not_discriminating:{inv_id}")
    # Step 8: mutation vacuity -- every invariant. Apply the
    # mutation in a fresh scratch copy of the post tree; a
    # probe that cannot be observed to fail is vacuous, and a
    # mutated run that fails with a harness-crash signature
    # in stderr is mutation_invalid, never noticing.
    for inv_id in ids:
        inv = by_id[inv_id]
        result, side_effect, applied = _run_in_scratch(
            inv["argv"], post_root, scope, mutation=inv["mutation"])
        if side_effect:
            add(f"check_side_effect:{inv_id}")
            continue
        if not applied:
            add(f"mutation_invalid:{inv_id}")
            continue
        if result is None or result[0] == 0:
            add(f"check_vacuous:{inv_id}")
            continue
        if _harness_crash_in_stderr(result[2]):
            add(f"mutation_invalid:{inv_id}")
    return tuple(reasons)


def record_ship_with_proof(loop, *, base_root, post_root, artefact,
                           expected_change_id=None,
                           **record_ship_kwargs):
    """The proof-carrying ship path: verify the artefact
    against the live trees first; any refusal raises ShipRefused
    before anything is delegated, so nothing is burned for an
    unproven change. On acceptance the wrapper snapshots the
    post tree, verifies the artefact against the snapshot, and
    delegates to trust.shipcheck.record_ship with
    root=<snapshot> -- the live post tree is never delegated.
    After a successful ship it sets proof_artefact_hash and
    proof_post_tree_hash on the returned entry and appends a
    hash-chained binding record to proof-bindings.jsonl in
    the ledger's journal directory. Before anything is
    delegated the existing chain must verify and the file
    must be appendable (fail-closed, pre-burn). The proof
    keys set on the returned entry are a convenience on the
    caller's copy only and are not persisted loop state; the
    bindings file is the durable carrier. The chain detects
    edits to recorded bindings; it does not anchor the tail
    outside the journal's trust domain — that remains a
    separate follow-up and is not claimed here."""
    # W0: guards, before anything else.
    if "root" in record_ship_kwargs:
        raise ProofError("root is supplied by record_ship_with_proof")
    if "ledger" not in record_ship_kwargs \
            or "manifest" not in record_ship_kwargs:
        raise ProofError(
            "record_ship_with_proof requires ledger=... and "
            "manifest=... so the proof binding can be recorded")
    # W1: live verification.
    reasons = verify_proof_artefact(
        artefact, base_root=base_root, post_root=post_root,
        expected_change_id=expected_change_id)
    if reasons:
        raise ShipRefused(
            "proof_refused:" + ",".join(reasons), reasons)
    try:
        current_post_hash = tree_hash(post_root, artefact["scope_paths"])
    except ProofError:
        current_post_hash = None
    if current_post_hash != artefact["post_tree_hash"]:
        raise ShipRefused("proof_refused:post_tree_mismatch",
                          ("post_tree_mismatch",))
    # W2: unscoped refusal.
    try:
        unscoped = _unscoped_changes(
            base_root, post_root, artefact["scope_paths"])
    except ProofError:
        unscoped = ("unscoped_changes",)
    if unscoped:
        raise ShipRefused("proof_refused:unscoped_changes",
                          ("unscoped_changes",))
    # W2b: fail-closed binding gate, after live verification
    # and before the snapshot/delegation — still before any
    # burn, because the burn happens inside the delegation.
    # The existing binding chain must verify and the bindings
    # file must be appendable; a corrupt or unwritable
    # bindings file refuses here, while nothing is spent —
    # a ship that cannot be bound must not happen at all,
    # instead of shipping and discovering it afterwards.
    binding_reasons = _preflight_proof_binding(
        record_ship_kwargs["ledger"].journal_dir)
    if binding_reasons:
        raise ShipRefused(
            "proof_refused:" + ",".join(binding_reasons),
            binding_reasons)
    # W3: snapshot the post tree. W4/W5 run inside the context.
    entered = False
    try:
        with _snapshot_tree(post_root) as snapshot:
            entered = True
            # W4: snapshot verification (authoritative).
            reasons = verify_proof_artefact(
                artefact, base_root=base_root, post_root=snapshot,
                expected_change_id=expected_change_id)
            if reasons:
                raise ShipRefused(
                    "proof_refused:" + ",".join(reasons), reasons)
            # W4b: unscoped re-check against the SNAPSHOT.
            # W2 checked the live trees; an out-of-scope edit
            # landing between W2 and the snapshot copy would
            # otherwise enter the snapshot, pass W4 (which
            # verifies scope_paths only) and ship invisibly
            # for paths the manifest does not bind.
            try:
                snap_unscoped = _unscoped_changes(
                    base_root, snapshot, artefact["scope_paths"])
            except ProofError:
                snap_unscoped = ("unscoped_changes",)
            if snap_unscoped:
                raise ShipRefused(
                    "proof_refused:unscoped_changes",
                    ("unscoped_changes",))
            # W5: delegate inside the context.
            entry = trust.shipcheck.record_ship(
                loop, root=snapshot, **record_ship_kwargs)
    except (ProofError, OSError, shutil.Error):
        if entered:
            raise
        raise ShipRefused("proof_refused:post_tree_mismatch",
                          ("post_tree_mismatch",))
    # W6: returned-entry proof fields (non-durable convenience).
    entry["proof_artefact_hash"] = artefact["artefact_hash"]
    entry["proof_post_tree_hash"] = artefact["post_tree_hash"]
    # W7: durable binding record.
    record = {
        "cycle_id": entry["cycle_id"],
        "item_id": entry["item_id"],
        "change_id": artefact["change_id"],
        "manifest_hash": record_ship_kwargs["manifest"].manifest_hash,
        "artefact_hash": artefact["artefact_hash"],
        "post_tree_hash": artefact["post_tree_hash"],
        "recorded_at": _now(),
    }
    try:
        _append_proof_binding(
            record_ship_kwargs["ledger"].journal_dir, record)
    except (OSError, ProofError) as exc:
        raise ShipRefused(
            f"cycle {entry['cycle_id']} recorded and the decision "
            f"finalised, but the proof binding failed: {exc}")
    return entry
