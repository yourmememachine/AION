"""Schema-v2 consumption journal tests (cycle 23, WS3 / R3;
DECISION-CONSUMPTION-HEAD Addendum 3, pending).

Covers: backward compatibility with v1 journals written by
the OLD (cycle 21-22) exact key set — entries constructed
literally, hashes computed by hand; v1->v2 mixed journals;
positional monotonicity (v1 after v2 is corrupt); v2 value
coherence at load; lineage recorded end-to-end through the
REAL verifier modes; the depth cap (MAX_RECOVERY_DEPTH = 2:
primary + depth-1 + depth-2 land, depth-3 refuses as
AlreadyConsumedError at consume and ceremony_recovery_unproven
at authorise); the two-recoveries race against the SAME burn
(exactly one lands; a fresh recovery bound to the winner's
burn lands at depth+1); and exhaustion-is-not-a-deadlock
(the next sequence takes a primary chain_gap_recovery).

Fixture discipline for the verifier e2e follows
test_trust_ceremony_consumption.py: temp verifier home,
generated keys, real evidence artifacts, live clock.
"""

import hashlib
import json
import multiprocessing
import sys
import tempfile
import unittest
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
    load_ceremony_seed,
    sign_ceremony_authorisation,
)
from signing.gate_decision import _canonical, _sha256
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.ledger import (
    MAX_RECOVERY_DEPTH,
    AlreadyConsumedError,
    CeremonyAuthorisationLedger,
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
    CorruptLedgerError,
    HeadRegressionError,
    SupersedeRequiredError,
)

NOW = "2026-11-20T12:00:00+00:00"
GENESIS = "0" * 64

# -- literal journal construction (OLD key sets) --------------------------

V1_CONSUMPTION_FIELDS = dict(
    authorisation_id="auth-v1-1", ceremony_id="ceremony-v1-1",
    operator_id="operator-1", old_cycle_seq=41,
    old_payload_hash="a" * 64, new_cycle_seq=47,
    new_payload_hash="b" * 64, evidence_hash="e" * 64,
    consumed_at=NOW)
V1_AUTHORISATION_FIELDS = dict(
    authorisation_id="auth-v1-1", payload_hash="f" * 64,
    ceremony_id="ceremony-v1-1", evidence_hash="e" * 64,
    operator_id="operator-1", issued_at=NOW)


def write_journal(journal_dir, filename, field_dicts):
    """Write a journal file literally: seq/prev/entry_hash
    computed by hand over exactly the given fields, so a v1
    file here is byte-shaped as the OLD code wrote it."""
    journal_dir = Path(journal_dir)
    journal_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    prev = GENESIS
    for i, fields in enumerate(field_dicts, start=1):
        entry = {"seq": i, "kind": fields.pop("kind"),
                 "recorded_at": NOW, "prev_hash": prev}
        entry.update(fields)
        entry["entry_hash"] = _sha256(_canonical(
            {k: v for k, v in entry.items() if k != "entry_hash"}))
        prev = entry["entry_hash"]
        entries.append(entry)
    (journal_dir / filename).write_text(
        json.dumps({"entries": entries}, sort_keys=True),
        encoding="utf-8")
    return entries


def v1_consumption(**over):
    fields = dict(V1_CONSUMPTION_FIELDS, kind="consume")
    fields.update(over)
    return fields


def v2_consumption(**over):
    fields = v1_consumption(
        consumption_kind="primary", recovery_of="",
        recovery_depth=0)
    fields.update(over)
    return fields


# -- direct-minted envelopes (ledger-level tests) -------------------------

VERIFIER_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle23 schema v2 test seed").digest())
_counter = [0]


