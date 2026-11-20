# War-room review — cycle 9 (Trust Boundary v2, fix cycle)

Subject: `cycle-9-build` — evidence-derived attestation,
persistent `signed_only`, ship transaction machine, in-verifier
budgets, dual-ledger + budget anchoring, separate OS identity.
Backlog item: `signer-recompute-from-raw-inputs` (7.5).
Calibration log: `state/calibration` (subject `cycle-9-build`,
blind scores locked before discussion, outcome recorded at
close). External verdict: **PROVISIONAL** — this record is the
internal reconciliation only; ChatGPT and Gemini re-review from
`internal/CROSS-CHECK-BRIEF-CYCLE-V2.md`.

## Blind round (scores = probability the build is correct)

| Seat | Role | Score | Verdict |
|------|------|-------|---------|
| rev-r1 | evidence & attestation | 0.84 | SHIP |
| rev-r2 | assigned forced dissent | 0.12 | FIX |
| rev-r3 | ship tx & anchoring | 0.13 | FIX |
| rev-r4 | budgets & path policy | 0.20 | FIX |
| rev-r5 | memory mode & quarantine | 0.82 | SHIP |
| rev-r6 | OS identity & deployment | 0.15 | FIX |

Five FIX, one clear SHIP plus rev-r5's SHIP on its slice. The
FIX seats' findings were reproduced, not asserted:

- **rev-r2 (dissent, flagship):** every v2 guarantee held only
  on the sanctioned wrapper while primitives stayed callable —
  `_commit_gated` accepted a hand-built unsigned
  `GateDecision` on a signed store (Critical 1); ship recovery
  fabricated AUTHORISATION_VERIFIED / POST_RECORD_VERIFIED and
  finalised the deliberate drift case (Critical 2); budget
  scoping, legacy-digest downgrade channel, anchoring opt-in,
  stale README warning (Medium 10).
- **rev-r3:** recovery misattributed another ship's cycle (H1);
  poisoned-tx LedgerError loop (H2); recovery ignored loop
  evidence and anchor (H3); concurrent recovery corrupted the
  chain (M1); `initialise_anchor` blessed rolled-back journals
  (M4).
- **rev-r4:** all budget detection scoped per caller-chosen
  label (HIGH-1); sub-threshold probes invisible, small-set
  detector dead (HIGH-2); budgets.json rollback undetected
  (MEDIUM-1); garbage transcripts burned budget (MEDIUM-2);
  path-policy adoption docs stale (MEDIUM-3).
- **rev-r6:** budget env vars missing from the deployment
  wrapper allowlist (Finding 1); OS identity real but
  unprovisioned (documented ceremony, fail-closed).
- **rev-r5 vs rev-r2 conflict, reconciled explicitly:** both
  probed the same signed_only routes. rev-r5 judged them inside
  the documented threat model (SHIP); rev-r2 judged the
  mandate's wording ("non-downgradable") as stronger than the
  code (FIX). Both were right about different things: the fix
  round closed what code can close (permit handshake, journal
  verification on open) and the record + code docs now state
  the residual routes as accepted limits instead of claiming
  the stronger wording.
- **rev-r1's mediums** (public/capability maps caller-asserted;
  gap check's public side caller-asserted) were confirmed by
  rev-r2's probes and are carried as disclosed residuals, with
  docstring wording scoped to the sealed side.

## Fix rounds and verification

Three fix rounds, each verified by the finding seat re-running
its own probes (never by the fix author):

1. **Round 1** (permit handshake; ANOMALY terminal + recovery
   provenance rules + one-in-flight; identity-scoped budgets +
   absolute-difference probes + hash-chained budget store +
   two-phase wiring; distinct/ordered/scope-bound evidence;
   anchor ceremony guard + reanchor audit; deploy allowlist) —
   rev-r2 SHIP 0.86, rev-r6 SHIP 0.90; rev-r4 FIX (MEDIUM-1
   partial: combined store+anchor deletion, corrupt-store
   mislabelling, latch not materialised); rev-r3 FIX (new
   N1/N2/N3: cycle-claim uniqueness, finalised-exception scope,
   indiscriminate anchor parking; H1 journal porosity).
2. **Round 2** (budgets-anchor startup strictness + clean
   corrupt refusal + latch persistence, coordinator; ship
   N1/N2/N3 + gate hardening) — rev-r4 re-verified SHIP ~0.95;
   rev-r3 re-verified N1/N2/N3 FIXED but found the gate still
   evadable by first-binding at an earlier transition (S1/S1b)
   or never binding (S2).
3. **Round 3** (gate fires at first item binding on any
   transition; itemless CYCLE_RECORDED refused) — rev-r3 spot
   re-check SHIP ~0.95.

Coordinator fixes during the rounds: stale pre-v2 README
warning replaced; budgets two-phase + anchor wiring in the
verifier; gate evidence scope-root check (rev-r2 minor).

## Reconciled verdict

**SHIP (internal, unanimous after verification) — PROVISIONAL
pending external seats.** Full suite 602 → 820 tests, all
passing, including crash-at-every-transition ship tests,
adversarial attestation/budget/memory probes, and a real
separate-OS-user end-to-end run. Nothing ships on the split
blind round: the split was reconciled by fixes and re-probes,
not by vote. The residuals in `BUILD-CYCLE-9.md`'s honest-limits
register are carried openly into the external brief.
