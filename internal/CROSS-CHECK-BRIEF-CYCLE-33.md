# CROSS-CHECK BRIEF — CYCLE 33 (blind, for external seats)

What was built: a fix to the test harness only. Several
ship-transaction test modules computed their timestamps
(NOW, ATTESTED, SATT_AT) once at module import. Production
freshness checks read the host wall clock, so when the full
test suite ran long, fixtures created at import were judged
expired by the time their tests executed, producing failures
unrelated to the code under test.

Design decisions:
- Each affected module gained a _refresh_clock() helper that
  rebinds its module-level timestamp globals to fresh values;
  every fixture setUp that uses those stamps calls it first.
- Two modules that imported a copied NOW from a sibling test
  module now refresh the source module at setUp and rebind
  their own global; one fixture class that had no setUp
  gained one.
- No production code changed. No test assertion changed.
  Tests that deliberately assert expiry still do so relative
  to the fresh stamps.
- One new regression test ages the canonical module's
  globals by ~2 hours, builds the fixture, and asserts the
  resulting manifest/attestation are fresh and pass the
  ship check.

Evidence supplied: diff summary (+77 lines, tests only),
failing-first result for the new regression test, targeted
run of 172 tests across the seven affected modules, all
passing. The full suite (~1,903 tests) was not re-run in
this cycle.

Questions for reviewers: (1) Is setUp-time re-stamping the
right layer, or should the timestamps stop being module
globals altogether? (2) Does rebinding globals risk
cross-test contamination in any runner that interleaves
tests from these modules? (3) Is one aged-clock regression
test on the canonical module sufficient evidence for the
other five modules using the identical pattern?
