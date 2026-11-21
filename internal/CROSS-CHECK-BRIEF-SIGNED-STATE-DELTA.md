# Cross-check brief — signed state snapshots, delta round (re-review)

You previously reviewed `signing/state_snapshot.py` (signed
snapshots of the core loop state and the calibration log) and
returned FIX. This brief covers ONLY what changed in response to
the combined internal + external findings, the demonstrations,
and the updated declared limits. The original brief's design and
claims are unchanged except where this delta says so. Judge the
fixes on the code; try to refute them.

## What the first round found (all seats converging)

- The payload builder validated almost none of the facts it
  MACed, so a hand-built envelope carrying signer-impossible
  facts (schema 999, inconsistent cycle fields, garbage
  timestamps) verified standalone.
- Snapshot chaining was carried data, never verified; the pin
  was a sequence floor with no successor continuity.
- The anti-backdate check (`signed_before_state`) fired only
  when the caller supplied the state bytes, though the envelope
  itself carries the timestamp it needs.
- The state parser validated `completed_at` only on the last
  history entry.
- Verification could raise raw TypeError/ValueError on
  untrusted field types instead of returning reason strings.
- Cross-file capture consistency (state + calibration read as a
  pair that coexisted) was a documented caller duty, not code.
- Empty calibration bytes (`b""`) and `None` (unbound) were two
  spellings of nearly the same claim.

## What changed

1. **Payload re-derivation is now a complete validator.** Every
   attested fact is validated inside the payload builder — the
   one chokepoint shared by signing, verification and envelope
   reconstruction: schema must be the integer 1; sequence/length
   fields must be non-bool integers in range; `cycle_seq` must
   equal the last history cycle (and 0 iff history is empty);
   `last_item_id` emptiness must agree with history length;
   timestamps are normalised and parsed; a `signed_at` earlier
   than the state's last completed cycle (minus the 300 s skew)
   is refused in the builder itself, so it fires on every path,
   not only when state bytes are supplied.
2. **Chaining is verified where a single pin supports it.** A
   caller may supply `expected_prev_snapshot_hash` (checked
   directly), and a pin's immediate successor must chain to the
   pin (`chain_discontinuity` otherwise). The pin is compared
   against the RECOMPUTED payload hash, is strictly shaped
   (exact allowed keys, non-negative sequence, hex hash), and
   may additionally bind `key_id` / `signer_id`. Declared limit,
   unchanged and now stated in the module docstring: snapshots
   more than one sequence past a pin are NOT chain-checked, and
   a chain alone does not establish completeness — omitted
   intermediate snapshots are invisible without a trusted
   checkpoint.
3. **Verification never crashes on untrusted input.** The
   payload re-derivation and hash recomputation sit inside a
   guard that converts malformed fields (wrong types, non-finite
   floats, unserialisable values) into a `malformed_payload`
   reason.
4. **Capture protocol is code.** `sign_state_files` reads state,
   reads calibration, re-reads state, and refuses if the state
   bytes changed. Residual race (a calibration write racing in
   the other order) is stated in the docstring. A strict wrapper,
   `verify_snapshot_for_state`, requires every binding (state
   bytes, calibration bytes, pin, signer pin); bare verification
   remains an envelope-only check and is documented as such.
5. **Parser completeness.** Every history entry's `completed_at`
   is validated, and the sequence must be non-decreasing.
   `state_hash_for` enforces the same size cap as the parser.
   Empty calibration bytes are refused at signing; `None` alone
   means unbound.
6. **Documentation corrections.** The docstring now states: the
   pin storage contract (outside the rollback domain, advanced
   only after a verification returns no reasons, never
   reconstructed from the snapshot being verified); clock trust
   as an external dependency (300 s skew is policy, not proof);
   a snapshot proves key-holder-GROUP membership, not individual
   authorship; replay inside the TTL is allowed unless the pin
   has advanced; a snapshot is a freshness-bounded attestation
   (≤48 h), not archival proof; the `now` parameters are test
   seams that production wrappers must never accept.
7. **Live-state test defect found and fixed after the first
   round.** The module test that signs the REAL loop state
   hard-coded its signing instant; when the next cycle recorded,
   the instant fell before the state's last completed cycle and
   the (correct) anti-backdate guard refused. The guard was left
   untouched; the test now derives its instant from the live
   file, and two tests pin the refusal direction and the exact
   skew boundary against the real file and a fixture.

## Not adopted (recorded as open limits, not closures)

- A pin persistence/recovery ceremony and an enforceable atomic
  multi-file generation protocol: deployment machinery beyond
  this module's scope.
- Chain completeness beyond the immediate successor of a pin
  (see item 2's declared limit).

## Demonstrations to reproduce or refute

- Hand-build an envelope with schema 999, or `cycle_seq`
  inconsistent with `last_cycle_id`, or a garbage
  `last_completed_at`, MACed correctly with the key → standalone
  verification returns `malformed_payload`, never a pass.
- Present a pin's immediate successor whose `prev_snapshot_hash`
  does not equal the pin's payload hash → `chain_discontinuity`.
- Feed verify an envelope whose fields have hostile types
  (float sequence, bool length, list signer) → reason tuple,
  never an exception.
- Sign with `calibration_bytes=b""` → refusal; with `None` →
  succeeds with the record explicitly unbound, and strict
  verification with `require_calibration` reports it.
- Mutate the state file between the two reads of
  `sign_state_files` (test seam `_reader`) → refusal.
- Full suite at this delta: 1077 tests, all passing
  (2 live-deployment skips in their by-design consumed state).

Return: verdict (SHIP/FIX), confidence, findings ordered by
severity with file references.
