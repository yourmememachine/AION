# Re-review — cycle 21, rev-r5 (claims) — after fix round

Reviewer: rev-r5, re-checking only its own original findings
F1–F5 (review-r5.md, FIX 0.80, wording only) against the
current tree, plus the cycle-number reconciliation after the
fix round. All greps below are this reviewer's own, run on
the current tree — not the fix seats' reports.

## Verdict: SHIP — score 0.94

All five findings are fixed, with the wording precision the
original review asked for. No finding survives, and no new
contradiction was introduced by the fixes.

## F1 — FIXED (pin_ceremony.py stale "(nothing burns…)")

Own grep for `nothing burns` / `burns when` /
`NOT consumption` in signing/pin_ceremony.py: zero hits for
the old sentence. The evidence-provenance paragraph now
reads, in substance: issuance-side single-use "is NOT itself
consumption enforcement. Consumption enforcement is the
separate cycle-21 mechanism (see the cycle-21 section
below): under the mandated production wiring, reanchor_pin
invokes the required consume_authorisation callable exactly
once, after every local check and before the ceremony record
is constructed, and the verifier-backed consumer burns the
authorisation in the verifier's consumption journal before
any record exists. That protection holds only under that
wiring — a caller-supplied no-op callable gets no
protection (the R5 integrated-system wording in the cycle-21
section below)." The no-op-callable boundary is kept, and no
sentence in the file still asserts the old cycle-20 residual
(nothing burns at consumption) as current fact.

## F2 — FIXED (deploy README exactly-0600)

deploy/verifier-identity/README.md, gate.key layout line now
states: owner-only — "load_signing_key accepts exactly modes
{0400, 0600} under the shared owner-only predicate: no
group/world bits, no setuid/setgid/sticky bits, owner-read
required; it refuses any other mode". Checked against
signing/gate_decision.py `_check_owner_only_mode`: the
predicate refuses `mode & 0o7000` (setuid/setgid/sticky —
the README says so explicitly), refuses group/world bits,
requires owner-read, and additionally refuses owner-execute,
so the accepted set is literally exactly {0400, 0600} as the
README states. The README also gained the cycle-21
"Ceremony consumption" paragraph (ceremony_consume mode,
consumption journal in the verifier home, commit before any
pin movement is adopted) with a "Burned-but-unmoved
recovery" note (consumed target permanently spent, never
re-anchorable; recovery is a new ceremony ahead of the head;
no un-consume; no automatic client retry) — matching R3/R7
as built. Tree-wide grep: "exactly 0600" now survives only
as the explicitly *retired* wording in gate_decision.py and
ceremony_authorisation.py.

## F3 — FIXED (ceremony_authorisation.py "remains the fix")

The Honest-limits bullet now states the built truth in past/
present-correct form: "a genuine envelope replayed within
its TTL against a moved pin is a consumption-side problem
this module does not solve. The protected monotonic
consumption head that addresses it EXISTS as built in cycle
21: the verifier-owned CeremonyConsumptionLedger
(trust/ledger.py), driven through the verifier's
ceremony_consume mode, with signing/pin_ceremony.py's
reanchor_pin invoking the required consumer before a
ceremony record is constructed." It carries the R5
integrated qualification verbatim in substance ("single-use
consumption is a property of the INTEGRATED SYSTEM under
its production wiring — authorise via the verifier client,
re-anchor with the verifier-backed consumer, adopt the
returned pin atomically — not a property of this envelope,
or of reanchor_pin for an arbitrary caller-supplied
callable, in the abstract") and pointers to
signing/pin_ceremony.py and trust/ledger.py "for the built
mechanism and its residuals". Wording is precise: "remains
the fix" is gone (own grep: zero hits).

## F4 — FIXED (trailing residual paragraph unlabeled)

The trailing paragraph in pin_ceremony.py is now headed
"Issuance-journal rollback residual (the ceremony
authorisation — ISSUANCE — journal; NOT the consumption
journal)" and its clauses name the issuance journal
throughout ("reuse is prevented against an intact issuance
journal; after a rollback it is detectable only for
same-ceremony_id reuse, and otherwise only by audit against
retained envelopes — not prevented" — the garbled "not
prevented by one" is also gone). It closes with the
cross-reference: "The consumption journal's own rollback
residual is different (R10, stated precisely in
CeremonyConsumptionLedger's docstring): a rollback of the
verifier home cannot resurrect a consumed envelope whose
consumption is mirrored in the anchored signing ledger
(production), but can lower the enforced head for
never-consumed envelopes." The two residuals are now
distinguishable in place, and neither contradicts R10.

## F5 — FIXED (head-vs-pin-head narrowing)

The narrowing sentence is present in all three required
places, plus the ledger:

- trust/ledger.py, CeremonyConsumptionLedger class
  docstring: "That head is a CEREMONY head — it sees
  consumptions only; advance_pin movements never pass
  through the verifier, so a pin advanced outside ceremonies
  is invisible to this journal. The residual class that
  leaves is named in DECISION-CONSUMPTION-HEAD.md."
- trust/verifier_main.py, _mode_ceremony_consume docstring:
  "The head enforced here is a CEREMONY head — it sees
  consumptions only; advance_pin movements never pass
  through the verifier, so a pin advanced outside ceremonies
  is invisible to this journal. The residual class that
  leaves is named in DECISION-CONSUMPTION-HEAD.md."
- trust/client.py, BOTH consume docstrings:
  ceremony_consume — "Head-vs-pin-head narrowing: the head
  is a ceremony head; it sees consumptions only; advance_pin
  movements never pass through the verifier.";
  ceremony_consumer — "Head-vs-pin-head narrowing: the head
  the consumer enforces is a ceremony head; it sees
  consumptions only; advance_pin movements never pass
  through the verifier."

Overstatement check: own grep for "pin head" across
signing/, trust/, deploy/ and DECISION-CONSUMPTION-HEAD.md
finds it only in negations ("ceremony head, not the pin
head" / "is a ceremony head"). No summary sentence anywhere
in the changed docs overstates the head as a pin head.

## Numbers reconciliation after the fix round

Method counts (def test) in the affected files, as found:

- tests/test_signing_ed25519_differential.py: 9 → 10 (+1)
- tests/test_signing_ceremony_seed_hygiene.py: 12 → 13 (+1)
- tests/test_trust_ceremony_consume.py: 26 → 32 (+6)
- tests/test_trust_ceremony_consumption.py: 6 (unchanged)
- tests/test_signing_pin_ceremony.py: 55 (unchanged — the
  spy legs were extended within existing tests, as stated)

This reviewer ran those five files read-only:
116 tests, OK, skipped=2 — exactly 10+13+32+6+55, with the
same 2 root/euid-only hygiene skips as before the fix round.
Delta vs the original review's reconciliation: +8 tests,
+0 skips. Projected full-suite totals: 1464 + 8 = 1472,
skipped 28 (unchanged). The coordinator runs the full suite
after this re-review; nothing in the per-file counts leaves
unexplained growth.

## Score rationale

0.94. Every one of F1–F5 is fixed at the precision the
original review demanded — F1 and F4 in the flagship
docstring, F2 in operator-facing deploy text including the
0o7000 refusal and the new ceremony_consume/recovery
paragraph, F3 with the R5 qualification carried into the
sibling module, and F5 in all three mandated locations plus
the ledger itself. The numbers reconcile exactly after the
fix round. Held back from higher only because this
re-review's scope was its own five findings plus counts;
the rest of the fix round is other seats' to re-verify.

**Verdict: SHIP. Score: 0.94.**
