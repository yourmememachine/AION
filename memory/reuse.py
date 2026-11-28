"""Sealed reuse measurement: the P2 exit test.

Standard library only. One run of run_reuse_measurement():

1. registers a public practice batch (factory generation 1), a
   sealed batch (generation 2) and a golden batch (generation 0) in
   a fresh registry — generations differ because factory batch ids
   depend only on generation and index;
2. scores the sealed set with a memory-less solver (baseline);
3. derives lessons from the PUBLIC items only, and gates each one
   individually through the safety gate (decide_write): the verifier
   side computes per-family sealed maps by regenerating the sealed
   batch from its seed and joining an instrumented scorer's recorded
   responses against it, cross-checked against the registry's own
   aggregate reports — the registry's builder-facing surface stays
   aggregate-only throughout;
4. re-scores the same sealed set with the committed memory;
5. runs two controls — an empty store, and the full store with
   retrieval disabled — which must reproduce the baseline exactly;
6. takes the verdict from the registry's compare_reports with a
   minimum delta on both sets.

Sealed reuse gain shows scores improved on that sealed run. It does
not by itself exclude contamination, baseline gaming, oracle tuning
over repeated runs, or eval-only special-casing. What this harness
does about those, concretely: lessons derive from a public item list
with no registry handle (contamination by construction); the solver
is one frozen implementation across baseline, after and control runs
(baseline gaming would have to be committed code, visible in review);
every sealed evaluation goes through the registry's logged path and
the run reports how many there were (the oracle budget is auditable
for evaluations — the per-family map join below also regenerates
the sealed batch from its seed in-process, and that access is not
an evaluation and is not in the count); the public and sealed
batches are checked for prompt overlap before registration, and
batch seeds are rejected when any active family — present or
absent — falls below the item floor.

The verifier separation in this run is a protocol role, not a
process boundary, stated plainly: run_reuse_measurement is one
function in one process. It holds the sealed batch (prompts and
expected answers) from the start, computes the maps, and constructs
the gate attestation itself, with reward_hacking_checked asserted
by the harness — no independent verifier process exists in this
run and no reward-hacking check code runs; the gate verifies the
boolean is True and consistency-checks the maps it is given. What
the run proves is that the machinery (derivation, gating,
commit, retrieval, measurement) works end to end with the gate's
checks enforced; it does not prove an independent verifier
reviewed these lessons. Seeds are verifier-supplied inputs and
are never returned; whoever holds a seed can regenerate its batch
offline and unlogged — custody is the secrecy, stated not enforced.

One coverage blind spot, by construction: the golden set is a
generation-0 batch, whose active families are arithmetic,
subtract-multiply, reverse, largest and sequence. The gate's
forgetting check therefore never sees nth-word or parity; a lesson
that damaged those families' retained capability would not be
caught by the capability maps (the per-family sealed maps would
still catch a regression on the sealed set itself).

QUARANTINE (Trust Boundary v2): this harness is the legacy
unsigned path — it commits through plain commit_write. It is
reachable only behind run_reuse_measurement's test-only
legacy_test_mode=True switch; the default call raises before any
commit. Production flows must use the signed path.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eval.factory import (
    active_families,
    assess_gap,
    generate_batch,
    register_batch,
)
from eval.gate import VerifierAttestation
from eval.registry import EvalRegistry

from .solver import StrategySolver, derive_lessons
from .store import MemoryStore, decide_write

# The harness's writer identities authored the solver and the
# lessons (builders); the reviewers include the verifier, who is
# never a builder. The registry actor for sealed operations is the
# verifier.
WRITER_IDS = ("seat-9", "seat-10", "seat-11")
REVIEWER_IDS = ("seat-1", "seat-2", "seat-3", "seat-4", "seat-5", "seat-6")
VERIFIER_ID = "seat-3"
LESSON_AUTHOR = "seat-11"
MIN_DELTA = 0.02


class ReuseError(ValueError):
    """Raised when a reuse run cannot be set up honestly."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _family_floor(count: int) -> int:
    return 12 if count >= 100 else max(2, count // 10)


def _check_floor(batch, generation: int, count: int, label: str) -> None:
    """Every ACTIVE family for the generation must reach the floor —
    including a family absent from the batch entirely (0 items)."""
    floor = _family_floor(count)
    tallies = Counter(item.family for item in batch)
    for name, _fn in active_families(generation):
        n = tallies.get(name, 0)
        if n < floor:
            raise ReuseError(
                f"{label} seed rejected: family {name} has {n} items, "
                f"below the floor of {floor}")


class _Recorder:
    """Verifier-side scorer wrapper: records prompt -> response so
    per-family maps can be joined against the held batch afterwards.
    The solver never sees these records."""

    def __init__(self, solver):
        self.solver = solver
        self.responses = {}

    def __call__(self, prompt):
        response = self.solver.solve(prompt)
        self.responses[prompt] = response
        return response


def _per_family_map(responses: dict, batch, report: dict,
                    prefix: str) -> dict:
    """Per-family score map from recorded responses, cross-checked
    against the registry's own aggregate report: if the joined map
    does not reproduce the report's correct count exactly, the
    measurement machinery itself is broken and the run aborts
    (ReuseError) rather than gating lessons on an unverified map.
    The cross-check binds the totals, not the family labels: a
    total-preserving relabelling of the held batch would pass it.
    That is inherent — the registry's aggregate-only surface makes
    a per-family cross-check impossible by design — and it is why
    the held batch must come from the same trusted process that
    registered it."""
    from eval.registry import _normalise_answer
    tallies = {}
    correct_total = 0
    for item in batch:
        slot = tallies.setdefault(item.family, [0, 0])
        slot[1] += 1
        response = responses.get(item.prompt)
        if (response is not None
                and _normalise_answer(response)
                == _normalise_answer(item.expected)):
            slot[0] += 1
            correct_total += 1
    if correct_total != report["correct"] or len(batch) != report["n"]:
        raise ReuseError(
            f"{prefix} per-family map does not match the registry report")
    return {f"{prefix}-{family}": correct / total
            for family, (correct, total) in sorted(tallies.items())}


def run_reuse_measurement(registry_dir, memory_dir, *, public_seed,
                          sealed_seed, golden_seed, public_count=100,
                          sealed_count=100, golden_count=20,
                          legacy_test_mode: bool = False) -> dict:
    """Run the full P2 reuse measurement once. See module docstring.

    Both directories must be fresh: if a registry or memory file
    already exists in either, the run refuses (ReuseError) rather
    than measuring against state it did not create.

    QUARANTINE (Trust Boundary v2): this harness commits through
    the plain unsigned commit_write path — the legacy path. It is
    quarantined behind the test-only switch legacy_test_mode: with
    the default (False) the call raises ReuseError BEFORE anything
    is created, measured or committed. Pass legacy_test_mode=True
    only from tests exercising this harness; production code must
    use the signed path (signing.commit_signed) instead. No
    production entrypoint calls this function.
    """
    if not isinstance(legacy_test_mode, bool):
        raise ReuseError("legacy_test_mode must be a bool")
    if not legacy_test_mode:
        raise ReuseError(
            "legacy unsigned reuse path is quarantined: "
            "run_reuse_measurement commits through the plain "
            "unsigned commit_write path and is reachable only with "
            "legacy_test_mode=True from tests; use the signed path "
            "(signing.commit_signed) in production")
    registry_dir = Path(registry_dir)
    memory_dir = Path(memory_dir)
    if (registry_dir / "registry.json").exists():
        raise ReuseError("registry directory already holds a registry")
    if (memory_dir / "memory.json").exists():
        raise ReuseError("memory directory already holds a memory store")

    public_batch = generate_batch(public_seed, 1, public_count)
    sealed_batch = generate_batch(sealed_seed, 2, sealed_count)
    golden_batch = generate_batch(golden_seed, 0, golden_count)
    _check_floor(public_batch, 1, public_count, "public")
    _check_floor(sealed_batch, 2, sealed_count, "sealed")
    _check_floor(golden_batch, 0, golden_count, "golden")
    overlap = ({it.prompt for it in public_batch}
               & {it.prompt for it in sealed_batch})
    if overlap:
        raise ReuseError(
            "public and sealed batches share prompts; seed rejected")

    registry = EvalRegistry(registry_dir)
    store = MemoryStore(memory_dir)
    for item in golden_batch:
        registry.add_golden_item(item.item_id, item.domain, item.prompt,
                                 item.expected, VERIFIER_ID)
    for item in public_batch:
        registry.add_public_item(item.item_id, item.domain, item.prompt,
                                 item.expected)
    register_batch(registry, VERIFIER_ID, sealed_seed, 2, sealed_count)
    manifest = registry.sealed_manifest_hash(VERIFIER_ID)

    problems = []
    sealed_evaluations = 0

    def run_all(solver):
        """One public + sealed + golden pass with per-family maps."""
        nonlocal sealed_evaluations
        pub_rec = _Recorder(solver)
        pub_report = registry.run_public_evaluation(VERIFIER_ID, pub_rec)
        pub_map = _per_family_map(pub_rec.responses, public_batch,
                                  pub_report, "pub")
        sealed_rec = _Recorder(solver)
        sealed_report = registry.run_sealed_evaluation(VERIFIER_ID,
                                                       sealed_rec)
        sealed_evaluations += 1
        if sealed_report.get("manifest_hash") != manifest:
            raise ReuseError(
                "sealed manifest changed during the measurement run")
        sealed_map = _per_family_map(sealed_rec.responses, sealed_batch,
                                     sealed_report, "sealed")
        gold_rec = _Recorder(solver)
        gold_report = registry.run_golden_evaluation(VERIFIER_ID, gold_rec)
        gold_map = _per_family_map(gold_rec.responses, golden_batch,
                                   gold_report, "golden")
        return pub_report, sealed_report, pub_map, sealed_map, gold_map

    def run_sealed_only(solver):
        nonlocal sealed_evaluations
        rec = _Recorder(solver)
        report = registry.run_sealed_evaluation(VERIFIER_ID, rec)
        sealed_evaluations += 1
        return report

    # Baseline: no memory at all.
    naive = StrategySolver()
    (pub_before, sealed_before,
     base_pub, base_sealed, base_gold) = run_all(naive)
    orig_base_sealed = dict(base_sealed)
    orig_base_pub = dict(base_pub)

    # Lessons from public items only — derivation gets the item list,
    # never the registry.
    derived = derive_lessons(registry.list_public_items())
    committed = []
    lesson_records = []
    for lesson in derived["lessons"]:
        family = lesson["family"]
        fields = {
            "id": f"lesson-{family}",
            "domain": lesson["domain"],
            "kind": "strategy",
            "content": lesson["content"],
            "author": LESSON_AUTHOR,
            "source": "derivation:public-practice-gen1",
            "evidence_ref": lesson["evidence_ref"],
            "proposal_id": f"p2-lesson-{family}",
            "verifier_id": VERIFIER_ID,
            "supersedes": None,
        }
        trial = StrategySolver(lessons_override=committed + [fields])
        _, _, cand_pub, cand_sealed, cand_gold = run_all(trial)
        attestation = VerifierAttestation(
            verifier_id=VERIFIER_ID,
            decision="approve",
            sealed_hash=manifest,
            reward_hacking_checked=True,
            evidence_ref=f"reuse-run:sealed-manifest:{manifest[:16]}",
            attested_at=_now(),
        )
        decision = decide_write(
            entry_fields=fields,
            builder_ids=list(WRITER_IDS),
            reviewer_ids=list(REVIEWER_IDS),
            baseline_public=base_pub, candidate_public=cand_pub,
            baseline_sealed=base_sealed, candidate_sealed=cand_sealed,
            capability_baseline=base_gold, capability_candidate=cand_gold,
            attestation=attestation,
            expected_sealed_hash=manifest,
            verifier_note=(
                "verifier seat-3 — rotated in for this "
                "cycle; the verifier is never a builder"),
        )
        record = {"family": family, "token": lesson["content"],
                  "accepted": decision.accepted,
                  "reasons": list(decision.reasons)}
        lesson_records.append(record)
        if decision.accepted:
            store.commit_write(fields, decision)
            committed.append(fields)
            base_pub, base_sealed, base_gold = cand_pub, cand_sealed, cand_gold
        else:
            problems.append(
                f"lesson for {family} rejected by the gate: "
                f"{', '.join(decision.reasons)}")

    # After: the committed store, retrieval on.
    with_memory = StrategySolver(store=store)
    pub_rec = _Recorder(with_memory)
    pub_after = registry.run_public_evaluation(VERIFIER_ID, pub_rec)
    pub_map_after = _per_family_map(pub_rec.responses, public_batch,
                                    pub_after, "pub")
    sealed_rec = _Recorder(with_memory)
    sealed_after = registry.run_sealed_evaluation(VERIFIER_ID, sealed_rec)
    sealed_evaluations += 1
    if sealed_after.get("manifest_hash") != manifest:
        raise ReuseError("sealed manifest changed during the measurement run")
    sealed_map_after = _per_family_map(sealed_rec.responses, sealed_batch,
                                       sealed_after, "sealed")

    # Controls: empty store, and full store with retrieval disabled.
    with tempfile.TemporaryDirectory() as tmp:
        empty_store = MemoryStore(Path(tmp) / "empty")
        control_empty = run_sealed_only(StrategySolver(store=empty_store))
    control_disabled = run_sealed_only(
        StrategySolver(store=store, retrieval_enabled=False))

    verdict = registry.compare_reports(pub_before, pub_after,
                                       sealed_before, sealed_after,
                                       min_delta=MIN_DELTA)
    gap = assess_gap(pub_before["score"], pub_after["score"],
                     sealed_before["score"], sealed_after["score"])

    controls_ok = (
        control_empty["correct"] == sealed_before["correct"]
        and control_disabled["correct"] == sealed_before["correct"])
    if not controls_ok:
        problems.append("a control run does not reproduce the baseline")
    # Final-map regression is judged against the ORIGINAL baseline
    # sealed map, not the last accepted state.
    sealed_regressed = [k for k in orig_base_sealed
                        if sealed_map_after.get(k, 0.0)
                        < orig_base_sealed[k] - 1e-9]
    if sealed_regressed:
        problems.append(
            f"sealed families regressed in the final maps: "
            f"{', '.join(sealed_regressed)}")
    all_lessons_accepted = all(r["accepted"] for r in lesson_records) \
        and bool(lesson_records)
    passed = bool(verdict["accepted"] and controls_ok
                  and all_lessons_accepted and not problems)

    return {
        "public_before": pub_before,
        "public_after": pub_after,
        "sealed_before": sealed_before,
        "sealed_after": sealed_after,
        "verdict": verdict,
        "gap": gap,
        "controls": {"empty_memory": control_empty,
                     "retrieval_disabled": control_disabled},
        "lessons": lesson_records,
        "accepted_families": [r["family"] for r in lesson_records
                              if r["accepted"]],
        "derivation_audit": derived["audit"],
        "per_family": {
            "public_before": orig_base_pub,
            "sealed_before": orig_base_sealed,
            "public_after": pub_map_after,
            "sealed_after": sealed_map_after,
        },
        "counts": {
            "public_n": pub_after["n"],
            "sealed_n": sealed_after["n"],
            "public_per_family": dict(Counter(
                it.family for it in public_batch)),
            "sealed_per_family": dict(Counter(
                it.family for it in sealed_batch)),
        },
        "sealed_evaluations": sealed_evaluations,
        "manifest_hash": manifest,
        "invalidated": bool(problems),
        "invalidation_reasons": problems,
        "passed": passed,
    }
