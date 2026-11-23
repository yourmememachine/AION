# Cycle 23 — War-room RE-REVIEW rev-r1 (fix round)

Lens: my round-1 findings F1–F4 against the fix round
(working tree, uncommitted). Method: read the new
`CeremonyConsumptionLedger._load` / `_recorded_depth`,
`check_head` supersede narrowing, and
`CeremonyAuthorisationLedger._load` in `trust/ledger.py`;
read `CrossEntryLineageTests` and the re-pinned
`test_coherent_recovery_entry_loads` in
`tests/test_trust_consumption_schema_v2.py`; re-ran the
mandated spot-check suites (schema-v2 + ceremony
consumption: 43 tests OK; plus ceremony-consume /
signing-pin-ceremony / signing-ceremony-recovery: 119
tests OK — no regression in the properties verified in
round 1); ran a 26-probe battery of hand-hashed literal
journals and live-ledger appends.

## Verdict: FIX — score 0.86

F2, F3, F4 are fully discharged, and F1's core is
discharged — every round-1 probe (P2/P3/P4) is now
corrupt at load, wrong-order and forward references are
refused, and the v1/v2 boundary arithmetic is exact in
both directions. One residual in F1's own class remains:
the cross-entry check grounds a recovery on ANY earlier
matching entry, not on its lineage predecessor, so
forked and non-adjacent lineage loads. It is the same
defence-in-depth tier as F1 (unreachable through the
append path, gates still fail closed), and it has a
one-condition strengthening that closes it exactly.

---

## F1 — DISCHARGED in core; one residual (MEDIUM-LOW)

Implemented as specified: in `_load`, a v2 recovery must
name, via `recovery_of`, an earlier entry (v1 or v2) with
the same old→new pair whose `_recorded_depth` is exactly
depth − 1. Verified by probe:

- P2 (lone recovery, depth 2, ghost binding) → corrupt.
- P3 (recovery for a different pair, ghost binding) →
  corrupt.
- P4 (depth jump 0→2 naming the primary) → corrupt.
- Wrong lineage order (depth-2 recovery naming the
  depth-0 primary instead of the depth-1 recovery) →
  corrupt.
- Forward reference (recovery naming a later entry) →
  corrupt.
- Boundary arithmetic: v1 pair ×2 → v2 recovery depth 2
  naming the second v1 entry LOADS (the pinned mixed
  transition; the middle entry being v1 is handled —
  `_recorded_depth` pair-derives v1 depths per entry);
  v1 pair ×1 → v2 recovery depth 2 is corrupt; v1 pair
  ×1 → v2 recovery depth 1 loads.
- Valid primary→recovery→recovery chains load, recorded
  depths [0, 1, 2].

### Re-pin judgment: `test_coherent_recovery_entry_loads`

Sound. The pre-existing test pinned a LONE recovery
entry as "coherent" — that shape is exactly round-1
probe P2, which F1 required to be corrupt; the pin
could not survive the fix it named. The re-pin replaces
it with a full primary→recovery→recovery chain and says
so in its comment. This is a correction of a pin that
encoded the bug, not a weakening to fit the code.

### Residual R1 — lineage is checked as a DAG, not a chain

The grounding test is `any(earlier …)` over all earlier
entries. Probes that LOAD today (hand-hashed journals):

- Branch: [primary P, recovery R1 (d1, of P), recovery
  R1b (d1, of P)] — two depth-1 recoveries of one burn.
- Branch + depth 2: [P, R1, R1b, R2 (d2, of R1b)] — the
  pair is recorded consumed FOUR times while the head's
  recorded depth reads 2, against the class docstring's
  "consumable at most 1 + MAX_RECOVERY_DEPTH times".
  Same shape across the boundary: [v1, v1, v2 d2, v2 d2]
  loads (4 consumptions).
- Branch at the boundary: [v1 ×2 (depths 0, 1), v2
  recovery d1 naming the FIRST v1 entry] loads.
