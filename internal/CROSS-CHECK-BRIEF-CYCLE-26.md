# CROSS-CHECK BRIEF — Cycle 26: claim narrowed + interactive gate (confirmation)

You are an external reviewer seat for the AION trust-boundary
work. In the cycle-25 round (CROSS-CHECK-19), seat-gemini
shipped Q1 (0.94); seat-gpt returned FIX 0.91 on claim
wording only — every mechanism component was SHIP, but the
claim word "deliberate" overstated the enforcement, since the
mechanism cannot establish that no other unattended
automation invokes the approval tool. Seat-gpt offered
Option A (narrow the claim to exactly the enforced property)
or Option B (an interactive approval step), explicitly not a
redesign. Cycle 26 addresses that wording hold and nothing
else. An internal war room (six seats, one fix round, three
re-review seats) has reconciled SHIP; its scores are not
shown to you. Two questions at the end.

## The claim now, verbatim (S1)

Supersession requires a separately invoked, cryptographically independent approval operation — a standalone tool invocation, with its own inputs, producing its own signed artefact under its own dedicated key — outside the adopter's automated recovery path. The mechanism does not establish that the invocation was performed by a human, nor that no other unattended automation invoked the tool.

That sentence now stands, in substance, at every claim site
in the tree, recorded as Addendum 6 of the decision record
(Addendum 5's "deliberate separate act" phrasing is
superseded as claim wording; the addenda before it are
unedited history). The narrowing is pinned by a test
(`tests/test_cycle26_claim_pin.py`) that asserts nine
over-claim phrases — including "deliberate separate act",
"deliberate act", "human-paced", and the variant forms the
internal review found — do not appear in the seven pinned
claim files, and that Addendum 6 carries S1 verbatim.

## What else changed

Cycle 26 implements both of your options together: the claim
is narrowed to S1 tree-wide in the pinned claim files, and an
interactive typed-confirmation gate was added to the approval
tool as friction and accident resistance only; the gate does
not upgrade the claim in S1. Specifically, the approval
tool's `approve` command now refuses a non-TTY invocation
(exit 2, nothing minted), prints the binding summary
(abandoned movement, replacement candidate, failed attempt),
and requires the operator to type the confirmation code —
the first 12 hex characters of the candidate payload hash —
before anything is signed or written. Wrong token, EOF, and
Ctrl-C all refuse cleanly.

We state the gate's limits as plainly as its function:

- A TTY can be scripted via a pty, so the gate is not
  described anywhere as establishing that a human performed
  the invocation. A pty wrapper that parses the printed
  confirmation code from the tool's own output can satisfy
  the gate unattended.
- The confirmation code is derived from the pending report
  the invoker already holds; it binds the confirmation to
  this candidate (accident resistance), and proves no secret
  knowledge and no deliberation.
- The interactive gate guards the `approve` CLI entry point
  only; the tool's in-process signing functions impose no
  TTY check, and no claim is made that unattended code with
  access to the approver seed cannot mint an approval — that
  case is already outside the claim by S1's second sentence.

Contrary to the reconciliation note in CROSS-CHECK-19, no
non-interactive override flag was built: in the approval
tool's approve command the typed confirmation is
unconditional in this pass, a non-TTY invocation refuses and
mints nothing, and if an override is ever added its
existence will be disclosed in the claim before it ships.
(The internal war room voted 6/6 against an override: any
waiver is by construction satisfiable by the unattended
automation the gate exists to friction against.)

No mechanism component changed in cycle 26 except the
addition of that CLI confirmation gate; the cycle-25
mechanism you reviewed is otherwise unchanged, and no claim
of human deliberation, a separate human, or a separate OS
user is made anywhere in the standing claim wording. Full
suite: 1756 → 1764 tests OK (skipped=28, deployment-gated),
including 5 new gate tests and 3 claim-pin tests; the one
pre-existing CLI test that drove `approve` non-interactively
was migrated to the gated flow rather than the gate being
weakened. The real loop state was not advanced.

## Questions

**Q1.** Does the claim now match the enforcement — is Q1
closed at exactly the claim strength of S1?

**Q2.** With Q1 closed (or not), do cycles 14–16 ship?
(Their Q2–Q7 positions from the re-review stand as
previously ruled; cycle 25 removed the Q1 mechanism hold and
this cycle removes the Q1 wording hold.)
