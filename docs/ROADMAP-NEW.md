# New Roadmap — AION: ASI in 2027 (working title; ASI claim provisional — see v4)
Updated 2026-11-19 (v4, after three external critique rounds + Dilip's 15-coder order)

Goal: ASI — the AI that would exist in 2036, in 2027.
Repo: ai (yourmememachine/ai, local until Dilip says create it)
Independent project — no blockchain, no crypto. Separate repo.

## Team — all 15 are coders, 5 pods of 3
- Pod A Foundation (1 Chief, 5 Model Builder, 8 Compute): core loop, infra, speed
- Pod B Memory & World (2 AGI Science, 6 World Models, 7 Spatial): memory, world model, vision
- Pod C Agents & Tools (9 Coding Agents, 10 Framework, 11 Open Models): agent system, tools, open models
- Pod D Safety & Eval (3 Safety, 4 Scaling/Eval, 15 Future & Risk): sealed eval, oversight, calibration, red team
- Pod E Action (12 Robotics, 13 Voice, 14 Product): real-world action, voice, robot, product
War room: 6+ reviewers per slice, drawn from other pods — nobody reviews own work.
Cadence: 1 build cycle every hour, update to Dilip every hour, no stopping.
Daily re-score, weekly strategy war room (pivot or extend a failing phase — never lower a gate).

## Scorecard (reported hourly)
Research / Building / Self-improvement / Memory+World / Action+Guardrails — % each, with evidence.

## Phases
### P0 Foundation — DONE Nov 2026
Loop, gates in code, persistent state. 36 tests green.
### P1 Trustworthy Evaluation — Nov–Dec 2026 (building now, cycle 2)
Sealed held-out benchmarks (hash-locked, builders cannot see), public frozen set,
self-improvement safety gate (no regression anywhere + forgetting check +
independent verifier), calibration log (independent scores before discussion).
Exit: a fake/gamed "gain" is caught and rejected by the gate in tests.
### P2 Memory That Works — Dec 2026
Long-term memory store, retrieval, memory writes gated against poisoning.
Exit: same task scores better 2nd time from memory alone, on sealed tasks.
### P3 Tool Agents — Dec 2026–Jan 2027
Browser, code, files, search — permission-tiered tools (X1 oversight tiers).
Exit: multi-step real task end-to-end alone, every action logged and reversible where possible.
### P4 Research Agent — Jan 2027
Hourly future scan, cited synthesis, debates among pods, proposes roadmap changes.
Exit: 10 roadmap proposals, at least half survive war room with citations checked.
### P5 Self-Improvement Engine — Jan–Apr 2027
Agents change own prompts/tools/code; X3 gate keeps only sealed, no-regression gains.
Exit: 3 consecutive months of sealed gains, zero regressions. If not met: pivot per X5, do not fake it.
### P6 World Model + Voice/Vision — Mar–Jun 2027
Predict outcomes before acting; voice and vision in the loop.
Exit: beats no-world-model baseline on sealed, held-out prediction tasks.
### P7 Real-World Agency — Jun–Sep 2027
Acting through ordinary tools and services (no blockchain, no crypto): approvals for consequential actions, spending limits set by Dilip, full audit log. External red team FIRST (X5).
Test amounts only until audit. Exit: agent pays correctly, is blocked on a bad
launch, everything logged on test chain.
### P8 Physical Agency — Sep–Nov 2027
Connect to the 4-foot robot (bench brain first, per robot Phase 1).
Red team + safety case first. Exit: spoken multi-step task done safely, e-stop proven.
### P9 ASI Candidate Test — Dec 2027
3 unseen goals in a row, from domains the system was not built for:
research → plan → build → test → ship → learn, no human coding.
Pass = ASI-candidate scorecard published, honestly, whatever the result.
Fail = the scorecard says where, and the loop continues into 2028 on the same map.

## Cross-cutting, every phase (X1–X5)
X1 Oversight scales with capability; tier jumps need Dilip's gate.
X2 Sealed anti-gaming evaluation. X3 Self-mod safety (regression + forgetting + independent verifier).
X4 Calibration over consensus; dissent preserved. X5 Adversarial tests + contingency:
calendar is a target, gates are not negotiable.

## v3 — Operational mechanisms added 2026-11-19 after second critique review
Accepted: sealed tests alone are not enough, X3 is the highest risk, and
P9 is an agent test, not a full ASI test. Now operational, not just listed:
- Adversarial Test Factory (Pod D, continuous): a generator pod creates NEW
  sealed tests every cycle from shifting distributions — builders never see
  them, old sealed sets are retired on a schedule, and any cycle where the
  public-vs-sealed gap widens is flagged as gaming, not gain.
- External red team: independent (non-team) review is mandatory before any
  capability tier jump, before P7 payments and before P8 physical — and on
  a recurring schedule once P5 self-improvement is live, not only at gates.
- Protected Gate Rule (hard, in code from cycle 3): the system may NEVER
  modify its own evaluator, safety gate, calibration log or oversight code.
  Those files are outside self-modification scope; changing them requires
  Dilip's explicit approval + external review. A system that can edit its
  own judge can fake any gain — so it can't.
- Self-mod budget + canary: self-changes are small, one at a time, run first
  in a sandbox/canary against sealed tests, with instant rollback to the
  last verified state. No batch self-rewrites.
- Verifier strength rule: the verifier ensemble must be independent of and
  differently-built from the builders; as builder capability rises, human
  spot-checks by Dilip on random sealed cases are added — oversight scales
  (X1) instead of trusting the log alone.
- Dates are attempt dates, not promises: each phase starts when the previous
  exit passes, however long that takes. P9 in Dec 2027 is when we RUN the
  test, not a guarantee we pass it.

## v4 — Scale, drift, framing, dissent (added 2026-11-19, third critique)
1. Team scale vs scope: 15 is the CORE team, not the whole workforce.
   Each pod may spawn specialised sub-teams for its slice (test writers,
   adversarial generators, researchers) — core 15 own design, integration
   and accountability. Hard problems do NOT run on hourly cadence alone:
   world models, long-horizon agency and self-mod safety get multi-day
   DEEP SPRINTS (one pod, one problem, no hourly shipping pressure), with
   written handoffs so rotation never loses depth. Coordination is via
   pod leads + the persistent state/backlog, not meetings.
2. Subtle self-mod failures, now monitored:
   - Value drift: a GOLDEN SET of original baseline tasks/values is never
     retired; every self-mod cycle re-runs it. Drift beyond a set band = alarm + revert review.
   - Off-distribution capability: sealed tests are drawn from rotating
     distributions (Test Factory), plus periodic "wild" tasks from real
     use, so capability that only exists outside the sealed set is seen.
   - Verifier correlation: verifier seats ROTATE and are periodically
     replaced with fresh, differently-prompted verifiers; a verifier whose
     scores correlate too strongly with builder outcomes is retired.
3. Framing (honest): "ASI in 2027" is the aspiration and working title.
   The measurable milestone is the AUTONOMOUS AGENT THRESHOLD (P9).
   No public ASI claim is made unless a broader, externally-reviewed test
   (multiple domains, recursive improvement, independent evaluators) is
   passed. Internally we aim at ASI; externally we claim only what the
   scorecard proves.
4. Calibration made mechanical:
   - Forced dissent slot: in every war room, at least one reviewer is
     ASSIGNED to argue against shipping, with their best case, before any vote.
   - Independent scores are locked in writing before discussion (already in X4, now enforced in the loop record).
   - Minority tracker: dissenting predictions are logged with dates and
     scored when outcomes arrive; reviewers whose minority views prove
     right gain weight, and their dissent patterns are studied, not buried.

## Biggest risks, owned openly
Self-improvement gaming, long-horizon drift, memory poisoning, consensus illusion,
sim-to-real gap, payment risk. Each has a pod owner (D for eval/oversight, B for
memory, E for physical/payment) and a test in its phase exit — not a hope.
