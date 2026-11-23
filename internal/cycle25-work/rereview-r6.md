# Cycle 25 — Re-review, seat rev-r6 (FORCED DISSENT, re-review)

**Role:** judge the fix round against the four-item minimal flip set in
my predecessor's `review-r6.md` §9 (FIX 0.35). I re-read the current
tree, not the coordinator's summary of it — one item in that summary
does not match the tree, and it is flagged where it belongs (§2 below).

**Verification performed:** `design-approval.md` §§6–7 as amended;
`trust/supersession_approval_tool.py` (TTL path read in full);
`trust/verifier_main.py` `_load_config` approver blocks and the
step-8b binding site; `trust/pin_adoption.py::_stop_at_pending`;
`deploy/verifier-identity/README.md` supersession section;
`tests/test_trust_supersession_approval.py::test_ttl_bounds`.
Test run: `python3 -m unittest tests.test_trust_supersession_approval`
— **22 tests, OK** (pytest is not installed on this VM; unittest is
the runner used).

---

## 1. Hand transcription — disclosure + inertness: ACCEPTED

My predecessor's §9.1 demanded a mechanical completion step (signed
refusal receipt, or a read-only journal completion step in the tool).
The fix round did neither. It instead amended design §7 with a
"Completion step, disclosed precisely" paragraph: the report carries
`head.seq`/`head.entry_hash` as null; the approver copies both fields
from the verifier's consumption journal as a deliberate transcription
step inside the approval act; the tool performs no journal access by
design, so the approver is the data bus for exactly those two fields;
a wrong transcription is inert because the signing projection refuses
nulls and the verifier re-derives and binding-checks at step 8b,
refusing rather than misapproving.

I verified the inertness claim in code, not prose:
`PinAdopter._stop_at_pending` writes `"seq": None, "entry_hash": None`
with a docstring carrying the same disclosure, and
`_mode_ceremony_supersede` step 8b calls
`approval_binding_mismatches(approval, abandoned_entry=head_entry,
head_entry_seq=head_entry["seq"], head_entry_hash=head_entry["entry_hash"],
signed=signed)` — the seq/hash compared against are the verifier's
own journal values, and every mismatch folds into the single
`ceremony_supersede_unproven` code. The hand never adjudicates; it
only proposes. The verifier adjudicates.

**Judgement: this satisfies the concern, and I withdraw the demand
for a mechanical step.** My predecessor's §3 had three sub-objections:
(a) a transcription step inside a cryptographic binding — but §3
itself conceded integrity survives (fail-closed); the binding's
authority was always the verifier's re-derivation, and the hand-copy
was never load-bearing for correctness, only undisclosed;
(b) the approver's mandatory read access to the verifier's
consumption journal was nowhere disclosed — it is now disclosed in
the operative section (§7), in the sentence that defines the act;
(c) the tests concealed the gap — the adopter harness's
`mint_approval_into_inbox` still completes the two fields
programmatically, but it now does so by copying the exact values
from the consumption entries, which is semantically the disclosed
operator step, and the corrupted-field case is covered at the unit
level by the binding-mismatch tests (`test_failed_attempt_head_moved`).
What remains is a usability cost — a mistyped hex digit burns an
approval attempt and, via §3 below, envelope time — not a security
defect. For a single-operator prototype whose entire claim is
"deliberate act", a deliberate transcription that is inert when
wrong is an acceptable, now-honest design. Two non-blocking nits:
the §4 custody table still does not list "approver reads the
verifier consumption journal" as a custody/access fact (§7 discloses
it; the table is where a reader looks first), and no end-to-end
restoration test drives a *corrupted* transcription through the full
route. Neither blocks.

## 2. Startup coupling — non-decoupling ACCEPTED; the claimed README note is NOT in the tree

**Coupling itself: accepted.** I demanded decoupling in §9.2. The
fix round refused, on the ground that production fail-fast on
key configuration is the discipline the external seats demanded in
cycles 22–23 for the ceremony key (and the consumption anchor follows
the same production rule in this very loader). That precedent is
real, and my predecessor's framing underweighted one point: a
startup refusal is loud at deploy/health-check time, whereas the
per-request alternative produces a verifier that looks healthy and
can never supersede — discovered only at the moment of need, which
is the worse failure shape for a rare recovery path. Symmetry with
the ceremony-seed rule is a defensible, externally-endorsed reason,
not the hand-wave §4 of my review took it for. The added startup
check is genuine and verified in `_load_config`: an approver public
key equal to the snapshot signing key — either its raw bytes or the
Ed25519 public key derived from them — refuses startup as
`verifier_misconfigured`, alongside the pre-existing
approver == ceremony-public-key refusal. That closes an equality
the design's prose had claimed but code had not enforced.

**The note: the coordinator's brief states a rotation/seed-loss note
was added to the deploy README's supersession section. It was not.**
I read that section in full (`deploy/verifier-identity/README.md`,
"Supersession approval (cycle 25)") and grepped the whole repo for
approver rotation / seed-loss text: the section covers provisioning,
the startup refusal, and key distinctness — there is no rotation
procedure and no statement of what seed loss means, anywhere in the
deploy docs. Substantively the exposure is smaller than my
predecessor claimed: seed loss is not a *permanent* wedge, because
rotation-by-reprovisioning is available through the documented
provisioning act itself (generate a new seed outside the verifier
home, write its public key into the verifier env, restart;
outstanding approvals die within their ≤ 3600 s TTL). But an
operator who has lost the seed should not have to infer that from
the provisioning paragraph during an incident. This is a
one-paragraph prose gap, not a code defect: it must actually be
written before the ship record closes, and the coordinator should
not report it as landed until it is in the tree. It does not hold
my verdict, because the recovery it would document already exists
and works through documented steps.

