# Cycle 30 war-room review — seats R3 (claims/scope) and R4 (safety)

Scope reviewed: `internal/CROSS-CHECK-BRIEF-CYCLE-30.md`,
`internal/cycle30-work/design-final.md`, and the new test
`test_wired_resume_repends_after_head_moves_ahead` (plus the
`wired=False` kwarg on `make_adopter`) in
`tests/test_trust_supersede_adopter.py`. No production code was
changed in this cycle. Both seats reviewed blind to the internal
seats' verdicts.

---

## Seat R3 — claims / scope

**Verdict: SHIP**
**Score: 0.88**

### Findings

1. **The headline claim is honest only in its qualified form, and
   the design-final states that form correctly.** What is now
   justified is: *in the sequential, single-actor wired
   composition, a fresh attempt does not reach pending (pinned in
   prior cycles: beyond-head refuses exit 6, at-head exact pair
   recovers exit 0), and a retained pending in the one
   reconciliation-clean resume shape re-pends on a wired
   no-approval attempt.* The unqualified sentence "pending is
   resume-only in the wired composition" must not be used as the
   closure wording without those qualifiers — see findings 3
   and 4.

2. **This test pins only the resume half; the fresh half is
   inherited evidence, not re-proven here.** The brief is candid
   about this (fresh shapes are pinned in `test_trust_runner`),
   and design-final is candid that the pin covers only the
   consume-first fall-through re-raise branch. The
   `_stop_at_pending` re-pend and the runner exit-7 /
   cycle-step exit-5 surfaces remain code-only, as design-final
   says. Closure text must keep that enumeration; a reader of
   this test alone could otherwise over-infer that all re-pend
   surfaces are pinned.

3. **The seeded state is legitimate, but it is a deliberately
   narrow slice of "retained pending", and the claim must not
   generalise past it.** The seed is not fabricated state: the
   pend arises from a real adopter attempt against a real
   verifier, the supersession decision is really journaled via
   `ceremony_supersede` against a real approver-signed artefact,
   and the manually appended `supersede_decided` journal line
   follows the established F1 precedent (decision committed,
   adopter died before consume — a genuinely reachable crash
   state, also used by two prior tests in this suite). However,
   the seed uses a **single (non-cap) burn by design**, because
   design-final records that the canonical cap-burn pending
   would actually *refuse* wired resume. So this test proves
   re-pend for the reconciliation-clean single-burn shape only.
   It does not prove — and must not be cited as proving — that
   retained pendings in general resume wired; the cap-burn shape
   is a known counterexample within the same design note.

