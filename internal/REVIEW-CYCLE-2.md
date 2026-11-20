# INTERNAL — War Room Record, Build Cycle 2 (do not publish)

Six reviewer seats, none of them builders of the code under review
(builders ∩ reviewers = ∅). Blind pass first: each seat read the code
and probed it independently and recorded a blind confidence score in
the calibration log (subject "cycle-2-build") BEFORE any discussion.
Scores are locked; dissent is preserved below, not averaged away.

## Blind verdicts (as recorded, before fixes)
- R1 Registry Correctness — SHIP, 0.78. Core behaviours verified by
  probing (return-value sealing, hash-lock on load/save/evaluate,
  log-before-access is real, corrupt input fails closed, compare_gains
  strict). Majors: sealed prompts reach any caller-supplied scorer and
  small-set scores are an extraction oracle (deployment constraint:
  sealed evaluation must never be builder-callable); set completeness,
  versions and log tail not integrity-protected on load. Minors:
  unknown keys accepted; compare_reports does not type-check versions;
  a directory in place of the file raises raw IsADirectoryError;
  failed-operation logging is asymmetric; public evaluation does not
  verify hashes first.
- R2 Registry Adversarial — FIX, 0.35 (assigned dissent seat).
  BLOCKER: a caller-supplied scorer could mutate the sealed set
  mid-evaluation (rotate/add during the run) and receive a perfect
  score stamped with the pre-mutation version — the report was false
  and its version binding meaningless. Majors: docstring overclaimed
  "never returned" while prompts go to the scorer; compare_reports
  "version binding" accepted fully forged report dicts; version
  counters had no integrity protection, so a rollback was cheaper
  than any documented limit; the deterministic content hash plus a
  known prompt allows offline, unlogged brute-force of low-entropy
  expected answers. Minors: scorer exception chain could carry prompt
  text; access log attests attempts indistinguishably from successes.
- R3 Gate Semantics — SHIP, 0.90. ~70 adversarial probes, all
  fail-closed. Minors: a 1e-9 float-noise band exists inside the
  "epsilon 0" rule (documented); the sealed-hash binding is only as
  deep as the caller's manifest computation; attested_at was checked
  for presence only.
- R4 Calibration — FIX, 0.85. MAJOR: persisted outcome fields were
  not tamper-evident — the entry hash covered only the blind core,
  so outcome/error/discussion fields could be rewritten in the file
  undetected. Minors: reviewer_stats trusted stored error fields;
  outcome_at was not type-checked as text.
- R5 Integration/Tests — SHIP, 0.92. Minors: a dead branch in the
  forgetting check; subject outcome recording was not atomic across
  entries (both already fixed before reconciliation).
- R6 Adversarial/Honesty — FIX, 0.88. Blockers were overclaiming in
  code documentation, not behaviour: the gate docstring implied
  guarantees about inputs it cannot check; the registry docstring
  did not state scorer trust or the missing-file fresh-start limit;
  sealed reports carried no manifest binding; verify_sealed_integrity
  returned vacuous True on an empty sealed set; calibration limits
  were unstated.

## Reconciled fix list (one list, all applied)
- F1 (R2 blocker): evaluations run on a deep-copied snapshot; a
  sealed-version change during evaluation raises EvaluationError.
  Regression tests cover scorer-side rotate and add mid-run.
- F2 (R2/R1): a state digest binds versions, item membership and the
  log head; recomputed on save, checked on load. Strict key sets for
  registry, items and log entries. Version rollback, item deletion
  and unknown keys now fail on load (unless the digest is also
  recomputed — the documented co-located limit).
- F3 (R2/R1): compare_reports type-checks versions and n/correct,
  requires score = correct/n, and rejects a sealed report whose
  manifest hash mismatches the current manifest at the current
  version. Sealed reports carry manifest_hash (R6).
- F4 (R4): outcome fields sealed by an outcome hash, the discussion
  timestamp by a close hash (close_discussion records no actor),
  closed-subject map by a state-level digest — all checked on load,
  with regression tests that recompute the arithmetic fields
  consistently and still get caught.
- F5 (R6): docstrings rewritten to state trusted-input limits
  plainly in gate.py, registry.py and calibration.py; "anchored"
  wording removed where the baseline is not externally anchored;
  verify_sealed_integrity raises on an empty sealed set.
- F6 (R3/R5 minors): attested_at is parsed (bad value rejects);
  dead forgetting branch removed; subject outcome recording made
  atomic in one save; public evaluation verifies item hashes first;
  unreadable registry file raises CorruptRegistryError; scorer
  exceptions on the sealed path no longer chain context (prompt
  text cannot leak through __cause__).
