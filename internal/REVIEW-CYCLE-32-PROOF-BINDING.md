# REVIEW CYCLE 32-PROOF — BINDING ROUND

Verdict: **PROVISIONAL** — nothing ships, working tree not
committed. External seats have not reviewed this round
(brief: internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF-BINDING.md);
under the current rule a ship needs the external seats'
scores at the bar, and no internal approval overrides that.

## Crew (current staffing rule)
- Lead: design, implementation, tests, verification.
- Bug hunter 1 (adversarial, binding design): findings —
  preflight-to-append TOCTOU; os.access probe weak for
  privileged processes; no append lock, so concurrent
  shippers can fork the chain on the same prev; torn final
  line bricks later ships (fail-closed, no recovery tool);
  chain does not stop a writer who recomputes it; field
  types inside records are not individually validated.
  Disposition: all accepted as stated limits/follow-ups;
  none blocks a prototype-scope review, because none is
  claimed closed in the code, the docstring, or the brief.
- Bug hunter 2 (test + claim surface): exactly two key-set
  assertions needed updating (done); the two
  failure-stands tests keep their meaning post-change;
  claim-pin suite unaffected (CLAIM untouched);
  "durable carrier" wording flagged — docstring now
  carries the same-domain anchor disclaimer.
- Dissent slot (lead, assigned against shipping): the
  strongest case against — the post-ship append can still
  fail after the burn, so "fail-closed" is true only of
  the predictable failure classes; and the chain's threat
  model excludes the journal writer, who is exactly the
  author the original Gemini finding worried about. The
  honest name for this round is "tamper-evident binding
  with a pre-burn writability gate", and the records use
  that framing. Preserved, not averaged away.

## Reconciled fix list
None outstanding within this round's scope: the two
key-set updates and the docstring scoping were the only
reconciled items, both landed and re-verified (targeted
128 tests OK; new suite 6/6).

## Evidence
- Failing-first: new suite 3 failures + 2 errors of 6 on
  the pre-fix tree.
- After: new suite 6 OK; targeted 128 OK; ship suites
  standalone 86 OK and 119 OK combined with cycle-32.
- Full discover run: 1,902 ran, 28 skipped, 7F + 14E —
  all expiry refusals in import-time-stamped ship
  fixtures under a ~24-minute loaded run; attributed
  pre-existing, not this change (see BUILD record).

## Next item
External-seat round on the binding brief; then the
non-author anchor for the binding head, or the fresh
flagship artefact under the current checker.
