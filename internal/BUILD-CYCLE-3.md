# INTERNAL — Build Cycle 3 Record (do not publish)

Scope: Adversarial Test Factory (queued at the end of cycle 2) —
sealed tests continuously generated from shifting distributions,
old generations retired by rotation, public-vs-sealed gap widening
flagged as suspected gaming. This advances P1 (Trustworthy
Evaluation) toward its exit and builds the X2/X5 machinery P2 will
depend on. Phase check against the map: P1's exit (a gamed gain is
caught) was met by cycle 2's gate; the factory is the remaining
named P1-era mechanism in the roadmap v3 section, so it is still
the fastest path — no map change this cycle.

## Staffing — all 15 seats, 5 pods of 3 coders
- Pod A Foundation (1 Chief, 5 Model Builder, 8 Compute):
  integration slice — eval/__init__ exports, determinism check of
  seeded generation across repeated runs, suite integration.
- Pod B Memory & World (2 AGI Science, 6 World Models, 7 Spatial):
  item-family slice — sequence, nth-word and largest families,
  prompt wording kept unambiguous, 1-indexed nth-word.
- Pod C Agents & Tools (9 Coding Agents, 10 Framework, 11 Open
  Models): registrar slice — register_batch / retire_generation
  over the registry API, metadata-only returns, rotation as the
  only retirement path the registry allows.
- Pod D Safety & Eval (3 Safety, 4 Scaling/Eval, 15 Future & Risk):
  factory core + gap semantics — generate_batch, distribution
  shift by generation, assess_gap. Code authors of record for the
  cycle gate: seat-3, seat-4, seat-15.
- Pod E Action (12 Robotics, 13 Voice, 14 Product): adversarial
  slice — stale-answer replay after retirement, duplicate
  registration, bad-actor and bad-input cases, test plan.
- Coordinator: froze the contract, wrote eval/factory.py and
  tests/test_factory.py from the pods' slices, ran the suite.

War room: 6 reviewer seats drawn from pods other than the code
authors (A, B, C, E seats), blind first, one assigned dissent seat,
reconciled to one fix list — see REVIEW-CYCLE-3.md.

## Scope built
- eval/factory.py: 7 item families; deterministic batches
  (seed, generation, count); active family window rotates with
  generation; numeric ranges and string/list sizes grow with
  generation; register_batch returns registry metadata only;
  retire_generation rotates a generation's ids to fresh content
  from a different seed; assess_gap flags public-only gains and
  gap widening, and notes sealed regressions separately.
- eval/__init__.py: factory exports added.
- tests/test_factory.py: 21 tests as built (determinism, shift,
  independent answer verification per family, registry
  integration, retirement replay, gap cases, input validation).
- Full suite as built: 144 tests, all passing before the war
  room. The war room's reconciled fix list and the late-report
  addendum added code fixes (pre-flight batch checks, explicit
  retirement seed, sealed-regression precedence, determinism
  pin, wrong-seed retirement detection, full family coverage in
  the answer test) and further tests: final suite 160 tests,
  all passing (factory file: 35). See REVIEW-CYCLE-3.md,
  including its count-correction addendum.
- State: this cycle IS recorded in the core loop (item
  adversarial-test-factory, loop cycle 2 — the loop's sequence is
  one behind the build-cycle numbering because cycle 2 was never
  entered; that gap is the paper-trail backlog item, not a
  renumbering). Calibration blind scores for cycle-3-build are
  locked, discussed and scored in state/calibration.

## Honest limits (stated in the module docstring, not hidden)
- The factory knows the answers it generates: it is verifier-side
  only. Whoever holds the seed can regenerate a batch — seed
  custody is a process rule, not enforced by this code.
- assess_gap judges numbers only; a public-only gain can be genuine.
  It flags for reviewers, it does not convict.
- Retirement is rotation: item ids and domains persist, content is
  replaced. There is still no sealed deletion in the registry.

## Bookkeeping debt found this cycle (recorded, not hidden)
Cycle 2's code and tests shipped (119 green) but its CoreLoop state
entry was never recorded and its review record still carries an
open verification placeholder. Cycle 3 records its own state entry
through the core loop; closing cycle 2's paper trail is queued as
a backlog item rather than silently backfilled.

## Queued for cycle 4 (not built)
- P2 start: long-term memory store with gated writes (poisoning
  checks), retrieval, and the same-task-twice sealed improvement
  test that is P2's exit.
- Cycle-2 paper-trail closure (state entry + review record).
- Commit–reveal for calibration timing proof (deferred since cycle 2).
