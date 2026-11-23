# Cycle 22 — Re-Review R3 (seat rev-r3, blind)

Re-review of the fix round for `signing/pin_store.py` +
`tests/test_signing_pin_store.py`, against my first review
(review-r3.md, FIX 0.70, findings F1/F2/F4). No other seats'
re-reviews read. Production code and tests not edited;
counterexample probes were re-run from /tmp only, using
records genuinely minted through `reanchor_pin` via the test
suite's own fixture (no hand-MACed records).

**Verdict: SHIP — score 0.96**

## F1 — CLOSED (old-side binding)

`adopt` now re-reads the document under the flock and calls
`verify_ceremony_record` with
`expected_old_pin=<pin re-read under the lock>` and
`expected_new_pin=<record target>`; any reason refuses before
serialising. Re-ran my counterexamples against current code:

- **P1 (genesis with-pin):** REFUSED — "genesis adoption
  requires a no-pin ceremony record (old pin absent)"; no
  file created, `read_all` still `(None, ())`.
- **P2 (splice, seq-3-bound record onto seq-1 store):**
  REFUSED — `['pin_context_mismatch']` from the context-bound
  verification; bytes unchanged, store still loads
  `(pin1, (rec1,))`.

## F2 — CLOSED (never write what the load would refuse)

`adopt` now refuses an already-ceremonied target and runs
`_check_consistency(new_pin, prospective_history)` before
serialising. Re-ran my counterexample plus two isolating
variants:

- **P3 (re-adopt genesis head record at its own target):**
  REFUSED; bytes unchanged; store still loads clean and
  remains adoptable (test_14 also asserts this).
- **P3b (re-adopt a non-genesis head record, old=pin1 →
  pin5, at pin5):** REFUSED (`pin_context_mismatch` — the
  replayed record's old side no longer equals the pin under
  the lock); bytes unchanged, loads clean.
- **F2-isolated probe (new):** a genuine record old=pin5 →
  pin7 whose context binds CLEAN but whose `evidence_hash`
  duplicates an existing history record's (minted with an
  empty history view so minting could not see the clash).
  Neither F1 nor the already-ceremonied-target check can
  catch this one — the prospective `_check_consistency`
  refused it alone: "pin store history reuses an evidence
  hash"; bytes unchanged, store loads clean. This proves
  the consistency layer independently, not just as a
  passenger on F1.

Note: the already-ceremonied-target refusal is largely
shadowed by the F1 context check for genuinely minted
records (a replayed record's old side almost never equals
the current pin). It is harmless defence-in-depth, not a
defect; the load-bearing F2 layer is the prospective
consistency check, proven above.

## F4 — CLOSED (message)

`_check_consistency` now raises "pin does not match the
history head; the combined document is internally
inconsistent" — the unconditional refusal and the message
now describe the same condition. (The crash-test section
header in the test file also now states the invariant
precisely — whole old or whole new generation — which was
my F3 docstring note.)

## Coordinator ruling — genesis SHAPE rule: SOUND, upheld

The shape rule admits at genesis any record whose old side
is absent and refuses any with-pin record, replacing a
reason whitelist (`initial_anchor`/`lost_pin` only).
Judged on my own probes:

- **It does not reopen P1.** Extra probe: a WITH-PIN
  `burned_unadopted` record (old_seq=3, the either-shape
  reason in its with-pin form) is REFUSED at genesis by the
  same shape check. The refusal is reason-blind in both
  directions — every with-pin record is out, whatever its
  label.
- **It admits the genuine no-pin shapes the whitelist
  dead-ended.** test_15: no-pin `burned_unadopted` creates
  the store and loads clean. My extra probe: no-pin
  `corrupted_pin` — also excluded by the two-reason
  whitelist — likewise admitted and loads clean.
- **Why shape is the right invariant:** the genesis defect
  in P1 was never the reason label; it was a record
  *asserting a predecessor* (seq 3) being installed as the
  first entry of a store that never held that pin — a false
  continuity claim. A no-pin record asserts no predecessor,
  which is exactly true at genesis; there is no foreign old
  side to splice and no prior history to contradict. The
  explicit shape check and the context-bound verification
  (`expected_old_pin=None` mechanically requires
  old-absent) enforce the same invariant twice.
- **No new trust assumption.** One caveat I checked:
  `verify_ceremony_record`'s own docstring states MAC-only
  verification does not prove a burn existed for a
  `burned_unadopted` record (burn linkage runs through
  `authorisation_id` → issuance/consumption journals). But
  that is equally true of the whitelist's reasons — a
  `lost_pin` label is not proven by the record MAC either.
  Every no-pin record rests on the same issuance proof:
  key-holder MAC plus the authorisation `reanchor_pin`
  consumed exactly once before constructing the record.
  The whitelist conflated an unprovable-at-this-layer label
  with the mechanically checkable shape, and in exchange
  for no added assurance it dead-ended real recovery: a
  genesis ceremony consumed but never adopted (store file
  never existed) is recoverable only by a no-pin
  `burned_unadopted`; under the whitelist that store could
  never be created by its true record at all. The
  whitelist's dead-end is the worse defect. Ruling upheld.

Residual (declared, non-blocking): a no-pin record minted
for a different deployment could be transplanted as another
store's genesis — but that is equally true of an
`initial_anchor` record under the whitelist, genesis has
no in-store state to falsify, and cross-deployment binding
lives in the authorisation/journal layer, not the store.

## Test run

`python3 -m unittest tests.test_signing_pin_store` — 18
tests, all OK (2.0s), run by this reviewer. Regression
tests 12/13/14 map exactly onto P1/P2/P3 and assert bytes
unchanged / store still usable; test_15 covers the shape
rule's positive case. The fix seat's mutation claim
(stripping the new layers fails exactly 12/13/14) is
consistent with my independent probes: each counterexample
refuses at a new layer, with the refusal messages naming
those layers.

## Bottom line

SHIP, 0.96. F1, F2 and F4 are closed with layered,
independently probed defences; the genesis shape rule is
sound, reopens no splice I found, and removes a genuine
recovery dead-end the whitelist would have kept.
