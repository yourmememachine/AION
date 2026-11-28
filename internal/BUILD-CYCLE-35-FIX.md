# BUILD CYCLE 35 — FIX ROUND (delta on commit ae68b00)

**What this round is:** the post-round-1 improvement delta for
Cycle 35, implementing every condition the three external
seats attached to their round-1 verdicts, plus the honest
record corrections one seat required. Blind round-2 brief:
internal/CROSS-CHECK-BRIEF-CYCLE-35-R2.md. Parent record:
internal/BUILD-CYCLE-35.md (see its ADDENDUM).

**STATUS: SHIPPED (2026-11-28).** Final scores — Round 1:
ChatGPT 0.97 SHIP, Gemini 0.94 SHIP, Claude 0.88 SHIP with
conditions. Round 2 (on this fix round): ChatGPT 0.99 SHIP
(all conditions discharged, no fixes required), Claude 0.95
SHIP (in the 0.95–0.99 band; three documentation fixes
requested before closing — applied in the closing section
below). Gemini's round-2 score was not obtained (its
sign-in stalled on phone verification); the owner shipped
on the two in-band round-2 seats plus Gemini's round-1
SHIP. Full ship record: internal/CROSS-CHECK-35.md.

**Ship sequence (Dilip, 2026-11-28):** round-1 verdicts as
above; two scores sat below the 0.95 ship band. Dilip first
directed "Ok ship", then corrected it the same day
(12:57 CST) to **"Fix n ship" — fix first, then ship** —
hence this round. After the round-2 scores landed he
directed **"Ship it" (13:12 CST)** and the cycle shipped.
Ship rules unchanged: 0.95+ seat score ships; engineering
standard is the full spec, no scope trimmed.

## Changes
- memory/principles.py (modified):
  - Agreement-gated answering: derive_principles now returns
    tied_groups (shape, candidate programs, shared
    preconditions) for clusters where derivation abstained on
    a tie; the audit records agreement_gated: true. The
    engine evaluates every tied candidate on the item: all
    agree → APPLY with source "agreement_gate"; disagree →
    code agreement_gate_disagreement and the usual fallback.
    Derivation still stores no principle on a tie.
  - Version-space cross-check (_version_space_block): a
    stored principle on a few-shot task is blocked when
    (a) induction finds NO consistent program within the
    search bound — sample agreement alone never fires it;
    (b) a shortest induced program predicts differently on
    the query; (c) any consistent program no more complex
    than the stored program (longest program among the
    passed principles sharing the prediction) predicts
    differently on the query. Blocks carry the codes
    no_consistent_program / stored_induced_disagreement /
    version_space_disagreement.
  - Generic invariant conflicts: the trap_mismatch:* codes
    are now generated from the invariant framework — a
    required invariant that fails while its registered
    antagonist holds (diag_additive ↔ diag_multiplicative,
    const_diff ↔ const_ratio) — replacing the branch on the
    principle's ratio_mode. ratio_mode remains as descriptive
    metadata (it is part of the principle digest). The guard
    contains no branch on any principle's identity, program
    or type.
  - Every assessment now carries refusal_category (None on
    APPLY): insufficient_evidence, no_consistent_program,
    precondition_failed, trap_refused, evidence_contradiction,
    unparseable, no_principle_available, induction_disabled.
- memory/heldout35fresh.py (new, FROZEN): six fresh few-shot
  families for cross-check re-measurement (fresh-last,
  fresh-secondmin, fresh-nextgeo, fresh-count, fresh-coincide,
  fresh-degenerate). Written and hashed BEFORE the fix-round
  measurement ran. sha256
  501e0ff863761bbe7ef01c22232e333b22fa7a15696d2cbd756d09682c94b6cb
  memory/heldout35.py is untouched (sha256 re-verified:
  da4096e5ff03294b830e37f195369d27553e424772f9be177537e16cfa2d4262).
