# Cycle 27 — War-Room Review, seat rev-r4 (claim honesty)

Reviewer: rev-r4. I did not build this slice. Review was blind and
independent: uncommitted `git diff` plus
`internal/cycle27-work/design-final.md`, then repo-wide greps for
stale and over-claimed rollback wording about the ceremony
issuance and supersession journals.

Slice: every docstring/README statement changed or left unchanged
about these two journals' rollback position —
`trust/ledger.py` (both journal docstrings), `trust/verifier_main.py`
header, `signing/pin_ceremony.py`,
`deploy/verifier-identity/README.md`, `trust/anchoring.py` — plus
`internal/DECISION-CONSUMPTION-HEAD.md` and the internal records.

## Score: 0.86

## Verdict: FIX

The five named code/deploy surfaces are rewritten accurately and
with the full qualification set (findings 4–5). The verdict is FIX
on finding 1: the living decision record still carries the
pre-cycle-27 unanchored position as its last word on the
supersession journal, with no cycle-27 addendum superseding it —
and on two smaller enumeration/catalogue gaps in surfaces this
cycle itself edited (findings 2–3). All three are wording/record
fixes; no mechanism finding is made by this seat.

## Findings

1. **FIX — `internal/DECISION-CONSUMPTION-HEAD.md` has no cycle-27
   addendum, so its standing claim about the supersession journal
   is now stale.** This file's established discipline is that the
   original text is unchanged history and each later cycle
   supersedes it by a dated addendum (cycle 22 anchored the
   consumption journal by Addendum 1; cycles 23–26 each added
   one). Addendum 4 states, as a standing condition, that
   supersession "closure is also conditional on the
   unanchored-journal residual", that "the supersession journal
   is authoritative for abandonment yet is not externally
   anchored (follow-up `ceremony-journal-anchoring` now covers
   BOTH the authorisation journal and the supersession
   journal)", and the main text (lines 47–49, 72, 77) and
   Addendum 4 (lines 316–317, 326) repeat the unanchored
   position. Addenda 5 and 6 do not touch anchoring. Without an
   Addendum 7 recording that cycle 27 anchored both journals
   (kinds `ceremony-issuance` / `ceremony-supersession`,
   production requirement keyed to the ceremony seed, the
   append→anchor-update window caveat, and the research-mode /
   unconfigured no-claim rule) and discharging Addendum 4's
   anchoring condition, a reader of the decision record — the
   file the war room itself treats as the canonical decision
   history — is left with "not externally anchored" as the
   latest, un-superseded statement. The cycle-22 precedent
   (design-b's deliverables table) treated exactly this addendum
   as part of an anchoring cycle's work, not as optional.

2. **FIX (minor) — `deploy/verifier-identity/README.md`
   production bullet enumerates an incomplete INIT-refusal set.**
   Lines 124–125 list the anchor-init flags whose presence
   production refuses as `AION_ANCHOR_INIT` /
   `AION_BUDGETS_ANCHOR_INIT` /
   `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` — the two new flags
   `AION_CEREMONY_ISSUANCE_ANCHOR_INIT` and
   `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT` are absent, in the
   same bullet this cycle edited (the cycle-27 sentences were
   added a few lines below, and the later ceremony paragraph at
   lines 346–356 does correctly say production "refuses both
   INIT flags" for the new journals). As written, the normative
   production-mode enumeration reads as the complete set and
   contradicts, by omission, the paragraph below it. Add the two
   flags to the list.

3. **FIX (minor) — `trust/verifier_main.py` header env-var
   catalogue has no entries for the four new variables.** The
   header documents the consumption anchor pair in full
   (optional, must live outside the verifier home and be
   distinct, production-with-seed requires the path and refuses
   INIT, research/unconfigured makes no rollback claim, INIT
   bootstraps an empty journal only). The issuance and
   supersession PATH/INIT variables appear only in the prose
   rollback paragraph (lines 271–290), with no catalogue entry
   stating their placement, distinctness, production, or
   INIT-bootstrap semantics. Relatedly, no changed surface
   states the new journals' INIT semantics at all (bootstrap of
   an empty journal only — the behaviour the helper inherits
   from `initialise_anchor`'s established-ledger guard in
   `trust/anchoring.py`). This is an omission, not a false
   claim, but the header is the operator-facing reference for
   every other anchor pair and is now asymmetrically silent on
   two of the five.

4. **No over-claim found in the changed claim surfaces — checked
   explicitly.** Every new rollback statement carries all three
   qualifications, consistently worded across surfaces:
   (a) protection only "with the anchor configured" /
   "required in production with the ceremony seed";
   (b) only for an issuance/decision "whose anchor update
   completed"; (c) the append→anchor-update window "NOT
   protected against a full rollback inside that window"; and
   (d) "research mode / anchor unconfigured: no rollback claim".
   Verified in: `CeremonyAuthorisationLedger` and
   `CeremonySupersessionLedger` docstrings (`trust/ledger.py`),
   the `trust/verifier_main.py` header paragraph,
   `signing/pin_ceremony.py` (which correctly retains the
   audit-only fallback — detectable only for same-ceremony_id
   reuse, otherwise only by audit against retained envelopes,
   "not prevented" — scoped to the unconfigured case), and both
   `deploy/verifier-identity/README.md` passages. No text claims
   or implies rollback protection in research mode, and none
   claims protection inside the window. `trust/anchoring.py`
   makes no rollback claim beyond adding the two kinds to the
   format spec and `ANCHOR_KINDS`.

5. **Correctly preserved qualifications / history handling.**
   (a) The supersession docstring's change from "No rollback-
   or forgery-resistance is claimed" to "No forgery-resistance
   is claimed for this journal itself" is the right narrowing —
   rollback resistance is now claimed (qualified), forgery
   resistance still is not, and the pre-cycle-27 fail-closed
   loss behaviour is correctly re-scoped to the
   research/unconfigured branch. (b) The consumption docstring's
   parenthetical — follow-up "narrowed to the issuance journal
   by cycle 22 and extended to the supersession journal by
   cycle 24, was closed for both journals in cycle 27" — is
   accurate. (c) The issuance docstring correctly preserves the
   anchored signing ledger's limits (neither evidence_hash nor
   operator_id stored) inside the unconfigured branch. (d)
   Dated internal history — `BUILD-CYCLE-19` through
   `BUILD-CYCLE-26`, the `cycle19-work`…`cycle25-work` designs
   and reviews, `CROSS-CHECK-*`, `internal/CROSS-CHECK-20.md`
   and `internal/REREVIEW-14-16.md` listing
   `ceremony-journal-anchoring` as open — is **not** stale:
   those records were true when written, and the repo's own
   convention (stated in the cycle-22 re-reviews) is that dated
   internal history is not rewritten. Finding 1 is not in
   tension with this: `DECISION-CONSUMPTION-HEAD.md` is the one
   record whose own mechanism for staying current is the
   addendum, and it is the addendum that is missing.

## Method note

Greps run over the whole repo for
`ceremony-journal-anchoring`, "NOT externally anchored",
"unanchored", "no external anchor", "rollback-vulnerable" and
over-claim shapes ("survives a rollback", "rollback-protected",
"protected against"). Outside `internal/` history, the only
current-claim surfaces mentioning these journals' rollback
position are the five named in the brief, and all were read in
full, not only in diff hunks.
