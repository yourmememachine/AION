# RE-REVIEW R2 — Cycle 21 fix round (cryptography)

Reviewer: rev-r2, re-reviewing only my own original findings
(LOW-1 to LOW-4 in review-r2.md) plus the two spot-checks in
the re-review brief. No other review files re-read for this
delta; no files edited by this reviewer except this report
and the calibration entry.

**Verdict: SHIP — score 0.95**

All four LOWs are closed: LOW-1, LOW-3 and LOW-4 fixed and
independently verified below; LOW-2 accepted as recorded.
No regression found. signing/ed25519.py is byte-unchanged.

## LOW-1 — special bits (FIXED, independently probed)

- Code: `signing/gate_decision.py` `_check_owner_only_mode`
  now refuses `perm & 0o7000` (setuid/setgid/sticky) in
  addition to the group/world, owner-read and owner-exec
  conditions, and its docstring states the accepted set is
  "literally exactly {0400, 0600}" with the S_IMODE rationale.
- New tests: `test_special_bits_refused` in
  tests/test_signing_ceremony_seed_hygiene.py pins 04600,
  01600 and 02600 on the seed loader, and
  `GateLoaderPredicateParityTests` pins 04600/01600 on the
  gate loader too.
- My own probe (temp files outside the repo, both loaders):
  helper — 0400 ACCEPT, 0600 ACCEPT; 04600, 01600, 02600,
  07600, 0500, 0700 all REFUSE. Seed loader — 04600/01600/
  02600 REFUSED with the mode named in the error; 0400 and
  0600 LOADED with the correct seed bytes. Gate loader —
  same refusals for 04600/01600, same loads for 0400/0600.
  The accepted set is now literally {0400, 0600}.

## LOW-3 — message bit-flip dimension (FIXED, run)

- New `test_message_bit_flips_long_message`: 32-byte message
  (`bytes(range(32))`) under TEST_2's seed, unflipped
  signature asserted True first (sweep is not vacuous), then
  all 256 single-bit flips asserted False against the
  production `verify` imported from signing.ed25519.
- Ran it standalone: OK. My measured time was 11.0 s on this
  throttled shared-CPU VM versus the 3.5 s recorded in the
  test comment — a timing-comment variance, not a failure;
  the test's own 60 s ceiling assertion passes with wide
  margin either way.

## LOW-4 — openssl capability probe (FIXED, simulated)

- Code: `OpensslDifferentialTests.setUpClass` still probes
  `openssl version`, then performs a real round-trip —
  `_openssl_sign` on TEST_2's seed/message must return a
  signature byte-identical to TEST_2's pinned signature AND
  `_openssl_verify` must accept it — raising SkipTest (not a
  failure) on execution error, on a non-matching signature,
  or on a failed verify.
- Simulation: a fake `openssl` shim placed first on PATH
  that answers `version` successfully but exits 1 on every
  pkeyutl call made the whole class skip cleanly
  ("openssl Ed25519 round-trip cannot execute: openssl sign
  failed…", Ran 0 tests, OK skipped=1) instead of failing.
  Present-but-incapable now skips, exactly as required.

## LOW-2 — owner-exec refusal beyond R9's literal iff (ACCEPTED as recorded)

Behaviour unchanged in the fix round: the helper still
refuses `perm & 0o100` (0500/0700 refused in my probe
above), the condition is stated explicitly in the helper's
docstring, and the reconciliation addendum records the
fix-round scope. This remains a fail-closed narrowing with
no legitimate deployment meaning for an exec bit on a key
file. I accept it as recorded; no further action.

## Spot-checks

- **signing/ed25519.py byte-unchanged:** `git diff HEAD --
  signing/ed25519.py` is empty, the file is absent from
  `git status`, and its sha256
  (d1571ff8d70142708b667be88a6eadaccbf2b213e800480e838c6b
  68fc06f386) is identical to `git show HEAD:` of the same
  path.
- **Adversarial table:** re-ran the full differential file:
  10 tests OK in 50.6 s, including
  `test_ours_rejects_every_adversarial_row` (ours=False on
  every row) and `test_adversarial_pairs_are_pinned_exactly`
  (the pinned (ours, openssl) pairs, divergences included,
  still reproduce against the real openssl).
- **Hygiene suite:** 13 tests OK (skipped=2, the two
  root-vacuous uid tests — expected under this harness),
  including the new `test_special_bits_refused`.

## Summary

The fix round closed exactly what it claimed for my seat:
the permission predicate's accepted set is now literally
{0400, 0600} on both loaders, the message bit-flip sweep is
no longer token (256 flips over a 32-byte message), and the
openssl probe is a genuine Ed25519 sign/verify round-trip
pinned to TEST_2 that skips rather than fails when openssl
is incapable. LOW-2 stands as a documented, fail-closed
interpretation. Nothing in the production verifier changed.

**Verdict: SHIP. Score: 0.95.**
