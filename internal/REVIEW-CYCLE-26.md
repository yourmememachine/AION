# REVIEW CYCLE 26 — war room record (claim precision + interactive gate)

Requirement: internal/CROSS-CHECK-19.md (seat-gpt FIX 0.91,
claim wording only; seat-gemini SHIP 0.94). Build record:
internal/BUILD-CYCLE-26.md. Verdict: **SHIP (internal,
reconciled) — PROVISIONAL on the parent's external
confirmation round** on internal/
CROSS-CHECK-BRIEF-CYCLE-26.md.

## Builder seats (3, disjoint files)

- Seat A — Option A claim narrowing (canonical sentence into
  the approval module, adopter docstrings, design record,
  Addendum 6 appended; claim-pin test created).
- Seat B — Option B interactive gate in
  `trust/supersession_approval_tool.py` + gate tests;
  recommended against an override flag.
- Seat C — independent audit: repo-wide claim-site
  classification (found the design-record remnants and the
  one legacy-test failure), adjacent over-claim checks (none
  found: no site claims a different approver-person, seed
  unreadability by same-user processes, single-file inbox
  moves, or an anchored decision journal).

## War room — blind round (scores locked before discussion)

| Seat | Angle | Score | Verdict |
|---|---|---|---|
| r1 | overall claim-vs-enforcement | 0.85 | FIX |
| r2 | gate implementation/security | 0.84 | FIX |
| r3 | claim completeness | 0.84 | FIX |
| r4 | regression safety | 0.90 | FIX |
| r5 | external seats' perspective | 0.90 | FIX |
| r6 | forced dissent | 0.58 | FIX |

Unanimous FIX — on wording/tests only; every seat found the
mechanism and the canonical sentence sound. Convergent
findings:

1. **Suite red (all seats; r6 HIGH):** the gate broke the
   pre-existing CLI test
   `test_seed_file_generate_load_and_cli` (approve driven
   non-TTY → exit 2). A cycle does not ship on a red suite.
2. **Design-record remnants (r1/r3/r5/r6; r3 HIGH):**
   `design-approval.md` §§2/3/7 still carried "deliberate
   act" phrasing (incl. the markdown-broken variant "make
   the *act* deliberate"), the claim pin did not scan that
   file, and Addendum 6's "every claim site" sentence was
   therefore itself an over-claim.
3. **"By default" (r1/r2/r3/r5/r6):** gate wording said
   "interactive by default" while no override exists — a
   phantom-override implication, and a silent deviation from
   CROSS-CHECK-19's reconciliation, which had contemplated
   a documented override.
4. **Option B framing (r6 HIGH, r5 concurring):** seat-gpt's
   Option B as literally specified ("unattended recovery
   cannot satisfy") is NOT met by any TTY gate — a pty
   wrapper parsing the printed token satisfies it unattended,
   the token derives from the report the invoker holds, and
   the in-process signing functions are ungated. Closure
   must therefore rest on Option A, with the gate described
   only as friction and all three facts disclosed in the
   confirmation brief. (r2/r5: the code and Addendum 6
   already describe the gate at exactly that strength; the
   constraint binds the brief, not the code.)
5. Minor: "operator-paced" as a thesaurus substitute for
   "human-paced" in the TTL comment (r5); library-seam
   disclosure sentence (r2); clean KeyboardInterrupt refusal
   (r2); deploy README gate note (r3).

**Override-flag vote: 6/6 NO.** An override would be
satisfiable by exactly the unattended automation the gate
frictions against, would convert Option B into ceremony,
and would burden the claim with permanent disclosure;
seat-gpt had already accepted Option A alone. If a genuine
operational need ever arises it is a new war-room decision,
disclosed in the claim before it ships.

## Fix round (2 seats)

- Code seat: legacy CLI test migrated to the FakeTTY pattern
  (token derived from the built report; gate not weakened);
  "by default" struck in the tool; gate-scope disclosure
  sentence added; KeyboardInterrupt caught → exit 2, clean
  stderr refusal, nothing minted.
- Text/pin seat: design record §§2/3/7 (and §6 pacing line)
  narrowed in place, header note corrected; claim pin
  extended to 7 scanned files and 9 banned phrases (incl.
  variants and standalone "human-paced"); Addendum 6
  corrected — completeness sentence now enumerates exactly
  the pinned files, gate wording unconditional, deviation
  from CROSS-CHECK-19 + the 6/6 vote recorded; TTL pacing
  claim removed in both files; deploy README operator note
  added.

## Re-review (3 seats)

| Seat | Score | Verdict |
|---|---|---|
| rr-gate | 0.96 | SHIP |
| rr-claim | 0.96 | SHIP |
| rr-dissent | 0.93 | SHIP — dissent withdrawn |

rr-dissent verified all five of r6's withdrawal conditions
met (green affected suites; design record narrowed;
Addendum 6 enumeration matches the pin's file list exactly;
pin extended and shown to fail on the pre-cycle tree;
"by default" reconciled with the deviation recorded) and
confirmed the brief-framing condition is satisfiable as
drafted — it binds the delivered brief's wording, which the
coordinator has written to that specification.

## Final state

Full suite, coordinator-run on the final tree: **1764 tests
OK (skipped=28)**. `state/state.json` sha256 identical to
HEAD; `eval/` untouched; cycles 14–16 NOT shipped or
recorded; loop state NOT advanced. Verdict PROVISIONAL
until the parent seats seat-gpt and seat-gemini on
internal/CROSS-CHECK-BRIEF-CYCLE-26.md.
