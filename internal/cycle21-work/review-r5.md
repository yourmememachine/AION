# Review — cycle 21, rev-r5 (claims + consistency) — BLIND

Reviewer did not build this cycle and did not read any other
reviewer's review-*.md. Sources: CROSS-CHECK-14.md,
cycle21-work/DESIGN-FINAL.md (R5/R6/R7/R9/R10 + claim mandates),
DECISION-CONSUMPTION-HEAD.md, BUILD-CYCLE-20.md ("What remains
open"), and a grep/read audit of the built tree (signing/,
trust/, deploy/). Coordinator totals taken as given and
independently reconciled where possible: 1464 OK (skipped=28),
baseline 1406 (skipped=26).

## Verdict: FIX — score 0.80

The core new claims are right and several mandated wordings are
present verbatim (R5 integrated-system claim, R7 crash contract,
R9 residual, R10 residual). But the flagship docstring still
contains cycle-20 sentences that directly contradict the new
truth, one sibling module still describes the head as future
work, and the deploy README still states the retired
exactly-0600 rule as a live refusal. In this project wording is
a security surface and the external seats have FIXed cycles for
less direct contradictions; these must be cleaned before the
external brief goes out, because the brief will quote these
docstrings.

## Findings

### F1 — HIGH — pin_ceremony.py still says nothing burns at consumption

signing/pin_ceremony.py, evidence-provenance paragraph (module
docstring, ~line 159):

> "it is NOT consumption enforcement (nothing burns when
> ``reanchor_pin`` runs — see the consumption limit below)"

This is the old cycle-20 F1 truth, unreplaced. Since cycle 21
it is false under the production wiring the same docstring
mandates 100 lines later: reanchor_pin invokes the required
``consume_authorisation`` callable exactly once, and the
verifier-backed consumer burns the authorisation in the
consumption journal before any record is constructed. The
docstring therefore asserts both "nothing burns when
reanchor_pin runs" and (cycle-21 section) "single-use
consumption … is achieved ONLY as an integrated-system
property". Task item (1) asked whether the old F1 paragraph was
actually replaced: the "REMAINING limits" paragraph WAS
replaced and states the new truth correctly (closed at the
integrated level), but this earlier paragraph was not, and the
replacement does not state the R10/R3 residuals (unanchored
journal, ceremony-head-vs-pin-head narrowing) — those live only
in trust/ledger.py and DECISION-CONSUMPTION-HEAD.md.
Fix: rewrite the sentence to the integrated form, e.g.
issuance single-use is not consumption enforcement; consumption
is burned at the verifier through the required consumer (see
the cycle-21 section).

### F2 — HIGH — deploy README still states exactly-0600 as a live refusal

deploy/verifier-identity/README.md line 19:

> "The signing key file (`gate.key`, itself exactly 0600 —
> `load_signing_key` refuses any other mode)"

False as built: the shared `_check_owner_only_mode` predicate
accepts {0400, 0600}, and
tests/test_signing_ceremony_seed_hygiene.py
`test_0400_loads_via_load_signing_key` pins 0400 loading.
Task item (3): a tree-wide grep for "exactly 0600" finds it
correctly framed as *retired* in signing/gate_decision.py:317
and signing/ceremony_authorisation.py:267 — the only place it
survives as a present-tense claim about current code is this
README line (the hit in internal/REVIEW-CYCLE-7.md is a
historical record and is fine). The README also received no
consumption-mode / recovery note this cycle; R11 made that
conditional ("if modes are documented there") and modes are
barely documented there, so that omission alone is LOW — but
the exactly-0600 line is a live contradiction in operator-facing
deployment text.

### F3 — MEDIUM — ceremony_authorisation.py describes the head as unbuilt

signing/ceremony_authorisation.py module docstring (~lines
92–97):

> "a genuine envelope replayed within its TTL against a moved
> pin is a consumption-side problem this module does not solve;
> the protected monotonic consumption head remains the fix."

