# Cycle 23 — rev-r6 (FORCED DISSENT) review

Reviewer: rev-r6, dissent seat, blind (no other reviewers' notes read).
Baseline 59a656a, working tree as built + fix round. Read:
DESIGN-FINAL (all rulings), CROSS-CHECK-16, CROSS-CHECK-15, the full
`git diff 59a656a`, and the new suites. Targeted re-run by this seat:
schema-v2 + ceremony recovery/consume/consumption + pin ceremony +
production e2e + live run + ship anchors = 163 tests, OK. The defects
below are semantic and procedural, not red tests.

## VERDICT: FIX — score 0.64

Strongest single objection: **the `check_head` SUPERSEDE rule
(F1).** It is a verifier-side security relaxation that appears
nowhere in DESIGN-FINAL, reverses the cycle-21 ruling that the
consumption head is verifier-owned and monotonic (caller-side
history demoted to audit-only), re-pins a cycle-20 regression test
that existed precisely to refuse this shape, and as coded it is
not conditioned on the deadlock it claims to fix.

---

## F1 — HIGH: supersede is undesigned, over-broad, and re-delegates head non-regression to the caller side

Where: `trust/ledger.py` `check_head` (old-pin branch), docstring
"supersede (cycle 23 fix seat)"; re-pins in
`tests/test_trust_ceremony_consume.py::test_old_pin_behind_head_superseded_when_candidate_ahead`,
`tests/test_signing_ceremony_recovery.py::CheckHeadTests` third
block, `tests/test_signing_pin_ceremony.py::Cycle20ConsumptionTests`
(T8′ third leg); new pins in
`tests/test_trust_consumption_schema_v2.py::SupersedeRuleTests` and
the discarded-pair leg of `test_trust_pin_adoption_crash.py`
scenario 6.

What the designed rule was: DESIGN-FINAL R3's exhaustion clause is
one sentence — "Exhaustion is never a deadlock: the next snapshot
sequence takes a primary `chain_gap_recovery` (test-pinned)."
Nothing in R1–R5, and nothing in the file-ownership table,
authorises changing `check_head`'s old-pin rule. The deadlock the
fix seat found (cap-exhausted movement, pair discarded, pin behind
head forever) is real — the crash-suite trace proves it — but it
was a FINDING against the design, and the design's own R2 rule for
findings ("that is a FINDING for the war room, not a silent fix")
was not followed for the remedy either (see F2).

Why the coded rule is broader than its justification:

1. **Not conditioned on the deadlock.** The branch fires whenever
   `not recovery and old_seq < head_seq and cand_seq > head_seq`.
   It never checks that the head is cap-exhausted, that its pair
   was discarded, or that the head movement is unadoptable.
   Concrete trace the deadlock story does not cover: head is a
   depth-0 primary burn to seq 47 whose returned pair is RETAINED
   by adopter A (`adopt_returned` would land it). A second,
   stale-capture primary with old pin seq 41 and candidate seq 52
   now CONSUMES via supersede. A's movement is abandoned by
   verifier fiat, the journal records a 41→52 movement that was
   never the live pin's movement, and A's pair is stranded. The
   pre-cycle-23 rule refused exactly this. "The burned head
   movement is superseded — abandoned, never adopted" is a
   decision the verifier now makes about a movement it cannot
   know is abandoned: the docstring itself concedes the verifier
   cannot observe the pin or the pair.
2. **Not conditioned on reason.** The branch applies to every
   non-recovery reason, including `lost_pin` — an envelope whose
   premise is that the pin is lost may now also leapfrog the
   consumed head. No test or docstring discusses the lost_pin
   shape under supersede.
3. **Not conditioned on distance.** DESIGN's exhaustion clause
   says "the NEXT snapshot sequence". The re-pinned consume test
   lands candidate seq 50 over a head at seq ~47 from an old pin
   behind it; `SupersedeRuleTests` lands 41→52 over head 47. Gap
   recovery already skips sequences, but the old-pin check was
   the one place the verifier tied a ceremony to a pin position
   it had itself consumed; that tie is now gone for any ahead
   candidate.
4. **The T8′ re-pin moves a verifier property to the adopter.**
   The re-pinned leg is explicit: envelope old=seq1 /
   candidate=seq5, head=4, LIVE pin=6 — consumption now LANDS and
   `reanchor` returns the seq-5 pin, i.e. a pin that regresses
   the live pin. The docstring's defence is PinStore context
   binding. This seat verified that defence exists
   (`signing/pin_store.py::adopt` CAS on `expected_old_pin` under
   flock, re-read under lock; tests in
   `tests/test_signing_pin_store.py`). But: (a) it protects only
   callers who adopt through PinStore with the same capture used
   to authorise — `reanchor_pin` as a library function returns
   the regressed pin to anyone else; (b) cycle 21's
   DECISION-CONSUMPTION-HEAD moved the head rule INTO the
   verifier precisely because caller-side state was demoted to
   audit-only (Gemini, CROSS-CHECK-15: closure rejected while it
   "rests on test-harness wiring"). Supersede partially reverses
   that decision, in a fix round, with no design seat, no
   addendum, and no external brief. Even if the room ultimately
   ratifies it, it cannot ride in as a fix-seat patch.

What would settle it: a designed ruling (addendum + design note)
that either (i) narrows supersede to the proven-deadlock shape —
e.g. only when the head's derived depth == MAX_RECOVERY_DEPTH,
the one state in which the head movement is provably terminal —
or (ii) honestly re-rules the head as "verifier-monotonic except
forward supersede, non-regression enforced at PinStore.adopt"
and puts THAT sentence to the external seats, since it amends
the cycle-21 decision they are still split on.

## F2 — MEDIUM-HIGH: two fix-round production changes sit outside DESIGN-FINAL ownership; one violates R2's explicit rule

- `trust/client.py` (+38 lines, `_check_ceremony_pins`) is owned
  by NO seat in DESIGN-FINAL's file table and mentioned in no
  ruling. Its own docstring states the consequence of the old
  code: the production wiring mandates the gate `key-` pin, so
  `_check_pins` "refuses every correctly issued envelope" — i.e.
  **cycle 22's "first production adopter" could never have
  completed a ceremony through a correctly pinned production
  client.** The fix itself looks sound (pin is the
  CeremonyPublicKey object; key_id derived from its bytes; signer
  pin shared; unpinned ceremony key now refuses explicitly). But
  its existence retroactively confirms Gemini's cycle-22 FIX
  ("zero live loop wiring… research-mode harness") in a stronger
  form than stated, and R2 said in terms: "No production code
  changes expected. If composition fails, that is a FINDING for
  the war room, not a silent fix." Composition failed; the fix
  seat fixed it silently and the cycle continued. Same pattern
  as F1 (ledger supersede, seat-1 file but undesigned rule).
  A cycle whose headline claim is "production integration,
  finally exercised" must record that the exercise broke two
  production paths on first contact — in the build record, as
  findings with dispositions — not only in docstrings written
  by the fix seat.
- Downstream honesty check: any BUILD-CYCLE-23 sentence of the
  form "the adopter was production-ready; only wiring was
  missing" would now be false. The wiring exercise found the
  adopter's client path broken. That is the integration working
  as intended — and it is exactly why the remaining unexercised
  surface (F5) cannot be waved through.

## F3 — MEDIUM: the issuance binding has a fail-open default (`recovery_of=None` sentinel)

DESIGN-FINAL R3 calls the issuance binding "load-bearing": lineage
is derived from the issuance entry's `recovery_of`, "never read
from the request". In `trust/ledger.py`, both `check_head` and
`append_consumption` default `recovery_of=None`, and
`_derive_lineage` treats `None` as "the bound id is the head
entry's own authorisation_id" — i.e. a caller that simply
forgets to thread the binding gets the recovery exception anyway,
bound to whatever is at head. `trust/verifier_main.py` threads it
correctly, and a v1 issuance entry yields `None` via `.get`, so
any pre-v2 issued `burned_unadopted` envelope still live at
upgrade time also consumes under the sentinel, unbound. The
production path is currently safe; the PREDICATE's default is
not. A load-bearing binding should fail closed: default `""`
(enforced mismatch → primary-shaped → refusal), with the v1
migration case, if it is wanted at all, as an explicit named
argument at the one migration call site. As shipped, the next
direct caller of this ledger API silently re-opens the
unbound-recovery shape cycles 21–22 spent two war rooms closing.

## F4 — MEDIUM: cap-2's reconciliation story is honest in the design and unfinished in the record — do not let it be quoted as ratified

Interrogation (3) from the brief, answered: the cycle does NOT
claim GPT ratified cap-2. DESIGN-FINAL R3 flags the change
explicitly ("seat-gpt ratified one-shot, so the brief must flag
the change explicitly"), code comments consistently say
"Addendum 3 (pending)", and GPT's CROSS-CHECK-16 concurrency
condition (exactly one consumption lands for two authorisations
bound to the same burn) is preserved in the re-pinned race test,
which also pins the fresh-recovery-at-depth+1 follow-on. Gemini's
demanded schema lineage is genuinely delivered. That part of the
story is honest.

What is NOT done at review time:
- `internal/DECISION-CONSUMPTION-HEAD.md` still ends at Addendum 2
  ("recovery is ONE-SHOT") — the authoritative decision record in
  the tree contradicts the code it governs.
- There is no `internal/BUILD-CYCLE-23.md` yet, so R3's "Addendum 3
  records this" and R5's "recorded in BUILD-CYCLE-23" are
  promises, not records.
- The external brief asking the seats to ratify the re-rule has
  not been sent (both seats are recorded vacant/provisional).

Ship must be gated on: Addendum 3 written, the brief sent with
the one-shot→cap-2 change AND the F1 supersede flagged as a
second, separate re-rule (bundling them into one "cycle 23"
question would let supersede ride on cap-2's much stronger
case), and the cycle recorded as provisional until both seats
answer. Note the asymmetry the brief must state plainly: GPT
ratified one-shot 0.91 with the concurrency condition; cap-2 is
a DIFFERENT bound than the one approved, and depth-2 exists to
cover "one full incident's double fault" — a rationale neither
external seat has seen.

## F5 — LOW-MEDIUM: "production integration" is still one step removed everywhere it matters — wording is honest in the texts read; keep it that way

Interrogation (4)/(5), answered with traces:
- The live run (R1) runs against a byte COPY of `state/`, a
  DISPOSABLE verifier home, a FRESH sandbox snapshot key, and an
  EMPTY pin store (genesis `initial_anchor` at seq 13). No real
  pin store exists to adopt into; the real verifier home has
  never run in production mode; the real snapshot signer has
  never signed an adoption. The sha256-before/after assertion
  proves the real state was NOT touched — which is the correct
  safety posture and simultaneously the proof that nothing has
  run in situ. `tests/test_cycle23_live_run.py`'s docstring says
  all of this accurately ("byte copy", "sandbox", "disposable").
- WS5's real anchors are a real act against the real ship
  ledgers, and the tripwire test is a genuine currency check.
  But the anchors sit in `state/anchors/` in the same repo on
  the same disk, and at review time the tree is UNCOMMITTED —
  DESIGN-FINAL's "joint ledger+anchor rollback is then
  detectable against git history" is not operative until the
  commit lands, and a rollback to baseline deletes the anchors
  outright (detectable only as absence, via the tripwire's
  missing-anchor failure). The claim wording in
  `trust/shipcheck.py` and the anchor tests stays inside the
  cap ("outside the ledger dir"; no "outside writable storage"
  claim found in production code or test names — this seat
  grepped). R5's own completion claim is correctly scoped.
- Residual, not overclaim: `anchored_record_ship` has never
  recorded against the real ledgers, and per R5's three reasons
  cannot until cycles 14–16 clear external re-review. So the
  honest cycle-23 claim is "every production path has now been
  exercised end-to-end exactly once, in composition, against
  stand-ins for every credential, home, and store it will meet
  in production." Any shorter version ("production integration
  done") overclaims.

## F6 — LOW: `authorise_pending` (R4) — the brief's misread scenarios mostly do NOT hold; two small residuals

Traced through `trust/pin_adoption.py` (`_journal_ceremonies`,
`_unadopted_burns`, `_retained_current_candidate`,
`_retained_candidate`, `_find_unadopted_burn`):
- Phase merging is per `ceremony_id`, and `_reanchor` mints
  `pin-adopt-<seq>-<uuid4 hex[:12]>` per attempt, so a pending
  line for a ceremony that later completes under a DIFFERENT id
  cannot merge phases or fields with the completing ceremony.
- `_unadopted_burns` requires an `authorised`/`consumed` phase;
  a pending-only slot is excluded. `_retained_*` additionally
  require a `candidate_envelope`, which the pending line does
  not carry. The R4 pin ("pending with no authorised line →
  fresh primary next attempt") is correctly implemented and
  test-pinned (crash suite scenario 2). This objection does
  not hold; recorded so the room does not have to re-derive it.
Residuals worth one line each in the record:
- The pending append in `_reanchor` is NOT wrapped: an OSError
  from `_append_journal` propagates raw, bypassing the
  PinAdoptionRefused typing and `pin_cycle_hook`'s
  `.cycle_entry` attachment — a small crack in R1's "cycle
  recorded, pin pending, alert" contract, which keys the alert
  payload off those two exception types.
- Pending-only lines accumulate without bound on repeated
  authorise failure (the journal is never pruned). Pre-existing
  pattern for other phases; the new phase makes failed attempts
  — previously journal-silent — permanent residents.

## Re-pin audit (brief item 1) — summary

- `test_trust_ceremony_consume` old-pin-behind-head: faithful pin
  of the supersede code change; also pins the non-supersede shape
  still refuses. Legitimate as a pin; the SEMANTICS are F1.
- `CheckHeadTests` third block: same; adds fork-at-head refusal.
  Faithful.
- T8′ third leg (`test_signing_pin_ceremony`): the most
  consequential re-pin of the three. It converts a cycle-20
  verifier-side refusal into a consumption that lands, and
  relocates the safety argument to a different component's
  tests in a different file. The docstring is candid about this
  ("At this raw library level the would-be regressed pin is
  returned"). Candour is not ratification: this is a semantics
  change to a pinned security behaviour, taken in the fix round.
- The cap-2 re-pins (OneShotRecoveryTests,
  `test_recovery_is_bounded_second_lands_third_refused`) are the
  legitimate kind: they follow DESIGN-FINAL R3 exactly, cite the
  (pending) addendum, and preserve GPT's concurrency condition.

## What does NOT block (dissent seat's honest negatives)

- Schema v2 mechanics: dual key sets, positional monotonicity,
  value validation, v1 never rewritten, lineage derived inside
  the retry loop from fresh entries — all as designed; the race
  test shows exactly-one-success.
- R1 hook placement: hook fires after the persistence try/except,
  exactly once, idle never fires, exceptions unwrapped;
  `record_ship` and `run_one_cycle_and_pin` both refuse hooked
  loops. As designed.
- R4 crash coverage: scenarios 1 and 7 are true subprocess
  SIGKILL/barrier tests; surgery cases are labelled as surgery.
- WS5 currency requirement: a merely-verifying stale prefix
  anchor refuses pre-burn; the derivation-from-anchor design
  has no caller-head input to override it.

## Required before SHIP

1. F1: narrow supersede to the provably-terminal head (derived
   depth == MAX) or take the broader rule to a designed ruling +
   external brief as its own question. Re-pin T8′ accordingly.
2. F2: record both fix-round production changes (client pin
   namespace, supersede) in BUILD-CYCLE-23 as findings with
   dispositions; state plainly that cycle 22's adopter had
   never completed a production ceremony before this cycle.
3. F3: make the binding fail-closed by default, or record an
   explicit ruling accepting the sentinel and its v1 scope.
4. F4: write Addendum 3; keep the cycle provisional until both
   external seats ratify cap-2 (and, per 1, rule on supersede).

Verdict: **FIX, 0.64.** The designed core of cycle 23 (R1 hook,
schema v2 lineage, crash coverage, anchored recording path) is
sound and, in the texts this seat read, honestly claimed. The
cycle should not ship carrying an undesigned verifier-side
relaxation of the consumption head — the exact class of change
this war-room process, and rev-r6's cycle-22 F1 before it,
exists to catch.
