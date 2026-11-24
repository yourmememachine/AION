# Cycle 27 — War-Room Re-Review (fix round), seat re-review-tests

Reviewer: re-review seat (did not build this slice). Scope was
limited to the five findings listed for the fix round, read
against the current uncommitted tree. No other files were
edited and no commit was made.

Evidence run by this seat: `python3 -m unittest
tests.test_cycle27_journal_anchors -v` — **18 tests, OK**
(11.2s). (`pytest` is not installed in this environment; the
unittest run is the evidence.)

**Score: 0.95**
**Verdict: SHIP** — all five fix-round findings are closed by
discriminating tests that pass, each backed by the production
code path it pins. No remaining FIX item within this scope.

## Finding-by-finding verification

### 1. r3 INIT-discrimination gap — CLOSED

New class `IssuanceAnchorInitDiscriminationTests` adds both
cases r3 asked for:

- `test_issuance_init_refused_anchor_deleted_on_established_journal`:
  bootstraps, asserts the issuance journal has ≥1 entry,
  deletes the anchor, then calls with
  `AION_CEREMONY_ISSUANCE_ANCHOR_INIT=1`. Expects exit 3 /
  `anchor_refused` **and** asserts the anchor file still does
  not exist afterwards — so a re-pin is observable, not merely
  a refusal code.
- `test_issuance_init_refused_anchor_ahead_after_journal_rollback`:
  bootstraps, authorises (anchor advances), restores the
  pre-authorise home snapshot so the anchor is ahead of the
  journal (the test asserts `anchor["seq"] >
  len(issuance_entries())` before calling), then calls with
  INIT=1. Expects exit 3 / `anchor_refused` **and** asserts
  the anchor file's bytes are byte-for-byte unchanged.

These pin the observable behaviour at two layers, both read in
the tree: `verify_anchor` (`trust/anchoring.py`) returns
`("anchor_missing_established_ledger",)` for a missing anchor
on a non-empty journal and `("anchor_ahead_of_journal",)` for
the rolled-back case — never the bare `("anchor_missing",)`;
and `_load_ceremony_journal_anchor` (`trust/verifier_main.py`)
initialises only when `reasons == ("anchor_missing",)` and
INIT is set, with `initialise_anchor`'s own established-ledger
/ existing-anchor guards as the second layer. A re-pin in
either scenario would change the asserted file existence /
bytes and fail the test.

### 2. r3 production-gate gap for the supersession anchor — CLOSED

New class `SupersessionProductionGateTests` mirrors the
issuance pair, over a production env with every anchor
initialised at genesis and the ceremony seed configured:

- `test_production_without_supersession_anchor_refused`:
  deletes only `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`;
  a `sealed_eval` (i.e. any startup) expects exit 3 /
  `verifier_misconfigured`.
- `test_production_supersession_anchor_init_refused`: sets
  `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT=1`; expects exit 3 /
  `verifier_misconfigured`.

Both discriminate: the production helper is reached only
because the issuance path is still present, and dropping the
supersession branch's production requirement / INIT refusal
in `_load_ceremony_journal_anchor` would let both calls start
and succeed instead of refusing.

### 3. r1/r3 alias gap (supersession path == issuance path) — CLOSED

New class `SupersessionAnchorAliasTests`:
`test_supersession_anchor_equal_to_issuance_refused`
bootstraps, then sets
`AION_CEREMONY_SUPERSESSION_ANCHOR_PATH` to the issuance
anchor file and expects exit 3 / `verifier_misconfigured`.
Backed in code: the supersession call site in `_load_config`
passes the issuance path in `other_anchors`, and the loader
refuses any resolved equality with a listed other anchor as
`verifier_misconfigured`. Without that entry the same call
would surface as a kind-mismatch `anchor_refused`, so the
asserted code distinguishes the alias check.

### 4. Positive supersession anchor advance — CLOSED

New class `SupersessionAnchorPositiveAdvanceTests`:
`test_supersession_anchor_advances_on_successful_supersede`
runs the full flow (bootstrap, authorise, consume, authorise
the superseding envelope, approver approval, successful
`ceremony_supersede` via the client), asserts the receipt's
`supersession_seq == 1`, then asserts on the anchor file
itself: it exists, `load_anchor(...)["kind"] ==
"ceremony-supersession"`, `anchor["head"]` equals the
supersession journal's `head()`, and `anchor["seq"]` equals
the journal length. A supersede path that omitted the anchor
update would leave the anchor at its genesis pin and fail
the head/seq assertions.

### 5. r6 migration test — CLOSED

New class `IssuanceMigrationCeremonyTests` (fixture with
`anchored = False`):
`test_issuance_migration_first_pin_ceremony_on_established_journal`
builds an issuance journal with no anchor configured,
asserts ≥1 entry and no anchor file, then performs the
operator first-pin ceremony outside the verifier —
`initialise_anchor(journal, path, kind="ceremony-issuance",
recorded_at=NOW, allow_nonempty_ceremony=True)` — and
asserts the pin's kind, `seq == len(entries)`, and
`head == journal.head()`. It then invokes the verifier with
`AION_CEREMONY_ISSUANCE_ANCHOR_PATH` set: the call succeeds
(exit 0, no error), and afterwards the anchor has advanced
to `pinned["seq"] + 1` with head equal to the journal's new
head — i.e. startup verifies against the first pin and the
next issuance advances it, exactly the migration sequence r6
found missing. The test's docstring is honest about the
limit: the first pin blesses the journal's current history
as-is and cannot detect a rollback that happened before the
pin.

## Notes

- Test total for this module is now 18 (up from the 11 the
  first round reviewed); all pass in the run above.
- This re-review covers only the five listed findings. It
  makes no claim about the rest of cycle 27 or the full
  suite, which were outside this seat's scope.
