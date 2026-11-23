# Cycle 21 — War-room RE-REVIEW rev-r1 (scope fidelity)

Reviewer: rev-r1, re-reviewing only my own first-review findings
(review-r1.md, FIX 0.87) against the fix-round tree, plus anything
new the fix round introduced in that scope. No code or tests edited.

Score: 0.94 — Verdict: SHIP

Calibration: blind entry `cycle-21-rereview-rev-r1` recorded
(subject `cycle-21-rereview`, rev-r1, 0.94) under the flock guard on
state/calibration/.record.lock.

Tests run by this seat: `tests/test_trust_ceremony_consume.py` +
`tests/test_signing_ceremony_seed_hygiene.py` via unittest —
45 tests, OK (skipped=2, both root-vacuity skips by design),
82.8 s. K1–K6/K6b all pass, including K5 with its in-test
APPEND_WINDOW_REACHED assertions.

## Per-finding dispositions

### MEDIUM-1 (deploy README) — VERIFIED FIXED
deploy/verifier-identity/README.md:
- (a) The gate.key row no longer says "exactly 0600". It now reads
  "itself owner-only — `load_signing_key` accepts exactly modes
  {0400, 0600} under the shared owner-only predicate: no
  group/world bits, no setuid/setgid/sticky bits, owner-read
  required; it refuses any other mode". Checked against the code
  predicate `_check_owner_only_mode` (signing/gate_decision.py:230):
  refuse iff `perm & 0o7000 or perm & 0o077 or not perm & 0o400 or
  perm & 0o100` — i.e. the accepted set is literally {0400, 0600},
  and the README's enumeration matches it (the owner-execute-clear
  condition is subsumed by "accepts exactly modes {0400, 0600}").
  A tree-wide grep finds no remaining stale "exactly 0600" loader
  claim outside retired-rule context.
- (b) A "**Ceremony consumption (cycle 21)**" paragraph now exists:
  it names the `ceremony_consume` mode, the consumption journal
  (`home/ceremony-consumptions.json`), the signing-ledger mirror and
  the monotonic head, and carries a "**Burned-but-unmoved
  recovery:**" note matching R3/R7 — consumed target permanently
  spent, never re-anchorable, recovery is a NEW ceremony (new
  ceremony_id, new evidence) ahead of the head, no un-consume,
  client never retries automatically. Both halves of the seat-B
  report are accurate.

### MEDIUM-2 (crash coverage traceability) — VERIFIED FIXED
tests/test_trust_ceremony_consume.py now opens with a K1–K6 mapping
comment (lines 24–56) tying every kill point to a named test, and
the tests are K-labelled: test_k1_kill_before_append_burns_nothing,
test_k2_kill_after_append_before_response_burns,
test_k3_response_lost_retry_refused,
test_k4_corrupt_consumption_journal_ledger_failed (first half),
test_k4_deleted_journal_mirror_still_refuses_replay,
test_k5_concurrent_double_consume_one_winner,
test_k6_mirror_failure_after_commit_burns,
test_k6b_kill_after_mirror_before_anchor.
- K5 interleave is genuinely FORCED, verified by reading both the
  wrapper and the ledger: APPEND_BARRIER_MODULE patches
  `CeremonyConsumptionLedger._save` with a rendezvous that, on the
  first save, writes a per-pid `.ready` file and waits until both
  processes have arrived before calling the original `_save`.
  In `append_consumption` (trust/ledger.py:842) `_save` is reached
  only via `_append`, after `_reload()` and the single-use/head
  re-checks — so both processes demonstrably pass the re-checks on
  the still-empty journal and park inside the reload→save window;
  neither has saved. On release, the loser's `_save` freshness
  check (under the directory flock) raises CorruptLedgerError and
  the bounded retry re-check surfaces `ceremony_already_consumed`,
  exactly as asserted. The test asserts BOTH stderr streams contain
  APPEND_WINDOW_REACHED, plus codes [0, 3] and exactly one entry.
  It passed in my run. This is a true in-window synchronisation,
  not a start-line barrier.
- K6b is new and real: KILL_AFTER_MIRROR_MODULE wraps
  `SigningLedger.append_ceremony_consumption`, runs the original,
  then os._exit(70) — the process dies after the mirror append and
  before `_update_anchor` is reached; the test pins one consumption
  entry + one kind="consume" mirror entry, retry refused
  already-consumed, neither journal grows. (Disclosed in the test
  comment: no anchor is configured in this fixture, so
  `_update_anchor` is a no-op there — the boundary exercised is
  structurally post-mirror/pre-anchor, and the comment says so
  honestly. Accepted.)
- K3 (response-lost) and K4's second half (deleted journal, mirror
  cross-check still refuses replay, scoped kind="consume" +
  format="ceremony-consumption") are present and pass, as reported.

### LOW-1 (extra overlap relation (7), second reading) — RATIFIED, CONFIRMED, NO DISPUTE
The DESIGN-FINAL addendum records the ratification verbatim
("The R9 closed set is now (1)–(7) with (7) read both ways").
The code matches: trust/verifier_main.py:583–590 comment reads
(7) "both ways the designs used it", including the public key
derived by treating the HMAC key bytes as an Ed25519 seed, and
test_seed_is_sha256_of_signing_keys_public_key_refused pins the
refusal (passed in my run). I do not dispute the ratification —
it refuses more, in an owned file, disclosed and tested, exactly
the conservative deviation my original finding allowed for.

### LOW-2 (predicate formula stricter than ruled) — VERIFIED, NOW LITERAL
`_check_owner_only_mode` now also refuses `perm & 0o7000`
(setuid/setgid/sticky), on top of no group/world bits, owner-read
set, owner-execute clear — the accepted set is literally exactly
{0400, 0600}, as the helper's docstring states. Pinned on BOTH
loaders in tests/test_signing_ceremony_seed_hygiene.py:
test_special_bits_refused (04600/01600/02600 on the seed loader)
and GateLoaderPredicateParityTests (04600/01600 among the gate
loader refusals, 0400 loads). All passed in my run. The shared
helper is used by both loaders (gate_decision.py:337,
ceremony_authorisation.py:312). Closed.

### LOW-3 (RFC "TEST 1024" is 1023 bytes) — NO ACTION WAS REQUIRED
Evidence-backed correction recorded in my first review; nothing
in the fix round changes it and nothing further is owed.

### LOW-4 (signed_in_future → expired) — CONFIRMED AS RECORDED
The addendum records interpretation (a): temporal verify reasons
(expired / signed_in_future) map to
ceremony_authorisation_expired, all other verify failures to
ceremony_authorisation_invalid. The code matches exactly:
trust/verifier_main.py:2492, `if set(reasons) <= {"expired",
"signed_in_future"}` → expired code, else invalid. Closed.

## Anything NEW introduced by the fix round (in my scope)

- Nothing that reopens a finding. One cosmetic nit, non-blocking:
  the K5 test leaves its Popen stdout/stderr pipes unclosed,
  emitting ResourceWarnings under unittest (observed in my run).
  Test-hygiene only; no behavioural consequence.
- The fix round's stderr-oracle change (my scope check only) did
  not disturb the R2 single-code surface my findings depend on:
  the consume mode still maps verification failures to exactly
  the two ruled codes with no per-reason output.

## Verdict

SHIP (score 0.94). Both MEDIUMs are fixed and verified against
code and by running the suites; LOW-1 is ratified and matches
code+test, LOW-2's predicate is now literally {0400, 0600} with
the 0o7000 refusal pinned on both loaders, and LOW-4 is recorded
and matches the code. No new scope-fidelity defect found.
