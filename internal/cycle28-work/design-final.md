# Cycle 28 — Design Record (design-final)

Date: 2026-11-24.

## Scope

Cycle 28 closes the follow-up `pin-store-history-reconciliation`
named in internal/REREVIEW-14-16.md §2/§6: the detection branch
of the cycle-15 audit hole. Cycle 15's fix round rescoped the
claim (store history = non-authoritative, restoration-lossy
replica; the verifier's externally anchored consumption journal
= sole authoritative ceremony audit history). Detection was
explicitly left open: after a pin-store restoration the store
history could *silently* lack a record the consumption journal
has (re-review leg 4 ends with store history [seq 1, seq 4]).

This cycle adds detection only. It does not redesign the
ceremony, does not change any journal format, does not touch
`eval/`, and does not advance real `state/state.json`.

## Options considered

1. **Anchor the pin-store document head externally** (the
   other branch named in REREVIEW-14-16 §6). Rejected for this
   cycle: the pin store lives on the adopter side, outside the
   verifier home; a new anchor kind + provisioning + startup
   verification is a larger change, it detects *any* rollback
   of the document (including a legitimate operator restore of
   pin + history together, which the consumption head already
   bounds), and it still cannot say *which* ceremony record is
   missing. It remains available as a future follow-up.
2. **A new verifier mode carrying the store history in the
   request.** Rejected: new protocol surface, new wiring keys,
   and the verifier would be judging caller-supplied history —
   the cycle-16/21 lesson is that caller-supplied history can
   only refuse, and the refusal decision belongs where both
   inputs are already held.
3. **Reconciliation at the adopter, against journal entries
   supplied by the composition layer (CHOSEN).** The adopter
   (`trust/pin_adoption.PinAdopter`) is the one production
   component that already holds the verified store history on
   every attempt. The consumption/supersession journal entries
   reach it through optional provider callables — the same
   composition-seam discipline as cycle 21's
   `consume_authorisation` and cycle 25's internal/test-only
   seam warnings: the adopter never reads the verifier home
   itself (cycle 25: the adopter has no access to the
   verifier's journals, and this design does not give it any);
   the operator/orchestrator composition that legitimately
   holds both supplies the entries, freshly on each attempt.

## Mechanism

New module `trust/history_reconciliation.py`:

- `find_missing_history(store_history, consumption_entries,
  supersession_entries=(), *, candidate_seq,
  known_unadopted_authorisation_ids=())` — a pure function
  returning the tuple of consumption-journal entries (in
  journal order) that are *missing* from the store history and
  *relevant to the candidate*. An entry E is missing iff ALL
  of:
  1. `E.new_cycle_seq < candidate_seq` — relevance: E attests
     a ceremony movement strictly behind the candidate the
     caller is about to adopt/advance to. Entries at or ahead
     of the candidate are not ancestors of it; an entry whose
     target *is* the candidate is the in-flight burn case
     (rule 3 also covers it), and a same-sequence
     different-hash entry is a fork — head-regression
     territory, already refused by the consumption head rules,
     not a history-completeness fact, so it is not double-
     reported here.
  2. No store record carries `authorisation_id ==
     E.authorisation_id`.
  3. No store record carries E's exact movement pair
     `(old_cycle_seq, old_payload_hash, new_cycle_seq,
     new_payload_hash)` — recovery coverage: a primary burn
     and its `burned_unadopted` recovery share one pair, and
     the recovery record that *was* adopted covers both
     journal entries. Without this rule every legitimate burn
     recovery would false-positive forever.
  4. E is not the abandoned movement of a supersession
     decision whose replacement (`new_authorisation_id`) *is*
     present in the store history — a superseded movement was
     consumed but never adopted, so its record legitimately
     never entered the store; the adopted superseding record
     is the evidence the abandonment was completed. A decision
     whose replacement record is absent excuses nothing.
  5. `E.authorisation_id` is not in
     `known_unadopted_authorisation_ids` — movements the
     adopter's own pending journal proves were consumed but
     never adopted (genuine burns and supersession-pending
     movements). Those are handled by the existing recovery /
     supersession flows, not by a completeness refusal. This
     excuse is deliberately narrow and caller-attested: it is
     derived by `PinAdopter` from its own pending journal
     only, and a wholesale pin-directory rollback that also
     loses the pending journal loses the excuse too — the
     refusal then fails closed and an operator reconciles,
     which is the honest direction.
- `reconcile_history(...)` — same inputs; returns `()` when
  complete, else raises `HistoryReconciliationRefused`, a
  `SigningError` subclass carrying the deterministic code
  `pin_store_history_incomplete` (class attribute `code`,
  mirroring the `verifier_code` pattern in trust/client.py)
  and `.missing_authorisation_ids` / `.missing_ceremony_ids`
  in journal order. Deterministic: same inputs, same refusal,
  same missing list, no clock, no randomness.
- Input discipline: store history entries must be
  `PinCeremonyRecord`s and journal entries must carry the
  keys the check reads; anything else is a `SigningError`
  refusal, never a silent skip — a malformed journal entry
  cannot launder a missing record past the check.
- `consumption_entries_provider_from_home(home)` /
  `supersession_entries_provider_from_home(home)` — helpers
  building provider callables that load the verifier's
  journals fresh per call. Labelled in the module docstring
  with the cycle-25 seam warning: driving the ledger classes
  in-process is a composition/test seam for the layer that
  legitimately holds the verifier home, not a licence for the
  adopter to reach into it.

## Wiring (trust/pin_adoption.py)

- `PinAdopter.__init__` gains two optional keyword parameters,
  `consumption_entries_provider=None` and
  `supersession_entries_provider=None`. `None` (the default,
  and therefore every existing construction) means no
  reconciliation check — the pre-cycle-28 behaviour, stated
  plainly: detection is an integrated-system property of the
  wiring that supplies the providers, exactly as cycle 21
  scoped single-use consumption to the wiring that supplies
  the verifier-backed consumer. `build_pin_adopter` passes
  optional providers through and never derives them from the
  verifier env: the adopter must not read the verifier home.
- In `snapshot_and_adopt`, after the candidate is selected
  (step 3) and before any branch persists or consumes
  anything, the adopter — when a consumption provider is
  configured — calls `reconcile_history` with the captured
  store history, the providers' fresh entries, the candidate's
  sequence, and `known_unadopted_authorisation_ids` derived
  from its pending journal's genuine burns and
  supersession-pending entries. A refusal propagates as
  `HistoryReconciliationRefused` (a `SigningError`, so
  existing refusal handling sees it) and nothing is persisted:
  no pin write, no evidence artefact, no authorise/consume
  call has happened yet at that point in the flow.
- Placement rationale: after candidate selection because
  relevance is defined against the candidate; before the
  classify branches because the advance path must be covered
  too — a normal one-step advance over an incomplete history
  is exactly the silent case (the pin moves, the gap is
  laundered into continuity). The candidate's own in-flight
  burn cannot false-positive: its journal entry's target is
  the candidate itself (rule 1) and its pair is the recovery
  pair (rule 3).

## Docstring updates

- `signing/pin_store.py`: the VERIFIED-PRESENT-HISTORY bullet
  gains one sentence — incompleteness against the journal is
  now *detected* at adoption time when the adopter is wired
  with journal providers (cycle 28), naming
  `trust/history_reconciliation.py` and the refusal code; the
  bullet's existing scoping (journal sole authoritative; a gap
  proves nothing about safety) is unchanged.
