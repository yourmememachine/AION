# CROSS-CHECK BRIEF — CYCLE 32-PROOF, BINDING ROUND (blind)

For the external seats. This brief states what was built,
the design decisions, and the test evidence. It contains no
internal verdicts or scores.

## Context
The check-carrying self-improvement prototype
(trust/proofcarry.py) gates a ship on a proof artefact. After
a successful ship it appends a binding record (cycle, item,
change, manifest hash, artefact hash, post-tree hash) to
proof-bindings.jsonl in the ship ledger's journal directory.
Prior rounds established two defects in that binding:
(1) the record was a plain JSON line — anyone able to write
the journal directory could edit a recorded binding
undetectably; (2) the append happened after the ship
committed, and its failure left a shipped, finalised cycle
with no binding (that behaviour was pinned by a test named
test_proof_binding_failure_ship_stands).

## What was built this round (trust/proofcarry.py only)
1. Hash-chained bindings. Each appended record now carries
   prev_binding_hash (the previous record's binding_hash;
   64 zeroes for the first) and binding_hash (sha256 of the
   canonical JSON of the record core). Appending re-reads
   and re-verifies the existing chain first and refuses to
   extend a broken one.
2. verify_proof_bindings(journal_dir) — a pure check
   returning () or a reason tuple: malformed JSON/shape is
   proof_binding_malformed; a prev-link or self-hash
   mismatch is proof_binding_chain_broken.
3. Fail-closed pre-burn gate. record_ship_with_proof, after
   live verification and before the snapshot/delegation
   (the burn happens inside the delegation), runs a
   side-effect-free preflight: the existing chain must
   verify, the bindings path must be a regular file when it
   exists, and the target must be writable. Failure raises
   ShipRefused before anything is spent.
4. The two existing tests that pinned the exact binding
   record key set were updated to the new 9-key set. The
   post-ship append-failure behaviour is unchanged (the
   ship stands, the failure is raised as an anomaly) — the
   preflight is what moved the predictable failures
   (corrupt chain, unwritable path) to before the burn.

## Stated limits (not claimed as solved)
- Tail truncation: deleting the last record(s) is
  indistinguishable from a shorter history to the chain
  check alone. A non-author anchor for the binding head
  remains an open follow-up.
- A writer who recomputes the whole chain after editing
  defeats the chain; the chain detects edits that do not
  recompute it. Same anchor follow-up.
- No locking: two concurrent shippers could both read the
  same tail and fork the chain (both records naming the
  same prev). Follow-up: flock the append.
- The preflight is a probe: a failure mode that appears
  between probe and append (disk fills mid-ship) still
  lands in the post-ship anomaly path. The writability
  probe uses os.access, which is weak for privileged
  processes.
- A torn final line (crash mid-append) makes the chain
  malformed and refuses later ships until repaired; no
  truncation-recovery tooling was built.

## Tests
- New: tests/test_cycle32_proof_binding.py — 6 tests
  (genesis chain + self-hash, second-record linkage,
  edited record detected, corrupt chain refuses before
  delegation, directory-in-place-of-file refuses before
  delegation, missing/empty file verifies). Before the
  fix: 3 failures + 2 errors of 6. After: 6 OK.
- Targeted suites after the fix: 128 tests OK
  (test_cycle32_proof_binding, test_trust_proofcarry,
  test_cycle32_proof_ship, test_cycle32_proof_fix2,
  test_cycle32_claim_pin).
- Full suite: 1,902 tests ran (1,896 prior + 6 new),
  28 skipped, with 7 failures + 14 errors — identical in
  two consecutive full runs, all in test_trust_shipcheck,
  test_trust_shiptx and test_trust_shiptx_recovery, every
  one an "expired / attestation_expired" refusal. Those
  fixtures stamp their timestamps at module import time
  and the freshness checks use the host clock; the full
  runs took ~24 minutes under heavy machine contention,
  so the import-time stamps expired before the
  late-alphabetical suites executed. The three suites
  pass standalone (86 tests OK) and combined with all
  cycle-32 suites (119 tests OK). Attributed: a
  pre-existing latent defect in those fixtures (stamp at
  setUp, not at import), NOT a regression of this change,
  whose diff touches only trust/proofcarry.py and the two
  binding key-set assertions. Recorded as a follow-up.

## Questions for the seats
1. Is the pre-burn preflight + hash chain an honest step
   toward "fail-closed binding", or does the unchanged
   post-ship anomaly path make the claim overstated?
2. Which of the stated limits blocks a prototype-scope
   ship, and which are acceptable disclosed follow-ups?
3. Score and verdict (SHIP / FIX) for this round at
   prototype scope.
