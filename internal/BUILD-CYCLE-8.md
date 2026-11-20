# Build cycle 8 — trust boundary, completion

Item: `store-enforced-signed-commits` (leverage 8.0), scanned by
cycle 7 from its external review. Recorded as loop cycle 8 via
the sanctioned ship path (`trust.shipcheck.record_ship`) — the
first production traversal of that path. Coders: 15 (5 pods of
3: signing/key custody, manifest, out-of-process verifier,
integration, adversarial tests). War room: 6 internal seats +
2 external seats pending (see the review record). Full suite:
**466 → 602 tests, all passing.**

## Numbering note

This is state cycle 8. The commissioning brief for this work
assumed "cycle 5 / 270 tests" from an older snapshot; the repo
had already advanced through cycles 5–7 (selfmod canary,
protected-gate enforcement, signed gate decisions — the last
recorded by the hourly build cron while this cycle was in
flight). Records therefore live at `BUILD-CYCLE-8.md` /
`REVIEW-CYCLE-8.md`; the external brief keeps the
parent-specified filename `CROSS-CHECK-BRIEF-CYCLE-5.md`, and
the external reconciliation will be `CROSS-CHECK-3.md`.

## What was built

- **Signed verifier attestations** (`signing/attestation.py`):
  HMAC envelope over the gate's `VerifierAttestation`, binding
  proposal id and optionally a manifest hash; strict validated
  parsing; nested-expiry discipline enforced at sign and at
  consume; manifest-bound attestations refused on the memory
  path.
- **Store-enforced signed commits** (`memory/store.py`,
  `signing/gate_decision.py`): `signed_only=True` stores refuse
  plain commits; `commit_signed` verifies the envelope and
  delegates to the store's `_commit_gated` (no plain-path
  fallback); optional store-state epoch binding checked inside
  the store's lock.
- **Artifact-bound authorisation** (`trust/manifest.py`,
  `trust/release.py`): canonical build manifest over the
  source/test/evaluator trees + the bound review record;
  `__pycache__` bytecode shadows (including symlinked ones)
  refuse builds and invalidate verification; release records
  tie manifest + decision + expected cycle + pre-ship state.
- **Out-of-process verifier** (`trust/verifier_main.py`,
  `trust/client.py`, `trust/protocol.py`): subprocess service,
  env-only config, four modes (`gate`, `sealed_eval`, `attest`,
  `verify_envelope`); accepts require a presented signed
  attestation; signer may not be builder/reviewer/attester;
  empty sealed set refuses; every signature ledgered before
  return; ledger home required; strict exit-code contract.
- **Signed ship path** (`trust/shipcheck.py`,
  `trust/ledger.py`): pure `check_ship` re-deriving everything
  from primary artefacts; `record_ship` requires a release
  record and an externally pinned ledger head, verifies the
  loop before burning, re-verifies the tree after recording.
- **Counted call-graph lint** (`tests/test_trust_lint.py`)
  covering `commit_write`, `_commit_gated`, `run_one_cycle`,
  and `GateDecision` constructions (incl. import aliases), with
  pinned blind spots (`getattr`, method references,
  `functools.partial`).

## Anchors (out-of-band record)

- Build manifest hash:
  `f630740d4e0071e98641ade870dde022d81abb462364a36ff2e4b1628c118e8e`
  (58 files; stage final; proposal `cycle-8-ship`)
- Bound review record (`internal/REVIEW-CYCLE-8.md`) hash:
  `25c711ce4d4d12d2320f8ac3c2364b7f5e614085b856952597e383265f517969`
- Ship decision id:
  `ef8d39d00a63823b80415c202f1f16b07c907258a5793d2cfff24acf36e7586f`
- Ship payload hash:
  `16ec248dc8ce1cb68c1d0eb7f5ed123c784644557ba5294a4dee7effd035a124`
- Ship ledger (`state/ship-ledger/ship-ledger.json`): pinned
  head before recording was the genesis head; head after
  finalise:
  `f7d9cb23c94d197b5c96f2847fa3bd98ce6c9c56676fc15c44dcae6e0562e7d9`
