"""Fresh frozen held-out generators for the Cycle 35 FIX round.

Written after external round 1, in response to a recorded
contamination: the stored/induced cross-check mechanism was
designed after observing a held-out failure in seed set 2 of
memory/heldout35.py, so that seed set is dev data for the
mechanism and its post-fix numbers are not clean evidence for
it. This file is the fresh set the cross-check is re-measured
on. It was written and sha256-hashed BEFORE the fix-round
measurement ran; the hash is recorded in
internal/BUILD-CYCLE-35-FIX.md. If the hash there does not
match this file, the fresh-set claim is void. DO NOT EDIT.

The generators receive no lesson, principle or solver input.
Families are chosen to exercise the cross-check paths:

- fresh-last / fresh-secondmin / fresh-nextgeo / fresh-count:
  positive transfer families with parameters disjoint from
  heldout35 (different ranges, lengths, term counts).
- fresh-coincide: every example has its maximum in last
  position (last == max throughout, lists NOT sorted), so the
  stored max principle passes the sample check while the
  samples equally support "last". The query's last element is
  not its maximum. Safe behaviour: abstain; a false
  application is a confident wrong answer.
- fresh-degenerate (Claude's degenerate-examples family):
  every example list is sorted ascending — again last == max
  throughout — and the query is unsorted with last != max.
  Target: zero false applications.

Determinism: every generator is seeded and pure.
"""

from __future__ import annotations

import random

from memory.heldout35 import fewshot_prompt, render
from memory.transfer import TransferError


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


def generate_fresh(seed: str, count_per_family: int = 20) -> tuple:
    """Six fresh few-shot families for cross-check re-measurement."""
    _check_count(count_per_family)
    rng = random.Random(f"cycle35-fresh:{seed}")
    items, seen = [], set()

    def ints(lo, hi, n):
        return [rng.randint(lo, hi) for _ in range(n)]

    def make_last():
        ex = []
        for _ in range(3):
            xs = ints(1, 999_999, rng.randint(6, 14))
            ex.append((xs, xs[-1]))
        q = ints(1, 999_999, rng.randint(6, 14))
        return fewshot_prompt(ex, q), render(q[-1])

    def make_secondmin():
        ex = []
        for _ in range(3):
            xs = rng.sample(range(1, 999_999), rng.randint(6, 14))
            ex.append((xs, sorted(xs)[1]))
        q = rng.sample(range(1, 999_999), rng.randint(6, 14))
        return fewshot_prompt(ex, q), render(sorted(q)[1])

    def make_nextgeo():
        ex = []
        for _ in range(3):
            start, ratio = rng.randint(1, 99), rng.choice((2, 3, 4, 5))
            terms = [start * ratio ** i for i in range(5)]
            ex.append((terms, start * ratio ** 5))
        start, ratio = rng.randint(1, 99), rng.choice((2, 3, 4, 5))
        q = [start * ratio ** i for i in range(5)]
        return fewshot_prompt(ex, q), render(start * ratio ** 5)

    def make_count():
        ex = []
        for _ in range(3):
            xs = ints(1, 99_999, rng.randint(4, 18))
            ex.append((xs, len(xs)))
        q = ints(1, 99_999, rng.randint(4, 18))
        return fewshot_prompt(ex, q), render(len(q))

    def _max_last_list():
        # Unsorted list whose maximum sits in last position, so
        # "last" and "max" agree on it by construction.
        xs = ints(1, 999_999, rng.randint(5, 10))
        top = max(xs) + rng.randint(1, 999)
        xs.append(top)
        return xs

    def make_coincide():
        ex = [(xs, xs[-1]) for xs in
              (_max_last_list(), _max_last_list(), _max_last_list())]
        q = ints(1, 999_999, rng.randint(5, 10))
        while q[-1] == max(q):
            q = ints(1, 999_999, rng.randint(5, 10))
        return fewshot_prompt(ex, q), render(q[-1])

    def make_degenerate():
        ex = []
        for _ in range(3):
            xs = sorted(ints(1, 999_999, rng.randint(5, 10)))
            ex.append((xs, xs[-1]))
        q = ints(1, 999_999, rng.randint(5, 10))
        while q[-1] == max(q) or q == sorted(q):
            q = ints(1, 999_999, rng.randint(5, 10))
        return fewshot_prompt(ex, q), render(q[-1])

    makers = (
        ("fresh-last", make_last),
        ("fresh-secondmin", make_secondmin),
        ("fresh-nextgeo", make_nextgeo),
        ("fresh-count", make_count),
        ("fresh-coincide", make_coincide),
        ("fresh-degenerate", make_degenerate),
    )
    for family, make in makers:
        _fill(items, seen, family, count_per_family, make)
    return tuple(items)
