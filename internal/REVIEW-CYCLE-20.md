# REVIEW — Cycle 20: cycle-19 Parts B/C fix round

Six blind reviewers, none of whom built the cycle; scores
locked in state/calibration/calibration.json BEFORE
reconciliation (subject `cycle-20-fixround`; re-reviews under
`cycle-20-rereview`, spot re-check under `cycle-20-spotcheck`,
same reviewer ids). External seats (seat-gpt, seat-gemini)
review the brief (internal/CROSS-CHECK-BRIEF-CYCLE-20.md);
the verdict below is PROVISIONAL on that round. An external
approval never overrides an internal FIX.

Builders: 3 coder seats (A key boundary, B verifier
authority/evidence, C ceremony integration) — design and
cross-critique in internal/cycle20-work/, rulings in
DESIGN-FINAL.md. Seat B's build agent died mid-round on a
runtime error; a continuation seat audited and completed its
work. The original rev-r3 agent ended without delivering; a
replacement seat reviewed blind under the same id.

## Blind round

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 | scope fidelity vs CROSS-CHECK-13 + DESIGN-FINAL | 0.87 | FIX |
| rev-r2 | cryptography (Ed25519) | 0.97 | SHIP |
| rev-r3 | verifier mode + config | 0.58 | FIX |
| rev-r4 | ceremony integration | 0.92 | SHIP |
| rev-r5 | consistency + wording | 0.90 | FIX |
| rev-r6 | whole cycle (forced dissent) | 0.42 | FIX |

Principal verifications by the SHIP seats: the Ed25519
implementation is correct — RFC 8032 vectors, blocklist
verified computationally (exactly the 8 small-order
encodings, completeness proven two ways), verify() fuzzed
never-raising, and a signature cross-checked against OpenSSL
(r2); the consumption contract matches DESIGN-FINAL R6 point
for point, the None-check genuinely precedes envelope
verification in code, and T7/T8 pin the stale-history residual
executably, asserting the regressed pin value (r4).

## Findings and dispositions

- **rev-r1 HIGH + rev-r3 F1 BLOCKER (same defect, found
  independently) → CLOSED.** The anti-replay scan→append pair
  was not atomic: append_authorisation reloaded but never
  re-checked duplicates, so a concurrent commit between scan
  and append handed out two envelopes for one pair — and the
  cycle-19 race-honesty docstring claimed the contrary
  guarantee. Fix: post-reload duplicate re-check in
  append_authorisation composing with _save's under-flock
  freshness; regression test reproduces the interleave.
  Re-reviews: rev-r1 0.95 SHIP (both interleavings probed),
  rev-r3 0.94 SHIP (incl. its own two-process barrier probe:
  exactly one issuance).
- **rev-r3 F2 HIGH → CLOSED.** FIFO evidence leaf hung the
  verifier (leaf open lacked O_NONBLOCK; the S_ISREG check
  sat after the blocking open). O_NONBLOCK added; FIFO is in
  the identical-bytes sub-case test.
- **rev-r3 F3 MEDIUM + rev-r6 F2 → CLOSED.** The built order
  (sign → retention → scan) deviated from DESIGN-FINAL R5(a)
  and let refused replays grow the retained store. The scan
  now runs before signing and retention; a test pins retained
  count + journal length unchanged across both replay
  refusals. The retained-store policy is written (deploy
  README).
- **rev-r5 MEDIUM → CLOSED.** signing/__init__.py did not
  export the cycle-20 names. Full surface + ed25519 submodule
  exported; PackageExportTests pin it.
- **rev-r6 F5.1 → CLOSED.** REFUSED_TEST_SEEDS was a
  conditional import with a silent fallback. Single source in
  signing/ceremony_authorisation.py; unconditional import;
  exact-equality drift test.
- **rev-r6 F3 → CLOSED for this cycle.** The decode path had
  no adversarial differential vectors. 7 Wycheproof/C2SP-style
  vectors added (mixed-torsion R and A among them); each
  rejects for the stated strict-profile reason. (The deeper
  point — permanent in-house ECC ownership — is the owner's
  standing acceptance via route choice, restated in the
  brief.)
- **rev-r6 F5.2/F5.3 → CLOSED.** v1-refusal wording downgraded
  to the marker truth; seed-rotation procedure written;
  production_client pin: mandatory attempted, reverted on
  evidence (39 errors, all legitimate non-ceremony clients),
  README warning instead — accepted by rev-r6's re-review.
- **rev-r5 re-review F1 MEDIUM + F2 LOW → CLOSED.** The fix
  round's own README text introduced a false claim (identical
  evidence "re-retains under NEW ids" after rotation — the
  journal persists and refuses it) and two over-broad policy
  absolutes. Wording corrected; rev-r5 spot re-check 0.96
  SHIP.
- **Lows → CLOSED.** rev-r2 (odd-hex loader ValueError →
  SigningError), rev-r3 F4 (retention orphan unlink), rev-r3
  F5 (env-pop test), rev-r5 (workflow-attribution heading).
- **rev-r6 F1 + F4 → OPEN BY DESIGN, dissent preserved.**
  The stale-history leg of consumption replay is conceded in
  full (F1 narrowed, still open; GPT's 14–16 condition
  explicitly not met), and operator authentication is a
  narrowed claim, not a mechanism. rev-r6's re-review (0.80)
  states its FIX is a hold, not a code rejection: every code
  finding is closed, and its verdict flips to SHIP
  automatically on a reconciled external poll that accepts
  the two-of-three-legs basis — with cycles 14–16 held and no
  record describing Parts B/C as closed. The coordinator's
  R11 ruling (rooms review built code; no pre-build re-poll)
  stands as process, and the dissent against it is recorded
  here verbatim in substance: the seat holds that shipping on
  owner ratification without the seats' acceptance of their
  own FIX conditions repeats cycle 19's pattern. That
  question is now exactly what the external brief puts to
  seat-gpt and seat-gemini.

## Reconciled verdict

**SHIP — internal, after the fix round** (re-reviews:
rev-r1 0.95 SHIP, rev-r3 0.94 SHIP, rev-r5 0.96 SHIP on spot
re-check; rev-r2 0.97 and rev-r4 0.92 SHIP from the blind
round, their findings closed in the round; rev-r6 0.80 FIX
as a conditional hold whose flip condition is the external
poll itself). The verdict is **PROVISIONAL** on the external
seats. Parts B/C are NOT described as closed by this record:
two of the external seats' four conditions are met in full
(asymmetric minting boundary; verifier-side evidence
resolution), one is met on two of three legs (consumption:
omission + updated-history fail, stale-history conceded),
and one is discharged as an explicitly narrowed claim
(operator authentication). Cycles 14–16 remain HELD; their
re-review additionally requires the protected monotonic
consumption head.