4. **The concurrent-actor residual should NOT block closing this
   follow-up, but it must survive as its own open item.** A
   second actor burning mid-flight producing a genuine fresh
   pend is outside the sequential model all three traces
   analysed, and closing it needs cross-process atomicity — a
   separate design change, not a defect in this pin. It blocks
   only an *unqualified* closure ("fresh pending is
   unreachable"); it does not block closure scoped to the
   sequential model, provided the residual stays explicitly
   open in the backlog rather than being silently absorbed.

5. **Assertions are largely non-vacuous and discriminate the
   intended branch.** Same-envelope identity is checked
   (`repend.authorisation_id == pending.authorisation_id`,
   candidate seq 5), the no-escalation counters are exact
   (authorise 0, supersede 0), exactly one consume is attempted,
   and the no-commit state is checked on both ledgers
   (consumptions stay 3, supersessions stay 1) with the pin
   unmoved at seq 1. Authorise 0 in particular discriminates the
   consume-first fall-through from a fresh-ceremony path, which
   is the branch design-final claims to pin.

6. **Minor specificity gap (non-blocking): the test does not
   prove the wired providers actually ran.** `wired=True`
   forwards the cycle-28 history-reconciliation providers, but
   there is no spy, call count, or negative control showing the
   outcome differs from — or even passes through — the wired
   path; an unwired adopter in the same clean state would
   plausibly re-pend identically, since reconciliation is a
   pre-step that simply does not flag this state. The test
   therefore proves "wired composition does not block this
   resume", relying on prior cycles to prove the wiring itself
   is live. Acceptable for this cycle's question, but worth a
   one-line caveat in the closure record. Similarly,
   `repend.report_written` is asserted as a flag only, without
   re-checking report contents for the re-pended envelope
   (contents are pinned for the unwired case in the deadlock
   test).

### R3 conclusion

Claim scope is honest as written in design-final; ship, with
the closure wording retaining the qualifiers in findings 1, 3
and 4 (sequential model; single-burn reconciliation-clean
shape; concurrent-actor residual remains a separate open item).

---

## Seat R4 — safety

**Verdict: SHIP**
**Score: 0.92**

### Findings

1. **No production or state risk from this change.** The diff is
   one test plus a test-harness kwarg defaulting to `False`;
   the wired providers are forwarded only when a test opts in.
   No production code path, verifier behaviour, ledger format,
   or pin semantics changed. Existing tests calling
   `make_adopter` without `wired` are unaffected by
   construction.

2. **The test cannot mutate real state.** It runs inside the
   suite's isolated fixture (temporary verifier home, real
   verifier subprocess, throwaway keys), consistent with every
   other test in the file. The head-ahead movement to seq 7 is
   a real `ceremony_authorise` + `ceremony_consume` through the
   verifier — not a hand-edited ledger — so the state the wired
   attempt reconciles against is verifier-committed state, not
   a forged journal. Its candidate payload is a dummy hash
   (`"d" * 64`), which is acceptable here: reconciliation and
   the head check operate on the seq/hash pair, and the same
   construction is already used by the suite's head-mover
   helper.

3. **The safety-relevant assertions actually bind.** The
   dangerous outcomes for this shape would be: a second
   decision issued without approval, a consume committing
   pre-approval, or the pin moving. All three are excluded by
   asserted facts, not by the exception type alone:
   supersede_calls 0 (and `CountingClient` itself raises if
   `ceremony_supersede` is ever invoked without an approval
   artefact), consume_calls 1 with consumption count unchanged
   at 3 (the one consume was the pre-commit refusal), and pin
   read back from the store at seq 1. The approval inbox is
   genuinely empty at the wired attempt (seeded artefact
   deleted after the direct decision call), so "no approval
   available" is a constructed fact, not an assumption.

4. **No self-escalation or approval-bypass surface is
   exercised or created.** The wired attempt presents nothing,
   requests nothing, and the re-pend preserves the retained
   envelope as the approvable one — the same fail-closed
   posture the unwired deadlock test pins. Re-pending is the
   safe outcome for this state; landing or burning would each
   have been a safety finding, and both are excluded by the
   count/pin assertions above.

5. **Residual risks are pre-existing, not introduced here.**
   (a) The concurrent-actor seam noted by R3 is a real
   production-model limitation, but it exists independently of
   this test and this test neither widens nor masks it — it is
   explicitly named in design-final. (b) The manual
   `_append_journal` / inbox-deletion crash simulation is a
   test-only seam with established precedent in this suite; it
   grants the test no capability production code lacks. Neither
   is a reason to hold a test-only pin.

6. **Gate note:** the brief states the full-suite result "will
   be recorded after review" and only the standalone pass is in
   evidence at review time. This SHIP is for the test and its
   claim as designed; the cycle's ship gate still requires the
   recorded full-suite green in the normal way. That is a
   process gate, not a finding against this test.

### R4 conclusion

No production, state-integrity, or approval-bypass risk. The
one wired attempt fails closed (re-pend, nothing consumed,
nothing decided, pin unmoved) and the assertions prove it.
Ship.

---

## Combined R3+R4 position

Both seats: **SHIP** (R3 0.88, R4 0.92), subject to two
record-keeping conditions, neither requiring code changes:

- The follow-up closure wording keeps the scoped claim:
  sequential/single-actor model, reconciliation-clean
  single-burn resume shape, consume-first fall-through branch
  only.
- The concurrent-actor residual remains an explicit open item
  (cross-process atomicity), not closed by this cycle.
