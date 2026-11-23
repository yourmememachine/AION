# REVIEW R2 — Cycle 21 (cryptography + workstream A)

Reviewer: rev-r2 (blind; did not build this cycle; no other
review-*.md read). Scope: CROSS-CHECK-14 item (1), DESIGN-FINAL
R8 + R9, critique-c §6, signing/ed25519.py (production verify),
tests/test_signing_ed25519_differential.py,
signing/ceremony_authorisation.py (load_ceremony_seed),
signing/gate_decision.py (shared perm helper + load_signing_key),
tests/test_signing_ceremony_seed_hygiene.py, and the R9 overlap
block in trust/verifier_main.py `_load_config`.

**Verdict: SHIP — score 0.93**

No BLOCKER, no HIGH, no MEDIUM findings. Four LOW findings, all
fail-closed or cosmetic; none blocks the cycle.

## Evidence gathered by this reviewer (independent probes)

- `git diff HEAD -- signing/ed25519.py` is EMPTY and the file is
  absent from `git status`: production verify is byte-unchanged
  this cycle, as required.
- Independent probe script (own openssl driver code, SPKI/PKCS#8
  prefixes re-typed, openssl 3.0.13 on this VM) re-ran the
  pinned adversarial rows extracted from the suite:
  - `identity A=I R=I S=0`: pinned (False, True), probed
    ours=False, openssl=True — MATCH.
  - `identity A=order2 R=I S=0`: pinned (False, True), probed
    ours=False, openssl=True — MATCH.
  - `noncanonical A y=1+q identity spelling`: pinned
    (False, True), probed ours=False, openssl=True — MATCH.
  - `S=S+L malleation`: pinned (False, False), probed
    ours=False, openssl=False — MATCH (agree-reject, exactly as
    critique-c §6.1 required; it is NOT in a divergence bucket).
  - Bonus calibration row, `noncanonical R y=1+q identity
    spelling`: pinned (False, False), probed (False, False) —
    the asymmetric A-side-only leniency is real and pinned.
  - FULL-table re-probe: all 51 rows, ours and openssl, zero
    mismatches against the pinned pairs.
- KAT TEST_1024 verified independently: message length 1023
  bytes; `public_key_from_seed(seed) == public` True; in-house
  sign byte-identical to the literal; in-house verify True;
  openssl sign byte-identical to the literal; openssl verify
  True. TEST_1/2/3 in-house sign/verify also re-checked True.
- Suites re-run by this reviewer: differential + hygiene =
  21 tests OK (skipped=2, the two root-vacuous uid tests —
  expected under this root harness) in 15.0 s.
- Skip probe: `env PATH=/nonexistent python3 -m unittest
  …OpensslDifferentialTests` → 5 tests, OK (skipped=5). The
  suite skips cleanly, does not fail, without openssl.
- Perm-predicate probe against `_check_owner_only_mode`:
  0400 ACCEPT, 0600 ACCEPT, 0500 refuse, 0700 refuse, 0200
  refuse, 0640 refuse, 0000 refuse — and (see LOW-1) 04600 and
  01600 ACCEPT.

## Scope questions, answered

(1) **Production verify exercised? YES.** The suite does
`from signing.ed25519 import public_key_from_seed, sign, verify`
and `from signing import ed25519`; every verify assertion calls
that imported production `verify`. There is no copy, re-implementation,
or affine oracle anywhere in the file. The module's private point
arithmetic (`_point_decode/_point_add/_scalarmult/_B`) is used
ONLY to construct mixed-torsion inputs; expectations are the
pinned literals/pairs, never derived from the code under test
(the cycle-20 F3 discipline). This is the correct shape.

(2) **Pinned pairs honest? YES** — see probe evidence above.
All three pinned (False, True) divergences reproduce, the S+L
malleation reproduces as (False, False), and the full 51-row
table re-probes with zero mismatches. No BLOCKER.