- memory/transfer35.py (modified): the engine receives the
  tied groups; every tier reports engine behaviour separately
  from headline accuracy (apply / fallback / abstention
  rates, selective accuracy, refusal taxonomy); the trap
  tier's primary metric is stated as false_application_rate
  and trap-squares is additionally reported as a Cross-Domain
  Structural Transfer result with the audit note below; the
  report carries open_gaps (arithmetic) and the
  fresh_crosscheck section.
- tests: +7 unit tests (agreement gate agree/disagree, tied
  groups recorded, ChatGPT's version-space coincidence test,
  empty-induction abstention, degenerate sorted examples,
  trap-code-from-invariants) and +3 measurement tests
  (open-gap + agreement fraction, engine-stats reporting,
  traps split + taxonomy, fresh set) — the arithmetic test
  was reworked from a pinned 0.00 to the computed agreement
  fraction. Total new this round: 10.

## Seat-by-seat disposition

**Claude (0.88, SHIP with conditions):**
- (a) Arithmetic relabelled an OPEN GAP — DONE: addendum to
  BUILD-CYCLE-35.md, open_gaps entry in the measurement
  report, test docstrings and assertions reworked. The audit
  note the seat asked for is in the measurement's
  structural-transfer entry: squares is NOT treated like the
  arithmetic tie because the principles involved carry
  different preconditions (constant first vs second
  difference) and no shared-precondition tie exists, while
  the arithmetic candidates share identical (empty)
  preconditions and differ only in evaluation order.
- (b) Seed set 2 marked contaminated for the cross-check;
  fresh frozen set written, hashed before use, cross-check
  re-measured on it — DONE (results below).
