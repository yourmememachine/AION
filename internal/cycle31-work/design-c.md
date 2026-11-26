# Cycle 31 — Seat C (adversarial / limits trace): honest limits and open items of cycles 17+18 recovery

Scope: trace only. No code was changed for this note. Sources read in full or in the
relevant part: `trust/anchoring.py`, `trust/shiptx.py` (module docstring, `recover()`
and its post-settlement re-verification), `tests/test_trust_shiptx_anchoring.py`,
`internal/BUILD-CYCLE-17.md`, `internal/BUILD-CYCLE-18.md`, `internal/REVIEW-CYCLE-17.md`,
`internal/REVIEW-CYCLE-18.md`; plus, for the caller grep in §4, the current tree
(`trust/shipcheck.py`, `internal/BUILD-CYCLE-23.md`, `tests/test_cycle23_ship_anchors.py`).

One-line verdict: cycles 17+18 deliver exactly what their docstrings claim — an
*unkeyed, prefix-only, location-dependent* pin for the ship-tx journal, and a *typed*
surface for the journal-level case where that pin's evidence has nowhere to land.
Everything beyond that — authenticity, atomicity, a wired production caller for the
recovery side, and a non-`[]` surface for operator-error evidence with no transaction
to carry it — is either explicitly not claimed or still open. §4 records one place
where the tree has moved and the in-code claim has not.

---

## 1. Unkeyed anchor limits

Evidence: `trust/anchoring.py` module docstring, final paragraph ("Honest scope");
`trust/shiptx.py` module docstring, "Journal location" paragraph; anchor format at
the top of `trust/anchoring.py`.

1. **The anchor carries no key, signature, or MAC.** The format is exactly
   `{"v", "kind", "head", "seq", "anchored_at"}` — a plain JSON claim about a chain
   prefix. Anchoring.py states it verbatim: "The anchor is unkeyed, like the
   journals themselves: it detects rollback by disagreement, it grants no
   authority." Anyone who can write the anchor file can write a *valid* anchor
   for any head/seq pair; there is nothing to forge because there is nothing
   keyed to check.
2. **Joint rewrite defeats it completely.** Shiptx.py states the attack in so
   many words: "an attacker who can rewrite both this journal and its anchor
   can roll both back to a matching earlier pair and verification passes."
   Detection exists only relative to an anchor copy the journal's writer cannot
   reach (see §2). This is not a bug found in review — REVIEW-CYCLE-17 rev-r2 F6
   records it as "ACCEPTED as the module's stated honest scope, unchanged from
   the signing / ship anchors."
3. **Protection is prefix-only, up to the last `update_anchor`.**
   `verify_anchor` accepts an anchor naming *any older prefix* ("staleness is
   not tampering"); the test `test_stale_tx_anchor_still_verifies` pins this.
   Everything appended after the last anchor advance is unpinned until someone
   advances the anchor. Recovery makes this sharper, not softer: `recover()`
   "verifies the tx anchor once and never advances it," so (shiptx.py, Tx-anchor
   bullet) "rolling this journal back to the anchored prefix erases recovery's
   settlements undetectably" until the caller calls
   `update_anchor(..., kind="ship-tx")`. Pinned by
   `test_recovery_never_advances_tx_anchor_then_caller_does` (anchor file
   byte-identical after a COMMITTED recovery).
4. **An older anchor restored against a newer journal is not detected.**
   Same bullet: "restoring an older anchor than the journal will not be
   detected" — it still names a true prefix. Conversely, restoring journal and
   anchor from *different* backup points, or the journal without a
   `force_reanchor`, parks live transactions at ANOMALY. Backup/restore is
   therefore an operator discipline, not a property the code enforces.
5. **`force_reanchor` is a legitimate, in-band way to move the pin.** It is
   audited (hash-chained reanchor-audit file written *before* the new anchor,
   non-empty reason required, malformed audit chain refuses), but the audit
   file lives *alongside the anchor* (`reanchor_audit_path`), i.e. inside the
   same trust location as the anchor itself (§2). Whoever controls that
   location controls both the pin and the record of its re-pins;
   `verify_anchor` only checks the audit chain when
   `check_reanchor_audit=True`, and a *missing* audit file adds no reason
   there at all — "the anchor alone cannot prove one did not [happen]."

## 2. Shared-directory = one trust location

Evidence: `trust/shiptx.py` "Journal location" paragraph; `trust/anchoring.py`
`_check_outside_journal` and its "Honest scope" paragraph.

1. **The two journals already share one fate.** `ShipTxJournal` lives alongside
   the ship ledger — `ship-tx.json` in `ledger.journal_dir` — "so the two
   journals share one verifier-home directory and one fate, while remaining
   separate hash chains with separate heads." Deleting or rolling back that
   directory hits both journals together; the chains are separate, the storage
   is not.
2. **Two anchors in one external directory are one boundary, not two.**
   Shiptx.py, verbatim: "Two anchors in the same external directory are one
   trust location, not two: the tx anchor adds a second head, not a second
   boundary." Cycle 17's gain is therefore a second *head* for a journal that
   previously had none — not a second independent witness. The test fixture
   itself models the weak deployment: `TxAnchorFixture` places both
   `ship.anchor.json` and `ship-tx.anchor.json` in the same `anchors/`
   directory.
3. **The code enforces only the weakest placement rule.** `_check_outside_journal`
   refuses a path *inside the journal's own directory* (including nested
   subdirectories; pinned by `PlacementTests`). It does not and cannot enforce
   the docstring's real requirement — "storage the journal writer cannot
   rewrite — a verifier-owned directory under a separate OS user … or
   off-machine." Any other same-writer-writable directory passes every check
   in the tree while providing, per the docstring, only "a second copy of the
   journal's own claim, not a pin." Deployment topology is asserted by the
   operator and unverifiable in-tree.

