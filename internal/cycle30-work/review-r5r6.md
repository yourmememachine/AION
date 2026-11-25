# Cycle 30 war-room review — seats R5 and R6

Scope reviewed: `internal/CROSS-CHECK-BRIEF-CYCLE-30.md`,
`internal/cycle30-work/design-final.md`, and the new test
`test_wired_resume_repends_after_head_moves_ahead` in
`tests/test_trust_supersede_adopter.py`. No production code
changed in this cycle; both seats review the test and the
claim it is asked to carry.

---

## Seat R5 — adversarial

**Verdict: FIX**
**Score: 0.45**

Mandate: show the test passes for the wrong reason, or that
the seeded state is artificial. Both succeed in part.

### F1 — The test does not discriminate wired from unwired (mutation hole)

Nothing in the wired attempt asserts that reconciliation
actually ran. `make_adopter(wired=True)` only forwards the two
provider callables; there is no counting/spying provider, no
assertion on a reconciliation outcome, and no reconciliation-
specific side effect. In `trust/pin_adoption.py`,
`_reconcile_history` returns silently when the consumption
provider is `None`, and every downstream step (pending
intercept, consume-first, approval lookup, re-pend) is shared
code. The prior unwired F2 test
(`test_head_move_after_decision_resume_not_burned_fresh_approval_presented`,
attempt 1) already exhibits exactly this outcome signature —
consume-first consume refuses pre-commit, fall-through, no
approval, re-pend, `consume_calls == 1`, counts unchanged, pin
unmoved. The only deltas here are "providers present" and
"head seq 7 > candidate 5 instead of a rival hash at 5".
Until someone runs the mutation — same test with
`wired=False` — and shows it FAILS, the test pins "resume
re-pends when the head is ahead", not "resume re-pends
*in the wired composition*". That mutation check is absent
from the brief's test evidence (only "passes standalone").

### F2 — `consume_calls == 1` does not prove the claimed branch