- Non-adjacent grounding: [P (pair X), primary Q
  (pair Y, ahead), recovery of P (d1)] loads — and its
  head is the X recovery, so `head_target()` returns a
  target BEHIND Q's already-consumed movement: the
  loaded journal's head is not monotonic in sequence,
  contradicting the "authoritative monotonic consumption
  head" claim, and head-rule checks against that snapshot
  treat Y's candidate as merely "ahead".
- Duplicate authorisation_id: load never checks
  uniqueness, so `recovery_of` can ground ambiguously
  via a second entry carrying the same id (append
  enforces single-use; load does not).

Why this is still only defence-in-depth: the append
path cannot write any of these shapes — `_derive_lineage`
returns "recovery" only when the bound burn IS the
current head entry, so every appended recovery names
`entries[-1]`, its immediate predecessor, with the
head's pair and depth + 1 (cycle-22 v1 recoveries were
likewise written only against the burn at head). Both
gates fail closed on the forked shapes (head depth is
what 5b/consume consult, and it never exceeds the cap).
But F1's premise was that load is the coherence check
for journals the append path didn't write, and a forked
lineage is exactly a coherence failure of that class.

Cheap exact fix: require the grounding entry to be
`entries[index - 1]` — authorisation_id equal to
`recovery_of`, same pair, recorded depth == depth − 1 —
and refuse a duplicate `authorisation_id` anywhere in
the journal at load. Adjacency is an invariant of every
append-reachable history (argued above), so this breaks
no legitimate journal; it closes every probe in this
section at once.

## F2 — DISCHARGED, extension endorsed

- `burned_unadopted` exclusion: `_derive_lineage` now
  returns the never-written ("unrecoverable", "", 0)
  marker for a burned_unadopted envelope that does not
  validly match the head burn, and `check_head` refuses
  it at every candidate position (empty journal included).
  Probe P7 re-run: a burned_unadopted envelope with
  candidate ahead of the head now raises
  HeadRegressionError instead of landing as a primary.
- Hash binding in BOTH journal roles: the supersede
  branch collects every recorded hash for the old pin's
  seq — from entries where it is a `new_cycle_seq`
  (bound to `new_payload_hash`) AND from entries where
  it is an `old_cycle_seq` (bound to `old_payload_hash`)
  — and refuses when the claimed hash matches none.
  Probe P8 re-run (fabricated hash at seq 47, the head's
  new seq) → HeadRegressionError. Extension probe
  (fabricated hash at seq 41, the head entry's OLD seq,
  candidate ahead) → HeadRegressionError.
