# Cycle 25 — full review, seat rev-r3 (ADOPTER side)

Scope: `trust/pin_adoption.py`, `trust/runner.py` (plus read-only
checks of `trust/client.py`, `trust/verifier_main.py` and
`trust/supersession_approval_tool.py` where the adopter's
contract depends on them). Blind verdict filed first in
`blind-r3.md` (SHIP, 0.84). This review **changes** that verdict;
the reason is a concrete stranding path found only when the
resume code is read against the verifier's decision gates
(finding F1). The authorisation core is as strong as the blind
read judged it — nothing below reopens self-escalation.

Tests run by this seat (unittest; pytest is not installed):
`tests/test_trust_supersede_adopter.py`,
`tests/test_trust_pin_adoption_crash.py`,
`tests/test_trust_runner.py` — **31 tests, OK, 75s.**

---

## 1. Prove the negative: no unapproved decision request remains — PASS

Grep over production code for `ceremony_supersede` call sites:

- `trust/pin_adoption.py`: exactly one call, inside
  `_request_supersession_decision` (line ~296), invoked exactly
  once, from `_resume_pending` (line ~1099), and only after
  `_find_supersession_approval` has returned an artefact whose
  `replacement.authorisation_id` equals the retained envelope's
  id. There is no other caller.
- The cycle-24 auto-request is **deleted, not gated**: the
  `CeremonySupersedeRequired` handler in `_reanchor` contains no
  decision call and no re-run — it calls `_stop_at_pending`
  (journal line + report) and raises
  `PinSupersessionPendingApproval`. No flag, env var or fallback
  re-enables the old behaviour.
- Exception paths checked one by one: authorise failure →
  `PinAdoptionRefused`; consume failure other than
  supersede-required → `PinAdoptionBurned`; resume decision
  failure → `PinAdoptionBurned` (generic) or stays pending
  (TypeError, §3); post-decision re-anchor failure → `Burned`.
  None of them calls `ceremony_supersede`. No retry loop exists
  anywhere in `snapshot_and_adopt` / `_reanchor` /
  `_resume_pending`; `pin_cycle_hook` only attaches
  `cycle_entry` and re-raises.
- Client contract reinforces it: `VerifierClient.ceremony_supersede`
  takes `approval_dict` as a **required** positional (no
  default), echo-checks it against the envelope before sending,
  and the verifier refuses unapproved requests at step (5b)
  before any journal read, with step (0) disabling the mode
  entirely when no approver key is configured. GPT criteria
  (ii), (iii) and (iv) are satisfied on this side; the
  regression proof is real — the test suite's `CountingClient`
  raises `AssertionError` if `ceremony_supersede` is ever
  invoked without an approval, and
  `test_deadlock_stops_at_pending_without_approval` pins
  supersede_calls == 0, consume_calls == 1, zero decision
  entries, pin unmoved, plus a second approval-less attempt
  making zero authorise/consume/supersede calls.

