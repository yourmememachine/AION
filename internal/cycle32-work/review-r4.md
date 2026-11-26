# Cycle 32 — War-room review R4 (safety / limits)

Reviewer seat: R4, safety/limits. Scope: `git diff` on `trust/shiptx.py`,
`docs/RECOVERY-CONTRACT.md`, `tests/test_trust_shiptx_anchoring.py`.
No code edited by this seat.

## Verdict: FIX (docs-only) — Score: 8/10

The code change is safe and fail-closed on every safety question put to
this seat; nothing in it needs rework. The FIX is for two stale/incomplete
wordings in `docs/RECOVERY-CONTRACT.md` that this same cycle edited —
one a hard-wrong number created by the change itself (F5), one a lead
paragraph the new "Closed" text supersedes but does not harmonise (F6).
Both are one-line doc fixes; no code or test change is requested.

Evidence run by this seat: `python3 -m unittest
tests.test_trust_shiptx_anchoring` → **68 tests, OK**.

## Findings

### F1 — PASS: no pre-settlement behaviour change
`git diff -U0 trust/shiptx.py` shows hunks only at the `recover()`
docstring (~L765) and inside the post-settlement re-verification block
(~L1010, L1036, L1043). The pre-settlement path is byte-untouched:
same-file guard, both initial `verify_anchor` calls, N3
park-over-error classification (`ship_reasons` / `tx_reasons`,
`ANCHOR_PARK_REASONS` filtering), per-transaction operator-error
outcomes, and the settlement loop all run exactly as before. The new
`elif` branches can only execute in the post-settlement loops, after
the settlement loop has completed.

### F2 — PASS: park semantics unchanged
The new branches are guarded by `r not in ANCHOR_PARK_REASONS` and
append `(f"<source>: {r}", None)`. Because the bare reason is `None`:
- they can never add to `park_pairs`, `JournalIntegrityError.reasons`,
  or `.anchor_sources` (park_pairs filters `r is not None`);
- they can never park a transaction, create an ANOMALY outcome, or
  trigger `JournalIntegrityError` on their own;
- when a genuine new park reason accompanies them, they ride in
  `.anchor_errors` — exactly the channel the contract reserves for
  non-integrity failures, never in `.reasons`.
Pinned by the new tests: mixed park+malformed raises JIE with
`reasons == ("anchor_head_not_in_chain",)` and
`anchor_errors == ("ship: anchor_malformed",)`; pre-settlement park
plus a post-settlement returned error stays plain `AnchorError`
(the pre-settlement park itself is neither upgraded nor repeated).

### F3 — PASS: the no-park-target raise is untouched
The pre-settlement raise (tx park reasons present, zero non-terminal
transactions → `JournalIntegrityError`) is in the untouched region
and fires, as before, only on initial-verdict tx park reasons.
Returned non-park reasons cannot reach it: they are not park reasons
by construction (F2). The post-settlement plain `AnchorError` with
`outcomes == ()` when there were no settlements (new test
`test_post_returned_error_with_no_settlements_raises`) is a distinct,
pre-existing surface — the post-settlement `if new_park:` raise was
already unconditional on settlement count for the park/exception
channels; cycle 32 only extends which evidence can enter it. It does
not borrow, weaken, or duplicate the no-park-target raise.

### F4 — PASS (safety-positive): limits hold, direction is fail-closed
- Previously a mid-recovery swap to a malformed/missing anchor was
  silently discarded; now it raises. No new silent path is created.
- Any non-park returned string — including an unknown/future reason —
  is surfaced as an operator error (pinned by
  `test_post_returned_unknown_reason_is_operator_error`). That matches
  the pre-settlement classification in the same method (everything not
  in the park set is operator error) and errs toward raising, not
  passing. Residual limit, unchanged from pre-settlement: a future
  reason intended as integrity evidence but not yet added to
  `ANCHOR_PARK_REASONS` would be misrouted to the operator channel —
  but it would still raise, not pass silently.
