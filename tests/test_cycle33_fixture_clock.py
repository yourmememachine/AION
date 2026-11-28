"""Cycle 33 regression: ship fixtures must not be poisoned by a
stale import-time clock.

The ship suites used to stamp NOW / ATTESTED / SATT_AT once at
module import. Freshness checks run against the host wall clock,
so in a long full-suite run those stamps expired before the late
suites executed and produced spurious "expired /
attestation_expired" failures. The fix re-stamps the fixture
clock in setUp. This test ages the shipcheck module's globals far
into the past, builds the fixture, and asserts the stamps the
fixture actually used are fresh.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_trust_shipcheck as shipcheck


def _age_minutes(iso_ts):
    moment = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - moment).total_seconds() / 60.0


class FixtureClockTests(unittest.TestCase):
    def test_setup_restamps_a_stale_import_clock(self):
        # Simulate a long test run: the import-time stamps are
        # now two hours old, well past every freshness window.
        shipcheck.NOW = shipcheck._ts(-120)
        shipcheck.ATTESTED = shipcheck._ts(-130)
        shipcheck.SATT_AT = shipcheck._ts(-125)

        case = shipcheck.CheckShipTests("test_happy_path_is_clean")
        case.setUp()
        try:
            # The module clock itself was re-stamped ...
            self.assertLess(abs(_age_minutes(shipcheck.NOW)), 5)
            # ... and the fixture was built from the fresh stamps,
            # not the aged ones.
            self.assertLess(
                abs(_age_minutes(case.manifest.created_at)), 5)
            self.assertLess(
                abs(_age_minutes(case.att.attested_at) - 10), 5)
            # The fixture's own freshness check is clean: no
            # spurious expiry from the aged import-time clock.
            self.assertEqual(case.check(), ())
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