(3) **KAT literals? YES** — TEST_1024 seed/message/signature
verified against openssl independently (probe above). The
1023-vs-"1024" label discrepancy is pinned by
`test_long_message_vector_shape` and documented in the header.

(4) **Bit-flip sweep exhaustive? YES, with a noted thinness
(LOW-3).** Loops are unconditional: 64×8 = 512 signature flips
(TEST_1, empty message), 32×8 = 256 public-key flips, and every
bit of TEST_2's message — each iteration asserts False
individually, no sampling, no try/except swallow. Total 776
verifies; a 60 s ceiling assertion guards the fallback trigger.
Thinness: TEST_2's message is 1 byte, so the message dimension
is 8 flips. That is exhaustive over the chosen vector and
matches R8's wording, but a longer message vector would make
the message sweep less token.

(5) **Openssl skip discipline? YES** (probe above).
`OPENSSL = shutil.which("openssl")` at import, `skipUnless` on
the class, `setUpClass` version probe raising SkipTest on
execution failure. The ours-only tables (adversarial ours-half,
bit-flips, KAT) are outside the openssl class and still run.
Minor gap: LOW-4.

(6) **Seed-loader fd discipline? YES.** `load_ceremony_seed`
opens once with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`; S_ISREG,
mode, uid and size are all taken from `os.fstat(fd)` on the
opened fd; the read is bounded (`remaining = _MAX+1`, chunks
capped, post-read length re-checked), so a file that grows
after fstat still refuses. A FIFO opens under O_NONBLOCK and
is refused as non-regular instead of hanging (pinned by the
threaded hygiene test). There is no stat-then-read of file
properties left in this loader. (The pre-open `_check_key_path`
placement walk is still path-based — inherited, shared with
the gate loader, and about placement/symlinks, not content;
the final component is protected by O_NOFOLLOW. Not a new
gap.) **Uid check:** exactly R9 — `euid != 0` requires
`st_uid == euid`; euid 0 skips (vacuous). Seed loader only;
gate loader correctly has no uid check.

(7) **Perm predicate: shared, both loaders, and the exec
question.** One helper, `_check_owner_only_mode` in
gate_decision.py, imported by the seed loader and used by
`load_signing_key`; hygiene tests pin parity (0400/0600 accept;
0640/0644/0660/0200 refuse) on BOTH loaders. On owner-exec:
the helper adds `perm & 0o100` refusal beyond R9's literal iff
("no group/world bits AND owner-read set"), so 0500/0700
refuse. **Defensible, not a deviation that matters:** R9's own
operative sentence is "in practice {0400, 0600}", and the
shipped predicate accepts exactly that set (modulo LOW-1);
the extra condition only refuses MORE, in the fail-closed
direction, and it IS recorded — in the helper's docstring,
which states the exec-clear condition explicitly. An exec bit
on a key file has no legitimate deployment meaning. LOW-2
records the wording delta for the build record; no fix
required.

(8) **Derivation-overlap set in `_load_config`: COMPLETE and
sound.** All R9 relations present in the one place both
secrets exist: (1) seed == key (pre-existing byte-equality,
separate refusal); (2) seed == sha256(key); (3) key ==
sha256(seed); (4) key == ceremony public key; (5) seed ==
sha256(ceremony public key); (6) key == sha256(ceremony
public key); (7) seed == sha256(own public key) under BOTH
readings (see below); (8) key ∈ REFUSED_TEST_SEEDS. The dead
A-R4 relation is correctly absent. The refusal is a single
`verifier_misconfigured` with a value-free detail ("fail the
derivation-overlap check; provision them as independent
random draws") — no secret, hash, or relation identity leaks.
The mandatory residual wording ("catch accidents and known
derivations, not arbitrary KDF overlap…") is present in the
comment block. Startup tests in test_trust_ceremony_consume.py
pin relations (2), (3), (5), (6), (7-second-reading) and a
non-overlapping control.
  Relation (7)'s double reading — SOUND. The code checks
  seed == sha256(ceremony_public) (which is both R9-(5) and
  the first reading of (7), "the ceremony key's own public
  key", kept explicit in the comment) AND seed ==
  sha256(public_key_from_seed(key_bytes)) (the second
  reading: the public key derived by treating the HMAC key
  as an Ed25519 seed). The second reading only ADDS a refusal
  of a value derivable from the key; it cannot weaken any
  other check, and the length guard (`len(key_bytes) ==
  SEED_BYTES`) is belt-and-braces since the gate loader
  already enforces exactly 32 bytes. B's flagged ambiguity is
  resolved in the safe direction: both interpretations are
  enforced.

(9) **Do the hygiene changes weaken any existing refusal?
NO.** Diff-checked against HEAD: hex grammar unchanged
(strip → ASCII decode → `_HEX64_RE` fullmatch BEFORE
`bytes.fromhex`, then exact 32-byte length); size cap
unchanged at 1024 and now enforced twice (fstat + bounded
read); forbidden roots unchanged (`_check_key_path` still
runs first, repo root always forbidden); refused-seed/key
lists untouched, and `_load_config`'s independent refusals
(seed ∈ REFUSED_TEST_SEEDS, key ∈ _REFUSED_TEST_KEYS) stand
alongside the new overlap block. The ONLY widening anywhere
is 0400 acceptance, which is R9's explicit intent, plus the
exec-bit narrowing in the other direction. The gate loader's
fd gap remains open BY DESIGN (named follow-up
`signing-key-loader-fd-hardening` recorded in its docstring,
per R9's split ruling) — not a regression, its prior state.

## Findings

- **LOW-1 — Perm predicate ignores special bits.**
  `_check_owner_only_mode` tests `S_IMODE(mode)` only against
  0o077 / 0o400 / 0o100, so modes 04600 (setuid) and 01600
  (sticky) ACCEPT (probe above). "Exactly {0400, 0600}" is
  therefore overstated by the special bits. No practical
  weakening — setuid/sticky on a data file grant no read
  access and the file is never executed — but a one-line
  `perm & 0o7000` refusal would make the claim literal.
  Fix optional, next cycle.
- **LOW-2 — R9 wording delta on owner-exec, recorded in code
  but not in DESIGN-FINAL.** The helper refuses 0500/0700,
  which R9's literal iff would accept; R9's "in practice
  {0400, 0600}" sentence covers the outcome and the helper
  docstring records the condition. Fail-closed; noted so the
  build record does not claim the predicate is R9's iff
  verbatim.
- **LOW-3 — Message bit-flip dimension is 8 flips.** The
  message sweep runs over TEST_2's 1-byte message only.
  Exhaustive per R8 as written; a multi-byte message vector
  would strengthen it cheaply (the sweep has ~45 s of headroom
  under its own ceiling). Optional.
- **LOW-4 — Openssl capability probe is shallow.**
  `setUpClass` probes only `openssl version`; an openssl that
  runs but lacks Ed25519/pkeyutl support would fail tests
  rather than skip. Theoretical on the target platform
  (3.0.13 verified working end-to-end by this reviewer's
  probes); the repo's stated skip pattern is followed.

## Summary

Workstream A delivers what CROSS-CHECK-14 item (1) and R8
demanded: the production strict verifier is pinned against
RFC literals and an independent implementation with per-case
pinned (ours, openssl) pairs — independently re-probed here,
all 51 rows, zero mismatches — and the three genuine
divergences are openssl leniencies our profile correctly
refuses. R9 lands as specified: shared predicate on both
loaders, real fd discipline with the root carve-out uid check
on the seed loader, and the full 7-relation derivation-overlap
set (with relation (7) soundly double-read) behind a
value-free refusal. Nothing existing got weaker.

**Verdict: SHIP. Score: 0.93.**
