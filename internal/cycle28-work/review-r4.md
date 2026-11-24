# Review seat rev-r4 (claims & docs) — cycle 28, blind

VERDICT: SHIP 0.87 (reported as "SHIP 8.7")

1. signing/pin_store.py — PASS. Added text is correctly conditional
   ("when the adopter is wired with journal providers"), authority
   unchanged, claim-pin test_16 passes, full pin-store suite passes.
2. signing/pin_ceremony.py — PASS with minor nit: "rather than passing
   silently" could state explicitly that the refusal happens one layer
   up, in the adopter, not in this module's history checks.
3. trust/history_reconciliation.py docstring — PASS, scope limits
   honest. Nit: KNOWN-UNADOPTED bullet says caller "proves" — the
   function verifies no proof; design record honestly calls it
   caller-attested. Soften "proves" to "attests" in a future doc pass;
   not a ship blocker.
4. trust/pin_adoption.py docstring — PASS, accurate about the factory;
   two omissions, neither false (genesis baseline; supersession excuse
   needs the second provider).
5. Branding/independence grep — PASS, no hits in added lines/new files.
6. Follow-up closure scope — PASS; no surface claims closure beyond
   the detection branch the re-review defined disjunctively.
