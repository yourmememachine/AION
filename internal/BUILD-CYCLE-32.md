# BUILD CYCLE 32 — post-settlement returned-failure surface

**Summary:** The Cycle 31 open item "post-settlement
re-verification discards returned malformed/missing anchor
failures" is closed in code. `ShipTxJournal.recover()`
(`trust/shiptx.py`) post-settlement re-verification now collects
RETURNED non-park anchor reasons as well as park reasons and
exception-path failures: a returned reason that is new for that
anchor (per-anchor dedup against its initial verdict) surfaces
on the same terms as a new exception-path failure — plain
`AnchorError` carrying `.outcomes` when error-only, or in
`JournalIntegrityError.anchor_errors` (labelled
`"<source>: <bare reason>"`, never `.reasons`) when a new park
reason accompanies it. Any non-park returned string counts,
matching the pre-settlement classifier. Within-run labels are
deduped. Docs updated: `recover()` docstring and
`docs/RECOVERY-CONTRACT.md` (gap paragraph replaced with
"Closed (cycle 32)", item-2 lead harmonised, pin count 68,
open item removed).

**Failing-first:** 10 new tests in
`tests/test_trust_shiptx_anchoring.py`; 9 red / 1 green (the
dedup guard) on the old code, independently re-verified by R5
in a scratch copy. Pin file: **68 tests OK**. Full suite on the
modified tree (unittest discovery): **1848 tests OK
(skipped=28)** on two confirming runs; one earlier run showed a
single unidentified failure that did not recur — recorded as
flaky, outside the pin file. NOTE: the 1848 total includes
tests from a concurrent session's in-progress work in the same
repo (see Blocker); the pre-concurrency baseline was 1814 + 10
new = 1824 expected for this cycle's tree alone.
Real `state/state.json` untouched (sha256
86cb4de0f9d0d01871b7d654c395cfe101e63de7545aa501c42b01a750f1ec39
identical before/after).

## Staffing
15 coders, 5 pods of 3: Pod A (1,5,8) correctness design;
Pod B (2,6,7) adversarial/limits design; Pod C (9,10,11) test
design; Pod D (3,4,15) implementation/records; Pod E (12,13,14)
brief/update. Three coder seats ran as delegated blind agents
(internal/cycle32-work/design-a/b/c). War room: 6 internal
seats + 2 external seats (2 rounds, per the 2026-11-26 rule) +
coordinator reconciliation. Records:
internal/REVIEW-CYCLE-32-SHIPTX.md,
internal/CROSS-CHECK-32-SHIPTX.md. (The -SHIPTX suffix keeps
this cycle's records disjoint from a concurrent session's
cycle 32; see Blocker.)

## Self-improvement delta
The discarded channel was the PRIMARY one: `verify_anchor`
returns the three operator reasons as values and raises only
out-of-contract — the exception channel the old code handled is
nearly unreachable for them. Lesson recorded: when a callee has
two failure channels, audit both; a test whose fake raises a
shape the real function never produces (the old mixed test)
pins nothing. Scorecard: Action+Guardrails evidence
strengthened (recovery now reports mid-run anchor corruption);
no capability % change claimed.

## Open follow-ups (carried)
- Production recovery caller passing tx_anchor_path.
- Non-[] surface for carrier-less evidence (design decision).
- Same-file re-check at post-settlement re-verification (new,
  from R3 dissent).
- Pin-store head anchoring; pin-directory-loss reconciliation;
  operator-authentication-channel; concurrent-actor interleaving.

## Concurrency note
A concurrent session built a different "cycle 32"
(proof-carrying change artefacts, trust/proofcarry.py + tests)
in the same repo during this run. This cycle's commit was held
until that session's commit landed (a7e522b) and disjointness
was verified (no shared files); then this cycle's files were
committed locally only, bare message, no push. Renumbering one
of the two cycle-32s is a coordinator follow-up.
