# Cycle 25 — Blind review, seat rev-r4 (DEPLOYMENT/ALLOWLIST + restoration evidence)

**Score: 0.82**
**Verdict: SHIP (blind, provisional)**

Justification: On a first pass over only the design contract
(`design-approval.md` §4.3), `internal/CROSS-CHECK-18.md` (seat-gpt's
five criteria), and the working-tree diff stat — before reading any
other seat's cycle-25 output (none was present in
`internal/cycle25-work/` at the time of writing) — the deployment
surface looks correctly and completely wired: `AION_SUPERSESSION_APPROVER_PUBLIC_KEY`
appears as the 20th allowlist entry in both
`deploy/verifier-identity/run-verifier.sh` and
`deploy/verifier-identity/health_check.py`, in `trust/wiring.py`'s
`ALLOWED_ENV_KEYS`, in `trust/verifier_main.py`'s `_load_config`, in
`deploy/verifier-identity/setup.sh`'s generated env template, and in
the deploy README, while `AION_SUPERSESSION_APPROVER_SEED_PATH`
appears in none of those verifier-side places (only in the approval
tool itself and in tests asserting its absence). The restoration and
supersede test files show large, deliberate growth consistent with
criteria (iv)/(v) rather than stubs. This blind SHIP is explicitly
conditional on the full review below confirming, by execution, that
(a) no §4.3 site was missed or left at 19, (b) the seed-path var is
refused as unknown by wiring and discarded by the wrapper, and
(c) restoration leg 4 / test_06 genuinely drives the independently
authorised route with no shortcut — any failure there flips this
seat to FIX.
