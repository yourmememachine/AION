"""Immutable build manifests: one decision authorises one artifact.

A signed gate decision used to authorise a *directory* — whatever
the source tree happened to contain when someone later acted on
it. A manifest names the artifact exactly: every regular file in
the evaluated source roots, content-hashed, bucketed, and rolled
into one manifest_hash under canonical serialisation. A ship
decision binds that hash (as its gate_inputs_hash, and in the
verifier_note's first segment); the ship check rebuilds the
manifest from the live tree at ship time and refuses on any
difference. The artifact a decision authorised is the artifact
that ships, or nothing ships.

Scope decisions, stated plainly:

* Buckets: evaluator (eval/), tests (tests/), source (core/,
  memory/, signing/, selfmod/, oversight/, trust/, machine/,
  products/). Inclusion is extension-agnostic: every regular file
  under those roots is in. Directories themselves are not entries
  (an empty directory ships nothing; a file later dropped into it
  is an added file). __pycache__ is treated as hostile, not
  ignored: a .pyc there is a bytecode shadow that Python may
  execute instead of the authorised source (a forged
  timestamp-header .pyc runs without the source changing), so ANY
  file inside a __pycache__ directory refuses a build and
  invalidates a verification. A planted .pyc anywhere else is an
  added file and fails verification. Release hygiene follows:
  build manifests over a pycache-clean tree.
* state/ is NEVER in the manifest: recording a ship mutates
  state, so including it would make every authorisation
  self-invalidating. The cost, stated not hidden: a decision
  authorises code + tests + evaluator + the review record — not
  data state. Binding state belongs to a future cycle.
* docs/, agents/, README.md are excluded (non-behavioural).
  internal/ is excluded except the cycle's review record, which
  is bound separately by review_record_hash so the record that
  authorised the ship cannot be edited afterwards either.
* The executable bit is bound (a chmod +x on a script is a
  behaviour change); the full mode and mtime are not (they are
  not behaviour).
* Canonical paths only: relative, "/" separated, no "", ".", ".."
  or empty components, no backslash, no duplicates. Two files
  differing only by case are refused (case-insensitive filesystems
  would alias them).
* Symlinks and non-regular files under an included root are
  refused outright: the walk refuses every symlink it observes.
  A link swapped in between the walk's check and the subsequent
  file read would be followed by the read — an accepted race
  under the stated threat model (convenience/evolved code, not a
  malicious same-user process racing the walk), disclosed here
  rather than claimed away.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from signing.gate_decision import _canonical, _now, _sha256
from trust.pathpolicy import canonicalise as _policy_canonicalise

MANIFEST_DOMAIN = "build-manifest/1"
REVIEW_RECORD_DOMAIN = "review-record/1"

BUCKETS = {
    "evaluator": ("eval",),
    "tests": ("tests",),
    "source": ("core", "memory", "signing", "selfmod", "oversight",
               "trust", "machine", "products"),
}
INCLUDED_ROOTS = tuple(root for roots in BUCKETS.values() for root in roots)

MAX_TREE_FILES = 2000
MAX_TREE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_DIFF_ENTRIES = 100

_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_STAGES = ("provisional", "final")
_MANIFEST_KEYS = {"v", "proposal_id", "item_id", "created_at", "stage",
                  "supersedes_manifest_hash", "files", "bucket_hashes",
                  "review_record", "manifest_hash"}
_FILE_KEYS = {"path", "bucket", "sha256", "size", "executable"}
_REVIEW_KEYS = {"path", "sha256", "size", "record_hash"}
_BUCKET_NAMES = tuple(BUCKETS)


class ManifestError(ValueError):
    """A tree or manifest document is malformed or refused. Raised
    for structural problems only; content differences are reported
    by verify_manifest as a ManifestDiff, never raised."""


def canonicalise_path(raw, *, field="path") -> str:
    """Repo-relative canonical path or ManifestError. Backslashes
    are refused rather than translated: accepting both spellings
    would let one file hide behind two names.

    Adoption of the shared path policy (trust/pathpolicy.py,
    POLICY_VERSION "path-policy/1"): the strict spelling checks
    above/below are this module's own — a manifest must name ONE
    spelling per file, so spellings the policy would rewrite
    (backslashes, "//", "./", a trailing "/") are refused here
    rather than normalised — but the final canonicalisation is
    delegated to the policy, and any spelling the policy's
    canonical form differs from (surrounding whitespace, a drive
    prefix, a NUL byte) is refused instead of rewritten. For
    every spelling this function accepts, its result is exactly
    the policy's canonical spelling."""
    if not isinstance(raw, str) or not raw:
        raise ManifestError(f"{field} must be a non-empty string")
    if "\\" in raw:
        raise ManifestError(f"{field} must use '/' separators: {raw!r}")
    if raw.startswith("/") or raw.endswith("/"):
        raise ManifestError(f"{field} must be a clean relative path: {raw!r}")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ManifestError(
            f"{field} has an empty, '.' or '..' component: {raw!r}")
    try:
        canonical = _policy_canonicalise(raw)
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc
    if canonical != raw:
        raise ManifestError(
            f"{field} must use the canonical spelling {canonical!r}: "
            f"{raw!r}")
    return canonical


