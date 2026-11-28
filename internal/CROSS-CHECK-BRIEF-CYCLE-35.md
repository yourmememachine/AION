# CROSS-CHECK BRIEF — CYCLE 35 (blind)

You are an external reviewer seat for AION, a local stdlib-only
Python system for self-improving agents. This brief is blind: it
contains the design and the measured results, and no internal
verdicts or scores. All three external designs obtained for this
cycle (Claude, ChatGPT, Gemini) were reconciled into the build;
you are now asked to judge the result.

## Background

Cycle 34 measured out-of-distribution transfer of the existing
strategy-token memory and found: in-distribution 0.20 → 1.00,
shifted tier (same types, extreme ranges) 0.00 → 0.80, brand-new
formats 0.00 → 0.00, and a trap tier (geometric sequences in the
arithmetic-sequence prompt format) at 0.00 — the learned rule
fired and was wrong. Cycle 35 was built to close the two failing
gaps: (1) no transfer to new formats, (2) no protection against
negative transfer.

## What was built

New module memory/principles.py (the engine), new frozen
held-out generators memory/heldout35.py (written and sha256
hashed BEFORE the engine; hash verified unchanged at the end of
the build), new measurement memory/transfer35.py, 37 new tests.

Design (the three external designs converged; the merged form):
- Lessons are principles: a small program over shared
  primitives, the structural invariants that held on every
  positive episode (its preconditions), and excluders learned
  from failures. Features are structural and task-name-free
  (type, length, constant-difference, constant-ratio, second
  differences, monotonicity).
- Derivation clusters public practice episodes by semantic
  shape, never by family name, and stores a program only with
  the preconditions its form requires. Where two consistent
  programs share preconditions and disagree somewhere in the
  shape's domain, derivation abstains on the tie and records it.
- A guard (self_check_principle) runs before any principle
  fires: signature, invariants, excluders, sequence trap
  diagnostics, and agreement with the task's own sample pairs
  when the task carries them. Named failure codes include
  trap_mismatch:multiplicative_progression and
  sample_pair_contradiction. Abstention is a valid result.
- New formats are handled by induction from the task's own
  examples: the shortest primitive program consistent with all
  examples. A stored principle may fire on a few-shot task only
  if its prediction also agrees with every shortest induced
  program; disagreement abstains.
- Refusal never scores worse than the no-memory baseline:
  factory prompts fall back to the naive solver; few-shot
  prompts abstain.
- Principles carry an evidence-derived confidence and a
  canonical sha256 digest of their definition.

Held-out discipline: the ten held-out few-shot families
(smallest, sum, count, word length, last element, descending
sort, order inversion, second smallest, next-geometric,
next-quadratic) exist only in the frozen generator file, which
receives no solver or lesson input; derivation sees only the
public practice batch. Trap families: geometric, squares,
alternating ratio, periodic (factory format), plus geometric
and quadratic few-shot traps.

## Measured results (3 independent seed sets, 20 items/family)

In-distribution (sealed gen-2): 0.20 → 1.00 on all three seeds,
every family 1.00.

Shifted tier: the four lesson families (reverse, largest,
sequence, nth-word) score 1.00 each on all seeds. The fifth
family, arithmetic, scores 0.00 (aggregate 0.80). Diagnosis
offered for your judgement: the public batch's expression
episodes are all of the form (a * b - c), on which operator
precedence and left-to-right evaluation coincide exactly, so
derivation abstained on the tie (audit records both candidate
programs) rather than store a coin flip. The family is the
tier's designated no-lesson control carried over from Cycle 34.

Held-out formats, per family (seed sets 1 / 2 / 3): smallest
1.00/1.00/1.00; sum 1.00/1.00/1.00; count 1.00/1.00/1.00; word
length 1.00/1.00/1.00; last 1.00/0.95/1.00; descending sort
1.00/1.00/1.00; order inversion 1.00/1.00/1.00; second smallest
1.00/0.95/0.95; next-geometric 1.00/1.00/1.00; next-quadratic
1.00/1.00/1.00. Aggregates 1.00 / 0.99 / 0.995. The sub-1.00
items are abstentions, not wrong answers: on those items a
positional program (drop the first two elements, take the min)
is consistent with all three examples but disagrees on the
query, so the evidence genuinely underdetermines the task and
the engine abstains. (On seed set 2 one last-element item was
initially answered wrongly by a stored principle whose samples
coincided with the true rule in every example; the
stored/induced cross-check above was added in response, and
the item now abstains.)

Trap tier (factory format): safe handling 1.00 on every family
and seed — zero false applications anywhere. Geometric,
alternating and periodic items are refused by the guard and
fall back to the baseline (end-to-end 0.00, equal to the
no-memory baseline). Squares items are answered correctly
(end-to-end 1.00) by a second-difference principle derived
from the public arithmetic-sequence episodes, whose
precondition (constant second difference) the squares satisfy
and the other traps do not.

Few-shot traps: geometric and quadratic both 1.00 end-to-end
on all seeds, zero false applications; the additive principle
is refused by the sample-pair check and the correct program is
induced.

Guard calibration: false-refusal rate 0.00 across 400
legitimate items per seed set (a refusal counts only if the
bypassed program would have answered correctly and the final
answer was wrong). The no-memory control reproduces the naive
baseline per family by exact correct counts on both factory
tiers; memory-on is never worse than memory-off on any tier.

Full test suite: 1,918 baseline + 37 new tests; result in the
build record.

## Questions

Q1. Score the memory leg as it now stands (0.00–1.00) and give
your verdict for the cycle: SHIP or FIX, with the fixes you
require, if any.
Q2. Is the arithmetic diagnosis acceptable — derivation
abstaining on a genuinely indistinguishable tie — or do you
require a different treatment of that family?
Q3. Are the second-smallest abstentions the correct behaviour
for genuinely underdetermined examples, or should the engine
prefer the majority prediction among consistent programs?
Q4. Is answering the squares trap via the derived
second-difference principle legitimate transfer, or does it
blur the trap tier's meaning?
Q5. Does the stored/induced cross-check adequately close the
coincidence hole (a stored principle whose sample agreement is
accidental), or is more required?
