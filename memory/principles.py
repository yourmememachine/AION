"""Principle engine: guarded, induction-capable memory (Cycle 35).

Cycle 34 measured the boundary of the strategy-token memory
(memory/solver.py): within-family transfer only, zero transfer to
new formats, and a learned rule firing wrongly on a trap
distribution. Three external designs (Claude, ChatGPT, Gemini —
obtained blind, reconciled in internal/BUILD-CYCLE-35.md)
converged on the same fix, implemented here:

- Lessons are PRINCIPLES, not procedures: a small program over
  shared primitives, plus the structural invariants that held on
  every positive episode (its preconditions), plus excluders
  learned from failures. Features are structural and task-name
  free (Gemini's TaskObservation; Claude's features()).
- A principle never fires unchecked (ChatGPT's RuleGate; Gemini's
  self_check_principle): signature, invariants, excluders, trap
  diagnostics and — when the task carries sample pairs — agreement
  with the task's own examples. Failures carry named codes,
  including trap_mismatch:multiplicative_progression and
  sample_pair_contradiction. Abstention is a valid result.
- New formats are handled by INDUCTION: the shortest primitive
  program consistent with the task's own examples, with abstention
  when two shortest programs disagree on the query (Claude's
  induce; the codebase's tie-abstention discipline).
- Derivation from public practice items clusters episodes by
  semantic shape, never by family name, and abstains on ties that
  the evidence cannot distinguish (see the expression cluster:
  precedence and left-to-right coincide on every public episode).

Honest scope, continuous with solver.py's own docstring: the
primitive vocabulary is a hand-built hypothesis space. What this
cycle adds is not invention of primitives but (a) selection by
induction with recorded preconditions, (b) a guard that refuses
traps instead of misfiring, and (c) per-task induction that
transfers across presentations. A refusal never scores worse
than the no-memory baseline: factory prompts fall back to the
naive strategy solver, few-shot prompts abstain ("").
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from fractions import Fraction

from eval.registry import _normalise_answer

from .solver import StrategySolver

MIN_CLUSTER_ITEMS = 4
MIN_EXAMPLES = 2


class _Inconsistent(Exception):
    """A primitive's precondition does not hold for this payload."""


# -- structural features (name-free) ---------------------------------------

def _ratios(values):
    """Successive ratios, exact for ints, 9-dp rounded for floats.

    None when any denominator is zero (ratio undefined).
    """
    out = []
    for a, b in zip(values, values[1:]):
        if a == 0:
            return None
        if isinstance(a, int) and isinstance(b, int):
            out.append(Fraction(b, a))
        else:
            out.append(round(b / a, 9))
    return out


def sequence_diagnostics(values) -> dict:
    """Additive / multiplicative structure of a numeric sequence.

    Independent of any learned rule (ChatGPT's diagnostics): a
    sequence can be additive, multiplicative, both (constant —
    genuinely ambiguous), or neither; constant second differences
    are reported for the quadratic case.
    """
    vals = list(values)
    result = {"sufficient_data": len(vals) >= 3,
              "additive": False, "multiplicative": False,
              "ambiguous": False, "constant_second_difference": False,
              "differences": [], "ratios": None}
    if len(vals) < 2:
        return result
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    result["differences"] = diffs
    if len(vals) >= 3:
        result["additive"] = len(set(diffs)) == 1
        ratios = _ratios(vals)
        result["ratios"] = ratios
        if ratios is not None:
            result["multiplicative"] = len(set(ratios)) == 1
        if len(diffs) >= 2:
            second = [b - a for a, b in zip(diffs, diffs[1:])]
            result["constant_second_difference"] = len(set(second)) == 1
        result["ambiguous"] = result["additive"] and result["multiplicative"]
    return result