## 3. Initial anchoring ceremony limits

Evidence: `trust/anchoring.py` `initialise_anchor` and module docstring;
`trust/shiptx.py` Tx-anchor bullet; `CeremonyTests` in the cycle-17 suite.

1. **The ceremony pins whatever history is on disk at that moment.** On a
   non-empty journal it refuses by default; with
   `allow_nonempty_ceremony=True` it "blesses its history as-is, including a
   rolled-back one" (anchoring.py). The flag is an operator *assertion* that
   the current history is the true one — the code records no evidence for
   that assertion and the anchor format has no field for it.
2. **It cannot detect any rollback that predates it.** Shiptx.py, verbatim:
   "Initial anchoring of an established tx journal requires the nonempty
   ceremony (allow_nonempty_ceremony=True) and therefore cannot detect any
   rollback that predates it." For the ship-tx journal this is the normal
   case, not an edge case: an established tx journal is by definition
   non-empty, and the test helper `init_tx_anchor()` defaults the flag to
   `True`. The genesis pin (seq 0, empty journal,
   `test_initialise_empty_tx_journal_pins_genesis`) is the only ceremony
   whose starting point is self-evident — and it is available only before
   the first transaction exists.
3. **Before any ceremony, the absence signal is weak by design.** No anchor +
   non-empty journal yields only the `anchor_missing_established_ledger`
   reason, which recovery classifies as an *operator error* (non-destructive,
   transaction left in place) — indistinguishable in kind from a mistyped
   path. A ledger that ran unanchored, was rolled back, and re-grown presents
   the same surface as a ledger whose operator simply has not run the
   ceremony yet.
4. **The ceremony is one-shot and unforgiving of path mistakes.**
   `initialise_anchor` refuses if *any* file exists at the path, "even a
   malformed file"; the only way forward after a wrong first pin is
   `force_reanchor` (§1.5). There is no in-tree record that a ceremony took
   place, when, or under which flag — the resulting anchor is identical in
   form whether it pinned genesis or blessed an established history.

## 4. No in-tree caller passing `tx_anchor_path` — grep verification, with a correction

Method (this run, current tree): `grep -rn "tx_anchor_path" --include="*.py" .`
over `~/workspace/ai`, classified by file; cross-checked against
`trust/shipcheck.py` signatures and callers of `record_ship` /
`recover_ship_tx` / `anchored_record_ship` outside `tests/`.

**What was true at cycles 17+18.** BUILD-CYCLE-17 §"What was built" and
REVIEW-CYCLE-17 rev-r3 #5 both record it in the present tense: "NO in-tree
caller passes tx_anchor_path yet — this is operator/library plumbing."
`ShipTxJournal.recover(tx_anchor_path=None)` defaulted to pre-cycle-17
behaviour exactly, and `recover_ship_tx` merely forwarded the keyword. The
only exercisers were the tests. That claim was accurate when written.

