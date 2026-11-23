# Cycle 25 — Review, seat rev-r5

Scope: RELABELLING honesty, the two small settled adds from CROSS-CHECK-18
(Q2 disclosure, Q4 precaution), and claim discipline across the cycle's
records. Blind score/verdict recorded first in `blind-r5.md` (0.70, FIX),
before reading any other seat's cycle-25 output. This review confirms it.

Method: whole-tree greps for `separately authorised` / `separate
authorisation` / `separately authorized` (+ broader `separately`),
overclaim phrases (`independent approver`, `second operator`, `four-eyes`,
`separate human`), and the exact claim phrase (`authorisation-event
level`), across code, `docs/`, `deploy/`, READMEs and the decision record;
close reads of every current-facing docstring that describes the
supersede flow.

---

## What is correct (credit where due)

- **Stage naming in the new surfaces is right.** The three artefacts are
  named for what they are, consistently, in `trust/supersession_approval.py`
  (approval artefact, verify-side only), `trust/verifier_main.py` module
  docstring (lines ~290–325) and `_mode_ceremony_supersede` docstring
  (~2770–2825), `trust/pin_adoption.py` module docstring (lines 17–56),
  `trust/client.py::ceremony_supersede` (required `approval_dict`, "never
  called in response to a refusal — the adopter calls it only when it
  holds an approval to present"), `trust/ledger.py::CeremonySupersessionLedger`
  (records `approval_id` / `approval_payload_hash` / `approver_key_id` as
  "the independent record of the approval"), and
  `deploy/verifier-identity/README.md` ("Supersession approval (cycle 25)").
- **Trust-claim precision holds everywhere I probed.** Every description
  of the new approval — design §1, `verifier_main` (both docstrings),
  `pin_adoption`, `supersession_approval`, `supersession_approval_tool`,
  deploy README line ~279 — states exactly "authorisation-event level,
  and nothing more / NOT a claim of a separate human or a separate OS
  user". Grep found **no** overclaim: no "independent approver", no
  "second operator", no "four-eyes" in current-facing text. The only
  "separate human / separate OS user" occurrences are negations.
- **Historical records were NOT rewritten.** Addendum 4 of
  `internal/DECISION-CONSUMPTION-HEAD.md`, `internal/BUILD-CYCLE-24.md`,
  `internal/REVIEW-CYCLE-24.md` and the cycle-24 work designs still carry
  the old wording as history. Correct — see F2 for the missing other half.
- **Code comments in the adopter are honestly past-tense:**
  `trust/pin_adoption.py` ~1341 ("Cycle 24 auto-requested a supersession
  decision after this refusal… The auto-request call is DELETED, not
  gated") describes the old behaviour as replaced, not current. This is
  the standard the stale texts in F1/F3 fail to meet.

---

## Findings

### F1 (blocking, coordinator flag — VERIFIED) — `trust/client.py::ceremony_consumer` docstring still teaches the deleted cycle-24 auto-step as the current flow

At `trust/client.py:938–953` the docstring still reads, in the present
tense, as the description of what happens now:

> "the ADOPTER — not this callable — then requests the journaled
> supersession decision via `ceremony_supersede` and re-runs
> `reanchor_pin` once with the same envelope."

Every clause is false in cycle 25: the adopter requests nothing on a
refusal (it stops, journals `supersession_pending_approval`, writes the
pending-supersession report and raises `PinSupersessionPendingApproval`);
`ceremony_supersede` now requires an approval artefact the adopter can
only present, on a *later* attempt, from its inbox; and the re-run is a
resume of the retained envelope, not a re-run "once with the same
envelope" in the same flow. This is the single most misleading
current-facing text in the tree: a reader of the production consumer —
the callable every production ceremony actually uses — learns the exact
behaviour CROSS-CHECK-18 Q1 held cycles 14–16 over.

**Required corrected wording** (replace the sentences from "This callable
translates exactly that code…" to the end of that paragraph):

> "This callable translates exactly that code into
> ``CeremonySupersedeRequired`` (a SigningError carrying the presented
> envelope dict) and does nothing further. In cycle 25 the ADOPTER —
> not this callable — then STOPS: it requests no supersession decision
> and re-runs nothing. It records the pending state, writes a
> pending-supersession report, and raises
> ``PinSupersessionPendingApproval``. A journaled supersession
> decision (verifier-journaled, ``ceremony_supersede``) can be
> obtained only later, on a separate attempt, by presenting an
> independent supersession approval — a signed artefact minted
> out-of-band by ``trust.supersession_approval_tool`` under a
> dedicated approver key, which this callable, the client and the
> adopter have no route to create — after which the retained
> envelope is consumed exactly once. This callable itself still
> makes exactly one consume attempt per invocation and never
> re-decides or re-runs anything."

### F2 (blocking) — No cycle-25 addendum supersedes Addendum 4; the decision record's CURRENT claim is still the old one

Design §9 requires: "Addendum 4's disclosed reading is superseded by a
cycle-25 addendum carrying §1's claim verbatim in substance."
`grep "cycle 25" internal/DECISION-CONSUMPTION-HEAD.md` returns
**nothing**. The file's last word on supersession is Addendum 4:
"explicit, separately authorised, journaled supersession decision"
(line 262) and "**What "separately authorised" means here — disclosed
reading.** … `PinAdopter` requests the decision automatically — exactly
one decision request and exactly one re-run of the consume attempt with
the same envelope" (lines ~296–310).

Addendum 4 must NOT be edited (it is history, and its own text makes its
closure conditional on external ratification that never came) — but
without the promised Addendum 5 it is not merely history, it is the
record's standing claim, and it describes a flow that no longer exists.
Required: append **Addendum 5 — cycle 25** stating (a) Addendum 4's
"separately authorised" reading was NOT ratified (CROSS-CHECK-18 Q1:
seat-gpt FIX, seat-gemini relabel-only); (b) the auto-request is deleted,
the adopter stops and reports pending-approval; (c) a decision now
issues only against an independent supersession approval artefact
verified before journaling; (d) §1's claim verbatim in substance —
authorisation-event-level independence, not a separate human/OS user.

### F3 (blocking) — `signing/pin_ceremony.py` module docstring still frames the old two-phase auto-flow, with no approval gate

At `signing/pin_ceremony.py` ~311–332 ("Supersede decisions (cycle 24,
Option A)"): "the decision is the verifier's journaled act, **requested
by the adopter, and the re-run that follows it is the second phase of a
two-phase authorised flow**, not a retry of an ambiguous consume."
No mention of the approval artefact, the stop-and-report, or the
separate later resume attempt. The `reanchor_pin` function docstring
(~757–770) is vaguer ("the adopter owns that two-phase flow") and
inherits the same omission. Required: rewrite the module paragraph to
the cycle-25 three-stage naming — refusal → adopter stops/reports
pending-approval → out-of-band independent supersession approval →
adopter presents it on a later attempt, verifier verifies it BEFORE
journaling the supersession decision → retained envelope consumed once —
and drop "two-phase authorised flow" (it names the cycle-24 shape).

### F4 (non-blocking but required for the Q2 add to count as landed) — Q2 disclosure: present and accurate in code, absent where an operator would find it

Present and accurate in exactly one place:
`signing/ceremony_authorisation.py:43` — removal prevents FUTURE
issuance, does NOT revoke already-issued authorisations, outstanding
envelopes remain valid/consumable until TTL expiry, allowlist membership
is an issuance fact not a consumption gate, pair with ceremony
signing-key rotation for immediate cutover. That is precisely the
CROSS-CHECK-18 Q2 disclosure, and it is pinned by
`tests/test_rereview_restoration_regressions.py:74`.

But an operator does not configure `AION_CEREMONY_OPERATORS` from a
signing module's docstring. Grep for the disclosure across `docs/`,
`deploy/` and the READMEs returns **nothing**: `deploy/verifier-identity/README.md`
(the doc that walks through setting `AION_CEREMONY_OPERATORS` and seed
rotation, ~252–265) says rotation kills in-flight envelopes "within
900 s" but never says removal alone does not revoke; `trust/verifier_main.py`'s
operator-list prose is silent too. Required: add the disclosure, in
substance, to `deploy/verifier-identity/README.md` beside the
`AION_CEREMONY_OPERATORS` / rotation discussion. Until then Q2 is
landed in the code record and unlanded in the security-facing docs.

### F5 (non-blocking but required for the Q4 add to count as landed) — Q4 precaution: `pin_ceremony` marked; `trust/ledger.py` itself unmarked

Present and accurate in `signing/pin_ceremony.py:695–710`: the
"INTERNAL / TEST-ONLY SEAM (cycle 25, CROSS-CHECK-18 Q4 precaution)"
paragraph names `consume_authorisation` a composition seam, not a
production API surface; a fabricated consumer "silently voids" the
single-use/head guarantees; and it extends the same marking to direct
in-process use of `trust.ledger.CeremonyConsumptionLedger`.

However, `trust/ledger.py`'s own `CeremonyConsumptionLedger` docstring
(line 817 ff.) carries **no** internal/test-only marking at all — grep
for `internal` / `test-only` in `trust/ledger.py` finds only unrelated
"fabricated" mentions in `check_head` prose. A caller who reaches the
ledger class directly — exactly the composition Q4 worries about —
never sees the warning at the surface they are touching. (The
supersession ledger's note that "direct in-process appends record ""
for all three" approval fields makes the same point sharper: the direct
path is documented neutrally, not marked as a seam.) Required: add the
internal/test-only marking to `CeremonyConsumptionLedger`'s docstring
in `trust/ledger.py`, mirroring pin_ceremony's wording: the class is
the verifier process's store; driving it from any other process is
internal/test-only and voids the system-level guarantees.

### F6 (minor, naming drift) — Approval tool CLI help re-calls the approval an "authorisation act"

`trust/supersession_approval_tool.py:415–416`: the argparse description
reads "Mint supersession approvals (cycle 25) as a deliberate, separate
authorisation act." Design §9: "The approval artefact is never called
an "authorisation" in new prose: it is an **approval**; the envelope
remains the authorisation; the journal entry remains the decision."
This is also the one current-facing place where "separate authorisation"
phrasing survives outside history/negation. Required wording:
"Mint supersession approvals (cycle 25) as a deliberate, separate
approval act." (The module docstring's own claim sentence at ~55–57 is
correct and should be the model.) Relatedly,
`trust/supersession_approval.py:10–11` "This artefact is what makes the
authorisation separate" is defensible (it speaks of the decision's
authorisation) but would be cleaner as "what makes the supersession
independently approved"; non-blocking.

### Checked and cleared

- Whole-tree grep for the old label: every remaining
  "separately authorised / separate authorisation" occurrence outside
  F6 is in historical/internal records (Addendum 4 — see F2,
  BUILD/REVIEW-CYCLE-24, cycle-24 work designs, CROSS-CHECK files) or in
  negating/historical sentences in the new modules
  (`supersession_approval.py:7–10`, design-approval.md). No occurrence
  in `docs/`, `deploy/` prose (other than F4's absence) or README
  presents the old auto-step as an independent act.
- `trust/client.py::CeremonySupersedeRequired` docstring (~108–127)
  describes only the refusal semantics and points at the adopter flow —
  no auto-step claim. Cleared.
- Root `README.md` / `trust/README.md` / `docs/*.md` make no supersession
  claim at all — silence, not overclaim. Cleared (the deploy README
  carries the cycle-25 claim, correctly).

---

## Summary

The mechanism's new prose is honest and the claim discipline in the new
modules is exemplary; the cycle fails my scope on completeness of the
relabelling sweep, not on its quality where it was done. F1 and F3 are
current-facing docstrings that still teach the deleted auto-step /
two-phase flow; F2 is the missing superseding addendum that leaves
Addendum 4 as the decision record's standing claim; F4/F5 are the two
settled small adds landed in code but not at the operator/direct-caller
surfaces they were for; F6 is a one-line CLI naming fix. All six are
text-only fixes; none touches the mechanism.

**Final verdict: FIX (0.70)** — fix round = F1 (with the required wording above), F2, F3, F4, F5, F6; re-review of the text diff only.
