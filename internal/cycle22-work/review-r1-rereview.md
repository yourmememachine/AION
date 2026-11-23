# Cycle 22 — Re-Review R1 (rev-r1, blind re-review after fix round)

Reviewer seat: rev-r1. Scope: my first review
(internal/cycle22-work/review-r1.md, SHIP 0.88, one Minor F1),
the fix-round changes to `trust/ledger.py`
(`match_head_burn` one-shot rule), and the two new pins:
`OneShotRecoveryTests` / `test_two_recoveries_race_pinned_outcome`
in tests/test_signing_ceremony_recovery.py and
`test_recovery_is_one_shot_second_recovery_refused` in
tests/test_trust_ceremony_consumption.py. No other seat's
re-review was read.

## Verdict: SHIP — score 0.92

## Findings

### F1 (was Minor — CLOSED): the race outcome is now test-pinned, in its tightened form, honestly labelled

My F1 asked for a pin of the §4.4.5 race (two recoveries
authorised against one head burn, then both consume). The
fix round changed the consume-side semantics under the
coordinator ruling (one-shot, rev-r6 F1, supersedes
§4.4.5's both-land wording), and the new pin is honest
about exactly that:

- `test_two_recoveries_race_pinned_outcome`
  (tests/test_signing_ceremony_recovery.py, OneShotRecoveryTests)
  mints two DISTINCT recovery authorisations (asserts
  different authorisation_ids), predicate-checks BOTH
  against the original burn head (`match_head_burn` non-None
  and `check_head` None for each, on the pre-consume
  snapshot) — so "both authorised before either consumes"
  is genuinely established, not assumed. The first
  `append_consumption` lands; the second raises
  `AlreadyConsumedError`. Final journal: exactly 2 entries,
  whose (old_seq, old_hash, new_seq, new_hash) set is the
  single burned movement {(41, OLD_HASH, 47, CAND_HASH)}.
- The test's own comment names the deviation in plain words
  ("DEVIATION pinned deliberately: §4.4.5 also specified
  both CONSUMPTIONS land. The rev-r6 F1 one-shot rule
  supersedes that consume-side outcome…") and states its
  purpose: pin the tightened semantics so a future change
  cannot silently flip them in either direction. That is
  the honesty my F1 was asking for — the pin would now
  fail if the semantics drifted back to both-land OR to
  authorise-side refusal of the second pre-consume recovery.
- The ledger-level race pin composes with the verifier-level
  pin rather than substituting for it (see F2).

### F2 (Info — verified): the one-shot rule is a single shared predicate, enforced at both gates end-to-end

- `match_head_burn` (trust/ledger.py) now returns the head
  entry only if NO earlier entry carries the head's exact
  (old_cycle_seq, old_payload_hash, new_cycle_seq,
  new_payload_hash) pair. The reasoning in its docstring is
  sound: a recovery consumption writes an entry
  indistinguishable from the original burn (same old→new
  pair, no reason field in the strict entry schema), and an
  ordinary (non-recovery) envelope for an already-consumed
  target is refused by `check_head`, so a duplicate-pair
  head entry can only have been produced by riding the
  recovery exception — it cannot ground another recovery.
  I found no legitimate non-recovery path that produces a
  duplicate pair at the head (head seq is monotonic:
  candidate-behind-head is refused, so the journal cannot
  walk away and legitimately re-burn the same movement).
- Both gates go through this one predicate, unchanged from
  my first review's verification: authorise step (5b)
  (trust/verifier_main.py:2539, fresh ledger read, single
  `ceremony_recovery_unproven` code for every predicate
  failure) and consume (`check_head`'s scoped exception).
  No second copy of the rule exists to drift.
- `test_recovery_is_one_shot_second_recovery_refused`
  (tests/test_trust_ceremony_consumption.py) pins it
  end-to-end through the real verifier: burn via the crash
  harness, first recovery authorises + consumes + adopts
  (record verifies clean), then a SECOND `burned_unadopted`
  authorise for the same target/old-pin is refused with
  `ceremony_recovery_unproven` (asserted to appear exactly
  once — no oracle detail), and the consumption journal is
  unchanged (still 2 entries). Its docstring explicitly
  records that it supersedes the §6.2 iterated-chain
  semantics the predecessor test pinned.
- Supporting unit pins in OneShotRecoveryTests:
  `test_match_head_burn_refuses_recovery_head` (pure
  duplicate-pair head → None),
  `test_second_authorise_predicate_fails_after_recovery`,
  and `test_second_recovery_consume_raises_already_consumed`
  (a pre-authorised second recovery is refused at BOTH
  `check_head` and `append_consumption`, journal stays at
  2 entries). The consume-side refusal is the race-relevant
  one: `append_consumption` reloads fresh entries on every
  retry attempt, so the loser's refusal is computed against
  the post-winner journal, not a stale snapshot.

### F3 (Info — verified): one-shot breaks none of the guarantees my first review verified; it strengthens two of them

- **Permanence:** unchanged and strengthened. Nothing
  un-burns or rewrites an entry (no such API; the journal
  is append-only); one-shot additionally prevents the
  original burn's movement from being re-consumed under a
  second recovery envelope. Original-envelope re-consume
  and recovery-envelope double-consume refusals still pass
  in the suite (`test_recovery_envelope_consumed_twice_refused`).
- **No bypass:** the scoped exception in `check_head` is
  still gated on `reason == "burned_unadopted"` AND
  `match_head_burn(...) is not None` — and that predicate
  is now strictly narrower than in my first review, so the
  exception can fire at most once per burned movement.
  Relabel routes (chain_gap_recovery / lost_pin envelopes
  for the consumed target) still raise AlreadyConsumed
  (CheckHeadTests + suite green). No-pin and with-pin
  shapes are both covered by the pair encoding
  (seq=None/hash="" participates in the pair equality), so
  the one-shot rule cannot be evaded by switching pin shape
  for the same movement — a shape switch already fails the
  exact old-pin equality in `match_head_burn`.
- **Burn proof:** unchanged. Step (5b) still proves the
  recovery against the freshly read, hash-chain-validated
  recorded journal with exact target + old-pin equality,
  head-only, one refusal code, self-recovery (burned
  ceremony's own id) refused. One-shot only removes one
  formerly-acceptable head state (duplicate-pair head)
  from the provable set; it adds no caller-asserted input.

### F4 (Info — accepted trade-off, not a defect): §6.2 iterated recovery is gone; a recovery that itself burns unadopted cannot be re-recovered

The tightened rule has a real liveness cost, which the
record should carry plainly: if a recovery consumption
lands and the caller again crashes before adopting the
pin, that movement is terminal — no second
`burned_unadopted` ceremony can be authorised (authorise:
`ceremony_recovery_unproven`) or consumed (consume:
`AlreadyConsumedError`), and no other reason reaches the
already-consumed target either. The previous §6.2 chain
semantics covered exactly that double-crash case. This is
a fail-closed trade — safety (a burn grounds exactly one
recovery; no unbounded re-issuance chain off one burn) over
double-crash liveness — it is the coordinator's stated
ruling, both new tests document the supersession in their
own text, and it touches none of the safety guarantees in
F3. I do not block on it. Noted for the cycle record: the
pre-fix DESIGN-FINAL R1 lines ("Iterated recovery is a
chain… the two-recoveries race outcome (A §4.4.5) is
specified and test-pinned") still read in the old wording;
the supersession currently lives in the ruling, the
ledger docstrings, and the two test docstrings/comments.
REVIEW-CYCLE-22.md should record the supersession
explicitly so the design-final text is not quoted later as
current semantics.

## Tests run (by this seat, this re-review)

- `python3 -m unittest tests.test_signing_ceremony_recovery
  tests.test_trust_ceremony_consumption`: **43 tests, OK**
  (25.2s) — including all four OneShotRecoveryTests, the
  race pin, the verifier-level one-shot pin, both recovery
  happy paths, the forgery/no-oracle pins, and every
  regression my first review relied on.

## Headlines

- SHIP 0.92: F1 closed — the race is test-pinned in its tightened one-shot form (both recoveries authorised against the original burn, first consumption lands, second refused AlreadyConsumedError), with the deviation from §4.4.5 labelled in the test itself.
- One-shot is safe and breaks nothing I verified: it runs through the single shared `match_head_burn` predicate at both authorise (5b) and consume, narrows the recovery exception to once per burned movement, and leaves permanence, relabel resistance, and journal-proven burn proof intact or stronger.
- Accepted trade-off, recorded not blocking: §6.2 iterated recovery is superseded — a recovery that itself burns unadopted is terminal for that movement (fail-closed by coordinator ruling); REVIEW-CYCLE-22.md should state the supersession explicitly against DESIGN-FINAL R1's older wording.
