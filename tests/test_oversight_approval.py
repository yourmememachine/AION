import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oversight.approval import (
    OWNER_ID, ApprovalError, ApprovalManager, CorruptJournalError,
    ExternalReview, OwnerApproval, ProtectedChangeRequest,
    canonicalise_path, content_hash_for, evaluate_approvals,
    is_protected_path, preimage_hash_for,
)

T0 = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)


def ts(dt):
    return dt.isoformat()


NOW = ts(T0)
BUILDERS = ["seat-9", "seat-10", "seat-11"]
CAND = {"eval/gate.py": b"new gate code"}
PRE = {"eval/gate.py": b"old gate code"}


def make_manager(tmp):
    return ApprovalManager(Path(tmp) / "journal")


def make_request(mgr, **kw):
    args = dict(proposal_id="prop-1", author_id="seat-9",
                builder_ids=list(BUILDERS), candidate=dict(CAND),
                preimage=dict(PRE), rationale="tighten the gate",
                evidence_ref="review record 6", ttl_seconds=3600, now=NOW)
    args.update(kw)
    return mgr.create_request(**args)


def owner_leg(req, **kw):
    args = dict(owner_id=OWNER_ID, proposal_id=req["proposal_id"],
                content_hash=req["content_hash"],
                bound_expires_at=req["expires_at"], decision="approve",
                evidence_ref="owner review note", attested_at=ts(T0 + timedelta(minutes=5)),
                expires_at=req["expires_at"])
    args.update(kw)
    return OwnerApproval(**args)


def external_leg(req, **kw):
    args = dict(reviewer_id="external-1", proposal_id=req["proposal_id"],
                content_hash=req["content_hash"],
                bound_expires_at=req["expires_at"], decision="approve",
                reward_hacking_checked=True,
                independence_note="separate reviewer, own channel",
                evidence_ref="external report 1",
                attested_at=ts(T0 + timedelta(minutes=6)),
                expires_at=req["expires_at"])
    args.update(kw)
    return ExternalReview(**args)


def armed(mgr):
    req = make_request(mgr)
    mgr.record_owner_approval(owner_leg(req), now=ts(T0 + timedelta(minutes=5)))
    mgr.record_external_review(external_leg(req), now=ts(T0 + timedelta(minutes=6)))
    return req


class PathTests(unittest.TestCase):
    def test_protected_scope_gate_and_local(self):
        self.assertTrue(is_protected_path("eval/gate.py"))
        self.assertTrue(is_protected_path("core/loop.py"))
        self.assertTrue(is_protected_path("oversight/approval.py"))
        self.assertTrue(is_protected_path("oversight"))
        self.assertFalse(is_protected_path("memory/store.py"))
        self.assertFalse(is_protected_path("docs/ROADMAP-2027.md"))

    def test_canonicalise_collapses_and_refuses(self):
        self.assertEqual(canonicalise_path("eval//./gate.py"), "eval/gate.py")
        self.assertEqual(canonicalise_path("eval\\gate.py"), "eval/gate.py")
        for bad in ("../eval/gate.py", "/eval/gate.py", "C:/eval/gate.py",
                    "", "eval/../gate.py", "a\x00b"):
            with self.assertRaises(ApprovalError, msg=bad):
                canonicalise_path(bad)

    def test_spelling_evasion_still_protected(self):
        self.assertTrue(is_protected_path(canonicalise_path("eval/./gate.py")))
        self.assertTrue(is_protected_path(canonicalise_path("./core/loop.py")))


class HashTests(unittest.TestCase):
    def test_hash_binds_bytes_paths_preimage_proposal_expiry(self):
        base = content_hash_for(proposal_id="p1", expires_at="e",
                                candidate=CAND, preimage=PRE)
        self.assertNotEqual(base, content_hash_for(
            proposal_id="p2", expires_at="e", candidate=CAND, preimage=PRE))
        self.assertNotEqual(base, content_hash_for(
            proposal_id="p1", expires_at="e2", candidate=CAND, preimage=PRE))
        self.assertNotEqual(base, content_hash_for(
            proposal_id="p1", expires_at="e",
            candidate={"eval/gate.py": b"other"}, preimage=PRE))
        self.assertNotEqual(base, content_hash_for(
            proposal_id="p1", expires_at="e", candidate=CAND,
            preimage={"eval/gate.py": b"drifted"}))
        self.assertNotEqual(base, content_hash_for(
            proposal_id="p1", expires_at="e", candidate=CAND,
            preimage={"eval/gate.py": None}))

    def test_preimage_hash(self):
        self.assertEqual(preimage_hash_for(PRE), preimage_hash_for(dict(PRE)))
        self.assertNotEqual(preimage_hash_for(PRE),
                            preimage_hash_for({"eval/gate.py": None}))


