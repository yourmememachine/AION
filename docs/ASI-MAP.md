# ASI Map — How We Complete The Task

Goal (Dilip): ASI is the goal. Bring the AI that would exist in 2036 into
2027. Keep updating, thinking and planning about the future, every hour.

## What "ASI" means here — the scorecard we measure, not a slogan
A system counts as ASI-like only as it earns these, measured:
1. Autonomous research — finds, reads, debates and synthesises new knowledge alone
2. Autonomous building — plans, codes, tests and ships real products alone
3. Self-improvement — improves its own prompts, tools, memory and code, with a
   measured delta (metric, baseline, after, evidence, independent verifier)
4. Long memory + world model — remembers across months, predicts consequences
5. Action with guardrails — uses tools, browser, chain and (later) robots,
   blocked by safety gates, never free to spend or harm

Every hourly update reports this scorecard: % per capability, tests, verdict.

## The map — phases, each with an exit gate
- P0 Foundation (NOW, Nov 2026): never-stop loop, 3-coder gate, 6-reviewer
  war-room gate, persistent state. Exit: loop + tests green. [36 tests, done]
- P1 Memory + Benchmarks (Nov–Dec 2026): long-term memory store, frozen
  benchmark suite (coding, research, reasoning, self-improvement delta).
  Exit: same task run twice scores better the 2nd time, from memory alone.
- P2 Tool Agents (Dec 2026): browser, code, files, search as safe tools with
  permission gates. Exit: agent completes a multi-step real task end-to-end.
- P3 Research Agent (Jan 2027): scans the future hourly, debates findings
  (15 seats), updates the roadmap itself. Exit: its roadmap changes are
  cited, debated and survive war-room review.
- P4 Self-Improvement Engine (Jan–Mar 2027): agents propose changes to
  themselves, test on frozen benchmarks, keep only verified gains.
  Exit: 3 consecutive months of measured benchmark gains, no regressions.
- P5 World Model + Multimodal (Mar–Jun 2027): vision, voice, prediction of
  outcomes before acting. Exit: predicts tool/action outcomes better than
  the no-world-model baseline on a held-out set.
- P6 Real-World Integration (2027): acting through ordinary tools and
  services with guardrails and human approval for consequential actions.
  No blockchain, no crypto anywhere in AION — it is fully independent.
  Exit: agent pays, is blocked on a bad launch, logs everything on-chain (test).
- P7 Physical (mid–late 2027): connect to the 4-foot robot — perception,
  voice, safe action. Exit: robot completes a spoken multi-step task safely.
- P8 ASI Candidate (late 2027): whole system given a brand-new goal it has
  never seen: research → plan → build → test → ship → learn, no human coding.
  Exit: passes on 3 unseen goals in a row, scorecard published.

## Cross-cutting tracks — added 2026-11-19 after external critique review
The critique was checked and accepted in substance. These tracks run in
EVERY phase, not at the end:
- X1 Scalable oversight: as capability grows, oversight grows with it.
  Any self-modification, tool permission, or payment capability above the
  current tier needs extra reviewers + a dedicated red-team seat, and a
  human (Dilip) gate for tier jumps. No silent capability escalation.
- X2 Anti-gaming evaluation: benchmarks are split — a frozen public set the
  builders may see, and a SEALED held-out set they may not (hash-locked,
  rotated, access-logged). A gain counts only if it appears on the sealed
  set too. Memorised/gamed gains are rejected.
- X3 Self-modification safety: every self-change must pass (a) the full
  regression suite — no benchmark may go down, not just the target one,
  (b) a forgetting check on old capabilities, (c) a reward-hacking check
  by a verifier who did not build it, on sealed data. One failure = revert.
- X4 Calibration, not consensus: the 15 record independent scores BEFORE
  discussion; dissent is preserved in the record, never averaged away.
  Reviewer calibration is tracked against real outcomes, so a seat that is
  confidently wrong loses weight. Consensus without independent evidence
  is treated as no evidence.
- X5 Robustness + contingency: adversarial/distribution-shift tests in
  every phase's exit gate. Calendar is a target, not a forcing function:
  if a phase exit fails twice, the weekly war room must pivot the approach
  or extend that phase — it may not lower the gate to meet the date.
  External red-teaming is required before P6 (money) and P7 (robot) unlock.

P4 exit is amended: gains must hold on the sealed set, with zero regressions
on any benchmark, for 3 consecutive months. P8 is a candidate bar, not ASI
itself: true ASI would need broad competence across domains, tested on
sealed tasks from domains the system was not built for — added to P8.

## How the 15 work, continuously
Hourly cycle: Scan (2,6,7,15) → Build, 3+ coders (rotating) → War room,
6 reviewers, blind then reconciled → Fix + verify → Self-improve record →
Ship/record. Next hour starts from state, never from zero.
Daily: roadmap re-plan — Future pod re-scores the scorecard, re-ranks backlog.
Weekly: strategy war room — is this still the fastest path to ASI in 2027?
Kill what is not measuring up.

## Honest limits that shape the plan
- We do not train a frontier model from scratch first — no compute/budget for
  that, and it is the slowest path. Our system uses the best available models
  as brains; our edge is the loop, memory, self-improvement and guardrails
  around them. Model training/fine-tuning comes later if gains demand it.
- True ASI is not proven by anyone. We publish the scorecard so progress is
  verified, never claimed.
- Safety gates are part of ASI, not a brake on it: no real assets, no
  spending, no public push without Dilip's word and the war-room pass.

## Completion condition
Task is complete when P8 passes: 3 unseen goals in a row, end-to-end,
with measured self-improvement — and the scorecard is public.
Until then: hourly development, hourly updates, no stopping.

## Planning under uncertainty (added 2026-11-19, after external feasibility review)

The review's verdict, accepted: P0–P5 and the integrity machinery are
high-probability; the full P9 threshold by Dec 2027 is low-probability;
true ASI in 2027 is very low probability for anyone. We plan for that
honestly instead of planning as if the calendar were a promise:

1. **Two spines, both must pay off.** Capability spine (P0–P9) and
   integrity spine (sealed eval, factory, gates, calibration). The
   integrity spine is the highest-probability value in the project —
   every cycle keeps it shippable as a product in its own right, not
   just scaffolding for later phases.
2. **Every phase exit ships something usable on its own** (e.g. memory
   that measurably helps, a research agent that proposes cited roadmap
   changes). If P9 slips, 2027 still delivers working systems, not a
   half-finished moonshot.
3. **De-risk late phases early, cheaply.** P6 world-model: benchmark
   prediction against baselines in simulation long before it gates
   anything. P7 economic agency: testnet/test amounts only, external
   red team first (already required). P8 physical: simulation and a
   written safety case before any hardware spend is even proposed.
   Failures must surface in early 2027, not late 2027.
4. **Graded P9.** The threshold is scored in levels: 1 unseen goal,
   then 2, then 3, with domain novelty graded. A level honestly passed
   is published as that level — never rounded up to the full bar.
5. **Effort follows compounding.** Most cycles go to P3–P5 (tool
   agents, research agent, self-improvement), where gains compound.
   Later phases get scoped, timeboxed spikes until their early
   benchmarks say they deserve full cycles.
6. **Quarterly external calibration.** The scorecard and phase claims
   go to outside reviewers at least quarterly; their probability
   assessments are recorded in the calibration log like any other
   prediction, and scored when outcomes land.
7. **Dates stay attempt dates.** If a gate is not met, the phase
   extends or pivots — the gate is never lowered, and the slip is
   published on the scorecard with the reason.