def mint(reason="chain_gap_recovery", **over):
    _counter[0] += 1
    kwargs = dict(
        signing_key=VERIFIER_KEY, signer_id="verifier-svc",
        operator_id="operator-1",
        ceremony_id=f"ceremony-v2-{_counter[0]}",
        reason=reason,
        old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
        candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                   "signer_id": "snapshot-svc",
                   "key_id": "key-0123456789abcdef"},
        evidence_hash="e" * 64, evidence_ref="evidence-bundle-1",
        now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def _race_append_worker(journal_dir, envelope_dict, recovery_of,
                        barrier, queue):
    """Child-process racer for the true concurrent race test:
    barrier-synchronised, then one append_consumption of the
    given envelope against the shared journal dir, reporting
    "ok" or the exception class name on the queue."""
    try:
        barrier.wait(timeout=60)
        envelope = ceremony_authorisation_envelope_from_dict(
            envelope_dict)
        ledger = CeremonyConsumptionLedger(journal_dir)
        ledger.append_consumption(
            envelope, recorded_at=NOW, recovery_of=recovery_of)
        queue.put("ok")
    except Exception as exc:  # report, never swallow silently
        queue.put(type(exc).__name__)


class V1BackwardCompatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "home"

    def test_v1_consumption_journal_written_by_old_key_set_loads(self):
        write_journal(self.dir, "ceremony-consumptions.json",
                      [v1_consumption()])
        ledger = CeremonyConsumptionLedger(self.dir)
        entries = ledger.entries()
        self.assertEqual(len(entries), 1)
        self.assertNotIn("consumption_kind", entries[0])
        self.assertEqual(ledger.head_target(), (47, "b" * 64))
        # A v1 head's depth derives by the pair-scan: the
        # pair occurs once, so depth 0.
        self.assertEqual(
            CeremonyConsumptionLedger.derived_head_depth(entries), 0)

    def test_v1_pair_twice_derives_depth_1(self):
        write_journal(self.dir, "ceremony-consumptions.json", [
            v1_consumption(),
            v1_consumption(authorisation_id="auth-v1-2",
                           ceremony_id="ceremony-v1-2")])
        entries = CeremonyConsumptionLedger(self.dir).entries()
        self.assertEqual(
            CeremonyConsumptionLedger.derived_head_depth(entries), 1)

    def test_v1_authorisation_journal_loads(self):
        fields = dict(V1_AUTHORISATION_FIELDS, kind="authorise")
        write_journal(self.dir, "ceremony-authorisations.json",
                      [fields])
        entries = CeremonyAuthorisationLedger(self.dir).entries()
        self.assertEqual(len(entries), 1)
        self.assertNotIn("recovery_of", entries[0])

    def test_v1_then_v2_mixed_consumption_journal_loads(self):
        write_journal(self.dir, "ceremony-consumptions.json",
                      [v1_consumption()])
        ledger = CeremonyConsumptionLedger(self.dir)
        # New appends are always v2, extending the v1 prefix.
        env = mint(reason="chain_gap_recovery",
                   old_pin={"cycle_seq": 47, "payload_hash": "b" * 64},
                   candidate={"cycle_seq": 52,
                              "payload_hash": "c" * 64,
                              "signer_id": "snapshot-svc",
                              "key_id": "key-0123456789abcdef"})
        entry = ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(entry["consumption_kind"], "primary")
        self.assertEqual(entry["recovery_depth"], 0)
        self.assertEqual(entry["recovery_of"], "")
        fresh = CeremonyConsumptionLedger(self.dir).entries()
        self.assertEqual(len(fresh), 2)
        self.assertNotIn("consumption_kind", fresh[0])
        self.assertIn("consumption_kind", fresh[1])

    def test_v1_after_v2_consumption_is_corrupt(self):
        write_journal(self.dir, "ceremony-consumptions.json", [
            v2_consumption(),
            v1_consumption(authorisation_id="auth-v1-2",
                           ceremony_id="ceremony-v1-2")])
        with self.assertRaises(CorruptLedgerError):
            CeremonyConsumptionLedger(self.dir)

    def test_v1_after_v2_authorisation_is_corrupt(self):
        v2 = dict(V1_AUTHORISATION_FIELDS, kind="authorise",
                  recovery_of="")
        v1 = dict(V1_AUTHORISATION_FIELDS, kind="authorise",
                  authorisation_id="auth-v1-2",
                  ceremony_id="ceremony-v1-2",
                  evidence_hash="d" * 64)
        write_journal(self.dir, "ceremony-authorisations.json",
                      [v2, v1])
        with self.assertRaises(CorruptLedgerError):
            CeremonyAuthorisationLedger(self.dir)


