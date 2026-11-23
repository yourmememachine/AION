# Cycle 23 — War-room RE-REVIEW, seat rev-r3

Round-1 verdict: SHIP 0.92 (`review-r3.md`). Lens unchanged:
WS1 + WS5, Protected File question. Duty: confirm the fix round
(working tree, uncommitted) does not undermine round-1
conclusions, re-run the real-anchor tripwire, check the
`pin_adoption.py` docstring rewrite against the R1 hook
contract, and judge one new item (r6-F6 wrap).

**Verdict: SHIP — score 0.92 (unchanged)**

## Fix-round scope — as briefed, verified

File mtimes and diff inspection confirm the fix round touched
`trust/ledger.py`, `trust/pin_adoption.py`, tests, and the two
READMEs, and did NOT touch `core/loop.py`, `trust/shipcheck.py`,
or `trust/client.py` (all three retain their pre-fix-round
timestamps, 11:21/11:21/11:29, against 11:48–11:49 for the fix
files). Therefore round-1 sections (1) loop diff / exactly-once
/ deepcopy / exception placement, (3) `record_ship` pre-side-
effect hooked-loop refusal, (4) `anchored_record_ship` currency
check and tx-anchor advance, and (6) double-wiring are
literally unchanged code — those conclusions stand without
re-derivation. The protected-file reasoning in (2) is likewise
unaffected: no new protected path is touched by the fix round,
and the standing obligation (cycle 23's eventual recording must
carry `core/loop.py` as a protected violation) is intact.

## Tripwire — re-run by this seat

`python3 -m unittest tests.test_cycle23_ship_anchors
tests.test_core_loop_hook` — **17 tests, OK** (same count and
result as round 1). The real-anchor verification in round-1
section (5) therefore still holds against the live files: the
ship and ship-tx anchors remain current, and the tripwire's
head/seq equality assertions still pass. The `trust/ledger.py`
changes (load validation via `_allowed_entry_key_sets` /
`_load` overrides, supersede narrowing in `check_head`) are in
the ceremony consumption/signing journals, not the ship-ledger
path `shipcheck` anchors; they are fail-closed in direction
(stricter load acceptance, supersede never riding an invalidly
matching burned envelope, hash-bound supersede) and nothing in
them loosens a check round 1 relied on. WS5 conclusion stands.

## Docstring rewrite — hook contract wording undisturbed

The module-docstring rewrite in `pin_adoption.py` is scope
honesty only: it adds the `already_current` TTL qualification
and the "Honest scope" paragraph (live run against a byte copy,
real `state/` never adopted against, no production deployment).
It does not touch the R1 contract surfaces, which I re-read
verbatim:

- `pin_cycle_hook` docstring still states the entry is attached
  as `.cycle_entry` on `PinAdoptionBurned` /
  `PinAdoptionRefused` before re-raising, with the contract
  quoted unchanged: "cycle recorded, pin pending, alert".
- `run_one_cycle_and_pin` docstring still carries the same
  contract sentence and the double-wiring refusal wording.
- The hook body is unchanged: `except (PinAdoptionBurned,
  PinAdoptionRefused) as exc: exc.cycle_entry = entry; raise`.

## New item — r6-F6: authorise_pending append wrapped

In `_reanchor`, the step-(1b) `authorise_pending` journal
append is now wrapped: `except OSError as exc: raise
PinAdoptionRefused("authorise-pending journal append failed:
…") from exc`. Judged against the hook's `.cycle_entry`
contract: **correct, and it closes a real gap in that
contract.**

- **Typing is right.** The append sits BEFORE the authorise
  call (step 2): on failure no envelope has been issued,
  nothing has been consumed, nothing can be burned. That is
  exactly `PinAdoptionRefused`'s documented semantics
  ("nothing persisted"), and exactly NOT `PinAdoptionBurned`
  — a Burned typing here would falsely feed the
  `burned_unadopted` recovery machinery for a ceremony that
  never authorised.
- **Contract interaction is right.** Before the wrap, a raw
  `OSError` escaped `snapshot_and_adopt()` outside the hook's
  `except (PinAdoptionBurned, PinAdoptionRefused)` tuple, so
  `pin_cycle_hook` re-raised it WITHOUT attaching
  `.cycle_entry` — the alert path keying off the typed
  exceptions would have seen an untyped error with no cycle
  entry, silently breaking "cycle recorded, pin pending,
  alert" for this one failure mode. Now the failure enters
  the tuple: the hook attaches `.cycle_entry`, re-raises, and
  the loop's post-save propagation (round-1 section 1:
  cycle stays recorded, exception unwrapped by the loop)
  delivers the contract intact. The wrap also matches the
  function's existing convention — the authorise call's own
  failures are already normalised to `PinAdoptionRefused` in
  the immediately following block, with `PinAdoptionRefused`
  re-raised untouched.
- **No masking concern.** The journal is a detection aid,
  never authority; refusing the attempt when its FIRST
  (pre-authorise) line cannot be written is fail-closed and
  costs nothing — no consumption is stranded, and the next
  attempt proceeds as a fresh primary ceremony, consistent
  with the pending line's own documented semantics (a pending
  line proves nothing could have consumed). This is the
  opposite of the post-adoption "adopted"-line swallow
  elsewhere in the file, which is correct for the opposite
  reason (success already committed). The asymmetry is
  principled, not accidental.

## Conclusion

Nothing in the fix round undermines any round-1 conclusion;
the tripwire passes at 17/17; the docstring rewrite is
honesty-narrowing only and leaves the R1 hook contract wording
verbatim; and the one new item in my lens strengthens the very
contract I signed off on. The two minor observations from
round 1 (dual-stale-anchor path, protected-violation recording
obligation) remain open-but-non-blocking and untouched.

**SHIP, 0.92.**