**What the grep shows now — the in-code claim is stale in one direction and
still true in the other.** `trust/shiptx.py` `recover()`'s docstring still
asserts, unqualified: "No in-tree caller passes ``tx_anchor_path`` yet."
Against the current tree that sentence needs splitting:

1. **Recovery side — still no production caller (claim holds).** Outside
   `tests/` and the definitions/forwarding themselves, no `.py` file passes
   `tx_anchor_path` to `recover()` or `recover_ship_tx()`. The non-test hits
   are exactly: the parameter and forwarding in
   `trust/shipcheck.py:507-508, 547, 567` (`recover_ship_tx` definition) and
   `trust/shiptx.py` itself. `grep` for callers of `recover_ship_tx` in
   non-test code finds only its definition, its export line in
   `trust/__init__.py:69`, and doc references. Exercisers remain tests only:
   `tests/test_trust_shiptx_anchoring.py` and
   `tests/test_cycle23_ship_anchors.py:152` (the latter passes it to a
   fixture helper around `anchored_record_ship`, not to recovery).
2. **Write side — the follow-on partially landed in cycle 23, and the
   docstring does not say so.** `trust/shipcheck.py:425`
   `anchored_record_ship(...)` takes `tx_anchor_path` as a *required*
   keyword, verifies the ship-tx anchor and its *currency* (head and seq
   equal to the journal's current head/length — stricter than recovery's
   prefix check) before anything is spent, and after COMMITTED advances
   the tx anchor itself: `update_anchor(tx_journal, tx_anchor_path,
   kind="ship-tx", ...)` at `trust/shipcheck.py:497` (BUILD-CYCLE-23
   records the same). So "wire the ship flow" (§6a) is done for the
   recording path via a new wrapper — but note the limits of that wiring:
   `record_ship` itself still has **no** `tx_anchor_path` parameter
   (signature at `trust/shipcheck.py:202-206` carries only `anchor_path`),
   and `anchored_record_ship` itself has **no non-test caller** in the
   tree (grep: definition + `tests/test_cycle23_ship_anchors.py` only).
   It is a production-*shaped* library entry point, not a wired production
   entry point.
3. **Net adversarial point.** A reader trusting the `recover()` docstring
   today would conclude the tx anchor is entirely unexercised outside
   tests; a reader trusting "cycle 23 wired the ship flow" would conclude
   recovery is anchored in production. Both are wrong. The accurate
   statement is: *write-side advancement exists in a wrapper nobody in-tree
   calls; recovery-side verification exists in a parameter nobody in-tree
   supplies.*

## 5. TOCTOU non-claims

Evidence: `trust/shiptx.py` `recover()` post-settlement comment and code;
`internal/BUILD-CYCLE-18.md` "What was built" item 3; REVIEW-CYCLE-17 rev-r2 F5.

1. **No path-replacement / TOCTOU claim is made — explicitly.** BUILD-CYCLE-18,
   verbatim: "No path-replacement/TOCTOU claim is made this cycle." Cycle 18
   added hardlink pins for the same-file guard but did not claim the guard is
   race-proof, and nothing since in the read sources upgrades that.
2. **The same-file guard is a point-in-time identity check.** `recover()`
   diagnoses "same file" via `os.path.samefile` with a resolved-path fallback,
   at the moment of the check. A path replaced (symlink retargeted, file
   swapped) between that check and either `verify_anchor` call is outside
   the claim. The guard's pinned semantics are about *identity at check
   time*: symlink and hardlink aliases are caught
   (`test_same_file_symlink_alias_is_error_not_anomaly`,
   `test_same_file_hardlink_alias_of_ship_anchor`,
   `test_same_file_hardlink_alias_of_tx_anchor`), while a byte-identical
   *copy* on a distinct inode is deliberately treated as a different —
   possibly substituted — file and parks
   (`test_byte_copy_distinct_inode_still_parks`). Content equality proves
   nothing; inode equality proves only that moment.