class V2CoherenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "home"

    def _assert_corrupt(self, **v2over):
        write_journal(self.dir, "ceremony-consumptions.json",
                      [v2_consumption(**v2over)])
        with self.assertRaises(CorruptLedgerError):
            CeremonyConsumptionLedger(self.dir)

    def test_primary_with_depth_is_corrupt(self):
        self._assert_corrupt(recovery_depth=1)

    def test_primary_with_recovery_of_is_corrupt(self):
        self._assert_corrupt(recovery_of="auth-x")

    def test_recovery_without_recovery_of_is_corrupt(self):
        self._assert_corrupt(consumption_kind="recovery",
                             recovery_depth=1, recovery_of="")

    def test_recovery_depth_zero_is_corrupt(self):
        self._assert_corrupt(consumption_kind="recovery",
                             recovery_depth=0, recovery_of="auth-x")

    def test_recovery_depth_above_cap_is_corrupt(self):
        self._assert_corrupt(
            consumption_kind="recovery",
            recovery_depth=MAX_RECOVERY_DEPTH + 1,
            recovery_of="auth-x")

    def test_unknown_kind_is_corrupt(self):
        self._assert_corrupt(consumption_kind="tertiary")

    def test_coherent_recovery_entry_loads(self):
        # Re-pinned by the cycle-23 fix round (r1-F1): a lone
        # recovery entry is NOT coherent — cross-entry lineage
        # requires an earlier same-pair entry at depth - 1
        # named by recovery_of. The coherent shape is a full
        # primary -> recovery -> recovery chain.
        write_journal(self.dir, "ceremony-consumptions.json", [
            v2_consumption(authorisation_id="auth-p"),
            v2_consumption(
                authorisation_id="auth-r1", ceremony_id="ceremony-r1",
                consumption_kind="recovery", recovery_depth=1,
                recovery_of="auth-p"),
            v2_consumption(
                authorisation_id="auth-r2", ceremony_id="ceremony-r2",
                consumption_kind="recovery", recovery_depth=2,
                recovery_of="auth-r1")])
        entries = CeremonyConsumptionLedger(self.dir).entries()
        self.assertEqual([e["recovery_depth"] for e in entries],
                         [0, 1, 2])