Minor (doc, not code): `trust/client.py::ceremony_consumer`'s
docstring still narrates the cycle-24 behaviour ("the ADOPTER
… then requests the journaled supersession decision via
ceremony_supersede and re-runs reanchor_pin once"). The code
does no such thing, but this is exactly the relabel hazard
seat-gemini flagged in CROSS-CHECK-18: the prose must match
what the code enforces. Fix the paragraph in the same round.

## 2. PinSupersessionPendingApproval binding facts; the null head fields — PASS

The exception carries everything GPT criterion (i) requires an
approver to bind: the original failed attempt
(`authorisation_id`, `ceremony_id`, `operator_id`, `reason`,
plus the full `envelope_dict`), the replacement candidate
(`candidate_seq`/`candidate_hash`), the exact movement
(`old_cycle_seq`/`old_payload_hash`, exposed as `.movement`),
and `abandoned_movement_candidates` from the adopter's own
journal — honestly labelled as an adopter-side aid, with the
verifier authoritative for the abandoned head. It also carries
`report_path`/`report_written`, `approval_path` and
`journal_persisted`, so a failed journal/report write is
visible on the exception rather than silent.

The pending report writing `head.seq`/`head.entry_hash` as
null is **sound, not a hole**, for two independent reasons:
(a) an uncompleted report cannot be approved by accident —
the approval tool's signing projection validates the head
fields it copies into `failed_attempt` (`head_entry_seq`,
`head_entry_hash`), so nulls refuse at signing time; and
(b) a *wrongly* completed report is inert — the verifier
re-derives the abandoned movement from its own consumption
head and checks the approval binding exactly at step (8b)
(abandoned entry, head seq, head entry_hash, replacement
envelope); any mismatch collapses to
`ceremony_supersede_unproven` and no decision is committed.
A lazy/mistaken completion therefore costs a refused approval,
never a wrong decision. One adopter-side wart, noted not
blocking: `_find_supersession_approval`'s head-hash selection
check is effectively dead — the pending journal line stores
`head_entry_hash: None` and `_journal_ceremonies`' merge skips
`None` values, so `pending_entry.get("head_entry_hash")` is
always `None` and selection is always by authorisation_id
alone. This is disclosed in the docstring and is safe only
because of (b); the docstring should stop implying the check
can ever fire from adopter-written journals.

## 3. Resume: exactly-once, move-aside, TypeError — FAIL (see F1)

What is right: resume is attempted before any new ceremony in
`_reanchor` (a fresh authorisation cannot orphan the retained
envelope); with no approval it re-raises pending with zero
verifier calls; with an approval it presents once, re-runs the
consume of the *same* envelope once, and adopts. In directory
mode the approval file is moved to `<name>.presented` on
success and on generic decision failure
(`test_decision_failure_is_burned_not_retried` pins this), so a
presented artefact cannot be silently re-presented by the
adopter. The TypeError path is sound in intent and effect: a
client that cannot accept an approval argument has presented
nothing, the file is deliberately **not** moved aside, and the
movement stays pending — no fallback to an unapproved request
exists. (Caveat: the `except TypeError` is broad; a TypeError
raised inside a real client *after* the request was sent would
be misclassified the same way — it degrades to F1's family,
not to a safety issue.)

### F1 (blocker, availability): a journaled decision the adopter cannot use strands the movement permanently

The resume path assumes the decision request is the only
gateway to the consume, and that a failed/ambiguous decision
request means "no decision". Both assumptions are false in a
window the verifier and client explicitly document:

- The verifier commits the decision at step (9); a mirror
  failure at step (10) returns `ledger_failed` with **the
  decision standing**. The client's own docstring states the
  consequence: a decision may already be journaled, the
  envelope is still unconsumed, and "the failure is
  recoverable by consuming, not by re-deciding (a re-decide
  would refuse as already decided)."
- The adopter defeats exactly that recovery. On any generic
  exception from `_request_supersession_decision` it moves the
  approval aside and raises `PinAdoptionBurned` (returned pair
  `None`). The same happens if the process dies after the
  decision lands but before the consume, or if the
  `supersede_decided` journal append fails (also `Burned`,
  approval already moved aside). On the next attempt
  `_find_pending_supersession` still matches, but the inbox no
  longer contains a `*.json` approval → pending again. If the
  approver mints a *fresh* approval, presenting it refuses at
  verifier step (8) — a prior decision already exists for this
  envelope (`prior is not None` → `ceremony_supersede_unproven`)
  → `Burned` again, new approval also moved aside. The adopter
  never attempts the one action that would succeed: consuming
  the retained envelope against the already-journaled decision
  (the consume path looks the decision up by authorisation_id
  itself).
- The concurrent-head-move sub-case the code explicitly
  contemplates ("the decision landed but the head moved
  concurrently: still a stop — pending again, against the new
  head", `_resume_pending`) strands the same way: a second
  decision for the same envelope is barred by the
  prior-decision gate, and resume intercepts before any fresh
  ceremony for that candidate/old-pin forever, so no new
  envelope can be minted for the movement either.

No safety property is violated — nothing is decided or
consumed without an approval — but GPT criterion (v)
(restoration through the independently authorised route) is
only proven for the happy path, and the crash/ambiguity window
is precisely the surface this seat was asked to probe. The
fix is narrow and adopter-side: on resume, treat
"decision may already exist" as a consume-first state — e.g.
when the pending entry already carries a `supersede_decided`
phase, or when a decision request refuses with
`ceremony_supersede_unproven` after an approval was presented,
fall through to the single re-anchor/consume attempt of the
retained envelope instead of `Burned`/pending; only if that
consume itself refuses supersede-required should the movement
return to pending (for a genuinely new head). Add a regression
test that kills/ambiguates the decision response after the
verifier commits (the step-(10) `ledger_failed` shape is the
natural seam) and shows the next attempt landing the consume
with no approval in the inbox.

Secondary resume notes (non-blocking, same family):
- Single-file inbox mode (`move_aside=False`): the approval
  file is never moved aside on any outcome, so the "presented
  once" invariant rests entirely on verifier single-use.
  Safety holds (step (8b) `prior_approval`), but the docs
  should state the asymmetry instead of implying move-aside is
  universal.
- A stale approval (minted against a head that has since
  moved) is selected and presented, refuses `unproven`, and is
  classified `Burned` with the file moved aside, rather than
  staying pending for a corrected approval; and the pending
  report is not rewritten on approval-less resume attempts, so
  its head block can go stale underneath the approver. Both
  are recoverable by hand, neither is documented.

## 4. Pending ceremonies excluded from genuine-burn classification — PASS

`_genuine_burn_entries` excludes a ceremony only when it has a
`supersession_pending_approval` phase **and** no `consumed`
phase. That exclusion cannot hide a real burn: the verifier
emits `ceremony_supersede_required` only pre-commit, after its
already-consumed check has certified that envelope unconsumed,
so a pending ceremony's envelope is provably not a burn; and
any ceremony that did reach `consumed` keeps its genuine-burn
status regardless of a pending line. Consequently
`_find_unadopted_burn` cannot mis-select `burned_unadopted`
from a pending ceremony (its candidate was never consumed, so
the `match_head_burn` premise would be false), and
`_known_abandoned_movements` cannot name a pending ceremony as
the abandoned head — while the actual abandoned head (a
genuinely consumed, unadopted movement) remains listed, as
`test_deadlock_stops_at_pending_without_approval` asserts.
`_retained_candidate` deliberately still uses
`_unadopted_burns` (retention is a cache, classification is a
claim — the code says exactly this), and `_resume_pending`
intercepts an exact pending match before burn selection runs.
Residual risk is the usual one for this journal: merging is
per `ceremony_id` over a detection-aid file, so corruption can
lose detection — it cannot manufacture a burn, and the
verifier remains authoritative. Accepted.

## 5. Runner exit 7 — PASS with a coverage gap

By inspection the exit-7 line leaks nothing configured: it
emits only the exception type name, `authorisation_id`,
`ceremony_id`, candidate seq/hash and old seq/hash — all
movement facts/hashes, no operator id, no env values, no
paths, no approval contents. That is consistent with the
runner's structured-line no-echo guarantee (which is honestly
scoped: exit 1 tracebacks are explicitly excluded). Cycle-step
handling is consistent with the documented contract: a hook
that stops pending surfaces as exit 5
(`cycle_recorded_pin_pending`, `adoption_error:
PinSupersessionPendingApproval`) because the cycle *was*
recorded, while an adopt step surfaces as exit 7; the
asymmetry is documented in the module docstring and matches
the Burned/Refused precedent. Two gaps, non-blocking: (a)
`tests/test_trust_runner.py` contains **no** exit-7 test and
no cycle-step-pending test — the new exit code is entirely
untested at runner level; (b) the exit-7 line omits
`journal_persisted`/`report_written`, so the one case where
the approver's input may not exist (report write failed) is
indistinguishable in runner output from a clean pending stop.

## 6. Against seat-gpt's five criteria (CROSS-CHECK-18, Q1)

(i) Independent event binding abandoned head + replacement +
exact movement + original failed attempt — **met** (approval
artefact + verifier step (8b); adopter carries all binding
facts, §2). (ii) Approval independently recorded and verified
before the envelope issues — **met** (verifier steps (5b)/(9):
verified before any journal read, approval id/hash/key
recorded in the decision). (iii) Verifier refuses to issue
merely because the adopter auto-requests — **met** (no
auto-request exists to refuse; unapproved requests refuse at
(5b), mode disabled at (0)). (iv) Regression proof an ordinary
recovery cannot self-escalate — **met** (§1, CountingClient +
deadlock test; `burned_unadopted` envelopes are additionally
refused by the approval tool itself). (v) Restoration tests
exercise the independently authorised route — **met for the
happy path, not for the decision-ambiguity window** (F1): no
test lands a consume against a decision whose request outcome
was lost, and the adopter currently cannot.

---

Final verdict: FIX (0.78) — narrow and adopter-side only: F1 (resume must be able to consume against an already-journaled decision instead of stranding the movement when the decision outcome is ambiguous/lost, with a regression test for that window); the authorisation core — stop-and-pend, deleted auto-request, approval-gated single resume call site — is sound and should not be reworked. Non-blocking adds: the stale cycle-24 paragraph in `client.ceremony_consumer`'s docstring, a runner-level exit-7 test, and `report_written` on the exit-7 line.