3. **Verify-then-settle is not atomic, and the mitigation is detection, not
   prevention.** `recover()`'s own comment: the pre-settlement verdicts are
   "a snapshot taken before the loop, and no lock is held across
   verify+settle." The cycle-17 fix (rev-r2 F5) re-verifies both anchors
   *after* the settlement loop; a park reason appearing only then raises
   `JournalIntegrityError` (cycle 18 typing) — but "settlements already
   journaled stand (they are evidence too)." A journal swapped mid-recovery
   can therefore have settlements land against it before the swap is
   surfaced; the guarantee is that the run does not *silently pass* on the
   stale verdict, not that no settlement occurs. The ship-tx journal's flock
   serialises *appends through ShipTxJournal instances*; it does not lock
   the anchor files, the ship ledger, or an attacker with raw file access.
4. **Consequence for §1:** between the last `verify_anchor` and the caller's
   post-recovery `update_anchor`, the window in §1.3 is a TOCTOU window as
   well as a staleness window — a rollback to the anchored prefix in that
   interval is, by the module's own statement, undetectable.

## 6. Follow-on items (named, not built — or only half-built)

### 6a. Ship-flow wiring

Named in BUILD-CYCLE-17 as its own cycle: "wire the ship flow (record_ship
advancing the tx anchor after COMMITTED, and an operator recovery path that
passes tx_anchor_path)". Status at this trace:

- *Recording half:* landed in cycle 23 as `anchored_record_ship` (§4.2),
  including the currency requirement and the post-COMMITTED tx-anchor
  advance — with its own stated residual: if that advance fails, "the ship
  stands recorded and finalised; … the stale tx anchor is the anomaly
  signal," and the next anchored recording refuses until an operator
  reconciles. Still open: any actual production/operator caller of
  `anchored_record_ship`.
- *Recovery half:* **not wired.** No operator recovery path in-tree passes
  `tx_anchor_path` (§4.1). Until one does, the entire cycle-17/18 recovery
  classification — park-over-error, the deleted-journal raise, the typed
  error — is reachable only by a caller who already knows to supply the
  parameter. Default calls (`tx_anchor_path=None`) reproduce pre-cycle-17
  behaviour exactly, silently.
- *Doc debt:* the stale sentence in `recover()`'s docstring (§4.3) should
  be corrected when the recovery half is wired, or sooner; as written it
  now understates cycle 23 and overstates nothing — the dangerous
  direction for a limits claim is the reverse, but a limits docstring
  that is wrong at all stops being load-bearing.

### 6b. Silent-`[]` surface design

Named in BUILD-CYCLE-18 "Honest scope" item (a) and preserved in
REVIEW-CYCLE-18: "Pod D's silent-[] holes — operator-error / same-file
evidence with no transaction to carry it returns [] (a chosen non-[] surface
is a design decision for its own cycle)". Cycle 18 closed only the
*chain-mismatch* branch of this hole. What remains, traced through
`recover()`:

1. **How the hole works.** Outcomes are per-transaction dicts built in the
   loop over non-terminal transactions. Operator-error reasons
   (`anchor_error_reasons`, including the same-file diagnosis) are only
   ever *attached* to such a dict. If the journal holds no non-terminal
   transaction — empty, or rolled back / settled to a terminal-only
   prefix — the loop appends nothing and `recover()` returns `[]`, which
   every caller reads as "nothing to settle," even though the caller
   supplied an anchor that failed to load, was malformed, was misplaced,
   or was the same file as the other anchor.
2. **The asymmetry beside it is deliberate and pinned.** Tx-anchor
   *chain-mismatch* reasons with no park target raise
   `JournalIntegrityError` (pre-settlement; also post-settlement for new
   reasons), because the tx journal *is* the pinned object. Ship-anchor
   chain-mismatch reasons with no park target deliberately do **not**
   raise — "the ledger it pins is a different file … and the ledger's
   anchor is verified by the ledger's own consumers" — pinned by
   `test_ship_anchor_only_park_with_nothing_to_park_no_raise` (returns
   `[]`). So today's surface is: park evidence about the tx journal →
   raise; park evidence about the ship ledger alone → `[]`; operator
   evidence about either → `[]`. That is a *labelled* asymmetry
   (REVIEW-CYCLE-18 preserves rev-r3's dissent that the outcome model is
   "still non-uniform (list vs raise)" and "labelled, not cured"), but
   the operator-error row of the table has no label at the call site —
   it is indistinguishable from a clean run.