class CrossEntryLineageTests(unittest.TestCase):
    """Fix round (r1-F1 / r1-F3 / r1-F4): cross-entry lineage
    validation at load for the consumption journal, the v1
    pair cap, and the authorisation journal's v2 recovery_of
    format."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "home"

    def _load_consumption(self, field_dicts):
        write_journal(self.dir, "ceremony-consumptions.json",
                      field_dicts)
        return CeremonyConsumptionLedger(self.dir)

    def test_ghost_recovery_of_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1",
                    ceremony_id="ceremony-r1",
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-ghost")])

    def test_wrong_pair_recovery_is_corrupt(self):
        # The recovery names a real earlier authorisation but
        # for a DIFFERENT old->new pair.
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1",
                    ceremony_id="ceremony-r1",
                    old_cycle_seq=47, old_payload_hash="b" * 64,
                    new_cycle_seq=52, new_payload_hash="c" * 64,
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-p")])

    def test_depth_jump_0_to_2_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r2",
                    ceremony_id="ceremony-r2",
                    consumption_kind="recovery", recovery_depth=2,
                    recovery_of="auth-p")])

    def test_valid_primary_recovery_recovery_chain_loads(self):
        ledger = self._load_consumption([
            v2_consumption(authorisation_id="auth-p"),
            v2_consumption(
                authorisation_id="auth-r1", ceremony_id="ceremony-r1",
                consumption_kind="recovery", recovery_depth=1,
                recovery_of="auth-p"),
            v2_consumption(
                authorisation_id="auth-r2", ceremony_id="ceremony-r2",
                consumption_kind="recovery", recovery_depth=2,
                recovery_of="auth-r1")])
        self.assertEqual(len(ledger.entries()), 3)

    def test_v1_pair_three_times_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v1_consumption(),
                v1_consumption(authorisation_id="auth-v1-2",
                               ceremony_id="ceremony-v1-2"),
                v1_consumption(authorisation_id="auth-v1-3",
                               ceremony_id="ceremony-v1-3")])

    def test_authorisation_v2_recovery_of_format(self):
        def auth_entry(rec_of):
            return dict(V1_AUTHORISATION_FIELDS, kind="authorise",
                        recovery_of=rec_of)
        # A non-id string is corrupt at load.
        write_journal(self.dir, "ceremony-authorisations.json",
                      [auth_entry("not-an-authorisation-id !!!")])
        with self.assertRaises(CorruptLedgerError):
            CeremonyAuthorisationLedger(self.dir)
        # Uppercase hex is not a lowercase authorisation id.
        write_journal(self.dir, "ceremony-authorisations.json",
                      [auth_entry("A" * 64)])
        with self.assertRaises(CorruptLedgerError):
            CeremonyAuthorisationLedger(self.dir)
        # "" and a genuine 64-char lowercase hex id load.
        for ok in ("", "a" * 64):
            write_journal(self.dir, "ceremony-authorisations.json",
                          [auth_entry(ok)])
            entries = CeremonyAuthorisationLedger(self.dir).entries()
            self.assertEqual(entries[0]["recovery_of"], ok)


class LedgerLevelCapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = CeremonyConsumptionLedger(self.tmp.name)

    def test_depth3_consume_refused_already_consumed(self):
        burn = mint()
        self.ledger.append_consumption(burn, recorded_at=NOW)
        rec1 = mint(reason="burned_unadopted")
        self.ledger.append_consumption(
            rec1, recorded_at=NOW, recovery_of=burn.authorisation_id)
        rec2 = mint(reason="burned_unadopted")
        landed = self.ledger.append_consumption(
            rec2, recorded_at=NOW, recovery_of=rec1.authorisation_id)
        self.assertEqual(landed["recovery_depth"], 2)
        rec3 = mint(reason="burned_unadopted")
        with self.assertRaises(AlreadyConsumedError):
            self.ledger.append_consumption(
                rec3, recorded_at=NOW,
                recovery_of=rec2.authorisation_id)
        self.assertEqual(len(self.ledger.entries()), 3)


# -- verifier e2e ----------------------------------------------------------

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
ARTIFACT = b"ceremony evidence bundle: schema v2 case file\n"
EVIDENCE = hashlib.sha256(ARTIFACT).hexdigest()
EVIDENCE_REF = "evidence-bundle-v2"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
OLD = {"cycle_seq": 41, "payload_hash": "a" * 64}
CAND = {"cycle_seq": 47, "payload_hash": "b" * 64,
        "signer_id": "snapshot-svc",
        "key_id": "key-0123456789abcdef"}


class VerifierV2Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.assertEqual(
            load_ceremony_seed(self.seed_path).key_id,
            self.seed_key.key_id)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        (self.evidence_dir / EVIDENCE_REF).write_bytes(ARTIFACT)
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATORS,
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        self._cid = 0
        self._eid = 0

    def tearDown(self):
        self.tmp.cleanup()

    def authorise(self, reason, old_pin, candidate):
        self._cid += 1
        self._eid += 1
        data = f"evidence bundle v2 number {self._eid}\n".encode()
        ref = f"evidence-v2-{self._eid}"
        (self.evidence_dir / ref).write_bytes(data)
        envelope = self.client.ceremony_authorise(
            operator_id=OPERATOR,
            ceremony_id=f"ceremony-v2-e2e-{self._cid}",
            reason=reason, old_pin=old_pin, candidate=candidate,
            evidence_hash=hashlib.sha256(data).hexdigest(),
            evidence_ref=ref)
        return ceremony_authorisation_envelope_from_dict(envelope)

    def consume(self, envelope):
        return self.client.ceremony_consumer()(envelope)

    def consumption_entries(self):
        path = self.home / "ledger" / "ceremony-consumptions.json"
        if not path.exists():
            return []
        return CeremonyConsumptionLedger(self.home / "ledger").entries()

    def issuance_entry(self, authorisation_id):
        return CeremonyAuthorisationLedger(
            self.home / "ledger").find_by_authorisation_id(
                authorisation_id)

    def burn_primary(self):
        auth = self.authorise("chain_gap_recovery", OLD, CAND)
        self.consume(auth)
        return auth

    def recover_and_consume(self):
        rec = self.authorise("burned_unadopted", OLD, CAND)
        self.consume(rec)
        return rec


class VerifierV2LineageTests(VerifierV2Fixture):
    def test_primary_and_recovery_lineage_end_to_end(self):
        primary = self.burn_primary()
        issued_primary = self.issuance_entry(primary.authorisation_id)
        self.assertEqual(issued_primary["recovery_of"], "")
        entries = self.consumption_entries()
        self.assertEqual(entries[-1]["consumption_kind"], "primary")
        self.assertEqual(entries[-1]["recovery_of"], "")
        self.assertEqual(entries[-1]["recovery_depth"], 0)
        recovery = self.recover_and_consume()
        issued_rec = self.issuance_entry(recovery.authorisation_id)
        # Step (5b) bound the recovery issuance to the burn.
        self.assertEqual(issued_rec["recovery_of"],
                         primary.authorisation_id)
        entries = self.consumption_entries()
        self.assertEqual(entries[-1]["consumption_kind"], "recovery")
        self.assertEqual(entries[-1]["recovery_of"],
                         primary.authorisation_id)
        self.assertEqual(entries[-1]["recovery_depth"], 1)

    def test_cap_depth2_lands_depth3_authorise_refused(self):
        self.burn_primary()
        self.recover_and_consume()   # depth 1
        self.recover_and_consume()   # depth 2
        entries = self.consumption_entries()
        self.assertEqual([e["recovery_depth"] for e in entries],
                         [0, 1, 2])
        with self.assertRaises(VerifierConfigError) as cm:
            self.authorise("burned_unadopted", OLD, CAND)
        self.assertIn("ceremony_recovery_unproven", str(cm.exception))
        self.assertEqual(len(self.consumption_entries()), 3)

    def test_race_same_burn_exactly_one_then_fresh_recovery(self):
        primary = self.burn_primary()
        rec_a = self.authorise("burned_unadopted", OLD, CAND)
        rec_b = self.authorise("burned_unadopted", OLD, CAND)
        # Both issuances bound to the SAME (primary) burn.
        for rec in (rec_a, rec_b):
            self.assertEqual(
                self.issuance_entry(rec.authorisation_id)["recovery_of"],
                primary.authorisation_id)
        self.consume(rec_a)
        with self.assertRaises(Exception) as cm:
            self.consume(rec_b)
        self.assertIn("already_consumed", str(cm.exception))
        self.assertEqual(len(self.consumption_entries()), 2)
        # A fresh recovery bound to the WINNER's burn lands
        # at depth + 1.
        fresh = self.recover_and_consume()
        self.assertEqual(
            self.issuance_entry(fresh.authorisation_id)["recovery_of"],
            rec_a.authorisation_id)
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[-1]["recovery_depth"], 2)
        self.assertEqual(entries[-1]["recovery_of"],
                         rec_a.authorisation_id)

    def test_exhaustion_is_not_a_deadlock_next_sequence_primary(self):
        self.burn_primary()
        self.recover_and_consume()
        self.recover_and_consume()
        with self.assertRaises(VerifierConfigError):
            self.authorise("burned_unadopted", OLD, CAND)
        # The next snapshot sequence takes a PRIMARY
        # chain_gap_recovery off the consumed head and lands.
        nxt = {"cycle_seq": 52, "payload_hash": "c" * 64,
               "signer_id": "snapshot-svc",
               "key_id": "key-0123456789abcdef"}
        auth = self.authorise(
            "chain_gap_recovery",
            {"cycle_seq": 47, "payload_hash": "b" * 64}, nxt)
        self.consume(auth)
        entries = self.consumption_entries()
        self.assertEqual(entries[-1]["consumption_kind"], "primary")
        self.assertEqual(entries[-1]["recovery_depth"], 0)
        self.assertEqual(entries[-1]["new_cycle_seq"], 52)


class SupersedeRuleTests(unittest.TestCase):
    """Fix-seat tests (cycle 23): the check_head SUPERSEDE
    rule. Once a movement is consumed to its recovery cap
    with its adoption pair discarded, the pin sits behind
    the consumed head forever; a fresh primary whose
    candidate is STRICTLY AHEAD of the head may pass a
    behind-head old pin (the burned head movement is
    superseded — abandoned, never adopted). Every other
    head rule is unchanged."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = CeremonyConsumptionLedger(self.tmp.name)
        # Head: primary consumption to seq 47 / "b"*64 from
        # old pin 41 / "a"*64.
        self.ledger.append_consumption(mint(), recorded_at=NOW)
        self.assertEqual(self.ledger.head_target(), (47, "b" * 64))

    def _cand(self, seq, payload_hash):
        return {"cycle_seq": seq, "payload_hash": payload_hash,
                "signer_id": "snapshot-svc",
                "key_id": "key-0123456789abcdef"}

    def _decision_for(self, env):
        """Journal a supersession decision for ``env`` against
        the current head (cycle 24, Option A) and return the
        decision entry dict."""
        head = self.ledger.entries()[-1]
        return CeremonySupersessionLedger(
            self.tmp.name).append_decision(
                abandoned_entry=head, signed=env, recorded_at=NOW)

    def test_supersede_lands_primary_candidate_ahead_old_behind(self):
        # Re-pinned cycle 24 / Option A: the bare supersede no
        # longer lands — without a journaled decision the same
        # call raises SupersedeRequiredError; with a decision
        # bound to this envelope and the current head, threaded
        # as supersede_decision=, it lands as before.
        env = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate=self._cand(52, "c" * 64))
        with self.assertRaises(SupersedeRequiredError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)
        decision = self._decision_for(env)
        entry = self.ledger.append_consumption(
            env, recorded_at=NOW, supersede_decision=decision)
        self.assertEqual(entry["consumption_kind"], "primary")
        self.assertEqual(entry["recovery_depth"], 0)
        self.assertEqual(entry["recovery_of"], "")
        self.assertEqual(self.ledger.head_target(), (52, "c" * 64))

    def test_supersede_does_not_rescue_fork_at_head(self):
        from trust.ledger import HeadRegressionError
        # Cycle 24: unchanged — an old pin AT the head seq is
        # not the supersede shape, so the decision check is
        # never reached and no decision is involved.
        # Old pin AT the head seq with a different hash is a
        # fork of the head target — refused even with the
        # candidate ahead.
        env = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 47, "payload_hash": "f" * 64},
            candidate=self._cand(52, "c" * 64))
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_fabricated_old_hash_journal_known_seq_refuses(self):
        # Fix round (r1-F2b): the head entry records old pin
        # 41 / "a"*64. A supersede envelope claiming old pin
        # seq 41 with a FABRICATED hash refuses — the seq is
        # journal-known, so its hash is bound.
        # Cycle 24 order pin: the hash binding runs BEFORE the
        # decision check, so with NO decision journaled this
        # still raises HeadRegressionError — never
        # SupersedeRequiredError (the assertRaises below is
        # exact on that point: SupersedeRequiredError is not a
        # HeadRegressionError subclass).
        env = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "f" * 64},
            candidate=self._cand(52, "c" * 64))
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)

    def test_supersede_fabricated_old_hash_known_as_new_seq_refuses(self):
        # Cycle 24: outcome unchanged, and (no decision is
        # journaled here) the refusal is HeadRegressionError,
        # not SupersedeRequiredError — hash binding precedes
        # the decision check.
        # The journal-known binding also covers a seq recorded
        # as an entry's new_cycle_seq: journal 35->41, 41->47;
        # old pin seq 41 must carry hash "a"*64 (the recorded
        # new_payload_hash), not a fabrication.
        ledger = CeremonyConsumptionLedger(
            Path(self.tmp.name) / "second")
        first = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 35, "payload_hash": "9" * 64},
            candidate=self._cand(41, "a" * 64))
        ledger.append_consumption(first, recorded_at=NOW)
        ledger.append_consumption(mint(), recorded_at=NOW)
        self.assertEqual(ledger.head_target(), (47, "b" * 64))
        env = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "f" * 64},
            candidate=self._cand(52, "c" * 64))
        with self.assertRaises(HeadRegressionError):
            ledger.append_consumption(env, recorded_at=NOW)
        self.assertEqual(len(ledger.entries()), 2)

    def test_burned_unadopted_candidate_ahead_refuses_no_primary(self):
        # Fix round (r1-F2a): a burned_unadopted envelope that
        # does not validly match the head burn NEVER rides
        # supersede and is never reclassified as a primary.
        env = mint(
            reason="burned_unadopted",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate=self._cand(52, "c" * 64))
        kind = CeremonyConsumptionLedger._derive_lineage(
            self.ledger.entries(), env, None)[0]
        self.assertNotEqual(kind, "primary")
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(env, recorded_at=NOW)
        entries = self.ledger.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["consumption_kind"], "primary")

    def test_candidate_at_or_behind_head_old_behind_still_refuses(self):
        from trust.ledger import HeadRegressionError
        # Candidate AT the head (same target), old pin behind:
        # the movement is already consumed, not superseded.
        env_at = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate=self._cand(47, "b" * 64))
        with self.assertRaises(AlreadyConsumedError):
            self.ledger.append_consumption(env_at, recorded_at=NOW)
        # Candidate BEHIND the head, old pin behind: head
        # regression, unchanged.
        env_behind = mint(
            reason="chain_gap_recovery",
            old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
            candidate=self._cand(44, "d" * 64))
        with self.assertRaises(HeadRegressionError):
            self.ledger.append_consumption(
                env_behind, recorded_at=NOW)
        self.assertEqual(len(self.ledger.entries()), 1)