def bucket_for_path(path: str) -> str:
    top = path.split("/", 1)[0]
    for bucket, roots in BUCKETS.items():
        if top in roots:
            return bucket
    raise ManifestError(f"path is outside the included roots: {path!r}")


def _is_excluded(rel_parts) -> bool:
    return "__pycache__" in rel_parts


def _iter_tree_files(root: Path):
    """Yield (canonical_rel_path, abs_path, stat_result) for every
    regular file under the included roots. Raises ManifestError on
    symlinks, non-regular files, case collisions, and cap breaches.
    Missing roots are simply absent (an empty root is fine; a
    missing *repo* is the caller's error, checked in build)."""
    seen = {}
    total_bytes = 0
    count = 0
    for top in INCLUDED_ROOTS:
        base = root / top
        if not base.exists():
            continue
        if base.is_symlink() or not base.is_dir():
            raise ManifestError(f"included root is not a real directory: {top}")
        for dirpath, dirnames, filenames in os.walk(base,
                                                    followlinks=False):
            dirnames.sort()
            for dirname in list(dirnames):
                full = Path(dirpath) / dirname
                if full.is_symlink():
                    rel = full.relative_to(root).as_posix()
                    # No exemption for __pycache__: a SYMLINKED
                    # __pycache__ directory points the interpreter
                    # at bytecode outside the tree — the same
                    # shadow channel with a narrower plant — so
                    # every symlinked directory is refused.
                    raise ManifestError(
                        f"symlinked directory inside the tree: {rel}")
            for name in sorted(filenames):
                full = Path(dirpath) / name
                rel = full.relative_to(root).as_posix()
                if _is_excluded(rel.split("/")):
                    continue
                if full.is_symlink() or not full.is_file():
                    raise ManifestError(
                        f"non-regular file inside the tree: {rel}")
                canonical = canonicalise_path(rel)
                lowered = canonical.lower()
                if lowered in seen and seen[lowered] != canonical:
                    raise ManifestError(
                        f"case-colliding paths in tree: {seen[lowered]!r} "
                        f"and {canonical!r}")
                seen[lowered] = canonical
                try:
                    info = full.stat()
                except OSError as exc:
                    raise ManifestError(
                        f"file is unstatable: {rel}: {exc}") from exc
                if info.st_size > MAX_FILE_BYTES:
                    raise ManifestError(f"file exceeds the size cap: {rel}")
                count += 1
                total_bytes += info.st_size
                if count > MAX_TREE_FILES or total_bytes > MAX_TREE_BYTES:
                    raise ManifestError("tree exceeds the manifest caps")
                yield canonical, full, info