def features(payload) -> dict:
    """Structural features of a payload; never a task/family name."""
    f = {"kind": "other", "length": 0, "is_sequence": False,
         "is_numeric_sequence": False, "const_diff": None,
         "const_ratio": None, "second_diff_const": None,
         "monotone_increasing": None, "all_positive": None,
         "all_ints": None, "text_blob": None}
    if isinstance(payload, str):
        f.update(kind="str", length=len(payload), text_blob=payload)
        return f
    if isinstance(payload, bool):
        return f
    if isinstance(payload, int):
        f.update(kind="int", length=1)
        return f
    if isinstance(payload, (list, tuple)):
        f["is_sequence"] = True
        f["length"] = len(payload)
        if payload and all(isinstance(v, str) for v in payload):
            f["kind"] = "wordlist"
            f["text_blob"] = " ".join(payload)
            return f
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in payload):
            f["kind"] = "numlist"
            f["is_numeric_sequence"] = True
            f["all_ints"] = all(isinstance(v, int) for v in payload)
            f["all_positive"] = all(v > 0 for v in payload)
            if len(payload) >= 2:
                diffs = [b - a for a, b in zip(payload, payload[1:])]
                f["monotone_increasing"] = all(d > 0 for d in diffs)
            if len(payload) >= 3:
                diag = sequence_diagnostics(payload)
                f["const_diff"] = diag["additive"]
                f["const_ratio"] = diag["multiplicative"]
                f["second_diff_const"] = diag["constant_second_difference"]
        return f
    return f


# Invariant catalog: name -> predicate over a features dict.
_INVARIANTS = {
    "diag_additive": lambda f: f["const_diff"] is True,
    "diag_multiplicative": lambda f: f["const_ratio"] is True,
    "diag_second_diff": lambda f: f["second_diff_const"] is True,
    "const_diff": lambda f: f["const_diff"] is True,
    "const_ratio": lambda f: f["const_ratio"] is True,
    "not_const_ratio": lambda f: f["const_ratio"] is False,
    "not_const_diff": lambda f: f["const_diff"] is False,
    "monotone_increasing": lambda f: f["monotone_increasing"] is True,
    "all_positive": lambda f: f["all_positive"] is True,
    "len_ge_3": lambda f: f["length"] >= 3,
    "is_numeric_sequence": lambda f: f["is_numeric_sequence"] is True,
}


# -- primitives --------------------------------------------------------------

def _num_seq(payload):
    if (not isinstance(payload, (list, tuple)) or len(payload) < 2
            or not all(isinstance(v, (int, float))
                       and not isinstance(v, bool) for v in payload)):
        raise _Inconsistent("not a numeric sequence")
    return list(payload)


def _p_reverse(payload, params):
    if isinstance(payload, (list, tuple)):
        return list(payload)[::-1]
    if isinstance(payload, str):
        return payload[::-1]
    raise _Inconsistent("reverse needs a sequence or string")


def _p_sort(payload, params):
    if isinstance(payload, (list, tuple)):
        return sorted(payload)
    raise _Inconsistent("sort needs a sequence")


def _p_sort_desc(payload, params):
    if isinstance(payload, (list, tuple)):
        return sorted(payload, reverse=True)
    raise _Inconsistent("sort_desc needs a sequence")


def _p_sum(payload, params):
    return sum(_num_seq(payload))


def _p_min(payload, params):
    if isinstance(payload, (list, tuple)) and payload:
        return min(payload)
    raise _Inconsistent("min needs a non-empty sequence")


def _p_max(payload, params):
    if isinstance(payload, (list, tuple)) and payload:
        return max(payload)
    raise _Inconsistent("max needs a non-empty sequence")


def _p_len(payload, params):
    if isinstance(payload, (list, tuple, str)):
        return len(payload)
    raise _Inconsistent("len needs a sequence or string")


def _p_first(payload, params):
    if isinstance(payload, (list, tuple)) and payload:
        return payload[0]
    raise _Inconsistent("first needs a non-empty sequence")


