# Cycle 30 design — wired-pending-reachability, settled

Question (cycle-29 open follow-up): can a fresh wired attempt reach
supersession-pending, or is pending resume-only wired?

Three blind coder traces (coder-a-trace.md, coder-b-tests.md,
coder-c-adversarial.md) agree: fresh cannot. Beyond-head refuses at
reconciliation step 3b (exit 6); at-head exact pair recovers
(burned_unadopted, exit 0); rival hash burns (exit 4); genesis is
excluded from the supersede shape. The only seam (decision bound to
an earlier envelope) implies a retained pending entry — resume by
definition. Residual outside the sequential model: a concurrent
second actor burning mid-flight could produce a genuine pend;
closing it needs cross-process atomicity, a separate design change.

But coder B showed the resume half was unpinned inference, and the
canonical cap-burn pending would actually REFUSE wired resume.
Cycle 30 therefore pins the one reconciliation-clean resume shape:
single-burn pend @5 (unwired), journaled decision bound to the
retained envelope, head moved strictly ahead (@7, reconciliation-
irrelevant), then one wired no-approval attempt re-pends for the
same envelope (authorise 0, supersede 0, consume 1 pre-commit
refusal, consumptions/supersession counts unchanged, pin @1).

Scope kept narrow: this pins the consume-first fall-through
re-raise branch only. The _stop_at_pending re-pend and runner
exit-7 / cycle-step exit-5 surfaces remain code-only.
