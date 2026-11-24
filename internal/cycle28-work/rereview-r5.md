# Re-review seat rr-r5 — cycle 28 fix round

Evidence: runner.py wiring verified in main() (providers built via
_history_providers(verifier_env) from AION_VERIFIER_HOME, passed to
build_pin_adopter; factory still never derives them — cycle-25
separation respected). Providers lazy, fresh per call. Cycle28 suite
23 OK incl. integration test_20; runner suite 13 OK with
reconciliation active end-to-end (genesis, chain_gap_recovery,
genuine burn exit 4, cycle-hook burn exit 5, supersession-pending
exit 7 all keep pre-cycle-28 outcomes).

New minor defect found: _history_providers called before
build_pin_adopter with no upstream validation — a missing
AION_VERIFIER_HOME would raise KeyError escaping main()'s
_ConfigRefusal handler (exit-1 traceback instead of structured
exit-2). Fails closed; named as a small follow-up.
[Coordinator note: fixed in the same fix round after this report —
_history_providers now refuses via _refuse/_ConfigRefusal, pinned by
an assertion in integration test_20.]

Finding-by-finding: 1 CLOSED; 2 CLOSED; 3 CLOSED; 4 OPEN (pin-store
anchor remains a live named follow-up, not a closure blocker);
5 CLOSED (runner wires both providers); 6 CLOSED; 7 CLOSED (first
branch: wired + tested); 8 production-wiring follow-up CLOSED by
the fix; anchor / lost-advance / provider-trust remain OPEN as
named follow-ups; 9 CLOSED.

"The follow-up pin-store-history-reconciliation can now honestly
close."

VERDICT: SHIP 0.86
