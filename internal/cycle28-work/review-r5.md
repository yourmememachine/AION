# Review seat rev-r5 (scope & residuals) — cycle 28, blind

VERDICT: FIX 0.60 (reported as "FIX 6")

1. Scope confirmed clean (pass): only intended files; eval/ untouched;
   state/state.json sha256 86cb4de0...f1ec39 verified.
2. No ceremony/journal redesign (pass): ledger/verifier_main/protocol/
   wiring diffs empty; signing diffs are docstring sentences only.
3. Rejected verifier-mode alternative: rejection sound.
4. Rejected pin-store anchor: defensible but narrower than presented —
   an anchor detects shapes this check cannot (lost advance_pin
   movements). Keep it as a live named future follow-up.
5. RULING: NOT an acceptable end state for closing the follow-up. No
   production caller wires the providers at all: trust/runner.py calls
   build_pin_adopter with no providers; repo-wide grep finds no
   non-test caller passing consumption_entries_provider; test_17 pins
   the unwired silence. The cycle-21 precedent does not carry: there
   the scoped property existed in a wiring that actually supplied it.
6. The separation ruling does not justify 5: cycle-25 forbids the
   FACTORY deriving providers / the adopter reading the verifier home;
   it does not forbid the composition layer (trust/runner.py, which
   holds AION_VERIFIER_HOME) from explicitly passing the from-home
   helpers. Seat B's recommendation was overruled where wrong (factory)
   and not re-applied where right (runner).
7. Required fix: wire providers in trust/runner.py with a test, OR do
   not close the follow-up (record "mechanism landed, detection
   inactive in production", carry forward renamed).
8. New follow-up to name: pin-store-history-reconciliation-
   production-wiring. Keep open alongside: the external pin-store
   anchor; lost advance_pin undetectability. Note: provider entries
   are trusted as supplied (from-home helpers do not re-verify the
   cycles-22/27 anchors, which are checked at verifier startup).
9. The mechanism itself is genuinely good and should not be redone.
