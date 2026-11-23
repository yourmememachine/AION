# Cycle 23 — War-room review rev-r1 (BLIND)

Lens: WS3 schema v2 correctness (DESIGN-FINAL R3 is the contract).
Baseline 59a656a, working tree as built. Method: read the R3 diff
in `trust/ledger.py` / `trust/verifier_main.py`, the new suite
`tests/test_trust_consumption_schema_v2.py` (21 tests, green),
the neighbouring ceremony suites (130 tests, green), and ran an
adversarial probe battery against literal hand-hashed journals
and live ledger objects (probes P2–P10, P21 cited below).

## Verdict: FIX — score 0.76

The core mechanism is right: the seam is behaviour-preserving,
monotonicity holds in both journals, lineage is re-derived
inside the retry loop from fresh entries, 5b and consume share
one depth derivation, the true-concurrency race lands exactly
one, and v1 hashes/anchors survive untouched. Two findings are
concrete, reachable weakenings that a fix round can close
cheaply (F1, F2); the rest are fail-closed residuals.

---

## F1 — MEDIUM — v2 lineage is validated only *locally* at load; cross-entry lineage incoherence loads and is trusted

`trust/ledger.py:825-862` (`CeremonyConsumptionLedger._load`)
validates each v2 entry in isolation: kind ∈ {primary,
recovery}, depth is a non-bool int, primary ⇔ depth 0 ⇔
recovery_of "", recovery ⇒ 1 ≤ depth ≤ 2 and recovery_of
non-empty. Nothing ties an entry to its predecessor. Probes
(hand-hashed literal journals, exactly as an intact-hash-chain
file would present):

- P2: a journal whose **sole** entry is
  `consumption_kind="recovery", recovery_depth=2,
  recovery_of="auth-ghost"` **LOADS**, and
  `derived_head_depth` returns 2 for a movement that was never
  primarily consumed. (The suite itself pins this shape as
  "coherent": `test_coherent_recovery_entry_loads`.)
- P3: `[primary X, recovery for a *different* old→new pair Y,
  depth 1, recovery_of="auth-ghost"]` **LOADS** — a recovery
  of a movement that is not the head it follows, bound to an
  authorisation that does not exist in the journal.
- P4: `[primary depth 0, recovery depth 2]` (depth jump,
  skipping 1) **LOADS**.

Why it matters: `derived_head_depth` (ledger.py:865) trusts a
v2 head's recorded depth blindly, and both gates (authorise
5b, consume) spend that trust. Through the verifier modes the
incoherent shapes are not writable today (check_head blocks
the appends that would create them), so this is
defence-in-depth, not a live bypass — but R3's load validation
was sold as the v2 coherence check, and the cap's integrity
now rests on a single recorded integer with no chain check.
Cheap fix: in `_load`, for each v2 recovery entry require
`recovery_of` == the authorisation_id of an earlier entry
with the same old→new pair and `recovery_depth` == that
entry's (recorded or pair-derived) depth + 1; for a v2
primary, require its pair not to duplicate the current
head-pair lineage. At minimum, a recovery entry at position 1
or whose `recovery_of` names no earlier entry must be corrupt.

## F2 — MEDIUM — the supersede exception in `check_head` is hash-blind for a behind-head old pin, and reclassifies recovery envelopes as primaries at the ledger level

`trust/ledger.py:1097-1112` (fix-seat supersede; it appears
nowhere in DESIGN-FINAL R3 — R3's exhaustion remedy is a
primary whose old pin *is* the head target, as the schema
suite's own exhaustion test constructs it). Two probes on a
live ledger with head = primary 41/a → 47/b:

- P8: a `chain_gap_recovery` envelope with
  `old_pin={41, "f"*64}` — a **fabricated old-pin hash** that
  matches no pin that ever existed — and candidate 52/c
  **LANDS**. Cycle-22 code refused any behind-head old pin
  with HeadRegressionError unconditionally; the new branch
  compares only `old_seq < head_seq` and, when the candidate
  is ahead, never looks at `old_hash` at all. This is
  reachable through the verifier modes: authorise validates
  the old pin's *shape* only (the verifier by design does not
  know the pin store), so consume is the only place this hash
  was ever checked against the journal. The journal now
  records a false old pin as fact and advances the head; the
  adopter then cannot adopt (its real pin ≠ recorded old),
  burning the movement into the recovery path. The information
  needed for the check is in the journal: 41/a *is* the head
  entry's recorded old pin. Fix: when `old_seq` equals any
  entry's `new_cycle_seq`, or the head entry's
  `old_cycle_seq`, require `old_hash` to equal the recorded
  hash for that seq; refuse otherwise.
