# Cycle 21 re-review — rev-r3 (verifier side) after the fix round

Re-review of my own findings only (review-r3.md: FIX 0.78, the round's
only HIGH), against the reconciliation addendum in DESIGN-FINAL.md.
I read the fixed mode and ledger bodies, grepped the tree myself, and
re-ran tests/test_trust_ceremony_consume.py read-only: **full suite
32 tests OK** (was 26), with the K5 race test additionally run
standalone — three K5 passes in total across the runs below.

**Score: 0.92 — Verdict: SHIP**

---

## HIGH-1 (stderr oracle) — FIXED, verified

- The verify-reasons print is gone from `_mode_ceremony_consume`.
  Step (4) now carries only a comment explaining why no per-reason
  output may exist anywhere, and collapses reasons to the two R2
  codes (temporal set → `ceremony_authorisation_expired`, everything
  else → `ceremony_authorisation_invalid` with a fixed detail).
- Whole-mode audit for other case-distinguishing output: the mode
  contains no other `print`/stderr write. Its exception paths do not
  leak distinctions R2 forbids: envelope parse → `malformed_request`
  with the caller's own structural defect (as scored originally, not
  a leak); steps (5)/(6) ledger loads, the commit append, and the
  mirror append each catch broad `Exception` and surface ONE fixed
  `ledger_failed` detail — no exception text, no stderr. Seed/config
  failures happen in `_load_config`, before any envelope is examined,
  are identical for every mode, and cannot be driven per-envelope to
  probe signature-vs-binding — not an oracle for R2's guarantee.
- The one remaining stderr print in the file, inside
  `ceremony_authorise`'s evidence helper (~line 1880,
  `_evidence_unresolvable`), does **not** matter for my finding: it
  is reachable only from `_resolve_ceremony_evidence`, whose sole
  caller is the `ceremony_authorise` mode (line 2297). The consume
  mode never resolves evidence (an issuance fact, per R2), so no
  consume caller can reach it. It remains a cycle-20 issue in its
  own right, outside this finding's consume-specific scope.
- Residual note, not a blocker: `main()`'s unhandled-exception path
  prints a traceback to stderr. In the consume mode that path
  requires an internal bug — `verify_ceremony_authorisation`
  returns reason tuples for authentic-but-failing envelopes and its
  `SigningError` case is caught at step (3) — so it is not a
  forger-controlled discrimination channel in operation.
- Regression test `test_invalid_envelopes_indistinguishable_to_caller`:
  bad signature vs binding mismatch, same request id → byte-identical
  stdout error documents AND byte-identical stderr, plus
  `assertNotIn` for `signature_mismatch`, `payload_hash_mismatch`,
  `authorisation_id_mismatch`, `verify reasons`. **Ran it: ok.**

## MEDIUM-1 (head() override) — FIXED, verified

- `trust/ledger.py`: `CeremonyConsumptionLedger` no longer overrides
  `head()`. `head_target()` (lines 761+) reloads and returns
  `(new_cycle_seq, new_payload_hash)` or `None` when empty;
  `chain_head()` delegates explicitly to `HashChainJournal.head`;
  `_append` uses `chain_head()`. Class docstring states the contract.
- My own grep for `.head()` across the tree: every caller is on a
  `ShipLedger` / `SigningLedger` / ship-tx journal, or is the base
  class's own internal use. The only `.head()` calls on a
  consumption-ledger instance anywhere are in
  `test_head_contract_polymorphic`, asserting the restored base
  contract (`GENESIS_HASH` when empty, hex64 chain hash otherwise) —
  no caller anywhere expects a tuple from `.head()` on this class.
  All former tuple call sites now use `head_target()`
  (tests lines 287, 386, 469, 543).
- `test_head_contract_polymorphic` exercises the contract across
  `CeremonyConsumptionLedger` (empty and after a real consume),
  `ShipLedger`, `SigningLedger`, and `CeremonyAuthorisationLedger`.
  **Ran it: ok.**

## MEDIUM-2 (race test interleave) — FIXED, verified

- K5 rewritten: `APPEND_BARRIER_MODULE` rendezvous sits in
  `CeremonyConsumptionLedger._save` — i.e. after `append_consumption`'s
  reload and single-use/head re-checks, before the save lands. Both
  processes must print `APPEND_WINDOW_REACHED` (asserted for both),
  so both demonstrably passed the mode's snapshot pre-checks and
  entered the append window before either saved; the loser's save
  hits `_save`'s freshness check and it surfaces
  `ceremony_already_consumed` via the in-loop re-check — asserted as
  the loser's code, with exactly one consumption entry. The old
  start-line file barrier + wall-clock sleep design is gone.
- Determinism: **ran K5 three times** (targeted batch, standalone,
  full suite) — ok every time. The rendezvous is state-based (ready
  files counted, 30 s deadline), not timing-based.

## LOWs — disposition

- **LOW-1 (retry exhaustion → `ledger_failed`): CONFIRM the recorded
  acceptance** (addendum (b)). Eight contended attempts surfacing
  fail-closed `ledger_failed` matches the issuance bounded-retry
  precedent; the realistic concurrent loser is now proven by K5 to
  surface `ceremony_already_consumed`. Wording precision only, no
  dispute.
- **LOW-2 (crash coverage): addressed as far as the fix round
  promised.** Module comment now labels K1–K6 traceably, including
  K6b (post-mirror kill: consumed AND mirrored, retry refuses,
  both journals unchanged — ran ok), K3 (response-lost retry —
  ran ok), and K4's mirror half (deleted consumption journal, mirror
  cross-check still refuses replay — ran ok). The one sub-case still
  not simulated is a torn write mid-`_save`; as noted originally,
  tmp+replace+fsync makes a torn main file structurally unlikely and
  the corrupt-journal test pins fail-closed load. Accepted residual.
- **LOW-3 (journal-only duplicate check): fixed in wording.**
  `append_consumption`'s docstring now carries the scope note: the
  check here is consumption-journal-only by design, and the
  signing-ledger mirror cross-check is a mode-level responsibility
  that direct callers do not get.
- **LOW-4 (old_pin == head mode test): fixed.**
  `test_old_pin_equal_head_equal_hash_admitted` — second ceremony
  whose old pin is exactly the head (seq + hash) with candidate
  ahead is admitted. **Ran it: ok.**

---

## Verdict

**SHIP (0.92).** Every finding I raised is fixed in code or test and
independently re-verified: the stderr oracle is closed with a
byte-identity regression test, the `head()` contract is restored
polymorphically with `head_target()` as the separate accessor, and
the race test now forces the exact interleave it claims to prove,
deterministically. The recorded retry-exhaustion interpretation is
confirmed, not disputed. The 0.08 reserve is for the two named
residuals (unhandled-traceback path in `main()`, torn-write
simulation) — neither is reachable as a caller oracle and neither
blocks this cycle.