- (c) Agreement-gated answering for tied programs — DONE.
  On the shifted tier the gate abstains on all 20 arithmetic
  items per seed (they are all a + b * c, where the
  candidates disagree; taxonomy: insufficient_evidence), so
  the family remains 0.00 there — reported, not hidden. On
  agreeing forms (a * b ± c, the public/sealed distribution)
  the gate answers directly (unit tests pin both branches).
  Broadening the public practice batch with a discriminating
  episode (the seat's second suggestion) was NOT done: the
  public batch is generated by eval/factory.py, an eval-side
  surface; changing generations to make a family learnable
  is an eval decision for a future cycle, not something this
  delta reaches for. The declared-prior alternative was also
  not taken — no hidden priors.
- Identifiability: addressed in the version-space form the
  seats converged on — beyond query agreement with the
  shortest induced programs, a stored principle must now
  also survive every consistent program up to its own
  complexity (see ChatGPT below). The seat's stronger form
  (examples must distinguish the principle from each close
  alternative) is the same check stated at the query: a
  close alternative that the examples cannot distinguish
  AND that disagrees on the query blocks firing.
- Empty induction must abstain — DONE (rule (a) above;
  pinned by test_empty_induction_never_fires_on_sample_
  agreement: a stored parity principle agreeing with every
  sample no longer fires when no vocabulary program is
  consistent with the examples).
- Degenerate-examples adversarial family — DONE:
  fresh-degenerate (all example lists sorted ascending) plus
  fresh-coincide, and a unit pin. Zero false applications;
  zero applications at all — every item abstained.
- Abstention rate + selective accuracy reported separately —
  DONE for every tier (engine stats block). Selective
  accuracy is 1.0 on every tier and seed: every answer the
  engine actually gave was right; all remaining loss is
  abstention/fallback, now visible as such.
- Q3 check (which cross-check does the code run?): verified
  against the code — the cross-check compares against ALL
  shortest induced programs (the earlier draft's claim) and,
  after this delta, the bounded version space up to the
  stored complexity. The second-smallest abstentions arise
  when a shortest program ties in length with a disagreeing
  one (drop_first/drop_first/min at the same depth as the
  true program), which is why abstention, not preference,
  is the outcome.
- Correlated errors (stored and induced share primitives):
  acknowledged as a residual limit, recorded here rather
  than claimed closed. The version-space check detects
  disagreement among hypotheses in the shared vocabulary;
  it cannot detect a wrong shortcut the whole vocabulary
  shares. Broadening the vocabulary is future work.

**ChatGPT (0.97, SHIP; reservations):**
- Bounded version-space validation — DONE as specified:
  enumerate consistent programs within the documented bound
  (the induction search bound, depth ≤ 3), group by query
  prediction, block the stored principle when a program no
  more complex than it disagrees. The seat's coincidence
  test is implemented verbatim in construction: ≥3 examples,
  stored principle agreeing with all, unique shortest
  induced program agreeing, a longer consistent program
  (drop_first, drop_first, min) disagreeing on the query →
  abstention (pre-fix the engine answered it confidently).
- Abstention taxonomy — DONE: insufficient_evidence and
  no_consistent_program are distinguished, alongside
  precondition_failed, trap_refused, evidence_contradiction
  and the config/input categories; reported per tier.
- Tie resolution on future evidence: derivation is a pure
  function of the public batch, so a future batch containing
  a discriminating episode resolves the cluster at
  derivation time with no code change; nothing about the
  tie is permanently encoded (the audit records candidates,
  not an inability).
- Broader held-out coverage: partially — the fresh set adds
  six families exercising the cross-check paths (including
  two adversarial coincidence families). Wider structural
  coverage (combined transformations) remains future work,
  recorded honestly rather than padded here.

**Gemini (0.94, SHIP; deductions):**
- (-0.03) Named failure codes / sequence diagnostics looked
  domain-specific: the trap codes are now GENERATED by the
  invariant framework from whichever invariants a principle
  declares (antagonist pairs), with no per-program branch —
  a principle whose invariants have no antagonist is refused
  by its invariant alone, with no trap code attached (unit
  test pins this). What remains sequence-specific is
  sequence_diagnostics itself, and that is by design, stated
  plainly: it computes structural features OF THE PAYLOAD
  (constant difference / ratio / second difference), in the
  same category as length or monotonicity, independently of
  any rule — the features are generic even though this
  payload type's mathematics is specific. No measured result
  changed from this refactor (all trap metrics identical).
- (-0.03) Cross-check added after a seed-2 held-out failure:
  acknowledged in the records as post-freeze iteration;
  seed set 2 marked contaminated for the mechanism; the
  mechanism re-measured on the fresh frozen set (below).
- Sub-minimal concern (design note): a strictly simpler
  induced program that disagrees forces abstention — rule
  (b), it is checked first; a stored principle at least as
  simple as the shortest induced fires when all tied minimal
  programs agree AND no consistent program up to its own
  length disagrees — rules (b)+(c) together.

## Re-measured results (3 seed sets, 20 items/family)

No tier regressed against round 1; every round-1 number is
reproduced exactly unless noted.

- In-distribution: 0.20/0.31/0.24 → 1.00 on all seeds.
  Selective accuracy 1.0. (Apply rate 0.74–0.85; the rest is
  baseline fallback on shapes with no derived principle —
  parity and expression items the gate does not cover —
  now categorised no_principle_available instead of silent.)
- Shifted: lesson families 1.00 each, all seeds. Arithmetic
  0.00 = the computed agreement fraction (0 of 20 items are
  of an agreeing form); all 20 items per seed now show the
  gate's abstention in the taxonomy (insufficient_evidence).
  Aggregate 0.80, as before, with the family labelled an
  open gap.
- Held-out formats: aggregates 1.00 / 0.99 / 0.995 —
  identical to round 1. The sub-1.00 items (heldout-last
  seed 2, heldout-secondmin seeds 2–3) are abstentions,
  taxonomy insufficient_evidence; selective accuracy 1.0.
- Traps (factory): primary metric false-application rate
  0.00 — zero false applications; the rate's denominator is
  the items where applying would be wrong: 0/60 per seed,
  0/180 pooled (the 240 pooled trap-tier items include the
  60 squares applications, which are legitimate and are
  reported under Cross-Domain Structural Transfer — see the
  closing section below).
  Refusal taxonomy per seed: trap_refused 40 (geometric,
  alternating), precondition_failed 20 (periodic — refused
  on invariant miss; it satisfies no antagonist, so no trap
  code is attached, which is the generic framework behaving
  as designed). Squares: Cross-Domain Structural Transfer
  end-to-end 1.00, 20/20 correct applications.
- Few-shot traps: 1.00 end-to-end both families, all seeds,
  zero false applications — unchanged.
- FRESH cross-check set (the clean evidence for the
  cross-check mechanism): positive families (fresh-last,
  fresh-secondmin, fresh-nextgeo, fresh-count) at 1.00
  end-to-end on all three seed sets; fresh-coincide and
  fresh-degenerate: 0 applications, 0 false applications,
  40/40 items abstained as insufficient_evidence; selective
  accuracy 1.0; abstention rate 0.333 (exactly the two
  coincidence families).
- False-refusal rate: 0.00 (400 legitimate items per seed).
  Controls reproduce the naive baseline per family by exact
  counts; memory-on never worse than memory-off on any tier.

## Tests
- New this round: 10 (7 unit + 3 measurement).
- Full suite on the final tree: 1,965 tests, OK
  (skipped=28) — the 1,955 of round 1 plus the 10 new, one
  clean run, no intermittents.

## Self-improvement delta
Round 1's lesson was "sample agreement is not applicability."
This round's: an abstention is also a claim, and it must be
auditable — every refusal now carries a category saying which
kind of not-knowing it was, and the one family the system
cannot learn is labelled a gap in the open instead of being
framed as a control after the fact. Second: a mechanism
designed after seeing a failure has contaminated its own
evidence; the honest repair is a fresh frozen set, not a
better story about the old one.

## Closing documentation fixes (Claude, round 2)

Claude's round-2 verdict (0.95, SHIP) asked for three
documentation fixes before the cycle closed. Each was
verified against memory/principles.py before being written
here; this section states only what the code does.

**(a) Complexity unit for the version-space cap, and the
stored-length-vs-bound case.** The cap's complexity unit is
the program length: the number of primitives in the program
tuple (`len(program)` in `_version_space_block`). Programs
in this engine have no macro or compound layer — a stored
principle's program IS its sequence of DSL primitives,
executed directly by `run_program` — so the stored length
is the minimal DSL expansion length, not a count of named
macros. (In the coincidence item, the disagreeing consistent
program (drop_first, drop_first, min) has length 3 and is
caught by rule (c) against a cap of the stored program's
length.) The rules interact with the search bound as
follows: the shortest-program search behind rules (a)/(b)
is bounded at depth 3 (`induce_program(episodes,
max_depth=3)`), but the rule-(c) enumeration is run with
the cap itself as its bound (`consistent_programs(episodes,
max_depth=cap)`). So when a stored program's length exceeds
depth 3, the checked region extends to the stored program's
full length — the cap is NOT silently clipped to the
induction bound. What the guarantee does not cover, by
design: consistent programs LONGER than the stored program
(the Occam cap itself), and programs outside the VALUE_PRIMS
vocabulary. One further behaviour, stated for completeness:
a consistent program that raises on the query (e.g. is
undefined there) is skipped by rules (b)/(c), not counted
as disagreeing.

**(b) False-application-rate denominator.** The factory
trap tier runs 80 items per seed set: geometric 20,
alternating 20, periodic 20 — the items where applying a
learned principle would be wrong — plus squares 20, where
application is legitimate. The false-application rate is
therefore 0/60 per seed set, 0/180 pooled. The 240 pooled
trap-tier total quoted in round-1 and round-2 documents
includes the 60 pooled squares applications; those belong
to the Cross-Domain Structural Transfer result (1.00,
20/20 per seed), not to the rate's denominator. Fresh set:
the two coincidence families (fresh-coincide,
fresh-degenerate) run 20 items each — 40 items per seed
set, 120 pooled — with 0 applications and 0 false
applications (all abstained, insufficient_evidence).

**(c) The agreement gate's guarantee, stated as a
residual.** The agreement gate's guarantee is relative to
the recorded tie set {eval_precedence, eval_left_to_right}:
agreement between the two candidates is consensus, not
correctness. If the true evaluation rule were a third
order, the two candidates could still agree on a * b ± c
forms and the gate's answer would be wrong. This is a
second instance of the correlated-error residual — the
gate validates agreement inside a hypothesis set; it
cannot validate the set itself.
