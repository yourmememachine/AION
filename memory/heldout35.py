"""Frozen held-out generators for Cycle 35 — DO NOT EDIT.

This module was written and frozen BEFORE the Cycle 35 principle
engine (memory/principles.py) and before its primitive set was
finalised. Its sha256 is recorded in internal/BUILD-CYCLE-35.md;
if the hash there does not match this file, the held-out claim is
void. The generators receive no lesson, principle or solver input:
the formats here are held out from derivation by construction.

Formats:
- few-shot value tasks: "Learn from examples: IN => OUT; ...
  Now solve: IN => ?" — a presentation that appears nowhere in
  the factory families or the Cycle 34 tiers. Inputs/outputs are
  Python literals (int lists, word lists, strings, ints).
- factory-disguise traps: the exact factory sequence prompt with
  non-additive generating rules (geometric, squares, alternating
  ratio, periodic).
- few-shot traps: geometric / quadratic value tasks in the
  few-shot format — bait for a surface solver that pattern-matches
  "sequence -> add the last difference".

Determinism: every generator is seeded and pure.
"""

from __future__ import annotations

import random
import string

from memory.transfer import TransferError

_WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
    "kilo lima mango nectar ocean piano quartz river solar tango "
    "umbra violet walnut xenon yellow zephyr"
).split()


def render(value) -> str:
    """Canonical text form of a value, used for prompts AND answers."""
    if isinstance(value, list):
        return "[" + ", ".join(render(v) for v in value) + "]"
    if isinstance(value, str):
        return "'" + value + "'"
    return str(value)


def fewshot_prompt(examples, query) -> str:
    parts = "; ".join(f"{render(i)} => {render(o)}" for i, o in examples)
    return f"Learn from examples: {parts}. Now solve: {render(query)} => ?"


def _check_count(count_per_family):
    if not isinstance(count_per_family, int) or count_per_family < 4:
        raise TransferError("count_per_family must be an int >= 4")


def _fill(items, seen, family, count, make):
    made, attempts = 0, 0
    while made < count:
        attempts += 1
        if attempts > count * 200:
            raise TransferError(f"could not generate enough {family} items")
        prompt, expected = make()
        if prompt in seen:
            continue
        seen.add(prompt)
        items.append({"id": f"{family}-{len(items):03d}",
                      "family": family, "prompt": prompt,
                      "expected": expected})
        made += 1


def generate_heldout(seed: str, count_per_family: int = 20) -> tuple:
    """Ten genuinely new few-shot format families. See module docstring."""
    _check_count(count_per_family)
    rng = random.Random(f"cycle35-heldout:{seed}")
    items, seen = [], set()

    def ints(lo, hi, n):
        return [rng.randint(lo, hi) for _ in range(n)]

    def make_min():
        ex = []
        for _ in range(3):
            xs = ints(1, 99_999, rng.randint(5, 12))
            ex.append((xs, min(xs)))
        q = ints(1, 99_999, rng.randint(5, 12))
        return fewshot_prompt(ex, q), render(min(q))

    def make_sum():
        ex = []
        for _ in range(3):
            xs = ints(1, 9_999, rng.randint(4, 10))
            ex.append((xs, sum(xs)))
        q = ints(1, 9_999, rng.randint(4, 10))
        return fewshot_prompt(ex, q), render(sum(q))

    def make_count():
        ex = []
        for _ in range(3):
            xs = ints(1, 999, rng.randint(3, 15))
            ex.append((xs, len(xs)))
        q = ints(1, 999, rng.randint(3, 15))
        return fewshot_prompt(ex, q), render(len(q))

    def make_wordlen():
        ex = []
        for _ in range(3):
            w = "".join(rng.choice(string.ascii_lowercase)
                        for _ in range(rng.randint(3, 15)))
            ex.append((w, len(w)))
        q = "".join(rng.choice(string.ascii_lowercase)
                    for _ in range(rng.randint(3, 15)))
        return fewshot_prompt(ex, q), render(len(q))

    def make_last():
        ex = []
        for _ in range(3):
            xs = ints(1, 99_999, rng.randint(4, 10))
            ex.append((xs, xs[-1]))
        q = ints(1, 99_999, rng.randint(4, 10))
        return fewshot_prompt(ex, q), render(q[-1])

    def make_sortdesc():
        ex = []
        for _ in range(3):
            xs = ints(1, 9_999, rng.randint(5, 10))
            ex.append((xs, sorted(xs, reverse=True)))
        q = ints(1, 9_999, rng.randint(5, 10))
        return fewshot_prompt(ex, q), render(sorted(q, reverse=True))

    def make_order_inversion():
        ex = []
        for _ in range(3):
            ws = rng.sample(_WORDS, rng.randint(4, 8))
            ex.append((ws, ws[::-1]))
        q = rng.sample(_WORDS, rng.randint(4, 8))
        return fewshot_prompt(ex, q), render(q[::-1])

    def make_secondmin():
        ex = []
        for _ in range(3):
            xs = rng.sample(range(1, 99_999), rng.randint(5, 12))
            ex.append((xs, sorted(xs)[1]))
        q = rng.sample(range(1, 99_999), rng.randint(5, 12))
        return fewshot_prompt(ex, q), render(sorted(q)[1])

    def make_nextgeo():
        ex = []
        for _ in range(3):
            start, ratio = rng.randint(1, 50), rng.choice((2, 3, 4))
            terms = [start * ratio ** i for i in range(4)]
            ex.append((terms, start * ratio ** 4))
        start, ratio = rng.randint(1, 50), rng.choice((2, 3, 4))
        q = [start * ratio ** i for i in range(4)]
        return fewshot_prompt(ex, q), render(start * ratio ** 4)

    def make_nextquad():
        ex = []
        for _ in range(3):
            start = rng.randint(1, 5_000)
            step, d2 = rng.randint(1, 900), rng.randint(1, 6)
            terms = [start]
            for i in range(4):
                terms.append(terms[-1] + step + d2 * i)
            ex.append((terms, terms[-1] + step + d2 * 4))
        start = rng.randint(1, 5_000)
        step, d2 = rng.randint(1, 900), rng.randint(1, 6)
        q = [start]
        for i in range(4):
            q.append(q[-1] + step + d2 * i)
        return fewshot_prompt(ex, q), render(q[-1] + step + d2 * 4)

    makers = (
        ("heldout-min", make_min),
        ("heldout-sum", make_sum),
        ("heldout-count", make_count),
        ("heldout-wordlen", make_wordlen),
        ("heldout-last", make_last),
        ("heldout-sortdesc", make_sortdesc),
        ("heldout-order-inversion", make_order_inversion),
        ("heldout-secondmin", make_secondmin),
        ("heldout-nextgeo", make_nextgeo),
        ("heldout-nextquad", make_nextquad),
    )
    for family, make in makers:
        _fill(items, seen, family, count_per_family, make)
    return tuple(items)


