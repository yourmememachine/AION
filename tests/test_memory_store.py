"""Tests for the gated long-term memory store. Standard library only."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import GateDecision, VerifierAttestation
from memory.store import (
    MAX_CONTENT_CHARS,
    MAX_MEMORY_BYTES,
    CorruptMemoryError,
    MemoryError,
    MemoryStore,
    TamperDetectedError,
    _entry_hash,
    _state_digest,
    content_hash_for,
    decide_write,
)

HASH = "a" * 64


def decision(proposal_id="prop-1", verifier_id="seat-3", accepted=True,
             fields_for=None):
    note = (f"content-hash:{content_hash_for(fields_for)}"
            if fields_for is not None else "")
    return GateDecision(
        accepted=accepted,
        proposal_id=proposal_id,
        reasons=() if accepted else ("regression",),
        regressions=(),
        forgetting_failures=(),
        verifier_id=verifier_id,
        evaluated_at="2026-11-20T00:00:00+00:00",
        verifier_note=note,
    )


def fields(**over):
    base = {
        "id": "lesson-reverse",
        "domain": "factory-reverse",
        "kind": "strategy",
        "content": "full-reverse",
        "author": "seat-11",
        "source": "derivation:public-practice-gen1",
        "evidence_ref": "derive:abc:reverse",
        "proposal_id": "prop-1",
        "verifier_id": "seat-3",
        "supersedes": None,
    }
    base.update(over)
    return base


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = MemoryStore(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, **over):
        f = fields(**over)
        return self.store.commit_write(
            f, decision(f["proposal_id"], f["verifier_id"], fields_for=f))


class CommitTests(StoreTestCase):
    def test_fresh_start_is_empty_and_writes_no_file(self):
        self.assertEqual(self.store.retrieve(), [])
        self.assertFalse((self.dir / "memory.json").exists())

    def test_commit_happy_path_persists_and_reloads(self):
        entry = self.commit()
        self.assertEqual(entry["seq"], 1)
        self.assertEqual(entry["content_hash"], content_hash_for(fields()))
        fresh = MemoryStore(self.dir)
        got = fresh.retrieve(domain="factory-reverse", kind="strategy")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["content"], "full-reverse")
        self.assertEqual(got[0]["author"], "seat-11")

    def test_commit_rejected_decision_refused(self):
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(), decision(accepted=False))
        self.assertEqual(self.store.retrieve(), [])
        self.assertFalse((self.dir / "memory.json").exists())

    def test_commit_mismatched_proposal_refused(self):
        with self.assertRaises(MemoryError):
            self.store.commit_write(
                fields(), decision("other-prop", fields_for=fields()))
        self.assertEqual(self.store.retrieve(), [])

    def test_commit_mismatched_verifier_refused(self):
        with self.assertRaises(MemoryError):
            self.store.commit_write(
                fields(),
                decision(verifier_id="seat-4", fields_for=fields()))
        self.assertEqual(self.store.retrieve(), [])

    def test_commit_decision_without_content_binding_refused(self):
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(), decision(fields_for=None))
        self.assertEqual(self.store.retrieve(), [])

    def test_commit_decision_bound_to_other_entry_refused(self):
        other = fields(id="lesson-largest", domain="factory-largest",
                       content="scan-max", proposal_id="prop-1")
        with self.assertRaises(MemoryError):
            self.store.commit_write(
                fields(), decision("prop-1", fields_for=other))
        self.assertEqual(self.store.retrieve(), [])

    def test_accepted_decision_with_reasons_refused(self):
        f = fields()
        bad = GateDecision(
            accepted=True, proposal_id="prop-1",
            reasons=("regression",), regressions=(),
            forgetting_failures=(), verifier_id="seat-3",
            evaluated_at="2026-11-20T00:00:00+00:00",
            verifier_note=f"content-hash:{content_hash_for(f)}")
        with self.assertRaises(MemoryError):
            self.store.commit_write(f, bad)
        self.assertEqual(self.store.retrieve(), [])

    def test_commit_wrong_type_decision_refused(self):
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(), {"accepted": True})
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(), None)

    def test_commit_fake_gate_decision_not_stopped(self):
        # Documents the A30 limit honestly: GateDecision is a plain
        # dataclass; a hand-constructed accepted decision — including
        # the content-hash binding, which is computable by anyone
        # holding the entry — commits. commit_write checks
        # consistency, never provenance.
        f = fields()
        entry = self.store.commit_write(
            f, decision(f["proposal_id"], f["verifier_id"], fields_for=f))
        self.assertEqual(entry["id"], "lesson-reverse")

    def test_commit_verifier_equals_author_refused(self):
        f = fields(author="seat-3")
        with self.assertRaises(MemoryError):
            self.store.commit_write(f, decision(verifier_id="seat-3"))

    def test_duplicate_id_commit_refused(self):
        self.commit()
        with self.assertRaises(MemoryError):
            self.commit(id="lesson-reverse", proposal_id="prop-2",
                        domain="factory-largest", content="scan-max")

    def test_reused_proposal_id_rejected(self):
        self.commit()
        with self.assertRaises(MemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-1")

    def test_second_current_entry_same_domain_kind_rejected(self):
        self.commit()
        with self.assertRaises(MemoryError):
            self.commit(id="lesson-reverse-2", proposal_id="prop-2")

    def test_oversized_content_refused_and_at_cap_accepted(self):
        with self.assertRaises(MemoryError):
            self.commit(content="x" * (MAX_CONTENT_CHARS + 1))
        self.assertEqual(self.store.retrieve(), [])
        entry = self.commit(content="x" * MAX_CONTENT_CHARS)
        self.assertEqual(len(entry["content"]), MAX_CONTENT_CHARS)

    def test_bad_char_content_refused(self):
        for bad in ("a\x00b", "a\u200bb", "a\u202eb", "a\x7fb"):
            with self.assertRaises(MemoryError):
                self.commit(content=bad)
        self.assertEqual(self.store.retrieve(), [])

    def test_content_with_newline_accepted(self):
        entry = self.commit(content="line one\nline two")
        self.assertIn("\n", entry["content"])

    def test_entry_id_edge_cases(self):
        for bad_id in ("", "A", "a b", "a/b", "../x", "a" * 65, None, 7):
            with self.assertRaises(MemoryError):
                self.commit(id=bad_id)
        self.assertEqual(self.store.retrieve(), [])

    def test_unknown_kind_rejected(self):
        with self.assertRaises(MemoryError):
            self.commit(kind="fact")


class SupersedeTests(StoreTestCase):
    def test_supersede_happy_path(self):
        self.commit()
        newer = self.commit(id="lesson-reverse-2", proposal_id="prop-2",
                            content="full-reverse-v2",
                            supersedes="lesson-reverse")
        self.assertEqual(newer["seq"], 2)
        current = self.store.retrieve(domain="factory-reverse")
        self.assertEqual([e["id"] for e in current], ["lesson-reverse-2"])
        self.assertFalse(self.store.get("lesson-reverse")["current"])
        self.assertTrue(self.store.get("lesson-reverse-2")["current"])

    def test_supersede_unknown_refused(self):
        with self.assertRaises(MemoryError):
            self.commit(supersedes="nope")

    def test_supersede_already_superseded_refused(self):
        self.commit()
        self.commit(id="lesson-reverse-2", proposal_id="prop-2",
                    supersedes="lesson-reverse")
        with self.assertRaises(MemoryError):
            self.commit(id="lesson-reverse-3", proposal_id="prop-3",
                        supersedes="lesson-reverse")

    def test_supersede_self_refused(self):
        with self.assertRaises(MemoryError):
            self.commit(supersedes="lesson-reverse")

    def test_supersede_cross_domain_rejected(self):
        self.commit()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        with self.assertRaises(MemoryError):
            self.commit(id="lesson-largest-2", proposal_id="prop-3",
                        domain="factory-largest", content="scan-max-v2",
                        supersedes="lesson-reverse")

    def test_chain_a_b_c_only_c_current(self):
        self.commit()
        self.commit(id="lesson-reverse-2", proposal_id="prop-2",
                    supersedes="lesson-reverse")
        self.commit(id="lesson-reverse-3", proposal_id="prop-3",
                    supersedes="lesson-reverse-2")
        current = self.store.retrieve()
        self.assertEqual([e["id"] for e in current], ["lesson-reverse-3"])
        chain = self.store.history("lesson-reverse-2")
        self.assertEqual([e["id"] for e in chain],
                         ["lesson-reverse", "lesson-reverse-2",
                          "lesson-reverse-3"])


class RetrievalTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.commit()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        self.commit(id="lesson-sequence", proposal_id="prop-3",
                    domain="factory-sequence", content="plus-step")

    def test_retrieve_filters_and_commit_order(self):
        all_entries = self.store.retrieve()
        self.assertEqual([e["id"] for e in all_entries],
                         ["lesson-reverse", "lesson-largest",
                          "lesson-sequence"])
        only = self.store.retrieve(domain="factory-largest")
        self.assertEqual([e["id"] for e in only], ["lesson-largest"])
        self.assertEqual(self.store.retrieve(domain="factory-parity"), [])
        self.assertEqual(self.store.list_current(), all_entries)

    def test_retrieve_returns_deep_copies(self):
        got = self.store.retrieve()
        got[0]["content"] = "tampered"
        self.assertEqual(self.store.retrieve()[0]["content"], "full-reverse")

    def test_retrieve_limit_validation(self):
        self.assertEqual(len(self.store.retrieve(limit=2)), 2)
        for bad in (0, -1, True, "2"):
            with self.assertRaises(MemoryError):
                self.store.retrieve(limit=bad)

    def test_get_unknown_id_raises(self):
        with self.assertRaises(MemoryError):
            self.store.get("nope")

    def test_history_all_includes_superseded(self):
        self.commit(id="lesson-reverse-2", proposal_id="prop-4",
                    supersedes="lesson-reverse")
        hist = self.store.history()
        self.assertEqual(len(hist), 4)
        flags = {e["id"]: e["current"] for e in hist}
        self.assertFalse(flags["lesson-reverse"])
        self.assertTrue(flags["lesson-reverse-2"])

    def test_state_digest_and_chain_head_accessors(self):
        self.assertEqual(self.store.chain_head(),
                         self.store.get("lesson-sequence")["entry_hash"])
        digest = self.store.state_digest()
        self.assertEqual(len(digest), 64)
        fresh = MemoryStore(self.dir)
        self.assertEqual(fresh.state_digest(), digest)


class TamperTests(StoreTestCase):
    def _rewrite(self, mutate):
        path = self.dir / "memory.json"
        data = json.loads(path.read_text())
        mutate(data)
        path.write_text(json.dumps(data))

    def test_tamper_content_detected(self):
        self.commit()
        self._rewrite(lambda d: d["entries"][0].update(content="identity"))
        with self.assertRaises(TamperDetectedError):
            MemoryStore(self.dir)

    def test_tamper_provenance_detected(self):
        self.commit()
        self._rewrite(lambda d: d["entries"][0].update(author="seat-9"))
        with self.assertRaises(TamperDetectedError):
            MemoryStore(self.dir)

    def test_entry_deletion_detected(self):
        self.commit()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        self._rewrite(lambda d: d.update(entries=d["entries"][1:],
                                         entry_seq=1))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_entry_reordering_detected(self):
        self.commit()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        self._rewrite(lambda d: d.update(
            entries=[d["entries"][1], d["entries"][0]]))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_fully_rehashed_tamper_not_detected_internally(self):
        # Documents the limit: a rewrite that recomputes every hash
        # and the digest loads cleanly. Detection requires anchoring
        # state_digest()/chain_head() outside the store.
        from memory.store import _content_hash, _entry_hash, _state_digest
        self.commit()
        path = self.dir / "memory.json"
        data = json.loads(path.read_text())
        entry = data["entries"][0]
        entry["content"] = "identity"
        entry["content_hash"] = _content_hash(entry)
        entry["entry_hash"] = _entry_hash(entry)
        data["state_digest"] = _state_digest(data)
        path.write_text(json.dumps(data))
        fresh = MemoryStore(self.dir)
        self.assertEqual(fresh.retrieve()[0]["content"], "identity")

    def test_rollback_to_older_valid_file_loads(self):
        # Documents the limit: an older, internally valid file is
        # indistinguishable from the current state to a fresh load.
        self.commit()
        path = self.dir / "memory.json"
        snapshot = path.read_bytes()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        path.write_bytes(snapshot)
        fresh = MemoryStore(self.dir)
        self.assertEqual(len(fresh.retrieve()), 1)

    def test_rollback_seen_by_live_instance(self):
        self.commit()
        path = self.dir / "memory.json"
        snapshot = path.read_bytes()
        self.commit(id="lesson-largest", proposal_id="prop-2",
                    domain="factory-largest", content="scan-max")
        path.write_bytes(snapshot)
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-sequence", proposal_id="prop-3",
                        domain="factory-sequence", content="plus-step")

    def test_corrupt_json_fails_closed_and_quarantines(self):
        self.commit()
        path = self.dir / "memory.json"
        path.write_text("{not json")
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        quarantined = list(self.dir.glob("memory.corrupt-*.json"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(path.read_text(), "{not json")

    def test_load_rejects_unknown_kind(self):
        self.commit()
        self._rewrite(lambda d: d["entries"][0].update(kind="fact"))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)


class ConcurrencyTests(StoreTestCase):
    def test_two_instances_interleaved_saves(self):
        other = MemoryStore(self.dir)
        self.commit()
        f2 = fields(id="lesson-largest", domain="factory-largest",
                    content="scan-max", proposal_id="prop-2")
        with self.assertRaises(CorruptMemoryError):
            other.commit_write(f2, decision("prop-2", fields_for=f2))
        fresh = MemoryStore(self.dir)
        self.assertEqual([e["id"] for e in fresh.retrieve()],
                         ["lesson-reverse"])

    def test_two_threads_one_instance_both_land(self):
        errors = []

        def work(entry_id, domain, content, prop):
            try:
                f = fields(id=entry_id, domain=domain, content=content,
                           proposal_id=prop)
                self.store.commit_write(
                    f, decision(prop, fields_for=f))
            except Exception as exc:  # noqa: BLE001 - collected for assert
                errors.append(exc)

        threads = [
            threading.Thread(target=work, args=(
                "lesson-largest", "factory-largest", "scan-max", "prop-t1")),
            threading.Thread(target=work, args=(
                "lesson-sequence", "factory-sequence", "plus-step",
                "prop-t2")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        fresh = MemoryStore(self.dir)
        self.assertEqual(len(fresh.retrieve()), 2)


BUILDERS = ["seat-9", "seat-10", "seat-11"]
REVIEWERS = ["seat-1", "seat-2", "seat-3", "seat-4", "seat-5", "seat-6"]


def attestation(**over):
    base = dict(verifier_id="seat-3", decision="approve", sealed_hash=HASH,
                reward_hacking_checked=True, evidence_ref="run:1",
                attested_at="2026-11-20T00:00:00+00:00")
    base.update(over)
    return VerifierAttestation(**base)


def gate_maps(pub_b, pub_c, sealed_b, sealed_c, gold_b=None, gold_c=None):
    return dict(
        baseline_public=pub_b, candidate_public=pub_c,
        baseline_sealed=sealed_b, candidate_sealed=sealed_c,
        capability_baseline=gold_b if gold_b is not None else {"golden-reverse": 0.0},
        capability_candidate=gold_c if gold_c is not None else {"golden-reverse": 0.0},
    )


class WarRoomRegressionTests(StoreTestCase):
    """Findings from the cycle-4 war room, pinned as tests."""

    def _rehash_and_write(self, mutate):
        data = json.loads(self.store.memory_path.read_text())
        mutate(data)
        entry = data["entries"][0]
        entry["content_hash"] = content_hash_for(entry)
        entry["entry_hash"] = _entry_hash(entry)
        data["state_digest"] = _state_digest(data)
        self.store.memory_path.write_text(json.dumps(data))

    def test_genuine_decision_cannot_be_redirected(self):
        # R3/R6 F1 + R2 F1: a decision decide_write really issued for
        # one entry must not commit a different entry.
        good_maps = {
            "baseline_public": {"pub": 0.5}, "candidate_public": {"pub": 0.6},
            "baseline_sealed": {"sealed": 0.5},
            "candidate_sealed": {"sealed": 0.6},
            "capability_baseline": {"golden": 1.0},
            "capability_candidate": {"golden": 1.0},
        }
        real = decide_write(
            entry_fields=fields(), builder_ids=BUILDERS,
            reviewer_ids=REVIEWERS,
            attestation=attestation(), expected_sealed_hash=HASH,
            **good_maps)
        self.assertTrue(real.accepted)
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(content="identity"), real)
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(domain="factory-largest"), real)
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(author="seat-9"), real)
        entry = self.store.commit_write(fields(), real)
        self.assertEqual(entry["content"], "full-reverse")

    def test_post_replace_fsync_failure_does_not_lose_entry(self):
        # R1 M1: replace succeeded, directory fsync failed. The entry
        # IS on disk; the live instance must wedge loudly, never roll
        # back over it.
        self.commit()
        import os
        from unittest import mock
        real_fsync = os.fsync
        calls = {"n": 0}

        def flaky(fd):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("injected directory fsync failure")
            return real_fsync(fd)

        with mock.patch.object(os, "fsync", flaky):
            with self.assertRaises(OSError):
                self.commit(id="lesson-largest", domain="factory-largest",
                            content="scan-max", proposal_id="prop-2")
        fresh = MemoryStore(self.dir)
        self.assertEqual(len(fresh.retrieve()), 2)
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-seq", domain="factory-sequence",
                        content="plus-step", proposal_id="prop-3")
        self.assertEqual(len(MemoryStore(self.dir).retrieve()), 2)

    def test_live_instance_refuses_save_over_naive_tamper(self):
        # R2 F2: edit the entry content, leave the stored digest
        # field untouched. The live instance must refuse, not
        # silently clobber the tampered file.
        self.commit()
        data = json.loads(self.store.memory_path.read_text())
        data["entries"][0]["content"] = "identity"
        self.store.memory_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-2")
        on_disk = json.loads(self.store.memory_path.read_text())
        self.assertEqual(on_disk["entries"][0]["content"], "identity")

    def test_live_instance_refuses_save_over_duplicate_key_file(self):
        # R1 verification N1: the freshness guard parses with the
        # same strictness as the loader — a file a fresh instance
        # would reject (duplicate key, semantically identical) must
        # read as changed to the live instance too, not be silently
        # healed over.
        self.commit()
        raw = self.store.memory_path.read_text()
        dup = raw.replace('"content": "full-reverse"',
                          '"content": "identity", '
                          '"content": "full-reverse"', 1)
        self.assertNotEqual(dup, raw)
        self.store.memory_path.write_text(dup)
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-2")
        self.assertEqual(self.store.memory_path.read_text(), dup)

    def test_live_instance_refuses_save_over_unknown_key(self):
        # R2 verification residual: an extra key a fresh instance
        # would reject must read as changed to the live instance.
        self.commit()
        data = json.loads(self.store.memory_path.read_text())
        data["entries"][0]["surprise"] = "x"
        self.store.memory_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-2")

    def test_live_instance_refuses_save_over_digest_field_tamper(self):
        # R2 verification residual: corrupting ONLY the stored
        # state_digest field (which the digest core excludes) must
        # still read as changed.
        self.commit()
        data = json.loads(self.store.memory_path.read_text())
        data["state_digest"] = "0" * 64
        self.store.memory_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-2")

    def test_surrogate_content_refused_as_memory_error(self):
        bad = GateDecision(
            accepted=True, proposal_id="prop-1", reasons=(),
            regressions=(), forgetting_failures=(), verifier_id="seat-3",
            evaluated_at="2026-11-20T00:00:00+00:00",
            verifier_note="content-hash:" + "0" * 64)
        with self.assertRaises(MemoryError):
            self.store.commit_write(fields(content="a\ud800b"), bad)
        self.assertEqual(self.store.retrieve(), [])

    def test_surrogate_in_file_is_corrupt_not_unicode_error(self):
        self.commit()
        data = json.loads(self.store.memory_path.read_text())
        data["entries"][0]["content"] = "a\ud800b"
        self.store.memory_path.write_text(json.dumps(data))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_oversized_disk_file_refused_on_save(self):
        self.commit()
        self.store.memory_path.write_bytes(b" " * (MAX_MEMORY_BYTES + 1))
        with self.assertRaises(CorruptMemoryError):
            self.commit(id="lesson-largest", domain="factory-largest",
                        content="scan-max", proposal_id="prop-2")

    def test_duplicate_json_keys_rejected_and_quarantined(self):
        self.commit()
        raw = self.store.memory_path.read_text()
        self.store.memory_path.write_text(raw[:-1] + ', "entry_seq": 1}')
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        quarantined = [p for p in self.dir.iterdir()
                       if p.name.startswith("memory.corrupt-")]
        self.assertTrue(quarantined)

    def test_non_finite_constant_quarantined(self):
        self.store.memory_path.write_text(
            '{"schema_version": 1, "entry_seq": NaN}')
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)
        quarantined = [p for p in self.dir.iterdir()
                       if p.name.startswith("memory.corrupt-")]
        self.assertTrue(quarantined)

    def test_load_rejects_verifier_equals_author_rehashed(self):
        self.commit()
        self._rehash_and_write(
            lambda d: d["entries"][0].update(verifier_id="seat-11"))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_load_rejects_float_seq_rehashed(self):
        self.commit()
        self._rehash_and_write(
            lambda d: d["entries"][0].update(seq=1.0))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)

    def test_load_rejects_naive_created_at_rehashed(self):
        self.commit()
        self._rehash_and_write(
            lambda d: d["entries"][0].update(
                created_at="2026-11-20T00:00:00"))
        with self.assertRaises(CorruptMemoryError):
            MemoryStore(self.dir)


class DecideWriteTests(unittest.TestCase):
    def decide(self, maps, att=None, fields_over=None):
        return decide_write(
            entry_fields=fields(**(fields_over or {})),
            builder_ids=BUILDERS, reviewer_ids=REVIEWERS,
            attestation=att or attestation(),
            expected_sealed_hash=HASH, **maps)

    def test_valid_lesson_with_sealed_gain_accepted(self):
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 1.0},
                         {"golden-reverse": 0.0}, {"golden-reverse": 1.0})
        result = self.decide(maps)
        self.assertTrue(result.accepted)
        self.assertEqual(result.reasons, ())

    def test_wrong_strategy_lesson_rejected_public_regression(self):
        maps = gate_maps({"pub-reverse": 0.2}, {"pub-reverse": 0.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 0.5})
        result = self.decide(maps)
        self.assertFalse(result.accepted)
        self.assertIn("regression", result.reasons)

    def test_forged_attestation_writer_as_verifier_rejected(self):
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 1.0})
        result = self.decide(maps, att=attestation(verifier_id="seat-9"))
        self.assertFalse(result.accepted)
        self.assertIn("verifier_is_builder", result.reasons)
        self.assertIn("verifier_not_reviewer", result.reasons)

    def test_forged_attestation_sealed_hash_mismatch_rejected(self):
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 1.0})
        result = self.decide(maps, att=attestation(sealed_hash="b" * 64))
        self.assertFalse(result.accepted)
        self.assertIn("sealed_hash_mismatch", result.reasons)

    def test_lesson_with_no_sealed_gain_rejected(self):
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.3}, {"sealed-reverse": 0.3})
        result = self.decide(maps)
        self.assertFalse(result.accepted)
        self.assertIn("no_sealed_gain", result.reasons)

    def test_lesson_regressing_different_family_rejected(self):
        maps = gate_maps(
            {"pub-largest": 0.0, "pub-reverse": 0.4},
            {"pub-largest": 1.0, "pub-reverse": 0.4},
            {"sealed-largest": 0.0, "sealed-reverse": 0.4},
            {"sealed-largest": 1.0, "sealed-reverse": 0.1})
        result = self.decide(maps)
        self.assertFalse(result.accepted)
        self.assertIn("regression", result.reasons)
        hit = [r for r in result.regressions
               if r.benchmark_id == "sealed-reverse"]
        self.assertEqual(len(hit), 1)

    def test_lesson_dropping_golden_family_rejected_forgetting(self):
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 1.0},
                         {"golden-reverse": 0.5}, {"golden-reverse": 0.4})
        result = self.decide(maps)
        self.assertFalse(result.accepted)
        self.assertIn("forgetting", result.reasons)

    def test_memory_write_touching_eval_rejected_protected_path(self):
        # decide_write always supplies changed_paths inside memory/;
        # a proposal whose id tried to escape into eval/ cannot be a
        # valid id at all, and the gate's own protected-path check is
        # covered by test_gate.py. Here: the supplied path is safe.
        maps = gate_maps({"pub-reverse": 0.0}, {"pub-reverse": 1.0},
                         {"sealed-reverse": 0.0}, {"sealed-reverse": 1.0})
        result = self.decide(maps)
        self.assertEqual(result.protected_violations, ())


if __name__ == "__main__":
    unittest.main()
