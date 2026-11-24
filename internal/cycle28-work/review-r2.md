# Review seat rev-r2 (adopter wiring) — cycle 28, blind

VERDICT: SHIP 0.85 (reported as "SHIP 8.5")

1. Step (3b) placement correct on every snapshot_and_adopt path; all
   outcomes pass through it; the supersede-resume path does not bypass
   it (call-graph verified: _resume_pending only from _reanchor,
   _reanchor only from post-(3b) sites).
2. Minor residual (non-blocking): adopt_returned persists without
   reconciliation. It adopts only a pair whose consumption committed in
   an originating snapshot_and_adopt attempt; a future cycle should
   reconcile there or document why the originating check suffices.
3. _known_unadopted_authorisation_ids / _genuine_burn_entries reuse is
   correct and cannot excuse an adopted ceremony (any adopted phase
   excludes it); the purely supersession-pending ceremony is correctly
   excluded; the underlying consumed burn is included.
4. Low/theoretical: head excuse in the pure function compares
   authorisation_id, not entry identity (hardening: compare seq).
5. Provider failure handling fails closed on every path checked;
   provider returning None or a generator raises via validation, no
   silent fall-back; non-callable refused at construction. Asymmetry:
   consumption provider without supersession provider loses decision
   excuses (fail-closed, acceptable; composition should supply both).
6. Ruling: build_pin_adopter must NOT auto-wire from AION_VERIFIER_HOME
   — agrees with the coordinator over seat B (cycle-25 separation;
   silent behaviour change; explicit pass-through is auditable). Honest
   cost: trust/runner.py currently passes no providers, so the shipped
   production path makes no history-completeness claim until a
   composition layer wires providers — a disclosed design residual.
7. No non-regression in existing constructions (all keyword-based;
   runner factory call unchanged and valid). Tests: cycle28 18 OK;
   test_trust_pin_adoption 9 OK.