- Extension judgment: correct and necessary. My round-1
  fix text said "when old_seq equals any entry's
  new_cycle_seq, OR the head entry's old_cycle_seq"; the
  fix seat generalised the second clause to every
  entry's old seq. That is strictly more faithful to the
  intent (the journal's knowledge of a seq's hash does
  not stop at the head), it cannot refuse a genuine
  supersede (a real old pin's hash IS the recorded one),
  and the two named residuals (unrecorded seq unchecked;
  resurfaced-pair stall, r2-F4) are stated in the
  docstring rather than hidden.
- No liveness regression: supersede with the CORRECT
  recorded hash for a behind-head seq still lands as a
  primary (probe), and the consume / pin-ceremony /
  recovery suites (119 tests) stay green.

## F3 — DISCHARGED

`_load` counts v1 pairs and refuses a third occurrence
of any v1 pair with CorruptLedgerError. Probe: v1 pair
×3 → corrupt; v1 pair ×2 still loads and derives depth
1; a v2 pair occurring three times as a coherent chain
still loads (the cap counts v1 occurrences only, as
specified — v2 multiplicity is lineage-checked, subject
to residual R1 above).

## F4 — DISCHARGED

`CeremonyAuthorisationLedger._load` now validates the
v2 `recovery_of` shape: "" or a 64-char lowercase hex
authorisation id; anything else is corrupt. Probes:
garbage string → corrupt; uppercase hex → corrupt;
short hex → corrupt; "" and a 64-char lowercase hex id
load. Shape-only is the maximum this journal can check
at load (its entries carry no reason field to bind
against), so this closes F4 as far as the format
allows; the round-1 observation that the binding's
semantic check lives at consume stands and is unchanged.

## Fix list (bounded, one item)

1. F1-residual R1: in `CeremonyConsumptionLedger._load`,
   ground a v2 recovery on its IMMEDIATE predecessor
   only (`entries[index - 1]`: authorisation_id ==
   recovery_of, same pair, recorded depth == depth − 1),
   and refuse duplicate `authorisation_id`s at load.
   Add pins: branched recoveries, non-adjacent recovery,
   and duplicate-id journals are corrupt; the existing
   coherent-chain and mixed v1/v2 pins must stay green.

---

# Targeted second re-review (rev-r1) — adjacency strengthening

Method: read the changed `_load` grounding block, the
duplicate-id scan, and the `append_consumption` defensive
guard in `trust/ledger.py`; read
`ImmediatePredecessorGroundingTests`; re-ran the mandated
suites (`tests.test_trust_consumption_schema_v2` +
`tests.test_trust_ceremony_consumption`: 47 tests OK;
schema-v2 alone 35 tests OK, incl. the 4 new pins); ran an
11-probe battery of hand-hashed literal journals and live
append-path histories.

## Verdict: FIX — score 0.90

The assigned residual R1 is FULLY DISCHARGED — the
strengthening is exactly as prescribed and every boundary
case behaves correctly. One new residual in the same
load-coherence class (R2, below) keeps this at FIX; it is
narrower than R1 and has a one-condition fix.

## R1 — DISCHARGED (all probes)

- Grounding is now `entries[index - 1]` only:
  authorisation_id == recovery_of, same pair,
  `_recorded_depth(entries, index - 1) == depth - 1`.
- Original branch probes now corrupt: [P, R1 d1, R1b d1];
  [P, R1, R1b, R2-of-R1b]; [v1, v1, v2 d2, v2 d2];
  [v1 ×2, v2 d1 naming the FIRST v1 entry].
- Non-adjacent grounding corrupt (the new pin's
  [P, R1, X-different-pair, R2-of-R1] shape and variants).
- Duplicate authorisation_id anywhere → corrupt at load,
  checked before lineage, so an ambiguous grounding id is
  refused outright.
- Recovery at index 0 → corrupt (`index > 0` guard).
- v1 predecessor with pair-derived depth is exact in both
  directions: v1 first occurrence (depth 0) grounds a v2
  d1 naming it — LOADS; v1 SECOND occurrence (depth 1)
  grounds a v2 d2 naming the second v1 entry — LOADS;
  d2 naming the first v1 while the predecessor is the
  second, and d1 naming the second v1 (predecessor depth
  1 ≠ 0), both corrupt.
- No append-reachable history is wrongly refused, checked
  against `append_consumption`'s derivation (the recovered
  burn is always the head at consume time, hence always
  the immediate predecessor of the landed recovery):
  live appends of a d2 recovery onto a literal v1×2 journal
  (bound to the second v1 entry) and of a recovery onto an
  interleaved primary→primary history both land and reload
  cleanly in a fresh instance.
- r6-N1 guard verified by reading: `append_consumption`
  raises LedgerError when the derived kind is outside
  {primary, recovery}, before any `_append` — the
  "unrecoverable" marker can never be written even if a
  future `check_head` change lets it through.

## Residual R2 — a v2 primary can re-root an already-consumed pair (MEDIUM-LOW, same tier as R1)

Primaries carry no load-time pair check, so a hand-hashed
journal LOADS today:

    [P (pair X, d0), R1 (d1), R2 (d2), P2 (pair X again,
     primary, d0), R1b (d1, of P2)]

— pair X is recorded consumed five times (a second full
chain is admissible: six at the cap), against the class
docstring's "consumable at most 1 + MAX_RECOVERY_DEPTH
times". Every recovery in the shape is correctly
adjacent-grounded; the hole is the second ROOT. It is
append-unreachable for the same reason R1's shapes were:
`check_head` refuses a candidate equal to the head target
(AlreadyConsumedError) and any candidate behind the head
(HeadRegressionError), so an exact-pair primary can never
be appended once its pair has occurred. Same
defence-in-depth tier as R1: load is the coherence check
for journals the append path did not write, and pair
multiplicity was F3's concern for v1 — its v2 analogue was
deferred to lineage checking, which roots evade.

