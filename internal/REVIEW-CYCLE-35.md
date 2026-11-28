# REVIEW — CYCLE 35 (lead's own bug-hunt pass)

Verdict: PROVISIONAL. External seats (Claude, ChatGPT,
Gemini) have not yet scored this cycle; blind brief at
internal/CROSS-CHECK-BRIEF-CYCLE-35.md. Under Dilip's
2026-11-28 rule the cycle ships on a 0.95+ seat score; the
engineering bar applied during the build was the full
acceptance spec regardless.

Method: attack the implementation where the designs said it
would break — ambiguous sequences, zero/negative/float edges,
parser mismatches, normaliser leakage, induction ambiguity,
and per-seed diagnosis of every non-perfect item (no aggregate
accepted without naming its items).

## Real bugs found and fixed
1. CRASH — trap diagnostics ran on word lists.
   self_check_principle called sequence_diagnostics on any list
   payload when a principle carried a ratio_mode; the
   order-inversion queries (word lists) raised TypeError inside
   solve(), breaking the never-raise contract. Found by the
   first smoke run. Fix: diagnostics computed only when the
   payload is a numeric sequence. Pinned by the held-out
   measurement (order-inversion family scores 1.00).
2. Few-shot answer rendering mismatch. The engine rendered
   string values unquoted where the frozen item format quotes
   them; held-out string/list answers would have scored 0
   while being substantively right. Caught by inspection
   before the first run; _render_query now mirrors the frozen
   render exactly.
3. Alternating traps bypassed the guard entirely. The engine
   required the baseline classifier to accept a prompt before
   the guard saw it; the baseline's sequence pattern cannot
   parse negative terms, so alternating-sign traps (and,
   worse, legitimate negative additive sequences) never
   reached the guard. Fix: the engine's own frame parser is
   authoritative. Pinned by tests: a negative additive
   sequence now APPLIES (-14) and the alternating trap is
   refused by the guard with trap_mismatch:
   multiplicative_progression in its codes.
4. FALSE APPLICATION — stored principle coincidence
   (seed set 2, heldout-last, 1 item). All three examples had
   last == max, so the stored max principle passed the sample
   check and fired on a query where last != max: a confidently
   wrong answer — exactly the failure this cycle exists to
   prevent. Fix: the stored/induced cross-check — a stored
   prediction must agree with every shortest program induced
   from the task's own samples, or the engine abstains.
   Pinned by test_coinciding_stored_principle_abstains. The
   item now abstains (family stays 0.95 on that seed; the
   failure mode changed from false application to honesty).

## Attacks that held (no fix needed)
- Ambiguous induction: (drop_first, drop_first, min)
  coincides with second-smallest on all 3 examples of the
  affected items (seed sets 2 and 3, 1 item each) but is a
  genuinely different function. The engine abstains. A
  majority-vote among consistent programs was considered and
  REJECTED: it would void the ambiguity guarantee the unit
  tests pin, and vote-counting among programs is not evidence.
  Recorded as a measured cost of the discipline (family
  0.95 on those seeds), not a defect to engineer around.
- Constant sequence [5,5,5,5]: diagnostics report ambiguous
  (additive and multiplicative); both stored sequence
  principles predict 5, prediction agreement answers it.
- Zeros: [0,2,4,6] — ratios undefined, multiplicative False,
  additive principle applies. Negatives: ratio -2 detected
  exactly. Floats: 9-dp ratio rounding detects 1.0,1.1,1.21,
  1.331 as multiplicative. Short sequences (< 3 terms):
  diagnostics report insufficient data; extrapolators refuse.
- Expression tie: precedence vs left-to-right are consistent
  with all 26 public expression episodes and disagree on
  synthetic probes -> derivation abstains (abstain_tie),
  audit records both candidates. No principle is stored on a
  coin flip.
- extrap_add2 double-consistency: it is consistent with every
  arithmetic episode (second differences are 0). Stored as a
  separate principle under its own precondition; on quadratic
  payloads only it passes the guard, on geometric payloads
  neither sequence principle passes (verified in trap
  metrics: squares solved, geometric refused, 0 false
  applications in 240 trap items).
- Leakage: held-out prompts are unclassifiable by the factory
  classifier (verified); the held-out generator file was
  written before the engine and its sha256 re-verified
  unchanged after all fixes (the fixes touched the engine and
  tests only); derivation input is the public batch alone —
  the measurement's audit contains no held-out or trap family.
- Failure learning: after one recorded failure, the bare
  additive principle (no preconditions) learns const_ratio as
  an excluder and refuses 24/24 fresh geometric instances
  while still applying to legitimate additive tasks.
- Metamorphic: example order permutation does not change any
  answer (induction checks all episodes; enumeration order is
  fixed); the solver never reads item family labels.

## Fix round (post round-1 external review)

External round 1: ChatGPT 0.97 SHIP, Gemini 0.94 SHIP,
Claude 0.88 SHIP with conditions. Dilip's sequence: "Fix n
ship" — the delta lands before the cycle is recorded as
shipped. Full disposition: internal/BUILD-CYCLE-35-FIX.md.
Delta-specific attack notes:

- Agreement gate reach: the gate runs only when NO stored
  principle passed for the shape, so it can never override a
  stored principle's refusal or break a stored competition.
  Verified on the sealed tier: in-distribution stays 1.00,
  and the gate's only shifted-tier trace is the 20 arithmetic
  abstentions per seed (insufficient_evidence), exactly the
  items where the candidates disagree.
- Version-space block, false-block risk: the block fires
  only when a consistent program within the complexity cap
  DISAGREES on the query. Held-out aggregates are unchanged
  (1.00 / 0.99 / 0.995) and the fresh positive families are
  1.00 on all seeds — no legitimate stored firing was lost.
  The cap enumeration runs only when a stored principle
  passed and is longer than the shortest induced program;
  for all derived principles (length 1) it never enumerates,
  so measurement cost is unchanged in the common path.
- Empty-induction block: checked against every existing
  few-shot unit test and both few-shot tiers — no held-out
  or trap item relied on firing a stored principle with an
  empty version space (every legitimately firing stored
  principle's own program is in the vocabulary, hence in
  the space). The one behaviour change is the constructed
  parity case, which is the point of the rule.
- Generic antagonist refactor: trap metrics byte-identical
  to round 1 (0 false applications; geometric/alternating
  refused with the trap code, now produced by extrap_add's
  declared invariant rather than its ratio_mode). Periodic
  traps now show precondition_failed in the taxonomy — a
  reporting difference, not a behaviour difference: they
  were and are refused on invariant miss.
- Contamination handling: heldout35.py untouched (sha256
  re-verified da4096e5…); the fresh generator was written
  and hashed (501e0ff8…) before the measurement code that
  consumes it was run, and it imports only the frozen
  prompt/render helpers from heldout35.

## Residual risks accepted and disclosed
- The primitive vocabulary is hand-built (as was the strategy
  vocabulary before it): transfer is demonstrated across
  presentations within that hypothesis space, not invention
  outside it. The module docstring says so.
- Three examples per few-shot task is a property of the
  frozen format; genuinely underdetermined items abstain.
  More examples would raise second-smallest/last to 1.00 on
  the affected seeds; that is a format decision for a future
  cycle, not an engine change to smuggle in now.
- In-distribution parity is answered by the naive fallback
  (the public generations contain no parity episodes to
  derive from). It is correct, but it is baseline behaviour,
  and the build record says so.
