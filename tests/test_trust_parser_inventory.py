"""Parser-differential agreement tests (Trust Boundary v3.1,
mandate item 4; docs/PARSER-INVENTORY.md).

The strict parsing contract: every security-relevant consumer of
a signed / integrity-checked artefact refuses, AT PARSE TIME,
duplicate keys and non-finite numbers (NaN, Infinity, -Infinity,
and float tokens that overflow to infinity such as 1e999). A
permissive parser that silently takes the LAST value of a
duplicated key can disagree with a strict consumer about what
the same document says — that differential is what these tests
kill.

For each fixed consumer the discriminating case is a FULLY VALID
document with a bogus FIRST copy of a duplicated key and the real
value second: a last-wins parser accepts it (and validates the
real value), a strict parser refuses it outright. Non-finite
cases splice the token into a field of an otherwise valid
document and assert the module's own corruption error.

Fixture idioms mirror the corresponding suites:
tests/test_trust_anchoring.py (ledger burns + anchor ceremony),
tests/test_trust_budgets.py (check_and_record), tests/
test_signing_state_snapshot.py (state_bytes), tests/
test_trust_shiptx.py (ShipTxJournal.begin), tests/
test_memory_store.py (MemoryStore on a temp dir).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop, CorruptStateError
from memory.store import CorruptMemoryError, MemoryStore, \
    verify_migration_audit
from oversight.approval import ApprovalManager
from oversight.approval import CorruptJournalError as \
    ApprovalCorruptJournalError
from selfmod.canary import CanaryManager
from selfmod.canary import CorruptJournalError as \
    CanaryCorruptJournalError
from signing import SigningError
from signing.attestation import attestation_envelope_from_json
from signing.gate_decision import envelope_from_json
from signing.state_snapshot import parse_state_bytes, \
    snapshot_envelope_from_json
from trust import protocol
from trust.anchoring import AnchorError, force_reanchor, \
    initialise_anchor, load_anchor, load_reanchor_audit
from trust.budgets import BudgetError, BudgetStore
from trust.ledger import CorruptLedgerError, ShipLedger, \
    SigningLedger
from trust.manifest import ManifestError, manifest_from_json
from trust.release import release_from_json
from trust.shiptx import ShipTxJournal

T0 = "2026-11-20T00:00:00+00:00"
T1 = "2026-11-20T00:01:00+00:00"
NON_FINITE = ("NaN", "Infinity", "-Infinity", "1e999", "-1e999")


def splice_first(text, anchor, bogus_pair):
    """Insert bogus_pair (a raw '"key": value,' fragment) just
    before the first occurrence of anchor, so the document carries
    the bogus value FIRST and the real value second."""
    assert anchor in text, anchor
    return text.replace(anchor, bogus_pair + anchor, 1)


class LedgerParserTests(unittest.TestCase):
    """trust/ledger.py HashChainJournal._load — fixed this cycle.
    One loader serves ShipLedger, SigningLedger and (via
    trust/shiptx.py) ShipTxJournal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "ledger"
        ledger = ShipLedger(self.dir)
        ledger.burn(decision_id="d-1", proposal_id="p",
                    manifest_hash="a" * 64, payload_hash="b" * 64,
                    recorded_at=T0)
        self.path = self.dir / "ship-ledger.json"
        self.raw = self.path.read_text(encoding="utf-8")

    def reload(self):
        return ShipLedger(self.dir)

    def test_valid_journal_loads(self):
        self.assertEqual(len(self.reload().entries()), 1)

    def test_duplicate_entry_key_bogus_first_refused(self):
        dup = splice_first(self.raw, '"kind":"burn"',
                           '"kind":"bogus",')
        self.path.write_text(dup, encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            self.reload()

    def test_duplicate_top_level_key_bogus_first_refused(self):
        dup = self.raw.replace('{"entries":[', '{"entries":[],'
                               '"entries":[', 1)
        assert dup != self.raw
        self.path.write_text(dup, encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            self.reload()

    def test_non_finite_tokens_refused(self):
        for token in NON_FINITE:
            bad = self.raw.replace(f'"{T0}"', token, 1)
            assert bad != self.raw
            self.path.write_text(bad, encoding="utf-8")
            with self.assertRaises(CorruptLedgerError, msg=token):
                self.reload()

    def test_signing_ledger_empty_journal_duplicate_refused(self):
        other = Path(self.tmp.name) / "signing"
        SigningLedger(other)  # no file yet: loads as empty
        (other / "signing-ledger.json").write_text(
            '{"entries": [], "entries": []}', encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            SigningLedger(other)

    def test_ship_tx_journal_duplicate_refused(self):
        tx_dir = Path(self.tmp.name) / "tx"
        journal = ShipTxJournal(tx_dir)
        journal.begin("d-1", "p", "a" * 64, T0, item_id="item-1")
        path = tx_dir / "ship-tx.json"
        raw = path.read_text(encoding="utf-8")
        dup = raw.replace('{"entries":[', '{"entries":[],'
                          '"entries":[', 1)
        assert dup != raw
        path.write_text(dup, encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            ShipTxJournal(tx_dir)


class BudgetParserTests(unittest.TestCase):
    """trust/budgets.py BudgetStore._load — fixed this cycle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budgets.json"
        store = BudgetStore(self.path)
        store.check_and_record("alice", "prop-a", ["x", "y"])
        self.raw = self.path.read_text(encoding="utf-8")

    def assert_corrupt(self, text):
        self.path.write_text(text, encoding="utf-8")
        with self.assertRaises(BudgetError) as ctx:
            BudgetStore(self.path)
        self.assertEqual(ctx.exception.reason, "budget_store_corrupt")

    def test_valid_store_loads(self):
        BudgetStore(self.path)

    def test_duplicate_chain_hash_bogus_first_refused(self):
        import re
        head = re.search(r'"chain_hash":"([0-9a-f]{64})"',
                         self.raw).group(1)
        dup = self.raw.replace(
            f'"chain_hash":"{head}"',
            f'"chain_hash":"{"0" * 64}","chain_hash":"{head}"', 1)
        self.assert_corrupt(dup)

    def test_non_finite_tokens_refused(self):
        self.assert_corrupt(
            self.raw.replace('"schema_version":2',
                             '"schema_version":NaN', 1))
        self.assert_corrupt(
            self.raw.replace('"count":1', '"count":Infinity', 1))
        self.assert_corrupt(
            self.raw.replace('"count":1', '"count":1e999', 1))


class AnchorParserTests(unittest.TestCase):
    """trust/anchoring.py _read_anchor / _read_audit — fixed
    this cycle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.journal_dir = base / "journal"
        self.anchor_path = base / "anchors" / "ship.anchor.json"
        self.ledger = ShipLedger(self.journal_dir)
        initialise_anchor(self.ledger, self.anchor_path,
                          kind="ship", recorded_at=T0)
        self.raw = self.anchor_path.read_text(encoding="utf-8")

    def test_valid_anchor_loads(self):
        self.assertEqual(load_anchor(self.anchor_path)["seq"], 0)

    def test_duplicate_head_bogus_first_refused(self):
        import re
        head = re.search(r'"head":"([0-9a-f]{64})"',
                         self.raw).group(1)
        dup = self.raw.replace(
            f'"head":"{head}"',
            f'"head":"{"f" * 64}","head":"{head}"', 1)
        self.anchor_path.write_text(dup, encoding="utf-8")
        with self.assertRaises(AnchorError):
            load_anchor(self.anchor_path)

    def test_non_finite_seq_refused(self):
        for token in NON_FINITE:
            bad = self.raw.replace('"seq":0', f'"seq":{token}', 1)
            assert bad != self.raw
            self.anchor_path.write_text(bad, encoding="utf-8")
            with self.assertRaises(AnchorError, msg=token):
                load_anchor(self.anchor_path)

    def test_reanchor_audit_duplicate_refused(self):
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="parser inventory fixture",
                       recorded_at=T1)
        self.assertEqual(len(load_reanchor_audit(self.anchor_path)),
                         1)
        audit_path = self.anchor_path.parent / \
            "ship.anchor.reanchor-audit.json"
        raw = audit_path.read_text(encoding="utf-8")
        dup = raw.replace('{"entries":[', '{"entries":[],'
                          '"entries":[', 1)
        if dup == raw:  # different serialisation: duplicate a key
            dup = raw.replace('"v":"reanchor-audit/1"',
                              '"v":"bogus","v":"reanchor-audit/1"',
                              1)
        assert dup != raw
        audit_path.write_text(dup, encoding="utf-8")
        with self.assertRaises(AnchorError):
            load_reanchor_audit(self.anchor_path)


class LoopSnapshotAgreementTests(unittest.TestCase):
    """The SAME artefact (the loop's state.json bytes) is parsed
    by two security-relevant consumers: core/loop.py CoreLoop
    (state integrity; shipcheck joins ship transactions against
    its history) and signing/state_snapshot.py parse_state_bytes
    (the facts a state snapshot signs). They must agree — both
    accept the valid document and read the same facts, both
    refuse every ambiguous one. CoreLoop's duplicate-key refusal
    was added this cycle; its non-finite hooks already existed."""

    @staticmethod
    def state_doc(**over):
        doc = {"schema_version": 1, "cycle_seq": 0, "phase": "SCAN",
               "backlog": [], "history": [], "deltas": [],
               "history_pruned": 0, "deltas_pruned": 0,
               "current_item_id": None}
        doc.update(over)
        import json
        return json.dumps(doc, sort_keys=True)

    def load_loop(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state_dir = Path(tmp.name)
        (state_dir / "state.json").write_text(text,
                                              encoding="utf-8")
        return CoreLoop(state_dir)

    def test_valid_state_agrees(self):
        text = self.state_doc()
        loop = self.load_loop(text)
        facts = parse_state_bytes(text.encode("utf-8"))
        self.assertEqual(loop.state["cycle_seq"], facts.cycle_seq)

    def test_duplicate_key_differing_values_both_refuse(self):
        # Bogus 999 first, real 0 second: a last-wins parser loads
        # cycle_seq 0 and validates cleanly.
        text = self.state_doc().replace(
            '"cycle_seq": 0', '"cycle_seq": 999, "cycle_seq": 0', 1)
        with self.assertRaises(CorruptStateError):
            self.load_loop(text)
        with self.assertRaises(SigningError):
            parse_state_bytes(text.encode("utf-8"))

    def test_non_finite_both_refuse(self):
        for token in NON_FINITE:
            text = self.state_doc().replace(
                '"cycle_seq": 0', f'"cycle_seq": {token}', 1)
            with self.assertRaises(CorruptStateError, msg=token):
                self.load_loop(text)
            with self.assertRaises(SigningError, msg=token):
                parse_state_bytes(text.encode("utf-8"))


class StrictConsumerCorpusTests(unittest.TestCase):
    """Parse-stage refusal pins for consumers that were already
    strict before this cycle (regression coverage for the
    inventory's 'strict' rows). The documents are minimal: the
    refusal must happen in the PARSER, before any schema
    validation could save or condemn the document."""

    def test_protocol_strict_loads(self):
        for raw in (b'{"a": 1, "a": 2}', b'{"a": NaN}',
                    b'{"a": Infinity}', b'{"a": 1e999}'):
            with self.assertRaises(protocol.ProtocolError,
                                   msg=raw):
                protocol.strict_loads(raw, cap=1 << 20, what="doc")

    def test_signing_envelope_parsers(self):
        for loader in (envelope_from_json,
                       attestation_envelope_from_json,
                       snapshot_envelope_from_json):
            for text in ('{"a": 1, "a": 2}', '{"a": NaN}',
                         '{"a": 1e999}'):
                with self.assertRaises(SigningError,
                                       msg=(loader.__name__, text)):
                    loader(text)

    def test_manifest_and_release_parsers(self):
        for loader in (manifest_from_json, release_from_json):
            for text in ('{"a": 1, "a": 2}', '{"a": NaN}',
                         '{"a": 1e999}'):
                with self.assertRaises(ManifestError,
                                       msg=(loader.__name__, text)):
                    loader(text)

    def test_memory_store_load(self):
        for text in ('{"schema_version": 1, "schema_version": 1}',
                     '{"schema_version": NaN}'):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            store_dir = Path(tmp.name)
            (store_dir / "memory.json").write_text(
                text, encoding="utf-8")
            with self.assertRaises(CorruptMemoryError, msg=text):
                MemoryStore(store_dir)

    def test_memory_migration_audit_load(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_dir = Path(tmp.name)
        (store_dir / "migration-audit.json").write_text(
            '{"entries": [], "entries": []}', encoding="utf-8")
        with self.assertRaises(CorruptMemoryError):
            verify_migration_audit(store_dir)

    def test_oversight_journal_load(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        journal_dir = Path(tmp.name) / "journal"
        journal_dir.mkdir(parents=True)
        (journal_dir / "journal.json").write_text(
            '{"seq": 0, "seq": 0}', encoding="utf-8")
        with self.assertRaises(ApprovalCorruptJournalError):
            ApprovalManager(journal_dir)

    def test_canary_journal_load(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        root = base / "tree"
        root.mkdir()
        journal_dir = base / "journal"
        journal_dir.mkdir()
        (journal_dir / "journal.json").write_text(
            '{"seq": NaN}', encoding="utf-8")
        with self.assertRaises(CanaryCorruptJournalError):
            CanaryManager(root, journal_dir)


if __name__ == "__main__":
    unittest.main()
