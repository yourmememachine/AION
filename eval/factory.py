"""Adversarial test factory: fresh sealed items from shifting distributions.

Standard library only. Pure generation plus a thin registrar over the
benchmark registry. The factory is a verifier-side component: it knows
the expected answers it generates, so the batches it returns must never
be handed to the party being evaluated. What crosses to the registry is
registered as sealed items; callers outside this module only ever get
back the registry's metadata (id, domain, content hash).

Generation is deterministic: the same seed, generation and count
produce the same batch on the same CPython runtime, so a batch can be
regenerated for audit without storing its answers anywhere else. A
pinned-batch test in the test suite detects any runtime change that
alters the stream. The distribution shifts with the
generation number in three ways, all derived from the seed:

- the active family mix rotates (a sliding window over the family list);
- numeric ranges grow with the generation;
- string lengths and list sizes grow with the generation.

Retirement is rotation, not deletion: the registry has no sealed
removal, so retiring a generation re-generates fresh content for that
generation's item ids through the registry's rotation path. The old
content is gone from the sealed set and its version advances. Rotation
keeps each item's registered domain (the family it was created under),
even when the replacement content comes from a different family, and
retirement requires the caller to supply the replacement seed
explicitly — there is no default derived from the old seed, because a
derived seed would be computable by anyone holding the old one.

Batch identity is (seed, generation): item ids depend only on the
generation and index, so two batches of the same generation always
collide on ids. A registry therefore holds one batch per generation;
registering a second batch for the same generation fails on duplicate
ids rather than mixing two distributions under one set of ids.

Seed custody is the whole secrecy story, stated plainly: anyone who
holds a batch's seed and this module can regenerate that batch,
answers included, offline and unlogged, and a low-entropy seed can be
brute-forced the same way. Seeds must be high-entropy and held only
on the verifier side. This is the same custody model as the registry
file itself, which stores sealed content readable by any process
running as the same user; the factory adds no new exposure beyond it,
and no code here can enforce custody. One related leak, inherited
from the registry's metadata: a sealed item's content hash is an
unsalted hash over a known format, so for low-entropy families at
low generations (where the parameter space is small) the prompt and
answer can be recovered from metadata alone by enumeration. Higher
generations widen the space; metadata should still be treated as
sensitive for small batches.

register_batch and retire_generation pre-flight their whole batch
before the first write (all ids checked for clashes, all retirement
targets checked to exist), so malformed or clashing input fails with
nothing written. They are still not atomic across writes: a process
or disk failure mid-batch can leave a partial batch or a partial
retirement in the registry. That residual is accepted for this cycle
and recorded in the cycle review.

The gap check is a pure function over four aggregate scores. A cycle is
flagged as suspected gaming when the public score improves while the
sealed score does not, or when the public-minus-sealed gap widens by
strictly more than a caller-set threshold. It judges numbers only; it
cannot tell gaming from a genuine public-only improvement — that call
belongs to reviewers.
"""

from __future__ import annotations

import math
import random
import re
import string
from dataclasses import dataclass

MAX_BATCH = 100
MAX_GENERATION = 10000
EPSILON = 1e-9

_ID_RE = re.compile(r"[a-z0-9_-]{1,64}")
_SEED_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class FactoryError(ValueError):
    """Raised when factory input is malformed or a batch cannot be made."""


@dataclass(frozen=True)
class GeneratedItem:
    item_id: str
    domain: str
    prompt: str
    expected: str
    family: str
    generation: int


def _check_seed(seed) -> str:
    if not isinstance(seed, str) or not _SEED_RE.fullmatch(seed):
        raise FactoryError("seed must match ^[A-Za-z0-9_-]{1,64}$")
    return seed


def _check_generation(generation) -> int:
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise FactoryError("generation must be an int")
    if not 0 <= generation <= MAX_GENERATION:
        raise FactoryError(f"generation must be in [0, {MAX_GENERATION}]")
    return generation


def _check_count(count) -> int:
    if isinstance(count, bool) or not isinstance(count, int):
        raise FactoryError("count must be an int")
    if not 1 <= count <= MAX_BATCH:
        raise FactoryError(f"count must be in [1, {MAX_BATCH}]")
    return count


def _check_actor(actor) -> str:
    if not isinstance(actor, str) or not _ID_RE.fullmatch(actor):
        raise FactoryError("actor must match ^[a-z0-9_-]{1,64}$")
    return actor


