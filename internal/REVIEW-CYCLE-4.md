# INTERNAL — War Room Record, Build Cycle 4 (do not publish)

Six reviewer seats, none of them authors of the code under review
(all 15 scientist seats coded this cycle, in 5 pods of 3, so the
review seats are fresh rev-r1..rev-r6, the cycle-2 pattern for a
15-coder cycle). Blind pass first: each seat probed the code
independently and returned a verdict and confidence before any
discussion. Scores are locked in the calibration log (subject
"cycle-4-build"); dissent is preserved below, not averaged away.

Reviewer seats: R1 Store Correctness, R2 Store Adversarial
(assigned dissent), R3 Gate/Write-Path, R4 Solver/Reuse Validity,
R5 Integration/Tests, R6 Honesty/Docs.

## Blind verdicts (as recorded, before fixes)
- R1 Store Correctness — FIX, 0.35. M1 MAJOR (real bug): in
  _save_locked, _disk_digest was assigned right after os.replace
  but before the directory fsync; on fsync failure the commit
  raised but the entry was on disk, in-memory state rolled back,
  and the next commit reused the seq and silently overwrote the
  committed entry. Minors: load did not check verifier != author;
  entry seq type unvalidated (1.0/true load); created_at
  parseability only; duplicate JSON keys silently accepted;
  non-finite-number parse failures skipped quarantine;
  commit_write docstring wrong on error type; CRLF content
  contract unstated. Noted: the same fsync window exists in
  eval/registry.py — flagged, out of scope.
- R2 Adversarial (dissent) — FIX, 0.25. F1 MAJOR: gate decisions
  bound only proposal_id + verifier_id, so a genuine decision
  could be redirected to a different entry (content, domain,
  author, supersedes all probed); decide_write accepted garbage
  field values; single-use silently void after a rollback. F2
  MEDIUM: the live-instance freshness guard compared only the
  stored state_digest field — naive tamper was silently clobbered,
  never detected. F3 MEDIUM: lone surrogates leaked
  UnicodeEncodeError through the API and the file path. F4
  MEDIUM: _disk_changed read the disk file with no size cap. F5:
  race-loser instance permanently wedged and stale reads silent,
  both undocumented; commit_write's docstring exception promise
  wrong (CorruptMemoryError is not a MemoryError). F6 LOW:
  quarantine growth unbounded; NaN path skipped quarantine. F7
  LOW: internally inconsistent accepted decisions committed. F8:
  misc validation laxity. Credited as genuinely strong: the
  hash-chain/supersede-graph/race integrity engine (full tamper
  matrix, barrier-synchronised races, caps all verified).
- R3 Gate/Write-Path — FIX, 0.35. F1 HIGH = R2 F1 (binding
  absent; the build record's "one decision = one entry" claim
  falsified for first-use substitution). F2 MEDIUM: commit_write
  ignored decision internal consistency; decide_write never set
  evaluated_at. F3 LOW: per-family cross-check failure only
  invalidated post-hoc, after lessons were committed on the bad
  map. F4 LOW: golden batch never floor-checked; golden gen-0
  window lacks nth-word/parity so forgetting was ungated for
  them, unstated; per-lesson manifest not re-checked. All six
  advertised poison cases verified correct.
- R4 Solver/Reuse Validity — SHIP, 0.93. The gain is real:
  reproduced the shipped run; 8 fresh seed triples all reached
  100 with controls exact; untouched-holdout test — the shipped
  store scored 24->100 and 29->100 on sealed batches it was
  never gated on; correct tokens verified on 2,800 generated
  items, generations 0-9999. Findings: F1 floor iterated only
  present families; F2 per-family cross-check binds totals, not
  family labels; F5 retrieval_enabled=False does not suppress
  lessons_override (precedence undocumented).
- R5 Integration/Tests — SHIP, 0.88. Counts/exports verified;
  mutation-tested the assertions (deleting commit gate checks ->
  4 store failures; memory-ignoring solver -> 5 solver + 6 reuse
  failures). Minors: untested reuse branches (floor rejection,
  prompt-overlap rejection, invalidation path); MAX_ENTRIES cap
  and empty-store digest accessors untested; concurrency tests
  intra-process only.
- R6 Honesty/Docs — FIX, 0.18. F1 BLOCKER = R2/R3 F1 (docstring
  "one accepted decision authorises exactly one entry"
  overstated). F2 BLOCKER: the reuse run's gate attestation is
  constructed in-line by the harness itself
  (reward_hacking_checked asserted, not performed; "seat-3" is a
  string constant; no independent verifier process exists
  in-run) and the build record did not disclose it for THIS run.
  F3: oracle-budget claim needed the qualifier that per-family
  map joining via in-process seed regeneration sits outside the
  count of 8. F4: created_at/attested_at are local host clock —
  undisclosed. F5: derivation audit described as "preserved"
  when it is only returned in-memory. F6: floor claim needed the
  "families present in the batch" qualification; the build
  record did not name its seeds. R6 re-derived every measurement
  number and confirmed them all.