class PureEvaluateTests(unittest.TestCase):
    def req_obj(self):
        return ProtectedChangeRequest(
            proposal_id="p1", author_id="seat-9", builder_ids=tuple(BUILDERS),
            changed_paths=("eval/gate.py",), content_hash="a" * 64,
            preimage_hash="b" * 64, rationale="r", evidence_ref="e",
            requested_at=NOW, expires_at=ts(T0 + timedelta(hours=1)))

    def test_both_legs_authorize(self):
        req = self.req_obj()
        d = evaluate_approvals(
            request=req,
            owner_approval=owner_leg({"proposal_id": "p1", "content_hash": "a" * 64,
                                      "expires_at": req.expires_at}),
            external_review=external_leg({"proposal_id": "p1", "content_hash": "a" * 64,
                                          "expires_at": req.expires_at}),
            now=ts(T0 + timedelta(minutes=10)))
        self.assertTrue(d.authorized, d.reasons)

    def test_missing_legs_collect_reasons(self):
        d = evaluate_approvals(request=self.req_obj(), owner_approval=None,
                               external_review=None, now=NOW)
        self.assertFalse(d.authorized)
        self.assertIn("missing_owner_approval", d.reasons)
        self.assertIn("missing_external_review", d.reasons)

    def test_role_collisions_refused(self):
        req = self.req_obj()
        base = {"proposal_id": "p1", "content_hash": "a" * 64,
                "expires_at": req.expires_at}
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base, owner_id="seat-9"),
            external_review=external_leg(base), now=NOW)
        self.assertIn("not_owner", d.reasons)
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base),
            external_review=external_leg(base, reviewer_id="seat-10"), now=NOW)
        self.assertIn("external_review_actor_forbidden", d.reasons)
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base),
            external_review=external_leg(base, reviewer_id=OWNER_ID), now=NOW)
        self.assertIn("external_review_actor_forbidden", d.reasons)

    def test_earliest_expiry_wins_and_boundary_is_expired(self):
        req = self.req_obj()
        base = {"proposal_id": "p1", "content_hash": "a" * 64,
                "expires_at": req.expires_at}
        early = ts(T0 + timedelta(minutes=30))
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base, expires_at=early),
            external_review=external_leg(base), now=ts(T0 + timedelta(minutes=31)))
        self.assertIn("expired", d.reasons)
        self.assertEqual(d.effective_expires_at, early)
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base),
            external_review=external_leg(base), now=req.expires_at)
        self.assertIn("expired", d.reasons)

    def test_reward_hacking_and_deny(self):
        req = self.req_obj()
        base = {"proposal_id": "p1", "content_hash": "a" * 64,
                "expires_at": req.expires_at}
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base),
            external_review=external_leg(base, reward_hacking_checked=False),
            now=NOW)
        self.assertIn("reward_hacking_not_checked", d.reasons)
        d = evaluate_approvals(
            request=req, owner_approval=owner_leg(base, decision="deny"),
            external_review=external_leg(base), now=NOW)
        self.assertIn("owner_approval_did_not_approve", d.reasons)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = make_manager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path_armed_then_consume(self):
        req = armed(self.mgr)
        self.assertEqual(self.mgr.state("prop-1", now=ts(T0 + timedelta(minutes=10))), "ARMED")
        receipt = self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                                   preimage=dict(PRE),
                                   now=ts(T0 + timedelta(minutes=10)))
        self.assertEqual(receipt.content_hash, req["content_hash"])
        self.assertEqual(self.mgr.state("prop-1", now=NOW), "CONSUMED")

    def test_consume_is_single_use(self):
        armed(self.mgr)
        self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                         preimage=dict(PRE), now=ts(T0 + timedelta(minutes=10)))
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                             preimage=dict(PRE), now=ts(T0 + timedelta(minutes=10)))

    def test_consume_requires_both_legs(self):
        req = make_request(self.mgr)
        self.mgr.record_owner_approval(owner_leg(req), now=NOW)
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                             preimage=dict(PRE), now=NOW)

    def test_consume_drift_refused(self):
        armed(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1",
                             candidate={"eval/gate.py": b"tampered"},
                             preimage=dict(PRE), now=NOW)
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                             preimage={"eval/gate.py": b"drift"}, now=NOW)

    def test_non_protected_path_refused(self):
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, candidate={"memory/store.py": b"x"},
                         preimage={"memory/store.py": b"y"})

    def test_oversight_path_is_protected(self):
        req = make_request(self.mgr, proposal_id="prop-self",
                           candidate={"oversight/approval.py": b"n"},
                           preimage={"oversight/approval.py": b"o"})
        self.assertEqual(req["changed_paths"], ["oversight/approval.py"])

    def test_deletion_refused(self):
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, candidate={"eval/gate.py": None})

    def test_one_active_and_burned_ids(self):
        make_request(self.mgr)
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, proposal_id="prop-2")
        self.mgr.revoke(proposal_id="prop-1", revoked_by=OWNER_ID,
                        reason="stop", now=NOW)
        with self.assertRaises(ApprovalError):
            make_request(self.mgr)  # prop-1 burned
        make_request(self.mgr, proposal_id="prop-2")

    def test_deny_is_terminal(self):
        req = make_request(self.mgr)
        self.mgr.record_owner_approval(owner_leg(req, decision="deny"), now=NOW)
        self.assertEqual(self.mgr.state("prop-1", now=NOW), "DENIED")
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(external_leg(req), now=NOW)

    def test_expiry_terminal_on_access(self):
        make_request(self.mgr, ttl_seconds=60)
        later = ts(T0 + timedelta(minutes=2))
        self.assertEqual(self.mgr.state("prop-1", now=later), "EXPIRED")
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                             preimage=dict(PRE), now=later)

    def test_ttl_bounds(self):
        for bad in (0, 59, 172801, True, 1.5):
            with self.assertRaises(ApprovalError, msg=repr(bad)):
                make_request(self.mgr, ttl_seconds=bad)

    def test_wrong_owner_and_forged_binding_refused_at_record(self):
        req = make_request(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(owner_leg(req, owner_id="seat-1"),
                                           now=NOW)
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, content_hash="0" * 64), now=NOW)
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(
                external_leg(req, reviewer_id="seat-9"), now=NOW)

    def test_idempotent_rerecord_and_conflict(self):
        req = make_request(self.mgr)
        leg = owner_leg(req)
        self.mgr.record_owner_approval(leg, now=NOW)
        again = self.mgr.record_owner_approval(leg, now=NOW)
        self.assertEqual(again["owner_id"], OWNER_ID)
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, evidence_ref="different"), now=NOW)

    def test_revoke_roles(self):
        armed(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.revoke(proposal_id="prop-1", revoked_by="seat-1",
                            reason="x", now=NOW)
        self.mgr.revoke(proposal_id="prop-1", revoked_by="external-1",
                        reason="withdrawing", now=NOW)
        self.assertEqual(self.mgr.state("prop-1", now=NOW), "REVOKED")

    def test_persistence_across_instances(self):
        req = armed(self.mgr)
        mgr2 = make_manager(self.tmp.name)
        self.assertEqual(mgr2.state("prop-1", now=ts(T0 + timedelta(minutes=10))), "ARMED")
        mgr2.consume(proposal_id="prop-1", candidate=dict(CAND),
                     preimage=dict(PRE), now=ts(T0 + timedelta(minutes=10)))
        mgr3 = make_manager(self.tmp.name)
        self.assertEqual(mgr3.state("prop-1", now=NOW), "CONSUMED")
        self.assertEqual(req["content_hash"],
                         mgr3.status("prop-1", now=NOW)["request"]["content_hash"])

    def test_journal_tamper_detected_and_quarantined(self):
        armed(self.mgr)
        path = Path(self.tmp.name) / "journal" / "journal.json"
        data = json.loads(path.read_text())
        data["entries"][0]["request"]["rationale"] = "tampered"
        path.write_text(json.dumps(data))
        with self.assertRaises(CorruptJournalError):
            make_manager(self.tmp.name)
        self.assertTrue(list((Path(self.tmp.name) / "journal").glob(
            "journal.corrupt-*.json")))

    def test_journal_truncation_detected(self):
        armed(self.mgr)
        path = Path(self.tmp.name) / "journal" / "journal.json"
        raw = path.read_bytes()
        path.write_bytes(raw[: len(raw) // 2])
        with self.assertRaises(CorruptJournalError):
            make_manager(self.tmp.name)

    def test_unknown_and_malformed(self):
        with self.assertRaises(ApprovalError):
            self.mgr.state("nope", now=NOW)
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, builder_ids=["seat-1", "seat-2"])
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, author_id=OWNER_ID)
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, candidate={}, preimage={})

    def test_status_reports_reasons(self):
        make_request(self.mgr)
        st = self.mgr.status("prop-1", now=NOW)
        self.assertEqual(st["state"], "REQUESTED")
        self.assertFalse(st["authorized"])
        self.assertIn("missing_owner_approval", st["reasons"])