class ConcurrentRecoveryRaceTests(unittest.TestCase):
    """Fix round (r2-F2): a TRUE concurrent race — two
    PROCESSES (multiprocessing fork context, the process
    pattern of tests/test_trust_multiprocess_race.py adapted
    to direct ledger appends), barrier-synchronised, each
    appending a consumption of a DISTINCT envelope bound to
    the SAME burn (recovery_of = the burn's authorisation_id)
    against the same journal dir. Exactly one lands; the
    other raises AlreadyConsumedError; the journal contains
    exactly one recovery entry for that burn."""

    def test_two_processes_same_burn_exactly_one_recovery_lands(self):
        ctx = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CeremonyConsumptionLedger(tmp)
            burn = mint()
            ledger.append_consumption(burn, recorded_at=NOW)
            rec_a = mint(reason="burned_unadopted")
            rec_b = mint(reason="burned_unadopted")
            barrier = ctx.Barrier(2)
            queue = ctx.Queue()
            procs = [
                ctx.Process(
                    target=_race_append_worker,
                    args=(tmp,
                          ceremony_authorisation_envelope_to_dict(rec),
                          burn.authorisation_id, barrier, queue))
                for rec in (rec_a, rec_b)]
            for proc in procs:
                proc.start()
            outcomes = sorted(queue.get(timeout=120)
                              for _ in procs)
            for proc in procs:
                proc.join(timeout=120)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=10)
                    self.fail("race child did not finish")
            self.assertEqual(
                outcomes, ["AlreadyConsumedError", "ok"], outcomes)
            entries = CeremonyConsumptionLedger(tmp).entries()
            self.assertEqual(len(entries), 2)
            recoveries = [e for e in entries
                          if e.get("consumption_kind") == "recovery"]
            self.assertEqual(len(recoveries), 1)
            self.assertEqual(recoveries[0]["recovery_of"],
                             burn.authorisation_id)
            self.assertEqual(recoveries[0]["recovery_depth"], 1)


