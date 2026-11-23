# Cycle 22 — Review R3 (seat rev-r3, blind)

Scope: WS3 pin store only — `signing/pin_store.py` and
`tests/test_signing_pin_store.py`, against DESIGN-FINAL R3 and
design-c §2/§8.1. Working tree on top of aeb6ef6, uncommitted.
No other reviewers' notes read. Production code and tests not
edited; counterexample probes were run from /tmp only, using
records genuinely minted through `reanchor_pin` via the test
suite's own fixture (no hand-MACed records).

**Verdict: FIX — score 0.70**

The atomic-write core is sound: single combined document, one
`os.replace`, loop.save() discipline matched line-for-line,
CAS under flock judged on a re-read under the lock, corrupt
files refused and never touched, caps enforced, verified load
real. But `adopt` does not bind the record's OLD side to the
pin it is adopted onto, and never consistency-checks the
document it is about to write. Three counterexamples below
were executed and all three succeeded against the current
code. Two of them write history the store's own verified load
accepts forever (silent audit falsification — the exact
defect class design-c §2.1 names); the third writes a
document its own load refuses forever (self-bricking through
a call that reported success).

## Findings

### F1 — MAJOR: `adopt` never binds the record's old side to the current pin

`signing/pin_store.py:386-396` — when a record is given, adopt
checks only `(record.new_cycle_seq, record.new_payload_hash)
== new_pin` and calls `verify_ceremony_record(record,
signing_key=...)` with NO pin context. Per that function's own
docstring (`signing/pin_ceremony.py:973ff`), context-free
verification "proves ISSUANCE only, not applicability to any
pin state"; the function already accepts
`expected_old_pin=` / `expected_new_pin=` and reports
`pin_context_mismatch` — adopt simply never passes them.

Executed counterexamples (genuine records, test fixture):

- **P2 (splice):** genesis at seq 1, then `adopt(pin5, rec5,
  expected_old_pin=pin1)` where `rec5` was minted with its old
  side bound to a seq-3 pin. Adopt succeeded; pin moved 1→5;
  the stored history now attests a ceremony *from seq 3* that
  never happened against this store, and `read_all` loads it
  clean — `_check_consistency` (pin_store.py:300) checks
  evidence duplication, forked targets and pin-vs-head, none
  of which see an old-side discontinuity. The falsified
  history is permanent and undetectable in-store.