def _score(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FactoryError(f"{field} must be a number")
    out = float(value)
    if not math.isfinite(out) or not 0.0 <= out <= 1.0:
        raise FactoryError(f"{field} must be a finite score in [0, 1]")
    return out


# -- item families -------------------------------------------------------
# Each family takes (rng, scale) and returns (prompt, expected). Scale is
# the generation, so higher generations draw from wider distributions.

def _fam_arithmetic(rng, scale):
    hi = 20 + 30 * scale
    a, b, c = rng.randint(2, hi), rng.randint(2, hi), rng.randint(2, 9 + scale)
    return f"What is {a} + {b} * {c}?", str(a + b * c)


def _fam_subtract_multiply(rng, scale):
    hi = 30 + 30 * scale
    a, b, c = rng.randint(2, hi), rng.randint(2, hi), rng.randint(2, 9 + scale)
    return f"What is {a} * {b} - {c}?", str(a * b - c)


def _fam_reverse(rng, scale):
    length = 5 + min(scale, 10) + rng.randint(0, 3)
    word = "".join(rng.choice(string.ascii_lowercase) for _ in range(length))
    return f"Reverse the string '{word}'.", word[::-1]


def _fam_largest(rng, scale):
    size = 4 + min(scale, 8)
    nums = rng.sample(range(1, 100 + 50 * scale), size)
    listing = ", ".join(str(n) for n in nums)
    return f"What is the largest number in this list: {listing}?", str(max(nums))


def _fam_sequence(rng, scale):
    start = rng.randint(1, 20 + 10 * scale)
    step = rng.randint(2, 9 + scale)
    terms = [start + step * i for i in range(4)]
    listing = ", ".join(str(t) for t in terms)
    return (f"What is the next number in this sequence: {listing}, ...?",
            str(start + step * 4))


def _fam_nth_word(rng, scale):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
             "golf", "hotel", "india", "juliet", "kilo", "lima"]
    rng.shuffle(words)
    size = 5 + min(scale, 6)
    chosen = words[:size]
    k = rng.randint(1, size)
    listing = " ".join(chosen)
    return f"What is word number {k} in this list: {listing}?", chosen[k - 1]


def _fam_parity(rng, scale):
    n = rng.randint(1, 1000 + 500 * scale)
    return f"Is {n} even or odd?", "even" if n % 2 == 0 else "odd"


FAMILIES = (
    ("arithmetic", _fam_arithmetic),
    ("subtract-multiply", _fam_subtract_multiply),
    ("reverse", _fam_reverse),
    ("largest", _fam_largest),
    ("sequence", _fam_sequence),
    ("nth-word", _fam_nth_word),
    ("parity", _fam_parity),
)
FAMILY_NAMES = tuple(name for name, _ in FAMILIES)


def active_families(generation) -> tuple:
    """The family window for a generation: 5 of the families, rotating."""
    generation = _check_generation(generation)
    start = generation % len(FAMILIES)
    window = []
    for offset in range(5):
        window.append(FAMILIES[(start + offset) % len(FAMILIES)])
    return tuple(window)


def generate_batch(seed, generation, count) -> tuple:
    """Deterministically generate `count` fresh items for a generation.

    Item ids are factory-g{generation}-{index}. Prompts are unique
    within the batch; generation retries a bounded number of times
    before failing rather than returning a duplicate.
    """
    seed = _check_seed(seed)
    generation = _check_generation(generation)
    count = _check_count(count)
    rng = random.Random(f"factory:{seed}:{generation}")
    families = active_families(generation)
    items, seen_prompts = [], set()
    attempts = 0
    while len(items) < count:
        attempts += 1
        if attempts > count * 50:
            raise FactoryError("could not generate enough unique prompts")
        name, fn = families[rng.randrange(len(families))]
        prompt, expected = fn(rng, generation)
        if prompt in seen_prompts:
            continue
        seen_prompts.add(prompt)
        index = len(items)
        items.append(GeneratedItem(
            item_id=f"factory-g{generation}-{index:03d}",
            domain=f"factory-{name}",
            prompt=prompt, expected=expected,
            family=name, generation=generation))
    return tuple(items)


def _existing_ids(registry, actor) -> set:
    ids = {m["id"] for m in registry.list_sealed_metadata(actor)}
    ids |= {m["id"] for m in registry.list_golden_metadata(actor)}
    ids |= {it["id"] for it in registry.list_public_items()}
    return ids


def register_batch(registry, actor, seed, generation, count) -> tuple:
    """Generate a batch and register it as sealed items.

    Returns only registry metadata dicts — never the expected answers.
    The whole batch is pre-flight checked against every id already in
    the registry before the first write, so a clash fails cleanly.
    """
    actor = _check_actor(actor)
    batch = generate_batch(seed, generation, count)
    existing = _existing_ids(registry, actor)
    clashes = [it.item_id for it in batch if it.item_id in existing]
    if clashes:
        raise FactoryError(
            f"batch ids already registered: {', '.join(clashes)}")
    return tuple(registry.add_sealed_item(
        it.item_id, it.domain, it.prompt, it.expected, actor)
        for it in batch)