- Recording key: a throwaway ceremony key generated under
  `/tmp/ceremony8/` (not a production key; the recording
  demonstrates the path, it does not establish a production
  signer).

## Compliance

No protected file was touched: `eval.gate.check_protected_paths`
over all changed/new paths returned `()` and the oversight
canonicalised check returned `[]`. Changed/new: `signing/`
(attestation module, gate-decision and export updates),
`memory/store.py`, the new `trust/` package (10 modules +
README), and 9 test files/fixtures under `tests/`.

## State repair disclosure

The loop's state file, as written by the hourly cron's cycle-7
run, failed the loop's own validation: two backlog items it had
scanned (`store-enforced-signed-commits`,
`signing-key-rotation`) carried `title_hash` values that do not
recompute from their stored titles, bricking `CoreLoop` loads.
Before recording, the two hashes were recomputed from the
stored titles and repaired in place (titles unchanged; backup
of the pre-repair file kept with the cycle's working papers).
The cron's scan path should be audited — it persisted a state
its own loader rejects. This is flagged for the parent.

## War room (summary; full record in REVIEW-CYCLE-8.md)

Blind round unanimous FIX (0.32–0.74, dissent lowest). Three
fix rounds (571 → 602 tests). Verification round: rev-r1 0.95
SHIP, rev-r3 0.90 SHIP, rev-r5 0.87 SHIP, rev-r4 0.78 FIX →
confirmation probe closed all items, rev-r6 0.88 FIX →
confirmation probe verified all corrections, rev-r2 (dissent)
0.40 FIX with the dissent preserved in the review record.
Internal verdict: reconciled SHIP. **Overall verdict:
PROVISIONAL — war-room passed, awaiting external cross-check**
(seat-gpt, seat-gemini; brief at
`internal/CROSS-CHECK-BRIEF-CYCLE-5.md`; reconciliation lands
in `internal/CROSS-CHECK-3.md`).

## Residual-risk register

- R1 Same-user HMAC boundary: process isolation only; a
  separate OS user (or asymmetric signatures) is required for
  a real domain. Backlog: `separate-os-user-verifier` (6.5).
- R2 Gate evidence is caller-asserted; the signer does not
  recompute from raw inputs, and `attest` signs a seat's
  assertions. The dissent seat's flagship objection; design
  change backlogged as `signer-recompute-from-raw-inputs`
  (7.5) — the top pending item.
- R3 Production wiring: beyond this recording, no production
  flow traverses the signed paths; `memory/reuse.py` remains a
  counted legacy exception. Backlog:
  `production-signed-path-wiring` (7.0).
- R4 Ledger rollback/deletion is detectable only against an
  externally pinned head; `record_ship` now requires the pin,
  external anchoring is backlogged (`ledger-head-anchoring`,
  6.5).
- R5 `signed_only` is construction-time and unpersisted; a
  plain store over the same directory re-enables unsigned
  commits (operator warnings in code and README).
- R6 The gate's protected-path list and the oversight list
  disagree (canonical `oversight/` paths earn gate accepts);
  the gate list lives in a protected module. Backlog:
  `protected-list-reconciliation` (6.0).
- R7 `sealed_eval` is a per-position score oracle and burns
  registry access-log entries (~5,000 evals exhaust the cap);
  the verifier has no internal timeout. Client capture is
  memory-buffered (cap bounds acceptance, not capture).
  Backlog: `client-streaming-capture` (4.0),
  `attestation-freshness-window` (4.5).
- R8 Reviewer independence is asserted by roster construction,
  not measured. Backlog: `reviewer-independence-measurement`
  (5.0).
- R9 Suite runtime grew across cycles 7–8 (~60–140s depending
  on host throttling). Backlog: `suite-speed-budget` (3.5).

## Next

Top pending backlog item: `signer-recompute-from-raw-inputs`
(7.5). External seats' reviews are the immediate gate on this
cycle's final status.