- P7: a `burned_unadopted` envelope with candidate *ahead* of
  the head and old pin behind it **LANDS as
  `consumption_kind="primary", depth 0`** — `_derive_lineage`
  returns primary-shaped (match_head_burn fails on the
  candidate), and the supersede branch then waives the
  old-pin rule for it. Through the verifier this specific
  envelope is unissuable (5b binds candidate to the head
  target), so reachability is ledger-API only — but the
  ledger is the commit point whose docstring claims the head
  rules, and a recovery-intended envelope silently becoming a
  cap-exempt primary is exactly the class of reclassification
  R3 was written to eliminate. Fix: supersede must not apply
  when `signed.reason == "burned_unadopted"`.

The supersede rule itself (coordinator fix-seat, re-pinned in
`test_signing_pin_ceremony.py` / `test_trust_ceremony_consume.py`)
may well be the right liveness call — but as built it is
broader than its own docstring ("a NON-recovery consumption
whose old pin is BEHIND the head": P7 shows a recovery
envelope riding it, and P8 shows the hash is unchecked), and
it needs the narrowing above plus an explicit line in the
cycle record ratifying it against R3.

## F3 — LOW — the v1 "pair occurs at most twice" invariant is asserted, not enforced; pair-scan is exact only for verifier-reachable histories (proof below, plus the gap)

`trust/ledger.py:865-885` (`derived_head_depth`). Probe P6: a
v1 journal with the same pair **three** times **LOADS** (no
load check on pair multiplicity) and derives depth 2. All
downstream uses fail closed (5b refuses ≥ MAX, consume
refuses), so nothing unsafe lands — but the docstring's
"exact under cycles 21–22 history" is a load-bearing claim
with no enforcement behind it.

Exactness, by cases, for histories the verifier modes could
actually write (I checked the predecessors in git, not just
the claim):
- Pair once, head = that entry: it cannot be a recovery.
  Cycle 21 had **no `burned_unadopted` reason at all**
  (REASONS at aeb6ef6 = initial_anchor / chain_gap_recovery /
  lost_pin / corrupted_pin), and cycle 22's 5b + consume both
  required the burn at head with the identical old→new pair,
  so any cycle-22 recovery consumption is by construction the
  **second** occurrence of its pair. First occurrence ⇒
  primary ⇒ depth 0. ✓
- Pair twice, head = second: primary (0) + one-shot recovery
  (1) ⇒ derived 1. ✓
- Mixed transition: v1 pair-twice head (derived 1) grounds a
  v2 recovery at depth 2, and a v1 pair-once head grounds v2
  depth 1 — both verified in the re-pinned recovery suite. ✓
- The adversarial case the lens posed — a v1 recovery head
  whose pair occurs once because its primary is absent — is
  **not reachable** through the verifier modes in either
  cycle (above). It *is* constructible by direct ledger
  callers / synthetic histories, where v1's missing reason
  field makes it indistinguishable in principle. Accepted
  residual; the load check for pair ≥ 3 (P6) is the cheap
  half of this finding and should land with F1's fix.

## F4 — LOW — authorisation-journal v2 `recovery_of` is type-checked only

`trust/ledger.py:653-671`: any string loads — probe: a v2
issuance with `recovery_of="not-an-authorisation-id !!!"`
**LOADS**; a non-recovery issuance carrying a non-empty
binding, or a burned_unadopted issuance carrying "", would
load equally. (Non-strings are refused — probe with int →
CorruptLedgerError ✓.) Consume-side impact is fail-closed
(a bogus bound id mismatches the head burn → primary-shaped
→ AlreadyConsumedError), and R3 specified only the dual key
set + monotonicity for this journal, so this is within the
letter of the contract — recorded so the room knows the
issuance binding's load-side guarantee is "is a string",
nothing more.

## F5 — LOW / accepted-residual — the `recovery_of=None` legacy sentinel auto-binds any direct caller (and every v1 issuance) to whatever the head burn is

`trust/ledger.py:888-935` (`_derive_lineage`) and
`trust/verifier_main.py` consume step (6): a v1 issuance
entry's `.get("recovery_of")` yields None, and None means
"the head entry itself is the bound burn" — no issuance-side
proof is consulted. That is the correct backward-compat
behaviour for genuine cycle-22 issuances (their 5b *did*
prove the burn, one-shot), and for v2 issuances the verifier
threads the exact string, so the binding R3 requires is
enforced on the production path. But the ledger-level API —
the commit point — enforces no binding at all when the
argument is omitted, so R3's "issuance binding (load-bearing)"
is a verifier-mode property, not a ledger property. The
docstrings say this plainly; flagged so the ratification
record does not over-claim it.

