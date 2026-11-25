# Cycle 30 — Coder A trace: can a FRESH wired adopt reach supersession-pending?

**Question:** post-cycle-28/29, can any fresh (not resume) wired adopt attempt
reach the supersession-pending stop (`PinSupersessionPendingApproval`,
runner exit 7 for an adopt step / exit 5 via a cycle-step hook)?
"Wired" = production composition: `trust/runner.py:main()` builds the adopter
via `build_pin_adopter(..., consumption_entries_provider=…,
supersession_entries_provider=…)` from `_history_providers(verifier_env)`
(`trust/runner.py:351-365`).

## Verdict

**No — not in any in-flow state the code can construct, and no test shape
reaches it.** Every fresh shape that would pend unwired is either refused by
history reconciliation before any ceremony, lands as `burned_unadopted`
recovery, or burns on a head-regression. The one reconciliation pass-through
that is not ruled out by construction (supersession candidate-pair excuse,
§3b below) collapses to *resume* in every state the flow itself creates, and
to *burned* in the journal-loss variant — it is a theoretical seam, not a
reachable fresh path. This confirms the open follow-up in
`internal/BUILD-CYCLE-29.md:71-79` ("wired-pending-reachability").

## 1. The fresh-pending gauntlet (all gates must pass, in order)

`PinAdopter.snapshot_and_adopt` (`trust/pin_adoption.py:1073ff`):

1. **Candidate selection (step 3)** — retained-current, retained burned
   candidate, else fresh `sign_state_snapshot`.
2. **Reconciliation (step 3b, `pin_adoption.py:1139-1146`, `_reconcile_history`
   :1032ff)** — runs before anything is persisted/authorised/consumed; a
   `HistoryReconciliationRefused` propagates unwrapped.
3. **Classification (step 5)** — `ok` → advance/`already_current` (no
   ceremony, cannot pend); integrity failure → `PinAdoptionRefused`;
   only `reanchor_required` reaches `_reanchor`.
4. **Resume intercept (`_reanchor`, `pin_adoption.py:1589-1605`)** — if
   `_find_pending_supersession(candidate_seq, candidate_hash, old_pin)`
   matches a retained pending entry, the attempt is by definition a
   *resume* (`_resume_pending`), not fresh. Genesis (`old_pin is None`)
   skips this check but can never pend (§2d).
5. **Fresh ceremony (`_reanchor`, :1729ff)** — pend requires the verifier
   consume to raise `CeremonySupersedeRequired`, caught at
   `pin_adoption.py:1729-1746` → `_stop_at_pending` (:853ff) →
   `PinSupersessionPendingApproval`; runner maps it to exit 7
   (`trust/runner.py:399-412`). Any other consume exception →
   `PinAdoptionBurned` (:1747ff).

Verifier side, pend requires the exact supersede shape
(`CeremonyConsumptionLedger.supersede_head`, `trust/ledger.py:1205-1258`,
enforced in `check_head` :1440-1510; consume mode
`trust/verifier_main.py:3627-3666`): reason is a fresh primary
(`chain_gap_recovery` — not `burned_unadopted`, not `initial_anchor`, not a
recovery lineage), old pin present, **candidate strictly ahead of the
consumption head, old pin strictly behind it**, old-pin hash binding holds,
and **no journaled decision keyed to this envelope's `authorisation_id`**
(decision lookup is by new-authorisation id only,
`trust/ledger.py:1873-1880`).

## 2. Why each candidate position fails wired

