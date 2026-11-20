"""Strategy solver: a deterministic harness that memory can improve.

Standard library only. The solver answers factory-style prompts
(eval/factory.py formats) using, per task family, one strategy token.
Without memory it uses a NAIVE default per family — plausible
simplistic behaviour that is wrong for five of the seven families.
A committed memory lesson (kind "strategy", domain "factory-<family>",
content = token) overrides the naive strategy for that family.
Tokens are namespaced per family and whitelisted: a lesson whose
content is not a known token for its family is ignored, never
interpreted, and the naive strategy applies. Retrieved lessons are
data, not instructions: a lesson can only select among the fixed
computations defined here.

solve() never raises. An unclassifiable prompt, a parse failure, or
an out-of-range index returns "" — a wrong answer, not an exception —
because the registry turns a scorer exception into an aborted
evaluation run. explain() exposes exactly which family, strategy and
lesson produced an answer, over the same code path as solve().

Honest scope: this is a measurement harness, not a mind. The strategy
vocabulary — naive, correct and wrong-extra tokens per family — was
written by builders who already knew each family's structure.
Lesson derivation (below) is selection over that hand-built
hypothesis space from public practice items only: it proves that
public items suffice to identify, store and re-apply the right
strategy from a menu containing it. It does not prove the system
invented a strategy, and gains measured with it are gains on unseen
items of the same generator families, not on unseen task types.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from eval.registry import _normalise_answer

# -- family patterns (anchored fullmatch; mutually exclusive) -------------

_PATTERNS = (
    ("arithmetic",
     re.compile(r"What is ([0-9]+) \+ ([0-9]+) \* ([0-9]+)\?")),
    ("subtract-multiply",
     re.compile(r"What is ([0-9]+) \* ([0-9]+) - ([0-9]+)\?")),
    ("reverse",
     re.compile(r"Reverse the string '([a-z]+)'\.")),
    ("largest",
     re.compile(r"What is the largest number in this list: ([0-9, ]+)\?")),
    ("sequence",
     re.compile(r"What is the next number in this sequence: ([0-9, ]+), \.\.\.\?")),
    ("nth-word",
     re.compile(r"What is word number ([0-9]+) in this list: ([a-z ]+)\?")),
    ("parity",
     re.compile(r"Is ([0-9]+) even or odd\?")),
)

FAMILIES = tuple(name for name, _ in _PATTERNS)


def _ints(text: str) -> tuple:
    return tuple(int(part) for part in text.split(",") if part.strip())


def _compute(family: str, operands, token: str) -> str:
    if family == "arithmetic":
        a, b, c = operands
        if token == "precedence":
            return str(a + b * c)
        if token == "sum-all":
            return str(a + b + c)
        return str((a + b) * c)  # left-to-right
    if family == "subtract-multiply":
        a, b, c = operands
        if token == "subtract-first":
            return str(a * (b - c))
        if token == "add-instead":
            return str(a * b + c)
        return str(a * b - c)  # multiply-first
    if family == "reverse":
        (word,) = operands
        if token == "full-reverse":
            return word[::-1]
        if token == "swap-ends":
            return word[-1] + word[1:-1] + word[0] if len(word) > 1 else word
        return word  # identity
    if family == "largest":
        nums = operands
        if token == "scan-max":
            return str(max(nums))
        if token == "last":
            return str(nums[-1])
        if token == "smallest":
            return str(min(nums))
        return str(nums[0])  # first
    if family == "sequence":
        terms = operands
        if token == "plus-step":
            return str(terms[-1] + (terms[1] - terms[0]))
        if token == "plus-first-term":
            return str(terms[-1] + terms[0])
        return str(terms[-1] + 1)  # plus-one
    if family == "nth-word":
        k, words = operands
        if token == "one-indexed":
            return words[k - 1]
        if token == "last-word":
            return words[-1]
        if token == "first-word":
            return words[0]
        # zero-indexed: out of range on k == len(words) is a wrong
        # answer (""), never a crash and never a clamp — clamping
        # would make the naive bug accidentally correct there.
        return words[k] if k < len(words) else ""
    if family == "parity":
        (n,) = operands
        even = n % 2 == 0
        if token == "inverted-parity":
            even = not even
        return "even" if even else "odd"  # mod-two
    raise ValueError(f"unknown family: {family}")


VOCABULARY = {
    "arithmetic": ("left-to-right", "precedence", "sum-all"),
    "subtract-multiply": ("multiply-first", "subtract-first", "add-instead"),
    "reverse": ("identity", "full-reverse", "swap-ends"),
    "largest": ("first", "scan-max", "last", "smallest"),
    "sequence": ("plus-one", "plus-step", "plus-first-term"),
    "nth-word": ("zero-indexed", "one-indexed", "last-word", "first-word"),
    "parity": ("mod-two", "inverted-parity"),
}

NAIVE = {
    "arithmetic": "left-to-right",
    "subtract-multiply": "multiply-first",
    "reverse": "identity",
    "largest": "first",
    "sequence": "plus-one",
    "nth-word": "zero-indexed",
    "parity": "mod-two",
}


def classify(prompt):
    """The family a prompt belongs to, from its text alone, or None.

    Detection follows the prompt, never any stored domain: rotated
    registry items keep their original domain while carrying another
    family's prompt.
    """
    if not isinstance(prompt, str):
        return None
    for family, pattern in _PATTERNS:
        if pattern.fullmatch(prompt):
            return family
    return None


def _parse(family: str, prompt: str):
    for name, pattern in _PATTERNS:
        if name == family:
            match = pattern.fullmatch(prompt)
            break
    groups = match.groups()
    if family in ("arithmetic", "subtract-multiply"):
        return tuple(int(g) for g in groups)
    if family == "reverse":
        return (groups[0],)
    if family in ("largest", "sequence"):
        return _ints(groups[0])
    if family == "nth-word":
        return (int(groups[0]), tuple(groups[1].split()))
    return (int(groups[0]),)  # parity


@dataclass(frozen=True)
class Explanation:
    family: str | None
    strategy: str | None
    source: str  # "naive", "lesson", or "none" (unclassifiable)
    lesson_id: str | None
    answer: str


class StrategySolver:
    """Answers factory prompts, optionally improved by memory lessons.

    Lesson source, in order: an explicit lessons_override list (used
    by the reuse harness to score a candidate lesson before it is
    committed), else the store's current entries when a store is
    given and retrieval is enabled, else nothing. Note the
    precedence: when lessons_override is given, retrieval_enabled
    has no effect — the override IS the lesson source. With no valid
    lesson for a family, the naive strategy applies.
    """

    def __init__(self, store=None, *, retrieval_enabled=True,
                 lessons_override=None):
        self.store = store
        self.retrieval_enabled = retrieval_enabled
        self.lessons_override = lessons_override

    def _lessons_for(self, family: str) -> list:
        domain = f"factory-{family}"
        if self.lessons_override is not None:
            return [e for e in self.lessons_override
                    if e.get("domain") == domain
                    and e.get("kind") == "strategy"]
        if self.store is not None and self.retrieval_enabled:
            return self.store.retrieve(domain=domain, kind="strategy")
        return []

    def explain(self, prompt) -> Explanation:
        family = classify(prompt)
        if family is None:
            return Explanation(None, None, "none", None, "")
        try:
            operands = _parse(family, prompt)
            token, source, lesson_id = NAIVE[family], "naive", None
            for entry in self._lessons_for(family):
                candidate = entry.get("content")
                if candidate in VOCABULARY[family]:
                    # Last valid lesson wins; invalid tokens are
                    # filtered before ranking, never win-then-fallback.
                    token, source, lesson_id = (
                        candidate, "lesson", entry.get("id"))
            return Explanation(family, token, source, lesson_id,
                               _compute(family, operands, token))
        except Exception:
            return Explanation(family, None, "none", None, "")

    def solve(self, prompt) -> str:
        """The answer only. Never raises; "" means no answer."""
        return self.explain(prompt).answer

    def solve_with_strategy(self, prompt, token) -> str:
        """Answer with a forced strategy token for the prompt's family.

        Used by lesson derivation to score candidate tokens on public
        items. A token outside the family's vocabulary falls back to
        the naive strategy.
        """
        family = classify(prompt)
        if family is None:
            return ""
        if token not in VOCABULARY[family]:
            token = NAIVE[family]
        try:
            return _compute(family, _parse(family, prompt), token)
        except Exception:
            return ""


# -- lesson derivation -----------------------------------------------------

MIN_ITEMS = 4
MIN_DELTA_ITEMS = 2
MIN_DELTA_SCORE = 0.25
MIN_BEST_SCORE = 0.75


def _public_digest(items) -> str:
    def binding(item):
        if item.get("content_hash"):
            return (item["id"], item["content_hash"])
        raw = json.dumps({"prompt": item.get("prompt"),
                          "expected": item.get("expected")},
                         sort_keys=True).encode("utf-8")
        return (item["id"], hashlib.sha256(raw).hexdigest())

    core = sorted(binding(it) for it in items)
    return hashlib.sha256(json.dumps(core).encode("utf-8")).hexdigest()


def derive_lessons(public_items, solver=None) -> dict:
    """Propose strategy lessons from public practice items only.

    Takes the public item list itself — no registry handle — so
    sealed or golden material cannot be touched by construction.
    Items are grouped by the solver's own classifier, never by their
    stored domain. For each family, every vocabulary token is scored
    on that family's items; a lesson is proposed only when one
    non-naive token is the unique best by correct count, beats naive
    by at least MIN_DELTA_ITEMS items and MIN_DELTA_SCORE, and scores
    at least MIN_BEST_SCORE. Ties at the top abstain: on a small
    sample a coinciding wrong token is indistinguishable from the
    correct one, and guessing would store a coin flip as a fact.

    Returns {"lessons": [...], "audit": {...}} with one audit record
    per family examined, negative results included. The audit is
    returned to the caller, not persisted anywhere: preserving it
    (and with it, the evidence that a family was examined and
    declined) is the caller's responsibility.
    """
    solver = solver or StrategySolver()
    items = list(public_items)
    digest = _public_digest(items)
    by_family = {family: [] for family in VOCABULARY}
    unclassified = 0
    for item in items:
        family = classify(item.get("prompt"))
        if family is None:
            unclassified += 1
        else:
            by_family[family].append(item)

    lessons = []
    records = {}
    absent = []
    for family in sorted(VOCABULARY):
        group = sorted(by_family[family], key=lambda it: it["id"])
        if not group:
            absent.append(family)
            continue
        counts = {}
        for token in VOCABULARY[family]:
            correct = 0
            for item in group:
                response = solver.solve_with_strategy(item["prompt"], token)
                if _normalise_answer(response) == _normalise_answer(
                        item["expected"]):
                    correct += 1
            counts[token] = correct
        n = len(group)
        naive_token = NAIVE[family]
        naive_correct = counts[naive_token]
        best_correct = max(counts.values())
        leaders = [t for t, c in counts.items() if c == best_correct]
        record = {
            "family": family, "n": n,
            "item_ids": [it["id"] for it in group],
            "naive_token": naive_token, "naive_correct": naive_correct,
            "counts": dict(sorted(counts.items())),
            "best_correct": best_correct,
        }
        if n < MIN_ITEMS:
            record["decision"] = "insufficient_items"
        elif len(leaders) > 1:
            record["decision"] = "tie_at_top"
        elif leaders[0] == naive_token:
            record["decision"] = "naive_best"
        elif (best_correct - naive_correct < MIN_DELTA_ITEMS
                or (best_correct - naive_correct) / n < MIN_DELTA_SCORE
                or best_correct / n < MIN_BEST_SCORE):
            record["decision"] = "margin_not_met"
        else:
            record["decision"] = "proposed"
            record["token"] = leaders[0]
            lessons.append({
                "family": family,
                "domain": f"factory-{family}",
                "kind": "strategy",
                "content": leaders[0],
                "evidence_ref": f"derive:{digest}:{family}",
            })
        records[family] = record
    return {
        "lessons": lessons,
        "audit": {
            "public_digest": digest,
            "unclassified": unclassified,
            "families_absent": absent,
            "families": records,
        },
    }