def _hash_file(full: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestError(f"file is unreadable: {full}: {exc}") from exc
    return digest.hexdigest()


def _find_shadows(root: Path) -> list:
    """Files inside __pycache__ directories under the included
    roots: bytecode shadows that must refuse a build and
    invalidate a verification (see the module docstring)."""
    shadows = []
    for top in INCLUDED_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            for dirname in dirnames:
                full = Path(dirpath) / dirname
                if dirname == "__pycache__" and full.is_symlink():
                    shadows.append(full.relative_to(root).as_posix())
            parts = Path(dirpath).relative_to(root).parts
            if "__pycache__" not in parts:
                continue
            for name in filenames:
                shadows.append(
                    (Path(dirpath) / name).relative_to(root).as_posix())
    return sorted(shadows)


def review_record_hash_for(*, path: str, sha256: str, size: int) -> str:
    return _sha256(_canonical({"v": REVIEW_RECORD_DOMAIN, "path": path,
                               "sha256": sha256, "size": size}))


def _bucket_hash(entries) -> str:
    lines = "\n".join(f"{e['path']}\0{e['sha256']}\0{e['size']}"
                      for e in entries)
    return _sha256(_canonical(
        {"v": MANIFEST_DOMAIN + "-files", "lines": lines}))


_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")


def _check_manifest_id(value, field_name):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ManifestError(f"{field_name} must match ^[a-z0-9_-]{{1,64}}$")
    return value


def _manifest_core(*, proposal_id, item_id, stage,
                   supersedes_manifest_hash, files, bucket_hashes,
                   review_record) -> dict:
    return {
        "v": MANIFEST_DOMAIN,
        "proposal_id": proposal_id,
        "item_id": item_id,
        "stage": stage,
        "supersedes_manifest_hash": supersedes_manifest_hash,
        "files": files,
        "bucket_hashes": bucket_hashes,
        "review_record": review_record,
    }


@dataclass(frozen=True)
class BuildManifest:
    proposal_id: str
    item_id: str
    created_at: str
    stage: str
    supersedes_manifest_hash: str
    files: tuple          # tuple of dicts, sorted by path
    bucket_hashes: dict
    review_record: dict   # {path, sha256, size, record_hash}
    manifest_hash: str

    def core(self) -> dict:
        return _manifest_core(
            proposal_id=self.proposal_id, item_id=self.item_id,
            stage=self.stage,
            supersedes_manifest_hash=self.supersedes_manifest_hash,
            files=[dict(f) for f in self.files],
            bucket_hashes=dict(self.bucket_hashes),
            review_record=dict(self.review_record))

    def recomputed_hash(self) -> str:
        return _sha256(_canonical(self.core()))

    def to_dict(self) -> dict:
        doc = self.core()
        doc["created_at"] = self.created_at
        doc["manifest_hash"] = self.manifest_hash
        return doc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)


def _check_hex64(value, field_name):
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise ManifestError(f"{field_name} must be a lowercase hex64")
    return value


def manifest_from_dict(data) -> BuildManifest:
    """Strict structural load. Content mismatches (including a
    manifest_hash that does not recompute) are NOT raised here —
    verify_manifest reports them — but anything structurally off
    (unknown keys, bad types, unsorted or duplicated paths, bad
    buckets) is a ManifestError."""
    if not isinstance(data, dict) or set(data) != _MANIFEST_KEYS:
        raise ManifestError("manifest has missing or unknown keys")
    if data["v"] != MANIFEST_DOMAIN:
        raise ManifestError("manifest version is not build-manifest/1")
    _check_manifest_id(data["proposal_id"], "proposal id")
    _check_manifest_id(data["item_id"], "item id")
    if data["stage"] not in _STAGES:
        raise ManifestError("manifest stage is unknown")
    if data["supersedes_manifest_hash"]:
        _check_hex64(data["supersedes_manifest_hash"],
                     "supersedes_manifest_hash")
    if not isinstance(data["created_at"], str) or not data["created_at"]:
        raise ManifestError("created_at must be a non-empty string")
    _check_hex64(data["manifest_hash"], "manifest_hash")
    files = data["files"]
    if not isinstance(files, list) or len(files) > MAX_TREE_FILES:
        raise ManifestError("files must be a bounded list")
    seen = set()
    seen_lowered = {}
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != _FILE_KEYS:
            raise ManifestError("file entry has missing or unknown keys")
        path = canonicalise_path(entry["path"], field="file path")
        if path in seen:
            raise ManifestError(f"duplicate file entry: {path}")
        seen.add(path)
        lowered = path.lower()
        if lowered in seen_lowered:
            raise ManifestError(
                f"case-colliding file entries: {seen_lowered[lowered]!r} "
                f"and {path!r}")
        seen_lowered[lowered] = path
        if entry["bucket"] != bucket_for_path(path):
            raise ManifestError(f"file entry bucket disagrees with path: {path}")
        _check_hex64(entry["sha256"], f"sha256 for {path}")
        if not isinstance(entry["size"], int) \
                or isinstance(entry["size"], bool) or entry["size"] < 0:
            raise ManifestError(f"size for {path} must be a non-negative int")
        if entry["size"] > MAX_FILE_BYTES:
            raise ManifestError(f"size for {path} exceeds the per-file cap")
        total += entry["size"]
        if not isinstance(entry["executable"], bool):
            raise ManifestError(f"executable for {path} must be a bool")
    if total > MAX_TREE_BYTES:
        raise ManifestError("manifest exceeds the tree byte cap")
    bucket_hashes = data["bucket_hashes"]
    if not isinstance(bucket_hashes, dict) \
            or set(bucket_hashes) != set(_BUCKET_NAMES):
        raise ManifestError("bucket_hashes must cover exactly the buckets")
    for name, value in bucket_hashes.items():
        _check_hex64(value, f"bucket hash {name}")
    record = data["review_record"]
    if not isinstance(record, dict) or set(record) != _REVIEW_KEYS:
        raise ManifestError("review_record has missing or unknown keys")
    record_path = canonicalise_path(record["path"],
                                    field="review record path")
    if not record_path.startswith("internal/"):
        raise ManifestError("review record must live under internal/")
    _check_hex64(record["sha256"], "review record sha256")
    _check_hex64(record["record_hash"], "review record hash")
    if not isinstance(record["size"], int) \
            or isinstance(record["size"], bool) or record["size"] < 0:
        raise ManifestError("review record size must be a non-negative int")
    if record["record_hash"] != review_record_hash_for(
            path=record_path, sha256=record["sha256"],
            size=record["size"]):
        raise ManifestError("review record hash does not recompute")
    ordered = sorted(files, key=lambda e: e["path"])
    return BuildManifest(
        proposal_id=data["proposal_id"], item_id=data["item_id"],
        created_at=data["created_at"], stage=data["stage"],
        supersedes_manifest_hash=data["supersedes_manifest_hash"],
        files=tuple(dict(e) for e in ordered),
        bucket_hashes=dict(bucket_hashes),
        review_record={"path": record_path, "sha256": record["sha256"],
                       "size": record["size"],
                       "record_hash": record["record_hash"]},
        manifest_hash=data["manifest_hash"])