if __name__ == "__main__":
    unittest.main()


LATER = None  # set in classes below via ts()


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = make_manager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, minutes):
        return ts(T0 + timedelta(minutes=minutes))

    def test_stale_manager_refused_and_no_double_consume(self):
        req = armed(self.mgr)
        stale = make_manager(self.tmp.name)
        self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                         preimage=dict(PRE), now=self.at(10))
        with self.assertRaises(ApprovalError):
            stale.consume(proposal_id="prop-1", candidate=dict(CAND),
                          preimage=dict(PRE), now=self.at(10))
        with self.assertRaises(ApprovalError):
            stale.create_request(proposal_id="prop-2", author_id="seat-9",
                                 builder_ids=list(BUILDERS),
                                 candidate=dict(CAND), preimage=dict(PRE),
                                 rationale="r", evidence_ref="e", now=self.at(11))

    def test_bad_external_leg_refused_at_record_not_bricked(self):
        req = make_request(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(
                external_leg(req, reward_hacking_checked=False), now=self.at(6))
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(
                external_leg(req, independence_note=""), now=self.at(6))
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(
                external_leg(req, independence_note="​"), now=self.at(6))
        # slot is free: the good leg records and arms
        self.mgr.record_external_review(external_leg(req), now=self.at(6))
        self.mgr.record_owner_approval(owner_leg(req), now=self.at(5))
        self.assertEqual(self.mgr.state("prop-1", now=self.at(10)), "ARMED")

    def test_future_and_pre_request_attestations_refused_at_record(self):
        req = make_request(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, attested_at=self.at(120)), now=self.at(5))
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, attested_at=ts(T0 - timedelta(hours=2))),
                now=self.at(5))
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, expires_at=self.at(-1)), now=self.at(5))

    def test_attestation_after_expiry_never_authorizes(self):
        req = self.mgr.create_request(
            proposal_id="prop-x", author_id="seat-9",
            builder_ids=list(BUILDERS), candidate=dict(CAND),
            preimage=dict(PRE), rationale="r", evidence_ref="e",
            ttl_seconds=3600, now=NOW)
        req_obj = ProtectedChangeRequest(
            proposal_id="prop-x", author_id="seat-9",
            builder_ids=tuple(BUILDERS), changed_paths=("eval/gate.py",),
            content_hash=req["content_hash"], preimage_hash=req["preimage_hash"],
            rationale="r", evidence_ref="e", requested_at=NOW,
            expires_at=req["expires_at"])
        d = evaluate_approvals(
            request=req_obj,
            owner_approval=owner_leg(req, attested_at=self.at(50),
                                     expires_at=self.at(30)),
            external_review=external_leg(req), now=self.at(10))
        self.assertIn("attestation_after_expiry", d.reasons)

    def test_revoke_after_expiry_reports_expired(self):
        make_request(self.mgr, ttl_seconds=60)
        with self.assertRaises(ApprovalError):
            self.mgr.revoke(proposal_id="prop-1", revoked_by=OWNER_ID,
                            reason="late", now=self.at(5))
        self.assertEqual(self.mgr.state("prop-1", now=self.at(5)), "EXPIRED")

    def test_evaluate_after_consume_is_not_authorized(self):
        armed(self.mgr)
        self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                         preimage=dict(PRE), now=self.at(10))
        d = self.mgr.evaluate("prop-1", now=self.at(11))
        self.assertFalse(d.authorized)
        self.assertIn("terminal_consumed", d.reasons)
        st = self.mgr.status("prop-1", now=self.at(11))
        self.assertFalse(st["authorized"])

    def test_deny_rerecord_is_idempotent(self):
        req = make_request(self.mgr)
        leg = owner_leg(req, decision="deny")
        self.mgr.record_owner_approval(leg, now=self.at(5))
        again = self.mgr.record_owner_approval(leg, now=self.at(5))
        self.assertEqual(again["decision"], "deny")
        self.assertEqual(self.mgr.state("prop-1", now=self.at(5)), "DENIED")

    def test_owner_in_builders_refused_at_create(self):
        with self.assertRaises(ApprovalError):
            make_request(self.mgr, builder_ids=[OWNER_ID, "seat-10", "seat-11"])

    def test_owner_in_builders_pure_evaluate(self):
        req = ProtectedChangeRequest(
            proposal_id="p1", author_id="seat-9",
            builder_ids=(OWNER_ID, "seat-10", "seat-11"),
            changed_paths=("eval/gate.py",), content_hash="a" * 64,
            preimage_hash="b" * 64, rationale="r", evidence_ref="e",
            requested_at=NOW, expires_at=ts(T0 + timedelta(hours=1)))
        base = {"proposal_id": "p1", "content_hash": "a" * 64,
                "expires_at": req.expires_at}
        d = evaluate_approvals(request=req, owner_approval=owner_leg(base),
                               external_review=external_leg(base), now=NOW)
        self.assertIn("owner_approval_actor_forbidden", d.reasons)

    def test_consume_none_candidate_is_approval_error(self):
        armed(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.consume(proposal_id="prop-1",
                             candidate={"eval/gate.py": None},
                             preimage=dict(PRE), now=self.at(10))
        with self.assertRaises(ApprovalError):
            content_hash_for(proposal_id="p", expires_at="e",
                             candidate=dict(CAND), preimage={})

    def test_receipt_carries_expiry_and_preimage(self):
        req = armed(self.mgr)
        receipt = self.mgr.consume(proposal_id="prop-1", candidate=dict(CAND),
                                   preimage=dict(PRE), now=self.at(10))
        self.assertEqual(receipt.preimage_hash, req["preimage_hash"])
        self.assertTrue(receipt.effective_expires_at)

    def test_package_exports_importable(self):
        import oversight
        for name in oversight.__all__:
            self.assertTrue(hasattr(oversight, name), name)

    def test_journal_replay_state_machine_enforced(self):
        import oversight.approval as ap
        mgr = self.mgr
        req = make_request(mgr)
        # craft a hash-valid journal that resurrects a consumed proposal
        entries = copy.deepcopy(mgr.journal["entries"])
        fake = {"kind": "requested", "proposal_id": "prop-1", "at": NOW,
                "request": req}
        fake["seq"] = len(entries) + 1
        prev = entries[-1]["entry_hash"]
        fake["entry_hash"] = mgr._entry_hash(fake, prev)
        entries.append(fake)
        journal = {"schema_version": 1, "seq": len(entries),
                   "entries": entries, "used_proposal_ids": ["prop-1"],
                   "digest": ""}
        journal["digest"] = mgr._compute_digest(journal)
        path = Path(self.tmp.name) / "journal" / "journal.json"
        path.write_text(json.dumps(journal))
        with self.assertRaises(CorruptJournalError):
            make_manager(self.tmp.name)

    def test_journal_used_ids_mismatch_detected(self):
        armed(self.mgr)
        path = Path(self.tmp.name) / "journal" / "journal.json"
        data = json.loads(path.read_text())
        data["used_proposal_ids"] = []
        data["digest"] = self.mgr._compute_digest(data)
        path.write_text(json.dumps(data))
        with self.assertRaises(CorruptJournalError):
            make_manager(self.tmp.name)

    def test_save_failure_rolls_back(self):
        import os as _os
        import oversight.approval as ap
        req = make_request(self.mgr)
        real_replace = _os.replace

        def boom(src, dst):
            raise OSError("simulated replace failure")

        ap.os.replace = boom
        try:
            with self.assertRaises(OSError):
                self.mgr.record_owner_approval(owner_leg(req), now=self.at(5))
        finally:
            ap.os.replace = real_replace
        self.assertEqual(len(self.mgr.journal["entries"]), 1)
        # retry succeeds exactly once
        self.mgr.record_owner_approval(owner_leg(req), now=self.at(5))
        kinds = [e["kind"] for e in self.mgr.history()]
        self.assertEqual(kinds, ["requested", "owner_approval"])

    def test_bound_expiry_and_proposal_mismatch_refused_at_record(self):
        req = make_request(self.mgr)
        with self.assertRaises(ApprovalError):
            self.mgr.record_owner_approval(
                owner_leg(req, bound_expires_at=self.at(999)), now=self.at(5))
        with self.assertRaises(ApprovalError):
            self.mgr.record_external_review(
                external_leg(req, proposal_id="other"), now=self.at(6))

    def test_intermediate_states(self):
        req = make_request(self.mgr)
        self.mgr.record_owner_approval(owner_leg(req), now=self.at(5))
        self.assertEqual(self.mgr.state("prop-1", now=self.at(5)),
                         "OWNER_APPROVED")
        mgr2_dir = tempfile.TemporaryDirectory()
        try:
            mgr2 = make_manager(mgr2_dir.name)
            req2 = make_request(mgr2)
            mgr2.record_external_review(external_leg(req2), now=self.at(6))
            self.assertEqual(mgr2.state("prop-1", now=self.at(6)),
                             "EXTERNALLY_REVIEWED")
        finally:
            mgr2_dir.cleanup()

    def test_history_and_digest_accessors(self):
        armed(self.mgr)
        self.assertEqual(len(self.mgr.history()), 3)
        self.assertEqual(self.mgr.state_digest(), self.mgr.journal["digest"])


class VerificationRound2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = make_manager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, minutes):
        return ts(T0 + timedelta(minutes=minutes))

    def test_deny_is_single_append_and_terminal(self):
        req = make_request(self.mgr)
        self.mgr.record_owner_approval(owner_leg(req, decision="deny"),
                                       now=self.at(5))
        kinds = [e["kind"] for e in self.mgr.history()]
        self.assertEqual(kinds, ["requested", "owner_approval"])
        self.assertEqual(self.mgr.state("prop-1", now=self.at(5)), "DENIED")
        mgr2 = make_manager(self.tmp.name)
        self.assertEqual(mgr2.state("prop-1", now=self.at(5)), "DENIED")
        # slot is free for a fresh proposal id
        make_request(mgr2, proposal_id="prop-2")

    def test_external_deny_derives_terminal(self):
        req = make_request(self.mgr)
        self.mgr.record_external_review(external_leg(req, decision="deny"),
                                        now=self.at(6))
        self.assertEqual(self.mgr.state("prop-1", now=self.at(6)), "DENIED")

    def test_post_replace_fsync_failure_still_commits(self):
        import oversight.approval as ap
        req = make_request(self.mgr)
        real_fsync = ap.os.fsync
        calls = {"n": 0}

        def flaky(fd):
            calls["n"] += 1
            if calls["n"] == 2:  # directory fsync, after os.replace
                raise OSError("simulated dir fsync failure")
            return real_fsync(fd)

        ap.os.fsync = flaky
        try:
            self.mgr.record_owner_approval(owner_leg(req), now=self.at(5))
        finally:
            ap.os.fsync = real_fsync
        # commit point was the replace: entry is kept, memory == disk
        self.assertEqual(self.mgr.state("prop-1", now=self.at(5)),
                         "OWNER_APPROVED")
        mgr2 = make_manager(self.tmp.name)
        self.assertEqual(mgr2.state("prop-1", now=self.at(5)), "OWNER_APPROVED")
        kinds = [e["kind"] for e in mgr2.history()]
        self.assertEqual(kinds, ["requested", "owner_approval"])

    def test_crafted_journal_deny_leg_then_consume_rejected(self):
        req = armed(self.mgr)
        path = Path(self.tmp.name) / "journal" / "journal.json"
        data = json.loads(path.read_text())
        # flip the owner leg to a deny and drop the consumed entry is not
        # possible without recompute; instead craft deny->consumed chain
        entries = data["entries"][:1]  # just requested
        deny = {"kind": "owner_approval", "proposal_id": "prop-1",
                "at": NOW, "approval": dict(owner_leg(req, decision="deny").__dict__)}
        deny["seq"] = 2
        deny["entry_hash"] = self.mgr._entry_hash(deny, entries[-1]["entry_hash"])
        entries.append(deny)
        cons = {"kind": "consumed", "proposal_id": "prop-1", "at": NOW,
                "decision_id": "x", "content_hash": req["content_hash"]}
        cons["seq"] = 3
        cons["entry_hash"] = self.mgr._entry_hash(cons, deny["entry_hash"])
        entries.append(cons)
        journal = {"schema_version": 1, "seq": 3, "entries": entries,
                   "used_proposal_ids": ["prop-1"], "digest": ""}
        journal["digest"] = self.mgr._compute_digest(journal)
        path.write_text(json.dumps(journal))
        with self.assertRaises(CorruptJournalError):
            make_manager(self.tmp.name)