def _sequence_prompt(terms) -> str:
    return ("What is the next number in this sequence: "
            + ", ".join(str(t) for t in terms) + ", ...?")


def generate_traps(seed: str, count_per_family: int = 20) -> tuple:
    """Factory-disguise traps: non-additive rules, sequence format."""
    _check_count(count_per_family)
    rng = random.Random(f"cycle35-traps:{seed}")
    items, seen = [], set()

    def make_geometric():
        start, ratio = rng.randint(1, 30), rng.choice((2, 3))
        terms = [start * ratio ** i for i in range(5)]
        return _sequence_prompt(terms), str(start * ratio ** 5)

    def make_squares():
        k = rng.randint(1, 20)
        terms = [(k + i) ** 2 for i in range(6)]
        return _sequence_prompt(terms), str((k + 6) ** 2)

    def make_alternating():
        start, ratio = rng.randint(1, 30), rng.choice((-2, -3))
        terms = [start * ratio ** i for i in range(5)]
        return _sequence_prompt(terms), str(start * ratio ** 5)

    def make_periodic():
        a, b, c = rng.sample(range(1, 99), 3)
        if rng.random() < 0.5:
            terms = [a, b, c, a, b, c]
            nxt = a
        else:
            terms = [a, b, c, a, b, c, a]
            nxt = b
        return _sequence_prompt(terms), str(nxt)

    makers = (
        ("trap-geometric", make_geometric),
        ("trap-squares", make_squares),
        ("trap-alternating", make_alternating),
        ("trap-periodic", make_periodic),
    )
    for family, make in makers:
        _fill(items, seen, family, count_per_family, make)
    return tuple(items)


def generate_traps_fewshot(seed: str, count_per_family: int = 20) -> tuple:
    """Few-shot traps: geometric / quadratic value tasks."""
    _check_count(count_per_family)
    rng = random.Random(f"cycle35-traps-fewshot:{seed}")
    items, seen = [], set()

    def make_fs_geometric():
        ex = []
        for _ in range(3):
            start, ratio = rng.randint(1, 40), rng.choice((2, 3))
            terms = [start * ratio ** i for i in range(4)]
            ex.append((terms, start * ratio ** 4))
        start, ratio = rng.randint(1, 40), rng.choice((2, 3))
        q = [start * ratio ** i for i in range(4)]
        return fewshot_prompt(ex, q), render(start * ratio ** 4)

    def make_fs_squares():
        ex = []
        for _ in range(3):
            k = rng.randint(1, 15)
            terms = [(k + i) ** 2 for i in range(5)]
            ex.append((terms, (k + 5) ** 2))
        k = rng.randint(1, 15)
        q = [(k + i) ** 2 for i in range(5)]
        return fewshot_prompt(ex, q), render((k + 5) ** 2)

    makers = (
        ("fst-geometric", make_fs_geometric),
        ("fst-squares", make_fs_squares),
    )
    for family, make in makers:
        _fill(items, seen, family, count_per_family, make)
    return tuple(items)