## 3. TTL — FULLY SATISFIED

This item flips completely, in the stronger of the two forms my
§9.3 offered. Verified in `trust/supersession_approval_tool.py`:
`sign_supersession_approval` now refuses —

```python
if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) \
        or ttl_seconds < 60 or ttl_seconds > APPROVAL_TTL_MAX_SECONDS:
    raise SigningError("ttl_seconds outside the TTL bounds")
```

There is no `min(...)` clamp anywhere in the signing path, and the
docstring says so ("never silently clamped"). The pinning test was
updated to match: `test_ttl_bounds` asserts `SigningError` at
`ttl_seconds=30`, `99999`, and `3601`, and that exactly 3600 mints
and verifies — and it passes in the 22-test run above. Design §6
now states the honest effective window: the usable approval window
is bounded by the candidate envelope's *remaining* TTL (its 900 s
cap runs from issuance, which precedes the failed consume, the
report, the §7 completion step, and the tool run), so a late-minted
approval may have far less than its own TTL, or none. One story,
in design, docstring, code, and test — which is what
seat-gemini's naming condition asks for. The 3600 s exposure itself
remains, bounded by single-use + full binding + head staleness as
§6 argues; with the envelope bound now stated, I no longer call
the window illusory, only generous.

## 4. Ship-record wording — code/docs state ACCEPTED; the brief must say the following

I cannot see the coordinator's external brief, so I judge the
state it will describe and state my conditions on its wording.
The in-tree state is clean: design §1 carries the deliberate-act
claim verbatim, the deploy README repeats it ("Independence is at
the authorisation-event level only — not a claim of a separate
human or OS user"), and I found no upgraded phrasing
("independent approver", "second operator", "four-eyes") in the
cycle-25 surfaces. That is necessary but not sufficient. **To
satisfy this seat, the brief / cycle-25 addendum must:**

1. Present design §1's claim as *the* claim and ask seat-gpt to
   ratify **that** — stating explicitly that criterion (i)'s
   original wording ("a genuinely independent authorisation
   event") is met only in the weakened deliberate-act sense:
   same human, same OS user, same VM; a separate signed artefact
   minted by a separate deliberate tool invocation under a
   dedicated key. It must not state or imply criterion (i) is
   met as written.
2. Describe the adopter as custodian/presenter — it holds the
   inbox, selects the artefact, and executes the decision and
   consume automatically on its next run — not as "merely
   transport" / "merely carries".
3. Qualify "independently recorded" per my predecessor's §8:
   the record is `approval_id` / `approval_payload_hash` /
   `approver_key_id` inside the decision entry in the
   supersession journal (itself not externally anchored), plus
   the anchored signing-ledger mirror of the decision; the
   verifier retains no copy of the full approval artefact.
4. Disclose the §7 hand-completion step (approver copies
   `seq`/`entry_hash` from the verifier's consumption journal;
   wrong values are inert at step 8b), the §6 envelope-bound on
   the effective approval window, and the deliberate production
   startup coupling (§2 above).
5. Include the approver-seed rotation / seed-loss paragraph
   (§2) in the operator docs it points to — written, not
   asserted.

If the brief does those five things and seat-gpt ratifies the
§1 claim, criterion (i) is honestly closed. If seat-gpt does
not ratify it, that is the external seats' call on a
claim-framing position — no further code in this cycle's scope
closes it, and none should be demanded: the remaining distance
to literal criterion (i) is a separate human / OS boundary,
which §1 has always declared out of the prototype's claim.

---

## Summary against the flip set

| §9 item | Fix-round form | This seat |
|---|---|---|
| 1. Hand transcription | Disclosure (§7) + verified fail-closed inertness (step 8b), no mechanical step | **Accepted** — security core was non-disclosure; now disclosed and code-verified inert |
| 2. Startup coupling | Deliberately not decoupled (cycles 22–23 fail-fast precedent); approver == snapshot-key startup refusal added and verified; rotation/seed-loss note **claimed but absent from the tree** | Coupling **accepted**; note is a pre-ship prose TODO, not a code defect |
| 3. TTL | Tool refuses outside [60, 3600] (no clamp); test re-pinned to refusal; §6 states envelope-remaining bound | **Fully satisfied** |
| 4. Ship-record wording | In-tree docs carry §1 claim without upgrade; brief unseen | **Conditionally satisfied** — brief must meet the five wording conditions in §4 above |

No remaining objection of mine is a code defect. The two open
items — the missing rotation/seed-loss paragraph and the brief's
wording — are documentation and claim-framing, and the second is
explicitly for the external seats to judge.

**Final verdict: SHIP — score 0.72. Remaining objections are claim-framing / documentation positions for the external seats to judge, not code defects; the rotation/seed-loss paragraph must be written into the deploy README before the ship record closes, and the external brief must meet the five wording conditions in §4.**