Present-tense future: the head was built this cycle
(CeremonyConsumptionLedger + ceremony_consume). The narrow
reading ("this module does not solve it") is defensible, but
"remains the fix" reads as still-outstanding to any external
reader and omits the mandatory R5 qualification that the
integrated system now closes it. This file was in cycle-21
ownership (seed loader), so the docstring was in scope.
Fix: past-tense + pointer to the consumption journal / R5
integrated-system wording.

### F4 — MEDIUM — pin_ceremony.py trailing residual paragraph conflates the journals

Immediately after the (correct) cycle-21 section, the module
docstring ends (~lines 269–283):

> "No consumption-side ledger-presence check exists in-process
> (the ceremony cannot read the verifier's ledgers — limit M5);
> the ceremony journal's reuse memory is rollback-vulnerable
> until the follow-up ``ceremony-journal-anchoring`` lands
> (reuse is prevented against an intact journal; after a
> rollback it is detectable only for same-ceremony_id reuse,
> and otherwise only by audit against retained envelopes — not
> prevented by one); …"

This is the cycle-19/20 ISSUANCE-journal residual, left in place
directly under the new consumption claims with no journal
named distinctly. Read in position, it states the consumption
residual as "reuse … detectable only for same-ceremony_id
reuse", which contradicts R10's precise built residual
(consumed envelopes are protected by the anchored signing-ledger
mirror in production; only the head for never-consumed
envelopes can be lowered). It also ends a clause with the
garbled "not prevented by one". Fix: label it as the issuance
journal's residual, or move/replace it with a pointer to the
ledger docstrings where R10 is stated precisely.

### F5 — MEDIUM — head-vs-pin-head narrowing silently dropped in three head descriptions

DESIGN-FINAL R3, last paragraph: the head is a CEREMONY head,
not a pin head; the advance_pin residual class is narrowed by
the old-pin rule, full closure is the future pin-store CAS;
"Do not claim otherwise anywhere." No docstring claims
otherwise — but the narrowing itself is absent where the head
is described in:

- trust/ledger.py, CeremonyConsumptionLedger docstring: "This
  journal is the authoritative monotonic consumption head: its
  latest entry's (new_cycle_seq, new_payload_hash) is the head
  target every later consumption is checked against" — no
  ceremony-vs-pin-head statement, no advance_pin residual.
- trust/verifier_main.py, _mode_ceremony_consume docstring:
  "enforce the monotonic consumption head" — no narrowing.
- trust/client.py, ceremony_consume / ceremony_consumer
  docstrings: head rules mentioned, narrowing absent.

The narrowing IS stated in DECISION-CONSUMPTION-HEAD.md
("Accepted residuals") and, for the history head, in
pin_ceremony.py's cycle-16 paragraph ("its head is the ceremony
head, not the pin head"). But a reader of the ledger — the
head's own home — is never told the head does not see
advance_pin movements. One sentence in the ledger docstring
fixes the class.

### F6 — LOW — R10 residual in the ledger docstring: PRECISE (pass, noted)

trust/ledger.py, CeremonyConsumptionLedger docstring carries
R10's wording essentially verbatim — "A rollback of the
verifier home cannot resurrect a consumed envelope whose
consumption is mirrored in the anchored signing ledger
(production), but can lower the enforced head for
never-consumed envelopes" — and adds a research-mode caveat
(mirror unanchored ⇒ not rollback-protected) that is more
precise, not overbroad. Task item (2): pass.

### F7 — LOW — R9 residual wording: present verbatim (pass, noted)

trust/verifier_main.py, _load_config pair block (~lines
595–596), immediately above the overlap checks: "these
relations catch accidents and known derivations, not arbitrary
KDF overlap; no stronger claim is made." All seven R9 relations
(2)–(8) are implemented in the closed set below the comment,
(1) stands as the byte-equality check above it, and the dead
R4 relation is correctly not implemented. Task item (3),
second half: pass.

## Checks that passed

- **R5 claim wording (mandatory form): present.** The
  integrated-system sentence appears in pin_ceremony.py's
  module docstring AND in reanchor_pin's own docstring, with
  the no-op-callable sentence, plus the offline trade-off
  verbatim ("reanchor_pin is no longer an offline function …
  that flag-day breakage is intended") in both places.
- **R6:** ceremony_history wording demoted everywhere in
  pin_ceremony.py — "audit/consistency input that can only
  refuse, never grant", COMPLETE-HISTORY demoted to an audit
  obligation, verifier head authoritative. No docstring in
  signing/ or trust/ still describes ceremony_history as replay
  protection; the one "not rollback or replay protection" hit
  is the correct negative statement about the history check.
- **R7 crash contract:** exact wording present in
  verifier_main.py's ceremony_consume docstring, pin_ceremony.py
  (module + function), and in substance in client.py's
  ceremony_consumer ("never auto-retry … treated as burned").
- **DECISION-CONSUMPTION-HEAD.md vs the built tree (item 5):**
  every claim verified. Zero new env vars — the wrapper
  allowlist is 17 names in both copies
  (deploy/verifier-identity/run-verifier.sh ALLOWED_KEYS and
  health_check.py ALLOWED_KEYS, identical lists, unchanged set
  incl. AION_CEREMONY_SIGNING_SEED_PATH from cycle 20). Mirror
  exists — SigningLedger.append_ceremony_consumption, kind
  "consume", format "ceremony-consumption", existing EXTRA_KEYS,
  invoked only after the consumption append in
  _mode_ceremony_consume. Recovery story matches R3 as built
  (burned-but-unmoved ⇒ new ceremony ahead of the head; consumed
  target never re-anchorable — check_head + append_consumption
  enforce exactly this). Residuals in the decision match R10/R3.
- **Numbers discipline (item 6): reconciles exactly.**
  1406 → 1464 = +58. New test files contribute 53 test methods
  (seed hygiene 12, differential 9, ceremony_consume 26,
  ceremony_consumption 6) and test_signing_pin_ceremony.py goes
  50 → 55 methods (+5); 53 + 5 = 58, no unexplained growth.
  Skips 26 → 28 = +2, both in
  tests/test_signing_ceremony_seed_hygiene.py and both
  root/euid-only: test_real_euid_owns_generated_seed
  (skipIf euid == 0) and test_uid_match_accepted_when_euid_nonzero
  (skipTest when the file owner is root) — confirmed by running
  the four new files read-only as root: 53 tests, OK,
  skipped=2, those two names. Nothing else skips.
- **Operator claim (item 7): untouched, not strengthened.** The
  cycle-20 canonical sentence stands verbatim in
  signing/ceremony_authorisation.py, signing/pin_ceremony.py,
  trust/verifier_main.py (×2) and trust/client.py.
  ceremony_consume's new client docstring adds only a consistent
  narrowing ("consumption checks no operator allowlist —
  allowlist membership is an issuance fact, not a consumption
  gate"), which weakens rather than strengthens the claim.
- **design-c.md re-delivery (item 8): complete.** 629 lines,
  §§0–8 all present (§0 summary … §8 claim wording / weakest
  point), ends with the §8 weakest-point paragraph, no
  truncation marker; its positions match DESIGN-FINAL as built.
- **Loader docstrings (R9):** both loaders state the shared
  predicate as {0400, 0600} with "exactly 0600" explicitly
  retired; gate_decision.py records the
  signing-key-loader-fd-hardening follow-up in load_signing_key's
  docstring as mandated.

## Score rationale

0.80. The built system's own new claims (R5/R7 in the ceremony
path, R9, R10, the decision record, the numbers) are accurate
and several are verbatim-mandated text correctly placed. The
deductions are for stale text the cycle touched or should have
touched: one direct contradiction in the flagship docstring
(F1), one live falsehood in operator-facing deploy text (F2),
and the head narrowing missing from the head's own docstring
(F5). All are wording fixes, none requires code changes — but
under this project's rules they block the external brief, whose
readers will quote the docstrings, not the decision record.

**Verdict: FIX (wording only). Score: 0.80.**
