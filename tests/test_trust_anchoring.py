"""Tests for trust.anchoring (Trust Boundary v2, mandate item 7):
external monotonic head anchoring for BOTH ledgers.

Pins: the first-init ceremony refuses a second init AND refuses
a non-empty journal without the explicit ceremony flag (M4: the
previous pin — init on a non-empty journal silently blessing its
current head — was the unsafe behaviour the review flagged;
pinning a rolled-back journal's head would launder the rollback
into a valid anchor); updates are strictly monotonic and refuse
over a rolled-back journal; a rolled-back, truncated or deleted
journal refuses verification with the specific reason; an
established ledger with no anchor refuses as
anchor_missing_established_ledger; kind mismatch and malformed
anchors refuse; force_reanchor is the only overwrite, returns
the old anchor, and persists a hash-chained audit record of
every re-pin (HIGH-6).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust.anchoring import (
    AnchorError,
    force_reanchor,
    initialise_anchor,
    load_anchor,
    load_reanchor_audit,
    reanchor_audit_path,
    update_anchor,
    verify_anchor,
    verify_reanchor_audit,
)
from trust.ledger import GENESIS_HASH, ShipLedger, SigningLedger

T0 = "2026-11-20T00:00:00+00:00"
T1 = "2026-11-20T00:01:00+00:00"
T2 = "2026-11-20T00:02:00+00:00"
T3 = "2026-11-20T00:03:00+00:00"


class AnchorFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.journal_dir = base / "journal"
        self.anchor_path = base / "anchors" / "ship.anchor.json"
        self.ledger = ShipLedger(self.journal_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def burn(self, decision_id="d-1"):
        # ShipLedger burns are single-use per (proposal, manifest)
        # pair, so each decision_id gets its own manifest hash.
        suffix = decision_id.rsplit("-", 1)[-1]
        return self.ledger.burn(
            decision_id=decision_id, proposal_id="p",
            manifest_hash=suffix * 64, payload_hash="b" * 64,
            recorded_at=T0)

    def init(self, **over):
        kw = dict(kind="ship", recorded_at=T0)
        kw.update(over)
        return initialise_anchor(self.ledger, self.anchor_path, **kw)

    def verify(self, **over):
        kw = dict(kind="ship")
        kw.update(over)
        return verify_anchor(self.ledger, self.anchor_path, **kw)


class CeremonyTests(AnchorFixture):
    def test_initialise_empty_journal_pins_genesis(self):
        anchor = self.init()
        self.assertEqual(anchor, {
            "v": "ledger-anchor/1", "kind": "ship",
            "head": GENESIS_HASH, "seq": 0, "anchored_at": T0})
        self.assertEqual(load_anchor(self.anchor_path), anchor)
        # Journal-empty + anchor-at-genesis is the valid pre-init
        # state.
        self.assertEqual(self.verify(), ())

    def test_initialise_nonempty_journal_refused_by_default(self):
        # M4 (review): this test previously PINNED init on a
        # non-empty journal as intended behaviour. That is the
        # bug: called directly on a rolled-back non-empty journal,
        # initialise_anchor blessed the rolled-back head. The
        # default must now refuse; no anchor file is written.
        self.burn()
        with self.assertRaises(AnchorError):
            self.init()
        self.assertFalse(self.anchor_path.exists())
        self.assertEqual(self.verify(),
                         ("anchor_missing_established_ledger",))

    def test_initialise_nonempty_ceremony_flag_pins_current_head(self):
        # The documented first-initialisation ceremony for a
        # pre-existing ledger: the flag is required AND sufficient.
        entry = self.burn()
        anchor = self.init(allow_nonempty_ceremony=True)
        self.assertEqual(anchor["head"], entry["entry_hash"])
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(self.verify(), ())

    def test_ceremony_flag_on_empty_journal_still_works(self):
        anchor = self.init(allow_nonempty_ceremony=True)
        self.assertEqual(anchor["seq"], 0)
        self.assertEqual(self.verify(), ())

    def test_double_init_refused_and_anchor_unchanged(self):
        self.init()
        before = self.anchor_path.read_bytes()
        with self.assertRaises(AnchorError):
            self.init(recorded_at=T1)
        self.assertEqual(self.anchor_path.read_bytes(), before)

    def test_anchor_inside_journal_dir_refused(self):
        with self.assertRaises(AnchorError):
            initialise_anchor(
                self.ledger, self.journal_dir / "anchor.json",
                kind="ship", recorded_at=T0)

    def test_bad_kind_and_bad_time_refused(self):
        with self.assertRaises(AnchorError):
            self.init(kind="other")
        with self.assertRaises(AnchorError):
            self.init(recorded_at="not-a-time")


class UpdateTests(AnchorFixture):
    def test_update_advances_monotonically(self):
        self.init()
        self.burn()
        anchor = update_anchor(self.ledger, self.anchor_path,
                               kind="ship", recorded_at=T1)
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(anchor["head"], self.ledger.head())
        self.assertEqual(self.verify(), ())
        self.burn("d-2")
        anchor = update_anchor(self.ledger, self.anchor_path,
                               kind="ship", recorded_at=T2)
        self.assertEqual(anchor["seq"], 2)
        self.assertEqual(self.verify(), ())

    def test_update_without_appends_refused(self):
        self.init()
        with self.assertRaises(AnchorError):
            update_anchor(self.ledger, self.anchor_path,
                          kind="ship", recorded_at=T1)
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        with self.assertRaises(AnchorError):
            update_anchor(self.ledger, self.anchor_path,
                          kind="ship", recorded_at=T2)

    def test_update_without_anchor_refused(self):
        with self.assertRaises(AnchorError):
            update_anchor(self.ledger, self.anchor_path,
                          kind="ship", recorded_at=T0)

    def test_stale_anchor_still_verifies(self):
        # The journal grew past the anchor: the anchor names an
        # older prefix, which is staleness, not tampering.
        self.init()
        self.burn()
        self.assertEqual(self.verify(), ())

    def test_update_over_foreign_anchor_head_refused(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        # An attacker (or a confused operator) re-pins the anchor
        # file to a head this journal never had.
        anchor = load_anchor(self.anchor_path)
        anchor["head"] = "f" * 64
        self.anchor_path.write_text(json.dumps(anchor))
        self.burn("d-2")
        with self.assertRaises(AnchorError):
            update_anchor(self.ledger, self.anchor_path,
                          kind="ship", recorded_at=T2)


class RollbackTests(AnchorFixture):
    def test_rollback_to_snapshot_refuses_ahead_of_journal(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        snapshot = self.ledger.journal_path.read_bytes()
        self.burn("d-2")
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T2)
        self.assertEqual(self.verify(), ())
        # Roll the journal file back to the one-entry snapshot:
        # the anchor (seq 2) is now ahead of the journal (seq 1).
        self.ledger.journal_path.write_bytes(snapshot)
        fresh = ShipLedger(self.journal_dir)
        self.assertEqual(
            verify_anchor(fresh, self.anchor_path, kind="ship"),
            ("anchor_ahead_of_journal",))
        # And an update must refuse to paper over the rollback.
        with self.assertRaises(AnchorError):
            update_anchor(fresh, self.anchor_path,
                          kind="ship", recorded_at=T3)

    def test_replaced_journal_history_refuses_head_not_in_chain(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        # Replace the journal with a DIFFERENT one-entry history
        # (same length, different head): not truncation, forgery.
        other_dir = Path(self.tmp.name) / "other"
        other = ShipLedger(other_dir)
        other.burn(decision_id="d-x", proposal_id="q",
                   manifest_hash="c" * 64, payload_hash="d" * 64,
                   recorded_at=T0)
        self.ledger.journal_path.write_bytes(
            other.journal_path.read_bytes())
        fresh = ShipLedger(self.journal_dir)
        self.assertEqual(
            verify_anchor(fresh, self.anchor_path, kind="ship"),
            ("anchor_head_not_in_chain",))

    def test_head_seq_pair_mismatch_refuses(self):
        self.init()
        self.burn()
        self.burn("d-2")
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        anchor = load_anchor(self.anchor_path)
        anchor["seq"] = 1  # head is entry 2's, seq claims entry 1
        self.anchor_path.write_text(json.dumps(anchor))
        self.assertEqual(self.verify(), ("anchor_head_not_in_chain",))

    def test_ledger_deletion_refuses(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        self.ledger.journal_path.unlink()
        fresh = ShipLedger(self.journal_dir)  # loads as empty
        self.assertEqual(fresh.entries(), [])
        self.assertEqual(
            verify_anchor(fresh, self.anchor_path, kind="ship"),
            ("anchor_ahead_of_journal",))

    def test_empty_journal_non_genesis_anchor_refuses(self):
        # Anchor claims seq 0 but a non-genesis head, journal
        # empty: the ledger that produced that head is gone.
        self.anchor_path.parent.mkdir(parents=True)
        self.anchor_path.write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship",
            "head": "e" * 64, "seq": 0, "anchored_at": T0}))
        self.assertEqual(self.verify(), ("anchor_head_not_in_chain",))


class MissingAnchorTests(AnchorFixture):
    def test_missing_anchor_empty_journal(self):
        self.assertEqual(self.verify(), ("anchor_missing",))

    def test_missing_anchor_established_ledger(self):
        self.burn()
        self.assertEqual(self.verify(),
                         ("anchor_missing_established_ledger",))

    def test_anchor_deleted_after_establishment(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        self.anchor_path.unlink()
        self.assertEqual(self.verify(),
                         ("anchor_missing_established_ledger",))


class KindAndMalformedTests(AnchorFixture):
    def test_kind_mismatch(self):
        self.init()
        self.assertEqual(self.verify(kind="signing"),
                         ("anchor_kind_mismatch",))
        with self.assertRaises(AnchorError):
            update_anchor(self.ledger, self.anchor_path,
                          kind="signing", recorded_at=T1)

    def test_malformed_anchor_variants(self):
        self.anchor_path.parent.mkdir(parents=True)
        variants = [
            b"this is not json",
            json.dumps({"v": "ledger-anchor/1"}).encode(),
            json.dumps({"v": "ledger-anchor/2", "kind": "ship",
                        "head": GENESIS_HASH, "seq": 0,
                        "anchored_at": T0}).encode(),
            json.dumps({"v": "ledger-anchor/1", "kind": "ship",
                        "head": "zz", "seq": 0,
                        "anchored_at": T0}).encode(),
            json.dumps({"v": "ledger-anchor/1", "kind": "ship",
                        "head": GENESIS_HASH, "seq": -1,
                        "anchored_at": T0}).encode(),
            json.dumps({"v": "ledger-anchor/1", "kind": "ship",
                        "head": GENESIS_HASH, "seq": True,
                        "anchored_at": T0}).encode(),
            json.dumps({"v": "ledger-anchor/1", "kind": "ship",
                        "head": GENESIS_HASH, "seq": 0,
                        "anchored_at": "not-a-time"}).encode(),
            json.dumps({"v": "ledger-anchor/1", "kind": "bogus",
                        "head": GENESIS_HASH, "seq": 0,
                        "anchored_at": T0}).encode(),
        ]
        for raw in variants:
            self.anchor_path.write_bytes(raw)
            self.assertEqual(self.verify(), ("anchor_malformed",),
                             msg=raw[:60])


class ForceReanchorTests(AnchorFixture):
    def test_force_reanchor_returns_old_and_appends_nothing(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        snapshot = self.ledger.journal_path.read_bytes()
        # Legitimate restore: journal rolled back to genesis on
        # purpose (e.g. a fresh deployment re-using the path).
        self.ledger.journal_path.unlink()
        fresh = ShipLedger(self.journal_dir)
        old = force_reanchor(fresh, self.anchor_path, kind="ship",
                             reason="deployment reset, ticket 42",
                             recorded_at=T2)
        self.assertEqual(old["seq"], 1)
        self.assertEqual(old["head"],
                         json.loads(snapshot)["entries"][0]
                         ["entry_hash"])
        self.assertEqual(
            verify_anchor(fresh, self.anchor_path, kind="ship"), ())
        self.assertEqual(fresh.entries(), [])  # nothing appended

    def test_force_reanchor_requires_reason(self):
        self.init()
        for bad in ("", "   ", None):
            with self.assertRaises(AnchorError):
                force_reanchor(self.ledger, self.anchor_path,
                               kind="ship", reason=bad,
                               recorded_at=T1)

    def test_force_reanchor_without_existing_anchor(self):
        old = force_reanchor(self.ledger, self.anchor_path,
                             kind="ship", reason="initial pin via "
                             "the explicit form", recorded_at=T0)
        self.assertIsNone(old)
        self.assertEqual(self.verify(), ())

    # HIGH-6: the reason (and both anchors) must be persisted by
    # force_reanchor itself, in a hash-chained audit file
    # alongside the anchor — previously it was stored NOWHERE.

    def test_force_reanchor_persists_audit_entry(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        old_anchor = load_anchor(self.anchor_path)
        self.ledger.journal_path.unlink()
        fresh = ShipLedger(self.journal_dir)
        force_reanchor(fresh, self.anchor_path, kind="ship",
                       reason="deployment reset, ticket 42",
                       recorded_at=T2)
        entries = load_reanchor_audit(self.anchor_path)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["seq"], 1)
        self.assertEqual(entry["old_anchor"], old_anchor)
        self.assertEqual(entry["new_anchor"],
                         load_anchor(self.anchor_path))
        self.assertEqual(entry["reason"],
                         "deployment reset, ticket 42")
        self.assertEqual(entry["timestamp"], T2)
        self.assertEqual(entry["prev_hash"], GENESIS_HASH)
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ())

    def test_reanchor_audit_chains_across_repins(self):
        self.init()
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="first re-pin", recorded_at=T1)
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="second re-pin", recorded_at=T2)
        entries = load_reanchor_audit(self.anchor_path)
        self.assertEqual([e["seq"] for e in entries], [1, 2])
        self.assertEqual(entries[1]["prev_hash"],
                         entries[0]["entry_hash"])
        self.assertEqual(entries[1]["reason"], "second re-pin")
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ())

    def test_reanchor_audit_missing_is_detectable(self):
        # No re-pin ever happened: the helper reports missing, and
        # plain verify_anchor is unaffected (missing adds nothing
        # unless the caller checks the audit explicitly).
        self.init()
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ("reanchor_audit_missing",))
        self.assertEqual(
            self.verify(check_reanchor_audit=True), ())
        # After a re-pin, deleting the audit file is detectable
        # by exactly the same check.
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="audited re-pin", recorded_at=T1)
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ())
        reanchor_audit_path(self.anchor_path).unlink()
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ("reanchor_audit_missing",))

    def test_reanchor_audit_tamper_detected(self):
        self.init()
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="honest reason", recorded_at=T1)
        audit_path = reanchor_audit_path(self.anchor_path)
        data = json.loads(audit_path.read_text())
        data["entries"][0]["reason"] = "rewritten reason"
        audit_path.write_text(json.dumps(data))
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ("reanchor_audit_chain_broken",))
        self.assertEqual(
            self.verify(check_reanchor_audit=True),
            ("reanchor_audit_chain_broken",))
        # And a further re-pin refuses to paper over the broken
        # chain.
        with self.assertRaises(AnchorError):
            force_reanchor(self.ledger, self.anchor_path,
                           kind="ship", reason="cover-up",
                           recorded_at=T2)

    def test_reanchor_audit_anchor_rewrite_detected(self):
        self.init()
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T1)
        self.ledger.journal_path.unlink()
        fresh = ShipLedger(self.journal_dir)
        force_reanchor(fresh, self.anchor_path, kind="ship",
                       reason="reset to genesis", recorded_at=T2)
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ())
        # Silently rewriting the anchor file afterwards (here:
        # back to the pre-re-pin anchor) breaks consistency with
        # the audit chain's latest entry.
        anchor = load_anchor(self.anchor_path)
        anchor["head"] = "f" * 64
        self.anchor_path.write_text(json.dumps(anchor))
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ("reanchor_audit_anchor_mismatch",))

    def test_anchor_advance_after_repin_still_verifies_audit(self):
        # Normal update_anchor advancement past a re-pin is not
        # an audit mismatch.
        self.init()
        force_reanchor(self.ledger, self.anchor_path, kind="ship",
                       reason="re-pin at genesis", recorded_at=T1)
        self.burn()
        update_anchor(self.ledger, self.anchor_path,
                      kind="ship", recorded_at=T2)
        self.assertEqual(verify_reanchor_audit(self.anchor_path),
                         ())
        self.assertEqual(
            self.verify(check_reanchor_audit=True), ())


class SigningLedgerAnchorTests(unittest.TestCase):
    """The signing ledger anchors under kind='signing' with the
    same semantics (the mechanism is journal-generic)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.journal_dir = base / "signing-home"
        self.anchor_path = base / "anchors" / "signing.anchor.json"
        self.ledger = SigningLedger(self.journal_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _append_eval(self, payload_hash):
        record = {"payload": {"signer_id": "verifier-svc"},
                  "payload_hash": payload_hash}
        return self.ledger.append_eval_attestation(
            record, recorded_at=T0)

    def test_signing_anchor_cycle(self):
        anchor = initialise_anchor(self.ledger, self.anchor_path,
                                   kind="signing", recorded_at=T0)
        self.assertEqual((anchor["seq"], anchor["head"]),
                         (0, GENESIS_HASH))
        self._append_eval("a" * 64)
        anchor = update_anchor(self.ledger, self.anchor_path,
                               kind="signing", recorded_at=T1)
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(
            verify_anchor(self.ledger, self.anchor_path,
                          kind="signing"), ())
        self.assertEqual(
            verify_anchor(self.ledger, self.anchor_path,
                          kind="ship"), ("anchor_kind_mismatch",))
        self._append_eval("b" * 64)
        self.assertEqual(  # stale prefix still verifies
            verify_anchor(self.ledger, self.anchor_path,
                          kind="signing"), ())
        update_anchor(self.ledger, self.anchor_path,
                      kind="signing", recorded_at=T2)
        self.ledger.journal_path.unlink()
        fresh = SigningLedger(self.journal_dir)
        self.assertEqual(
            verify_anchor(fresh, self.anchor_path, kind="signing"),
            ("anchor_ahead_of_journal",))


if __name__ == "__main__":
    unittest.main()