- **P1 (genesis shape):** on a missing file,
  `adopt(pin5, rec5, expected_old_pin=None)` succeeded with
  `rec5.reason == "chain_gap_recovery"` and
  `rec5.old_cycle_seq == 3`. Design-c §2.4 / R3 require
  genesis to require an `initial_anchor` / `lost_pin`
  (no-pin) record; pin_store.py:365-372 checks only
  `record is None`. The genesis branch inherits the same
  missing old-side check (expected old side is None, the
  record's is seq 3).

Reachability honesty: today's `PinAdopter` flow passes only
records `reanchor_pin` minted against its captured pin, and
the CAS catches pin movement, so the honest in-tree caller
does not produce these today. But the store is the layer
design-c charges with discharging the preconditions
*mechanically* ("the store never persists a record it has
not itself verified" — pin_store.py:394-396 — is currently
true only in the issuance sense), and R3's
`adopt_returned(...)` recovery entry point takes a
caller-supplied (pin, record) pair: a pair recovered from a
different store/branch is precisely the input that splices.
Fix is small and local: verify with
`expected_old_pin=current_pin` (None at genesis),
`expected_new_pin=new_pin`, before writing.

### F2 — MAJOR: `adopt` writes a document it never consistency-checks — one successful call bricks the store

`signing/pin_store.py:384,398` — the idempotent no-op triggers
only when `record is None`. With a record whose target equals
the current pin (same seq, same hash), adopt falls through,
verifies the record (issuance only), appends it
(`history = history + (record,)`) and writes — with no call
to `_check_consistency` on the prospective document anywhere
in `adopt` (it is only called from `_validate_doc`,
pin_store.py:296, i.e. on read).

Executed counterexample:

- **P3 (self-brick):** re-adopting the store's own head
  record at its own target pin returned SUCCESS and wrote a
  document with a duplicate `evidence_hash`. Every subsequent
  `read_all` raises `PinStoreError` ("pin store history
  reuses an evidence hash"), and every subsequent `adopt`
  also refuses at its under-lock re-read — the store is
  permanently unusable, bytes frozen, recoverable only by
  operator ceremony/manual intervention. The same hole
  admits any prospective history `_validate_doc` would
  refuse (duplicate evidence from a record minted against a
  different history context; a second record for an
  already-ceremonied target — `_check_ceremony_history`
  refuses that at ceremony time, the store load's fork check
  does not catch same-seq+same-hash duplicates).

Fix: run `_check_consistency(new_pin, prospective_history)`
(plus an already-ceremonied-target refusal) before serialising
in `adopt`. A writer must never persist a document its own
verified load would refuse.

### F3 — MINOR: the four crash-point tests prove the exception-path invariant, not crash durability — and 10a's leftover assertion is vacuous

`tests/test_signing_pin_store.py` test_10a–10d. Judged
individually:

- **10a (temp write, /dev/full):** the patched `mkstemp`
  returns an fd on /dev/full and a path that is never created
  on disk, so the "no .tmp leftovers" half of
  `_assert_old_generation` passes trivially — partial-temp
  cleanup is not exercised here (10c does exercise it, with a
  real temp file). The old-generation assertion is real.
- **10b (file fsync):** patches `os.fsync` globally; valid
  only because the first fsync in the adopt path is the temp
  file's — correct today, brittle if any earlier fsync is
  added to the path.
- **10c (replace raises):** the strongest of the three
  pre-commit tests — real temp file, real cleanup, old
  generation intact.
- **10d (dir fsync after replace):** honestly named and
  asserts the correct commit-point semantics: new generation
  returned whole. But it asserts *visibility through the page
  cache*, not durability — after a power loss in the
  replace→dir-fsync window the rename itself may not be
  durable, and no unit test of this shape can show otherwise.

None of the four kills a process mid-write or simulates
power loss; they are exception-injection tests. That is
acceptable for this layer (rename atomicity is the actual
mechanism, and `_write_atomically` at pin_store.py:416-438
does match `core/loop.py` `save()` exactly: mkstemp in
target dir → write → flush → fsync → replace → dir fsync,
temp unlinked on failure), but the invariant they "prove"
should be stated as: *any exception at these four points
leaves a whole old or whole new generation observable* — not
crash-at-any-point in the power-loss sense. No code change
required; test-docstring precision only.

### F4 — MINOR (cosmetic): consistency message overstates its condition

`signing/pin_store.py:319-322` — a pin with
`pin.seq < head.seq` is refused unconditionally, but the
message says "pin sits behind the history head **with a
different hash**". Behaviour is the stricter (correct) one;
the message misdescribes it. Cosmetic only.

## What was checked and held

- **(a) Atomic adoption:** one combined `snapshot-pin.json`;
  `_write_atomically` matches `core/loop.py:310-327`
  discipline exactly, including temp-unlink-on-failure and
  the post-replace dir fsync whose failure is reported, not
  rolled back. No two-file ordering residue exists.
- **(b) CAS adopt:** flock is non-blocking exclusive
  (`PinStoreBusy` on contention, test_11), re-read and
  re-verification happen under the lock (pin_store.py:358ff),
  `expected_old_pin` mismatch → `PinMovedError` with bytes
  unchanged (test_04, including genesis-over-existing),
  non-regression guard refuses lower seq and same-seq
  different-hash, same-seq same-hash recordless adopt is a
  true no-op (bytes + mtime unchanged, test_05), record
  target binding and MAC verification happen before any
  write (test_06). The gap is only the old-side binding (F1).
- **(c) Genesis:** bare genesis refused (record required) —
  but see F1/P1: the record's genesis *shape* is unchecked.
- **(d) Corruption:** truncated JSON, wrong version, oversize
  all refused on read AND adopt with bytes left exactly as
  found (test_08); tampered history record and tampered pin
  refused with bytes untouched (test_07). No quarantine,
  rename-aside, repair or bootstrap-over path exists in the
  module. Strict JSON parsing (duplicate keys, non-finite
  numbers rejected) is a genuine strengthening.
- **(e) Verified load:** single parse for pin+history
  (FRESH-PIN, no caching — test_02), every record re-verified
  via `verify_ceremony_record` AND payload re-derivation in
  `ceremony_record_from_dict` (payload_hash must re-derive),
  duplicate evidence and forked targets refused (test_07),
  pin-behind-head refused. Note the load-side consistency
  set is exactly the one F2 says adopt must also enforce on
  write.
- **(f) Placement and caps:** `pin_dir` equal-to or inside
  `state_dir` refused at construction before any mkdir
  (pin_store.py:208ff, test_09; resolved paths, so symlink
  spelling does not evade it); 1 MiB cap enforced on read
  and on the serialised payload pre-write; 1000-record cap
  enforced on load and on append in adopt (pin_store.py:398ff).

## Test run

`python3 -m unittest tests.test_signing_pin_store` — 14 tests,
all OK (2.4s), run by this reviewer against the working tree.

## Bottom line

FIX, 0.70. The atomicity, CAS, corruption and caps work is
ship-quality; the store's verification at adopt time is
weaker than at load time, and that asymmetry is exploitable
with genuine records in both directions — silent history
splice (F1) and self-bricking write (F2). Both fixes are
small, local to `adopt`, and need regression tests in the
§8.1 style: genesis with a with-pin record refused;
old-side-mismatched record refused with bytes unchanged;
duplicate/already-ceremonied record refused at adopt with
the pre-existing file still loading clean.