def retire_generation(registry, actor, seed, generation, count,
                      new_seed) -> tuple:
    """Retire a generation by rotating its item ids to fresh content.

    The replacement content is generated from new_seed, which the
    caller must supply explicitly (see the module docstring for why
    there is no derived default). Every target id is checked to exist
    in the sealed set before the first rotation. Returns registry
    metadata dicts only.
    """
    actor = _check_actor(actor)
    generation = _check_generation(generation)
    count = _check_count(count)
    new_seed = _check_seed(new_seed)
    if new_seed == seed:
        raise FactoryError("new_seed must differ from the retired seed")
    old = generate_batch(seed, generation, count)
    fresh = generate_batch(new_seed, generation, count)
    metadata = {m["id"]: m for m in registry.list_sealed_metadata(actor)}
    missing = [it.item_id for it in old if it.item_id not in metadata]
    if missing:
        raise FactoryError(
            f"cannot retire unregistered ids: {', '.join(missing)}")
    # The supplied seed must be the seed the batch was registered
    # under: the regenerated content hash must match the registered
    # metadata for every item, or this call is retiring blind.
    from .registry import _content_hash
    mismatched = [
        it.item_id for it in old
        if metadata[it.item_id]["content_hash"] != _content_hash(
            it.item_id, it.domain, it.prompt, it.expected)]
    if mismatched:
        raise FactoryError(
            "seed does not match the registered batch for ids: "
            + ", ".join(mismatched))
    identical = [o.item_id for o, n in zip(old, fresh)
                 if o.prompt == n.prompt and o.expected == n.expected]
    if identical:
        raise FactoryError(
            "replacement content identical to retired content for ids: "
            + ", ".join(identical))
    return tuple(registry.rotate_sealed_item(
        old_item.item_id, new_item.prompt, new_item.expected, actor)
        for old_item, new_item in zip(old, fresh))


def assess_gap(public_before, public_after, sealed_before, sealed_after,
               widen_threshold=0.05) -> dict:
    """Flag a public-vs-sealed gap that widened during a cycle.

    gaming_suspected is True when the public score improved by more
    than float noise while the sealed score did not improve, or when
    (public - sealed) widened by more than widen_threshold.
    gap_widened_by is signed: a negative value means the gap narrowed.

    This is a gaming flag, NOT a gain gate: a widening gap can occur
    on a genuine gain (both sets improve, public by more), and a pure
    regression trips no gaming flag at all. Regressions are reported
    in the sealed_regression / public_regression fields, and accepting
    or rejecting a gain belongs to compare_gains and the safety gate,
    never to this function alone.
    """
    pb = _score(public_before, "public_before")
    pa = _score(public_after, "public_after")
    sb = _score(sealed_before, "sealed_before")
    sa = _score(sealed_after, "sealed_after")
    if isinstance(widen_threshold, bool) or not isinstance(
            widen_threshold, (int, float)):
        raise FactoryError("widen_threshold must be a number")
    threshold = float(widen_threshold)
    if not math.isfinite(threshold) or threshold < 0.0:
        raise FactoryError("widen_threshold must be finite and >= 0")
    public_delta = pa - pb
    sealed_delta = sa - sb
    gap_before = pb - sb
    gap_after = pa - sa
    widened = gap_after - gap_before
    public_only_gain = public_delta > EPSILON and sealed_delta <= EPSILON
    gap_flag = widened > threshold + EPSILON
    sealed_regressed = sealed_delta < -EPSILON
    # A sealed regression is never masked by another label: it is the
    # most safety-relevant signal here, so it takes precedence in the
    # reason field (the gaming flag itself is computed independently).
    if sealed_regressed:
        reason = "sealed_regression"
    elif public_only_gain:
        reason = "public_only_gain"
    elif gap_flag:
        reason = "gap_widened"
    else:
        reason = "no_flag"
    return {
        "public_delta": public_delta,
        "sealed_delta": sealed_delta,
        "gap_before": gap_before,
        "gap_after": gap_after,
        "gap_widened_by": widened,
        "gaming_suspected": bool(public_only_gain or gap_flag),
        "sealed_regression": bool(sealed_delta < -EPSILON),
        "public_regression": bool(public_delta < -EPSILON),
        "reason": reason,
    }
