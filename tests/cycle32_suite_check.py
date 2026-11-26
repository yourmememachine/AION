"""Cycle-32 suite check: runs the cycle-32 unittest suites and
prints exactly CYCLE32_TESTS_PASS on success (stdout), nothing
to stdout on failure. Used as a proof-artefact invariant check
by tests/cycle32_real_change_demo.py.

Run: python3 tests/cycle32_suite_check.py
"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SUITES = (
    "tests.test_trust_proofcarry",
    "tests.test_cycle32_proof_ship",
    "tests.test_cycle32_claim_pin",
)


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in SUITES:
        suite.addTests(loader.loadTestsFromName(name))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if result.wasSuccessful():
        print("CYCLE32_TESTS_PASS")
        return 0
    sys.stderr.write(stream.getvalue())
    return 1


if __name__ == "__main__":
    sys.exit(main())
