"""Ship-tx journal anchoring (cycle 17): kind="ship-tx" in
trust.anchoring, and ShipTxJournal.recover(tx_anchor_path=...)
under the same classification as the ship-ledger anchor.

Pins: the anchor ceremony over a ShipTxJournal, kind mismatch
in both directions, rollback by truncation / deletion /
replacement, the outside-the-journal-dir placement rule (the tx
journal shares the ship ledger's directory), recovery parks on
tx chain mismatch, non-destructive operator errors (missing /
malformed / inside-dir / same-path-as-ship-anchor), the
deleted-journal AnchorError surface, back-compat when
tx_anchor_path is omitted, and the park-beats-error combination
when both anchors are supplied.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_trust_shiptx_recovery as _rec

from trust.anchoring import (
    AnchorError,
    initialise_anchor,
    load_anchor,
    update_anchor,
    verify_anchor,
)
from trust.ledger import GENESIS_HASH, ShipLedger
from trust.shipcheck import recover_ship_tx
from trust.shiptx import (
    ANOMALY,
    AUTHORISATION_VERIFIED,
    BURN_PENDING,
    COMMITTED,
    CYCLE_RECORDED,
    POST_RECORD_VERIFIED,
    ShipTxJournal,
)

NOW = _rec.NOW


def _refresh_clock():
    """Re-stamp the fixture clock (cycle 33): NOW is copied from
    test_trust_shiptx_recovery at import time and goes stale
    during a long test run; refresh the source chain and re-read
    its stamp."""
    global NOW
    _rec._refresh_clock()
    NOW = _rec.NOW
StubLoop = _rec.StubLoop
JournalRecoveryFixture = _rec.JournalRecoveryFixture


class TxAnchorFixture(JournalRecoveryFixture):
    def setUp(self):
        super().setUp()
        _refresh_clock()

    def tx_anchor_path(self):
        return Path(self.tmp.name) / "anchors" / "ship-tx.anchor.json"

    def ship_anchor_path(self):
        return Path(self.tmp.name) / "anchors" / "ship.anchor.json"

    def init_tx_anchor(self, **kw):
        kw.setdefault("allow_nonempty_ceremony", True)
        return initialise_anchor(self.journal, self.tx_anchor_path(),
                                 kind="ship-tx", recorded_at=NOW, **kw)

    def post_record_tx(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        return tx_id

    def loop3(self):
        return StubLoop([{"cycle_id": 3, "item_id": "item-1"}])


class CeremonyTests(TxAnchorFixture):
    def test_initialise_empty_tx_journal_pins_genesis(self):
        anchor = initialise_anchor(self.journal, self.tx_anchor_path(),
                                   kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["kind"], "ship-tx")
        self.assertEqual(anchor["head"], GENESIS_HASH)
        self.assertEqual(anchor["seq"], 0)
        self.assertEqual(load_anchor(self.tx_anchor_path()), anchor)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_initialise_nonempty_refused_by_default(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, self.tx_anchor_path(),
                              kind="ship-tx", recorded_at=NOW)
        self.assertFalse(self.tx_anchor_path().exists())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"),
            ("anchor_missing_established_ledger",))

    def test_nonempty_ceremony_flag_pins_current_head(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        anchor = self.init_tx_anchor()
        self.assertEqual(anchor["seq"], len(self.journal.entries()))
        self.assertEqual(anchor["head"], self.journal.head())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_double_init_refused_and_anchor_unchanged(self):
        self.init_tx_anchor()
        before = self.tx_anchor_path().read_bytes()
        with self.assertRaises(AnchorError):
            self.init_tx_anchor()
        self.assertEqual(self.tx_anchor_path().read_bytes(), before)

    def test_update_advances_monotonically(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        anchor = update_anchor(self.journal, self.tx_anchor_path(),
                               kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(anchor["head"], self.journal.head())
        self.journal.transition(
            self.journal.transactions()[0]["tx_id"],
            AUTHORISATION_VERIFIED, NOW)
        anchor = update_anchor(self.journal, self.tx_anchor_path(),
                               kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["seq"], 2)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_update_without_appends_or_anchor_refused(self):
        self.init_tx_anchor()
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        other = Path(self.tmp.name) / "anchors" / "never.anchor.json"
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, other, kind="ship-tx",
                          recorded_at=NOW)

    def test_stale_tx_anchor_still_verifies(self):
        self.init_tx_anchor()
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_missing_anchor_empty_journal(self):
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ("anchor_missing",))

    def test_bad_kind_still_refused(self):
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, self.tx_anchor_path(),
                              kind="other", recorded_at=NOW)


class KindMismatchTests(TxAnchorFixture):
    def test_ship_anchor_used_as_ship_tx_refuses(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship", recorded_at=NOW)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ("anchor_kind_mismatch",))
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)

    def test_ship_tx_anchor_used_as_ship_refuses(self):
        self.init_tx_anchor()
        self.assertEqual(
            verify_anchor(self.ledger, self.tx_anchor_path(),
                          kind="ship"), ("anchor_kind_mismatch",))


class RollbackTests(TxAnchorFixture):
    def test_truncation_refuses_anchor_ahead_of_journal(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        snapshot = (self.home / "ship-tx.json").read_bytes()
        tx_id = self.journal.transactions()[0]["tx_id"]
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.init_tx_anchor()
        (self.home / "ship-tx.json").write_bytes(snapshot)
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_ahead_of_journal",))
        with self.assertRaises(AnchorError):
            update_anchor(fresh, self.tx_anchor_path(), kind="ship-tx",
                          recorded_at=NOW)

    def test_deleted_tx_journal_refuses_ahead_of_journal(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_ahead_of_journal",))

    def test_replaced_tx_journal_refuses_head_not_in_chain(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.init_tx_anchor()
        other_home = Path(self.tmp.name) / "other-home"
        other = ShipTxJournal(other_home)
        other.begin("d-9", "p-1", "b" * 64, NOW, item_id="item-9")
        (self.home / "ship-tx.json").write_bytes(
            (other_home / "ship-tx.json").read_bytes())
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_head_not_in_chain",))


class PlacementTests(TxAnchorFixture):
    def test_tx_anchor_inside_journal_dir_refused(self):
        inside = self.home / "ship-tx.anchor.json"
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, inside, kind="ship-tx",
                              recorded_at=NOW)
        with self.assertRaises(AnchorError):
            verify_anchor(self.journal, inside, kind="ship-tx")
        nested = self.home / "sub" / "ship-tx.anchor.json"
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, nested, kind="ship-tx",
                              recorded_at=NOW)


class RecoveryParkTests(TxAnchorFixture):
    def test_recovery_parks_on_tx_head_not_in_chain(self):
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship-tx: anchor_head_not_in_chain"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        # A second run with the SAME still-mismatched anchor
        # raises: the park landed, but the anchor still
        # disagrees and there is no non-terminal transaction
        # left to park (fix round, rev-r1/r2/r3).
        with self.assertRaises(AnchorError):
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())

    def test_recovery_parks_on_tx_kind_mismatch(self):
        # A DIFFERENT file with the wrong kind is indistinguishable
        # from a substituted anchor: park, not operator error.
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.ship_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_kind_mismatch", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_deleted_tx_journal_raises_instead_of_empty_recovery(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        fresh = ShipTxJournal(self.home)
        with self.assertRaises(AnchorError) as ctx:
            fresh.recover(self.ledger, self.loop3(), recorded_at=NOW,
                          tx_anchor_path=self.tx_anchor_path())
        self.assertIn("anchor_ahead_of_journal", str(ctx.exception))


class RecoveryErrorTests(TxAnchorFixture):
    def test_missing_tx_anchor_is_error_and_retry_succeeds(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("ship-tx: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(outcomes[0]["to_state"], POST_RECORD_VERIFIED)
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_malformed_tx_anchor_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text("this is not an anchor\n")
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("anchor_malformed", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_inside_dir_tx_anchor_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.home / "ship-tx.anchor.json")
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_error:", outcomes[0]["error"])
        self.assertIn("OUTSIDE", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_same_path_for_both_anchors_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.ship_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])


class RecoveryProceedTests(TxAnchorFixture):
    def test_recovery_proceeds_with_valid_tx_anchor(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_recovery_proceeds_with_stale_valid_tx_anchor(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])

    def test_recovery_unchanged_when_tx_anchor_omitted(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertFalse(self.tx_anchor_path().exists())

    def test_recover_ship_tx_wrapper_passes_tx_anchor(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = recover_ship_tx(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)


class CombinedAnchorTests(TxAnchorFixture):
    def _both_valid(self):
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()

    def test_combined_both_valid_proceeds(self):
        self.post_record_tx()
        self._both_valid()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_combined_ship_valid_tx_park_parks(self):
        self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_combined_park_beats_operator_error(self):
        # Ship anchor missing (operator error) + tx anchor chain
        # mismatch (park): park wins, as with the single anchor.
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_combined_ship_valid_tx_operator_error_is_nondestructive(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)


class FixRoundTests(TxAnchorFixture):
    """Review fix round (rev-r1/r2/r3/r5): the same-file
    guard in both directions and under aliasing, the
    all-terminal raise, the discriminating wrapper cases, the
    never-advances claim, force_reanchor/audit for the new
    kind, the ahead-of-journal park, and the combined matrix."""

    def _forge_tx_anchor(self, head="f" * 64, seq=1, kind="ship-tx"):
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": kind,
            "head": head, "seq": seq, "anchored_at": NOW}))

    def test_same_file_tx_anchor_shared_is_error_not_anomaly(self):
        # The shared file IS the tx anchor: the ship-side check
        # must be suppressed too (rev-r2 F1 / rev-r3 F1).
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.tx_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_same_file_symlink_alias_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        alias = Path(self.tmp.name) / "anchors" / "alias.anchor.json"
        alias.symlink_to(self.ship_anchor_path())
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=alias)
        self.assertEqual(len(outcomes), 1)
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)

    def test_all_terminal_journal_with_forged_tx_anchor_raises(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self._forge_tx_anchor()
        with self.assertRaises(AnchorError) as ctx:
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertIn("anchor_head_not_in_chain", str(ctx.exception))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_wrapper_discriminates_bogus_tx_anchor(self):
        # Deleting the shipcheck pass-through must fail this:
        # a valid-anchor wrapper call commits (other tests),
        # a forged one parks.
        tx_id = self.post_record_tx()
        self._forge_tx_anchor()
        outcomes = recover_ship_tx(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_wrapper_deleted_journal_raises(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        with self.assertRaises(AnchorError):
            recover_ship_tx(
                ShipLedger(self.home), self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())

    def test_recovery_never_advances_tx_anchor_then_caller_does(self):
        self.post_record_tx()
        self.init_tx_anchor()
        before = self.tx_anchor_path().read_bytes()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        # Recovery appended a COMMITTED transition but the
        # anchor file is byte-identical: it never advances it.
        self.assertEqual(self.tx_anchor_path().read_bytes(), before)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())
        advanced = update_anchor(self.journal, self.tx_anchor_path(),
                                 kind="ship-tx", recorded_at=NOW)
        self.assertEqual(advanced["head"], self.journal.head())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_force_reanchor_and_audit_for_ship_tx(self):
        from trust.anchoring import (
            force_reanchor,
            verify_anchor as va,
            verify_reanchor_audit,
        )
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.init_tx_anchor()
        old = force_reanchor(self.journal, self.tx_anchor_path(),
                             kind="ship-tx",
                             reason="operator restore drill",
                             recorded_at=NOW)
        self.assertIsNotNone(old)
        self.assertEqual(old["kind"], "ship-tx")
        self.assertEqual(verify_reanchor_audit(self.tx_anchor_path()), ())
        self.assertEqual(va(self.journal, self.tx_anchor_path(),
                            kind="ship-tx",
                            check_reanchor_audit=True), ())

    def test_truncated_journal_with_live_tx_parks_ahead_of_journal(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        snapshot = (self.home / "ship-tx.json").read_bytes()
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        self.init_tx_anchor()
        (self.home / "ship-tx.json").write_bytes(snapshot)
        fresh = ShipTxJournal(self.home)
        outcomes = fresh.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_ahead_of_journal", outcomes[0]["reasons"])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship-tx: anchor_ahead_of_journal"])

    def test_ship_tx_file_passed_as_ship_anchor_parks(self):
        # Reverse direction of the kind-mismatch park: a
        # ship-tx anchor supplied as the SHIP anchor_path.
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_kind_mismatch", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_combined_both_operator_errors_labelled(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("ship: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertIn("ship-tx: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)

    def test_combined_ship_park_tx_error_parks_with_source(self):
        self.post_record_tx()
        self.ship_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.ship_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=Path(self.tmp.name) / "anchors"
            / "missing.anchor.json")
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertNotIn("error", outcomes[0])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship: anchor_head_not_in_chain"])


class JournalIntegrityErrorTests(TxAnchorFixture):
    """Cycle 18: the journal-level raises are a DISTINCT type
    (JournalIntegrityError, an AnchorError subclass carrying
    bare reasons + labelled sources), so a journal-level
    integrity failure cannot be conflated with an anchor-load
    error; hardlink aliases of the same-file guard are pinned."""

    def test_deleted_journal_raises_distinct_type_with_reasons(self):
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        fresh = ShipTxJournal(self.home)
        with self.assertRaises(JournalIntegrityError) as ctx:
            fresh.recover(self.ledger, self.loop3(), recorded_at=NOW,
                          tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertIs(type(exc), JournalIntegrityError)
        self.assertIsInstance(exc, AnchorError)
        self.assertEqual(exc.reasons, ("anchor_ahead_of_journal",))
        self.assertEqual(exc.anchor_sources,
                         ("ship-tx: anchor_ahead_of_journal",))
        self.assertEqual(exc.anchor_source, "ship-tx")
        self.assertIn("anchor_ahead_of_journal", str(exc))

    def test_all_terminal_forged_anchor_raises_distinct_type(self):
        from trust.anchoring import JournalIntegrityError
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        with self.assertRaises(JournalIntegrityError) as ctx:
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(ctx.exception.reasons,
                         ("anchor_head_not_in_chain",))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_second_run_after_park_raises_distinct_type(self):
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        with self.assertRaises(JournalIntegrityError) as ctx:
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), JournalIntegrityError)

    def test_wrapper_propagates_distinct_type_unwrapped(self):
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        with self.assertRaises(JournalIntegrityError) as ctx:
            recover_ship_tx(
                ShipLedger(self.home), self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), JournalIntegrityError)

    def test_constructor_contract(self):
        from trust.anchoring import JournalIntegrityError
        exc = JournalIntegrityError(
            "m: anchor_head_not_in_chain",
            reasons=["anchor_head_not_in_chain",
                     "anchor_head_not_in_chain"],
            anchor_sources=["ship-tx: anchor_head_not_in_chain"])
        self.assertEqual(exc.reasons, ("anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_source, "ship-tx")
        combined = JournalIntegrityError(
            "m", reasons=["anchor_head_not_in_chain"],
            anchor_sources=["ship: anchor_head_not_in_chain",
                            "ship-tx: anchor_head_not_in_chain"])
        self.assertEqual(combined.anchor_source, "combined")
        with self.assertRaises(ValueError):
            JournalIntegrityError("m", reasons=[],
                                  anchor_sources=[])

    def test_anchor_primitives_stay_plain_anchor_error(self):
        from trust.anchoring import JournalIntegrityError
        self.init_tx_anchor()
        with self.assertRaises(AnchorError) as ctx:
            self.init_tx_anchor()
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertNotIsInstance(ctx.exception, JournalIntegrityError)

    def test_ship_anchor_only_park_with_nothing_to_park_no_raise(self):
        # The deliberate asymmetry stands (cycle 17): the ship
        # anchor pins a DIFFERENT file, so its park reasons with
        # no non-terminal transaction do not raise.
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.ship_anchor_path().parent.mkdir(parents=True,
                                             exist_ok=True)
        self.ship_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path())
        self.assertEqual(outcomes, [])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_same_file_hardlink_alias_of_ship_anchor(self):
        import os
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        alias = Path(self.tmp.name) / "anchors" / "hardlink.anchor.json"
        os.link(self.ship_anchor_path(), alias)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=alias)
        self.assertEqual(len(outcomes), 1)
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id),
                         POST_RECORD_VERIFIED)

    def test_same_file_hardlink_alias_of_tx_anchor(self):
        import os
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        alias = Path(self.tmp.name) / "anchors" / "hardlink2.anchor.json"
        os.link(self.tx_anchor_path(), alias)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=alias,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id),
                         POST_RECORD_VERIFIED)

    def test_byte_copy_distinct_inode_still_parks(self):
        # A byte-identical COPY is a different file (distinct
        # inode): file identity, not content, is the guard, so
        # a copied ship anchor passed as the tx anchor parks on
        # kind mismatch like any substituted anchor.
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        copy_path = Path(self.tmp.name) / "anchors" / "copy.anchor.json"
        copy_path.write_bytes(self.ship_anchor_path().read_bytes())
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=copy_path)
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_kind_mismatch", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_post_settlement_park_reason_raises_distinct_type(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        calls = {"n": 0}

        def fake_verify(journal, path, *, kind, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return ()
            return ("anchor_head_not_in_chain",)

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake_verify):
            with self.assertRaises(JournalIntegrityError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertIs(type(exc), JournalIntegrityError)
        self.assertEqual(exc.reasons, ("anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_source, "ship-tx")
        # Settlements stand and ride on the exception.
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual([o["to_state"] for o in exc.outcomes],
                         [COMMITTED])

    def test_constructor_validation_fix_round(self):
        from trust.anchoring import JournalIntegrityError
        # An operator reason can never mint the distinct type.
        with self.assertRaises(ValueError):
            JournalIntegrityError(
                "m", reasons=["anchor_malformed"],
                anchor_sources=["ship-tx: anchor_malformed"])
        # Empty sources fabricate provenance: refused.
        with self.assertRaises(ValueError):
            JournalIntegrityError(
                "m", reasons=["anchor_ahead_of_journal"],
                anchor_sources=[])
        # A reason with no matching labelled source: refused.
        with self.assertRaises(ValueError):
            JournalIntegrityError(
                "m", reasons=["anchor_ahead_of_journal",
                              "anchor_head_not_in_chain"],
                anchor_sources=["ship-tx: anchor_ahead_of_journal"])
        # Bare strings are not sequences of reasons.
        with self.assertRaises(ValueError):
            JournalIntegrityError(
                "m", reasons="anchor_ahead_of_journal",
                anchor_sources=["ship-tx: anchor_ahead_of_journal"])
        # Duplicate sources dedupe; pickle/deepcopy round-trip.
        import copy
        import pickle
        exc = JournalIntegrityError(
            "m", reasons=["anchor_head_not_in_chain"],
            anchor_sources=["ship-tx: anchor_head_not_in_chain",
                            "ship-tx: anchor_head_not_in_chain"],
            outcomes=[{"to_state": "COMMITTED"}])
        self.assertEqual(exc.anchor_sources,
                         ("ship-tx: anchor_head_not_in_chain",))
        for clone in (pickle.loads(pickle.dumps(exc)),
                      copy.deepcopy(exc)):
            self.assertIs(type(clone), JournalIntegrityError)
            self.assertEqual(clone.reasons, exc.reasons)
            self.assertEqual(clone.anchor_sources, exc.anchor_sources)
            self.assertEqual(clone.outcomes, exc.outcomes)

    def test_pre_settlement_combined_anchors_carry_both_sources(self):
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        for path, kind in ((self.tx_anchor_path(), "ship-tx"),
                           (self.ship_anchor_path(), "ship")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "v": "ledger-anchor/1", "kind": kind,
                "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        with self.assertRaises(JournalIntegrityError) as ctx:
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                anchor_path=self.ship_anchor_path(),
                tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertIs(type(exc), JournalIntegrityError)
        self.assertEqual(exc.anchor_source, "combined")
        self.assertEqual(
            set(exc.anchor_sources),
            {"ship: anchor_head_not_in_chain",
             "ship-tx: anchor_head_not_in_chain"})
        self.assertIn("ship anchor also failed", str(exc))

    def test_post_settlement_combined_sources(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()
        seen = {}

        def fake_verify(journal, path, *, kind, **kw):
            seen[kind] = seen.get(kind, 0) + 1
            if seen[kind] == 1:
                return ()
            return ("anchor_head_not_in_chain",)

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake_verify):
            with self.assertRaises(JournalIntegrityError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    anchor_path=self.ship_anchor_path(),
                    tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertIs(type(exc), JournalIntegrityError)
        self.assertEqual(exc.anchor_source, "combined")
        self.assertEqual(exc.anchor_sources,
                         ("ship: anchor_head_not_in_chain",
                          "ship-tx: anchor_head_not_in_chain"))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_post_settlement_mixed_park_and_anchor_error(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()
        seen = {}

        def fake_verify(journal, path, *, kind, **kw):
            seen[kind] = seen.get(kind, 0) + 1
            if seen[kind] == 1:
                return ()
            if kind == "ship":
                raise AnchorError("anchor_malformed")
            return ("anchor_head_not_in_chain",)

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake_verify):
            with self.assertRaises(JournalIntegrityError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    anchor_path=self.ship_anchor_path(),
                    tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertIs(type(exc), JournalIntegrityError)
        self.assertEqual(exc.reasons, ("anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_sources,
                         ("ship-tx: anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_errors,
                         ("ship: anchor_error:anchor_malformed",))
        self.assertIn("anchor_error:anchor_malformed", str(exc))

    def test_post_settlement_no_new_reason_does_not_raise(self):
        from unittest import mock
        self.post_record_tx()
        self.init_tx_anchor()

        def fake_verify(journal, path, *, kind, **kw):
            return ("anchor_head_not_in_chain",)

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake_verify):
            outcomes = self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])

    def test_post_settlement_anchor_error_only_stays_plain(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        calls = {"n": 0}

        def fake_verify(journal, path, *, kind, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return ()
            raise AnchorError("anchor_malformed")

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake_verify):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertNotIsInstance(ctx.exception, JournalIntegrityError)
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual(
            [o["to_state"] for o in ctx.exception.outcomes],
            [COMMITTED])


    # -- cycle 32: post-settlement RETURNED non-park reasons -----

    def _fake_seq(self, seq_by_kind):
        seen = {}

        def fake_verify(journal, path, *, kind, **kw):
            seen[kind] = seen.get(kind, 0) + 1
            seq = seq_by_kind[kind]
            result = seq[min(seen[kind], len(seq)) - 1]
            if isinstance(result, Exception):
                raise result
            return result

        return fake_verify

    def test_post_returned_malformed_only_raises_plain(self):
        from unittest import mock
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        fake = self._fake_seq({"ship-tx": [(), ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        from trust.anchoring import JournalIntegrityError
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertNotIsInstance(ctx.exception, JournalIntegrityError)
        self.assertIn("ship-tx: anchor_malformed", str(ctx.exception))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual(
            [o["to_state"] for o in ctx.exception.outcomes],
            [COMMITTED])

    def test_post_returned_missing_established_raises_plain(self):
        from unittest import mock
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        fake = self._fake_seq(
            {"ship-tx": [(), ("anchor_missing_established_ledger",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertIn("anchor_missing_established_ledger",
                      str(ctx.exception))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_post_returned_mixed_park_and_malformed_is_jie(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()
        fake = self._fake_seq({
            "ship": [(), ("anchor_malformed",)],
            "ship-tx": [(), ("anchor_head_not_in_chain",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(JournalIntegrityError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    anchor_path=self.ship_anchor_path(),
                    tx_anchor_path=self.tx_anchor_path())
        exc = ctx.exception
        self.assertEqual(exc.reasons, ("anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_sources,
                         ("ship-tx: anchor_head_not_in_chain",))
        self.assertEqual(exc.anchor_errors,
                         ("ship: anchor_malformed",))
        self.assertEqual([o["to_state"] for o in exc.outcomes],
                         [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_post_returned_same_reason_pre_and_post_no_raise(self):
        from unittest import mock
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        fake = self._fake_seq(
            {"ship-tx": [("anchor_malformed",), ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            outcomes = self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("anchor_malformed", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id),
                         POST_RECORD_VERIFIED)

    def test_post_returned_reason_on_other_anchor_is_new(self):
        from unittest import mock
        self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()
        fake = self._fake_seq({
            "ship": [("anchor_malformed",), ("anchor_malformed",)],
            "ship-tx": [(), ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    anchor_path=self.ship_anchor_path(),
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertIn("ship-tx: anchor_malformed", str(ctx.exception))

    def test_post_returned_unknown_reason_is_operator_error(self):
        from unittest import mock
        self.post_record_tx()
        self.init_tx_anchor()
        fake = self._fake_seq(
            {"ship-tx": [(), ("some_future_reason",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertIn("ship-tx: some_future_reason", str(ctx.exception))

    def test_post_returned_error_with_no_settlements_raises(self):
        from unittest import mock
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        self.journal.transition(tx_id, COMMITTED, NOW)
        fake = self._fake_seq({"ship-tx": [(), ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertEqual(ctx.exception.outcomes, ())

    def test_pre_park_plus_post_returned_error_stays_plain(self):
        from unittest import mock
        from trust.anchoring import JournalIntegrityError
        self.post_record_tx()
        self.init_tx_anchor()
        fake = self._fake_seq({
            "ship-tx": [("anchor_head_not_in_chain",),
                        ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertNotIsInstance(ctx.exception, JournalIntegrityError)
        self.assertEqual(
            [o["to_state"] for o in ctx.exception.outcomes],
            [ANOMALY])

    def test_post_returned_and_exception_errors_both_surface(self):
        from unittest import mock
        self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()
        fake = self._fake_seq({
            "ship": [(), AnchorError("boom")],
            "ship-tx": [(), ("anchor_malformed",)]})
        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=fake):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    anchor_path=self.ship_anchor_path(),
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertIn("ship: anchor_error:boom", str(ctx.exception))
        self.assertIn("ship-tx: anchor_malformed", str(ctx.exception))

    def test_post_real_anchor_corrupted_mid_recovery_raises(self):
        from unittest import mock
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        real_verify = verify_anchor
        calls = {"n": 0}

        def corrupting_verify(journal, path, *, kind, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                Path(path).write_bytes(b"not json at all")
            return real_verify(journal, path, kind=kind, **kw)

        with mock.patch("trust.anchoring.verify_anchor",
                        side_effect=corrupting_verify):
            with self.assertRaises(AnchorError) as ctx:
                self.journal.recover(
                    self.ledger, self.loop3(), recorded_at=NOW,
                    tx_anchor_path=self.tx_anchor_path())
        self.assertIs(type(ctx.exception), AnchorError)
        self.assertIn("anchor_malformed", str(ctx.exception))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)


if __name__ == "__main__":
    unittest.main()