## Reconciled fix list (all implemented, all pinned by tests)
1. Decision<->content binding: decide_write validates the full
   field set (shared _validate_fields), stamps
   "content-hash:<hex>" as the first verifier_note segment, sets
   evaluated_at; commit_write requires the segment to match the
   presented entry's content hash. Store docstring, _content_hash
   docstring and BUILD-CYCLE-4.md corrected. (R2 F1, R3 F1, R6 F1)
2. Decision consistency: commit_write refuses an accepted
   decision carrying reasons/regressions/forgetting_failures/
   protected_violations. (R3 F2, R2 F7)
3. M1: _disk_digest assigned only after successful directory
   fsync; fault-injection test pins no-silent-loss + loud wedge.
   (R1 M1)
4. Freshness guard recomputes: _disk_changed re-derives every
   entry's content/entry hashes and the state digest from the
   parsed file instead of trusting stored fields. (R2 F2)
5. Surrogates rejected in _check_text (category Cs); _load wraps
   validation failures as CorruptMemoryError. (R2 F3)
6. _disk_changed read is size-capped at MAX_MEMORY_BYTES. (R2 F4)
7. Load validation: verifier != author, _is_int on seq,
   timezone-aware created_at. (R1 m1-m3)
8. Duplicate JSON keys rejected on load (object_pairs_hook);
   parse-stage failures incl. non-finite constants quarantine.
   (R1 m4/m5, R2 F6)
9. Floors iterate active_families(generation) — an absent active
   family fails — and apply to the golden batch too; the golden
   forgetting blind spot for nth-word/parity is disclosed.
   (R4 F1, R6 F6, R3 F4)
10. Cross-check fail-closed: _per_family_map raises ReuseError
    on mismatch (no post-hoc invalidation); run_all raises if a
    sealed report's manifest differs from setup. (R3 F3/F4)
11. Disclosures: harness self-attestation paragraph in reuse.py
    + build record; oracle-budget qualifier; host-clock
    timestamps; derivation audit "returned, not persisted";
    retrieval_enabled precedence under lessons_override; seeds
    named in the build record; signed-gate-decisions backlog
    item reworded (signature must cover the binding segment).
    (R6 F2-F6, R4 F2/F5, R1 m6/m7, R2 F5)

## Verification round (fresh seats, same assignments)
- R1 — SHIP, 0.80. M1 closed in all variants probed (first-commit
  fsync failure, sticky wedge, pre-replace failure correctly NOT
  wedging); minors closed with margin. New minor N1: the
  freshness guard's parser was weaker than the loader's
  (duplicate keys / unknown keys silently healed). Fixed in the
  verification round: _disk_changed now uses the loader's strict
  parser and exact key-set checks; pinned by
  test_live_instance_refuses_save_over_duplicate_key_file.
- R2 (dissent) — SHIP, 0.85. Redirect probe against a genuine
  decision: every field variation refused. One LOW residual:
  corrupting only the stored state_digest field was invisible to
  the guard (the digest core excludes that field). Fixed in the
  verification round per R2's own suggested fix: the guard now
  also requires the stored field to equal the recomputed digest;
  pinned by test_live_instance_refuses_save_over_digest_field_tamper
  and test_live_instance_refuses_save_over_unknown_key.
- R3 — SHIP, 0.90. All four findings closed; probe mutated each
  proposer field against a genuine decision — all refused,
  original committed, replay refused. Two residuals noted, both
  inside documented classes (hand-built decision with empty
  evaluated_at still commits = A30; control-path manifest check
  absent but fails safe).
- R6 — SHIP, 0.93. All six disclosures verified present,
  accurate, not overstated; measurement independently
  reproduced exactly; registry fsync flag verified accurate
  (registry.py assigns its digest before its dir fsync — same
  window, correctly flagged as queued, not claimed fixed). One
  wording imprecision in the disclosing direction only.

Final verdict: RECONCILED SHIP — unanimous (blind SHIPs R4/R5
stand; all four FIX seats flipped to SHIP after verifying their
own findings closed). Full suite after all rounds: 270 tests,
all passing (160 before the cycle).

## Calibration (X4 dogfood)
Blind scores locked in state/calibration for subject
cycle-4-build: R1 0.35, R2 0.25 (dissent role), R3 0.35,
R4 0.93, R5 0.88, R6 0.18. Discussion closed before any outcome
was recorded. The outcome (shipped = 1.0) is recorded after the
ship decision; minority_report keeps the FIX seats' low blind
scores on record — they were accurate readings of the as-built
code, and the fixes they forced are the reason the ship is
sound.