- `signing/pin_ceremony.py`: the COMPLETE-HISTORY paragraph
  gains the same pointer in one sentence. Claim-pin test
  `test_16` in tests/test_signing_pin_store.py must still pass
  (its required substrings are preserved verbatim).

## Failing-first evidence

tests/test_cycle28_history_reconciliation.py is written
against the pre-change tree first: on that tree the module
does not exist, so the suite fails at import — recorded in
internal/cycle28-work/failing-first.md together with a
pre-change demonstration that a `PinAdopter` attempt over a
restored store (journal holding a ceremony the store lacks)
proceeds with no detection.

## Honest residuals

- Detection is wiring-dependent (above). An adopter built
  without providers behaves exactly as before cycle 28.
- The check sees consumptions only. `advance_pin` movements
  never enter the consumption journal, so a lost *advance*
  leaves no journal trace to reconcile against — unchanged
  from cycle 21's head narrowing; the pin itself is the
  evidence for advances, and a restored pin is caught by the
  consumption head rules on the next ceremony.
- A coordinated rollback of the pin store *and* the journal
  entries supplied to the check is out of scope: the journal's
  own external anchors (cycles 22/27) are the control there,
  verified at verifier startup.
- `known_unadopted_authorisation_ids` is adopter-attested
  (rule 5). A fabricated excuse list could suppress detection
  — the same trust already placed in the adopter's pending
  journal as a detection aid; it can only excuse entries the
  journal independently shows as consumed, and the excuse
  list is an explicit argument, auditable at the call site.

## Staffing

15 coders, 5 pods of 3:

- Pod A (seats 1, 5, 8): reconciliation core
  (`trust/history_reconciliation.py`).