3. **State-dependence compounds it.** The same forged tx anchor parks on
   run 1 and raises on run 2 (the park made every transaction terminal;
   `test_second_run_after_park_raises_distinct_type`). A monitoring caller
   that treats `[]` as success and exceptions as failure will see the
   operator-error hole as permanent success and the park hole as
   success-then-failure for a single underlying fact.
4. **What a fix must decide (not decided anywhere in the read sources):**
   a non-`[]` surface for evidence with no carrier — e.g. a typed raise
   for operator errors too (rejected implicitly so far: operator errors
   are defined as non-destructive and retryable, and a raise discards
   the return channel, cf. cycle 18's `.outcomes` fix-round work), a
   journal-level outcome entry in the returned list, or an explicit
   pre-flight anchor report the caller must consume. Each choice changes
   the caller contract in `trust/shipcheck.py:recover_ship_tx`, whose
   docstring currently promises "Returns the list of outcome dicts" with
   the raise named only for the deleted-journal/chain-mismatch case.

## 7. Consolidated non-claims

| Claim a reader might assume | What the evidence actually supports |
|---|---|
| The tx anchor authenticates the journal head | No — unkeyed JSON; detects disagreement only (§1.1–1.2) |
| Two anchors = two independent boundaries | No — one external directory = one trust location; both journals also share one directory (§2) |
| Anchoring an established journal secures its past | No — the nonempty ceremony blesses current history; pre-ceremony rollback is undetectable (§3) |
| Recovery keeps the anchor current | No — recovery never advances either anchor; the caller must, and the gap is undetectable rollback space (§1.3, §5.4) |
| The ship flow uses `tx_anchor_path` in production | No — write-side wrapper exists (cycle 23) with no in-tree caller; recovery side has no caller at all; `recover()`'s docstring claim is stale about the former (§4) |
| Same-file / placement checks are race-safe | No — point-in-time identity; verify+settle unlocked; post-settlement re-verification detects, settlements stand (§5) |
| `recover() == []` means nothing was wrong | No — operator-error and ship-only park evidence with no non-terminal transaction return `[]` by design; the non-`[]` surface is an unbuilt follow-on (§6b) |
| Cycles 17+18 cleared the cycles 14–16 gate | No — both build records state cycles 14+15+16 remain held on the separate Protected Gate decision, and both verdicts were PROVISIONAL with external seats vacant |

## Evidence index

- Unkeyed / honest scope: `trust/anchoring.py` module docstring (final
  paragraph); `trust/shiptx.py` "Journal location" paragraph.
- Prefix / stale / never-advances: `trust/anchoring.py` `verify_anchor`;
  `trust/shiptx.py` Tx-anchor bullet and `recover()` docstring; tests
  `test_stale_tx_anchor_still_verifies`,
  `test_recovery_never_advances_tx_anchor_then_caller_does`.
- Ceremony: `trust/anchoring.py` `initialise_anchor`; tests
  `test_initialise_nonempty_refused_by_default`,
  `test_nonempty_ceremony_flag_pins_current_head`,
  `test_double_init_refused_and_anchor_unchanged`.
- Caller grep: this run, `grep -rn "tx_anchor_path" --include="*.py" .`
  (hits classified in §4); `trust/shipcheck.py:202-206` (`record_ship`
  signature), `:425`/`:497` (`anchored_record_ship`), `:507-567`
  (`recover_ship_tx` forwarding); `internal/BUILD-CYCLE-23.md`.
- TOCTOU: `internal/BUILD-CYCLE-18.md` ("No path-replacement/TOCTOU claim
  is made this cycle"); `trust/shiptx.py` `recover()` same-file diagnosis
  and post-settlement re-verification comment ("no lock is held across
  verify+settle"); alias/copy tests in
  `tests/test_trust_shiptx_anchoring.py` (`FixRoundTests`,
  `JournalIntegrityErrorTests`).
- Silent-`[]`: `internal/BUILD-CYCLE-18.md` "Honest scope" (a);
  `internal/REVIEW-CYCLE-18.md` (Pod D holes recorded; rev-r3 dissent
  preserved); `trust/shiptx.py` `recover()` outcome loop and
  no-park-target raise; test
  `test_ship_anchor_only_park_with_nothing_to_park_no_raise`.