def _p_last(payload, params):
    if isinstance(payload, (list, tuple)) and payload:
        return payload[-1]
    raise _Inconsistent("last needs a non-empty sequence")


def _p_drop_first(payload, params):
    if isinstance(payload, (list, tuple)) and len(payload) >= 2:
        return list(payload)[1:]
    raise _Inconsistent("drop_first needs length >= 2")


def _p_drop_last(payload, params):
    if isinstance(payload, (list, tuple)) and len(payload) >= 2:
        return list(payload)[:-1]
    raise _Inconsistent("drop_last needs length >= 2")


def _p_extrap_add(payload, params):
    vals = _num_seq(payload)
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if len(set(diffs)) != 1:
        raise _Inconsistent("first differences not constant")
    return vals[-1] + diffs[-1]


def _p_extrap_add2(payload, params):
    vals = _num_seq(payload)
    if len(vals) < 3:
        raise _Inconsistent("need >= 3 terms for second differences")
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    second = [b - a for a, b in zip(diffs, diffs[1:])]
    if len(set(second)) != 1:
        raise _Inconsistent("second differences not constant")
    return vals[-1] + diffs[-1] + second[-1]


def _p_extrap_mul(payload, params):
    vals = _num_seq(payload)
    ratios = _ratios(vals)
    if ratios is None or len(set(ratios)) != 1:
        raise _Inconsistent("ratios not constant")
    out = vals[-1] * ratios[-1]
    if isinstance(out, Fraction):
        if out.denominator != 1:
            raise _Inconsistent("non-integral extrapolation")
        return int(out)
    return out


def _p_plus_one(payload, params):
    return _num_seq(payload)[-1] + 1


def _p_plus_first(payload, params):
    vals = _num_seq(payload)
    return vals[-1] + vals[0]


