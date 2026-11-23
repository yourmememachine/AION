"""Tests for ceremony supersession decisions (cycle 24,
Option A; design-b / DESIGN-FINAL R3).

Covered, in three layers:

* CeremonySupersessionLedger (the new journal): append/find
  roundtrip with fields copied from the head entry + the
  envelope; single-decision-per-envelope refused at append;
  two decisions against the SAME abandoned head for DIFFERENT
  envelopes allowed (the deliberate non-enforcement); load-time
  coherence refusals (duplicate new_authorisation_id, candidate
  not strictly ahead of the abandoned target, superseding old
  pin not behind the abandoned target, non-hex ids); hash-chain
  integrity (tamper -> CorruptLedgerError).
* check_head binding: the supersede shape without a decision
  raises SupersedeRequiredError (NOT a HeadRegressionError);
  a bound decision lands the primary; the mutation cases —
  decision bound to a different candidate, a different head,
  a different envelope, a different operator — all refuse
  HeadRegressionError; a decision minted against a head that
  has since moved is stale and refuses; the journal-known
  hash binding precedes the decision check; non-supersede
  shapes never raise supersede-required; burned_unadopted
  never supersedes.
* The ceremony_supersede verifier mode, through the real
  subprocess (fixture cloned from
  tests/test_trust_ceremony_consume.py): every refusal code,
  the happy path (decision journaled + signing-ledger mirror),
  a second decision for the same envelope ->
  ceremony_supersede_unproven, a decision for an envelope that
  needs no supersede -> ceremony_supersede_unproven, and the
  consume integration (a supersede-shaped envelope consumes
  ONLY after a decision; the decision is spent by its own
  envelope only).
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from signing.ceremony_authorisation import (
    _make_ceremony_signing_key,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_to_dict,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    sign_ceremony_authorisation,
)
from signing.gate_decision import _canonical, _sha256
from trust import protocol
from trust.client import VerifierClient
from trust.ledger import (
    AlreadyConsumedError,
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
    CorruptLedgerError,
    HeadRegressionError,
    LedgerError,
    SigningLedger,
    SupersedeRequiredError,
)

NOW = "2026-11-20T12:00:00+00:00"
GENESIS = "0" * 64

# -- direct-minted envelopes (ledger-level tests) -------------------------

VERIFIER_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle24 supersede test seed").digest())
_counter = [0]


def mint(reason="chain_gap_recovery", **over):
    _counter[0] += 1
    kwargs = dict(
        signing_key=VERIFIER_KEY, signer_id="verifier-svc",
        operator_id="operator-1",
        ceremony_id=f"ceremony-sup-{_counter[0]}",
        reason=reason,
        old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
        candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                   "signer_id": "snapshot-svc",
                   "key_id": "key-0123456789abcdef"},
        evidence_hash="e" * 64, evidence_ref="evidence-bundle-1",
        now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def cand(seq, payload_hash):
    return {"cycle_seq": seq, "payload_hash": payload_hash,
            "signer_id": "snapshot-svc",
            "key_id": "key-0123456789abcdef"}


def supersede_env(**over):
    over.setdefault("old_pin",
                    {"cycle_seq": 41, "payload_hash": "a" * 64})
    over.setdefault("candidate", cand(52, "c" * 64))
    return mint(reason="chain_gap_recovery", **over)


def write_supersession_journal(journal_dir, field_dicts):
    """Write a supersession journal file literally, hashes
    computed by hand over exactly the given fields."""
    journal_dir = Path(journal_dir)
    journal_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    prev = GENESIS
    for i, fields in enumerate(field_dicts, start=1):
        entry = {"seq": i, "kind": "supersede",
                 "recorded_at": NOW, "prev_hash": prev}
        entry.update(fields)
        entry["entry_hash"] = _sha256(_canonical(
            {k: v for k, v in entry.items() if k != "entry_hash"}))
        prev = entry["entry_hash"]
        entries.append(entry)
    (journal_dir / "ceremony-supersessions.json").write_text(
        json.dumps({"entries": entries}, sort_keys=True),
        encoding="utf-8")
    return entries


def decision_fields(**over):
    fields = dict(
        abandoned_authorisation_id="1" * 64,
        abandoned_ceremony_id="ceremony-old-1",
        abandoned_old_cycle_seq=41,
        abandoned_old_payload_hash="a" * 64,
        abandoned_new_cycle_seq=47,
        abandoned_new_payload_hash="b" * 64,
        new_authorisation_id="2" * 64,
        new_ceremony_id="ceremony-new-1",
        operator_id="operator-1",
        superseding_old_cycle_seq=41,
        superseding_old_payload_hash="a" * 64,
        candidate_cycle_seq=52,
        candidate_payload_hash="c" * 64,
        decided_at=NOW)
    fields.update(over)
    return fields


class CeremonySupersessionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.consumption = CeremonyConsumptionLedger(self.tmp.name)
        self.head_env = mint()
        self.consumption.append_consumption(
            self.head_env, recorded_at=NOW)
        self.head_entry = self.consumption.entries()[-1]
        self.ledger = CeremonySupersessionLedger(self.tmp.name)

    def test_append_and_find_by_new_authorisation_roundtrip(self):
        env = supersede_env()
        entry = self.ledger.append_decision(
            abandoned_entry=self.head_entry, signed=env,
            recorded_at=NOW)
        self.assertEqual(entry["kind"], "supersede")
        self.assertEqual(entry["abandoned_authorisation_id"],
                         self.head_entry["authorisation_id"])
        self.assertEqual(entry["abandoned_ceremony_id"],
                         self.head_entry["ceremony_id"])
        self.assertEqual(entry["abandoned_old_cycle_seq"], 41)
        self.assertEqual(entry["abandoned_old_payload_hash"],
                         "a" * 64)
        self.assertEqual(entry["abandoned_new_cycle_seq"], 47)
        self.assertEqual(entry["abandoned_new_payload_hash"],
                         "b" * 64)
        self.assertEqual(entry["new_authorisation_id"],
                         env.authorisation_id)
        self.assertEqual(entry["new_ceremony_id"], env.ceremony_id)
        self.assertEqual(entry["operator_id"], "operator-1")
        self.assertEqual(entry["superseding_old_cycle_seq"], 41)
        self.assertEqual(entry["superseding_old_payload_hash"],
                         "a" * 64)
        self.assertEqual(entry["candidate_cycle_seq"], 52)
        self.assertEqual(entry["candidate_payload_hash"], "c" * 64)
        self.assertEqual(entry["decided_at"], NOW)
        self.assertEqual(entry["decided_at"], entry["recorded_at"])
        found = self.ledger.find_by_new_authorisation(
            env.authorisation_id)
        self.assertEqual(found, entry)
        self.assertIsNone(
            self.ledger.find_by_new_authorisation("f" * 64))

    def test_second_decision_same_envelope_refused_at_append(self):
        env = supersede_env()
        self.ledger.append_decision(
            abandoned_entry=self.head_entry, signed=env,
            recorded_at=NOW)
        with self.assertRaises(LedgerError):
            self.ledger.append_decision(
                abandoned_entry=self.head_entry, signed=env,
                recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_two_decisions_same_abandoned_different_envelopes_allowed(self):
        # Deliberate non-enforcement (design-b §4.1): the first
        # envelope may expire unconsumed; a second envelope gets
        # its own decision against the same head.
        env1 = supersede_env()
        env2 = supersede_env(candidate=cand(55, "d" * 64))
        self.ledger.append_decision(
            abandoned_entry=self.head_entry, signed=env1,
            recorded_at=NOW)
        self.ledger.append_decision(
            abandoned_entry=self.head_entry, signed=env2,
            recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 2)

    def test_load_rejects_duplicate_new_authorisation_id(self):
        other = Path(self.tmp.name) / "dup"
        write_supersession_journal(other, [
            decision_fields(),
            decision_fields(abandoned_authorisation_id="3" * 64,
                            new_ceremony_id="ceremony-new-2")])
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(other)

    def test_load_rejects_candidate_not_strictly_ahead_of_abandoned(self):
        other = Path(self.tmp.name) / "ahead"
        write_supersession_journal(other, [
            decision_fields(candidate_cycle_seq=47)])
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(other)

    def test_load_rejects_superseding_old_not_behind_abandoned(self):
        other = Path(self.tmp.name) / "behind"
        write_supersession_journal(other, [
            decision_fields(superseding_old_cycle_seq=47)])
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(other)

    def test_load_rejects_non_hex_ids(self):
        other = Path(self.tmp.name) / "hex"
        write_supersession_journal(other, [
            decision_fields(new_authorisation_id="zz" * 32)])
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(other)

    def test_hash_chain_intact_after_append(self):
        env = supersede_env()
        self.ledger.append_decision(
            abandoned_entry=self.head_entry, signed=env,
            recorded_at=NOW)
        fresh = CeremonySupersessionLedger(self.tmp.name)
        self.assertEqual(len(fresh.entries()), 1)
        # Tamper: rewrite a binding field in the file; the
        # entry hash no longer matches -> corrupt on load.
        path = Path(self.tmp.name) / "ceremony-supersessions.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["entries"][0]["candidate_payload_hash"] = "f" * 64
        path.write_text(json.dumps(doc, sort_keys=True),
                        encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(self.tmp.name)


class SupersedeDecisionBindingTests(unittest.TestCase):
    """check_head / append_consumption decision binding
    (design-b §5, §9.1). Head fixture: primary consumption
    41/"a"*64 -> 47/"b"*64, as in SupersedeRuleTests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = CeremonyConsumptionLedger(self.tmp.name)
        self.ledger.append_consumption(mint(), recorded_at=NOW)
        self.assertEqual(self.ledger.head_target(), (47, "b" * 64))

    def _decision_for(self, env, head_entry=None):
        head = head_entry or self.ledger.entries()[-1]
        return CeremonySupersessionLedger(
            self.tmp.name).append_decision(
                abandoned_entry=head, signed=env, recorded_at=NOW)

    def test_supersede_shape_without_decision_raises_supersede_required(self):
        env = supersede_env()
        with self.assertRaises(SupersedeRequiredError) as ctx:
            CeremonyConsumptionLedger.check_head(
                self.ledger.entries(), env)
        self.assertNotIsInstance(ctx.exception,
                                 HeadRegressionError)
        with self.assertRaises(SupersedeRequiredError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_with_bound_decision_lands_primary(self):
        env = supersede_env()
        decision = self._decision_for(env)
        entry = self.ledger.append_consumption(
            env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(entry["consumption_kind"], "primary")
        self.assertEqual(entry["recovery_depth"], 0)
        self.assertEqual(self.ledger.head_target(), (52, "c" * 64))

    def test_supersede_decision_bound_to_other_candidate_refuses(self):
        env = supersede_env()
        decision = dict(self._decision_for(env),
                        candidate_payload_hash="f" * 64)
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_decision_bound_to_other_head_refuses(self):
        env = supersede_env()
        decision = self._decision_for(env)
        for field, value in (
                ("abandoned_authorisation_id", "f" * 64),
                ("abandoned_new_payload_hash", "f" * 64)):
            mutated = dict(decision, **{field: value})
            with self.assertRaises(HeadRegressionError):
                self.ledger.append_consumption(
                    env, recorded_at=NOW,
                    supersede_decision=mutated)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_decision_bound_to_other_envelope_refuses(self):
        env = supersede_env()
        decision = dict(self._decision_for(env),
                        new_authorisation_id="f" * 64)
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_decision_wrong_operator_refuses(self):
        env = supersede_env()
        decision = dict(self._decision_for(env),
                        operator_id="operator-2")
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_decision_stale_after_head_moves_refuses(self):
        env = supersede_env()
        decision = self._decision_for(env)
        # A different primary consumes to 50 off the head
        # (old pin == head, the normal next ceremony).
        nxt = mint(old_pin={"cycle_seq": 47,
                            "payload_hash": "b" * 64},
                   candidate=cand(50, "d" * 64))
        self.ledger.append_consumption(nxt, recorded_at=NOW)
        self.assertEqual(self.ledger.head_target(), (50, "d" * 64))
        # The decision was minted against head 47; against
        # head 50 it is misbound -> HeadRegressionError, NOT
        # supersede-required.
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(len(self.ledger.entries()), 2)

    def test_supersede_hash_binding_failure_precedes_decision_check(self):
        # Fabricated old hash at a journal-known seq, NO
        # decision: HeadRegressionError, never
        # SupersedeRequiredError (design-b §3 order).
        env = supersede_env(
            old_pin={"cycle_seq": 41, "payload_hash": "f" * 64})
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_non_supersede_shapes_never_raise_supersede_required(self):
        from trust.ledger import AlreadyConsumedError
        env_at = supersede_env(candidate=cand(47, "b" * 64))
        with self.assertRaises(AlreadyConsumedError):
            self.ledger.append_consumption(env_at, recorded_at=NOW)
        env_behind = supersede_env(candidate=cand(44, "d" * 64))
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env_behind, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_burned_unadopted_never_supersede(self):
        env = mint(reason="burned_unadopted",
                   old_pin={"cycle_seq": 41,
                            "payload_hash": "a" * 64},
                   candidate=cand(52, "c" * 64))
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)


# -- fix-round tests (cycle 24 part 1, r3-F1/F2/F3, r4-F3) ----------------


class _StubSigned:
    """Minimal envelope stand-in for shapes the signing layer
    refuses to mint (e.g. initial_anchor carrying an old pin):
    supersede_head / check_head read only these attributes."""

    def __init__(self, *, reason, old_pin, candidate):
        self.reason = reason
        self.old_pin = old_pin
        self.candidate = candidate
        self.operator_id = "operator-1"
        self.authorisation_id = "f" * 64


def _synth_entry(old_seq, old_hash, new_seq, new_hash, auth):
    return {
        "authorisation_id": auth, "ceremony_id": f"ceremony-{auth}",
        "operator_id": "operator-1",
        "old_cycle_seq": old_seq, "old_payload_hash": old_hash,
        "new_cycle_seq": new_seq, "new_payload_hash": new_hash,
        "evidence_hash": "e" * 64, "consumed_at": NOW}


def _bound_decision(entries, env):
    head = entries[-1]
    return {
        "abandoned_authorisation_id": head["authorisation_id"],
        "abandoned_old_cycle_seq": head["old_cycle_seq"],
        "abandoned_old_payload_hash": head["old_payload_hash"],
        "abandoned_new_cycle_seq": head["new_cycle_seq"],
        "abandoned_new_payload_hash": head["new_payload_hash"],
        "new_authorisation_id": env.authorisation_id,
        "candidate_cycle_seq": env.candidate["cycle_seq"],
        "candidate_payload_hash": env.candidate["payload_hash"],
        "superseding_old_cycle_seq": env.old_pin["cycle_seq"],
        "superseding_old_payload_hash": env.old_pin["payload_hash"],
        "operator_id": env.operator_id}


class SupersedeDriftEquivalenceTests(unittest.TestCase):
    """r3-F1 drift equivalence: check_head's supersede branch
    derives its shape/hash-binding determination from
    supersede_head itself, so for EVERY generated journal /
    envelope shape the mode-side predicate and the consume-side
    branch must agree: supersede_head offers the shape (not
    None) IFF check_head, with no decision supplied, raises
    SupersedeRequiredError — never HeadRegressionError in one
    and shape-offered in the other. Where the predicate holds,
    a decision bound to the envelope + current head must make
    check_head pass; where it does not hold in the branch
    position, no decision can rescue the envelope."""

    def _classify(self, entries, env, decision=None):
        try:
            CeremonyConsumptionLedger.check_head(
                entries, env, supersede_decision=decision)
        except SupersedeRequiredError:
            return "supersede_required"
        except AlreadyConsumedError:
            return "already_consumed"
        except HeadRegressionError:
            return "head_regression"
        return "pass"

    def _cases(self):
        base = [_synth_entry(35, "9" * 64, 41, "a" * 64, "auth-e1"),
                _synth_entry(41, "a" * 64, 47, "b" * 64, "auth-e2")]
        genesis = [_synth_entry(None, "", 47, "b" * 64, "auth-g")]
        probe_b = [_synth_entry(41, "", 47, "b" * 64, "auth-pb")]
        old41 = {"cycle_seq": 41, "payload_hash": "a" * 64}
        return [
            ("holds_old_known_as_head_old_and_prior_new", base,
             supersede_env()),
            ("fabricated_old_at_known_seq", base,
             supersede_env(old_pin={
                 "cycle_seq": 41, "payload_hash": "f" * 64})),
            ("holds_old_known_via_earlier_entry_old", base,
             mint(old_pin={"cycle_seq": 35, "payload_hash": "9" * 64},
                  candidate=cand(52, "c" * 64))),
            ("fabricated_old_at_earlier_known_seq", base,
             mint(old_pin={"cycle_seq": 35, "payload_hash": "f" * 64},
                  candidate=cand(52, "c" * 64))),
            ("holds_old_at_unrecorded_seq", base,
             mint(old_pin={"cycle_seq": 30, "payload_hash": "d" * 64},
                  candidate=cand(52, "c" * 64))),
            ("candidate_at_head_same_hash", base,
             mint(old_pin=old41, candidate=cand(47, "b" * 64))),
            ("candidate_behind_head", base,
             mint(old_pin=old41, candidate=cand(44, "d" * 64))),
            ("old_at_head_correct_normal_next", base,
             mint(old_pin={"cycle_seq": 47, "payload_hash": "b" * 64},
                  candidate=cand(52, "c" * 64))),
            ("old_at_head_fork", base,
             mint(old_pin={"cycle_seq": 47, "payload_hash": "f" * 64},
                  candidate=cand(52, "c" * 64))),
            ("burned_unadopted_candidate_ahead", base,
             mint(reason="burned_unadopted", old_pin=old41,
                  candidate=cand(52, "c" * 64))),
            ("burned_unadopted_matching_head_is_recovery", base,
             mint(reason="burned_unadopted", old_pin=old41,
                  candidate=cand(47, "b" * 64))),
            ("initial_anchor_no_pin", base,
             mint(reason="initial_anchor", old_pin=None,
                  candidate=cand(52, "c" * 64))),
            ("initial_anchor_with_old_pin_stub", base,
             _StubSigned(reason="initial_anchor", old_pin=old41,
                         candidate=cand(52, "c" * 64))),
            ("lost_pin_with_old_pin_stub", base,
             _StubSigned(reason="lost_pin", old_pin=old41,
                         candidate=cand(52, "c" * 64))),
            ("probe_b_empty_string_old_hash", probe_b,
             supersede_env(old_pin={
                 "cycle_seq": 41, "payload_hash": "f" * 64})),
            ("genesis_head_old_seq_unrecorded", genesis,
             supersede_env(old_pin={
                 "cycle_seq": 41, "payload_hash": "f" * 64})),
        ]

    def test_mode_predicate_and_consume_branch_agree(self):
        for name, entries, env in self._cases():
            with self.subTest(case=name):
                predicate = CeremonyConsumptionLedger.supersede_head(
                    entries, env) is not None
                outcome = self._classify(entries, env)
                self.assertEqual(
                    predicate, outcome == "supersede_required",
                    f"{name}: supersede_head offered={predicate} "
                    f"but check_head outcome={outcome}")
                if predicate:
                    self.assertEqual(
                        self._classify(
                            entries, env,
                            decision=_bound_decision(entries, env)),
                        "pass", name)

    def test_probe_b_int_seq_empty_hash_old_side_corner(self):
        # Reviewer's probe B: the head entry spells its old
        # side as int seq 41 with the empty-string (no-pin)
        # hash; the envelope claims old pin 41 / "f"*64 with
        # candidate 52. supersede_head SKIPS the "" spelling
        # when collecting recorded hashes, so its recorded set
        # for seq 41 is empty and the shape holds; the pre-fix
        # check_head collected "" unconditionally and refused
        # HeadRegressionError — the two sides had diverged.
        # After the structural fix both sides derive from the
        # predicate: the bare consume is refused as
        # supersede-required (NOT head regression), and with a
        # bound decision it passes — identically on both sides.
        entries = [_synth_entry(41, "", 47, "b" * 64, "auth-pb")]
        env = supersede_env(old_pin={
            "cycle_seq": 41, "payload_hash": "f" * 64})
        self.assertIsNotNone(
            CeremonyConsumptionLedger.supersede_head(entries, env))
        self.assertEqual(self._classify(entries, env),
                         "supersede_required")
        self.assertEqual(
            self._classify(entries, env,
                          decision=_bound_decision(entries, env)),
            "pass")

    def test_fabricated_known_hash_refuses_even_with_decision(self):
        # The hash-binding gate runs BEFORE the decision gate:
        # a decision, however bound, cannot rescue a fabricated
        # old-pin hash at a journal-known seq.
        entries = [_synth_entry(35, "9" * 64, 41, "a" * 64, "auth-e1"),
                   _synth_entry(41, "a" * 64, 47, "b" * 64, "auth-e2")]
        env = supersede_env(old_pin={
            "cycle_seq": 41, "payload_hash": "f" * 64})
        self.assertIsNone(
            CeremonyConsumptionLedger.supersede_head(entries, env))
        self.assertEqual(
            self._classify(entries, env,
                          decision=_bound_decision(entries, env)),
            "head_regression")

    def test_supersede_head_excludes_initial_anchor(self):
        # r4-F3: check_head refuses initial_anchor outright
        # against a non-empty journal; the predicate must not
        # offer the shape either (unreachable via the signing
        # layer, which refuses initial_anchor + old pin, but
        # agreement is by construction, not by reachability).
        entries = [_synth_entry(41, "a" * 64, 47, "b" * 64, "auth-e2")]
        stub = _StubSigned(
            reason="initial_anchor",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate=cand(52, "c" * 64))
        self.assertIsNone(
            CeremonyConsumptionLedger.supersede_head(entries, stub))
        self.assertEqual(self._classify(entries, stub),
                         "head_regression")


class AppendDecisionShapeValidationTests(unittest.TestCase):
    """r3-F2: append_decision must refuse, BEFORE appending,
    a decision its own _load would reject — otherwise it can
    write a self-bricking journal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.consumption = CeremonyConsumptionLedger(self.tmp.name)
        self.consumption.append_consumption(mint(), recorded_at=NOW)
        self.head_entry = self.consumption.entries()[-1]
        self.assertEqual(self.head_entry["new_cycle_seq"], 47)
        self.ledger = CeremonySupersessionLedger(self.tmp.name)

    def test_candidate_not_ahead_of_abandoned_refuses_writes_nothing(self):
        # Reviewer's probe F shape: abandoned head @47,
        # candidate 45 (and the boundary case, candidate == 47).
        for seq in (45, 47):
            env = supersede_env(candidate=cand(seq, "c" * 64))
            with self.assertRaises(LedgerError):
                self.ledger.append_decision(
                    abandoned_entry=self.head_entry, signed=env,
                    recorded_at=NOW)
            self.assertEqual(self.ledger.entries(), [])
        # Nothing was written: a fresh instance loads cleanly.
        self.assertEqual(
            CeremonySupersessionLedger(self.tmp.name).entries(), [])

    def test_superseding_old_not_behind_abandoned_refuses(self):
        env = supersede_env(
            old_pin={"cycle_seq": 47, "payload_hash": "b" * 64})
        with self.assertRaises(LedgerError):
            self.ledger.append_decision(
                abandoned_entry=self.head_entry, signed=env,
                recorded_at=NOW)
        self.assertEqual(self.ledger.entries(), [])
        self.assertEqual(
            CeremonySupersessionLedger(self.tmp.name).entries(), [])


class SupersessionJournalLoadCoherenceTests(unittest.TestCase):
    """r3-F3: _load coherence for the supersession journal —
    hand-built journals with a recomputed hash chain (the
    reviewer's method), so each refusal is the new validation,
    not a broken chain."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _assert_corrupt(self, name, fields_list):
        other = Path(self.tmp.name) / name
        write_supersession_journal(other, fields_list)
        with self.assertRaises(CorruptLedgerError):
            CeremonySupersessionLedger(other)

    def test_decided_at_must_equal_recorded_at(self):
        self._assert_corrupt("decided", [
            decision_fields(
                decided_at="2026-11-20T13:00:00+00:00")])

    def test_candidate_payload_hash_empty_is_corrupt(self):
        self._assert_corrupt("candempty", [
            decision_fields(candidate_payload_hash="")])

    def test_candidate_payload_hash_non_hex_is_corrupt(self):
        self._assert_corrupt("candhex", [
            decision_fields(candidate_payload_hash="z" * 64)])

    def test_entry_kind_must_be_supersede(self):
        self._assert_corrupt("kind", [
            dict(decision_fields(), kind="consume")])

    def test_abandoned_old_empty_hash_genesis_spelling_loads(self):
        # The abandoned OLD side keeps the legitimate
        # empty-string spelling (genesis burns: no old pin,
        # seq None, hash "").
        other = Path(self.tmp.name) / "genesis"
        write_supersession_journal(other, [
            decision_fields(abandoned_old_cycle_seq=None,
                            abandoned_old_payload_hash="")])
        entries = CeremonySupersessionLedger(other).entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["abandoned_old_payload_hash"], "")


# -- verifier-mode tests (real subprocess) --------------------------------

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-uma"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
ARTIFACT = b"ceremony evidence bundle: case file 1\n"
EVIDENCE_HASH = hashlib.sha256(ARTIFACT).hexdigest()
ARTIFACT2 = b"ceremony evidence bundle: case file 2\n"
EVIDENCE_HASH2 = hashlib.sha256(ARTIFACT2).hexdigest()
ARTIFACT3 = b"ceremony evidence bundle: case file 3\n"
EVIDENCE_HASH3 = hashlib.sha256(ARTIFACT3).hexdigest()
REPO = Path(__file__).resolve().parents[1]


class SupersedeFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        (self.evidence_dir / "case-file-1").write_bytes(ARTIFACT)
        (self.evidence_dir / "case-file-2").write_bytes(ARTIFACT2)
        (self.evidence_dir / "case-file-3").write_bytes(ARTIFACT3)
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.ledger_home = self.home / "ledger"
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.ledger_home),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATOR + ",operator-backup",
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, **over):
        body = {
            "operator_id": OPERATOR,
            "ceremony_id": "ceremony-2026-11-28-001",
            "reason": "chain_gap_recovery",
            "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
            "candidate": {"cycle_seq": 47, "payload_hash": CAND_HASH,
                          "signer_id": "snapshot-svc",
                          "key_id": "key-0123456789abcdef"},
            "evidence_hash": EVIDENCE_HASH,
            "evidence_ref": "case-file-1",
        }
        body.update(over)
        return body

    def authorise(self, **over):
        body = self.body(**over)
        return self.client.ceremony_authorise(
            operator_id=body["operator_id"],
            ceremony_id=body["ceremony_id"], reason=body["reason"],
            old_pin=body["old_pin"], candidate=body["candidate"],
            evidence_hash=body["evidence_hash"],
            evidence_ref=body["evidence_ref"])

    def full_env(self, env_over=None):
        env = dict(self.env)
        if env_over:
            env.update(env_over)
        full_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
        full_env.update(env)
        return full_env

    def raw(self, body, *, env_over=None, mode="ceremony_supersede"):
        request_id = protocol.new_request_id()
        raw = protocol.encode_request(request_id, mode, body)
        result = subprocess.run(
            [sys.executable, "-m", "trust.verifier_main"],
            input=raw, capture_output=True, timeout=30,
            cwd=str(REPO), env=self.full_env(env_over))
        doc = None
        try:
            doc = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
        return result.returncode, doc, result.stdout

    def supersede(self, envelope, operator_id=OPERATOR, **kw):
        return self.raw({"operator_id": operator_id,
                         "signed_authorisation": envelope}, **kw)

    def consume(self, envelope, **kw):
        return self.raw({"signed_authorisation": envelope},
                        mode="ceremony_consume", **kw)

    def error_code(self, doc):
        return doc["error"]["code"] if doc and doc.get("error") \
            else None

    def candidate(self, seq, payload_hash):
        return {"cycle_seq": seq, "payload_hash": payload_hash,
                "signer_id": "snapshot-svc",
                "key_id": "key-0123456789abcdef"}

    def consumption_entries(self):
        if not (self.ledger_home
                / "ceremony-consumptions.json").exists():
            return []
        return CeremonyConsumptionLedger(self.ledger_home).entries()

    def supersession_entries(self):
        if not (self.ledger_home
                / "ceremony-supersessions.json").exists():
            return []
        return CeremonySupersessionLedger(self.ledger_home).entries()

    def signing_entries(self):
        if not (self.ledger_home / "signing-ledger.json").exists():
            return []
        return SigningLedger(self.ledger_home).entries()

    def sign_directly(self, *, ceremony_id, candidate, old_pin=None,
                      reason="chain_gap_recovery",
                      operator_id=OPERATOR,
                      evidence_hash=EVIDENCE_HASH,
                      evidence_ref="case-file-1", now=None):
        signed = sign_ceremony_authorisation(
            signing_key=self.seed_key, signer_id=SIGNER,
            operator_id=operator_id, ceremony_id=ceremony_id,
            reason=reason, old_pin=old_pin, candidate=candidate,
            evidence_hash=evidence_hash, evidence_ref=evidence_ref,
            now=now)
        return ceremony_authorisation_envelope_to_dict(signed)

    def head_and_supersede_envelope(self):
        """Consume the primary to 47; authorise a fresh primary
        (old 41, candidate 50) standing in the supersede shape.
        Returns the new envelope dict."""
        code, doc, _ = self.consume(self.authorise())
        self.assertEqual(code, 0, msg=str(doc))
        return self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            candidate=self.candidate(50, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")


class CeremonySupersedeModeTests(SupersedeFixture):
    def test_supersede_happy_path_journals_bound_decision(self):
        envelope = self.head_and_supersede_envelope()
        head = self.consumption_entries()[-1]
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        result = doc["result"]
        signed = ceremony_authorisation_envelope_from_dict(envelope)
        self.assertEqual(
            set(result),
            {"abandoned_authorisation_id", "new_authorisation_id",
             "candidate_cycle_seq", "candidate_payload_hash",
             "supersession_seq"})
        self.assertEqual(result["abandoned_authorisation_id"],
                         head["authorisation_id"])
        self.assertEqual(result["new_authorisation_id"],
                         signed.authorisation_id)
        self.assertEqual(result["candidate_cycle_seq"], 50)
        self.assertEqual(result["candidate_payload_hash"], "d" * 64)
        self.assertEqual(result["supersession_seq"], 1)
        decisions = self.supersession_entries()
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision["abandoned_authorisation_id"],
                         head["authorisation_id"])
        self.assertEqual(decision["abandoned_old_cycle_seq"],
                         head["old_cycle_seq"])
        self.assertEqual(decision["abandoned_old_payload_hash"],
                         head["old_payload_hash"])
        self.assertEqual(decision["abandoned_new_cycle_seq"],
                         head["new_cycle_seq"])
        self.assertEqual(decision["abandoned_new_payload_hash"],
                         head["new_payload_hash"])
        self.assertEqual(decision["new_authorisation_id"],
                         signed.authorisation_id)
        self.assertEqual(decision["candidate_cycle_seq"], 50)
        self.assertEqual(decision["operator_id"], OPERATOR)
        # Signing-ledger mirror, scoped kind/format.
        mirrors = [e for e in self.signing_entries()
                   if e["kind"] == "supersede"]
        self.assertEqual(len(mirrors), 1)
        self.assertEqual(mirrors[0]["format"],
                         "ceremony-supersession")
        self.assertEqual(mirrors[0]["decision_id"],
                         signed.authorisation_id)
        # Nothing was consumed by the decision itself.
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_supersede_then_consume_lands(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        ledger = CeremonyConsumptionLedger(self.ledger_home)
        self.assertEqual(ledger.head_target(), (50, "d" * 64))

    def test_consume_without_decision_refuses_supersede_required(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_required")
        # Pre-commit certification: nothing consumed.
        self.assertEqual(len(self.consumption_entries()), 1)
        self.assertEqual(self.supersession_entries(), [])

    def test_decision_for_other_envelope_does_not_spend(self):
        # A decision keyed to envelope A cannot be spent by
        # envelope B: B's consume finds no decision keyed to B.
        envelope_a = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope_a)
        self.assertEqual(code, 0, msg=str(doc))
        envelope_b = self.authorise(
            ceremony_id="ceremony-2026-11-28-003",
            candidate=self.candidate(55, "e" * 64),
            evidence_hash=EVIDENCE_HASH3,
            evidence_ref="case-file-3")
        code, doc, _ = self.consume(envelope_b)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_required")
        self.assertEqual(len(self.consumption_entries()), 1)
        # And A's own consume still lands against its decision.
        code, doc, _ = self.consume(envelope_a)
        self.assertEqual(code, 0, msg=str(doc))
        ledger = CeremonyConsumptionLedger(self.ledger_home)
        self.assertEqual(ledger.head_target(), (50, "d" * 64))

    def test_supersede_unconfigured_operators_refuses(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope, env_over={
            "AION_CEREMONY_OPERATORS": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operators_unconfigured")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_unconfigured_seed_refuses(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope, env_over={
            "AION_CEREMONY_SIGNING_SEED_PATH": ""})
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_seed_unconfigured")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_extra_body_key_malformed(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.raw(
            {"operator_id": OPERATOR,
             "signed_authorisation": envelope, "extra": 1})
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc), "malformed_request")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_missing_operator_malformed(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.raw({"signed_authorisation": envelope})
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc), "malformed_request")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_unlisted_operator_refuses(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope,
                                      operator_id="operator-nope")
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_operator_not_authorised")
        # Oracle pin: membership is checked before any journal
        # read — the supersession journal file is not created.
        self.assertFalse(
            (self.ledger_home
             / "ceremony-supersessions.json").exists())

    def test_supersede_forged_envelope_single_code(self):
        envelope = self.head_and_supersede_envelope()
        forged = dict(envelope, signature="0" * 128)
        code, doc, _ = self.supersede(forged)
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc),
                         "ceremony_authorisation_invalid")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_envelope_for_other_operator_single_code(self):
        # Envelope issued to operator-backup, presented under
        # OPERATOR: the operator mismatch folds into the single
        # invalid code.
        self.consume(self.authorise())
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            operator_id="operator-backup",
            candidate=self.candidate(50, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.supersede(envelope, operator_id=OPERATOR)
        self.assertEqual(code, 2)
        self.assertEqual(self.error_code(doc),
                         "ceremony_authorisation_invalid")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_expired_envelope_refuses_expired(self):
        past = (datetime.now(timezone.utc)
                - timedelta(seconds=2000)).isoformat()
        envelope = self.sign_directly(
            ceremony_id="ceremony-expired-001",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate=self.candidate(50, "d" * 64), now=past)
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_authorisation_expired")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_unissued_envelope_refuses_not_issued(self):
        self.consume(self.authorise())
        envelope = self.sign_directly(
            ceremony_id="ceremony-never-issued-001",
            old_pin={"cycle_seq": 41, "payload_hash": OLD_HASH},
            candidate=self.candidate(50, "d" * 64))
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_not_issued")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_consumed_envelope_refuses_already_consumed(self):
        envelope = self.authorise()
        code, doc, _ = self.consume(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_already_consumed")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_not_needed_candidate_not_ahead_unproven(self):
        self.consume(self.authorise())
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            candidate=self.candidate(47, CAND_HASH),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_not_needed_old_pin_not_behind_unproven(self):
        # The normal next ceremony (old pin == head): no
        # supersede is needed, so no decision may be minted.
        self.consume(self.authorise())
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            old_pin={"cycle_seq": 47, "payload_hash": CAND_HASH},
            candidate=self.candidate(50, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_burned_unadopted_envelope_unproven(self):
        self.consume(self.authorise())
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            reason="burned_unadopted",
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_fabricated_old_hash_unproven(self):
        self.consume(self.authorise())
        envelope = self.authorise(
            ceremony_id="ceremony-2026-11-28-002",
            old_pin={"cycle_seq": 41, "payload_hash": "f" * 64},
            candidate=self.candidate(50, "d" * 64),
            evidence_hash=EVIDENCE_HASH2,
            evidence_ref="case-file-2")
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])

    def test_supersede_second_decision_same_envelope_unproven(self):
        envelope = self.head_and_supersede_envelope()
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 0, msg=str(doc))
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(len(self.supersession_entries()), 1)

    def test_supersede_empty_journal_unproven(self):
        envelope = self.authorise(
            candidate=self.candidate(50, "d" * 64))
        code, doc, _ = self.supersede(envelope)
        self.assertEqual(code, 3)
        self.assertEqual(self.error_code(doc),
                         "ceremony_supersede_unproven")
        self.assertEqual(self.supersession_entries(), [])


if __name__ == "__main__":
    unittest.main()
