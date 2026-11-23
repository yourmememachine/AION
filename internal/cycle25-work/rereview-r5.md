# Cycle 25 — Re-review, seat rev-r5 (fix round)

Scope: verify predecessor findings F1–F6 in `review-r5.md` against the
current tree; spot-check the two fix-round additions named in the
assignment (approver ≠ snapshot signing key enforcement at verifier
startup; single-file inbox asymmetry documentation in
`pin_adoption.py`); re-run the stale-wording sweep. No code modified
by this seat.

Method: close reads of every changed passage cited below; whole-tree
greps (code, `docs/`, `deploy/`, READMEs; historical `internal/`
records excluded from the stale-claim sweep) for `separately
authorised` / `separate authorisation` / `separately authorized` /
`separate authorization`, broader `separately`, auto-flow phrasing
(`auto-request`, `two-phase`, requests-the-decision), and overclaim
phrases (`independent approver`, `second operator`, `four-eyes`,
`separate human`, `separate OS user`).

---

## Findings — verification

### F1 — LANDED
`trust/client.py::ceremony_consumer` docstring (now ~944–966). The
deleted cycle-24 auto-step is gone. The passage now reads, in
substance verbatim against the required wording: the callable
"translates exactly that code into ``CeremonySupersedeRequired``
… and does nothing further. In cycle 25 the ADOPTER — not this
callable — then STOPS: it requests no supersession decision and
re-runs nothing. It records the pending state, writes a
pending-supersession report, and raises
``PinSupersessionPendingApproval``." It then states the decision
can be obtained only later, on a separate attempt, by presenting
an independent supersession approval minted out-of-band by
``trust.supersession_approval_tool`` under a dedicated approver
key "which this callable, the client and the adopter have no
route to create", after which the retained envelope is consumed
exactly once, and that the callable itself still makes exactly
one consume attempt per invocation. Every false clause identified
in F1 is corrected.

### F2 — OUTSTANDING, but assigned to the coordinator — NOT a fix-round failure
Confirmed still absent: `grep "cycle 25" / "Addendum 5"` on
`internal/DECISION-CONSUMPTION-HEAD.md` returns nothing; its last
word on supersession remains Addendum 4 (line 256 ff.), whose
"separately authorised" reading and auto-request description
therefore still stand as the decision record's current claim.
Per the assignment, this addendum is the COORDINATOR's item, not
part of the fix round under re-review, so it is recorded here as
outstanding-but-assigned and does not drive this seat's verdict.
It must still land before the cycle's records can be called
closed: until Addendum 5 is appended (Addendum 4 itself correctly
left unedited as history), the record-level relabelling is
incomplete even though the code/docs relabelling is complete.

### F3 — LANDED
`signing/pin_ceremony.py` module docstring (~307–340) is rewritten
to the three-stage flow: "(1) the refusal reaches the adopter,
which STOPS and reports the movement as pending independent
approval (it requests no decision and re-runs nothing); (2) an
independent supersession approval artefact is minted out-of-band
by the approval tool under a dedicated approver key — the
approval gate; (3) on a later attempt the adopter presents that
approval, the verifier verifies it BEFORE journaling the
supersession decision, and only then is the retained envelope
consumed exactly once." The old "two-phase authorised flow"
framing survives only as an explicit negation ("three-stage, not
a two-phase flow requested by the adopter"). The `reanchor_pin`
docstring (~783–784) is also updated: it "does not request a
decision and does not re-run itself; the adopter owns the
stop-and-report that follows, and completion happens only on a
later attempt presenting an out-of-band independent supersession
approval (the cycle-25 approval gate)".

### F4 — LANDED
Q2 disclosure now present in `deploy/verifier-identity/README.md`
(~265–274), beside the `AION_CEREMONY_OPERATORS` migration /
seed-rotation discussion (~252–263) where an operator would look:
"**Operator removal does NOT revoke (cycle 25, CROSS-CHECK-18 Q2
disclosure).** Removing an operator from
`AION_CEREMONY_OPERATORS` prevents FUTURE issuance for that
operator only; it does NOT revoke authorisations already issued —
outstanding envelopes remain valid and consumable until their TTL
expiry, because allowlist membership is an issuance fact, not a
consumption gate. Where an immediate cutover is required, pair
the removal with a ceremony signing-key rotation (above), which
does invalidate outstanding envelopes." This matches, in
substance, the code-side disclosure at
`signing/ceremony_authorisation.py:43`. Q2 now counts as landed
at the operator surface, not only in the code record.

### F5 — LANDED (both ledgers; supersession marking exceeds the requirement)
`trust/ledger.py`:
- `CeremonyConsumptionLedger` docstring (~879–888) now carries
  "INTERNAL / TEST-ONLY SEAM (cycle 25, CROSS-CHECK-18 Q4
  precaution): this class is the VERIFIER PROCESS's store.
  Driving it — or append_consumption — directly in-process from
  any other process is an internal/test-only seam, not a
  production API surface", with the fabricated-consumer /
  direct-append "silently voids those guarantees" consequence,
  mirroring `signing/pin_ceremony.py`'s marking.