def _apply_op(a, op, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    raise _Inconsistent(f"unknown operator {op!r}")


def _expr(payload):
    if (not isinstance(payload, tuple) or len(payload) != 5):
        raise _Inconsistent("not an expression payload")
    return payload


def _p_eval_precedence(payload, params):
    a, op1, b, op2, c = _expr(payload)
    if op2 == "*" and op1 in "+-":
        return _apply_op(a, op1, _apply_op(b, op2, c))
    if op1 == "*" and op2 in "+-":
        return _apply_op(_apply_op(a, op1, b), op2, c)
    return _apply_op(_apply_op(a, op1, b), op2, c)


def _p_eval_left_to_right(payload, params):
    a, op1, b, op2, c = _expr(payload)
    return _apply_op(_apply_op(a, op1, b), op2, c)


def _p_eval_sum_all(payload, params):
    a, _o1, b, _o2, c = _expr(payload)
    return a + b + c


def _p_identity(payload, params):
    return payload


def _p_swap_ends(payload, params):
    if isinstance(payload, str) and len(payload) > 1:
        return payload[-1] + payload[1:-1] + payload[0]
    raise _Inconsistent("swap_ends needs a string of length >= 2")


def _p_pick_kth(payload, params):
    if not isinstance(payload, (list, tuple)) or "k" not in params:
        raise _Inconsistent("pick_kth needs a sequence and k")
    k = params["k"]
    if not 1 <= k <= len(payload):
        raise _Inconsistent("k out of range")
    return payload[k - 1]


def _p_pick_kth0(payload, params):
    if not isinstance(payload, (list, tuple)) or "k" not in params:
        raise _Inconsistent("pick_kth0 needs a sequence and k")
    k = params["k"]
    if not 0 <= k < len(payload):
        raise _Inconsistent("k out of range")
    return payload[k]


def _p_parity_word(payload, params):
    if not isinstance(payload, int):
        raise _Inconsistent("parity needs an int")
    return "even" if payload % 2 == 0 else "odd"


def _p_parity_inverted(payload, params):
    if not isinstance(payload, int):
        raise _Inconsistent("parity needs an int")
    return "odd" if payload % 2 == 0 else "even"


_PRIMS = {
    "reverse": _p_reverse, "sort": _p_sort, "sort_desc": _p_sort_desc,
    "sum": _p_sum, "min": _p_min, "max": _p_max, "len": _p_len,
    "first": _p_first, "last": _p_last,
    "drop_first": _p_drop_first, "drop_last": _p_drop_last,
    "extrap_add": _p_extrap_add, "extrap_add2": _p_extrap_add2,
    "extrap_mul": _p_extrap_mul, "plus_one": _p_plus_one,
    "plus_first": _p_plus_first,
    "eval_precedence": _p_eval_precedence,
    "eval_left_to_right": _p_eval_left_to_right,
    "eval_sum_all": _p_eval_sum_all,
    "identity": _p_identity, "swap_ends": _p_swap_ends,
    "pick_kth": _p_pick_kth, "pick_kth0": _p_pick_kth0,
    "parity_word": _p_parity_word, "parity_inverted": _p_parity_inverted,
}

# Primitives searched by per-task induction on value tasks.
VALUE_PRIMS = (
    "reverse", "sort", "sort_desc", "sum", "min", "max", "len",
    "first", "last", "drop_first", "drop_last",
    "extrap_add", "extrap_add2", "extrap_mul",
)


def run_program(program, payload, params=None):
    """Run a primitive program; raises _Inconsistent on failure."""
    value = payload
    for name in program:
        value = _PRIMS[name](value, params or {})
    return value


def _consistent(program, episodes) -> bool:
    for payload, params, expected in episodes:
        try:
            got = run_program(program, payload, params)
        except Exception:
            return False
        if _normalise_answer(_render(got)) != _normalise_answer(
                _render(expected)):
            return False
    return True


def induce_program(episodes, max_depth: int = 2) -> list:
    """All shortest programs consistent with every episode.

    Episodes are (payload, params, expected). Fewer than
    MIN_EXAMPLES episodes can never ground a program. Returns the
    programs at the shortest depth that has any consistent
    program, or [] when none exists up to max_depth — the caller
    decides what agreement among them means (see the engine).
    """
    episodes = list(episodes)
    if len(episodes) < MIN_EXAMPLES:
        return []
    for depth in range(1, max_depth + 1):
        found = []
        for program in itertools.product(VALUE_PRIMS, repeat=depth):
            if _consistent(program, episodes):
                found.append(program)
        if found:
            return found
    return []


# -- principles ---------------------------------------------------------------

@dataclass
class Principle:
    id: str
    program: tuple
    shape: str
    ratio_mode: str | None = None
    invariants: frozenset = frozenset()
    excluders: frozenset = frozenset()
    payload_kind: str | None = None
    positives_features: list = field(default_factory=list)
    n_pos: int = 0
    n_neg: int = 0

    @property
    def confidence(self) -> float:
        total = self.n_pos + self.n_neg
        return self.n_pos / total if total else 0.0

    @property
    def digest(self) -> str:
        """Canonical sha256 of the principle definition (Gemini)."""
        definition = {
            "id": self.id, "program": list(self.program),
            "shape": self.shape, "ratio_mode": self.ratio_mode,
            "invariants": sorted(self.invariants),
            "excluders": sorted(self.excluders),
            "payload_kind": self.payload_kind,
        }
        blob = json.dumps(definition, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def self_check_principle(principle, payload, params=None, examples=None):
    """Gemini's self-check: (ok, passed, failed) with named codes.

    Checks, in order: payload signature, learned invariants,
    learned excluders, trap diagnostics for sequence principles,
    and agreement with the task's own sample pairs when supplied.
    """
    passed, failed = [], []
    feats = features(payload)
    if principle.payload_kind is not None:
        if feats["kind"] != principle.payload_kind:
            failed.append("signature_mismatch")
        else:
            passed.append("signature")
    for name in sorted(principle.invariants):
        if _INVARIANTS[name](feats):
            passed.append(f"invariant:{name}")
        else:
            failed.append(f"invariant_violated:{name}")
    for name in sorted(principle.excluders):
        if _INVARIANTS[name](feats):
            failed.append(f"excluder_present:{name}")
        else:
            passed.append(f"excluder_absent:{name}")
    diag = None
    if feats["is_numeric_sequence"]:
        diag = sequence_diagnostics(payload)
    if principle.ratio_mode == "additive_diff":
        if diag and diag["multiplicative"] and not diag["additive"]:
            failed.append("trap_mismatch:multiplicative_progression")
    if principle.ratio_mode == "multiplicative_ratio":
        if diag and diag["additive"] and not diag["multiplicative"]:
            failed.append("trap_mismatch:additive_progression")
    if examples:
        for ex_in, ex_out in examples:
            try:
                got = run_program(principle.program, ex_in, params)
            except Exception:
                got = None
            if got is None or _normalise_answer(_render(got)) != (
                    _normalise_answer(_render(ex_out))):
                failed.append("sample_pair_contradiction")
                break
        else:
            passed.append("sample_pairs")
    return (not failed), passed, failed


def learn_from_failure(principle, payload) -> None:
    """Turn a misfire into an excluder (Claude's learn_from_failure).

    Any catalog predicate true on the failing payload and false on
    EVERY positive episode becomes a forbidding excluder: negative
    transfer becomes data that sharpens the boundary.
    """
    feats = features(payload)
    for name, pred in _INVARIANTS.items():
        try:
            if pred(feats) and not any(
                    pred(pf) for pf in principle.positives_features):
                principle.excluders = principle.excluders | {name}
        except Exception:
            continue
    principle.n_neg += 1


# -- frames: factory prompts and few-shot prompts ------------------------------

_EXPR_RE = re.compile(r"What is ([0-9]+) ([+\-*]) ([0-9]+) ([+\-*]) ([0-9]+)\?")
_SEQ_RE = re.compile(
    r"What is the next number in this sequence: ([0-9, \-]+), \.\.\.\?")
_LARGEST_RE = re.compile(
    r"What is the largest number in this list: ([0-9, ]+)\?")
_REVERSE_RE = re.compile(r"Reverse the string '([a-z]+)'\.")
_NTH_RE = re.compile(
    r"What is word number ([0-9]+) in this list: ([a-z ]+)\?")
_PARITY_RE = re.compile(r"Is ([0-9]+) even or odd\?")

# shape -> (prims searched at derivation, payload_kind, ratio modes)
_SHAPE_PRIMS = {
    "expression": (("eval_precedence", "eval_left_to_right",
                    "eval_sum_all"), "expr"),
    "string-transform": (("reverse", "identity", "swap_ends"), "str"),
    "list-extreme": (("max", "min", "first", "last"), "numlist"),
    "sequence-next": (("extrap_add", "extrap_add2", "extrap_mul",
                       "plus_one", "plus_first"), "numlist"),
    "list-index": (("pick_kth", "pick_kth0", "first", "last"), "wordlist"),
    "number-property": (("parity_word", "parity_inverted"), "int"),
}

_PROGRAM_PRECONDITIONS = {
    "extrap_add": (frozenset({"diag_additive"}), "additive_diff"),
    "extrap_add2": (frozenset({"diag_second_diff"}), "additive_diff"),
    "extrap_mul": (frozenset({"diag_multiplicative"}),
                   "multiplicative_ratio"),
}


def _ints(text):
    return [int(part) for part in text.split(",") if part.strip()]


def parse_factory_frame(prompt):
    """Prompt -> (shape, payload, params) or None. Name-free shapes."""
    if not isinstance(prompt, str):
        return None
    m = _EXPR_RE.fullmatch(prompt)
    if m:
        a, op1, b, op2, c = m.groups()
        return ("expression",
                (int(a), op1, int(b), op2, int(c)), {})
    m = _SEQ_RE.fullmatch(prompt)
    if m:
        return "sequence-next", _ints(m.group(1)), {}
    m = _LARGEST_RE.fullmatch(prompt)
    if m:
        return "list-extreme", _ints(m.group(1)), {}
    m = _REVERSE_RE.fullmatch(prompt)
    if m:
        return "string-transform", m.group(1), {}
    m = _NTH_RE.fullmatch(prompt)
    if m:
        return ("list-index", m.group(2).split(),
                {"k": int(m.group(1))})
    m = _PARITY_RE.fullmatch(prompt)
    if m:
        return "number-property", int(m.group(1)), {}
    return None


_FEWSHOT_RE = re.compile(
    r"Learn from examples: (.+)\. Now solve: (.+) => \?")


def parse_fewshot(prompt):
    """Few-shot prompt -> (examples, query) or None.

    Examples are (input, output) literal pairs; anything that does
    not parse cleanly returns None (the engine abstains).
    """
    if not isinstance(prompt, str):
        return None
    m = _FEWSHOT_RE.fullmatch(prompt)
    if not m:
        return None
    try:
        examples = []
        for pair in m.group(1).split("; "):
            left, right = pair.split(" => ")
            examples.append((ast.literal_eval(left),
                             ast.literal_eval(right)))
        query = ast.literal_eval(m.group(2))
    except Exception:
        return None
    return examples, query


def _render(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_render(v) for v in value) + "]"
    if isinstance(value, str):
        return value
    return str(value)


def _expected_value(shape, expected: str):
    if shape in ("expression", "list-extreme", "sequence-next",
                 "number-property") and shape != "number-property":
        return int(expected)
    return expected


# -- derivation from public practice items -------------------------------------

# Synthetic probes used only to test whether two tied programs
# actually disagree somewhere in their shape's domain.
_TIE_PROBES = {
    "expression": [(2, "+", 3, "*", 4), (2, "*", 3, "+", 4),
                   (5, "-", 2, "*", 3), (4, "*", 2, "-", 1)],
    "string-transform": ["abcd", "wxyz"],
    "list-extreme": [[3, 1, 4], [9, 2, 7]],
    "list-index": [(["a", "b", "c"], {"k": 2}),
                   (["x", "y", "z"], {"k": 1})],
    "number-property": [3, 8],
}


def _probe_disagreement(shape, prog_a, prog_b, episodes) -> bool:
    probes = _TIE_PROBES.get(shape, [])
    cases = []
    for probe in probes:
        if shape == "list-index":
            cases.append((probe[0], probe[1]))
        else:
            cases.append((probe, episodes[0][1] if episodes else {}))
    for payload, params in cases:
        try:
            va = run_program(prog_a, payload, params)
        except Exception:
            va = None
        try:
            vb = run_program(prog_b, payload, params)
        except Exception:
            vb = None
        if va != vb:
            return True
    return False


def derive_principles(public_items) -> dict:
    """Derive principles from public practice items only.

    Items are clustered by semantic shape (never family name).
    Per cluster, every candidate primitive is scored for
    consistency with ALL episodes. A program is stored only with
    the preconditions its form mathematically requires. When two
    consistent programs share the same preconditions and disagree
    somewhere in the shape's domain, the evidence cannot
    distinguish them and derivation abstains — the audit records
    the tie instead of storing a coin flip as a fact.
    """
    clusters: dict[str, list] = {}
    unclassified = 0
    for item in public_items:
        frame = parse_factory_frame(item.get("prompt"))
        if frame is None:
            unclassified += 1
            continue
        shape, payload, params = frame
        expected = item["expected"]
        if shape in ("expression", "list-extreme", "sequence-next"):
            expected = int(expected)
        clusters.setdefault(shape, []).append((payload, params, expected))

    principles = []
    audit_clusters = {}
    for shape in sorted(clusters):
        episodes = clusters[shape]
        prim_names, payload_kind = _SHAPE_PRIMS[shape]
        record = {"n": len(episodes), "programs": [], "tied": []}
        if len(episodes) < MIN_CLUSTER_ITEMS:
            record["decision"] = "insufficient_items"
            audit_clusters[shape] = record
            continue
        consistent = [name for name in prim_names
                      if _consistent((name,), episodes)]
        record["consistent"] = consistent
        if not consistent:
            record["decision"] = "no_consistent_program"
            audit_clusters[shape] = record
            continue
        # Group consistent programs by their precondition set.
        groups: dict[frozenset, list] = {}
        for name in consistent:
            inv, _mode = _PROGRAM_PRECONDITIONS.get(
                name, (frozenset(), None))
            groups.setdefault(inv, []).append(name)
        abstained = False
        for inv, names in sorted(groups.items(), key=lambda kv: sorted(kv[1])):
            if len(names) > 1:
                # Same preconditions: storable only if the programs
                # never disagree in the shape's domain.
                base = names[0]
                if any(_probe_disagreement(shape, (base,), (other,),
                                           episodes)
                       for other in names[1:]):
                    record["tied"] = names
                    abstained = True
                    continue
            for name in names:
                _inv, mode = _PROGRAM_PRECONDITIONS.get(
                    name, (frozenset(), None))
                principle = Principle(
                    id=f"{shape}:{'/'.join((name,))}",
                    program=(name,), shape=shape, ratio_mode=mode,
                    invariants=inv, payload_kind=payload_kind,
                    positives_features=[features(p)
                                        for p, _pa, _e in episodes[:32]],
                    n_pos=len(episodes), n_neg=0)
                principles.append(principle)
                record["programs"].append(name)
        record["decision"] = ("abstain_tie" if abstained
                              and not record["programs"]
                              else "stored" if record["programs"]
                              else "abstain_tie")
        audit_clusters[shape] = record
    return {"principles": principles,
            "audit": {"clusters": audit_clusters,
                      "unclassified": unclassified}}


# -- the engine ------------------------------------------------------------------

class TransferMemoryEngine:
    """Gemini's TransferMemoryEngine: evaluate_and_apply or ABSTAIN.

    solve() returns the answer string ("" = abstained / no
    answer). explain() returns the full assessment: verdict
    (APPLY / FALLBACK / ABSTAIN), source, principle id, and the
    named failure codes the guard produced. ABSTAIN carries
    output "" — never a manufactured guess (Gemini).
    """

    def __init__(self, principles=(), *, baseline=None,
                 induction_enabled=True):
        self.principles = list(principles)
        self.baseline = baseline if baseline is not None \
            else StrategySolver()
        self.induction_enabled = induction_enabled

    # Gemini's name for the assessment entry point.
    def evaluate_and_apply(self, prompt) -> dict:
        return self.explain(prompt)

    def solve(self, prompt) -> str:
        return self.explain(prompt)["answer"]

    def explain(self, prompt) -> dict:
        if isinstance(prompt, str) and prompt.startswith(
                "Learn from examples:"):
            return self._explain_fewshot(prompt)
        return self._explain_factory(prompt)

    # -- factory prompts: stored principles + naive fallback -----------
    def _explain_factory(self, prompt) -> dict:
        # parse_factory_frame is authoritative for the engine: it
        # accepts negative sequence terms, which the baseline
        # classifier cannot parse — those prompts must still reach
        # the guard (legitimate negative additive sequences apply;
        # alternating-sign traps are refused by it, not by a
        # parser mismatch upstream).
        frame = parse_factory_frame(prompt)
        if frame is None:
            return {"answer": "", "verdict": "ABSTAIN",
                    "source": "none", "principle_id": None,
                    "failure_codes": ["unclassifiable"]}
        shape, payload, params = frame
        passed, codes = [], []
        for principle in self.principles:
            if principle.shape != shape:
                continue
            ok, _p, failed = self_check_principle(
                principle, payload, params)
            codes.extend(failed)
            if ok:
                try:
                    passed.append((principle,
                                   run_program(principle.program,
                                               payload, params)))
                except Exception:
                    codes.append("program_error")
        predictions = {_render(v) for _pr, v in passed}
        if len(predictions) == 1:
            principle, value = passed[0]
            return {"answer": _render(value), "verdict": "APPLY",
                    "source": "principle", "principle_id": principle.id,
                    "failure_codes": codes}
        if len(predictions) > 1:
            codes.append("ambiguous_competition")
        return {"answer": self.baseline.solve(prompt),
                "verdict": "FALLBACK", "source": "baseline",
                "principle_id": None, "failure_codes": codes}

    # -- few-shot prompts: stored principles, then induction -----------
    def _explain_fewshot(self, prompt) -> dict:
        parsed = parse_fewshot(prompt)
        if parsed is None:
            return {"answer": "", "verdict": "ABSTAIN",
                    "source": "none", "principle_id": None,
                    "failure_codes": ["corrupted_input"]}
        examples, query = parsed
        codes = []
        passed = []
        for principle in self.principles:
            ok, _p, failed = self_check_principle(
                principle, query, {}, examples=examples)
            codes.extend(failed)
            if ok:
                try:
                    passed.append((principle,
                                   run_program(principle.program,
                                               query, {})))
                except Exception:
                    codes.append("program_error")
        stored_predictions = {_render_query(v) for _pr, v in passed}
        if len(stored_predictions) > 1:
            return {"answer": "", "verdict": "ABSTAIN",
                    "source": "none", "principle_id": None,
                    "failure_codes": codes + ["ambiguous_competition"]}
        if not self.induction_enabled:
            if stored_predictions:
                principle, value = passed[0]
                return {"answer": _render_query(value),
                        "verdict": "APPLY", "source": "principle",
                        "principle_id": principle.id,
                        "failure_codes": codes}
            return {"answer": "", "verdict": "ABSTAIN",
                    "source": "none", "principle_id": None,
                    "failure_codes": codes + ["induction_disabled"]}
        # Cross-check: a stored principle that passes the sample
        # check may still be the WRONG explanation of the samples
        # (three examples where last == max in every one cannot
        # distinguish the two). The stored prediction must agree
        # with every shortest program the samples themselves
        # induce; disagreement is ambiguity, and ambiguity abstains.
        episodes = [(ex_in, {}, ex_out) for ex_in, ex_out in examples]
        programs = induce_program(episodes, max_depth=3)
        induced_predictions = set()
        for program in programs:
            try:
                induced_predictions.add(
                    _render_query(run_program(program, query, {})))
            except Exception:
                continue
        all_predictions = stored_predictions | induced_predictions
        if len(all_predictions) > 1:
            return {"answer": "", "verdict": "ABSTAIN",
                    "source": "none", "principle_id": None,
                    "failure_codes": codes + [
                        "stored_induced_disagreement"
                        if stored_predictions else "ambiguous_induction"]}
        if stored_predictions:
            principle, value = passed[0]
            return {"answer": _render_query(value), "verdict": "APPLY",
                    "source": "principle", "principle_id": principle.id,
                    "failure_codes": codes}
        if induced_predictions:
            return {"answer": induced_predictions.pop(),
                    "verdict": "APPLY", "source": "induced",
                    "principle_id": None, "failure_codes": codes}
        codes.append("no_consistent_program")
        return {"answer": "", "verdict": "ABSTAIN",
                "source": "none", "principle_id": None,
                "failure_codes": codes}


def _render_query(value) -> str:
    """Render a few-shot answer exactly as memory.heldout35.render."""
    if isinstance(value, list):
        return "[" + ", ".join(_render_query(v) for v in value) + "]"
    if isinstance(value, str):
        return "'" + value + "'"
    return str(value)