---

## What I tried to break and could not (passes)

1. **Key-set seam (Q1)** — `HashChainJournal._allowed_entry_key_sets`
   (ledger.py:120) returns exactly `(frozenset(_ENTRY_KEYS |
   EXTRA_KEYS),)` by default, so ShipLedger, SigningLedger and
   ShipTxJournal (`trust/shiptx.py:392`, the fifth subclass —
   easy to miss) are byte-identical in acceptance. Only the two
   ceremony ledgers override. No other journal class changes
   behaviour; the 130 neighbouring tests stay green.
2. **Positional monotonicity (Q2)** — both ceremony `_load`s
   track `seen_v2` and refuse a later v1 entry; all-v1 and
   all-v2 journals load; v1→v2 mixed loads; v2→v1 is corrupt
   in both journals (suite-pinned and re-verified). Writes are
   monotonic by construction (appends are always v2), and
   `_save`'s freshness re-check goes through the overridden
   `_load`, so a non-monotonic on-disk state cannot be saved
   over silently.
3. **Local v2 value validation (Q3, the part that works)** —
   probes: depth as string → corrupt; depth as float 1.0 →
   corrupt (bool is explicitly excluded in code); depth −1 /
   3, primary with depth ≠ 0 or recovery_of ≠ "", recovery
   with depth 0 or empty recovery_of, unknown kind → all
   corrupt. Key-set exactness means a partial v2 entry (some
   lineage keys missing) cannot load at all.
4. **Retry-loop derivation (Q5)** — `append_consumption`
   (ledger.py:1116+) calls `self._reload()`, then
   `check_head`, then `_derive_lineage`, all on the same fresh
   `self._entries` per attempt; a `_save` freshness failure
   (CorruptLedgerError under flock) retries the whole loop, so
   the derivation is recomputed from the post-competitor
   entries — there is no path where a derivation computed
   against a stale head is what gets appended. Probe P9: four
   threads racing recovery appends bound to the same burn on
   separate ledger instances → **exactly one LANDS at depth
   1, three refuse AlreadyConsumedError**, journal holds
   exactly the primary + one recovery.
5. **5b depth refusal (Q6)** — verifier_main.py:2548-2557 uses
   the *same* `derived_head_depth` on a freshly constructed
   ledger's entries, refuses `>= MAX_RECOVERY_DEPTH` under the
   single `ceremony_recovery_unproven` code (no new oracle),
   before signing, and sets `recovery_of =
   burn["authorisation_id"]` from its own journal — the
   request's key set is unchanged and no request field is
   read. Consume derives with the same function inside the
   append loop. The two gates cannot disagree about depth
   arithmetic; they can only disagree about *when* the head
   moved, which consume re-checks.
6. **Backward compatibility / anchor (Q7)** — probe P10: a
   literal cycle-22 v1 consumption journal loads; after a v2
   append, the v1 entry's `entry_hash` is **byte-identical**
   and the v2 entry's `prev_hash` chains to it (v1 entries are
   never rewritten or normalised — `_save` re-serialises the
   file but entry hashes are over the canonical core, not the
   file bytes). The consumption anchor verifies a
   seq→entry_hash prefix map (`trust/anchoring.py`
   `verify_anchor` / `_chain_prefixes`), so a pre-upgrade
   anchor naming the v1 prefix still verifies against the
   mixed journal, and the upgraded journal's new head is a
   strict extension. A journal written by cycle-22 code loads
   and keeps verifying under this code.
7. **Cap semantics end-to-end** — primary + depth 1 + depth 2
   land; depth 3 refuses AlreadyConsumedError at consume and
   `ceremony_recovery_unproven` at authorise; the race pair
   bound to the same burn lands exactly one, and a fresh
   recovery bound to the winner's burn lands at depth + 1
   (suite + P9).

## Fix list (bounded)

1. F1: cross-entry lineage validation in
   `CeremonyConsumptionLedger._load` (recovery_of must name
   an earlier same-pair entry; depth must be its depth + 1;
   orphan/depth-jump/different-pair recoveries corrupt).
2. F2: narrow supersede — never for `burned_unadopted`
   envelopes; when the behind-head old seq is recorded in the
   journal (as an entry's new seq or the head's old seq),
   require the old hash to match the recorded hash.
3. F3 (ride-along): refuse a v1 pair occurring ≥ 3 times at
   load, matching the docstring's stated invariant.
