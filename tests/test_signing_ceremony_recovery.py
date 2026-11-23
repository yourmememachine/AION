"""Unit tests for cycle 22 WS1 / R1: burned_unadopted recovery.

Covers design A section 9's unit list: vocabulary/drift,
projection coherence, match_head_burn, check_head's scoped
exception, reanchor_pin recovery paths (with a REAL
ledger-backed consumer over a temp dir, per the cycle-21 R12
test-helper discipline — no always-succeed fakes), and
verify_ceremony_record's recovery shapes.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import signing.pin_ceremony as pin_ceremony
from signing import SigningError, make_signing_key
from signing.ceremony_authorisation import (
    REASONS as AUTH_REASONS,
    _EITHER_PIN_REASONS as AUTH_EITHER,
    _NO_PIN_REASONS as AUTH_NO_PIN,
    _make_ceremony_signing_key,
    ceremony_authorisation_payload,
    ceremony_public_key_for,
    sign_ceremony_authorisation,
)
from signing.pin_ceremony import (
    REASONS,
    _EITHER_PIN_REASONS,
    _NO_PIN_REASONS,
    reanchor_pin,
    verify_ceremony_record,
)
from signing.state_snapshot import sign_state_snapshot
from trust.ledger import (
    AlreadyConsumedError,
    CeremonyConsumptionLedger,
    HeadRegressionError,
    LedgerError,
)

# -- shared fixtures ----------------------------------------------------

VERIFIER_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle22 test verifier ceremony seed").digest())
VERIFIER_PIN = ceremony_public_key_for(VERIFIER_KEY)
VERIFIER_SIGNER = "verifier-svc"
SNAPSHOT_KEY = make_signing_key(bytes(range(32, 64)))
SIGNER = "seat-3"
NOW = "2026-11-20T12:00:00+00:00"
OPERATOR = "operator-1"
EVIDENCE = "e" * 64
EVIDENCE2 = "d" * 64
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
CANDIDATE = {"cycle_seq": 47, "payload_hash": CAND_HASH,
             "signer_id": "snapshot-svc",
             "key_id": "key-0123456789abcdef"}
OLD_PIN_PROJ = {"cycle_seq": 41, "payload_hash": OLD_HASH}
CAL = b'{"log":1}'

_mint_counter = [0]


def payload_kwargs(**over):
    kwargs = dict(
        signer_id="verifier-svc", key_id=VERIFIER_KEY.key_id,
        operator_id="operator-uma",
        ceremony_id="ceremony-2026-11-28-001",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN_PROJ),
        candidate=dict(CANDIDATE), evidence_hash="c" * 64,
        evidence_ref="case-file-1", signed_at=NOW,
        expires_at="2026-11-20T12:15:00+00:00")
    kwargs.update(over)
    return kwargs


def mint_envelope(**over):
    _mint_counter[0] += 1
    kwargs = dict(
        signing_key=VERIFIER_KEY, signer_id=VERIFIER_SIGNER,
        operator_id=OPERATOR,
        ceremony_id=f"ceremony-cycle22-{_mint_counter[0]}",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN_PROJ),
        candidate=dict(CANDIDATE), evidence_hash=EVIDENCE,
        evidence_ref="evidence-bundle-1", now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def entry(*, old_seq, old_hash, new_seq, new_hash):
    return {"old_cycle_seq": old_seq, "old_payload_hash": old_hash,
            "new_cycle_seq": new_seq, "new_payload_hash": new_hash}


BURN_WITH_PIN = entry(old_seq=41, old_hash=OLD_HASH,
                      new_seq=47, new_hash=CAND_HASH)
BURN_NO_PIN = entry(old_seq=None, old_hash="",
                    new_seq=47, new_hash=CAND_HASH)


def state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq,
           "phase": "SCAN", "backlog": [], "history": history,
           "deltas": [], "history_pruned": 0, "deltas_pruned": 0,
           "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


def snap(seq, prev=""):
    return sign_state_snapshot(
        state_bytes(seq), signing_key=SNAPSHOT_KEY,
        signer_id=SIGNER, calibration_bytes=CAL,
        prev_snapshot_hash=prev, now=NOW)


def pin_of(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "key_id": s.key_id, "signer_id": s.signer_id}


def project(old):
    if old is None:
        return None
    return {"cycle_seq": old["cycle_seq"],
            "payload_hash": old["payload_hash"]}


def mint_for(old, cand, *, reason, evidence_hash):
    _mint_counter[0] += 1
    candidate = {"cycle_seq": cand.cycle_seq,
                 "payload_hash": cand.payload_hash,
                 "signer_id": cand.signer_id, "key_id": cand.key_id}
    return sign_ceremony_authorisation(
        signing_key=VERIFIER_KEY, signer_id=VERIFIER_SIGNER,
        operator_id=OPERATOR,
        ceremony_id=f"ceremony-cycle22-{_mint_counter[0]}",
        reason=reason, old_pin=project(old), candidate=candidate,
        evidence_hash=evidence_hash,
        evidence_ref="evidence-bundle-1", now=NOW)


class LedgerBackedConsumer:
    """R12 discipline: a REAL consumer over a temp dir. Each
    call opens a fresh CeremonyConsumptionLedger over the same
    on-disk dir, so check_head/append_consumption genuinely
    run against persisted entries. Counts invocations so tests
    can pin exactly-once / zero-on-local-refusal."""

    def __init__(self, journal_dir):
        self.journal_dir = Path(journal_dir)
        self.calls = 0

    def __call__(self, authorisation):
        self.calls += 1
        ledger = CeremonyConsumptionLedger(self.journal_dir)
        try:
            ledger.append_consumption(authorisation,
                                      recorded_at=NOW)
        except LedgerError as exc:
            raise SigningError(str(exc)) from exc
        return None

    def entries(self):
        return CeremonyConsumptionLedger(self.journal_dir).entries()


def do_reanchor(old, cand, *, reason, evidence_hash, consumer,
                history=(), strict_reasons="default", auth=None):
    kwargs = dict(
        signing_key=SNAPSHOT_KEY,
        state_bytes=state_bytes(cand.cycle_seq),
        calibration_bytes=CAL, expected_signer_id=SIGNER,
        operator_id=OPERATOR, reason=reason,
        evidence_hash=evidence_hash,
        authorisation=auth if auth is not None else mint_for(
            old, cand, reason=reason, evidence_hash=evidence_hash),
        authorisation_public_key=VERIFIER_PIN,
        expected_verifier_signer_id=VERIFIER_SIGNER,
        ceremony_history=history, consume_authorisation=consumer,
        now=NOW)
    if strict_reasons == "default":
        if reason in ("chain_gap_recovery", "burned_unadopted") \
                and old is not None:
            kwargs["strict_reasons"] = ("chain_gap",)
    else:
        kwargs["strict_reasons"] = strict_reasons
    return reanchor_pin(old, cand, **kwargs)


# -- vocabulary / drift ---------------------------------------------------

class VocabularyTests(unittest.TestCase):
    def test_reasons_grew_by_one_and_mirrors_match(self):
        self.assertIn("burned_unadopted", REASONS)
        self.assertEqual(REASONS, AUTH_REASONS)
        self.assertEqual(len(REASONS), 5)
        self.assertEqual(pin_ceremony.REASON_BURNED_UNADOPTED,
                         "burned_unadopted")

    def test_no_pin_reasons_unchanged_and_mirrored(self):
        self.assertEqual(
            _NO_PIN_REASONS,
            frozenset({"initial_anchor", "lost_pin",
                       "corrupted_pin"}))
        self.assertEqual(_NO_PIN_REASONS, AUTH_NO_PIN)
        self.assertNotIn("burned_unadopted", _NO_PIN_REASONS)

    def test_either_pin_reasons_mirrored(self):
        self.assertEqual(_EITHER_PIN_REASONS,
                         frozenset({"burned_unadopted"}))
        self.assertEqual(_EITHER_PIN_REASONS, AUTH_EITHER)
        self.assertEqual(_EITHER_PIN_REASONS,
                         pin_ceremony._EITHER_PIN_REASONS)


# -- projection coherence -------------------------------------------------

class ProjectionTests(unittest.TestCase):
    def test_burned_unadopted_with_pin_projects(self):
        payload = ceremony_authorisation_payload(
            **payload_kwargs(reason="burned_unadopted"))
        self.assertEqual(payload["reason"], "burned_unadopted")
        self.assertEqual(payload["old_pin"], OLD_PIN_PROJ)

    def test_burned_unadopted_no_pin_projects(self):
        payload = ceremony_authorisation_payload(**payload_kwargs(
            reason="burned_unadopted", old_pin=None))
        self.assertIsNone(payload["old_pin"])

    def test_burned_unadopted_with_pin_gap_refusal(self):
        for seq in (41, 42):
            with self.assertRaises(SigningError, msg=f"seq {seq}"):
                ceremony_authorisation_payload(**payload_kwargs(
                    reason="burned_unadopted",
                    candidate=dict(CANDIDATE, cycle_seq=seq)))

    def test_burned_unadopted_evidence_refusals(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                reason="burned_unadopted", evidence_hash=CAND_HASH))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                reason="burned_unadopted", evidence_hash=OLD_HASH))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                reason="burned_unadopted", old_pin=None,
                evidence_hash=CAND_HASH))

    def test_existing_reasons_coherence_regression(self):
        # chain_gap still requires a pin; no-pin reasons still
        # refuse a pin; no-pin reasons still project without one.
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(old_pin=None))
        for reason in ("initial_anchor", "lost_pin",
                       "corrupted_pin"):
            with self.assertRaises(SigningError, msg=reason):
                ceremony_authorisation_payload(
                    **payload_kwargs(reason=reason))
            payload = ceremony_authorisation_payload(
                **payload_kwargs(reason=reason, old_pin=None))
            self.assertEqual(payload["reason"], reason)


# -- match_head_burn ------------------------------------------------------

class MatchHeadBurnTests(unittest.TestCase):
    def test_empty_journal_returns_none(self):
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [], candidate=dict(CANDIDATE), old_pin=dict(OLD_PIN_PROJ)))

    def test_match_with_pin_shape(self):
        head = dict(BURN_WITH_PIN)
        self.assertIs(CeremonyConsumptionLedger.match_head_burn(
            [head], candidate=dict(CANDIDATE),
            old_pin=dict(OLD_PIN_PROJ)), head)

    def test_match_no_pin_shape(self):
        head = dict(BURN_NO_PIN)
        self.assertIs(CeremonyConsumptionLedger.match_head_burn(
            [head], candidate=dict(CANDIDATE), old_pin=None), head)

    def test_target_only_match_wrong_old_returns_none(self):
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [dict(BURN_WITH_PIN)], candidate=dict(CANDIDATE),
            old_pin={"cycle_seq": 40, "payload_hash": OLD_HASH}))
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [dict(BURN_WITH_PIN)], candidate=dict(CANDIDATE),
            old_pin=None))
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [dict(BURN_NO_PIN)], candidate=dict(CANDIDATE),
            old_pin=dict(OLD_PIN_PROJ)))

    def test_target_mismatch_returns_none(self):
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [dict(BURN_WITH_PIN)],
            candidate=dict(CANDIDATE, payload_hash="c" * 64),
            old_pin=dict(OLD_PIN_PROJ)))

    def test_matching_entry_at_non_head_returns_none(self):
        later = entry(old_seq=47, old_hash=CAND_HASH,
                      new_seq=52, new_hash="d" * 64)
        self.assertIsNone(CeremonyConsumptionLedger.match_head_burn(
            [dict(BURN_WITH_PIN), later], candidate=dict(CANDIDATE),
            old_pin=dict(OLD_PIN_PROJ)))


# -- check_head -----------------------------------------------------------

class CheckHeadTests(unittest.TestCase):
    def test_recovery_envelope_passes_against_its_burn_head(self):
        env = mint_envelope(reason="burned_unadopted")
        self.assertIsNone(CeremonyConsumptionLedger.check_head(
            [dict(BURN_WITH_PIN)], env))

    def test_recovery_no_pin_passes_against_its_burn_head(self):
        env = mint_envelope(reason="burned_unadopted", old_pin=None)
        self.assertIsNone(CeremonyConsumptionLedger.check_head(
            [dict(BURN_NO_PIN)], env))

    def test_relabelled_chain_gap_raises_already_consumed(self):
        env = mint_envelope(reason="chain_gap_recovery")
        with self.assertRaises(AlreadyConsumedError):
            CeremonyConsumptionLedger.check_head(
                [dict(BURN_WITH_PIN)], env)

    def test_burned_unadopted_different_hash_at_head_seq(self):
        env = mint_envelope(
            reason="burned_unadopted",
            candidate=dict(CANDIDATE, payload_hash="c" * 64))
        with self.assertRaises(HeadRegressionError):
            CeremonyConsumptionLedger.check_head(
                [dict(BURN_WITH_PIN)], env)

    def test_burned_unadopted_non_head_burn_refused(self):
        later = entry(old_seq=47, old_hash=CAND_HASH,
                      new_seq=52, new_hash="d" * 64)
        env = mint_envelope(reason="burned_unadopted")
        with self.assertRaises(HeadRegressionError):
            CeremonyConsumptionLedger.check_head(
                [dict(BURN_WITH_PIN), later], env)

    def test_ordinary_behaviour_regression(self):
        # Ahead candidate with old pin at head passes.
        ahead = mint_envelope(
            candidate=dict(CANDIDATE, cycle_seq=52,
                           payload_hash="d" * 64),
            old_pin={"cycle_seq": 47, "payload_hash": CAND_HASH})
        self.assertIsNone(CeremonyConsumptionLedger.check_head(
            [dict(BURN_WITH_PIN)], ahead))
        # Candidate behind head -> regression.
        behind = mint_envelope(
            candidate=dict(CANDIDATE, cycle_seq=44,
                           payload_hash="c" * 64))
        with self.assertRaises(HeadRegressionError):
            CeremonyConsumptionLedger.check_head(
                [dict(BURN_WITH_PIN)], behind)
        # Old pin behind head with candidate ahead ->
        # SUPERSEDE passes (re-pinned by the cycle-23 fix
        # seat): the burned head movement is abandoned and
        # the fresh primary moves the pin forward to the
        # ahead candidate. This block previously asserted a
        # regression here; that rule deadlocked the adopter
        # once a movement was consumed to its recovery cap
        # with its pair discarded.
        stale_old = mint_envelope(
            candidate=dict(CANDIDATE, cycle_seq=52,
                           payload_hash="d" * 64))
        self.assertIsNone(CeremonyConsumptionLedger.check_head(
            [dict(BURN_WITH_PIN)], stale_old))
        # Old pin AT the head seq with a different hash
        # (fork of the head target) still refuses, even with
        # the candidate ahead — supersede does not rescue it.
        fork_old = mint_envelope(
            candidate=dict(CANDIDATE, cycle_seq=52,
                           payload_hash="d" * 64),
            old_pin={"cycle_seq": 47, "payload_hash": "f" * 64})
        with self.assertRaises(HeadRegressionError):
            CeremonyConsumptionLedger.check_head(
                [dict(BURN_WITH_PIN)], fork_old)
        # Empty journal passes anything.
        self.assertIsNone(CeremonyConsumptionLedger.check_head(
            [], mint_envelope()))


# -- reanchor_pin ---------------------------------------------------------

class ReanchorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.consumer = LedgerBackedConsumer(self.tmp.name)

    def _burn_with_pin(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        new_pin, rec = do_reanchor(
            pin_of(a), cand, reason="chain_gap_recovery",
            evidence_hash=EVIDENCE, consumer=self.consumer)
        return a, cand, new_pin, rec

    def test_with_pin_recovery_happy_path_real_ledger(self):
        a, cand, _burned_pin, _rec = self._burn_with_pin()
        self.assertEqual(self.consumer.calls, 1)
        self.assertEqual(len(self.consumer.entries()), 1)
        # Crash: pin unmoved (still a), record not persisted.
        # Recovery under burned_unadopted against the same real
        # ledger: check_head's scoped exception must lift the
        # candidate==head and old-pin-behind-head refusals.
        new_pin, rec = do_reanchor(
            pin_of(a), cand, reason="burned_unadopted",
            evidence_hash=EVIDENCE2, consumer=self.consumer)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.reason, "burned_unadopted")
        self.assertEqual(self.consumer.calls, 2)
        entries = self.consumer.entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["new_cycle_seq"],
                         cand.cycle_seq)
        self.assertEqual(verify_ceremony_record(
            rec, signing_key=SNAPSHOT_KEY), ())

    def test_no_pin_recovery_happy_path_real_ledger(self):
        cand = snap(3)
        do_reanchor(None, cand, reason="lost_pin",
                    evidence_hash=EVIDENCE, consumer=self.consumer)
        self.assertEqual(self.consumer.calls, 1)
        new_pin, rec = do_reanchor(
            None, cand, reason="burned_unadopted",
            evidence_hash=EVIDENCE2, consumer=self.consumer,
            strict_reasons=None)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(rec.reason, "burned_unadopted")
        self.assertIsNone(rec.old_cycle_seq)
        self.assertEqual(self.consumer.calls, 2)
        self.assertEqual(verify_ceremony_record(
            rec, signing_key=SNAPSHOT_KEY), ())

    def test_forged_strict_tuple_refuses_and_consumer_not_called(self):
        a, cand, _p, _r = self._burn_with_pin()
        before = self.consumer.calls
        # Supplied ("chain_gap",) but recomputation against a
        # pin with a forged signer binding is not chain_gap.
        bad_pin = pin_of(a)
        bad_pin["signer_id"] = "evil-9"
        auth = mint_for(bad_pin, cand, reason="burned_unadopted",
                        evidence_hash=EVIDENCE2)
        with self.assertRaises(SigningError):
            do_reanchor(bad_pin, cand, reason="burned_unadopted",
                        evidence_hash=EVIDENCE2,
                        consumer=self.consumer, auth=auth)
        # A non-chain_gap supplied tuple also refuses locally.
        with self.assertRaises(SigningError):
            do_reanchor(pin_of(a), cand, reason="burned_unadopted",
                        evidence_hash=EVIDENCE2,
                        consumer=self.consumer,
                        strict_reasons=("expired",))
        self.assertEqual(self.consumer.calls, before)

    def test_history_containing_target_refuses_consumer_not_called(self):
        a, cand, _p, rec = self._burn_with_pin()
        before = self.consumer.calls
        with self.assertRaises(SigningError) as cm:
            do_reanchor(pin_of(a), cand, reason="burned_unadopted",
                        evidence_hash=EVIDENCE2,
                        consumer=self.consumer, history=[rec])
        self.assertIn("already a ceremonied target",
                      str(cm.exception))
        self.assertEqual(self.consumer.calls, before)


# -- verify_ceremony_record ----------------------------------------------

class VerifyRecordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.consumer = LedgerBackedConsumer(self.tmp.name)

    def _remac(self, rec):
        from signing.pin_ceremony import _mac, _payload_hash
        ph = _payload_hash(rec.payload())
        return replace(rec, payload_hash=ph, signature=_mac(
            SNAPSHOT_KEY.key, ph, SNAPSHOT_KEY.key_id))

    def test_both_recovery_shapes_verify_clean(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        do_reanchor(pin_of(a), cand, reason="chain_gap_recovery",
                    evidence_hash=EVIDENCE, consumer=self.consumer)
        _pin, rec_with = do_reanchor(
            pin_of(a), cand, reason="burned_unadopted",
            evidence_hash=EVIDENCE2, consumer=self.consumer)
        self.assertEqual(verify_ceremony_record(
            rec_with, signing_key=SNAPSHOT_KEY), ())
        # No-pin shape on a fresh ledger.
        consumer2 = LedgerBackedConsumer(
            tempfile.mkdtemp(dir=self.tmp.name))
        cand2 = snap(3)
        do_reanchor(None, cand2, reason="lost_pin",
                    evidence_hash=EVIDENCE, consumer=consumer2)
        _pin2, rec_without = do_reanchor(
            None, cand2, reason="burned_unadopted",
            evidence_hash=EVIDENCE2, consumer=consumer2,
            strict_reasons=None)
        self.assertEqual(verify_ceremony_record(
            rec_without, signing_key=SNAPSHOT_KEY), ())

    def test_one_step_with_pin_recovery_record_not_a_gap(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        do_reanchor(pin_of(a), cand, reason="chain_gap_recovery",
                    evidence_hash=EVIDENCE, consumer=self.consumer)
        _pin, rec = do_reanchor(
            pin_of(a), cand, reason="burned_unadopted",
            evidence_hash=EVIDENCE2, consumer=self.consumer)
        one_step = self._remac(replace(
            rec, new_cycle_seq=rec.old_cycle_seq + 1))
        self.assertIn("not_a_gap_reanchor", verify_ceremony_record(
            one_step, signing_key=SNAPSHOT_KEY))

    def test_lost_pin_with_pin_record_still_invalid_reason(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _pin, rec = do_reanchor(
            pin_of(a), cand, reason="chain_gap_recovery",
            evidence_hash=EVIDENCE, consumer=self.consumer)
        forged = self._remac(replace(rec, reason="lost_pin"))
        self.assertIn("invalid_reason", verify_ceremony_record(
            forged, signing_key=SNAPSHOT_KEY))


# -- bounded recovery (cycle 23, superseding cycle-22 one-shot) -----------

class OneShotRecoveryTests(unittest.TestCase):
    """Re-pinned to cap-2 semantics — cycle 23 /
    DECISION-CONSUMPTION-HEAD Addendum 3 (pending): recovery
    is BOUNDED at MAX_RECOVERY_DEPTH = 2, not one-shot. A
    recovery consumption is a schema-v2 entry recording its
    lineage (recovery_of = the burn it consumes, depth =
    head depth + 1), so a recovery head CAN ground a further
    recovery up to the cap; match_head_burn is identification
    only. The cycle-22 one-shot pins in this class are
    superseded by the tests below."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = CeremonyConsumptionLedger(self.tmp.name)

    def _burn_then_recover(self):
        burn = mint_envelope()
        self.ledger.append_consumption(burn, recorded_at=NOW)
        recovery = mint_envelope(reason="burned_unadopted")
        self.ledger.append_consumption(
            recovery, recorded_at=NOW,
            recovery_of=burn.authorisation_id)
        return burn, recovery

    def test_match_head_burn_identifies_recovery_head(self):
        # Cycle 23 / DECISION-CONSUMPTION-HEAD Addendum 3
        # (pending): the pair-scan refusal is removed — a
        # recovery head is identified as a burn like any head
        # whose target/old exactly match; the CAP, not
        # identification, bounds the chain.
        entries = [dict(BURN_WITH_PIN), dict(BURN_WITH_PIN)]
        head = CeremonyConsumptionLedger.match_head_burn(
            entries, candidate=dict(CANDIDATE),
            old_pin=dict(OLD_PIN_PROJ))
        self.assertIs(head, entries[-1])

    def test_second_authorise_predicate_passes_below_cap(self):
        # Predicate level (authorise step 5b): after a depth-1
        # recovery lands, a second burned_unadopted authorise
        # for the same target IS proven (match + depth 1 < 2);
        # step (5b) refuses only at depth >= MAX_RECOVERY_DEPTH
        # (pinned at the cap in the schema-v2 suite).
        self._burn_then_recover()
        second = mint_envelope(reason="burned_unadopted")
        self.assertIsNotNone(CeremonyConsumptionLedger.match_head_burn(
            self.ledger.entries(), candidate=second.candidate,
            old_pin=second.old_pin))
        self.assertEqual(
            CeremonyConsumptionLedger.derived_head_depth(
                self.ledger.entries()), 1)

    def test_second_recovery_lands_at_depth_2_third_refused(self):
        # Cycle 23 / DECISION-CONSUMPTION-HEAD Addendum 3
        # (pending): the second recovery, bound to the first
        # recovery's burn, lands at depth 2; a third, bound to
        # the depth-2 burn, hits the cap and refuses
        # AlreadyConsumedError at consume.
        _burn, recovery = self._burn_then_recover()
        second = mint_envelope(reason="burned_unadopted")
        entry = self.ledger.append_consumption(
            second, recorded_at=NOW,
            recovery_of=recovery.authorisation_id)
        self.assertEqual(entry["consumption_kind"], "recovery")
        self.assertEqual(entry["recovery_depth"], 2)
        self.assertEqual(entry["recovery_of"],
                         recovery.authorisation_id)
        third = mint_envelope(reason="burned_unadopted")
        with self.assertRaises(AlreadyConsumedError):
            CeremonyConsumptionLedger.check_head(
                self.ledger.entries(), third,
                recovery_of=second.authorisation_id)
        with self.assertRaises(AlreadyConsumedError):
            self.ledger.append_consumption(
                third, recorded_at=NOW,
                recovery_of=second.authorisation_id)
        self.assertEqual(len(self.ledger.entries()), 3)

    def test_two_recoveries_race_pinned_outcome(self):
        # Race re-pinned — cycle 23 / DECISION-CONSUMPTION-HEAD
        # Addendum 3 (pending): BOTH recoveries are authorised
        # BEFORE either consumes, both bound (via their
        # issuance entries' recovery_of) to the SAME original
        # burn. Exactly one consumption lands: the winner at
        # depth 1; the loser, whose bound burn is no longer
        # head, refuses AlreadyConsumedError. A FRESH recovery
        # bound to the WINNER's burn then lands at depth 2.
        burn = mint_envelope()
        self.ledger.append_consumption(burn, recorded_at=NOW)
        rec_a = mint_envelope(reason="burned_unadopted")
        rec_b = mint_envelope(reason="burned_unadopted")
        self.assertNotEqual(rec_a.authorisation_id,
                            rec_b.authorisation_id)
        entries = self.ledger.entries()
        for rec in (rec_a, rec_b):
            self.assertIsNotNone(
                CeremonyConsumptionLedger.match_head_burn(
                    entries, candidate=rec.candidate,
                    old_pin=rec.old_pin))
            self.assertIsNone(CeremonyConsumptionLedger.check_head(
                entries, rec, recovery_of=burn.authorisation_id))
        winner = self.ledger.append_consumption(
            rec_a, recorded_at=NOW,
            recovery_of=burn.authorisation_id)
        self.assertEqual(winner["recovery_depth"], 1)
        with self.assertRaises(AlreadyConsumedError):
            self.ledger.append_consumption(
                rec_b, recorded_at=NOW,
                recovery_of=burn.authorisation_id)
        fresh = mint_envelope(reason="burned_unadopted")
        landed = self.ledger.append_consumption(
            fresh, recorded_at=NOW,
            recovery_of=rec_a.authorisation_id)
        self.assertEqual(landed["recovery_depth"], 2)
        self.assertEqual(landed["recovery_of"],
                         rec_a.authorisation_id)
        entries = self.ledger.entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(
            {(e["old_cycle_seq"], e["old_payload_hash"],
              e["new_cycle_seq"], e["new_payload_hash"])
             for e in entries},
            {(41, OLD_HASH, 47, CAND_HASH)})


if __name__ == "__main__":
    unittest.main()