- Accepted as documented limits (not fixed, stated in code docs):
  sealed prompts are shown to the trusted scorer by design, so
  sealed evaluation must run verifier-side and never be
  builder-callable; small-set aggregate scores are an extraction
  oracle for low-entropy answers, and the public content hash allows
  offline guessing once a prompt is known — the access log cannot
  see offline steps; access-log entries record attempts, persisted
  before the operation, and are not proof of success.

## Post-fix additions in the same cycle (v3/v4 roadmap)
Protected Gate Rule (gate rejects self-changes touching eval/ or
core/loop.py, with tests), golden set (never-retired baseline),
calibration dissent role + minority_report, gate verifier_note.
The protected-gate rule landed while the blind pass was running;
the verification round re-checked the final code as a whole.

- F7 (R2 verification round): the first verification pass confirmed
  every same-instance fix but found a cross-instance hole — a second
  registry instance on the same directory could mutate the sealed
  set mid-evaluation, and a stale instance's later save silently
  rolled back newer state under a valid digest. Fixed with a
  file-freshness guard: each instance remembers the state digest it
  last loaded/saved; save() refuses (CorruptRegistryError) when the
  file has moved on, and sealed/golden evaluations fail if the file
  changed mid-run. Also: a scorer-raised EvaluationError on the
  sealed path is replaced by the generic message (it could carry
  prompt text). compare_reports' remaining limit — it binds set
  identity, not provenance; reports are unsigned — is now stated in
  the module docstring as an accepted limit.

## Verification round
- R6: SHIP. All five honesty findings verified resolved in the
  text; the new state-digest and golden-set passages pass its
  strict no-overclaim scan.
- R4: SHIP. Outcome/discussion sealing verified by independent
  probes (tampered outcome with recomputed error fields and
  tampered discussion stamp both fail on load); the role/minority
  additions do not weaken the seals. Residual noted: the seals are
  unkeyed hashes — tamper-and-recompute loads, the documented
  co-located limit, same standard as the blind core.
- F8 (R2 verification round 2): the freshness guard itself raced —
  check-then-replace without a lock silently lost writes under
  barrier-synchronized threaded saves (27/30 trials in R2's probe).
  Fixed: save() now holds an exclusive inter-instance flock across
  the freshness check and the replace. Evaluations deliberately do
  not hold the lock while scoring (that deadlocked the cross-instance
  probe); they detect concurrent writes via the snapshot, version
  and end-of-run digest checks. Regression test races two instances
  on a 200-item registry and requires exactly one winner and one
  loud refusal.
- F9 (R2 verification round 3): the two-instance race was verified
  closed (0/30, multi-process 0/10), but the lock itself had two
  defeats — a lockfile unlink mid-race split the lock across inodes
  (19/20 silent loss), and one instance shared by two threads
  mistook the second thread for lock re-entry (3/30 silent loss).
  Fixed: the acquire verifies the locked descriptor's inode against
  the lockfile path and retries on mismatch; re-entrancy is owned
  by thread ident; and every public registry method is serialised
  per instance with a threading.RLock.
- F10 (R2 verification round 4): shared-instance defeat verified
  resolved (30/30), but the inode-check fix left a window — an
  unlink landing after the holder's one-time check still split the
  lock (spinning deleter 8/30). Root fix, as R2 itself proposed:
  the lock is now taken on the registry directory's own descriptor
  (no lockfile exists to unlink), and save() re-verifies the
  directory inode just before the replace.
- R2: first pass FIX (cross-instance hole, F7); second pass FIX
  (guard raced, F8); third pass FIX (lock defeats, F9); fourth pass
  FIX (unlink window, F10); fifth pass SHIP — directory-fd lock
  verified: deterministic probe 10/10 (was 10/10 split), spinning
  deleter 30/30, delayed unlink 30/30, plain race 30/30, suite 125
  clean. Two out-of-scope observations, both fail-closed: rmdir of
  the registry directory under a holder raises loudly, and
  rename-away + recreate ends in refused saves, never a lost update.

## Final verdict: SHIP (unanimous after reconciliation)
Blind pass: 3 SHIP / 3 FIX. Every FIX finding was either fixed and
re-verified by the seat that raised it (R2 through five rounds, R4
and R6 in one) or dispositioned as a documented limit in the code.
No seat's dissent was overridden; R2's 0.35 blind score stands in
the calibration log as the record of how the as-built code looked
before the fix rounds — the blockers it found were real.

## Calibration (X4 dogfood)
Blind scores locked in state/calibration for subject cycle-2-build:
R1 0.78, R2 0.35 (dissent role), R3 0.90, R4 0.85, R5 0.92, R6 0.88.
Discussion closed before any outcome was recorded. The outcome is
recorded after the ship decision; minority_report keeps R2's
dissent on record with its later accuracy.
