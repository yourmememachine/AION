# INTERNAL — War Room Record, Build Cycle 5 (do not publish)

Six reviewer seats, none of them authors of the code under review
(all 15 scientist seats coded this cycle in 5 pods of 3, so review
seats are fresh rev-r1..rev-r6, the cycle-3/4 pattern). Blind pass
first; R2 held the assigned dissent role. R5's first seat ended
without a report and was re-seated; the replacement completed.

Reviewer seats: R1 Journal Correctness, R2 Adversarial (dissent),
R3 Gate Binding, R4 Commit/Rollback/Recovery, R5 Integration/Tests,
R6 Honesty/Docs.

## Blind verdicts (as reported)
- R1 — FIX, 0.93. Digest ordering verified correct (computed before
  replace, payload-consistent). CRITICAL F1: commit's canary tamper
  check is tautological (canary compared to itself; stored root
  hash never checked) — probe committed EVIL_TAMPERED bytes under a
  genuine decision. HIGH F2: recover() unreachable (constructor
  raises first). Mediums: stage orphans, snapshot durability,
  mode drift, journal cap bricking via _validate in _save.
- R2 (dissent) — FIX, 0.90. F1 = R1 F1 (probe P1). F2 = R1 F2
  (test suite's own object.__new__ bypass cited as smoking gun).
  F3: direct GateDecision construction + unauthenticated
  mark_verified (A30 class, partly disclosed). F4: symlink swap
  mid-commit writes outside tree, rollback deletes the outside
  file, journal bricks in COMMITTING. F5: drift TOCTOU. F6:
  single-use is journal-local. F7: stage crash bricks proposal id.
  F8: tree caps dead code (unbounded copytree). F9: bare protected
  names (eval/selfmod/.git/state as files) slip prefix checks.
  F10: journal validation shallow (bare KeyError on malformed).
- R3 — FIX, 0.95. F1 = R1 F1 plus canary symlink follows (secret
  file leaked into tree). Commit re-checks neither decision nor
  protected scope; journal stores only verifier_id. P12: crafted
  VERIFIED journal entry commits eval/gate.py (self-anchored chain
  class, disclosed). Root hash binds (path, bytes) only — decision
  portable across trees (now documented).
- R4 — FIX, 0.92. F1/F2 as above. F3: missing snapshot in recovery
  = bare FileNotFoundError. F4: mode drift ignored. F5: rollback
  prunes PRE-EXISTING empty dirs. F6 = R2 F7. F7: commit failure
  surfaces raw OSError, not CanaryError. Credited: multi-file
  failure auto-rollback byte+mode exact in both orderings;
  rollback survives deleted canary; recovery logic sound once
  reached.
- R5 (replacement seat) — SHIP, 0.90. 45 tests verified; exports
  exact (13 names); mutation check: removing the content-hash
  check fails exactly test_decision_bound_to_other_bytes_refused.
- R6 — FIX, 0.92. F1/F2 as above. F3: "live manifest" claim
  overstates (changed paths only; _tree_manifest dead code). F4:
  mode never verified on rollback. F5: timestamps claim false for
  journal (form not validated). F6: ".." mechanism misdescribed.
  Undocumented: U1 retention, U2 200-entry lifetime cap, U3 modes
  unchangeable / creates 0o644, U4 caps dead code, U5 single-
  process only + stage orphans, U6 abort() undocumented.

## Reconciled fix list (all implemented, pinned by tests)
1. Canary binding: per-file candidate hashes + root hash stored in
   journal at stage; commit re-verifies canary bytes against them
   BEFORE the COMMITTING transition; post-verify against staged
   hashes; canary symlink walk (root + every component) refused.
   (R1/R2/R3/R4/R6 F1)
2. Recovery: CanaryManager.recover_journal() classmethod is the
   public entry point; recovery test rewritten to use it — no
   object.__new__ bypass anywhere. (F2, all seats)
3. Commit re-validation: decision fields stored at stage;
   reconstructed and re-checked at commit; protected re-check;
   per-file _resolve_in_tree + drift re-check before each replace;
   restore never writes/deletes through a symlink. (R3, R2 F4/F5)
4. Mode drift refused; rollback verify checks bytes AND mode.
   (R1/R4/R6 F4)
5. Pre-existing dirs recorded at stage (preexisting_dirs); rollback
   prunes only dirs the change created. (R4 F5)
6. Stage failure cleanup: snapshot/canary removed only if this
   attempt created them; id retryable; pre-existing content
   preserved. (R1 F3, R2 F7, R4 F6, R6 U5)
7. Commit failure wraps in CanaryError after auto-rollback; if
   restore itself fails, journal stays COMMITTING for
   recover_journal, stated in the error. (R4 F7)
8. Missing snapshot raises CorruptJournalError (typed). (R4 F3)
9. Bare protected names refused (first-component check). (R2 F9)
10. Tree caps enforced at stage via _tree_manifest; non-regular
    files (FIFO/socket/device) refused via lstat S_ISREG before
    any read (verification round 2: FIFO hang fix). (R2 F8, R6 U4)
11. Journal cap: stage reserves len(changes)+5 headroom; lifecycle
    transitions exempt from the soft cap (200); hard cap 264
    bounds append/load; graceful CanaryError, never a bricked
    COMMITTING. (R1 F6, R6 U2, verification round 2 F2)
12. Journal entry field presence/type validation on load. (R2 F10)
13. Snapshot writes use the same atomic write as live files;
    unlink in restore fsyncs the parent dir. (R1 F4)
14. Docstring reconciled: abort documented; decision consumed by
    commit/rollback/abort; retention, journal lifetime, mode
    limits, single-writer + residual drift race, decision
    portability, narrowed changed-paths verify claim, corrected
    ".." mechanism and UTC timestamp wording. (R6 F3/F5/F6, U1/U3/U6)

## Verification rounds
Round 1 (R1+R4 seats, fresh probes): SHIP, high confidence — all
original findings closed; 15/15 adversarial probes passed (incl.
two-file byte-swap, journal-hash tamper, 2nd-file corruption after
pre-verify). Two non-blocking nits (canary parent symlink —
closed in round 2 by the component walk; recover_journal
containment check — queued in selfmod-journal-compaction).
Round 1 (R2+R6 seats): FIX, 0.88 — four new findings (FIFO hang in
the new _tree_manifest path, journal-cap mid-lifecycle brick,
canary ancestor symlink claim, stage cleanup deleting pre-existing
content), all fixed above as items 10, 11, 1 and 6, with 5 new
regression tests (58 canary tests total).
Round 2 (fresh adversarial seat): SHIP, ~0.95 — 18/18 probes on the
four round-2 fixes passed, incl. recovery with soft cap patched
to 0 and late _append failure cleanup.

Final verdict: RECONCILED SHIP — unanimous after verification
(R5 blind SHIP stands; all five FIX seats' findings verified
closed). Full suite after all rounds: 328 tests, all passing
(270 before the cycle).

## Calibration (X4)
Blind ship-confidence scores locked in state/calibration for
subject cycle-5-build: R1 0.07, R2 0.10 (dissent role), R3 0.05,
R4 0.08, R5 0.90, R6 0.08. (FIX seats reported confidence in their
FIX verdict; the recorded score is 1 minus that, i.e. confidence
the build should ship as-is — low scores were accurate readings
of the as-built code.) Outcome recorded after ship: 1.0.
Minority note: R5's blind SHIP at 0.90 was the outlier; its scope
was integration/tests, where the build was in fact sound.