`CountingClient.ceremony_consumer` counts the call and
discards the `authorisation` argument: it never records
which envelope was consumed, and the test never asserts the
refusal's `verifier_code` or reason. The brief's claim —
"consume 1 (pre-commit refusal)" via "the consume-first
fall-through re-raise branch only" — is therefore inferred,
not pinned. Any single non-committing consume (head
regression, supersede-required, already-consumed, a generic
pre-commit refusal) followed by a re-pend for candidate 5
satisfies every assertion in the test. Combined with F1, the
specific branch named in the design ("consume-first
fall-through re-raise") is not isolated by the assertions.

### F3 — `report_written` is vacuous for the wired attempt

In the fall-through re-pend raise in `trust/pin_adoption.py`,
`report_written=self.pending_report_path.is_file()` — mere
existence of the file — and `journal_persisted=True` is a
literal. The report file was already written by the initial
*unwired* pend earlier in the same test and is never deleted,
so `repend.report_written is True` would hold even if the
wired attempt wrote nothing. The test also does not assert
that a new `supersession_pending_approval` journal line was
appended by the wired attempt, nor that the report's contents
still bind the retained envelope after the head move. The
brief's "pending report still written" overstates what is
checked: at most "a report file from the earlier pend still
exists".

### F4 — The seeded state is a stack of three out-of-band constructions

The "retained pending" the wired attempt resumes was never
produced by the wired composition, nor by any single adopter
lifecycle:

1. The pend itself is created by an **unwired** adopter
   (`make_adopter(...)` without `wired=True`).
2. The decided state is hand-assembled: a direct
   `client2.ceremony_supersede(...)` call bypassing the
   adopter, a private `adopter._append_journal({... "phase":
   "supersede_decided"})`, and a manual `path.unlink()` sweep
   of the inbox to simulate the spent approval. (This mirrors
   the F1 precedent — acceptable as crash simulation in
   isolation — but here it is one of three stacked seams.)
3. The head-ahead entry is authored by the test harness
   directly against the verifier client: an envelope with
   `old_pin` = the @3 burn pair, candidate seq 7 with payload
   hash `"d" * 64` — no signed snapshot backs that candidate —
   consumed via `client.ceremony_consume(envelope)`, jumping
   the head 3 → 7 over the pending candidate in a way no
   adopter/runner attempt in the suite produces.

Individually defensible, jointly they mean the test shows:
*if* this hand-built state exists, a wired attempt re-pends.
It does not show the state is reachable, which was the
follow-up's actual question.

### F5 — The pinned shape is the non-canonical one

By the design's own admission, the canonical cap-burn
pending (the `drive_to_pending` deadlock shape used by every
other test in this suite) would **refuse** wired resume. The
one shape pinned is the single-burn exception. A claim of the
form "pending is resume-only in the wired composition"
resting on the exceptional shape, while the canonical shape's
wired behaviour is refusal, is a claim whose scope is easy to
misread downstream.

### What R5 concedes

The counts that are asserted (consumptions 3, supersessions
1, pin @1, same `authorisation_id`, candidate 5) are real and
non-trivial; the test is not empty. It pins a genuine
re-pend outcome for a decided, head-ahead state. It does not
pin that the outcome is wired-specific (F1), via the named
branch (F2), or with a freshly written report (F3).

**Required to flip R5 to SHIP:** (a) a wired=False mutation
run recorded as failing, or a counting provider asserting
reconciliation was consulted; (b) record the consumed
envelope's authorisation id and/or the refusal code in
`CountingClient` and assert them; (c) delete the pending
report (or snapshot its mtime/content) before the wired
attempt and assert the wired attempt's own write.

---

## Seat R6 — forced dissent

**Verdict: FIX (against shipping; against closing the
wired-pending-reachability follow-up)**
**Score: 0.30**

Mandate: argue the strongest case against. The case is that
this cycle answers a narrower question than the follow-up
asks, leaves the one admitted hole exactly where the risk
lives, and closing the follow-up on this evidence would
convert an open, tracked uncertainty into a false settled
fact.

### D1 — The concurrent-actor residual must block closing

The design states the residual plainly: a concurrent second
actor burning mid-flight could produce a *genuine fresh*
pend, and closing that needs cross-process atomicity — a
separate design change. That is not a footnote; it negates
the headline claim. "Pending is resume-only in the wired
composition" is a statement about the composition's
reachability space. The sequential model excludes the one
actor class — concurrency — under which the statement is
admitted to be false or unknown. Worse, this very test
*uses* an out-of-band actor (direct client authorise +
consume) to move the head: the test's own setup demonstrates
that actors outside the adopter routinely mutate the head,
yet the interleaving that matters (burn landing *between*
reconciliation at step 3b and the consume) is untested and,
per the design, unclosable without new machinery. Ship the
test if it is useful; do not close the follow-up while its
own design document names an unclosed counterexample class.
The follow-up should be split, not closed: "sequential
resume re-pend — pinned" stays open alongside "concurrent
mid-flight burn — needs cross-process atomicity design".

### D2 — The canonical deadlock shape still refuses wired resume

The follow-up arose from the production deadlock: cap-burn
pending, pin behind the head. The design concedes that shape
"would actually REFUSE wired resume", and this cycle pins
only the single-burn exception that happens to be
reconciliation-clean. Closing the follow-up on the exception
while the production-shaped case refuses is exactly how a
scorecard drifts from evidence: a future reader sees
"wired-pending-reachability: closed" and assumes the
deadlock composition was exercised. It was not.

### D3 — The user-visible surfaces remain code-only

The design's own scope note: the `_stop_at_pending` re-pend
and the runner exit-7 / cycle-step exit-5 surfaces "remain
code-only". What an operator actually observes in the wired
composition is the runner's exit code, not the adopter's
exception type. A reachability claim about the wired
composition that pins neither runner surface is a claim
about a library branch, and should be recorded as such — not
as closure of a composition-level follow-up.

### D4 — One shape, one distance, one ordering

Exactly one configuration is exercised: single burn, decision
journaled *before* the head move, head ahead by a single
direct jump to 7, candidate 5, no approval. Untested
neighbours that a closure would implicitly cover: decision
journaled *after* the head moves ahead; head ahead by a
recovery burn rather than a fresh primary; more than one
entry ahead; head-ahead entry that is itself an unadopted
burn in the adopter's journal. Each plausibly changes the
reconciliation classification. One point does not close a
space.

### D5 — No production code changed, so "ship" buys nothing and closure costs clarity

This cycle is test-only. Shipping the test is low-risk, but
the *decision under review* is closing the follow-up and
recording the claim as justified. The cost asymmetry favours
keeping it open: an open follow-up with a pinned sub-case is
honest state; a closed follow-up with an admitted concurrent
counterexample, a refusing canonical shape, and unpinned
runner surfaces is a latent false premise for every later
cycle that builds on "pending is resume-only wired".

**R6 position:** keep the test (it is a real pin of a narrow
branch, subject to R5's fixes), record the claim verbatim as
"in the sequential model, for the single-burn decided shape,
a wired resume attempt re-pends", and leave the
wired-pending-reachability follow-up OPEN with the concurrent-
actor and canonical-cap-shape items as its remaining content.
Closing it on this evidence is the one outcome R6 dissents
from unconditionally.

---

## Reconciliation note (R5 + R6)

Both seats: **FIX**. Agreement: the test is a genuine but
narrow pin; the assertions do not isolate the wired-specific
branch (R5 F1–F3); the seeded state is heavily constructed
(R5 F4); the claim as worded overreaches the evidence, and
the concurrent-actor residual plus the refusing canonical
cap-burn shape block closing the follow-up (R6 D1–D2).
Disagreement is only on emphasis: R5 would ship after the
mutation/discrimination fixes even with the follow-up
re-scoped; R6 would not close the follow-up under any
version of this cycle's evidence.
