"""Cycle 32 ship-path coverage guard (design 12.7, F4).

Statically scans every non-test .py file in the repository
for CALL sites of the three recording entry points and pins
the sanctioned sets exactly. Any new unsanctioned call site
-- or the disappearance of a sanctioned one -- fails this
suite until the pin is updated deliberately in a reviewed
change.

Call sites are counted from the AST (ast.Call nodes whose
func is an ast.Attribute with the watched attribute name, or
an ast.Name with the watched id), so matching is exact-name:
run_one_cycle_and_pin does NOT match run_one_cycle, and
record_ship_with_proof / anchored_record_ship calls are not
miscounted as record_ship calls. Definitions, docstrings and
string literals are not calls and are not counted (the
run_one_cycle definition in core/loop.py is asserted
separately, as a definition).

Sanctioned sets (design 12.7's enumeration of the recording
routes):

- run_one_cycle: trust/shipcheck.py (the signed ship route),
  trust/pin_adoption.py (the pin-adoption path's own signed
  discipline), trust/runner.py (the runner path) -- the two
  latter are pre-existing sanctioned NON-proof routes,
  recorded here so the enumeration is complete. The only
  proof-gated route is record_ship_with_proof's composition
  over record_ship.
- record_ship: trust/shipcheck.py (the call inside
  anchored_record_ship) and trust/proofcarry.py (the proof
  wrapper's delegation).
- anchored_record_ship: NO production caller. The empty pin
  is the point: the first production caller must arrive as a
  deliberate, reviewed pin update -- which is also the moment
  the deferred anchored proof composition (design 12.7) must
  be revisited.

Blind spots, inherited from the trust lint tradition and
stated plainly: getattr-style indirection, functools.partial
wrapping and name reassignment are not detected by a static
AST scan. This guard is enforcement by test against
evolved/convenience code paths, which is the threat model --
not a barrier against a determined same-user caller.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

WATCHED = ("run_one_cycle", "record_ship", "anchored_record_ship")

SANCTIONED_CALL_SITES = {
    "run_one_cycle": {
        "trust/shipcheck.py": 1,
        "trust/pin_adoption.py": 1,
        "trust/runner.py": 1,
    },
    "record_ship": {
        "trust/shipcheck.py": 1,
        "trust/proofcarry.py": 1,
    },
    "anchored_record_ship": {},
}


def _iter_scanned_files():
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if rel.parts[0] == "tests":
            continue
        if "__pycache__" in rel.parts:
            continue
        if path.resolve() == SELF:
            continue
        yield rel, path


def _call_sites():
    counts = {name: {} for name in WATCHED}
    for rel, path in _iter_scanned_files():
        tree = ast.parse(path.read_bytes(), filename=str(rel))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                called = func.attr
            elif isinstance(func, ast.Name):
                called = func.id
            else:
                continue
            if called in counts:
                key = rel.as_posix()
                counts[called][key] = counts[called].get(key, 0) + 1
    return counts


class TestCycle32ShipCoverage(unittest.TestCase):

    def test_call_sites_match_sanctioned_sets(self):
        counts = _call_sites()
        for name in WATCHED:
            with self.subTest(entry_point=name):
                self.assertEqual(
                    counts[name], SANCTIONED_CALL_SITES[name],
                    f"unsanctioned {name} call-site set: "
                    f"{counts[name]} != pinned "
                    f"{SANCTIONED_CALL_SITES[name]}")

    def test_run_one_cycle_definition_lives_in_core_loop(self):
        tree = ast.parse(
            (REPO / "core" / "loop.py").read_bytes(),
            filename="core/loop.py")
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef,
                                 ast.AsyncFunctionDef))}
        self.assertIn("run_one_cycle", defined)


if __name__ == "__main__":
    unittest.main()