Cheap exact fix: in `_load`, a v2 primary whose exact
old→new pair occurs in ANY earlier entry (v1 or v2) is
corrupt — a primary must be the first occurrence of its
pair. No append-reachable history violates this (argued
above), and it caps every pair at one coherent chain of
1 + MAX_RECOVERY_DEPTH entries.

## Fix list (bounded, one item)

1. R2: in `CeremonyConsumptionLedger._load`, refuse a v2
   primary whose pair has occurred earlier in the journal.
   Add a pin: the re-rooted-pair journal above is corrupt;
   the existing coherent-chain, mixed v1/v2, and
   supersede pins must stay green.

---

# Final targeted re-check (rev-r1) — R2 re-root fix

Method: read the new primary branch of
`CeremonyConsumptionLedger._load` in `trust/ledger.py`
and `PrimaryReRootTests` in
`tests/test_trust_consumption_schema_v2.py`; re-ran
`tests.test_trust_consumption_schema_v2` (38 tests OK,
incl. the 3 new pins); ran a 9-probe battery of
hand-hashed literal journals.

## Verdict: SHIP — score 0.95

R2 is FULLY DISCHARGED. The fix is exactly the bounded
condition prescribed: a v2 primary whose `_pair_of`
(4-tuple old seq/hash → new seq/hash) equals any earlier
entry's pair — v1 or v2, primary or recovery — raises
CorruptLedgerError at load.

- Original R2 probe now corrupt: [P X, R1, R2, P2 X,
  R1b] — the second root is refused at P2, before R1b is
  even considered. The coordinator's pins also pass:
  immediate second primary corrupt; re-root after a full
  chain corrupt; primary of a NEW pair after a chain
  loads.
- Boundary probes (this re-check): v1 primary + v2
  primary of the same pair → CORRUPT (the check scans
  ALL earlier entries, not only v2 ones, so the mixed
  transition cannot smuggle a re-root). v2 primary of a
  pair that occurred only as a v1 pair twice → CORRUPT.
  Non-adjacent re-root [P X, P Y, P2 X] → CORRUPT.
  Re-root whose last earlier occurrence is a recovery
  [P X, R1 X, P2 X] → CORRUPT.
- Controls still load, so nothing legitimate is refused:
  v1 ×1 + v2 recovery d1 naming the v1 entry; v1 ×2 + v2
  recovery d2 naming the second v1 entry; v1 pair + v2
  primary of a NEW pair; the coherent chains and mixed
  pins in the suite.
- No append-reachable history is refused — argued from
  `check_head`: for a second primary of an already-
  occurred pair, the candidate IS that pair's target, so
  against the current head it is either AT the head
  target (AlreadyConsumedError, or the head is a recovery
  of the same pair, whose candidate also equals it) or
  BEHIND the head (HeadRegressionError; appended primary
  targets strictly advance, recoveries repeat the head
  target, so an earlier pair's target never exceeds the
  head seq). Supersede cannot rescue it: supersede
  requires a candidate STRICTLY AHEAD of the head, which
  the same pair's target is not. And a primary of a pair
  whose earlier occurrence was a RECOVERY is impossible
  on the append path: a recovery is derived only against
  the head burn of the same pair (`_derive_lineage` /
  `match_head_burn`), which inductively traces to that
  pair's primary — so the "earlier occurrence is only a
  recovery" case has no append-reachable witness either,
  and the load check refuses it regardless.
- Scope note: pair identity is the exact 4-tuple used by
  `_pair_of` everywhere (F3's v1 cap included); a primary
  at the same seqs with a different hash is a different
  pair, not a re-root, and full `check_head` replay at
  load was never this bounded class. No further gap in
  the R1/R2 load-coherence class was found.
