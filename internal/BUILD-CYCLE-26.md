# BUILD CYCLE 26 — claim precision + interactive approval gate

**Summary (claim scope):** Cycle 26 resolves the one
remaining external hold from cycle 25 (internal/
CROSS-CHECK-19.md): seat-gpt's FIX 0.91 was on claim wording
ONLY — every mechanism component was SHIP, but the claim word
"deliberate" overstated the enforcement. Seat-gpt offered
Option A (narrow the claim to exactly the enforced property)
or Option B (an interactive approval step), explicitly not a
redesign. Cycle 26 does both, at the strength the mechanism
can honestly carry. Seat-gemini had already shipped (0.94).
All ship decisions this cycle are PROVISIONAL on the parent's
external confirmation round on internal/
CROSS-CHECK-BRIEF-CYCLE-26.md. Cycles 14–16 were NOT shipped
or recorded; loop state was NOT advanced; `eval/` untouched.

Baseline: cycle-25 tree at 1756 tests OK (skipped=28).
Decision record: DECISION-CONSUMPTION-HEAD Addendum 6
(appended; Addenda 1–5 unedited history). Three builder
seats, disjoint files; six-seat war room, one fix round,
three-seat re-review in internal/REVIEW-CYCLE-26.md.

## Option A — the claim narrowed to the enforced property

**The canonical claim, verbatim, as of cycle 26:**

> Supersession requires a separately invoked,
> cryptographically independent approval operation — a
> standalone tool invocation, with its own inputs, producing
> its own signed artefact under its own dedicated key —
> outside the adopter's automated recovery path. The
> mechanism does not establish that the invocation was
> performed by a human, nor that no other unattended
> automation invoked the tool.

Every claim site stating the supersession guarantee was
narrowed to this sentence in substance: the approval
module's trust claim and TTL comment
(`trust/supersession_approval.py` — the "human-paced act"
TTL justification is now "a separately invoked operation —
report, separate tool invocation, adopter re-run", the
pacing claim removed entirely), the adopter's docstrings
(`trust/pin_adoption.py`), the approval tool's own text
(`trust/supersession_approval_tool.py`), the cycle-25 design
record (`internal/cycle25-work/design-approval.md` — header
narrowing note added; §§1/2/3/6/7 narrowed in place), and
Addendum 6 itself. Sites audited and found already compliant
(no change): `trust/verifier_main.py` (disclaims separate
human/OS user), `signing/pin_ceremony.py` ("does not prove
which human or process made the presentation"), the deploy
README's independence sentence. `docs/`, the root README and
website-facing text contain no supersession claim at all
(verified negative).

**Claim pin:** `tests/test_cycle26_claim_pin.py` (3 tests)
whitespace-normalises and asserts nine over-claim phrases —
"deliberate separate act", "deliberate act", "human-paced
act", "deliberate tool invocation", "deliberate approval
act", "deliberate, separate approval act", "make the *act*
deliberate", "deliberate transcription", "human-paced" — do
not appear in the seven pinned claim files
(`trust/supersession_approval.py`,
`trust/supersession_approval_tool.py`,
`trust/pin_adoption.py`,
`deploy/verifier-identity/README.md`,
`internal/cycle25-work/design-approval.md`,
`signing/pin_ceremony.py`, `trust/runner.py`), and that
Addendum 6 exists and carries the canonical sentence
verbatim. Re-review verified the pin would have failed on
the pre-cycle-26 tree (HEAD hits in three of the files).

## Option B — interactive confirmation gate (friction only)

`trust/supersession_approval_tool.py`'s `approve` command
now requires an interactive typed confirmation BEFORE any
signing or output-file creation:

- stdin must be a TTY (`sys.stdin` resolved at call time;
  `isatty()` must exist and return true). A non-TTY / piped /
  redirected invocation refuses (exit 2) and mints nothing.
- The tool prints a binding summary — the abandoned movement
  (old → new cycle seq, head authorisation id), the
  replacement candidate (cycle seq, full payload hash), and
  the failed attempt (authorisation id, refusal code) — and
  the operator must type the confirmation code: the first 12
  hex characters of the candidate payload hash, displayed in
  the summary. Wrong token, empty line, and EOF all refuse
  and write nothing. Ctrl-C at the prompt is caught and
  exits 2 with a clean refusal (fix round).
- `generate-key` / `public-key` are ungated (neither signs
  an approval; `public-key` is needed at provisioning).
- **Override decision (war room, 6/6 against):** NO
  non-interactive override flag exists. This deviates from
  CROSS-CHECK-19's reconciliation, which had contemplated a
  documented override; the deviation and the vote are
  recorded in Addendum 6. If an override is ever added, its
  existence will be disclosed in the claim before it ships.
  All gate wording is unconditional ("requires an
  interactive typed confirmation; no non-interactive
  override exists") — the phrase "by default" was struck
  tree-wide in the fix round.
- **Scope disclosure (in the tool's docstring):** the gate
  is a property of the CLI `main()` approve path only; the
  module's in-process signing functions
  (`build_approval_for_report` /
  `sign_supersession_approval`) are deliberately ungated —
  the security boundary is approver-seed custody.
- **What the gate is NOT:** it is friction and
  accident-resistance only. A TTY can be scripted via a pty;
  the confirmation token is derived from the pending report
  the invoker already holds and is printed in the tool's own
  summary, so a pty wrapper parsing stdout can satisfy the
  gate unattended. The canonical claim is NOT upgraded by
  the gate, and no text describes the gate as establishing
  that a human performed the invocation. Closure rests on
  Option A; the gate is surplus friction, honestly labelled.

New tests: `tests/test_cycle26_interactive_gate.py` (5) —
non-TTY refusal writes nothing; wrong-token refusal; EOF
refusal; correct token mints an approval that verifies under
the approver public key; generate-key/public-key need no
TTY. The legacy CLI test
(`test_trust_supersession_approval.ToolTests.
test_seed_file_generate_load_and_cli`) was migrated in the
fix round to drive `approve` through a fake TTY with the
token derived from the built report — the gate was not
weakened.

## Tests

1756 (cycle 25) → **1764 tests OK (skipped=28)** on the
final tree, coordinator-run full suite
(`python3 -m unittest discover -s tests`): +3 claim-pin,
+5 interactive-gate. skipped=28 unchanged (documented
deployment-gated skips — deployment is not provisioned on
this VM). Real `state/state.json` not advanced (sha256
verified identical before/after). `eval/` untouched.
Everything else from cycle 25 is intact: the production
diffs to `trust/supersession_approval.py` and
`trust/pin_adoption.py` are docstring/comment-only; the only
production behaviour change is the approval tool's `approve`
CLI gate.