- Pod B (seats 2, 6, 7): adopter wiring
  (`trust/pin_adoption.py`).
- Pod C (seats 9, 10, 11): adversarial tests
  (tests/test_cycle28_history_reconciliation.py).
- Pod D (seats 3, 4, 15): docstring / claim updates
  (signing/pin_store.py, signing/pin_ceremony.py).
- Pod E (seats 12, 13, 14): records, cross-check brief,
  calibration entries.

War room: 6 internal reviewer seats drawn from pods other
than the builders of the slice under review, one forced-
dissent seat, plus the two external seats (brief only this
run — external verdicts are the parent's browser round; the
cycle verdict stays PROVISIONAL until they are reconciled).

## Reconciliation of the coder discussion (pre-build)

The three coder seats (core / adopter wiring / adversarial
tests) reviewed the draft above blind; the following rulings
amend it and are the built design:

- **Rule 4 is fully bound** (seat A): a supersession decision
  excuses E only when `abandoned_authorisation_id ==
  E.authorisation_id` AND the decision's new side is landed:
  `new_authorisation_id` present among store record ids, OR
  the decision's candidate pair is pair-covered by the store
  history, OR the decision's candidate pair equals the
  candidate under attempt (the superseding record is the one
  being adopted now). Existence of *some* decision excuses
  nothing.
- **Rule 5 is head-scoped** (seats A+B reconciled): the
  known-unadopted excuse applies only when E is the
  consumption journal's head entry. A non-head entry claimed
  unadopted is a contradiction — the head can move past a
  burn only via its recovery (rule 3) or its supersession
  (rule 4) — so a non-head excuse is never honoured. The
  wired source of the excuse list is solely the adopter's own
  pending journal (`_genuine_burn_entries()`), never a free
  caller list in the production path; the pure function takes
  it as an explicit, auditable argument.
- **Rule 1 is pair-aware** (seats A+C, same ruling): relevance
  is `E.new_cycle_seq < candidate_seq` OR (`== candidate_seq`
  AND `E.new_payload_hash != candidate_hash`). The exact-pair
  at-seq case is the candidate's own in-flight burn (excused
  by the head rule / pair logic); a different-hash at-seq
  entry is a consumed movement at the candidate's own target
  the store does not hold, and flags.
- **Rule 2 is pair-bound** (seat A): id coverage requires the
  store record to agree on authorisation_id AND the full
  movement pair (and on ceremony_id when the journal entry
  carries one). An id-only match excuses nothing.
- **Genesis baseline** (seat A): when the attempt is a genesis
  (no old pin — a sanctioned `lost_pin` / `corrupted_pin` /
  initial store creation), prior journal entries are the
  attested loss, not missing history: `genesis_baseline=True`
  makes the check return no missing entries. `PinAdopter`
  passes it exactly when its captured old pin is None. The
  pure function's default is False.
- **No pin-seq bound** (seat A): relevance never consults the
  store pin's sequence — in the leg-4 shape the missing
  entries sit at/below the restored pin, which is the most
  damning position, not an excused one.
- **Malformed inputs raise `SigningError`** (seat C asked the
  war room to fix one type): non-record history entries,
  journal entries missing a required key or carrying a bool /
  wrong-typed sequence, and duplicate authorisation ids in
  the store history all refuse with `SigningError`, never a
  silent skip and never a fabricated missing entry. Required
  journal keys are exactly: `seq`, `authorisation_id`,
  `old_cycle_seq`, `old_payload_hash`, `new_cycle_seq`,
  `new_payload_hash` (v1 consumption entries carry no lineage
  keys and must reconcile).
- **Wiring placement** (seat B): one call in
  `snapshot_and_adopt` as step (3b), after candidate selection
  and before classification — the only point all outcomes
  (advanced / already_current / reanchored / genesis) pass
  through, where nothing has been persisted or consumed yet.
  Provider failures (exception or malformed entries) fail
  closed as `PinAdoptionRefused`, never as a silent fall-back
  to no-provider behaviour; `HistoryReconciliationRefused`
  itself propagates unwrapped so its `.code` survives.
- **`build_pin_adopter` does NOT auto-wire** (coordinator
  ruling over seat B's recommendation): seat B showed it
  *can* (the verifier env it receives carries
  AION_VERIFIER_HOME), but cycle 25's separation stands — the
  adopter does not read the verifier's journals; auto-wiring
  would also silently change the production factory's
  behaviour for every existing deployment and test. The
  factory gains optional provider pass-through arguments
  only. This disagreement is recorded here and put to the
  war room.
