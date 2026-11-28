"""Tests for trust.budgets — in-verifier sealed-eval query
budgets (Trust Boundary v2, item 5). All stores live in temp
directories; no real verifier home is touched.

Review fix round (Trust Boundary v2): detection is now
IDENTITY-scoped (HIGH-1), probes also count on an absolute
differing-positions rule (HIGH-2), the store is hash-chained
with verify_integrity()/head_hash() (MEDIUM-1), and a two-phase
check_only/record API exists (MEDIUM-2). Three pre-existing
tests were updated where those mandated behaviour changes force
it, each with an inline "UPDATED" rationale:
test_byte_identical_replay_refused_and_free (replay is now
identity-scoped, so the same transcript under a different
proposal label IS a replay for the same identity),
test_near_duplicate_probes_latch_at_limit (probe counting and
the latch are identity-scoped and family-scoped), and
test_below_threshold_similarity_is_not_a_probe (accessor scope).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust.budgets import (
    GENESIS_CHAIN_HASH,
    BudgetError,
    BudgetStore,
    differing_positions,
    transcript_similarity,
)

IDENTITY = "verifier-actor"
OTHER_IDENTITY = "second-actor"


def transcript(tag, n=10):
    """A positional transcript of n distinct answers."""
    return [f"{tag}-answer-{i}" for i in range(n)]


def variant(base, changes):
    """base with the given {position: new_answer} replacements."""
    out = list(base)
    for pos, value in changes.items():
        out[pos] = value
    return out


class BudgetStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"

    def store(self, **kwargs):
        return BudgetStore(self.path, **kwargs)

    def reason(self, fn, *args):
        with self.assertRaises(BudgetError) as ctx:
            fn(*args)
        return ctx.exception.reason

    # -- caps ---------------------------------------------------------

    def test_proposal_cap_enforced_exactly_at_boundary(self):
        store = self.store(per_proposal_cap=3, per_identity_cap=100)
        for i in range(3):
            self.assertIsNone(store.check_and_record(
                IDENTITY, "prop-a", transcript(f"t{i}")))
        self.assertEqual(store.proposal_count("prop-a"), 3)
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-a",
                        transcript("t3")),
            "proposal_budget_exceeded")
        # The refused query was not recorded.
        self.assertEqual(store.proposal_count("prop-a"), 3)

    def test_default_caps_are_the_documented_values(self):
        store = self.store()
        self.assertEqual(store.per_proposal_cap, 25)
        self.assertEqual(store.per_identity_cap, 500)

    def test_identity_cap_spans_proposals(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=2)
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        store.check_and_record(IDENTITY, "prop-b", transcript("b"))
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-c",
                        transcript("c")),
            "identity_budget_exceeded")
        # A different identity is unaffected by the first one's cap.
        self.assertIsNone(store.check_and_record(
            OTHER_IDENTITY, "prop-c", transcript("c")))

    def test_per_proposal_isolation(self):
        store = self.store(per_proposal_cap=1, per_identity_cap=100)
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-a",
                        transcript("a2")),
            "proposal_budget_exceeded")
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-b", transcript("b")))

    # -- replay ---------------------------------------------------------

    def test_byte_identical_replay_refused_and_free(self):
        store = self.store(per_proposal_cap=2, per_identity_cap=100)
        answers = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", answers)
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-a",
                        list(answers)),
            "transcript_replay")
        # Replay did not consume budget: one more fresh transcript
        # still fits under the cap of 2.
        self.assertEqual(store.proposal_count("prop-a"), 1)
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-a", transcript("fresh")))
        # UPDATED (review HIGH-1): replay detection is
        # IDENTITY-scoped now, so the same transcript under a
        # DIFFERENT proposal label IS a replay for the same
        # identity — the old per-proposal assertion here encoded
        # exactly the label-rotation hole the fix closes.
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-b",
                        answers),
            "transcript_replay")
        # A DIFFERENT identity submitting the same transcript is
        # not a replay: identities are budgeted independently.
        self.assertIsNone(store.check_and_record(
            OTHER_IDENTITY, "prop-b", answers))

    # -- adaptive-query detection ---------------------------------------

    def test_similarity_metric(self):
        base = [f"h{i}" for i in range(10)]
        self.assertEqual(transcript_similarity(base, base), 1.0)
        half = base[:5] + ["x"] * 5
        self.assertEqual(transcript_similarity(base, half), 0.5)
        self.assertEqual(transcript_similarity(base, ["y"] * 10), 0.0)
        # Padding cannot dilute: denominator is the longer length.
        self.assertEqual(transcript_similarity(base, base + ["z"]), 10 / 11)

    def test_near_duplicate_probes_latch_at_limit(self):
        # UPDATED (review HIGH-1): probe counting is
        # IDENTITY-scoped (the accessor takes an identity now) and
        # the latch is scoped to the probed transcript FAMILY for
        # that identity — the old assertions encoded per-proposal
        # counting and a per-proposal total latch, both of which
        # label rotation defeated / mis-scoped.
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", base)
        # Each variant differs from base in exactly 2 of 10
        # positions: similarity 0.8, exactly at the threshold.
        probe1 = variant(base, {0: "p1-a", 1: "p1-b"})
        probe2 = variant(base, {2: "p2-a", 3: "p2-b"})
        probe3 = variant(base, {4: "p3-a", 5: "p3-b"})
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-a", probe1))
        self.assertEqual(store.identity_probes(IDENTITY), 1)
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-a", probe2))
        self.assertEqual(store.identity_probes(IDENTITY), 2)
        # The third probe trips the latch and is itself refused.
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-a", probe3),
            "adaptive_query_detected")
        self.assertTrue(store.is_blocked(IDENTITY))
        self.assertEqual(store.blocked_family_count(IDENTITY), 1)
        # The latch follows the identity and the family, not the
        # label: a further near-duplicate of the family is refused
        # under a fresh proposal label too.
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-b",
                        variant(base, {0: "once-more"})),
            "adaptive_query_detected")
        # A completely dissimilar transcript is NOT refused: the
        # latch is family-scoped, on this proposal or another.
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-a", transcript("unrelated")))
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-b", transcript("also-unrelated")))

    def test_below_threshold_similarity_is_not_a_probe(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", base)
        # 0.5-similarity transcripts: half the positions changed.
        w1 = variant(base, {i: f"w1-{i}" for i in range(5)})
        w2 = variant(base, {i: f"w2-{i}" for i in range(5, 10)})
        w3 = variant(base, {i: f"w3-{i}" for i in range(5)})
        for answers in (w1, w2, w3):
            self.assertIsNone(
                store.check_and_record(IDENTITY, "prop-a", answers))
        # UPDATED (accessor scope only): probes are counted per
        # identity now. The behaviour asserted is unchanged —
        # 5 differing positions is neither >= 0.8 similarity nor
        # <= 2 absolute differences, so none of these is a probe.
        self.assertEqual(store.identity_probes(IDENTITY), 0)
        self.assertFalse(store.is_blocked(IDENTITY))
        self.assertEqual(store.proposal_count("prop-a"), 4)

    # -- persistence and corruption -------------------------------------

    def test_persistence_across_instances(self):
        first = self.store(per_proposal_cap=2, per_identity_cap=100)
        first.check_and_record(IDENTITY, "prop-a", transcript("a"))
        second = self.store(per_proposal_cap=2, per_identity_cap=100)
        self.assertEqual(second.proposal_count("prop-a"), 1)
        self.assertEqual(second.identity_count(IDENTITY), 1)
        second.check_and_record(IDENTITY, "prop-a", transcript("b"))
        third = self.store(per_proposal_cap=2, per_identity_cap=100)
        self.assertEqual(
            self.reason(third.check_and_record, IDENTITY, "prop-a",
                        transcript("c")),
            "proposal_budget_exceeded")

    def test_interleaved_instances_do_not_lose_records(self):
        a = self.store(per_proposal_cap=100, per_identity_cap=100)
        b = self.store(per_proposal_cap=100, per_identity_cap=100)
        a.check_and_record(IDENTITY, "prop-a", transcript("a"))
        b.check_and_record(IDENTITY, "prop-a", transcript("b"))
        fresh = self.store()
        self.assertEqual(fresh.proposal_count("prop-a"), 2)
        self.assertEqual(fresh.identity_count(IDENTITY), 2)

    def test_corrupt_store_refuses_and_is_never_reset(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        for garbage in (b"not json", b"{}", b'{"schema_version": 99,'
                        b' "identities": {}, "proposals": {}}'):
            self.path.write_bytes(garbage)
            with self.assertRaises(BudgetError) as ctx:
                self.store()
            self.assertEqual(ctx.exception.reason, "budget_store_corrupt")
            # The corrupt bytes are left exactly as found: no
            # silent reset handed anyone a fresh budget.
            self.assertEqual(self.path.read_bytes(), garbage)

    def test_tampered_accounting_refuses(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        data = json.loads(self.path.read_text())
        data["proposals"]["prop-a"]["count"] = 0  # erase the spend
        self.path.write_text(json.dumps(data))
        with self.assertRaises(BudgetError) as ctx:
            self.store()
        self.assertEqual(ctx.exception.reason, "budget_store_corrupt")

    def test_store_records_hashes_not_answers(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("secret"))
        raw = self.path.read_text()
        self.assertNotIn("secret-answer-0", raw)
        self.assertIn("answers_hash", raw)
        self.assertIn("position_hashes", raw)

    def test_malformed_api_arguments_raise_value_error(self):
        store = self.store()
        with self.assertRaises(ValueError):
            store.check_and_record("Bad Identity!", "prop-a",
                                   transcript("a"))
        with self.assertRaises(ValueError):
            store.check_and_record(IDENTITY, "", transcript("a"))
        with self.assertRaises(ValueError):
            store.check_and_record(IDENTITY, "prop-a", ["ok", 7])


class IdentityScopedDetectionTests(unittest.TestCase):
    """Review HIGH-1: rotating the caller-chosen proposal label
    must not reset replay, similarity or probe detection — all
    three are scoped to the verifier identity across proposals."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"

    def store(self, **kwargs):
        return BudgetStore(self.path, **kwargs)

    def reason(self, fn, *args):
        with self.assertRaises(BudgetError) as ctx:
            fn(*args)
        return ctx.exception.reason

    def test_label_rotation_replay_is_caught(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        answers = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", answers)
        for label in ("prop-b", "prop-c", "fresh-label"):
            self.assertEqual(
                self.reason(store.check_and_record, IDENTITY, label,
                            list(answers)),
                "transcript_replay")
        # None of the rotated replays consumed budget.
        self.assertEqual(store.identity_count(IDENTITY), 1)

    def test_label_rotation_probes_accumulate_and_latch(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", base)
        # One probe per fresh label: per-label counting would see
        # one probe each and never latch; identity counting sees
        # three and latches.
        probe1 = variant(base, {0: "r1-a", 1: "r1-b"})
        probe2 = variant(base, {2: "r2-a", 3: "r2-b"})
        probe3 = variant(base, {4: "r3-a", 5: "r3-b"})
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-b",
                                                 probe1))
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-c",
                                                 probe2))
        self.assertEqual(store.identity_probes(IDENTITY), 2)
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-d",
                        probe3),
            "adaptive_query_detected")
        # The latch is not escapable by rotating the label again.
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-e",
                        variant(base, {9: "one-more"})),
            "adaptive_query_detected")

    def test_detection_does_not_leak_across_identities(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.check_and_record(IDENTITY, "prop-a", base)
        store.check_and_record(IDENTITY, "prop-a",
                               variant(base, {0: "x", 1: "y"}))
        self.assertEqual(store.identity_probes(IDENTITY), 1)
        # The other identity starts clean: the same transcript is
        # not its replay, and its near-duplicate is its FIRST
        # probe, not a continuation of the first identity's.
        self.assertIsNone(store.check_and_record(
            OTHER_IDENTITY, "prop-a", base))
        self.assertIsNone(store.check_and_record(
            OTHER_IDENTITY, "prop-a", variant(base, {0: "x", 1: "y"})))
        self.assertEqual(store.identity_probes(OTHER_IDENTITY), 1)
        self.assertFalse(store.is_blocked(OTHER_IDENTITY))


class AbsoluteDifferenceProbeTests(unittest.TestCase):
    """Review HIGH-2: probes whose similarity FRACTION is below
    0.8 still count when the absolute number of differing
    positions is <= 2 — decisively for small sealed sets, where
    the fraction detector can never fire on single-position
    probes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"

    def store(self, **kwargs):
        return BudgetStore(self.path, **kwargs)

    def reason(self, fn, *args):
        with self.assertRaises(BudgetError) as ctx:
            fn(*args)
        return ctx.exception.reason

    def test_differing_positions_metric(self):
        self.assertEqual(
            differing_positions(["a", "b", "c"], ["a", "x", "c"]), 1)
        self.assertEqual(
            differing_positions(["a", "b"], ["x", "y"]), 2)
        # Positions beyond the shorter transcript differ.
        self.assertEqual(differing_positions(["a"], ["a", "b"]), 1)
        self.assertEqual(differing_positions([], []), 0)

    def test_small_set_single_position_probes_count_and_latch(self):
        # n=3: a single-position probe has similarity 2/3 = 0.667,
        # far below the 0.8 fraction threshold — under the old
        # detector these NEVER counted. Absolute difference is 1.
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("tiny", n=3)
        store.check_and_record(IDENTITY, "prop-a", base)
        probe1 = variant(base, {0: "s1"})
        probe2 = variant(base, {1: "s2"})
        probe3 = variant(base, {2: "s3"})
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-a",
                                                 probe1))
        self.assertEqual(store.identity_probes(IDENTITY), 1)
        self.assertIsNone(store.check_and_record(IDENTITY, "prop-a",
                                                 probe2))
        self.assertEqual(store.identity_probes(IDENTITY), 2)
        self.assertEqual(
            self.reason(store.check_and_record, IDENTITY, "prop-a",
                        probe3),
            "adaptive_query_detected")
        self.assertTrue(store.is_blocked(IDENTITY, base))

    def test_two_differing_positions_count_below_fraction(self):
        # n=5, 2 differing positions: similarity 0.6 (< 0.8) but
        # absolute difference 2 — a probe under the absolute rule.
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("five", n=5)
        store.check_and_record(IDENTITY, "prop-a", base)
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-a", variant(base, {0: "d1", 4: "d2"})))
        self.assertEqual(store.identity_probes(IDENTITY), 1)

    def test_three_differing_positions_do_not_count(self):
        # n=10, 3 differing positions: similarity 0.7 (< 0.8) AND
        # absolute difference 3 (> 2) — not a probe under either
        # rule. (0.70 was one of the review's invisible probes
        # at n=3..4 scale; at n=10 a 3-position change is a
        # genuinely different transcript, and the fraction rule
        # takes over from 2 differing positions upward in effect
        # because 2/10 already reaches the 0.8 threshold.)
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("ten")
        store.check_and_record(IDENTITY, "prop-a", base)
        self.assertIsNone(store.check_and_record(
            IDENTITY, "prop-a",
            variant(base, {0: "e1", 1: "e2", 2: "e3"})))
        self.assertEqual(store.identity_probes(IDENTITY), 0)


class IntegrityTests(unittest.TestCase):
    """Review MEDIUM-1: the persisted state is hash-chained;
    tampering that keeps the structural invariants consistent
    still fails, verify_integrity() reports it without raising,
    and head_hash() gives an external anchor something to pin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"

    def store(self, **kwargs):
        return BudgetStore(self.path, **kwargs)

    def test_fresh_store_head_is_genesis_and_integrity_clean(self):
        store = self.store()
        self.assertEqual(store.head_hash(), GENESIS_CHAIN_HASH)
        self.assertEqual(store.verify_integrity(), ())
        self.assertEqual(
            store.verify_integrity(expected_head=GENESIS_CHAIN_HASH),
            ())

    def test_head_advances_with_each_record(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        head1 = store.head_hash()
        self.assertNotEqual(head1, GENESIS_CHAIN_HASH)
        self.assertEqual(store.verify_integrity(), ())
        self.assertEqual(store.verify_integrity(expected_head=head1),
                         ())
        store.check_and_record(IDENTITY, "prop-a", transcript("b"))
        self.assertNotEqual(store.head_hash(), head1)

    def test_invariant_consistent_tamper_fails_chain(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        witness = self.store()  # constructed before the tamper
        data = json.loads(self.path.read_text())
        # Erase the spend CONSISTENTLY: transcript removed and
        # both counts fixed, so every structural invariant still
        # holds. Only the hash chain can catch this.
        data["proposals"]["prop-a"]["transcripts"] = []
        data["proposals"]["prop-a"]["count"] = 0
        data["identities"][IDENTITY]["count"] = 0
        self.path.write_text(json.dumps(data))
        self.assertEqual(witness.verify_integrity(),
                         ("budget_store_corrupt",))
        with self.assertRaises(BudgetError) as ctx:
            self.store()
        self.assertEqual(ctx.exception.reason, "budget_store_corrupt")

    def test_rollback_detected_only_against_pinned_head(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        snapshot = self.path.read_bytes()
        store.check_and_record(IDENTITY, "prop-a", transcript("b"))
        pinned = store.head_hash()
        # Roll the file back to the earlier, self-consistent
        # state: the file alone cannot tell (documented limit),
        # but the externally pinned head can.
        self.path.write_bytes(snapshot)
        self.assertEqual(store.verify_integrity(), ())
        self.assertEqual(store.verify_integrity(expected_head=pinned),
                         ("budget_head_mismatch",))

    def test_deleted_store_detected_against_pinned_head(self):
        store = self.store()
        store.check_and_record(IDENTITY, "prop-a", transcript("a"))
        pinned = store.head_hash()
        self.path.unlink()
        self.assertEqual(store.verify_integrity(expected_head=pinned),
                         ("budget_store_missing",))
        self.assertEqual(store.head_hash(), GENESIS_CHAIN_HASH)
        self.assertEqual(store.verify_integrity(), ())


class TwoPhaseApiTests(unittest.TestCase):
    """Review MEDIUM-2: check_only refuses exactly when record
    would, but records NOTHING — so a transcript the verifier
    later rejects on its own validation (e.g. answer count) burns
    no budget."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"

    def store(self, **kwargs):
        return BudgetStore(self.path, **kwargs)

    def reason(self, fn, *args):
        with self.assertRaises(BudgetError) as ctx:
            fn(*args)
        return ctx.exception.reason

    def test_check_only_records_nothing(self):
        store = self.store()
        self.assertIsNone(store.check_only(IDENTITY, "prop-a",
                                           transcript("a")))
        self.assertEqual(store.proposal_count("prop-a"), 0)
        self.assertEqual(store.identity_count(IDENTITY), 0)
        self.assertFalse(self.path.exists())  # no write happened
        # Repeated checks are free: the budget moves only on
        # record().
        for _ in range(5):
            self.assertIsNone(store.check_only(IDENTITY, "prop-a",
                                               transcript("a")))
        self.assertIsNone(store.record(IDENTITY, "prop-a",
                                       transcript("a")))
        self.assertEqual(store.proposal_count("prop-a"), 1)
        self.assertEqual(store.identity_count(IDENTITY), 1)

    def test_check_only_replay_refuses_and_records_nothing(self):
        store = self.store()
        answers = transcript("a")
        store.record(IDENTITY, "prop-a", answers)
        self.assertEqual(
            self.reason(store.check_only, IDENTITY, "prop-b", answers),
            "transcript_replay")
        self.assertEqual(store.identity_count(IDENTITY), 1)

    def test_check_only_probe_accounting_is_predictive_not_spent(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.record(IDENTITY, "prop-a", base)
        probe = variant(base, {0: "p"})
        # A tolerated probe passes check_only repeatedly without
        # the probe count moving...
        self.assertIsNone(store.check_only(IDENTITY, "prop-a", probe))
        self.assertIsNone(store.check_only(IDENTITY, "prop-a", probe))
        self.assertEqual(store.identity_probes(IDENTITY), 0)
        # ...and is counted exactly once, by record().
        self.assertIsNone(store.record(IDENTITY, "prop-a", probe))
        self.assertEqual(store.identity_probes(IDENTITY), 1)

    def test_check_only_tripping_probe_refuses_and_latches_nothing(self):
        store = self.store(per_proposal_cap=100, per_identity_cap=100)
        base = transcript("base")
        store.record(IDENTITY, "prop-a", base)
        store.record(IDENTITY, "prop-a", variant(base, {0: "p1"}))
        store.record(IDENTITY, "prop-a", variant(base, {1: "p2"}))
        self.assertEqual(store.identity_probes(IDENTITY), 2)
        trip = variant(base, {2: "p3"})
        self.assertEqual(
            self.reason(store.check_only, IDENTITY, "prop-a", trip),
            "adaptive_query_detected")
        # check_only latched nothing and counted nothing: the
        # refusal state is identical to before the call.
        self.assertEqual(store.identity_probes(IDENTITY), 2)
        self.assertFalse(store.is_blocked(IDENTITY))
        self.assertEqual(store.proposal_count("prop-a"), 3)
        # record() of the same transcript performs the latch.
        self.assertEqual(
            self.reason(store.record, IDENTITY, "prop-a", trip),
            "adaptive_query_detected")
        self.assertTrue(store.is_blocked(IDENTITY))

    def test_check_only_respects_caps_without_recording(self):
        store = self.store(per_proposal_cap=1, per_identity_cap=100)
        store.record(IDENTITY, "prop-a", transcript("a"))
        self.assertEqual(
            self.reason(store.check_only, IDENTITY, "prop-a",
                        transcript("b")),
            "proposal_budget_exceeded")
        self.assertEqual(store.proposal_count("prop-a"), 1)


if __name__ == "__main__":
    unittest.main()
