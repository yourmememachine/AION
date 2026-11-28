"""Cycle 35 transfer measurement: principles + guard + induction.

Re-runs the Cycle 34 tiers against the principle engine
(memory/principles.py) and adds the tiers Cycle 35 exists for:

- heldout: ten few-shot format families from the frozen
  generators (memory/heldout35.py, written and hashed before the
  engine), reported PER FAMILY — an aggregate must not hide a
  family at zero;
- traps: factory-disguise non-additive sequences (geometric,
  squares, alternating, periodic), measured as SAFE HANDLING —
  applications, false applications, correct rejections and
  end-to-end accuracy reported separately (ChatGPT's condition:
  a system that refuses everything has not solved transfer, and
  a system that misfires has not either);
- traps_fewshot: geometric / quadratic few-shot tasks, where the
  additive principle must be refused by the sample check and the
  correct program induced.

Discipline carried over from Cycle 34: principles are derived
from the public batch alone and frozen before any tier is
scored; tiers are reported separately, never averaged into a
headline; the no-memory control must reproduce the naive
baseline per family by exact correct counts; no seed used by
any tier appears in the returned report.
"""

from __future__ import annotations

from eval.factory import generate_batch
from eval.registry import _normalise_answer

from .heldout35 import generate_heldout, generate_traps, \
    generate_traps_fewshot
from .principles import TransferMemoryEngine, derive_principles, \
    parse_factory_frame, parse_fewshot, run_program, self_check_principle
from .solver import StrategySolver
from .transfer import _score_items, generate_shifted

LESSON_FAMILIES = ("reverse", "largest", "sequence", "nth-word")


def _trap_metrics(engine, items) -> dict:
    per_family = {}
    for item in items:
        slot = per_family.setdefault(item["family"], {
            "n": 0, "applications": 0, "false_applications": 0,
            "correct_applications": 0, "rejections": 0, "correct": 0})
        slot["n"] += 1
        assessment = engine.explain(item["prompt"])
        ok = _normalise_answer(assessment["answer"]) == (
            _normalise_answer(item["expected"]))
        if ok:
            slot["correct"] += 1
        if assessment["verdict"] == "APPLY":
            slot["applications"] += 1
            if ok:
                slot["correct_applications"] += 1
            else:
                slot["false_applications"] += 1
        else:
            slot["rejections"] += 1
    for slot in per_family.values():
        n = slot["n"]
        slot["false_application_rate"] = slot["false_applications"] / n
        slot["safe_handling"] = 1.0 - slot["false_application_rate"]
        slot["end_to_end"] = slot["correct"] / n
    return per_family


def _false_refusals(engine, principles, factory_items, heldout_items):
    """Guard refusals of a principle that would have answered right.

    A refusal counts only when the bypassed program (guard
    ignored) produces the expected answer AND the engine's final
    answer is wrong — a refusal the induction path then repairs
    is not a false refusal in effect.
    """
    bad = 0
    total = 0
    for item in factory_items:
        total += 1
        frame = parse_factory_frame(item["prompt"])
        if frame is None:
            continue
        shape, payload, params = frame
        expected = item["expected"]
        refused_correct = False
        for principle in principles:
            if principle.shape != shape:
                continue
            ok, _p, _f = self_check_principle(principle, payload, params)
            if ok:
                continue
            try:
                got = run_program(principle.program, payload, params)
            except Exception:
                continue
            if _normalise_answer(str(got)) == _normalise_answer(expected):
                refused_correct = True
        if refused_correct and _normalise_answer(
                engine.solve(item["prompt"])) != _normalise_answer(expected):
            bad += 1
    for item in heldout_items:
        total += 1
        parsed = parse_fewshot(item["prompt"])
        if parsed is None:
            continue
        examples, query = parsed
        refused_correct = False
        for principle in principles:
            ok, _p, _f = self_check_principle(
                principle, query, {}, examples=examples)
            if ok:
                continue
            try:
                got = run_program(principle.program, query, {})
            except Exception:
                continue
            from .heldout35 import render
            if _normalise_answer(render(got)) == _normalise_answer(
                    item["expected"]):
                refused_correct = True
        if refused_correct and _normalise_answer(
                engine.solve(item["prompt"])) != _normalise_answer(
                    item["expected"]):
            bad += 1
    return {"false_refusals": bad, "items": total,
            "rate": bad / total if total else 0.0}


def run_cycle35_measurement(*, public_seed, sealed_seed, shifted_seed,
                            heldout_seed, trap_seed, public_count=100,
                            sealed_count=100, per_family=20) -> dict:
    """Measure the principle engine across all Cycle 35 tiers."""
    public_batch = generate_batch(public_seed, 1, public_count)
    sealed_batch = generate_batch(sealed_seed, 2, sealed_count)
    public_items = [{"id": it.item_id, "prompt": it.prompt,
                     "expected": it.expected} for it in public_batch]
    sealed_items = [{"id": it.item_id, "family": it.family,
                     "prompt": it.prompt, "expected": it.expected}
                    for it in sealed_batch]
    shifted_items = list(generate_shifted(shifted_seed, per_family))
    heldout_items = list(generate_heldout(heldout_seed, per_family))
    trap_items = list(generate_traps(trap_seed, per_family))
    fst_items = list(generate_traps_fewshot(trap_seed, per_family))

    derived = derive_principles(public_items)
    principles = derived["principles"]

    naive = StrategySolver()
    memory_off = TransferMemoryEngine(principles=[],
                                      induction_enabled=False)
    memory_on = TransferMemoryEngine(principles=principles)

    tiers = {}
    for label, tier_items in (("in_distribution", sealed_items),
                              ("shifted", shifted_items),
                              ("heldout", heldout_items),
                              ("traps_fewshot", fst_items)):
        before = _score_items(naive if label in
                              ("in_distribution", "shifted") else memory_off,
                              tier_items)
        after = _score_items(memory_on, tier_items)
        tiers[label] = {"before": before, "after": after,
                        "delta": after["score"] - before["score"]}

    # Control: memory-off must reproduce the naive baseline per
    # family by exact correct counts on the factory tiers.
    controls_ok = True
    for label, tier_items in (("in_distribution", sealed_items),
                              ("shifted", shifted_items)):
        off = _score_items(memory_off, tier_items)
        base = _score_items(naive, tier_items)
        if off["per_family_correct"] != base["per_family_correct"]:
            controls_ok = False

    trap_metrics = _trap_metrics(memory_on, trap_items)
    fst_metrics = _trap_metrics(memory_on, fst_items)
    trap_baseline = _score_items(naive, trap_items)

    false_ref = _false_refusals(
        memory_on, principles,
        sealed_items + shifted_items, heldout_items)

    never_worse = all(
        tiers[label]["after"]["score"]
        >= tiers[label]["before"]["score"] - 1e-9
        for label in tiers)

    return {
        "tiers": tiers,
        "traps": {"per_family": trap_metrics,
                  "baseline_score": trap_baseline["score"]},
        "traps_fewshot_metrics": fst_metrics,
        "false_refusals": false_ref,
        "controls_ok": controls_ok,
        "never_worse_than_baseline": never_worse,
        "principles": sorted(p.id for p in principles),
        "derivation_audit": derived["audit"],
    }
