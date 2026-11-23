"""Call-graph lint for the trust boundary (cycle 7/8).

The sanctioned paths are signed-only: memory commits go through
signing.commit_signed, ships go through trust.shipcheck
.record_ship. Nothing in-process can stop arbitrary same-user
code from calling the raw entry points anyway — so the suite
fails the build if non-allowlisted PRODUCTION code reaches for
them. This is enforcement by test, stated as such in
trust/README.md; it catches evolved/convenience code paths,
which is the threat model, not a determined same-user attacker.

The allowlist is COUNTED: each entry names the exact number of
call sites in that file, so a second call site added inside an
already-allowlisted file is a lint failure, not a free pass.
Watched: attribute calls to commit_write, _commit_gated (the
store's internal gated commit — commit_signed must be its only
outside caller), and run_one_cycle, plus GateDecision
constructions, including constructions through an import alias
(`from eval.gate import GateDecision as GD; GD(...)`).

Also watched (Trust Boundary v2 fix round, F1): calls to
run_reuse_measurement (bare-name or attribute) and to
migrate_security_mode (attribute). Both are legacy/audited paths
that must have ZERO production callers — a future production
caller passing legacy_test_mode=True to the quarantined reuse
harness, or flipping a store's security mode outside tests and
operator tooling, must fail this lint, not pass silently. They
are deliberately ABSENT from ALLOWLIST (whose entries all carry
positive counts); the zero-caller expectation is pinned by
test_legacy_paths_have_no_production_callers below.

Also watched (cycle 13, production signed-path wiring):
constructions of VerifierClient and MemoryStore in production
code, in the same forms as GateDecision constructions (bare
name, module attribute, and import alias). The sanctioned
production construction site is trust/wiring.py, with exactly
one construction of each; memory/reuse.py's two legacy
MemoryStore constructions are an explicit counted QUARANTINED
exception, in the design note's terms. Any other production
construction in the detected forms (bare / attribute /
import-alias constructions) — e.g. a convenience path building
its own client from an unvalidated env, or opening a plain
store where a signed_only one is required — fails this lint.

Known blind spots, pinned by tests below rather than hidden:
getattr-style indirection, bare method references
(`f = store.commit_write` without a call), functools.partial
wrapping, subclassing a watched class
(`class C(VerifierClient)`), and name-reassignment
(`VC2 = VerifierClient; VC2(...)`) are NOT detected. Runtime
trickery is out of scope for a static lint and the record
says so.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("core", "eval", "memory", "signing", "selfmod",
                    "oversight", "trust", "machine", "products",
                    "deploy")

# (repo-relative path, kind) -> (exact call-site count, why this
# call site is sanctioned). Every entry must correspond to real
# call sites (the stale-entry test enforces it), every real call
# site must appear here, and the counts must match exactly.
ALLOWLIST = {
    ("eval/gate.py", "gate_decision_ctor"): (
        1, "the gate itself constructs its decisions"),
    ("signing/gate_decision.py", "gate_decision_ctor"): (
        2, "envelope deserialisation and the self-test probe "
           "reconstruct decisions inside the signing package"),
    ("signing/gate_decision.py", "commit_gated"): (
        1, "commit_signed's delegation to the store's gated "
           "commit — the only sanctioned outside caller"),
    ("memory/store.py", "commit_gated"): (
        1, "the plain commit_write path's own internal delegation "
           "on non-strict stores"),
    ("selfmod/canary.py", "gate_decision_ctor"): (
        1, "the canary manager reconstructs a stored decision "
           "from its journal; it does not mint new ones"),
    ("memory/reuse.py", "commit_write"): (
        1, "LEGACY, QUARANTINED (Trust Boundary v2): the cycle-4 "
           "reuse harness commits in-process decisions on plain "
           "stores, but the path is quarantined behind "
           "run_reuse_measurement's test-only legacy_test_mode flag "
           "— the default call raises before any commit happens, "
           "and no production entrypoint calls it. Reachable only "
           "from tests that opt in explicitly. New code must use "
           "commit_signed"),
    ("trust/shipcheck.py", "run_one_cycle"): (
        1, "THE sanctioned ship path"),
    ("trust/pin_adoption.py", "run_one_cycle"): (
        1, "cycle 22: the pin adopter's loop driver "
           "(run_one_cycle_and_pin) runs one CoreLoop cycle and "
           "then pins the resulting snapshot through the "
           "production-wired adopter; it constructs no client or "
           "store itself — the client comes only from "
           "trust.wiring.production_client"),
    ("trust/runner.py", "run_one_cycle"): (
        1, "cycle 24: THE production entry point — its plan cycle "
           "steps run through the hooked CoreLoop it constructs "
           "(cycle_hook=pin_cycle_hook(adopter)); the hook, not "
           "this call, performs adoption. It constructs no client "
           "or store itself"),
    ("trust/wiring.py", "verifier_client_ctor"): (
        1, "THE sanctioned production construction site "
           "(production signed-path wiring): production_client "
           "validates a copy of the env against the wrapper "
           "allowlist, requires production mode and both "
           "anchors, and pins signer, key and deployment mode "
           "before this one construction"),
    ("trust/wiring.py", "memory_store_ctor"): (
        1, "THE sanctioned production construction site: "
           "open_production_store constructs the store only "
           "after a read-only parse shows the persisted mode "
           "is signed_only, and re-asserts the mode on the "
           "constructed instance"),
    ("memory/reuse.py", "memory_store_ctor"): (
        2, "LEGACY, QUARANTINED (production signed-path wiring "
           "design note): the cycle-4 reuse harness constructs "
           "plain stores in-process (its measurement store and "
           "an empty control store), but the path is "
           "quarantined behind run_reuse_measurement's "
           "test-only legacy_test_mode flag — the default call "
           "raises before any store is constructed, and no "
           "production entrypoint calls it (pinned by "
           "test_legacy_paths_have_no_production_callers). New "
           "code must use trust.wiring.open_production_store"),
}

_KIND_BY_ATTR = {"commit_write": "commit_write",
                 "run_one_cycle": "run_one_cycle",
                 "_commit_gated": "commit_gated",
                 "run_reuse_measurement": "run_reuse_measurement",
                 "migrate_security_mode": "migrate_security_mode"}

# Watched bare-name calls (imported functions invoked without a
# receiver). run_reuse_measurement is defined in memory/reuse.py
# and imported by name everywhere else, so attribute-only watching
# would miss its real call form. Definitions are not Call nodes,
# so the defining module does not trip this.
_KIND_BY_NAME = {"run_reuse_measurement": "run_reuse_measurement"}


# Watched constructions, by class name. Constructions are
# detected in bare form (ClassName(...)), attribute form
# (module.ClassName(...), which also covers module import
# aliases, whose receiver spelling the scanner does not need to
# resolve) and import-alias form (from x import ClassName as
# Alias; Alias(...)).
_CTOR_KIND_BY_CLASS = {"GateDecision": "gate_decision_ctor",
                       "VerifierClient": "verifier_client_ctor",
                       "MemoryStore": "memory_store_ctor"}


def scan_source(text: str) -> dict:
    """{kind: count} of watched calls in one source text."""
    tree = ast.parse(text)
    ctor_names = {name: kind for name, kind
                  in _CTOR_KIND_BY_CLASS.items()}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _CTOR_KIND_BY_CLASS:
                    ctor_names[alias.asname or alias.name] = \
                        _CTOR_KIND_BY_CLASS[alias.name]
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        kind = None
        if isinstance(func, ast.Attribute) \
                and func.attr in _KIND_BY_ATTR:
            kind = _KIND_BY_ATTR[func.attr]
        elif isinstance(func, ast.Name) and func.id in _KIND_BY_NAME:
            kind = _KIND_BY_NAME[func.id]
        elif isinstance(func, ast.Name) and func.id in ctor_names:
            kind = ctor_names[func.id]
        elif isinstance(func, ast.Attribute) \
                and func.attr in _CTOR_KIND_BY_CLASS:
            kind = _CTOR_KIND_BY_CLASS[func.attr]
        if kind:
            found[kind] = found.get(kind, 0) + 1
    return found


def scan_repo() -> dict:
    """{(relpath, kind): count} for every watched call in
    production code."""
    found = {}
    for root_name in PRODUCTION_ROOTS:
        root = REPO / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO).as_posix()
            for kind, count in scan_source(
                    path.read_text(encoding="utf-8")).items():
                found[(rel, kind)] = count
    return found


class LintTests(unittest.TestCase):
    def test_no_unlisted_or_extra_call_sites(self):
        found = scan_repo()
        expected = {key: count for key, (count, _why)
                    in ALLOWLIST.items()}
        self.assertEqual(
            found, expected,
            "production call sites at trust-boundary entry points "
            "differ from the counted allowlist; route new calls "
            "through the sanctioned path or record an explicit, "
            "counted exception in ALLOWLIST")

    def test_scanner_catches_planted_calls(self):
        self.assertEqual(
            scan_source("store.commit_write(f, d)\n"),
            {"commit_write": 1})
        self.assertEqual(
            scan_source("loop.run_one_cycle(a, b)\n"),
            {"run_one_cycle": 1})
        self.assertEqual(
            scan_source("d = GateDecision(accepted=True)\n"),
            {"gate_decision_ctor": 1})
        self.assertEqual(
            scan_source("store._commit_gated(f, d)\n"),
            {"commit_gated": 1})

    def test_scanner_catches_legacy_path_calls(self):
        # F1: the quarantined reuse harness, called by bare name
        # (its real import form) or through a module attribute.
        self.assertEqual(
            scan_source(
                "run_reuse_measurement(a, b, legacy_test_mode=True)\n"),
            {"run_reuse_measurement": 1})
        self.assertEqual(
            scan_source("reuse.run_reuse_measurement(a, b)\n"),
            {"run_reuse_measurement": 1})
        # F1: the audited security-mode migration, called on the
        # class (its real call form).
        self.assertEqual(
            scan_source(
                "MemoryStore.migrate_security_mode("
                "d, to_mode='unsigned', actor='op', reason='r')\n"),
            {"migrate_security_mode": 1})

    def test_legacy_paths_have_no_production_callers(self):
        # F1 pin: expected production-caller count for both legacy
        # paths is exactly 0. Any future production call site —
        # e.g. one passing legacy_test_mode=True — fails here even
        # though neither kind appears in ALLOWLIST.
        found = scan_repo()
        for kind in ("run_reuse_measurement", "migrate_security_mode"):
            offenders = {rel: count for (rel, k), count
                         in found.items() if k == kind}
            self.assertEqual(
                offenders, {},
                f"production callers of {kind} are forbidden "
                f"(expected 0); found: {offenders}")

    def test_scanner_catches_import_alias_construction(self):
        source = ("from eval.gate import GateDecision as GD\n"
                  "d = GD(accepted=True)\n")
        self.assertEqual(scan_source(source), {"gate_decision_ctor": 1})

    def test_scanner_catches_production_constructions(self):
        # Cycle 13: VerifierClient and MemoryStore constructions
        # are counted in bare and attribute forms.
        self.assertEqual(
            scan_source("c = VerifierClient(verifier_env={})\n"),
            {"verifier_client_ctor": 1})
        self.assertEqual(
            scan_source("c = client.VerifierClient(verifier_env={})\n"),
            {"verifier_client_ctor": 1})
        self.assertEqual(
            scan_source("s = MemoryStore(d, signed_only=True)\n"),
            {"memory_store_ctor": 1})
        self.assertEqual(
            scan_source("s = store.MemoryStore(d)\n"),
            {"memory_store_ctor": 1})
        # A method call ON the class is not a construction: the
        # audited migration keeps its own kind, not the ctor kind.
        self.assertEqual(
            scan_source(
                "MemoryStore.migrate_security_mode("
                "d, to_mode='unsigned', actor='op', reason='r')\n"),
            {"migrate_security_mode": 1})

    def test_scanner_catches_construction_import_aliases(self):
        source = ("from trust.client import VerifierClient as VC\n"
                  "from memory.store import MemoryStore as MS\n"
                  "c = VC(verifier_env={})\n"
                  "s = MS(d, signed_only=True)\n")
        self.assertEqual(
            scan_source(source),
            {"verifier_client_ctor": 1, "memory_store_ctor": 1})

    def test_production_constructions_confined_to_wiring(self):
        # Cycle 13 pin, stated positively: the ONLY production
        # VerifierClient construction is trust/wiring.py's one,
        # and production MemoryStore constructions are wiring's
        # one plus memory/reuse.py's two quarantined legacy ones.
        # (The exact-equality allowlist test above also enforces
        # this; this pin names the intent so a failure here reads
        # as a wiring violation, not a bookkeeping mismatch.)
        found = scan_repo()
        client_sites = {rel: count for (rel, k), count
                        in found.items()
                        if k == "verifier_client_ctor"}
        self.assertEqual(client_sites, {"trust/wiring.py": 1})
        store_sites = {rel: count for (rel, k), count
                       in found.items() if k == "memory_store_ctor"}
        self.assertEqual(
            store_sites,
            {"trust/wiring.py": 1, "memory/reuse.py": 2})

    def test_production_roots_cover_every_python_directory(self):
        # A new top-level package must not silently escape the
        # lint: any top-level directory containing Python files
        # (tests/ excluded — tests may call anything) must be a
        # production root.
        for child in sorted(REPO.iterdir()):
            if not child.is_dir() or child.name.startswith(".") \
                    or child.name == "tests":
                continue
            has_python = any(
                p.suffix == ".py" and "__pycache__" not in p.parts
                for p in child.rglob("*"))
            if has_python:
                self.assertIn(
                    child.name, PRODUCTION_ROOTS,
                    f"top-level package {child.name}/ contains "
                    "Python but is not linted")

    def test_getattr_indirection_is_a_known_blind_spot(self):
        # Documented limit, asserted so it is never silently
        # forgotten: dynamic dispatch defeats the static lint.
        sneaky = 'getattr(store, "commit_" + "write")(f, d)\n'
        self.assertEqual(scan_source(sneaky), {})

    def test_method_reference_is_a_known_blind_spot(self):
        # Assigning the bound method without calling it is not a
        # Call node; a later call through the alias is invisible.
        sneaky = "f = store.commit_write\nf(fields, decision)\n"
        self.assertEqual(scan_source(sneaky), {})

    def test_partial_wrapping_is_a_known_blind_spot(self):
        # functools.partial(store.commit_write, ...) is a Call to
        # partial, not to the watched attribute; the later call
        # through the partial is invisible to the scanner.
        sneaky = ("from functools import partial\n"
                  "f = partial(store.commit_write, fields)\n"
                  "f(decision)\n")
        self.assertEqual(scan_source(sneaky), {})

    def test_subclassing_is_a_known_blind_spot(self):
        # Subclassing a watched class is not a construction in
        # any detected form: the class definition names the
        # watched class as a base (not a Call), and calling the
        # subclass calls the subclass's own name, which the
        # scanner does not resolve to the watched class.
        sneaky = ("class C(VerifierClient):\n"
                  "    pass\n"
                  "c = C(verifier_env={})\n")
        self.assertEqual(scan_source(sneaky), {})

    def test_name_reassignment_is_a_known_blind_spot(self):
        # Reassigning a watched class to a new name (not an
        # import alias) is not detected: the assignment is not
        # an ImportFrom, so the scanner never learns the new
        # name, and calling it is invisible to the scanner.
        sneaky = ("VC2 = VerifierClient\n"
                  "c = VC2(verifier_env={})\n")
        self.assertEqual(scan_source(sneaky), {})


if __name__ == "__main__":
    unittest.main()
