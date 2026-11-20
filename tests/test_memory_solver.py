"""Tests for the strategy solver and lesson derivation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.solver import StrategySolver, classify, derive_lessons

ARITH = "What is 2 + 3 * 4?"
SUBMULT = "What is 2 * 3 - 4?"
REVERSE = "Reverse the string 'abcde'."
LARGEST = "What is the largest number in this list: 6, 3, 9, 7?"
SEQUENCE = "What is the next number in this sequence: 2, 5, 8, 11, ...?"
NTH = "What is word number 2 in this list: alpha bravo charlie delta?"
PARITY = "Is 7 even or odd?"


def lesson(family, token, kind="strategy", entry_id=None):
    return {"id": entry_id or f"lesson-{family}",
            "domain": f"factory-{family}", "kind": kind, "content": token}


def solver_with(*lessons):
    return StrategySolver(lessons_override=list(lessons))


class ClassifyTests(unittest.TestCase):
    def test_classify_each_family(self):
        cases = {ARITH: "arithmetic", SUBMULT: "subtract-multiply",
                 REVERSE: "reverse", LARGEST: "largest",
                 SEQUENCE: "sequence", NTH: "nth-word", PARITY: "parity"}
        for prompt, family in cases.items():
            self.assertEqual(classify(prompt), family, prompt)

    def test_classify_unknown_returns_none(self):
        self.assertIsNone(classify("What is 2 + 2?"))
        self.assertIsNone(classify("Tell me a story."))
        self.assertIsNone(classify(None))

    def test_detect_subtract_multiply_not_arithmetic(self):
        self.assertEqual(classify("What is 6 * 3 - 4?"),
                         "subtract-multiply")

    def test_detect_largest_not_sequence(self):
        self.assertEqual(
            classify("What is the largest number in this list: 7, 42, 9, 13?"),
            "largest")
        self.assertEqual(
            classify("What is the next number in this sequence: "
                     "3, 7, 11, 15, ...?"), "sequence")


class NaiveTests(unittest.TestCase):
    def setUp(self):
        self.solver = StrategySolver()

    def test_naive_answers(self):
        cases = [
            (ARITH, "20"),        # (2+3)*4, left-to-right
            (SUBMULT, "2"),       # naive already correct
            (REVERSE, "abcde"),   # identity
            (LARGEST, "6"),       # first
            (SEQUENCE, "12"),     # last + 1
            (NTH, "charlie"),     # 0-indexed
            (PARITY, "odd"),      # naive already correct
        ]
        for prompt, expected in cases:
            self.assertEqual(self.solver.solve(prompt), expected, prompt)

    def test_naive_subtract_multiply_negative(self):
        self.assertEqual(self.solver.solve("What is 2 * 2 - 9?"), "-5")

    def test_unknown_prompt_returns_empty_not_raise(self):
        self.assertEqual(self.solver.solve("What is 2 + 2?"), "")
        exp = self.solver.explain("What is 2 + 2?")
        self.assertIsNone(exp.family)
        self.assertEqual(exp.answer, "")

    def test_nth_word_k_equals_size_zero_indexed_no_crash(self):
        prompt = ("What is word number 4 in this list: "
                  "alpha bravo charlie delta?")
        self.assertEqual(self.solver.solve(prompt), "")

    def test_output_is_bare(self):
        for prompt in (ARITH, REVERSE, LARGEST, SEQUENCE, NTH, PARITY):
            answer = self.solver.solve(prompt)
            self.assertEqual(answer, answer.strip())
            self.assertNotIn("?", answer)
            self.assertNotIn("'", answer)


class LessonDispatchTests(unittest.TestCase):
    def test_correct_lessons_override(self):
        cases = [
            ("arithmetic", "precedence", ARITH, "14"),
            ("reverse", "full-reverse", REVERSE, "edcba"),
            ("largest", "scan-max", LARGEST, "9"),
            ("sequence", "plus-step", SEQUENCE, "14"),
            ("nth-word", "one-indexed", NTH, "bravo"),
        ]
        for family, token, prompt, expected in cases:
            solver = solver_with(lesson(family, token))
            self.assertEqual(solver.solve(prompt), expected, prompt)
            exp = solver.explain(prompt)
            self.assertEqual(exp.source, "lesson")
            self.assertEqual(exp.strategy, token)
            self.assertEqual(exp.lesson_id, f"lesson-{family}")

    def test_wrong_extra_tokens_compute_wrong_answers(self):
        cases = [
            ("arithmetic", "sum-all", ARITH, "9"),
            ("subtract-multiply", "subtract-first", SUBMULT, "-2"),
            ("subtract-multiply", "add-instead", SUBMULT, "10"),
            ("reverse", "swap-ends", REVERSE, "ebcda"),
            ("largest", "last", LARGEST, "7"),
            ("largest", "smallest", LARGEST, "3"),
            ("sequence", "plus-first-term", SEQUENCE, "13"),
            ("nth-word", "last-word", NTH, "delta"),
            ("nth-word", "first-word", NTH, "alpha"),
            ("parity", "inverted-parity", PARITY, "even"),
        ]
        for family, token, prompt, expected in cases:
            solver = solver_with(lesson(family, token))
            self.assertEqual(solver.solve(prompt), expected,
                             f"{family}/{token}")

    def test_unknown_token_falls_back_to_naive(self):
        solver = solver_with(lesson("reverse", "banana"))
        self.assertEqual(solver.solve(REVERSE), "abcde")
        self.assertEqual(solver.explain(REVERSE).source, "naive")

    def test_cross_family_token_ignored(self):
        solver = solver_with(lesson("reverse", "precedence"))
        self.assertEqual(solver.solve(REVERSE), "abcde")

    def test_wrong_kind_ignored(self):
        solver = solver_with(lesson("arithmetic", "precedence", kind="fact"))
        self.assertEqual(solver.solve(ARITH), "20")

    def test_last_valid_lesson_wins(self):
        solver = solver_with(lesson("arithmetic", "precedence", entry_id="l1"),
                             lesson("arithmetic", "sum-all", entry_id="l2"))
        self.assertEqual(solver.solve(ARITH), "9")
        solver = solver_with(lesson("arithmetic", "sum-all", entry_id="l1"),
                             lesson("arithmetic", "precedence", entry_id="l2"))
        self.assertEqual(solver.solve(ARITH), "14")

    def test_invalid_then_valid_lesson_valid_executes(self):
        solver = solver_with(lesson("arithmetic", "precedence", entry_id="l1"),
                             lesson("arithmetic", "banana", entry_id="l2"))
        self.assertEqual(solver.solve(ARITH), "14")

    def test_nth_word_k_one_discriminates(self):
        prompt = ("What is word number 1 in this list: "
                  "alpha bravo charlie delta echo?")
        self.assertEqual(StrategySolver().solve(prompt), "bravo")
        solver = solver_with(lesson("nth-word", "one-indexed"))
        self.assertEqual(solver.solve(prompt), "alpha")

    def test_explain_matches_solve(self):
        solver = solver_with(lesson("largest", "scan-max"))
        for prompt in (ARITH, SUBMULT, REVERSE, LARGEST, SEQUENCE, NTH,
                       PARITY, "What is 2 + 2?"):
            self.assertEqual(solver.solve(prompt),
                             solver.explain(prompt).answer, prompt)

    def test_solver_deterministic(self):
        solver = solver_with(lesson("sequence", "plus-step"))
        for prompt in (ARITH, REVERSE, SEQUENCE, NTH):
            self.assertEqual(solver.solve(prompt), solver.solve(prompt))


def pub(item_id, prompt, expected):
    return {"id": item_id, "domain": "factory-x", "prompt": prompt,
            "expected": expected}


def nth_items(n, start=0):
    words = ["alpha", "bravo", "charlie", "delta", "echo"]
    items = []
    for i in range(n):
        k = (i % 4) + 1
        items.append(pub(f"pub-nth-{start + i}",
                         f"What is word number {k} in this list: "
                         f"{' '.join(words)}?", words[k - 1]))
    return items


class DerivationTests(unittest.TestCase):
    def test_lesson_proposed_when_correct_beats_naive_by_margin(self):
        result = derive_lessons(nth_items(6))
        self.assertEqual(len(result["lessons"]), 1)
        proposed = result["lessons"][0]
        self.assertEqual(proposed["family"], "nth-word")
        self.assertEqual(proposed["content"], "one-indexed")
        record = result["audit"]["families"]["nth-word"]
        self.assertEqual(record["decision"], "proposed")
        self.assertEqual(record["naive_correct"], 0)

    def test_no_lesson_when_naive_already_best(self):
        items = [pub(f"pub-sub-{i}", f"What is {i + 2} * 3 - 4?",
                     str((i + 2) * 3 - 4)) for i in range(5)]
        result = derive_lessons(items)
        self.assertEqual(result["lessons"], [])
        record = result["audit"]["families"]["subtract-multiply"]
        self.assertEqual(record["decision"], "naive_best")

    def test_no_lesson_on_tie_between_non_naive_tokens(self):
        # step == first term, so plus-step and plus-first-term agree
        # on every item and tie at the top: derivation must abstain.
        items = [pub(f"pub-seq-{i}",
                     "What is the next number in this sequence: "
                     "3, 6, 9, 12, ...?", "15") for i in range(5)]
        result = derive_lessons(items)
        self.assertEqual(result["lessons"], [])
        record = result["audit"]["families"]["sequence"]
        self.assertEqual(record["decision"], "tie_at_top")

    def test_no_lesson_below_min_items(self):
        result = derive_lessons(nth_items(3))
        self.assertEqual(result["lessons"], [])
        record = result["audit"]["families"]["nth-word"]
        self.assertEqual(record["decision"], "insufficient_items")

    def test_no_lesson_when_margin_too_small(self):
        # scan-max beats first by exactly one item out of five.
        items = [
            pub("pub-lg-0", "What is the largest number in this list: "
                "9, 1, 2, 3?", "9"),
            pub("pub-lg-1", "What is the largest number in this list: "
                "8, 1, 2, 3?", "8"),
            pub("pub-lg-2", "What is the largest number in this list: "
                "7, 1, 2, 3?", "7"),
            pub("pub-lg-3", "What is the largest number in this list: "
                "6, 1, 2, 3?", "6"),
            pub("pub-lg-4", "What is the largest number in this list: "
                "1, 9, 2, 3?", "9"),
        ]
        result = derive_lessons(items)
        self.assertEqual(result["lessons"], [])
        record = result["audit"]["families"]["largest"]
        self.assertEqual(record["decision"], "margin_not_met")

    def test_unclassified_items_excluded_and_counted(self):
        items = nth_items(5) + [pub("pub-x", "What is 2 + 2?", "4")]
        result = derive_lessons(items)
        self.assertEqual(result["audit"]["unclassified"], 1)
        self.assertEqual(len(result["lessons"]), 1)

    def test_evidence_ref_binds_public_content(self):
        first = derive_lessons(nth_items(5))
        changed = nth_items(5)
        changed[0] = dict(changed[0], expected="delta")
        second = derive_lessons(changed)
        self.assertNotEqual(first["audit"]["public_digest"],
                            second["audit"]["public_digest"])
        self.assertNotEqual(first["lessons"][0]["evidence_ref"],
                            second["lessons"][0]["evidence_ref"]
                            if second["lessons"] else "changed-anyway")

    def test_derivation_is_deterministic(self):
        items = nth_items(6)
        one = derive_lessons(items)
        two = derive_lessons(list(items))
        self.assertEqual(one["lessons"], two["lessons"])
        self.assertEqual(one["audit"]["public_digest"],
                         two["audit"]["public_digest"])

    def test_audit_emitted_for_no_lesson_families(self):
        result = derive_lessons(nth_items(5))
        self.assertIn("nth-word", result["audit"]["families"])
        self.assertIn("arithmetic", result["audit"]["families_absent"])


if __name__ == "__main__":
    unittest.main()