def manifest_from_json(text) -> BuildManifest:
    if not isinstance(text, str):
        raise ManifestError("manifest JSON must be text")
    if len(text.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest exceeds the size cap")

    def _no_duplicates(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ManifestError(f"duplicate key in JSON: {key!r}")
            out[key] = value
        return out

    def _reject_constant(name):
        raise ManifestError(f"non-finite JSON number: {name}")

    def _parse_float(text):
        # Mirror signing/gate_decision.py's parse_float hook: a
        # float token that overflows to inf (e.g. 1e999) is
        # refused by the PARSER, structurally.
        value = float(text)
        if not math.isfinite(value):
            raise ManifestError(f"non-finite JSON number: {text}")
        return value

    try:
        data = json.loads(text, object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except ManifestError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    return manifest_from_dict(data)


def build_manifest(root, *, proposal_id, item_id, review_record_path,
                   stage, supersedes_manifest_hash="",
                   created_at="") -> BuildManifest:
    """Hash the live tree under root into a manifest. The review
    record (under internal/) is read and bound by hash; it is not
    part of the file list."""
    root = Path(root)
    if not root.is_dir():
        raise ManifestError(f"manifest root is not a directory: {root}")
    shadows = _find_shadows(root)
    if shadows:
        raise ManifestError(
            "bytecode shadows inside __pycache__ refuse a build: "
            + ", ".join(shadows[:5]))
    _check_manifest_id(proposal_id, "proposal id")
    _check_manifest_id(item_id, "item id")
    if stage not in _STAGES:
        raise ManifestError("manifest stage is unknown")
    if supersedes_manifest_hash:
        _check_hex64(supersedes_manifest_hash, "supersedes_manifest_hash")
    record_rel = canonicalise_path(review_record_path,
                                   field="review record path")
    if not record_rel.startswith("internal/"):
        raise ManifestError("review record must live under internal/")
    record_full = root / record_rel
    if record_full.is_symlink() or not record_full.is_file():
        raise ManifestError(f"review record is not a regular file: "
                            f"{record_rel}")
    record_bytes_hash = _hash_file(record_full)
    record_size = record_full.stat().st_size
    review_record = {
        "path": record_rel, "sha256": record_bytes_hash,
        "size": record_size,
        "record_hash": review_record_hash_for(
            path=record_rel, sha256=record_bytes_hash, size=record_size),
    }
    files = []
    for canonical, full, info in _iter_tree_files(root):
        files.append({
            "path": canonical,
            "bucket": bucket_for_path(canonical),
            "sha256": _hash_file(full),
            "size": info.st_size,
            "executable": bool(info.st_mode & 0o111),
        })
    files.sort(key=lambda e: e["path"])
    bucket_hashes = {
        name: _bucket_hash([e for e in files if e["bucket"] == name])
        for name in _BUCKET_NAMES
    }
    core = _manifest_core(
        proposal_id=proposal_id, item_id=item_id, stage=stage,
        supersedes_manifest_hash=supersedes_manifest_hash, files=files,
        bucket_hashes=bucket_hashes, review_record=review_record)
    return BuildManifest(
        proposal_id=proposal_id, item_id=item_id,
        created_at=created_at or _now(), stage=stage,
        supersedes_manifest_hash=supersedes_manifest_hash,
        files=tuple(files), bucket_hashes=bucket_hashes,
        review_record=review_record,
        manifest_hash=_sha256(_canonical(core)))


def write_manifest(manifest: BuildManifest, root, out_path) -> Path:
    """Write the manifest JSON. Refuses any destination inside an
    included root (the manifest must not be able to name itself)
    and refuses to overwrite the review record."""
    root = Path(root)
    target = Path(out_path)
    if not target.is_absolute():
        target = root / target
    try:
        rel = target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = None  # outside the tree entirely: allowed
    if rel is not None:
        top = rel.split("/", 1)[0]
        if top in INCLUDED_ROOTS:
            raise ManifestError(
                "manifest must not be written inside an included root")
        if rel == manifest.review_record["path"]:
            raise ManifestError("manifest must not overwrite the "
                                "review record")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.to_json(), encoding="utf-8")
    return target


@dataclass
class ManifestDiff:
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    executable_flips: list = field(default_factory=list)
    bucket_mismatches: list = field(default_factory=list)
    pycache_shadows: list = field(default_factory=list)
    review_record_mismatch: bool = False
    manifest_hash_mismatch: bool = False

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed
                    or self.executable_flips or self.bucket_mismatches
                    or self.pycache_shadows
                    or self.review_record_mismatch
                    or self.manifest_hash_mismatch)

    def summary(self) -> tuple:
        out = []
        if self.manifest_hash_mismatch:
            out.append("manifest_hash_mismatch")
        if self.review_record_mismatch:
            out.append("review_record_mismatch")
        out += [f"added:{p}" for p in self.added]
        out += [f"removed:{p}" for p in self.removed]
        out += [f"changed:{c['path']}" for c in self.changed]
        out += [f"executable_flip:{p}" for p in self.executable_flips]
        out += [f"bucket_mismatch:{b}" for b in self.bucket_mismatches]
        out += [f"pycache_shadow:{p}" for p in self.pycache_shadows]
        return tuple(out)


def verify_manifest(root, manifest: BuildManifest) -> ManifestDiff:
    """Rebuild the file list from the live tree and compare against
    the stored manifest. A malformed live tree (symlink, oversize)
    raises ManifestError — callers on authorising paths must treat
    that as refusal, which trust.shipcheck does."""
    root = Path(root)
    diff = ManifestDiff()
    if manifest.recomputed_hash() != manifest.manifest_hash:
        diff.manifest_hash_mismatch = True
    for shadow in _find_shadows(root):
        if len(diff.pycache_shadows) < MAX_DIFF_ENTRIES:
            diff.pycache_shadows.append(shadow)
    record_full = root / manifest.review_record["path"]
    try:
        record_size = record_full.stat().st_size
    except OSError:
        record_size = -1
    if record_full.is_symlink() or not record_full.is_file() \
            or _hash_file(record_full) != manifest.review_record["sha256"] \
            or record_size != manifest.review_record["size"]:
        diff.review_record_mismatch = True
    live = {}
    for canonical, full, info in _iter_tree_files(root):
        live[canonical] = {
            "path": canonical, "bucket": bucket_for_path(canonical),
            "sha256": _hash_file(full), "size": info.st_size,
            "executable": bool(info.st_mode & 0o111),
        }
    stored = {e["path"]: e for e in manifest.files}
    for path in sorted(set(live) - set(stored)):
        if len(diff.added) < MAX_DIFF_ENTRIES:
            diff.added.append(path)
    for path in sorted(set(stored) - set(live)):
        if len(diff.removed) < MAX_DIFF_ENTRIES:
            diff.removed.append(path)
    for path in sorted(set(stored) & set(live)):
        before, after = stored[path], live[path]
        if before["sha256"] != after["sha256"] \
                or before["size"] != after["size"]:
            if len(diff.changed) < MAX_DIFF_ENTRIES:
                diff.changed.append({"path": path,
                                     "stored": before["sha256"],
                                     "live": after["sha256"]})
        elif before["executable"] != after["executable"]:
            if len(diff.executable_flips) < MAX_DIFF_ENTRIES:
                diff.executable_flips.append(path)
    for name in _BUCKET_NAMES:
        live_bucket = _bucket_hash(
            [live[p] for p in sorted(live) if live[p]["bucket"] == name])
        stored_bucket = _bucket_hash(
            [stored[p] for p in sorted(stored)
             if stored[p]["bucket"] == name])
        if live_bucket != manifest.bucket_hashes[name] \
                or stored_bucket != manifest.bucket_hashes[name]:
            diff.bucket_mismatches.append(name)
    return diff