- `CeremonySupersessionLedger` docstring (~1694–1710) carries the
  same marking AND names the append_decision default-fields
  consequence the assignment asked about: append_decision's three
  approval fields (`approval_id`, `approval_payload_hash`,
  `approver_key_id`) are DEFAULTED to `""`, so a direct in-process
  append records an approval-free decision, and the consumption
  ledger's decision binding (`check_head`) never inspects the
  approval fields, so such a fabricated decision would be honoured
  by a direct in-process consume composition; only the verifier's
  `ceremony_supersede` mode passes a verified approval's fields
  and only that path carries the cycle-25 approval guarantee.
  This is more candid than the predecessor's required fix, which
  asked only for the consumption ledger.

### F6 — LANDED (required part)
`trust/supersession_approval_tool.py:415–418`: the argparse
description now reads "Mint supersession approvals (cycle 25) as
a deliberate, separate approval act." The "authorisation act"
naming drift is gone. Residual, non-blocking: the predecessor's
optional clean-up in `trust/supersession_approval.py:10–11`
("This artefact is what makes the authorisation separate") was
not taken; as the predecessor itself noted, that sentence is
defensible (it speaks of the decision's authorisation, in a
passage quoting the CROSS-CHECK-18 ruling) and was explicitly
non-blocking.

---

## Spot-checks of the fix-round additions

### Approver ≠ snapshot signing key at verifier startup — no overclaim
`trust/verifier_main.py::_load_config` (~795–820, fix round, r2
F3) now refuses startup when the configured approver public key
equals either (a) the snapshot (HMAC) signing key bytes
themselves, or (b) the Ed25519 public key derived by treating
those bytes as an Ed25519 seed (the cycle-21 overlap derivation;
skipped only when the key is not seed-length, in which case (a)
still applies). This sits alongside the pre-existing check that
the approver public key differs from the ceremony public key.
Wording check: the comment scopes itself honestly — startup
"ENFORCES that claim where it is checkable here" — and the
neighbouring ceremony-key check carries the same discipline
("the one seed collision the verifier can detect"; "The verifier
never sees either seed; no stronger claim is made"). The
docstrings that call the approver key "a third Ed25519 key,
distinct from the snapshot signing key and the verifier's
ceremony seed" (`trust/verifier_main.py:311`,
`trust/pin_adoption.py:28`, `trust/supersession_approval.py:14`)
state the provisioning/design fact; none claims startup proves
seed-level distinctness beyond the public-key relations actually
checked. No overclaim introduced.

### Single-file inbox asymmetry in `pin_adoption.py` — accurate, no overclaim
Module docstring (~54–62): "the move-aside above is a
DIRECTORY-mode property. When the inbox is configured as a single
artefact file (``move_aside=False``), the approval is NOT moved
aside on any outcome — it remains in place and may be
re-presented by a later attempt — and the presented-once property
rests entirely on the verifier's single-use rule (a second
decision against the same approval refuses at the verifier).
Safety holds in both modes; only the local housekeeping differs."
Verified against the code: `_find_supersession_approval`
(~700–735) sets `move_aside=False` for a single file and repeats
the same statement; the verifier's `ceremony_supersede` step (8b)
(`trust/verifier_main.py` ~3057, ~3064–3095) refuses when a prior
decision already carries the approval_id (`find_by_approval_id`)
or one already exists for the envelope — so a re-presented
single-file approval cannot mint a second decision. "Safety holds
in both modes" is therefore supported. One looseness, non-blocking:
"presented-once" is shorthand — in single-file mode the file may
in fact be re-presented (an attempt made); what the verifier
enforces is decided-once. The surrounding sentences say exactly
that, so the shorthand does not mislead on any guarantee.

---

## Stale-wording sweep (re-run)

- `separately authorised` / `separate authorisation` (+ US
  spellings) outside `internal/`: exactly one hit —
  `trust/supersession_approval.py:7–10`, the historical/negating
  sentence quoting CROSS-CHECK-18 ("a separately signed decision
  is not a separately authorised one"). No present-tense
  occurrence in code, `docs/`, `deploy/` or READMEs.
- Auto-flow phrasing: every remaining `auto-request` occurrence in
  current-facing text is a negation or a past-tense history
  (`trust/verifier_main.py:325, 2835, 2986`;
  `trust/pin_adoption.py:~1457` "Cycle 24 auto-requested …
  The auto-request call is DELETED, not gated"). `two-phase`
  survives in the supersede context only as the F3 negation in
  `signing/pin_ceremony.py:324`; other `two-phase` hits are the
  unrelated budgets/provenance APIs.
- Overclaim phrases: no `independent approver`, `second operator`
  or `four-eyes` anywhere current-facing; every `separate human` /
  `separate OS user` occurrence is a negation carrying the
  authorisation-event-level claim, which remains stated exactly
  and consistently ("authorisation-event level, and nothing
  more") across `verifier_main`, `pin_adoption`,
  `supersession_approval_tool` and the deploy README.

---

## Summary

The fix round landed F1, F3, F4, F5 and F6 completely and, for
F5's supersession ledger, beyond the requirement; neither
spot-checked addition introduces a wording overclaim. The only
open item in this seat's original scope is F2 — the missing
DECISION Addendum 5 — which is the coordinator's assigned item,
recorded above as outstanding-but-assigned rather than a
fix-round failure; the cycle's records should not be called
closed until the coordinator appends it.

**Verdict: SHIP (0.92)**