if __name__ == "__main__":
    unittest.main()


class ImmediatePredecessorGroundingTests(unittest.TestCase):
    """Re-review strengthening (rev-r1, cycle 23): a recovery
    grounds ONLY on its immediate predecessor, and an
    authorisation_id occurs at most once in the journal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "home"

    def _load_consumption(self, field_dicts):
        write_journal(self.dir, "ceremony-consumptions.json",
                      field_dicts)
        return CeremonyConsumptionLedger(self.dir)

    def test_branched_lineage_is_corrupt(self):
        # [P d0, R1 d1, R1b d1]: R1b's predecessor is R1 (depth
        # 1), not the depth-0 primary it names — a branched
        # lineage the append path can never write.
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1",
                    ceremony_id="ceremony-r1",
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1b",
                    ceremony_id="ceremony-r1b",
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-p")])

    def test_non_adjacent_grounding_is_corrupt(self):
        # [P, R1, X (different pair, primary), R2 bound to R1]:
        # R2's immediate predecessor is X, not its named burn.
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1",
                    ceremony_id="ceremony-r1",
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-p"),
                v2_consumption(
                    authorisation_id="auth-x",
                    ceremony_id="ceremony-x",
                    old_cycle_seq=52, old_payload_hash="c" * 64,
                    new_cycle_seq=57, new_payload_hash="d" * 64),
                v2_consumption(
                    authorisation_id="auth-r2",
                    ceremony_id="ceremony-r2",
                    consumption_kind="recovery", recovery_depth=2,
                    recovery_of="auth-r1")])

    def test_duplicate_authorisation_id_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-p",
                    ceremony_id="ceremony-again",
                    old_cycle_seq=52, old_payload_hash="c" * 64,
                    new_cycle_seq=57, new_payload_hash="d" * 64)])

    def test_adjacent_chain_still_loads(self):
        ledger = self._load_consumption([
            v2_consumption(authorisation_id="auth-p"),
            v2_consumption(
                authorisation_id="auth-r1",
                ceremony_id="ceremony-r1",
                consumption_kind="recovery", recovery_depth=1,
                recovery_of="auth-p"),
            v2_consumption(
                authorisation_id="auth-r2",
                ceremony_id="ceremony-r2",
                consumption_kind="recovery", recovery_depth=2,
                recovery_of="auth-r1")])
        self.assertEqual(len(ledger.entries()), 3)


class PrimaryReRootTests(unittest.TestCase):
    """Re-review (rev-r1, cycle 23): a v2 primary whose pair
    already occurred in an earlier entry is a second root for
    the movement — corrupt at load."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "home"

    def _load_consumption(self, field_dicts):
        write_journal(self.dir, "ceremony-consumptions.json",
                      field_dicts)
        return CeremonyConsumptionLedger(self.dir)

    def test_second_primary_of_same_pair_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-p2",
                    ceremony_id="ceremony-p2")])

    def test_primary_reroot_after_recovery_chain_is_corrupt(self):
        with self.assertRaises(CorruptLedgerError):
            self._load_consumption([
                v2_consumption(authorisation_id="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r1",
                    ceremony_id="ceremony-r1",
                    consumption_kind="recovery", recovery_depth=1,
                    recovery_of="auth-p"),
                v2_consumption(
                    authorisation_id="auth-r2",
                    ceremony_id="ceremony-r2",
                    consumption_kind="recovery", recovery_depth=2,
                    recovery_of="auth-r1"),
                v2_consumption(
                    authorisation_id="auth-p2",
                    ceremony_id="ceremony-p2")])

    def test_primary_of_new_pair_after_chain_loads(self):
        ledger = self._load_consumption([
            v2_consumption(authorisation_id="auth-p"),
            v2_consumption(
                authorisation_id="auth-r1",
                ceremony_id="ceremony-r1",
                consumption_kind="recovery", recovery_depth=1,
                recovery_of="auth-p"),
            v2_consumption(
                authorisation_id="auth-q",
                ceremony_id="ceremony-q",
                old_cycle_seq=52, old_payload_hash="c" * 64,
                new_cycle_seq=57, new_payload_hash="d" * 64)])
        self.assertEqual(len(ledger.entries()), 3)