- Dedup is per anchor against that anchor's own initial verdict
  (`r not in ship_reasons` / `r not in tx_reasons`); a reason seen on
  the other anchor does not suppress it (pinned). Only identical
  repeats on the same anchor are suppressed, so no new failure can be
  masked by an unrelated anchor's earlier failure. Within-run
  `dict.fromkeys` dedup prevents duplicate `anchor_errors` entries.
- Settlements already journaled stand in both raise branches and ride
  on `.outcomes`; the change adds no writes, no anchor advancement,
  no lock, and no prevention claim — detection only, as before.
- The same-file guard still suppresses the entire post-settlement
  block (`if not same_path_error and ...`), so returned reasons
  cannot manufacture a raise in the same-file wiring-error case.

### F5 — LOW / FIX: stale pin count in the contract (created by this cycle)
`docs/RECOVERY-CONTRACT.md` L166–167 still says the pin file runs
"(58 tests)". This cycle adds 10 tests to that exact file; it now
runs **68 tests** (verified above). Update 58 → 68 in the same doc
this cycle already edits, or the contract's verification command
understates its own pin.

### F6 — LOW / FIX: "The two raises" lead sentences are now incomplete
The lead text of item 2 (L84–88) still describes `.anchor_errors` as
carrying "any accompanying EXCEPTION-path load failures" and the plain
raise as "a new exception-path load failure alone". After cycle 32
both statements are true but incomplete: returned non-park reasons
also land in `.anchor_errors`, and a returned reason alone also
raises plain `AnchorError`. The new "Closed (cycle 32)" paragraph
that follows states the full behaviour correctly — its claims were
checked line-by-line against the code (per-anchor dedup against the
initial verdict; label `"<source>: <bare reason>"`; plain
`AnchorError` when it is the only change; `.anchor_errors` when a
park reason accompanies it; only identical repeats suppressed) and
are all accurate. Harmonise the lead sentences to match (e.g.
"exception-path or returned") so a reader who stops before the
Closed paragraph is not left with the pre-32 model.

### F7 — Checked, no finding: non-claims and the open-item listing
Searched `docs/RECOVERY-CONTRACT.md` for the post-settlement open
item / gap listing:
- The old "**Gap:**" paragraph under "The two raises" is gone,
  replaced by the "Closed (cycle 32)" text — correct, the gap is
  closed by this change.
- "Open items carried from this contract" (L229+) does **not** list
  the post-settlement returned-reason gap — correct; nothing stale
  is carried forward as open, and no still-open item was dropped
  (production recovery caller, non-`[]` surface choice, pin-store
  head anchoring, pin-directory loss, operator-auth channel,
  concurrent actors all remain).
- Limits/non-claims remain accurate after the change: "Post-settlement
  re-verification detects only the changes listed in 'The two raises'
  — it does not prevent a swap, and settlements stand" (L211–213)
  still holds, with the list now correctly including returned
  reasons via F6's paragraph; "Recovery NEVER advances either
  anchor" still holds; the `JournalIntegrityError` "Known gaps"
  (no content validation of `outcomes`/`anchor_errors`, mutability,
  no pickle round-trip of a non-empty `anchor_errors`) are unaffected
  — the new mixed test asserts `.anchor_errors` content but does not
  round-trip it, so that gap statement stays true.
- "Silent-`[]` holes" bullet still holds for its stated cases:
  carrier-less pre-settlement operator-error evidence still returns
  `[]` (an identical post-settlement repeat is deduped/suppressed,
  pinned by `test_post_returned_same_reason_pre_and_post_no_raise`),
  and same-file / ship-only-park carrier-less cases are untouched.
  The cycle narrows the hole only for genuinely new post-settlement
  evidence, which the bullet does not claim returns `[]`.

## Summary for reconciliation
Code: SHIP on safety/limits — no pre-settlement, park, or
no-park-target change; fail-closed extension of an existing surface;
all contract non-claims verified still accurate. Overall verdict is
FIX solely for the two doc items F5 (58 → 68) and F6 (harmonise the
"The two raises" lead with the Closed paragraph), both in
`docs/RECOVERY-CONTRACT.md`, both trivial, neither requiring a code
or test change.
