# Cycle 31 — War-room review R6 (completeness / reader)

Reviewer: R6, completeness/reader seat (blind)
Subject: `docs/RECOVERY-CONTRACT.md` against `internal/BUILD-CYCLE-17.md`
and `internal/BUILD-CYCLE-18.md` only. Cycle-31 design files not read.

Score: 0.78
Verdict: FIX

## Summary

The contract is substantively strong on behaviour: the same-file guard
(file identity via `samefile`, byte-identical copy still parks), the
park-over-error combination and park-reason set, the ship/tx asymmetry
on the no-park-target raise, the non-type-idempotence consequence
(park on run 1, raise on run 2), post-settlement re-verification with
only new reasons counting, `JournalIntegrityError` constructor
validation / set-equality / derived `anchor_source` / handler-order
rule, recovery never advancing either anchor, the unkeyed-anchor and
prefix-only limits, the nonempty-ceremony caveat, the no-TOCTOU claim,
and the silent-`[]` holes are all present and match cycles 17+18,
including the honest cycle-23 correction to the stale "no caller"
claim for the write half. The gaps below are completeness and
operability gaps, not behavioural contradictions — but they fail the
second half of the R6 test: a new operator cannot act on this
document alone.

## Numbered gaps

1. **No operator procedure at all.** The doc gives the `recover()` /
   `recover_ship_tx()` signatures but no step-by-step runbook: how to
   create/initialise the two anchors in the first place, where the
   anchor files are expected to live (actual filenames / directory),
   in what order an operator verifies, recovers, and re-checks, and
   what to do with each outcome class. Cycle 17 states all anchor
   operations (`initialise` / `update` / `force_reanchor` / `verify`)
   work generically on `ShipTxJournal`; the contract never names
   those operations or their call shape.

2. **Anchor advancement after recovery is unspecified.** The doc says
   recovery never advances either anchor and advancement is "a caller
   duty", then documents only the write half (`anchored_record_ship`,
   cycle 23). It never tells the operator what, if anything, they
   should do to advance the tx anchor after a successful recovery
   settlement — advance it, leave it, or use `force_reanchor` — even
   though the Limits section notes rollback to the anchored prefix
   "erases its settlements undetectably" precisely because recovery
   does not advance. An operator following the doc alone cannot close
   that window or know they are not supposed to.

3. **Unexplained signature parameters.** `recorded_at`, `root`,
   `anchor_path`, and `ledger` / `loop` are shown in the entry-point
   signature with no statement of what they are, when an operator
   must pass them, or safe defaults. `root=None` in particular is
   load-bearing for locating journals/anchors and is never defined.

4. **Outcome-dict shape is not defined.** The doc says recovery
   "returns one outcome dict per changed or failed transaction" and
   mentions per-tx `error` outcomes and (from cycle 17) park outcomes
   carrying `anchor_sources`, but never enumerates the outcome dict's
   keys or the terminal/non-terminal transaction states, nor what
   parking "at ANOMALY" means operationally (what the operator should
   do with a parked transaction next). A reader cannot interpret a
   real return value from the doc alone.

5. **Placement rule is asserted, not stated.** Cycle 17 (Pod D) and
   the doc both invoke the ship ledger's "directory placement rules"
   and warn that two anchors in one external directory are one trust
   location, but the contract never states the rule itself — which
   directory the anchors must/must not share with the journal, and
   what placement counts as compliant. The operator is told a rule
   exists, not what it is.

6. **Cycle-18 public surface is incompletely pinned.** The doc locates
   `JournalIntegrityError` at `trust/anchoring.py:159` but omits that
   cycle 18 also exported it from `trust/__init__.py` (including
   `__all__`) — the import path an operator would actually use — and
   gives no handling example showing the catch-`JournalIntegrityError`-
   before-`AnchorError` order in code. It also omits cycle 18's
   constraint that the two message substrings existing tests check
   must survive verbatim, so a reader cannot tell which parts of the
   error text are stable API and which are free to change.

7. **Caller propagation through `recover_ship_tx` is unstated.**
   Cycle 18 (Pod B) records that `recover_ship_tx` is the only
   production caller and "propagates unwrapped". The contract says
   the function "forwards" `recover()` but never states that the two
   raises propagate through it unwrapped — an operator writing a
   handler around `recover_ship_tx` has to guess whether to catch
   there or further up.

8. **No verification instructions.** The doc claims "every claim is
   pinned by a test in `tests/test_trust_shiptx_anchoring.py`" but
   gives no test count (41 after cycle 17, 58 after cycle 18), no
   command to run the suite, and no expected result, so a new operator
   cannot confirm the tree in front of them actually satisfies the
   contract before acting on it.

## What would change the verdict

Add a short "Operating it" section covering gaps 1–3 (initialise →
verify → recover → advance-or-not, with the placement rule from gap 5
stated inline), a one-paragraph outcome-dict / transaction-state
reference (gap 4), and the import path plus propagation note
(gaps 6–7). Gap 8 needs only one line with the test file, count, and
run command. No behavioural rewrite is required.