Reconciliation relevance (`trust/history_reconciliation.py:347-352`):
entry E is relevant iff `E.new_seq < candidate_seq`, or `== candidate_seq`
with a different hash. Excuses (`find_missing_history`, :354-390), exhaustive:
pair coverage, fully-bound supersession excuse, known-unadopted **head**
excuse. Provider/known-unadopted derivation: `pin_adoption.py:1013-1030`
(genuine burns from the adopter's own pending journal only).

### a) Beyond head (the canonical supersede shape) → REFUSE, exit 6

Head entry E is relevant (`E.new_seq < candidate_seq`):

- **Known-unadopted head excuse cannot apply** — post-fix-round it is
  at-sequence only: `entry is head_entry and … E.new_seq == candidate_seq`
  (`history_reconciliation.py:382-386`; unit-pinned test_09/test_10).
- **Pair coverage is impossible in a verified store.** If E's pair were in
  the store history, that record's `new_seq == E.new_seq == head_seq`, so
  store-consistency (`signing/pin_store.py:338-347`: pin must not sit below
  the history head, and must hash-match at it) forces
  `old_seq >= head_seq` — contradicting the supersede shape's
  `old_seq < head_seq`.
- **Supersession excuse, landed branches are impossible for the head**
  (see §3b for the third branch): a landed/pair-covered superseding record
  implies a consumption entry appended *after* E for that movement, so E
  would not be the head the verifier (same fresh journals) checks against;
  store-consistency independently forces `old_seq >=` the landed record's
  `new_seq > head_seq`.
- Result: E is missing → `HistoryReconciliationRefused`
  (`pin_store_history_incomplete`). It is a `SigningError` but not a typed
  adoption error, so the runner emits `step_refused`, **exit 6**
  (`trust/runner.py:413-418`). Non-head unadopted entries (e.g. the
  primary/depth-1 burns under a cap head) are never excused at all
  (`history_reconciliation.py` head-scoping; test_09), so the cap-burn
  deadlock shape flags every unadopted entry, not just the head.

### b) At head sequence → RECOVER or BURN, never pend

Supersede shape itself requires `candidate_seq > head_seq`
(`ledger.py:1241-1242`), so at-sequence cannot pend verifier-side either.

- **Exact pair** (same seq + hash): E is *not even relevant*
  (`history_reconciliation.py:347-352`); step 3 re-presents the retained
  burned candidate, reason becomes `burned_unadopted`, recovery lands if
  head depth < cap 2 → **exit 0** (cycle 29, §4 #2).
- **Exact pair at cap** (head depth = `MAX_RECOVERY_DEPTH`): lineage is no
  longer a recovery (`ledger.py:1123-1127,1378-1380`) → consume raises
  already-consumed → `PinAdoptionBurned`, exit 4. (Inferred from
  `check_head`; no wired test pins this variant.)
- **Rival hash at head seq**: E is relevant but *can* be excused by the
  known-unadopted head excuse (at-sequence, test_10) — the only at-sequence
  pass. Downstream it still cannot pend: `check_head` raises
  head-regression for a fork at the head sequence (`ledger.py:1412-1417`)
  → `_reanchor` generic branch → `PinAdoptionBurned`, exit 4. (Predicted by
  cycle-29 design seat A, `internal/cycle29-work/design-final.md`; no wired
  test pins it.)

### c) Behind head / at-or-behind with behind old pin → BURN/refuse

`check_head` head-regression branches (`ledger.py:1405-1410,1443-1446`)
→ burned (exit 4) if reconciliation passes at all; entries behind the
candidate are relevant, so thinned shapes refuse first (exit 6).

### d) Genesis (`old_pin is None`) → cannot pend

Reconciliation is bypassed by excuse, not by absence: `genesis_baseline`
returns no missing entries (`history_reconciliation.py:326-327`, wired
test_19). But the ceremony reason is `initial_anchor`, which
`supersede_head` excludes (`ledger.py:1220-1221`) and `check_head` refuses
outright against a non-empty journal (:1397-1400); against an empty journal
there is no head to supersede. Outcome is reanchor-land or
head-regression-burn, never pending.

## 3. The one seam: supersession candidate-pair excuse (§3b)

`find_missing_history._supersede_excused` (`history_reconciliation.py:303-345`)
has three landed branches: (i) replacement record in store by
`new_authorisation_id`, (ii) decision candidate pair pair-covered in store,
(iii) **decision candidate pair == the candidate under attempt**
(:332-335) — no landed record required. Branches (i)/(ii) are ruled out for
the head in §2a. Branch (iii) is the only pass where a fresh consume could
still pend: reconciliation excuses E via a decision bound to an *earlier*
envelope with the identical candidate pair, while the verifier's decision
lookup, keyed to the *fresh* envelope's new `authorisation_id`, finds none
→ `SupersedeRequiredError` → pending. But it cannot arise fresh in-flow:

- **Decisions are only created on the resume path**: `_resume_pending`
  presents an inbox approval and requests the decision for the *retained*
  envelope (`pin_adoption.py:1372ff,1560ff`); the fresh path never requests
  one (auto-request deleted, :1729-1746 comment). A decision for pair P
  therefore implies a retained pending entry for P exists in the adopter's
  pending journal.
- **While that entry exists, the attempt is a resume**, by gate 4 above
  (`_find_pending_supersession` matches on candidate seq+hash + old pin,
  pending phase, not adopted/consumed, envelope present,
  `pin_adoption.py:770-795`) — excluded by the question.
- **Losing only the pending phase line turns it into a burn, not a fresh
  pend**: with the pending line gone, the ceremony's authorised line makes
  it a *genuine burn* (`_genuine_burn_entries`, :655-675 — the exclusion
  needs the pending phase), so `_find_unadopted_burn` selects reason
  `burned_unadopted` (:1606-1615), `supersede_head` returns None for that
  reason (`ledger.py:1218-1219`), and the ahead-of-head recovery envelope
  raises head-regression (`ledger.py:1419-1432`) → `PinAdoptionBurned`.
- **Losing the authorised line too removes the identical candidate**:
  the candidate pair can only be reproduced by re-presenting the retained
  candidate envelope (`_retained_candidate`, :716ff, reads the authorised
  line). A fresh signing cannot reproduce it as a designed path —
  `payload_hash` binds `signed_at`/`expires_at`
  (`signing/state_snapshot.py:506-520`).
- Remaining constructions (a second adopter/pin-dir against the same
  verifier home importing the retained candidate out-of-band; a decision
  minted by a direct `ceremony_supersede` call outside the adopter) are
  outside the production wiring — the runner builds exactly one adopter
  from its env (`trust/runner.py:355-365`) — and are exercised by no test.

## 4. Shapes actually tried in tests

### Wired — production composition (`tests/test_trust_runner.py`, both providers)

| # | Shape | Result | Ref |
|---|-------|--------|-----|
| 1 | Beyond-head single burn: genesis @13, hookless to 15, held-lock burn 13→15 (exit 4, consumption 2, pin 13), state to 16, fresh adopt cand 16 / old 13 | **Exit 6**, `HistoryReconciliationRefused`; consumption stays 2, supersession ledger empty, pin 13 | `test_trust_runner.py:270-334` |
| 2 | At-head exact pair: same burn, fresh adopt cand 15 / old 13 | **Exit 0**, `reanchored`, `record_reason=burned_unadopted`, recovery consume depth 1 (`recovery_of` = head id), consumption 2→3, no pending report, supersession ledger empty | `test_trust_runner.py:336-418` (cycle 29) |
| 3 | Ordinary genesis / advance / idle shapes | Exit 0, no ceremony pending | `test_trust_runner.py:147-269,420ff` |

### Wired — adopter with from-home providers (`tests/test_cycle28_history_reconciliation.py`)

| # | Shape | Result | Ref |
|---|-------|--------|-----|
| 4 | Restored store: genesis 1, gap ceremony to 3 adopted, store restored to genesis generation, cand 4 | `HistoryReconciliationRefused`, missing = gap entry, nothing persisted/consumed | test_16, :686-696 |
| 5 | Compound: adopted-line loss + store restore (gap head 3, cand 4) | Refused, missing = gap entry | test_22, :802-824 |
| 6 | Store-only restore, pending journal intact | Refused (adopted ⇒ not known-unadopted) | test_23, :826-838 |
| 7 | Pending-journal rollback + store restore | Refused (no known-unadopted evidence) | test_24, :840-855 |
| 8 | Pending-journal rollback alone, store intact | Pair coverage ⇒ **advanced** to 4 (no refusal, no pend) | test_25, :857-869 |
| 9 | Wired matching history; provider raises / malformed | Advanced to 2; provider failure ⇒ `PinAdoptionRefused` (fail-closed) | test_18, :714-738 |
| 10 | Wired genesis after pin loss (journal non-empty, no old pin) | Reconciliation does **not** refuse (genesis baseline); ceremony layer decides | test_19, :740ff |
| 11 | Pure `find_missing_history`: at-seq rival excused by head excuse; beyond-head and non-head never excused; supersession excuse branches incl. candidate-pair (test_19 pure) and pair-covered (test_20 pure) | Unit-level only — no adopter/verifier behind them, so no pend is or could be observed | test_09 :297, test_10 :339, test_19 :417, test_20 :451 |

### Unwired — pending IS reachable (contrast; not wired evidence)

| # | Shape | Result | Ref |
|---|-------|--------|-----|
| 12 | Same restored-store shape as #4, **no providers** | `PinSupersessionPendingApproval` — silently, with no history-completeness signal (the hole cycle 28 closed) | cycle-28 test_17, :698-712 |
| 13 | Cap-burn deadlock: genesis @1, movement to 3 burned to cap (primary + depth 1 + depth 2, pairs discarded), fresh primary cand 5 / old 1, no approval | **Pending**: exactly 1 consume, 0 supersede calls, no decision, pin 1; report + pending journal line written | `tests/test_trust_supersede_adopter.py:231-352` (`drive_to_pending`) |
| 14 | Second attempt in #13 with still no approval | Re-pends with 0 authorise / 0 consume / 0 supersede — this is the **resume** path (`_resume_pending` no-approval branch, `pin_adoption.py:1463ff`), excluded from "fresh" | `test_trust_supersede_adopter.py:340-352` |

All other `test_trust_supersede_adopter.py` / `test_trust_supersession_approval.py`
pending outcomes are resume-with-approval, consume-first, or decision-failure
paths — none is a fresh wired attempt.

## 5. Return-path summary (fresh wired adopt)

- `PinSupersessionPendingApproval` → runner exit 7 (adopt) / exit 5 (cycle
  hook): **fresh path exists in code** (`pin_adoption.py:1729-1746`,
  `_stop_at_pending` :850-946; `_consume_retained` re-pends :1309-1335 are
  resume-only) **but is unreachable wired** per §2–§3.
- `HistoryReconciliationRefused` → exit 6: beyond-head, restored-store,
  compound-loss shapes (§2a, §4 #1, #4–#7).
- Recovery `AdoptionResult(reanchored, burned_unadopted)` → exit 0:
  at-head exact pair below cap (§4 #2).
- `PinAdoptionBurned` → exit 4 (adopt) / exit 5 (cycle): held-lock burns,
  head-regression forks, cap-exhausted exact pair, burned-classified
  journal-loss variant of §3.
- `PinAdoptionRefused` → exit 3: corrupt store capture, integrity-failure
  classification, provider failure/malformed inputs (§4 #9).
- Advance / `already_current` → exit 0: classification `ok`, no ceremony.

**Bottom line for cycle 30:** if pending is to be reachable fresh in the
wired composition, it needs a reconciliation design change (e.g. a
supersede-shaped exception at step 3b for a head entry the verifier — not
the store — can adjudicate); no rearrangement of existing test shapes gets
there, because step 3b refuses exactly the states whose only verifier
outcome was pending, and the at-sequence states it lets through are
adjudicated by the verifier as recovery or head-regression, never
supersede-required.
